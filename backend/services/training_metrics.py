"""Pure functions that assemble the raw inputs an LLM needs to reason about
today's training recommendation and the most-recent workout.

No rules, no prescriptions — just the numbers. Anything interpretive lives in
`backend/services/insights.py` (the LLM wrapper).
"""

from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    Activity,
    ActivityLap,
    Recovery,
    SleepSession,
    WeatherSnapshot,
)


# ──────────────────────────────────────────────────────────────────────────
# Training load snapshot
# ──────────────────────────────────────────────────────────────────────────


HARD_CLASSIFICATIONS = {"intervals", "tempo", "race", "mixed"}


def _stress_score(a: Activity) -> float:
    """TRIMP-ish training stress proxy. Prefer Strava's suffer_score."""
    if a.suffer_score:
        return float(a.suffer_score)
    if a.moving_time and a.average_hr:
        # Crude fallback: duration-weighted HR factor. Scaled so typical easy
        # run ~40–60, hard run ~100–150, similar to Strava's Relative Effort.
        return (a.moving_time / 60.0) * (a.average_hr / 180.0) * 1.2
    if a.moving_time:
        return a.moving_time / 120.0  # 30-min activity ≈ 15
    return 0.0


async def get_training_load_snapshot(db: AsyncSession, days: int = 42) -> dict:
    """Snapshot of the user's recent training load.

    Returns a dict with:
      - acute_load_7d, chronic_load_28d (sums of stress score)
      - acwr (acute:chronic workload ratio)
      - monotony, strain (Foster's definitions over last 7 days)
      - days_since_hard (last intervals/tempo/race/mixed session)
      - classification_counts_7d / _28d
      - daily_loads (chronological list of {date, value} for 28d)
    """
    today = date.today()
    window_start = today - timedelta(days=days)
    cutoff_dt = datetime.combine(window_start, datetime.min.time())

    rows = await db.execute(
        select(Activity)
        .where(Activity.start_date >= cutoff_dt)
        .order_by(Activity.start_date.asc())
    )
    activities = list(rows.scalars().all())

    # Daily load map
    daily: dict[date, float] = {}
    class_7d: dict[str, int] = {}
    class_28d: dict[str, int] = {}
    last_hard_date: date | None = None

    for a in activities:
        day = (a.start_date_local or a.start_date).date()
        daily[day] = daily.get(day, 0.0) + _stress_score(a)

        if a.classification_type:
            if (today - day).days < 28:
                class_28d[a.classification_type] = class_28d.get(a.classification_type, 0) + 1
            if (today - day).days < 7:
                class_7d[a.classification_type] = class_7d.get(a.classification_type, 0) + 1
            if a.classification_type in HARD_CLASSIFICATIONS:
                if last_hard_date is None or day > last_hard_date:
                    last_hard_date = day

    # Acute (7d) and Chronic (28d) sums
    def _sum_window(days_back: int) -> float:
        total = 0.0
        for i in range(days_back):
            d = today - timedelta(days=i)
            total += daily.get(d, 0.0)
        return total

    acute_7d = _sum_window(7)
    chronic_28d = _sum_window(28)

    # ACWR: acute average per day vs chronic average per day
    acute_avg = acute_7d / 7.0
    chronic_avg = chronic_28d / 28.0
    acwr = acute_avg / chronic_avg if chronic_avg > 0 else None

    # Monotony = mean(7d daily loads) / stdev(7d daily loads). Strain = load * monotony.
    last_7_values = [daily.get(today - timedelta(days=i), 0.0) for i in range(7)]
    monotony: float | None = None
    strain: float | None = None
    if any(v > 0 for v in last_7_values):
        m = statistics.mean(last_7_values)
        s = statistics.pstdev(last_7_values)
        if s > 0:
            monotony = m / s
            strain = acute_7d * monotony

    days_since_hard = (today - last_hard_date).days if last_hard_date else None

    # Chronological daily series (28 days oldest-first)
    daily_series = [
        {
            "date": (today - timedelta(days=27 - i)).isoformat(),
            "value": round(daily.get(today - timedelta(days=27 - i), 0.0), 1),
        }
        for i in range(28)
    ]

    return {
        "acute_load_7d": round(acute_7d, 1),
        "chronic_load_28d": round(chronic_28d, 1),
        "acwr": round(acwr, 2) if acwr is not None else None,
        "monotony": round(monotony, 2) if monotony is not None else None,
        "strain": round(strain, 1) if strain is not None else None,
        "days_since_hard": days_since_hard,
        "last_hard_date": last_hard_date.isoformat() if last_hard_date else None,
        "classification_counts_7d": class_7d,
        "classification_counts_28d": class_28d,
        "daily_loads": daily_series,
        "activity_count_7d": sum(
            1 for a in activities
            if (today - (a.start_date_local or a.start_date).date()).days < 7
        ),
    }


# ──────────────────────────────────────────────────────────────────────────
# Sleep snapshot
# ──────────────────────────────────────────────────────────────────────────


