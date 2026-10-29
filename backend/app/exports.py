"""Attendance exports ported from BunkerAtt.

Payroll columns and face-enrollment are omitted. Layout, status labels, date
formats, and the hours calculation match the reference reports.
"""

from __future__ import annotations

import csv
import io
import os
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.page import PageMargins
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.branding import add_excel_logo, pdf_logo
from app.time_utils import hours_between, parse_working_days

MAX_DAYS = 366
MAX_ROWS = 50_000
REPORT_TYPES = ("daily", "monthly", "employees", "late", "absences", "hours")
FORMATS = ("xlsx", "csv", "pdf")
DETAIL_DEFAULT = ["employee_id", "name", "date", "check_in", "check_out", "hours", "status"]
DETAIL_ALL = DETAIL_DEFAULT + ["shift", "department", "branch", "late_minutes", "device"]
DIRECTORY_DEFAULT = ["employee_id", "name", "email", "department", "branch", "shift", "status"]
DIRECTORY_ALL = DIRECTORY_DEFAULT + ["phone", "job_title", "joining_date"]
SUMMARY_HEADERS = ["Employee", "Days present", "Late arrivals", "Absences", "Incomplete days", "Total hours"]
NO_CHECKOUT = "No check-out"
HOURS_NOTE = (
    "Working time is check-out minus check-in, shown as hours:minutes (7:43 is 7 hours 43 minutes). "
    "Incomplete days have no check-out and no hours."
)

INK = PatternFill("solid", fgColor="001F3F")
CREAM = PatternFill("solid", fgColor="FFFFFF")
GREEN = PatternFill("solid", fgColor="C6F4D6")
LATE = PatternFill("solid", fgColor="FCE4C4")
RED = PatternFill("solid", fgColor="FFC7C7")
PURPLE = PatternFill("solid", fgColor="E3D0F2")
INCOMPLETE = PatternFill("solid", fgColor="FFE08A")  # check-in without check-out
WEEKEND = PatternFill("solid", fgColor="D6E4F5")  # days off (Friday and Saturday by default)
INCOMPLETE_FONT = Font(bold=True, color="7A4B00", name="Calibri")
ZEBRA = PatternFill("solid", fgColor="F4F5EE")
HEAD_FONT = Font(bold=True, color="FFFFFF", name="Calibri")
TITLE_FONT = Font(bold=True, color="001F3F", size=16, name="Calibri")
THIN = Border(
    left=Side(style="thin", color="DDDDDD"),
    right=Side(style="thin", color="DDDDDD"),
    top=Side(style="thin", color="DDDDDD"),
    bottom=Side(style="thin", color="DDDDDD"),
)
PDF_INK = colors.HexColor("#001F3F")
PDF_CREAM = colors.HexColor("#FFFFFF")
PDF_GREEN = colors.HexColor("#C6F4D6")
PDF_LATE = colors.HexColor("#FCE4C4")
PDF_RED = colors.HexColor("#FFC7C7")
PDF_PURPLE = colors.HexColor("#E3D0F2")
PDF_INCOMPLETE = colors.HexColor("#FFE08A")
PDF_WEEKEND = colors.HexColor("#D6E4F5")
_FONT_REGISTERED = False


class ExportError(ValueError):
    pass


