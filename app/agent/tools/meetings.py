"""Turn extracted class meetings into commitment rows, and flag odd ones.

The model copies times from the syllabus; it does not judge them. Syllabi have
typos ("6:00-10:40pm" for a 2h40m lecture), and a wrong lecture time silently
blocks or frees evening study. So every extracted meeting is stored
unconfirmed, and these checks say which ones deserve a second look.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

EARLIEST = time(7, 0)
LATEST = time(23, 0)
MIN_MINUTES = 20
MAX_MINUTES = 4 * 60


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def meeting_issue(start: time, end: time) -> str | None:
    """The first thing that looks wrong about a class time, or None."""
    length = _minutes(end) - _minutes(start)
    if length <= 0:
        return "Ends before it starts."
    if length > MAX_MINUTES:
        h, m = divmod(length, 60)
        return f"Runs {h}h{m:02d}m. Check the end time; syllabi often have typos here."
    if length < MIN_MINUTES:
        return f"Only {length} minutes long."
    if start < EARLIEST or end > LATEST:
        return "Outside 7am–11pm. Check AM/PM."
    return None


def parse_clock(text: str) -> time | None:
    """'18:00', '18:00:00', '6:00 PM' -> time. None if it isn't a time."""
    text = text.strip().upper().replace(".", "")
    for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p", "%I %p", "%I%p"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


@dataclass
class MeetingRow:
    title: str
    weekday: int
    start: time
    end: time
    note: str | None


def meeting_rows(course_code: str, meetings) -> tuple[list[MeetingRow], list[str]]:
    """One row per (meeting, weekday). Returns (rows, skipped-reasons).

    A meeting whose times can't be read at all is skipped, not guessed at --
    the trace says so and the user can add it by hand.
    """
    rows: list[MeetingRow] = []
    skipped: list[str] = []
    seen: set[tuple[int, time, time]] = set()
    for m in meetings:
        start, end = parse_clock(m.start_time), parse_clock(m.end_time)
        if start is None or end is None:
            skipped.append(f"unreadable time {m.start_time!r}-{m.end_time!r}")
            continue
        title = course_code if m.kind == "lecture" else f"{course_code} {m.kind}"
        note = m.source_text.strip()[:500] if m.source_text else None
        if m.location and note and m.location not in note:
            note = f"{note} ({m.location})"[:500]
        for day in dict.fromkeys(m.days):  # de-duplicate, keep order
            key = (DAYS.index(day), start, end)
            if key in seen:
                continue
            seen.add(key)
            rows.append(MeetingRow(title, DAYS.index(day), start, end, note))
    return rows, skipped
