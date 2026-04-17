"""Tests for backend.services.training_metrics."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models import Activity, Recovery, SleepSession
from backend.services import training_metrics


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


def _make_activity(
    *,
    strava_id: int,
    days_ago: int,
    sport_type: str = "Run",
    classification_type: str | None = "easy",
    moving_time: int | None = 1800,  # 30 min
    distance: float | None = 5000.0,
    average_hr: float | None = 145.0,
    average_speed: float | None = 2.8,
    suffer_score: int | None = 40,
    enrichment_status: str = "complete",
) -> Activity:
    start = datetime.utcnow() - timedelta(days=days_ago)
    return Activity(
        strava_id=strava_id,
        name=f"Activity {strava_id}",
        sport_type=sport_type,
        start_date=start,
        start_date_local=start,
        elapsed_time=moving_time,
        moving_time=moving_time,
        distance=distance,
        average_hr=average_hr,
        average_speed=average_speed,
        suffer_score=suffer_score,
        classification_type=classification_type,
        enrichment_status=enrichment_status,
    )


async def _seed(db: AsyncSession, items) -> None:
    for i in items:
        db.add(i)
    await db.commit()


# ── Training load snapshot ────────────────────────────────────────────


async def test_empty_training_load(db):
    snap = await training_metrics.get_training_load_snapshot(db)
    assert snap["acute_load_7d"] == 0.0
    assert snap["chronic_load_28d"] == 0.0
    assert snap["acwr"] is None
    assert snap["monotony"] is None
    assert snap["days_since_hard"] is None
    assert snap["activity_count_7d"] == 0
    assert len(snap["daily_loads"]) == 28


async def test_training_load_with_activities(db):
    # 3 sessions in last 7 days (4 days ago, 2 days ago, today),
    # 2 sessions between 8–27 days ago
    await _seed(
        db,
        [
            _make_activity(strava_id=1, days_ago=0, suffer_score=50),
            _make_activity(strava_id=2, days_ago=2, suffer_score=60),
            _make_activity(strava_id=3, days_ago=4, suffer_score=40),
            _make_activity(strava_id=4, days_ago=10, suffer_score=80, classification_type="intervals"),
            _make_activity(strava_id=5, days_ago=20, suffer_score=30),
        ],
    )
    snap = await training_metrics.get_training_load_snapshot(db)
    # Acute load: 50 + 60 + 40 = 150
    assert snap["acute_load_7d"] == 150.0
    # Chronic load: 150 + 80 + 30 = 260
    assert snap["chronic_load_28d"] == 260.0
    # ACWR = (150/7) / (260/28) = 21.43 / 9.29 = 2.31
    assert snap["acwr"] == pytest.approx(2.31, abs=0.05)
    assert snap["activity_count_7d"] == 3
    assert snap["days_since_hard"] == 10
    assert snap["last_hard_date"] == (date.today() - timedelta(days=10)).isoformat()


async def test_training_load_classification_counts(db):
    await _seed(
        db,
        [
            _make_activity(strava_id=1, days_ago=1, classification_type="easy"),
            _make_activity(strava_id=2, days_ago=3, classification_type="tempo"),
            _make_activity(strava_id=3, days_ago=5, classification_type="easy"),
            _make_activity(strava_id=4, days_ago=12, classification_type="intervals"),
        ],
    )
    snap = await training_metrics.get_training_load_snapshot(db)
    assert snap["classification_counts_7d"] == {"easy": 2, "tempo": 1}
    assert snap["classification_counts_28d"] == {"easy": 2, "tempo": 1, "intervals": 1}


async def test_training_load_stress_fallback(db):
    # Activity without suffer_score → uses duration*HR fallback.
    await _seed(
        db,
        [
            _make_activity(
                strava_id=1,
                days_ago=1,
                suffer_score=None,
                moving_time=3600,
                average_hr=150,
            )
        ],
    )
    snap = await training_metrics.get_training_load_snapshot(db)
    # (60 min) * (150/180) * 1.2 = 60.0
    assert snap["acute_load_7d"] == 60.0


async def test_training_load_monotony_zero_stdev(db):
    # Same load every day for 7 days → stdev is 0, monotony undefined (None).
    acts = [
        _make_activity(strava_id=i, days_ago=i, suffer_score=50) for i in range(7)
    ]
    await _seed(db, acts)
    snap = await training_metrics.get_training_load_snapshot(db)
    assert snap["monotony"] is None  # stdev=0 → can't compute


# ── Sleep snapshot ────────────────────────────────────────────────────


async def test_empty_sleep_snapshot(db):
    snap = await training_metrics.get_sleep_snapshot(db)
    assert snap["last_night_score"] is None
    assert snap["sleep_debt_min"] is None
    assert snap["nights_of_data"] == 0


async def test_sleep_snapshot_computes_debt(db):
    today = date.today()
    # Target = 8h = 480 min. Provide 3 nights, each 420 min → debt = 3 * 60 = 180
    await _seed(
        db,
        [
            SleepSession(
                source="eight_sleep",
                date=today - timedelta(days=i),
                total_duration=420,
                sleep_score=75,
                hrv=45.0,
            )
            for i in range(3)
        ],
    )
    snap = await training_metrics.get_sleep_snapshot(db)
    assert snap["nights_of_data"] == 3
    assert snap["last_night_score"] == 75
    assert snap["last_night_duration_min"] == 420
    assert snap["avg_duration_min_7d"] == 420.0
    assert snap["sleep_debt_min"] == 180


async def test_sleep_snapshot_last_night_is_most_recent(db):
    today = date.today()
    await _seed(
        db,
        [
            SleepSession(source="eight_sleep", date=today - timedelta(days=5), sleep_score=60),
            SleepSession(source="eight_sleep", date=today, sleep_score=90),
            SleepSession(source="eight_sleep", date=today - timedelta(days=2), sleep_score=75),
        ],
    )
    snap = await training_metrics.get_sleep_snapshot(db)
    assert snap["last_night_score"] == 90
    assert snap["last_night_date"] == today.isoformat()


# ── Recovery snapshot ─────────────────────────────────────────────────


async def test_empty_recovery_snapshot(db):
    snap = await training_metrics.get_recovery_snapshot(db)
    assert snap["today_score"] is None
    assert snap["trend"] is None


async def test_recovery_snapshot_trend_improving(db):
    today = date.today()
    # Older records around 60; today is 80 → improving
    rs = [
        Recovery(source="whoop", date=today - timedelta(days=i), recovery_score=60)
        for i in range(1, 6)
    ]
    rs.insert(0, Recovery(source="whoop", date=today, recovery_score=80))
    await _seed(db, rs)
    snap = await training_metrics.get_recovery_snapshot(db)
    assert snap["today_score"] == 80
    assert snap["trend"] == "improving"


async def test_recovery_snapshot_trend_declining(db):
    today = date.today()
    rs = [
        Recovery(source="whoop", date=today - timedelta(days=i), recovery_score=80)
        for i in range(1, 6)
    ]
    rs.insert(0, Recovery(source="whoop", date=today, recovery_score=50))
    await _seed(db, rs)
    snap = await training_metrics.get_recovery_snapshot(db)
    assert snap["trend"] == "declining"


# ── Latest workout snapshot ───────────────────────────────────────────


async def test_latest_workout_snapshot_none_when_empty(db):
    snap = await training_metrics.get_latest_workout_snapshot(db)
    assert snap is None


async def test_latest_workout_snapshot_picks_most_recent_complete(db):
    await _seed(
        db,
        [
            _make_activity(strava_id=1, days_ago=5, suffer_score=40),
            _make_activity(strava_id=2, days_ago=1, suffer_score=80),
            _make_activity(
                strava_id=3, days_ago=0, enrichment_status="pending"
            ),  # should be skipped
        ],
    )
    snap = await training_metrics.get_latest_workout_snapshot(db)
    assert snap is not None
    assert snap["strava_id"] == 2  # most recent complete
    assert snap["suffer_score"] == 80


async def test_latest_workout_snapshot_formats_pace(db):
    # 5m/s → pace = 1000/5 = 200 s/km = 3:20/km
    await _seed(db, [_make_activity(strava_id=1, days_ago=0, average_speed=5.0)])
    snap = await training_metrics.get_latest_workout_snapshot(db)
    assert snap is not None
    assert snap["pace"] == "3:20/km"


# ── Full snapshot (integration) ───────────────────────────────────────


async def test_full_snapshot_assembles_all_sections(db):
    today = date.today()
    await _seed(
        db,
        [
            _make_activity(strava_id=1, days_ago=0, suffer_score=55),
            SleepSession(source="eight_sleep", date=today, sleep_score=78, total_duration=440),
            Recovery(source="whoop", date=today, recovery_score=70),
        ],
    )
    snap = await training_metrics.get_full_snapshot(db)
    assert snap["today"] == today.isoformat()
    assert snap["training_load"]["acute_load_7d"] == 55.0
    assert snap["sleep"]["last_night_score"] == 78
    assert snap["recovery"]["today_score"] == 70
    assert snap["latest_workout"] is not None
    assert len(snap["recent_activities"]) == 1
