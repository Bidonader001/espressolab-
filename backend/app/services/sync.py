"""Device sync. Read-only toward hardware: logs are copied in, never cleared on the device."""

from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import Device, DeviceUser, Employee, Punch, SyncRun
from app.security import decrypt_secret, safe_error
from app.services.attendance import get_settings, rebuild_employees
from app.zk.base import ConnParams, NormalizedLog, NormalizedUser
from app.zk import pyzk_adapter, simulator

log = logging.getLogger("espressolab.sync")
_ACTIVE = {"queued", "connecting", "downloading", "importing", "recalculating"}
_WRITE = threading.Lock()


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def _params(device: Device) -> ConnParams:
    secret = decrypt_secret(device.comm_key_encrypted)
    try:
        comm_key = int(secret or "0")
    except ValueError as exc:
        raise ValueError("The stored communication key is not a number.") from exc
    return ConnParams(
        device_id=device.id,
        name=device.name,
        host=device.host,
        port=int(device.port),
        timeout=int(device.timeout_seconds or 8),
        protocol=device.protocol,
        comm_key=comm_key,
        serial_number=device.serial_number or "",
    )


def _success_status(protocol: str) -> str:
    if protocol == "simulator":
        return "simulated"
    if protocol == "agent":
        return "agent"
    return "online"


def _fetch(params: ConnParams, retries: int) -> tuple[list[NormalizedLog], list[NormalizedUser]]:
    last: Exception | None = None
    attempts = max(1, retries)
    for attempt in range(attempts):
        try:
            if params.protocol == "simulator":
                return simulator.fetch(params)
            if params.protocol in {"tcp", "udp"}:
                return pyzk_adapter.fetch(params)
            raise ValueError(f"Protocol {params.protocol} is not pulled by the server.")
        except Exception as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(0.4)
    assert last is not None
    raise last


def _punch(device: Device, item: NormalizedLog, run_id: int) -> Punch:
    return Punch(
        device_id=device.id,
        device_user_id=item.user_id,
        punched_at=item.punched_at,
        punch=int(item.punch),
        status_code=int(item.status),
        record_uid=int(item.uid),
        sync_run_id=run_id,
        device_name_snapshot=device.name,
        imported_at=_now(),
    )


def _insert(
    db: Session, device: Device, logs: list[NormalizedLog], run_id: int, run: SyncRun | None = None
) -> tuple[int, int, set[str]]:
    """Skip punches already stored, then save the new ones in one write.

    Returns inserted count, skipped count, and the device user ids that received new punches.
    """
    stored = {
        (user_id, punched_at, int(punch))
        for user_id, punched_at, punch in db.execute(
            select(Punch.device_user_id, Punch.punched_at, Punch.punch).where(Punch.device_id == device.id)
        )
    }
    fresh_logs: list[NormalizedLog] = []
    seen: set[tuple[str, datetime, int]] = set()
    for item in logs:
        if not item.user_id:
            continue
        key = (item.user_id, item.punched_at, int(item.punch))
        if key in seen or key in stored:
            continue
        seen.add(key)
        fresh_logs.append(item)
    skipped = max(0, len(logs) - len(fresh_logs))
    for attempt in range(6):
        try:
            if fresh_logs:
                db.add_all(_punch(device, item, run_id) for item in fresh_logs)
            if run is not None:
                run.records_inserted = len(fresh_logs)
                run.records_skipped = skipped
                run.message = f"Saving {len(fresh_logs)} new punches, {skipped} already stored"
            db.commit()
            return len(fresh_logs), skipped, {item.user_id for item in fresh_logs}
        except OperationalError as exc:
            db.rollback()
            if "locked" not in str(exc).lower() or attempt == 5:
                raise
            time.sleep(0.4 * (attempt + 1))
    raise OperationalError("database is locked", None, None)


_PLACEHOLDER = re.compile(r"^(user|nn|no\s*name|unnamed)[\s_-]*\d*$", re.IGNORECASE)


def is_placeholder_name(name: str) -> bool:
    """Terminals label unnamed users 'NN-435' and this app labels them 'User 435'."""
    value = (name or "").strip()
    return not value or bool(_PLACEHOLDER.match(value))


