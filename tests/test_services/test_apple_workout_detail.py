"""Tests for backend.services.apple_workout_detail.

Hydrates the Apple side of GET /activities/{id}. Covers:

* Unknown id → ``None``.
* Apple-only HDP + Workout → dict in the same shape ``_activity_summary``
  returns (matched key-for-key against the Strava builder).
* Derived ``laps`` reflect the ``WorkoutLap`` rows.
* ``zones=None`` when ``heartRateData`` is absent.
* Synthesized 5-bucket HR zones (``sensor_based=False``) when the
  ``heartRateData`` series is present.
* ``sport_type`` is the CamelCase form the frontend's
  ``classifyActivity`` switch expects.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.database import Base
from backend.models import (
    Activity,
    HealthDataPoint,
    UserProfile,
    WeatherSnapshot,
    Workout,
    WorkoutLap,
)
from backend.routers.activities import _activity_summary
from backend.services.apple_workout_detail import get_apple_workout_detail
from backend.services.time_utils import utc_now_naive


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


async def _seed_profile(db: AsyncSession, *, max_hr: int = 190) -> None:
    db.add(UserProfile(id=1, payload={"maxHr": str(max_hr)}))
    await db.commit()


async def _seed_apple_workout(
    db: AsyncSession,
    *,
    external_id: str = "apple-1",
    activity_type: str = "run",
    raw_payload: dict | None = None,
    linked_activity_id: int | None = None,
    laps: list[WorkoutLap] | None = None,
    avg_hr: float | None = 150.0,
    distance_m: float | None = 5000.0,
    duration_s: int = 1800,
) -> tuple[Workout, HealthDataPoint]:
    start = utc_now_naive() - timedelta(days=1)
    dp = HealthDataPoint(
        source="apple_health",
        data_type="workout",
        external_id=external_id,
        start_time=start,
        raw_payload=raw_payload,
    )
    db.add(dp)
    await db.flush()
    workout = Workout(
        id=dp.id,
        activity_type=activity_type,
        duration_s=duration_s,
        distance_m=distance_m,
        avg_hr=avg_hr,
        max_hr=180.0 if avg_hr else None,
        avg_speed_mps=distance_m / duration_s if (distance_m and duration_s) else None,
        activity_id=linked_activity_id,
    )
    db.add(workout)
    await db.flush()
    if laps:
        for lap in laps:
            lap.workout_id = workout.id
            db.add(lap)
    await db.commit()
    await db.refresh(dp)
    await db.refresh(workout)
    return workout, dp


# ── unknown id ─────────────────────────────────────────────────────


async def test_returns_none_for_unknown_id(db: AsyncSession):
    assert await get_apple_workout_detail(db, 999) is None


async def test_returns_none_when_id_is_not_an_apple_workout(db: AsyncSession):
    """A HealthDataPoint with source != apple_health must not resolve here.

    Strava rows live in ``activities``, not ``health_data_points``, so
    in practice this guards an unexpected Whoop / Eight Sleep id from
    leaking through.
    """
    dp = HealthDataPoint(
        source="whoop",
        data_type="workout",
        external_id="w-1",
        start_time=utc_now_naive(),
    )
    db.add(dp)
    await db.commit()
    await db.refresh(dp)
    assert await get_apple_workout_detail(db, dp.id) is None


# ── shape parity with _activity_summary ────────────────────────────


async def test_detail_dict_matches_activity_summary_keys(db: AsyncSession):
    """Apple detail must expose the same top-level keys the Strava builder does,
    plus the additional fields the detail endpoint layers on top."""
    await _seed_profile(db)
    _, dp = await _seed_apple_workout(db, activity_type="run")

    detail = await get_apple_workout_detail(db, dp.id)
    assert detail is not None

    # Reference dict from a fresh Strava activity, then assert every key
    # is present in the Apple response.
    reference = _activity_summary(
        Activity(
            strava_id=1,
            name="ref",
            sport_type="Run",
            start_date=datetime(2026, 1, 1, 9, 0),
            start_date_local=datetime(2026, 1, 1, 9, 0),
        )
    )
    missing = set(reference.keys()) - set(detail.keys())
    assert not missing, f"Apple detail is missing summary keys: {missing}"

    # Extra fields the detail page tacks on.
    for extra in (
        "laps",
        "zones",
        "weather",
        "streams_cached",
        "hr_drift",
        "pace_hr_decoupling",
        "power_hr_decoupling",
        "raw_data",
        "zones_synthetic",
        "splits_synthetic",
    ):
        assert extra in detail, f"missing extra field: {extra}"

    assert detail["source"] == "apple_health"
    assert detail["pace_hr_decoupling"] is None
    assert detail["power_hr_decoupling"] is None


# ── sport_type CamelCase ───────────────────────────────────────────


@pytest.mark.parametrize(
    "normalized,camel",
    [
        ("run", "Run"),
        ("ride", "Ride"),
        ("strength", "WeightTraining"),
        ("walk", "Walk"),
        ("hike", "Hike"),
        ("yoga", "Yoga"),
        ("other", "Workout"),
    ],
)
async def test_sport_type_is_camelcase(db: AsyncSession, normalized: str, camel: str):
    await _seed_profile(db)
    _, dp = await _seed_apple_workout(
        db, external_id=f"apple-{normalized}", activity_type=normalized
    )
    detail = await get_apple_workout_detail(db, dp.id)
    assert detail is not None
    assert detail["sport_type"] == camel


# ── laps ───────────────────────────────────────────────────────────


async def test_includes_derived_laps(db: AsyncSession):
    """Synthetic ``WorkoutLap`` rows surface in the ``laps`` array shaped
    like ``ActivityLap`` dicts (HR / power are None — HAE doesn't ship them)."""
    await _seed_profile(db)
    laps = [
        WorkoutLap(
            lap_index=0,
            name="Split 1",
            elapsed_time_s=360,
            moving_time_s=360,
            distance_m=1000.0,
            avg_speed_mps=2.78,
            split=1,
        ),
        WorkoutLap(
            lap_index=1,
            name="Split 2",
            elapsed_time_s=360,
            moving_time_s=360,
            distance_m=1000.0,
            avg_speed_mps=2.78,
            split=2,
        ),
    ]
    _, dp = await _seed_apple_workout(db, laps=laps)

    detail = await get_apple_workout_detail(db, dp.id)
    assert detail is not None
    assert len(detail["laps"]) == 2
    first = detail["laps"][0]
    assert first["lap_index"] == 0
    assert first["distance"] == 1000.0
    assert first["elapsed_time"] == 360
    # Apple synthetic laps have no per-lap HR or power.
    assert first["average_heartrate"] is None
    assert first["average_watts"] is None
    assert detail["splits_synthetic"] is True


async def test_no_laps_when_workout_has_none(db: AsyncSession):
    await _seed_profile(db)
    _, dp = await _seed_apple_workout(db, activity_type="other", laps=None)
    detail = await get_apple_workout_detail(db, dp.id)
    assert detail is not None
    assert detail["laps"] == []
    assert detail["splits_synthetic"] is False


# ── zones ─────────────────────────────────────────────────────────


async def test_zones_none_when_no_hr_series(db: AsyncSession):
    """No ``heartRateData`` in raw_payload → no synthesized zones."""
    await _seed_profile(db)
    _, dp = await _seed_apple_workout(
        db, raw_payload={"name": "Running"}  # no heart-rate series
    )
    detail = await get_apple_workout_detail(db, dp.id)
    assert detail is not None
    assert detail["zones"] is None
    assert detail["zones_synthetic"] is False


async def test_zones_none_when_no_user_profile(db: AsyncSession):
    """No profile → no max HR → can't bucket → zones None."""
    raw = {
        "heartRateData": [
            {"date": "2026-05-24 13:14:01 -0400", "qty": 130, "units": "count/min"},
            {"date": "2026-05-24 13:15:01 -0400", "qty": 150, "units": "count/min"},
        ]
    }
    _, dp = await _seed_apple_workout(db, raw_payload=raw)
    detail = await get_apple_workout_detail(db, dp.id)
    assert detail is not None
    assert detail["zones"] is None


async def test_synthesized_zones_when_series_present(db: AsyncSession):
    """A multi-sample HR series + profile max HR → 5 buckets, sensor_based=False."""
    await _seed_profile(db, max_hr=200)
    raw = {
        "heartRateData": [
            {"date": "2026-05-24 13:14:01 -0400", "qty": 90, "units": "count/min"},
            {"date": "2026-05-24 13:14:02 -0400", "qty": 130, "units": "count/min"},
            {"date": "2026-05-24 13:14:03 -0400", "qty": 150, "units": "count/min"},
            {"date": "2026-05-24 13:14:04 -0400", "qty": 170, "units": "count/min"},
            {"date": "2026-05-24 13:14:05 -0400", "qty": 190, "units": "count/min"},
        ]
    }
    _, dp = await _seed_apple_workout(db, raw_payload=raw)
    detail = await get_apple_workout_detail(db, dp.id)
    assert detail is not None
    zones = detail["zones"]
    assert zones is not None
    assert len(zones) == 1
    entry = zones[0]
    assert entry["type"] == "heartrate"
    assert entry["sensor_based"] is False
    assert len(entry["distribution_buckets"]) == 5
    assert entry["points"] == 5
    assert detail["zones_synthetic"] is True
    # Streams are "cached" by virtue of riding in raw_payload.
    assert detail["streams_cached"] is True


# ── weather linking ───────────────────────────────────────────────


async def test_weather_present_when_apple_links_to_strava_with_snapshot(
    db: AsyncSession,
):
    """Apple-wins-dedup row inherits the linked Strava activity's weather."""
    await _seed_profile(db)
    activity = Activity(
        strava_id=42,
        name="strava-42",
        sport_type="Run",
        start_date=utc_now_naive(),
        start_date_local=utc_now_naive(),
    )
    db.add(activity)
    await db.flush()
    snapshot = WeatherSnapshot(
        activity_id=activity.id,
        temp_c=18.0,
        feels_like_c=17.5,
        humidity=60,
        conditions="Clouds",
        description="overcast",
    )
    db.add(snapshot)
    await db.commit()
    _, dp = await _seed_apple_workout(db, linked_activity_id=activity.id)

    detail = await get_apple_workout_detail(db, dp.id)
    assert detail is not None
    assert detail["weather"] is not None
    assert detail["weather"]["temp_c"] == 18.0
    assert detail["weather"]["conditions"] == "Clouds"


async def test_weather_none_for_apple_only_workout(db: AsyncSession):
    await _seed_profile(db)
    _, dp = await _seed_apple_workout(db, linked_activity_id=None)
    detail = await get_apple_workout_detail(db, dp.id)
    assert detail is not None
    assert detail["weather"] is None
