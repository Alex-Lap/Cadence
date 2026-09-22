"""Deterministic scheduler.

This is plain code, NOT the LLM. The agent calls it as a tool. Earliest-
deadline-first with effort spreading and a max-hours-per-day constraint.
Swappable for OR-Tools later behind the same signature.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

# Float slop guard. Hours are floats, so "is this task done?" is never `== 0`.
EPS = 1e-9


@dataclass
class Task:
    id: str
    title: str
    due: date
    hours: float
    weight: float | None = None


@dataclass
class DayCapacity:
    day: date
    start: time
    max_hours: float


@dataclass
class Block:
    task_id: str | None
    title: str | None
    day: date
    start_time: time
    hours: float
    pinned: bool = False


@dataclass
class Plan:
    blocks: list[Block] = field(default_factory=list)
    unscheduled: list[str] = field(default_factory=list)


def _advance(t: time, hours: float) -> time:
    """Add `hours` to a wall-clock time, clamping at 23:59 instead of rolling
    into the next day. Clamping is a safety net, not a feature -- capacity
    should be small enough that it never fires."""
    moved = datetime.combine(date.min, t) + timedelta(hours=hours)
    if moved.date() > date.min:
        return time(23, 59)
    return moved.time()


def build_schedule(
    tasks: list[Task],
    capacity: list[DayCapacity],
    *,
    pinned: list[Block] | None = None,
    min_block_hours: float = 0.5,
) -> Plan:
    """Assign each task's hours to days on or before its due date.

    Pinned blocks are treated as immovable: they consume capacity and are
    carried through into the returned plan untouched.
    """
    pinned = pinned or []
    days = sorted(capacity, key=lambda c: c.day)

    # Mutable per-day state: how many hours are left, and where the next
    # block on that day should start.
    remaining: dict[date, float] = {c.day: c.max_hours for c in days}
    cursor: dict[date, time] = {c.day: c.start for c in days}

    plan = Plan(blocks=list(pinned))

    # Pinned work is already spoken for -- charge it against capacity first.
    for block in pinned:
        if block.day in remaining:
            remaining[block.day] = max(0.0, remaining[block.day] - block.hours)
            cursor[block.day] = _advance(cursor[block.day], block.hours)

    def place(task: Task, day: date, hours: float) -> None:
        plan.blocks.append(
            Block(
                task_id=task.id,
                title=task.title,
                day=day,
                start_time=cursor[day],
                hours=hours,
            )
        )
        cursor[day] = _advance(cursor[day], hours)
        remaining[day] -= hours

    # Earliest deadline first; heavier assignments win ties.
    for task in sorted(tasks, key=lambda t: (t.due, -(t.weight or 0.0))):
        left = task.hours
        eligible = [c.day for c in days if c.day <= task.due and remaining[c.day] > EPS]

        # Pass 1 -- spread evenly across every day that still has room.
        if eligible:
            target = max(min_block_hours, task.hours / len(eligible))
            for day in eligible:
                if left <= EPS:
                    break
                take = min(target, remaining[day], left)
                # Skip slivers, unless the sliver finishes the task.
                if take < min_block_hours and take < left - EPS:
                    continue
                if take > EPS:
                    place(task, day, take)
                    left -= take

        # Pass 2 -- greedily mop up whatever the even spread left behind.
        if left > EPS:
            for day in (c.day for c in days if c.day <= task.due):
                if left <= EPS:
                    break
                take = min(remaining[day], left)
                if take > EPS:
                    place(task, day, take)
                    left -= take

        # Still hours left? The window is genuinely overcommitted. Keep the
        # partial placement -- doing some of it beats doing none -- but be
        # loud about the shortfall.
        if left > EPS:
            plan.unscheduled.append(task.title)

    plan.blocks.sort(key=lambda b: (b.day, b.start_time))
    return plan


def replan(
    current: Plan,
    tasks: list[Task],
    capacity: list[DayCapacity],
    *,
    unavailable_days: list[date] | None = None,
) -> Plan:
    """Reschedule around a disruption while minimizing churn.

    TODO(week3): keep every pinned and completed block, drop blocks on
    unavailable days, and only re-place the freed hours. Measure churn as the
    number of non-pinned blocks that moved; that number is the demo.
    """
    raise NotImplementedError