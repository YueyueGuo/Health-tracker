"""Tests for the HAE workout ingest service.

Covers:
* Upsert by ``(source, data_type, external_id)`` — second POST updates
  rather than duplicating.
* Lap derivation per sport (1 km runs, 5 km rides, 100 m swims,
  no laps for unmatched sports).
* Lap replacement on re-post (full wipe, no merge).
* Batch processing — per-workout errors don't abort the batch.
* Dedup hook fires and links the matched Strava activity.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models import Activity, HealthDataPoint, Workout, WorkoutLap
from backend.services.apple_health_ingest import ingest_workouts
from backend.services.apple_health_parser import HAEBatch


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


def _payload(
    *,
    external_id: str = "apple-1",
    name: str = "Running",
    distance_m: float | None = 5000.0,
    duration_s: float = 1800.0,
    avg_hr: float | None = 150.0,
    start: str = "2026-05-24 13:00:00 +0000",
    end: str = "2026-05-24 13:30:00 +0000",
) -> dict:
    w: dict = {
        "id": external_id,
        "name": name,
        "start": start,
        "end": end,
        "duration": duration_s,
    }
    if distance_m is not None:
        w["distance"] = {"qty": distance_m, "units": "m"}
    if avg_hr is not None:
        w["avgHeartRate"] = {"qty": avg_hr, "units": "count/min"}
    return {"data": {"workouts": [w]}}


# ── upsert / idempotency ────────────────────────────────────────────


async def test_first_post_creates_data_point_workout_and_laps(db):
    results = await ingest_workouts(
        db, HAEBatch.model_validate(_payload(distance_m=5000.0))
    )
    assert len(results) == 1
    assert results[0]["status"] == "created"
    assert results[0]["lap_count"] == 5  # 5 km @ 1 km splits

    dp = (await db.execute(select(HealthDataPoint))).scalar_one()
    workout = (await db.execute(select(Workout))).scalar_one()
    assert dp.source == "apple_health"
    assert dp.data_type == "workout"
    assert dp.external_id == "apple-1"
    assert workout.activity_type == "run"
    assert workout.distance_m == 5000.0
    laps = (await db.execute(select(WorkoutLap))).scalars().all()
    assert len(laps) == 5


async def test_replay_same_external_id_updates_in_place(db):
    # First POST — 5 km run.
    await ingest_workouts(
        db, HAEBatch.model_validate(_payload(distance_m=5000.0))
    )
    # Second POST with the same id but different distance.
    results = await ingest_workouts(
        db, HAEBatch.model_validate(_payload(distance_m=8000.0, duration_s=2700))
    )
    assert results[0]["status"] == "updated"

    # Still exactly one workout / hdp.
    assert len((await db.execute(select(HealthDataPoint))).scalars().all()) == 1
    workout = (await db.execute(select(Workout))).scalar_one()
    assert workout.distance_m == 8000.0
    # Laps fully replaced — 8 km @ 1 km splits = 8 laps.
    laps = (await db.execute(select(WorkoutLap))).scalars().all()
    assert len(laps) == 8


# ── lap derivation per sport ────────────────────────────────────────


async def test_run_uses_1km_splits(db):
    await ingest_workouts(
        db,
        HAEBatch.model_validate(_payload(name="Running", distance_m=3500.0)),
    )
    laps = (await db.execute(select(WorkoutLap).order_by(WorkoutLap.lap_index))).scalars().all()
    # 3 x 1 km full splits + a 500 m partial.
    assert len(laps) == 4
    assert laps[0].distance_m == 1000.0
    assert laps[3].distance_m == 500.0


async def test_ride_uses_5km_splits(db):
    await ingest_workouts(
        db,
        HAEBatch.model_validate(
            _payload(
                external_id="ride-1",
                name="Cycling",
                distance_m=22000.0,
                duration_s=3600.0,
            )
        ),
    )
    laps = (await db.execute(select(WorkoutLap).order_by(WorkoutLap.lap_index))).scalars().all()
    # 4 x 5 km + 2 km partial = 5 laps.
    assert len(laps) == 5
    assert laps[0].distance_m == 5000.0
    assert laps[-1].distance_m == 2000.0


async def test_swim_uses_100m_splits(db):
    await ingest_workouts(
        db,
        HAEBatch.model_validate(
            _payload(
                external_id="swim-1",
                name="Pool Swim",
                distance_m=550.0,
                duration_s=900.0,
            )
        ),
    )
    laps = (await db.execute(select(WorkoutLap))).scalars().all()
    # 5 x 100 m + 50 m partial.
    assert len(laps) == 6


async def test_yoga_produces_no_laps(db):
    # Yoga isn't in the split table → no laps.
    await ingest_workouts(
        db,
        HAEBatch.model_validate(
            _payload(
                external_id="yoga-1",
                name="Yoga",
                distance_m=None,
                duration_s=2700.0,
            )
        ),
    )
    laps = (await db.execute(select(WorkoutLap))).scalars().all()
    assert laps == []


async def test_run_without_distance_produces_no_laps(db):
    await ingest_workouts(
        db,
        HAEBatch.model_validate(
            _payload(external_id="run-no-dist", distance_m=None)
        ),
    )
    laps = (await db.execute(select(WorkoutLap))).scalars().all()
    assert laps == []


# ── batch / error handling ──────────────────────────────────────────


async def test_batch_processes_multiple_workouts(db):
    batch = {
        "data": {
            "workouts": [
                _payload(external_id="a")["data"]["workouts"][0],
                _payload(
                    external_id="b",
                    name="Cycling",
                    distance_m=10000.0,
                    duration_s=1800.0,
                    start="2026-05-25 13:00:00 +0000",
                    end="2026-05-25 13:30:00 +0000",
                )["data"]["workouts"][0],
            ]
        }
    }
    results = await ingest_workouts(db, HAEBatch.model_validate(batch))
    assert {r["external_id"] for r in results} == {"a", "b"}
    assert all(r["status"] == "created" for r in results)
    assert len((await db.execute(select(Workout))).scalars().all()) == 2


async def test_batch_continues_after_per_workout_error(db):
    """A bad-units workout fails its own slot but doesn't block the next."""
    batch = {
        "data": {
            "workouts": [
                {
                    "id": "bad-units",
                    "name": "Running",
                    "start": "2026-05-24 13:00:00 +0000",
                    "end": "2026-05-24 13:30:00 +0000",
                    "duration": 1800.0,
                    # Truly unknown unit — flatten raises.
                    "distance": {"qty": 5.0, "units": "parsec"},
                },
                _payload(external_id="ok")["data"]["workouts"][0],
            ]
        }
    }
    results = await ingest_workouts(db, HAEBatch.model_validate(batch))
    by_id = {r["external_id"]: r for r in results}
    assert by_id["bad-units"]["status"] == "error"
    assert by_id["bad-units"]["error"] is not None
    assert by_id["ok"]["status"] == "created"
    # Only the good one persisted.
    assert (await db.execute(select(HealthDataPoint))).scalars().all()
    assert len((await db.execute(select(Workout))).scalars().all()) == 1


# ── dedup hook ──────────────────────────────────────────────────────


async def test_ingest_dedups_against_existing_strava(db):
    start = datetime(2026, 5, 24, 13, 0, 0)
    strava = Activity(
        strava_id=999,
        name="Morning run",
        sport_type="Run",
        start_date=start,
        start_date_local=start,
        enrichment_status="complete",
    )
    db.add(strava)
    await db.commit()
    await db.refresh(strava)

    # Apple workout starts 4 minutes later — inside the ±10 min window.
    payload = _payload(
        external_id="apple-1",
        start=(start + timedelta(minutes=4)).strftime("%Y-%m-%d %H:%M:%S +0000"),
        end=(start + timedelta(minutes=34)).strftime("%Y-%m-%d %H:%M:%S +0000"),
    )
    results = await ingest_workouts(db, HAEBatch.model_validate(payload))

    assert results[0]["dedup_matched_activity_id"] == strava.id
    await db.refresh(strava)
    workout = (await db.execute(select(Workout))).scalar_one()
    assert workout.activity_id == strava.id
    assert strava.superseded_by_id == workout.id
