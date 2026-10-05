from datetime import time
from types import SimpleNamespace

from app.agent.tools.meetings import meeting_issue, meeting_rows, parse_clock


def m(days, start, end, kind="lecture", source="Lecture: TR", location=None):
    return SimpleNamespace(days=days, start_time=start, end_time=end, kind=kind,
                           source_text=source, location=location)


def test_normal_lecture_has_no_issue():
    assert meeting_issue(time(18), time(20, 40)) is None


def test_overlong_meeting_is_flagged():
    assert "4h40m" in meeting_issue(time(18), time(22, 40))


def test_backwards_meeting_is_flagged():
    assert meeting_issue(time(20), time(18)) == "Ends before it starts."


def test_tiny_meeting_is_flagged():
    assert "10 minutes" in meeting_issue(time(9), time(9, 10))


def test_am_pm_mixup_is_flagged():
    assert "AM/PM" in meeting_issue(time(6), time(8, 40))


def test_parse_clock_formats():
    assert parse_clock("18:00") == time(18)
    assert parse_clock("6:00 PM") == time(18)
    assert parse_clock("9:35am") == time(9, 35)
    assert parse_clock("noonish") is None


def test_rows_one_per_day_and_kind_in_title():
    rows, skipped = meeting_rows("CIS 6307", [m(["Tue", "Thu"], "18:00", "20:40"),
                                              m(["Wed"], "10:00", "11:50", kind="lab")])
    assert [(r.title, r.weekday) for r in rows] == [
        ("CIS 6307", 1), ("CIS 6307", 3), ("CIS 6307 lab", 2)]
    assert skipped == []


def test_unreadable_times_are_skipped_not_guessed():
    rows, skipped = meeting_rows("X", [m(["Mon"], "TBA", "TBA")])
    assert rows == [] and len(skipped) == 1


def test_duplicate_days_collapse():
    rows, _ = meeting_rows("X", [m(["Mon", "Mon"], "09:00", "10:00"),
                                 m(["Mon"], "09:00", "10:00")])
    assert len(rows) == 1


def test_location_is_kept_in_the_note():
    rows, _ = meeting_rows("X", [m(["Mon"], "09:00", "10:00", location="CSE E119")])
    assert "CSE E119" in rows[0].note


# ------------------------------------------------ participation classifier

from app.agent.tools.classify import is_participation_title  # noqa: E402


def test_participation_titles():
    for t in ["Attendance", "Class Participation", "In-class activities", "iClicker"]:
        assert is_participation_title(t), t


def test_real_work_is_not_participation():
    for t in ["Final Exam", "Paper Presentation", "Project 1: Hash Tables", "Homework 3"]:
        assert not is_participation_title(t), t
