from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import Activity, ActivityStream, WeatherSnapshot

router = APIRouter()


@router.get("")
async def list_activities(
    sport_type: str | None = Query(None),
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List activities with optional filtering."""
    from datetime import timedelta, timezone

    query = select(Activity).order_by(Activity.start_date.desc())

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
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
    """Get full activity detail including streams and weather."""
    result = await db.execute(
        select(Activity).where(Activity.id == activity_id)
    )
    activity = result.scalar_one_or_none()
    if not activity:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Activity not found")

    # Get streams
    streams_result = await db.execute(
        select(ActivityStream).where(ActivityStream.activity_id == activity_id)
    )
    streams = {s.stream_type: s.data for s in streams_result.scalars().all()}

    # Get weather
    weather_result = await db.execute(
        select(WeatherSnapshot).where(WeatherSnapshot.activity_id == activity_id)
    )
    weather = weather_result.scalar_one_or_none()

    detail = _activity_summary(activity)
    detail["streams"] = streams
    detail["weather"] = _weather_dict(weather) if weather else None
    detail["raw_data"] = activity.raw_data
    return detail


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
        "average_cadence": a.average_cadence,
        "calories": a.calories,
        "suffer_score": a.suffer_score,
        "has_streams": a.has_streams,
        "weather_enriched": a.weather_enriched,
    }


def _weather_dict(w: WeatherSnapshot) -> dict:
    return {
        "temp_c": w.temp_c,
        "feels_like_c": w.feels_like_c,
        "humidity": w.humidity,
        "wind_speed": w.wind_speed,
        "conditions": w.conditions,
        "description": w.description,
        "pressure": w.pressure,
        "uv_index": w.uv_index,
    }
