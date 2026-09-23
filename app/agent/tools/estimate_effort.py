"""Tool: per-assignment hour estimates.

The model judges relative difficulty; this module keeps the numbers honest.
A term budget derived from credit hours caps the total, and each assignment
is held inside a band around what its grade weight implies.
"""

from __future__ import annotations

from app.llm.provider import get_chat_model
from app.schemas import EffortEstimate, EffortEstimates

# Rule of thumb: ~2 hours outside class per credit hour per week, 15-week term.
HOURS_PER_CREDIT = 30.0

# How far the model may stray from what an assignment's weight implies.
BAND_LOW = 0.4
BAND_HIGH = 2.5

QUANTUM = 0.25  # round to quarter hours -- calendars look wrong otherwise

SYSTEM_PROMPT = """You estimate how long each assignment takes a competent
graduate student, in hours.

Judge RELATIVE difficulty from the assignment's title and the course's subject.
Implementing a data structure from a paper is not a reading response. A final
exam needs study time, not sitting time.

Give a one-line rationale naming the specific work involved. Do not try to make
the numbers sum to anything -- proportions are what matter."""


def _round_q(hours: float) -> float:
    return max(QUANTUM, round(hours / QUANTUM) * QUANTUM)


def clamp_to_budget(
    raw: dict[str, float],
    weights: dict[str, float | None],
    budget: float,
) -> dict[str, float]:
    """Hold each estimate inside a band around its weight-implied share, then
    rescale so the course total equals the budget.

    Rescaling after clamping can nudge a value back past its band edge. That's
    accepted: the total staying realistic matters more than any single row,
    and the band has already removed the outliers.
    """
    if not raw:
        return {}

    weighted = {t: w for t, w in weights.items() if w}
    total_weight = sum(weighted.values())

    expected: dict[str, float] = {}
    for title in raw:
        w = weights.get(title)
        if w and total_weight:
            expected[title] = budget * (w / total_weight)
        else:
            # Unweighted item: give it an even share as a fallback prior.
            expected[title] = budget / len(raw)

    clamped = {
        title: min(max(hours, BAND_LOW * expected[title]), BAND_HIGH * expected[title])
        for title, hours in raw.items()
    }

    total = sum(clamped.values())
    factor = budget / total if total else 1.0
    return {title: _round_q(h * factor) for title, h in clamped.items()}


def estimate_effort(
    course_title: str,
    assignments: list[dict],
    *,
    effort_multiplier: float = 1.0,
    credit_hours: float = 3.0,
) -> list[EffortEstimate]:
    """Estimate hours per assignment.

    `assignments` are dicts with at least `title`, optionally `weight` and
    `is_category`. Categories are skipped -- they aren't schedulable work.
    `effort_multiplier` is what the weekly check-in learns per course: >1 means
    this course consistently runs long for this student.
    """
    real = [a for a in assignments if not a.get("is_category")]
    if not real:
        return []

    lines = "\n".join(
        f"- {a['title']}"
        + (f" (worth {a['weight']:.0%} of the grade)" if a.get("weight") else "")
        for a in real
    )

    model = get_chat_model(temperature=0).with_structured_output(EffortEstimates)
    result = model.invoke(
        [
            ("system", SYSTEM_PROMPT),
            ("human", f"Course: {course_title}\n\nAssignments:\n{lines}"),
        ]
    )

    raw = {e.assignment_title: e.estimated_hours for e in result.estimates}
    weights = {a["title"]: a.get("weight") for a in real}

    # Scale the term budget to the share of the grade these items actually
    # cover. Categories and undated work were filtered out above; without this,
    # five projects worth 50% would absorb 100% of the term's hours.
    covered = sum(w for w in weights.values() if w)
    budget = credit_hours * HOURS_PER_CREDIT * effort_multiplier
    if covered:
        budget *= min(1.0, covered)

    final = clamp_to_budget(raw, weights, budget)

    rationales = {e.assignment_title: e.rationale for e in result.estimates}
    return [
        EffortEstimate(
            assignment_title=title,
            estimated_hours=hours,
            rationale=rationales.get(title, ""),
        )
        for title, hours in final.items()
    ]