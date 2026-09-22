"""Tool: per-assignment hour estimates."""

from app.schemas import EffortEstimate


def estimate_effort(
    course_title: str,
    assignments: list[dict],
    *,
    effort_multiplier: float = 1.0,
) -> list[EffortEstimate]:
    """TODO(week1): ask the model for hours per assignment given the course
    level and the assignment title/weight, then multiply by
    effort_multiplier (which the weekly check-in learns per course).
    """
    raise NotImplementedError
