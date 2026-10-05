"""HTTP surface.

Only this module touches both the database and the agent. The graph stays pure;
everything transactional happens here.

One rule keeps the two scheduling paths honest: `_reschedule` is the ONLY writer
of ScheduleBlock rows, and it works entirely from persisted assignments with no
LLM call. Upload uses the agent to read and estimate; scheduling always happens
the same way afterwards, whether triggered by an upload, a corrected date, or
(in week 3) a disruption.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.graph import build_graph, key_for
from app.agent.tools.classify import is_participation_title
from app.agent.tools.meetings import meeting_issue, meeting_rows
from app.agent.tools.parse_syllabus import extract_text
from app.config import get_settings
from app.ical import calendar as ical_calendar
from app.db import SessionLocal, get_db
from app.models import Assignment, Availability, Commitment, Course, ScheduleBlock, User
from app.scheduler.capacity import DEFAULT_START, build_capacity, occurs_on
from app.scheduler.core import Block, Task, build_schedule, churn, replan
from app.scheduler.learning import rescale, update_multiplier
from app.schemas import (
    AssignmentOut,
    AssignmentPatch,
    BlockPatch,
    CheckIn,
    CommitmentIn,
    CommitmentOut,
    CommitmentPatch,
    ScheduleBlockOut,
    ScheduleOut,
    StudySettings,
)

router = APIRouter()

PLANNING_HORIZON_DAYS = 120


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _as_utc(value: datetime | None) -> datetime | None:
    """Attach UTC to a naive datetime.

    The DateTime columns are timezone=True, so values read back from Postgres
    are aware, while a datetime parsed from JSON without an offset is naive.
    Comparing the two raises TypeError, so everything entering the database
    gets normalised here first.
    """
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _get_or_create_user(db: Session, external_id: str) -> User:
    user = db.scalar(select(User).where(User.external_id == external_id))
    if user is None:
        user = User(external_id=external_id)
        db.add(user)
        db.flush()
    return user


def _require_user(db: Session, external_id: str) -> User:
    user = db.scalar(select(User).where(User.external_id == external_id))
    if user is None:
        raise HTTPException(404, f"No user with external_id={external_id!r}.")
    return user


def _user_assignments(db: Session, user: User) -> list[Assignment]:
    return list(
        db.scalars(
            select(Assignment).join(Course).where(Course.user_id == user.id)
        )
    )


def _reschedule(db: Session, user: User, *, fresh: bool = False) -> dict:
    """Rebuild the user's schedule from persisted assignments.

    By default this is a replan: upcoming blocks that are still valid stay
    exactly where they are and only displaced hours move, so fixing one date
    doesn't reshuffle the whole month. `fresh=True` ignores the old plan.

    Pinned blocks survive untouched and are charged against both the day's
    capacity and their assignment's remaining hours -- work the user already
    committed to a slot should not be planned twice.

    Flushes but does not commit; the caller owns the transaction.
    """
    assignments = _user_assignments(db, user)
    by_id = {str(a.id): a for a in assignments}

    pinned_rows = list(
        db.scalars(
            select(ScheduleBlock).where(
                ScheduleBlock.user_id == user.id, ScheduleBlock.pinned.is_(True)
            )
        )
    )

    today = date.today()

    # Hours already spoken for, per assignment: pinned blocks, plus past blocks
    # not yet reviewed (assumed done until the check-in says otherwise -- else
    # every passing day would replan yesterday's work). Reviewed blocks don't
    # count here; their real hours live in Assignment.completed_hours.
    accounted = db.scalars(
        select(ScheduleBlock).where(
            ScheduleBlock.user_id == user.id,
            ScheduleBlock.completed.is_(False),
        )
    )
    done_hours: dict[str, float] = {}
    for row in accounted:
        if row.assignment_id and (row.pinned or row.day < today):
            key = str(row.assignment_id)
            done_hours[key] = done_hours.get(key, 0.0) + row.hours

    tasks: list[Task] = []
    for a in assignments:
        if not a.schedulable:
            continue  # a bucket, credit for showing up, or finished
        if a.due_at is None:
            continue  # waiting on a date from the user
        remaining = (
            a.estimated_hours - (a.completed_hours or 0.0) - done_hours.get(str(a.id), 0.0)
        )
        if remaining <= 0:
            continue
        tasks.append(
            Task(
                id=str(a.id),
                title=a.title,
                due=a.due_at.date(),
                hours=remaining,
                weight=a.weight,
                earliest_start=a.available_at.date() if a.available_at else None,
            )
        )

    availability = list(
        db.scalars(select(Availability).where(Availability.user_id == user.id))
    )
    commitments = list(
        db.scalars(
            select(Commitment).where(
                Commitment.user_id == user.id, Commitment.confirmed.is_(True)
            )
        )
    )
    capacity = build_capacity(
        date.today(),
        PLANNING_HORIZON_DAYS,
        availability=availability,
        default_hours=user.max_hours_per_day or get_settings().max_hours_per_day,
        window_start=user.study_start,
        window_end=user.study_end,
        commitments=commitments,
    )

    pinned_blocks = [
        Block(
            task_id=str(r.assignment_id) if r.assignment_id else None,
            title=by_id[str(r.assignment_id)].title if str(r.assignment_id) in by_id else None,
            day=r.day,
            start_time=r.start_time,
            hours=r.hours,
            pinned=True,
        )
        for r in pinned_rows
    ]

    # Only upcoming blocks are replanned. Past ones are history: they stay on the
    # calendar and wait for the check-in.
    stale_rows = list(
        db.scalars(
            select(ScheduleBlock).where(
                ScheduleBlock.user_id == user.id,
                ScheduleBlock.pinned.is_(False),
                ScheduleBlock.day >= today,
            )
        )
    )
    previous = [
        Block(
            task_id=str(r.assignment_id) if r.assignment_id else None,
            title=None,
            day=r.day,
            start_time=r.start_time,
            hours=r.hours,
        )
        for r in stale_rows
    ]
    if fresh or not previous:
        plan = build_schedule(tasks, capacity, pinned=pinned_blocks)
        moved = churn(previous, plan.blocks)
    else:
        plan, moved = replan(previous, tasks, capacity, pinned=pinned_blocks)

    for stale in stale_rows:
        db.delete(stale)
    db.flush()

    written = 0
    for block in plan.blocks:
        if block.pinned:
            continue  # already in the table
        db.add(
            ScheduleBlock(
                user_id=user.id,
                assignment_id=uuid.UUID(block.task_id) if block.task_id else None,
                day=block.day,
                start_time=block.start_time,
                hours=block.hours,
                pinned=False,
            )
        )
        written += 1
    db.flush()

    return {
        "scheduled": len(tasks),
        "blocks": written,
        "pinned_kept": len(pinned_rows),
        "unscheduled": plan.unscheduled,
        "needs_date": [
            a.title for a in assignments if a.needs_date
        ],
        "categories": [a.title for a in assignments if a.is_category],
        # How much of the previous plan survived: the stability metric.
        "churn": {"kept": moved.kept, "moved": moved.moved, "added": moved.added},
    }


def _persist_extraction(
    db: Session, user: User, extraction, hours: dict, term_start: date | None = None
) -> list[str]:
    """Write courses and assignments. Returns the course codes written.

    Nothing is dropped: categories and undated items are stored with their flags
    so the user can correct them. Flushes but does not commit.
    """
    codes: list[str] = []
    for parsed in extraction.courses:
        # Re-uploading a syllabus means "this course, again" -- replace it rather
        # than stacking a second copy (which doubled every hour on the calendar).
        # What check-ins learned about this course survives the re-upload.
        multiplier = 1.0
        for stale in db.scalars(
            select(Course).where(Course.user_id == user.id, Course.code == parsed.code)
        ):
            multiplier = stale.effort_multiplier or 1.0
            db.delete(stale)
        db.flush()

        course = Course(
            user_id=user.id,
            code=parsed.code,
            title=parsed.title,
            term=parsed.term,
            effort_multiplier=multiplier,
        )
        db.add(course)
        db.flush()
        codes.append(parsed.code)

        for item in parsed.assignments:
            # Attendance and the like: graded, but nothing to date or schedule.
            participation = item.is_participation or is_participation_title(item.title)
            db.add(
                Assignment(
                    course_id=course.id,
                    title=item.title,
                    due_at=item.due_at,
                    available_at=item.available_at,
                    weight=item.weight,
                    estimated_hours=rescale(
                        hours.get(key_for(parsed.code, item.title), 2.0), 1.0, multiplier
                    ),
                    notes=item.notes,
                    is_category=item.is_category and not participation,
                    is_participation=participation,
                )
            )

        # Class meetings become commitments, unconfirmed until the user checks
        # them. They hang off the course, so a re-upload replaces them too.
        rows, _skipped = meeting_rows(parsed.code, parsed.meetings)
        for r in rows:
            db.add(
                Commitment(
                    user_id=user.id,
                    course_id=course.id,
                    title=r.title,
                    kind="class",
                    source="syllabus",
                    weekday=r.weekday,
                    starts_on=term_start,
                    start_time=r.start,
                    end_time=r.end,
                    confirmed=False,
                    note=r.note,
                )
            )
    db.flush()
    return codes


def _sse(event: str, payload: dict) -> str:
    """One server-sent event. The blank line terminates the frame."""
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


def _assignment_out(a: Assignment) -> AssignmentOut:
    return AssignmentOut(
        id=str(a.id),
        course_code=a.course.code,
        title=a.title,
        due_at=a.due_at,
        available_at=a.available_at,
        weight=a.weight,
        estimated_hours=a.estimated_hours,
        needs_date=a.needs_date,
        is_category=a.is_category,
        is_participation=a.is_participation,
        color=a.color,
    )


# --------------------------------------------------------------------------
# endpoints
# --------------------------------------------------------------------------


@router.get("/healthz")
def healthz():
    return {"status": "ok"}


@router.post("/syllabus")
async def upload_syllabus(
    file: UploadFile = File(...),
    external_id: str = Form("demo"),
    term_start: str | None = Form(None),
    credit_hours: float = Form(3.0),
    db: Session = Depends(get_db),
):
    """Parse a syllabus, persist what it found, then schedule.

    Items with no date are persisted too, flagged `needs_date`. They are not
    scheduled -- but they exist, so the user can supply a date and reschedule
    rather than re-uploading the file.
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Empty upload.")
    try:
        text = extract_text(raw)
    except ValueError as exc:
        raise HTTPException(415, str(exc)) from exc
    if not text.strip():
        raise HTTPException(
            422,
            "No text layer found. Scanned PDFs need OCR, which isn't supported yet.",
        )

    start = date.fromisoformat(term_start) if term_start else date.today()
    user = _get_or_create_user(db, external_id)

    result = build_graph().invoke(
        {
            "syllabus_text": text,
            "term_start": start,
            "credit_hours": credit_hours,
        }
    )

    codes = _persist_extraction(db, user, result["extraction"], result["hours"], start)

    summary = _reschedule(db, user)
    db.commit()

    return {
        "user_id": str(user.id),
        "trace": result.get("trace", []),
        "courses": codes,
        **summary,
    }


