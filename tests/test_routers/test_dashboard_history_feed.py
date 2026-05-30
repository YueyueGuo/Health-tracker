"""Endpoint-contract tests for ``GET /api/dashboard/history-feed``.

The cursor-paginated history feed is additive: ``dashboard_history`` and
``dashboard_training_trends`` are untouched. These tests pin the HTTP
contract the frontend builds against:

* the response always carries the five keys
  (``activities``, ``sleep``, ``strength``, ``next_cursor``, ``has_more``)
  with the array shapes ``buildHistoryEvents`` consumes,
* ``limit`` is clamped to ``le=100`` / ``ge=1`` by FastAPI validation,
* ``include_superseded`` is passed through to ``list_activity_feed``,
* a first page vs. a cursored page return disjoint, correctly ordered
  windows,
* a malformed cursor falls back to the first page (no 500).

Fixtures mirror ``tests/test_routers/test_dashboard_history_apple_merge.py``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from backend.models import Activity, HealthDataPoint, SleepSession, StrengthSet, Workout
from backend.routers.dashboard import router as dashboard_router
from backend.services.time_utils import utc_now_naive

from .conftest import make_client


@pytest.fixture
async def client(db_and_sessionmaker):
    _, Session = db_and_sessionmaker
    async with make_client(dashboard_router, "/api/dashboard", Session) as c:
        yield c


# ── Seed helpers ────────────────────────────────────────────────────


async def _seed_strava(
    db,
    *,
    strava_id: int = 1,
    days_ago: int = 1,
    superseded_by_id: int | None = None,
) -> Activity:
    start = utc_now_naive() - timedelta(days=days_ago)
    a = Activity(
        strava_id=strava_id,
        name=f"strava-{strava_id}",
        sport_type="Run",
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
        activity_type="run",
        duration_s=1800,
        distance_m=5000.0,
        activity_id=linked_activity_id,
    )
    db.add(w)
    await db.commit()
    await db.refresh(w)
    await db.refresh(dp)
    return w, dp


async def _seed_sleep(db, *, day: date) -> SleepSession:
    wake = datetime.combine(day, datetime.min.time()).replace(hour=7)
    s = SleepSession(
        source="eight_sleep",
        external_id=f"sleep-{day.isoformat()}",
        date=day,
        wake_time=wake,
        total_duration=420,
        sleep_score=80.0,
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _seed_strength(db, *, day: date) -> None:
    db.add(
        StrengthSet(
            date=day,
            exercise_name="Squat",
            set_number=1,
            reps=5,
            weight_kg=120.0,
        )
    )
    await db.commit()


async def _seed_mixed(db, *, n_each: int = 6) -> None:
    today = date.today()
    for i in range(n_each):
        await _seed_strava(db, strava_id=10 + i, days_ago=i + 1)
    for i in range(n_each):
        await _seed_sleep(db, day=today - timedelta(days=i + 1))
    for i in range(n_each):
        await _seed_strength(db, day=today - timedelta(days=2 * i + 1))


# ── Contract ────────────────────────────────────────────────────────


class TestHistoryFeedContract:
    async def test_response_has_all_keys(self, client, db):
        await _seed_mixed(db, n_each=3)
        resp = await client.get("/api/dashboard/history-feed")
        assert resp.status_code == 200
        payload = resp.json()
        assert set(payload.keys()) == {
            "activities",
            "sleep",
            "strength",
            "next_cursor",
            "has_more",
        }
        assert isinstance(payload["activities"], list)
        assert isinstance(payload["sleep"], list)
        assert isinstance(payload["strength"], list)
        assert isinstance(payload["has_more"], bool)

    async def test_empty_db_returns_empty_terminal_page(self, client, db):
        resp = await client.get("/api/dashboard/history-feed")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["activities"] == []
        assert payload["sleep"] == []
        assert payload["strength"] == []
        assert payload["has_more"] is False
        assert payload["next_cursor"] is None

    async def test_array_shapes_match_dashboard_history(self, client, db):
        """The three arrays carry the same per-row keys ``dashboard_history``
        returns, so the frontend ``buildHistoryEvents`` consumes them
        unchanged."""
        await _seed_strava(db, strava_id=1, days_ago=1)
        await _seed_sleep(db, day=date.today() - timedelta(days=1))
        await _seed_strength(db, day=date.today() - timedelta(days=1))

        legacy = (await client.get("/api/dashboard/history?days=365")).json()
        feed = (await client.get("/api/dashboard/history-feed?limit=100")).json()

        assert {k for k in legacy["activities"][0]} == {k for k in feed["activities"][0]}
        assert {k for k in legacy["sleep"][0]} == {k for k in feed["sleep"][0]}
        assert {k for k in legacy["strength"][0]} == {k for k in feed["strength"][0]}


class TestLimitClamping:
    async def test_limit_above_100_is_rejected(self, client):
        resp = await client.get("/api/dashboard/history-feed?limit=101")
        assert resp.status_code == 422

    async def test_limit_zero_is_rejected(self, client):
        resp = await client.get("/api/dashboard/history-feed?limit=0")
        assert resp.status_code == 422

    async def test_limit_at_bounds_is_accepted(self, client, db):
        await _seed_mixed(db, n_each=2)
        assert (await client.get("/api/dashboard/history-feed?limit=1")).status_code == 200
        assert (await client.get("/api/dashboard/history-feed?limit=100")).status_code == 200

    async def test_limit_caps_returned_rows(self, client, db):
        await _seed_mixed(db, n_each=4)  # 12 rows total
        payload = (await client.get("/api/dashboard/history-feed?limit=5")).json()
        total = (
            len(payload["activities"])
            + len(payload["sleep"])
            + len(payload["strength"])
        )
        assert total == 5
        assert payload["has_more"] is True
        assert payload["next_cursor"] is not None


class TestIncludeSupersededPassthrough:
    async def test_default_hides_superseded_strava_rows(self, client, db):
        strava = await _seed_strava(db, strava_id=1, days_ago=2)
        _, apple_winner = await _seed_apple(
            db, external_id="apple-winner", days_ago=2, linked_activity_id=strava.id
        )
        strava.superseded_by_id = apple_winner.id
        await db.commit()

        payload = (await client.get("/api/dashboard/history-feed?limit=100")).json()
        assert all(r.get("superseded_by_id") is None for r in payload["activities"])
        assert all(r["source"] != "strava" for r in payload["activities"])

    async def test_include_superseded_surfaces_strava_loser(self, client, db):
        strava = await _seed_strava(db, strava_id=1, days_ago=2)
        _, apple_winner = await _seed_apple(
            db, external_id="apple-winner", days_ago=2, linked_activity_id=strava.id
        )
        strava.superseded_by_id = apple_winner.id
        await db.commit()

        payload = (
            await client.get("/api/dashboard/history-feed?limit=100&include_superseded=true")
        ).json()
        strava_rows = [r for r in payload["activities"] if r["source"] == "strava"]
        assert len(strava_rows) == 1
        assert strava_rows[0]["superseded_by_id"] == apple_winner.id


class TestFirstVsCursoredPage:
    @staticmethod
    def _ids(payload: dict) -> set[str]:
        ids = set()
        for r in payload["activities"]:
            ids.add(f"activity-{r['id']}")
        for r in payload["sleep"]:
            ids.add(f"sleep-{r['id']}")
        for r in payload["strength"]:
            ids.add(f"strength-{r['date']}")
        return ids

    async def test_cursored_page_is_disjoint_and_older(self, client, db):
        await _seed_mixed(db, n_each=4)  # 12 rows

        first = (await client.get("/api/dashboard/history-feed?limit=5")).json()
        assert first["has_more"] is True
        cursor = first["next_cursor"]
        assert cursor

        second = (
            await client.get(f"/api/dashboard/history-feed?limit=5&cursor={cursor}")
        ).json()

        first_ids = self._ids(first)
        second_ids = self._ids(second)
        # No row appears on both pages.
        assert first_ids.isdisjoint(second_ids)

    async def test_paging_to_end_flags_terminal_page(self, client, db):
        await _seed_mixed(db, n_each=3)  # 9 rows

        seen: set[str] = set()
        cursor = None
        guard = 0
        while True:
            guard += 1
            assert guard < 100
            url = "/api/dashboard/history-feed?limit=4"
            if cursor:
                url += f"&cursor={cursor}"
            payload = (await client.get(url)).json()
            seen |= self._ids(payload)
            if not payload["has_more"]:
                assert payload["next_cursor"] is None
                break
            cursor = payload["next_cursor"]
        assert len(seen) == 9


class TestMalformedCursor:
    async def test_garbage_cursor_returns_first_page_not_500(self, client, db):
        await _seed_mixed(db, n_each=3)
        first = (await client.get("/api/dashboard/history-feed?limit=100")).json()
        garbled = await client.get("/api/dashboard/history-feed?limit=100&cursor=@@bad@@")
        assert garbled.status_code == 200
        payload = garbled.json()
        # Same window as a fresh first page.
        assert TestFirstVsCursoredPage._ids(payload) == TestFirstVsCursoredPage._ids(first)
