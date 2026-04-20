from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.services import insights, training_metrics

router = APIRouter()

logger = logging.getLogger(__name__)


@router.get("/training-metrics")
async def training_metrics_snapshot(db: AsyncSession = Depends(get_db)):
    """Return the raw training-load / sleep / recovery snapshot that
    feeds the LLM recommendation. Useful for debugging + the training-load
    card on the dashboard."""
    return await training_metrics.get_full_snapshot(db)


@router.get("/daily-recommendation")
async def daily_recommendation(
    refresh: bool = Query(False, description="Force regen (ignore cache)."),
    model: str | None = Query(None, description="Override the LLM model."),
    db: AsyncSession = Depends(get_db),
):
    """LLM-driven daily training recommendation. Cached per-day per-inputs-hash."""
    try:
        result = await insights.get_daily_recommendation(db, model=model, refresh=refresh)
    except Exception:
        # Full details in server logs; user gets a generic message so we
        # don't leak SDK internals / keys / paths in the HTTP response.
        logger.exception("daily_recommendation failed")
        raise HTTPException(status_code=502, detail="LLM unavailable") from None
    return result.to_dict()


@router.get("/latest-workout")
async def latest_workout_insight(
    activity_id: int | None = Query(None, description="Optional activity id; defaults to latest."),
    refresh: bool = Query(False, description="Force regen (ignore cache)."),
    model: str | None = Query(None, description="Override the LLM model."),
    db: AsyncSession = Depends(get_db),
):
    """LLM-driven insight on a workout (latest by default). Cached per activity."""
    try:
        result = await insights.get_latest_workout_insight(
            db, activity_id=activity_id, model=model, refresh=refresh
        )
    except Exception:
        logger.exception("latest_workout_insight failed")
        raise HTTPException(status_code=502, detail="LLM unavailable") from None
    if not result:
        raise HTTPException(status_code=404, detail="No completed activities yet")
    return result.to_dict()
