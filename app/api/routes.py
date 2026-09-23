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

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.graph import build_graph, key_for
from app.agent.tools.parse_syllabus import extract_text
from app.config import get_settings
from app.db import get_db
from app.models import Assignment, Availability, Course, ScheduleBlock, User
from app.scheduler.capacity import build_capacity
from app.scheduler.core import Block, Task, build_schedule
from app.schemas import AssignmentOut, AssignmentPatch, ScheduleBlockOut, ScheduleOut

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

    for parsed in result["extraction"].courses:
        course = Course(
            user_id=user.id, code=parsed.code, title=parsed.title, term=parsed.term
        )
        db.add(course)
        db.flush()

        for item in parsed.assignments:
            # Categories are stored, not dropped. A syllabus that says
            # "Homework: 30%" with no listed assignments is information the
            # user needs to act on, and an exam the model mislabels as a
            # category must not disappear along with it.
            db.add(
                Assignment(
                    course_id=course.id,
                    title=item.title,
                    due_at=item.due_at,
                    available_at=item.available_at,
                    weight=item.weight,
                    estimated_hours=result["hours"].get(
                        key_for(parsed.code, item.title), 2.0
                    ),
                    notes=item.notes,
                    is_category=item.is_category,
                )
            )
    db.flush()

    summary = _reschedule(db, user)
    db.commit()

    return {
        "user_id": str(user.id),
        "trace": result.get("trace", []),
        "courses": [c.code for c in result["extraction"].courses],
        **summary,
    }


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
