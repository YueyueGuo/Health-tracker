from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import (
    Activity,
    ActivityLap,
    ActivityStream,
    HealthDataPoint,
    Shoe,
    WeatherSnapshot,
    Workout,
)
from backend.services.activity_feed import list_activity_feed
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


class ActivityShoePatch(BaseModel):
    """Tag (or untag) a running shoe on an activity / workout.

    ``shoe_id=None`` clears the tag. Retired shoes are not tag-eligible
    for new tags; existing tags to a now-retired shoe are untouched.
    """

    shoe_id: int | None = None


@router.get("")
async def list_activities(
    sport_type: str | None = Query(None),
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    include_superseded: bool = Query(
        False,
        description=(
            "When False (default), hide Strava activities that an Apple "
            "Health workout has superseded."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """List activities with optional filtering.

    Surfaces both Strava ``Activity`` rows and Apple Health ``Workout``
    rows in one merged list sorted by start time. We run two Apple
    queries (Apple-only + Apple-wins-dedup) so the canonical Apple row
    never disappears when it has a back-link to a Strava activity that
    Apple superseded. Volumes are small and the column shapes differ
    enough that a UNION would be more code than sort-merge.

    Canonical row policy:
    * Strava rows whose ``superseded_by_id`` is NULL → canonical Strava.
    * Apple workouts with ``activity_id`` NULL → canonical Apple-only.
    * Apple workouts with ``activity_id`` set AND the linked Strava
      row's ``superseded_by_id`` is non-NULL → canonical Apple (Apple
      won the dedup).
    With ``include_superseded=True`` we also surface superseded Strava
    rows (the "losers"); the linked Apple winners still appear, so
    callers will see two rows for the same conceptual workout — that's
    intentional for the debug-style view.
    """
    from datetime import timedelta

    cutoff = utc_now_naive() - timedelta(days=days)
    return await list_activity_feed(
        db,
        cutoff=cutoff,
        limit=limit,
        offset=offset,
        sport_type=sport_type,
        include_superseded=include_superseded,
    )


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
async def get_activity(
    activity_id: int,
    source: str | None = Query(
        None,
        description=(
            "Disambiguate Strava vs Apple Health when the integer ids "
            "collide. ``strava`` forces the Strava row, ``apple_health`` "
            "forces the Apple HealthDataPoint row. When omitted, retains "
            "the legacy Strava-first / Apple-fallback resolution."
        ),
    ),
    units: Literal["metric", "imperial"] = Query(
        "metric",
        description=(
            "Unit preference used when re-binning Apple Health synthetic "
            "splits. ``metric`` (default) returns the persisted "
            "kilometre-bucket laps verbatim; ``imperial`` re-bins from "
            "the workout totals using mile-sized buckets. Has no effect "
            "on Strava activities, whose laps come from the sensor."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """Get full activity detail including laps, zones, and weather.

    Does NOT include streams — those are fetched on-demand via
    `GET /{activity_id}/streams` (see below) so they can be fetched lazily
    and cached.

    The ``activity_id`` may resolve to either a Strava ``Activity`` row
    or an Apple Health ``HealthDataPoint`` (workout) row — they live in
    independent tables but share the same integer id space. Without
    ``source``, Strava wins on collisions and Apple-only ids only resolve
    after the Strava lookup misses. Pass ``source=apple_health`` or
    ``source=strava`` to disambiguate explicitly.
    """
    if source is not None and source not in ("strava", "apple_health"):
        raise HTTPException(
            status_code=400,
            detail="source must be 'strava' or 'apple_health'",
        )

    if source == "apple_health":
        from backend.services.apple_workout_detail import (
            get_apple_workout_detail,
        )

        apple_detail = await get_apple_workout_detail(
            db, activity_id, units=units
        )
        if apple_detail is None:
            raise HTTPException(status_code=404, detail="Activity not found")
        return apple_detail

    result = await db.execute(select(Activity).where(Activity.id == activity_id))
    activity = result.scalar_one_or_none()
    if not activity:
        if source == "strava":
            # Explicit Strava intent — do not fall through to Apple.
            raise HTTPException(status_code=404, detail="Activity not found")
        from backend.services.apple_workout_detail import (
            get_apple_workout_detail,
        )

        apple_detail = await get_apple_workout_detail(
            db, activity_id, units=units
        )
        if apple_detail is not None:
            return apple_detail
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
    streams_count = (
        (await db.execute(select(ActivityStream).where(ActivityStream.activity_id == activity_id)))
        .scalars()
        .first()
    )

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
    activity = (
        await db.execute(select(Activity).where(Activity.id == activity_id))
    ).scalar_one_or_none()
    if activity is None:
        # RPE is a Strava-only feature in v1 — the ``rpe`` / ``user_notes``
        # columns live on ``activities`` and the Apple side has no
        # equivalent. If the id resolves to an Apple Health workout
        # instead, refuse explicitly so the frontend can render a "not
        # supported" hint rather than swallow a 404.
        is_apple = (
            await db.execute(
                select(HealthDataPoint).where(
                    HealthDataPoint.id == activity_id,
                    HealthDataPoint.source == "apple_health",
                    HealthDataPoint.data_type == "workout",
                )
            )
        ).scalar_one_or_none()
        if is_apple is not None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "RPE / notes are not supported for apple_health "
                    "workouts in v1"
                ),
            )
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


@router.patch("/{activity_id}/shoe")
async def patch_activity_shoe(
    activity_id: int,
    payload: ActivityShoePatch,
    source: str | None = Query(
        None,
        description=(
            "Disambiguate Strava vs Apple Health when the integer ids "
            "collide. ``strava`` forces the Strava ``Activity`` row, "
            "``apple_health`` forces the Apple ``Workout`` row. When "
            "omitted, retains the legacy Strava-first / Apple-fallback "
            "resolution for back-compat with older clients."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """Tag or untag a running shoe on an activity / workout.

    Resolves ``activity_id`` honoring ``?source=`` exactly like
    ``GET /{activity_id}``: ``apple_health`` skips the ``Activity``
    lookup and writes ``Workout.shoe_id`` directly; ``strava`` writes
    ``Activity.shoe_id`` and does NOT fall through to Apple on miss.
    When ``source`` is omitted, the legacy Strava-first / Apple-fallback
    behavior is preserved so older clients keep working.

    Rejects tagging a retired shoe with a 400; untagging
    (``shoe_id=null``) is always allowed.
    """
    if source is not None and source not in ("strava", "apple_health"):
        raise HTTPException(
            status_code=400,
            detail="source must be 'strava' or 'apple_health'",
        )

    new_shoe_id = payload.shoe_id

    # Validate the target shoe up front so both branches share the
    # same error path.
    if new_shoe_id is not None:
        shoe = (
            await db.execute(select(Shoe).where(Shoe.id == new_shoe_id))
        ).scalar_one_or_none()
        if shoe is None:
            raise HTTPException(status_code=400, detail="Shoe not found")
        if shoe.status == "retired":
            raise HTTPException(
                status_code=400, detail="Cannot tag a retired shoe"
            )

    if source == "apple_health":
        # Explicit Apple intent — skip the ``Activity`` lookup entirely
        # so a colliding Strava row at the same numeric id cannot
        # absorb the write.
        return await _patch_apple_workout_shoe(db, activity_id, new_shoe_id)

    activity = (
        await db.execute(select(Activity).where(Activity.id == activity_id))
    ).scalar_one_or_none()
    if activity is not None:
        activity.shoe_id = new_shoe_id
        await db.commit()
        await db.refresh(activity)
        return {
            "id": activity.id,
            "source": "strava",
            "shoe_id": activity.shoe_id,
        }

    if source == "strava":
        # Explicit Strava intent — do not fall through to Apple.
        raise HTTPException(status_code=404, detail="Activity not found")

    # Legacy / source-less call: fall through to Apple Health workout.
    return await _patch_apple_workout_shoe(db, activity_id, new_shoe_id)


async def _patch_apple_workout_shoe(
    db: AsyncSession, activity_id: int, new_shoe_id: int | None
) -> dict:
    """Write ``shoe_id`` to the Apple ``Workout`` row at ``activity_id``.

    Mirrors the feedback endpoint's lookup: HDP with
    ``source='apple_health'`` and ``data_type='workout'``, then load the
    joined ``Workout`` row. 404 if either is missing.
    """
    dp = (
        await db.execute(
            select(HealthDataPoint).where(
                HealthDataPoint.id == activity_id,
                HealthDataPoint.source == "apple_health",
                HealthDataPoint.data_type == "workout",
            )
        )
    ).scalar_one_or_none()
    if dp is None:
        raise HTTPException(status_code=404, detail="Activity not found")
    workout = (
        await db.execute(select(Workout).where(Workout.id == dp.id))
    ).scalar_one_or_none()
    if workout is None:
        # An HDP without a joined Workout row is a data-integrity bug,
        # not a user-visible 4xx. Surface as 404 rather than 500 — the
        # caller can't recover either way.
        raise HTTPException(status_code=404, detail="Activity not found")
    workout.shoe_id = new_shoe_id
    await db.commit()
    await db.refresh(workout)
    return {
        "id": dp.id,
        "source": "apple_health",
        "shoe_id": workout.shoe_id,
    }


@router.post("/{activity_id}/classify")
async def classify_activity(activity_id: int, db: AsyncSession = Depends(get_db)):
    """(Re-)run the classifier on this activity and persist the result.

    Useful for debugging classifier changes without touching enrichment.
    """
    from backend.services.classifier import classify_and_persist, dump

    activity = (
        await db.execute(select(Activity).where(Activity.id == activity_id))
    ).scalar_one_or_none()
    if not activity:
        # Apple-resolved ids surface a soft no-op response — classifier
        # is a rules engine for Strava-shaped activities and has no
        # equivalent input from HAE. Returning HTTP 200 lets the caller
        # treat this as "nothing to do" rather than a hard failure.
        is_apple = (
            await db.execute(
                select(HealthDataPoint).where(
                    HealthDataPoint.id == activity_id,
                    HealthDataPoint.source == "apple_health",
                    HealthDataPoint.data_type == "workout",
                )
            )
        ).scalar_one_or_none()
        if is_apple is not None:
            return {
                "classified": False,
                "reason": "apple_health workouts are not classified yet",
            }
        raise HTTPException(status_code=404, detail="Activity not found")

    laps = (
        (
            await db.execute(
                select(ActivityLap)
                .where(ActivityLap.activity_id == activity_id)
                .order_by(ActivityLap.lap_index)
            )
        )
        .scalars()
        .all()
    )

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
    activity = (
        await db.execute(select(Activity).where(Activity.id == activity_id))
    ).scalar_one_or_none()
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")

    snapshot = (
        await db.execute(select(WeatherSnapshot).where(WeatherSnapshot.activity_id == activity_id))
    ).scalar_one_or_none()
    if not snapshot:
        raise HTTPException(status_code=404, detail="No weather snapshot for this activity")

    return _weather_full_dict(snapshot, include_raw=raw)


@router.get("/{activity_id}/streams")
async def get_activity_streams(
    activity_id: int,
    source: str | None = Query(
        None,
        description=(
            "Disambiguate Strava vs Apple Health when the integer ids "
            "collide. ``strava`` forces the Strava row, ``apple_health`` "
            "forces the Apple HealthDataPoint row. When omitted, retains "
            "the legacy Strava-first / Apple-fallback resolution."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """Get per-sample streams for an activity. Lazy-fetched from Strava.

    First call for a given Strava activity pulls streams from Strava and
    caches them in ``activity_streams``. Subsequent calls return the
    cached data.

    Apple Health ids resolve through ``raw_payload`` instead — HR comes
    from ``heartRateData``; ``velocity_smooth`` is added only when HAE
    ships per-sample speed in the ``route`` array. No Strava call is
    made for Apple ids, ever.

    The ``activity_id`` lives in the same shared integer id space as
    ``GET /{activity_id}``; pass ``source=apple_health`` or
    ``source=strava`` to disambiguate explicitly when colliding ids
    exist across the two tables. Without ``source``, Strava wins on
    collisions for backward compatibility.

    Stream load itself is delegated to
    ``backend.services.strava_streams.load_streams_for_activity`` so the
    strength-link service can share the same lazy-fetch + cache path.
    """
    if source is not None and source not in ("strava", "apple_health"):
        raise HTTPException(
            status_code=400,
            detail="source must be 'strava' or 'apple_health'",
        )

    if source == "apple_health":
        apple_streams = await _maybe_apple_streams(db, activity_id)
        if apple_streams is None:
            raise HTTPException(status_code=404, detail="Activity not found")
        return apple_streams

    from backend.services.strava_streams import (
        StravaStreamFetchError,
        load_streams_for_activity,
    )

    activity = (
        await db.execute(select(Activity).where(Activity.id == activity_id))
    ).scalar_one_or_none()
    if not activity:
        if source == "strava":
            # Explicit Strava intent — do not fall through to Apple.
            raise HTTPException(status_code=404, detail="Activity not found")
        apple_streams = await _maybe_apple_streams(db, activity_id)
        if apple_streams is not None:
            return apple_streams
        raise HTTPException(status_code=404, detail="Activity not found")

    try:
        return await load_streams_for_activity(db, activity)
    except StravaStreamFetchError as e:
        logger.warning(f"Streams fetch failed for activity {activity_id}: {e}")
        raise HTTPException(
            status_code=502, detail=f"Strava streams fetch failed: {e}"
        )


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
        "source": a.source or "strava",
        "external_id": a.external_id,
        "superseded_by_id": a.superseded_by_id,
        "shoe_id": a.shoe_id,
    }


def _apple_workout_summary(workout: Workout, dp: HealthDataPoint) -> dict:
    """Map an Apple-only ``Workout`` onto the ``ActivitySummary`` shape.

    Frontend consumers treat ``source == "apple_health"`` as the cue
    that Strava-specific fields (``strava_id``, zones, power, etc.) are
    intentionally absent.
    """
    from backend.services.sport_mapping import normalized_to_strava_view

    return {
        # Use the health_data_points.id as the ``id`` — there's no
        # Strava row to point at, and HDP is the polymorphic anchor.
        "id": dp.id,
        "strava_id": None,
        "name": (dp.raw_payload or {}).get("name") or workout.activity_type,
        # Emit the CamelCase Strava-style label the frontend's
        # ``classifyActivity`` helper (frontend/src/lib/historyEvents.ts)
        # uses to drive the Run/Ride/Strength view switch. Apple stores
        # the normalized lowercase form ("run", "ride", "strength") —
        # the frontend's switch doesn't match those, so the detail page
        # would fall through to the generic view. ``classifyActivity``
        # also accepts lowercase in the history feed, so this is a safe
        # widening, not a breaking change.
        "sport_type": normalized_to_strava_view(workout.activity_type),
        "start_date": dp.start_time.isoformat() if dp.start_time else None,
        # HealthDataPoint stores only a UTC ``start_time``; HAE does not
        # surface a separate local-time field. Pass the UTC value through
        # so the frontend's ``formatActivityDateTime`` can render a date
        # subtitle (it formats in the viewer's local TZ, which is the
        # right behavior for a single-user app). Without this the
        # subtitle was rendering blank.
        "start_date_local": dp.start_time.isoformat() if dp.start_time else None,
        "elapsed_time": workout.duration_s,
        "moving_time": workout.duration_s,
        "distance": workout.distance_m,
        "total_elevation": workout.total_elevation_m,
        "average_hr": workout.avg_hr,
        "max_hr": workout.max_hr,
        "average_speed": workout.avg_speed_mps,
        "max_speed": None,
        "average_power": None,
        "max_power": None,
        "weighted_avg_power": None,
        "average_cadence": None,
        "calories": workout.active_energy_kcal,
        "kilojoules": None,
        "suffer_score": None,
        "device_watts": None,
        "workout_type": None,
        "available_zones": None,
        # Apple-Health-sourced rows are never enriched through the
        # Strava Phase-B path, but the frontend renders any
        # ``enrichment_status`` value other than ``"complete"`` as a raw
        # status pill (see ``ActivityHeader.tsx``). The badge already
        # carries the "Apple Health" source label, so we report
        # ``"complete"`` here — there is no further server-side
        # enrichment to do for Apple workouts in v1 (no Strava-style
        # stream enrichment, no classifier pass).
        "enrichment_status": "complete",
        "enriched_at": None,
        "classification_type": None,
        "classification_flags": None,
        "classified_at": None,
        "weather_enriched": False,
        "elev_high_m": None,
        "elev_low_m": None,
        "base_elevation_m": None,
        "elevation_enriched": False,
        "location_id": None,
        "start_lat": None,
        "start_lng": None,
        "rpe": None,
        "user_notes": None,
        "rated_at": None,
        "source": "apple_health",
        "external_id": dp.external_id,
        "superseded_by_id": dp.superseded_by_id,
        "shoe_id": workout.shoe_id,
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


async def _maybe_apple_streams(
    db: AsyncSession, activity_id: int
) -> dict | None:
    """Reconstruct an Apple workout's streams from its HAE ``raw_payload``.

    Returns ``None`` if the id isn't an Apple workout (the caller will
    then 404). Returns an empty dict when the workout exists but has
    no usable series — matching the frontend's "degrade gracefully"
    expectation. Otherwise returns ``{"heartrate": [...], "time": [...]}``
    plus an optional ``"velocity_smooth"`` series when HAE ships per-
    sample speed in ``route``.
    """
    from datetime import datetime as _datetime

    row = (
        await db.execute(
            select(HealthDataPoint).where(
                HealthDataPoint.id == activity_id,
                HealthDataPoint.source == "apple_health",
                HealthDataPoint.data_type == "workout",
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None

    payload = row.raw_payload or {}
    streams: dict[str, list] = {}

    # HR series — HAE emits per-minute or per-second entries shaped
    # ``{"date": "...", "qty": <bpm>, "units": "count/min"}``. We
    # convert ``date`` into seconds-since-first-sample to populate a
    # parallel ``time`` array. Falls back to a 0..N index when dates
    # are unparseable so the chart can still render.
    #
    # HAE also emits a scalar shape ``{"qty": <bpm>, "units": "count/min"}``
    # when "Aggregate workout data" is enabled — surface that as a single
    # sample at ``time=0`` so the chart can render at least one point
    # rather than silently dropping the series. Parity with
    # ``derive_hr_samples_from_raw_payload`` in ``backend/services/hr_zones.py``.
    hr_series = payload.get("heartRateData")
    if isinstance(hr_series, dict):
        qty = hr_series.get("qty")
        if qty is not None:
            try:
                streams["heartrate"] = [float(qty)]
                streams["time"] = [0.0]
            except (TypeError, ValueError):
                pass
    elif isinstance(hr_series, list) and hr_series:
        hr_values: list[float] = []
        time_values: list[float] = []
        base_ts: float | None = None
        for i, entry in enumerate(hr_series):
            if not isinstance(entry, dict):
                continue
            qty = entry.get("qty")
            if qty is None:
                continue
            try:
                hr_values.append(float(qty))
            except (TypeError, ValueError):
                continue
            ts: float | None = None
            date_raw = entry.get("date")
            if isinstance(date_raw, str):
                try:
                    parsed = _datetime.strptime(date_raw, "%Y-%m-%d %H:%M:%S %z")
                    ts = parsed.timestamp()
                except ValueError:
                    ts = None
            if ts is not None:
                if base_ts is None:
                    base_ts = ts
                time_values.append(ts - base_ts)
            else:
                time_values.append(float(i))
        if hr_values:
            streams["heartrate"] = hr_values
            streams["time"] = time_values

    # Velocity — only when HAE actually ships a per-sample speed field.
    # The tests-of-record (``test_apple_health_parser.py``) carry routes
    # as ``[{"lat", "lon"}]`` with no speed; the HAE export ships a
    # ``speed`` key per point when the user enables it.
    route = payload.get("route")
    if isinstance(route, list) and route:
        velocities: list[float] = []
        for entry in route:
            if not isinstance(entry, dict):
                continue
            speed = entry.get("speed")
            if speed is None:
                continue
            try:
                velocities.append(float(speed))
            except (TypeError, ValueError):
                continue
        if velocities:
            streams["velocity_smooth"] = velocities

    return streams


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
