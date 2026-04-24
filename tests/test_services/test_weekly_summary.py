"""Tests for backend.services.weekly_summary.

Seeds a small set of activities in an in-memory SQLite DB and verifies
the week_summary / weekly_summaries outputs — totals, per-sport
breakdown, run-classification breakdown, flags, notable-activity
pointers, and enrichment/classification pending counters.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models import Activity
import backend.services.weekly_summary as weekly_summary_module
from backend.services.weekly_summary import (
    iso_week_start,
    week_summary,
    weekly_summaries,
)


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


def _mk(
    *,
    strava_id: int,
    start: datetime,
    sport: str = "Run",
    duration_s: int = 1800,
    distance_m: float = 5000.0,
    elevation_m: float = 0.0,
    suffer: int | None = None,
    kj: float | None = None,
    calories: float | None = None,
    classification: str | None = None,
    classification_flags: list[str] | None = None,
    enrichment: str = "complete",
) -> Activity:
    return Activity(
        strava_id=strava_id,
        name=f"Activity {strava_id}",
        sport_type=sport,
        start_date=start,
        start_date_local=start,
        moving_time=duration_s,
        distance=distance_m,
        total_elevation=elevation_m,
        suffer_score=suffer,
        kilojoules=kj,
        calories=calories,
        classification_type=classification,
        classification_flags=classification_flags,
        enrichment_status=enrichment,
    )


# A week we control: Monday 2026-04-13 → Sunday 2026-04-19.
MONDAY = date(2026, 4, 13)


# ── iso_week_start ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "d,expected",
    [
        (date(2026, 4, 13), date(2026, 4, 13)),  # Monday
        (date(2026, 4, 14), date(2026, 4, 13)),  # Tuesday
        (date(2026, 4, 19), date(2026, 4, 13)),  # Sunday
        (date(2026, 4, 20), date(2026, 4, 20)),  # next Monday
    ],
)
def test_iso_week_start_snaps_to_monday(d, expected):
    assert iso_week_start(d) == expected


# ── Empty weeks ────────────────────────────────────────────────────


async def test_empty_week_returns_zeroed_totals(db):
    summary = await week_summary(db, MONDAY)
    assert summary["totals"]["activity_count"] == 0
    assert summary["totals"]["duration_s"] == 0
    assert summary["totals"]["distance_m"] == 0.0
    assert summary["by_sport"] == {}
    assert summary["run_breakdown"] == {}
    assert summary["notable"]["longest_activity_id"] is None
    assert summary["notable"]["hardest_activity_id"] is None
    assert summary["enrichment_pending"] == 0
    assert summary["classification_pending"] == 0


async def test_non_monday_start_date_is_snapped(db):
    """Passing a Thursday should produce the same summary as passing
    that week's Monday."""
    thursday = MONDAY + timedelta(days=3)
    t = await week_summary(db, thursday)
    m = await week_summary(db, MONDAY)
    assert t["week_start"] == m["week_start"]


async def test_week_bounds_exclude_neighbouring_weeks(db):
    """Activities in the prior week or the next week must not leak in."""
    db.add_all(
        [
            _mk(
                strava_id=1,
                start=datetime(2026, 4, 12, 23, 30),  # Sun 23:30 = prior week
                duration_s=1200,
                distance_m=3000,
            ),
            _mk(
                strava_id=2,
                start=datetime(2026, 4, 15, 7, 0),  # Wednesday — in week
                duration_s=1800,
                distance_m=5000,
            ),
            _mk(
                strava_id=3,
                start=datetime(2026, 4, 20, 6, 0),  # next Monday — out
                duration_s=999,
                distance_m=999,
            ),
        ]
    )
    await db.commit()

    summary = await week_summary(db, MONDAY)
    assert summary["totals"]["activity_count"] == 1
    assert summary["totals"]["duration_s"] == 1800


# ── Totals + breakdowns ────────────────────────────────────────────


async def test_totals_and_by_sport(db):
    db.add_all(
        [
            _mk(
                strava_id=1,
                start=datetime(2026, 4, 13, 8),
                sport="Run",
                duration_s=1800,
                distance_m=5000,
                elevation_m=40,
                kj=0,
                suffer=30,
                calories=400,
            ),
            _mk(
                strava_id=2,
                start=datetime(2026, 4, 14, 8),
                sport="Ride",
                duration_s=3600,
                distance_m=25_000,
                elevation_m=150,
                kj=500.2,
                suffer=40,
                calories=650,
            ),
            _mk(
                strava_id=3,
                start=datetime(2026, 4, 15, 8),
                sport="WeightTraining",
                duration_s=2700,
                distance_m=0,
                elevation_m=0,
                suffer=10,
                calories=200,
            ),
        ]
    )
    await db.commit()

    s = await week_summary(db, MONDAY)
    assert s["totals"]["activity_count"] == 3
    assert s["totals"]["duration_s"] == 1800 + 3600 + 2700
    assert s["totals"]["distance_m"] == 30_000
    assert s["totals"]["total_elevation_m"] == 190
    assert s["totals"]["suffer_score"] == 80
    assert s["totals"]["kilojoules"] == 500.2
    assert s["totals"]["calories"] == 1250

    assert set(s["by_sport"].keys()) == {"Run", "Ride", "WeightTraining"}
    assert s["by_sport"]["Ride"]["count"] == 1
    assert s["by_sport"]["Ride"]["distance_m"] == 25_000
    assert s["by_sport"]["WeightTraining"]["count"] == 1


