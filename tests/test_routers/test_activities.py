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
    # Apple rows emit the CamelCase Strava-style label so the frontend's
    # ``classifyActivity`` switch resolves to ``Run`` (the normalized
    # "run" form wouldn't trigger the Run-specific detail view).
    assert apple_rows[0]["sport_type"] == "Run"
    # Apple workouts report ``enrichment_status == "complete"`` — the
    # frontend renders any other value as a raw status pill next to the
    # source badge, and there's no Strava-style Phase-B enrichment to do
    # for Apple rows. Updated from the previous ``"apple_health"`` value
    # that was leaking into the UI as a literal pill.
    assert apple_rows[0]["enrichment_status"] == "complete"
    # ``start_date_local`` must be an ISO-8601 string so the frontend's
    # ``formatActivityDateTime`` can render the date subtitle. HAE only
    # exposes a UTC ``start_time``; we pass it through and let the
    # client format it in the viewer's local TZ.
    assert apple_rows[0]["start_date_local"] is not None
    assert isinstance(apple_rows[0]["start_date_local"], str)


async def test_mixed_list_sorts_by_start_date_desc(client, db):
    # Strava row older than the Apple row → Apple comes first.
    await _seed_strava(db, strava_id=1, days_ago=5)
    await _seed_apple(db, external_id="apple-fresh", days_ago=1)

    resp = await client.get("/api/activities")
    body = resp.json()
    assert len(body) == 2
    assert body[0]["source"] == "apple_health"
    assert body[1]["source"] == "strava"


# ── GET /activities/{id} — Apple fallback ───────────────────────────


