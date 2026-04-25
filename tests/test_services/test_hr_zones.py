"""Tests for backend.services.hr_zones.

Pure helpers (summarize_hr_zones, assign_lap_hr_zone) plus the DB-backed
drift / decoupling computations. The compute_* tests assert that the
read-only invariant holds — uncached streams yield None, never a fetch.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models import Activity, ActivityStream
from backend.services.hr_zones import (
    _find_hr_buckets,
    assign_lap_hr_zone,
    compute_hr_drift,
    compute_pace_hr_decoupling,
    compute_power_hr_decoupling,
    summarize_hr_zones,
)


HR_ZONES_5BUCKET = [
    {
        "type": "heartrate",
        "distribution_buckets": [
            {"min": 0, "max": 124, "time": 100.0},
            {"min": 125, "max": 154, "time": 2860.0},
            {"min": 155, "max": 169, "time": 200.0},
            {"min": 170, "max": 184, "time": 40.0},
            {"min": 185, "max": -1, "time": 0.0},
        ],
    },
    {
        "type": "pace",
        "distribution_buckets": [
            {"min": 0, "max": 2.7, "time": 1861.0},
            {"min": 2.7, "max": -1, "time": 1099.0},
        ],
    },
]


HR_ZONES_7BUCKET = [
    {
        "type": "heartrate",
        "distribution_buckets": [
            {"min": 0, "max": 109, "time": 60.0},
            {"min": 110, "max": 129, "time": 240.0},
            {"min": 130, "max": 149, "time": 1200.0},
            {"min": 150, "max": 159, "time": 600.0},
            {"min": 160, "max": 169, "time": 300.0},
            {"min": 170, "max": 179, "time": 60.0},
            {"min": 180, "max": -1, "time": 0.0},
        ],
    },
]


# ── _find_hr_buckets ────────────────────────────────────────────────


def test_find_hr_buckets_picks_heartrate_entry():
    buckets = _find_hr_buckets(HR_ZONES_5BUCKET)
    assert buckets is not None
    assert len(buckets) == 5
    assert buckets[0]["min"] == 0


def test_find_hr_buckets_handles_no_heartrate_entry():
    pace_only = [
        {"type": "pace", "distribution_buckets": [{"min": 0, "max": 2.7, "time": 100}]}
    ]
    assert _find_hr_buckets(pace_only) is None


# ── summarize_hr_zones ─────────────────────────────────────────────


def test_summarize_returns_none_for_empty_input():
    assert summarize_hr_zones(None) is None
    assert summarize_hr_zones([]) is None


def test_summarize_returns_none_when_no_heartrate_entry():
    pace_only = [
        {"type": "pace", "distribution_buckets": [{"min": 0, "max": 2.7, "time": 100}]}
    ]
    assert summarize_hr_zones(pace_only) is None


def test_summarize_5bucket_shape_and_percentages():
    out = summarize_hr_zones(HR_ZONES_5BUCKET)
    assert out is not None
    assert out["bucket_count"] == 5
    assert set(out.keys()) >= {
        "z1_pct", "z2_pct", "z3_pct", "z4_pct", "z5_pct",
        "dominant_zone", "total_minutes", "ranges",
    }
    # 100 + 2860 + 200 + 40 + 0 = 3200s. z2 = 2860/3200 = 89.4% → 89.
    assert out["z2_pct"] == 89
    assert out["dominant_zone"] == 2
    assert out["total_minutes"] == 53  # 3200/60 = 53.3 → 53
    # Pcts should sum to ~100 (rounding may give 99-101).
    pct_sum = sum(out[f"z{i}_pct"] for i in range(1, 6))
    assert 98 <= pct_sum <= 102


def test_summarize_7bucket_supported():
    out = summarize_hr_zones(HR_ZONES_7BUCKET)
    assert out is not None
    assert out["bucket_count"] == 7
    assert "z7_pct" in out
    assert out["dominant_zone"] == 3  # 1200s in z3


def test_summarize_returns_none_when_all_zero_time():
    zero = [
        {
            "type": "heartrate",
            "distribution_buckets": [
                {"min": 0, "max": 124, "time": 0},
                {"min": 125, "max": -1, "time": 0},
            ],
        }
    ]
    assert summarize_hr_zones(zero) is None


def test_summarize_dominant_zone_picks_max_time():
    data = [
        {
            "type": "heartrate",
            "distribution_buckets": [
                {"min": 0, "max": 124, "time": 100.0},
                {"min": 125, "max": 154, "time": 200.0},
                {"min": 155, "max": 169, "time": 1000.0},
                {"min": 170, "max": -1, "time": 50.0},
            ],
        }
    ]
    out = summarize_hr_zones(data)
    assert out is not None
    assert out["dominant_zone"] == 3


def test_summarize_ranges_preserve_open_top():
    out = summarize_hr_zones(HR_ZONES_5BUCKET)
    assert out is not None
    assert out["ranges"][-1] == {"zone": 5, "min": 185, "max": -1}
    assert out["ranges"][0] == {"zone": 1, "min": 0, "max": 124}


# ── assign_lap_hr_zone ──────────────────────────────────────────────


def test_assign_lap_zone_none_hr():
    assert assign_lap_hr_zone(None, HR_ZONES_5BUCKET) is None


def test_assign_lap_zone_no_zones():
    assert assign_lap_hr_zone(140.0, None) is None
    assert assign_lap_hr_zone(140.0, []) is None


def test_assign_lap_zone_below_lowest_clamps_to_one():
    """A 90 bpm lap (below the 0-124 range) still gets zone 1."""
    assert assign_lap_hr_zone(90.0, HR_ZONES_5BUCKET) == 1


def test_assign_lap_zone_mid_zone():
    # 140 bpm falls into bucket 2 (125-154).
    assert assign_lap_hr_zone(140.0, HR_ZONES_5BUCKET) == 2


def test_assign_lap_zone_open_top():
    # 200 bpm falls in bucket 5 with max=-1.
    assert assign_lap_hr_zone(200.0, HR_ZONES_5BUCKET) == 5


def test_assign_lap_zone_at_exact_boundary():
    # HR exactly equal to bucket 1's max (124) — half-open [min, max),
    # so 124 lands in zone 2.
    assert assign_lap_hr_zone(124.0, HR_ZONES_5BUCKET) == 2


# ── DB fixture + seeding helpers ────────────────────────────────────


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


_id_counter = [200_000]


def _next_strava_id() -> int:
    _id_counter[0] += 1
    return _id_counter[0]


async def _seed_activity(db: AsyncSession) -> Activity:
    activity = Activity(
        strava_id=_next_strava_id(),
        name="Test",
        sport_type="Run",
        start_date=datetime(2026, 4, 21, 9, 0, 0),
        start_date_local=datetime(2026, 4, 21, 9, 0, 0),
    )
    db.add(activity)
    await db.flush()
    return activity


async def _add_stream(db: AsyncSession, activity_id: int, stream_type: str, data: list):
    db.add(ActivityStream(activity_id=activity_id, stream_type=stream_type, data=data))
    await db.flush()


# ── compute_hr_drift ────────────────────────────────────────────────


async def test_drift_none_when_streams_missing(db: AsyncSession):
    activity = await _seed_activity(db)
    assert await compute_hr_drift(db, activity.id) is None


async def test_drift_none_when_only_time_cached(db: AsyncSession):
    activity = await _seed_activity(db)
    await _add_stream(db, activity.id, "time", list(range(700)))
    assert await compute_hr_drift(db, activity.id) is None


async def test_drift_none_when_under_min_duration(db: AsyncSession):
    """5-minute activity should return None (default 10-min gate)."""
    activity = await _seed_activity(db)
    times = list(range(300))
    hrs = [140] * len(times)
    await _add_stream(db, activity.id, "time", times)
    await _add_stream(db, activity.id, "heartrate", hrs)
    assert await compute_hr_drift(db, activity.id) is None


async def test_drift_positive_when_hr_rises(db: AsyncSession):
    """First half avg=140, second half avg=150 → drift ≈ 0.0714."""
    activity = await _seed_activity(db)
    times = list(range(0, 1200))  # 20 min
    hrs = [140] * 600 + [150] * 600
    await _add_stream(db, activity.id, "time", times)
    await _add_stream(db, activity.id, "heartrate", hrs)
    drift = await compute_hr_drift(db, activity.id)
    assert drift is not None
    assert drift == pytest.approx(0.0714, abs=0.005)


async def test_drift_negative_when_hr_falls(db: AsyncSession):
    activity = await _seed_activity(db)
    times = list(range(0, 1200))
    hrs = [160] * 600 + [140] * 600
    await _add_stream(db, activity.id, "time", times)
    await _add_stream(db, activity.id, "heartrate", hrs)
    drift = await compute_hr_drift(db, activity.id)
    assert drift is not None
    assert drift < 0


async def test_drift_handles_mismatched_lengths(db: AsyncSession):
    """Trims to the shorter stream rather than crashing."""
    activity = await _seed_activity(db)
    times = list(range(0, 1200))
    hrs = [140] * 800  # shorter
    await _add_stream(db, activity.id, "time", times)
    await _add_stream(db, activity.id, "heartrate", hrs)
    # Effective duration is 800s ≥ 600 → non-None expected (steady HR → ~0).
    drift = await compute_hr_drift(db, activity.id)
    assert drift is not None
    assert abs(drift) < 0.01


async def test_drift_none_when_all_zero_hr(db: AsyncSession):
    activity = await _seed_activity(db)
    times = list(range(0, 1200))
    hrs = [0] * len(times)
    await _add_stream(db, activity.id, "time", times)
    await _add_stream(db, activity.id, "heartrate", hrs)
    assert await compute_hr_drift(db, activity.id) is None


# ── compute_pace_hr_decoupling ──────────────────────────────────────


async def test_pace_decoupling_none_without_velocity_stream(db: AsyncSession):
    activity = await _seed_activity(db)
    times = list(range(0, 1500))
    hrs = [140] * len(times)
    await _add_stream(db, activity.id, "time", times)
    await _add_stream(db, activity.id, "heartrate", hrs)
    assert await compute_pace_hr_decoupling(db, activity.id) is None


async def test_pace_decoupling_near_zero_when_steady(db: AsyncSession):
    activity = await _seed_activity(db)
    times = list(range(0, 1500))
    hrs = [140] * len(times)
    vel = [3.0] * len(times)  # 3 m/s constant
    await _add_stream(db, activity.id, "time", times)
    await _add_stream(db, activity.id, "heartrate", hrs)
    await _add_stream(db, activity.id, "velocity_smooth", vel)
    out = await compute_pace_hr_decoupling(db, activity.id)
    assert out is not None
    assert abs(out) < 0.01


async def test_pace_decoupling_positive_when_hr_rises_at_same_pace(db: AsyncSession):
    """Pace held at 3.0 m/s; HR drifts 140→160. Efficiency drops →
    decoupling positive."""
    activity = await _seed_activity(db)
    times = list(range(0, 1500))
    hrs = [140] * 750 + [160] * 750
    vel = [3.0] * len(times)
    await _add_stream(db, activity.id, "time", times)
    await _add_stream(db, activity.id, "heartrate", hrs)
    await _add_stream(db, activity.id, "velocity_smooth", vel)
    out = await compute_pace_hr_decoupling(db, activity.id)
    assert out is not None
    assert out > 0.05


# ── compute_power_hr_decoupling ─────────────────────────────────────


async def test_power_decoupling_none_without_watts(db: AsyncSession):
    activity = await _seed_activity(db)
    times = list(range(0, 1500))
    hrs = [140] * len(times)
    await _add_stream(db, activity.id, "time", times)
    await _add_stream(db, activity.id, "heartrate", hrs)
    assert await compute_power_hr_decoupling(db, activity.id) is None


async def test_power_decoupling_near_zero_when_steady(db: AsyncSession):
    activity = await _seed_activity(db)
    times = list(range(0, 1500))
    hrs = [150] * len(times)
    watts = [200] * len(times)
    await _add_stream(db, activity.id, "time", times)
    await _add_stream(db, activity.id, "heartrate", hrs)
    await _add_stream(db, activity.id, "watts", watts)
    out = await compute_power_hr_decoupling(db, activity.id)
    assert out is not None
    assert abs(out) < 0.01


async def test_power_decoupling_positive_when_hr_rises_at_same_power(db: AsyncSession):
    activity = await _seed_activity(db)
    times = list(range(0, 1500))
    hrs = [145] * 750 + [165] * 750
    watts = [220] * len(times)
    await _add_stream(db, activity.id, "time", times)
    await _add_stream(db, activity.id, "heartrate", hrs)
    await _add_stream(db, activity.id, "watts", watts)
    out = await compute_power_hr_decoupling(db, activity.id)
    assert out is not None
    assert out > 0.05