def _syllabus_events(
    text: str, external_id: str, term_start: date, credit_hours: float
) -> Iterator[str]:
    """Run the agent, emitting one event per completed node, then schedule.

    This opens its own Session rather than taking Depends(get_db). Since FastAPI
    0.106 a yield-dependency's teardown runs before the response body is sent, so
    a session from get_db would already be closed by the time this generator runs.
    """
    db = SessionLocal()
    try:
        user = _get_or_create_user(db, external_id)
        db.commit()
        yield _sse("start", {"user_id": str(user.id)})

        state: dict = {}
        for update in build_graph().stream(
            {
                "syllabus_text": text,
                "term_start": term_start,
                "credit_hours": credit_hours,
            },
            stream_mode="updates",
        ):
            for node, delta in update.items():
                state.update(delta)
                yield _sse("node", {"node": node, "trace": delta.get("trace", [])})

        codes = _persist_extraction(
            db, user, state["extraction"], state.get("hours", {}), term_start
        )
        yield _sse("persisted", {"courses": codes})

        summary = _reschedule(db, user)
        db.commit()
        yield _sse("scheduled", summary)
        yield _sse("done", {"user_id": str(user.id)})
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        # The 200 and its headers are long gone, so a mid-stream failure can only
        # be reported as an event. Clients must handle this, not just onerror.
        yield _sse("error", {"detail": f"{type(exc).__name__}: {exc}"})
    finally:
        db.close()


