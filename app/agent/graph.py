"""LangGraph agent.

Flow for week 1:
    parse_syllabus -> estimate_effort -> build_schedule -> END

build_schedule is a deterministic node that calls app.scheduler.core, not the
model. That separation is the point of the project.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph


class AgentState(TypedDict, total=False):
    user_id: str
    pdf_text: str
    extraction: Any        # SyllabusExtraction
    estimates: Any         # list[EffortEstimate]
    plan: Any              # scheduler.core.Plan
    trace: Annotated[list[str], lambda a, b: a + b]


def node_parse(state: AgentState) -> AgentState:
    raise NotImplementedError  # TODO(week1)


def node_estimate(state: AgentState) -> AgentState:
    raise NotImplementedError  # TODO(week1)


def node_build_schedule(state: AgentState) -> AgentState:
    """Deterministic: map estimates -> scheduler Tasks, load Availability ->
    DayCapacity, call scheduler.core.build_schedule."""
    raise NotImplementedError  # TODO(week1)


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
