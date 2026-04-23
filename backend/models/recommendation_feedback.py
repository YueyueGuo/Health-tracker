from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class RecommendationFeedback(Base):
    """User's thumbs-up/down on a given day's daily recommendation.

    ``cache_key`` is stored as an audit column only (NOT a FK) because
    the insights cache has a 24h TTL — the underlying cache row may be
    gone long before the feedback row is purged. One vote per date
    (unique) so rating the same day twice updates in place.
    """

    __tablename__ = "recommendation_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recommendation_date: Mapped[date] = mapped_column(
        Date, nullable=False, unique=True, index=True
    )
    cache_key: Mapped[str | None] = mapped_column(String(32))
    vote: Mapped[str] = mapped_column(String(8), nullable=False)  # "up" | "down"
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
