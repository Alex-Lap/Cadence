"""Turn course-week references into calendar dates. Plain arithmetic."""

from datetime import date, datetime, timedelta

from app.schemas import SyllabusExtraction


def resolve_dates(extraction: SyllabusExtraction, term_start: date) -> SyllabusExtraction:
    """Fill due_at from due_week. Week 1 is the week containing term_start;
    an item due in week N is due on that week's Friday."""
    for course in extraction.courses:
        for a in course.assignments:
            if a.due_at is None and a.due_week is not None:
                monday = term_start + timedelta(weeks=a.due_week - 1)
                a.due_at = datetime.combine(
                    monday + timedelta(days=4), datetime.min.time()
                )
                a.due_date_confidence = "inferred"
    return extraction