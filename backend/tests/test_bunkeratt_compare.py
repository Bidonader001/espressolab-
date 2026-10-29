"""Compare attendance rows with BunkerAtt's export function on the same sessions.

Salary columns and the face-enrollment column are intentionally absent.
"""

from __future__ import annotations

import csv
import io
import pickle
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from openpyxl import load_workbook

BUNKER = Path(__file__).resolve().parents[3] / "bunkeratt"
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


# Rows this app adds on top of BunkerAtt: days off and working days with no punch at all.
EXTRA = {"Weekend", "Absent"}


def _minutes(decimal_hours) -> int:
    return round(float(decimal_hours) * 60)


def _our_layout(reference_rows, workbook=False):
    """BunkerAtt rows (Employee ID, Name, dd/mm/yyyy, ...) shown the way this app shows them.

    Rows are ordered by name then date, the date gains its day name, and hours are shown as
    hours:minutes (7:43) instead of a decimal (7.72). In a workbook the hours become a real duration.
    Nothing else changes.
    """
    def day(text):
        return datetime.strptime(text, "%d/%m/%Y")

    ordered = sorted(reference_rows, key=lambda row: (row[1].lower(), row[0], day(row[2]).date()))
    out = []
    for row in ordered:
        row = list(row)
        row[2] = f"{row[2]} {DAY_NAMES[day(row[2]).weekday()]}"
        if row[5] not in (None, ""):
            minutes = _minutes(row[5])
            row[5] = timedelta(minutes=minutes) if workbook else f"{minutes // 60}:{minutes % 60:02d}"
        elif workbook:
            row[5] = None
        if row[6] == "Incomplete":
            row[4] = "No check-out"  # a check-in without a check-out is spelled out, never left blank
        out.append(row)
    return out


def _install_numpy_stub() -> None:
    if "numpy" in sys.modules:
        return
    try:
        import numpy  # noqa: F401
    except Exception:
        sys.modules["numpy"] = types.ModuleType("numpy")


def _hours(clock_in: str, clock_out: str) -> float:
    start = datetime.fromisoformat(clock_in)
    end = datetime.fromisoformat(clock_out)
    return round((end - start).total_seconds() / 3600.0, 4)


