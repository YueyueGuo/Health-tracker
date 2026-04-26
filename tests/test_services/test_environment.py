"""Tests for backend.services.environment.

Covers the in-memory TTL cache, default-location gating, parallel client
fan-out, and partial-failure tolerance. Open-Meteo client methods are
patched at the class level so no network is involved.
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.clients.openmeteo import OpenMeteoClient
from backend.database import Base
from backend.models.user_location import UserLocation
from backend.services import environment as env_mod
from backend.services.environment import fetch_environment_today
from backend.services.snapshot_models import EnvironmentTodaySnapshot


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def _clear_module_cache():
    env_mod._clear_cache()
    yield
    env_mod._clear_cache()


def _sample_forecast() -> dict:
    return {
        "temp_c": 18.4,
        "high_c": 22.1,
        "low_c": 11.8,
        "conditions": "overcast",
        "wind_ms": 3.2,
    }


def _sample_air_quality() -> dict:
    return {
        "us_aqi": 41,
        "european_aqi": 32,
        "pollen": {
            "alder": 0.5,
            "birch": 1.2,
            "grass": 0.0,
            "mugwort": 0.1,
            "olive": 0.0,
            "ragweed": 2.7,
        },
    }


async def _add_default_location(db: AsyncSession) -> UserLocation:
    loc = UserLocation(
        name="Home",
        lat=40.7128,
        lng=-74.0060,
        elevation_m=10.0,
        is_default=True,
    )
    db.add(loc)
    await db.commit()
    await db.refresh(loc)
    return loc


# ── No default location ─────────────────────────────────────────────


async def test_returns_none_without_default_location(db_session, monkeypatch):
    """No row with ``is_default=True`` → no client calls, no payload."""
    calls = {"forecast": 0, "aq": 0}

    async def _forecast(self, lat, lng):
        calls["forecast"] += 1
        return _sample_forecast()

    async def _aq(self, lat, lng):
        calls["aq"] += 1
        return _sample_air_quality()

    monkeypatch.setattr(OpenMeteoClient, "get_forecast_today", _forecast)
    monkeypatch.setattr(
        OpenMeteoClient, "get_air_quality_and_pollen", _aq
    )

    # Add a non-default location to confirm the filter is on is_default.
    db_session.add(
        UserLocation(name="Other", lat=1.0, lng=2.0, is_default=False)
    )
    await db_session.commit()

    assert await fetch_environment_today(db_session) is None
    assert calls == {"forecast": 0, "aq": 0}


# ── Happy path + contract validation ────────────────────────────────


async def test_returns_validated_payload(db_session, monkeypatch):
    await _add_default_location(db_session)

    async def _forecast(self, lat, lng):
        return _sample_forecast()

    async def _aq(self, lat, lng):
        return _sample_air_quality()

    monkeypatch.setattr(OpenMeteoClient, "get_forecast_today", _forecast)
    monkeypatch.setattr(
        OpenMeteoClient, "get_air_quality_and_pollen", _aq
    )

    payload = await fetch_environment_today(db_session)

    assert payload is not None
    assert payload["forecast"] == _sample_forecast()
    assert payload["air_quality"] == _sample_air_quality()
    # Validates without raising — contract holds.
    EnvironmentTodaySnapshot.model_validate(payload)


# ── Cache hit ───────────────────────────────────────────────────────


async def test_cache_hit_within_same_hour_bucket(db_session, monkeypatch):
    await _add_default_location(db_session)

    calls = {"forecast": 0, "aq": 0}

    async def _forecast(self, lat, lng):
        calls["forecast"] += 1
        return _sample_forecast()

    async def _aq(self, lat, lng):
        calls["aq"] += 1
        return _sample_air_quality()

    monkeypatch.setattr(OpenMeteoClient, "get_forecast_today", _forecast)
    monkeypatch.setattr(
        OpenMeteoClient, "get_air_quality_and_pollen", _aq
    )

    p1 = await fetch_environment_today(db_session)
    p2 = await fetch_environment_today(db_session)

    assert p1 == p2
    assert calls == {"forecast": 1, "aq": 1}, (
        "Second call within the hour bucket should hit the cache."
    )


# ── Cache miss after bucket flip ─────────────────────────────────────


async def test_cache_miss_when_hour_bucket_changes(db_session, monkeypatch):
    await _add_default_location(db_session)

    calls = {"forecast": 0, "aq": 0}

    async def _forecast(self, lat, lng):
        calls["forecast"] += 1
        return _sample_forecast()

    async def _aq(self, lat, lng):
        calls["aq"] += 1
        return _sample_air_quality()

    monkeypatch.setattr(OpenMeteoClient, "get_forecast_today", _forecast)
    monkeypatch.setattr(
        OpenMeteoClient, "get_air_quality_and_pollen", _aq
    )

    # First call: bucket = 0
    bucket = {"v": 0}
    monkeypatch.setattr(env_mod, "_hour_bucket", lambda: bucket["v"])

    await fetch_environment_today(db_session)
    assert calls == {"forecast": 1, "aq": 1}

    # Bucket flips → cache key changes → fresh client calls.
    bucket["v"] = 1
    await fetch_environment_today(db_session)
    assert calls == {"forecast": 2, "aq": 2}


# ── Partial failure ──────────────────────────────────────────────────


async def test_partial_failure_keeps_forecast(db_session, monkeypatch):
    """Forecast OK + air quality raising → result has forecast, AQ is None."""
    await _add_default_location(db_session)

    async def _forecast(self, lat, lng):
        return _sample_forecast()

    async def _aq(self, lat, lng):
        raise RuntimeError("upstream 503")

    monkeypatch.setattr(OpenMeteoClient, "get_forecast_today", _forecast)
    monkeypatch.setattr(
        OpenMeteoClient, "get_air_quality_and_pollen", _aq
    )

    payload = await fetch_environment_today(db_session)
    assert payload is not None
    assert payload["forecast"] == _sample_forecast()
    assert payload["air_quality"] is None
    EnvironmentTodaySnapshot.model_validate(payload)


async def test_total_failure_returns_none(db_session, monkeypatch):
    """Both legs raise → return None, don't poison the cache."""
    await _add_default_location(db_session)

    async def _boom(self, lat, lng):
        raise RuntimeError("everything is on fire")

    monkeypatch.setattr(OpenMeteoClient, "get_forecast_today", _boom)
    monkeypatch.setattr(
        OpenMeteoClient, "get_air_quality_and_pollen", _boom
    )

    assert await fetch_environment_today(db_session) is None
    # Cache must stay empty so the next request re-attempts.
    assert env_mod._cache == {}


async def test_both_legs_return_none_collapses_to_none(db_session, monkeypatch):
    """Both legs succeed but return None (coverage gap) → return None,
    don't cache an empty payload that would render a blank tile for an hour."""
    await _add_default_location(db_session)

    async def _none_forecast(self, lat, lng):
        return None

    async def _none_aq(self, lat, lng):
        return None

    monkeypatch.setattr(OpenMeteoClient, "get_forecast_today", _none_forecast)
    monkeypatch.setattr(
        OpenMeteoClient, "get_air_quality_and_pollen", _none_aq
    )

    assert await fetch_environment_today(db_session) is None
    assert env_mod._cache == {}