def employees_for_users(db: Session, device: Device, user_ids: set[str]) -> set[int]:
    if not user_ids:
        return set()
    rows = db.scalars(
        select(DeviceUser.employee_pk).where(
            DeviceUser.device_id == device.id,
            DeviceUser.device_user_id.in_(user_ids),
            DeviceUser.employee_pk.is_not(None),
        )
    ).all()
    return {int(pk) for pk in rows if pk}


def _enroll_from_device(db: Session, device: Device, row: DeviceUser) -> bool:
    """Create or reuse an employee for a user id that arrived from the terminal.

    Returns True when this call linked the device user to an employee for the first time.
    """
    name = (row.name_on_device or "").strip()
    if row.employee_pk:
        current = db.get(Employee, row.employee_pk)
        if (
            current is not None
            and (current.origin or "manual") == "device"
            and not is_placeholder_name(name)
            and is_placeholder_name(current.full_name)
        ):
            current.full_name = name[:160]
        return False
    employee_id = row.device_user_id.strip()[:40]
    emp = db.scalar(select(Employee).where(Employee.employee_id == employee_id))
    if emp is None:
        emp = Employee(
            employee_id=employee_id,
            full_name=(name or f"User {employee_id}")[:160],
            branch_id=device.branch_id,
            employment_status="active",
            origin="device",
        )
        db.add(emp)
        db.flush()
    row.employee_pk = emp.id
    return True


def _touch_users(db: Session, device: Device, logs: list[NormalizedLog], users: list[NormalizedUser]) -> set[int]:
    """Save the terminal's user list. Returns employees that were linked for the first time."""
    names: dict[str, str] = {}
    for item in users:
        if item.user_id:
            names[item.user_id] = item.name or names.get(item.user_id, "")
    for item in logs:
        names.setdefault(item.user_id, "")
    existing = {
        row.device_user_id: row
        for row in db.scalars(select(DeviceUser).where(DeviceUser.device_id == device.id)).all()
    }
    linked: set[int] = set()
    for user_id, name in names.items():
        if not user_id:
            continue
        row = existing.get(user_id)
        if row is None:
            row = DeviceUser(device_id=device.id, device_user_id=user_id, name_on_device=name or "")
            db.add(row)
            existing[user_id] = row
        elif name:
            row.name_on_device = name
        if _enroll_from_device(db, device, row) and row.employee_pk:
            linked.add(row.employee_pk)
    db.flush()
    return linked


def enroll_from_stored_punches(db: Session, device: Device) -> set[int]:
    """Link punches that were saved before a sync was interrupted."""
    user_ids = db.scalars(select(Punch.device_user_id).where(Punch.device_id == device.id).distinct()).all()
    existing = {
        row.device_user_id: row
        for row in db.scalars(select(DeviceUser).where(DeviceUser.device_id == device.id)).all()
    }
    linked: set[int] = set()
    for user_id in user_ids:
        user_id = (user_id or "").strip()
        if not user_id:
            continue
        row = existing.get(user_id)
        if row is None:
            row = DeviceUser(device_id=device.id, device_user_id=user_id, name_on_device="")
            db.add(row)
            existing[user_id] = row
        if _enroll_from_device(db, device, row) and row.employee_pk:
            linked.add(row.employee_pk)
    db.flush()
    return linked


def release_stuck_syncs(db: Session) -> None:
    """A restarted server cannot still be inside an old sync."""
    now = _now()
    rows = db.scalars(select(SyncRun).where(SyncRun.status.in_(_ACTIVE), SyncRun.finished_at.is_(None))).all()
    for run in rows:
        run.status = "error"
        run.error_message = "Sync was interrupted. The punches already saved were kept."
        run.message = run.error_message
        run.finished_at = now
        device = db.get(Device, run.device_id)
        if device is not None and (device.last_error or "").lower().find("database is locked") >= 0:
            device.last_error = ""
            device.last_sync_status = "error"
    db.commit()


def repair_stored_attendance(db: Session) -> int:
    """Create employees for punches that never got a device user."""
    from app.services.attendance import rebuild_employees

    touched: set[int] = set()
    devices = db.scalars(select(Device)).all()
    for device in devices:
        punches = db.scalar(select(func.count()).select_from(Punch).where(Punch.device_id == device.id)) or 0
        if not punches:
            continue
        touched |= enroll_from_stored_punches(db, device)
    if touched:
        rebuild_employees(db, touched)
    db.commit()
    log.info("linked %s stored device users to employees", len(touched))
    return len(touched)


