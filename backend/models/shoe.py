"""Running-shoe lifespan tracking.

A ``Shoe`` is an account-level label the user assigns to runs (Strava
``Activity`` or Apple Health ``Workout``) so the dashboard can show
cumulative mileage and a "you've put X / Y km on these" progress bar.

Cumulative distance is computed on demand from the tagged activities
and workouts (``backend/services/shoe_mileage.py``); there is no stored
counter and no trigger. See ``docs/plans/running-shoe-mileage.md``.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base

if TYPE_CHECKING:
    from backend.models.activity import Activity
    from backend.models.workout import Workout


class Shoe(Base):
    __tablename__ = "shoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(120))
    # ``shoe_type`` enum-ish, enforced at the router layer (Pydantic
    # regex). No DB CHECK so widening the enum stays a metadata-only
    # change. Matches ``goals.status`` / Apple ``source`` patterns.
    shoe_type: Mapped[str] = mapped_column(
        String(24), nullable=False, default="everyday", server_default="everyday"
    )
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="active", server_default="active", index=True
    )
    total_usable_distance_m: Mapped[float | None] = mapped_column(Float)
    purchased_on: Mapped[date | None] = mapped_column(Date)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    activities: Mapped[list[Activity]] = relationship(
        "Activity", back_populates="shoe"
    )
    apple_workouts: Mapped[list[Workout]] = relationship(
        "Workout", back_populates="shoe"
    )
