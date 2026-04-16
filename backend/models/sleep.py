from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class SleepSession(Base):
    __tablename__ = "sleep_sessions"
    __table_args__ = (UniqueConstraint("source", "date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String, nullable=False)  # "eight_sleep" or "whoop"
    external_id: Mapped[str | None] = mapped_column(String)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    bed_time: Mapped[datetime | None] = mapped_column(DateTime)
    wake_time: Mapped[datetime | None] = mapped_column(DateTime)
    total_duration: Mapped[int | None] = mapped_column(Integer)  # minutes
    deep_sleep: Mapped[int | None] = mapped_column(Integer)  # minutes
    rem_sleep: Mapped[int | None] = mapped_column(Integer)  # minutes
    light_sleep: Mapped[int | None] = mapped_column(Integer)  # minutes
    awake_time: Mapped[int | None] = mapped_column(Integer)  # minutes
    sleep_score: Mapped[float | None] = mapped_column(Float)
    avg_hr: Mapped[float | None] = mapped_column(Float)
    hrv: Mapped[float | None] = mapped_column(Float)
    respiratory_rate: Mapped[float | None] = mapped_column(Float)
    bed_temp: Mapped[float | None] = mapped_column(Float)  # Eight Sleep specific
    raw_data: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
