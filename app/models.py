"""SQLAlchemy models. Week 1 data model: User, Course, Assignment,
Availability, ScheduleBlock."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text, Time, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _pk()
    external_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(320))
    timezone: Mapped[str] = mapped_column(String(64), default="America/New_York")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    courses: Mapped[list[Course]] = relationship(back_populates="user", cascade="all, delete-orphan")
    availability: Mapped[list[Availability]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(32))          # "CAI 6108"
    title: Mapped[str] = mapped_column(String(255))
    term: Mapped[str | None] = mapped_column(String(64))
    # Learned multiplier from the weekly check-in: >1 means this course
    # consistently takes longer than estimated.
    effort_multiplier: Mapped[float] = mapped_column(Float, default=1.0)

    user: Mapped[User] = relationship(back_populates="courses")
    assignments: Mapped[list[Assignment]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )


class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[uuid.UUID] = _pk()
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    weight: Mapped[float | None] = mapped_column(Float)        # fraction of final grade
    estimated_hours: Mapped[float] = mapped_column(Float, default=2.0)
    completed_hours: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str | None] = mapped_column(Text)

    course: Mapped[Course] = relationship(back_populates="assignments")
    blocks: Mapped[list[ScheduleBlock]] = relationship(
        back_populates="assignment", cascade="all, delete-orphan"
    )


class Availability(Base):
    """Recurring weekly availability window."""

    __tablename__ = "availability"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    weekday: Mapped[int] = mapped_column(Integer)   # 0 = Monday ... 6 = Sunday
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    max_hours: Mapped[float | None] = mapped_column(Float)  # cap for this day

    user: Mapped[User] = relationship(back_populates="availability")


class ScheduleBlock(Base):
    __tablename__ = "schedule_blocks"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assignments.id", ondelete="CASCADE"), index=True
    )
    day: Mapped[date] = mapped_column(Date, index=True)
    start_time: Mapped[time] = mapped_column(Time)
    hours: Mapped[float] = mapped_column(Float)
    # True when the user dragged/edited this block. The replan tool treats
    # pinned blocks as hard constraints so replanning preserves user edits.
    pinned: Mapped[bool] = mapped_column(default=False)
    completed: Mapped[bool] = mapped_column(default=False)

    assignment: Mapped[Assignment | None] = relationship(back_populates="blocks")
