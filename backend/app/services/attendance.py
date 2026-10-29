"""Calculated sessions and the BunkerAtt-compatible report bundle.

Raw punches are never deleted by a recalculation.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import (
    AttendanceSession,
    Branch,
    Device,
    DeviceUser,
    Employee,
    Holiday,
    LeaveEntry,
    Punch,
    Setting,
    Shift,
)
from app.services.pairing import build_sessions
from app.time_utils import hours_between, parse_working_days, shift_bounds, work_date_for

SETTING_DEFAULTS = {
    "company_name": "EspressoLab",
    "grace_minutes": "10",
    "working_days": "Sun-Thu",
    "timezone": "Europe/Istanbul",
    "sync_retries": "2",
    "default_start": "08:00",
    "default_end": "16:00",
    "dormant_after_days": "90",
    "punch_debounce_minutes": "2",
    "max_session_hours": "12",
    "retap_window_minutes": "30",
}


def get_settings(db: Session) -> dict[str, str]:
    data = dict(SETTING_DEFAULTS)
    for row in db.scalars(select(Setting)).all():
        data[row.key] = row.value
    return data


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.replace(" ", "T")[:19]
    return value.replace(microsecond=0).isoformat(timespec="seconds")


def load_bundle(
    db: Session,
    *,
    employee_id: str = "",
    date_from: str = "",
    date_to: str = "",
) -> dict:
    settings = get_settings(db)
    global_grace = int(settings.get("grace_minutes") or 10)
    global_working = settings.get("working_days") or "Sun-Thu"
    branches = {row.id: row for row in db.scalars(select(Branch)).all()}
    shifts = {row.id: row for row in db.scalars(select(Shift)).all()}
    # A session belongs to the branch of the terminal that recorded its check-in.
    device_branch = {
        row.id: branches[row.branch_id].name
        for row in db.scalars(select(Device)).all()
        if row.branch_id in branches
    }
    people = []
    eq = select(Employee)
    if employee_id:
        eq = eq.where(Employee.employee_id == employee_id)
    for emp in db.scalars(eq).all():
        branch = branches.get(emp.branch_id)
        shift = effective_shift(emp, branches, shifts)
        grace = global_grace
        if shift is not None and shift.grace_minutes is not None:
            grace = int(shift.grace_minutes)
        elif branch is not None and branch.grace_minutes is not None:
            grace = int(branch.grace_minutes)
        working_text = branch.working_days if branch and branch.working_days else global_working
        people.append(
            {
                "employee_id": emp.employee_id,
                "name": emp.full_name,
                "email": emp.email or "",
                "phone": emp.phone or "",
                "job_title": emp.job_title or "",
                "department": emp.department or "",
                "branch": branch.name if branch else "HQ",
                "employment_status": emp.employment_status or "active",
                "joining_date": emp.joining_date or "",
                "shift_name": shift.name if shift else "",
                "grace_minutes": grace,
                "own_grace": shift is not None and shift.grace_minutes is not None,
                "working_days": parse_working_days(working_text),
                "pk": emp.id,
            }
        )
    sessions = []
    sq = select(AttendanceSession, Employee).join(Employee, AttendanceSession.employee_pk == Employee.id)
    if date_from:
        sq = sq.where(AttendanceSession.work_date >= date_from)
    if date_to:
        sq = sq.where(AttendanceSession.work_date <= date_to)
    if employee_id:
        sq = sq.where(Employee.employee_id == employee_id)
    for sess, emp in db.execute(sq).all():
        sessions.append(
            {
                "employee_id": emp.employee_id,
                "employee_name": emp.full_name,
                "work_date": sess.work_date,
                "clock_in": _iso(sess.clock_in),
                "clock_out": _iso(sess.clock_out),
                "hours": sess.hours,
                "shift_name": sess.shift_name or "",
                "minutes_late": int(sess.minutes_late or 0),
                "device_mac": sess.device_name or "",
                "branch": device_branch.get(sess.device_id, ""),
            }
        )
    activity: dict[str, tuple[str, str]] = {}
    first_rows = db.execute(
        select(Employee.employee_id, func.min(AttendanceSession.work_date))
        .join(AttendanceSession, AttendanceSession.employee_pk == Employee.id)
        .group_by(Employee.employee_id)
    ).all()
    last_query = (
        select(Employee.employee_id, func.max(AttendanceSession.work_date))
        .join(AttendanceSession, AttendanceSession.employee_pk == Employee.id)
        .group_by(Employee.employee_id)
    )
    if date_to:
        last_query = last_query.where(AttendanceSession.work_date <= date_to)
    last_by_person = {eid: stamp for eid, stamp in db.execute(last_query).all()}
    for eid, first in first_rows:
        activity[eid] = (first or "", last_by_person.get(eid) or "")
    device_employee_ids: set[str] = set()
    device_links: dict[str, set[int]] = defaultdict(set)
    link_rows = db.execute(
        select(DeviceUser, Employee).join(Employee, DeviceUser.employee_pk == Employee.id)
    ).all()
    for link, emp in link_rows:
        device_employee_ids.add(emp.employee_id)
        device_links[emp.employee_id].add(link.device_id)
    holidays = []
    for row in db.scalars(select(Holiday)).all():
        branch = branches.get(row.branch_id)
        holidays.append({"date": row.holiday_date, "branch": branch.name if branch else "", "name": row.name})
    leaves = []
    lq = select(LeaveEntry, Employee).join(Employee, LeaveEntry.employee_pk == Employee.id)
    if employee_id:
        lq = lq.where(Employee.employee_id == employee_id)
    for row, emp in db.execute(lq).all():
        leaves.append({"employee_id": emp.employee_id, "work_date": row.work_date, "note": row.note or ""})
    branch_rules = {
        row.name: {
            "grace_minutes": int(row.grace_minutes) if row.grace_minutes is not None else global_grace,
            "working_days": parse_working_days(row.working_days or global_working),
        }
        for row in branches.values()
    }
    return {
        "employees": people,
        "branch_rules": branch_rules,
        "sessions": sessions,
        "settings": settings,
        "holidays": holidays,
        "leaves": leaves,
        "activity": activity,
        "device_employee_ids": device_employee_ids,
        "device_links": {key: sorted(value) for key, value in device_links.items()},
    }


def effective_shift(emp: Employee, branches: dict, shifts: dict[int, Shift]):
    """The employee's own shift, else the default shift of their branch, else none (company default times)."""
    shift = shifts.get(emp.shift_id) if emp.shift_id else None
    if shift is None and emp.branch_id:
        branch = branches.get(emp.branch_id)
        if branch is not None and branch.default_shift_id:
            shift = shifts.get(branch.default_shift_id)
    return shift


