"""Apple Health (HAE) workout ingest.

Owns the upsert flow for an HAE batch:

1. For each workout in the batch:
   a. Look up the backing ``HealthDataPoint`` by
      ``(source='apple_health', data_type='workout', external_id=...)``.
   b. Insert or update the polymorphic row and its typed
      ``Workout`` child.
   c. Replace ``WorkoutLap`` rows wholesale (no in-place merge) — HAE
      doesn't ship lap markers, so laps are derived server-side via
      simple time/distance splits.
   d. Run cross-source dedup (Apple wins over a same-window Strava
      activity).
2. Commit once at the end.

The result list is what the webhook returns to HAE, one entry per
workout: ``{"external_id", "workout_id", "dedup_matched_activity_id",
"lap_count", "status"}`` where ``status`` is ``"created"`` or
``"updated"``.
"""
from __future__ import annotations

import logging
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import HealthDataPoint, Workout, WorkoutLap
from backend.services import workout_dedup
from backend.services.apple_health_parser import (
    HAEBatch,
    ParsedWorkout,
    flatten_hae_workout,
)

logger = logging.getLogger(__name__)

# Distance-based split thresholds (meters). Time-based laps are derived
# proportionally from the workout's total duration / distance.
_SPLIT_METERS: dict[str, float] = {
    "run": 1000.0,
    "walk": 1000.0,
    "hike": 1000.0,
    "ride": 5000.0,
    "swim": 100.0,
}


class IngestResult(TypedDict):
    external_id: str
    workout_id: int | None
    dedup_matched_activity_id: int | None
    lap_count: int
    status: str  # "created" | "updated" | "error"
    error: str | None


async def ingest_workouts(db: AsyncSession, batch: HAEBatch) -> list[IngestResult]:
    """Process an HAE batch end-to-end. Commits once at the end.

    Per-workout failures are captured in the result list (``status:
    "error"``) so a single bad row doesn't take down a multi-workout
    batch.
    """
    results: list[IngestResult] = []

    for hae in batch.data.workouts:
        try:
            parsed = flatten_hae_workout(hae)
        except Exception as exc:  # noqa: BLE001 — surfaced in result
            logger.warning("HAE workout %s failed to parse: %s", hae.id, exc)
            results.append(
                IngestResult(
                    external_id=hae.id,
                    workout_id=None,
                    dedup_matched_activity_id=None,
                    lap_count=0,
                    status="error",
                    error=str(exc),
                )
            )
            continue

        try:
            result = await _upsert_one(db, parsed)
        except Exception as exc:  # noqa: BLE001
            logger.exception("HAE workout %s failed to upsert", hae.id)
            results.append(
                IngestResult(
                    external_id=hae.id,
                    workout_id=None,
                    dedup_matched_activity_id=None,
                    lap_count=0,
                    status="error",
                    error=str(exc),
                )
            )
            continue

        results.append(result)

    await db.commit()
    return results


