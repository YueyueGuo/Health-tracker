"""Tests for backend.services.strength_hr.

Covers the pure slice/decimate helpers and the DB-backed
``attach_hr_to_sets`` against an in-memory SQLite DB.
"""
from __future__ import annotations

from datetime import date, datetime

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


# ── _slice_hr_for_set ───────────────────────────────────────────────


def test_slice_picks_window_ending_at_performed_at():
    """45s lookback; samples at t=[0..100] with hr=[100..200] (linear)."""
    start = datetime(2026, 4, 21, 9, 0, 0)
    time_stream = list(range(0, 101))  # 0..100s
    hr_stream = [100 + t for t in time_stream]  # 100..200

    # Set ends at 60s → window [15, 60] inclusive → 46 samples hr=115..160.
    avg, mx = _slice_hr_for_set(
        performed_at=datetime(2026, 4, 21, 9, 1, 0),
        activity_start=start,
        time_stream=time_stream,
        hr_stream=hr_stream,
        window_sec=45,
    )
    assert mx == 160.0
    assert avg == pytest.approx(137.5, abs=0.1)


def test_slice_returns_none_when_window_outside_stream():
    start = datetime(2026, 4, 21, 9, 0, 0)
    time_stream = list(range(0, 101))
    hr_stream = [140] * len(time_stream)
    # performed_at is 10 minutes after activity ends.
    avg, mx = _slice_hr_for_set(
        performed_at=datetime(2026, 4, 21, 9, 11, 0),
        activity_start=start,
        time_stream=time_stream,
        hr_stream=hr_stream,
    )
    assert (avg, mx) == (None, None)


def test_slice_skips_zero_and_none_dropouts():
    start = datetime(2026, 4, 21, 9, 0, 0)
    time_stream = [0, 10, 20, 30, 40]
    hr_stream = [0, None, 140, 150, 0]
    avg, mx = _slice_hr_for_set(
        performed_at=datetime(2026, 4, 21, 9, 0, 45),
        activity_start=start,
        time_stream=time_stream,
        hr_stream=hr_stream,
    )
    assert avg == pytest.approx(145.0, abs=0.1)
    assert mx == 150.0


def test_slice_handles_mismatched_lengths():
    """Strava occasionally truncates one of the two arrays — fall back to min."""
    start = datetime(2026, 4, 21, 9, 0, 0)
    time_stream = [0, 10, 20, 30, 40, 50]
    hr_stream = [140, 145, 150]  # shorter
    avg, mx = _slice_hr_for_set(
        performed_at=datetime(2026, 4, 21, 9, 0, 30),
        activity_start=start,
        time_stream=time_stream,
        hr_stream=hr_stream,
    )
    # Window (-15, 30] picks indices 0..2 → hr=140,145,150.
    assert avg == pytest.approx(145.0, abs=0.1)
    assert mx == 150.0


def test_slice_all_dropouts_returns_none():
    start = datetime(2026, 4, 21, 9, 0, 0)
    time_stream = [0, 10, 20, 30]
    hr_stream = [0, 0, None, 0]
    assert _slice_hr_for_set(
        performed_at=datetime(2026, 4, 21, 9, 0, 30),
        activity_start=start,
        time_stream=time_stream,
        hr_stream=hr_stream,
    ) == (None, None)


def test_slice_empty_streams():
    start = datetime(2026, 4, 21, 9, 0, 0)
    assert _slice_hr_for_set(start, start, [], []) == (None, None)
    assert _slice_hr_for_set(start, start, [0], []) == (None, None)


# ── _decimate ──────────────────────────────────────────────────────


def test_decimate_respects_target_points():
    n = 3600  # 1Hz for 60 minutes
    time_stream = list(range(n))
    hr_stream = [140] * n
    out = _decimate(time_stream, hr_stream, target_points=300)
    # step = 3600 // 300 = 12 → 300 points.
    assert len(out) == 300
    assert out[0] == [0, 140.0]
    assert out[-1][0] == 3588  # last step


def test_decimate_skips_dropouts():
    time_stream = list(range(10))
    hr_stream = [0, 140, None, 150, 0, 160, 0, 170, 180, 0]
    out = _decimate(time_stream, hr_stream, target_points=10)
    # step=1, filters out zero/None.
    assert out == [[1, 140.0], [3, 150.0], [5, 160.0], [7, 170.0], [8, 180.0]]


def test_decimate_short_stream_returns_all_valid():
    time_stream = [0, 1, 2]
    hr_stream = [140, 145, 150]
    out = _decimate(time_stream, hr_stream, target_points=CURVE_TARGET_POINTS)
    assert out == [[0, 140.0], [1, 145.0], [2, 150.0]]


def test_decimate_empty():
    assert _decimate([], []) == []
    assert _decimate([0], []) == []


# ── attach_hr_to_sets (DB-backed) ──────────────────────────────────


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


_next_id_counter = [100_000]


def _next_strava_id() -> int:
    _next_id_counter[0] += 1
    return _next_id_counter[0]


async def _seed_activity_with_streams(
    db: AsyncSession,
    start: datetime,
    time_stream: list | None,
    hr_stream: list | None,
) -> Activity:
    activity = Activity(
        strava_id=_next_strava_id(),
        name="Lift",
        sport_type="WeightTraining",
        start_date=start,
        start_date_local=start,
    )
    db.add(activity)
    await db.flush()
    if time_stream is not None:
        db.add(ActivityStream(activity_id=activity.id, stream_type="time", data=time_stream))
    if hr_stream is not None:
        db.add(
            ActivityStream(activity_id=activity.id, stream_type="heartrate", data=hr_stream)
        )
    await db.commit()
    return activity


