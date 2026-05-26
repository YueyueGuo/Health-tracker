"""Tests for backend.routers.shoes + the shoe-tagging endpoint on
backend.routers.activities."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.database import get_db
from backend.models import Activity, HealthDataPoint, Shoe, Workout
from backend.routers.activities import router as activities_router
from backend.routers.shoes import router as shoes_router
from backend.services.time_utils import utc_now_naive

from .conftest import make_client


@pytest.fixture
async def client(db_and_sessionmaker):
    _, Session = db_and_sessionmaker
    async with make_client(shoes_router, "/api/shoes", Session) as c:
        yield c


@pytest.fixture
async def combined_client(db_and_sessionmaker):
    """A client wired with BOTH routers, so we can hit the
    ``/api/activities/{id}/shoe`` endpoint and create the shoe to tag
    in the same in-memory DB."""
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

    _, Session = db_and_sessionmaker
    app = FastAPI()
    app.include_router(shoes_router, prefix="/api/shoes")
    app.include_router(activities_router, prefix="/api/activities")

    async def _override() -> AsyncIterator[AsyncSession]:
        async with Session() as session:
            yield session

    app.dependency_overrides[get_db] = _override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ── Seed helpers ────────────────────────────────────────────────────


async def _seed_strava(
    db,
    *,
    strava_id: int = 1,
    distance: float = 5000.0,
    sport_type: str = "Run",
    shoe_id: int | None = None,
) -> Activity:
    start = utc_now_naive() - timedelta(days=1)
    a = Activity(
        strava_id=strava_id,
        name=f"strava-{strava_id}",
        sport_type=sport_type,
        start_date=start,
        start_date_local=start,
        distance=distance,
        shoe_id=shoe_id,
        enrichment_status="complete",
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


async def _seed_apple(
    db,
    *,
    external_id: str = "apple-1",
    distance_m: float = 5000.0,
    shoe_id: int | None = None,
) -> tuple[Workout, HealthDataPoint]:
    start = utc_now_naive() - timedelta(days=1)
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
        distance_m=distance_m,
        shoe_id=shoe_id,
    )
    db.add(w)
    await db.commit()
    await db.refresh(w)
    await db.refresh(dp)
    return w, dp


# ── List / empty state ──────────────────────────────────────────────


async def test_list_shoes_empty_returns_empty_array(client):
    """Frontend empty-state hinges on this contract: 200 [] when no
    shoes exist."""
    resp = await client.get("/api/shoes")
    assert resp.status_code == 200
    assert resp.json() == []


# ── Create ──────────────────────────────────────────────────────────


async def test_create_shoe_minimal(client):
    resp = await client.post("/api/shoes", json={"name": "Just a name"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Just a name"
    assert body["shoe_type"] == "everyday"
    assert body["status"] == "active"
    assert body["brand"] is None
    assert body["total_usable_distance_m"] is None
    assert body["cumulative_distance_m"] == 0.0
    assert body["percent_used"] is None


async def test_create_shoe_full(client):
    payload = {
        "name": "Vaporfly 3",
        "brand": "Nike",
        "model": "Alphafly Next% 3",
        "shoe_type": "race",
        "total_usable_distance_m": 800000.0,
        "purchased_on": date.today().isoformat(),
        "notes": "Race-day only",
    }
    resp = await client.post("/api/shoes", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    for k, v in payload.items():
        assert body[k] == v
    assert body["status"] == "active"
    assert body["percent_used"] == 0.0


async def test_create_shoe_invalid_type(client):
    resp = await client.post(
        "/api/shoes", json={"name": "Bad", "shoe_type": "rocket"}
    )
    assert resp.status_code == 422


async def test_create_shoe_negative_distance(client):
    resp = await client.post(
        "/api/shoes",
        json={"name": "Bad", "total_usable_distance_m": -1.0},
    )
    assert resp.status_code == 422


# ── Patch ───────────────────────────────────────────────────────────


async def test_patch_shoe_partial(client):
    created = (
        await client.post("/api/shoes", json={"name": "Old name", "brand": "Nike"})
    ).json()
    resp = await client.patch(
        f"/api/shoes/{created['id']}", json={"name": "New name"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "New name"
    # ``brand`` untouched
    assert body["brand"] == "Nike"


async def test_patch_shoe_does_not_change_status(client):
    """``status`` is not in the schema so submitting it is silently
    ignored by Pydantic (default behavior with no ``extra='forbid'``).
    The endpoint must NEVER change ``status`` through PATCH."""
    created = (
        await client.post("/api/shoes", json={"name": "X"})
    ).json()
    resp = await client.patch(
        f"/api/shoes/{created['id']}", json={"status": "retired", "name": "Y"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "active"
    assert body["name"] == "Y"


# ── Retire / unretire ───────────────────────────────────────────────


async def test_retire_shoe(client):
    created = (
        await client.post("/api/shoes", json={"name": "Retiree"})
    ).json()
    resp = await client.post(f"/api/shoes/{created['id']}/retire")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "retired"
    assert body["retired_at"] is not None


async def test_retire_is_idempotent(client):
    created = (
        await client.post("/api/shoes", json={"name": "Twice"})
    ).json()
    r1 = await client.post(f"/api/shoes/{created['id']}/retire")
    first_retired_at = r1.json()["retired_at"]
    r2 = await client.post(f"/api/shoes/{created['id']}/retire")
    assert r1.status_code == 200
    assert r2.status_code == 200
    # ``retired_at`` should not be re-stamped on the second call.
    assert r2.json()["retired_at"] == first_retired_at


async def test_unretire_shoe(client):
    created = (
        await client.post("/api/shoes", json={"name": "Comeback"})
    ).json()
    await client.post(f"/api/shoes/{created['id']}/retire")
    resp = await client.post(f"/api/shoes/{created['id']}/unretire")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "active"
    assert body["retired_at"] is None


# ── List filtering ──────────────────────────────────────────────────


async def test_list_default_active_only(client):
    a = (await client.post("/api/shoes", json={"name": "active"})).json()
    r = (await client.post("/api/shoes", json={"name": "retired"})).json()
    await client.post(f"/api/shoes/{r['id']}/retire")

    resp = await client.get("/api/shoes")
    ids = {row["id"] for row in resp.json()}
    assert a["id"] in ids
    assert r["id"] not in ids


async def test_list_status_filter(client):
    a = (await client.post("/api/shoes", json={"name": "active"})).json()
    r = (await client.post("/api/shoes", json={"name": "retired"})).json()
    await client.post(f"/api/shoes/{r['id']}/retire")

    retired_only = await client.get("/api/shoes?status=retired")
    assert {row["id"] for row in retired_only.json()} == {r["id"]}

    all_rows = await client.get("/api/shoes?status=all")
    assert {row["id"] for row in all_rows.json()} == {a["id"], r["id"]}


# ── Cumulative distance / percent used ──────────────────────────────


async def test_get_shoe_includes_cumulative_distance(client, db):
    shoe = Shoe(name="Mileage shoe")
    db.add(shoe)
    await db.commit()
    await db.refresh(shoe)

    await _seed_strava(db, strava_id=1, distance=10000.0, shoe_id=shoe.id)
    await _seed_strava(db, strava_id=2, distance=5000.0, shoe_id=shoe.id)

    resp = await client.get(f"/api/shoes/{shoe.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["cumulative_distance_m"] == pytest.approx(15000.0)
    assert body["tagged_activity_count"] == 2


async def test_get_shoe_untagged_activities_do_not_count(client, db):
    shoe = Shoe(name="X")
    db.add(shoe)
    await db.commit()
    await db.refresh(shoe)
    # Untagged
    await _seed_strava(db, strava_id=1, distance=9999.0, shoe_id=None)

    resp = await client.get(f"/api/shoes/{shoe.id}")
    body = resp.json()
    assert body["cumulative_distance_m"] == 0.0
    assert body["tagged_activity_count"] == 0


async def test_get_shoe_percent_used(client, db):
    shoe = Shoe(name="Pct", total_usable_distance_m=10000.0)
    db.add(shoe)
    await db.commit()
    await db.refresh(shoe)
    await _seed_strava(db, strava_id=1, distance=2500.0, shoe_id=shoe.id)

    resp = await client.get(f"/api/shoes/{shoe.id}")
    body = resp.json()
    assert body["percent_used"] == pytest.approx(25.0)


async def test_get_shoe_percent_used_null_when_no_target(client, db):
    shoe = Shoe(name="No target")  # total_usable_distance_m=None
    db.add(shoe)
    await db.commit()
    await db.refresh(shoe)
    await _seed_strava(db, strava_id=1, distance=5000.0, shoe_id=shoe.id)

    resp = await client.get(f"/api/shoes/{shoe.id}")
    assert resp.json()["percent_used"] is None


async def test_retired_shoe_still_reports_distance(client, db):
    shoe = Shoe(name="Old faithful", total_usable_distance_m=10000.0)
    db.add(shoe)
    await db.commit()
    await db.refresh(shoe)
    await _seed_strava(db, strava_id=1, distance=8000.0, shoe_id=shoe.id)

    await client.post(f"/api/shoes/{shoe.id}/retire")

    # Detail still reports the historical mileage.
    resp = await client.get(f"/api/shoes/{shoe.id}")
    body = resp.json()
    assert body["status"] == "retired"
    assert body["cumulative_distance_m"] == pytest.approx(8000.0)
    assert body["percent_used"] == pytest.approx(80.0)


# ── Tag / untag activity ────────────────────────────────────────────


async def test_tag_activity_with_shoe(combined_client, db_and_sessionmaker):
    _, Session = db_and_sessionmaker
    async with Session() as db:
        activity = await _seed_strava(db, strava_id=42, distance=5000.0)

    create = await combined_client.post("/api/shoes", json={"name": "Tagger"})
    shoe_id = create.json()["id"]

    resp = await combined_client.patch(
        f"/api/activities/{activity.id}/shoe", json={"shoe_id": shoe_id}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["shoe_id"] == shoe_id
    assert body["source"] == "strava"

    # Verify the shoe now reports the activity's distance.
    detail = await combined_client.get(f"/api/shoes/{shoe_id}")
    assert detail.json()["cumulative_distance_m"] == pytest.approx(5000.0)


async def test_untag_activity(combined_client, db_and_sessionmaker):
    """``shoe_id=null`` clears the tag — no retired check, no errors."""
    _, Session = db_and_sessionmaker
    create = await combined_client.post("/api/shoes", json={"name": "Untagger"})
    shoe_id = create.json()["id"]

    async with Session() as db:
        activity = await _seed_strava(
            db, strava_id=43, distance=3000.0, shoe_id=shoe_id
        )

    resp = await combined_client.patch(
        f"/api/activities/{activity.id}/shoe", json={"shoe_id": None}
    )
    assert resp.status_code == 200
    assert resp.json()["shoe_id"] is None

    # Cumulative drops back to zero.
    detail = await combined_client.get(f"/api/shoes/{shoe_id}")
    assert detail.json()["cumulative_distance_m"] == 0.0


async def test_tag_apple_workout_with_shoe(combined_client, db_and_sessionmaker):
    """Dual-resolution: id resolves to an Apple Workout via
    HealthDataPoint, not a Strava Activity. Mirrors the path exercised
    by ``test_activities_feedback.py``."""
    _, Session = db_and_sessionmaker
    async with Session() as db:
        _, dp = await _seed_apple(db, external_id="apple-tag-1", distance_m=4200.0)

    create = await combined_client.post("/api/shoes", json={"name": "Apple tagger"})
    shoe_id = create.json()["id"]

    resp = await combined_client.patch(
        f"/api/activities/{dp.id}/shoe", json={"shoe_id": shoe_id}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "apple_health"
    assert body["shoe_id"] == shoe_id

    detail = await combined_client.get(f"/api/shoes/{shoe_id}")
    assert detail.json()["cumulative_distance_m"] == pytest.approx(4200.0)


async def test_tag_nonexistent_activity_returns_404(combined_client):
    create = await combined_client.post("/api/shoes", json={"name": "404"})
    shoe_id = create.json()["id"]
    resp = await combined_client.patch(
        "/api/activities/9999/shoe", json={"shoe_id": shoe_id}
    )
    assert resp.status_code == 404


async def test_tag_nonexistent_shoe_returns_400(combined_client, db_and_sessionmaker):
    _, Session = db_and_sessionmaker
    async with Session() as db:
        activity = await _seed_strava(db, strava_id=44, distance=1000.0)

    resp = await combined_client.patch(
        f"/api/activities/{activity.id}/shoe", json={"shoe_id": 9999}
    )
    assert resp.status_code == 400


async def test_cannot_tag_retired_shoe(combined_client, db_and_sessionmaker):
    _, Session = db_and_sessionmaker
    async with Session() as db:
        activity = await _seed_strava(db, strava_id=45, distance=1000.0)

    create = await combined_client.post("/api/shoes", json={"name": "Retired"})
    shoe_id = create.json()["id"]
    await combined_client.post(f"/api/shoes/{shoe_id}/retire")

    resp = await combined_client.patch(
        f"/api/activities/{activity.id}/shoe", json={"shoe_id": shoe_id}
    )
    assert resp.status_code == 400
    assert "retired" in resp.json()["detail"].lower()


async def test_existing_tag_to_retired_shoe_is_preserved(
    combined_client, db_and_sessionmaker
):
    """Retiring a shoe must NOT clear pre-existing tags. Historical
    mileage stays on the shoe; future tags are blocked separately."""
    _, Session = db_and_sessionmaker
    create = await combined_client.post("/api/shoes", json={"name": "History"})
    shoe_id = create.json()["id"]

    async with Session() as db:
        activity = await _seed_strava(
            db, strava_id=46, distance=2500.0, shoe_id=shoe_id
        )

    await combined_client.post(f"/api/shoes/{shoe_id}/retire")

    async with Session() as db:
        row = (
            await db.execute(select(Activity).where(Activity.id == activity.id))
        ).scalar_one()
        assert row.shoe_id == shoe_id

    detail = await combined_client.get(f"/api/shoes/{shoe_id}")
    assert detail.json()["cumulative_distance_m"] == pytest.approx(2500.0)


# ── List activities for a shoe ──────────────────────────────────────


async def test_patch_shoe_clear_nullable_via_null(client):
    """PATCH with explicit ``null`` must clear the nullable columns.
    Regression: a prior ``if value is None: continue`` loop silently
    dropped these clears."""
    created = (
        await client.post(
            "/api/shoes",
            json={
                "name": "Clearable",
                "brand": "Nike",
                "model": "Pegasus",
                "total_usable_distance_m": 800000.0,
                "purchased_on": date.today().isoformat(),
                "notes": "abc",
            },
        )
    ).json()
    shoe_id = created["id"]

    # Sanity: everything is present after create.
    assert created["brand"] == "Nike"
    assert created["model"] == "Pegasus"
    assert created["total_usable_distance_m"] == 800000.0
    assert created["purchased_on"] == date.today().isoformat()
    assert created["notes"] == "abc"

    resp = await client.patch(
        f"/api/shoes/{shoe_id}",
        json={
            "notes": None,
            "brand": None,
            "model": None,
            "total_usable_distance_m": None,
            "purchased_on": None,
        },
    )
    assert resp.status_code == 200

    detail = await client.get(f"/api/shoes/{shoe_id}")
    body = detail.json()
    assert body["notes"] is None
    assert body["brand"] is None
    assert body["model"] is None
    assert body["total_usable_distance_m"] is None
    assert body["purchased_on"] is None


async def test_patch_shoe_null_name_rejected(client):
    """``name`` is non-nullable on the model; PATCHing ``{"name": null}``
    must come back as 422 rather than silently no-oping or 500-ing."""
    created = (
        await client.post("/api/shoes", json={"name": "Keep me"})
    ).json()
    resp = await client.patch(
        f"/api/shoes/{created['id']}", json={"name": None}
    )
    assert resp.status_code == 422


async def test_patch_shoe_null_shoe_type_rejected(client):
    """``shoe_type`` is non-nullable on the model. Pydantic's pattern
    validator does NOT reject ``None`` against ``str | None``, so the
    handler must guard it."""
    created = (
        await client.post("/api/shoes", json={"name": "Type test"})
    ).json()
    resp = await client.patch(
        f"/api/shoes/{created['id']}", json={"shoe_type": None}
    )
    assert resp.status_code == 422


async def test_unretire_is_idempotent(client):
    """Calling unretire twice on a never-retired shoe must stay 200 +
    active + retired_at=None on both calls."""
    created = (
        await client.post("/api/shoes", json={"name": "Never retired"})
    ).json()
    r1 = await client.post(f"/api/shoes/{created['id']}/unretire")
    r2 = await client.post(f"/api/shoes/{created['id']}/unretire")
    assert r1.status_code == 200
    assert r2.status_code == 200
    for body in (r1.json(), r2.json()):
        assert body["status"] == "active"
        assert body["retired_at"] is None


async def test_tag_activity_id_collision_no_source_defaults_to_strava(
    combined_client, db_and_sessionmaker
):
    """When a Strava ``Activity`` and an Apple ``HealthDataPoint`` share
    the same id AND the caller omits ``?source=``, the PATCH retains the
    legacy Strava-first / Apple-fallback resolution for back-compat with
    older clients. Explicit ``?source=apple_health`` callers (see the
    sibling collision tests below) bypass this default. Pin the
    no-source precedence so a future refactor can't silently flip it.
    """
    _, Session = db_and_sessionmaker
    collision_id = 777
    async with Session() as db:
        # Seed Apple first so we can force the HDP id, then seed a
        # Strava Activity with the same numeric id via direct insert.
        dp = HealthDataPoint(
            id=collision_id,
            source="apple_health",
            data_type="workout",
            external_id="apple-collision",
            start_time=utc_now_naive() - timedelta(days=1),
        )
        db.add(dp)
        await db.flush()
        w = Workout(
            id=dp.id,
            activity_type="run",
            duration_s=1800,
            distance_m=1111.0,
        )
        db.add(w)

        start = utc_now_naive() - timedelta(days=1)
        a = Activity(
            id=collision_id,
            strava_id=99999,
            name="strava-collision",
            sport_type="Run",
            start_date=start,
            start_date_local=start,
            distance=2222.0,
            enrichment_status="complete",
        )
        db.add(a)
        await db.commit()

    create = await combined_client.post(
        "/api/shoes", json={"name": "Collision shoe"}
    )
    shoe_id = create.json()["id"]

    resp = await combined_client.patch(
        f"/api/activities/{collision_id}/shoe", json={"shoe_id": shoe_id}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "strava"
    assert body["shoe_id"] == shoe_id


# Back-compat alias for any external module that imported the old name.
test_tag_activity_id_collision_strava_wins = (
    test_tag_activity_id_collision_no_source_defaults_to_strava
)


async def test_patch_shoe_with_source_apple_health_routes_to_workout_on_id_collision(
    combined_client, db_and_sessionmaker
):
    """Smoking-gun regression for the server-side persistence bug.

    With both an ``Activity`` and a ``HealthDataPoint``/``Workout`` at
    the same numeric id, an explicit ``?source=apple_health`` PATCH must
    write ``Workout.shoe_id`` (not the unrelated Strava row). A follow-
    up ``GET ...?source=apple_health`` must echo the shoe back, and the
    untouched Strava row must still report ``shoe_id=None``.
    """
    _, Session = db_and_sessionmaker
    collision_id = 778
    async with Session() as db:
        dp = HealthDataPoint(
            id=collision_id,
            source="apple_health",
            data_type="workout",
            external_id="apple-collision-explicit",
            start_time=utc_now_naive() - timedelta(days=1),
        )
        db.add(dp)
        await db.flush()
        w = Workout(
            id=dp.id,
            activity_type="run",
            duration_s=1800,
            distance_m=1111.0,
        )
        db.add(w)

        start = utc_now_naive() - timedelta(days=1)
        a = Activity(
            id=collision_id,
            strava_id=88888,
            name="strava-collision-explicit",
            sport_type="Run",
            start_date=start,
            start_date_local=start,
            distance=2222.0,
            enrichment_status="complete",
        )
        db.add(a)
        await db.commit()

    create = await combined_client.post(
        "/api/shoes", json={"name": "Apple-routed shoe"}
    )
    shoe_id = create.json()["id"]

    resp = await combined_client.patch(
        f"/api/activities/{collision_id}/shoe?source=apple_health",
        json={"shoe_id": shoe_id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "apple_health"
    assert body["shoe_id"] == shoe_id

    # GET the Apple side — the user-visible regression: the dropdown
    # rehydrates from this response on a fresh page load.
    apple_get = await combined_client.get(
        f"/api/activities/{collision_id}?source=apple_health"
    )
    assert apple_get.status_code == 200
    assert apple_get.json()["shoe_id"] == shoe_id

    # The unrelated Strava row at the same numeric id must NOT have
    # been mutated by the Apple-targeted PATCH.
    strava_get = await combined_client.get(
        f"/api/activities/{collision_id}?source=strava"
    )
    assert strava_get.status_code == 200
    assert strava_get.json()["shoe_id"] is None


async def test_patch_shoe_with_source_strava_routes_to_activity_on_id_collision(
    combined_client, db_and_sessionmaker
):
    """Symmetric to the Apple-routed collision test: an explicit
    ``?source=strava`` PATCH writes ``Activity.shoe_id`` and leaves the
    colliding Apple ``Workout`` row untouched."""
    _, Session = db_and_sessionmaker
    collision_id = 779
    async with Session() as db:
        dp = HealthDataPoint(
            id=collision_id,
            source="apple_health",
            data_type="workout",
            external_id="apple-collision-strava-side",
            start_time=utc_now_naive() - timedelta(days=1),
        )
        db.add(dp)
        await db.flush()
        w = Workout(
            id=dp.id,
            activity_type="run",
            duration_s=1800,
            distance_m=1111.0,
        )
        db.add(w)

        start = utc_now_naive() - timedelta(days=1)
        a = Activity(
            id=collision_id,
            strava_id=77777,
            name="strava-collision-strava-side",
            sport_type="Run",
            start_date=start,
            start_date_local=start,
            distance=2222.0,
            enrichment_status="complete",
        )
        db.add(a)
        await db.commit()

    create = await combined_client.post(
        "/api/shoes", json={"name": "Strava-routed shoe"}
    )
    shoe_id = create.json()["id"]

    resp = await combined_client.patch(
        f"/api/activities/{collision_id}/shoe?source=strava",
        json={"shoe_id": shoe_id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "strava"
    assert body["shoe_id"] == shoe_id

    strava_get = await combined_client.get(
        f"/api/activities/{collision_id}?source=strava"
    )
    assert strava_get.status_code == 200
    assert strava_get.json()["shoe_id"] == shoe_id

    # The colliding Apple workout row must NOT have been mutated.
    apple_get = await combined_client.get(
        f"/api/activities/{collision_id}?source=apple_health"
    )
    assert apple_get.status_code == 200
    assert apple_get.json()["shoe_id"] is None


async def test_patch_shoe_with_invalid_source_returns_400(
    combined_client, db_and_sessionmaker
):
    """Validation parity with ``GET /api/activities/{id}``: an unknown
    ``?source=`` value (e.g. ``garmin``) returns 400, not a confusing
    404 from the resolution branches."""
    _, Session = db_and_sessionmaker
    async with Session() as db:
        activity = await _seed_strava(db, strava_id=4242, distance=5000.0)

    create = await combined_client.post(
        "/api/shoes", json={"name": "Invalid-source shoe"}
    )
    shoe_id = create.json()["id"]

    resp = await combined_client.patch(
        f"/api/activities/{activity.id}/shoe?source=garmin",
        json={"shoe_id": shoe_id},
    )
    assert resp.status_code == 400


async def test_patch_shoe_then_get_activity_returns_shoe_id_strava(
    combined_client, db_and_sessionmaker
):
    """Round-trip regression for the shoe-mileage-frontend QA bug:
    after PATCH /api/activities/{id}/shoe persists the tag, a subsequent
    GET /api/activities/{id} must include ``shoe_id`` in the JSON so
    the frontend selector can rehydrate on reload (previously the field
    was omitted entirely, so the selector silently reset to "— None —").
    """
    _, Session = db_and_sessionmaker
    async with Session() as db:
        activity = await _seed_strava(db, strava_id=5001, distance=5000.0)

    create = await combined_client.post(
        "/api/shoes", json={"name": "Round-trip shoe"}
    )
    shoe_id = create.json()["id"]

    patch = await combined_client.patch(
        f"/api/activities/{activity.id}/shoe", json={"shoe_id": shoe_id}
    )
    assert patch.status_code == 200
    assert patch.json()["shoe_id"] == shoe_id

    # The bug: GET response did not echo ``shoe_id``. Fix emits it.
    detail = await combined_client.get(f"/api/activities/{activity.id}")
    assert detail.status_code == 200
    body = detail.json()
    assert "shoe_id" in body
    assert body["shoe_id"] == shoe_id

    # Untag — null clears, GET must reflect it.
    untag = await combined_client.patch(
        f"/api/activities/{activity.id}/shoe", json={"shoe_id": None}
    )
    assert untag.status_code == 200
    after = await combined_client.get(f"/api/activities/{activity.id}")
    assert after.json()["shoe_id"] is None


async def test_patch_shoe_then_get_activity_returns_shoe_id_apple(
    combined_client, db_and_sessionmaker
):
    """Same round-trip but for the Apple-Health (dual-resolved) path —
    ``_apple_workout_summary`` must also emit ``shoe_id``."""
    _, Session = db_and_sessionmaker
    async with Session() as db:
        _, dp = await _seed_apple(
            db, external_id="apple-roundtrip", distance_m=4200.0
        )

    create = await combined_client.post(
        "/api/shoes", json={"name": "Apple round-trip shoe"}
    )
    shoe_id = create.json()["id"]

    patch = await combined_client.patch(
        f"/api/activities/{dp.id}/shoe", json={"shoe_id": shoe_id}
    )
    assert patch.status_code == 200
    assert patch.json()["source"] == "apple_health"
    assert patch.json()["shoe_id"] == shoe_id

    detail = await combined_client.get(f"/api/activities/{dp.id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["source"] == "apple_health"
    assert "shoe_id" in body
    assert body["shoe_id"] == shoe_id


async def test_list_activities_for_shoe(client, db):
    shoe = Shoe(name="Listing shoe")
    db.add(shoe)
    await db.commit()
    await db.refresh(shoe)

    await _seed_strava(db, strava_id=101, distance=4000.0, shoe_id=shoe.id)
    await _seed_apple(db, external_id="apple-list-1", distance_m=6000.0, shoe_id=shoe.id)
    # Untagged — should NOT show up.
    await _seed_strava(db, strava_id=102, distance=1.0, shoe_id=None)

    resp = await client.get(f"/api/shoes/{shoe.id}/activities")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    sources = sorted(item["source"] for item in body["items"])
    assert sources == ["apple", "strava"]
    distances = sorted(item["distance_m"] for item in body["items"])
    assert distances == [4000.0, 6000.0]
