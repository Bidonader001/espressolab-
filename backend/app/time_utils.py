"""Shift windows and elapsed hours. Overnight punches stay on the shift's work date."""

from __future__ import annotations

from datetime import date, datetime, timedelta, time
from typing import Optional

_DAY_INDEX = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def parse_hhmm(value: str) -> time:
    parts = (value or "00:00").strip().split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    return time(hour % 24, minute)


def is_overnight(start_hhmm: str, end_hhmm: str) -> bool:
    return parse_hhmm(end_hhmm) <= parse_hhmm(start_hhmm)


def work_date_for(now: datetime, start_hhmm: str | None, end_hhmm: str | None) -> date:
    if not start_hhmm or not end_hhmm:
        return now.date()
    if is_overnight(start_hhmm, end_hhmm) and now.time() <= parse_hhmm(end_hhmm):
        return now.date() - timedelta(days=1)
    return now.date()


def hours_between(clock_in: datetime, clock_out: datetime) -> float:
    delta = clock_out - clock_in
    return max(0.0, delta.total_seconds() / 3600.0)


def hours_status(hours: Optional[float]) -> str:
    if hours is None:
        return "open"
    if hours < 8:
        return "under"
    if round(hours, 2) == 8.00:
        return "exact"
    return "over"


def format_hours(hours: Optional[float]) -> str:
    if hours is None:
        return "—"
    whole = int(hours)
    minutes = int(round((hours - whole) * 60))
    if minutes == 60:
        whole += 1
        minutes = 0
    return f"{whole}:{minutes:02d}"


def shift_bounds(day: date, start_hhmm: str, end_hhmm: str) -> tuple[datetime, datetime]:
    start = parse_hhmm(start_hhmm or "00:00")
    end = parse_hhmm(end_hhmm or "00:00")
    start_dt = datetime.combine(day, start)
    overnight = bool(start_hhmm and end_hhmm) and (is_overnight(start_hhmm, end_hhmm) or end == time(0, 0))
    end_dt = datetime.combine(day + timedelta(days=1), end) if overnight else datetime.combine(day, end)
    return start_dt, end_dt


def shift_window(now: datetime, start_hhmm: str, end_hhmm: str) -> tuple[datetime, datetime, date]:
    wd = work_date_for(now, start_hhmm, end_hhmm)
    start_dt, end_dt = shift_bounds(wd, start_hhmm, end_hhmm)
    return start_dt, end_dt, wd


def period_range(period: str, anchor: date) -> tuple[date, date]:
    period = (period or "daily").lower()
    if period == "weekly":
        start = anchor - timedelta(days=anchor.weekday())
        return start, start + timedelta(days=6)
    if period == "monthly":
        start = anchor.replace(day=1)
        if start.month == 12:
            nxt = start.replace(year=start.year + 1, month=1, day=1)
        else:
            nxt = start.replace(month=start.month + 1, day=1)
        return start, nxt - timedelta(days=1)
    return anchor, anchor


def parse_working_days(text: str) -> set[int]:
    raw = (text or "Sun-Thu").strip().lower()
    if "-" in raw and "," not in raw:
        left, right = raw.split("-", 1)
        a = _DAY_INDEX.get(left.strip()[:3])
        b = _DAY_INDEX.get(right.strip()[:3])
        if a is not None and b is not None:
            out = set()
            k = a
            while True:
                out.add(k)
                if k == b:
                    break
                k = (k + 1) % 7
            return out
    found = {_DAY_INDEX[p.strip()[:3]] for p in raw.replace(";", ",").split(",") if p.strip()[:3] in _DAY_INDEX}
    return found or {6, 0, 1, 2, 3}


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(str(value))