def _dec(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _hours_out(value: float | None) -> float | None:
    parsed = _dec(value)
    return float(parsed) if parsed is not None else None


def csv_safe(value) -> str:
    text = "" if value is None else str(value)
    if text[:1] in {"=", "+", "-", "@", "\t", "\r"}:
        return "'" + text
    return text


def _status_wanted(label: str, status_filter: str) -> bool:
    if not (status_filter or "").strip():
        return True
    want = status_filter.strip().lower()
    if want in {"missing check-out", "missing checkout", "incomplete"}:
        return label.lower() == "incomplete"
    if want in {"on leave", "leave"}:
        return label.lower() == "on leave"
    return label.lower() == want


def _session_minutes(session: dict) -> int | None:
    """Check-out minus check-in, in whole minutes (30 seconds and over round up)."""
    if not session.get("clock_out"):
        return None
    try:
        start = datetime.fromisoformat(str(session["clock_in"]))
        end = datetime.fromisoformat(str(session["clock_out"]))
        seconds = Decimal(str(max(0.0, (end - start).total_seconds())))
    except (TypeError, ValueError, KeyError):
        if session.get("hours") is None:
            return None
        seconds = Decimal(str(float(session["hours"]))) * 3600
    return int((seconds / 60).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def minutes_text(minutes: int | None) -> str:
    """7:43 means 7 hours 43 minutes."""
    if minutes is None:
        return ""
    return f"{minutes // 60}:{minutes % 60:02d}"


def _dates_between(start: date, end: date) -> list[date]:
    days = []
    cursor = start
    while cursor <= end:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _parse_day(value: str, fallback: date) -> date:
    text = (value or "").strip()
    if not text:
        return fallback
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise ExportError("Dates must be YYYY-MM-DD.") from exc


def validate_range(start_date: str, end_date: str) -> tuple[date, date]:
    today = date.today()
    start = _parse_day(start_date, today)
    end = _parse_day(end_date, today)
    if end < start:
        raise ExportError("End date must be on or after the start date.")
    if (end - start).days + 1 > MAX_DAYS:
        raise ExportError(f"Date range cannot exceed {MAX_DAYS} days.")
    return start, end


WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _fmt_date(iso: str) -> str:
    """28/10/2026 Wed. The day name is fixed English text so it never depends on the server locale."""
    try:
        day = date.fromisoformat(str(iso)[:10])
    except ValueError:
        return str(iso or "")
    return f"{day.strftime('%d/%m/%Y')} {WEEKDAY_NAMES[day.weekday()]}"


def _by_name_then_date(row: dict) -> tuple:
    return ((row.get("name") or "").lower(), row.get("employee_id") or "", row.get("date_iso") or "")


def _fmt_time(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(str(iso)).strftime("%H:%M")
    except ValueError:
        return str(iso)


def _filter_people(people, *, branch="", department="", employee_id="", include_inactive=False) -> list[dict]:
    out = []
    for person in people:
        status = (person.get("employment_status") or "active").lower()
        if not include_inactive and status == "inactive":
            continue
        if employee_id and person.get("employee_id") != employee_id:
            continue
        if branch and (person.get("branch") or "HQ") != branch:
            continue
        if department and (person.get("department") or "") != department:
            continue
        out.append(person)
    return out


def _person_working(person: dict, fallback: set[int]) -> set[int]:
    custom = person.get("working_days")
    if isinstance(custom, set) and custom:
        return custom
    return fallback


def _person_grace(person: dict, fallback: int) -> int:
    if person.get("grace_minutes") is not None:
        return int(person["grace_minutes"])
    return fallback


def _holiday_for(person: dict, day: date, holidays: list[dict]) -> bool:
    key = day.isoformat()
    branch = person.get("branch") or "HQ"
    for item in holidays:
        if item.get("date") != key:
            continue
        scope = item.get("branch") or ""
        if not scope or scope == branch:
            return True
    return False


def _active_in_period(people, bundle, settings, start: date, end: date, employee_id: str):
    """Keep people who really worked in this period.

    A terminal lists everyone ever enrolled: former staff, test accounts, people who have not
    started yet. Someone linked to a terminal is reported when they have at least one punch in
    the `dormant_after_days` days up to the end of the period, and is never marked absent on days
    before their first punch. Asking for one employee by id always returns that employee.
    Typed-in people and the BunkerAtt-compatible directory are not affected.

    Returns the people to report and, per device-linked person, the date their history begins.
    """
    try:
        window = int(settings.get("dormant_after_days") or 0)
    except (TypeError, ValueError):
        window = 0
    if window <= 0 or employee_id:
        return people, {}
    linked = set(bundle.get("device_employee_ids") or [])
    activity = bundle.get("activity") or {}
    oldest = (end - timedelta(days=window)).isoformat()
    end_iso = end.isoformat()
    kept = []
    first_seen: dict[str, str] = {}
    for person in people:
        eid = person.get("employee_id")
        if eid not in linked:
            kept.append(person)
            continue
        first, last = activity.get(eid, ("", ""))
        if not first or first > end_iso or not last or last < oldest:
            continue
        first_seen[eid] = first
        kept.append(person)
    return kept, first_seen


def _apply_branches(people: list[dict], sessions: list[dict], rules: dict, branch: str):
    """Connect reports to branches through the terminal that recorded each check-in.

    A session belongs to the branch of the device it was punched on, and to the employee's own branch
    when that device has none. A person's home branch for the period is where most of their sessions
    are, which decides their summary row, their absent and weekend days, and which working days and
    grace period apply. With a branch filter, only people who punched there are listed, with only the
    sessions recorded there.
    """
    own = {p["employee_id"]: p.get("branch") or "HQ" for p in people}
    tagged = []
    counts: dict[str, dict[str, int]] = {}
    for item in sessions:
        eid = item.get("employee_id")
        name = item.get("branch") or own.get(eid) or "HQ"
        tagged.append({**item, "branch": name})
        counts.setdefault(eid, {})
        counts[eid][name] = counts[eid].get(name, 0) + 1
    kept = []
    for person in people:
        eid = person["employee_id"]
        mine = counts.get(eid) or {}
        if mine:
            top = max(mine.values())
            winners = sorted(name for name, number in mine.items() if number == top)
            home = own[eid] if own[eid] in winners else winners[0]
        else:
            home = own[eid]
        if branch and not (branch in mine or (not mine and home == branch)):
            continue
        shown = {**person, "branch": home}
        rule = rules.get(home)
        if home != own[eid] and rule:
            shown["working_days"] = rule["working_days"]
            if not person.get("own_grace"):
                shown["grace_minutes"] = rule["grace_minutes"]
        kept.append(shown)
    allowed = {p["employee_id"] for p in kept}
    tagged = [item for item in tagged if item.get("employee_id") in allowed]
    elsewhere: set[tuple[str, str]] = set()
    if branch:
        # Days worked at another branch are not listed here, but they are not absences either.
        elsewhere = {(item["employee_id"], str(item.get("work_date") or "")) for item in tagged if item["branch"] != branch}
        tagged = [item for item in tagged if item["branch"] == branch]
    return kept, tagged, elsewhere


def collect(params: dict, bundle: dict) -> dict:
    report = (params.get("report") or "monthly").strip().lower()
    if report not in REPORT_TYPES:
        raise ExportError("Unknown report type.")
    start, end = validate_range(params.get("start_date") or "", params.get("end_date") or "")
    branch = (params.get("branch") or params.get("branch_id") or "").strip()
    department = (params.get("department") or params.get("department_id") or "").strip()
    employee_id = (params.get("employee_id") or "").strip()
    status_filter = (params.get("status") or "").strip()
    include_inactive = str(params.get("include_inactive") or "") in {"1", "true", "yes"}
    settings = bundle.get("settings") or {}
    try:
        grace = max(0, int(settings.get("grace_minutes") or 10))
    except ValueError:
        grace = 10
    working = parse_working_days(settings.get("working_days") or "Sun-Thu")
    # The employee directory filters on the branch an employee is assigned to. Every attendance report
    # filters on where the person actually punched, which is decided below once the sessions are known.
    people = _filter_people(
        bundle.get("employees") or [],
        branch=branch if report == "employees" else "",
        department=department,
        employee_id=employee_id,
        include_inactive=include_inactive,
    )
    source = (params.get("source") or "").strip().lower()
    device_filter = str(params.get("device_id") or "").strip()
    if source == "device" or device_filter:
        linked = set(bundle.get("device_employee_ids") or [])
        links = bundle.get("device_links") or {}
        if device_filter.isdigit():
            wanted = int(device_filter)
            linked = {eid for eid in linked if wanted in (links.get(eid) or [])}
        people = [person for person in people if person.get("employee_id") in linked]
    first_seen: dict[str, str] = {}
    if report != "employees":
        people, first_seen = _active_in_period(people, bundle, settings, start, end, employee_id)
    allowed = {p["employee_id"] for p in people}
    by_id = {p["employee_id"]: p for p in people}
    start_iso = start.isoformat()
    end_iso = end.isoformat()
    sessions = [
        s
        for s in (bundle.get("sessions") or [])
        if s.get("employee_id") in allowed and start_iso <= str(s.get("work_date") or "") <= end_iso
    ]
    elsewhere: set[tuple[str, str]] = set()
    if report != "employees":
        people, sessions, elsewhere = _apply_branches(people, sessions, bundle.get("branch_rules") or {}, branch)
        allowed = {p["employee_id"] for p in people}
        by_id = {p["employee_id"]: p for p in people}
    if len(sessions) > MAX_ROWS:
        raise ExportError("Export is too large. Narrow the date range or filters.")

    grouped: dict[tuple[str, str], list[dict]] = {}
    for session in sessions:
        eid = str(session.get("employee_id") or "")
        work_day = str(session.get("work_date") or "")
        grouped.setdefault((eid, work_day), []).append(session)

    details = []
    present_days: dict[str, set[str]] = {eid: set() for eid in allowed}
    late_days: dict[str, set[str]] = {eid: set() for eid in allowed}
    incomplete_days: dict[str, set[str]] = {eid: set() for eid in allowed}
    minutes_sum: dict[str, int] = {eid: 0 for eid in allowed}

    for (eid, work_day), group in grouped.items():
        person = by_id.get(eid) or {}
        group = sorted(group, key=lambda s: str(s.get("clock_in") or ""))
        closed = [s for s in group if s.get("clock_out")]
        open_rows = [s for s in group if not s.get("clock_out")]
        # Working time is check-out minus check-in. A day is the sum of its closed sessions in whole minutes.
        # A day with any unclosed session is Incomplete and carries no hours, so a half-known day never adds to a total.
        parts = [m for m in (_session_minutes(s) for s in closed) if m is not None]
        day_minutes = sum(parts) if parts and not open_rows else None
        hours = round(day_minutes / 60, 2) if day_minutes is not None else None
        late_min = max(int(s.get("minutes_late") or 0) for s in group)
        row_grace = _person_grace(person, grace)
        if open_rows:
            label = "Incomplete"
        elif late_min > row_grace:
            label = "Late"
        else:
            label = "Present"
        try:
            work_dt = date.fromisoformat(work_day)
        except ValueError:
            work_dt = None
        is_weekend = work_dt is not None and work_dt.weekday() not in _person_working(person, working)
        if label in {"Present", "Late", "Incomplete"}:
            if not is_weekend:
                present_days[eid].add(work_day)
        if label == "Late":
            late_days[eid].add(work_day)
        if label == "Incomplete":
            incomplete_days[eid].add(work_day)
        if day_minutes is not None:
            minutes_sum[eid] += day_minutes
        last_out = ""
        if closed and not open_rows:
            last = max(closed, key=lambda s: str(s.get("clock_out") or ""))
            last_out = _fmt_time(last.get("clock_out"))
        row = {
            "employee_id": eid,
            "name": group[0].get("employee_name") or person.get("name") or "",
            "date": _fmt_date(work_day),
            "date_iso": work_day,
            "check_in": _fmt_time(group[0].get("clock_in")),
            "check_out": last_out,
            "hours": hours,
            "hours_minutes": day_minutes,
            "hours_text": minutes_text(day_minutes),
            "status": label,
            "shift": group[0].get("shift_name") or person.get("shift_name") or "",
            "department": person.get("department") or "",
            "branch": group[0].get("branch") or person.get("branch") or "HQ",
            "late_minutes": late_min,
            "device": group[0].get("device_mac") or "",
            "weekend": is_weekend,
        }
        if report == "late" and label != "Late":
            continue
        if not _status_wanted(label, status_filter):
            continue
        details.append(row)

    holidays = bundle.get("holidays") or []
    leave_index = {
        (item.get("employee_id"), item.get("work_date"))
        for item in (bundle.get("leaves") or [])
    }
    absences = []
    leave_rows = []
    weekend_rows = []
    worked_days: dict[str, set[str]] = {}
    for eid_key, day_key in grouped:
        worked_days.setdefault(eid_key, set()).add(day_key)
    summary = []
    for person in sorted(people, key=lambda p: (p.get("name") or "").lower()):
        eid = person["employee_id"]
        # Under a branch filter, days without punches belong to the person's home branch only.
        at_home = report == "employees" or not branch or person.get("branch") == branch
        person_days = _person_working(person, working)
        begins = first_seen.get(eid, "")
        scheduled = [
            day
            for day in _dates_between(start, end)
            if at_home
            and day.weekday() in person_days
            and not _holiday_for(person, day, holidays)
            and (not begins or day.isoformat() >= begins)
        ]
        present = present_days.get(eid, set())
        absent_n = 0
        for day in scheduled:
            key = day.isoformat()
            if key in present or (eid, key) in elsewhere:
                continue
            if (eid, key) in leave_index:
                leave_rows.append(
                    {
                        "employee_id": eid,
                        "name": person.get("name") or "",
                        "date": _fmt_date(key),
                        "date_iso": key,
                        "check_in": "",
                        "check_out": "",
                        "hours": None,
                        "hours_minutes": None,
                        "hours_text": "",
                        "status": "On Leave",
                        "shift": person.get("shift_name") or "",
                        "department": person.get("department") or "",
                        "branch": person.get("branch") or "HQ",
                        "late_minutes": 0,
                        "device": "",
                        "weekend": False,
                    }
                )
                continue
            absent_n += 1
            if report in {"absences", "monthly", "daily"}:
                absences.append(
                    {
                        "employee_id": eid,
                        "name": person.get("name") or "",
                        "date": _fmt_date(key),
                        "date_iso": key,
                        "check_in": "",
                        "check_out": "",
                        "hours": None,
                        "hours_minutes": None,
                        "hours_text": "",
                        "status": "Absent",
                        "shift": person.get("shift_name") or "",
                        "department": person.get("department") or "",
                        "branch": person.get("branch") or "HQ",
                        "late_minutes": 0,
                        "device": "",
                        "weekend": False,
                    }
                )
        if report in {"monthly", "daily"}:
            # Days off (Friday and Saturday with the default Sun-Thu week) get their own highlighted row,
            # unless the person punched that day. Those days never count as absences.
            for day in _dates_between(start, end):
                key = day.isoformat()
                if (
                    not at_home
                    or day.weekday() in person_days
                    or key in worked_days.get(eid, set())
                    or (eid, key) in elsewhere
                    or (begins and key < begins)
                ):
                    continue
                weekend_rows.append(
                    {
                        "employee_id": eid,
                        "name": person.get("name") or "",
                        "date": _fmt_date(key),
                        "date_iso": key,
                        "check_in": "",
                        "check_out": "",
                        "hours": None,
                        "hours_minutes": None,
                        "hours_text": "",
                        "status": "Weekend",
                        "shift": person.get("shift_name") or "",
                        "department": person.get("department") or "",
                        "branch": person.get("branch") or "HQ",
                        "late_minutes": 0,
                        "device": "",
                        "weekend": True,
                    }
                )
        total_minutes = minutes_sum.get(eid, 0)
        summary.append(
            {
                "employee": person.get("name") or eid,
                "employee_id": eid,
                "days_present": len(present),
                "late_arrivals": len(late_days.get(eid, set())),
                "absences": absent_n,
                "incomplete_days": len(incomplete_days.get(eid, set())),
                "total_minutes": total_minutes,
                "total_text": minutes_text(total_minutes),
                "total_hours": round(total_minutes / 60, 2),
                "branch": person.get("branch") or "HQ",
                "department": person.get("department") or "",
            }
        )

    if report in {"monthly", "daily"}:
        # Every calendar day of the period gets a row. A working day with no punches at all (no check-in and
        # no check-out) is Absent, a day off is Weekend, and approved leave stays On Leave.
        for row in leave_rows + weekend_rows + absences:
            if _status_wanted(row["status"], status_filter):
                details.append(row)

    details.sort(key=_by_name_then_date)

    if report == "absences":
        if status_filter and status_filter.lower() not in {"absent"}:
            if status_filter.lower() in {"on leave", "leave"}:
                details = sorted(leave_rows, key=_by_name_then_date)
            else:
                details = []
        else:
            details = sorted(absences, key=_by_name_then_date)

    directory = []
    for person in sorted(people, key=lambda p: (p.get("name") or "").lower()):
        directory.append(
            {
                "employee_id": person.get("employee_id"),
                "name": person.get("name"),
                "email": person.get("email") or "",
                "phone": person.get("phone") or "",
                "job_title": person.get("job_title") or "",
                "department": person.get("department") or "",
                "branch": person.get("branch") or "HQ",
                "shift": person.get("shift_name") or "",
                "status": person.get("employment_status") or "active",
                "joining_date": person.get("joining_date") or "",
            }
        )

    return {
        "report": report,
        "start": start,
        "end": end,
        "details": details,
        "summary": summary,
        "absences": absences,
        "directory": directory,
        "grace": grace,
        "company": settings.get("company_name") or "EspressoLab",
        "working_days": settings.get("working_days") or "Sun-Thu",
        "hours_note": HOURS_NOTE,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "branch": branch or "All branches",
        "department": department or "All departments",
        "count": len(directory) if report == "employees" else len(details),
    }


def selected_columns(report: str, raw: str) -> list[str]:
    allowed = DIRECTORY_ALL if report == "employees" else DETAIL_ALL
    defaults = DIRECTORY_DEFAULT if report == "employees" else DETAIL_DEFAULT
    if not (raw or "").strip():
        return list(defaults)
    picked = []
    for key in raw.split(","):
        key = key.strip()
        if key in allowed and key not in picked:
            picked.append(key)
    return picked or list(defaults)


def column_labels(keys: list[str]) -> list[str]:
    labels = {
        "employee_id": "Employee ID",
        "name": "Name",
        "date": "Date",
        "check_in": "Check-in",
        "check_out": "Check-out",
        "hours": "Hours",
        "status": "Status",
        "shift": "Shift",
        "department": "Department",
        "branch": "Branch",
        "late_minutes": "Late minutes",
        "device": "Device",
        "email": "Email",
        "phone": "Phone",
        "job_title": "Job title",
        "joining_date": "Joining date",
    }
    return [labels.get(key, key) for key in keys]


def _detail_value(row: dict, key: str):
    value = row.get(key)
    if key == "hours":
        return row.get("hours_text") or None  # "7:43", never a decimal
    if key == "check_out" and row.get("status") == "Incomplete":
        return NO_CHECKOUT  # a check-in without a check-out is never left blank
    return csv_safe(value) if isinstance(value, str) else value


def preview_payload(data: dict, columns: str, page: int, page_size: int) -> dict:
    """What a download would contain, as plain cells for the screen.

    Rows, columns, hours text and the No check-out wording come from the same data the files are built
    from, so the preview and the download cannot disagree.
    """
    report = data["report"]
    cols = selected_columns(report, columns)
    rows = data["directory"] if report == "employees" else data["details"]
    page_size = max(1, min(int(page_size), 500))
    page = max(1, int(page))
    window = rows[(page - 1) * page_size : page * page_size]
    cells = []
    for row in window:
        line = []
        for key in cols:
            if report == "employees":
                value = row.get(key) or ""
            elif key == "hours":
                value = row.get("hours_text") or ""
            elif key == "check_out" and row.get("status") == "Incomplete":
                value = NO_CHECKOUT
            else:
                value = row.get(key)
                value = "" if value is None else value
            line.append(value if isinstance(value, (int, float)) else str(value))
        cells.append({"cells": line, "status": "" if report == "employees" else row.get("status") or ""})
    summary = []
    if report != "employees":
        summary = [
            {
                "employee": item["employee"],
                "employee_id": item["employee_id"],
                "branch": item["branch"],
                "days_present": item["days_present"],
                "late_arrivals": item["late_arrivals"],
                "absences": item["absences"],
                "incomplete_days": item["incomplete_days"],
                "total_text": item["total_text"],
            }
            for item in data["summary"]
        ]
    total_minutes = sum(item["total_minutes"] for item in data["summary"]) if report != "employees" else 0
    return {
        "report": report,
        "title": _title(report),
        "start": data["start"].isoformat(),
        "end": data["end"].isoformat(),
        "branch": data["branch"],
        "department": data["department"],
        "company": data["company"],
        "hours_note": data["hours_note"],
        "columns": column_labels(cols),
        "keys": cols,
        "rows": cells,
        "count": data["count"],
        "page": page,
        "page_size": page_size,
        "summary": summary,
        "total_hours": minutes_text(total_minutes) if report != "employees" else "",
        "incomplete_days": sum(item["incomplete_days"] for item in data["summary"]) if report != "employees" else 0,
    }


def filename_for(report: str, fmt: str, start: date, end: date) -> str:
    if report == "employees":
        return f"EspressoLabAttendance_Employees_{date.today().isoformat()}.{fmt}"
    if report == "monthly" and start.month == end.month and start.year == end.year:
        stamp = start.strftime("%Y-%m")
    else:
        stamp = f"{start.isoformat()}_to_{end.isoformat()}"
    names = {
        "daily": "Attendance",
        "monthly": "Attendance",
        "late": "Late_Arrivals",
        "absences": "Absences",
        "hours": "Working_Hours",
    }
    prefix = names.get(report, "Attendance")
    if fmt == "pdf" and report in {"monthly", "daily", "hours"}:
        return f"EspressoLabAttendance_Attendance_Summary_{stamp}.pdf"
    return f"EspressoLabAttendance_{prefix}_{stamp}.{fmt}"


def media_type(fmt: str) -> str:
    if fmt == "xlsx":
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if fmt == "pdf":
        return "application/pdf"
    return "text/csv; charset=utf-8"


def _title(report: str) -> str:
    return {
        "daily": "Daily Attendance",
        "monthly": "Monthly Attendance",
        "late": "Late Arrivals",
        "absences": "Absences",
        "hours": "Working Hours (elapsed time)",
        "employees": "Employee Directory",
    }.get(report, "Attendance")


def _banner(ws, data: dict, title: str, width: int) -> int:
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(2, width))
    ws["A1"] = "EspressoLab Attendance"
    ws["A1"].font = TITLE_FONT
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=max(2, width))
    ws["A2"] = title
    ws["A2"].font = Font(size=12, color="333333", name="Calibri")
    ws["A3"] = "Period"
    ws["B3"] = f"{data['start'].isoformat()} to {data['end'].isoformat()}"
    ws["A4"] = "Generated"
    ws["B4"] = data["generated_at"].replace("T", " ")
    ws["A5"] = "Company / branch"
    ws["B5"] = f"{data['company']} · {data['branch']}"
    ws["A6"] = "Hours note"
    ws.merge_cells(start_row=6, start_column=2, end_row=6, end_column=max(2, width))
    ws["B6"] = data["hours_note"]
    add_excel_logo(ws, f"{get_column_letter(max(4, width - 1))}1")
    return 8


def _style_header(ws, row: int, width: int) -> None:
    for col in range(1, width + 1):
        cell = ws.cell(row, col)
        cell.fill = INK
        cell.font = HEAD_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = THIN
    ws.freeze_panes = f"A{row + 1}"
    ws.auto_filter.ref = f"A{row}:{get_column_letter(width)}{max(ws.max_row, row)}"
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.print_title_rows = f"{row}:{row}"
    ws.page_margins = PageMargins(left=0.4, right=0.4, top=0.6, bottom=0.6)
    ws.sheet_properties.pageSetUpPr.fitToPage = True


def _status_fills(ws, header_row: int, status_col: int, last_row: int) -> None:
    if last_row <= header_row:
        return
    col = get_column_letter(status_col)
    rng = f"{col}{header_row + 1}:{col}{last_row}"
    ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"Present"'], fill=GREEN))
    ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"Late"'], fill=LATE))
    ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"Absent"'], fill=RED))
    ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"On Leave"'], fill=PURPLE))
    ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"Incomplete"'], fill=INCOMPLETE))
    ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"Weekend"'], fill=WEEKEND))


def _excel(data: dict, cols: list[str]) -> bytes:
    wb = Workbook()
    report = data["report"]
    if report == "employees":
        ws = wb.active
        ws.title = "Employees"
        labels = column_labels(cols)
        header_row = _banner(ws, data, "Employee Directory", max(2, len(cols)))
        for idx, label in enumerate(labels, start=1):
            ws.cell(header_row, idx, label)
        for row in data["directory"]:
            ws.append([csv_safe(row.get(key) or "") for key in cols])
        last = ws.max_row
        for r in range(header_row + 1, last + 1):
            for c in range(1, len(cols) + 1):
                cell = ws.cell(r, c)
                cell.border = THIN
                if r % 2 == 0:
                    cell.fill = ZEBRA
        _style_header(ws, header_row, len(cols))
        for i in range(1, len(cols) + 1):
            ws.column_dimensions[get_column_letter(i)].width = 18
    else:
        ws = wb.active
        ws.title = "Attendance Details"
        labels = column_labels(cols)
        header_row = _banner(ws, data, _title(report), max(2, len(cols)))
        for idx, label in enumerate(labels, start=1):
            ws.cell(header_row, idx, label)
        for item in data["details"]:
            excel_row = []
            for key in cols:
                val = _detail_value(item, key)
                if key == "hours":
                    minutes = item.get("hours_minutes")
                    val = timedelta(minutes=minutes) if minutes is not None else None  # real duration, sums in Excel
                if key in {"name", "employee_id", "status", "shift", "department", "branch", "device"}:
                    val = csv_safe(val)
                excel_row.append(val)
            ws.append(excel_row)
        last = ws.max_row
        hours_idx = cols.index("hours") + 1 if "hours" in cols else None
        status_idx = cols.index("status") + 1 if "status" in cols else None
        date_idx = cols.index("date") + 1 if "date" in cols else None
        for r in range(header_row + 1, last + 1):
            for c in range(1, len(cols) + 1):
                cell = ws.cell(r, c)
                cell.border = THIN
                if r % 2 == 0:
                    cell.fill = ZEBRA
            if hours_idx:
                cell = ws.cell(r, hours_idx)
                if cell.value in ("", None):
                    cell.value = None
                else:
                    cell.number_format = "[h]:mm"
                    cell.alignment = Alignment(horizontal="right")
            if date_idx:
                ws.cell(r, date_idx).alignment = Alignment(horizontal="center")
            item = data["details"][r - header_row - 1]
            if item.get("status") == "Incomplete":
                for c in range(1, len(cols) + 1):
                    ws.cell(r, c).fill = INCOMPLETE
                    ws.cell(r, c).font = INCOMPLETE_FONT
            elif item.get("status") == "Weekend":
                for c in range(1, len(cols) + 1):
                    ws.cell(r, c).fill = WEEKEND
            elif item.get("weekend") and date_idx:
                ws.cell(r, date_idx).fill = WEEKEND  # worked on a day off
        _style_header(ws, header_row, max(1, len(cols)))
        ws.auto_filter.ref = f"A{header_row}:{get_column_letter(len(cols))}{max(last, header_row)}"
        if status_idx:
            _status_fills(ws, header_row, status_idx, last)
        for i in range(1, len(cols) + 1):
            ws.column_dimensions[get_column_letter(i)].width = 16
        ws.column_dimensions["A"].width = 14
        ws.column_dimensions["B"].width = 22

        if report in {"monthly", "daily", "hours"}:
            sm = wb.create_sheet("Employee Summary")
            width = len(SUMMARY_HEADERS)
            sh = _banner(sm, data, "Employee Summary", width)
            for idx, label in enumerate(SUMMARY_HEADERS, start=1):
                sm.cell(sh, idx, label)
            total_present = total_late = total_abs = total_incomplete = total_minutes = 0
            for item in data["summary"]:
                sm.append(
                    [
                        csv_safe(item["employee"]),
                        item["days_present"],
                        item["late_arrivals"],
                        item["absences"],
                        item["incomplete_days"],
                        timedelta(minutes=item["total_minutes"]),
                    ]
                )
                total_present += item["days_present"]
                total_late += item["late_arrivals"]
                total_abs += item["absences"]
                total_incomplete += item["incomplete_days"]
                total_minutes += item["total_minutes"]
            sm.append(
                ["Total", int(total_present), int(total_late), int(total_abs), int(total_incomplete), timedelta(minutes=total_minutes)]
            )
            last_s = sm.max_row
            for r in range(sh, last_s + 1):
                for c in range(1, width + 1):
                    cell = sm.cell(r, c)
                    cell.border = THIN
                    if r > sh and r % 2 == 0 and r < last_s:
                        cell.fill = ZEBRA
                if r > sh:
                    sm.cell(r, 6).number_format = "[h]:mm"
            for c in range(1, width + 1):
                sm.cell(last_s, c).font = Font(bold=True)
                sm.cell(last_s, c).fill = CREAM
            _style_header(sm, sh, width)
            sm.auto_filter.ref = f"A{sh}:{get_column_letter(width)}{max(last_s - 1, sh)}"
            sm.column_dimensions["A"].width = 28
            for col in "BCDEF":
                sm.column_dimensions[col].width = 16

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _csv(data: dict, cols: list[str]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(column_labels(cols))
    rows = data["directory"] if data["report"] == "employees" else data["details"]
    for row in rows:
        out = []
        for key in cols:
            val = row.get(key) if data["report"] == "employees" else _detail_value(row, key)
            if data["report"] == "employees":
                out.append(csv_safe(val or ""))
            elif val is None:
                out.append("")
            elif key == "hours":
                out.append(val)
            else:
                out.append(csv_safe(val) if not isinstance(val, (int, float)) else val)
        writer.writerow(out)
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


def _register_pdf_font() -> str:
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return "EspressoSans" if "EspressoSans" in pdfmetrics.getRegisteredFontNames() else "Helvetica"
    candidates = [
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\tahoma.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if os.path.isfile(path):
            try:
                pdfmetrics.registerFont(TTFont("EspressoSans", path))
                _FONT_REGISTERED = True
                return "EspressoSans"
            except Exception:
                continue
    _FONT_REGISTERED = True
    return "Helvetica"


def _shape(text: str) -> str:
    value = csv_safe("" if text is None else str(text))
    if any("\u0600" <= ch <= "\u06FF" for ch in value):
        try:
            import arabic_reshaper
            from bidi.algorithm import get_display

            return get_display(arabic_reshaper.reshape(value))
        except Exception:
            return value
    return value


PDF_WIDTH = A4[0] - 48  # portrait A4 between 24 pt margins

_PDF_WEIGHTS = {
    "employee_id": 1.3, "name": 1.8, "date": 2.0, "check_in": 1.2, "check_out": 1.6, "hours": 0.9,
    "status": 1.5, "shift": 0.9, "department": 1.4, "branch": 1.15, "late_minutes": 1.1, "device": 1.1,
    "email": 2.2, "phone": 1.4, "job_title": 1.5, "joining_date": 1.3,
}


def _pdf_widths(cols: list[str], available: float) -> list[float]:
    """Column widths that always add up to the page width, so a portrait page never overflows."""
    weights = [_PDF_WEIGHTS.get(key, 1.0) for key in cols]
    total = sum(weights) or 1.0
    return [available * weight / total for weight in weights]


def _pdf(data: dict, cols: list[str]) -> bytes:
    font = _register_pdf_font()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        title=f"EspressoLab Attendance {_title(data['report'])}",
        leftMargin=24,
        rightMargin=24,
        topMargin=28,
        bottomMargin=32,
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("elTitle", parent=styles["Title"], fontName=font, textColor=PDF_INK, fontSize=18)
    body = ParagraphStyle("elBody", parent=styles["Normal"], fontName=font, fontSize=9, leading=12)
    heading = ParagraphStyle("elH", parent=styles["Heading2"], fontName=font, textColor=PDF_INK, fontSize=12)

    compact = len(cols) > 8  # many columns on a portrait page: smaller type so words never break mid-way
    cell_style = ParagraphStyle("elCell", parent=body, fontSize=7, leading=9) if compact else body
    head_style = ParagraphStyle("elHead", parent=body, fontName=font, fontSize=7 if compact else 8, leading=9 if compact else 10, textColor=PDF_CREAM)

    def cell(value) -> Paragraph:
        safe = _shape("" if value is None else str(value)).replace("&", "&amp;").replace("<", "&lt;")
        return Paragraph(safe, cell_style)

    def on_page(canvas, doc_):
        canvas.saveState()
        canvas.setFillColor(PDF_INK)
        canvas.setFont(font, 8)
        canvas.drawString(24, 16, f"EspressoLab Attendance · {data['generated_at'].replace('T', ' ')}")
        canvas.drawRightString(A4[0] - 24, 16, f"Page {doc_.page}")
        canvas.restoreState()

    logo = pdf_logo(150)
    story = [
        logo if logo is not None else Paragraph("EspressoLab Attendance", title),
        Spacer(1, 6),
        Paragraph(_shape(_title(data["report"])), heading),
        Paragraph(
            _shape(f"{data['company']} · {data['branch']} · {data['start']} to {data['end']} · {data['hours_note']}"),
            body,
        ),
        Spacer(1, 10),
    ]
    if data["report"] != "employees" and data["summary"]:
        present = sum(x["days_present"] for x in data["summary"])
        late = sum(x["late_arrivals"] for x in data["summary"])
        absent = sum(x["absences"] for x in data["summary"])
        incomplete = sum(x["incomplete_days"] for x in data["summary"])
        worked = minutes_text(sum(x["total_minutes"] for x in data["summary"]))
        story.append(
            Paragraph(
                f"People {len(data['summary'])} · Present days {present} · Late {late} · Absences {absent} · "
                f"Incomplete days {incomplete} · Total hours {worked}",
                body,
            )
        )
        story.append(Spacer(1, 8))

    table_data = [[Paragraph(label, head_style) for label in column_labels(cols)]]
    source_rows = data["directory"] if data["report"] == "employees" else data["details"]
    for row in source_rows:
        cells = []
        for key in cols:
            if data["report"] != "employees" and key == "hours":
                cells.append(_detail_value(row, key) or "")
            elif data["report"] == "employees":
                cells.append(cell(row.get(key) or ""))
            else:
                cells.append(cell(_detail_value(row, key)))
        table_data.append(cells)

    table = Table(table_data, repeatRows=1, colWidths=_pdf_widths(cols, PDF_WIDTH))
    cmds = [
        ("FONTNAME", (0, 0), (-1, 0), font),
        ("BACKGROUND", (0, 0), (-1, 0), PDF_INK),
        ("TEXTCOLOR", (0, 0), (-1, 0), PDF_CREAM),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CCCCCC")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTSIZE", (0, 0), (-1, -1), 7 if compact else 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
    ]
    status_idx = cols.index("status") if "status" in cols else None
    if status_idx is not None:
        fills = {
            "Present": PDF_GREEN, "Late": PDF_LATE, "Absent": PDF_RED, "Incomplete": PDF_INCOMPLETE,
            "On Leave": PDF_PURPLE, "Weekend": PDF_WEEKEND,
        }
        for i, row in enumerate(source_rows, start=1):
            status = str(row.get("status") or "")
            if status in {"Incomplete", "Weekend"}:  # the whole row stands out, not only the status cell
                cmds.append(("BACKGROUND", (0, i), (-1, i), fills[status]))
            elif row.get("weekend") and "date" in cols:
                cmds.append(("BACKGROUND", (cols.index("date"), i), (cols.index("date"), i), PDF_WEEKEND))
            fill = fills.get(status)
            if fill:
                cmds.append(("BACKGROUND", (status_idx, i), (status_idx, i), fill))
    table.setStyle(TableStyle(cmds))
    story.append(table)

    if data["report"] in {"monthly", "daily", "hours"} and data["summary"]:
        story.append(Spacer(1, 14))
        story.append(Paragraph("Employee Summary", heading))
        story.append(Paragraph(_shape(data["hours_note"]), body))
        sm = [SUMMARY_HEADERS]
        for item in data["summary"]:
            sm.append(
                [
                    cell(item["employee"]),
                    str(item["days_present"]),
                    str(item["late_arrivals"]),
                    str(item["absences"]),
                    str(item["incomplete_days"]),
                    item["total_text"],
                ]
            )
        summary_table = Table(sm, repeatRows=1, colWidths=[PDF_WIDTH * share for share in (0.30, 0.13, 0.13, 0.13, 0.15, 0.16)])
        summary_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, 0), font),
                    ("BACKGROUND", (0, 0), (-1, 0), PDF_INK),
                    ("TEXTCOLOR", (0, 0), (-1, 0), PDF_CREAM),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CCCCCC")),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(summary_table)
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()


def build_payload(data: dict, fmt: str, columns: str) -> tuple[bytes, str, str]:
    if fmt not in FORMATS:
        raise ExportError("Format must be xlsx, csv, or pdf.")
    cols = selected_columns(data["report"], columns)
    if fmt == "xlsx":
        payload = _excel(data, cols)
    elif fmt == "csv":
        payload = _csv(data, cols)
    else:
        payload = _pdf(data, cols)
    name = filename_for(data["report"], fmt, data["start"], data["end"])
    return payload, name, media_type(fmt)
