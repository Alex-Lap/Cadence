"""Turn a user's availability into per-day capacity for the scheduler.

The scheduler takes DayCapacity structs and knows nothing about the database.
This module is the adapter between the two.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from app.scheduler.core import DayCapacity

DEFAULT_START = time(18, 0)


def build_capacity(
    start: date,
    days: int,
    *,
    availability: list | None = None,
    default_hours: float = 4.0,
) -> list[DayCapacity]:
    """One DayCapacity per available day, beginning at `start`.

    With Availability rows, each weekday carries its own window and only those
    weekdays appear. With none, fall back to `default_hours` every day: week 1
    has no availability UI, and a flat assumption still produces a useful
    schedule -- it just isn't personal yet.
    """
    by_weekday: dict[int, tuple[time, float]] = {}
    for row in availability or []:
        span = (
            datetime.combine(date.min, row.end_time)
            - datetime.combine(date.min, row.start_time)
        ).total_seconds() / 3600
        by_weekday[row.weekday] = (row.start_time, max(0.0, row.max_hours or span))

    out: list[DayCapacity] = []
    for i in range(days):
        day = start + timedelta(days=i)
        if by_weekday:
            if day.weekday() not in by_weekday:
                continue
            start_time, hours = by_weekday[day.weekday()]
        else:
            start_time, hours = DEFAULT_START, default_hours
        if hours > 0:
            out.append(DayCapacity(day=day, start=start_time, max_hours=hours))
    return out
