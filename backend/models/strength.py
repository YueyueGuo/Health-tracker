from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base

if TYPE_CHECKING:
    from backend.models.activity import Activity
    from backend.models.workout import Workout


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
    performed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Session/superset metadata added by migration ``f2a8d3c1e9b4``
    # (see ``docs/plans/strength-workout-detail.md`` and
    # ``alembic/versions/f2a8d3c1e9b4_strength_supersets_and_duration.py``).
    # All nullable so existing rows render as standalone exercises with
    # alphabetical fallback ordering and a derived duration.
    superset_group_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    order_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class StrengthSessionLink(Base):
    """Links a strength session (keyed by ``session_date``) to one device workout.

    Backs the "linked workout HR sets" feature
    (``docs/specs/linked-workout-hr-sets.md`` /
    ``docs/plans/linked-workout-hr-sets.md``). A row pairs the manual
    strength session for a given date with exactly one device-recorded
    workout — either a Strava ``activities`` row OR an Apple Health
    ``workouts`` row (joined-table inheritance over
    ``health_data_points``). The link is strictly 1:1 in both directions:

    * one ``session_date`` → at most one link row (UNIQUE on
      ``session_date``).
    * one device workout → at most one link row (partial UNIQUE indexes
      on ``(source, activity_id)`` and ``(source, workout_id)``).

    Mirrors the migration ``e1a3b7d2c9f4_add_strength_session_links.py``
    exactly — see that file for column-type rationale.
    """

    __tablename__ = "strength_session_links"

    # Partial UNIQUE indexes: enforce 1:1 device-workout → link by scoping
    # the constraint to the non-null FK column. Postgres + SQLite ≥ 3.8
    # both support partial indexes via the dialect-specific kwargs. Match
    # the migration shape exactly so the in-memory SQLite used by tests
    # gets the same constraint as Railway Postgres.
    __table_args__ = (
        Index(
            "ix_strength_session_links_session_date",
            "session_date",
            unique=True,
        ),
        Index(
            "ix_strength_session_links_source",
            "source",
        ),
        Index(
            "ix_strength_session_links_source_activity",
            "source",
            "activity_id",
            unique=True,
            sqlite_where=text("activity_id IS NOT NULL"),
            postgresql_where=text("activity_id IS NOT NULL"),
        ),
        Index(
            "ix_strength_session_links_source_workout",
            "source",
            "workout_id",
            unique=True,
            sqlite_where=text("workout_id IS NOT NULL"),
            postgresql_where=text("workout_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Enum-ish, app-enforced (no DB CHECK per AGENTS.md). Known values:
    # ``"strava"``, ``"apple_health"``.
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    # Integer (not BigInteger) — matches ``activities.id`` /
    # ``workouts.id`` column types. See migration docstring.
    activity_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("activities.id", ondelete="SET NULL"),
        nullable=True,
    )
    workout_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("workouts.id", ondelete="SET NULL"),
        nullable=True,
    )
    # ``pending`` | ``ok`` | ``too_few`` | ``too_many`` | ``flat`` |
    # ``no_stream`` | ``no_curve`` | ``error``.
    segmentation_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'pending'"),
        default="pending",
    )
    segmentation_detected_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    segmentation_target_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # ``[{start_sec, end_sec, avg_hr, max_hr, peak_sec, prominence}, ...]``
    segmentation_payload: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # One-way relationships. No back-refs — keeps Activity / Workout
    # ignorant of the link table.
    activity: Mapped[Activity | None] = relationship("Activity")
    workout: Mapped[Workout | None] = relationship("Workout")
