"""Users, audit, settings, backups, and the branch agent intake."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from secrets import token_urlsafe

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import BACKUP_DIR
from app.database import sqlite_file
from app.deps import current_user, get_db, require_admin, require_agent, require_writer
from app.models import AuditLog, Branch, Device, Employee, Punch, Setting, User
from app.schemas import AgentIngest, SettingsIn, UserIn, UserUpdate
from app.security import encrypt_secret, hash_password
from app.serialize import audit_out, device_out, sync_out, user_out
from app.services.attendance import get_settings, rebuild_employees, set_setting
from app.services.audit import audit
from app.services.sync import ingest
from app.zk.base import NormalizedLog, NormalizedUser, clean_stamp

router = APIRouter(prefix="/api/v1", tags=["system"])

# Rules that change how punches become sessions. Changing one recalculates every employee.
PAIRING_SETTINGS = ("punch_debounce_minutes", "max_session_hours", "retap_window_minutes")


def _differs(old, new) -> bool:
    try:
        return float(old) != float(new)
    except (TypeError, ValueError):
        return old != new


@router.get("/users")
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = db.scalars(select(User).order_by(User.role, User.username)).all()
    return {"items": [user_out(row) for row in rows]}


@router.post("/users")
def create_user(body: UserIn, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    if db.scalar(select(User).where(User.username == body.username.strip())):
        raise HTTPException(status_code=400, detail="That username already exists")
    row = User(username=body.username.strip(), password_hash=hash_password(body.password), role=body.role, is_active=True)
    db.add(row)
    db.flush()
    audit(db, actor, "create", "user", str(row.id), f"{row.username} {row.role}")
    db.commit()
    return user_out(row)


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    row = db.get(User, user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    if body.role and body.role != "admin" and row.role == "admin":
        admins = db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True))) or 0
        if admins <= 1:
            raise HTTPException(status_code=400, detail="Keep at least one administrator")
    if body.role:
        row.role = body.role
    if body.is_active is not None:
        if not body.is_active and row.role == "admin":
            admins = db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True))) or 0
            if admins <= 1:
                raise HTTPException(status_code=400, detail="Keep at least one administrator")
        row.is_active = body.is_active
    if body.password:
        row.password_hash = hash_password(body.password)
        if row.username == actor.username:
            set_setting(db, "using_default_admin_password", "0")
    audit(db, actor, "update", "user", str(row.id), row.username)
    db.commit()
    return user_out(row)


@router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    row = db.get(User, user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    if row.id == actor.id:
        raise HTTPException(status_code=400, detail="You cannot remove your own account")
    if row.role == "admin":
        admins = db.scalar(select(func.count()).select_from(User).where(User.role == "admin")) or 0
        if admins <= 1:
            raise HTTPException(status_code=400, detail="Keep at least one administrator")
    audit(db, actor, "delete", "user", str(row.id), row.username)
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/audit")
def list_audit(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if user.role == "viewer":
        raise HTTPException(status_code=403, detail="You do not have permission for this action")
    stmt = select(AuditLog).order_by(AuditLog.id.desc())
    total = db.scalar(select(func.count()).select_from(AuditLog)) or 0
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [audit_out(row) for row in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/settings")
def read_settings(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    data = get_settings(db)
    return {
        "company_name": data.get("company_name") or "EspressoLab",
        "grace_minutes": int(data.get("grace_minutes") or 10),
        "working_days": data.get("working_days") or "Sun-Thu",
        "timezone": data.get("timezone") or "Europe/Istanbul",
        "sync_retries": int(data.get("sync_retries") or 2),
        "dormant_after_days": int(data.get("dormant_after_days") or 0),
        "punch_debounce_minutes": float(data.get("punch_debounce_minutes") or 0),
        "max_session_hours": float(data.get("max_session_hours") or 12),
        "retap_window_minutes": float(data.get("retap_window_minutes") or 0),
        "default_start": data.get("default_start") or "08:00",
        "default_end": data.get("default_end") or "16:00",
        "agent_token": data.get("agent_token") or "",
        "using_default_admin_password": data.get("using_default_admin_password") == "1",
    }


@router.put("/settings")
def update_settings(body: SettingsIn, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    updates = body.model_dump(exclude_none=True)
    before = get_settings(db)
    for key, value in updates.items():
        set_setting(db, key, str(value).strip())
    after = get_settings(db)
    changed = [key for key in PAIRING_SETTINGS if _differs(before.get(key), after.get(key))]
    recalculated = 0
    if changed:
        recalculated = rebuild_employees(db, set(db.scalars(select(Employee.id)).all()))
    audit(db, user, "update", "settings", "", ", ".join(sorted(updates)) + (f"; recalculated {recalculated} sessions" if changed else ""))
    db.commit()
    return {**read_settings(db, user), "recalculated_sessions": recalculated if changed else None}


@router.post("/settings/rotate-agent-token")
def rotate_token(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    token = token_urlsafe(24)
    set_setting(db, "agent_token", token)
    audit(db, user, "rotate_token", "settings", "", "Agent token rotated")
    db.commit()
    return {"agent_token": token}


@router.post("/settings/backup")
def backup(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    copied = ""
    source = sqlite_file()
    if source and Path(source).exists():
        dest = BACKUP_DIR / f"espressolab-{stamp}.db"
        src = sqlite3.connect(source)
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        copied = str(dest)
    snapshot = {
        "created_at": stamp,
        "note": "No passwords or device communication keys are included.",
        "employees": [
            {
                "employee_id": row.employee_id,
                "full_name": row.full_name,
                "department": row.department,
                "branch_id": row.branch_id,
                "employment_status": row.employment_status,
            }
            for row in db.scalars(select(Employee)).all()
        ],
        "devices": [
            {"id": row.id, "name": row.name, "host": row.host, "port": row.port, "protocol": row.protocol, "branch_id": row.branch_id}
            for row in db.scalars(select(Device)).all()
        ],
        "punches": [
            {
                "device_id": row.device_id,
                "device_user_id": row.device_user_id,
                "punched_at": row.punched_at.isoformat(sep=" "),
                "punch": row.punch,
            }
            for row in db.scalars(select(Punch)).all()
        ],
    }
    json_path = BACKUP_DIR / f"espressolab-{stamp}.json"
    json_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    audit(db, user, "backup", "database", "", json_path.name)
    db.commit()
    return {"ok": True, "sqlite": copied, "json": str(json_path)}


@router.get("/agent/devices")
def agent_devices(db: Session = Depends(require_agent)):
    from app.security import decrypt_secret

    rows = db.scalars(select(Device).where(Device.protocol == "agent", Device.status == "active")).all()
    branches = {row.id: row.name for row in db.scalars(select(Branch)).all()}
    items = []
    for row in rows:
        payload = device_out(row, branches.get(row.branch_id, "") if row.branch_id else "")
        payload["comm_key"] = decrypt_secret(row.comm_key_encrypted) or "0"
        items.append(payload)
    return {"items": items}


@router.post("/agent/import")
def agent_import(body: AgentIngest, db: Session = Depends(require_agent)):
    device = db.get(Device, body.device_id)
    if device is None or device.status != "active":
        raise HTTPException(status_code=404, detail="Device not found")
    if device.protocol != "agent":
        raise HTTPException(status_code=400, detail="This device is not assigned to the branch agent")
    logs = []
    for item in body.logs:
        try:
            stamp = clean_stamp(datetime.fromisoformat(item.punched_at.strip().replace(" ", "T")[:19]))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Punch time must be YYYY-MM-DDTHH:MM:SS") from exc
        user_id = item.user_id.strip()
        if not user_id:
            continue
        logs.append(NormalizedLog(user_id=user_id, punched_at=stamp, punch=item.punch, status=item.status, uid=item.uid))
    users = [NormalizedUser(user_id=item.user_id.strip(), name=item.name.strip()) for item in body.users if item.user_id.strip()]
    run = ingest(db, device, logs, users, "agent")
    return sync_out(run, device.name)
