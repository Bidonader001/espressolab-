"""Dashboard and attendance rows. Figures come from the same calculation as the exports."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.deps import current_user, get_db, require_writer
from app.exports import DETAIL_ALL, DETAIL_DEFAULT, DIRECTORY_ALL, DIRECTORY_DEFAULT, FORMATS, REPORT_TYPES, ExportError, collect
from app.models import Branch, Device, DeviceUser, Employee, SyncRun, User
from app.services.attendance import get_settings, load_bundle, rebuild_employees
from app.services.audit import audit

router = APIRouter(prefix="/api/v1", tags=["attendance"])


def _today(zone: str):
    try:
        return datetime.now(ZoneInfo(zone or "Europe/Istanbul")).date()
    except Exception:
        return datetime.now().date()


@router.get("/dashboard")
def dashboard(branch: str = "", db: Session = Depends(get_db), _: User = Depends(current_user)):
    settings = get_settings(db)
    zone = settings.get("timezone") or "Europe/Istanbul"
    if branch.strip():
        row = db.scalar(select(Branch).where(Branch.name == branch.strip()))
        if row and row.timezone:
            zone = row.timezone
    today = _today(zone)
    bundle = load_bundle(db, date_from=today.isoformat(), date_to=today.isoformat())
    source = "device" if bundle.get("device_employee_ids") else ""
    try:
        data = collect(
            {"report": "daily", "start_date": today.isoformat(), "end_date": today.isoformat(), "branch": branch.strip(), "source": source},
            bundle,
        )
    except ExportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    punched = [row for row in data["details"] if row["status"] in {"Present", "Late", "Incomplete"}]
    month_start = today.replace(day=1)
    trend_bundle = load_bundle(db, date_from=month_start.isoformat(), date_to=today.isoformat())
    trend_source = "device" if trend_bundle.get("device_employee_ids") else ""
    trend = collect(
        {
            "report": "monthly",
            "start_date": month_start.isoformat(),
            "end_date": today.isoformat(),
            "branch": branch.strip(),
            "source": trend_source,
        },
        trend_bundle,
    )
    present_by_day: dict[str, set[str]] = {}
    late_by_day: dict[str, set[str]] = {}
    for row in trend["details"]:
        if row["status"] in {"Present", "Late", "Incomplete"}:
            present_by_day.setdefault(row["date_iso"], set()).add(row["employee_id"])
        if row["status"] == "Late":
            late_by_day.setdefault(row["date_iso"], set()).add(row["employee_id"])
    absent_by_day: dict[str, int] = {}
    for row in trend["absences"]:
        absent_by_day[row["date_iso"]] = absent_by_day.get(row["date_iso"], 0) + 1
    days = []
    cursor = month_start
    while cursor <= today:
        key = cursor.isoformat()
        days.append(
            {
                "date": key,
                "present": len(present_by_day.get(key, set())),
                "late": len(late_by_day.get(key, set())),
                "absent": absent_by_day.get(key, 0),
            }
        )
        cursor += timedelta(days=1)
    branch_stats: dict[str, dict] = {}
    for row in data["summary"]:
        item = branch_stats.setdefault(
            row["branch"],
            {"branch": row["branch"], "employees": 0, "present": 0, "late": 0, "absent": 0},
        )
        item["employees"] += 1
        item["present"] += row["days_present"]
        item["late"] += row["late_arrivals"]
        item["absent"] += row["absences"]
    devices = db.scalars(select(Device)).all()
    connectivity: dict[str, int] = {}
    last_sync = None
    for device in devices:
        connectivity[device.connection_status or "unknown"] = connectivity.get(device.connection_status or "unknown", 0) + 1
        if device.last_sync_at and (last_sync is None or device.last_sync_at > last_sync):
            last_sync = device.last_sync_at
    active_people = data["summary"]
    unmapped = db.scalar(select(func.count()).select_from(DeviceUser).where(DeviceUser.employee_pk.is_(None))) or 0
    recent_errors = db.scalars(select(SyncRun).where(SyncRun.status == "error").order_by(SyncRun.id.desc()).limit(5)).all()
    return {
        "date": today.isoformat(),
        "timezone": zone,
        "present": len({row["employee_id"] for row in punched}),
        "late": len({row["employee_id"] for row in punched if row["status"] == "Late"}),
        "missing_punches": len({row["employee_id"] for row in punched if row["status"] == "Incomplete"}),
        "absent": sum(row["absences"] for row in data["summary"]),
        "active_employees": len(active_people),
        "on_leave": len({row["employee_id"] for row in data["details"] if row["status"] == "On Leave"}),
        "branch_stats": list(branch_stats.values()),
        "devices": {
            "total": len(devices),
            "connectivity": connectivity,
            "unmapped_users": unmapped,
        },
        "last_sync_at": last_sync.isoformat(sep=" ") if last_sync else None,
        "recent_errors": [
            {"id": row.id, "device_id": row.device_id, "message": row.error_message, "finished_at": row.finished_at.isoformat(sep=" ") if row.finished_at else None}
            for row in recent_errors
        ],
        "trend": days,
        "hours_note": data["hours_note"],
        "working_days": settings.get("working_days") or "Sun-Thu",
    }


@router.get("/attendance")
def attendance(
    start_date: str = "",
    end_date: str = "",
    branch: str = "",
    department: str = "",
    employee_id: str = "",
    status: str = "",
    q: str = "",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    include_inactive: str = "",
    source: str = "",
    device_id: str = "",
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    bundle = load_bundle(db, employee_id=employee_id, date_from=start_date, date_to=end_date)
    try:
        data = collect(
            {
                "report": "daily",
                "start_date": start_date,
                "end_date": end_date,
                "branch": branch,
                "department": department,
                "employee_id": employee_id,
                "status": status,
                "include_inactive": include_inactive,
                "source": source,
                "device_id": device_id,
            },
            bundle,
        )
    except ExportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rows = list(data["details"])
    if (status or "").strip().lower() == "absent":
        rows = list(data["absences"])
    rows.sort(key=lambda row: ((row.get("name") or "").lower(), row.get("employee_id") or "", row.get("date_iso") or ""))
    if q.strip():
        needle = q.strip().lower()
        rows = [row for row in rows if needle in (row["name"] or "").lower() or needle in (row["employee_id"] or "").lower()]
    start = (page - 1) * page_size
    return {
        "items": rows[start : start + page_size],
        "total": len(rows),
        "page": page,
        "page_size": page_size,
        "summary": data["summary"],
        "hours_note": data["hours_note"],
        "start": data["start"].isoformat(),
        "end": data["end"].isoformat(),
    }


@router.post("/attendance/recalculate")
def recalculate(db: Session = Depends(get_db), user: User = Depends(require_writer)):
    ids = set(db.scalars(select(Employee.id)).all())
    count = rebuild_employees(db, ids)
    audit(db, user, "recalculate", "attendance", "", f"{count} sessions")
    db.commit()
    return {"ok": True, "sessions": count}
