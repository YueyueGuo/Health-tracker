from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base

if TYPE_CHECKING:
    from backend.models.weather import WeatherSnapshot


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strava_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    sport_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    start_date: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    start_date_local: Mapped[datetime | None] = mapped_column(DateTime)
    timezone: Mapped[str | None] = mapped_column(String)
    elapsed_time: Mapped[int | None] = mapped_column(Integer)
    moving_time: Mapped[int | None] = mapped_column(Integer)
    distance: Mapped[float | None] = mapped_column(Float)
    total_elevation: Mapped[float | None] = mapped_column(Float)
    average_hr: Mapped[float | None] = mapped_column(Float)
    max_hr: Mapped[float | None] = mapped_column(Float)
    average_speed: Mapped[float | None] = mapped_column(Float)
    max_speed: Mapped[float | None] = mapped_column(Float)
    average_power: Mapped[float | None] = mapped_column(Float)
    max_power: Mapped[int | None] = mapped_column(Integer)
    weighted_avg_power: Mapped[float | None] = mapped_column(Float)
    average_cadence: Mapped[float | None] = mapped_column(Float)
    calories: Mapped[float | None] = mapped_column(Float)
    kilojoules: Mapped[float | None] = mapped_column(Float)
    suffer_score: Mapped[int | None] = mapped_column(Integer)
    device_watts: Mapped[bool | None] = mapped_column(Boolean)
    workout_type: Mapped[int | None] = mapped_column(Integer)
    start_lat: Mapped[float | None] = mapped_column(Float)
    start_lng: Mapped[float | None] = mapped_column(Float)
    summary_polyline: Mapped[str | None] = mapped_column(Text)
    available_zones: Mapped[list | None] = mapped_column(JSON)
    zones_data: Mapped[list | None] = mapped_column(JSON)
    enrichment_status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", server_default="pending", index=True
    )
    enrichment_error: Mapped[str | None] = mapped_column(Text)
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Workout classification (populated after enrichment). See
    # backend/services/classifier.py. Nullable while we re-classify.
    classification_type: Mapped[str | None] = mapped_column(String, index=True)
    classification_flags: Mapped[list | None] = mapped_column(JSON)
    classified_at: Mapped[datetime | None] = mapped_column(DateTime)
    weather_enriched: Mapped[bool] = mapped_column(Boolean, default=False)
    # Base-elevation enrichment. ``elev_high_m`` / ``elev_low_m`` come
    # straight from the Strava detail response for GPS-backed activities.
    # ``base_elevation_m`` is the canonical "where did this happen"
    # altitude used by downstream analytics (classifier tier flag,
    # correlations). Derivation precedence:
    #   1. ``elev_low_m`` from Strava (watch-recorded)
    #   2. ``location_id``’s ``user_locations.elevation_m``
    #   3. Open-Meteo lookup by ``start_lat``/``start_lng``
    #   4. Default ``UserLocation`` when no coords at all
    elev_high_m: Mapped[float | None] = mapped_column(Float)
    elev_low_m: Mapped[float | None] = mapped_column(Float)
    base_elevation_m: Mapped[float | None] = mapped_column(Float)
    elevation_enriched: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    location_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("user_locations.id", ondelete="SET NULL"), index=True
    )
    # User-supplied workout context. ``rpe`` is the Borg CR-10 rating of
    # perceived exertion (1 = very light, 10 = max). Validated at the
    # router layer. Fed into the daily-recommendation LLM snapshot.
    rpe: Mapped[int | None] = mapped_column(Integer)
    user_notes: Mapped[str | None] = mapped_column(Text)
    rated_at: Mapped[datetime | None] = mapped_column(DateTime)
    raw_data: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    streams: Mapped[list[ActivityStream]] = relationship(
        back_populates="activity", cascade="all, delete-orphan"
    )
    laps: Mapped[list[ActivityLap]] = relationship(
        back_populates="activity", cascade="all, delete-orphan", order_by="ActivityLap.lap_index"
    )
    weather: Mapped[WeatherSnapshot] = relationship(
        "WeatherSnapshot", back_populates="activity", uselist=False, cascade="all, delete-orphan"
    )


class ActivityStream(Base):
    __tablename__ = "activity_streams"
    __table_args__ = (UniqueConstraint("activity_id", "stream_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    activity_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("activities.id", ondelete="CASCADE"), nullable=False
    )
    stream_type: Mapped[str] = mapped_column(String, nullable=False)
    data: Mapped[list] = mapped_column(JSON, nullable=False)

    activity: Mapped[Activity] = relationship(back_populates="streams")


class ActivityLap(Base):
    __tablename__ = "activity_laps"
    __table_args__ = (UniqueConstraint("activity_id", "lap_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    activity_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("activities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lap_index: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str | None] = mapped_column(String)
    elapsed_time: Mapped[int | None] = mapped_column(Integer)
    moving_time: Mapped[int | None] = mapped_column(Integer)
    distance: Mapped[float | None] = mapped_column(Float)
    start_date: Mapped[datetime | None] = mapped_column(DateTime)
    average_speed: Mapped[float | None] = mapped_column(Float)
    max_speed: Mapped[float | None] = mapped_column(Float)
    average_heartrate: Mapped[float | None] = mapped_column(Float)
    max_heartrate: Mapped[float | None] = mapped_column(Float)
    average_cadence: Mapped[float | None] = mapped_column(Float)
    average_watts: Mapped[float | None] = mapped_column(Float)
    total_elevation_gain: Mapped[float | None] = mapped_column(Float)
    pace_zone: Mapped[int | None] = mapped_column(Integer)
    hr_zone: Mapped[int | None] = mapped_column(Integer)
    split: Mapped[int | None] = mapped_column(Integer)
    start_index: Mapped[int | None] = mapped_column(Integer)
    end_index: Mapped[int | None] = mapped_column(Integer)

    activity: Mapped[Activity] = relationship(back_populates="laps")
