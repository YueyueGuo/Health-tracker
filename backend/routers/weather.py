"""Weather-specific endpoints.

Primarily exposes ``POST /api/weather/backfill`` so the frontend or ops
scripts can incrementally enrich activities with historical weather
without invoking the full ``sync_all`` pipeline.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db

router = APIRouter()


class WeatherBackfillRequest(BaseModel):
    batch: int = Field(
        50, ge=1, le=500,
        description="Max activities to enrich this pass.",
    )
    dry_run: bool = Field(
        False,
        description="Count candidates without hitting the weather provider.",
    )


@router.post("/backfill")
async def backfill_weather(
    req: WeatherBackfillRequest | None = None,
    batch: int = Query(50, ge=1, le=500),
    dry_run: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """Enrich a batch of activities with historical weather.

    Accepts either a JSON body ``{"batch": N, "dry_run": bool}`` or
    equivalent query params. Returns the progress counters from
    ``sync_weather``:

    ``{"enriched": int, "skipped": int, "failed": int, "remaining": int}``.
    """
    from backend.clients import get_weather_client
    from backend.clients.eight_sleep import EightSleepClient
    from backend.clients.strava import StravaClient
    from backend.clients.whoop import WhoopClient
    from backend.services.sync import SyncEngine

    # Body wins over query params when present.
    eff_batch = req.batch if req else batch
    eff_dry = req.dry_run if req else dry_run

    strava = StravaClient()
    eight_sleep = EightSleepClient()
    whoop = WhoopClient()
    weather = get_weather_client()

    try:
        engine = SyncEngine(db, strava, eight_sleep, whoop, weather)
        result = await engine.sync_weather(limit=eff_batch, dry_run=eff_dry)
        return {
            **result,
            "batch": eff_batch,
            "dry_run": eff_dry,
            "configured": weather.is_configured,
        }
    finally:
        await strava.close()
        await eight_sleep.close()
        await whoop.close()
        await weather.close()
