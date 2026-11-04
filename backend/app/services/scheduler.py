"""Daily backup. Device sync runs only when someone presses Sync now."""

from __future__ import annotations

import logging
import threading

from app.database import get_session
from app.services.backup import write_backup

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
    while not _stop.is_set():
        try:
            _backup_tick()
        except Exception:
            log.exception("daily backup failed")
        if _stop.wait(3600):
            return


def _backup_tick() -> None:
    db = get_session()
    try:
        path = write_backup(db)
        log.info("Daily backup is %s", path)
    finally:
        db.close()