@router.post("/syllabus/stream")
async def upload_syllabus_stream(
    file: UploadFile = File(...),
    external_id: str = Form("demo"),
    term_start: str | None = Form(None),
    credit_hours: float = Form(3.0),
):
    """Same work as POST /syllabus, streamed as server-sent events.

    Validation happens here, before the stream opens, so a bad upload gets a real
    4xx rather than a 200 whose body says it failed.

    This is a POST, so EventSource cannot consume it -- the client uses fetch()
    and reads response.body. The alternative (POST returning a job id, then an
    EventSource GET) needs a job store for no benefit at this scale.
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Empty upload.")
    try:
        text = extract_text(raw)
    except ValueError as exc:
        raise HTTPException(415, str(exc)) from exc
    if not text.strip():
        raise HTTPException(
            422,
            "No text layer found. Scanned PDFs need OCR, which isn't supported yet.",
        )

    start = date.fromisoformat(term_start) if term_start else date.today()
    return StreamingResponse(
        _syllabus_events(text, external_id, start, credit_hours),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/assignments", response_model=list[AssignmentOut])
def list_assignments(
    external_id: str = "demo",
    needs_date: bool | None = None,
    db: Session = Depends(get_db),
):
    """All assignments. `?needs_date=true` returns just the ones waiting on a
    date -- that filter is what the upload flow's follow-up form reads."""
    user = _require_user(db, external_id)
    rows = _user_assignments(db, user)
    if needs_date is not None:
        rows = [a for a in rows if a.needs_date == needs_date]
    rows.sort(key=lambda a: (a.due_at is not None, a.due_at or datetime.max, a.title))
    return [_assignment_out(a) for a in rows]