async def test_attach_hr_returns_per_set_stats_and_curve(db: AsyncSession):
    start = datetime(2026, 4, 21, 9, 0, 0)
    time_stream = list(range(0, 600))  # 10 minutes
    hr_stream = [100 + (t // 60) * 10 for t in time_stream]  # ramps 100→190
    activity = await _seed_activity_with_streams(db, start, time_stream, hr_stream)

    sets = [
        StrengthSet(
            date=date(2026, 4, 21),
            exercise_name="Squat",
            set_number=1,
            reps=5,
            weight_kg=100,
            performed_at=datetime(2026, 4, 21, 9, 1, 0),  # offset 60s
            activity_id=activity.id,
        ),
        StrengthSet(
            date=date(2026, 4, 21),
            exercise_name="Squat",
            set_number=2,
            reps=5,
            weight_kg=100,
            performed_at=datetime(2026, 4, 21, 9, 3, 0),  # offset 180s
            activity_id=activity.id,
        ),
    ]
    for s in sets:
        db.add(s)
    await db.commit()

    out = await attach_hr_to_sets(db, activity.id, sets)
    assert set(out.keys()) == {"hr_by_set_id", "hr_curve", "activity_start_iso"}
    assert out["activity_start_iso"] == start.isoformat()
    assert len(out["hr_by_set_id"]) == 2
    # Each stats dict has both keys.
    for stats in out["hr_by_set_id"].values():
        assert set(stats.keys()) == {"avg_hr", "max_hr"}
        assert stats["max_hr"] >= stats["avg_hr"]
    # Curve is decimated (<= target points).
    assert 0 < len(out["hr_curve"]) <= CURVE_TARGET_POINTS


async def test_attach_hr_empty_when_no_performed_at(db: AsyncSession):
    start = datetime(2026, 4, 21, 9, 0, 0)
    activity = await _seed_activity_with_streams(
        db, start, list(range(60)), [140] * 60
    )
    sets = [
        StrengthSet(
            date=date(2026, 4, 21),
            exercise_name="Squat",
            set_number=1,
            reps=5,
            weight_kg=100,
            performed_at=None,
            activity_id=activity.id,
        ),
    ]
    for s in sets:
        db.add(s)
    await db.commit()
    assert await attach_hr_to_sets(db, activity.id, sets) == {}


async def test_attach_hr_empty_when_streams_missing(db: AsyncSession):
    start = datetime(2026, 4, 21, 9, 0, 0)
    # Seed activity without streams.
    activity = await _seed_activity_with_streams(db, start, None, None)
    sets = [
        StrengthSet(
            date=date(2026, 4, 21),
            exercise_name="Squat",
            set_number=1,
            reps=5,
            weight_kg=100,
            performed_at=datetime(2026, 4, 21, 9, 1, 0),
            activity_id=activity.id,
        ),
    ]
    for s in sets:
        db.add(s)
    await db.commit()
    assert await attach_hr_to_sets(db, activity.id, sets) == {}


async def test_attach_hr_empty_when_only_one_stream_cached(db: AsyncSession):
    start = datetime(2026, 4, 21, 9, 0, 0)
    # Time only, no HR.
    activity = await _seed_activity_with_streams(db, start, list(range(60)), None)
    sets = [
        StrengthSet(
            date=date(2026, 4, 21),
            exercise_name="Squat",
            set_number=1,
            reps=5,
            weight_kg=100,
            performed_at=datetime(2026, 4, 21, 9, 0, 30),
            activity_id=activity.id,
        ),
    ]
    for s in sets:
        db.add(s)
    await db.commit()
    assert await attach_hr_to_sets(db, activity.id, sets) == {}


async def test_attach_hr_empty_when_activity_missing(db: AsyncSession):
    """Stale FK — activity row was deleted but set still references it."""
    sets = [
        StrengthSet(
            id=999,
            date=date(2026, 4, 21),
            exercise_name="Squat",
            set_number=1,
            reps=5,
            weight_kg=100,
            performed_at=datetime(2026, 4, 21, 9, 0, 30),
            activity_id=404,
        ),
    ]
    assert await attach_hr_to_sets(db, 404, sets) == {}


async def test_attach_hr_skips_set_with_window_outside_stream(db: AsyncSession):
    """Set logged 10 min after activity ended → no sample in window."""
    start = datetime(2026, 4, 21, 9, 0, 0)
    activity = await _seed_activity_with_streams(
        db, start, list(range(60)), [140] * 60
    )
    sets = [
        StrengthSet(
            date=date(2026, 4, 21),
            exercise_name="Squat",
            set_number=1,
            reps=5,
            weight_kg=100,
            performed_at=datetime(2026, 4, 21, 9, 0, 30),  # in-window
            activity_id=activity.id,
        ),
        StrengthSet(
            date=date(2026, 4, 21),
            exercise_name="Squat",
            set_number=2,
            reps=5,
            weight_kg=100,
            performed_at=datetime(2026, 4, 21, 9, 10, 0),  # way out
            activity_id=activity.id,
        ),
    ]
    for s in sets:
        db.add(s)
    await db.commit()
    out = await attach_hr_to_sets(db, activity.id, sets)
    assert out != {}
    # Only the first set has stats.
    assert len(out["hr_by_set_id"]) == 1
    assert sets[0].id in out["hr_by_set_id"]
    assert sets[1].id not in out["hr_by_set_id"]