async def test_unknown_sport_bucketed_under_unknown(db):
    """Empty sport_type falls back to the 'Unknown' bucket label."""
    db.add(
        _mk(strava_id=1, start=datetime(2026, 4, 14, 10), sport="", distance_m=0)
    )
    await db.commit()
    s = await week_summary(db, MONDAY)
    assert "Unknown" in s["by_sport"]


async def test_run_breakdown_per_classification(db):
    db.add_all(
        [
            _mk(
                strava_id=1,
                start=datetime(2026, 4, 13, 7),
                classification="easy",
                distance_m=6000,
            ),
            _mk(
                strava_id=2,
                start=datetime(2026, 4, 14, 7),
                classification="easy",
                distance_m=7000,
            ),
            _mk(
                strava_id=3,
                start=datetime(2026, 4, 15, 7),
                classification="tempo",
                distance_m=8000,
            ),
            _mk(
                strava_id=4,
                start=datetime(2026, 4, 15, 17),
                sport="Ride",
                classification="endurance",
                distance_m=30_000,
            ),
        ]
    )
    await db.commit()

    s = await week_summary(db, MONDAY)
    # Only runs show up in run_breakdown.
    assert set(s["run_breakdown"].keys()) == {"easy", "tempo"}
    assert s["run_breakdown"]["easy"]["count"] == 2
    assert s["run_breakdown"]["easy"]["distance_m"] == 13_000
    assert s["run_breakdown"]["tempo"]["count"] == 1


async def test_run_breakdown_buckets_unclassified_runs(db):
    db.add(
        _mk(
            strava_id=1,
            start=datetime(2026, 4, 14, 7),
            classification=None,
            distance_m=5000,
        )
    )
    await db.commit()
    s = await week_summary(db, MONDAY)
    assert "unclassified" in s["run_breakdown"]


# ── Flags ──────────────────────────────────────────────────────────


async def test_flags_has_long_run_tracks_max_distance(db):
    db.add_all(
        [
            _mk(
                strava_id=1,
                start=datetime(2026, 4, 13, 7),
                classification="easy",
                classification_flags=["is_long"],
                distance_m=18_000,
            ),
            _mk(
                strava_id=2,
                start=datetime(2026, 4, 15, 7),
                classification="easy",
                classification_flags=["is_long"],
                distance_m=22_000,
            ),
        ]
    )
    await db.commit()
    s = await week_summary(db, MONDAY)
    assert s["flags"]["has_long_run"] is True
    assert s["flags"]["long_run_distance_m"] == 22_000


async def test_flags_speed_tempo_and_race(db):
    db.add_all(
        [
            _mk(
                strava_id=1,
                start=datetime(2026, 4, 13, 7),
                classification="intervals",
                distance_m=8000,
            ),
            _mk(
                strava_id=2,
                start=datetime(2026, 4, 15, 7),
                classification="tempo",
                distance_m=10_000,
            ),
            _mk(
                strava_id=3,
                start=datetime(2026, 4, 18, 9),
                classification="race",
                distance_m=21_000,
            ),
        ]
    )
    await db.commit()
    s = await week_summary(db, MONDAY)
    assert s["flags"]["has_speed_session"] is True
    assert s["flags"]["has_tempo"] is True
    assert s["flags"]["has_race"] is True


async def test_flags_long_ride_and_ride_race(db):
    db.add_all(
        [
            _mk(
                strava_id=1,
                start=datetime(2026, 4, 13, 8),
                sport="Ride",
                classification="endurance",
                classification_flags=["is_long"],
                distance_m=80_000,
                duration_s=3 * 3600,
            ),
            _mk(
                strava_id=2,
                start=datetime(2026, 4, 17, 8),
                sport="Ride",
                classification="race",
                distance_m=50_000,
            ),
        ]
    )
    await db.commit()
    s = await week_summary(db, MONDAY)
    assert s["flags"]["has_long_ride"] is True
    assert s["flags"]["has_race"] is True


async def test_flags_all_false_on_recovery_week(db):
    db.add_all(
        [
            _mk(
                strava_id=1,
                start=datetime(2026, 4, 14, 7),
                classification="easy",
                distance_m=3000,
            ),
            _mk(
                strava_id=2,
                start=datetime(2026, 4, 16, 7),
                classification="easy",
                distance_m=4000,
            ),
        ]
    )
    await db.commit()
    s = await week_summary(db, MONDAY)
    assert s["flags"] == {
        "has_long_run": False,
        "long_run_distance_m": 0.0,
        "has_speed_session": False,
        "has_tempo": False,
        "has_race": False,
        "has_long_ride": False,
    }