@router.patch("/assignments/{assignment_id}", response_model=AssignmentOut)
def patch_assignment(
    assignment_id: uuid.UUID,
    patch: AssignmentPatch,
    external_id: str = "demo",
    db: Session = Depends(get_db),
):
    """Correct an assignment.

    `is_category=false` promotes a mislabelled bucket into real work -- the
    model routinely calls an undated final exam a category, and the user is the
    one who can say otherwise.

    Does NOT reschedule: call POST /reschedule when the user is done editing, so
    a form with five corrections costs one rebuild instead of five.
    """
    user = _require_user(db, external_id)
    row = db.get(Assignment, assignment_id)
    if row is None or row.course.user_id != user.id:
        raise HTTPException(404, "No such assignment.")

    fields = patch.model_dump(exclude_unset=True)
    if "estimated_hours" in fields and fields["estimated_hours"] is not None:
        if fields["estimated_hours"] <= 0:
            raise HTTPException(422, "estimated_hours must be positive.")
    for name, value in fields.items():
        setattr(row, name, _as_utc(value) if isinstance(value, datetime) else value)

    if row.due_at and row.available_at and row.available_at > row.due_at:
        raise HTTPException(422, "available_at cannot be after due_at.")

    db.commit()
    db.refresh(row)
    return _assignment_out(row)


