"""Tests for backend.services.whoop_sync."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models import SleepSession
from backend.services import whoop_sync
from backend.services.whoop_sync import _upsert_sleep, sync_whoop


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


class StubWhoopClient:
    is_enabled = True

    def __init__(self) -> None:
        self.windows: list[tuple[datetime, datetime]] = []

    async def get_cycles(self, start: datetime, end: datetime) -> list[dict]:
        self.windows.append((start, end))
        return []

    async def get_recovery(self, start: datetime, end: datetime) -> list[dict]:
        self.windows.append((start, end))
        return []

    async def get_sleep(self, start: datetime, end: datetime) -> list[dict]:
        self.windows.append((start, end))
        return []

    async def get_workouts(self, start: datetime, end: datetime) -> list[dict]:
        self.windows.append((start, end))
        return []


async def test_sync_whoop_default_window_uses_utc_now(db, monkeypatch):
    now = datetime(2026, 4, 24, 16, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(whoop_sync, "utc_now", lambda: now)
    client = StubWhoopClient()

    stats = await sync_whoop(db, client, days=3)

    assert stats["failed"] == 0
    assert client.windows
    expected_start = datetime(2026, 4, 21, 16, 30, tzinfo=timezone.utc)
    assert all(start == expected_start for start, _ in client.windows)
    assert all(end == now for _, end in client.windows)


# ── _upsert_sleep field mapping ─────────────────────────────────────


# A trimmed-down but realistic Whoop /activity/sleep payload, mirroring the
# shape we observe in raw_data on real rows. Numbers chosen so each derived
# minute value is exact (no rounding ambiguity).
WHOOP_SLEEP_FIXTURE = {
    "id": "1e1abc7f-6866-435b-bdf9-76f1a4b58867",
    "cycle_id": 1457544397,
    "user_id": 32515264,
    "start": "2026-04-26T05:47:00.000Z",
    "end": "2026-04-26T13:14:00.000Z",
    "timezone_offset": "-04:00",
    "nap": False,
    "score_state": "SCORED",
    "score": {
        "stage_summary": {
            "total_in_bed_time_milli": 27_000_000,  # 450 min
            "total_awake_time_milli": 1_200_000,  # 20 min
            "total_no_data_time_milli": 0,
            "total_light_sleep_time_milli": 13_200_000,  # 220 min
            "total_slow_wave_sleep_time_milli": 7_800_000,  # 130 min
            "total_rem_sleep_time_milli": 4_800_000,  # 80 min
            "sleep_cycle_count": 4,
            "disturbance_count": 8,
        },
        "sleep_needed": {
            "baseline_milli": 28_800_000,  # 480 min
            "need_from_sleep_debt_milli": 1_800_000,  # 30 min
            "need_from_recent_strain_milli": 600_000,
            "need_from_recent_nap_milli": 0,
        },
        "respiratory_rate": 16.7,
        "sleep_performance_percentage": 86.0,
        "sleep_consistency_percentage": 78.0,
        "sleep_efficiency_percentage": 95.5,
    },
}


async def test_upsert_sleep_maps_whoop_extras(db):
    result = await _upsert_sleep(db, WHOOP_SLEEP_FIXTURE)
    await db.commit()

    assert result == "sleep_new"
    row = (await db.execute(select(SleepSession))).scalar_one()
    # Stage durations are derived from the score.stage_summary millis.
    assert row.source == "whoop"
    assert row.deep_sleep == 130
    assert row.rem_sleep == 80
    assert row.light_sleep == 220
    assert row.awake_time == 20
    assert row.total_duration == 430  # in_bed (450) - awake (20)
    assert row.wake_count == 8
    assert row.respiratory_rate == pytest.approx(16.7)
    assert row.sleep_score == pytest.approx(86.0)
    # The four new fields the migration added.
    assert row.sleep_efficiency == pytest.approx(95.5)
    assert row.sleep_consistency == pytest.approx(78.0)
    assert row.sleep_need_baseline_min == 480
    assert row.sleep_debt_min == 30


async def test_upsert_sleep_skips_naps(db):
    nap = dict(WHOOP_SLEEP_FIXTURE)
    nap["nap"] = True

    result = await _upsert_sleep(db, nap)
    await db.commit()

    assert result is None
    rows = (await db.execute(select(SleepSession))).scalars().all()
    assert rows == []
