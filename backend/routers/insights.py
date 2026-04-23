from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import RecommendationFeedback
from backend.services import insights, training_metrics

router = APIRouter()

logger = logging.getLogger(__name__)


class FeedbackIn(BaseModel):
    recommendation_date: date
    cache_key: str | None = Field(default=None, max_length=32)
    vote: str = Field(pattern="^(up|down)$")
    reason: str | None = Field(default=None, max_length=2000)


class FeedbackOut(BaseModel):
    id: int
    recommendation_date: date
    vote: str
    reason: str | None
    cache_key: str | None


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


@router.post("/feedback", response_model=FeedbackOut)
async def post_feedback(
    payload: FeedbackIn, db: AsyncSession = Depends(get_db)
):
    """Upsert the user's thumbs-up/down on a given day's recommendation.

    Unique on ``recommendation_date`` — re-rating the same day updates
    the existing row in place rather than stacking votes.
    """
    existing = (await db.execute(
        select(RecommendationFeedback).where(
            RecommendationFeedback.recommendation_date == payload.recommendation_date
        )
    )).scalar_one_or_none()

    if existing:
        existing.vote = payload.vote
        existing.reason = payload.reason
        existing.cache_key = payload.cache_key
        row = existing
    else:
        row = RecommendationFeedback(
            recommendation_date=payload.recommendation_date,
            cache_key=payload.cache_key,
            vote=payload.vote,
            reason=payload.reason,
        )
        db.add(row)

    await db.commit()
    await db.refresh(row)
    return FeedbackOut(
        id=row.id,
        recommendation_date=row.recommendation_date,
        vote=row.vote,
        reason=row.reason,
        cache_key=row.cache_key,
    )


@router.get("/feedback/stats")
async def feedback_stats(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    cutoff = date.today() - timedelta(days=days)
    rows = (await db.execute(
        select(RecommendationFeedback)
        .where(RecommendationFeedback.recommendation_date >= cutoff)
        .order_by(RecommendationFeedback.recommendation_date.desc())
    )).scalars().all()
    up = sum(1 for r in rows if r.vote == "up")
    down = sum(1 for r in rows if r.vote == "down")
    return {
        "up": up,
        "down": down,
        "total": len(rows),
        "window_days": days,
        "recent": [
            {
                "recommendation_date": r.recommendation_date.isoformat(),
                "vote": r.vote,
                "reason": r.reason,
            }
            for r in rows[:10]
        ],
    }


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
