"""Behavior added for production use: names, incremental recalculation, scheduling, safety checks."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from test_app import _device, _employee, _ids


def _load(client, auth, device_id, users, logs):
    stored = client.post(
        f"/api/v1/devices/{device_id}/simulator-logs",
        headers=auth,
        json={"users": users, "logs": logs},
    )
    assert stored.status_code == 200, stored.text
    synced = client.post(f"/api/v1/devices/{device_id}/sync?wait=1", headers=auth)
    assert synced.status_code == 200, synced.text
    assert synced.json()["run"]["status"] == "success", synced.text
    return synced.json()["run"]


def test_placeholder_names_are_recognised():
    from app.services.sync import is_placeholder_name

    for name in ("", "NN-435", "nn 7", "User 12", "No Name", "unnamed-3"):
        assert is_placeholder_name(name), name
    for name in ("Ahmed", "Nina", "Noor Hassan", "User Support Lead"):
        assert not is_placeholder_name(name), name


def test_real_name_replaces_placeholder_but_never_a_typed_name(client, auth):
    device = _device(client, auth, name="Kitchen")
    logs = [{"user_id": "435", "punched_at": "2026-10-01T08:00:00", "punch": 0}]
    _load(client, auth, device["id"], [{"user_id": "435", "name": "NN-435"}], logs)
    people = client.get("/api/v1/employees", headers=auth).json()["items"]
    assert next(row for row in people if row["employee_id"] == "435")["full_name"] == "NN-435"

    _load(client, auth, device["id"], [{"user_id": "435", "name": "Mona Said"}], logs)
    people = client.get("/api/v1/employees", headers=auth).json()["items"]
    assert next(row for row in people if row["employee_id"] == "435")["full_name"] == "Mona Said"

    _load(client, auth, device["id"], [{"user_id": "435", "name": "Someone Else"}], logs)
    people = client.get("/api/v1/employees", headers=auth).json()["items"]
    assert next(row for row in people if row["employee_id"] == "435")["full_name"] == "Mona Said"


def test_sync_recalculates_only_people_with_new_punches(client, auth, monkeypatch):
    device = _device(client, auth, name="Gate")
    users = [{"user_id": "1", "name": "Amal Fares"}, {"user_id": "2", "name": "Bassem Nour"}]
    first = [
        {"user_id": "1", "punched_at": "2026-10-01T08:00:00", "punch": 0},
        {"user_id": "1", "punched_at": "2026-10-01T16:00:00", "punch": 1},
        {"user_id": "2", "punched_at": "2026-10-01T08:05:00", "punch": 0},
        {"user_id": "2", "punched_at": "2026-10-01T16:05:00", "punch": 1},
    ]
    _load(client, auth, device["id"], users, first)

    import app.services.sync as sync

    rebuilt: list[set[int]] = []
    original = sync.rebuild_employees

    def spy(db, pks):
        rebuilt.append(set(pks))
        return original(db, pks)

    monkeypatch.setattr(sync, "rebuild_employees", spy)
    second = first + [{"user_id": "1", "punched_at": "2026-10-04T08:00:00", "punch": 0}]
    run = _load(client, auth, device["id"], users, second)
    assert run["records_inserted"] == 1
    assert run["records_skipped"] == 4

    people = {row["employee_id"]: row["id"] for row in client.get("/api/v1/employees", headers=auth).json()["items"]}
    assert rebuilt, "the changed person must be recalculated"
    assert rebuilt[-1] == {people["1"]}

    rebuilt.clear()
    again = _load(client, auth, device["id"], users, second)
    assert again["records_inserted"] == 0
    assert not any(rebuilt), "a sync with nothing new must not recalculate anyone"


def test_failing_terminal_is_retried_slowly():
    from app.services.scheduler import FAILURE_BACKOFF_MINUTES, is_due

    now = datetime(2026, 10, 28, 12, 0, 0)

    def device(**kwargs):
        base = dict(sync_interval_minutes=2, last_sync_at=None, last_test_at=None, last_sync_status="")
        base.update(kwargs)
        return SimpleNamespace(**base)

    assert is_due(device(), now)
    assert not is_due(device(last_sync_at=now - timedelta(minutes=1), last_sync_status="success"), now)
    assert is_due(device(last_sync_at=now - timedelta(minutes=3), last_sync_status="success"), now)
    failed = device(last_sync_at=now - timedelta(days=2), last_test_at=now - timedelta(minutes=3), last_sync_status="error")
    assert not is_due(failed, now), "an attempt three minutes ago must hold back the next retry"
    failed.last_test_at = now - timedelta(minutes=FAILURE_BACKOFF_MINUTES + 1)
    assert is_due(failed, now)


def test_production_refuses_published_defaults(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "espressolab-dev-secret-change-me")
    monkeypatch.setenv("ADMIN_PASSWORD", "ChangeMe-EspressoLab-2026")
    monkeypatch.setenv("ALLOW_SIMULATOR", "1")
    monkeypatch.setenv("FERNET_KEY", "")

    from app.config import production_problems
    from app.main import app, lifespan

    problems = " | ".join(production_problems())
    for needle in ("SECRET_KEY", "FERNET_KEY", "ADMIN_PASSWORD", "ALLOW_SIMULATOR"):
        assert needle in problems

    async def start():
        async with lifespan(app):
            pass

    with pytest.raises(RuntimeError, match="Refusing to start in production"):
        asyncio.run(start())

    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("FERNET_KEY", "k" * 10)
    monkeypatch.setenv("ADMIN_PASSWORD", "a-long-private-passphrase-2026")
    monkeypatch.setenv("ALLOW_SIMULATOR", "0")
    monkeypatch.setenv("CORS_ORIGINS", "https://attendance.example.com")
    assert production_problems() == []


def test_example_password_triggers_the_change_password_banner(monkeypatch):
    from app.config import uses_default_admin_password

    monkeypatch.setenv("ADMIN_PASSWORD", "ChangeMe-EspressoLab-2026")
    assert uses_default_admin_password()
    monkeypatch.setenv("ADMIN_PASSWORD", "something-private-and-long")
    assert not uses_default_admin_password()


def test_security_headers_and_readiness(client):
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "database": "ready"}
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"


def _punches(user_id, *stamps):
    rows = []
    for index, stamp in enumerate(stamps):
        rows.append({"user_id": user_id, "punched_at": stamp, "punch": index % 2})
    return rows


def test_reports_skip_former_staff_and_days_before_the_first_punch(client, auth):
    device = _device(client, auth, name="HQ terminal")
    users = [
        {"user_id": "1", "name": "Active Amal"},
        {"user_id": "2", "name": "Former Fadi"},
        {"user_id": "3", "name": "Late Joiner"},
    ]
    logs = (
        _punches("1", "2026-10-01T08:00:00", "2026-10-01T16:00:00")
        + _punches("2", "2025-01-12T08:00:00", "2025-01-12T16:00:00")
        + _punches("3", "2026-10-20T08:00:00", "2026-10-20T16:00:00")
    )
    _load(client, auth, device["id"], users, logs)

    params = {"start_date": "2026-10-01", "end_date": "2026-10-28", "source": "device", "page_size": 200}
    absent = client.get("/api/v1/attendance", headers=auth, params={**params, "status": "Absent"}).json()
    who = {}
    for row in absent["items"]:
        who.setdefault(row["employee_id"], []).append(row["date_iso"])
    assert "2" not in who, "former staff must not be listed absent for the whole month"
    assert "1" in who and len(who["1"]) >= 15
    assert who["3"] and min(who["3"]) > "2026-10-20", "no absences before the first punch"

    summary = {row["employee_id"] for row in absent["summary"]}
    assert summary == {"1", "3"}

    csv_text = client.get(
        "/api/v1/exports", headers=auth, params={"report": "monthly", "format": "csv", **params}
    ).content.decode("utf-8-sig")
    assert "Active Amal" in csv_text and "Former Fadi" not in csv_text

    asked = client.get("/api/v1/attendance", headers=auth, params={**params, "employee_id": "2", "status": "Absent"}).json()
    assert asked["items"], "asking for one employee by id always reports that employee"

    changed = client.put("/api/v1/settings", headers=auth, json={"dormant_after_days": 0})
    assert changed.status_code == 200, changed.text
    everyone = client.get("/api/v1/attendance", headers=auth, params={**params, "status": "Absent"}).json()
    assert "2" in {row["employee_id"] for row in everyone["items"]}


def test_report_is_ordered_by_name_and_dates_show_the_day(client, auth):
    device = _device(client, auth, name="Order check")
    users = [{"user_id": "10", "name": "Zed Zaki"}, {"user_id": "11", "name": "amal Adel"}]
    logs = []
    for user in ("10", "11"):
        for day in ("2026-10-01", "2026-10-04"):
            logs += _punches(user, f"{day}T08:00:00", f"{day}T16:00:00")
    _load(client, auth, device["id"], users, logs)
    params = {"report": "monthly", "start_date": "2026-10-01", "end_date": "2026-10-04", "source": "device"}

    import csv
    import io

    text = client.get("/api/v1/exports", headers=auth, params={**params, "format": "csv"}).content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))[1:]
    # Friday and Saturday are listed too, as highlighted Weekend rows, in date order inside each name.
    assert [(row[1], row[2], row[6]) for row in rows] == [
        ("amal Adel", "01/10/2026 Thu", "Present"),
        ("amal Adel", "02/10/2026 Fri", "Weekend"),
        ("amal Adel", "03/10/2026 Sat", "Weekend"),
        ("amal Adel", "04/10/2026 Sun", "Present"),
        ("Zed Zaki", "01/10/2026 Thu", "Present"),
        ("Zed Zaki", "02/10/2026 Fri", "Weekend"),
        ("Zed Zaki", "03/10/2026 Sat", "Weekend"),
        ("Zed Zaki", "04/10/2026 Sun", "Present"),
    ]

    listed = client.get("/api/v1/attendance", headers=auth, params={**params, "page_size": 50}).json()["items"]
    assert [(row["name"], row["date"]) for row in listed] == [(row[1], row[2]) for row in rows]


def test_history_exports_use_the_period_not_today(client, auth):
    device = _device(client, auth, name="Old log")
    users = [{"user_id": "9", "name": "Retired Rami"}]
    logs = _punches("9", "2025-05-08T08:00:00", "2025-05-08T16:00:00")
    _load(client, auth, device["id"], users, logs)
    in_period = client.get(
        "/api/v1/attendance",
        headers=auth,
        params={"start_date": "2025-05-01", "end_date": "2025-05-31", "source": "device", "page_size": 200},
    ).json()
    assert "9" in {row["employee_id"] for row in in_period["summary"]}
    today = client.get(
        "/api/v1/attendance",
        headers=auth,
        params={"start_date": "2026-10-01", "end_date": "2026-10-28", "source": "device", "page_size": 200},
    ).json()
    assert "9" not in {row["employee_id"] for row in today["summary"]}


def test_directory_export_honours_the_machine_filter(client, auth):
    hq, day, _night = _ids(client, auth)
    _employee(client, auth, "MANUAL-1", "Typed In", hq, day)
    device = _device(client, auth, name="Gate reader")
    _load(
        client,
        auth,
        device["id"],
        [{"user_id": "77", "name": "Device Ada"}],
        [{"user_id": "77", "punched_at": "2026-10-01T08:00:00", "punch": 0}],
    )
    everyone = client.get("/api/v1/exports/employees", headers=auth, params={"format": "csv"}).content.decode("utf-8-sig")
    assert "Typed In" in everyone and "Device Ada" in everyone
    from_machines = client.get(
        "/api/v1/exports/employees", headers=auth, params={"format": "csv", "source": "device"}
    ).content.decode("utf-8-sig")
    assert "Device Ada" in from_machines
    assert "Typed In" not in from_machines
