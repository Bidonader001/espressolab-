"""Read-only ZKTeco pull via pyzk. Never clears logs or writes device users."""

from __future__ import annotations

from datetime import datetime

from app.zk.base import ConnParams, DeviceInfo, NormalizedLog, NormalizedUser, clean_stamp


def _connect(params: ConnParams):
    from zk import ZK

    zk = ZK(
        params.host,
        port=params.port,
        timeout=params.timeout,
        password=int(params.comm_key or 0),
        force_udp=params.protocol == "udp",
        ommit_ping=True,
    )
    return zk.connect()


def _call(conn, name: str) -> str:
    fn = getattr(conn, name, None)
    if not callable(fn):
        return ""
    try:
        value = fn()
    except Exception:
        return ""
    return "" if value is None else str(value)


def test_connection(params: ConnParams) -> DeviceInfo:
    conn = None
    try:
        conn = _connect(params)
        return DeviceInfo(
            ok=True,
            message=f"Connected to {params.host}:{params.port}",
            firmware=_call(conn, "get_firmware_version"),
            serial=_call(conn, "get_serialnumber"),
            model=_call(conn, "get_device_name"),
            simulated=False,
        )
    finally:
        if conn is not None:
            conn.disconnect()


def _logs_from(records) -> list[NormalizedLog]:
    logs: list[NormalizedLog] = []
    for rec in records or []:
        user_id = str(getattr(rec, "user_id", "") or "").strip()
        stamp = getattr(rec, "timestamp", None)
        if not user_id or not isinstance(stamp, datetime):
            continue
        logs.append(
            NormalizedLog(
                user_id=user_id,
                punched_at=clean_stamp(stamp),
                punch=int(getattr(rec, "punch", 0) or 0),
                status=int(getattr(rec, "status", 0) or 0),
                uid=int(getattr(rec, "uid", 0) or 0),
            )
        )
    return logs


def _users_from(records) -> list[NormalizedUser]:
    users: list[NormalizedUser] = []
    for rec in records or []:
        user_id = str(getattr(rec, "user_id", "") or "").strip()
        if not user_id:
            continue
        users.append(NormalizedUser(user_id=user_id, name=str(getattr(rec, "name", "") or "")))
    return users


def fetch(params: ConnParams) -> tuple[list[NormalizedLog], list[NormalizedUser]]:
    """Read attendance and the user list. Does not disable, clear, or edit the device."""
    conn = None
    try:
        conn = _connect(params)
        logs = _logs_from(conn.get_attendance())
        try:
            users = _users_from(conn.get_users())
        except Exception:
            users = []
        return logs, users
    finally:
        if conn is not None:
            conn.disconnect()
