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


async def test_create_sets_accepts_omitted_performed_at(client, db):
    """Legacy-shape coverage: a POST that omits ``performed_at`` must
    persist with ``performed_at = NULL`` and round-trip the same way.

    Per ``backend/routers/strength.py`` ``StrengthSetInput.performed_at``
    docstring, rows without ``performed_at`` are still a supported shape
    (legacy clients pre-dating the column). This also guards against a
    regression where the router substitutes a default value for None.
    """
    payload = {
        "date": "2026-05-05",
        "activity_id": None,
        "sets": [
            {
                "exercise_name": "Front Squat",
                "set_number": 1,
                "reps": 5,
                "weight_kg": 90.0,
            }
        ],
    }

    response = await client.post("/api/strength/sets", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["created"] == 1
    assert body["session"]["sets"][0]["performed_at"] is None

    row = (
        await db.execute(select(StrengthSet).where(StrengthSet.date == date(2026, 5, 5)))
    ).scalar_one()
    assert row.performed_at is None


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
    """Regression gate for SQLAlchemy-level ``autoincrement=True``.

    The router never provides ``id`` on insert; on SQLite this works
    because ``INTEGER PRIMARY KEY`` autoincrements implicitly via ROWID.
    This test fails if the model loses its SQLAlchemy primary-key
    declaration entirely — but it does *not* exercise the real Bug B
    failure mode, which is a Postgres ``id bigint NOT NULL`` column
    with no IDENTITY / no DEFAULT. The Postgres-IDENTITY regression
    gate lives in ``tests/test_migrations_autoincrement_timezone.py``
    (audit-001 W2-bug-B).
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


# ── Superset + duration round-trip ────────────────────────────────────


async def test_create_sets_persists_superset_and_duration(client, db):
    """POST with ``superset_group_id`` on inputs + session-level
    ``started_at`` / ``ended_at`` → fields land on every row, surface in
    the GET payload, and the session aggregates are computed."""
    payload = {
        "date": "2026-05-10",
        "activity_id": None,
        "started_at": "2026-05-10T17:30:00",
        "ended_at": "2026-05-10T18:25:00",
        "sets": [
            {
                "exercise_name": "Bench",
                "set_number": 1,
                "reps": 5,
                "weight_kg": 80.0,
                "performed_at": "2026-05-10T17:35:00",
                "superset_group_id": 1,
                "order_index": 0,
            },
            {
                "exercise_name": "Row",
                "set_number": 1,
                "reps": 10,
                "weight_kg": 60.0,
                "performed_at": "2026-05-10T17:40:00",
                "superset_group_id": 1,
                "order_index": 1,
            },
            {
                "exercise_name": "Squat",
                "set_number": 1,
                "reps": 5,
                "weight_kg": 100.0,
                "performed_at": "2026-05-10T17:55:00",
                "order_index": 2,
            },
        ],
    }
    response = await client.post("/api/strength/sets", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["created"] == 3

    # GET round-trip.
    got = (await client.get("/api/strength/session/2026-05-10")).json()
    assert got["total_sets"] == 3
    assert got["total_reps"] == 5 + 10 + 5
    assert got["total_volume_kg"] == pytest.approx(5 * 80 + 10 * 60 + 5 * 100)
    assert got["exercise_count"] == 3
    assert got["duration_sec"] == 55 * 60
    assert got["started_at"].startswith("2026-05-10T17:30:00")
    assert got["ended_at"].startswith("2026-05-10T18:25:00")

    # Exercises ordered by order_index.
    names = [ex["name"] for ex in got["exercises"]]
    assert names == ["Bench", "Row", "Squat"]
    by_name = {ex["name"]: ex for ex in got["exercises"]}
    assert by_name["Bench"]["superset_group_id"] == 1
    assert by_name["Row"]["superset_group_id"] == 1
    assert by_name["Squat"]["superset_group_id"] is None
    # Per-set serialization carries the new fields.
    assert all(
        "superset_group_id" in s and "order_index" in s for s in got["sets"]
    )

    # DB rows actually persisted the denormalized session stamps.
    rows = (
        await db.execute(select(StrengthSet).where(StrengthSet.date == date(2026, 5, 10)))
    ).scalars().all()
    assert len(rows) == 3
    for r in rows:
        assert r.started_at is not None
        assert r.ended_at is not None
        assert r.started_at.replace(tzinfo=None) == datetime(2026, 5, 10, 17, 30, 0)
        assert r.ended_at.replace(tzinfo=None) == datetime(2026, 5, 10, 18, 25, 0)


async def test_patch_set_updates_superset_group_id(client, db):
    """PATCH can set / change ``superset_group_id`` and ``order_index``."""
    seed = StrengthSet(
        date=date(2026, 5, 11),
        exercise_name="Bench",
        set_number=1,
        reps=5,
        weight_kg=80.0,
    )
    db.add(seed)
    await db.commit()
    await db.refresh(seed)
    set_id = seed.id

    response = await client.patch(
        f"/api/strength/sets/{set_id}",
        json={"superset_group_id": 2, "order_index": 5},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["superset_group_id"] == 2
    assert body["order_index"] == 5

    await db.refresh(seed)
    assert seed.superset_group_id == 2
    assert seed.order_index == 5


async def test_session_get_exposes_new_top_level_keys(client):
    """Contract: every new top-level key from the strength workout-detail
    plan is present in the GET response, even when the values are null /
    derived from a single row.
    """
    payload = {
        "date": "2026-05-12",
        "activity_id": None,
        "sets": [
            {
                "exercise_name": "Squat",
                "set_number": 1,
                "reps": 5,
                "weight_kg": 100.0,
            }
        ],
    }
    create = await client.post("/api/strength/sets", json=payload)
    assert create.status_code == 201

    got = await client.get("/api/strength/session/2026-05-12")
    assert got.status_code == 200
    body = got.json()
    for key in (
        "date",
        "activity_id",
        "sets",
        "exercises",
        "duration_sec",
        "total_sets",
        "total_reps",
        "total_volume_kg",
        "exercise_count",
        "started_at",
        "ended_at",
    ):
        assert key in body, f"missing top-level key: {key}"
    # Aggregates for a one-set bodyweight-free session.
    assert body["total_sets"] == 1
    assert body["total_reps"] == 5
    assert body["total_volume_kg"] == pytest.approx(5 * 100)
    assert body["exercise_count"] == 1
    assert body["duration_sec"] is None
    assert body["started_at"] is None
    assert body["ended_at"] is None
    # Per-exercise carries the new fields too.
    assert "superset_group_id" in body["exercises"][0]
    assert "order_index" in body["exercises"][0]