def _fail(db: Session, run: SyncRun, device: Device, message: str) -> None:
    run.status = "error"
    run.error_message = message
    run.message = message
    run.finished_at = _now()
    device.connection_status = "offline"
    device.last_error = message
    device.last_sync_status = "error"
    device.last_test_at = run.finished_at
    db.commit()


def _run_sync(run_id: int) -> None:
    _run_sync_locked(run_id)


def _run_sync_locked(run_id: int) -> None:
    db = get_session()
    secret = ""
    try:
        run = db.get(SyncRun, run_id)
        device = db.get(Device, run.device_id) if run else None
        if run is None or device is None:
            return
        secret = decrypt_secret(device.comm_key_encrypted)
        run.status = "connecting"
        run.message = f"Connecting to {device.host}:{device.port}"
        db.commit()
        try:
            params = _params(device)
            retries = int(get_settings(db).get("sync_retries") or "2")
        except Exception as exc:
            _fail(db, run, device, safe_error(exc, secret))
            return
        run.status = "downloading"
        run.message = "Downloading attendance logs"
        db.commit()
        try:
            logs, users = _fetch(params, retries)
        except Exception as exc:
            _fail(db, run, device, safe_error(exc, secret))
            log.warning("sync failed for device %s: %s", device.id, safe_error(exc, secret))
            return
        run.status = "importing"
        run.records_fetched = len(logs)
        run.message = f"Importing {len(logs)} logs"
        db.commit()
        with _WRITE:
            inserted, skipped, fresh_users = _insert(db, device, logs, run.id, run)
            touched = _touch_users(db, device, logs, users)
            touched |= enroll_from_stored_punches(db, device)
            touched |= employees_for_users(db, device, fresh_users)
            run.records_fetched = len(logs)
            run.records_inserted = inserted
            run.records_skipped = skipped
            db.commit()
            run.status = "recalculating"
            run.message = "Recalculating attendance"
            db.commit()
            if touched:
                rebuild_employees(db, touched)
            run.status = "success"
            run.message = f"Inserted {inserted}, skipped {skipped} duplicates"
            run.finished_at = _now()
            device.connection_status = _success_status(device.protocol)
            device.last_error = ""
            device.last_sync_at = run.finished_at
            device.last_sync_status = "success"
            device.last_test_at = run.finished_at
            db.commit()
    except Exception as exc:
        log.exception("sync crashed")
        db.rollback()
        _mark_crash(run_id, safe_error(exc, secret))
    finally:
        db.close()


def _mark_crash(run_id: int, message: str) -> None:
    db = get_session()
    try:
        run = db.get(SyncRun, run_id)
        if run is None:
            return
        device = db.get(Device, run.device_id)
        run.status = "error"
        run.error_message = message
        run.message = message
        run.finished_at = _now()
        if device is not None:
            device.connection_status = "offline"
            device.last_error = message
            device.last_sync_status = "error"
        db.commit()
    finally:
        db.close()


def start_sync(device_id: int, trigger: str = "manual", background: bool = True) -> int:
    db = get_session()
    try:
        device = db.get(Device, device_id)
        if device is None:
            raise ValueError("Device not found")
        if device.status != "active":
            raise ValueError("Device is disabled")
        if device.protocol in {"push", "agent"}:
            raise ValueError(
                "This device is not polled by the server. Push terminals send logs themselves. "
                "Agent devices are read by the branch agent on the store network."
            )
        running = db.scalar(
            select(SyncRun)
            .where(SyncRun.device_id == device.id, SyncRun.status.in_(_ACTIVE))
            .order_by(SyncRun.id.desc())
        )
        if running is not None:
            return int(running.id)
        run = SyncRun(device_id=device.id, trigger=trigger, status="queued", message="Queued", started_at=_now())
        db.add(run)
        db.commit()
        run_id = int(run.id)
    finally:
        db.close()
    if background:
        threading.Thread(target=_run_sync, args=(run_id,), name=f"sync-{run_id}", daemon=True).start()
    else:
        _run_sync(run_id)
    return run_id


