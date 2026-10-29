"""Branch agent. Run this on a network that can reach the attendance terminals.

The application server does not need a route to the device subnet.
The agent pulls logs with pyzk and posts them to the central API.

Example:
  set AGENT_SERVER=https://attendance.example
  set AGENT_TOKEN=the-token-from-settings
  python branch_agent.py sync
  python branch_agent.py test
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def _request(method: str, path: str, payload: dict | None = None) -> dict:
    server = os.environ.get("AGENT_SERVER", "").rstrip("/")
    token = os.environ.get("AGENT_TOKEN", "")
    if not server or not token:
        raise SystemExit("Set AGENT_SERVER and AGENT_TOKEN.")
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        server + path,
        data=data,
        method=method,
        headers={"X-Agent-Token": token, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise SystemExit(f"{exc.code} {detail}") from exc


def _pull(device: dict) -> tuple[list[dict], list[dict]]:
    from zk import ZK

    zk = ZK(
        device["host"],
        port=int(device["port"]),
        timeout=int(device.get("timeout_seconds") or 8),
        password=int(device.get("comm_key") or 0),
        force_udp=device.get("protocol") == "udp",
        ommit_ping=True,
    )
    conn = zk.connect()
    try:
        logs = []
        for rec in conn.get_attendance() or []:
            stamp = getattr(rec, "timestamp", None)
            user_id = str(getattr(rec, "user_id", "") or "").strip()
            if not user_id or stamp is None:
                continue
            logs.append(
                {
                    "user_id": user_id,
                    "punched_at": stamp.strftime("%Y-%m-%dT%H:%M:%S"),
                    "punch": int(getattr(rec, "punch", 0) or 0),
                    "status": int(getattr(rec, "status", 0) or 0),
                    "uid": int(getattr(rec, "uid", 0) or 0),
                }
            )
        users = []
        try:
            for rec in conn.get_users() or []:
                user_id = str(getattr(rec, "user_id", "") or "").strip()
                if user_id:
                    users.append({"user_id": user_id, "name": str(getattr(rec, "name", "") or "")})
        except Exception as exc:
            print(f"{device['name']}: user list was not read ({exc})", file=sys.stderr)
        return logs, users
    finally:
        conn.disconnect()


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "sync"
    devices = _request("GET", "/api/v1/agent/devices").get("items") or []
    if not devices:
        print("No agent devices are registered.")
        return
    for device in devices:
        print(f"{device['name']} {device['host']}:{device['port']}")
        try:
            logs, users = _pull(device)
        except Exception as exc:
            print(f"  connection failed: {exc}")
            continue
        print(f"  read {len(logs)} logs from the terminal")
        if command == "test":
            continue
        result = _request(
            "POST",
            "/api/v1/agent/import",
            {"device_id": device["id"], "logs": logs, "users": users},
        )
        print(
            f"  {result.get('status')}: inserted {result.get('records_inserted')} "
            f"skipped {result.get('records_skipped')}"
        )


if __name__ == "__main__":
    main()
