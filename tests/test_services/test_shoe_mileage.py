"""Tests for backend.services.shoe_mileage."""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models import Activity, HealthDataPoint, Shoe, Workout
from backend.services.shoe_mileage import (
    cumulative_distance_bulk,
    cumulative_distance_m,
    percent_used,
)
from backend.services.time_utils import utc_now_naive


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


async def _make_shoe(db, **overrides) -> Shoe:
    shoe = Shoe(name=overrides.pop("name", "Test shoe"), **overrides)
    db.add(shoe)
    await db.commit()
    await db.refresh(shoe)
    return shoe


async def _make_strava(db, *, shoe_id: int | None, strava_id: int, distance: float) -> Activity:
    start = utc_now_naive() - timedelta(days=1)
    a = Activity(
        strava_id=strava_id,
        name=f"strava-{strava_id}",
        sport_type="Run",
        start_date=start,
        start_date_local=start,
        distance=distance,
        shoe_id=shoe_id,
        enrichment_status="complete",
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


async def _make_apple(
    db, *, shoe_id: int | None, external_id: str, distance_m: float
) -> Workout:
    start = utc_now_naive() - timedelta(days=1)
    dp = HealthDataPoint(
        source="apple_health",
        data_type="workout",
        external_id=external_id,
        start_time=start,
    )
    db.add(dp)
    await db.flush()
    w = Workout(
        id=dp.id,
        activity_type="run",
        duration_s=1800,
        distance_m=distance_m,
        shoe_id=shoe_id,
    )
    db.add(w)
    await db.commit()
    await db.refresh(w)
    return w


# ── cumulative_distance_m ────────────────────────────────────────────


async def test_cumulative_distance_sums_both_tables(db):
    shoe = await _make_shoe(db)
    await _make_strava(db, shoe_id=shoe.id, strava_id=1, distance=10000.0)
    await _make_apple(db, shoe_id=shoe.id, external_id="ax-1", distance_m=5000.0)

    total = await cumulative_distance_m(db, shoe.id)
    assert total == pytest.approx(15000.0)


async def test_cumulative_distance_empty(db):
    """No tagged activities → 0.0 (a float, not None)."""
    shoe = await _make_shoe(db)
    total = await cumulative_distance_m(db, shoe.id)
    assert total == 0.0
    assert isinstance(total, float)


async def test_cumulative_distance_only_strava(db):
    shoe = await _make_shoe(db)
    await _make_strava(db, shoe_id=shoe.id, strava_id=1, distance=8000.0)
    total = await cumulative_distance_m(db, shoe.id)
    assert total == pytest.approx(8000.0)


async def test_cumulative_distance_only_apple(db):
    shoe = await _make_shoe(db)
    await _make_apple(db, shoe_id=shoe.id, external_id="ax-only", distance_m=7000.0)
    total = await cumulative_distance_m(db, shoe.id)
    assert total == pytest.approx(7000.0)


async def test_cumulative_distance_ignores_untagged(db):
    """Activities without ``shoe_id`` must not contribute."""
    shoe = await _make_shoe(db)
    await _make_strava(db, shoe_id=shoe.id, strava_id=1, distance=3000.0)
    # Untagged
    await _make_strava(db, shoe_id=None, strava_id=2, distance=99999.0)
    total = await cumulative_distance_m(db, shoe.id)
    assert total == pytest.approx(3000.0)


# ── cumulative_distance_bulk ─────────────────────────────────────────


async def test_cumulative_distance_bulk(db):
    """Two shoes split across four activities (mixed Strava + Apple)."""
    s1 = await _make_shoe(db, name="Shoe A")
    s2 = await _make_shoe(db, name="Shoe B")

    await _make_strava(db, shoe_id=s1.id, strava_id=11, distance=4000.0)
    await _make_strava(db, shoe_id=s1.id, strava_id=12, distance=6000.0)
    await _make_apple(db, shoe_id=s2.id, external_id="bx-1", distance_m=5000.0)
    await _make_strava(db, shoe_id=s2.id, strava_id=21, distance=2000.0)

    totals = await cumulative_distance_bulk(db, [s1.id, s2.id])
    assert totals[s1.id] == pytest.approx(10000.0)
    assert totals[s2.id] == pytest.approx(7000.0)


async def test_cumulative_distance_bulk_empty_ids(db):
    """Empty input → empty dict (no queries needed)."""
    totals = await cumulative_distance_bulk(db, [])
    assert totals == {}


async def test_cumulative_distance_bulk_zero_distance_not_in_dict(db):
    """A shoe with no tags simply doesn't appear in the dict; caller
    is responsible for default-filling 0.0."""
    s1 = await _make_shoe(db, name="Empty shoe")
    totals = await cumulative_distance_bulk(db, [s1.id])
    assert totals == {}


# ── percent_used ─────────────────────────────────────────────────────


def test_percent_used_helper():
    assert percent_used(1000.0, 250.0) == pytest.approx(25.0)
    assert percent_used(1000.0, 1000.0) == pytest.approx(100.0)
    # Overdue allowed (UI styles the overflow).
    assert percent_used(1000.0, 1500.0) == pytest.approx(150.0)


def test_percent_used_null_when_no_target():
    assert percent_used(None, 1234.0) is None
    assert percent_used(0.0, 1234.0) is None
    assert percent_used(-1.0, 1234.0) is None
