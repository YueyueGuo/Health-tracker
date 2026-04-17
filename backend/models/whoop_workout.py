"""WhoopWorkout — a Whoop-recorded workout session.

Distinct from the Strava-sourced ``Activity`` table because:
* Whoop IDs and Strava IDs don't overlap (different primary keys).
* Whoop records heart-rate-zone durations and strain the same way for
  every sport; Strava records sport-specific metrics.
* We want to join Whoop workouts to Strava activities by start-time
  proximity later, not force them into one table.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Integer, String, func
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class WhoopWorkout(Base):
    __tablename__ = "whoop_workouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Whoop's own workout id (v2 returns numeric ids); unique per Whoop user.
    whoop_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    start: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    end: Mapped[datetime | None] = mapped_column(DateTime)
    timezone_offset: Mapped[str | None] = mapped_column(String(8))
    sport_id: Mapped[int | None] = mapped_column(Integer)
    sport_name: Mapped[str | None] = mapped_column(String(64), index=True)
    score_state: Mapped[str | None] = mapped_column(String(32))
    strain: Mapped[float | None] = mapped_column(Float)
    average_heart_rate: Mapped[float | None] = mapped_column(Float)
    max_heart_rate: Mapped[float | None] = mapped_column(Float)
    kilojoule: Mapped[float | None] = mapped_column(Float)
    percent_recorded: Mapped[float | None] = mapped_column(Float)
    distance_meter: Mapped[float | None] = mapped_column(Float)
    altitude_gain_meter: Mapped[float | None] = mapped_column(Float)
    altitude_change_meter: Mapped[float | None] = mapped_column(Float)
    # Zone durations in milliseconds (HR zones 0-5, Whoop-defined).
    zone_zero_ms: Mapped[int | None] = mapped_column(Integer)
    zone_one_ms: Mapped[int | None] = mapped_column(Integer)
    zone_two_ms: Mapped[int | None] = mapped_column(Integer)
    zone_three_ms: Mapped[int | None] = mapped_column(Integer)
    zone_four_ms: Mapped[int | None] = mapped_column(Integer)
    zone_five_ms: Mapped[int | None] = mapped_column(Integer)
    # FK to Activity if we matched this Whoop workout to a Strava activity
    # (populated by a future join-by-start-time pass). Nullable.
    activity_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )
    raw_data: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
