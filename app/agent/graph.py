"""LangGraph agent.

    parse -> estimate -> schedule -> END

The graph is PURE: no database session, no HTTP, no file I/O. The caller hands
it syllabus text and the user's day capacity; it returns an extraction, hour
estimates and a plan. Persistence lives in app/api/routes.py.

That boundary is deliberate -- the whole agent can be exercised with three
dataclasses and no Postgres.
"""

from __future__ import annotations

import operator
from datetime import date
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agent.tools.estimate_effort import estimate_effort
from app.agent.tools.parse_syllabus import parse_syllabus
from app.agent.tools.resolve_dates import resolve_dates
from app.scheduler.core import DayCapacity, Task, build_schedule


def key_for(course_code: str, title: str) -> str:
    """Stable identity for an assignment across nodes. Titles repeat between
    courses ("Final Exam"), so the course code has to be part of the key."""
    return f"{course_code}::{title}"


class AgentState(TypedDict, total=False):
    # inputs
    syllabus_text: str
    term_start: date | None
    capacity: list[DayCapacity]
    credit_hours: float
    effort_multiplier: float
    # outputs
    extraction: Any           # SyllabusExtraction
    hours: dict[str, float]   # key_for(...) -> hours
    plan: Any                 # scheduler.core.Plan
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


def node_build_schedule(state: AgentState) -> AgentState:
    """Deterministic. Maps the extraction onto scheduler Tasks and calls
    build_schedule -- the model gets no vote on where hours land."""
    tasks: list[Task] = []
    needs_date: list[str] = []

    for course in state["extraction"].courses:
        for a in course.assignments:
            if a.is_category or a.due_at is None:
                needs_date.append(a.title)
                continue
            key = key_for(course.code, a.title)
            tasks.append(
                Task(
                    id=key,
                    title=a.title,
                    due=a.due_at.date(),
                    hours=state["hours"].get(key, 2.0),
                    weight=a.weight,
                    earliest_start=a.available_at.date() if a.available_at else None,
                )
            )

    plan = build_schedule(tasks, state.get("capacity", []))

    note = f"scheduled {len(tasks)} task(s) into {len(plan.blocks)} block(s)"
    if needs_date:
        note += f"; {len(needs_date)} need a date from the user"
    if plan.unscheduled:
        note += f"; {len(plan.unscheduled)} did not fit"
    return {"plan": plan, "trace": [note]}


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("parse", node_parse)
    g.add_node("estimate", node_estimate)
    g.add_node("schedule", node_build_schedule)
    g.add_edge(START, "parse")
    g.add_edge("parse", "estimate")
    g.add_edge("estimate", "schedule")
    g.add_edge("schedule", END)
    return g.compile()
