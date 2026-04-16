from __future__ import annotations

from datetime import datetime

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
    suffer_score: Mapped[int | None] = mapped_column(Integer)
    start_lat: Mapped[float | None] = mapped_column(Float)
    start_lng: Mapped[float | None] = mapped_column(Float)
    summary_polyline: Mapped[str | None] = mapped_column(Text)
    has_streams: Mapped[bool] = mapped_column(Boolean, default=False)
    weather_enriched: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_data: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    streams: Mapped[list[ActivityStream]] = relationship(
        back_populates="activity", cascade="all, delete-orphan"
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
