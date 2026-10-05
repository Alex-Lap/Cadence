"""Replanning keeps what still works and moves only what has to."""

from dataclasses import replace
from datetime import date, time, timedelta

from app.scheduler.core import (
    Block,
    DayCapacity,
    Task,
    build_schedule,
    churn,
    replan,
)

START = date(2026, 10, 5)  # a Monday


def cap(days=21, hours=4.0, busy=None):
    busy = busy or {}
    return [
        DayCapacity(
            day=START + timedelta(days=i),
            start=time(18),
            end=time(23),
            max_hours=hours,
            busy=busy.get(START + timedelta(days=i), []),
        )
        for i in range(days)
    ]


TASKS = [
    Task(id="p1", title="Project 1", due=START + timedelta(days=6), hours=6),
    Task(id="p2", title="Project 2", due=START + timedelta(days=13), hours=8),
    Task(id="p3", title="Project 3", due=START + timedelta(days=20), hours=6),
]


def sig(blocks):
    return sorted((b.task_id, b.day, b.start_time, b.hours) for b in blocks if not b.pinned)


def test_nothing_changed_means_nothing_moves():
    before = build_schedule(TASKS, cap()).blocks
    plan, c = replan(before, TASKS, cap())
    assert sig(plan.blocks) == sig(before)
    assert (c.kept, c.moved, c.added) == (len(before), 0, 0)


def test_a_new_commitment_moves_only_the_blocks_it_hits():
    before = build_schedule(TASKS, cap()).blocks
    hit = before[len(before) // 2]
    busy = {hit.day: [(time(18), time(23))]}  # that whole evening is gone
    plan, c = replan(before, TASKS, cap(busy=busy))

    on_that_day = [b for b in before if b.day == hit.day]
    assert c.moved == len(on_that_day)
    assert c.kept == len(before) - len(on_that_day)
    assert all(b.day != hit.day for b in plan.blocks)
    assert sum(b.hours for b in plan.blocks) == sum(t.hours for t in TASKS)


def test_a_pulled_in_deadline_moves_only_that_tasks_late_blocks():
    before = build_schedule(TASKS, cap()).blocks
    p2_days = sorted(b.day for b in before if b.task_id == "p2")
    new_due = p2_days[-1] - timedelta(days=1)
    tasks = [replace(t, due=new_due) if t.id == "p2" else t for t in TASKS]
    plan, c = replan(before, tasks, cap())

    assert all(b.day <= new_due for b in plan.blocks if b.task_id == "p2")
    untouched = [b for b in before if b.task_id != "p2"]
    kept_sigs = sig(plan.blocks)
    # Other tasks' blocks stay put unless displaced by p2's moved hours.
    assert sum(1 for s in sig(untouched) if s in kept_sigs) >= len(untouched) - 2
    assert c.moved >= 1


def test_a_new_assignment_is_added_without_reshuffling_everything():
    before = build_schedule(TASKS, cap()).blocks
    tasks = TASKS + [Task(id="hw", title="HW", due=START + timedelta(days=17), hours=2)]
    plan, c = replan(before, tasks, cap())
    assert c.moved == 0
    assert c.added >= 1
    assert sum(b.hours for b in plan.blocks if b.task_id == "hw") == 2


def test_stability_never_costs_a_deadline():
    """Holding old blocks must not leave urgent new work unscheduled when a
    clean rebuild could fit it."""
    days = cap(days=4, hours=2)
    old = [Task(id="old", title="Old", due=START + timedelta(days=3), hours=8)]
    before = build_schedule(old, days).blocks  # fills every evening
    urgent = Task(id="new", title="Urgent", due=START + timedelta(days=1), hours=4)
    tasks = [replace(old[0], hours=4), urgent]
    plan, _ = replan(before, tasks, days)
    assert not plan.unscheduled
    assert sum(b.hours for b in plan.blocks if b.task_id == "new") == 4


def test_finished_work_releases_its_blocks():
    before = build_schedule(TASKS, cap()).blocks
    tasks = [t for t in TASKS if t.id != "p1"]
    plan, c = replan(before, tasks, cap())
    assert not any(b.task_id == "p1" for b in plan.blocks)
    assert c.moved == sum(1 for b in before if b.task_id == "p1")
    assert c.added == 0


def test_pinned_blocks_are_left_alone_and_not_counted():
    before = build_schedule(TASKS, cap()).blocks
    pin = Block("p2", "Project 2", START + timedelta(days=9), time(19), 2.0, pinned=True)
    tasks = [replace(t, hours=t.hours - 2) if t.id == "p2" else t for t in TASKS]
    plan, c = replan(before, tasks, cap(), pinned=[pin])
    assert pin in plan.blocks
    assert c.kept + c.moved == len(before)


def test_remainder_merge_never_grows_a_pinned_block():
    pin = Block("a", "A", START, time(18), 2.0, pinned=True)
    plan = build_schedule(
        [Task(id="a", title="A", due=START + timedelta(days=2), hours=0.5)],
        cap(days=3),
        pinned=[pin],
    )
    assert pin.hours == 2.0
    assert sum(b.hours for b in plan.blocks if not b.pinned) == 0.5


def test_churn_counts():
    a = Block("x", "X", START, time(18), 1.0)
    b = Block("x", "X", START, time(19), 1.0)
    c = Block("x", "X", START + timedelta(days=1), time(18), 1.0)
    result = churn([a, b], [a, c])
    assert (result.kept, result.moved, result.added) == (1, 1, 1)


def test_a_tight_week_releases_a_few_blocks_not_the_whole_plan():
    """Every evening is full. Blocking one evening strands urgent work that can
    only fit by bumping something due later -- that should cost a couple of
    moves, not a fresh rebuild of every block."""
    days = cap(days=14, hours=4)
    tasks = [
        Task(id="p1", title="P1", due=START + timedelta(days=4), hours=10),
        Task(id="p2", title="P2", due=START + timedelta(days=13), hours=30),
    ]
    before = build_schedule(tasks, days).blocks
    p1_day = next(b.day for b in before if b.task_id == "p1")
    busy = {p1_day: [(time(18), time(23))]}
    plan, c = replan(before, tasks, cap(days=14, hours=4, busy=busy))

    assert not plan.unscheduled
    assert sum(b.hours for b in plan.blocks if b.task_id == "p1") == 10
    on_blocked_day = sum(1 for b in before if b.day == p1_day)
    assert c.moved <= on_blocked_day + 2, c
    assert c.kept >= len(before) - on_blocked_day - 2
