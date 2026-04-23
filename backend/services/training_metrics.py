"""Pure functions that assemble the raw inputs an LLM needs to reason about
today's training recommendation and the most-recent workout.

No rules, no prescriptions — just the numbers. Anything interpretive lives in
`backend/services/insights.py` (the LLM wrapper).
"""

from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    Activity,
    ActivityLap,
    Goal,
    RecommendationFeedback,
    Recovery,
    SleepSession,
    WeatherSnapshot,
)
from backend.services.snapshot_models import (
    EnvironmentalSnapshot,
    FeedbackSummarySnapshot,
    FullSnapshot,
    GoalsSnapshot,
    LatestWorkoutSnapshot,
    RecentActivitySnapshot,
    RecentRpeSnapshot,
    RecoverySnapshot,
    SleepSnapshot,
    TrainingLoadSnapshot,
    validate_baselines,
    validate_snapshot,
    validate_snapshot_list,
)
from backend.services.time_utils import local_today, utc_now_naive


# ──────────────────────────────────────────────────────────────────────────
# Training load snapshot
# ──────────────────────────────────────────────────────────────────────────


HARD_CLASSIFICATIONS = {"intervals", "tempo", "race", "mixed"}


def _stress_score(a: Activity) -> float:
    """TRIMP-ish training stress proxy, scaled to Strava's suffer_score.

    Three tiers of fidelity; all intended to land in roughly the same
    0–200 range for typical sessions so ACWR / monotony don't get skewed
    when HR is unavailable (e.g. strength sessions, indoor spin):

    1. Strava ``suffer_score`` (watch-derived) — preferred; 0–300.
    2. HR-based: ``duration_min * (avg_hr / 180) * 1.2`` — 60 min @
       140 bpm ≈ 56, matching Strava's RE for a typical aerobic run.
    3. Duration-only: ``duration_min``. Assumes moderate effort
       (≈140 bpm). A 60-min strength session scores 60, comparable to
       the HR-based path; previously this was ``duration_min / 2`` which
       underweighted unlogged-HR sessions by ~2x and tilted ACWR.
    """
    if a.suffer_score:
        return float(a.suffer_score)
    if a.moving_time and a.average_hr:
        return (a.moving_time / 60.0) * (a.average_hr / 180.0) * 1.2
    if a.moving_time:
        return a.moving_time / 60.0
    return 0.0


