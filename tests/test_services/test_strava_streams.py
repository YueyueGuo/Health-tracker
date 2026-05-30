"""Tests for backend.services.strava_streams.fetch_and_cache_streams.

Covers cache-miss (populates rows), cache-hit (returns early without
calling Strava), exception propagation (StravaRateLimitError not caught
internally), and graceful handling of empty stream responses.

The Strava HTTP client is stubbed -- no network.
"""
from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.clients.strava import StravaRateLimitError
from backend.database import Base
from backend.models import Activity, ActivityStream
from backend.services.strava_streams import fetch_and_cache_streams


# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


def _make_activity(strava_id: int = 1) -> Activity:
    from datetime import datetime

    return Activity(
        strava_id=strava_id,
        name="Test Run",
        sport_type="Run",
        start_date=datetime(2026, 5, 1, 8, 0, 0),
        enrichment_status="complete",
    )


class StubStravaClient:
    """Minimal stub exposing ``get_activity_streams``."""

    def __init__(
        self,
        *,
        streams: dict[int, dict[str, list]] | None = None,
        raises: dict[int, Exception] | None = None,
    ):
        self._streams = streams or {}
        self._raises = raises or {}
        self.calls: list[int] = []

    async def get_activity_streams(self, activity_id: int) -> dict[str, list]:
        self.calls.append(activity_id)
        if activity_id in self._raises:
            raise self._raises[activity_id]
        return self._streams.get(activity_id, {})


# ── Tests ──────────────────────────────────────────────────────────


async def test_cache_miss_populates_activity_streams(db):
    """On a cache miss, fetch_and_cache_streams should call Strava,
    persist ActivityStream rows, and return the streams dict."""
    activity = _make_activity(strava_id=42)
    db.add(activity)
    await db.commit()
    await db.refresh(activity)

    stream_data = {
        "heartrate": [120, 130, 140, 150],
        "time": [0, 1, 2, 3],
        "cadence": [80, 82, 84, 86],
    }
    client = StubStravaClient(streams={42: stream_data})

    result = await fetch_and_cache_streams(db, activity, client)

    # Strava was called.
    assert client.calls == [42]

    # Result matches what we sent.
    assert result == stream_data

    # Rows persisted in DB.
    rows = (
        await db.execute(
            select(ActivityStream).where(ActivityStream.activity_id == activity.id)
        )
    ).scalars().all()
    assert len(rows) == 3
    types = {r.stream_type for r in rows}
    assert types == {"heartrate", "time", "cadence"}
    for row in rows:
        assert row.data == stream_data[row.stream_type]


async def test_cache_hit_returns_early_without_calling_strava(db):
    """When ActivityStream rows already exist, fetch_and_cache_streams
    should return cached data without calling the Strava API."""
    activity = _make_activity(strava_id=55)
    db.add(activity)
    await db.commit()
    await db.refresh(activity)

    # Pre-populate cache.
    db.add(
        ActivityStream(
            activity_id=activity.id,
            stream_type="heartrate",
            data=[100, 110, 120],
        )
    )
    await db.commit()

    client = StubStravaClient(streams={55: {"heartrate": [999]}})

    result = await fetch_and_cache_streams(db, activity, client)

    # Strava was NOT called.
    assert client.calls == []

    # Cached data returned.
    assert result == {"heartrate": [100, 110, 120]}


async def test_raises_strava_rate_limit_error_to_caller(db):
    """StravaRateLimitError must propagate to the caller -- the function
    must NOT catch it internally."""
    activity = _make_activity(strava_id=77)
    db.add(activity)
    await db.commit()
    await db.refresh(activity)

    client = StubStravaClient(
        raises={77: StravaRateLimitError(retry_after=15)}
    )

    with pytest.raises(StravaRateLimitError):
        await fetch_and_cache_streams(db, activity, client)

    # Strava was called (the error came from the API).
    assert client.calls == [77]


async def test_empty_stream_response_handled_gracefully(db):
    """When Strava returns an empty dict, no rows should be created
    and an empty dict should be returned."""
    activity = _make_activity(strava_id=88)
    db.add(activity)
    await db.commit()
    await db.refresh(activity)

    client = StubStravaClient(streams={88: {}})

    result = await fetch_and_cache_streams(db, activity, client)

    assert result == {}
    assert client.calls == [88]

    # No rows persisted.
    rows = (
        await db.execute(
            select(ActivityStream).where(ActivityStream.activity_id == activity.id)
        )
    ).scalars().all()
    assert len(rows) == 0


async def test_empty_data_lists_not_persisted(db):
    """Stream types with empty data lists should not be persisted as rows."""
    activity = _make_activity(strava_id=99)
    db.add(activity)
    await db.commit()
    await db.refresh(activity)

    stream_data: dict[str, list[Any]] = {
        "heartrate": [120, 130],
        "cadence": [],  # empty -- should not be persisted
    }
    client = StubStravaClient(streams={99: stream_data})

    result = await fetch_and_cache_streams(db, activity, client)

    # Result includes both keys (mirrors Strava response).
    assert result == stream_data

    # Only the non-empty stream was persisted.
    rows = (
        await db.execute(
            select(ActivityStream).where(ActivityStream.activity_id == activity.id)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].stream_type == "heartrate"
