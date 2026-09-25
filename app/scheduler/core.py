"""Deterministic scheduler.

This is plain code, NOT the LLM. The agent calls it as a tool. Earliest-
deadline-first with effort spreading and a max-hours-per-day constraint.
Swappable for OR-Tools later behind the same signature.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil
from datetime import date, datetime, time, timedelta

# Float slop guard. Hours are floats, so "is this task done?" is never `== 0`.
EPS = 1e-9

# Blocks are rounded to this, so the calendar shows 1.75h rather than 1.7142857h.
QUANTUM = 0.25

# Nobody studies for a December final in September. Work does not begin more
# than this far before its deadline, whatever the handout date says. It also
# matches the common "handed out three weeks before it's due" pattern, so it
# rarely binds on projects and almost always binds on exams.
MAX_LEAD_DAYS = 21

# How long a useful sitting is. The scheduler spreads a task over as many days
# as it needs at roughly this size, instead of smearing it across every
# available day -- 30 minutes on five projects a night is not a study plan.
PREFERRED_BLOCK_HOURS = 2.0


@dataclass
class Task:
    id: str
    title: str
    due: date
    hours: float
    weight: float | None = None
    # Earliest day work can begin -- the handout date. Without it the scheduler
    # happily books time on an assignment the student hasn't received yet.
    earliest_start: date | None = None


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


def _round_q(hours: float) -> float:
    """Snap to the nearest QUANTUM, never below it."""
    return max(QUANTUM, round(hours / QUANTUM) * QUANTUM)


def _ceil_q(hours: float) -> float:
    """Snap UP to a QUANTUM. Used for block targets: rounding the target up and
    then clamping to what's left makes the final block absorb the remainder,
    instead of leaving a 15-minute orphan block at the end."""
    return max(QUANTUM, ceil(hours / QUANTUM) * QUANTUM)


def _pick_spread(days: list[date], n: int) -> list[date]:
    """Choose n days spaced as evenly as possible across `days`.

    Picking the first n would cram everything up front and waste the buffer
    before the deadline; picking the last n would leave no slack at all.
    """
    if n >= len(days):
        return days
    if n <= 1:
        return days[:1]
    step = (len(days) - 1) / (n - 1)
    chosen = sorted({round(i * step) for i in range(n)})
    # Rounding can collide; top up with the earliest unused days.
    for i in range(len(days)):
        if len(chosen) >= n:
            break
        if i not in chosen:
            chosen = sorted(chosen + [i])
    return [days[i] for i in chosen]


def _advance(t: time, hours: float) -> time:
    """Add `hours` to a wall-clock time, clamping at 23:59 instead of rolling
    into the next day. Clamping is a safety net, not a feature -- capacity
    should be small enough that it never fires."""
    moved = datetime.combine(date.min, t) + timedelta(minutes=round(hours * 60))
    if moved.date() > date.min:
        return time(23, 59)
    return moved.time().replace(second=0, microsecond=0)


def _relayout(blocks: list[Block], day_start: dict[date, time]) -> None:
    """Give every block on a day a start time that overlaps nothing else.

    Hours can change after a block is placed -- a small remainder gets merged
    into it -- which leaves it running into whatever was placed after it. Rather
    than patch cursors everywhere hours are adjusted, lay each day out once at
    the end: pinned blocks keep the time the user chose, everything else is
    packed in order around them.
    """
    by_day: dict[date, list[Block]] = {}
    for b in blocks:
        by_day.setdefault(b.day, []).append(b)

    for day, items in by_day.items():
        fixed = [b for b in items if b.pinned]
        movable = sorted((b for b in items if not b.pinned), key=lambda b: b.start_time)
        cursor = day_start.get(day, min(b.start_time for b in items))
        for b in movable:
            collided = True
            while collided:
                collided = False
                end = _advance(cursor, b.hours)
                for f in fixed:
                    f_end = _advance(f.start_time, f.hours)
                    if cursor < f_end and f.start_time < end:
                        cursor = f_end
                        collided = True
            b.start_time = cursor
            cursor = _advance(cursor, b.hours)


def build_schedule(
    tasks: list[Task],
    capacity: list[DayCapacity],
    *,
    pinned: list[Block] | None = None,
    min_block_hours: float = 1.0,
    max_lead_days: int = MAX_LEAD_DAYS,
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

        # Start no earlier than the handout, and no earlier than the lead cap.
        lead_bound = task.due - timedelta(days=max_lead_days)
        begin = max(lead_bound, task.earliest_start or lead_bound)

        eligible = [
            c.day
            for c in days
            if begin <= c.day <= task.due and remaining[c.day] > EPS
        ]

        # Pass 1 -- spread over as many days as the work needs at roughly
        # PREFERRED_BLOCK_HOURS each, spaced across the available window.
        if eligible:
            wanted = max(1, ceil(task.hours / PREFERRED_BLOCK_HOURS))
            chosen = _pick_spread(eligible, min(wanted, len(eligible)))
            target = task.hours / len(chosen)

            for day in chosen:
                if left <= EPS:
                    break
                take = min(_ceil_q(target), remaining[day], left)
                # Absorb a sub-quantum tail rather than leaving 6 minutes over.
                if 0 < left - take < QUANTUM and remaining[day] - take >= left - take:
                    take = left
                if take < min_block_hours and take < left - EPS:
                    continue
                if take > EPS:
                    place(task, day, take)
                    left -= take

        # Pass 2 -- mop up whatever the spread left behind, earliest first, but
        # only in useful amounts.
        if left > EPS:
            for day in eligible:
                if left <= EPS:
                    break
                take = min(remaining[day], left)
                if take >= min_block_hours - EPS:
                    place(task, day, _round_q(min(take, left)))
                    left = max(0.0, left - take)

        # Pass 3 -- a remainder too small to be its own sitting is added to an
        # existing block for the same task rather than left as a 15-minute stub.
        if EPS < left < min_block_hours:
            for block in sorted(
                (b for b in plan.blocks if b.task_id == task.id),
                key=lambda b: -b.hours,
            ):
                if remaining[block.day] >= left - EPS:
                    block.hours = _round_q(block.hours + left)
                    remaining[block.day] -= left
                    left = 0.0
                    break

        # Still hours left? The window is genuinely overcommitted. Keep the
        # partial placement -- doing some of it beats doing none -- but be
        # loud about the shortfall.
        if left > EPS:
            plan.unscheduled.append(task.title)

    _relayout(plan.blocks, {c.day: c.start for c in days})
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