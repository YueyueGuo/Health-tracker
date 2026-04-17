"""Tests for backend.services.correlations.

Exercises the sleep × next-day activity join, the noise/threshold filters,
and a known-value Pearson correlation case. Uses an in-memory SQLite DB
so we run against the real SQLAlchemy models.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models import Activity, SleepSession
from backend.services.correlations import (
    ACTIVITY_METRICS,
    MIN_PAIRED_SAMPLES,
    SLEEP_METRICS,
    sleep_vs_activity,
)


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


def _make_sleep(
    day: date,
    *,
    sleep_score: float | None = 80.0,
    hrv: float | None = 50.0,
    total_duration: int | None = 450,
    deep_sleep: int | None = 90,
    waso_duration: int | None = 10,
    source: str = "eight_sleep",
) -> SleepSession:
    return SleepSession(
        source=source,
        date=day,
        sleep_score=sleep_score,
        hrv=hrv,
        total_duration=total_duration,
        deep_sleep=deep_sleep,
        waso_duration=waso_duration,
    )


_COUNTER = {"n": 0}


def _next_strava_id() -> int:
    _COUNTER["n"] += 1
    return 10_000 + _COUNTER["n"]


def _make_activity(
    day: date,
    *,
    sport_type: str = "Run",
    moving_time: int | None = 1800,
    average_hr: float | None = 150.0,
    average_power: float | None = 200.0,
    suffer_score: int | None = 50,
    average_speed: float | None = 3.0,
    hour: int = 7,
) -> Activity:
    local = datetime.combine(day, datetime.min.time()).replace(hour=hour)
    return Activity(
        strava_id=_next_strava_id(),
        name=f"{sport_type} {day.isoformat()}",
        sport_type=sport_type,
        start_date=local,  # use local as UTC stand-in for test
        start_date_local=local,
        moving_time=moving_time,
        average_hr=average_hr,
        average_power=average_power,
        suffer_score=suffer_score,
        average_speed=average_speed,
    )


# ── Join logic ──────────────────────────────────────────────────────


async def test_pairs_activity_with_same_day_sleep(db: AsyncSession):
    today = date.today()
    d1 = today - timedelta(days=2)
    d2 = today - timedelta(days=3)
    db.add_all([
        _make_sleep(d1, sleep_score=82.0),
        _make_sleep(d2, sleep_score=60.0),
        # Unmatched sleep (no activity that day) — should be ignored.
        _make_sleep(today - timedelta(days=10), sleep_score=70.0),
        _make_activity(d1, average_hr=140.0),
        _make_activity(d2, average_hr=165.0),
        # Activity without a matching sleep — should be dropped.
        _make_activity(today - timedelta(days=1), average_hr=150.0),
    ])
    await db.commit()

    out = await sleep_vs_activity(db, days=30)
    assert out["pair_count"] == 2
    # Pairs come back in chronological ascending order.
    assert [p["date"] for p in out["pairs"]] == [d2.isoformat(), d1.isoformat()]
    pair_by_date = {p["date"]: p for p in out["pairs"]}
    assert pair_by_date[d1.isoformat()]["sleep"]["sleep_score"] == 82.0
    assert pair_by_date[d1.isoformat()]["activity"]["average_hr"] == 140.0


async def test_skips_non_eight_sleep_sources(db: AsyncSession):
    today = date.today()
    d = today - timedelta(days=1)
    db.add_all([
        _make_sleep(d, source="whoop", sleep_score=90.0),
        _make_activity(d),
    ])
    await db.commit()

    out = await sleep_vs_activity(db, days=30)
    assert out["pair_count"] == 0


# ── Noise filters ──────────────────────────────────────────────────


async def test_filters_short_activities_and_missing_hr(db: AsyncSession):
    today = date.today()
    good = today - timedelta(days=1)
    short = today - timedelta(days=2)
    no_hr = today - timedelta(days=3)
    db.add_all([
        _make_sleep(good),
        _make_sleep(short),
        _make_sleep(no_hr),
        _make_activity(good, moving_time=1800, average_hr=150.0),
        _make_activity(short, moving_time=300, average_hr=150.0),       # < 600s
        _make_activity(no_hr, moving_time=1800, average_hr=None),        # no HR
    ])
    await db.commit()

    out = await sleep_vs_activity(db, days=30)
    assert out["pair_count"] == 1
    assert out["pairs"][0]["date"] == good.isoformat()


# ── Threshold: sparse pairs → null ──────────────────────────────────


async def test_sparse_pairs_returns_null(db: AsyncSession):
    today = date.today()
    # Create only 5 paired days (< MIN_PAIRED_SAMPLES=8).
    assert MIN_PAIRED_SAMPLES == 8
    for i in range(5):
        d = today - timedelta(days=i + 1)
        db.add_all([
            _make_sleep(d, sleep_score=70.0 + i),
            _make_activity(d, average_hr=140.0 + i),
        ])
    await db.commit()

    out = await sleep_vs_activity(db, days=30)
    assert out["pair_count"] == 5
    # Every cell should be None (below threshold).
    for sm in SLEEP_METRICS:
        for am in ACTIVITY_METRICS:
            assert out["correlations"][sm][am] is None, (sm, am)


# ── Known-value correlation ────────────────────────────────────────


async def test_perfect_positive_correlation(db: AsyncSession):
    today = date.today()
    # 10 days of data where activity.average_hr = 2 * sleep.sleep_score + 3
    # → Pearson r between sleep_score and average_hr = 1.0.
    for i in range(10):
        d = today - timedelta(days=i + 1)
        score = 60.0 + i  # distinct values → non-zero variance
        db.add_all([
            _make_sleep(d, sleep_score=score),
            _make_activity(d, average_hr=2.0 * score + 3.0),
        ])
    await db.commit()

    out = await sleep_vs_activity(db, days=30)
    assert out["pair_count"] == 10
    assert out["correlations"]["sleep_score"]["average_hr"] == pytest.approx(1.0, abs=1e-6)


async def test_perfect_negative_correlation(db: AsyncSession):
    today = date.today()
    for i in range(10):
        d = today - timedelta(days=i + 1)
        score = 60.0 + i
        db.add_all([
            _make_sleep(d, sleep_score=score),
            _make_activity(d, average_hr=300.0 - 2.0 * score),
        ])
    await db.commit()

    out = await sleep_vs_activity(db, days=30)
    assert out["correlations"]["sleep_score"]["average_hr"] == pytest.approx(-1.0, abs=1e-6)


async def test_zero_variance_returns_null(db: AsyncSession):
    today = date.today()
    # 10 days with identical sleep_score → no variance → Pearson undefined → None.
    for i in range(10):
        d = today - timedelta(days=i + 1)
        db.add_all([
            _make_sleep(d, sleep_score=80.0),
            _make_activity(d, average_hr=140.0 + i),
        ])
    await db.commit()

    out = await sleep_vs_activity(db, days=30)
    assert out["correlations"]["sleep_score"]["average_hr"] is None


# ── sport_type filter ──────────────────────────────────────────────


async def test_sport_type_filter(db: AsyncSession):
    today = date.today()
    # 10 paired Runs + 10 paired Rides.
    for i in range(10):
        run_day = today - timedelta(days=i + 1)
        ride_day = today - timedelta(days=i + 15)
        db.add_all([
            _make_sleep(run_day, sleep_score=60.0 + i),
            _make_activity(run_day, sport_type="Run", average_hr=140.0 + i),
            _make_sleep(ride_day, sleep_score=70.0 + i),
            _make_activity(ride_day, sport_type="Ride", average_hr=130.0 + i),
        ])
    await db.commit()

    out_runs = await sleep_vs_activity(db, days=60, sport_type="Run")
    assert out_runs["pair_count"] == 10
    assert all(p["sport_type"] == "Run" for p in out_runs["pairs"])

    out_rides = await sleep_vs_activity(db, days=60, sport_type="Ride")
    assert out_rides["pair_count"] == 10
    assert all(p["sport_type"] == "Ride" for p in out_rides["pairs"])

    out_all = await sleep_vs_activity(db, days=60)
    assert out_all["pair_count"] == 20


async def test_empty_db_returns_structured_response(db: AsyncSession):
    out = await sleep_vs_activity(db, days=30)
    assert out == {
        "days": 30,
        "sport_type": None,
        "pair_count": 0,
        "pairs": [],
        "correlations": {
            sm: {am: None for am in ACTIVITY_METRICS} for sm in SLEEP_METRICS
        },
    }
