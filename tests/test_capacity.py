from datetime import date, time, timedelta
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


def commit(start, end, weekday=None, on_date=None, starts_on=None, ends_on=None):
    return SimpleNamespace(
        weekday=weekday,
        on_date=on_date,
        starts_on=starts_on,
        ends_on=ends_on,
        start_time=time.fromisoformat(start),
        end_time=time.fromisoformat(end),
    )


MONDAY = date(2026, 9, 28)


def test_defaults_are_unchanged_without_settings_or_commitments():
    caps = build_capacity(MONDAY, 1, default_hours=4)
    assert caps[0].start == time(18, 0) and caps[0].end is None and caps[0].busy == []
    assert caps[0].capacity_hours() == 4


def test_study_window_is_applied():
    caps = build_capacity(MONDAY, 1, window_start=time(9), window_end=time(12), default_hours=8)
    assert caps[0].start == time(9) and caps[0].end == time(12)
    assert caps[0].capacity_hours() == 3


def test_weekly_commitment_lands_on_its_weekday_only():
    caps = build_capacity(MONDAY, 7, commitments=[commit("18:00", "20:40", weekday=0)])
    busy = {c.day.weekday(): c.busy for c in caps}
    assert busy[0] == [(time(18), time(20, 40))]
    assert all(busy[d] == [] for d in range(1, 7))


def test_commitment_outside_its_term_is_ignored():
    c = commit("18:00", "20:00", weekday=0, starts_on=MONDAY + timedelta(days=7))
    caps = build_capacity(MONDAY, 14, commitments=[c])
    mondays = [cap for cap in caps if cap.day.weekday() == 0]
    assert mondays[0].busy == [] and mondays[1].busy != []


def test_one_off_commitment():
    c = commit("19:00", "21:00", on_date=MONDAY + timedelta(days=2))
    caps = build_capacity(MONDAY, 7, commitments=[c])
    assert [cap.day for cap in caps if cap.busy] == [MONDAY + timedelta(days=2)]


def test_commitments_reduce_capacity():
    caps = build_capacity(
        MONDAY, 1, window_start=time(18), window_end=time(23), default_hours=5,
        commitments=[commit("18:00", "20:00", weekday=0)],
    )
    assert caps[0].capacity_hours() == 3


def test_day_off_range_covers_every_day_in_it():
    off = commit("00:00", "23:59", on_date=MONDAY + timedelta(days=2),
                 ends_on=MONDAY + timedelta(days=4))
    caps = build_capacity(MONDAY, 7, commitments=[off])
    zero = [c.day for c in caps if c.capacity_hours() == 0]
    assert zero == [MONDAY + timedelta(days=d) for d in (2, 3, 4)]


def test_hosted_postgres_urls_use_psycopg3():
    from app.config import Settings

    for raw in ("postgres://u:p@h/db?sslmode=require", "postgresql://u:p@h/db?sslmode=require"):
        assert Settings(database_url=raw).database_url == "postgresql+psycopg://u:p@h/db?sslmode=require"
    already = "postgresql+psycopg://u:p@h/db"
    assert Settings(database_url=already).database_url == already
