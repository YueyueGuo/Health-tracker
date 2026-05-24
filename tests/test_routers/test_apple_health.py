"""Tests for the Apple Health (HAE) ingestion router."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.config import settings
from backend.models import HealthDataPoint, Workout
from backend.routers.apple_health import router as apple_router

from .conftest import make_client


_TOKEN = "test-shared-secret"


@pytest.fixture
async def client(db_and_sessionmaker, monkeypatch):
    """Set a known ingest token + mount the router on a fresh app."""
    monkeypatch.setattr(settings.apple_health, "ingest_token", _TOKEN, raising=False)
    _, Session = db_and_sessionmaker
    async with make_client(apple_router, "/api/ingest/apple-health", Session) as c:
        yield c


def _payload(*, external_id: str = "apple-1", name: str = "Running") -> dict:
    return {
        "data": {
            "workouts": [
                {
                    "id": external_id,
                    "name": name,
                    "start": "2026-05-24 13:00:00 +0000",
                    "end": "2026-05-24 13:30:00 +0000",
                    "duration": 1800.0,
                    "distance": {"qty": 5000.0, "units": "m"},
                    "avgHeartRate": {"qty": 150, "units": "count/min"},
                }
            ]
        }
    }


# ── auth ────────────────────────────────────────────────────────────


async def test_workouts_rejects_missing_token(client):
    resp = await client.post("/api/ingest/apple-health/workouts", json=_payload())
    assert resp.status_code == 401


async def test_workouts_rejects_wrong_token(client):
    resp = await client.post(
        "/api/ingest/apple-health/workouts",
        json=_payload(),
        headers={"X-Apple-Health-Token": "definitely-wrong"},
    )
    assert resp.status_code == 401


async def test_503_when_server_token_blank(client, monkeypatch):
    # Misconfigured deploy: the server-side secret is empty. Better to
    # 503 than to silently accept any client token.
    monkeypatch.setattr(settings.apple_health, "ingest_token", "", raising=False)
    resp = await client.post(
        "/api/ingest/apple-health/workouts",
        json=_payload(),
        headers={"X-Apple-Health-Token": "anything"},
    )
    assert resp.status_code == 503


# ── happy path ──────────────────────────────────────────────────────


async def test_workouts_happy_path_creates_and_returns_result(client, db):
    resp = await client.post(
        "/api/ingest/apple-health/workouts",
        json=_payload(),
        headers={"X-Apple-Health-Token": _TOKEN},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "results" in body
    assert len(body["results"]) == 1
    result = body["results"][0]
    assert result["external_id"] == "apple-1"
    assert result["status"] == "created"
    assert result["workout_id"] is not None
    assert result["lap_count"] == 5  # 5 km @ 1 km

    hdp = (await db.execute(select(HealthDataPoint))).scalar_one()
    assert hdp.external_id == "apple-1"
    workout = (await db.execute(select(Workout))).scalar_one()
    assert workout.activity_type == "run"


async def test_workouts_replay_returns_updated(client):
    """Second POST of the same external_id reports ``updated``."""
    body = _payload()
    headers = {"X-Apple-Health-Token": _TOKEN}
    r1 = await client.post(
        "/api/ingest/apple-health/workouts", json=body, headers=headers
    )
    r2 = await client.post(
        "/api/ingest/apple-health/workouts", json=body, headers=headers
    )
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["results"][0]["status"] == "created"
    assert r2.json()["results"][0]["status"] == "updated"
    # Workout ids match — replay didn't create a second row.
    assert (
        r1.json()["results"][0]["workout_id"]
        == r2.json()["results"][0]["workout_id"]
    )


async def test_workouts_rejects_invalid_payload(client):
    resp = await client.post(
        "/api/ingest/apple-health/workouts",
        json={"data": {"workouts": [{"id": "x"}]}},  # missing required fields
        headers={"X-Apple-Health-Token": _TOKEN},
    )
    assert resp.status_code == 422


# ── /ping ───────────────────────────────────────────────────────────


async def test_ping_auth_required(client):
    assert (await client.post("/api/ingest/apple-health/ping")).status_code == 401


async def test_ping_returns_ok(client, db):
    resp = await client.post(
        "/api/ingest/apple-health/ping",
        headers={"X-Apple-Health-Token": _TOKEN},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    # No data should have landed.
    assert (await db.execute(select(HealthDataPoint))).scalars().all() == []
