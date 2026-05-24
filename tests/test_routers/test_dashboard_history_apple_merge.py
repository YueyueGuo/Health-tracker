"""Regression tests for the Apple-Health merge + superseded-row filter
on the dashboard bundle endpoints.

These mirror the assertions exercised on ``/api/activities`` in
``test_activities.py``, but for the two callers that previously queried
the Strava ``activities`` table directly without going through the
shared ``list_activity_feed`` helper:

* ``GET /api/dashboard/history``
* ``GET /api/dashboard/training-trends``

Before the fix, both endpoints:
* hid Apple-only / Apple-winner workouts entirely (no merge), and
* returned Strava rows whose ``superseded_by_id`` was non-null.

Both behaviors are reproduced below — the tests fail on ``main`` and
pass on the branch.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from backend.models import Activity, HealthDataPoint, Workout
from backend.routers.dashboard import router as dashboard_router
from backend.services.time_utils import utc_now_naive

from .conftest import make_client


@pytest.fixture
async def client(db_and_sessionmaker):
    _, Session = db_and_sessionmaker
    async with make_client(dashboard_router, "/api/dashboard", Session) as c:
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


async def _seed_dedup_pair_plus_apple_only(db):
    """Seed one Apple+Strava dedup pair (Apple wins) and one Apple-only row.

    Returns ``(strava_loser, apple_winner_dp, apple_only_dp)``.
    """
    # The dedup pair: Strava row losing to Apple.
    strava = await _seed_strava(db, strava_id=1, days_ago=2)
    _, apple_winner_dp = await _seed_apple(
        db,
        external_id="apple-winner",
        days_ago=2,
        linked_activity_id=strava.id,
    )
    strava.superseded_by_id = apple_winner_dp.id
    await db.commit()

    # An unrelated Apple-only workout (no Strava back-link).
    _, apple_only_dp = await _seed_apple(
        db,
        external_id="apple-only",
        activity_type="run",
        days_ago=1,
        linked_activity_id=None,
    )
    return strava, apple_winner_dp, apple_only_dp


class TestDashboardHistoryAppleMerge:
    """Regression coverage for ``GET /api/dashboard/history``."""

    async def test_default_response_merges_apple_workouts(self, client, db):
        """Apple-only row AND the Apple winner of a deduped pair both
        appear in the default response, tagged ``source='apple_health'``.
        """
        _, apple_winner_dp, apple_only_dp = (
            await _seed_dedup_pair_plus_apple_only(db)
        )

        resp = await client.get("/api/dashboard/history?days=30")
        assert resp.status_code == 200
        payload = resp.json()
        apple_rows = [
            r for r in payload["activities"] if r["source"] == "apple_health"
        ]
        external_ids = sorted(r["external_id"] for r in apple_rows)
        assert external_ids == ["apple-only", "apple-winner"]
        # Each Apple row carries the HDP id as ``id``.
        ids = {r["id"] for r in apple_rows}
        assert ids == {apple_winner_dp.id, apple_only_dp.id}

    async def test_default_response_hides_superseded_strava_rows(
        self, client, db
    ):
        """No row with a non-null ``superseded_by_id`` is returned by
        default — the Strava loser is gone."""
        await _seed_dedup_pair_plus_apple_only(db)

        resp = await client.get("/api/dashboard/history?days=30")
        assert resp.status_code == 200
        payload = resp.json()
        assert all(
            r.get("superseded_by_id") is None for r in payload["activities"]
        )
        # And specifically: no ``strava`` row is in the response.
        assert all(r["source"] != "strava" for r in payload["activities"])

    async def test_include_superseded_returns_strava_loser_and_apple_rows(
        self, client, db
    ):
        """``?include_superseded=true`` surfaces both sides of the
        deduped pair AND the Apple-only row."""
        strava, apple_winner_dp, _ = await _seed_dedup_pair_plus_apple_only(db)

        resp = await client.get(
            "/api/dashboard/history?days=30&include_superseded=true"
        )
        assert resp.status_code == 200
        payload = resp.json()

        strava_rows = [
            r for r in payload["activities"] if r["source"] == "strava"
        ]
        apple_rows = [
            r for r in payload["activities"] if r["source"] == "apple_health"
        ]
        assert len(strava_rows) == 1
        assert strava_rows[0]["strava_id"] == strava.strava_id
        assert strava_rows[0]["superseded_by_id"] == apple_winner_dp.id

        external_ids = sorted(r["external_id"] for r in apple_rows)
        assert external_ids == ["apple-only", "apple-winner"]


class TestDashboardTrainingTrendsAppleMerge:
    """Same three assertions for ``GET /api/dashboard/training-trends``."""

    async def test_default_response_merges_apple_workouts(self, client, db):
        _, apple_winner_dp, apple_only_dp = (
            await _seed_dedup_pair_plus_apple_only(db)
        )

        resp = await client.get("/api/dashboard/training-trends?days=30")
        assert resp.status_code == 200
        payload = resp.json()
        apple_rows = [
            r for r in payload["activities"] if r["source"] == "apple_health"
        ]
        external_ids = sorted(r["external_id"] for r in apple_rows)
        assert external_ids == ["apple-only", "apple-winner"]
        ids = {r["id"] for r in apple_rows}
        assert ids == {apple_winner_dp.id, apple_only_dp.id}

    async def test_default_response_hides_superseded_strava_rows(
        self, client, db
    ):
        await _seed_dedup_pair_plus_apple_only(db)

        resp = await client.get("/api/dashboard/training-trends?days=30")
        assert resp.status_code == 200
        payload = resp.json()
        assert all(
            r.get("superseded_by_id") is None for r in payload["activities"]
        )
        assert all(r["source"] != "strava" for r in payload["activities"])

    async def test_include_superseded_returns_strava_loser_and_apple_rows(
        self, client, db
    ):
        strava, apple_winner_dp, _ = await _seed_dedup_pair_plus_apple_only(db)

        resp = await client.get(
            "/api/dashboard/training-trends?days=30&include_superseded=true"
        )
        assert resp.status_code == 200
        payload = resp.json()

        strava_rows = [
            r for r in payload["activities"] if r["source"] == "strava"
        ]
        apple_rows = [
            r for r in payload["activities"] if r["source"] == "apple_health"
        ]
        assert len(strava_rows) == 1
        assert strava_rows[0]["strava_id"] == strava.strava_id
        assert strava_rows[0]["superseded_by_id"] == apple_winner_dp.id

        external_ids = sorted(r["external_id"] for r in apple_rows)
        assert external_ids == ["apple-only", "apple-winner"]
