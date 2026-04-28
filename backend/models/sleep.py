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
    sleep_fitness_score: Mapped[float | None] = mapped_column(Float)  # Eight Sleep
    avg_hr: Mapped[float | None] = mapped_column(Float)
    hrv: Mapped[float | None] = mapped_column(Float)
    respiratory_rate: Mapped[float | None] = mapped_column(Float)
    bed_temp: Mapped[float | None] = mapped_column(Float)  # Eight Sleep specific
    tnt_count: Mapped[int | None] = mapped_column(Integer)  # toss & turn count
    latency: Mapped[int | None] = mapped_column(Integer)  # time to sleep (sec)
    # Mid-night wake-up metrics. NULL on archive nights where Eight Sleep
    # didn't return per-stage interval data.
    wake_count: Mapped[int | None] = mapped_column(Integer)  # awakenings after sleep onset
    waso_duration: Mapped[int | None] = mapped_column(Integer)  # wake-after-sleep-onset, minutes
    out_of_bed_count: Mapped[int | None] = mapped_column(Integer)
    out_of_bed_duration: Mapped[int | None] = mapped_column(Integer)  # minutes
    wake_events: Mapped[list | None] = mapped_column(JSON)  # [{type, duration_sec, start}]
    # Whoop-specific sleep extras. Whoop's score object exposes these for every
    # sleep cycle but they have no Eight Sleep equivalent, so they stay null on
    # Eight Sleep rows.
    sleep_efficiency: Mapped[float | None] = mapped_column(Float)  # %, time asleep / in bed
    sleep_consistency: Mapped[float | None] = mapped_column(Float)  # %, schedule regularity
    sleep_need_baseline_min: Mapped[int | None] = mapped_column(Integer)  # baseline need
    sleep_debt_min: Mapped[int | None] = mapped_column(Integer)  # accrued sleep debt
    raw_data: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
