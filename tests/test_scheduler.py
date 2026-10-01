"""Week 1 acceptance tests for the deterministic scheduler.

These are written before the implementation on purpose: they are the spec.
"""

from datetime import date, time, timedelta

import pytest

from app.scheduler.core import Block, DayCapacity, Task, build_schedule


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


def test_exam_study_does_not_start_months_early():
    """The complaint that prompted this: a December final was being studied for
    in September, because it had a due date and no handout date."""
    tasks = [
        Task(id="final", title="Final Exam", due=date(2026, 12, 11), hours=20, weight=0.3)
    ]
    caps = [
        DayCapacity(day=date(2026, 9, 14) + timedelta(days=i), start=time(18, 0), max_hours=4)
        for i in range(120)
    ]
    plan = build_schedule(tasks, caps)
    assert plan.blocks
    assert min(b.day for b in plan.blocks) >= date(2026, 11, 20)


def test_handout_still_wins_when_it_is_later_than_the_lead_cap():
    tasks = [
        Task(
            id="p",
            title="Late handout",
            due=date(2026, 10, 30),
            hours=6,
            earliest_start=date(2026, 10, 26),
        )
    ]
    caps = [
        DayCapacity(day=date(2026, 10, 1) + timedelta(days=i), start=time(18, 0), max_hours=4)
        for i in range(40)
    ]
    plan = build_schedule(tasks, caps)
    assert min(b.day for b in plan.blocks) >= date(2026, 10, 26)


def test_no_block_is_a_useless_sliver():
    """Every block should be long enough to be worth sitting down for, and long
    enough for the calendar to render its label."""
    tasks = [
        Task(id="a", title="A", due=date(2026, 9, 25), hours=7.25),
        Task(id="b", title="B", due=date(2026, 9, 27), hours=4.75),
    ]
    plan = build_schedule(tasks, cap(14, hours=4))
    assert plan.blocks
    assert min(b.hours for b in plan.blocks) >= 1.0


def test_hours_are_still_fully_placed_after_merging_remainders():
    tasks = [Task(id="a", title="A", due=date(2026, 9, 24), hours=7.25)]
    plan = build_schedule(tasks, cap(14, hours=4))
    assert sum(b.hours for b in plan.blocks) == pytest.approx(7.25, abs=0.25)
    assert not plan.unscheduled


def _overlaps(plan):
    from datetime import datetime as _dt
    by_day = {}
    for b in plan.blocks:
        start = _dt.combine(b.day, b.start_time)
        by_day.setdefault(b.day, []).append((start, start + timedelta(hours=b.hours), b))
    bad = []
    for spans in by_day.values():
        spans.sort(key=lambda s: s[0])
        for (s1, e1, b1), (s2, e2, b2) in zip(spans, spans[1:]):
            if s2 < e1:
                bad.append((b1, b2))
    return bad


def test_no_two_blocks_overlap_after_remainders_are_merged():
    """Regression: merging a remainder into a block made it longer without moving
    the block after it. The calendar then drew them side by side, squished."""
    tasks = [
        Task(id="a", title="A", due=date(2026, 9, 24), hours=7.25),
        Task(id="b", title="B", due=date(2026, 9, 24), hours=5.5),
        Task(id="c", title="C", due=date(2026, 9, 26), hours=3.25),
    ]
    plan = build_schedule(tasks, cap(14, hours=4))
    assert _overlaps(plan) == []


def test_unpinned_blocks_flow_around_a_pinned_one():
    pinned = [
        Block(task_id="a", title="A", day=date(2026, 9, 14),
              start_time=time(19, 0), hours=2, pinned=True)
    ]
    tasks = [Task(id="b", title="B", due=date(2026, 9, 14), hours=2)]
    plan = build_schedule(tasks, cap(1, hours=4), pinned=pinned)
    assert _overlaps(plan) == []
    pinned_after = [b for b in plan.blocks if b.pinned][0]
    assert pinned_after.start_time == time(19, 0)


# ---------------------------------------------------------------- commitments


