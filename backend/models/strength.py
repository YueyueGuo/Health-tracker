from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class StrengthSet(Base):
    """Manually-logged strength training set.

    Strava has no first-class concept of sets/reps/weight, so we keep
    strength data in its own table. An optional FK to `activities`
    lets the user link a session to an already-synced WeightTraining
    activity (Strava still gives us duration, HR, calories for those).

    A "session" is an implicit grouping of rows sharing the same `date`.
    We don't pre-compute sessions — the router groups on read.
    """

    __tablename__ = "strength_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    activity_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("activities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    exercise_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    set_number: Mapped[int] = mapped_column(Integer, nullable=False)
    reps: Mapped[int] = mapped_column(Integer, nullable=False)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    rpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
