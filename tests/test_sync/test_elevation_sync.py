"""Tests for backend.services.elevation_sync.

Exercises the four-path derivation precedence (Strava elev_low, attached
location, Open-Meteo lookup, default location) and the idempotency of the
``elevation_enriched`` flag.

Uses an in-memory SQLite DB so the real SQLAlchemy models are exercised,
with a fake in-memory ElevationClient standing in for HTTP calls.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models import Activity, UserLocation
from backend.services.elevation_sync import (
    extract_elev_from_raw,
    recompute_for_activity,
    sync_elevation,
)


# ── Fakes + fixtures ────────────────────────────────────────────────


class FakeElevationClient:
    """Stand-in for ElevationClient that returns scripted responses."""

    def __init__(self, *, responses: dict[tuple[float, float], float | None] | None = None,
                 raise_on: tuple[float, float] | None = None):
        self.responses = responses or {}
        self.raise_on = raise_on
        self.calls: list[tuple[float, float]] = []

    async def get_elevation(self, *, lat: float, lng: float) -> float | None:
        self.calls.append((lat, lng))
        if self.raise_on == (lat, lng):
            from backend.clients.elevation import ElevationRateLimitError
            raise ElevationRateLimitError(status_code=429)
        return self.responses.get((lat, lng))


_STRAVA_COUNTER = {"n": 0}


def _next_strava_id() -> int:
    _STRAVA_COUNTER["n"] += 1
    return 20_000 + _STRAVA_COUNTER["n"]


def _make_activity(**kwargs) -> Activity:
    defaults = dict(
        strava_id=_next_strava_id(),
        name="Test",
        sport_type="Run",
        start_date=datetime(2026, 4, 1, 12, 0, 0),
        enrichment_status="complete",
        elevation_enriched=False,
    )
    defaults.update(kwargs)
    return Activity(**defaults)


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


# ── Path 1: Strava elev_low ─────────────────────────────────────────


async def test_path1_uses_elev_low_without_api_call(db: AsyncSession):
    act = _make_activity(
        elev_low_m=1820.0,
        elev_high_m=2400.0,
        start_lat=39.5,
        start_lng=-106.0,
    )
    db.add(act)
    await db.commit()

    client = FakeElevationClient()
    result = await sync_elevation(db, client)

    await db.refresh(act)
    assert act.base_elevation_m == pytest.approx(1820.0)
    assert act.elevation_enriched is True
    assert result["enriched"] == 1
    assert client.calls == []  # no API call for Path 1


# ── Path 2: attached user_location ──────────────────────────────────


async def test_path2_uses_attached_location(db: AsyncSession):
    loc = UserLocation(
        name="Tahoe cabin", lat=39.0968, lng=-120.0324, elevation_m=1900.0
    )
    db.add(loc)
    await db.flush()

    act = _make_activity(location_id=loc.id)  # no start_lat/lng, no elev_low_m
    db.add(act)
    await db.commit()

    client = FakeElevationClient()
    result = await sync_elevation(db, client)

    await db.refresh(act)
    assert act.base_elevation_m == pytest.approx(1900.0)
    assert act.elevation_enriched is True
    assert result["enriched"] == 1
    assert client.calls == []


# ── Path 3: Open-Meteo lookup ───────────────────────────────────────


async def test_path3_calls_open_meteo_for_coords(db: AsyncSession):
    act = _make_activity(start_lat=40.015, start_lng=-105.2705)
    db.add(act)
    await db.commit()

    client = FakeElevationClient(responses={(40.015, -105.2705): 1655.0})
    result = await sync_elevation(db, client)

    await db.refresh(act)
    assert act.base_elevation_m == pytest.approx(1655.0)
    assert act.elevation_enriched is True
    assert result["enriched"] == 1
    assert client.calls == [(40.015, -105.2705)]


async def test_path3_open_meteo_null_marks_enriched_anyway(db: AsyncSession):
    """When Open-Meteo returns None, we still flip enriched so we don't retry."""
    act = _make_activity(start_lat=0.0, start_lng=0.0)
    db.add(act)
    await db.commit()

    client = FakeElevationClient(responses={(0.0, 0.0): None})
    result = await sync_elevation(db, client)

    await db.refresh(act)
    assert act.base_elevation_m is None
    # skipped because no value resolved; row left as enriched=False so a
    # later client might succeed. Path 3 doesn't flip enriched on None.
    assert act.elevation_enriched is False
    assert result["enriched"] == 0
    assert result["skipped"] == 1


# ── Path 4: default location fallback ───────────────────────────────


