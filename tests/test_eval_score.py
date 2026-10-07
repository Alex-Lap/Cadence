"""The eval scorer must itself be right, or the accuracy numbers mean nothing."""

from datetime import datetime

from app.schemas import ParsedAssignment, ParsedCourse, ParsedMeeting, SyllabusExtraction
from evals.score import match, score, similarity

GOLD = {
    "name": "Test",
    "term_start": "2026-08-24",
    "items": [
        {"title": "Project 1", "kind": "deliverable", "weight": 0.1, "due": {"week": 7}, "available_week": 4},
        {"title": "Project 2", "kind": "deliverable", "weight": 0.1, "due": {"date": "2026-10-16"}},
        {"title": "Final Exam", "kind": "deliverable", "weight": 0.3, "due": None},
        {"title": "Attendance", "kind": "participation", "weight": 0.1, "due": None},
    ],
    "optional_items": ["Homework 0"],
    "meetings": [{"days": ["Tue", "Thu"], "start": "18:00", "end": "20:40"}],
}


def extraction(items, meetings=()):
    return SyllabusExtraction(courses=[ParsedCourse(
        code="X 1", title="X", assignments=items, meetings=list(meetings))])


def perfect():
    return extraction(
        [
            ParsedAssignment(title="Project 1: Hash Tables", weight=0.1, due_week=7, available_week=4),
            ParsedAssignment(title="Project 2", weight=0.1, due_at=datetime(2026, 10, 16)),
            ParsedAssignment(title="Final Exam", weight=0.3),
            ParsedAssignment(title="Attendance", weight=0.1, is_participation=True),
        ],
        [ParsedMeeting(days=["Tue", "Thu"], start_time="18:00", end_time="20:40", source_text="TR")],
    )


def test_numbers_must_agree():
    assert similarity(["Project 1"], "Project 2") == 0
    assert similarity(["Project 1"], "Project 1: Hash Tables") == 1.0
    assert similarity(["Exam 1"], "Exam 1 (in class)") == 1.0


def test_matching_is_one_to_one():
    items = [ParsedAssignment(title="Project 1"), ParsedAssignment(title="Project 1 report")]
    pairs = match([{"title": "Project 1"}], items)
    assert len(pairs) == 1


def test_a_perfect_extraction_scores_perfectly():
    s = score(GOLD, perfect())
    assert (s.items_found.rate, s.kind.rate, s.weight.rate, s.due.rate) == (1, 1, 1, 1)
    assert s.handout.rate == 1 and s.undated_kept.rate == 1
    assert s.meetings_found.rate == 1 and s.meetings_extra == 0
    assert not s.problems and not s.extras and not s.invented_dates


def test_week_due_can_also_arrive_as_the_resolved_friday():
    e = perfect()
    p1 = e.courses[0].assignments[0]
    p1.due_week, p1.due_at = None, datetime(2026, 10, 9)  # Friday of week 7
    assert score(GOLD, e).due.rate == 1


def test_an_invented_date_is_caught():
    e = perfect()
    e.courses[0].assignments[2].due_at = datetime(2026, 12, 10)
    s = score(GOLD, e)
    assert s.invented_dates == ["Final Exam -> 2026-12-10"]
    assert s.undated_kept.rate == 0.5


def test_mislabelled_kind_and_wrong_weight():
    e = perfect()
    e.courses[0].assignments[2].is_category = True
    e.courses[0].assignments[1].weight = 0.2
    s = score(GOLD, e)
    assert s.kind.right == 3 and s.weight.right == 3


def test_missing_and_extra_items():
    e = perfect()
    e.courses[0].assignments.pop(1)
    e.courses[0].assignments.append(ParsedAssignment(title="Quiz 3"))
    e.courses[0].assignments.append(ParsedAssignment(title="Homework 0 survey"))  # optional
    s = score(GOLD, e)
    assert s.items_found.right == 3
    assert s.extras == ["Quiz 3"]
    assert "missing: Project 2" in s.problems


def test_meetings_wrong_time_and_extra():
    e = perfect()
    e.courses[0].meetings = [
        ParsedMeeting(days=["Tue"], start_time="18:00", end_time="20:40", source_text="T"),
        ParsedMeeting(days=["Thu"], start_time="18:00", end_time="22:40", source_text="R"),
    ]
    s = score(GOLD, e)
    assert s.meetings_found.right == 1 and s.meetings_extra == 1


def test_week_deadline_accepts_any_day_that_week():
    e = perfect()
    p1 = e.courses[0].assignments[0]
    p1.due_week, p1.due_at = None, datetime(2026, 10, 5)  # Monday of week 7
    assert score(GOLD, e).due.rate == 1
    p1.due_at = datetime(2026, 10, 12)  # Monday of week 8
    assert score(GOLD, e).due.rate == 0.5


def test_duplicate_titles_match_the_one_with_the_right_kind():
    e = perfect()
    dup = ParsedAssignment(title="Final Exam", is_participation=True)
    e.courses[0].assignments.insert(0, dup)
    s = score(GOLD, e)
    assert s.kind.rate == 1
    assert s.extras == ["Final Exam"]
