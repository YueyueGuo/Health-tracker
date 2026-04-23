"""Tests for backend.services.strength.

Covers the pure Epley 1RM helper and the session/progression query
helpers against an in-memory SQLite DB.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models import Activity, ActivityStream, StrengthSet
from backend.services.strength import (
    estimate_1rm,
    list_sessions,
    progression,
    search_exercises,
    session_summary,
)


# ── estimate_1rm ────────────────────────────────────────────────────


def test_estimate_1rm_single_rep():
    """A 1RM set returns its own weight (no extrapolation)."""
    assert estimate_1rm(100.0, 1) == 100.0


def test_estimate_1rm_multi_rep():
    """Epley: 100 * (1 + 5/30) ≈ 116.67."""
    assert estimate_1rm(100.0, 5) == pytest.approx(116.67, abs=0.01)


def test_estimate_1rm_beyond_12_reps():
    """Epley breaks down beyond 12 reps — return None."""
    assert estimate_1rm(100.0, 13) is None
    assert estimate_1rm(60.0, 20) is None


def test_estimate_1rm_zero_weight():
    """Bodyweight / placeholder rows → 0."""
    assert estimate_1rm(0.0, 5) == 0.0
    assert estimate_1rm(0.0, 1) == 0.0


def test_estimate_1rm_nonpositive_reps():
    """Refuse to extrapolate 0 or negative rep counts."""
    assert estimate_1rm(100.0, 0) is None
    assert estimate_1rm(100.0, -1) is None


# ── DB-backed helpers ──────────────────────────────────────────────


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


async def _seed(db: AsyncSession, rows: list[StrengthSet]) -> None:
    for r in rows:
        db.add(r)
    await db.commit()


async def test_list_sessions_groups_by_date_newest_first(db: AsyncSession):
    today = date.today()
    yesterday = today - timedelta(days=1)
    await _seed(
        db,
        [
            StrengthSet(date=yesterday, exercise_name="Squat", set_number=1, reps=5, weight_kg=100),
            StrengthSet(date=yesterday, exercise_name="Squat", set_number=2, reps=5, weight_kg=100),
            StrengthSet(date=today, exercise_name="Bench", set_number=1, reps=5, weight_kg=80),
            StrengthSet(date=today, exercise_name="Row", set_number=1, reps=10, weight_kg=60),
        ],
    )
    sessions = await list_sessions(db, limit=10)
    assert len(sessions) == 2
    # Newest first.
    assert sessions[0]["date"] == today.isoformat()
    assert sessions[0]["exercise_count"] == 2
    assert sessions[0]["total_sets"] == 2
    assert sessions[0]["total_volume_kg"] == pytest.approx(5 * 80 + 10 * 60)
    assert sessions[1]["exercise_count"] == 1
    assert sessions[1]["total_sets"] == 2
    assert sessions[1]["total_volume_kg"] == pytest.approx(2 * 5 * 100)


async def test_session_summary_groups_by_exercise(db: AsyncSession):
    today = date.today()
    await _seed(
        db,
        [
            StrengthSet(date=today, exercise_name="Squat", set_number=1, reps=5, weight_kg=100),
            StrengthSet(date=today, exercise_name="Squat", set_number=2, reps=3, weight_kg=110),
            StrengthSet(date=today, exercise_name="Bench", set_number=1, reps=5, weight_kg=80),
        ],
    )
    summary = await session_summary(db, today)
    assert summary is not None
    assert summary["date"] == today.isoformat()
    assert len(summary["sets"]) == 3
    by_name = {ex["name"]: ex for ex in summary["exercises"]}
    assert set(by_name.keys()) == {"Squat", "Bench"}
    squat = by_name["Squat"]
    assert squat["max_weight"] == 110
    assert squat["total_volume"] == pytest.approx(5 * 100 + 3 * 110)
    # Best Epley across both squat sets: 110 * (1 + 3/30) = 121 vs
    # 100 * (1 + 5/30) ≈ 116.67 → 121 wins.
    assert squat["est_1rm"] == pytest.approx(121.0, abs=0.01)


async def test_session_summary_empty_date(db: AsyncSession):
    assert await session_summary(db, date.today()) is None


async def test_progression_per_date_aggregates(db: AsyncSession):
    today = date.today()
    await _seed(
        db,
        [
            StrengthSet(date=today - timedelta(days=2), exercise_name="Squat",
                        set_number=1, reps=5, weight_kg=100),
            StrengthSet(date=today - timedelta(days=2), exercise_name="Squat",
                        set_number=2, reps=5, weight_kg=100),
            StrengthSet(date=today, exercise_name="Squat",
                        set_number=1, reps=3, weight_kg=110),
            # Other exercise should be ignored.
            StrengthSet(date=today, exercise_name="Bench",
                        set_number=1, reps=5, weight_kg=80),
            # Set with no weight should be ignored.
            StrengthSet(date=today - timedelta(days=1), exercise_name="Squat",
                        set_number=1, reps=10, weight_kg=None),
        ],
    )
    out = await progression(db, exercise_name="Squat", days=30)
    # Two dated points (days with weighted squat sets), oldest first.
    assert len(out) == 2
    assert out[0]["date"] == (today - timedelta(days=2)).isoformat()
    assert out[0]["max_weight_kg"] == 100
    assert out[0]["top_set_reps"] == 5
    assert out[0]["total_volume_kg"] == pytest.approx(2 * 5 * 100)
    assert out[1]["max_weight_kg"] == 110
    assert out[1]["est_1rm_kg"] == pytest.approx(121.0, abs=0.01)


async def test_session_summary_includes_hr_when_streams_cached(db: AsyncSession):
    """With a linked activity, cached streams, and sets carrying
    performed_at, session_summary emits hr_curve + per-set avg/max HR."""
    start = datetime(2026, 4, 22, 9, 0, 0)
    act = Activity(
        strava_id=222,
        name="Lift",
        sport_type="WeightTraining",
        start_date=start,
        start_date_local=start,
        moving_time=1800,
    )
    db.add(act)
    await db.commit()
    await db.refresh(act)

    db.add(
        ActivityStream(
            activity_id=act.id, stream_type="time", data=list(range(1801))
        )
    )
    hr = [110.0] * 1801
    for i in range(555, 601):
        hr[i] = 150.0
    db.add(ActivityStream(activity_id=act.id, stream_type="heartrate", data=hr))
    await db.commit()

    today = date(2026, 4, 22)
    await _seed(
        db,
        [
            StrengthSet(
                activity_id=act.id,
                date=today,
                exercise_name="Squat",
                set_number=1,
                reps=5,
                weight_kg=100,
                performed_at=start + timedelta(seconds=600),
            ),
        ],
    )

    summary = await session_summary(db, today)
    assert summary is not None
    assert summary["hr_curve"] is not None and len(summary["hr_curve"]) > 0
    assert summary["activity_start_iso"] == start.isoformat()
    set_dict = summary["exercises"][0]["sets"][0]
    assert set_dict["performed_at"] is not None
    assert set_dict["avg_hr"] is not None
    assert set_dict["max_hr"] == 150.0


async def test_session_summary_no_hr_when_no_streams(db: AsyncSession):
    """Without cached streams, HR fields are None but the session still renders."""
    today = date(2026, 4, 22)
    await _seed(
        db,
        [
            StrengthSet(
                date=today,
                exercise_name="Squat",
                set_number=1,
                reps=5,
                weight_kg=100,
            ),
        ],
    )
    summary = await session_summary(db, today)
    assert summary is not None
    assert summary["hr_curve"] is None
    assert summary["activity_start_iso"] is None
    set_dict = summary["exercises"][0]["sets"][0]
    assert set_dict["performed_at"] is None
    assert set_dict["avg_hr"] is None
    assert set_dict["max_hr"] is None


async def test_search_exercises_prefix_match(db: AsyncSession):
    today = date.today()
    await _seed(
        db,
        [
            StrengthSet(date=today, exercise_name="Back Squat", set_number=1, reps=5, weight_kg=100),
            StrengthSet(date=today, exercise_name="Bench Press", set_number=1, reps=5, weight_kg=80),
            StrengthSet(date=today, exercise_name="Barbell Row", set_number=1, reps=5, weight_kg=60),
            StrengthSet(date=today, exercise_name="Deadlift", set_number=1, reps=5, weight_kg=120),
        ],
    )
    # Case-insensitive prefix match.
    names = await search_exercises(db, q="b")
    assert set(names) == {"Back Squat", "Bench Press", "Barbell Row"}
    # Empty q → all distinct names.
    all_names = await search_exercises(db, q=None)
    assert set(all_names) == {"Back Squat", "Bench Press", "Barbell Row", "Deadlift"}