def test_detail_rows_match_bunkeratt(client, auth, tmp_path, monkeypatch):
    if not (BUNKER / "core" / "exports.py").is_file():
        pytest.skip("BunkerAtt project is not beside this workspace")
    _install_numpy_stub()
    monkeypatch.setenv("BUNKERATT_DB", str(tmp_path / "bunker.db"))
    sys.path.insert(0, str(BUNKER))
    from core import db as bunker_db
    from core.exports import build as bunker_build
    from core.exports import collect as bunker_collect

    bunker_db.init_db()
    with bunker_db.get_connection() as conn:
        conn.execute(
            "INSERT INTO gym_settings (key, value) VALUES ('grace_minutes', '10') ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        )
        conn.execute(
            "INSERT INTO gym_settings (key, value) VALUES ('working_days', 'Sun-Thu') ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        )
        conn.execute(
            "INSERT INTO gym_settings (key, value) VALUES ('company_name', 'Bunker Attendance') ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        )
        blob = pickle.dumps(b"")

        def person(eid, name, branch="HQ", department="Ops", status="active"):
            conn.execute(
                "INSERT INTO employees (employee_id, name, embedding, created_at, branch, department, employment_status, has_face) VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
                (eid, name, blob, "2026-01-01T00:00:00", branch, department, status),
            )

        def session(eid, name, work_date, clock_in, clock_out=None, minutes_late=0, shift_name="Day"):
            hours = _hours(clock_in, clock_out) if clock_out else None
            conn.execute(
                """
                INSERT INTO work_sessions
                    (employee_id, employee_name, work_date, clock_in, clock_out, hours, confidence,
                     created_at, shift_name, late, minutes_late)
                VALUES (?, ?, ?, ?, ?, ?, 0.99, ?, ?, ?, ?)
                """,
                (eid, name, work_date, clock_in, clock_out, hours, clock_in, shift_name, 1 if minutes_late else 0, minutes_late),
            )

        person("EMP-001", "Ahmed Mohamed")
        person("EMP-002", "Mariam Ali")
        person("EMP-003", "=2+2")
        person("EMP-004", "Inactive Person", status="inactive")
        person("EMP-005", "Other Branch", branch="Jeddah", department="Sales")
        person("EMP-006", "Ù…Ø±ÙŠÙ… Ø¹Ù„ÙŠ")
        session("EMP-001", "Ahmed Mohamed", "2026-10-01", "2026-10-01T08:55:00", "2026-10-01T17:02:00")
        session("EMP-002", "Mariam Ali", "2026-10-01", "2026-10-01T09:18:00", "2026-10-01T17:10:00", minutes_late=18)
        session("EMP-003", "=2+2", "2026-10-01", "2026-10-01T08:00:00", "2026-10-01T16:00:00")
        session("EMP-006", "Ù…Ø±ÙŠÙ… Ø¹Ù„ÙŠ", "2026-10-01", "2026-10-01T09:00:00", "2026-10-01T17:00:00")
        session("EMP-005", "Other Branch", "2026-10-01", "2026-10-01T08:00:00", "2026-10-01T16:00:00")
        session("EMP-001", "Ahmed Mohamed", "2026-10-02", "2026-10-02T10:00:00", "2026-10-02T14:00:00")
        session("EMP-001", "Ahmed Mohamed", "2026-10-04", "2026-10-04T20:00:00", "2026-10-05T04:00:00", shift_name="Night")
        session("EMP-001", "Ahmed Mohamed", "2026-10-05", "2026-10-05T08:00:00")
        session("EMP-001", "Ahmed Mohamed", "2026-10-06", "2026-10-06T08:00:00", "2026-10-06T12:00:00")
        session("EMP-001", "Ahmed Mohamed", "2026-10-06", "2026-10-06T13:00:00", "2026-10-06T17:00:00")

    params = {
        "report": "monthly",
        "format": "csv",
        "start_date": "2026-10-01",
        "end_date": "2026-10-06",
        "branch": "HQ",
    }
    reference = bunker_collect(params)
    ref_csv, ref_name, _media = bunker_build(params, "tester")

    from app.database import get_session
    from app.models import AttendanceSession, Branch, Employee

    db = get_session()
    try:
        hq = db.query(Branch).filter(Branch.name == "HQ").one()
        jeddah = Branch(name="Jeddah", code="JED", timezone="Asia/Riyadh")
        db.add(jeddah)
        db.flush()
        people = {
            "EMP-001": ("Ahmed Mohamed", hq.id, "Ops", "active"),
            "EMP-002": ("Mariam Ali", hq.id, "Ops", "active"),
            "EMP-003": ("=2+2", hq.id, "Ops", "active"),
            "EMP-004": ("Inactive Person", hq.id, "Ops", "inactive"),
            "EMP-005": ("Other Branch", jeddah.id, "Sales", "active"),
            "EMP-006": ("Ù…Ø±ÙŠÙ… Ø¹Ù„ÙŠ", hq.id, "Ops", "active"),
        }
        pk = {}
        for eid, (name, branch_id, department, status) in people.items():
            row = Employee(
                employee_id=eid,
                full_name=name,
                department=department,
                branch_id=branch_id,
                employment_status=status,
            )
            db.add(row)
            db.flush()
            pk[eid] = row.id

        def add_session(eid, work_date, clock_in, clock_out=None, minutes_late=0, shift_name="Day"):
            db.add(
                AttendanceSession(
                    employee_pk=pk[eid],
                    work_date=work_date,
                    clock_in=datetime.fromisoformat(clock_in),
                    clock_out=datetime.fromisoformat(clock_out) if clock_out else None,
                    hours=_hours(clock_in, clock_out) if clock_out else None,
                    minutes_late=minutes_late,
                    shift_name=shift_name,
                    device_name="",
                )
            )

        add_session("EMP-001", "2026-10-01", "2026-10-01T08:55:00", "2026-10-01T17:02:00")
        add_session("EMP-002", "2026-10-01", "2026-10-01T09:18:00", "2026-10-01T17:10:00", minutes_late=18)
        add_session("EMP-003", "2026-10-01", "2026-10-01T08:00:00", "2026-10-01T16:00:00")
        add_session("EMP-006", "2026-10-01", "2026-10-01T09:00:00", "2026-10-01T17:00:00")
        add_session("EMP-005", "2026-10-01", "2026-10-01T08:00:00", "2026-10-01T16:00:00")
        add_session("EMP-001", "2026-10-02", "2026-10-02T10:00:00", "2026-10-02T14:00:00")
        add_session("EMP-001", "2026-10-04", "2026-10-04T20:00:00", "2026-10-05T04:00:00", shift_name="Night")
        add_session("EMP-001", "2026-10-05", "2026-10-05T08:00:00")
        add_session("EMP-001", "2026-10-06", "2026-10-06T08:00:00", "2026-10-06T12:00:00")
        add_session("EMP-001", "2026-10-06", "2026-10-06T13:00:00", "2026-10-06T17:00:00")
        db.commit()
    finally:
        db.close()

    ours = client.get("/api/v1/exports", headers=auth, params=params)
    assert ours.status_code == 200, ours.text
    # CSV has no banner, so the attendance rows can be compared directly. Two layout choices differ
    # from BunkerAtt on purpose: rows are ordered by name then date, and dates carry the day name.
    # Apply those two choices to BunkerAtt's output, then every cell must still be identical.
    ref_table = list(csv.reader(io.StringIO(ref_csv.decode("utf-8-sig"))))
    our_table = list(csv.reader(io.StringIO(ours.content.decode("utf-8-sig"))))
    assert our_table[0] == ref_table[0]
    # This app also lists Friday and Saturday as highlighted "Weekend" rows. BunkerAtt has none, so set
    # them aside, check they exist, and compare everything else cell for cell.
    absent = [row for row in our_table[1:] if row[6] == "Absent"]
    assert absent and all(not row[3] and not row[4] and not row[5] for row in absent)
    weekend = [row for row in our_table[1:] if row[6] == "Weekend"]
    assert weekend and all(row[2].split()[-1] in {"Fri", "Sat"} for row in weekend)
    assert [row for row in our_table[1:] if row[6] not in EXTRA] == _our_layout(ref_table[1:])
    assert ref_name.startswith("BunkerAttendance_")
    assert "EspressoLabAttendance_Attendance_2026-10.csv" in ours.headers["content-disposition"]
    assert any(row[2] == "01/10/2026 Thu" for row in our_table[1:])
    names = [(row[1].lower(), row[0]) for row in our_table[1:] if row[6] not in EXTRA]
    assert names == sorted(names)

    def whole_minutes(hours):
        return None if hours is None else round(_minutes(hours) / 60, 2)

    ref_fields = [
        (row["employee_id"], row["date_iso"], row["check_in"], row["check_out"], whole_minutes(row["hours"]), row["status"])
        for row in sorted(reference["details"], key=lambda r: (r["name"].lower(), r["employee_id"], r["date_iso"]))
    ]
    from app.database import get_session as session_factory
    from app.exports import collect as our_collect
    from app.services.attendance import load_bundle

    db = session_factory()
    try:
        data = our_collect(params, load_bundle(db, date_from="2026-10-01", date_to="2026-10-06"))
    finally:
        db.close()
    our_fields = [(row["employee_id"], row["date_iso"], row["check_in"], row["check_out"], row["hours"], row["status"]) for row in data["details"] if row["status"] not in EXTRA]
    assert our_fields == ref_fields
    ref_summary = [(row["employee_id"], row["days_present"], row["late_arrivals"], row["absences"]) for row in reference["summary"]]
    our_summary = [(row["employee_id"], row["days_present"], row["late_arrivals"], row["absences"]) for row in data["summary"]]
    assert our_summary == ref_summary
    for ours_row, ref_row in zip(data["summary"], reference["summary"]):
        assert ours_row["total_minutes"] == sum(
            _minutes(item["hours"]) for item in reference["details"] if item["employee_id"] == ref_row["employee_id"] and item["hours"] is not None
        )

    ref_xlsx, _name, _media = bunker_build({**params, "format": "xlsx"}, "tester")
    our_xlsx = client.get("/api/v1/exports", headers=auth, params={**params, "format": "xlsx"})
    ref_book = load_workbook(io.BytesIO(ref_xlsx))
    our_book = load_workbook(io.BytesIO(our_xlsx.content))
    ref_sheet = ref_book["Attendance Details"]
    our_sheet = our_book["Attendance Details"]
    assert [our_sheet.cell(8, col).value for col in range(1, 8)] == [ref_sheet.cell(8, col).value for col in range(1, 8)]
    ref_rows = [list(row) for row in ref_sheet.iter_rows(min_row=9, max_col=7, values_only=True)]
    our_rows = [list(row) for row in our_sheet.iter_rows(min_row=9, max_col=7, values_only=True)]
    assert [row for row in our_rows if row[6] not in EXTRA] == _our_layout(ref_rows, workbook=True)
    # BunkerAtt's summary continues into salary. Those two columns are omitted here. This app adds
    # an "Incomplete days" column before the hours total and shows the total as a duration.
    assert [ref_book["Employee Summary"].cell(8, col).value for col in range(6, 8)] == ["Base salary", "Net pay"]
    assert [our_book["Employee Summary"].cell(8, col).value for col in range(5, 7)] == ["Incomplete days", "Total hours"]
    assert our_book["Employee Summary"].cell(8, 7).value is None
    ref_sum_rows = list(ref_book["Employee Summary"].iter_rows(min_row=9, max_col=5, values_only=True))
    our_sum_rows = list(our_book["Employee Summary"].iter_rows(min_row=9, max_col=6, values_only=True))
    assert len(our_sum_rows) == len(ref_sum_rows)
    for ours_row, ref_row in zip(our_sum_rows, ref_sum_rows):
        assert list(ours_row[:4]) == list(ref_row[:4])
        assert isinstance(ours_row[5], timedelta)
        if ref_row[0] != "Total":
            assert abs(ours_row[5].total_seconds() / 3600 - float(ref_row[4])) <= 0.02
