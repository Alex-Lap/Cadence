from datetime import date, time

import pytest

from app.ics_import import parse_ics

TODAY = date(2026, 10, 5)  # a Monday


def cal(*events: str) -> bytes:
    body = "\r\n".join(events)
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//test//EN\r\n"
        f"{body}\r\nEND:VCALENDAR\r\n"
    ).encode()


def event(uid, summary, start, end, extra=""):
    lines = [
        "BEGIN:VEVENT", f"UID:{uid}", f"SUMMARY:{summary}",
        f"DTSTART{start}", f"DTEND{end}", "DTSTAMP:20260901T000000Z",
    ]
    if extra:
        lines += extra.split("|")
    lines.append("END:VEVENT")
    return "\r\n".join(lines)


def test_weekly_shift_becomes_one_commitment_per_weekday():
    data = cal(event("w1", "Work", ";TZID=America/New_York:20260907T170000",
                     ";TZID=America/New_York:20260907T210000",
                     "RRULE:FREQ=WEEKLY;BYDAY=MO,WE;UNTIL=20261211T235959Z"))
    r = parse_ics(data, today=TODAY)
    weekly = [c for c in r.candidates if c.weekday is not None]
    assert [(c.weekday, c.start_time, c.end_time) for c in weekly] == [
        (0, time(17), time(21)), (2, time(17), time(21))]
    assert all(c.ends_on == date(2026, 12, 11) for c in weekly)
    assert weekly[0].starts_on == TODAY  # only the planning window is read


def test_utc_times_land_in_the_users_zone():
    data = cal(event("u1", "Dentist", ":20261008T140000Z", ":20261008T150000Z"))
    (c,) = parse_ics(data, today=TODAY).candidates
    assert (c.on_date, c.start_time, c.end_time) == (date(2026, 10, 8), time(10), time(11))


def test_one_off_and_past_events():
    data = cal(
        event("p1", "Old thing", ":20260901T100000", ":20260901T110000"),
        event("f1", "Interview", ":20261015T130000", ":20261015T140000"),
    )
    r = parse_ics(data, today=TODAY)
    assert [(c.title, c.on_date) for c in r.candidates] == [("Interview", date(2026, 10, 15))]


def test_all_day_free_and_cancelled_are_skipped():
    data = cal(
        event("a1", "Birthday", ";VALUE=DATE:20261010", ";VALUE=DATE:20261011"),
        event("t1", "Optional webinar", ":20261012T120000", ":20261012T130000", "TRANSP:TRANSPARENT"),
        event("c1", "Called off", ":20261013T120000", ":20261013T130000", "STATUS:CANCELLED"),
    )
    r = parse_ics(data, today=TODAY)
    assert r.candidates == []
    assert r.skipped == {"all-day": 1, "marked free": 1, "cancelled": 1}


def test_every_other_week_is_not_weekly():
    data = cal(event("b1", "Club", ":20261006T180000", ":20261006T190000",
                     "RRULE:FREQ=WEEKLY;INTERVAL=2;COUNT=4"))
    r = parse_ics(data, today=TODAY)
    assert all(c.weekday is None for c in r.candidates)
    assert len(r.candidates) == 4


def test_excluded_dates_are_respected():
    data = cal(event("x1", "Lab", ":20261006T090000", ":20261006T100000",
                     "RRULE:FREQ=DAILY;COUNT=3|EXDATE:20261007T090000"))
    r = parse_ics(data, today=TODAY)
    assert [c.on_date for c in r.candidates] == [date(2026, 10, 6), date(2026, 10, 8)]


def test_garbage_is_a_clear_error():
    with pytest.raises(ValueError):
        parse_ics(b"not a calendar", today=TODAY)
