"""Tests for backend.services.eight_sleep_sync.

Focus on the field-extraction logic and the upsert behavior. Uses an
in-memory SQLite DB so we exercise the real SQLAlchemy models.
"""
from __future__ import annotations

from datetime import date, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models import SleepSession
from backend.services import eight_sleep_sync
from zoneinfo import ZoneInfo

from backend.services.eight_sleep_sync import (
    _extract_fields,
    _index_intervals_by_date,
    _mean,
    _score,
    _sec_to_min,
    _series_mean,
    _to_local,
    _wake_stats,
    sync_eight_sleep,
)


# ── Helpers / fixtures ──────────────────────────────────────────────


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


def _trend_row(day: str = "2026-04-10") -> dict:
    """Realistic Eight Sleep trend row (matches the shape observed live)."""
    return {
        "day": day,
        "mainSessionId": "sess-42",
        "sleepQualityScore": 83,
        "score": 85,
        "sleepDuration": 7 * 3600 + 30 * 60,      # 7.5h asleep
        "presenceDuration": 8 * 3600,             # 8h in bed
        "deepDuration": 90 * 60,
        "remDuration": 100 * 60,
        "lightDuration": 230 * 60,
        "sleepStart": f"{day}T06:00:00Z",
        "sleepEnd": f"{day}T13:30:00Z",
        "presenceStart": f"{day}T05:50:00Z",      # 10 min latency
        "tnt": 6,
    }


def _interval(ts: str = "2026-04-09T23:00:00Z") -> dict:
    """Realistic interval with [timestamp, value] timeseries tuples."""
    return {
        "id": "iv-42",
        "ts": ts,
        "stages": [
            {"stage": "awake", "duration": 30 * 60},
            {"stage": "light", "duration": 230 * 60},
            {"stage": "deep", "duration": 90 * 60},
            {"stage": "rem", "duration": 100 * 60},
        ],
        "timeseries": {
            "heartRate": [[f"2026-04-10T06:0{i}:00Z", v] for i, v in enumerate([55, 57, 52, 56, 54])],
            "hrv": [[f"2026-04-10T06:0{i}:00Z", v] for i, v in enumerate([48, 50, 47, 49])],
            "respiratoryRate": [[f"2026-04-10T06:0{i}:00Z", v] for i, v in enumerate([14.5, 15.0, 14.8])],
            "tempBedC": [[f"2026-04-10T06:0{i}:00Z", v] for i, v in enumerate([27.5, 27.6, 27.4])],
        },
    }


# ── Unit helpers ────────────────────────────────────────────────────


def test_mean_handles_none_and_mixed():
    assert _mean(None) is None
    assert _mean([]) is None
    assert _mean([1, 2, 3]) == 2
    assert _mean([1, "x", 3]) == 2  # non-numeric skipped


def test_sec_to_min_rounds():
    assert _sec_to_min(None) is None
    assert _sec_to_min(3600) == 60
    assert _sec_to_min(90) == 2
    assert _sec_to_min("bad") is None


def test_score_unwraps_dicts():
    assert _score(None) is None
    assert _score(83) == 83
    assert _score({"total": 77}) == 77
    assert _score({"other": 1}) is None


def test_index_intervals_shifts_evening_bedtime_to_next_day():
    # Bedtime 11pm on the 9th → wake day is the 10th.
    iv = _interval(ts="2026-04-09T23:00:00Z")
    idx = _index_intervals_by_date([iv])
    assert list(idx.keys()) == [date(2026, 4, 10)]


def test_index_intervals_keeps_early_morning_bedtime_same_day():
    # Bedtime 2am → wake day is same calendar day.
    iv = {"ts": "2026-04-10T02:00:00Z", "stages": []}
    idx = _index_intervals_by_date([iv])
    assert list(idx.keys()) == [date(2026, 4, 10)]


