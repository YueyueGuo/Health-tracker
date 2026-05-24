"""Tests for the strength router.

Covers the manual lifting-entry POST/PATCH/DELETE endpoints that drive
Bug B's failure path. Specifically asserts that ``performed_at`` round-
trips through ``POST /api/strength/sets`` and that the auto-increment
``id`` is populated by SQLAlchemy's default behavior — the regression
gate for "INSERT failed because no autoincrement is configured".
"""
from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import select

from backend.models import StrengthSet
import backend.routers.strength as strength_router_module

from .conftest import make_client


@pytest.fixture
async def client(db_and_sessionmaker):
    _, Session = db_and_sessionmaker
    async with make_client(
        strength_router_module.router, "/api/strength", Session
    ) as c:
        yield c


# ── POST /api/strength/sets ────────────────────────────────────────────


async def test_create_sets_round_trips_performed_at(client, db):
    """Bug B regression gate: ``performed_at`` is persisted and returned.

    The frontend stamps a naive-local ISO timestamp on every set; if the
    column is missing or the router drops it, the GET response will not
    echo it back.
    """
    performed_at = "2026-05-01T18:30:00"
    payload = {
        "date": "2026-05-01",
        "activity_id": None,
        "sets": [
            {
                "exercise_name": "Back Squat",
                "set_number": 1,
                "reps": 5,
                "weight_kg": 100.0,
                "performed_at": performed_at,
            }
        ],
    }

    response = await client.post("/api/strength/sets", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["created"] == 1
    session_sets = body["session"]["sets"]
    assert len(session_sets) == 1
    assert session_sets[0]["performed_at"].startswith("2026-05-01T18:30:00")

    # GET round-trip via /session/{date}.
    get_response = await client.get("/api/strength/session/2026-05-01")
    assert get_response.status_code == 200
    got = get_response.json()
    assert got["sets"][0]["performed_at"].startswith("2026-05-01T18:30:00")

    # Verify directly in DB too.
    row = (
        await db.execute(select(StrengthSet).where(StrengthSet.date == date(2026, 5, 1)))
    ).scalar_one()
    assert row.performed_at is not None
    assert row.performed_at.replace(tzinfo=None) == datetime(2026, 5, 1, 18, 30, 0)


async def test_create_sets_empty_list_returns_400(client):
    payload = {"date": "2026-05-01", "activity_id": None, "sets": []}
    response = await client.post("/api/strength/sets", json=payload)
    assert response.status_code == 400
    assert response.json()["detail"] == "At least one set required"


async def test_create_sets_negative_weight_returns_422(client):
    payload = {
        "date": "2026-05-01",
        "activity_id": None,
        "sets": [
            {
                "exercise_name": "Back Squat",
                "set_number": 1,
                "reps": 5,
                "weight_kg": -1.0,
            }
        ],
    }
    response = await client.post("/api/strength/sets", json=payload)
    assert response.status_code == 422


async def test_create_sets_set_number_less_than_one_returns_422(client):
    payload = {
        "date": "2026-05-01",
        "activity_id": None,
        "sets": [
            {
                "exercise_name": "Back Squat",
                "set_number": 0,
                "reps": 5,
                "weight_kg": 100.0,
            }
        ],
    }
    response = await client.post("/api/strength/sets", json=payload)
    assert response.status_code == 422


async def test_create_sets_auto_assigns_id(client, db):
    """Regression gate for Bug B's underlying cause.

    The router never provides ``id`` on insert; SQLAlchemy/SQLite's
    autoincrement is what makes the row land. If ``StrengthSet.id`` ever
    loses its ``autoincrement=True`` primary key (e.g. a column-mode
    migration that drops it on Postgres), INSERT will fail loudly here
    rather than silently in production.
    """
    payload = {
        "date": "2026-05-02",
        "activity_id": None,
        "sets": [
            {
                "exercise_name": "Bench Press",
                "set_number": 1,
                "reps": 5,
                "weight_kg": 80.0,
            }
        ],
    }

    response = await client.post("/api/strength/sets", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["created"] == 1
    inserted_id = body["session"]["sets"][0]["id"]
    assert inserted_id is not None
    assert isinstance(inserted_id, int)
    assert inserted_id > 0


# ── PATCH /api/strength/sets/{id} ──────────────────────────────────────


async def test_patch_set_updates_persisted_row(client, db):
    seed = StrengthSet(
        date=date(2026, 5, 3),
        exercise_name="Deadlift",
        set_number=1,
        reps=5,
        weight_kg=120.0,
    )
    db.add(seed)
    await db.commit()
    await db.refresh(seed)
    set_id = seed.id

    response = await client.patch(
        f"/api/strength/sets/{set_id}",
        json={"reps": 6, "weight_kg": 125.0, "notes": "felt strong"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reps"] == 6
    assert body["weight_kg"] == 125.0
    assert body["notes"] == "felt strong"

    await db.refresh(seed)
    assert seed.reps == 6
    assert seed.weight_kg == 125.0
    assert seed.notes == "felt strong"


async def test_patch_unknown_set_returns_404(client):
    response = await client.patch(
        "/api/strength/sets/999999",
        json={"reps": 6},
    )
    assert response.status_code == 404


# ── DELETE /api/strength/sets/{id} ─────────────────────────────────────


async def test_delete_set_removes_row(client, db):
    seed = StrengthSet(
        date=date(2026, 5, 4),
        exercise_name="Overhead Press",
        set_number=1,
        reps=5,
        weight_kg=50.0,
    )
    db.add(seed)
    await db.commit()
    await db.refresh(seed)
    set_id = seed.id

    response = await client.delete(f"/api/strength/sets/{set_id}")
    assert response.status_code == 204

    # Use a fresh session to confirm the delete committed (the fixture
    # ``db`` session caches the seeded instance).
    remaining = (
        await db.execute(select(StrengthSet).where(StrengthSet.id == set_id))
    ).scalar_one_or_none()
    assert remaining is None


async def test_delete_unknown_set_returns_404(client):
    response = await client.delete("/api/strength/sets/999999")
    assert response.status_code == 404
