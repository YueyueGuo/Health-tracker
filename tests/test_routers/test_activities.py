"""Tests for GET /api/activities — superseded filter + source field.

Specifically exercises the Apple-Health-aware additions to the list
endpoint (see plan §7.11):
* ``include_superseded=False`` (default) hides Strava rows whose
  ``superseded_by_id`` is non-null.
* ``include_superseded=True`` returns them.
* The response carries ``source`` and ``external_id`` on every row.
* Apple-only workouts (no Strava back-link) appear alongside Strava
  rows, tagged with ``source='apple_health'``.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from backend.models import Activity, HealthDataPoint, Workout
from backend.routers.activities import router as activities_router
from backend.services.time_utils import utc_now_naive

from .conftest import make_client


@pytest.fixture
async def client(db_and_sessionmaker):
    _, Session = db_and_sessionmaker
    async with make_client(activities_router, "/api/activities", Session) as c:
        yield c


async def _seed_strava(
    db,
    *,
    strava_id: int = 1,
    sport_type: str = "Run",
    days_ago: int = 1,
    superseded_by_id: int | None = None,
) -> Activity:
    start = utc_now_naive() - timedelta(days=days_ago)
    a = Activity(
        strava_id=strava_id,
        name=f"strava-{strava_id}",
        sport_type=sport_type,
        start_date=start,
        start_date_local=start,
        enrichment_status="complete",
        superseded_by_id=superseded_by_id,
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


async def _seed_apple(
    db,
    *,
    external_id: str = "apple-1",
    activity_type: str = "run",
    days_ago: int = 0,
    linked_activity_id: int | None = None,
) -> tuple[Workout, HealthDataPoint]:
    start = utc_now_naive() - timedelta(days=days_ago)
    dp = HealthDataPoint(
        source="apple_health",
        data_type="workout",
        external_id=external_id,
        start_time=start,
    )
    db.add(dp)
    await db.flush()
    w = Workout(
        id=dp.id,
        activity_type=activity_type,
        duration_s=1800,
        distance_m=5000.0,
        activity_id=linked_activity_id,
    )
    db.add(w)
    await db.commit()
    await db.refresh(w)
    await db.refresh(dp)
    return w, dp


# ── source field on _activity_summary ──────────────────────────────


async def test_list_carries_source_and_external_id(client, db):
    a = await _seed_strava(db, strava_id=42)
    # Default ``source='strava'``/``external_id=str(strava_id)`` is set by
    # the before_insert event listener on Activity.
    resp = await client.get("/api/activities")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    row = body[0]
    assert row["source"] == "strava"
    assert row["external_id"] == str(a.strava_id)


# ── include_superseded filter ──────────────────────────────────────


async def test_apple_wins_dedup_shows_canonical_apple_row(client, db):
    """When Apple wins dedup, the canonical Apple row MUST be in the list.

    Previously the Apple query filtered ``activity_id IS NULL`` so the
    linked Apple workout was hidden while the Strava row was ALSO hidden
    (``superseded_by_id IS NOT NULL``). The canonical workout vanished.
    This test fails without the fix because no row is returned.
    """
    strava = await _seed_strava(db, strava_id=1)
    _, dp = await _seed_apple(db, external_id="a-1", linked_activity_id=strava.id)
    strava.superseded_by_id = dp.id
    await db.commit()

    resp = await client.get("/api/activities")
    assert resp.status_code == 200
    body = resp.json()

    # Exactly one canonical row — the Apple workout.
    assert len(body) == 1
    canonical = body[0]
    assert canonical["source"] == "apple_health"
    assert canonical["external_id"] == "a-1"
    assert canonical["id"] == dp.id
    # And the Strava loser is hidden.
    assert all(r["source"] != "strava" for r in body)


async def test_include_superseded_returns_both_strava_and_apple(client, db):
    """``include_superseded=true`` returns the Strava loser AND the
    canonical Apple winner — two rows for one conceptual workout."""
    strava = await _seed_strava(db, strava_id=1)
    _, dp = await _seed_apple(db, external_id="a-1", linked_activity_id=strava.id)
    strava.superseded_by_id = dp.id
    await db.commit()

    resp = await client.get("/api/activities?include_superseded=true")
    body = resp.json()

    strava_rows = [r for r in body if r["source"] == "strava"]
    apple_rows = [r for r in body if r["source"] == "apple_health"]
    assert len(strava_rows) == 1
    assert strava_rows[0]["superseded_by_id"] == dp.id
    assert len(apple_rows) == 1
    assert apple_rows[0]["external_id"] == "a-1"


async def test_no_duplicate_when_apple_only_and_winner_paths_disjoint(client, db):
    """Apple-only path (activity_id IS NULL) and Apple-winner path
    (activity_id IS NOT NULL) are disjoint — no row appears twice."""
    # Apple-only workout
    await _seed_apple(
        db, external_id="apple-only", activity_type="run", linked_activity_id=None
    )
    # Apple workout that won dedup
    strava = await _seed_strava(db, strava_id=2)
    _, dp = await _seed_apple(
        db, external_id="apple-winner", linked_activity_id=strava.id
    )
    strava.superseded_by_id = dp.id
    await db.commit()

    resp = await client.get("/api/activities")
    body = resp.json()
    external_ids = [r["external_id"] for r in body if r["source"] == "apple_health"]
    # Exactly two distinct Apple rows, no duplicates.
    assert sorted(external_ids) == ["apple-only", "apple-winner"]


# ── Apple-only workouts surface in the list ────────────────────────


async def test_apple_only_workouts_appear_with_apple_health_source(client, db):
    """An Apple workout with no Strava back-link must show up in the list."""
    await _seed_apple(
        db, external_id="apple-only", activity_type="run", linked_activity_id=None
    )
    resp = await client.get("/api/activities")
    body = resp.json()
    apple_rows = [r for r in body if r["source"] == "apple_health"]
    assert len(apple_rows) == 1
    assert apple_rows[0]["external_id"] == "apple-only"
    # Apple rows use the normalized sport label.
    assert apple_rows[0]["sport_type"] == "run"


async def test_mixed_list_sorts_by_start_date_desc(client, db):
    # Strava row older than the Apple row → Apple comes first.
    await _seed_strava(db, strava_id=1, days_ago=5)
    await _seed_apple(db, external_id="apple-fresh", days_ago=1)

    resp = await client.get("/api/activities")
    body = resp.json()
    assert len(body) == 2
    assert body[0]["source"] == "apple_health"
    assert body[1]["source"] == "strava"