async def test_get_activity_resolves_strava_id_first(client, db):
    a = await _seed_strava(db, strava_id=77)
    resp = await client.get(f"/api/activities/{a.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "strava"
    assert body["id"] == a.id
    # ``shoe_id`` must be emitted (null when no shoe is tagged) so the
    # frontend's shoe selector can render the current state on reload.
    # Regression for PR #65 / shoe-mileage-frontend QA: GET response
    # was omitting the field entirely.
    assert "shoe_id" in body
    assert body["shoe_id"] is None


async def test_get_activity_falls_back_to_apple_workout(client, db):
    """When no Strava row matches the id, fall back to the Apple workout."""
    _, dp = await _seed_apple(db, external_id="apple-detail", activity_type="run")
    resp = await client.get(f"/api/activities/{dp.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "apple_health"
    assert body["id"] == dp.id
    # CamelCase sport_type so frontend's classifyActivity resolves to Run.
    assert body["sport_type"] == "Run"
    # Detail-page extras present even for Apple.
    assert "laps" in body
    assert "zones" in body
    assert body["pace_hr_decoupling"] is None
    assert body["power_hr_decoupling"] is None
    # ``enrichment_status`` is "complete" (not "apple_health") so the
    # frontend's ``ActivityHeader`` doesn't render a raw status pill.
    assert body["enrichment_status"] == "complete"
    # ``start_date_local`` is populated so the date subtitle renders.
    assert body["start_date_local"] is not None
    assert isinstance(body["start_date_local"], str)
    # ``shoe_id`` must be emitted on Apple summaries too (null when no
    # shoe is tagged) — the frontend selector lives on the dual-resolved
    # ``ActivityDetail`` page and needs the field for both source types.
    assert "shoe_id" in body
    assert body["shoe_id"] is None


async def test_get_activity_404_when_neither_strava_nor_apple(client, db):
    resp = await client.get("/api/activities/99999")
    assert resp.status_code == 404


# ── GET /activities/{id}/streams — Apple reconstruction ─────────────


async def test_streams_for_apple_reconstructed_from_raw_payload(client, db):
    """HR series in ``raw_payload.heartRateData`` becomes ``{heartrate, time}``."""
    _, dp = await _seed_apple(db, external_id="apple-streams")
    # Populate the HR series on the DP we just seeded.
    dp.raw_payload = {
        "heartRateData": [
            {"date": "2026-05-24 13:14:01 -0400", "qty": 124, "units": "count/min"},
            {"date": "2026-05-24 13:14:02 -0400", "qty": 132, "units": "count/min"},
            {"date": "2026-05-24 13:14:03 -0400", "qty": 145, "units": "count/min"},
        ]
    }
    await db.commit()

    resp = await client.get(f"/api/activities/{dp.id}/streams")
    assert resp.status_code == 200
    body = resp.json()
    assert "heartrate" in body
    assert "time" in body
    assert body["heartrate"] == [124.0, 132.0, 145.0]
    # Time series is monotonically increasing, starts at 0.
    assert body["time"][0] == 0.0
    assert body["time"][-1] > 0
    # No velocity stream when route lacks per-sample speed.
    assert "velocity_smooth" not in body


async def test_streams_for_apple_returns_empty_dict_when_no_series(client, db):
    """No heartRateData and no route speed → empty payload, never a Strava call."""
    _, dp = await _seed_apple(db, external_id="apple-no-series")
    dp.raw_payload = {"name": "Running"}
    await db.commit()
    resp = await client.get(f"/api/activities/{dp.id}/streams")
    assert resp.status_code == 200
    assert resp.json() == {}


async def test_streams_for_apple_reconstructs_velocity_smooth_from_route(client, db):
    """HAE ``route[*].speed`` becomes the ``velocity_smooth`` stream entry.

    The reconstructor in ``_maybe_apple_streams`` walks the route array
    for a per-sample ``speed`` field; this test pins the contract so a
    refactor doesn't silently drop the pace stream.
    """
    _, dp = await _seed_apple(db, external_id="apple-velocity")
    dp.raw_payload = {"route": [{"speed": 2.5}, {"speed": 3.0}]}
    await db.commit()

    resp = await client.get(f"/api/activities/{dp.id}/streams")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("velocity_smooth") == [2.5, 3.0]


async def test_streams_404_when_neither_strava_nor_apple(client, db):
    resp = await client.get("/api/activities/99999/streams")
    assert resp.status_code == 404


# ── POST /activities/{id}/classify — Apple no-op ────────────────────


async def test_classify_returns_not_classified_for_apple(client, db):
    """The classifier is Strava-only — Apple ids surface a soft no-op."""
    _, dp = await _seed_apple(db, external_id="apple-classify")
    resp = await client.post(f"/api/activities/{dp.id}/classify")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "classified": False,
        "reason": "apple_health workouts are not classified yet",
    }


async def test_classify_404_when_neither_strava_nor_apple(client, db):
    resp = await client.post("/api/activities/99999/classify")
    assert resp.status_code == 404


# ── GET /activities/{id}?source=… — collision disambiguation ───────
#
# Regression for ``docs/bugs/apple-watch-routing-collision.md``: when an
# ``activities.id`` collides with a ``health_data_points.id`` from
# Apple Health, the legacy resolver always returns the Strava row. The
# ``source`` query param disambiguates without breaking back-compat.


async def _seed_colliding_pair(db, *, collision_id: int) -> tuple[Activity, HealthDataPoint]:
    """Seed a Strava row AND an Apple workout sharing the same integer id.

    The two tables autoincrement independently in production, so we set
    ``id`` explicitly on both inserts to reproduce the collision in a
    deterministic way. The Apple side uses joined-table inheritance —
    ``Workout.id`` is both PK and FK back to ``health_data_points.id``,
    so the ``Workout`` row also gets the collision id.
    """
    start = utc_now_naive() - timedelta(days=1)
    strava = Activity(
        id=collision_id,
        strava_id=900_000 + collision_id,
        name=f"strava-{collision_id}",
        sport_type="Ride",
        start_date=start,
        start_date_local=start,
        enrichment_status="complete",
    )
    db.add(strava)
    await db.flush()

    dp = HealthDataPoint(
        id=collision_id,
        source="apple_health",
        data_type="workout",
        external_id=f"apple-collide-{collision_id}",
        start_time=start,
    )
    db.add(dp)
    await db.flush()
    w = Workout(
        id=dp.id,
        activity_type="strength",
        duration_s=1800,
        distance_m=None,
    )
    db.add(w)
    await db.commit()
    await db.refresh(strava)
    await db.refresh(dp)
    return strava, dp


async def test_get_activity_collision_defaults_to_strava(client, db):
    """Back-compat: no ``source`` → Strava row wins on collision."""
    strava, dp = await _seed_colliding_pair(db, collision_id=12345)
    assert strava.id == dp.id  # sanity: collision is real
    resp = await client.get(f"/api/activities/{strava.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "strava"
    assert body["id"] == strava.id


async def test_get_activity_collision_source_apple_returns_apple(client, db):
    """``?source=apple_health`` returns the Apple row even when a Strava
    row with the same id exists."""
    strava, dp = await _seed_colliding_pair(db, collision_id=12346)
    resp = await client.get(
        f"/api/activities/{strava.id}?source=apple_health"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "apple_health"
    assert body["id"] == dp.id
    assert body["external_id"] == f"apple-collide-{dp.id}"


async def test_get_activity_collision_source_strava_returns_strava(client, db):
    """``?source=strava`` returns the Strava row explicitly."""
    strava, _ = await _seed_colliding_pair(db, collision_id=12347)
    resp = await client.get(f"/api/activities/{strava.id}?source=strava")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "strava"
    assert body["id"] == strava.id


async def test_get_activity_source_apple_404_when_only_strava_exists(client, db):
    """``?source=apple_health`` MUST NOT fall through to the Strava row.

    Without the fix, this 404 path would never be reached: the resolver
    would either return the Strava row (back-compat) or, with the param
    ignored, also return the Strava row. The explicit source forces an
    Apple lookup that misses.
    """
    strava = await _seed_strava(db, strava_id=998)
    resp = await client.get(
        f"/api/activities/{strava.id}?source=apple_health"
    )
    assert resp.status_code == 404


async def test_get_activity_source_strava_404_when_only_apple_exists(client, db):
    """``?source=strava`` MUST NOT fall through to the Apple row."""
    _, dp = await _seed_apple(db, external_id="apple-strava-strict")
    resp = await client.get(f"/api/activities/{dp.id}?source=strava")
    assert resp.status_code == 404


async def test_get_activity_invalid_source_returns_400(client, db):
    resp = await client.get("/api/activities/1?source=garmin")
    assert resp.status_code == 400


# ── GET /activities/{id}/streams?source=… — same matrix ────────────


async def test_streams_collision_defaults_to_strava(client, db):
    """Back-compat: no ``source`` → streams resolves Strava-first on collision.

    Strava has no cached streams here, so the lazy fetcher would try to
    hit the API. We stub it via the cached path: insert an empty
    ``ActivityStream`` row so the load helper returns from cache. The
    important assertion is that we DID NOT fall through to the Apple
    branch (which would return the HR series from ``raw_payload``).
    """
    strava, dp = await _seed_colliding_pair(db, collision_id=22345)
    # Seed Apple HR series; if the resolver fell through to Apple, we'd
    # see this back.
    dp.raw_payload = {
        "heartRateData": [
            {"date": "2026-05-24 13:14:01 -0400", "qty": 124, "units": "count/min"},
        ]
    }
    # Strava cache hit — empty time series, but the cached-streams path
    # returns it without an outbound Strava call.
    from backend.models import ActivityStream

    db.add(ActivityStream(activity_id=strava.id, stream_type="time", data=[0, 1, 2]))
    await db.commit()

    resp = await client.get(f"/api/activities/{strava.id}/streams")
    assert resp.status_code == 200
    body = resp.json()
    # Strava cache returns ``time`` series we just inserted, NOT the
    # Apple ``heartrate`` reconstruction.
    assert body.get("time") == [0, 1, 2]
    assert "heartrate" not in body


async def test_streams_collision_source_apple_returns_apple_series(client, db):
    """``?source=apple_health`` returns the Apple HR reconstruction even
    when a Strava row (with its own cached streams) shares the id."""
    strava, dp = await _seed_colliding_pair(db, collision_id=22346)
    dp.raw_payload = {
        "heartRateData": [
            {"date": "2026-05-24 13:14:01 -0400", "qty": 124, "units": "count/min"},
            {"date": "2026-05-24 13:14:02 -0400", "qty": 132, "units": "count/min"},
        ]
    }
    from backend.models import ActivityStream

    db.add(ActivityStream(activity_id=strava.id, stream_type="time", data=[0, 1, 2]))
    await db.commit()

    resp = await client.get(
        f"/api/activities/{strava.id}/streams?source=apple_health"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("heartrate") == [124.0, 132.0]
    # The Strava cached ``time`` series must NOT be returned.
    assert body.get("time") != [0, 1, 2]


async def test_streams_collision_source_strava_returns_strava(client, db):
    """``?source=strava`` returns the Strava-cached streams explicitly."""
    strava, dp = await _seed_colliding_pair(db, collision_id=22347)
    dp.raw_payload = {
        "heartRateData": [
            {"date": "2026-05-24 13:14:01 -0400", "qty": 200, "units": "count/min"},
        ]
    }
    from backend.models import ActivityStream

    db.add(
        ActivityStream(activity_id=strava.id, stream_type="heartrate", data=[80, 90])
    )
    await db.commit()

    resp = await client.get(
        f"/api/activities/{strava.id}/streams?source=strava"
    )
    assert resp.status_code == 200
    body = resp.json()
    # Strava cached HR, NOT the Apple HR series of [200.0].
    assert body.get("heartrate") == [80, 90]


async def test_streams_source_apple_404_when_only_strava_exists(client, db):
    """``?source=apple_health`` MUST NOT fall through to Strava streams."""
    strava = await _seed_strava(db, strava_id=997)
    resp = await client.get(
        f"/api/activities/{strava.id}/streams?source=apple_health"
    )
    assert resp.status_code == 404


async def test_streams_source_strava_404_when_only_apple_exists(client, db):
    """``?source=strava`` MUST NOT fall through to the Apple HR series."""
    _, dp = await _seed_apple(db, external_id="apple-streams-strict")
    dp.raw_payload = {
        "heartRateData": [
            {"date": "2026-05-24 13:14:01 -0400", "qty": 124, "units": "count/min"},
        ]
    }
    await db.commit()
    resp = await client.get(
        f"/api/activities/{dp.id}/streams?source=strava"
    )
    assert resp.status_code == 404


async def test_streams_invalid_source_returns_400(client, db):
    resp = await client.get("/api/activities/1/streams?source=garmin")
    assert resp.status_code == 400


# ── GET /activities/{id} — shoe_id emitted on summary ──────────────
#
# Regression for the shoe-mileage-frontend QA gap: PATCH /shoe persists
# the FK but the GET response was omitting ``shoe_id`` entirely, so the
# frontend's selector re-rendered as "— None —" after reload and the
# user's selection appeared lost. The serializer just forgot the field.


async def test_get_strava_activity_includes_shoe_id_when_tagged(client, db):
    """``GET /api/activities/{id}`` must surface ``shoe_id`` for Strava
    rows so the frontend can hydrate the shoe selector on reload."""
    from backend.models import Shoe

    shoe = Shoe(name="Pegasus")
    db.add(shoe)
    await db.commit()
    await db.refresh(shoe)

    a = await _seed_strava(db, strava_id=4242)
    a.shoe_id = shoe.id
    await db.commit()

    resp = await client.get(f"/api/activities/{a.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "strava"
    assert body["shoe_id"] == shoe.id


async def test_get_apple_workout_includes_shoe_id_when_tagged(client, db):
    """Same contract for the Apple-Health (dual-resolved) path:
    ``_apple_workout_summary`` must emit ``shoe_id`` from the Workout."""
    from backend.models import Shoe

    shoe = Shoe(name="Endorphin Speed")
    db.add(shoe)
    await db.commit()
    await db.refresh(shoe)

    w, dp = await _seed_apple(db, external_id="apple-shoe-detail")
    w.shoe_id = shoe.id
    await db.commit()

    resp = await client.get(f"/api/activities/{dp.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "apple_health"
    assert body["shoe_id"] == shoe.id
