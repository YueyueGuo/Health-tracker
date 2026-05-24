"""Tests for the cross-source workout dedup service.

Apple wins over Strava in both directions; tests assert the
``superseded_by_id`` flip happens in window AND with the right
normalized sport, and never otherwise.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models import Activity, HealthDataPoint, Workout
from backend.services import workout_dedup


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


async def _seed_strava(
    db, *, sport_type: str, start: datetime, strava_id: int = 100
) -> Activity:
    a = Activity(
        strava_id=strava_id,
        name=f"{sport_type} workout",
        sport_type=sport_type,
        start_date=start,
        start_date_local=start,
        enrichment_status="complete",
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


async def _seed_apple(
    db,
    *,
    activity_type: str,
    start: datetime,
    external_id: str = "apple-xyz",
) -> tuple[Workout, HealthDataPoint]:
    dp = HealthDataPoint(
        source="apple_health",
        data_type="workout",
        external_id=external_id,
        start_time=start,
    )
    db.add(dp)
    await db.flush()
    w = Workout(id=dp.id, activity_type=activity_type, duration_s=1800)
    db.add(w)
    await db.commit()
    await db.refresh(w)
    await db.refresh(dp)
    w.data_point = dp
    return w, dp


# ── match_apple_against_strava ──────────────────────────────────────


async def test_apple_dedups_strava_inside_window_same_sport(db):
    start = datetime(2026, 5, 24, 13, 14, 0)
    strava = await _seed_strava(db, sport_type="Run", start=start)
    workout, dp = await _seed_apple(
        db,
        activity_type="run",
        start=start + timedelta(minutes=3),  # within ±10 min
    )

    matched = await workout_dedup.match_apple_against_strava(db, workout)
    await db.commit()
    await db.refresh(strava)
    await db.refresh(workout)

    assert matched is not None
    assert matched.id == strava.id
    assert strava.superseded_by_id == dp.id
    assert workout.activity_id == strava.id


async def test_apple_dedup_skips_outside_window(db):
    start = datetime(2026, 5, 24, 13, 14, 0)
    strava = await _seed_strava(db, sport_type="Run", start=start)
    workout, _ = await _seed_apple(
        db,
        activity_type="run",
        start=start + timedelta(minutes=20),  # outside window
    )

    matched = await workout_dedup.match_apple_against_strava(db, workout)
    await db.refresh(strava)
    assert matched is None
    assert strava.superseded_by_id is None


async def test_apple_dedup_skips_mismatched_sport(db):
    start = datetime(2026, 5, 24, 13, 14, 0)
    strava = await _seed_strava(db, sport_type="Ride", start=start)
    workout, _ = await _seed_apple(db, activity_type="run", start=start)

    matched = await workout_dedup.match_apple_against_strava(db, workout)
    await db.refresh(strava)
    assert matched is None
    assert strava.superseded_by_id is None


async def test_apple_dedup_ignores_already_superseded_strava(db):
    """A Strava row already pointed at *some* HDP shouldn't be re-pointed."""
    start = datetime(2026, 5, 24, 13, 14, 0)
    strava = await _seed_strava(db, sport_type="Run", start=start)
    strava.superseded_by_id = 9999  # pretend already deduped
    await db.commit()

    workout, _ = await _seed_apple(db, activity_type="run", start=start)
    matched = await workout_dedup.match_apple_against_strava(db, workout)
    assert matched is None
    await db.refresh(strava)
    assert strava.superseded_by_id == 9999  # untouched


async def test_apple_dedup_handles_workout_without_data_point(db):
    # Defensive: a Workout instance with no attached HDP should bail
    # quietly rather than crashing the ingest.
    orphan = Workout(id=1, activity_type="run")
    assert await workout_dedup.match_apple_against_strava(db, orphan) is None


# ── match_strava_against_apple ─────────────────────────────────────


async def test_strava_dedups_against_existing_apple_in_window(db):
    start = datetime(2026, 5, 24, 13, 14, 0)
    workout, dp = await _seed_apple(db, activity_type="run", start=start)
    strava = await _seed_strava(
        db, sport_type="TrailRun", start=start + timedelta(minutes=2)
    )

    matched = await workout_dedup.match_strava_against_apple(db, strava)
    await db.commit()
    await db.refresh(strava)
    await db.refresh(workout)

    assert matched is not None
    assert matched.id == workout.id
    assert strava.superseded_by_id == dp.id
    assert workout.activity_id == strava.id


async def test_strava_dedup_skips_outside_window(db):
    start = datetime(2026, 5, 24, 13, 14, 0)
    await _seed_apple(db, activity_type="run", start=start)
    strava = await _seed_strava(
        db, sport_type="Run", start=start + timedelta(minutes=30)
    )

    matched = await workout_dedup.match_strava_against_apple(db, strava)
    assert matched is None
    assert strava.superseded_by_id is None


async def test_strava_dedup_skips_mismatched_sport(db):
    start = datetime(2026, 5, 24, 13, 14, 0)
    await _seed_apple(db, activity_type="ride", start=start)
    strava = await _seed_strava(db, sport_type="Run", start=start)

    matched = await workout_dedup.match_strava_against_apple(db, strava)
    assert matched is None
    assert strava.superseded_by_id is None


async def test_strava_dedup_ignores_non_workout_data_points(db):
    """Other HealthDataPoint data_types (e.g. steps) must never match."""
    start = datetime(2026, 5, 24, 13, 14, 0)
    db.add(
        HealthDataPoint(
            source="apple_health",
            data_type="steps",  # not a workout
            external_id="step-1",
            start_time=start,
        )
    )
    await db.commit()
    strava = await _seed_strava(db, sport_type="Run", start=start)
    matched = await workout_dedup.match_strava_against_apple(db, strava)
    assert matched is None
