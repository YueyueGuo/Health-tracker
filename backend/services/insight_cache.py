"""Analysis-cache helpers for dashboard insights."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import AnalysisCache
from backend.services.time_utils import utc_now_naive


def _hash_inputs(payload: dict | str) -> str:
    if isinstance(payload, dict):
        payload = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _cache_get(db: AsyncSession, key: str) -> dict | None:
    row = await db.execute(select(AnalysisCache).where(AnalysisCache.query_hash == key))
    hit = row.scalar_one_or_none()
    if not hit:
        return None
    if hit.expires_at and hit.expires_at < utc_now_naive():
        return None
    try:
        return json.loads(hit.response_text)
    except json.JSONDecodeError:
        return None


async def _cache_put(
    db: AsyncSession,
    key: str,
    query_text: str,
    payload: dict,
    model: str,
    ttl: timedelta | None = None,
) -> None:
    existing = await db.execute(select(AnalysisCache).where(AnalysisCache.query_hash == key))
    e = existing.scalar_one_or_none()
    now = utc_now_naive()
    expires = (now + ttl) if ttl else None
    if e:
        e.response_text = json.dumps(payload)
        e.model = model
        e.query_text = query_text
        e.expires_at = expires
        e.created_at = now
    else:
        db.add(
            AnalysisCache(
                query_hash=key,
                query_text=query_text,
                response_text=json.dumps(payload),
                model=model,
                expires_at=expires,
            )
        )
    await db.commit()
