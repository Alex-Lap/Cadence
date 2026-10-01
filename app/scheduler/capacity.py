"""Turn a user's availability and commitments into per-day capacity.

The scheduler takes DayCapacity structs and knows nothing about the database.
This module is the adapter between the two.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from app.scheduler.core import DayCapacity

DEFAULT_START = time(18, 0)


def occurs_on(commitment, day: date) -> bool:
    """Whether a commitment (recurring weekly or one-off) happens on `day`."""
    if commitment.on_date is not None:
        return commitment.on_date == day
    if commitment.weekday != day.weekday():
        return False
    if commitment.starts_on and day < commitment.starts_on:
        return False
    if commitment.ends_on and day > commitment.ends_on:
        return False
    return True


def build_capacity(
    start: date,
    days: int,
    *,
    availability: list | None = None,
    default_hours: float = 4.0,
    window_start: time | None = None,
    window_end: time | None = None,
    commitments: list | None = None,
) -> list[DayCapacity]:
    """One DayCapacity per available day, beginning at `start`.

    With Availability rows, each weekday carries its own window and only those
    weekdays appear. With none, every day gets the user's study window
    (`window_start`-`window_end`, defaulting to an open evening from 18:00)
    capped at `default_hours`. Commitments falling on a day become its `busy`
    list; the scheduler works around them.
    """
    by_weekday: dict[int, tuple[time, time, float]] = {}
    for row in availability or []:
        span = (
            datetime.combine(date.min, row.end_time)
            - datetime.combine(date.min, row.start_time)
        ).total_seconds() / 3600
        by_weekday[row.weekday] = (row.start_time, row.end_time, max(0.0, row.max_hours or span))

    out: list[DayCapacity] = []
    for i in range(days):
        day = start + timedelta(days=i)
        if by_weekday:
            if day.weekday() not in by_weekday:
                continue
            lo, hi, hours = by_weekday[day.weekday()]
        else:
            lo, hi, hours = window_start or DEFAULT_START, window_end, default_hours
        if hours <= 0:
            continue
        busy = sorted(
            (c.start_time, c.end_time) for c in commitments or [] if occurs_on(c, day)
        )
        out.append(DayCapacity(day=day, start=lo, end=hi, max_hours=hours, busy=busy))
    return out
