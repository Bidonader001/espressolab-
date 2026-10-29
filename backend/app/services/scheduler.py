"""Background polling for devices the server can route to. Push and agent devices are skipped."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from sqlalchemy import select

from app.database import get_session
from app.models import Device
from app.services.sync import start_sync

log = logging.getLogger("espressolab.scheduler")
_stop = threading.Event()
_thread: threading.Thread | None = None


def start_scheduler() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="espressolab-scheduler", daemon=True)
    _thread.start()


def stop_scheduler() -> None:
    _stop.set()


def _loop() -> None:
    if _stop.wait(60):
        return
    while not _stop.is_set():
        try:
            _tick()
        except Exception:
            log.exception("scheduler tick failed")
        _stop.wait(20)


FAILURE_BACKOFF_MINUTES = 10


def is_due(device: Device, now: datetime) -> bool:
    """A sync is due once the interval has passed since the last attempt, successful or not.

    A terminal that keeps failing is retried no more often than every ten minutes, so an
    unreachable device does not fill the history with errors.
    """
    interval = max(1, int(device.sync_interval_minutes or 15))
    if device.last_sync_status == "error":
        interval = max(interval, FAILURE_BACKOFF_MINUTES)
    attempts = [stamp for stamp in (device.last_sync_at, device.last_test_at) if stamp is not None]
    if not attempts:
        return True
    return max(attempts) <= now - timedelta(minutes=interval)


def _tick() -> None:
    db = get_session()
    due: list[int] = []
    try:
        now = datetime.now()
        devices = db.scalars(
            select(Device).where(
                Device.sync_enabled.is_(True),
                Device.status == "active",
                Device.protocol.in_(("tcp", "udp", "simulator")),
            )
        ).all()
        for device in devices:
            if is_due(device, now):
                due.append(device.id)
    finally:
        db.close()
    if not due:
        return
    workers = min(4, len(due))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(lambda device_id: _safe(device_id), due))


def _safe(device_id: int) -> None:
    try:
        start_sync(device_id, "schedule", background=False)
    except Exception:
        log.exception("scheduled sync failed for device %s", device_id)
