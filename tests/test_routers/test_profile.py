"""Tests for backend.routers.profile."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.models import UserProfile
from backend.routers.profile import router as profile_router

from .conftest import make_client


@pytest.fixture
async def client(db_and_sessionmaker):
    _, Session = db_and_sessionmaker
    async with make_client(profile_router, "/api/profile", Session) as c:
        yield c


async def test_get_profile_creates_singleton(client, db):
    resp = await client.get("/api/profile")
    assert resp.status_code == 200
    data = resp.json()
    assert data["displayName"] == ""
    assert data["email"] == ""
    assert data["vitals"]["maxHr"] == "192"

    row = (await db.execute(select(UserProfile))).scalar_one()
    assert row.id == 1
    assert isinstance(row.payload, dict)


async def test_patch_profile_merges_vitals(client):
    r1 = await client.get("/api/profile")
    assert r1.status_code == 200

    resp = await client.patch(
        "/api/profile",
        json={"vitals": {"weight": "180"}, "focus": "General Fitness"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["vitals"]["weight"] == "180"
    assert data["vitals"]["height"] == "5'10\""
    assert data["focus"] == "General Fitness"


async def test_patch_profile_persists_identity_fields(client, db):
    resp = await client.patch(
        "/api/profile",
        json={"displayName": "Yueyue", "email": "yueyue@example.com"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["displayName"] == "Yueyue"
    assert data["email"] == "yueyue@example.com"

    row = (await db.execute(select(UserProfile).where(UserProfile.id == 1))).scalar_one()
    assert row.payload["displayName"] == "Yueyue"
    assert row.payload["email"] == "yueyue@example.com"


async def test_patch_invalid_focus(client):
    resp = await client.patch("/api/profile", json={"focus": "Not A Real Focus"})
    assert resp.status_code == 422
