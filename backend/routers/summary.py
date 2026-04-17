from __future__ import annotations

from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.services.weekly_summary import (
    week_summary,
    weekly_summaries,
)

router = APIRouter()


@router.get("/weekly")
async def get_weekly_summaries(
    weeks: int = Query(4, ge=1, le=52),
    end_date: date_type | None = Query(
        None,
        description="Optional ISO date (YYYY-MM-DD). "
        "Summaries go back `weeks` weeks from the week containing this date. "
        "Defaults to today.",
    ),
    db: AsyncSession = Depends(get_db),
):
    """Newest-first list of weekly training summaries."""
    return await weekly_summaries(db, weeks=weeks, end_date=end_date)


@router.get("/week")
async def get_week(
    date: date_type = Query(
        ..., description="Any ISO date inside the target week (YYYY-MM-DD)."
    ),
    db: AsyncSession = Depends(get_db),
):
    """Summary for the ISO week containing `date`."""
    try:
        return await week_summary(db, date)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
