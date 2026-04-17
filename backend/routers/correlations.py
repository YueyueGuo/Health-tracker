from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.services.correlations import sleep_vs_activity

router = APIRouter()


@router.get("/sleep-vs-activity")
async def sleep_vs_activity_endpoint(
    days: int = Query(60, ge=1, le=365),
    sport_type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Pearson correlations: prior-night sleep metrics × same-day activity metrics.

    Returns paired records (one per activity that has a matched Eight Sleep
    session) and a `correlations` matrix keyed by sleep metric → activity
    metric. Individual cells are `null` when fewer than 8 non-null pairs are
    available.
    """
    return await sleep_vs_activity(db, days=days, sport_type=sport_type)