# ── Notable activities ────────────────────────────────────────────


async def test_notable_picks_longest_and_hardest(db):
    db.add_all(
        [
            _mk(
                strava_id=1,
                start=datetime(2026, 4, 13, 7),
                duration_s=60 * 60,
                distance_m=12_000,
                suffer=30,
            ),
            _mk(
                strava_id=2,
                start=datetime(2026, 4, 15, 7),
                duration_s=90 * 60,
                distance_m=18_000,
                suffer=45,
            ),
            _mk(
                strava_id=3,
                start=datetime(2026, 4, 17, 7),
                duration_s=45 * 60,
                distance_m=8_000,
                suffer=80,  # hardest by suffer
            ),
        ]
    )
    await db.commit()
    # IDs are autoincrement — look them up after commit.
    acts = {
        a.strava_id: a
        for a in (await db.execute(__import__("sqlalchemy").select(Activity))).scalars().all()
    }
    s = await week_summary(db, MONDAY)
    assert s["notable"]["longest_activity_id"] == acts[2].id
    assert s["notable"]["hardest_activity_id"] == acts[3].id


async def test_notable_hardest_falls_back_to_longest_without_suffer(db):
    """When no activity has suffer_score > 0, hardest == longest."""
    db.add_all(
        [
            _mk(
                strava_id=1,
                start=datetime(2026, 4, 13, 7),
                duration_s=30 * 60,
                suffer=None,
            ),
            _mk(
                strava_id=2,
                start=datetime(2026, 4, 15, 7),
                duration_s=60 * 60,
                suffer=0,
            ),
        ]
    )
    await db.commit()
    s = await week_summary(db, MONDAY)
    assert (
        s["notable"]["longest_activity_id"]
        == s["notable"]["hardest_activity_id"]
    )


# ── Pending counters ──────────────────────────────────────────────


async def test_enrichment_and_classification_pending(db):
    db.add_all(
        [
            # pending enrichment — counts toward enrichment_pending only.
            _mk(
                strava_id=1,
                start=datetime(2026, 4, 13, 7),
                enrichment="pending",
                classification=None,
            ),
            # complete, run, unclassified — counts toward classification_pending.
            _mk(
                strava_id=2,
                start=datetime(2026, 4, 14, 7),
                enrichment="complete",
                classification=None,
            ),
            # complete, unsupported sport — does NOT count as pending.
            _mk(
                strava_id=3,
                start=datetime(2026, 4, 15, 7),
                sport="WeightTraining",
                enrichment="complete",
                classification=None,
            ),
            # complete + classified — doesn't count.
            _mk(
                strava_id=4,
                start=datetime(2026, 4, 16, 7),
                enrichment="complete",
                classification="easy",
            ),
        ]
    )
    await db.commit()
    s = await week_summary(db, MONDAY)
    assert s["enrichment_pending"] == 1
    assert s["classification_pending"] == 1


# ── ISO week string ───────────────────────────────────────────────


async def test_iso_week_string_format(db):
    s = await week_summary(db, MONDAY)
    assert s["iso_week"] == "2026-W16"
    assert s["week_start"] == "2026-04-13"
    assert s["week_end"] == "2026-04-19"


# ── weekly_summaries (N-weeks strip) ──────────────────────────────


async def test_weekly_summaries_returns_n_weeks_newest_first(db):
    """Seed one activity in each of 4 consecutive weeks and verify
    weekly_summaries(weeks=4) returns them newest-first."""
    for i, start in enumerate(
        [
            datetime(2026, 3, 23, 7),  # W13
            datetime(2026, 3, 30, 7),  # W14
            datetime(2026, 4, 6, 7),   # W15
            datetime(2026, 4, 13, 7),  # W16
        ]
    ):
        db.add(_mk(strava_id=i + 1, start=start))
    await db.commit()

    summaries = await weekly_summaries(db, weeks=4, end_date=date(2026, 4, 19))
    assert [s["iso_week"] for s in summaries] == [
        "2026-W16",
        "2026-W15",
        "2026-W14",
        "2026-W13",
    ]
    # Each week has exactly one activity.
    assert all(s["totals"]["activity_count"] == 1 for s in summaries)


async def test_weekly_summaries_defaults_to_today(db):
    """Without end_date, weekly_summaries anchors to today's ISO week.
    We can't assert the exact week but we can assert count and ordering.
    """
    result = await weekly_summaries(db, weeks=3)
    assert len(result) == 3
    # Ordered newest-first: each successive week_start is strictly earlier.
    starts = [s["week_start"] for s in result]
    assert starts == sorted(starts, reverse=True)


async def test_weekly_summaries_default_uses_local_today_at_midnight_boundary(
    db, monkeypatch
):
    monkeypatch.setattr(
        weekly_summary_module, "local_today", lambda: date(2026, 4, 19)
    )

    result = await weekly_summaries(db, weeks=2)

    assert [s["week_start"] for s in result] == [
        "2026-04-13",
        "2026-04-06",
    ]
