from datetime import date, time
from types import SimpleNamespace

from app.scheduler.capacity import build_capacity


def avail(weekday, start="18:00", end="22:00", max_hours=None):
    return SimpleNamespace(
        weekday=weekday,
        start_time=time.fromisoformat(start),
        end_time=time.fromisoformat(end),
        max_hours=max_hours,
    )


def test_no_availability_gives_every_day_the_default():
    caps = build_capacity(date(2026, 9, 28), 7, default_hours=3)
    assert len(caps) == 7
    assert all(c.max_hours == 3 for c in caps)


def test_availability_limits_which_weekdays_appear():
    caps = build_capacity(date(2026, 9, 28), 14, availability=[avail(0), avail(2)])
    assert {c.day.weekday() for c in caps} == {0, 2}
    assert len(caps) == 4


def test_window_length_sets_hours():
    caps = build_capacity(date(2026, 9, 28), 1, availability=[avail(0, "17:30", "21:00")])
    assert caps[0].max_hours == 3.5
    assert caps[0].start == time(17, 30)


def test_explicit_max_hours_wins_over_window_length():
    caps = build_capacity(date(2026, 9, 28), 1, availability=[avail(0, "09:00", "22:00", 2)])
    assert caps[0].max_hours == 2


def test_zero_hour_days_are_dropped():
    caps = build_capacity(date(2026, 9, 28), 1, availability=[avail(0, "18:00", "18:00")])
    assert caps == []
