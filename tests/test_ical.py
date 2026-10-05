from datetime import date, datetime, time, timezone
from types import SimpleNamespace

from app.ical import calendar, escape, fold, label

NOW = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)


def block(title="Project 1", day=date(2026, 10, 6), start=time(18), hours=1.75, code="CIS 6307"):
    a = SimpleNamespace(title=title, course=SimpleNamespace(code=code)) if title else None
    return SimpleNamespace(id="b1", day=day, start_time=start, hours=hours, assignment=a)


def test_one_event_with_local_times():
    ics = calendar([block()], now=NOW)
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert "DTSTART:20261006T180000\r\n" in ics
    assert "DTEND:20261006T194500\r\n" in ics
    assert "SUMMARY:Work on Project 1\r\n" in ics
    assert "UID:b1@cadence" in ics
    assert ics.count("BEGIN:VEVENT") == 1


def test_labels_match_the_app():
    assert label("Final Exam") == "Study for Final Exam"
    assert label("Paper Presentation") == "Prepare Paper Presentation"
    assert label(None) == "Study"


def test_special_characters_are_escaped():
    assert escape("a, b; c\\d\ne") == "a\\, b\\; c\\\\d\\ne"
    ics = calendar([block(title="Project 5: Bitmap, FM; HLL")], now=NOW)
    assert "Bitmap\\, FM\\; HLL" in ics


def test_long_lines_are_folded_at_75_octets():
    line = "DESCRIPTION:" + "é" * 80
    folded = fold(line)
    parts = folded.split("\r\n")
    assert all(len(p.encode()) <= 75 for p in parts)
    assert all(p.startswith(" ") for p in parts[1:])
    assert "".join(p[1:] if i else p for i, p in enumerate(parts)) == line


def test_block_running_past_midnight_ends_next_day():
    ics = calendar([block(start=time(23), hours=1.5)], now=NOW)
    assert "DTEND:20261007T003000" in ics
