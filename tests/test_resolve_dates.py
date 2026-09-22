"""resolve_dates turns course-week references into calendar dates.

No LLM, no network -- pure arithmetic, so it can be tested exactly.
"""

from datetime import date, datetime

from app.agent.tools.resolve_dates import resolve_dates
from app.schemas import ParsedAssignment, ParsedCourse, SyllabusExtraction

TERM_START = date(2026, 8, 24)  # Monday of week 1


def make(**kw) -> SyllabusExtraction:
    return SyllabusExtraction(
        courses=[ParsedCourse(code="CIS 6307", title="T", assignments=[ParsedAssignment(**kw)])]
    )


def only(ex: SyllabusExtraction) -> ParsedAssignment:
    return ex.courses[0].assignments[0]


def test_week_one_is_the_term_start_week():
    a = only(resolve_dates(make(title="A", due_week=1), TERM_START))
    assert a.due_at.date() == date(2026, 8, 28)  # Friday of week 1


def test_cis6307_project_ladder():
    """Handout weeks 4,5,7,9,11 each +3 -> due weeks 7,8,10,12,14."""
    expected = {
        7: date(2026, 10, 9),
        8: date(2026, 10, 16),
        10: date(2026, 10, 30),
        12: date(2026, 11, 13),
        14: date(2026, 11, 27),
    }
    for wk, want in expected.items():
        a = only(resolve_dates(make(title=f"P{wk}", due_week=wk), TERM_START))
        assert a.due_at.date() == want, f"week {wk}"


def test_explicit_date_is_never_overwritten():
    fixed = datetime(2026, 10, 1)
    a = only(resolve_dates(make(title="A", due_at=fixed, due_week=99), TERM_START))
    assert a.due_at == fixed
    assert a.due_date_confidence == "explicit"


def test_no_week_and_no_date_stays_null():
    a = only(resolve_dates(make(title="Final Exam"), TERM_START))
    assert a.due_at is None


def test_resolved_dates_are_marked_inferred():
    a = only(resolve_dates(make(title="A", due_week=3), TERM_START))
    assert a.due_date_confidence == "inferred"
