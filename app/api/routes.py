from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import ScheduleOut

router = APIRouter()


@router.post("/syllabus", status_code=202)
async def upload_syllabus(
    user_id: uuid.UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """TODO(week1): read the PDF bytes, run build_graph().invoke(...),
    persist Course/Assignment/ScheduleBlock rows, return the run id."""
    raise NotImplementedError


@router.get("/schedule", response_model=ScheduleOut)
def get_schedule(user_id: uuid.UUID, db: Session = Depends(get_db)):
    """TODO(week1): return the user's ScheduleBlocks joined to assignments."""
    raise NotImplementedError


@router.get("/healthz")
def healthz():
    return {"status": "ok"}
