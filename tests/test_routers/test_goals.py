"""Tests for backend.routers.goals."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from backend.models import Goal
from backend.routers.goals import router as goals_router

from .conftest import make_client


@pytest.fixture
async def client(db_and_sessionmaker):
    _, Session = db_and_sessionmaker
    async with make_client(goals_router, "/api/goals", Session) as c:
        yield c


async def test_list_empty(client):
    resp = await client.get("/api/goals")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_create_goal(client):
    target = (date.today() + timedelta(weeks=10)).isoformat()
    resp = await client.post(
        "/api/goals",
        json={"race_type": "Marathon", "target_date": target, "is_primary": True},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["race_type"] == "Marathon"
    assert data["is_primary"] is True
    assert data["status"] == "active"


async def test_create_validates_race_type(client):
    target = (date.today() + timedelta(weeks=4)).isoformat()
    resp = await client.post(
        "/api/goals",
        json={"race_type": "", "target_date": target},
    )
    assert resp.status_code == 422


async def test_create_primary_clears_previous(client, db):
    target = (date.today() + timedelta(weeks=6)).isoformat()
    r1 = await client.post(
        "/api/goals",
        json={"race_type": "First", "target_date": target, "is_primary": True},
    )
    r2 = await client.post(
        "/api/goals",
        json={"race_type": "Second", "target_date": target, "is_primary": True},
    )
    assert r1.status_code == 201
    assert r2.status_code == 201

    # Only the second is primary now
    rows = (await db.execute(select(Goal).order_by(Goal.id))).scalars().all()
    assert [g.is_primary for g in rows] == [False, True]


async def test_patch_goal(client):
    target = (date.today() + timedelta(weeks=12)).isoformat()
    created = (await client.post(
        "/api/goals",
        json={"race_type": "Marathon", "target_date": target},
    )).json()
    goal_id = created["id"]

    new_target = (date.today() + timedelta(weeks=20)).isoformat()
    resp = await client.patch(
        f"/api/goals/{goal_id}",
        json={"race_type": "Half", "target_date": new_target, "status": "completed"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["race_type"] == "Half"
    assert data["target_date"] == new_target
    assert data["status"] == "completed"


async def test_patch_unknown_returns_404(client):
    resp = await client.patch("/api/goals/999", json={"race_type": "X"})
    assert resp.status_code == 404


async def test_set_primary_flips_others(client, db):
    target = (date.today() + timedelta(weeks=6)).isoformat()
    g1 = (await client.post(
        "/api/goals",
        json={"race_type": "A", "target_date": target, "is_primary": True},
    )).json()
    g2 = (await client.post(
        "/api/goals",
        json={"race_type": "B", "target_date": target, "is_primary": False},
    )).json()

    resp = await client.post(f"/api/goals/{g2['id']}/set-primary")
    assert resp.status_code == 200
    assert resp.json()["is_primary"] is True

    rows = {
        g.id: g.is_primary
        for g in (await db.execute(select(Goal))).scalars().all()
    }
    assert rows[g1["id"]] is False
    assert rows[g2["id"]] is True


async def test_delete_goal(client, db):
    target = (date.today() + timedelta(weeks=4)).isoformat()
    g = (await client.post(
        "/api/goals",
        json={"race_type": "X", "target_date": target},
    )).json()
    resp = await client.delete(f"/api/goals/{g['id']}")
    assert resp.status_code == 204
    rows = (await db.execute(select(Goal))).scalars().all()
    assert len(rows) == 0


async def test_delete_unknown_returns_404(client):
    resp = await client.delete("/api/goals/999")
    assert resp.status_code == 404
