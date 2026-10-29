"""ADMS endpoints. The terminal calls these. Responses never clear device data."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import Device, SyncRun
from app.services.sync import ingest
from app.zk.push import handshake, parse_attlog

router = APIRouter(tags=["iclock"])


def _device_for(db: Session, serial: str, host: str) -> Device | None:
    serial = (serial or "").strip()
    if not serial:
        return None
    device = db.scalar(select(Device).where(Device.serial_number == serial, Device.protocol == "push", Device.status == "active"))
    if device is None:
        return None
    if device.push_allowed_ip and host and device.push_allowed_ip != host:
        return None
    return device


def _touch(device: Device) -> None:
    device.last_push_at = datetime.now().replace(microsecond=0)
    device.connection_status = "online"
    device.last_error = ""


@router.api_route("/iclock/cdata", methods=["GET", "POST"])
async def iclock_cdata(request: Request, db: Session = Depends(get_db)):
    host = request.client.host if request.client else ""
    device = _device_for(db, request.query_params.get("SN", ""), host)
    if device is None:
        return PlainTextResponse("Device not registered", status_code=404)
    if request.method == "GET":
        _touch(device)
        db.commit()
        return PlainTextResponse(handshake(device.serial_number))
    table = (request.query_params.get("table") or "ATTLOG").strip().upper()
    raw = (await request.body()).decode("utf-8", errors="replace")
    if table != "ATTLOG":
        _touch(device)
        db.add(
            SyncRun(
                device_id=device.id,
                trigger="push",
                status="success",
                message=f"Ignored {table}. Device users and logs were not modified.",
                started_at=device.last_push_at,
                finished_at=device.last_push_at,
            )
        )
        db.commit()
        return PlainTextResponse("OK")
    logs, bad = parse_attlog(raw)
    ingest(db, device, logs, [], "push", bad_lines=bad)
    return PlainTextResponse("OK")


@router.get("/iclock/getrequest")
def iclock_getrequest(request: Request, db: Session = Depends(get_db)):
    host = request.client.host if request.client else ""
    device = _device_for(db, request.query_params.get("SN", ""), host)
    if device is None:
        return PlainTextResponse("Device not registered", status_code=404)
    _touch(device)
    db.commit()
    # OK means "no command". Never return CLEAR LOG, DATA DELETE, or user updates.
    return PlainTextResponse("OK")


@router.get("/iclock/ping")
def iclock_ping(request: Request, db: Session = Depends(get_db)):
    host = request.client.host if request.client else ""
    device = _device_for(db, request.query_params.get("SN", ""), host)
    if device is None:
        return PlainTextResponse("Device not registered", status_code=404)
    _touch(device)
    db.commit()
    return PlainTextResponse("OK")