@router.patch("/blocks/{block_id}", response_model=ScheduleBlockOut)
def patch_block(
    block_id: uuid.UUID,
    patch: BlockPatch,
    external_id: str = "demo",
    db: Session = Depends(get_db),
):
    """Move a block. Any edit pins it.

    Pinning is the whole point: a dragged block is a commitment, so the next
    reschedule leaves it alone and charges its hours against the assignment
    instead of planning them again.
    """
    user = _require_user(db, external_id)
    row = db.get(ScheduleBlock, block_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "No such block.")

    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(422, "Nothing to change.")
    if fields.get("hours") is not None and fields["hours"] < 0.25:
        # The calendar's smallest step. Anything shorter can't be placed on the
        # 15-minute grid or labelled.
        raise HTTPException(422, "A study block must be at least 15 minutes.")

    new_day = fields.get("day") or row.day
    new_start = fields.get("start_time") or row.start_time
    new_hours = fields.get("hours") or row.hours
    start_dt = datetime.combine(new_day, new_start)
    end_dt = start_dt + timedelta(hours=new_hours)

    # Pinned blocks are never moved by the scheduler, so two pinned blocks that
    # overlap would stay overlapped forever. Refuse the drop instead.
    for other in db.scalars(
        select(ScheduleBlock).where(
            ScheduleBlock.user_id == user.id,
            ScheduleBlock.pinned.is_(True),
            ScheduleBlock.day == new_day,
            ScheduleBlock.id != row.id,
        )
    ):
        o_start = datetime.combine(other.day, other.start_time)
        o_end = o_start + timedelta(hours=other.hours)
        if start_dt < o_end and o_start < end_dt:
            raise HTTPException(
                409,
                f"That overlaps another pinned block "
                f"({o_start:%-I:%M}–{o_end:%-I:%M %p}). Move it somewhere free.",
            )

    # Same reasoning for commitments: a pinned block on top of a lecture would
    # never move off it.
    for c in db.scalars(
        select(Commitment).where(
            Commitment.user_id == user.id, Commitment.confirmed.is_(True)
        )
    ):
        if not occurs_on(c, new_day):
            continue
        c_start = datetime.combine(new_day, c.start_time)
        c_end = datetime.combine(new_day, c.end_time)
        if start_dt < c_end and c_start < end_dt:
            raise HTTPException(
                409,
                f"That overlaps {c.title} ({c_start:%-I:%M}–{c_end:%-I:%M %p}).",
            )

    for name, value in fields.items():
        if value is not None:
            setattr(row, name, value)
    row.pinned = True

    db.commit()
    db.refresh(row)
    return ScheduleBlockOut(
        id=str(row.id),
        assignment_id=str(row.assignment_id) if row.assignment_id else None,
        assignment_title=row.assignment.title if row.assignment else None,
        day=row.day,
        start_time=row.start_time,
        hours=row.hours,
        pinned=row.pinned,
        completed=row.completed,
    )


@router.post("/reschedule")
def reschedule(
    external_id: str = "demo", fresh: bool = False, db: Session = Depends(get_db)
):
    """Rebuild the schedule from what's in the database. No LLM call.

    Keeps still-valid blocks in place unless `fresh=true`."""
    user = _require_user(db, external_id)
    summary = _reschedule(db, user, fresh=fresh)
    db.commit()
    return summary


@router.get("/courses")
def list_courses(external_id: str = "demo", db: Session = Depends(get_db)):
    user = _require_user(db, external_id)
    rows = db.scalars(select(Course).where(Course.user_id == user.id))
    return [
        {
            "id": str(c.id),
            "code": c.code,
            "title": c.title,
            "term": c.term,
            "assignments": len(c.assignments),
        }
        for c in rows
    ]


@router.delete("/courses/{course_id}")
def delete_course(course_id: uuid.UUID, external_id: str = "demo", db: Session = Depends(get_db)):
    """Remove a course with its assignments and blocks, then rebuild."""
    user = _require_user(db, external_id)
    course = db.get(Course, course_id)
    if course is None or course.user_id != user.id:
        raise HTTPException(404, "No such course.")
    db.delete(course)
    db.flush()
    summary = _reschedule(db, user)
    db.commit()
    return summary


@router.get("/schedule", response_model=ScheduleOut)
def get_schedule(external_id: str = "demo", db: Session = Depends(get_db)):
    user = _require_user(db, external_id)
    rows = db.scalars(
        select(ScheduleBlock)
        .where(ScheduleBlock.user_id == user.id)
        .order_by(ScheduleBlock.day, ScheduleBlock.start_time)
    )
    blocks = [
        ScheduleBlockOut(
            id=str(b.id),
            assignment_id=str(b.assignment_id) if b.assignment_id else None,
            assignment_title=b.assignment.title if b.assignment else None,
            day=b.day,
            start_time=b.start_time,
            hours=b.hours,
            pinned=b.pinned,
            completed=b.completed,
        )
        for b in rows
    ]
    return ScheduleOut(blocks=blocks, unscheduled=[])


# --------------------------------------------------------------------------
# commitments and study window
# --------------------------------------------------------------------------


