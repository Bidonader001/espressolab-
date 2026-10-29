"""Reports follow the branch of the terminal a person punched on."""

from __future__ import annotations

import pytest

from test_app import _device
from test_market_ready import _load

PARAMS = {"report": "monthly", "start_date": "2026-10-01", "end_date": "2026-10-06", "source": "device", "page_size": 200}


def _punches(user, day, device_branch_note=""):
    return [
        {"user_id": user, "punched_at": f"{day}T08:00:00", "punch": 0},
        {"user_id": user, "punched_at": f"{day}T16:00:00", "punch": 1},
    ]


@pytest.fixture()
def world(client, auth):
    kitchen = client.post("/api/v1/branches", headers=auth, json={"name": "Kitchen", "code": "K"}).json()
    hq = next(row for row in client.get("/api/v1/branches", headers=auth).json()["items"] if row["name"] == "HQ")
    hq_device = _device(client, auth, name="HQ door")
    kitchen_device = _device(client, auth, name="Kitchen door", host="kitchen-sim.local")
    assert client.patch(f"/api/v1/devices/{hq_device['id']}", headers=auth, json={"branch_id": hq["id"]}).status_code == 200
    assert client.patch(f"/api/v1/devices/{kitchen_device['id']}", headers=auth, json={"branch_id": kitchen["id"]}).status_code == 200
    # 30 is enrolled on both terminals: one day at HQ, two days in the kitchen. 31 only works in the kitchen, 32 only at HQ.
    _load(
        client, auth, hq_device["id"],
        [{"user_id": "30", "name": "Shared Sam"}, {"user_id": "32", "name": "Hana HQ"}],
        _punches("30", "2026-10-01") + _punches("32", "2026-10-01"),
    )
    _load(
        client, auth, kitchen_device["id"],
        [{"user_id": "30", "name": "Shared Sam"}, {"user_id": "31", "name": "Kay Kitchen"}],
        _punches("30", "2026-10-05") + _punches("30", "2026-10-06") + _punches("31", "2026-10-01"),
    )
    return {"kitchen": kitchen, "hq": hq, "kitchen_device": kitchen_device}


def _rows(client, auth, **extra):
    body = client.get("/api/v1/attendance", headers=auth, params={**PARAMS, **extra}).json()
    out: dict[str, dict[str, dict]] = {}
    for row in body["items"]:
        out.setdefault(row["employee_id"], {})[row["date_iso"]] = row
    return out, body["summary"]


def test_each_day_shows_the_branch_of_the_terminal_it_was_punched_on(client, auth, world):
    rows, summary = _rows(client, auth)
    sam = rows["30"]
    assert sam["2026-10-01"]["branch"] == "HQ"
    assert sam["2026-10-05"]["branch"] == "Kitchen" and sam["2026-10-06"]["branch"] == "Kitchen"
    assert rows["31"]["2026-10-01"]["branch"] == "Kitchen"
    assert rows["32"]["2026-10-01"]["branch"] == "HQ"
    # Sam spent most days in the kitchen, so the summary and the days without punches use the kitchen.
    assert next(row for row in summary if row["employee_id"] == "30")["branch"] == "Kitchen"
    assert sam["2026-10-04"]["status"] == "Absent" and sam["2026-10-04"]["branch"] == "Kitchen"


def test_kitchen_filter_lists_only_kitchen_work_and_never_calls_other_branch_days_absent(client, auth, world):
    rows, summary = _rows(client, auth, branch="Kitchen")
    assert set(rows) == {"30", "31"}
    sam = rows["30"]
    assert {day for day, row in sam.items() if row["status"] not in {"Absent", "Weekend"}} == {"2026-10-05", "2026-10-06"}
    # 10/01 was worked at HQ: it is not listed here and it is not an absence either.
    assert "2026-10-01" not in sam
    assert sam["2026-10-04"]["status"] == "Absent"
    assert next(row for row in summary if row["employee_id"] == "30")["absences"] == 1
    assert all(row["branch"] == "Kitchen" for person in rows.values() for row in person.values())


def test_hq_filter_lists_hq_work_only(client, auth, world):
    rows, summary = _rows(client, auth, branch="HQ")
    assert set(rows) == {"30", "32"}
    assert set(rows["30"]) == {"2026-10-01"}
    # Sam's home is the kitchen, so HQ does not blame Sam for the other days.
    assert next(row for row in summary if row["employee_id"] == "30")["absences"] == 0
    assert rows["32"]["2026-10-04"]["status"] == "Absent"


