"""Repository helpers for the ``oauth_tokens`` table.

Tokens persist in the database (durable across container restarts on
Railway) instead of `.env` (ephemeral on Railway). The clients use
``get_tokens`` on first request and ``save_tokens`` after every refresh.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.oauth_token import OAuthToken


async def get_tokens(db: AsyncSession, provider: str) -> OAuthToken | None:
    """Return the row for ``provider`` or None if no row exists yet."""
    result = await db.execute(
        select(OAuthToken).where(OAuthToken.provider == provider)
    )
    return result.scalar_one_or_none()


async def save_tokens(
    db: AsyncSession,
    provider: str,
    *,
    access_token: str | None,
    refresh_token: str | None,
    expires_at: datetime | None = None,
) -> None:
    """Upsert tokens for ``provider``. Commits the session."""
    existing = await get_tokens(db, provider)
    if existing is None:
        db.add(
            OAuthToken(
                provider=provider,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
            )
        )
    else:
        existing.access_token = access_token
        existing.refresh_token = refresh_token
        existing.expires_at = expires_at
    await db.commit()
