"""Tests for recovery snapshot HRV source and trend logic."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models import Activity, Recovery, SleepSession
from backend.services import training_metrics
from backend.services.training_load_snapshot import acwr_band


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


async def _seed(db: AsyncSession, items) -> None:
    db.add_all(items)
    await db.commit()


async def test_recovery_snapshot_prefers_eight_sleep_hrv(db):
    today = date(2026, 1, 8)
    await _seed(
        db,
        [
            SleepSession(
                source="eight_sleep",
                date=today,
                hrv=80,
                avg_hr=49,
            ),
            SleepSession(source="eight_sleep", date=today - timedelta(days=1), hrv=70),
            SleepSession(source="eight_sleep", date=today - timedelta(days=2), hrv=70),
            SleepSession(source="eight_sleep", date=today - timedelta(days=3), hrv=70),
            Recovery(
                source="whoop",
                date=today,
                recovery_score=72,
                hrv=50,
                resting_hr=58,
            ),
        ],
    )

    snap = await training_metrics.get_recovery_snapshot(db, today=today)

    assert snap["today_hrv"] == 80
    assert snap["today_resting_hr"] == 49
    assert snap["hrv_baseline_7d"] == 72.5
    assert snap["hrv_trend"] == "up"
    assert snap["hrv_source"] == "eight_sleep"
    assert snap["today_score"] == 72


async def test_recovery_snapshot_falls_back_to_whoop_hrv(db):
    today = date(2026, 1, 8)
    await _seed(
        db,
        [
            SleepSession(source="eight_sleep", date=today, hrv=None, avg_hr=50),
            Recovery(source="whoop", date=today, recovery_score=70, hrv=66),
            Recovery(source="whoop", date=today - timedelta(days=1), hrv=70),
            Recovery(source="whoop", date=today - timedelta(days=2), hrv=70),
            Recovery(source="whoop", date=today - timedelta(days=3), hrv=70),
        ],
    )

    snap = await training_metrics.get_recovery_snapshot(db, today=today)

    assert snap["today_hrv"] == 66
    assert snap["today_resting_hr"] == 50
    assert snap["hrv_baseline_7d"] == 69.0
    assert snap["hrv_trend"] == "down"
    assert snap["hrv_source"] == "whoop"


async def test_recovery_snapshot_ignores_stale_eight_sleep_hrv(db):
    today = date(2026, 1, 8)
    await _seed(
        db,
        [
            SleepSession(
                source="eight_sleep",
                date=today - timedelta(days=2),
                hrv=90,
                avg_hr=44,
            ),
            Recovery(
                source="whoop",
                date=today,
                recovery_score=70,
                hrv=66,
                resting_hr=53,
            ),
            Recovery(source="whoop", date=today - timedelta(days=1), hrv=70),
            Recovery(source="whoop", date=today - timedelta(days=2), hrv=70),
            Recovery(source="whoop", date=today - timedelta(days=3), hrv=70),
        ],
    )

    snap = await training_metrics.get_recovery_snapshot(db, today=today)

    assert snap["today_hrv"] == 66
    assert snap["today_resting_hr"] == 53
    assert snap["hrv_baseline_7d"] == 69.0
    assert snap["hrv_trend"] == "down"
    assert snap["hrv_source"] == "whoop"


async def test_recovery_snapshot_prefers_today_sleep_over_stale_recovery(db):
    today = date(2026, 1, 8)
    yesterday = today - timedelta(days=1)
    await _seed(
        db,
        [
            SleepSession(source="eight_sleep", date=today, hrv=76, avg_hr=47),
            SleepSession(source="eight_sleep", date=yesterday, hrv=70),
            Recovery(
                source="whoop",
                date=yesterday,
                recovery_score=70,
                hrv=60,
                resting_hr=55,
            ),
        ],
    )

    snap = await training_metrics.get_recovery_snapshot(db, today=today)

    assert snap["today_date"] == yesterday.isoformat()
    assert snap["today_hrv"] == 76
    assert snap["today_resting_hr"] == 47
    assert snap["hrv_source"] == "eight_sleep"


async def test_recovery_snapshot_does_not_report_stale_whoop_as_today_hrv(db):
    today = date(2026, 1, 8)
    yesterday = today - timedelta(days=1)
    await _seed(
        db,
        [
            Recovery(
                source="whoop",
                date=yesterday,
                recovery_score=70,
                hrv=60,
                resting_hr=55,
            ),
            Recovery(source="whoop", date=today - timedelta(days=2), hrv=64),
        ],
    )

    snap = await training_metrics.get_recovery_snapshot(db, today=today)

    assert snap["today_date"] == yesterday.isoformat()
    assert snap["today_score"] == 70
    assert snap["today_hrv"] is None
    assert snap["today_resting_hr"] is None
    assert snap["hrv_baseline_7d"] == 62.0
    assert snap["hrv_trend"] is None
    assert snap["hrv_source"] is None


async def test_recovery_snapshot_ignores_future_sleep_and_recovery_rows(db):
    today = date(2026, 1, 8)
    await _seed(
        db,
        [
            SleepSession(source="eight_sleep", date=today, hrv=74, avg_hr=48),
            SleepSession(
                source="eight_sleep",
                date=today + timedelta(days=1),
                hrv=95,
                avg_hr=40,
            ),
            Recovery(source="whoop", date=today, recovery_score=70, hrv=66),
            Recovery(
                source="whoop",
                date=today + timedelta(days=1),
                recovery_score=99,
                hrv=99,
            ),
        ],
    )

    snap = await training_metrics.get_recovery_snapshot(db, today=today)

    assert snap["today_date"] == "2026-01-08"
    assert snap["today_score"] == 70
    assert snap["today_hrv"] == 74
    assert snap["today_resting_hr"] == 48
    assert snap["hrv_source"] == "eight_sleep"


async def test_sleep_snapshot_ignores_future_sleep_rows(db):
    today = date(2026, 1, 8)
    await _seed(
        db,
        [
            SleepSession(source="eight_sleep", date=today, sleep_score=80),
            SleepSession(
                source="eight_sleep",
                date=today + timedelta(days=1),
                sleep_score=99,
            ),
        ],
    )

    snap = await training_metrics.get_sleep_snapshot(db, today=today)

    assert snap["last_night_date"] == "2026-01-08"
    assert snap["last_night_score"] == 80


async def test_recovery_snapshot_avg_score_uses_seven_dates(db):
    today = date(2026, 1, 8)
    await _seed(
        db,
        [
            Recovery(
                source="whoop",
                date=today - timedelta(days=i),
                recovery_score=70,
            )
            for i in range(7)
        ]
        + [
            Recovery(
                source="whoop",
                date=today - timedelta(days=7),
                recovery_score=0,
            )
        ],
    )

    snap = await training_metrics.get_recovery_snapshot(db, today=today)

    assert snap["avg_score_7d"] == 70.0
    assert snap["trend"] == "stable"


async def test_recovery_snapshot_uses_sleep_hrv_without_whoop_rows(db):
    today = date(2026, 1, 8)
    await _seed(
        db,
        [
            SleepSession(source="eight_sleep", date=today, hrv=74, avg_hr=48),
            SleepSession(source="eight_sleep", date=today - timedelta(days=1), hrv=70),
            SleepSession(source="eight_sleep", date=today - timedelta(days=2), hrv=70),
            SleepSession(source="eight_sleep", date=today - timedelta(days=3), hrv=70),
        ],
    )

    snap = await training_metrics.get_recovery_snapshot(db, today=today)

    assert snap["today_date"] == "2026-01-08"
    assert snap["today_score"] is None
    assert snap["today_hrv"] == 74
    assert snap["today_resting_hr"] == 48
    assert snap["hrv_baseline_7d"] == 71.0
    assert snap["hrv_trend"] == "up"
    assert snap["hrv_source"] == "eight_sleep"


@pytest.mark.parametrize(
    ("acwr", "expected"),
    [
        (None, None),
        (0.79, "detraining"),
        (0.8, "optimal"),
        (1.3, "optimal"),
        (1.31, "caution"),
        (1.5, "caution"),
        (1.51, "elevated"),
    ],
)
def test_acwr_band_thresholds(acwr, expected):
    assert acwr_band(acwr) == expected


async def test_training_load_ignores_future_activities(db):
    today = date(2026, 1, 8)
    current_start = datetime.combine(today, datetime.min.time())
    future_start = datetime.combine(today + timedelta(days=1), datetime.min.time())
    await _seed(
        db,
        [
            Activity(
                strava_id=1,
                name="Today",
                sport_type="Run",
                start_date=current_start,
                start_date_local=current_start,
                moving_time=1800,
                suffer_score=50,
                classification_type="easy",
                enrichment_status="complete",
            ),
            Activity(
                strava_id=2,
                name="Future hard workout",
                sport_type="Run",
                start_date=future_start,
                start_date_local=future_start,
                moving_time=1800,
                suffer_score=200,
                classification_type="intervals",
                enrichment_status="complete",
            ),
        ],
    )

    snap = await training_metrics.get_training_load_snapshot(db, today=today)

    assert snap["acute_load_7d"] == 50.0
    assert snap["chronic_load_28d"] == 50.0
    assert snap["classification_counts_7d"] == {"easy": 1}
    assert snap["classification_counts_28d"] == {"easy": 1}
    assert snap["days_since_hard"] is None


async def test_training_load_filters_by_local_activity_day(db):
    today = date(2026, 1, 8)
    local_today = datetime.combine(today, datetime.max.time())
    utc_tomorrow = datetime.combine(today + timedelta(days=1), datetime.min.time())
    local_tomorrow = datetime.combine(today + timedelta(days=1), datetime.min.time())
    utc_today = datetime.combine(today, datetime.max.time())
    await _seed(
        db,
        [
            Activity(
                strava_id=3,
                name="Local today, UTC tomorrow",
                sport_type="Run",
                start_date=utc_tomorrow,
                start_date_local=local_today,
                moving_time=1800,
                suffer_score=50,
                classification_type="easy",
                enrichment_status="complete",
            ),
            Activity(
                strava_id=4,
                name="Local tomorrow, UTC today",
                sport_type="Run",
                start_date=utc_today,
                start_date_local=local_tomorrow,
                moving_time=1800,
                suffer_score=200,
                classification_type="intervals",
                enrichment_status="complete",
            ),
        ],
    )

    snap = await training_metrics.get_training_load_snapshot(db, today=today)

    assert snap["acute_load_7d"] == 50.0
    assert snap["classification_counts_7d"] == {"easy": 1}
    assert snap["days_since_hard"] is None
    assert snap["activity_count_7d"] == 1
