"""Week 1 acceptance tests for the deterministic scheduler.

These are written before the implementation on purpose: they are the spec.
"""

from datetime import date, time

import pytest

from app.scheduler.core import DayCapacity, Task, build_schedule


def cap(days: int, hours: float = 4.0, start: date = date(2026, 9, 14)) -> list[DayCapacity]:
    return [
        DayCapacity(day=date.fromordinal(start.toordinal() + i), start=time(18, 0), max_hours=hours)
        for i in range(days)
    ]


def test_places_all_hours_before_due_date():
    tasks = [Task(id="a", title="PS1", due=date(2026, 9, 17), hours=6)]
    plan = build_schedule(tasks, cap(7))
    assert sum(b.hours for b in plan.blocks) == 6
    assert all(b.day <= date(2026, 9, 17) for b in plan.blocks)
    assert not plan.unscheduled

def test_respects_max_hours_per_day():
    tasks = [Task(id="a", title="Big", due=date(2026, 9, 20), hours=12)]
    plan = build_schedule(tasks, cap(7, hours=3))
    by_day: dict[date, float] = {}
    for b in plan.blocks:
        by_day[b.day] = by_day.get(b.day, 0) + b.hours
    assert max(by_day.values()) <= 3


def test_earliest_deadline_first():
    tasks = [
        Task(id="late", title="Late", due=date(2026, 9, 25), hours=4),
        Task(id="soon", title="Soon", due=date(2026, 9, 15), hours=4),
    ]
    plan = build_schedule(tasks, cap(14, hours=2))
    first = min(plan.blocks, key=lambda b: (b.day, b.start_time))
    assert first.task_id == "soon"


def test_overcommitted_reports_unscheduled():
    tasks = [Task(id="a", title="Impossible", due=date(2026, 9, 15), hours=40)]
    plan = build_schedule(tasks, cap(2, hours=2))
    assert plan.unscheduled == ["Impossible"]


def test_work_never_starts_before_the_handout_date():
    """The bug the first real run exposed: Project 5 is handed out in November
    and was being scheduled in September."""
    tasks = [
        Task(
            id="p5",
            title="Project 5",
            due=date(2026, 9, 25),
            hours=6,
            earliest_start=date(2026, 9, 20),
        )
    ]
    plan = build_schedule(tasks, cap(20, hours=4, start=date(2026, 9, 14)))
    assert plan.blocks, "should still schedule something"
    assert min(b.day for b in plan.blocks) >= date(2026, 9, 20)
    assert max(b.day for b in plan.blocks) <= date(2026, 9, 25)


def test_no_earliest_start_means_start_today():
    tasks = [Task(id="a", title="A", due=date(2026, 9, 20), hours=4)]
    plan = build_schedule(tasks, cap(10))
    assert min(b.day for b in plan.blocks) == date(2026, 9, 14)


def test_blocks_are_chunky_not_smeared():
    """9 hours over a 21-day window should be a handful of real sittings, not
    21 twenty-minute slivers."""
    tasks = [Task(id="a", title="A", due=date(2026, 10, 4), hours=9)]
    plan = build_schedule(tasks, cap(21, hours=4))
    assert len(plan.blocks) <= 6
    assert min(b.hours for b in plan.blocks) >= 1.0


def test_hours_and_start_times_are_clean():
    tasks = [
        Task(id="a", title="A", due=date(2026, 10, 4), hours=8.75),
        Task(id="b", title="B", due=date(2026, 10, 4), hours=6.5),
    ]
    plan = build_schedule(tasks, cap(21, hours=4))
    for b in plan.blocks:
        assert (b.hours * 4) % 1 == 0, f"{b.hours} is not a quarter hour"
        assert b.start_time.second == 0 and b.start_time.microsecond == 0
        assert b.start_time.minute % 15 == 0, b.start_time


def test_spread_leaves_buffer_before_the_deadline():
    """Work should not all pile up against the due date."""
    tasks = [Task(id="a", title="A", due=date(2026, 10, 4), hours=8)]
    plan = build_schedule(tasks, cap(21, hours=4))
    days = sorted({b.day for b in plan.blocks})
    assert days[0] <= date(2026, 9, 16), "should start early in the window"
    assert len(days) >= 3, "should span several days"
