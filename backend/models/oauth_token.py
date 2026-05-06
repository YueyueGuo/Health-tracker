"""Persistent OAuth token storage.

Source of truth for Whoop / Strava (and future) refresh + access tokens.
Lives in the database (SQLite locally, Postgres on Railway) so that token
rotation survives container restarts — `.env` is not durable on Railway.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class OAuthToken(Base):
    __tablename__ = "oauth_tokens"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