def _shift_for(emp: Employee, branches: dict, shifts: dict[int, Shift], settings: dict[str, str]):
    shift = effective_shift(emp, branches, shifts)
    if shift is not None:
        return shift.name, shift.start_time, shift.end_time
    branch = branches.get(emp.branch_id) if emp.branch_id else None
    if branch is not None and branch.work_start and branch.work_end:
        return "Branch hours", branch.work_start, branch.work_end
    return "Day", settings.get("default_start") or "08:00", settings.get("default_end") or "16:00"


def rebuild_employees(db: Session, employee_pks: set[int]) -> int:
    """Replace calculated sessions for these employees. Punches stay stored."""
    employee_pks = {int(pk) for pk in employee_pks if pk}
    if not employee_pks:
        return 0
    db.execute(delete(AttendanceSession).where(AttendanceSession.employee_pk.in_(employee_pks)))
    settings = get_settings(db)
    shifts = {row.id: row for row in db.scalars(select(Shift)).all()}
    branches = {row.id: row for row in db.scalars(select(Branch)).all()}
    employees = db.scalars(select(Employee).where(Employee.id.in_(employee_pks))).all()
    links = db.scalars(select(DeviceUser).where(DeviceUser.employee_pk.in_(employee_pks))).all()
    pair_keys = {(link.device_id, link.device_user_id) for link in links}
    if not pair_keys:
        db.flush()
        return 0
    device_ids = {key[0] for key in pair_keys}
    user_ids = {key[1] for key in pair_keys}
    punches = db.scalars(
        select(Punch).where(Punch.device_id.in_(device_ids), Punch.device_user_id.in_(user_ids))
    ).all()
    by_emp: dict[int, list[Punch]] = defaultdict(list)
    link_owner = {(link.device_id, link.device_user_id): link.employee_pk for link in links}
    for punch in punches:
        owner = link_owner.get((punch.device_id, punch.device_user_id))
        if owner:
            by_emp[owner].append(punch)
    created = 0
    debounce = _number(settings.get("punch_debounce_minutes"), 2.0)
    longest = _number(settings.get("max_session_hours"), 12.0)
    retap = _number(settings.get("retap_window_minutes"), 30.0)
    for emp in employees:
        shift_name, start_hhmm, end_hhmm = _shift_for(emp, branches, shifts, settings)
        by_time: dict[datetime, Punch] = {}
        for punch in sorted(by_emp.get(emp.id, []), key=lambda row: (row.punched_at, row.id)):
            by_time.setdefault(punch.punched_at, punch)
        late_counted: set[str] = set()
        taps = [(stamp, punch.punch) for stamp, punch in by_time.items()]
        for cin, cout in build_sessions(taps, debounce, longest, retap):
            work_day_date = work_date_for(cin, start_hhmm, end_hhmm)
            work_day = work_day_date.isoformat()
            minutes_late = 0
            if work_day not in late_counted:
                late_counted.add(work_day)
                start_dt, _end_dt = shift_bounds(work_day_date, start_hhmm, end_hhmm)
                minutes_late = max(0, int((cin - start_dt).total_seconds() // 60))
            hours = round(hours_between(cin, cout), 4) if cout is not None else None
            db.add(
                AttendanceSession(
                    employee_pk=emp.id,
                    work_date=work_day,
                    clock_in=cin,
                    clock_out=cout,
                    hours=hours,
                    minutes_late=minutes_late,
                    shift_name=shift_name,
                    device_name=by_time[cin].device_name_snapshot or "",
                    device_id=by_time[cin].device_id,
                )
            )
            created += 1
    db.flush()
    return created


def _number(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def punch_window(day: date) -> tuple[datetime, datetime]:
    return datetime.combine(day, datetime.min.time()), datetime.combine(day + timedelta(days=1), datetime.max.time())