async def _upsert_one(db: AsyncSession, parsed: ParsedWorkout) -> IngestResult:
    """Upsert a single parsed workout. No commit — caller batches."""
    existing_dp = (
        await db.execute(
            select(HealthDataPoint).where(
                HealthDataPoint.source == "apple_health",
                HealthDataPoint.data_type == "workout",
                HealthDataPoint.external_id == parsed.external_id,
            )
        )
    ).scalar_one_or_none()

    status = "updated" if existing_dp is not None else "created"

    if existing_dp is None:
        data_point = HealthDataPoint(
            source="apple_health",
            data_type="workout",
            external_id=parsed.external_id,
            start_time=parsed.start_time,
            end_time=parsed.end_time,
            raw_payload=parsed.raw_payload,
        )
        db.add(data_point)
        await db.flush()  # populate data_point.id

        workout = Workout(
            id=data_point.id,
            activity_type=parsed.activity_type,
            duration_s=parsed.duration_s,
            active_energy_kcal=parsed.active_energy_kcal,
            distance_m=parsed.distance_m,
            avg_speed_mps=parsed.avg_speed_mps,
            avg_hr=parsed.avg_hr,
            max_hr=parsed.max_hr,
            total_elevation_m=parsed.total_elevation_m,
        )
        db.add(workout)
        await db.flush()
        # Re-attach the relationship so dedup can read workout.data_point.
        workout.data_point = data_point
    else:
        data_point = existing_dp
        data_point.start_time = parsed.start_time
        data_point.end_time = parsed.end_time
        data_point.raw_payload = parsed.raw_payload

        workout = (
            await db.execute(select(Workout).where(Workout.id == data_point.id))
        ).scalar_one_or_none()
        if workout is None:
            # Edge case: parent existed without a child. Create one.
            workout = Workout(id=data_point.id, activity_type=parsed.activity_type)
            db.add(workout)
            await db.flush()
        workout.activity_type = parsed.activity_type
        workout.duration_s = parsed.duration_s
        workout.active_energy_kcal = parsed.active_energy_kcal
        workout.distance_m = parsed.distance_m
        workout.avg_speed_mps = parsed.avg_speed_mps
        workout.avg_hr = parsed.avg_hr
        workout.max_hr = parsed.max_hr
        workout.total_elevation_m = parsed.total_elevation_m
        workout.data_point = data_point

    # Replace laps wholesale — HAE re-posts are full replays, not deltas.
    laps = _derive_laps(parsed)
    if existing_dp is not None:
        existing_laps = (
            await db.execute(
                select(WorkoutLap).where(WorkoutLap.workout_id == workout.id)
            )
        ).scalars().all()
        for lap in existing_laps:
            await db.delete(lap)
        await db.flush()

    for lap in laps:
        lap.workout_id = workout.id
        db.add(lap)

    # Dedup: Apple wins over Strava in the ±10-min window.
    matched_activity = await workout_dedup.match_apple_against_strava(db, workout)

    await db.flush()

    return IngestResult(
        external_id=parsed.external_id,
        workout_id=workout.id,
        dedup_matched_activity_id=matched_activity.id if matched_activity else None,
        lap_count=len(laps),
        status=status,
        error=None,
    )


def _derive_laps(parsed: ParsedWorkout) -> list[WorkoutLap]:
    """Build evenly-spaced laps from total distance/duration.

    HAE doesn't expose ``HKWorkoutEvent`` lap markers, so we synthesize
    laps from the totals: split distance into ``_SPLIT_METERS[sport]``
    chunks and divide elapsed time proportionally. Falls back to no
    laps when the sport isn't in the table or distance is missing.
    """
    split_m = _SPLIT_METERS.get(parsed.activity_type)
    if (
        split_m is None
        or parsed.distance_m is None
        or parsed.distance_m <= 0
        or parsed.duration_s is None
        or parsed.duration_s <= 0
    ):
        return []

    total_distance = float(parsed.distance_m)
    total_seconds = float(parsed.duration_s)
    n_full = int(total_distance // split_m)
    remainder = total_distance - n_full * split_m

    laps: list[WorkoutLap] = []
    # Per-meter time so partial-final laps share the same pace.
    seconds_per_meter = total_seconds / total_distance

    for i in range(n_full):
        lap_seconds = split_m * seconds_per_meter
        laps.append(
            WorkoutLap(
                lap_index=i,
                name=f"Split {i + 1}",
                elapsed_time_s=int(round(lap_seconds)),
                moving_time_s=int(round(lap_seconds)),
                distance_m=split_m,
                avg_speed_mps=(
                    parsed.avg_speed_mps
                    if parsed.avg_speed_mps is not None
                    else split_m / lap_seconds
                ),
                split=i + 1,
            )
        )

    if remainder > 0.5:  # ignore sub-meter rounding artifacts
        lap_seconds = remainder * seconds_per_meter
        laps.append(
            WorkoutLap(
                lap_index=n_full,
                name=f"Split {n_full + 1}",
                elapsed_time_s=int(round(lap_seconds)),
                moving_time_s=int(round(lap_seconds)),
                distance_m=remainder,
                avg_speed_mps=(
                    parsed.avg_speed_mps
                    if parsed.avg_speed_mps is not None
                    else remainder / lap_seconds
                ),
                split=n_full + 1,
            )
        )

    return laps
