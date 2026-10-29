"""ZKTeco ADMS / PUSH receiver. The device dials us. Replies never delete logs or users."""

from __future__ import annotations

from datetime import datetime

from app.zk.base import NormalizedLog, clean_stamp


def handshake(serial: str) -> str:
    # SyncTime=0 and no CLEAR / DELETE commands. The device clock and logs stay as they are.
    return (
        f"GET OPTION FROM: {serial}\n"
        "ATTLOGStamp=0\n"
        "OPERLOGStamp=0\n"
        "ErrorDelay=60\n"
        "Delay=30\n"
        "TransInterval=1\n"
        "TransFlag=TransData AttLog\n"
        "Realtime=1\n"
        "Encrypt=None\n"
        "TimeZone=0\n"
        "Timeout=60\n"
        "SyncTime=0\n"
        "ServerVer=EspressoLabAttendance\n"
    )


def parse_attlog(body: str) -> tuple[list[NormalizedLog], int]:
    logs: list[NormalizedLog] = []
    bad = 0
    for line in (body or "").splitlines():
        raw = line.strip()
        if not raw:
            continue
        parts = raw.split("\t") if "\t" in raw else raw.split(",")
        if len(parts) < 2:
            bad += 1
            continue
        user_id = parts[0].strip()
        try:
            stamp = datetime.strptime(parts[1].strip()[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                stamp = datetime.fromisoformat(parts[1].strip()[:19])
            except ValueError:
                bad += 1
                continue
        if not user_id:
            bad += 1
            continue
        state = 0
        verify = 0
        if len(parts) > 2 and parts[2].strip().lstrip("-").isdigit():
            state = int(parts[2])
        if len(parts) > 3 and parts[3].strip().lstrip("-").isdigit():
            verify = int(parts[3])
        logs.append(NormalizedLog(user_id=user_id, punched_at=clean_stamp(stamp), punch=state, status=verify, uid=0))
    return logs, bad
