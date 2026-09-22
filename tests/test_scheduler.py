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