def test_exports_and_changing_a_terminals_branch_apply_without_recalculating(client, auth, world):
    csv_kitchen = client.get("/api/v1/exports", headers=auth, params={**PARAMS, "format": "csv", "branch": "Kitchen"})
    assert csv_kitchen.status_code == 200
    assert b"Kay Kitchen" in csv_kitchen.content and b"Hana HQ" not in csv_kitchen.content
    moved = client.patch(
        f"/api/v1/devices/{world['kitchen_device']['id']}", headers=auth, json={"branch_id": world["hq"]["id"]}
    )
    assert moved.status_code == 200
    rows, _summary = _rows(client, auth)
    assert rows["31"]["2026-10-01"]["branch"] == "HQ"
    assert _rows(client, auth, branch="Kitchen")[0] == {}


def _shift(client, auth, branch_id, name="Early", start="06:00", end="14:00"):
    response = client.post("/api/v1/shifts", headers=auth, json={"name": name, "start_time": start, "end_time": end, "branch_id": branch_id})
    assert response.status_code == 200, response.text
    return response.json()


def _branch_body(branch, **extra):
    body = {key: branch[key] for key in ("name", "code", "timezone", "address", "working_days", "grace_minutes", "default_shift_id", "work_start", "work_end")}
    return {**body, **extra}


def test_working_days_are_validated_not_silently_ignored(client, auth):
    made = client.post("/api/v1/branches", headers=auth, json={"name": "Days", "working_days": "Sun,Mon,Tue,Wed,Thu"})
    assert made.status_code == 200 and made.json()["working_days"] == "Sun,Mon,Tue,Wed,Thu"
    assert client.post("/api/v1/branches", headers=auth, json={"name": "Range", "working_days": "Sat-Wed"}).status_code == 200
    assert client.post("/api/v1/branches", headers=auth, json={"name": "Default", "working_days": ""}).status_code == 200
    bad = client.post("/api/v1/branches", headers=auth, json={"name": "Oops", "working_days": "Someday"})
    assert bad.status_code == 422


def test_branch_default_shift_decides_lateness_for_people_without_their_own_shift(client, auth):
    kitchen = client.post("/api/v1/branches", headers=auth, json={"name": "Bakery", "code": "B"}).json()
    other = client.post("/api/v1/branches", headers=auth, json={"name": "Cafe"}).json()
    early = _shift(client, auth, kitchen["id"])
    foreign = _shift(client, auth, other["id"], name="Cafe late", start="12:00", end="20:00")
    device = _device(client, auth, name="Bakery door")
    assert client.patch(f"/api/v1/devices/{device['id']}", headers=auth, json={"branch_id": kitchen["id"]}).status_code == 200
    _load(
        client, auth, device["id"],
        [{"user_id": "70", "name": "Bea Baker"}],
        [{"user_id": "70", "punched_at": "2026-10-05T06:30:00", "punch": 0}, {"user_id": "70", "punched_at": "2026-10-05T14:00:00", "punch": 1}],
    )

    def day():
        params = {"report": "monthly", "start_date": "2026-10-05", "end_date": "2026-10-05", "source": "device"}
        rows = client.get("/api/v1/attendance", headers=auth, params=params).json()["items"]
        return next(row for row in rows if row["employee_id"] == "70" and row["date_iso"] == "2026-10-05")

    # No default yet: the company hours (08:00) apply, so 06:30 is on time.
    assert day()["late_minutes"] == 0 and day()["status"] == "Present"

    current = next(row for row in client.get("/api/v1/branches", headers=auth).json()["items"] if row["id"] == kitchen["id"])
    # A shift that belongs to another branch cannot be this branch's default.
    refused = client.patch(f"/api/v1/branches/{kitchen['id']}", headers=auth, json=_branch_body(current, default_shift_id=foreign["id"]))
    assert refused.status_code == 400
    ok = client.patch(f"/api/v1/branches/{kitchen['id']}", headers=auth, json=_branch_body(current, default_shift_id=early["id"]))
    assert ok.status_code == 200 and ok.json()["default_shift_id"] == early["id"]
    # The branch's early shift now applies: 06:30 is 30 minutes after a 06:00 start.
    assert day()["late_minutes"] == 30 and day()["status"] == "Late" and day()["shift"] == "Early"

    # Editing the shift recalculates the people on it.
    changed = client.patch(
        f"/api/v1/shifts/{early['id']}", headers=auth,
        json={"name": "Early", "start_time": "06:30", "end_time": "14:00", "branch_id": kitchen["id"]},
    )
    assert changed.status_code == 200
    assert day()["late_minutes"] == 0 and day()["status"] == "Present"

    # A branch with shifts cannot be deleted until they are gone, and deleting the default shift clears it.
    assert client.delete(f"/api/v1/branches/{kitchen['id']}", headers=auth).status_code in {409}
    assert client.delete(f"/api/v1/shifts/{early['id']}", headers=auth).status_code == 200
    after = next(row for row in client.get("/api/v1/branches", headers=auth).json()["items"] if row["id"] == kitchen["id"])
    assert after["default_shift_id"] is None
    assert day()["shift"] in {"Day", ""} and day()["late_minutes"] == 0


