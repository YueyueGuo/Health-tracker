"""Apple-Health workout detail builder.

Mirrors :func:`backend.routers.activities._activity_summary` for the
Apple side. Given a ``health_data_points.id`` that resolves to an
Apple-Health workout row, hydrate the full detail-page dict — same
shape as the Strava detail endpoint plus a couple of flags
(``zones_synthetic`` / ``splits_synthetic``) so the frontend can
disclose that the bucket histogram and lap markers are computed, not
sensor-based.

This module is the only place that knows about the Apple-side data
shape. The router stays thin and delegates here on a Strava lookup
miss.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models import (
    HealthDataPoint,
    WeatherSnapshot,
    Workout,
    WorkoutLap,
)
from backend.services.hr_zones import (
    derive_hr_samples_from_raw_payload,
    synthesize_hr_zones_from_samples,
)


async def get_apple_workout_detail(
    db: AsyncSession, hdp_id: int
) -> dict | None:
    """Return the detail-page dict for an Apple workout, or ``None``.

    ``hdp_id`` is a ``health_data_points.id``. We resolve it through
    the joined-table inheritance (``Workout.id == HealthDataPoint.id``)
    and bail if the row isn't an Apple workout.

    The returned dict has the same keys ``_activity_summary`` returns
    (so the frontend's ``ActivityDetail`` typing keeps working) plus:

    * ``laps`` — ``WorkoutLap`` rows mapped onto the ``ActivityLap``
      shape (HR / power columns are ``None`` because HAE-derived laps
      don't carry per-lap sensor data).
    * ``zones`` — ``zones_data``-shaped HR bucket list synthesized from
      raw ``heartRateData`` samples, or ``None`` when no usable series.
    * ``weather`` — populated only when the workout has won dedup
      against a Strava activity that already enriched its
      ``WeatherSnapshot``.
    * ``streams_cached`` — always True for Apple (the series rides in
      ``raw_payload`` and is always available without a Strava fetch).
    * ``hr_drift`` / ``pace_hr_decoupling`` / ``power_hr_decoupling`` —
      None for v1; Apple drift is a follow-up because the existing
      compute_* helpers read ``activity_streams`` keyed on Strava IDs.
    * ``raw_data`` — None (we don't expose the full HAE payload here).
    * ``zones_synthetic`` / ``splits_synthetic`` — flags the frontend
      uses to disclose "computed from raw HR samples" / "auto-split"
      captions.
    """
    # The router calls this with the dp id; pull both rows in one go via
    # the inheritance join. Eager-load laps so the merge stays in one
    # round-trip.
    stmt = (
        select(Workout, HealthDataPoint)
        .join(HealthDataPoint, Workout.id == HealthDataPoint.id)
        .where(
            HealthDataPoint.id == hdp_id,
            HealthDataPoint.source == "apple_health",
            HealthDataPoint.data_type == "workout",
        )
        .options(selectinload(Workout.laps))
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        return None
    workout, dp = row

    # Reuse the existing list-shape mapper so the detail surface stays
    # bit-for-bit aligned with the list surface.
    from backend.routers.activities import _apple_workout_summary

    detail = _apple_workout_summary(workout, dp)

    # Laps — Workout.laps is already ordered by lap_index via the
    # relationship's order_by.
    detail["laps"] = [_workout_lap_dict(lap) for lap in workout.laps]

    # Zones — only synthesize when we actually have a series. HAE may
    # ship a scalar avg-HR, which is fine to surface but useless as a
    # histogram, so we treat single-sample lists as "no series" for the
    # purposes of zone synthesis.
    samples = derive_hr_samples_from_raw_payload(dp.raw_payload)
    profile_max_hr, profile_lthr = await _load_profile_hr_limits(db)
    if samples and len(samples) > 1 and profile_max_hr:
        detail["zones"] = [
            synthesize_hr_zones_from_samples(
                samples, max_hr=profile_max_hr, lthr=profile_lthr
            )
        ]
        if detail["zones"][0] is None:
            detail["zones"] = None
    else:
        detail["zones"] = None

    # Weather — only when an Apple-wins-dedup row has a Strava back-link
    # that already has an enriched WeatherSnapshot.
    detail["weather"] = await _maybe_weather_for_apple(db, workout)

    # Streams ride in raw_payload — the GET /{id}/streams endpoint will
    # reconstruct them on demand. From the detail-page perspective the
    # series is "cached".
    detail["streams_cached"] = bool(samples)

    detail["hr_drift"] = None
    detail["pace_hr_decoupling"] = None
    detail["power_hr_decoupling"] = None
    detail["raw_data"] = None

    detail["zones_synthetic"] = detail["zones"] is not None
    detail["splits_synthetic"] = bool(workout.laps)

    return detail


def _workout_lap_dict(lap: WorkoutLap) -> dict:
    """Map a ``WorkoutLap`` onto the ``ActivityLap`` JSON shape.

    HAE-derived laps lack per-lap HR / power, so the corresponding
    fields are ``None`` rather than synthesized. Field names match the
    Strava ``_lap_dict`` keys so the frontend doesn't branch on source.
    """
    return {
        "lap_index": lap.lap_index,
        "name": lap.name,
        "elapsed_time": lap.elapsed_time_s,
        "moving_time": lap.moving_time_s,
        "distance": lap.distance_m,
        "start_date": lap.start_time.isoformat() if lap.start_time else None,
        "average_speed": lap.avg_speed_mps,
        "max_speed": lap.max_speed_mps,
        "average_heartrate": lap.avg_hr,
        "max_heartrate": lap.max_hr,
        "average_cadence": lap.avg_cadence,
        "average_watts": None,
        "total_elevation_gain": lap.total_elevation_m,
        "pace_zone": None,
        "hr_zone": None,
        "split": lap.split,
        "start_index": None,
        "end_index": None,
    }


async def _maybe_weather_for_apple(
    db: AsyncSession, workout: Workout
) -> dict | None:
    """Pull the linked Strava activity's weather snapshot, if any.

    Apple-only workouts (``activity_id IS NULL``) have no weather. When
    Apple won dedup, ``activity_id`` points at the Strava row we
    superseded; its ``WeatherSnapshot`` (if enriched) is the right one
    to surface.
    """
    if workout.activity_id is None:
        return None
    # Importing the existing mapper keeps the JSON shape in one place.
    from backend.routers.activities import _weather_dict

    snapshot = (
        await db.execute(
            select(WeatherSnapshot).where(
                WeatherSnapshot.activity_id == workout.activity_id
            )
        )
    ).scalar_one_or_none()
    if snapshot is None:
        return None
    return _weather_dict(snapshot)


async def _load_profile_hr_limits(
    db: AsyncSession,
) -> tuple[int | None, int | None]:
    """Read ``maxHr`` / ``lthr`` from the single-user ``user_profile`` row.

    Returns ``(max_hr, lthr)`` as ints, with ``None`` for missing
    fields. The profile schema is single-row (single-user app); we
    pluck the first row regardless of user id.
    """
    # Import lazily — ``UserProfile`` is imported through models/__init__,
    # but we avoid loading the model at module import time so this
    # service stays test-fixture friendly.
    from backend.models import UserProfile

    profile = (await db.execute(select(UserProfile))).scalar_one_or_none()
    if profile is None or not isinstance(profile.payload, dict):
        return None, None
    payload = profile.payload
    max_hr = _opt_int(payload.get("maxHr"))
    lthr = _opt_int(payload.get("lthr"))
    return max_hr, lthr


def _opt_int(v: object) -> int | None:
    """Coerce a profile field (string or number) to int, or return None."""
    if v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


