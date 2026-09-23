"""HTTP surface.

Only this module touches both the database and the agent. The graph stays pure;
everything transactional happens here.
"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.graph import build_graph, key_for
from app.agent.tools.parse_syllabus import extract_text
from app.config import get_settings
from app.db import get_db
from app.models import Assignment, Availability, Course, ScheduleBlock, User
from app.scheduler.capacity import build_capacity
from app.schemas import ScheduleBlockOut, ScheduleOut

router = APIRouter()

PLANNING_HORIZON_DAYS = 120


def _get_or_create_user(db: Session, external_id: str) -> User:
    user = db.scalar(select(User).where(User.external_id == external_id))
    if user is None:
        user = User(external_id=external_id)
        db.add(user)
        db.flush()
    return user


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
    """Parse a syllabus, schedule it, and persist the result.

    Returns the agent's trace alongside the schedule -- week 2 streams that
    trace over SSE, and returning it now keeps the shape stable.
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

    availability = list(
        db.scalars(select(Availability).where(Availability.user_id == user.id))
    )
    capacity = build_capacity(
        date.today(),
        PLANNING_HORIZON_DAYS,
        availability=availability,
        default_hours=get_settings().max_hours_per_day,
    )

    result = build_graph().invoke(
        {
            "syllabus_text": text,
            "term_start": start,
            "capacity": capacity,
            "credit_hours": credit_hours,
        }
    )

    # ---- persist ----------------------------------------------------------
    assignments_by_key: dict[str, Assignment] = {}

    for parsed in result["extraction"].courses:
        course = Course(user_id=user.id, code=parsed.code, title=parsed.title, term=parsed.term)
        db.add(course)
        db.flush()

        for item in parsed.assignments:
            if item.is_category or item.due_at is None:
                continue  # not schedulable; week 2 asks the user for a date
            key = key_for(parsed.code, item.title)
            row = Assignment(
                course_id=course.id,
                title=item.title,
                due_at=item.due_at,
                available_at=item.available_at,
                weight=item.weight,
                estimated_hours=result["hours"].get(key, 2.0),
                notes=item.notes,
            )
            db.add(row)
            assignments_by_key[key] = row
        db.flush()

    # Replace the user's unpinned blocks; anything they dragged survives.
    for old in db.scalars(
        select(ScheduleBlock).where(
            ScheduleBlock.user_id == user.id, ScheduleBlock.pinned.is_(False)
        )
    ):
        db.delete(old)

    for block in result["plan"].blocks:
        assignment = assignments_by_key.get(block.task_id or "")
        db.add(
            ScheduleBlock(
                user_id=user.id,
                assignment_id=assignment.id if assignment else None,
                day=block.day,
                start_time=block.start_time,
                hours=block.hours,
                pinned=block.pinned,
            )
        )

    db.commit()

    return {
        "user_id": str(user.id),
        "trace": result.get("trace", []),
        "courses": [c.code for c in result["extraction"].courses],
        "blocks": len(result["plan"].blocks),
        "unscheduled": result["plan"].unscheduled,
        "needs_date": [
            a.title
            for c in result["extraction"].courses
            for a in c.assignments
            if a.is_category or a.due_at is None
        ],
    }


@router.get("/schedule", response_model=ScheduleOut)
def get_schedule(external_id: str = "demo", db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.external_id == external_id))
    if user is None:
        raise HTTPException(404, f"No user with external_id={external_id!r}.")

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
