"""Pydantic schemas. These double as the structured-output contracts for the
LLM tools, so keep them tight and well-described."""

from __future__ import annotations

from datetime import date, datetime, time

from typing import Literal

from pydantic import BaseModel, Field, model_validator


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
    is_participation: bool = Field(
        False,
        description=(
            "True for credit earned by showing up or taking part -- attendance, "
            "participation, in-class activities, clicker questions. No study time, "
            "no due date. Leave due_at null for these."
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


class ParsedMeeting(BaseModel):
    """A regular class meeting: when the user is in a lecture, lab or section."""

    days: list[Literal["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]] = Field(
        description="Weekdays it meets. 'TR' or 'Tu/Th' -> ['Tue', 'Thu']; 'MWF' -> ['Mon', 'Wed', 'Fri']."
    )
    start_time: str = Field(description="24-hour HH:MM, exactly as stated. 6:00 PM -> '18:00'.")
    end_time: str = Field(description="24-hour HH:MM, exactly as stated, even if it looks wrong.")
    kind: Literal["lecture", "lab", "discussion", "other"] = "lecture"
    location: str | None = None
    source_text: str = Field(
        description="The line of the syllabus these times came from, copied verbatim."
    )


class ParsedCourse(BaseModel):
    code: str
    title: str
    term: str | None = None
    assignments: list[ParsedAssignment] = []
    meetings: list[ParsedMeeting] = Field(
        default_factory=list,
        description="Regular weekly class meetings. Empty if the syllabus states none.",
    )


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
    id: str
    assignment_id: str | None
    assignment_title: str | None
    day: date
    start_time: time
    hours: float
    pinned: bool = False
    # Reviewed at a check-in (past blocks only).
    completed: bool = False

    model_config = {"from_attributes": True}


class ScheduleOut(BaseModel):
    blocks: list[ScheduleBlockOut]
    unscheduled: list[str] = Field(
        default_factory=list,
        description="Assignment titles that did not fit in available time.",
    )
    explanation: str | None = None


class AssignmentOut(BaseModel):
    id: str
    course_code: str
    title: str
    due_at: datetime | None
    available_at: datetime | None
    weight: float | None
    estimated_hours: float
    needs_date: bool
    is_category: bool
    is_participation: bool = False
    color: str | None = None


class AssignmentPatch(BaseModel):
    """Fields a user may correct. Everything else is derived."""

    due_at: datetime | None = None
    available_at: datetime | None = None
    estimated_hours: float | None = None
    is_category: bool | None = None
    # "#rrggbb" to set, null to go back to the automatic colour.
    color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")


class BlockPatch(BaseModel):
    """A dragged block. Any field present pins the block."""

    day: date | None = None
    start_time: time | None = None
    hours: float | None = None


# --------------------------------------------------------------- commitments


class CommitmentIn(BaseModel):
    """A busy stretch: weekly (`weekday`) or one-off (`on_date`), never both.

    A one-off can span days: `on_date` to `ends_on`, e.g. a week of spring
    break. kind="off" marks a whole day off rather than a few busy hours.
    """

    title: str = Field(min_length=1, max_length=255)
    kind: Literal["class", "work", "other", "off"] = "other"
    weekday: int | None = Field(None, ge=0, le=6, description="0 = Monday")
    on_date: date | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    start_time: time
    end_time: time
    course_id: str | None = None

    @model_validator(mode="after")
    def _check(self):
        if (self.weekday is None) == (self.on_date is None):
            raise ValueError("Give either a weekday (repeats weekly) or a date (one-off).")
        if self.end_time <= self.start_time:
            raise ValueError("A commitment must end after it starts.")
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValueError("ends_on is before starts_on.")
        if self.on_date and self.ends_on and self.ends_on < self.on_date:
            raise ValueError("The last day is before the first.")
        return self


class CommitmentOut(BaseModel):
    id: str
    confirmed: bool = True
    # Something about the times looks off (e.g. a 4h40m lecture). Shown in the
    # confirm step; never blocks anything.
    warning: str | None = None
    # Where it came from: the syllabus line, for extracted meetings.
    note: str | None = None
    title: str
    kind: str
    source: str
    weekday: int | None
    on_date: date | None
    starts_on: date | None
    ends_on: date | None
    start_time: time
    end_time: time
    course_id: str | None
    course_code: str | None


class CommitmentPatch(BaseModel):
    """Correct or confirm a commitment. Confirming puts it into scheduling."""

    title: str | None = Field(None, min_length=1, max_length=255)
    start_time: time | None = None
    end_time: time | None = None
    confirmed: bool | None = None


class CheckInEntry(BaseModel):
    assignment_id: str
    hours_spent: float = Field(ge=0, le=200)
    done: bool = False
    # Not done: how much more the user thinks it needs. Optional.
    hours_left: float | None = Field(None, ge=0, le=200)


class CheckIn(BaseModel):
    entries: list[CheckInEntry]


class StudySettings(BaseModel):
    """When the user is willing to study. Null fields fall back to defaults."""

    study_start: time | None = None
    study_end: time | None = None
    max_hours_per_day: float | None = Field(None, gt=0, le=24)

    @model_validator(mode="after")
    def _check(self):
        if self.study_start and self.study_end and self.study_end <= self.study_start:
            raise ValueError("The study window must end after it starts.")
        return self
