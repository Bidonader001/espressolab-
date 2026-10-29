"""ZKTeco devices, connection tests, and synchronization."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import allow_simulator
from app.deps import current_user, get_db, require_writer
from app.models import AttendanceSession, Branch, Device, DeviceUser, Employee, LeaveEntry, Punch, SyncRun, User
from app.schemas import DeviceIn, DeviceUpdate, MapIn, SimulatorIn
from app.security import encrypt_secret
from app.serialize import device_out, device_user_out, stamp, sync_out
from app.services.attendance import rebuild_employees
from app.services.audit import audit
from app.services.sync import start_sync, test_device
from app.zk import simulator

router = APIRouter(prefix="/api/v1", tags=["devices"])


def _device(db: Session, device_id: int) -> Device:
    row = db.get(Device, device_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return row


def _out(db: Session, row: Device) -> dict:
    branch = db.get(Branch, row.branch_id) if row.branch_id else None
    return device_out(row, branch.name if branch else "")


def _check_protocol(protocol: str, serial: str) -> None:
    if protocol == "simulator" and not allow_simulator():
        raise HTTPException(status_code=400, detail="The simulator adapter is disabled on this server")
    if protocol == "push" and not serial.strip():
        raise HTTPException(status_code=400, detail="Push devices need the terminal serial number")


@router.get("/devices")
def list_devices(db: Session = Depends(get_db), _: User = Depends(current_user)):
    branches = {row.id: row.name for row in db.scalars(select(Branch)).all()}
    rows = db.scalars(select(Device).order_by(Device.name)).all()
    return {"items": [device_out(row, branches.get(row.branch_id, "") if row.branch_id else "") for row in rows]}


@router.post("/devices")
def create_device(body: DeviceIn, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    _check_protocol(body.protocol, body.serial_number)
    row = Device(
        name=body.name.strip(),
        host=body.host,
        port=body.port,
        model=body.model.strip(),
        branch_id=body.branch_id,
        protocol=body.protocol,
        comm_key_encrypted=encrypt_secret(body.comm_key or ""),
        timeout_seconds=body.timeout_seconds,
        sync_interval_minutes=body.sync_interval_minutes,
        sync_enabled=body.sync_enabled and body.protocol not in {"push", "agent"},
        serial_number=body.serial_number.strip(),
        push_allowed_ip=body.push_allowed_ip.strip(),
        connection_status="unknown",
    )
    db.add(row)
    db.flush()
    audit(db, user, "create", "device", str(row.id), f"{row.name} {row.protocol} {row.host}")
    db.commit()
    return _out(db, row)


@router.get("/devices/{device_id}")
def get_device(device_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    row = _device(db, device_id)
    body = _out(db, row)
    body["punch_count"] = db.scalar(select(func.count()).select_from(Punch).where(Punch.device_id == row.id)) or 0
    body["user_count"] = db.scalar(select(func.count()).select_from(DeviceUser).where(DeviceUser.device_id == row.id)) or 0
    first, last = db.execute(
        select(func.min(Punch.punched_at), func.max(Punch.punched_at)).where(Punch.device_id == row.id)
    ).one()
    body["first_punch"] = stamp(first)
    body["last_punch"] = stamp(last)
    return body


@router.patch("/devices/{device_id}")
def update_device(device_id: int, body: DeviceUpdate, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    row = _device(db, device_id)
    data = body.model_dump(exclude_unset=True)
    protocol = data.get("protocol", row.protocol)
    serial = data.get("serial_number", row.serial_number) or ""
    _check_protocol(protocol, serial)
    if "name" in data and data["name"]:
        row.name = data["name"].strip()
    if "host" in data and data["host"]:
        row.host = data["host"]
    if "port" in data and data["port"] is not None:
        row.port = data["port"]
    if "model" in data and data["model"] is not None:
        row.model = data["model"].strip()
    if "branch_id" in data:
        row.branch_id = data["branch_id"]
    if "protocol" in data and data["protocol"]:
        row.protocol = data["protocol"]
    if "timeout_seconds" in data and data["timeout_seconds"] is not None:
        row.timeout_seconds = data["timeout_seconds"]
    if "sync_interval_minutes" in data and data["sync_interval_minutes"] is not None:
        row.sync_interval_minutes = data["sync_interval_minutes"]
    if "sync_enabled" in data and data["sync_enabled"] is not None:
        row.sync_enabled = bool(data["sync_enabled"])
    if "status" in data and data["status"]:
        row.status = data["status"]
    if "serial_number" in data and data["serial_number"] is not None:
        row.serial_number = data["serial_number"].strip()
    if "push_allowed_ip" in data and data["push_allowed_ip"] is not None:
        row.push_allowed_ip = data["push_allowed_ip"].strip()
    if "comm_key" in data:
        row.comm_key_encrypted = encrypt_secret(data["comm_key"] or "")
    audit(db, user, "update", "device", str(row.id), row.name)
    db.commit()
    return _out(db, row)


@router.delete("/devices/{device_id}")
def delete_device(device_id: int, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    row = _device(db, device_id)
    links = db.scalars(select(DeviceUser).where(DeviceUser.device_id == device_id)).all()
    touched = {link.employee_pk for link in links if link.employee_pk}
    db.execute(delete(Punch).where(Punch.device_id == device_id))
    db.execute(delete(DeviceUser).where(DeviceUser.device_id == device_id))
    db.execute(delete(SyncRun).where(SyncRun.device_id == device_id))
    name = row.name
    db.delete(row)
    db.flush()
    rebuild_employees(db, touched)
    removed_people = 0
    for pk in touched:
        emp = db.get(Employee, pk)
        if emp is None or (emp.origin or "manual") != "device":
            continue
        still_linked = db.scalar(select(func.count()).select_from(DeviceUser).where(DeviceUser.employee_pk == pk)) or 0
        if still_linked:
            continue
        db.execute(delete(AttendanceSession).where(AttendanceSession.employee_pk == pk))
        db.execute(delete(LeaveEntry).where(LeaveEntry.employee_pk == pk))
        db.delete(emp)
        removed_people += 1
    audit(db, user, "delete", "device", str(device_id), f"{name}; employees removed {removed_people}")
    db.commit()
    return {
        "ok": True,
        "deleted": True,
        "detail": "Device removed. Its imported attendance is no longer included in reports. The terminal was not changed.",
    }


@router.post("/devices/{device_id}/test")
def test_connection(device_id: int, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    _device(db, device_id)
    db.commit()
    try:
        result = test_device(device_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    audit(db, user, "test_device", "device", str(device_id), result.get("connection_status") or "")
    db.commit()
    db.expire_all()
    fresh = _device(db, device_id)
    return {**result, "device": _out(db, fresh)}


@router.post("/devices/{device_id}/sync")
def sync_device(
    device_id: int,
    wait: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(require_writer),
):
    _device(db, device_id)
    db.commit()
    try:
        run_id = start_sync(device_id, "manual", background=not bool(wait))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit(db, user, "sync", "device", str(device_id), f"run {run_id}")
    db.commit()
    db.expire_all()
    run = db.get(SyncRun, run_id)
    device = _device(db, device_id)
    return {"run": sync_out(run, device.name) if run else {"id": run_id}, "device": _out(db, device)}


@router.post("/devices/sync-all")
def sync_all(db: Session = Depends(get_db), user: User = Depends(require_writer)):
    ids = []
    for device in db.scalars(select(Device).where(Device.status == "active", Device.protocol.in_(("tcp", "udp", "simulator")))).all():
        try:
            ids.append(start_sync(device.id, "manual", background=True))
        except ValueError:
            continue
    audit(db, user, "sync_all", "device", "", f"{len(ids)} devices")
    db.commit()
    return {"runs": ids}


@router.get("/devices/{device_id}/punches")
def device_punches(
    device_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    _device(db, device_id)
    rows = db.scalars(select(Punch).where(Punch.device_id == device_id).order_by(Punch.punched_at.desc()).limit(limit)).all()
    return {
        "items": [
            {
                "id": row.id,
                "device_user_id": row.device_user_id,
                "punched_at": stamp(row.punched_at),
                "punch": row.punch,
                "status_code": row.status_code,
                "device_name": row.device_name_snapshot,
                "imported_at": stamp(row.imported_at),
            }
            for row in rows
        ]
    }


@router.get("/devices/{device_id}/users")
def device_users(device_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    _device(db, device_id)
    rows = db.scalars(select(DeviceUser).where(DeviceUser.device_id == device_id).order_by(DeviceUser.device_user_id)).all()
    employees = {row.id: row for row in db.scalars(select(Employee)).all()}
    items = []
    for row in rows:
        emp = employees.get(row.employee_pk) if row.employee_pk else None
        items.append(device_user_out(row, emp.employee_id if emp else "", emp.full_name if emp else ""))
    return {"items": items}


@router.post("/devices/{device_id}/map")
def map_device_user(device_id: int, body: MapIn, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    device = _device(db, device_id)
    pin = body.device_user_id.strip()
    row = db.scalar(select(DeviceUser).where(DeviceUser.device_id == device.id, DeviceUser.device_user_id == pin))
    if row is None:
        row = DeviceUser(device_id=device.id, device_user_id=pin, name_on_device="")
        db.add(row)
        db.flush()
    previous = row.employee_pk
    new_pk = None
    label = "unmapped"
    if body.employee_id:
        emp = db.scalar(select(Employee).where(Employee.employee_id == body.employee_id.strip()))
        if emp is None:
            raise HTTPException(status_code=404, detail="Employee not found")
        new_pk = emp.id
        label = emp.employee_id
    row.employee_pk = new_pk
    touched = {pk for pk in (previous, new_pk) if pk}
    rebuild_employees(db, touched)
    audit(db, user, "map_user", "device", str(device.id), f"{pin} -> {label}")
    db.commit()
    emp = db.get(Employee, row.employee_pk) if row.employee_pk else None
    return device_user_out(row, emp.employee_id if emp else "", emp.full_name if emp else "")


@router.post("/devices/{device_id}/simulator-logs")
def store_simulator_logs(device_id: int, body: SimulatorIn, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    device = _device(db, device_id)
    if device.protocol != "simulator":
        raise HTTPException(status_code=400, detail="Simulator logs can only be stored on a simulated device")
    if not allow_simulator():
        raise HTTPException(status_code=400, detail="The simulator adapter is disabled on this server")
    simulator.write_fixture(
        device.id,
        [item.model_dump() for item in body.logs],
        [item.model_dump() for item in body.users],
    )
    audit(db, user, "simulator_logs", "device", str(device.id), "Stored a simulator fixture. Not hardware.")
    db.commit()
    return {"ok": True, "logs": len(body.logs), "simulated": True, "warning": simulator.SIMULATOR_LABEL}


@router.post("/devices/{device_id}/clear-simulator")
def clear_simulator(device_id: int, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    device = _device(db, device_id)
    if device.protocol != "simulator":
        raise HTTPException(status_code=400, detail="Only a simulated device can be cleared here. Hardware logs are never deleted.")
    links = db.scalars(select(DeviceUser).where(DeviceUser.device_id == device.id)).all()
    touched = {row.employee_pk for row in links if row.employee_pk}
    db.query(Punch).filter(Punch.device_id == device.id).delete()
    simulator.clear_fixture(device.id)
    rebuild_employees(db, touched)
    device.last_error = ""
    audit(db, user, "clear_simulator", "device", str(device.id), "Removed simulated punches from the database")
    db.commit()
    return {"ok": True, "simulated": True}


@router.get("/sync-runs")
def list_sync_runs(
    device_id: int | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    stmt = select(SyncRun)
    if device_id:
        stmt = stmt.where(SyncRun.device_id == device_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(SyncRun.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    names = {row.id: row.name for row in db.scalars(select(Device)).all()}
    return {
        "items": [sync_out(row, names.get(row.device_id, "")) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/sync-runs/{run_id}")
def get_sync_run(run_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    row = db.get(SyncRun, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Sync run not found")
    device = db.get(Device, row.device_id)
    return sync_out(row, device.name if device else "")
