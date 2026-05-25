"""Typed `workouts` subtype and `workout_laps` child of
:class:`HealthDataPoint`.

`Workout.id` is both PK and FK to ``health_data_points.id`` — classic
joined-table inheritance — so a workout row always has exactly one
backing polymorphic row and is removed when that parent is deleted.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base

if TYPE_CHECKING:
    from backend.models.activity import Activity
    from backend.models.health_data_point import HealthDataPoint
    from backend.models.shoe import Shoe


class Workout(Base):
    __tablename__ = "workouts"

    # Joined-table inheritance: id IS the FK back to health_data_points.
    id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("health_data_points.id", ondelete="CASCADE"),
        primary_key=True,
        autoincrement=False,
    )
    activity_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    duration_s: Mapped[int | None] = mapped_column(Integer)
    active_energy_kcal: Mapped[float | None] = mapped_column(Float)
    distance_m: Mapped[float | None] = mapped_column(Float)
    avg_speed_mps: Mapped[float | None] = mapped_column(Float)
    avg_pace_s_per_km: Mapped[float | None] = mapped_column(Float)
    avg_hr: Mapped[float | None] = mapped_column(Float)
    max_hr: Mapped[float | None] = mapped_column(Float)
    total_elevation_m: Mapped[float | None] = mapped_column(Float)
    # Optional back-link to the (deduped) Strava activity when both
    # sources exist for the same workout.
    activity_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("activities.id", ondelete="SET NULL"),
        index=True,
    )
    # Optional running-shoe tag (mirrors ``activities.shoe_id``).
    shoe_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("shoes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    data_point: Mapped[HealthDataPoint] = relationship(
        "HealthDataPoint", back_populates="workout"
    )
    activity: Mapped[Activity | None] = relationship("Activity")
    shoe: Mapped[Shoe | None] = relationship("Shoe", back_populates="apple_workouts")
    laps: Mapped[list[WorkoutLap]] = relationship(
        "WorkoutLap",
        back_populates="workout",
        cascade="all, delete-orphan",
        order_by="WorkoutLap.lap_index",
    )


class WorkoutLap(Base):
    __tablename__ = "workout_laps"
    __table_args__ = (
        UniqueConstraint(
            "workout_id", "lap_index", name="uq_workout_laps_workout_lap_index"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workout_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("workouts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    lap_index: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str | None] = mapped_column(String)
    elapsed_time_s: Mapped[int | None] = mapped_column(Integer)
    moving_time_s: Mapped[int | None] = mapped_column(Integer)
    distance_m: Mapped[float | None] = mapped_column(Float)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    avg_speed_mps: Mapped[float | None] = mapped_column(Float)
    max_speed_mps: Mapped[float | None] = mapped_column(Float)
    avg_hr: Mapped[float | None] = mapped_column(Float)
    max_hr: Mapped[float | None] = mapped_column(Float)
    avg_cadence: Mapped[float | None] = mapped_column(Float)
    total_elevation_m: Mapped[float | None] = mapped_column(Float)
    split: Mapped[int | None] = mapped_column(Integer)

    workout: Mapped[Workout] = relationship("Workout", back_populates="laps")
