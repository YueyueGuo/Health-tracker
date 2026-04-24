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


async def test_session_summary_round_trips_performed_at(db: AsyncSession):
    today = date.today()
    stamped = datetime(today.year, today.month, today.day, 10, 30, 0)
    await _seed(
        db,
        [
            StrengthSet(
                date=today,
                exercise_name="Squat",
                set_number=1,
                reps=5,
                weight_kg=100,
                performed_at=stamped,
            ),
            StrengthSet(
                date=today,
                exercise_name="Squat",
                set_number=2,
                reps=5,
                weight_kg=100,
                performed_at=None,
            ),
        ],
    )
    summary = await session_summary(db, today)
    assert summary is not None
    stamps = [s["performed_at"] for s in summary["sets"]]
    assert stamps == [stamped.isoformat(), None]


async def test_session_summary_merges_hr_when_streams_cached(db: AsyncSession):
    """When a linked activity has cached time + heartrate streams, each
    set with ``performed_at`` gets ``avg_hr``/``max_hr`` merged in and the
    top-level payload carries ``hr_curve`` + ``activity_start_iso``."""
    today = date.today()
    start = datetime(today.year, today.month, today.day, 9, 0, 0)
    activity = Activity(
        strava_id=999_001,
        name="Lift",
        sport_type="WeightTraining",
        start_date=start,
        start_date_local=start,
    )
    db.add(activity)
    await db.flush()
    time_stream = list(range(0, 600))
    hr_stream = [140 + (t // 120) * 5 for t in time_stream]
    db.add(ActivityStream(activity_id=activity.id, stream_type="time", data=time_stream))
    db.add(
        ActivityStream(activity_id=activity.id, stream_type="heartrate", data=hr_stream)
    )
    await _seed(
        db,
        [
            StrengthSet(
                date=today,
                exercise_name="Squat",
                set_number=1,
                reps=5,
                weight_kg=100,
                performed_at=datetime(today.year, today.month, today.day, 9, 2, 0),
                activity_id=activity.id,
            ),
            StrengthSet(
                date=today,
                exercise_name="Squat",
                set_number=2,
                reps=5,
                weight_kg=100,
                performed_at=None,
                activity_id=activity.id,
            ),
        ],
    )

    summary = await session_summary(db, today)
    assert summary is not None
    assert summary["activity_start_iso"] == start.isoformat()
    assert isinstance(summary["hr_curve"], list) and summary["hr_curve"]
    logged = next(s for s in summary["sets"] if s["performed_at"] is not None)
    unlogged = next(s for s in summary["sets"] if s["performed_at"] is None)
    assert "avg_hr" in logged and "max_hr" in logged
    assert logged["avg_hr"] <= logged["max_hr"]
    assert "avg_hr" not in unlogged
    # And also merged into the per-exercise breakdown.
    ex_sets = summary["exercises"][0]["sets"]
    assert any("avg_hr" in s for s in ex_sets)


async def test_session_summary_no_hr_when_streams_missing(db: AsyncSession):
    """No cached streams → payload has no ``hr_curve`` / ``activity_start_iso``."""
    today = date.today()
    start = datetime(today.year, today.month, today.day, 9, 0, 0)
    activity = Activity(
        strava_id=999_002,
        name="Lift",
        sport_type="WeightTraining",
        start_date=start,
        start_date_local=start,
    )
    db.add(activity)
    await db.flush()
    await _seed(
        db,
        [
            StrengthSet(
                date=today,
                exercise_name="Squat",
                set_number=1,
                reps=5,
                weight_kg=100,
                performed_at=datetime(today.year, today.month, today.day, 9, 2, 0),
                activity_id=activity.id,
            ),
        ],
    )
    summary = await session_summary(db, today)
    assert summary is not None
    assert "hr_curve" not in summary
    assert "activity_start_iso" not in summary
    assert "avg_hr" not in summary["sets"][0]


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
