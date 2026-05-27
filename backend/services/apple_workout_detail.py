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

from typing import Literal

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

# Bucket sizes for request-time re-binning (meters). The metric values
# mirror ``apple_health_ingest._SPLIT_METERS`` so the persisted laps and
# the metric re-binning agree exactly; the imperial values are mile /
# block-of-five-miles equivalents.
_SPLIT_METERS_METRIC: dict[str, float] = {
    "run": 1000.0,
    "walk": 1000.0,
    "hike": 1000.0,
    "ride": 5000.0,
    "swim": 100.0,
}
_SPLIT_METERS_IMPERIAL: dict[str, float] = {
    "run": 1609.344,
    "walk": 1609.344,
    "hike": 1609.344,
    "ride": 8046.72,  # 5 miles
    # Swim splits stay at 100 (yard ≈ meter for UI purposes).
    "swim": 100.0,
}


async def get_apple_workout_detail(
    db: AsyncSession,
    hdp_id: int,
    *,
    units: Literal["metric", "imperial"] = "metric",
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

    ``units`` controls the lap bucket size used when re-binning the
    synthetic splits. ``"metric"`` (default) returns the persisted
    ``WorkoutLap`` rows verbatim — they were generated with km buckets
    by ``apple_health_ingest._derive_laps``. ``"imperial"`` re-bins the
    laps at request time using mile-sized buckets (1609.344 m for
    run/walk/hike, 8046.72 m for ride). Swim stays at the 100 m bucket
    in both modes. The DB stays metric; only the response changes.
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
    # relationship's order_by. For imperial we re-bin from the workout
    # totals using mile-sized buckets; metric returns the persisted
    # km-bucket rows verbatim.
    if units == "imperial" and workout.laps:
        rebinned = _rebin_laps_for_units(
            total_distance_m=workout.distance_m,
            total_duration_s=workout.duration_s,
            total_elev_gain_m=workout.total_elevation_m,
            activity_type=workout.activity_type,
            units=units,
        )
        # Fall back to the persisted laps if the totals couldn't be
        # re-binned (e.g. unknown sport, missing distance/duration).
        detail["laps"] = (
            rebinned
            if rebinned is not None
            else [_workout_lap_dict(lap) for lap in workout.laps]
        )
    else:
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


def _rebin_laps_for_units(
    *,
    total_distance_m: float | None,
    total_duration_s: int | None,
    total_elev_gain_m: float | None,
    activity_type: str,
    units: Literal["metric", "imperial"],
) -> list[dict] | None:
    """Re-bin synthetic laps from the workout totals for ``units``.

    Mirrors the math in ``apple_health_ingest._derive_laps`` (distance
    bucketed into ``_SPLIT_METERS[sport]`` chunks, time / elevation
    distributed proportionally) but uses an imperial bucket table when
    ``units="imperial"``. Returns ``None`` when the workout can't be
    split (unknown sport, missing distance / duration, zero totals);
    the caller falls back to the persisted lap rows.

    Per-lap HR is ``None`` because we don't slice the HR stream per
    bucket here — this matches the persisted-lap behavior.
    """
    table = (
        _SPLIT_METERS_IMPERIAL if units == "imperial" else _SPLIT_METERS_METRIC
    )
    split_m = table.get(activity_type)
    if (
        split_m is None
        or total_distance_m is None
        or total_distance_m <= 0
        or total_duration_s is None
        or total_duration_s <= 0
    ):
        return None

    total_distance = float(total_distance_m)
    total_seconds = float(total_duration_s)
    n_full = int(total_distance // split_m)
    remainder = total_distance - n_full * split_m

    # Per-meter time / elevation so partial-final laps share the same
    # pace and the same proportional elev gain.
    seconds_per_meter = total_seconds / total_distance
    elev_total = float(total_elev_gain_m) if total_elev_gain_m else 0.0
    elev_per_meter = (elev_total / total_distance) if total_distance > 0 else 0.0

    laps: list[dict] = []

    for i in range(n_full):
        lap_seconds = split_m * seconds_per_meter
        laps.append(
            {
                "lap_index": i,
                "name": f"Split {i + 1}",
                "elapsed_time": int(round(lap_seconds)),
                "moving_time": int(round(lap_seconds)),
                "distance": split_m,
                "start_date": None,
                "average_speed": split_m / lap_seconds if lap_seconds > 0 else None,
                "max_speed": None,
                "average_heartrate": None,
                "max_heartrate": None,
                "average_cadence": None,
                "average_watts": None,
                "total_elevation_gain": (
                    elev_per_meter * split_m if elev_total else None
                ),
                "pace_zone": None,
                "hr_zone": None,
                "split": i + 1,
                "start_index": None,
                "end_index": None,
            }
        )

    if remainder > 0.5:  # ignore sub-meter rounding artifacts
        lap_seconds = remainder * seconds_per_meter
        laps.append(
            {
                "lap_index": n_full,
                "name": f"Split {n_full + 1}",
                "elapsed_time": int(round(lap_seconds)),
                "moving_time": int(round(lap_seconds)),
                "distance": remainder,
                "start_date": None,
                "average_speed": (
                    remainder / lap_seconds if lap_seconds > 0 else None
                ),
                "max_speed": None,
                "average_heartrate": None,
                "max_heartrate": None,
                "average_cadence": None,
                "average_watts": None,
                "total_elevation_gain": (
                    elev_per_meter * remainder if elev_total else None
                ),
                "pace_zone": None,
                "hr_zone": None,
                "split": n_full + 1,
                "start_index": None,
                "end_index": None,
            }
        )

    return laps


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


