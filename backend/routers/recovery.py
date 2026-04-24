from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import Recovery
from backend.services.metrics import get_recovery_trends
from backend.services.time_utils import local_today

router = APIRouter()


@router.get("")
async def list_recovery(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """List recovery records."""
    from datetime import timedelta

    cutoff = local_today() - timedelta(days=days)
    result = await db.execute(
        select(Recovery)
        .where(Recovery.date >= cutoff)
        .order_by(Recovery.date.desc())
    )
    records = result.scalars().all()
    return [_recovery_dict(r) for r in records]


@router.get("/trends")
async def recovery_trends(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """Get recovery trend data."""
    return await get_recovery_trends(db, days=days)


@router.get("/today")
async def today_recovery(db: AsyncSession = Depends(get_db)):
    """Get today's recovery data."""
    result = await db.execute(
        select(Recovery).where(Recovery.date == local_today())
    )
    record = result.scalar_one_or_none()
    if not record:
        return None
    return _recovery_dict(record)


def _recovery_dict(r: Recovery) -> dict:
    return {
        "id": r.id,
        "source": r.source,
        "date": r.date.isoformat(),
        "recovery_score": r.recovery_score,
        "resting_hr": r.resting_hr,
        "hrv": r.hrv,
        "spo2": r.spo2,
        "skin_temp": r.skin_temp,
        "strain_score": r.strain_score,
        "calories": r.calories,
    }