def _day(busy, start="09:00", end="17:00", max_hours=8, day=date(2026, 9, 14)):
    return DayCapacity(
        day=day,
        start=time.fromisoformat(start),
        end=time.fromisoformat(end),
        max_hours=max_hours,
        busy=[(time.fromisoformat(a), time.fromisoformat(b)) for a, b in busy],
    )


def _span(b):
    from datetime import datetime as _dt
    s = _dt.combine(b.day, b.start_time)
    return s, s + timedelta(hours=b.hours)


def test_study_never_lands_on_a_commitment():
    lecture = (time(10, 40), time(11, 30))
    plan = build_schedule(
        [Task(id="a", title="A", due=date(2026, 9, 14), hours=6)],
        [_day([("10:40", "11:30")])],
    )
    from datetime import datetime as _dt
    l0 = _dt.combine(date(2026, 9, 14), lecture[0])
    l1 = _dt.combine(date(2026, 9, 14), lecture[1])
    for b in plan.blocks:
        s, e = _span(b)
        assert not (s < l1 and l0 < e), f"{b.start_time} +{b.hours}h hits the lecture"
    assert sum(b.hours for b in plan.blocks) == 6


def test_commitments_reduce_capacity():
    """A 4-hour window with a 1-hour meeting in it holds 3 hours of study."""
    plan = build_schedule(
        [Task(id="a", title="A", due=date(2026, 9, 14), hours=5)],
        [_day([("10:00", "11:00")], start="09:00", end="13:00")],
    )
    assert sum(b.hours for b in plan.blocks) == 3
    assert plan.unscheduled == ["A"]


def test_a_block_that_fits_after_the_lecture_is_not_split():
    """Don't cut a 2-hour block in half when there's a 2-hour gap later."""
    plan = build_schedule(
        [Task(id="a", title="A", due=date(2026, 9, 14), hours=2)],
        [_day([("10:00", "11:00")], start="09:00", end="14:00")],
    )
    assert len(plan.blocks) == 1
    assert plan.blocks[0].start_time == time(11, 0)


def test_a_block_is_split_around_a_commitment_only_when_it_must_be():
    """3.5h in a day whose free time is 9-11 and 11:30-13: no gap holds it
    whole, so it becomes 2h before the meeting and 1.5h after."""
    plan = build_schedule(
        [Task(id="a", title="A", due=date(2026, 9, 14), hours=3.5)],
        [_day([("11:00", "11:30")], start="09:00", end="13:00")],
        min_block_hours=0.25,
    )
    pieces = sorted((b.start_time, b.hours) for b in plan.blocks)
    assert pieces == [(time(9, 0), 2.0), (time(11, 30), 1.5)]


def test_study_stays_inside_the_window():
    plan = build_schedule(
        [Task(id="a", title="A", due=date(2026, 9, 16), hours=9)],
        [_day([], start="18:00", end="22:00", day=date(2026, 9, 14) + timedelta(days=i)) for i in range(3)],
    )
    for b in plan.blocks:
        s, e = _span(b)
        assert s.time() >= time(18, 0)
        assert e.time() <= time(22, 0) or e.time() == time(0, 0)


def test_off_grid_commitment_times_snap_to_quarter_hours():
    """A lecture ending at 11:25 frees time from 11:30, not 11:25."""
    plan = build_schedule(
        [Task(id="a", title="A", due=date(2026, 9, 14), hours=1)],
        [_day([("09:00", "11:25")], start="09:00", end="13:00")],
    )
    assert plan.blocks[0].start_time == time(11, 30)


def test_pinned_blocks_and_commitments_are_both_avoided():
    pinned = [Block(task_id="p", title="P", day=date(2026, 9, 14), start_time=time(9, 0), hours=1, pinned=True)]
    plan = build_schedule(
        [Task(id="a", title="A", due=date(2026, 9, 14), hours=2)],
        [_day([("10:00", "11:00")], start="09:00", end="14:00")],
        pinned=pinned,
    )
    assert _overlaps(plan) == []
    work = [b for b in plan.blocks if not b.pinned]
    assert work and all(b.start_time >= time(11, 0) for b in work)
