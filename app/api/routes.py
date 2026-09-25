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
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.graph import build_graph, key_for
from app.agent.tools.parse_syllabus import extract_text
from app.config import get_settings
from app.db import SessionLocal, get_db
from app.models import Assignment, Availability, Course, ScheduleBlock, User
from app.scheduler.capacity import build_capacity
from app.scheduler.core import Block, Task, build_schedule
from app.schemas import (
    AssignmentOut,
    AssignmentPatch,
    BlockPatch,
    ScheduleBlockOut,
    ScheduleOut,
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


def _reschedule(db: Session, user: User) -> dict:
    """Rebuild the user's schedule from persisted assignments.

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

    done_hours: dict[str, float] = {}
    for row in pinned_rows:
        if row.assignment_id:
            key = str(row.assignment_id)
            done_hours[key] = done_hours.get(key, 0.0) + row.hours

    tasks: list[Task] = []
    for a in assignments:
        if a.is_category:
            continue  # a bucket, not work
        if a.due_at is None:
            continue  # waiting on a date from the user
        remaining = a.estimated_hours - done_hours.get(str(a.id), 0.0)
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
    capacity = build_capacity(
        date.today(),
        PLANNING_HORIZON_DAYS,
        availability=availability,
        default_hours=get_settings().max_hours_per_day,
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

    plan = build_schedule(tasks, capacity, pinned=pinned_blocks)

    for stale in db.scalars(
        select(ScheduleBlock).where(
            ScheduleBlock.user_id == user.id, ScheduleBlock.pinned.is_(False)
        )
    ):
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
            a.title for a in assignments if a.due_at is None and not a.is_category
        ],
        "categories": [a.title for a in assignments if a.is_category],
    }


def _persist_extraction(db: Session, user: User, extraction, hours: dict) -> list[str]:
    """Write courses and assignments. Returns the course codes written.

    Nothing is dropped: categories and undated items are stored with their flags
    so the user can correct them. Flushes but does not commit.
    """
    codes: list[str] = []
    for parsed in extraction.courses:
        # Re-uploading a syllabus means "this course, again" -- replace it rather
        # than stacking a second copy (which doubled every hour on the calendar).
        for stale in db.scalars(
            select(Course).where(Course.user_id == user.id, Course.code == parsed.code)
        ):
            db.delete(stale)
        db.flush()

        course = Course(
            user_id=user.id, code=parsed.code, title=parsed.title, term=parsed.term
        )
        db.add(course)
        db.flush()
        codes.append(parsed.code)

        for item in parsed.assignments:
            db.add(
                Assignment(
                    course_id=course.id,
                    title=item.title,
                    due_at=item.due_at,
                    available_at=item.available_at,
                    weight=item.weight,
                    estimated_hours=hours.get(key_for(parsed.code, item.title), 2.0),
                    notes=item.notes,
                    is_category=item.is_category,
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
        needs_date=a.due_at is None and not a.is_category,
        is_category=a.is_category,
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

    codes = _persist_extraction(db, user, result["extraction"], result["hours"])

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

        codes = _persist_extraction(db, user, state["extraction"], state.get("hours", {}))
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
        rows = [a for a in rows if (a.due_at is None and not a.is_category) == needs_date]
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
    )


@router.post("/reschedule")
def reschedule(external_id: str = "demo", db: Session = Depends(get_db)):
    """Rebuild the schedule from what's in the database. No LLM call."""
    user = _require_user(db, external_id)
    summary = _reschedule(db, user)
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
        )
        for b in rows
    ]
    return ScheduleOut(blocks=blocks, unscheduled=[])