async def test_path4_applies_default_location_for_indoor(db: AsyncSession):
    default = UserLocation(
        name="Home", lat=40.0, lng=-73.0, elevation_m=15.0, is_default=True
    )
    db.add(default)

    # Indoor activity: no lat/lng, no location_id, no elev_low.
    act = _make_activity()
    db.add(act)
    await db.commit()

    client = FakeElevationClient()
    result = await sync_elevation(db, client)

    await db.refresh(act)
    assert act.base_elevation_m == pytest.approx(15.0)
    assert act.elevation_enriched is True
    assert result["enriched"] == 1
    assert client.calls == []


async def test_no_paths_available_marks_enriched_skipped(db: AsyncSession):
    """Indoor with no default location → enriched=True, base=None."""
    act = _make_activity()
    db.add(act)
    await db.commit()

    client = FakeElevationClient()
    result = await sync_elevation(db, client)

    await db.refresh(act)
    assert act.base_elevation_m is None
    # Enriched flipped so we don't keep retrying indefinitely.
    assert act.elevation_enriched is True
    assert result["skipped"] == 1


# ── Idempotency ─────────────────────────────────────────────────────


async def test_already_enriched_rows_skipped(db: AsyncSession):
    act = _make_activity(
        elev_low_m=500.0,
        base_elevation_m=500.0,
        elevation_enriched=True,
    )
    db.add(act)
    await db.commit()

    client = FakeElevationClient()
    result = await sync_elevation(db, client)

    assert result["enriched"] == 0
    assert result["skipped"] == 0
    assert client.calls == []


# ── Rate limit handling ─────────────────────────────────────────────


async def test_rate_limit_breaks_loop_preserves_prior_enrichments(db: AsyncSession):
    """On 429 partway through, we commit earlier successes and stop cleanly."""
    # sync_elevation orders by start_date DESC, so the newer activity runs
    # first. Make a1 the newer one and have the OLDER one trigger 429 so a1
    # gets enriched before the loop aborts.
    a1 = _make_activity(
        start_lat=1.0,
        start_lng=2.0,
        start_date=datetime(2026, 4, 2, 12, 0, 0),  # newer
    )
    a2 = _make_activity(
        start_lat=3.0,
        start_lng=4.0,
        start_date=datetime(2026, 4, 1, 12, 0, 0),  # older
    )
    db.add_all([a1, a2])
    await db.commit()

    client = FakeElevationClient(
        responses={(1.0, 2.0): 100.0, (3.0, 4.0): 200.0},
        raise_on=(3.0, 4.0),
    )
    await sync_elevation(db, client)

    await db.refresh(a1)
    await db.refresh(a2)
    # a1 processed first, got its elevation, was committed.
    assert a1.elevation_enriched is True
    assert a1.base_elevation_m == pytest.approx(100.0)
    # a2 triggered 429 and was NOT enriched.
    assert a2.elevation_enriched is False
    assert a2.base_elevation_m is None


# ── recompute_for_activity ──────────────────────────────────────────


async def test_recompute_prefers_elev_low_over_location(db: AsyncSession):
    loc = UserLocation(name="Gym", lat=1.0, lng=2.0, elevation_m=10.0)
    db.add(loc)
    await db.flush()

    act = _make_activity(elev_low_m=1500.0, location_id=loc.id)
    db.add(act)
    await db.commit()

    out = await recompute_for_activity(db, act, client=FakeElevationClient())
    assert out == pytest.approx(1500.0)
    assert act.elevation_enriched is True


async def test_recompute_uses_location_when_no_elev_low(db: AsyncSession):
    loc = UserLocation(name="Gym", lat=1.0, lng=2.0, elevation_m=10.0)
    db.add(loc)
    await db.flush()

    act = _make_activity(location_id=loc.id)  # no elev_low_m, no coords
    db.add(act)
    await db.commit()

    out = await recompute_for_activity(db, act, client=FakeElevationClient())
    assert out == pytest.approx(10.0)


# ── extract_elev_from_raw ───────────────────────────────────────────


def test_extract_elev_from_raw_pulls_both_keys():
    raw = {"elev_high": 3000.5, "elev_low": 1200.25, "other": 1}
    out = extract_elev_from_raw(raw)
    assert out == {"elev_high_m": 3000.5, "elev_low_m": 1200.25}


def test_extract_elev_from_raw_handles_missing_and_bad():
    assert extract_elev_from_raw(None) == {}
    assert extract_elev_from_raw({}) == {}
    assert extract_elev_from_raw({"elev_high": "notanumber"}) == {}
    # Only good key is returned when one side is malformed.
    assert extract_elev_from_raw({"elev_high": 100, "elev_low": None}) == {
        "elev_high_m": 100.0
    }
