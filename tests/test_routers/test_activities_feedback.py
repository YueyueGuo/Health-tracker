"""Tests for PATCH /api/activities/{id}/feedback (RPE + notes)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backend.models import Activity
from backend.routers.activities import router as activities_router

from .conftest import make_client


@pytest.fixture
async def client(db_and_sessionmaker):
    _, Session = db_and_sessionmaker
    async with make_client(activities_router, "/api/activities", Session) as c:
        yield c


async def _seed_activity(db) -> Activity:
    start = datetime.utcnow() - timedelta(days=1)
    a = Activity(
        strava_id=12345,
        name="Morning run",
        sport_type="Run",
        start_date=start,
        start_date_local=start,
        moving_time=1800,
        distance=5000.0,
        enrichment_status="complete",
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


async def test_patch_feedback_sets_rpe_and_notes(client, db):
    a = await _seed_activity(db)
    resp = await client.patch(
        f"/api/activities/{a.id}/feedback",
        json={"rpe": 7, "user_notes": "felt strong"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["rpe"] == 7
    assert body["user_notes"] == "felt strong"
    assert body["rated_at"] is not None


async def test_patch_feedback_rejects_rpe_zero(client, db):
    a = await _seed_activity(db)
    resp = await client.patch(f"/api/activities/{a.id}/feedback", json={"rpe": 0})
    assert resp.status_code == 422


async def test_patch_feedback_rejects_rpe_eleven(client, db):
    a = await _seed_activity(db)
    resp = await client.patch(f"/api/activities/{a.id}/feedback", json={"rpe": 11})
    assert resp.status_code == 422


async def test_patch_feedback_accepts_range_bounds(client, db):
    a = await _seed_activity(db)
    r1 = await client.patch(f"/api/activities/{a.id}/feedback", json={"rpe": 1})
    r10 = await client.patch(f"/api/activities/{a.id}/feedback", json={"rpe": 10})
    assert r1.status_code == 200
    assert r10.status_code == 200
    assert r10.json()["rpe"] == 10


async def test_patch_feedback_clear_via_null(client, db):
    a = await _seed_activity(db)
    await client.patch(
        f"/api/activities/{a.id}/feedback",
        json={"rpe": 6, "user_notes": "ok"},
    )
    resp = await client.patch(
        f"/api/activities/{a.id}/feedback",
        json={"rpe": None, "user_notes": None},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["rpe"] is None
    assert body["user_notes"] is None


async def test_patch_feedback_partial_leaves_other_untouched(client, db):
    a = await _seed_activity(db)
    await client.patch(
        f"/api/activities/{a.id}/feedback",
        json={"rpe": 5, "user_notes": "initial"},
    )
    resp = await client.patch(
        f"/api/activities/{a.id}/feedback",
        json={"rpe": 8},
    )
    body = resp.json()
    assert body["rpe"] == 8
    assert body["user_notes"] == "initial"


async def test_patch_feedback_empty_body_rejected(client, db):
    a = await _seed_activity(db)
    resp = await client.patch(f"/api/activities/{a.id}/feedback", json={})
    assert resp.status_code == 400


async def test_patch_feedback_unknown_activity_404(client):
    resp = await client.patch("/api/activities/999/feedback", json={"rpe": 5})
    assert resp.status_code == 404