def test_branch_working_hours_apply_to_people_without_a_shift_and_are_validated(client, auth):
    branch = client.post("/api/v1/branches", headers=auth, json={"name": "Dawn", "work_start": "06:00", "work_end": "14:00"})
    assert branch.status_code == 200, branch.text
    assert branch.json()["work_start"] == "06:00" and branch.json()["work_end"] == "14:00"
    # Both or neither, and a real time.
    assert client.post("/api/v1/branches", headers=auth, json={"name": "Half", "work_start": "06:00"}).status_code == 422
    assert client.post("/api/v1/branches", headers=auth, json={"name": "Bad", "work_start": "25:00", "work_end": "14:00"}).status_code == 422
    assert client.post("/api/v1/branches", headers=auth, json={"name": "Same", "work_start": "08:00", "work_end": "08:00"}).status_code == 422

    device = _device(client, auth, name="Dawn door")
    assert client.patch(f"/api/v1/devices/{device['id']}", headers=auth, json={"branch_id": branch.json()["id"]}).status_code == 200
    _load(
        client, auth, device["id"],
        [{"user_id": "80", "name": "Dan Dawn"}],
        [{"user_id": "80", "punched_at": "2026-10-05T06:30:00", "punch": 0}, {"user_id": "80", "punched_at": "2026-10-05T14:00:00", "punch": 1}],
    )

    def day():
        params = {"report": "monthly", "start_date": "2026-10-05", "end_date": "2026-10-05", "source": "device"}
        rows = client.get("/api/v1/attendance", headers=auth, params=params).json()["items"]
        return next(row for row in rows if row["employee_id"] == "80" and row["date_iso"] == "2026-10-05")

    # The branch's own hours decide lateness: 06:30 is 30 minutes after a 06:00 start.
    assert day()["late_minutes"] == 30 and day()["status"] == "Late" and day()["shift"] == "Branch hours"

    # Changing the hours recalculates; clearing them returns to the company hours (08:00), so 06:30 is on time.
    current = next(row for row in client.get("/api/v1/branches", headers=auth).json()["items"] if row["id"] == branch.json()["id"])
    moved = client.patch(f"/api/v1/branches/{current['id']}", headers=auth, json=_branch_body(current, work_start="06:30", work_end="14:30"))
    assert moved.status_code == 200 and day()["late_minutes"] == 0
    cleared = client.patch(f"/api/v1/branches/{current['id']}", headers=auth, json=_branch_body(current, work_start="", work_end=""))
    assert cleared.status_code == 200 and cleared.json()["work_start"] == "" and day()["late_minutes"] == 0 and day()["shift"] != "Branch hours"

    # A default shift beats the branch hours.
    shift = _shift(client, auth, current["id"], name="Late", start="05:00", end="13:00")
    current = next(row for row in client.get("/api/v1/branches", headers=auth).json()["items"] if row["id"] == current["id"])
    both = client.patch(
        f"/api/v1/branches/{current['id']}", headers=auth,
        json=_branch_body(current, work_start="06:00", work_end="14:00", default_shift_id=shift["id"]),
    )
    assert both.status_code == 200 and day()["shift"] == "Late" and day()["late_minutes"] == 90
