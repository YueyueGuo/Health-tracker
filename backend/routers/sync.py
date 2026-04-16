from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import SyncLog

router = APIRouter()


class SyncRequest(BaseModel):
    source: str = "all"  # "all", "strava", "eight_sleep", "whoop", "weather"


@router.post("/trigger")
async def trigger_sync(req: SyncRequest, db: AsyncSession = Depends(get_db)):
    """Manually trigger a data sync."""
    from backend.clients.eight_sleep import EightSleepClient
    from backend.clients.strava import StravaClient
    from backend.clients.weather import WeatherClient
    from backend.clients.whoop import WhoopClient
    from backend.services.sync import SyncEngine

    strava = StravaClient()
    eight_sleep = EightSleepClient()
    whoop = WhoopClient()
    weather = WeatherClient()

    engine = SyncEngine(db, strava, eight_sleep, whoop, weather)

    try:
        if req.source == "all":
            results = await engine.sync_all()
        elif req.source in ("strava", "eight_sleep", "whoop", "weather"):
            sync_method = getattr(engine, f"sync_{req.source}")
            count = await sync_method()
            results = {req.source: count}
        else:
            return {"error": f"Unknown source: {req.source}"}

        return {"status": "success", "synced": results}
    finally:
        await strava.close()
        await eight_sleep.close()
        await whoop.close()
        await weather.close()


@router.get("/status")
async def sync_status(db: AsyncSession = Depends(get_db)):
    """Get the last sync status for each source."""
    sources = ["strava", "eight_sleep", "whoop", "weather"]
    statuses = {}

    for source in sources:
        result = await db.execute(
            select(SyncLog)
            .where(SyncLog.source == source)
            .order_by(SyncLog.started_at.desc())
            .limit(1)
        )
        log = result.scalar_one_or_none()
        if log:
            statuses[source] = {
                "status": log.status,
                "last_sync": log.started_at.isoformat() if log.started_at else None,
                "records_synced": log.records_synced,
                "error": log.error_message,
            }
        else:
            statuses[source] = {"status": "never", "last_sync": None}

    return statuses
