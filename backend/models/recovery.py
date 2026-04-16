from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, func
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class Recovery(Base):
    __tablename__ = "recovery_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String, nullable=False, default="whoop")
    date: Mapped[date] = mapped_column(Date, unique=True, nullable=False, index=True)
    recovery_score: Mapped[float | None] = mapped_column(Float)
    resting_hr: Mapped[float | None] = mapped_column(Float)
    hrv: Mapped[float | None] = mapped_column(Float)  # milliseconds
    spo2: Mapped[float | None] = mapped_column(Float)
    skin_temp: Mapped[float | None] = mapped_column(Float)
    strain_score: Mapped[float | None] = mapped_column(Float)
    calories: Mapped[float | None] = mapped_column(Float)
    raw_data: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
