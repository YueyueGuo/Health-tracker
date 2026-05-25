"""Latest-workout snapshot assembly for dashboard insights."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Literal, NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    Activity,
    ActivityLap,
    HealthDataPoint,
    SleepSession,
    WeatherSnapshot,
    Workout,
)
from backend.services.hr_zones import (
    compute_hr_drift,
    compute_pace_hr_decoupling,
    compute_power_hr_decoupling,
    summarize_hr_zones,
)
from backend.services.snapshot_models import LatestWorkoutSnapshot, validate_snapshot
from backend.services.sport_mapping import normalized_to_strava_view
from backend.services.time_utils import utc_now_naive

_RUN_SPORTS = {"Run", "TrailRun", "VirtualRun"}
_RIDE_SPORTS = {"Ride", "VirtualRide", "GravelRide", "MountainBikeRide", "EBikeRide"}


class LatestCandidate(NamedTuple):
    """Tagged result for the latest-workout resolver.

    ``kind == "strava"`` carries an ``Activity`` row. ``kind == "apple"``
    carries the ``(HealthDataPoint, Workout)`` pair so the snapshot
    builder can read both halves of the joined-table row without an
    extra query.
    """

    kind: Literal["strava", "apple"]
    obj: object  # Activity | tuple[HealthDataPoint, Workout]


def _to_naive_utc(dt: datetime | None) -> datetime | None:
    """Normalize a datetime to naive-UTC for ordering across sources.

    ``Activity.start_date`` and ``HealthDataPoint.start_time`` are both
    declared ``DateTime(timezone=True)``, but SQLite-backed test rows are
    often inserted as naive datetimes. Coerce to a single representation
    before comparing.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


async def _get_latest_completed_activity(
    db: AsyncSession,
    activity_id: int | None = None,
    on_date: date | None = None,
) -> LatestCandidate | None:
    """Pick the most recent canonical workout across Strava + Apple Health.

    Strava candidates require ``enrichment_status == "complete"`` and
    ``superseded_by_id IS NULL`` (mirroring the History page's filter so
    Apple-wins-dedup rows don't leak through here). Apple candidates are
    ``HealthDataPoint(source="apple_health", data_type="workout")`` rows
    joined to their ``Workout`` child.

    The ``activity_id`` and ``on_date`` lookup paths are intentionally
    Strava-only — the cached-LLM-insight path keys off ``Activity.id``,
    and there's no equivalent cached output for Apple workouts in v1.
    The Home dashboard always calls without an id, which is the case
    this fix targets.
    """
    if activity_id is not None:
        # Require enrichment_status == "complete" even for explicit IDs;
        # running the LLM on a pending row feeds it a half-populated snapshot.
        row = await db.execute(
            select(Activity).where(
                Activity.id == activity_id,
                Activity.enrichment_status == "complete",
            )
        )
        activity = row.scalar_one_or_none()
        if activity is None:
            return None
        return LatestCandidate(kind="strava", obj=activity)

    # ── Strava candidate ────────────────────────────────────────────
    strava_query = (
        select(Activity)
        .where(
            Activity.enrichment_status == "complete",
            Activity.superseded_by_id.is_(None),
        )
        .order_by(Activity.start_date.desc())
        .limit(1)
    )
    if on_date is not None:
        # Match activities whose local start day equals on_date. Fall back
        # to start_date (UTC) when start_date_local is null.
        day_start = datetime.combine(on_date, time.min)
        day_end = datetime.combine(on_date, time.max)
        strava_query = strava_query.where(
            (
                (Activity.start_date_local.is_not(None))
                & (Activity.start_date_local >= day_start)
                & (Activity.start_date_local <= day_end)
            )
            | (
                (Activity.start_date_local.is_(None))
                & (Activity.start_date >= day_start)
                & (Activity.start_date <= day_end)
            )
        )
    strava_row = (await db.execute(strava_query)).scalar_one_or_none()

    # ── Apple Health candidate ──────────────────────────────────────
    # Skip the Apple branch when ``on_date`` is set: HealthDataPoint
    # only stores a UTC ``start_time`` (no separate local field), so
    # day-bucketing against ``on_date`` would be ambiguous. The Home
    # card never passes ``on_date``, which is the bug site.
    apple_pair: tuple[HealthDataPoint, Workout] | None = None
    if on_date is None:
        apple_query = (
            select(HealthDataPoint, Workout)
            .join(Workout, Workout.id == HealthDataPoint.id)
            .where(
                HealthDataPoint.source == "apple_health",
                HealthDataPoint.data_type == "workout",
            )
            .order_by(HealthDataPoint.start_time.desc())
            .limit(1)
        )
        apple_row = (await db.execute(apple_query)).first()
        if apple_row is not None:
            apple_pair = (apple_row[0], apple_row[1])

    if strava_row is None and apple_pair is None:
        return None
    if apple_pair is None:
        return LatestCandidate(kind="strava", obj=strava_row)
    if strava_row is None:
        return LatestCandidate(kind="apple", obj=apple_pair)

    # Both exist — pick the later start time. Normalize aware/naive to
    # naive-UTC so the comparison is well-defined even when the SQLite
    # test backend strips tzinfo on read.
    strava_ts = _to_naive_utc(strava_row.start_date)
    apple_ts = _to_naive_utc(apple_pair[0].start_time)
    if apple_ts is not None and (strava_ts is None or apple_ts > strava_ts):
        return LatestCandidate(kind="apple", obj=apple_pair)
    return LatestCandidate(kind="strava", obj=strava_row)