def test_index_intervals_picks_longest_when_multiple():
    short = {"ts": "2026-04-10T02:00:00Z", "stages": [{"duration": 60}]}
    long = {"ts": "2026-04-10T03:00:00Z", "stages": [{"duration": 9000}]}
    idx = _index_intervals_by_date([short, long])
    assert idx[date(2026, 4, 10)] is long


# ── Field extraction ───────────────────────────────────────────────


def test_extract_fields_full_payload():
    fields = _extract_fields(_trend_row(), _interval())
    assert fields["total_duration"] == 450  # 7.5h
    assert fields["deep_sleep"] == 90
    assert fields["rem_sleep"] == 100
    assert fields["light_sleep"] == 230
    # awake_time = presenceDuration - sleepDuration = 30 min
    assert fields["awake_time"] == 30
    assert fields["sleep_score"] == 83
    assert fields["sleep_fitness_score"] == 85  # from trend["score"]
    # Values pulled from [ts, value] tuples on the timeseries.
    assert fields["avg_hr"] == pytest.approx(54.8)
    assert fields["hrv"] == pytest.approx(48.5)
    assert fields["respiratory_rate"] == pytest.approx(14.766, rel=1e-3)
    assert fields["bed_temp"] == pytest.approx(27.5, rel=1e-3)
    assert fields["tnt_count"] == 6
    # Latency now derives from the interval's stages array (first awake
    # chunk before any sleep stage). The _interval() fixture has a
    # 30-minute pre-sleep awake chunk, so latency = 1800 seconds.
    # The coarser trend-level computation (which would give 600s here)
    # is only used as a fallback when the interval is absent.
    assert fields["latency"] == 30 * 60
    assert fields["external_id"] == "sess-42"
    assert isinstance(fields["bed_time"], datetime)
    assert fields["wake_time"] > fields["bed_time"]


def test_extract_fields_trend_only_returns_partial():
    fields = _extract_fields(_trend_row(), None)
    assert fields["total_duration"] == 450
    assert fields["avg_hr"] is None
    assert fields["hrv"] is None
    # bed_time still available from the trend's sleepStart field.
    assert isinstance(fields["bed_time"], datetime)
    # tnt_count comes from the trend scalar.
    assert fields["tnt_count"] == 6


def test_wake_stats_skips_pre_sleep_latency():
    interval = {
        "stages": [
            # Pre-sleep latency awake chunk — NOT counted.
            {"stage": "awake", "duration": 30 * 60},
            {"stage": "light", "duration": 60 * 60},
            # Mid-night wake-up: counted.
            {"stage": "awake", "duration": 10 * 60},
            {"stage": "light", "duration": 30 * 60},
            {"stage": "deep", "duration": 45 * 60},
            # Out-of-bed event.
            {"stage": "out", "duration": 5 * 60},
            {"stage": "light", "duration": 20 * 60},
            # Another mid-night wake-up.
            {"stage": "awake", "duration": 3 * 60},
        ],
    }
    s = _wake_stats(interval)
    assert s["wake_count"] == 2
    assert s["waso_duration"] == 13    # (10 + 3) minutes
    assert s["out_of_bed_count"] == 1
    assert s["out_of_bed_duration"] == 5
    # Three events in chronological order.
    types = [e["type"] for e in s["wake_events"]]
    assert types == ["awake", "out", "awake"]
    durations = [e["duration_sec"] for e in s["wake_events"]]
    assert durations == [600, 300, 180]


def test_wake_stats_prefers_stagesummary_waso():
    interval = {
        "stages": [
            {"stage": "awake", "duration": 30 * 60},   # latency
            {"stage": "light", "duration": 60 * 60},
            {"stage": "awake", "duration": 10 * 60},
            {"stage": "light", "duration": 60 * 60},
        ],
        "stageSummary": {
            "wasoDuration": 1500,   # Eight's "official" WASO = 25 min
            "outDuration": 0,
        },
    }
    s = _wake_stats(interval)
    # We override our sum (600s) with Eight's stageSummary (1500s).
    assert s["waso_duration"] == 25
    assert s["wake_count"] == 1


