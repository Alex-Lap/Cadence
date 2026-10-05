"""Deterministic scheduler.

This is plain code, NOT the LLM. The agent calls it as a tool. Earliest-
deadline-first with effort spreading and a max-hours-per-day constraint.
Swappable for OR-Tools later behind the same signature.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from math import ceil
from datetime import date, datetime, time, timedelta

# Float slop guard. Hours are floats, so "is this task done?" is never `== 0`.
EPS = 1e-9

# Blocks are rounded to this, so the calendar shows 1.75h rather than 1.7142857h.
QUANTUM = 0.25
QUANTUM_MIN = 15

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
    """When study can happen on one day.

    `start`-`end` is the study window; `busy` holds commitments inside it
    (lectures, work) that study must go around. `max_hours` caps the total even
    if more free time exists. Without `end` or `busy`, the day is one open
    stretch from `start`, which is how every day worked before commitments.
    """

    day: date
    start: time
    max_hours: float
    end: time | None = None
    busy: list[tuple[time, time]] = field(default_factory=list)

    def free_segments(self, extra: list[tuple[int, int]] = ()) -> list[list[int]]:
        """Free stretches as [start, end] in minutes after midnight, snapped
        to the 15-minute grid, with anything shorter than 15 minutes dropped."""
        lo = _minutes(self.start)
        hi = _minutes(self.end) if self.end else 24 * 60 - 1
        obstacles = sorted([(_minutes(a), _minutes(b)) for a, b in self.busy] + list(extra))
        segments: list[list[int]] = []
        cursor = lo
        for a, b in obstacles:
            if b <= cursor or a >= hi:
                continue
            if a > cursor:
                segments.append([cursor, min(a, hi)])
            cursor = max(cursor, b)
        if cursor < hi:
            segments.append([cursor, hi])
        snapped = []
        for a, b in segments:
            a = -(-a // QUANTUM_MIN) * QUANTUM_MIN  # round start up to the grid
            b = b // QUANTUM_MIN * QUANTUM_MIN  # round end down
            if b - a >= QUANTUM_MIN:
                snapped.append([a, b])
        return snapped

    def capacity_hours(self) -> float:
        """Hours actually available: the free time, capped at max_hours."""
        free = sum(b - a for a, b in self.free_segments()) / 60
        return min(self.max_hours, free)


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


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _clock(minutes: int) -> time:
    minutes = max(0, min(minutes, 24 * 60 - 1))
    return time(minutes // 60, minutes % 60)


def _advance(t: time, hours: float) -> time:
    """Add `hours` to a wall-clock time, clamping at 23:59 instead of rolling
    into the next day. Clamping is a safety net, not a feature -- capacity
    should be small enough that it never fires."""
    moved = datetime.combine(date.min, t) + timedelta(minutes=round(hours * 60))
    if moved.date() > date.min:
        return time(23, 59)
    return moved.time().replace(second=0, microsecond=0)


def _relayout(blocks: list[Block], capacity: dict[date, DayCapacity]) -> list[Block]:
    """Give every block on a day a time that overlaps nothing else.

    Runs once, at the end, because hours change after placement (a remainder
    merged into a block) and cursors would otherwise have to be patched
    everywhere. Pinned blocks keep the time the user chose. Everything else is
    poured into the day's free segments -- the study window minus commitments
    and pinned blocks. A block goes whole into the first segment it fits; only if
    none can hold it is it split around the obstacle ("45 minutes before the
    lecture, the rest after").
    """
    by_day: dict[date, list[Block]] = {}
    for b in blocks:
        by_day.setdefault(b.day, []).append(b)

    out: list[Block] = []
    for day, items in by_day.items():
        fixed = [b for b in items if b.pinned]
        movable = sorted((b for b in items if not b.pinned), key=lambda b: b.start_time)
        out.extend(fixed)
        if not movable:
            continue

        cap = capacity.get(day) or DayCapacity(
            day=day, start=min(b.start_time for b in items), max_hours=24
        )
        pinned_spans = [
            (_minutes(f.start_time), _minutes(f.start_time) + round(f.hours * 60)) for f in fixed
        ]
        segments = cap.free_segments(pinned_spans)

        for b in movable:
            need = round(b.hours * 60)

            whole = next((seg for seg in segments if seg[1] - seg[0] >= need), None)
            if whole is not None:
                out.append(replace(b, start_time=_clock(whole[0])))
                whole[0] += need
                continue

            for seg in segments:
                if need <= 0:
                    break
                room = (seg[1] - seg[0]) // QUANTUM_MIN * QUANTUM_MIN
                if room < QUANTUM_MIN:
                    continue
                take = min(room, need)
                out.append(replace(b, start_time=_clock(seg[0]), hours=take / 60))
                seg[0] += take
                need -= take

            if need > 0:
                # Capacity is computed from these same segments, so this only
                # happens through rounding. Keep the hours rather than lose them.
                last = max([seg[1] for seg in segments] + [_minutes(cap.start)])
                out.append(replace(b, start_time=_clock(last), hours=need / 60))
    return out


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
    remaining: dict[date, float] = {c.day: c.capacity_hours() for c in days}
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
                # Never a pinned block: those are the user's (or a replan
                # anchor), and growing one would silently move its end time.
                (b for b in plan.blocks if b.task_id == task.id and not b.pinned),
                key=lambda b: -b.hours,
            ):
                if remaining[block.day] >= left - EPS:
                    block.hours = _round_q(block.hours + left)
                    remaining[block.day] -= left
                    left = 0.0
                    break

        # Pass 4 -- nowhere to merge it: a short sitting beats dropping the
        # hours. Only reached when every day in the window is nearly full.
        if left > EPS:
            for day in eligible:
                if left <= EPS:
                    break
                take = min(remaining[day], left)
                if take >= QUANTUM - EPS:
                    take = min(_round_q(take), remaining[day])
                    place(task, day, take)
                    left = max(0.0, left - take)

        # Still hours left? The window is genuinely overcommitted. Keep the
        # partial placement -- doing some of it beats doing none -- but be
        # loud about the shortfall.
        if left > EPS:
            plan.unscheduled.append(task.title)

    plan.blocks = _relayout(plan.blocks, {c.day: c for c in days})
    plan.blocks.sort(key=lambda b: (b.day, b.start_time))
    return plan


@dataclass
class Churn:
    """How much a replan disturbed the previous plan.

    Counted over movable blocks only: pinned ones never move by definition. A
    block is "kept" if the new plan has one for the same task at the same day,
    time and length. Everything else in the old plan "moved"; everything else in
    the new plan is "added".
    """

    kept: int = 0
    moved: int = 0
    added: int = 0


def _sig(b: Block) -> tuple:
    return (b.task_id, b.day, b.start_time, round(b.hours, 4))


def churn(previous: list[Block], new: list[Block]) -> Churn:
    pool: dict[tuple, int] = {}
    for b in previous:
        if not b.pinned:
            pool[_sig(b)] = pool.get(_sig(b), 0) + 1
    kept = 0
    added = 0
    for b in new:
        if b.pinned:
            continue
        if pool.get(_sig(b), 0) > 0:
            pool[_sig(b)] -= 1
            kept += 1
        else:
            added += 1
    return Churn(kept=kept, moved=sum(pool.values()), added=added)


def _anchors(
    previous: list[Block],
    tasks: list[Task],
    capacity: list[DayCapacity],
    pinned: list[Block],
    max_lead_days: int,
) -> list[Block]:
    """Previous blocks that are still valid exactly where they are.

    A block stays only if its task still exists and still needs the hours, its
    day is still available and inside the task's window, and its exact time
    slot is still free -- inside the study window, clear of commitments, pinned
    blocks and the other anchors, and within the day's hour cap.
    """
    by_task = {t.id: t for t in tasks}
    by_day = {c.day: c for c in capacity}
    budget = {t.id: t.hours for t in tasks}
    taken: dict[date, list[tuple[int, int]]] = {}
    used: dict[date, float] = {}
    for p in pinned:
        start = _minutes(p.start_time)
        taken.setdefault(p.day, []).append((start, start + round(p.hours * 60)))
        used[p.day] = used.get(p.day, 0.0) + p.hours

    kept: list[Block] = []
    for b in sorted(previous, key=lambda b: (b.day, b.start_time)):
        task = by_task.get(b.task_id or "")
        cap = by_day.get(b.day)
        if b.pinned or task is None or cap is None:
            continue
        lead_bound = task.due - timedelta(days=max_lead_days)
        begin = max(lead_bound, task.earliest_start or lead_bound)
        if not begin <= b.day <= task.due:
            continue
        if b.hours > budget[task.id] + EPS:
            continue
        if used.get(b.day, 0.0) + b.hours > cap.capacity_hours() + EPS:
            continue
        lo = _minutes(b.start_time)
        hi = lo + round(b.hours * 60)
        segments = cap.free_segments(taken.get(b.day, []))
        if not any(a <= lo and hi <= z for a, z in segments):
            continue
        kept.append(replace(b, pinned=True))  # immovable while the rest is placed
        budget[task.id] -= b.hours
        taken.setdefault(b.day, []).append((lo, hi))
        used[b.day] = used.get(b.day, 0.0) + b.hours
    return kept


def replan(
    previous: list[Block],
    tasks: list[Task],
    capacity: list[DayCapacity],
    *,
    pinned: list[Block] | None = None,
    min_block_hours: float = 1.0,
    max_lead_days: int = MAX_LEAD_DAYS,
) -> tuple[Plan, Churn]:
    """Rebuild the schedule while moving as little of the previous one as possible.

    Every previous block that is still valid stays exactly where it was; only
    the hours that lost their place (a new commitment, a moved due date, a new
    assignment) are scheduled afresh. If holding those blocks in place would
    leave work unscheduled that a clean rebuild could fit, stability loses and
    the clean rebuild wins -- a calm plan that misses a deadline is worse.
    """
    pinned = pinned or []
    kw = dict(min_block_hours=min_block_hours, max_lead_days=max_lead_days)
    fresh = build_schedule(tasks, capacity, pinned=pinned, **kw)

    anchors = _anchors(previous, tasks, capacity, pinned, max_lead_days)
    if not anchors:
        return fresh, churn(previous, fresh.blocks)

    def placed(plan: Plan) -> float:
        return sum(b.hours for b in plan.blocks if not b.pinned)

    def attempt(held_blocks: list[Block]) -> Plan:
        anchors_now = [replace(a) for a in held_blocks]  # fresh copies each try
        held: dict[str, float] = {}
        for a in anchors_now:
            held[a.task_id] = held.get(a.task_id, 0.0) + a.hours
        rest = [
            replace(t, hours=t.hours - held.get(t.id, 0.0))
            for t in tasks
            if t.hours - held.get(t.id, 0.0) > EPS
        ]
        plan = build_schedule(rest, capacity, pinned=pinned + anchors_now, **kw)
        # Anchors come back marked pinned; they're ordinary blocks again.
        ids = {id(a) for a in anchors_now}
        for b in plan.blocks:
            if id(b) in ids:
                b.pinned = False
        return plan

    def window(t: Task) -> tuple[date, date]:
        lead = t.due - timedelta(days=max_lead_days)
        return max(lead, t.earliest_start or lead), t.due

    by_title = {t.title: t for t in tasks}
    by_id = {t.id: t for t in tasks}
    target = placed(fresh)

    # Hold everything that still fits. If that strands work a clean rebuild
    # could place, release held blocks one at a time -- always the one whose
    # task is due last, from inside the stranded task's window -- and retry.
    # A tight week costs a couple of moves, not a reshuffle of the month.
    while True:
        stable = attempt(anchors)
        if placed(stable) >= target - EPS:
            return stable, churn(previous, stable.blocks)
        stranded = [by_title[n] for n in stable.unscheduled if n in by_title]
        victim = None
        for t in sorted(stranded, key=lambda t: t.due):
            lo, hi = window(t)
            in_window = [a for a in anchors if lo <= a.day <= hi and a.task_id != t.id]
            if in_window:
                victim = max(
                    in_window, key=lambda a: (by_id[a.task_id].due, a.day, a.start_time)
                )
                break
        if victim is None:
            return fresh, churn(previous, fresh.blocks)
        anchors = [a for a in anchors if a is not victim]