async def get_training_load_snapshot(
    db: AsyncSession, days: int = 42, today: date | None = None
) -> dict:
    """Snapshot of the user's recent training load.

    Returns a dict with:
      - acute_load_7d, chronic_load_28d (sums of stress score)
      - acwr (acute:chronic workload ratio)
      - monotony, strain (Foster's definitions over last 7 days)
      - days_since_hard (last intervals/tempo/race/mixed session)
      - classification_counts_7d / _28d
      - daily_loads (chronological list of {date, value} for 28d)
    """
    today = today or local_today()
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

    payload = {
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
    return validate_snapshot(payload, TrainingLoadSnapshot)


# ──────────────────────────────────────────────────────────────────────────
# Sleep snapshot
# ──────────────────────────────────────────────────────────────────────────


async def get_sleep_snapshot(
    db: AsyncSession,
    days: int = 14,
    target_hours: float = 8.0,
    today: date | None = None,
) -> dict:
    today = today or local_today()
    cutoff = today - timedelta(days=days)
    rows = await db.execute(
        select(SleepSession)
        .where(SleepSession.date >= cutoff)
        .order_by(SleepSession.date.desc())
    )
    sessions = list(rows.scalars().all())

    if not sessions:
        payload = {
            "last_night_score": None,
            "last_night_duration_min": None,
            "last_night_hrv": None,
            "avg_score_7d": None,
            "avg_duration_min_7d": None,
            "avg_hrv_7d": None,
            "sleep_debt_min": None,
            "nights_of_data": 0,
        }
        return validate_snapshot(payload, SleepSnapshot)

    last = sessions[0]
    last_7 = sessions[:7]

    def _avg(attr: str, items: list[SleepSession]) -> float | None:
        values = [getattr(s, attr) for s in items if getattr(s, attr) is not None]
        return round(sum(values) / len(values), 1) if values else None

    target_min = int(target_hours * 60)
    durations_7 = [s.total_duration for s in last_7 if s.total_duration is not None]
    sleep_debt = sum(max(0, target_min - d) for d in durations_7) if durations_7 else None

    payload = {
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
    return validate_snapshot(payload, SleepSnapshot)


# ──────────────────────────────────────────────────────────────────────────
# Recovery snapshot (Whoop)
# ──────────────────────────────────────────────────────────────────────────


async def get_recovery_snapshot(
    db: AsyncSession, days: int = 7, today: date | None = None
) -> dict:
    today = today or local_today()
    cutoff = today - timedelta(days=days)
    rows = await db.execute(
        select(Recovery)
        .where(Recovery.date >= cutoff)
        .order_by(Recovery.date.desc())
    )
    records = list(rows.scalars().all())

    if not records:
        payload = {
            "today_score": None,
            "today_hrv": None,
            "today_resting_hr": None,
            "avg_score_7d": None,
            "trend": None,
        }
        return validate_snapshot(payload, RecoverySnapshot)

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

    payload = {
        "today_date": today_r.date.isoformat(),
        "today_score": today_r.recovery_score,
        "today_hrv": today_r.hrv,
        "today_resting_hr": today_r.resting_hr,
        "avg_score_7d": avg_7,
        "trend": trend,
    }
    return validate_snapshot(payload, RecoverySnapshot)


# ──────────────────────────────────────────────────────────────────────────
# Latest workout summary (one activity, enriched with context)
# ──────────────────────────────────────────────────────────────────────────


async def _get_latest_completed_activity(
    db: AsyncSession, activity_id: int | None = None
) -> Activity | None:
    if activity_id is not None:
        # Require enrichment_status == "complete" even for explicit IDs;
        # running the LLM on a pending row feeds it a half-populated
        # snapshot (no laps, no weighted power, etc.).
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


# ──────────────────────────────────────────────────────────────────────────
# Goals snapshot
# ──────────────────────────────────────────────────────────────────────────


def _periodization_phase(weeks_until: int) -> str:
    """Map weeks-until-goal to a training phase.

    Values cross-reference the LLM system prompt so the recommendation can
    name the phase explicitly.
    """
    if weeks_until <= 2:
        return "peak"
    if weeks_until <= 4:
        return "taper"
    if weeks_until <= 12:
        return "build"
    return "base"


def _goal_to_dict(g: Goal, today: date) -> dict:
    days_until = (g.target_date - today).days
    weeks_until = max(0, days_until // 7)
    return {
        "id": g.id,
        "race_type": g.race_type,
        "description": g.description,
        "target_date": g.target_date.isoformat(),
        "days_until": days_until,
        "weeks_until": weeks_until,
        "phase": _periodization_phase(weeks_until) if days_until >= 0 else "post",
        "is_primary": g.is_primary,
        "status": g.status,
    }


async def get_goals_snapshot(db: AsyncSession, today: date | None = None) -> dict:
    """Return the user's active goals, split into primary + secondary."""
    today = today or local_today()
    rows = await db.execute(
        select(Goal)
        .where(Goal.status == "active")
        .order_by(Goal.is_primary.desc(), Goal.target_date.asc())
    )
    goals = list(rows.scalars().all())
    primary = next((g for g in goals if g.is_primary), None)
    secondary = [g for g in goals if not g.is_primary]
    payload = {
        "primary": _goal_to_dict(primary, today) if primary else None,
        "secondary": [_goal_to_dict(g, today) for g in secondary],
    }
    return validate_snapshot(payload, GoalsSnapshot)


# ──────────────────────────────────────────────────────────────────────────
# Baselines — 90-day mean/sd per sport
# ──────────────────────────────────────────────────────────────────────────


def _mean_sd(values: list[float]) -> tuple[float, float] | None:
    clean = [v for v in values if v is not None]
    if len(clean) < 2:
        return None
    return statistics.mean(clean), statistics.pstdev(clean)


async def get_baselines(
    db: AsyncSession, days: int = 90, today: date | None = None
) -> dict:
    """Mean + stdev of pace / HR / power per sport over the last ``days``.

    Returns ``None`` for sports with fewer than 10 complete activities —
    sparse baselines are worse than no baseline for the LLM's reasoning.
    """
    today = today or local_today()
    cutoff_dt = datetime.combine(today - timedelta(days=days), datetime.min.time())
    rows = await db.execute(
        select(Activity).where(
            Activity.start_date >= cutoff_dt,
            Activity.enrichment_status == "complete",
        )
    )
    by_sport: dict[str, list[Activity]] = {}
    for a in rows.scalars().all():
        by_sport.setdefault(a.sport_type, []).append(a)

    out: dict[str, dict | None] = {}
    for sport, items in by_sport.items():
        if len(items) < 10:
            out[sport] = None
            continue

        def _round_pair(pair):
            if pair is None:
                return None
            return {"mean": round(pair[0], 2), "sd": round(pair[1], 2)}

        pace_values = [1000.0 / a.average_speed for a in items if a.average_speed]
        hr_values = [a.average_hr for a in items if a.average_hr]
        power_values = [a.average_power for a in items if a.average_power]
        out[sport] = {
            "sample_size": len(items),
            "pace_s_per_km": _round_pair(_mean_sd(pace_values)),
            "avg_hr": _round_pair(_mean_sd(hr_values)),
            "avg_power_w": _round_pair(_mean_sd(power_values)),
        }
    return validate_baselines(out)


# ──────────────────────────────────────────────────────────────────────────
# Recent RPE (user-reported effort)
# ──────────────────────────────────────────────────────────────────────────


async def get_recent_rpe(
    db: AsyncSession,
    days: int = 14,
    limit: int = 10,
    today: date | None = None,
) -> list[dict]:
    """Compact list of recent workouts where the user rated perceived effort.

    Empty list when nothing has been rated yet — the LLM knows to skip
    that branch of the prompt in that case.
    """
    today = today or local_today()
    cutoff_dt = datetime.combine(today - timedelta(days=days), datetime.min.time())
    rows = await db.execute(
        select(Activity)
        .where(
            Activity.start_date >= cutoff_dt,
            Activity.rpe.is_not(None),
        )
        .order_by(Activity.start_date.desc())
        .limit(limit)
    )
    out: list[dict] = []
    for a in rows.scalars().all():
        out.append(
            {
                "activity_id": a.id,
                "date": (a.start_date_local or a.start_date).strftime("%Y-%m-%d"),
                "sport_type": a.sport_type,
                "classification": a.classification_type,
                "rpe": a.rpe,
                "notes": a.user_notes,
                "avg_hr": round(a.average_hr) if a.average_hr else None,
                "suffer_score": a.suffer_score,
            }
        )
    return validate_snapshot_list(out, RecentRpeSnapshot)


# ──────────────────────────────────────────────────────────────────────────
# Feedback summary — past thumbs-up/down on daily recommendations
# ──────────────────────────────────────────────────────────────────────────


async def get_feedback_summary(
    db: AsyncSession, days: int = 30, today: date | None = None
) -> dict:
    today = today or local_today()
    cutoff = today - timedelta(days=days)
    rows = await db.execute(
        select(RecommendationFeedback)
        .where(RecommendationFeedback.recommendation_date >= cutoff)
        .order_by(RecommendationFeedback.recommendation_date.desc())
    )
    items = list(rows.scalars().all())
    up = sum(1 for r in items if r.vote == "up")
    down = sum(1 for r in items if r.vote == "down")
    recent_declines = [
        {
            "date": r.recommendation_date.isoformat(),
            "reason": r.reason,
        }
        for r in items
        if r.vote == "down"
    ][:5]
    payload = {
        "accepted": up,
        "declined": down,
        "total": len(items),
        "recent_declines": recent_declines,
    }
    return validate_snapshot(payload, FeedbackSummarySnapshot)


# ──────────────────────────────────────────────────────────────────────────
# Environmental snapshot (best-effort: last night's sleep temp)
# ──────────────────────────────────────────────────────────────────────────


async def get_environmental_snapshot(db: AsyncSession) -> dict | None:
    """Environmental context for today: last-night bed-temp + next-workout weather.

    Returns ``None`` when we have neither. Intentionally small — the LLM
    doesn't need a full weather forecast, just a nudge when conditions
    are unusual.
    """
    last_sleep = (await db.execute(
        select(SleepSession).order_by(SleepSession.date.desc()).limit(1)
    )).scalar_one_or_none()
    bed_temp_c = last_sleep.bed_temp if last_sleep else None
    if bed_temp_c is None:
        return None
    payload = {
        "last_night_bed_temp_c": bed_temp_c,
        "last_night_date": last_sleep.date.isoformat() if last_sleep else None,
    }
    return validate_snapshot(payload, EnvironmentalSnapshot)


# ──────────────────────────────────────────────────────────────────────────
# Combined snapshot used by the daily recommendation
# ──────────────────────────────────────────────────────────────────────────


async def get_full_snapshot(db: AsyncSession, today: date | None = None) -> dict:
    today = today or local_today()
    training = await get_training_load_snapshot(db, today=today)
    sleep = await get_sleep_snapshot(db, today=today)
    recovery = await get_recovery_snapshot(db, today=today)
    latest = await get_latest_workout_snapshot(db)
    goals = await get_goals_snapshot(db, today=today)
    baselines = await get_baselines(db, today=today)
    recent_rpe = await get_recent_rpe(db, today=today)
    feedback = await get_feedback_summary(db, today=today)
    environmental = await get_environmental_snapshot(db)

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

    validate_snapshot_list(recent, RecentActivitySnapshot)

    payload = {
        "today": today.isoformat(),
        "training_load": training,
        "sleep": sleep,
        "recovery": recovery,
        "latest_workout": latest,
        "recent_activities": recent,
        "goals": goals,
        "baselines": baselines,
        "recent_rpe": recent_rpe,
        "feedback_summary": feedback,
        "environmental": environmental,
    }
    return validate_snapshot(payload, FullSnapshot)
