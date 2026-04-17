"""Tests for backend.services.sleep_analytics.

Uses an in-memory SQLite DB so we exercise the real SQLAlchemy models.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models import SleepSession
from backend.services.sleep_analytics import (
    get_best_worst_nights,
    get_consistency_metrics,
    get_rolling_averages,
    get_sleep_debt,
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


def _make_session(
    day: date,
    *,
    source: str = "eight_sleep",
    sleep_score: float | None = 80,
    total_duration: int | None = 450,  # minutes
    deep_sleep: int | None = 90,
    rem_sleep: int | None = 100,
    hrv: float | None = 50.0,
    wake_count: int | None = 2,
    bed_hour: int = 23,
    bed_minute: int = 0,
    wake_hour: int = 7,
    wake_minute: int = 0,
) -> SleepSession:
    # bed_time on previous-day evening; wake_time on `day`.
    bed_time = datetime.combine(day - timedelta(days=1), datetime.min.time()).replace(
        hour=bed_hour, minute=bed_minute
    )
    wake_time = datetime.combine(day, datetime.min.time()).replace(
        hour=wake_hour, minute=wake_minute
    )
    return SleepSession(
        source=source,
        date=day,
        bed_time=bed_time,
        wake_time=wake_time,
        total_duration=total_duration,
        deep_sleep=deep_sleep,
        rem_sleep=rem_sleep,
        sleep_score=sleep_score,
        hrv=hrv,
        wake_count=wake_count,
    )


async def _seed(db: AsyncSession, sessions: list[SleepSession]) -> None:
    for s in sessions:
        db.add(s)
    await db.commit()


# ── Rolling averages ────────────────────────────────────────────────


async def test_rolling_averages_basic(db: AsyncSession):
    today = date.today()
    # 10 nights of score=80; earlier 20 nights of score=60. Duration 480 vs 360.
    sessions = []
    for i in range(10):
        sessions.append(
            _make_session(today - timedelta(days=i), sleep_score=80, total_duration=480)
        )
    for i in range(10, 30):
        sessions.append(
            _make_session(today - timedelta(days=i), sleep_score=60, total_duration=360)
        )
    await _seed(db, sessions)

    out = await get_rolling_averages(db, days=30)
    # Last 7 nights are all score=80.
    assert out["rolling_7_day"]["sample_size"] == 7
    assert out["rolling_7_day"]["metrics"]["sleep_score"] == 80.0
    assert out["rolling_7_day"]["metrics"]["total_duration"] == 480.0
    # 30-day window spans both score buckets — expected avg = (10*80 + 20*60)/30 ≈ 66.67.
    assert out["rolling_long"]["sample_size"] == 30
    assert out["rolling_long"]["metrics"]["sleep_score"] == pytest.approx(66.67, abs=0.01)
    assert out["rolling_long"]["metrics"]["total_duration"] == pytest.approx(400.0, abs=0.01)


async def test_rolling_averages_filters_non_eight_sleep(db: AsyncSession):
    today = date.today()
    await _seed(
        db,
        [
            _make_session(today, source="eight_sleep", sleep_score=80, total_duration=480),
            _make_session(
                today - timedelta(days=1), source="whoop", sleep_score=10, total_duration=120
            ),
        ],
    )
    out = await get_rolling_averages(db, days=30)
    # Whoop row must not drag the averages down.
    assert out["rolling_7_day"]["sample_size"] == 1
    assert out["rolling_7_day"]["metrics"]["sleep_score"] == 80.0


async def test_rolling_averages_handles_none_values(db: AsyncSession):
    today = date.today()
    await _seed(
        db,
        [
            _make_session(today, sleep_score=80, hrv=None, wake_count=None),
            _make_session(today - timedelta(days=1), sleep_score=None, hrv=40.0, wake_count=3),
        ],
    )
    out = await get_rolling_averages(db, days=30)
    metrics = out["rolling_7_day"]["metrics"]
    # Averages should skip Nones but still surface the other value.
    assert metrics["sleep_score"] == 80.0
    assert metrics["hrv"] == 40.0
    assert metrics["wake_count"] == 3.0


# ── Sleep debt ──────────────────────────────────────────────────────


async def test_sleep_debt_computes_per_night_and_cumulative(db: AsyncSession):
    today = date.today()
    # 3 nights: 7h, 8h, 6h → debts 1, 0, 2; cumulative = 3.
    await _seed(
        db,
        [
            _make_session(today, total_duration=7 * 60),
            _make_session(today - timedelta(days=1), total_duration=8 * 60),
            _make_session(today - timedelta(days=2), total_duration=6 * 60),
        ],
    )
    out = await get_sleep_debt(db, target_hours=8.0, days=7)
    assert out["target_hours"] == 8.0
    assert out["sample_size"] == 3
    assert out["cumulative_debt_hours"] == pytest.approx(3.0)
    assert out["average_debt_hours"] == pytest.approx(1.0)
    # Ordering within per_night mirrors the DB (ascending date).
    debts = {n["date"]: n["debt_hours"] for n in out["per_night"]}
    assert debts[today.isoformat()] == 1.0
    assert debts[(today - timedelta(days=1)).isoformat()] == 0.0
    assert debts[(today - timedelta(days=2)).isoformat()] == 2.0


async def test_sleep_debt_skips_rows_without_duration(db: AsyncSession):
    today = date.today()
    await _seed(
        db,
        [
            _make_session(today, total_duration=None),
            _make_session(today - timedelta(days=1), total_duration=7 * 60),
        ],
    )
    out = await get_sleep_debt(db, target_hours=8.0, days=7)
    assert out["sample_size"] == 1
    assert out["cumulative_debt_hours"] == pytest.approx(1.0)


# ── Best / worst nights ─────────────────────────────────────────────


async def test_best_worst_returns_top_n_each(db: AsyncSession):
    today = date.today()
    scores = [55, 92, 70, 88, 60, 75, 95, 50, 80, 65]
    sessions = [
        _make_session(today - timedelta(days=i), sleep_score=float(score))
        for i, score in enumerate(scores)
    ]
    # Add one night with a None score that should be skipped.
    sessions.append(_make_session(today - timedelta(days=20), sleep_score=None))
    await _seed(db, sessions)

    out = await get_best_worst_nights(db, days=90, top_n=3)
    assert out["sample_size"] == 10  # None filtered out.
    best_scores = [n["sleep_score"] for n in out["best"]]
    worst_scores = [n["sleep_score"] for n in out["worst"]]
    assert best_scores == [95, 92, 88]
    assert worst_scores == [50, 55, 60]
    # Each entry carries basic stats.
    for entry in out["best"] + out["worst"]:
        assert "date" in entry and "total_duration" in entry and "hrv" in entry


async def test_best_worst_respects_eight_sleep_filter(db: AsyncSession):
    today = date.today()
    await _seed(
        db,
        [
            _make_session(today, sleep_score=90, source="eight_sleep"),
            _make_session(today - timedelta(days=1), sleep_score=10, source="whoop"),
        ],
    )
    out = await get_best_worst_nights(db, days=90, top_n=5)
    assert out["sample_size"] == 1
    assert len(out["best"]) == 1
    assert out["best"][0]["sleep_score"] == 90
    # Worst list contains the single eight_sleep row, not the whoop 10-score.
    assert out["worst"][0]["sleep_score"] == 90


# ── Consistency ─────────────────────────────────────────────────────


async def test_consistency_zero_when_all_equal(db: AsyncSession):
    today = date.today()
    # 5 identical nights → zero stdev across all metrics.
    sessions = [
        _make_session(
            today - timedelta(days=i),
            total_duration=450,
            bed_hour=23,
            bed_minute=0,
            wake_hour=7,
            wake_minute=0,
        )
        for i in range(5)
    ]
    await _seed(db, sessions)

    out = await get_consistency_metrics(db, days=30)
    assert out["sample_size"] == 5
    assert out["bed_time"]["std_hours"] == 0.0
    assert out["wake_time"]["std_hours"] == 0.0
    assert out["total_duration"]["std_minutes"] == 0.0
    assert out["total_duration"]["mean_minutes"] == 450.0


async def test_consistency_handles_midnight_crossings(db: AsyncSession):
    """A person who alternates bed time between 23:30 and 00:30 is very
    consistent (std ≈ 30 minutes = 0.5 h), not wildly inconsistent."""
    today = date.today()
    # Five nights alternating around midnight.
    bed_times = [(23, 30), (0, 30), (23, 30), (0, 30), (23, 30)]
    sessions = []
    for i, (bh, bm) in enumerate(bed_times):
        sessions.append(
            _make_session(
                today - timedelta(days=i),
                bed_hour=bh,
                bed_minute=bm,
                wake_hour=7,
                wake_minute=0,
                total_duration=450,
            )
        )
    await _seed(db, sessions)

    out = await get_consistency_metrics(db, days=30)
    # Circular stdev of {23.5, 0.5} should be ≈ 0.5h, not ~11h (naive).
    assert out["bed_time"]["std_hours"] is not None
    assert out["bed_time"]["std_hours"] < 1.0
    # Wake times are all identical.
    assert out["wake_time"]["std_hours"] == 0.0
