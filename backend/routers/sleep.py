from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import SleepSession
from backend.services.metrics import get_sleep_trends

router = APIRouter()


@router.get("")
async def list_sleep_sessions(
    days: int = Query(30, ge=1, le=365),
    source: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List sleep sessions."""
    from datetime import date, timedelta

    query = select(SleepSession).order_by(SleepSession.date.desc())

    cutoff = date.today() - timedelta(days=days)
    query = query.where(SleepSession.date >= cutoff)

    if source:
        query = query.where(SleepSession.source == source)

    result = await db.execute(query)
    sessions = result.scalars().all()

    return [_sleep_dict(s) for s in sessions]


@router.get("/trends")
async def sleep_trends(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """Get sleep trend data."""
    return await get_sleep_trends(db, days=days)


@router.get("/latest")
async def latest_sleep(db: AsyncSession = Depends(get_db)):
    """Get the most recent sleep session."""
    result = await db.execute(
        select(SleepSession).order_by(SleepSession.date.desc()).limit(1)
    )
    session = result.scalar_one_or_none()
    if not session:
        return None
    return _sleep_dict(session)


def _sleep_dict(s: SleepSession) -> dict:
    return {
        "id": s.id,
        "source": s.source,
        "date": s.date.isoformat(),
        "bed_time": s.bed_time.isoformat() if s.bed_time else None,
        "wake_time": s.wake_time.isoformat() if s.wake_time else None,
        "total_duration": s.total_duration,
        "deep_sleep": s.deep_sleep,
        "rem_sleep": s.rem_sleep,
        "light_sleep": s.light_sleep,
        "awake_time": s.awake_time,
        "sleep_score": s.sleep_score,
        "avg_hr": s.avg_hr,
        "hrv": s.hrv,
        "respiratory_rate": s.respiratory_rate,
        "bed_temp": s.bed_temp,
    }
