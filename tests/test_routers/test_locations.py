"""Tests for backend.routers.locations."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.models import UserLocation
from backend.routers.locations import router as locations_router

from .conftest import make_client


@pytest.fixture
async def client(db_and_sessionmaker):
    _, Session = db_and_sessionmaker
    async with make_client(locations_router, "/api/locations", Session) as c:
        yield c


async def test_patch_location_elevation_to_null_clears_value(client):
    created = (await client.post(
        "/api/locations",
        json={
            "name": "Home",
            "lat": 40.0,
            "lng": -73.0,
            "elevation_m": 25.0,
        },
    )).json()

    resp = await client.patch(
        f"/api/locations/{created['id']}",
        json={"elevation_m": None},
    )

    assert resp.status_code == 200
    assert resp.json()["elevation_m"] is None


async def test_patch_location_omitted_elevation_keeps_value(client):
    created = (await client.post(
        "/api/locations",
        json={
            "name": "Home",
            "lat": 40.0,
            "lng": -73.0,
            "elevation_m": 25.0,
        },
    )).json()

    resp = await client.patch(
        f"/api/locations/{created['id']}",
        json={"name": "Gym"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Gym"
    assert data["elevation_m"] == 25.0


async def test_patch_location_coordinate_change_without_elevation_clears_value(
    client, db
):
    created = (await client.post(
        "/api/locations",
        json={
            "name": "Home",
            "lat": 40.0,
            "lng": -73.0,
            "elevation_m": 25.0,
        },
    )).json()

    resp = await client.patch(
        f"/api/locations/{created['id']}",
        json={"lat": 41.0},
    )

    assert resp.status_code == 200
    assert resp.json()["elevation_m"] is None
    loc = (await db.execute(
        select(UserLocation).where(UserLocation.id == created["id"])
    )).scalar_one()
    assert loc.lat == 41.0
    assert loc.elevation_m is None
