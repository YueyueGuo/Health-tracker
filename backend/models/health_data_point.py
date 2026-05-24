"""Polymorphic base for HealthKit-style health samples.

A `HealthDataPoint` is a generic row that anchors any health-data
record by ``(source, data_type, external_id)``. Typed subtypes (the
first being :class:`Workout`) hang off the same primary key via
joined-table inheritance.

The natural key ``(source, data_type, external_id)`` makes upsert
trivial and lets dedup queries scan a single composite index on
``(data_type, start_time)`` regardless of source. See
`docs/decisions/0002-apple-health-polymorphic-workouts.md` for the
rationale behind this shape.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base

if TYPE_CHECKING:
    from backend.models.workout import Workout


class HealthDataPoint(Base):
    __tablename__ = "health_data_points"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "data_type",
            "external_id",
            name="uq_health_data_points_source_type_ext",
        ),
        Index(
            "ix_health_data_points_data_type_start_time",
            "data_type",
            "start_time",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # `source` is enum-ish — enforced in app code, not via CHECK.
    # Known values: "apple_health", "strava", "whoop", "eight_sleep".
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # `data_type` taxonomy is open: "workout", "steps", "sleep", "heart_rate", ...
    data_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # Natural key per (source, data_type) — e.g. HKWorkout UUID for Apple,
    # Strava activity id as string. Stored as string so heterogeneous
    # external id shapes can live side-by-side.
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("health_data_points.id", ondelete="SET NULL"),
        index=True,
    )
    # Original payload (Apple HAE blob, Strava JSON, …). Heavy series
    # data like `heartRateData[]` lives here in v1 rather than getting
    # its own typed table.
    raw_payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    workout: Mapped[Workout | None] = relationship(
        "Workout",
        uselist=False,
        back_populates="data_point",
        cascade="all, delete-orphan",
    )
