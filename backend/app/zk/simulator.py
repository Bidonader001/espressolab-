"""Development adapter. Results from this module are not ZKTeco hardware readings."""

from __future__ import annotations

import json
from datetime import datetime

from app.config import DATA_DIR
from app.zk.base import ConnParams, DeviceInfo, NormalizedLog, NormalizedUser, clean_stamp

SIMULATOR_LABEL = "SIMULATOR — not read from ZKTeco hardware"
_OFFLINE = {"offline", "down", "0.0.0.0", "127.0.0.1"}


def fixture_path(device_id: int):
    folder = DATA_DIR / "simulator"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{device_id}.json"


def _offline(params: ConnParams) -> bool:
    host = (params.host or "").strip().lower()
    return host in _OFFLINE or host.endswith(".invalid")


def test_connection(params: ConnParams) -> DeviceInfo:
    if _offline(params):
        raise ConnectionError(f"Could not reach {params.host}:{params.port}: connection timed out")
    return DeviceInfo(
        ok=True,
        simulated=True,
        model="SIMULATOR",
        firmware="not-a-device",
        serial="SIM",
        message="Simulated adapter responded. This is not a ZKTeco machine.",
    )


def write_fixture(device_id: int, logs: list[dict], users: list[dict]) -> None:
    payload = {"label": SIMULATOR_LABEL, "logs": logs, "users": users}
    fixture_path(device_id).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def clear_fixture(device_id: int) -> None:
    path = fixture_path(device_id)
    if path.exists():
        path.unlink()


def fetch(params: ConnParams) -> tuple[list[NormalizedLog], list[NormalizedUser]]:
    test_connection(params)
    path = fixture_path(params.device_id)
    if not path.exists():
        return [], []
    data = json.loads(path.read_text(encoding="utf-8"))
    if SIMULATOR_LABEL not in str(data.get("label") or ""):
        raise ValueError("Simulator file is missing its simulator label and was not imported.")
    logs: list[NormalizedLog] = []
    for item in data.get("logs") or []:
        user_id = str(item.get("user_id") or "").strip()
        raw = str(item.get("punched_at") or "").strip().replace(" ", "T")
        if not user_id or not raw:
            continue
        stamp = clean_stamp(datetime.fromisoformat(raw[:19]))
        logs.append(
            NormalizedLog(
                user_id=user_id,
                punched_at=stamp,
                punch=int(item.get("punch") or 0),
                status=int(item.get("status") or 0),
                uid=int(item.get("uid") or 0),
            )
        )
    users = [
        NormalizedUser(user_id=str(item.get("user_id") or "").strip(), name=str(item.get("name") or ""))
        for item in (data.get("users") or [])
        if str(item.get("user_id") or "").strip()
    ]
    return logs, users
