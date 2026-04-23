"""Latest-workout snapshot assembly for dashboard insights."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Activity, ActivityLap, SleepSession, WeatherSnapshot
from backend.services.snapshot_models import LatestWorkoutSnapshot, validate_snapshot
from backend.services.time_utils import utc_now_naive


async def _get_latest_completed_activity(
    db: AsyncSession, activity_id: int | None = None
) -> Activity | None:
    if activity_id is not None:
        # Require enrichment_status == "complete" even for explicit IDs;
        # running the LLM on a pending row feeds it a half-populated snapshot.
        row = await db.execute(
            select(Activity).where(
                Activity.id == activity_id,
                Activity.enrichment_status == "complete",
            )
        )
        return row.scalar_one_or_none()

    row = await db.execute(
        select(Activity)
        .where(Activity.enrichment_status == "complete")
        .order_by(Activity.start_date.desc())
        .limit(1)
    )
    return row.scalar_one_or_none()


def _pace_str(avg_speed: float | None) -> str | None:
    """Speed (m/s) -> pace string like '4:52/km'."""
    if not avg_speed or avg_speed <= 0:
        return None
    pace_s_per_km = 1000.0 / avg_speed
    m, s = divmod(int(pace_s_per_km), 60)
    return f"{m}:{s:02d}/km"


async def get_latest_workout_snapshot(
    db: AsyncSession, activity_id: int | None = None
) -> dict | None:
    activity = await _get_latest_completed_activity(db, activity_id)
    if not activity:
        return None

    lap_rows = await db.execute(
        select(ActivityLap)
        .where(ActivityLap.activity_id == activity.id)
        .order_by(ActivityLap.lap_index.asc())
    )
    laps = list(lap_rows.scalars().all())
    lap_summaries = []
    for lap in laps:
        lap_summaries.append(
            {
                "index": lap.lap_index,
                "distance_m": round(lap.distance, 0) if lap.distance else None,
                "moving_time_s": lap.moving_time,
                "pace": _pace_str(lap.average_speed),
                "avg_hr": round(lap.average_heartrate, 0)
                if lap.average_heartrate
                else None,
                "avg_watts": round(lap.average_watts, 0) if lap.average_watts else None,
                "pace_zone": lap.pace_zone,
            }
        )

    weather_row = await db.execute(
        select(WeatherSnapshot).where(WeatherSnapshot.activity_id == activity.id)
    )
    w = weather_row.scalar_one_or_none()
    weather = None
    if w:
        weather = {
            "temp_c": w.temp_c,
            "feels_like_c": w.feels_like_c,
            "humidity": w.humidity,
            "wind_speed_ms": w.wind_speed,
            "conditions": w.conditions,
        }

    pre_sleep = None
    start_local_date = (
        activity.start_date_local.date() if activity.start_date_local else activity.start_date.date()
    )
    sleep_row = await db.execute(
        select(SleepSession)
        .where(SleepSession.date == start_local_date)
        .order_by(SleepSession.id.desc())
        .limit(1)
    )
    s = sleep_row.scalar_one_or_none()
    if s:
        pre_sleep = {
            "date": s.date.isoformat(),
            "score": s.sleep_score,
            "duration_min": s.total_duration,
            "hrv": s.hrv,
            "deep_min": s.deep_sleep,
            "rem_min": s.rem_sleep,
        }

    historical = None
    if activity.classification_type and activity.sport_type in ("Run", "TrailRun", "VirtualRun"):
        hist_cutoff = utc_now_naive() - timedelta(days=90)
        hist_rows = await db.execute(
            select(Activity)
            .where(
                Activity.classification_type == activity.classification_type,
                Activity.sport_type == activity.sport_type,
                Activity.start_date >= hist_cutoff,
                Activity.id != activity.id,
                Activity.enrichment_status == "complete",
            )
        )
        hist = list(hist_rows.scalars().all())
        if len(hist) >= 3:
            pace_values = [
                1000.0 / a.average_speed
                for a in hist
                if a.average_speed and a.average_speed > 0
            ]
            this_pace = (
                1000.0 / activity.average_speed
                if activity.average_speed and activity.average_speed > 0
                else None
            )
            pace_percentile = None
            if this_pace and pace_values:
                faster_than = sum(1 for v in pace_values if v > this_pace)
                pace_percentile = round(100 * faster_than / len(pace_values))

            effort_values = [a.suffer_score for a in hist if a.suffer_score]
            effort_percentile = None
            if activity.suffer_score and effort_values:
                lower = sum(1 for v in effort_values if v < activity.suffer_score)
                effort_percentile = round(100 * lower / len(effort_values))

            historical = {
                "classification": activity.classification_type,
                "sample_size": len(hist),
                "window_days": 90,
                "pace_percentile": pace_percentile,
                "effort_percentile": effort_percentile,
            }

    payload = {
        "id": activity.id,
        "strava_id": activity.strava_id,
        "name": activity.name,
        "sport_type": activity.sport_type,
        "classification_type": activity.classification_type,
        "classification_flags": activity.classification_flags or [],
        "start_date": activity.start_date.isoformat() if activity.start_date else None,
        "start_date_local": (
            activity.start_date_local.isoformat() if activity.start_date_local else None
        ),
        "distance_m": activity.distance,
        "moving_time_s": activity.moving_time,
        "elapsed_time_s": activity.elapsed_time,
        "total_elevation_m": activity.total_elevation,
        "avg_hr": activity.average_hr,
        "max_hr": activity.max_hr,
        "avg_speed_ms": activity.average_speed,
        "pace": _pace_str(activity.average_speed),
        "avg_power_w": activity.average_power,
        "weighted_avg_power_w": activity.weighted_avg_power,
        "kilojoules": activity.kilojoules,
        "suffer_score": activity.suffer_score,
        "calories": activity.calories,
        "laps": lap_summaries,
        "weather": weather,
        "pre_workout_sleep": pre_sleep,
        "historical_comparison": historical,
    }
    return validate_snapshot(payload, LatestWorkoutSnapshot)
