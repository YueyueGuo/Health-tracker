"""Tests for the sync router.

Covers ``POST /api/sync/trigger`` and ``GET /api/sync/status`` — the
endpoints where Bug A is invisible today because the per-source errors
get swallowed before reaching ``sync_log.error_message``. The "error
surfacing" test is marked ``xfail`` with a reference to audit-001 A6;
the production fix lifts it (see W2-bug-A brief).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from backend.models import SyncLog
import backend.routers.sync as sync_router_module

from .conftest import make_client


# ── Stub clients & engine ──────────────────────────────────────────────


class _StubClient:
    """No-op stand-in for Strava/Whoop/Eight-Sleep/Weather clients.

    The sync router awaits ``close()`` on each client in its ``finally``
    block; the status endpoint also calls the static
    ``StravaClient.quota_usage()`` so the stub exposes a matching no-op.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True

    @staticmethod
    def quota_usage() -> dict[str, int | None]:
        return {"short": 0, "long": 0, "short_limit": None, "long_limit": None}


class _StubSyncEngine:
    """Records which engine method was invoked so tests can assert routing.

    ``sync_all`` returns the configured ``all_results`` dict; the
    per-source ``sync_strava``/``sync_eight_sleep``/``sync_whoop``/
    ``sync_weather`` methods return the configured count for that
    source. Any source can be configured to raise via ``raise_for``.
    """

    def __init__(
        self,
        db: Any,
        strava: Any,
        eight_sleep: Any,
        whoop: Any,
        weather: Any,
    ) -> None:
        self.db = db
        self.strava = strava
        self.eight_sleep = eight_sleep
        self.whoop = whoop
        self.weather = weather
        self.calls: list[str] = []

    # Configurable per-instance via class attributes overridden in tests.
    all_results: dict[str, Any] = {}
    per_source_counts: dict[str, Any] = {}
    raise_for: dict[str, Exception] = {}

    async def sync_all(self) -> dict[str, Any]:
        self.calls.append("sync_all")
        return type(self).all_results

    async def sync_strava(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append("sync_strava")
        if "strava" in type(self).raise_for:
            raise type(self).raise_for["strava"]
        return type(self).per_source_counts.get("strava", 0)

    async def sync_eight_sleep(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append("sync_eight_sleep")
        if "eight_sleep" in type(self).raise_for:
            raise type(self).raise_for["eight_sleep"]
        return type(self).per_source_counts.get("eight_sleep", 0)

    async def sync_whoop(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append("sync_whoop")
        if "whoop" in type(self).raise_for:
            raise type(self).raise_for["whoop"]
        return type(self).per_source_counts.get("whoop", 0)

    async def sync_weather(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append("sync_weather")
        if "weather" in type(self).raise_for:
            raise type(self).raise_for["weather"]
        return type(self).per_source_counts.get("weather", 0)


# Records the engine instance the router most recently constructed; the
# fixture resets this list on each test.
_LAST_ENGINE: list[_StubSyncEngine] = []


def _stub_engine_factory(
    db: Any, strava: Any, eight_sleep: Any, whoop: Any, weather: Any
) -> _StubSyncEngine:
    engine = _StubSyncEngine(db, strava, eight_sleep, whoop, weather)
    _LAST_ENGINE.append(engine)
    return engine


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
async def client(db_and_sessionmaker):
    _, Session = db_and_sessionmaker
    async with make_client(
        sync_router_module.router, "/api/sync", Session
    ) as c:
        yield c


@pytest.fixture(autouse=True)
def patch_clients_and_engine(monkeypatch):
    """Swap real clients + SyncEngine for stubs.

    The sync router imports each module inline inside ``trigger_sync``,
    so we patch the source modules (which is what the inline ``from
    backend.clients... import ...`` resolves to).
    """
    _LAST_ENGINE.clear()
    _StubSyncEngine.all_results = {}
    _StubSyncEngine.per_source_counts = {}
    _StubSyncEngine.raise_for = {}

    import backend.clients as clients_pkg
    import backend.clients.eight_sleep as eight_sleep_mod
    import backend.clients.strava as strava_mod
    import backend.clients.whoop as whoop_mod
    import backend.services.sync as services_sync_mod

    monkeypatch.setattr(strava_mod, "StravaClient", _StubClient)
    monkeypatch.setattr(whoop_mod, "WhoopClient", _StubClient)
    monkeypatch.setattr(eight_sleep_mod, "EightSleepClient", _StubClient)
    monkeypatch.setattr(clients_pkg, "get_weather_client", lambda: _StubClient())
    monkeypatch.setattr(services_sync_mod, "SyncEngine", _stub_engine_factory)

    yield


# ── POST /api/sync/trigger ─────────────────────────────────────────────


async def test_trigger_all_routes_to_sync_all(client):
    _StubSyncEngine.all_results = {
        "strava": 3,
        "eight_sleep": 1,
        "whoop": {"recovery_new": 2, "sleep_new": 1, "workouts_new": 0},
        "weather": {"enriched": 0, "skipped": 0, "failed": 0, "remaining": 0},
        "elevation": {"enriched": 0, "skipped": 0, "failed": 0, "remaining": 0},
    }

    response = await client.post("/api/sync/trigger", json={"source": "all"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["synced"]["strava"] == 3
    assert body["synced"]["eight_sleep"] == 1
    assert body["synced"]["whoop"] == {
        "recovery_new": 2,
        "sleep_new": 1,
        "workouts_new": 0,
    }
    assert _LAST_ENGINE[-1].calls == ["sync_all"]


async def test_trigger_strava_routes_only_to_strava(client):
    _StubSyncEngine.per_source_counts = {"strava": 7}

    response = await client.post(
        "/api/sync/trigger", json={"source": "strava"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["synced"] == {"strava": 7}
    assert _LAST_ENGINE[-1].calls == ["sync_strava"]


async def test_trigger_unknown_source_returns_error_payload(client):
    response = await client.post(
        "/api/sync/trigger", json={"source": "garbage"}
    )

    assert response.status_code == 200
    assert response.json() == {"error": "Unknown source: garbage"}


# ── GET /api/sync/status ───────────────────────────────────────────────


async def test_status_reports_latest_sync_log_row_per_source(client, db):
    """Returns the most-recent sync_log row for each known source."""
    now = datetime.now(timezone.utc)
    older = now - timedelta(hours=2)

    db.add_all(
        [
            SyncLog(
                source="strava",
                sync_type="incremental",
                status="success",
                started_at=older,
                completed_at=older,
                records_synced=3,
                error_message=None,
            ),
            SyncLog(
                source="strava",
                sync_type="incremental",
                status="success",
                started_at=now,
                completed_at=now,
                records_synced=5,
                error_message=None,
            ),
            SyncLog(
                source="whoop",
                sync_type="incremental",
                status="success",
                started_at=now,
                completed_at=now,
                records_synced=2,
                error_message=None,
            ),
        ]
    )
    await db.commit()

    response = await client.get("/api/sync/status")

    assert response.status_code == 200
    body = response.json()
    assert body["strava"]["status"] == "success"
    # Most-recent row wins.
    assert body["strava"]["records_synced"] == 5
    assert body["whoop"]["records_synced"] == 2
    # Sources without any logs read as "never".
    assert body["eight_sleep"] == {"status": "never", "last_sync": None}
    assert body["weather"] == {"status": "never", "last_sync": None}
    # Enrichment / quota composite keys are always present.
    assert "strava_enrichment" in body
    assert "strava_quota" in body


# ── Error surfacing (audit-001 A6) ─────────────────────────────────────


@pytest.mark.xfail(
    strict=False,
    reason=(
        "audit-001 A6: backend/services/sync.py:56-60 (and the inner "
        "try/except in routers/sync.py:38-43) swallow per-source errors "
        "into the response dict but never write them to "
        "sync_log.error_message. W2-bug-A will fix this; once landed, "
        "this test becomes the regression gate."
    ),
)
async def test_trigger_surfaces_per_source_error_to_sync_log(client, db):
    """When a per-source sync raises, ``sync_log.error_message`` should
    contain the underlying error string — not the swallowed ``f"error: {e}"``
    string the response carries today.
    """
    _StubSyncEngine.raise_for = {"strava": RuntimeError("boom-token-expired")}

    response = await client.post(
        "/api/sync/trigger", json={"source": "strava"}
    )
    assert response.status_code == 200

    # The crucial assertion: a sync_log row was written with the underlying
    # error text. Today the router does not write a sync_log row at all on
    # this path; once W2-bug-A lifts the swallowing, this will pass.
    from sqlalchemy import select

    log = (
        await db.execute(
            select(SyncLog)
            .where(SyncLog.source == "strava")
            .order_by(SyncLog.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    assert log is not None
    assert log.status == "error"
    assert log.error_message is not None
    assert "boom-token-expired" in log.error_message
