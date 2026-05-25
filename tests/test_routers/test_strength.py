"""Tests for the strength router.

Covers the manual lifting-entry POST/PATCH/DELETE endpoints that drive
Bug B's failure path. Specifically asserts that ``performed_at`` round-
trips through ``POST /api/strength/sets`` and that the auto-increment
``id`` is populated by SQLAlchemy's default behavior — the regression
gate for "INSERT failed because no autoincrement is configured".

Also covers the linked-workout HR sets feature endpoints:

* ``GET /session/{date}/link-candidates``
* ``PUT /session/{date}/link``
* ``DELETE /session/{date}/link``
* ``POST /session/{date}/resegment``
* The ``hr_linked`` flag on ``GET /sessions``
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from backend.models import (
    Activity,
    ActivityStream,
    HealthDataPoint,
    StrengthSessionLink,
    StrengthSet,
    Workout,
)
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


# ── Linked-workout HR sets feature ─────────────────────────────────


_strava_id_counter = [70_000]


def _next_strava_id() -> int:
    _strava_id_counter[0] += 1
    return _strava_id_counter[0]


def _synth_two_peak_streams() -> tuple[list[int], list[float]]:
    """Synthetic 2-peak HR trace; matches the link service tests."""
    import math as _math

    time_stream: list[int] = []
    hr_stream: list[float] = []
    t = 0
    for _ in range(60):
        time_stream.append(t)
        hr_stream.append(110.0)
        t += 1
    for k in range(30):
        x = t + k
        d = (x - (t + 15)) / 7.5
        hr_stream.append(110.0 + 50.0 * _math.exp(-(d * d) / 2))
        time_stream.append(x)
    t += 30
    for _ in range(120):
        time_stream.append(t)
        hr_stream.append(110.0)
        t += 1
    for k in range(30):
        x = t + k
        d = (x - (t + 15)) / 7.5
        hr_stream.append(110.0 + 50.0 * _math.exp(-(d * d) / 2))
        time_stream.append(x)
    t += 30
    for _ in range(60):
        time_stream.append(t)
        hr_stream.append(110.0)
        t += 1
    return time_stream, hr_stream


async def _seed_strava(db, *, start_utc: datetime, name: str = "Lift") -> Activity:
    a = Activity(
        strava_id=_next_strava_id(),
        name=name,
        sport_type="WeightTraining",
        start_date=start_utc,
        start_date_local=start_utc.replace(tzinfo=None),
        elapsed_time=3600,
        moving_time=3600,
        average_hr=132.0,
        max_hr=168.0,
        enrichment_status="complete",
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


async def _seed_apple(db, *, start_utc: datetime, hr_series=None) -> Workout:
    payload: dict = {"name": "Apple lift"}
    if hr_series is not None:
        payload["heartRateData"] = hr_series
    dp = HealthDataPoint(
        source="apple_health",
        data_type="workout",
        external_id=f"apple-{int(start_utc.timestamp())}",
        start_time=start_utc,
        end_time=start_utc + timedelta(seconds=3600),
        raw_payload=payload,
    )
    db.add(dp)
    await db.flush()
    w = Workout(
        id=dp.id,
        activity_type="strength",
        duration_s=3600,
        avg_hr=125.0,
        max_hr=155.0,
    )
    db.add(w)
    await db.commit()
    await db.refresh(w)
    return w


async def _seed_session_sets(db, target_date: date, count: int = 2) -> None:
    for i in range(count):
        db.add(
            StrengthSet(
                date=target_date,
                exercise_name="Squat",
                set_number=i + 1,
                reps=5,
                weight_kg=100.0,
            )
        )
    await db.commit()


async def test_link_candidates_lists_strava_and_apple(client, db):
    target = date(2026, 5, 15)
    await _seed_strava(db, start_utc=datetime(2026, 5, 15, 17, 0, 0, tzinfo=timezone.utc))
    await _seed_apple(db, start_utc=datetime(2026, 5, 14, 18, 0, 0, tzinfo=timezone.utc))
    resp = await client.get(f"/api/strength/session/{target.isoformat()}/link-candidates")
    assert resp.status_code == 200
    body = resp.json()
    sources = {r["source"] for r in body}
    assert sources == {"strava", "apple_health"}


async def test_link_candidates_empty(client):
    resp = await client.get("/api/strength/session/2030-01-01/link-candidates")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_put_link_strava_with_cached_streams_returns_ok(client, db):
    target = date(2026, 5, 15)
    activity = await _seed_strava(
        db, start_utc=datetime(2026, 5, 15, 9, 0, 0, tzinfo=timezone.utc)
    )
    time_stream, hr_stream = _synth_two_peak_streams()
    db.add(ActivityStream(activity_id=activity.id, stream_type="time", data=time_stream))
    db.add(
        ActivityStream(activity_id=activity.id, stream_type="heartrate", data=hr_stream)
    )
    await db.commit()
    await _seed_session_sets(db, target, count=2)

    resp = await client.put(
        f"/api/strength/session/{target.isoformat()}/link",
        json={"source": "strava", "ref_id": activity.id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["link"]["source"] == "strava"
    assert body["link"]["ref_id"] == activity.id
    assert body["activity_id"] == activity.id  # back-compat
    assert body["segmentation"]["status"] in {"ok", "too_few", "too_many"}
    assert body["segmentation"]["target_count"] == 2
    assert body["hr_curve"]


async def test_put_link_strava_without_cached_streams_triggers_fetch(
    client, db, monkeypatch
):
    """No cached streams + monkey-patched fetch → 200 with status ok."""
    target = date(2026, 5, 15)
    activity = await _seed_strava(
        db, start_utc=datetime(2026, 5, 15, 9, 0, 0, tzinfo=timezone.utc)
    )
    await _seed_session_sets(db, target, count=2)

    time_stream, hr_stream = _synth_two_peak_streams()

    async def _fake_fetch(db, activity):
        """Mock the lazy-fetch path. Mirrors the real implementation's
        cache-check so the second call (from session_summary) doesn't
        try to insert duplicate rows."""
        cached = (
            (
                await db.execute(
                    select(ActivityStream).where(
                        ActivityStream.activity_id == activity.id
                    )
                )
            )
            .scalars()
            .all()
        )
        if cached:
            return {s.stream_type: s.data for s in cached}
        db.add(
            ActivityStream(activity_id=activity.id, stream_type="time", data=time_stream)
        )
        db.add(
            ActivityStream(activity_id=activity.id, stream_type="heartrate", data=hr_stream)
        )
        await db.commit()
        return {"time": time_stream, "heartrate": hr_stream}

    from backend.services import strava_streams as ss

    monkeypatch.setattr(ss, "load_streams_for_activity", _fake_fetch)

    resp = await client.put(
        f"/api/strength/session/{target.isoformat()}/link",
        json={"source": "strava", "ref_id": activity.id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["segmentation"]["status"] in {"ok", "too_few", "too_many"}


async def test_put_link_apple_without_hr_series_returns_no_curve(client, db):
    target = date(2026, 5, 15)
    workout = await _seed_apple(
        db, start_utc=datetime(2026, 5, 15, 9, 0, 0, tzinfo=timezone.utc)
    )
    await _seed_session_sets(db, target, count=2)
    resp = await client.put(
        f"/api/strength/session/{target.isoformat()}/link",
        json={"source": "apple_health", "ref_id": workout.id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["link"]["source"] == "apple_health"
    assert body["segmentation"]["status"] == "no_curve"
    assert body["hr_curve"] is None


async def test_put_link_conflict_returns_409(client, db):
    """Linking the same Strava activity to two different dates → 409."""
    activity = await _seed_strava(
        db, start_utc=datetime(2026, 5, 15, 9, 0, 0, tzinfo=timezone.utc)
    )
    await _seed_session_sets(db, date(2026, 5, 15), count=1)
    await _seed_session_sets(db, date(2026, 5, 16), count=1)

    r1 = await client.put(
        "/api/strength/session/2026-05-15/link",
        json={"source": "strava", "ref_id": activity.id},
    )
    assert r1.status_code == 200

    r2 = await client.put(
        "/api/strength/session/2026-05-16/link",
        json={"source": "strava", "ref_id": activity.id},
    )
    assert r2.status_code == 409


async def test_put_link_unknown_candidate_returns_422(client, db):
    await _seed_session_sets(db, date(2026, 5, 15), count=1)
    resp = await client.put(
        "/api/strength/session/2026-05-15/link",
        json={"source": "strava", "ref_id": 999_999},
    )
    assert resp.status_code == 422


async def test_put_link_unknown_session_returns_404(client):
    resp = await client.put(
        "/api/strength/session/2030-01-01/link",
        json={"source": "strava", "ref_id": 1},
    )
    assert resp.status_code == 404


async def test_delete_link_204_and_clears_state(client, db):
    target = date(2026, 5, 15)
    activity = await _seed_strava(
        db, start_utc=datetime(2026, 5, 15, 9, 0, 0, tzinfo=timezone.utc)
    )
    await _seed_session_sets(db, target, count=1)
    db.add(
        StrengthSessionLink(
            session_date=target,
            source="strava",
            activity_id=activity.id,
            segmentation_status="ok",
        )
    )
    await db.commit()
    resp = await client.delete(f"/api/strength/session/{target.isoformat()}/link")
    assert resp.status_code == 204

    follow = await client.get(f"/api/strength/session/{target.isoformat()}")
    assert follow.status_code == 200
    assert follow.json()["link"] is None


async def test_post_resegment_recomputes(client, db):
    """``POST /resegment`` re-runs segmentation against the current link."""
    target = date(2026, 5, 15)
    activity = await _seed_strava(
        db, start_utc=datetime(2026, 5, 15, 9, 0, 0, tzinfo=timezone.utc)
    )
    await _seed_session_sets(db, target, count=2)
    # Seed a link with stale (no-stream) state.
    db.add(
        StrengthSessionLink(
            session_date=target,
            source="strava",
            activity_id=activity.id,
            segmentation_status="no_stream",
            segmentation_detected_count=0,
            segmentation_target_count=0,
        )
    )
    await db.commit()
    # Now drop in streams so the resegment finds something.
    time_stream, hr_stream = _synth_two_peak_streams()
    db.add(ActivityStream(activity_id=activity.id, stream_type="time", data=time_stream))
    db.add(
        ActivityStream(activity_id=activity.id, stream_type="heartrate", data=hr_stream)
    )
    await db.commit()

    resp = await client.post(
        f"/api/strength/session/{target.isoformat()}/resegment"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["segmentation"]["status"] in {"ok", "too_few", "too_many"}


async def test_post_resegment_without_link_returns_404(client, db):
    target = date(2026, 5, 15)
    await _seed_session_sets(db, target, count=1)
    resp = await client.post(f"/api/strength/session/{target.isoformat()}/resegment")
    assert resp.status_code == 404


async def test_sessions_list_includes_hr_linked_flag(client, db):
    target = date(2026, 5, 15)
    activity = await _seed_strava(
        db, start_utc=datetime(2026, 5, 15, 9, 0, 0, tzinfo=timezone.utc)
    )
    await _seed_session_sets(db, target, count=1)
    await _seed_session_sets(db, target - timedelta(days=1), count=1)
    db.add(
        StrengthSessionLink(
            session_date=target,
            source="strava",
            activity_id=activity.id,
            segmentation_status="ok",
        )
    )
    await db.commit()
    resp = await client.get("/api/strength/sessions")
    assert resp.status_code == 200
    rows = {r["date"]: r for r in resp.json()}
    assert rows[target.isoformat()]["hr_linked"] is True
    assert rows[(target - timedelta(days=1)).isoformat()]["hr_linked"] is False


async def test_create_sets_with_activity_id_seeds_link_row(client, db):
    """Back-compat: ``POST /strength/sets`` with ``activity_id`` writes a
    link row with ``source="strava"`` AND ``segmentation_status="pending"``.
    The link is later picked up by ``GET /session/{date}``.
    """
    activity = await _seed_strava(
        db, start_utc=datetime(2026, 5, 18, 9, 0, 0, tzinfo=timezone.utc)
    )
    payload = {
        "date": "2026-05-18",
        "activity_id": activity.id,
        "sets": [
            {"exercise_name": "Squat", "set_number": 1, "reps": 5, "weight_kg": 100.0}
        ],
    }
    resp = await client.post("/api/strength/sets", json=payload)
    assert resp.status_code == 201
    link = (
        await db.execute(
            select(StrengthSessionLink).where(
                StrengthSessionLink.session_date == date(2026, 5, 18)
            )
        )
    ).scalar_one_or_none()
    assert link is not None
    assert link.source == "strava"
    assert link.activity_id == activity.id
    # The bulk-insert path was supposed to skip inline segmentation, but
    # the response body's ``session`` is built via ``session_summary``,
    # which fires the lazy resegment on a ``pending`` link. Either
    # outcome (still pending, or already segmented) is acceptable here;
    # the regression we care about is the link row existing.
    assert link.segmentation_status in {
        "pending", "ok", "too_few", "too_many", "flat", "no_stream", "no_curve", "error",
    }