def _commitment_out(c: Commitment) -> CommitmentOut:
    return CommitmentOut(
        id=str(c.id),
        confirmed=c.confirmed,
        warning=meeting_issue(c.start_time, c.end_time) if not c.confirmed else None,
        note=c.note,
        title=c.title,
        kind=c.kind,
        source=c.source,
        weekday=c.weekday,
        on_date=c.on_date,
        starts_on=c.starts_on,
        ends_on=c.ends_on,
        start_time=c.start_time,
        end_time=c.end_time,
        course_id=str(c.course_id) if c.course_id else None,
        course_code=c.course.code if c.course else None,
    )


@router.get("/commitments", response_model=list[CommitmentOut])
def list_commitments(external_id: str = "demo", db: Session = Depends(get_db)):
    user = _require_user(db, external_id)
    rows = db.scalars(
        select(Commitment)
        .where(Commitment.user_id == user.id)
        .order_by(Commitment.weekday, Commitment.on_date, Commitment.start_time)
    )
    return [_commitment_out(c) for c in rows]


@router.post("/commitments", response_model=CommitmentOut, status_code=201)
def create_commitment(
    body: CommitmentIn, external_id: str = "demo", db: Session = Depends(get_db)
):
    """Add a busy stretch and rebuild around it."""
    user = _get_or_create_user(db, external_id)
    course_id = None
    if body.course_id:
        try:
            course = db.get(Course, uuid.UUID(body.course_id))
        except ValueError:
            course = None
        if course is None or course.user_id != user.id:
            raise HTTPException(404, "No such course.")
        course_id = course.id
    row = Commitment(
        user_id=user.id,
        course_id=course_id,
        source="manual",
        **body.model_dump(exclude={"course_id"}),
    )
    db.add(row)
    db.flush()
    _reschedule(db, user)
    db.commit()
    db.refresh(row)
    return _commitment_out(row)


@router.delete("/commitments/{commitment_id}")
def delete_commitment(
    commitment_id: uuid.UUID, external_id: str = "demo", db: Session = Depends(get_db)
):
    user = _require_user(db, external_id)
    row = db.get(Commitment, commitment_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "No such commitment.")
    db.delete(row)
    db.flush()
    summary = _reschedule(db, user)
    db.commit()
    return summary


@router.patch("/commitments/{commitment_id}", response_model=CommitmentOut)
def patch_commitment(
    commitment_id: uuid.UUID,
    patch: CommitmentPatch,
    external_id: str = "demo",
    db: Session = Depends(get_db),
):
    """Correct a commitment's times or name, or confirm one read from a syllabus.
    Rebuilds, since either can change where study fits."""
    user = _require_user(db, external_id)
    row = db.get(Commitment, commitment_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "No such commitment.")
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(422, "Nothing to change.")
    start = fields.get("start_time") or row.start_time
    end = fields.get("end_time") or row.end_time
    if end <= start:
        raise HTTPException(422, "A commitment must end after it starts.")
    for name, value in fields.items():
        if value is not None:
            setattr(row, name, value)
    db.flush()
    _reschedule(db, user)
    db.commit()
    db.refresh(row)
    return _commitment_out(row)


def _settings_out(user: User) -> dict:
    return {
        "study_start": user.study_start,
        "study_end": user.study_end,
        "max_hours_per_day": user.max_hours_per_day,
        # What the scheduler actually uses when a field is unset.
        "effective": {
            "study_start": user.study_start or DEFAULT_START,
            "study_end": user.study_end,
            "max_hours_per_day": user.max_hours_per_day or get_settings().max_hours_per_day,
        },
    }


@router.get("/settings")
def get_study_settings(external_id: str = "demo", db: Session = Depends(get_db)):
    user = _get_or_create_user(db, external_id)
    db.commit()
    return _settings_out(user)


@router.put("/settings")
def put_study_settings(
    body: StudySettings, external_id: str = "demo", db: Session = Depends(get_db)
):
    """Replace the study window and daily cap, then rebuild."""
    user = _get_or_create_user(db, external_id)
    user.study_start = body.study_start
    user.study_end = body.study_end
    user.max_hours_per_day = body.max_hours_per_day
    db.flush()
    _reschedule(db, user)
    db.commit()
    return _settings_out(user)


# --------------------------------------------------------------------------
# weekly check-in
# --------------------------------------------------------------------------