def test_wake_stats_returns_empty_when_no_interval():
    assert _wake_stats(None) == {}
    assert _wake_stats({}) == {}
    assert _wake_stats({"stages": []}) == {}


def test_wake_stats_extracts_pre_sleep_latency():
    """The first awake chunk before any sleep stage = sleep latency."""
    interval = {
        "stages": [
            {"stage": "awake", "duration": 20 * 60},   # 20 min latency
            {"stage": "light", "duration": 60 * 60},
            {"stage": "awake", "duration": 5 * 60},    # mid-night, NOT latency
            {"stage": "deep", "duration": 30 * 60},
        ],
    }
    s = _wake_stats(interval)
    assert s["latency_sec"] == 20 * 60
    assert s["waso_duration"] == 5


def test_wake_stats_latency_prefers_stage_summary():
    """When stageSummary.awakeBeforeSleepDuration is present, prefer it."""
    interval = {
        "stages": [
            {"stage": "awake", "duration": 30 * 60},
            {"stage": "light", "duration": 60 * 60},
        ],
        "stageSummary": {
            "awakeBeforeSleepDuration": 900,  # Eight's authoritative = 15 min
            "wasoDuration": 0,
        },
    }
    s = _wake_stats(interval)
    assert s["latency_sec"] == 900


def test_wake_stats_latency_none_when_no_pre_sleep_awake():
    """Sleep starts immediately — latency is None, not zero."""
    interval = {
        "stages": [
            {"stage": "light", "duration": 60 * 60},
            {"stage": "deep", "duration": 30 * 60},
        ],
    }
    s = _wake_stats(interval)
    assert s["latency_sec"] is None


def test_extract_fields_falls_back_to_trend_latency_without_interval():
    """Archive nights without interval data use presenceStart → sleepStart."""
    fields = _extract_fields(_trend_row(), None)
    # _trend_row sets presenceStart 10 min before sleepStart.
    assert fields["latency"] == 600


def test_extract_fields_populates_wake_columns():
    interval = _interval()
    # Insert a mid-night awake chunk so we have a wake-up to detect.
    interval["stages"].insert(
        3, {"stage": "awake", "duration": 8 * 60}
    )
    interval["stageSummary"] = {"wasoDuration": 480, "outDuration": 0}
    fields = _extract_fields(_trend_row(), interval)
    assert fields["wake_count"] == 1
    assert fields["waso_duration"] == 8
    assert fields["out_of_bed_count"] == 0


def test_extract_fields_wake_columns_none_without_interval():
    fields = _extract_fields(_trend_row(), None)
    assert fields["wake_count"] is None
    assert fields["waso_duration"] is None
    assert fields["out_of_bed_count"] is None
    assert fields["wake_events"] is None


def test_to_local_converts_utc_to_naive_wall_clock():
    utc = datetime(2026, 4, 16, 4, 1, 30, tzinfo=ZoneInfo("UTC"))
    local = _to_local(utc, ZoneInfo("America/New_York"))
    # April is EDT (UTC-4), so 04:01:30 UTC → 00:01:30 EDT (the prev midnight).
    assert local == datetime(2026, 4, 16, 0, 1, 30)
    assert local.tzinfo is None


def test_to_local_handles_naive_input_as_utc():
    naive = datetime(2026, 4, 16, 4, 1, 30)
    local = _to_local(naive, ZoneInfo("America/New_York"))
    assert local == datetime(2026, 4, 16, 0, 1, 30)


def test_to_local_passthrough_none():
    assert _to_local(None, ZoneInfo("UTC")) is None


