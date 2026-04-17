"""Tests for the Strava enrichment drain job guards.

We don't exercise APScheduler itself — just the guard logic in
`_run_strava_enrichment_drain` (pending==0 skip, daily-quota-hit skip).
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backend import scheduler as scheduler_module
from backend.database import Base
from backend.models import Activity

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def setup_db(monkeypatch):
    """Replace the global async_session with an in-memory one."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(scheduler_module, "async_session", Session)
    yield Session
    await engine.dispose()


async def test_drain_noop_when_no_pending(setup_db, monkeypatch, caplog):
    # Configure Strava credentials so we get past the "not configured" guard.
    from backend.config import settings
    monkeypatch.setattr(settings.strava, "access_token", "fake-token", raising=False)

    called = {"phase_b": 0}

    # If Phase B runs, flag it — we expect it NOT to.
    async def _fake_phase_b(self, **kwargs):
        called["phase_b"] += 1
        return 0

    from backend.services.sync import SyncEngine
    monkeypatch.setattr(SyncEngine, "_strava_phase_b", _fake_phase_b)

    with caplog.at_level("DEBUG"):
        await scheduler_module._run_strava_enrichment_drain()

    assert called["phase_b"] == 0
    assert any("No pending" in m or "idle" in m for m in caplog.messages)


async def test_drain_skips_when_daily_quota_hit(setup_db, monkeypatch, caplog):
    # Seed one pending activity so we pass the pending==0 guard.
    Session = setup_db
    async with Session() as db:
        db.add(
            Activity(
                strava_id=1,
                name="Pending",
                sport_type="Run",
                start_date=datetime.utcnow() - timedelta(days=1),
                enrichment_status="pending",
            )
        )
        await db.commit()

    from backend.config import settings
    monkeypatch.setattr(settings.strava, "access_token", "fake-token", raising=False)

    # Force daily_quota_exhausted -> True
    from backend.clients.strava import StravaClient
    monkeypatch.setattr(StravaClient, "daily_quota_exhausted", staticmethod(lambda fraction=0.98: True))
    monkeypatch.setattr(
        StravaClient, "which_quota_exhausted", staticmethod(lambda fraction=0.98: ["daily_read"])
    )

    called = {"phase_b": 0}

    async def _fake_phase_b(self, **kwargs):
        called["phase_b"] += 1
        return 0

    from backend.services.sync import SyncEngine
    monkeypatch.setattr(SyncEngine, "_strava_phase_b", _fake_phase_b)

    with caplog.at_level("INFO"):
        await scheduler_module._run_strava_enrichment_drain()

    assert called["phase_b"] == 0
    assert any("daily quota exhausted" in m.lower() for m in caplog.messages)


async def test_drain_runs_phase_b_when_pending_and_quota_ok(setup_db, monkeypatch, caplog):
    Session = setup_db
    async with Session() as db:
        db.add(
            Activity(
                strava_id=1,
                name="Pending",
                sport_type="Run",
                start_date=datetime.utcnow() - timedelta(days=1),
                enrichment_status="pending",
            )
        )
        await db.commit()

    from backend.config import settings
    monkeypatch.setattr(settings.strava, "access_token", "fake-token", raising=False)

    from backend.clients.strava import StravaClient
    monkeypatch.setattr(StravaClient, "daily_quota_exhausted", staticmethod(lambda fraction=0.98: False))

    called = {"phase_b": 0, "limit": None}

    async def _fake_phase_b(self, *, limit=None):
        called["phase_b"] += 1
        called["limit"] = limit
        return 3

    from backend.services.sync import SyncEngine
    monkeypatch.setattr(SyncEngine, "_strava_phase_b", _fake_phase_b)

    # Stub the Strava client close() so it doesn't try to hit HTTP.
    async def _noop(self):
        return None
    monkeypatch.setattr(StravaClient, "close", _noop)

    with caplog.at_level("INFO"):
        await scheduler_module._run_strava_enrichment_drain(batch=40)

    assert called["phase_b"] == 1
    assert called["limit"] == 40
    assert any("enriched=3" in m for m in caplog.messages)
