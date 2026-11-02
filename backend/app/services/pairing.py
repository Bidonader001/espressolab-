"""Turn a person's raw punches into one session per day.

The in/out flag on a terminal is not used. A day is the first punch and the last punch.
Every punch between those two stays stored and is left out of the calculation.

1. Identical timestamps collapse to one punch.
2. A tap within `debounce_minutes` of the previous punch is the same tap recorded twice.
   It is ignored for the calculation and stays stored.
3. On each calendar day the earliest remaining punch is the check-in and the latest is the
   check-out. A day with only one punch stays open.
4. When a day has only that check-in, the first punch of the next day closes it if the gap is
   within `max_session_hours`. That is how a shift that crosses midnight stays one session
   on the check-in day.

Sessions may cross midnight. Each session belongs to the day of its clock-in.
"""

from __future__ import annotations

from datetime import datetime

# ZKTeco punch states: 0 check-in, 1 check-out, 2 break-out, 3 break-in, 4 overtime-in, 5 overtime-out.
IN_STATES = {0, 3, 4}
OUT_STATES = {1, 2, 5}

Tap = tuple[datetime, int | None]

# A same-flag tap this close is someone tapping the terminal again, not a new arrival or departure.
REAL_GAP_SECONDS = 10 * 60


def direction(state: int | None) -> str | None:
    if state in IN_STATES:
        return "in"
    if state in OUT_STATES:
        return "out"
    return None


def _normalise(taps) -> list[Tap]:
    """Accept bare datetimes or (datetime, state); sort, and keep one record per timestamp."""
    first: dict[datetime, int | None] = {}
    for item in taps:
        stamp, state = item if isinstance(item, tuple) else (item, None)
        first.setdefault(stamp, state)
    return sorted(first.items(), key=lambda pair: pair[0])


def _opposite_later_same_day(items: list[Tap], index: int) -> bool:
    """True when a later punch today carries the other in/out flag."""
    stamp, state = items[index]
    way = direction(state)
    if way is None:
        return False
    for later_stamp, later_state in items[index + 1 :]:
        if later_stamp.date() != stamp.date():
            return False
        later = direction(later_state)
        if later is not None and later != way:
            return True
    return False


def collapse_taps(taps, debounce_minutes: float, retap_minutes: float = 0.0) -> list[Tap]:
    items = _normalise(taps)
    kept: list[Tap] = []
    debounce = max(0.0, float(debounce_minutes)) * 60.0
    retap = max(0.0, float(retap_minutes)) * 60.0
    for index, (stamp, state) in enumerate(items):
        if kept:
            gap = (stamp - kept[-1][0]).total_seconds()
            if gap <= debounce:
                continue
            same_way = direction(state) is not None and direction(state) == direction(kept[-1][1])
            short_repeat = gap <= REAL_GAP_SECONDS
            if same_way and gap <= retap and (short_repeat or _opposite_later_same_day(items, index)):
                continue
        kept.append((stamp, state))
    return kept


def remove_duplicate_taps(times: list[datetime], debounce_minutes: float) -> list[datetime]:
    return [stamp for stamp, _state in collapse_taps(times, debounce_minutes)]


def pair_punches(times: list[datetime], max_session_hours: float) -> list[tuple[datetime, datetime | None]]:
    limit = max(0.0, float(max_session_hours)) * 3600.0
    sessions: list[tuple[datetime, datetime | None]] = []
    index = 0
    while index < len(times):
        clock_in = times[index]
        if index + 1 < len(times) and (times[index + 1] - clock_in).total_seconds() <= limit:
            sessions.append((clock_in, times[index + 1]))
            index += 2
        else:
            sessions.append((clock_in, None))
            index += 1
    return sessions


def build_sessions(
    taps, debounce_minutes: float, max_session_hours: float, retap_minutes: float = 0.0
) -> list[tuple[datetime, datetime | None]]:
    """One session per calendar day: the first punch and the last punch.

    `retap_minutes` is accepted so older callers keep working. Middle punches are discarded
    either way. `max_session_hours` only decides whether the next day's first punch can close
    a day that has no other punch.
    """
    del retap_minutes
    kept = collapse_taps(taps, debounce_minutes, 0)
    by_day: dict = {}
    for stamp, state in kept:
        by_day.setdefault(stamp.date(), []).append((stamp, state))
    days = sorted(by_day)
    limit = max(0.0, float(max_session_hours)) * 3600.0
    consumed: set = set()
    sessions: list[tuple[datetime, datetime | None]] = []
    for index, day in enumerate(days):
        punches = [item for item in by_day[day] if item[0] not in consumed]
        if not punches:
            continue
        first = punches[0][0]
        last = punches[-1][0]
        if first != last:
            sessions.append((first, last))
            continue
        closed_by_next = None
        if index + 1 < len(days):
            nxt = by_day[days[index + 1]][0][0]
            gap = (nxt - first).total_seconds()
            if 0 < gap <= limit:
                closed_by_next = nxt
        if closed_by_next is not None:
            sessions.append((first, closed_by_next))
            consumed.add(closed_by_next)
        else:
            sessions.append((first, None))
    return sessions