async def get_sleep_snapshot(
    db: AsyncSession, days: int = 14, target_hours: float = 8.0
) -> dict:
    cutoff = date.today() - timedelta(days=days)
    rows = await db.execute(
        select(SleepSession)
        .where(SleepSession.date >= cutoff)
        .order_by(SleepSession.date.desc())
    )
    sessions = list(rows.scalars().all())

    if not sessions:
        return {
            "last_night_score": None,
            "last_night_duration_min": None,
            "last_night_hrv": None,
            "avg_score_7d": None,
            "avg_duration_min_7d": None,
            "avg_hrv_7d": None,
            "sleep_debt_min": None,
            "nights_of_data": 0,
        }

    last = sessions[0]
    last_7 = sessions[:7]

    def _avg(attr: str, items: list[SleepSession]) -> float | None:
        values = [getattr(s, attr) for s in items if getattr(s, attr) is not None]
        return round(sum(values) / len(values), 1) if values else None

    target_min = int(target_hours * 60)
    durations_7 = [s.total_duration for s in last_7 if s.total_duration is not None]
    sleep_debt = sum(max(0, target_min - d) for d in durations_7) if durations_7 else None

    return {
        "last_night_date": last.date.isoformat(),
        "last_night_score": last.sleep_score,
        "last_night_duration_min": last.total_duration,
        "last_night_deep_min": last.deep_sleep,
        "last_night_rem_min": last.rem_sleep,
        "last_night_hrv": last.hrv,
        "last_night_resting_hr": last.avg_hr,
        "avg_score_7d": _avg("sleep_score", last_7),
        "avg_duration_min_7d": _avg("total_duration", last_7),
        "avg_hrv_7d": _avg("hrv", last_7),
        "sleep_debt_min": sleep_debt,
        "nights_of_data": len(sessions),
    }


# ──────────────────────────────────────────────────────────────────────────
# Recovery snapshot (Whoop)
# ──────────────────────────────────────────────────────────────────────────


async def get_recovery_snapshot(db: AsyncSession, days: int = 7) -> dict:
    cutoff = date.today() - timedelta(days=days)
    rows = await db.execute(
        select(Recovery)
        .where(Recovery.date >= cutoff)
        .order_by(Recovery.date.desc())
    )
    records = list(rows.scalars().all())

    if not records:
        return {
            "today_score": None,
            "today_hrv": None,
            "today_resting_hr": None,
            "avg_score_7d": None,
            "trend": None,
        }

    def _avg(attr: str) -> float | None:
        values = [getattr(r, attr) for r in records if getattr(r, attr) is not None]
        return round(sum(values) / len(values), 1) if values else None

    today_r = records[0]
    avg_7 = _avg("recovery_score")
    trend = None
    if today_r.recovery_score is not None and avg_7 is not None:
        diff = today_r.recovery_score - avg_7
        if diff > 5:
            trend = "improving"
        elif diff < -5:
            trend = "declining"
        else:
            trend = "stable"

    return {
        "today_date": today_r.date.isoformat(),
        "today_score": today_r.recovery_score,
        "today_hrv": today_r.hrv,
        "today_resting_hr": today_r.resting_hr,
        "avg_score_7d": avg_7,
        "trend": trend,
    }


# ──────────────────────────────────────────────────────────────────────────
# Latest workout summary (one activity, enriched with context)
# ──────────────────────────────────────────────────────────────────────────


async def _get_latest_completed_activity(
    db: AsyncSession, activity_id: int | None = None
) -> Activity | None:
    if activity_id is not None:
        row = await db.execute(select(Activity).where(Activity.id == activity_id))
        return row.scalar_one_or_none()

    row = await db.execute(
        select(Activity)
        .where(Activity.enrichment_status == "complete")
        .order_by(Activity.start_date.desc())
        .limit(1)
    )
    return row.scalar_one_or_none()


def _pace_str(avg_speed: float | None) -> str | None:
    """Speed (m/s) → pace string like '4:52/km'."""
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

    # Laps
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
                "avg_hr": round(lap.average_heartrate, 0) if lap.average_heartrate else None,
                "avg_watts": round(lap.average_watts, 0) if lap.average_watts else None,
                "pace_zone": lap.pace_zone,
            }
        )

    # Weather
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

    # Pre-workout sleep (the night before the activity's local date)
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

    # Historical comparison: last 90 days of the same classification (for runs)
    # Rank this activity on pace / HR-normalized pace / duration.
    historical = None
    if activity.classification_type and activity.sport_type in ("Run", "TrailRun", "VirtualRun"):
        hist_cutoff = datetime.now(timezone.utc) - timedelta(days=90)
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
                # Lower s/km is faster → percentile of being faster than N% of others.
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

    return {
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


# ──────────────────────────────────────────────────────────────────────────
# Combined snapshot used by the daily recommendation
# ──────────────────────────────────────────────────────────────────────────


async def get_full_snapshot(db: AsyncSession) -> dict:
    training = await get_training_load_snapshot(db)
    sleep = await get_sleep_snapshot(db)
    recovery = await get_recovery_snapshot(db)
    latest = await get_latest_workout_snapshot(db)

    # A compact list of the last 10 activities (summaries) for LLM context
    rows = await db.execute(
        select(Activity)
        .where(Activity.enrichment_status == "complete")
        .order_by(Activity.start_date.desc())
        .limit(10)
    )
    recent = []
    for a in rows.scalars().all():
        recent.append(
            {
                "date": (a.start_date_local or a.start_date).strftime("%Y-%m-%d"),
                "sport": a.sport_type,
                "classification": a.classification_type,
                "duration_min": (a.moving_time // 60) if a.moving_time else None,
                "distance_km": round(a.distance / 1000, 2) if a.distance else None,
                "avg_hr": round(a.average_hr) if a.average_hr else None,
                "suffer_score": a.suffer_score,
                "pace": _pace_str(a.average_speed) if a.sport_type.endswith("Run") else None,
            }
        )

    return {
        "today": date.today().isoformat(),
        "training_load": training,
        "sleep": sleep,
        "recovery": recovery,
        "latest_workout": latest,
        "recent_activities": recent,
    }
