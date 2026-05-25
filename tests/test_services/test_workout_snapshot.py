"""Regression tests for ``backend.services.workout_snapshot``.

Covers the home-dashboard fix: the latest-workout snapshot must merge
Strava ``Activity`` rows with Apple Health ``HealthDataPoint`` /
``Workout`` rows and return whichever is newer. Before the fix, only
Strava rows were considered, so the Home card stayed pinned to the most
recent Strava activity even when a newer Apple Health workout existed.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models import Activity, HealthDataPoint, Workout
from backend.services.workout_snapshot import get_latest_workout_snapshot


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


def _make_strava(
    *,
    strava_id: int,
    days_ago: float,
    enrichment_status: str = "complete",
    superseded_by_id: int | None = None,
) -> Activity:
    start = datetime.now() - timedelta(days=days_ago)
    return Activity(
        strava_id=strava_id,
        name=f"Strava {strava_id}",
        sport_type="Run",
        start_date=start,
        start_date_local=start,
        elapsed_time=1800,
        moving_time=1800,
        distance=5000.0,
        average_hr=145.0,
        average_speed=2.8,
        suffer_score=40,
        classification_type=None,
        enrichment_status=enrichment_status,
        superseded_by_id=superseded_by_id,
    )


async def _add_apple_workout(
    db: AsyncSession,
    *,
    external_id: str,
    days_ago: float,
    activity_type: str = "run",
    distance_m: float = 4200.0,
    duration_s: int = 1500,
    avg_hr: float = 152.0,
) -> tuple[HealthDataPoint, Workout]:
    """Insert a paired HealthDataPoint + Workout and return both rows."""
    start = datetime.now() - timedelta(days=days_ago)
    dp = HealthDataPoint(
        source="apple_health",
        data_type="workout",
        external_id=external_id,
        start_time=start,
        end_time=start + timedelta(seconds=duration_s),
        raw_payload={"name": f"Apple workout {external_id}"},
    )
    db.add(dp)
    await db.flush()
    workout = Workout(
        id=dp.id,
        activity_type=activity_type,
        duration_s=duration_s,
        active_energy_kcal=380.0,
        distance_m=distance_m,
        avg_speed_mps=distance_m / duration_s if duration_s else None,
        avg_hr=avg_hr,
        max_hr=avg_hr + 15,
        total_elevation_m=42.0,
    )
    db.add(workout)
    await db.commit()
    await db.refresh(dp)
    await db.refresh(workout)
    return dp, workout


async def test_latest_workout_snapshot_returns_apple_when_newer(db: AsyncSession):
    """Strava 2 days ago + Apple 1 hour ago → snapshot tracks Apple."""
    strava = _make_strava(strava_id=111, days_ago=2)
    db.add(strava)
    await db.commit()

    dp, _workout = await _add_apple_workout(
        db, external_id="apple-newer", days_ago=1 / 24
    )

    snap = await get_latest_workout_snapshot(db)
    assert snap is not None
    assert snap["source"] == "apple_health"
    assert snap["strava_id"] is None
    assert snap["id"] == dp.id
    # Apple-side fields populate from the Workout child.
    assert snap["distance_m"] == 4200.0
    assert snap["moving_time_s"] == 1500
    assert snap["avg_hr"] == 152.0
    # Strava-only fields stay None even when an Apple row wins.
    assert snap["avg_power_w"] is None
    assert snap["weighted_avg_power_w"] is None
    assert snap["kilojoules"] is None
    assert snap["hr_zones"] is None
    assert snap["historical_comparison"] is None
    assert snap["laps"] == []


async def test_latest_workout_snapshot_returns_strava_when_newer(db: AsyncSession):
    """Strava 1 hour ago + Apple 2 days ago → snapshot tracks Strava."""
    strava = _make_strava(strava_id=222, days_ago=1 / 24)
    db.add(strava)
    await db.commit()
    await db.refresh(strava)

    await _add_apple_workout(db, external_id="apple-older", days_ago=2)

    snap = await get_latest_workout_snapshot(db)
    assert snap is not None
    assert snap["source"] == "strava"
    assert snap["strava_id"] == 222
    assert snap["id"] == strava.id


async def test_latest_workout_snapshot_ignores_superseded_strava(db: AsyncSession):
    """A Strava activity superseded by an Apple winner must NOT be returned.

    Even though the (superseded) Strava row sorts later by ``start_date``,
    the resolver should treat it as ineligible and surface the winning
    Apple workout instead.
    """
    # Seed the Apple winner first so we have an id to point at.
    dp, _workout = await _add_apple_workout(
        db, external_id="apple-winner", days_ago=2
    )

    # The losing Strava activity is "newer" by raw start time but is
    # marked superseded — Home should still skip it.
    strava = _make_strava(
        strava_id=333,
        days_ago=1,
        superseded_by_id=dp.id,
    )
    db.add(strava)
    await db.commit()

    snap = await get_latest_workout_snapshot(db)
    assert snap is not None
    assert snap["source"] == "apple_health"
    assert snap["id"] == dp.id
    assert snap["strava_id"] is None


async def test_latest_workout_snapshot_apple_only_no_strava(db: AsyncSession):
    """Apple-only DB still produces a snapshot rather than returning None."""
    dp, _workout = await _add_apple_workout(
        db, external_id="apple-only", days_ago=0.5
    )

    snap = await get_latest_workout_snapshot(db)
    assert snap is not None
    assert snap["source"] == "apple_health"
    assert snap["id"] == dp.id
    assert snap["strava_id"] is None