def _pace_str(avg_speed: float | None) -> str | None:
    """Speed (m/s) -> pace string like '4:52/km'."""
    if not avg_speed or avg_speed <= 0:
        return None
    pace_s_per_km = 1000.0 / avg_speed
    m, s = divmod(int(pace_s_per_km), 60)
    return f"{m}:{s:02d}/km"


async def get_latest_workout_snapshot(
    db: AsyncSession,
    activity_id: int | None = None,
    on_date: date | None = None,
) -> dict | None:
    candidate = await _get_latest_completed_activity(db, activity_id, on_date)
    if candidate is None:
        return None

    if candidate.kind == "apple":
        payload = await _build_apple_snapshot(db, candidate.obj)
        return validate_snapshot(payload, LatestWorkoutSnapshot)

    activity: Activity = candidate.obj  # type: ignore[assignment]

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
                "hr_zone": lap.hr_zone,
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

    # Historical-comparison block is Strava-only by design: it reads
    # ``classification_type`` / ``suffer_score`` / ``average_speed`` from
    # the ``activities`` table. Apple rows already short-circuit via the
    # ``candidate.kind == "apple"`` branch above, but the explicit
    # comment keeps the dependency obvious.
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

    hr_drift = await compute_hr_drift(db, activity.id)
    pace_decoupling = (
        await compute_pace_hr_decoupling(db, activity.id)
        if activity.sport_type in _RUN_SPORTS
        else None
    )
    power_decoupling = (
        await compute_power_hr_decoupling(db, activity.id)
        if activity.sport_type in _RIDE_SPORTS
        else None
    )

    payload = {
        "id": activity.id,
        "strava_id": activity.strava_id,
        "source": "strava",
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
        "hr_zones": summarize_hr_zones(activity.zones_data),
        "hr_drift": hr_drift,
        "pace_hr_decoupling": pace_decoupling,
        "power_hr_decoupling": power_decoupling,
        "weather": weather,
        "pre_workout_sleep": pre_sleep,
        "historical_comparison": historical,
    }
    return validate_snapshot(payload, LatestWorkoutSnapshot)


async def _build_apple_snapshot(
    db: AsyncSession, pair: tuple[HealthDataPoint, Workout]
) -> dict:
    """Map an Apple ``(HealthDataPoint, Workout)`` pair onto the snapshot shape.

    Mirrors ``backend.routers.activities._apple_workout_summary`` for the
    fields that overlap; Strava-only fields (avg/weighted power,
    kilojoules, HR zones, lap detail, decoupling, weather, etc.) are
    intentionally ``None`` — there's no Apple-side equivalent in v1.

    Pre-workout sleep IS populated by ``start_time``-derived local date
    so the Home card can still surface that context for Apple workouts.
    """
    dp, workout = pair

    pre_sleep = None
    if dp.start_time is not None:
        # HealthDataPoint only stores a UTC ``start_time``. Use it as the
        # date key for pre-workout sleep — single-user app, viewer TZ
        # roughly matches the workout TZ.
        sleep_row = await db.execute(
            select(SleepSession)
            .where(SleepSession.date == dp.start_time.date())
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

    name = (dp.raw_payload or {}).get("name") or workout.activity_type
    return {
        "id": dp.id,
        "strava_id": None,
        "source": "apple_health",
        "name": name,
        "sport_type": normalized_to_strava_view(workout.activity_type),
        "classification_type": None,
        "classification_flags": [],
        "start_date": dp.start_time.isoformat() if dp.start_time else None,
        # HAE has no separate local-time field; surface UTC for both so
        # the frontend's date formatter still has something to render.
        "start_date_local": dp.start_time.isoformat() if dp.start_time else None,
        "distance_m": workout.distance_m,
        "moving_time_s": workout.duration_s,
        "elapsed_time_s": workout.duration_s,
        "total_elevation_m": workout.total_elevation_m,
        "avg_hr": workout.avg_hr,
        "max_hr": workout.max_hr,
        "avg_speed_ms": workout.avg_speed_mps,
        "pace": _pace_str(workout.avg_speed_mps),
        "avg_power_w": None,
        "weighted_avg_power_w": None,
        "kilojoules": None,
        "suffer_score": None,
        "calories": workout.active_energy_kcal,
        "laps": [],
        "hr_zones": None,
        "hr_drift": None,
        "pace_hr_decoupling": None,
        "power_hr_decoupling": None,
        "weather": None,
        "pre_workout_sleep": pre_sleep,
        "historical_comparison": None,
    }
