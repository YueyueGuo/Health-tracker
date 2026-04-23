"""Tests for backend.services.strength_hr.

Covers the pure HR-slicing helper plus the DB-backed ``attach_hr_to_sets``
against an in-memory SQLite DB with pre-seeded ``activity_streams`` rows.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models import Activity, ActivityStream, StrengthSet
from backend.services.strength_hr import (
    CURVE_TARGET_POINTS,
    _decimate,
    _slice_hr_for_set,
    attach_hr_to_sets,
)


# ── Pure helper: _slice_hr_for_set ─────────────────────────────────────


def test_slice_hr_for_set_happy():
    """Window ending at T=600s pulls the last 45s of HR samples."""
    start = datetime(2026, 4, 22, 9, 0, 0)
    # 1Hz stream, 0..700s.
    time_stream = list(range(701))
    hr_stream = [120.0] * 400 + [150.0] * 301  # step up at t=400
    performed_at = start + timedelta(seconds=600)
    avg, mx = _slice_hr_for_set(
        performed_at, start, time_stream, hr_stream, window_sec=45
    )
    # Window is [555, 600] inclusive → 46 samples, all 150.
    assert avg == 150.0
    assert mx == 150.0


def test_slice_hr_for_set_window_before_start():
    """performed_at before activity start → no samples land in window."""
    start = datetime(2026, 4, 22, 9, 0, 0)
    time_stream = list(range(100))
    hr_stream = [140.0] * 100
    performed_at = start - timedelta(seconds=60)
    assert _slice_hr_for_set(performed_at, start, time_stream, hr_stream) == (None, None)


def test_slice_hr_for_set_window_after_stream_end():
    """performed_at beyond stream end → no samples in window."""
    start = datetime(2026, 4, 22, 9, 0, 0)
    time_stream = list(range(100))
    hr_stream = [140.0] * 100
    performed_at = start + timedelta(seconds=500)
    # Window is [455, 500], stream ends at 99 → empty.
    assert _slice_hr_for_set(performed_at, start, time_stream, hr_stream) == (None, None)


def test_slice_hr_for_set_ignores_zero_and_none_samples():
    """Dropout samples (0 / None) excluded from avg/max computation."""
    start = datetime(2026, 4, 22, 9, 0, 0)
    time_stream = list(range(60))
    # First 30s: valid 120 bpm. Last 30s: dropouts mixed with valid 180.
    hr_stream: list = [120.0] * 30 + [180.0, 0, None] * 10
    performed_at = start + timedelta(seconds=59)
    # window_sec=29 → window [30, 59] (30 samples of the dropout region).
    avg, mx = _slice_hr_for_set(
        performed_at, start, time_stream, hr_stream, window_sec=29
    )
    # 30 samples = [180, 0, None, 180, 0, None, ...] → 10 valid at 180.
    assert avg == 180.0
    assert mx == 180.0


def test_slice_hr_for_set_empty_stream():
    start = datetime(2026, 4, 22, 9, 0, 0)
    assert _slice_hr_for_set(start, start, [], []) == (None, None)


def test_slice_hr_for_set_mismatched_lengths_tolerated():
    """Defensive: if Strava returns mismatched lengths, truncate to shorter."""
    start = datetime(2026, 4, 22, 9, 0, 0)
    time_stream = list(range(100))
    hr_stream = [140.0] * 50  # shorter
    performed_at = start + timedelta(seconds=45)
    avg, mx = _slice_hr_for_set(
        performed_at, start, time_stream, hr_stream, window_sec=45
    )
    # Both truncate to 50 samples; window [0, 45] → 46 samples of 140.
    assert avg == 140.0
    assert mx == 140.0


# ── Pure helper: _decimate ─────────────────────────────────────────────


def test_decimate_short_stream_returns_all_valid():
    """Stream < target → every valid sample included (step=1)."""
    time_stream = [0, 1, 2, 3, 4]
    hr_stream = [120.0, 130.0, 0, 140.0, None]
    out = _decimate(time_stream, hr_stream, target_points=300)
    # Zeros/Nones dropped.
    assert out == [[0, 120.0], [1, 130.0], [3, 140.0]]


def test_decimate_large_stream_under_target():
    """3000-sample stream → roughly CURVE_TARGET_POINTS entries."""
    time_stream = list(range(3000))
    hr_stream = [float(140 + (i % 40)) for i in range(3000)]
    out = _decimate(time_stream, hr_stream)
    # step = 3000 // 300 = 10, so roughly 300 entries.
    assert len(out) == pytest.approx(CURVE_TARGET_POINTS, abs=5)
    # First entry is at t=0, last entry is within one step of the end.
    assert out[0][0] == 0
    assert out[-1][0] >= 2990


# ── DB-backed: attach_hr_to_sets ───────────────────────────────────────


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


async def _seed_activity_with_streams(
    db: AsyncSession,
    *,
    include_time: bool = True,
    include_hr: bool = True,
    duration_sec: int = 1800,
) -> Activity:
    start = datetime(2026, 4, 22, 9, 0, 0)
    act = Activity(
        strava_id=111,
        name="Lifting",
        sport_type="WeightTraining",
        start_date=start,
        start_date_local=start,
        moving_time=duration_sec,
    )
    db.add(act)
    await db.commit()
    await db.refresh(act)

    if include_time:
        db.add(
            ActivityStream(
                activity_id=act.id,
                stream_type="time",
                data=list(range(duration_sec + 1)),
            )
        )
    if include_hr:
        # Baseline 100 bpm, spike to 160 at t∈[590,600] (set 1) and
        # [1190,1200] (set 2).
        hr = [100.0] * (duration_sec + 1)
        for i in range(590, 601):
            hr[i] = 160.0
        for i in range(1190, 1201):
            hr[i] = 155.0
        db.add(
            ActivityStream(activity_id=act.id, stream_type="heartrate", data=hr)
        )
    await db.commit()
    return act


async def test_attach_hr_to_sets_no_streams_cached(db: AsyncSession):
    """Activity exists but no stream rows → empty dict, no per-set HR."""
    act = await _seed_activity_with_streams(db, include_time=False, include_hr=False)
    set_row = StrengthSet(
        activity_id=act.id,
        date=date(2026, 4, 22),
        exercise_name="Squat",
        set_number=1,
        reps=5,
        weight_kg=60.0,
        performed_at=datetime(2026, 4, 22, 9, 10, 0),
    )
    db.add(set_row)
    await db.commit()
    await db.refresh(set_row)
    out = await attach_hr_to_sets(db, act.id, [set_row])
    assert out == {}


async def test_attach_hr_to_sets_no_performed_at(db: AsyncSession):
    """Streams cached but no set has performed_at → empty (nothing to map)."""
    act = await _seed_activity_with_streams(db)
    set_row = StrengthSet(
        activity_id=act.id,
        date=date(2026, 4, 22),
        exercise_name="Squat",
        set_number=1,
        reps=5,
        weight_kg=60.0,
    )
    db.add(set_row)
    await db.commit()
    await db.refresh(set_row)
    out = await attach_hr_to_sets(db, act.id, [set_row])
    assert out == {}


async def test_attach_hr_to_sets_missing_activity(db: AsyncSession):
    """Stale activity_id → graceful empty dict."""
    set_row = StrengthSet(
        activity_id=999,  # doesn't exist
        date=date(2026, 4, 22),
        exercise_name="Squat",
        set_number=1,
        reps=5,
        weight_kg=60.0,
        performed_at=datetime(2026, 4, 22, 9, 10, 0),
    )
    db.add(set_row)
    await db.commit()
    await db.refresh(set_row)
    out = await attach_hr_to_sets(db, 999, [set_row])
    assert out == {}


async def test_attach_hr_to_sets_full(db: AsyncSession):
    """End-to-end: two sets at the two HR spikes → expected avg/max per set."""
    act = await _seed_activity_with_streams(db)
    sets = [
        StrengthSet(
            activity_id=act.id,
            date=date(2026, 4, 22),
            exercise_name="Squat",
            set_number=1,
            reps=5,
            weight_kg=60.0,
            # End at t=10min → spike window [555..600] contains the
            # 11 samples at 160.
            performed_at=datetime(2026, 4, 22, 9, 10, 0),
        ),
        StrengthSet(
            activity_id=act.id,
            date=date(2026, 4, 22),
            exercise_name="Squat",
            set_number=2,
            reps=5,
            weight_kg=65.0,
            # End at t=20min → window [1155..1200] contains 11 samples at 155.
            performed_at=datetime(2026, 4, 22, 9, 20, 0),
        ),
    ]
    for s in sets:
        db.add(s)
    await db.commit()
    for s in sets:
        await db.refresh(s)

    out = await attach_hr_to_sets(db, act.id, sets)
    assert out["activity_start_iso"] == "2026-04-22T09:00:00"
    assert "hr_curve" in out and len(out["hr_curve"]) > 0
    hr = out["hr_by_set_id"]
    assert sets[0].id in hr and sets[1].id in hr
    # Set 1: window has 35 baseline samples (100) + 11 spike samples (160).
    # avg = (35*100 + 11*160) / 46 ≈ 114.3. max = 160.
    assert hr[sets[0].id]["max_hr"] == 160.0
    assert hr[sets[0].id]["avg_hr"] == pytest.approx(114.3, abs=0.3)
    assert hr[sets[1].id]["max_hr"] == 155.0


async def test_attach_hr_to_sets_missing_one_stream_type(db: AsyncSession):
    """Only time cached, heartrate missing → empty dict."""
    act = await _seed_activity_with_streams(db, include_hr=False)
    set_row = StrengthSet(
        activity_id=act.id,
        date=date(2026, 4, 22),
        exercise_name="Squat",
        set_number=1,
        reps=5,
        weight_kg=60.0,
        performed_at=datetime(2026, 4, 22, 9, 10, 0),
    )
    db.add(set_row)
    await db.commit()
    await db.refresh(set_row)
    out = await attach_hr_to_sets(db, act.id, [set_row])
    assert out == {}