def ingest(
    db: Session,
    device: Device,
    logs: list[NormalizedLog],
    users: list[NormalizedUser],
    trigger: str,
    bad_lines: int = 0,
) -> SyncRun:
    run = SyncRun(
        device_id=device.id,
        trigger=trigger,
        status="importing",
        message="Importing pushed logs",
        started_at=_now(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    with _WRITE:
        inserted, skipped, fresh_users = _insert(db, device, logs, run.id, run)
        touched = _touch_users(db, device, logs, users)
        touched |= enroll_from_stored_punches(db, device)
        touched |= employees_for_users(db, device, fresh_users)
        if touched:
            rebuild_employees(db, touched)
    run.records_fetched = len(logs) + bad_lines
    run.records_inserted = inserted
    run.records_skipped = skipped
    run.finished_at = _now()
    if bad_lines and inserted == 0 and not logs:
        run.status = "error"
        run.error_message = f"{bad_lines} attendance lines could not be parsed"
        run.message = run.error_message
        device.connection_status = "offline"
        device.last_error = run.error_message
        device.last_sync_status = "error"
    else:
        run.status = "partial" if bad_lines else "success"
        note = f"Inserted {inserted}, skipped {skipped} duplicates"
        if bad_lines:
            note = f"{note}. {bad_lines} lines could not be parsed"
        run.message = note
        run.error_message = "" if not bad_lines else f"{bad_lines} unparsed lines"
        device.connection_status = _success_status(device.protocol)
        device.last_error = ""
        device.last_sync_at = run.finished_at
        device.last_sync_status = run.status
        device.last_push_at = run.finished_at if trigger == "push" else device.last_push_at
    db.commit()
    return run


def test_device(device_id: int) -> dict:
    db = get_session()
    try:
        device = db.get(Device, device_id)
        if device is None:
            raise ValueError("Device not found")
        busy = db.scalar(
            select(SyncRun)
            .where(SyncRun.device_id == device.id, SyncRun.status.in_(_ACTIVE))
            .order_by(SyncRun.id.desc())
        )
        if busy is not None and device.protocol in {"tcp", "udp", "simulator"}:
            return {
                "ok": False,
                "simulated": device.protocol == "simulator",
                "message": f"A sync is already using this terminal ({busy.status}). Wait for it to finish, then test again.",
                "firmware": device.firmware or "",
                "serial_number": device.serial_number or "",
                "model": device.model or "",
                "connection_status": device.connection_status,
                "protocol": device.protocol,
            }
        now = _now()
        device.last_test_at = now
        info_message = ""
        ok = False
        simulated = device.protocol == "simulator"
        firmware = device.firmware or ""
        serial = device.serial_number or ""
        model = device.model or ""
        try:
            if device.protocol == "push":
                if device.last_push_at and (now - device.last_push_at).total_seconds() <= 180:
                    ok = True
                    device.connection_status = "online"
                    device.last_error = ""
                    info_message = f"Last contact from this terminal at {device.last_push_at.isoformat(sep=' ')}"
                else:
                    ok = False
                    device.connection_status = "unknown" if device.last_push_at is None else "offline"
                    info_message = (
                        "No recent push from this serial. Point the terminal at /iclock/cdata on this server. "
                        "A missing device is not reported as connected."
                    )
                    device.last_error = info_message
            elif device.protocol == "agent":
                ok = device.connection_status == "agent"
                info_message = (
                    "The application server does not open a socket to this device. "
                    "Run the branch agent on the store network."
                )
                if not ok:
                    device.last_error = info_message
            else:
                params = _params(device)
                if device.protocol == "simulator":
                    probe = simulator.test_connection(params)
                else:
                    probe = pyzk_adapter.test_connection(params)
                ok = probe.ok
                simulated = probe.simulated
                firmware = probe.firmware or firmware
                serial = probe.serial or serial
                model = probe.model or model
                info_message = probe.message
                device.firmware = firmware
                if probe.serial:
                    device.serial_number = probe.serial
                if probe.model and not device.model:
                    device.model = probe.model
                device.connection_status = "simulated" if simulated else "online"
                device.last_error = ""
        except Exception as exc:
            secret = decrypt_secret(device.comm_key_encrypted)
            info_message = safe_error(exc, secret)
            ok = False
            device.connection_status = "offline"
            device.last_error = info_message
            log.warning("connection test failed for device %s: %s", device.id, info_message)
        db.commit()
        return {
            "ok": ok,
            "simulated": simulated,
            "message": info_message,
            "firmware": device.firmware or "",
            "serial_number": device.serial_number or "",
            "model": device.model or model,
            "connection_status": device.connection_status,
            "protocol": device.protocol,
        }
    finally:
        db.close()
