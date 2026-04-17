from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import Activity, SyncLog

router = APIRouter()


class SyncRequest(BaseModel):
    source: str = "all"  # "all", "strava", "eight_sleep", "whoop", "weather"


@router.post("/trigger")
async def trigger_sync(req: SyncRequest, db: AsyncSession = Depends(get_db)):
    """Manually trigger a data sync."""
    from backend.clients import get_weather_client
    from backend.clients.eight_sleep import EightSleepClient
    from backend.clients.strava import StravaClient
    from backend.clients.whoop import WhoopClient
    from backend.services.sync import SyncEngine

    strava = StravaClient()
    eight_sleep = EightSleepClient()
    whoop = WhoopClient()
    weather = get_weather_client()

    engine = SyncEngine(db, strava, eight_sleep, whoop, weather)

    try:
        if req.source == "all":
            results = await engine.sync_all()
        elif req.source in ("strava", "eight_sleep", "whoop", "weather"):
            try:
                sync_method = getattr(engine, f"sync_{req.source}")
                count = await sync_method()
                results = {req.source: count}
            except Exception as e:
                results = {req.source: f"error: {e}"}
        else:
            return {"error": f"Unknown source: {req.source}"}

        # Check if any source needs configuration
        unconfigured = []
        from backend.config import settings
        if not settings.strava.access_token and not settings.strava.refresh_token:
            unconfigured.append("strava")
        if not settings.eight_sleep.email:
            unconfigured.append("eight_sleep")
        if not settings.whoop.enabled:
            unconfigured.append("whoop")
        # Only flag weather as unconfigured when the chosen provider
        # actually needs credentials (Open-Meteo does not).
        if settings.weather_provider == "openweathermap" and not settings.weather.api_key:
            unconfigured.append("weather")

        return {
            "status": "success",
            "synced": results,
            "unconfigured": unconfigured,
            "hint": "Add credentials to .env for unconfigured sources" if unconfigured else None,
        }
    finally:
        await strava.close()
        await eight_sleep.close()
        await whoop.close()
        await weather.close()


# NOTE: A POST /sync/streams endpoint existed briefly to bulk-fetch missing
# streams. It's been replaced by the on-demand GET /api/activities/{id}/streams
# endpoint (see backend/routers/activities.py), which fetches and caches
# streams per-activity when the UI actually needs them.


@router.get("/status")
async def sync_status(db: AsyncSession = Depends(get_db)):
    """Get the last sync status for each source, plus Strava enrichment state."""
    from backend.clients.strava import StravaClient

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

    # Strava-specific: enrichment breakdown + quota usage
    counts_rows = (await db.execute(
        select(Activity.enrichment_status, func.count())
        .group_by(Activity.enrichment_status)
    )).all()
    strava_enrichment = {row[0]: row[1] for row in counts_rows}
    statuses["strava_enrichment"] = {
        "pending": strava_enrichment.get("pending", 0),
        "complete": strava_enrichment.get("complete", 0),
        "failed": strava_enrichment.get("failed", 0),
        "total": sum(strava_enrichment.values()),
    }
    statuses["strava_quota"] = StravaClient.quota_usage()

    return statuses


@router.get("/debug/strava-raw")
async def debug_strava_raw():
    """Debug: fetch raw Strava data to see what's coming back."""
    from backend.clients.strava import StravaClient

    client = StravaClient()
    try:
        # Test 1: Can we authenticate?
        try:
            athlete = await client.get_athlete()
            auth_status = {"ok": True, "athlete": athlete.get("firstname", "?") + " " + athlete.get("lastname", "?")}
        except Exception as e:
            return {"auth_status": {"ok": False, "error": str(e)}}

        # Test 2: Fetch first page of activities (just 5)
        try:
            activities = await client.get_activities(per_page=5)
            activities_summary = [
                {
                    "id": a.get("id"),
                    "name": a.get("name"),
                    "type": a.get("type"),
                    "sport_type": a.get("sport_type"),
                    "start_date": a.get("start_date"),
                    "distance": a.get("distance"),
                    "moving_time": a.get("moving_time"),
                }
                for a in activities
            ]
        except Exception as e:
            return {"auth_status": auth_status, "activities_error": str(e)}

        return {
            "auth_status": auth_status,
            "activities_count": len(activities),
            "activities": activities_summary,
            "first_raw": activities[0] if activities else None,
        }
    finally:
        await client.close()