def _unreviewed(db: Session, user: User) -> list[ScheduleBlock]:
    """Past study blocks the user hasn't reported on yet."""
    return list(
        db.scalars(
            select(ScheduleBlock)
            .where(
                ScheduleBlock.user_id == user.id,
                ScheduleBlock.completed.is_(False),
                ScheduleBlock.day < date.today(),
                ScheduleBlock.assignment_id.is_not(None),
            )
            .order_by(ScheduleBlock.day, ScheduleBlock.start_time)
        )
    )


@router.get("/checkin")
def get_checkin(external_id: str = "demo", db: Session = Depends(get_db)):
    """What was planned since the last check-in, per task."""
    user = _get_or_create_user(db, external_id)
    rows = _unreviewed(db, user)
    tasks: dict[str, dict] = {}
    for r in rows:
        a = r.assignment
        t = tasks.setdefault(
            str(a.id),
            {
                "assignment_id": str(a.id),
                "title": a.title,
                "course_code": a.course.code,
                "due_at": a.due_at,
                "estimated_hours": a.estimated_hours,
                "completed_hours": a.completed_hours or 0.0,
                "planned_hours": 0.0,
            },
        )
        t["planned_hours"] += r.hours
    db.commit()
    return {
        "since": rows[0].day if rows else None,
        "tasks": sorted(tasks.values(), key=lambda t: (t["due_at"] is None, t["due_at"])),
    }


@router.post("/checkin")
def post_checkin(body: CheckIn, external_id: str = "demo", db: Session = Depends(get_db)):
    """Record what actually happened, learn from it, and replan.

    Per task: hours spent are added to its total. Finished tasks stop being
    scheduled and teach their course's effort multiplier (actual / estimated);
    when that moves, the course's untouched tasks are re-estimated with it.
    Unfinished tasks can carry a new "hours left" guess. Every past block is
    then marked reviewed, so its hours count only through what was reported.
    """
    user = _require_user(db, external_id)
    rows = _unreviewed(db, user)

    owned = {str(a.id): a for a in _user_assignments(db, user)}
    entries = []
    for e in body.entries:
        a = owned.get(e.assignment_id)
        if a is None:
            raise HTTPException(404, f"No such assignment: {e.assignment_id}")
        entries.append((e, a))

    adjustments: dict[str, dict] = {}
    reported = {a.id for _, a in entries}
    for e, a in entries:
        a.completed_hours = (a.completed_hours or 0.0) + e.hours_spent
        if e.done:
            a.done = True
            course = a.course
            before = course.effort_multiplier or 1.0
            after = update_multiplier(before, a.completed_hours, a.estimated_hours)
            course.effort_multiplier = after
            adj = adjustments.setdefault(
                course.code,
                {"course_code": course.code, "before": before, "after": after, "rescaled": 0},
            )
            adj["after"] = after
            if after != before:
                for sibling in course.assignments:
                    untouched = (
                        sibling.schedulable
                        and sibling.id not in reported
                        and not (sibling.completed_hours or 0.0)
                    )
                    if untouched:
                        sibling.estimated_hours = rescale(sibling.estimated_hours, before, after)
                        adj["rescaled"] += 1
        elif e.hours_left is not None:
            a.estimated_hours = max(0.25, a.completed_hours + e.hours_left)

    for r in rows:
        r.completed = True
    db.flush()

    summary = _reschedule(db, user)
    db.commit()
    return {
        **summary,
        "reviewed_blocks": len(rows),
        "adjustments": [a for a in adjustments.values() if a["after"] != a["before"]],
    }


# --------------------------------------------------------------------------
# calendar export
# --------------------------------------------------------------------------


@router.get("/calendar.ics")
def calendar_ics(external_id: str = "demo", db: Session = Depends(get_db)):
    """Upcoming study blocks as an .ics file, for Google/Apple/Outlook.

    Blocks keep stable UIDs only until the next rebuild (rows are rewritten),
    so importing again after changes can duplicate events in apps that don't
    replace by calendar. Subscribing to this URL avoids that once hosted.
    """
    user = _require_user(db, external_id)
    rows = db.scalars(
        select(ScheduleBlock)
        .where(ScheduleBlock.user_id == user.id, ScheduleBlock.day >= date.today())
        .order_by(ScheduleBlock.day, ScheduleBlock.start_time)
    )
    return Response(
        ical_calendar(list(rows)),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="cadence.ics"'},
    )
