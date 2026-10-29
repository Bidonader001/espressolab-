"""Hours and session rules, built from the punch patterns seen on real terminals."""

from __future__ import annotations

from datetime import datetime

from test_app import _device
from test_market_ready import _load

from app.services.pairing import build_sessions, pair_punches, remove_duplicate_taps


def _t(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _log(user: str, *stamps: str) -> list[dict]:
    return [{"user_id": user, "punched_at": stamp, "punch": index % 2} for index, stamp in enumerate(stamps)]


def _rows(client, auth, start="2026-10-01", end="2026-10-04"):
    body = client.get(
        "/api/v1/attendance",
        headers=auth,
        params={"start_date": start, "end_date": end, "source": "device", "page_size": 200},
    ).json()
    return {(row["employee_id"], row["date_iso"]): row for row in body["items"]}, body["summary"]


def test_repeat_taps_collapse_but_real_short_gaps_do_not():
    taps = [_t("2026-10-01T17:43:06"), _t("2026-10-01T17:43:08"), _t("2026-10-01T17:43:08")]
    assert remove_duplicate_taps(taps, 2) == [_t("2026-10-01T17:43:06")]
    spaced = [_t("2026-10-01T08:00:00"), _t("2026-10-01T08:01:59"), _t("2026-10-01T08:04:00"), _t("2026-10-01T08:04:30")]
    assert remove_duplicate_taps(spaced, 2) == [_t("2026-10-01T08:00:00"), _t("2026-10-01T08:04:00")]
    assert remove_duplicate_taps(spaced, 0) == sorted(set(spaced))
    # A tap exactly at the window edge is a repeat. One second later is a separate tap.
    edge = [_t("2026-10-01T08:00:00"), _t("2026-10-01T08:02:00"), _t("2026-10-01T08:04:01")]
    assert remove_duplicate_taps(edge, 2) == [_t("2026-10-01T08:00:00"), _t("2026-10-01T08:04:01")]


def test_same_flag_retap_is_not_a_session_but_opposite_flags_still_pair():
    # Real case: check-in 09:05, check-in again 09:07, check-out 17:14 is one 8.15 hour day.
    morning = [(_t("2026-10-12T09:05:55"), 0), (_t("2026-10-12T09:07:58"), 0), (_t("2026-10-12T17:14:04"), 1)]
    assert build_sessions(morning, 2, 12, 30) == [(_t("2026-10-12T09:05:55"), _t("2026-10-12T17:14:04"))]
    # With the rule off, the old behaviour (a two-minute session and a dangling check-out) returns.
    assert build_sessions(morning, 2, 12, 0) == [
        (_t("2026-10-12T09:05:55"), _t("2026-10-12T09:07:58")),
        (_t("2026-10-12T17:14:04"), None),
    ]
    # An in followed by an out a few minutes later is a real short session, kept.
    short = [(_t("2026-10-12T09:00:00"), 0), (_t("2026-10-12T09:10:00"), 1)]
    assert build_sessions(short, 2, 12, 30) == [(short[0][0], short[1][0])]
    # Unknown flags never trigger the rule.
    unknown = [(_t("2026-10-12T09:00:00"), None), (_t("2026-10-12T09:10:00"), None)]
    assert build_sessions(unknown, 2, 12, 30) == [(unknown[0][0], unknown[1][0])]
    # The same flag later than the window is not a re-tap: the pair still forms by time order.
    late = [(_t("2026-10-12T09:00:00"), 0), (_t("2026-10-12T09:31:00"), 0)]
    assert build_sessions(late, 2, 12, 30) == [(late[0][0], late[1][0])]
    # Taps chained within the window of the kept punch are all re-taps.
    chain = [(_t("2026-10-12T09:00:00"), 0), (_t("2026-10-12T09:20:00"), 0), (_t("2026-10-12T09:40:00"), 0)]
    assert build_sessions(chain, 2, 12, 30) == [(chain[0][0], chain[2][0])]


def test_a_retapped_check_in_still_counts_the_whole_day(client, auth):
    device = _device(client, auth, name="HQ")
    logs = [
        {"user_id": "9", "punched_at": "2026-10-01T09:05:00", "punch": 0},
        {"user_id": "9", "punched_at": "2026-10-01T09:08:00", "punch": 0},
        {"user_id": "9", "punched_at": "2026-10-01T17:00:00", "punch": 1},
    ]
    _load(client, auth, device["id"], [{"user_id": "9", "name": "Rita Retap"}], logs)
    rows, summary = _rows(client, auth)
    day = rows[("9", "2026-10-01")]
    assert day["check_in"] == "09:05" and day["check_out"] == "17:00"
    assert day["hours"] == 7.92 and day["status"] in {"Present", "Late"}
    assert next(row for row in summary if row["employee_id"] == "9")["total_hours"] == 7.92

    off = client.put("/api/v1/settings", headers=auth, json={"retap_window_minutes": 0})
    assert off.status_code == 200 and isinstance(off.json()["recalculated_sessions"], int)
    assert _rows(client, auth)[0][("9", "2026-10-01")]["status"] == "Incomplete"
    client.put("/api/v1/settings", headers=auth, json={"retap_window_minutes": 30})
    assert _rows(client, auth)[0][("9", "2026-10-01")]["hours"] == 7.92


def test_a_long_gap_leaves_a_session_open_instead_of_flipping_every_later_pair():
    stamps = [_t("2026-10-01T09:00:00"), _t("2026-10-02T09:00:00"), _t("2026-10-02T17:00:00")]
    assert pair_punches(stamps, 12) == [
        (_t("2026-10-01T09:00:00"), None),
        (_t("2026-10-02T09:00:00"), _t("2026-10-02T17:00:00")),
    ]
    edge = [_t("2026-10-01T08:00:00"), _t("2026-10-01T20:00:00")]
    assert pair_punches(edge, 12) == [(edge[0], edge[1])]
    over = [_t("2026-10-01T08:00:00"), _t("2026-10-01T20:00:01")]
    assert pair_punches(over, 12) == [(over[0], None), (over[1], None)]


def test_double_taps_do_not_create_phantom_sessions(client, auth):
    device = _device(client, auth, name="Kitchen")
    logs = _log("1", "2026-10-01T08:00:00", "2026-10-01T08:00:02", "2026-10-01T16:00:00", "2026-10-01T16:00:03")
    _load(client, auth, device["id"], [{"user_id": "1", "name": "Dina Doubletap"}], logs)
    rows, _summary = _rows(client, auth)
    day = rows[("1", "2026-10-01")]
    assert day["hours"] == 8.0
    assert day["check_in"] == "08:00" and day["check_out"] == "16:00"
    assert day["status"] == "Present"


def test_shift_across_midnight_is_one_session_on_the_clock_in_day(client, auth):
    device = _device(client, auth, name="Kitchen")
    logs = _log("2", "2026-10-01T22:00:00", "2026-10-02T06:00:00")
    _load(client, auth, device["id"], [{"user_id": "2", "name": "Nadia Night"}], logs)
    rows, _summary = _rows(client, auth)
    day = rows[("2", "2026-10-01")]
    assert day["hours"] == 8.0
    assert day["check_in"] == "22:00" and day["check_out"] == "06:00"
    # 02/10 is a Friday. The morning punch must not become a second broken day, only a plain Weekend row.
    assert rows[("2", "2026-10-02")]["status"] == "Weekend" and rows[("2", "2026-10-02")]["hours"] is None


def test_forgotten_checkout_is_reported_and_does_not_break_the_next_day(client, auth):
    device = _device(client, auth, name="Kitchen")
    logs = _log("3", "2026-10-01T09:00:00") + _log("3", "2026-10-04T09:00:00", "2026-10-04T17:00:00")
    _load(client, auth, device["id"], [{"user_id": "3", "name": "Fouad Forgot"}], logs)
    rows, _summary = _rows(client, auth)
    assert rows[("3", "2026-10-01")]["status"] == "Incomplete"
    assert rows[("3", "2026-10-01")]["hours"] is None
    assert rows[("3", "2026-10-04")]["hours"] == 8.0
    assert rows[("3", "2026-10-04")]["status"] in {"Present", "Late"}


def test_an_incomplete_day_shows_no_hours_and_adds_nothing_to_the_total(client, auth):
    device = _device(client, auth, name="Kitchen")
    # 08:00-12:00 closes, 13:00 has no check-out: the day is Incomplete even though part of it is paired.
    logs = _log("10", "2026-10-01T08:00:00", "2026-10-01T12:00:00", "2026-10-01T13:00:00")
    logs += _log("10", "2026-10-04T08:00:00", "2026-10-04T16:00:00")
    _load(client, auth, device["id"], [{"user_id": "10", "name": "Ivy Incomplete"}], logs)
    rows, summary = _rows(client, auth)
    broken = rows[("10", "2026-10-01")]
    assert broken["status"] == "Incomplete" and broken["hours"] is None and broken["check_out"] == ""
    assert rows[("10", "2026-10-04")]["hours"] == 8.0
    person = next(row for row in summary if row["employee_id"] == "10")
    assert person["total_hours"] == 8.0


def test_twelve_hours_pairs_and_one_second_more_does_not(client, auth):
    device = _device(client, auth, name="Kitchen")
    logs = _log("4", "2026-10-01T08:00:00", "2026-10-01T20:00:00") + _log("5", "2026-10-01T08:00:00", "2026-10-01T20:00:01")
    users = [{"user_id": "4", "name": "Omar Exact"}, {"user_id": "5", "name": "Samir Over"}]
    _load(client, auth, device["id"], users, logs)
    rows, _summary = _rows(client, auth)
    assert rows[("4", "2026-10-01")]["hours"] == 12.0
    assert rows[("5", "2026-10-01")]["status"] == "Incomplete"
    assert rows[("5", "2026-10-01")]["hours"] is None


def test_working_time_is_checkout_minus_checkin_in_whole_minutes(client, auth):
    device = _device(client, auth, name="Kitchen")
    logs = _log(
        "6",
        "2026-10-01T08:00:00", "2026-10-01T12:00:30",  # 4:00:30 -> 241 minutes (30 seconds rounds up)
        "2026-10-01T13:00:00", "2026-10-01T17:00:29",  # 4:00:29 -> 240 minutes
        "2026-10-04T09:46:28", "2026-10-04T17:29:53",  # 7:43:25 -> 463 minutes
    )
    _load(client, auth, device["id"], [{"user_id": "6", "name": "Rana Rounding"}], logs)
    rows, summary = _rows(client, auth)
    first, second = rows[("6", "2026-10-01")], rows[("6", "2026-10-04")]
    assert first["hours_text"] == "8:01" and first["hours_minutes"] == 481
    assert second["hours_text"] == "7:43" and second["hours_minutes"] == 463
    assert second["hours"] == 7.72, "the decimal is only another view of the same 463 minutes"
    person = next(row for row in summary if row["employee_id"] == "6")
    assert person["total_minutes"] == 481 + 463 and person["total_text"] == "15:44"
    assert person["total_hours"] == round(944 / 60, 2)


def test_every_hours_value_in_every_export_is_hours_and_minutes(client, auth):
    device = _device(client, auth, name="Kitchen")
    logs = _log("11", "2026-10-01T09:46:28", "2026-10-01T17:29:53")
    _load(client, auth, device["id"], [{"user_id": "11", "name": "Omar Minutes"}], logs)
    params = {"start_date": "2026-10-01", "end_date": "2026-10-01", "source": "device"}
    for report in ("monthly", "daily", "hours"):
        text = client.get("/api/v1/exports", headers=auth, params={**params, "report": report, "format": "csv"}).content.decode("utf-8-sig")
        line = next(row for row in text.splitlines() if row.startswith("11,"))
        assert ",7:43," in line and "7.72" not in line and "7.7" not in line, report


def test_changing_a_pairing_rule_recalculates_from_stored_punches(client, auth):
    device = _device(client, auth, name="Kitchen")
    logs = _log("7", "2026-10-01T08:00:00", "2026-10-01T16:00:00")
    _load(client, auth, device["id"], [{"user_id": "7", "name": "Sami Setting"}], logs)
    assert _rows(client, auth)[0][("7", "2026-10-01")]["hours"] == 8.0

    shorter = client.put("/api/v1/settings", headers=auth, json={"max_session_hours": 6})
    assert shorter.status_code == 200, shorter.text
    assert isinstance(shorter.json()["recalculated_sessions"], int)
    assert _rows(client, auth)[0][("7", "2026-10-01")]["status"] == "Incomplete"

    restored = client.put("/api/v1/settings", headers=auth, json={"max_session_hours": 12})
    assert restored.status_code == 200, restored.text
    assert _rows(client, auth)[0][("7", "2026-10-01")]["hours"] == 8.0

    unrelated = client.put("/api/v1/settings", headers=auth, json={"grace_minutes": 12})
    assert unrelated.json()["recalculated_sessions"] is None


def test_raw_punches_survive_every_recalculation(client, auth):
    device = _device(client, auth, name="Kitchen")
    logs = _log("8", "2026-10-01T08:00:00", "2026-10-01T08:00:02", "2026-10-01T16:00:00")
    _load(client, auth, device["id"], [{"user_id": "8", "name": "Pia Preserved"}], logs)
    client.put("/api/v1/settings", headers=auth, json={"punch_debounce_minutes": 5})
    stored = client.get(f"/api/v1/devices/{device['id']}/punches", headers=auth).json()["items"]
    assert len(stored) == 3, "the repeat tap is ignored by the calculation and still stored"
    assert len(build_sessions([_t(row["punched_at"].replace(" ", "T")) for row in stored], 2, 12)) == 1