def test_extract_fields_returns_bed_time_in_local_tz():
    trend = _trend_row("2026-04-16")
    trend["sleepStart"] = "2026-04-16T04:01:30Z"
    trend["sleepEnd"] = "2026-04-16T12:24:30Z"
    trend["presenceStart"] = "2026-04-16T03:18:00Z"
    interval = _interval("2026-04-16T04:00:00Z")
    interval["timezone"] = "America/New_York"

    fields = _extract_fields(trend, interval)
    # EDT = UTC-4; expect local wall-clock time.
    assert fields["bed_time"] == datetime(2026, 4, 16, 0, 1, 30)
    assert fields["wake_time"] == datetime(2026, 4, 16, 8, 24, 30)
    # Latency derives from the interval's first awake chunk (30 min in
    # the fixture), not trend-level timestamps.
    assert fields["latency"] == 30 * 60


def test_series_mean_handles_tuple_format():
    series = [["2026-04-10T06:00Z", 50], ["2026-04-10T06:05Z", 60]]
    assert _series_mean(series) == 55.0

    # Legacy raw-numbers shape still works.
    assert _series_mean([10, 20, 30]) == 20.0
    assert _series_mean(None) is None
    assert _series_mean([]) is None


# ── Upsert behavior ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_window_inserts_new_rows(db: AsyncSession):
    client = AsyncMock()
    client.get_trends.return_value = [_trend_row("2026-04-09"), _trend_row("2026-04-10")]
    # Bedtime 2026-04-09 23:00Z → wake date 2026-04-10, matching second trend.
    client.get_intervals.return_value = [_interval("2026-04-09T23:00:00Z")]

    count = await eight_sleep_sync._sync_window(db, client, date(2026, 4, 1), date(2026, 4, 11))
    assert count == 2

    rows = (await db.execute(
        select(SleepSession).where(SleepSession.source == "eight_sleep").order_by(SleepSession.date)
    )).scalars().all()
    assert [r.date for r in rows] == [date(2026, 4, 9), date(2026, 4, 10)]
    # The 10th has a matched interval, so its HR should be populated.
    assert rows[1].avg_hr is not None
    # The 9th has no interval; only trend-derived fields.
    assert rows[0].avg_hr is None


@pytest.mark.asyncio
async def test_sync_window_updates_existing_row(db: AsyncSession):
    db.add(SleepSession(
        source="eight_sleep",
        date=date(2026, 4, 10),
        sleep_score=50.0,  # stale; will be overwritten
    ))
    await db.commit()

    client = AsyncMock()
    client.get_trends.return_value = [_trend_row("2026-04-10")]
    client.get_intervals.return_value = [_interval("2026-04-09T23:00:00Z")]

    count = await eight_sleep_sync._sync_window(
        db, client, date(2026, 4, 1), date(2026, 4, 11)
    )
    assert count == 1

    row = (await db.execute(
        select(SleepSession).where(SleepSession.date == date(2026, 4, 10))
    )).scalar_one()
    assert row.sleep_score == 83.0
    assert row.avg_hr is not None


@pytest.mark.asyncio
async def test_sync_eight_sleep_writes_synclog(db: AsyncSession, monkeypatch):
    monkeypatch.setattr(
        eight_sleep_sync, "_eight_sleep_configured", lambda: True
    )
    client = AsyncMock()
    client.get_trends.return_value = []
    client.get_intervals.return_value = []

    count = await sync_eight_sleep(db, client, days=7)
    assert count == 0

    from backend.models import SyncLog
    log = (await db.execute(
        select(SyncLog).where(SyncLog.source == "eight_sleep")
    )).scalar_one()
    assert log.status == "success"
    assert log.records_synced == 0
    assert log.completed_at is not None


@pytest.mark.asyncio
async def test_sync_eight_sleep_short_circuits_when_unconfigured(db, monkeypatch):
    monkeypatch.setattr(
        eight_sleep_sync, "_eight_sleep_configured", lambda: False
    )
    client = AsyncMock()
    count = await sync_eight_sleep(db, client)
    assert count == 0
    client.get_trends.assert_not_called()
