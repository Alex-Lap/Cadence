"""Pydantic schemas. These double as the structured-output contracts for the
LLM tools, so keep them tight and well-described."""

from __future__ import annotations

from datetime import date, datetime, time

from pydantic import BaseModel, Field


class ParsedAssignment(BaseModel):
    title: str
    due_at: datetime | None = Field(
        None,
        description=(
            "When this is due. Null ONLY for a grading category with no individual "
            "dated items -- every real deliverable must have a date."
        ),
    )
    weight: float | None = Field(None, description="Fraction of final grade, 0-1")
    notes: str | None = None
    is_category: bool = Field(
        False,
        description=(
            "True if this row is a grading CATEGORY (e.g. 'Homework 30%') rather "
            "than one dated deliverable. Categories are not schedulable."
        ),
    )
    due_date_confidence: str = Field(
        "explicit",
        description="'explicit' if the syllabus states this date, 'inferred' if you derived it.",
    )
    available_at: datetime | None = Field(
        None,
        description="When work can begin. Leave null; derived from available_week.",
    )
    available_week: int | None = Field(
        None,
        description=(
            "1-based course week this is HANDED OUT / assigned, if the syllabus "
            "says. Work cannot start before it. For 'Project 3 handout in Week 7' "
            "-> available_week=7."
        ),
    )
    due_week: int | None = Field(
        None,
        description=(
            "1-based course week this is DUE, when the syllabus expresses timing "
            "in weeks rather than dates (e.g. 'handed out week 4, due after 3 "
            "weeks' -> due_week=7). Do the week arithmetic, not the calendar "
            "arithmetic -- leave due_at null and we compute the date."
        ),
    )


class ParsedCourse(BaseModel):
    code: str
    title: str
    term: str | None = None
    assignments: list[ParsedAssignment] = []


class SyllabusExtraction(BaseModel):
    """Top-level structured output of the parse_syllabus tool."""

    courses: list[ParsedCourse]


class EffortEstimate(BaseModel):
    assignment_title: str
    estimated_hours: float
    rationale: str
    
class EffortEstimates(BaseModel):
    """Top-level structured-output container for estimate_effort."""

    estimates: list[EffortEstimate]

    

class ScheduleBlockOut(BaseModel):
    assignment_id: str | None
    assignment_title: str | None
    day: date
    start_time: time
    hours: float
    pinned: bool = False

    model_config = {"from_attributes": True}


class ScheduleOut(BaseModel):
    blocks: list[ScheduleBlockOut]
    unscheduled: list[str] = Field(
        default_factory=list,
        description="Assignment titles that did not fit in available time.",
    )
    explanation: str | None = None
