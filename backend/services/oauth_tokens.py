"""Repository helpers for the ``oauth_tokens`` table.

Tokens persist in the database (durable across container restarts on
Railway) instead of `.env` (ephemeral on Railway). The clients use
``get_tokens`` on first request and ``save_tokens`` after every refresh.

``save_tokens`` is an atomic dialect-aware upsert so the concurrent
bootstrap window on a fresh deploy (two clients both INSERTing the same
row before either commits) doesn't surface a UniqueViolation.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
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
    """Atomically upsert tokens for ``provider``. Commits the session.

    Uses dialect-specific ``ON CONFLICT DO UPDATE`` so two concurrent
    callers can't collide on the primary key (the bootstrap race) or
    silently overwrite each other's writes via read-then-update TOCTOU.
    """
    values = {
        "provider": provider,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
    }
    update_cols = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
    }
    dialect = db.bind.dialect.name if db.bind is not None else (
        db.get_bind().dialect.name
    )
    if dialect == "postgresql":
        stmt = pg_insert(OAuthToken).values(**values).on_conflict_do_update(
            index_elements=["provider"], set_=update_cols
        )
    else:
        # SQLite (3.24+) supports the same ON CONFLICT syntax.
        stmt = sqlite_insert(OAuthToken).values(**values).on_conflict_do_update(
            index_elements=["provider"], set_=update_cols
        )
    await db.execute(stmt)
    await db.commit()
