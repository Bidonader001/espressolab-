"""Turn a person's raw punches into work sessions. Plain rules, no guessing.

Punches are paired in time order. The in/out flag some terminals attach is used only as a hint
for repeat taps, because it is not reliable on its own: some terminals label punches by the time
of day, so the flag cannot decide who is arriving and who is leaving.

1. Identical timestamps collapse to one punch.
2. A tap within `debounce_minutes` of the previously kept punch is the same tap recorded twice
   (these terminals often log one tap two seconds apart). It is ignored for the calculation and
   stays stored.
3. A tap carrying the same in/out flag as the previously kept punch, within `retap_minutes` of it,
   is a person tapping again (two check-ins at 09:05 and 09:07 mean one arrival at 09:05). The
   later one is ignored for the calculation and stays stored. Without a known flag this rule
   does nothing.
4. Walking forward, a punch opens a session and the next punch closes it, provided the gap is at
   most `max_session_hours`. A longer gap means the closing punch is missing, so the session stays
   open and the next punch starts a new one. This also stops one forgotten punch from flipping
   every later pair.

Sessions may cross midnight. Each session belongs to the day of its clock-in.
"""

from __future__ import annotations

from datetime import datetime

# ZKTeco punch states: 0 check-in, 1 check-out, 2 break-out, 3 break-in, 4 overtime-in, 5 overtime-out.
IN_STATES = {0, 3, 4}
OUT_STATES = {1, 2, 5}

Tap = tuple[datetime, int | None]


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


def collapse_taps(taps, debounce_minutes: float, retap_minutes: float = 0.0) -> list[Tap]:
    kept: list[Tap] = []
    debounce = max(0.0, float(debounce_minutes)) * 60.0
    retap = max(0.0, float(retap_minutes)) * 60.0
    for stamp, state in _normalise(taps):
        if kept:
            gap = (stamp - kept[-1][0]).total_seconds()
            if gap <= debounce:
                continue
            same_way = direction(state) is not None and direction(state) == direction(kept[-1][1])
            if same_way and gap <= retap:
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
    kept = [stamp for stamp, _state in collapse_taps(taps, debounce_minutes, retap_minutes)]
    return pair_punches(kept, max_session_hours)
