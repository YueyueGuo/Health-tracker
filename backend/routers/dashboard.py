from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.services.metrics import get_training_load, get_weekly_stats, get_sleep_trends, get_recovery_trends

router = APIRouter()


@router.get("/overview")
async def dashboard_overview(db: AsyncSession = Depends(get_db)):
    """Get dashboard overview data: recent stats, sleep, recovery, training load."""
    weekly = await get_weekly_stats(db, weeks=4)
    sleep = await get_sleep_trends(db, days=7)
    recovery = await get_recovery_trends(db, days=7)
    training = await get_training_load(db, days=42)

    return {
        "weekly_stats": weekly,
        "recent_sleep": sleep,
        "recent_recovery": recovery,
        "training_load": training,
    }
