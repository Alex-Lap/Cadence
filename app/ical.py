"""Study blocks as an iCalendar (.ics) feed.

Written by hand rather than with a library: the format needed here is a few
lines per event, and the two rules that matter -- escaping and 75-octet line
folding -- are easy to get right and easy to test.

Times are written as local "floating" times (no Z, no TZID): a block at 6pm is
6pm wherever the calendar app is, which is what a study plan means.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone

PRODID = "-//Cadence//Study schedule//EN"


def label(title: str | None) -> str:
    """What a block is for, matching the calendar in the app."""
    if not title:
        return "Study"
    if re.search(r"\b(exam|midterm|final|quiz|test)\b", title, re.I):
        return f"Study for {title}"
    if re.search(r"\b(presentation|talk|demo)\b", title, re.I):
        return f"Prepare {title}"
    if re.search(r"\b(reading|chapter)\b", title, re.I):
        return f"Read {title}"
    return f"Work on {title}"


def escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def fold(line: str) -> str:
    """Split a content line into 75-octet chunks, continuation lines starting
    with a space (RFC 5545 3.1). Never splits inside a UTF-8 character."""
    out: list[str] = []
    current = ""
    size = 0
    limit = 75
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > limit:
            out.append(current)
            current, size, limit = " ", 1, 75
        current += ch
        size += n
    out.append(current)
    return "\r\n".join(out)


def _local(d: date, t: time) -> str:
    return datetime.combine(d, t).strftime("%Y%m%dT%H%M%S")


def calendar(blocks, *, now: datetime | None = None) -> str:
    """`blocks`: objects with id, day, start_time, hours, and assignment (with
    title and course.code), as ScheduleBlock rows are."""
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Cadence study plan",
    ]
    for b in blocks:
        start = datetime.combine(b.day, b.start_time)
        end = start + timedelta(minutes=round(b.hours * 60))
        a = getattr(b, "assignment", None)
        title = a.title if a else None
        course = a.course.code if a and getattr(a, "course", None) else None
        lines += [
            "BEGIN:VEVENT",
            f"UID:{b.id}@cadence",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{_local(start.date(), start.time())}",
            f"DTEND:{_local(end.date(), end.time())}",
            f"SUMMARY:{escape(label(title))}",
        ]
        if course:
            lines.append(f"DESCRIPTION:{escape(f'{course}: {title}. Planned by Cadence.')}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines) + "\r\n"
