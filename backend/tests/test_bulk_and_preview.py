"""Bulk active/inactive on employees, and the report preview that shows what a download would contain."""

from __future__ import annotations

import csv
import io

from test_app import _device, _employee, _ids
from test_market_ready import _load


def _count(client, auth, **extra):
    response = client.get("/api/v1/exports/count", headers=auth, params={"report": "employees", **extra})
    assert response.status_code == 200, response.text
    return response.json()["count"]


def test_select_employees_and_make_them_inactive_then_active(client, auth):
    hq, day, _night = _ids(client, auth)
    for number, name in (("B1", "Ada Bulk"), ("B2", "Bea Bulk"), ("B3", "Cara Bulk"), ("Z9", "Zed Other")):
        _employee(client, auth, number, name, hq, day)
    before = _count(client, auth)

    done = client.post("/api/v1/employees/bulk-status", headers=auth, json={"status": "inactive", "employee_ids": ["B1", "B2"]})
    assert done.status_code == 200, done.text
    assert done.json() == {"selected": 2, "changed": 2, "status": "inactive"}
    listed = client.get("/api/v1/employees", headers=auth, params={"status": "inactive", "page_size": 200}).json()["items"]
    assert {row["employee_id"] for row in listed} == {"B1", "B2"}
    # Inactive people leave the reports until they are asked for.
    assert _count(client, auth) == before - 2
    assert _count(client, auth, include_inactive="1") == before

    # Repeating the change is harmless and reports that nothing changed.
    again = client.post("/api/v1/employees/bulk-status", headers=auth, json={"status": "inactive", "employee_ids": ["B1"]})
    assert again.json()["selected"] == 1 and again.json()["changed"] == 0

    back = client.post("/api/v1/employees/bulk-status", headers=auth, json={"status": "active", "employee_ids": ["B1", "B2"]})
    assert back.json()["changed"] == 2
    assert _count(client, auth) == before


def test_bulk_status_can_target_everything_matching_a_search_and_rejects_bad_input(client, auth):
    hq, day, _night = _ids(client, auth)
    for number, name in (("M1", "Match One"), ("M2", "Match Two"), ("N1", "Keep Me")):
        _employee(client, auth, number, name, hq, day)
    done = client.post("/api/v1/employees/bulk-status", headers=auth, json={"status": "inactive", "match": {"q": "Match"}})
    assert done.json()["selected"] == 2 and done.json()["changed"] == 2
    still = client.get("/api/v1/employees", headers=auth, params={"q": "Keep", "page_size": 200}).json()["items"]
    assert still and still[0]["employment_status"] == "active"

    assert client.post("/api/v1/employees/bulk-status", headers=auth, json={"status": "inactive", "employee_ids": []}).status_code == 400
    assert client.post("/api/v1/employees/bulk-status", headers=auth, json={"status": "banned", "employee_ids": ["M1"]}).status_code == 422
    missing = client.post("/api/v1/employees/bulk-status", headers=auth, json={"status": "active", "employee_ids": ["M1", "NOPE"]})
    assert missing.status_code == 404 and "NOPE" in missing.json()["detail"]
    # A rejected request changes nothing.
    assert client.get("/api/v1/employees/M1", headers=auth).json()["employment_status"] == "inactive"
    assert client.post("/api/v1/employees/bulk-status", json={"status": "active", "employee_ids": ["M1"]}).status_code == 401


PARAMS = {"report": "monthly", "start_date": "2026-10-01", "end_date": "2026-10-04", "source": "device"}


def _load_person(client, auth):
    device = _device(client, auth, name="HQ")
    logs = [
        {"user_id": "50", "punched_at": "2026-10-01T09:00:00", "punch": 0},  # check-in only: Incomplete
        {"user_id": "50", "punched_at": "2026-10-03T09:00:00", "punch": 0},  # Saturday, worked
        {"user_id": "50", "punched_at": "2026-10-03T17:00:00", "punch": 1},
    ]
    _load(client, auth, device["id"], [{"user_id": "50", "name": "Pia Preview"}], logs)


def test_preview_matches_the_csv_download_cell_for_cell(client, auth):
    _load_person(client, auth)
    preview = client.get("/api/v1/exports/preview", headers=auth, params={**PARAMS, "page_size": 500})
    assert preview.status_code == 200, preview.text
    body = preview.json()
    csv_text = client.get("/api/v1/exports", headers=auth, params={**PARAMS, "format": "csv"}).content.decode("utf-8-sig")
    table = list(csv.reader(io.StringIO(csv_text)))
    assert body["columns"] == table[0]
    assert [line["cells"] for line in body["rows"]] == [[str(cell) for cell in row] for row in table[1:]]
    assert body["count"] == len(table) - 1
    by_date = {line["cells"][2][:10]: line for line in body["rows"]}
    thursday = by_date["01/10/2026"]
    assert thursday["status"] == "Incomplete" and thursday["cells"][4] == "No check-out" and thursday["cells"][5] == ""
    assert by_date["02/10/2026"]["status"] == "Weekend"
    assert by_date["03/10/2026"]["cells"][5] == "8:00"
    # Totals shown with the preview follow the same rules as the files: Incomplete adds nothing.
    assert body["total_hours"] == "8:00" and body["incomplete_days"] == 1
    assert body["start"] == "2026-10-01" and body["end"] == "2026-10-04" and "check-out minus check-in" in body["hours_note"]
    assert any(item["employee"] == "Pia Preview" and item["total_text"] == "8:00" for item in body["summary"])


def test_preview_pages_follow_filters_and_report_the_same_errors_as_downloads(client, auth):
    _load_person(client, auth)
    first = client.get("/api/v1/exports/preview", headers=auth, params={**PARAMS, "page_size": 2}).json()
    second = client.get("/api/v1/exports/preview", headers=auth, params={**PARAMS, "page_size": 2, "page": 2}).json()
    assert len(first["rows"]) == 2 and first["count"] == 4 and second["rows"] and first["rows"] != second["rows"]
    only = client.get("/api/v1/exports/preview", headers=auth, params={**PARAMS, "status": "Incomplete"}).json()
    assert [line["status"] for line in only["rows"]] == ["Incomplete"]
    people = client.get("/api/v1/exports/preview", headers=auth, params={"report": "employees"}).json()
    assert people["columns"][:2] == ["Employee ID", "Name"] and people["rows"] and people["summary"] == []
    bad = client.get("/api/v1/exports/preview", headers=auth, params={**PARAMS, "end_date": "2020-01-01"})
    assert bad.status_code == 400
    assert client.get("/api/v1/exports/preview", params=PARAMS).status_code == 401
