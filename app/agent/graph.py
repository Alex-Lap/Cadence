"""LangGraph agent.

    parse -> estimate -> END

The graph does the two jobs that need a language model: reading the syllabus and
judging how long each item takes. It does NOT schedule. Scheduling is
deterministic code called from app/api/routes.py::_reschedule, which runs
identically whether an upload, a corrected date, or a disruption triggered it.

Keeping the scheduler outside the graph is the point of the project, not an
omission: there is exactly one writer of schedule blocks, and it needs no LLM.

The graph is PURE: no database session, no HTTP, no file I/O.
"""

from __future__ import annotations

import operator
from datetime import date
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agent.tools.estimate_effort import estimate_effort
from app.agent.tools.parse_syllabus import parse_syllabus
from app.agent.tools.resolve_dates import resolve_dates


def key_for(course_code: str, title: str) -> str:
    """Stable identity for an assignment across nodes. Titles repeat between
    courses ("Final Exam"), so the course code has to be part of the key."""
    return f"{course_code}::{title}"


class AgentState(TypedDict, total=False):
    # inputs
    syllabus_text: str
    term_start: date | None
    credit_hours: float
    effort_multiplier: float
    # outputs
    extraction: Any           # SyllabusExtraction
    hours: dict[str, float]   # key_for(...) -> hours
    trace: Annotated[list[str], operator.add]


def node_parse(state: AgentState) -> AgentState:
    term_start = state.get("term_start")
    extraction = parse_syllabus(
        state["syllabus_text"],
        term_start=term_start.isoformat() if term_start else None,
    )
    if term_start:
        extraction = resolve_dates(extraction, term_start)

    items = [a for c in extraction.courses for a in c.assignments]
    undated = sum(1 for a in items if a.due_at is None)
    return {
        "extraction": extraction,
        "trace": [
            f"parsed {len(extraction.courses)} course(s), {len(items)} item(s)"
            f" - {undated} without a date"
        ],
    }


def node_estimate(state: AgentState) -> AgentState:
    hours: dict[str, float] = {}
    trace: list[str] = []

    for course in state["extraction"].courses:
        items = [a.model_dump() for a in course.assignments]
        estimates = estimate_effort(
            course.title,
            items,
            effort_multiplier=state.get("effort_multiplier", 1.0),
            credit_hours=state.get("credit_hours", 3.0),
        )
        for e in estimates:
            hours[key_for(course.code, e.assignment_title)] = e.estimated_hours
        trace.append(
            f"estimated {course.code}: {sum(e.estimated_hours for e in estimates):.1f}h"
            f" across {len(estimates)} item(s)"
        )

    return {"hours": hours, "trace": trace}


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("parse", node_parse)
    g.add_node("estimate", node_estimate)
    g.add_edge(START, "parse")
    g.add_edge("parse", "estimate")
    g.add_edge("estimate", END)
    return g.compile()
