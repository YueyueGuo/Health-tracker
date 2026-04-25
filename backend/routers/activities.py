from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import Activity, ActivityLap, ActivityStream, WeatherSnapshot
from backend.services.hr_zones import (
    compute_hr_drift,
    compute_pace_hr_decoupling,
    compute_power_hr_decoupling,
)
from backend.services.time_utils import utc_now_naive

_RUN_SPORTS = {"Run", "TrailRun", "VirtualRun"}
_RIDE_SPORTS = {"Ride", "VirtualRide", "GravelRide", "MountainBikeRide", "EBikeRide"}

logger = logging.getLogger(__name__)
router = APIRouter()


class ActivityFeedbackPatch(BaseModel):
    """User-supplied RPE + notes for a completed activity.

    Both fields are optional — the UI may submit just RPE, just notes, or
    both. ``rpe`` is Borg CR-10 (1 very light → 10 max), validated here
    rather than at the DB layer because SQLite lacks CHECK-constraint
    portability for Alembic downgrades.
    """
    rpe: int | None = Field(default=None, ge=1, le=10)
    user_notes: str | None = Field(default=None, max_length=2000)


@router.get("")
async def list_activities(
    sport_type: str | None = Query(None),
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List activities with optional filtering."""
    from datetime import timedelta

    query = select(Activity).order_by(Activity.start_date.desc())

    cutoff = utc_now_naive() - timedelta(days=days)
    query = query.where(Activity.start_date >= cutoff)

    if sport_type:
        query = query.where(Activity.sport_type == sport_type)

    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    activities = result.scalars().all()

    return [_activity_summary(a) for a in activities]


@router.get("/types")
async def list_sport_types(db: AsyncSession = Depends(get_db)):
    """List all sport types in the database."""
    from sqlalchemy import distinct

    result = await db.execute(select(distinct(Activity.sport_type)))
    return [row[0] for row in result.all()]


@router.get("/stats")
async def activity_stats(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """Get aggregate activity stats."""
    from backend.services.metrics import get_weekly_stats

    return await get_weekly_stats(db, weeks=days // 7 or 1)


@router.get("/{activity_id}")
async def get_activity(activity_id: int, db: AsyncSession = Depends(get_db)):
    """Get full activity detail including laps, zones, and weather.

    Does NOT include streams — those are fetched on-demand via
    `GET /{activity_id}/streams` (see below) so they can be fetched lazily
    and cached.
    """
    result = await db.execute(
        select(Activity).where(Activity.id == activity_id)
    )
    activity = result.scalar_one_or_none()
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")

    # Get laps
    laps_result = await db.execute(
        select(ActivityLap)
        .where(ActivityLap.activity_id == activity_id)
        .order_by(ActivityLap.lap_index)
    )
    laps = [_lap_dict(lap) for lap in laps_result.scalars().all()]

    # Get weather
    weather_result = await db.execute(
        select(WeatherSnapshot).where(WeatherSnapshot.activity_id == activity_id)
    )
    weather = weather_result.scalar_one_or_none()

    # Does the activity have cached streams already? (metadata only)
    streams_count = (await db.execute(
        select(ActivityStream).where(ActivityStream.activity_id == activity_id)
    )).scalars().first()

    # Drift / decoupling metrics — read-only against cached streams.
    # Returns None when streams aren't cached, never triggers a Strava fetch.
    hr_drift = await compute_hr_drift(db, activity_id)
    pace_decoupling = (
        await compute_pace_hr_decoupling(db, activity_id)
        if activity.sport_type in _RUN_SPORTS
        else None
    )
    power_decoupling = (
        await compute_power_hr_decoupling(db, activity_id)
        if activity.sport_type in _RIDE_SPORTS
        else None
    )

    detail = _activity_summary(activity)
    detail["laps"] = laps
    detail["zones"] = activity.zones_data
    detail["weather"] = _weather_dict(weather) if weather else None
    detail["streams_cached"] = streams_count is not None
    detail["hr_drift"] = hr_drift
    detail["pace_hr_decoupling"] = pace_decoupling
    detail["power_hr_decoupling"] = power_decoupling
    detail["raw_data"] = activity.raw_data
    return detail


@router.patch("/{activity_id}/feedback")
async def patch_activity_feedback(
    activity_id: int,
    payload: ActivityFeedbackPatch,
    db: AsyncSession = Depends(get_db),
):
    """Attach user-supplied RPE + notes to an activity.

    Accepts partial payloads. Unset fields are left unchanged; explicit
    ``null`` clears a previously-stored value. ``rated_at`` is stamped
    whenever either field is updated.
    """
    activity = (await db.execute(
        select(Activity).where(Activity.id == activity_id)
    )).scalar_one_or_none()
    if activity is None:
        raise HTTPException(status_code=404, detail="Activity not found")

    fields_set = payload.model_fields_set
    if not fields_set:
        raise HTTPException(status_code=400, detail="No fields provided")

    if "rpe" in fields_set:
        activity.rpe = payload.rpe
    if "user_notes" in fields_set:
        activity.user_notes = payload.user_notes
    activity.rated_at = utc_now_naive()

    await db.commit()
    await db.refresh(activity)
    return {
        "activity_id": activity.id,
        "rpe": activity.rpe,
        "user_notes": activity.user_notes,
        "rated_at": activity.rated_at.isoformat() if activity.rated_at else None,
    }


@router.post("/{activity_id}/classify")
async def classify_activity(
    activity_id: int, db: AsyncSession = Depends(get_db)
):
    """(Re-)run the classifier on this activity and persist the result.

    Useful for debugging classifier changes without touching enrichment.
    """
    from backend.services.classifier import classify_and_persist, dump

    activity = (await db.execute(
        select(Activity).where(Activity.id == activity_id)
    )).scalar_one_or_none()
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")

    laps = (await db.execute(
        select(ActivityLap)
        .where(ActivityLap.activity_id == activity_id)
        .order_by(ActivityLap.lap_index)
    )).scalars().all()

    result = classify_and_persist(activity, list(laps))
    await db.commit()
    if result is None:
        return {"classified": False, "reason": f"no classifier for sport {activity.sport_type}"}
    return {"classified": True, **dump(result)}


@router.get("/{activity_id}/weather")
async def get_activity_weather(
    activity_id: int,
    raw: bool = Query(False, description="Include raw OpenWeatherMap payload."),
    db: AsyncSession = Depends(get_db),
):
    """Return the WeatherSnapshot joined to this activity.

    404 if the activity doesn't exist or has no snapshot yet. Omits the
    ``raw_data`` blob by default to keep payloads small; pass
    ``?raw=true`` to include it (useful for rendering icons from the
    ``weather[0].icon`` code).
    """
    activity = (await db.execute(
        select(Activity).where(Activity.id == activity_id)
    )).scalar_one_or_none()
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")

    snapshot = (await db.execute(
        select(WeatherSnapshot).where(
            WeatherSnapshot.activity_id == activity_id
        )
    )).scalar_one_or_none()
    if not snapshot:
        raise HTTPException(
            status_code=404, detail="No weather snapshot for this activity"
        )

    return _weather_full_dict(snapshot, include_raw=raw)


@router.get("/{activity_id}/streams")
async def get_activity_streams(
    activity_id: int, db: AsyncSession = Depends(get_db)
):
    """Get per-sample streams for an activity. Lazy-fetched from Strava.

    First call for a given activity pulls streams from Strava and caches
    them in `activity_streams`. Subsequent calls return the cached data.
    """
    activity = (await db.execute(
        select(Activity).where(Activity.id == activity_id)
    )).scalar_one_or_none()
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")

    cached = (await db.execute(
        select(ActivityStream).where(ActivityStream.activity_id == activity_id)
    )).scalars().all()
    if cached:
        return {s.stream_type: s.data for s in cached}

    # Fetch + cache
    from backend.clients.strava import StravaClient
    client = StravaClient()
    try:
        streams = await client.get_activity_streams(activity.strava_id)
    except Exception as e:
        logger.warning(f"Streams fetch failed for activity {activity_id}: {e}")
        raise HTTPException(status_code=502, detail=f"Strava streams fetch failed: {e}")
    finally:
        await client.close()

    for stream_type, data in streams.items():
        if data:
            db.add(ActivityStream(
                activity_id=activity_id,
                stream_type=stream_type,
                data=data,
            ))
    await db.commit()
    return streams


def _activity_summary(a: Activity) -> dict:
    return {
        "id": a.id,
        "strava_id": a.strava_id,
        "name": a.name,
        "sport_type": a.sport_type,
        "start_date": a.start_date.isoformat() if a.start_date else None,
        "start_date_local": a.start_date_local.isoformat() if a.start_date_local else None,
        "elapsed_time": a.elapsed_time,
        "moving_time": a.moving_time,
        "distance": a.distance,
        "total_elevation": a.total_elevation,
        "average_hr": a.average_hr,
        "max_hr": a.max_hr,
        "average_speed": a.average_speed,
        "max_speed": a.max_speed,
        "average_power": a.average_power,
        "max_power": a.max_power,
        "weighted_avg_power": a.weighted_avg_power,
        "average_cadence": a.average_cadence,
        "calories": a.calories,
        "kilojoules": a.kilojoules,
        "suffer_score": a.suffer_score,
        "device_watts": a.device_watts,
        "workout_type": a.workout_type,
        "available_zones": a.available_zones,
        "enrichment_status": a.enrichment_status,
        "enriched_at": a.enriched_at.isoformat() if a.enriched_at else None,
        "classification_type": a.classification_type,
        "classification_flags": a.classification_flags,
        "classified_at": a.classified_at.isoformat() if a.classified_at else None,
        "weather_enriched": a.weather_enriched,
        "elev_high_m": a.elev_high_m,
        "elev_low_m": a.elev_low_m,
        "base_elevation_m": a.base_elevation_m,
        "elevation_enriched": a.elevation_enriched,
        "location_id": a.location_id,
        "start_lat": a.start_lat,
        "start_lng": a.start_lng,
        "rpe": a.rpe,
        "user_notes": a.user_notes,
        "rated_at": a.rated_at.isoformat() if a.rated_at else None,
    }


def _lap_dict(lap: ActivityLap) -> dict:
    return {
        "lap_index": lap.lap_index,
        "name": lap.name,
        "elapsed_time": lap.elapsed_time,
        "moving_time": lap.moving_time,
        "distance": lap.distance,
        "start_date": lap.start_date.isoformat() if lap.start_date else None,
        "average_speed": lap.average_speed,
        "max_speed": lap.max_speed,
        "average_heartrate": lap.average_heartrate,
        "max_heartrate": lap.max_heartrate,
        "average_cadence": lap.average_cadence,
        "average_watts": lap.average_watts,
        "total_elevation_gain": lap.total_elevation_gain,
        "pace_zone": lap.pace_zone,
        "hr_zone": lap.hr_zone,
        "split": lap.split,
        "start_index": lap.start_index,
        "end_index": lap.end_index,
    }


def _weather_dict(w: WeatherSnapshot) -> dict:
    return {
        "temp_c": w.temp_c,
        "feels_like_c": w.feels_like_c,
        "humidity": w.humidity,
        "wind_speed": w.wind_speed,
        "wind_gust": w.wind_gust,
        "wind_deg": w.wind_deg,
        "conditions": w.conditions,
        "description": w.description,
        "pressure": w.pressure,
        "uv_index": w.uv_index,
    }


def _weather_full_dict(w: WeatherSnapshot, *, include_raw: bool) -> dict:
    """Full WeatherSnapshot payload for the /weather endpoint.

    ``raw_data`` is heavy and only needed when the UI wants the
    OpenWeatherMap icon code (``raw_data.data[0].weather[0].icon``) — gate
    it behind an explicit flag.
    """
    out = {
        "id": w.id,
        "activity_id": w.activity_id,
        "temp_c": w.temp_c,
        "feels_like_c": w.feels_like_c,
        "humidity": w.humidity,
        "wind_speed": w.wind_speed,
        "wind_gust": w.wind_gust,
        "wind_deg": w.wind_deg,
        "conditions": w.conditions,
        "description": w.description,
        "pressure": w.pressure,
        "uv_index": w.uv_index,
        "created_at": w.created_at.isoformat() if w.created_at else None,
    }
    if include_raw:
        out["raw_data"] = w.raw_data
    return out
