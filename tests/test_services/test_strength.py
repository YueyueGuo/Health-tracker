"""Tests for backend.services.strength.

Covers the pure Epley 1RM helper and the session/progression query
helpers against an in-memory SQLite DB.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models import Activity, ActivityStream, StrengthSessionLink, StrengthSet
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
    # No link rows yet → hr_linked False on every row.
    assert sessions[0]["hr_linked"] is False
    assert sessions[1]["exercise_count"] == 1
    assert sessions[1]["total_sets"] == 2
    assert sessions[1]["total_volume_kg"] == pytest.approx(2 * 5 * 100)
    assert sessions[1]["hr_linked"] is False


async def test_list_sessions_flags_hr_linked(db: AsyncSession):
    """A ``strength_session_links`` row flips ``hr_linked`` to True for
    that date — used by the history list HR-linked indicator."""
    today = date.today()
    yesterday = today - timedelta(days=1)
    start = datetime(today.year, today.month, today.day, 9, 0, 0)
    activity = Activity(
        strava_id=42_001,
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
            StrengthSet(date=today, exercise_name="Squat", set_number=1, reps=5, weight_kg=100),
            StrengthSet(date=yesterday, exercise_name="Bench", set_number=1, reps=5, weight_kg=80),
        ],
    )
    db.add(
        StrengthSessionLink(
            session_date=today,
            source="strava",
            activity_id=activity.id,
            segmentation_status="ok",
        )
    )
    await db.commit()
    sessions = await list_sessions(db, limit=10)
    by_date = {s["date"]: s for s in sessions}
    assert by_date[today.isoformat()]["hr_linked"] is True
    assert by_date[yesterday.isoformat()]["hr_linked"] is False


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


async def test_session_summary_merges_hr_via_link_with_segmentation(db: AsyncSession):
    """When a ``strength_session_links`` row exists pointing at a Strava
    activity whose streams are cached, segmentation runs lazily on the
    first GET and the payload carries the ``link`` / ``segmentation`` /
    ``hr_curve`` / ``segment_markers`` blocks plus per-set ``avg_hr`` /
    ``max_hr``."""
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
    # Synthetic HR trace with 2 clean peaks separated by 120s of rest.
    time_stream: list[int] = []
    hr_stream: list[float] = []
    import math as _math
    t = 0
    for _ in range(60):
        time_stream.append(t)
        hr_stream.append(110.0)
        t += 1
    for k in range(30):
        x = t + k
        center = t + 15
        d = (x - center) / 7.5
        hr_stream.append(110.0 + 50.0 * _math.exp(-(d * d) / 2))
        time_stream.append(x)
    t += 30
    for _ in range(120):
        time_stream.append(t)
        hr_stream.append(110.0)
        t += 1
    for k in range(30):
        x = t + k
        center = t + 15
        d = (x - center) / 7.5
        hr_stream.append(110.0 + 50.0 * _math.exp(-(d * d) / 2))
        time_stream.append(x)
    t += 30
    for _ in range(60):
        time_stream.append(t)
        hr_stream.append(110.0)
        t += 1

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
            ),
            StrengthSet(
                date=today,
                exercise_name="Squat",
                set_number=2,
                reps=5,
                weight_kg=100,
            ),
        ],
    )
    # The link table is the source of truth for the link target now.
    db.add(
        StrengthSessionLink(
            session_date=today,
            source="strava",
            activity_id=activity.id,
            segmentation_status="pending",
        )
    )
    await db.commit()

    summary = await session_summary(db, today)
    assert summary is not None
    # Back-compat: activity_id still exposed for the Strava source.
    assert summary["activity_id"] == activity.id
    assert summary["link"] is not None
    assert summary["link"]["source"] == "strava"
    assert summary["link"]["ref_id"] == activity.id
    assert summary["segmentation"] is not None
    assert summary["segmentation"]["status"] in {"ok", "too_few", "too_many"}
    assert summary["segmentation"]["target_count"] == 2
    assert isinstance(summary["hr_curve"], list) and summary["hr_curve"]
    assert summary["activity_start_iso"] == start.isoformat()
    assert summary["segment_markers"]
    # Each detected set carries avg/max HR.
    detected_count = summary["segmentation"]["detected_count"]
    sets_with_hr = [s for s in summary["sets"] if "avg_hr" in s]
    assert len(sets_with_hr) == detected_count


async def test_session_summary_maps_segments_to_chronological_logged_order(
    db: AsyncSession,
):
    """Regression for code-reviewer finding #1.

    An alternating Squat/Bench/Squat/Bench session: alphabetical display
    order is ``[Bench#1, Bench#2, Squat#1, Squat#2]`` but the
    chronologically logged order is
    ``[Squat#1, Bench#1, Squat#2, Bench#2]``. Segments come out of
    segmentation in chronological order — they must map to the logged
    order, not the alphabetical display order.

    Setup: four Gaussian peaks with strictly ascending magnitudes (so
    each peak has a unique max HR). The test asserts that ``Squat #1``
    (logged first) gets the lowest peak and ``Bench #2`` (logged last)
    gets the highest peak. Before the fix, alphabetical iteration order
    would have caused ``Bench #1`` to receive the lowest peak.
    """
    import math as _math

    today = date.today()
    start = datetime(today.year, today.month, today.day, 9, 0, 0)
    activity = Activity(
        strava_id=999_002,
        name="Alternating block",
        sport_type="WeightTraining",
        start_date=start,
        start_date_local=start,
    )
    db.add(activity)
    await db.flush()

    # 4 peaks at t=30, 150, 270, 390 with peak magnitudes 160, 170, 180, 190.
    time_stream: list[int] = []
    hr_stream: list[float] = []
    peak_centers = [30, 150, 270, 390]
    peak_magnitudes = [50.0, 60.0, 70.0, 80.0]  # baseline 110 → 160/170/180/190
    duration = 480
    for t in range(duration):
        baseline = 110.0
        hr = baseline
        # Add the contribution of every nearby peak (they're well
        # separated so cross-talk is negligible).
        for c, m in zip(peak_centers, peak_magnitudes):
            d = (t - c) / 7.5
            hr += m * _math.exp(-(d * d) / 2)
        time_stream.append(t)
        hr_stream.append(hr)
    db.add(ActivityStream(activity_id=activity.id, stream_type="time", data=time_stream))
    db.add(
        ActivityStream(activity_id=activity.id, stream_type="heartrate", data=hr_stream)
    )

    # Logged in chronological order Squat/Bench/Squat/Bench, each tagged
    # with the ``performed_at`` of the corresponding peak so the sort
    # key is unambiguous (no tie-breaking on id alone).
    base = datetime(today.year, today.month, today.day, 9, 0, 0)
    squat1 = StrengthSet(
        date=today,
        exercise_name="Squat",
        set_number=1,
        reps=5,
        weight_kg=100,
        performed_at=base + timedelta(seconds=30),
    )
    bench1 = StrengthSet(
        date=today,
        exercise_name="Bench",
        set_number=1,
        reps=5,
        weight_kg=80,
        performed_at=base + timedelta(seconds=150),
    )
    squat2 = StrengthSet(
        date=today,
        exercise_name="Squat",
        set_number=2,
        reps=5,
        weight_kg=100,
        performed_at=base + timedelta(seconds=270),
    )
    bench2 = StrengthSet(
        date=today,
        exercise_name="Bench",
        set_number=2,
        reps=5,
        weight_kg=80,
        performed_at=base + timedelta(seconds=390),
    )
    await _seed(db, [squat1, bench1, squat2, bench2])

    db.add(
        StrengthSessionLink(
            session_date=today,
            source="strava",
            activity_id=activity.id,
            segmentation_status="pending",
        )
    )
    await db.commit()

    summary = await session_summary(db, today)
    assert summary is not None
    # Segmentation should find all 4 peaks.
    assert summary["segmentation"]["status"] in {"ok", "too_few", "too_many"}
    assert summary["segmentation"]["detected_count"] == 4
    assert summary["segmentation"]["target_count"] == 4

    sets_by_key = {(s["exercise_name"], s["set_number"]): s for s in summary["sets"]}
    # Chronologically first set (Squat #1) gets the lowest peak (~160);
    # chronologically last (Bench #2) gets the highest (~190).
    assert sets_by_key[("Squat", 1)]["max_hr"] == pytest.approx(160.0, abs=2.0)
    assert sets_by_key[("Bench", 1)]["max_hr"] == pytest.approx(170.0, abs=2.0)
    assert sets_by_key[("Squat", 2)]["max_hr"] == pytest.approx(180.0, abs=2.0)
    assert sets_by_key[("Bench", 2)]["max_hr"] == pytest.approx(190.0, abs=2.0)

    # ``segment_markers`` must carry session-wide ordinals (1..4) over
    # chronological order — code-reviewer finding #2. The picker label
    # in ``SessionHRCurve`` reads ``set_number`` directly, so the
    # ordinal sequence must be 1, 2, 3, 4 — not a per-exercise repeat
    # like 1, 1, 2, 2.
    markers = summary["segment_markers"]
    assert [m["set_number"] for m in markers] == [1, 2, 3, 4]
    # ``per_exercise_set_number`` is preserved for tooltip captions.
    # Chronological exercise sequence: Squat / Bench / Squat / Bench.
    assert [m["exercise_name"] for m in markers] == [
        "Squat",
        "Bench",
        "Squat",
        "Bench",
    ]
    assert [m["per_exercise_set_number"] for m in markers] == [1, 1, 2, 2]


async def test_session_summary_no_link_returns_empty_link_blocks(db: AsyncSession):
    """No ``strength_session_links`` row → ``link`` / ``segmentation`` /
    ``hr_curve`` / ``activity_start_iso`` all None."""
    today = date.today()
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
            ),
        ],
    )
    summary = await session_summary(db, today)
    assert summary is not None
    assert summary["link"] is None
    assert summary["segmentation"] is None
    assert summary["hr_curve"] is None
    assert summary["activity_start_iso"] is None
    assert "avg_hr" not in summary["sets"][0]


async def test_session_summary_orders_by_order_index(db: AsyncSession):
    """Exercises render in ``order_index`` order, not alphabetical."""
    today = date.today()
    # Bench seeded first alphabetically but tagged with a later order_index
    # so Squat should still come out first in the response.
    await _seed(
        db,
        [
            StrengthSet(
                date=today,
                exercise_name="Bench",
                set_number=1,
                reps=5,
                weight_kg=80,
                order_index=2,
            ),
            StrengthSet(
                date=today,
                exercise_name="Squat",
                set_number=1,
                reps=5,
                weight_kg=100,
                order_index=0,
            ),
            StrengthSet(
                date=today,
                exercise_name="Row",
                set_number=1,
                reps=10,
                weight_kg=60,
                order_index=1,
            ),
        ],
    )
    summary = await session_summary(db, today)
    assert summary is not None
    names = [ex["name"] for ex in summary["exercises"]]
    assert names == ["Squat", "Row", "Bench"]
    indices = [ex["order_index"] for ex in summary["exercises"]]
    assert indices == [0, 1, 2]


async def test_session_summary_orders_falls_back_to_performed_at_then_name(
    db: AsyncSession,
):
    """No order_index → fall back to min(performed_at), then name."""
    today = date.today()
    t0 = datetime(today.year, today.month, today.day, 10, 0, 0)
    await _seed(
        db,
        [
            # Alphabetically first, but recorded second.
            StrengthSet(
                date=today,
                exercise_name="Bench",
                set_number=1,
                reps=5,
                weight_kg=80,
                performed_at=t0 + timedelta(minutes=10),
            ),
            # Alphabetically last, recorded first.
            StrengthSet(
                date=today,
                exercise_name="Squat",
                set_number=1,
                reps=5,
                weight_kg=100,
                performed_at=t0,
            ),
            # No performed_at, no order_index → falls through to name.
            StrengthSet(
                date=today,
                exercise_name="Deadlift",
                set_number=1,
                reps=5,
                weight_kg=120,
            ),
        ],
    )
    summary = await session_summary(db, today)
    assert summary is not None
    names = [ex["name"] for ex in summary["exercises"]]
    # Squat (earliest performed_at), Bench (later performed_at), then
    # Deadlift (no timestamp, falls through to alphabetical bucket).
    assert names == ["Squat", "Bench", "Deadlift"]


async def test_session_summary_emits_superset_group_id(db: AsyncSession):
    """Modal superset_group_id per exercise; standalone exercise → None."""
    today = date.today()
    await _seed(
        db,
        [
            # Two exercises share group 1 (a superset).
            StrengthSet(
                date=today,
                exercise_name="Bench",
                set_number=1,
                reps=5,
                weight_kg=80,
                order_index=0,
                superset_group_id=1,
            ),
            StrengthSet(
                date=today,
                exercise_name="Bench",
                set_number=2,
                reps=5,
                weight_kg=80,
                order_index=0,
                superset_group_id=1,
            ),
            StrengthSet(
                date=today,
                exercise_name="Row",
                set_number=1,
                reps=10,
                weight_kg=60,
                order_index=1,
                superset_group_id=1,
            ),
            # Standalone exercise — no group.
            StrengthSet(
                date=today,
                exercise_name="Squat",
                set_number=1,
                reps=5,
                weight_kg=100,
                order_index=2,
            ),
        ],
    )
    summary = await session_summary(db, today)
    assert summary is not None
    by_name = {ex["name"]: ex for ex in summary["exercises"]}
    assert by_name["Bench"]["superset_group_id"] == 1
    assert by_name["Row"]["superset_group_id"] == 1
    assert by_name["Squat"]["superset_group_id"] is None
    # Per-set serialization also carries the field.
    bench_sets = by_name["Bench"]["sets"]
    assert all(s["superset_group_id"] == 1 for s in bench_sets)
    squat_sets = by_name["Squat"]["sets"]
    assert all(s["superset_group_id"] is None for s in squat_sets)


async def test_session_summary_duration_from_started_ended(db: AsyncSession):
    """``duration_sec`` prefers max(ended_at) - min(started_at)."""
    today = date.today()
    started = datetime(today.year, today.month, today.day, 17, 30, 0)
    ended = datetime(today.year, today.month, today.day, 18, 25, 0)
    perf_mid = datetime(today.year, today.month, today.day, 17, 45, 0)
    await _seed(
        db,
        [
            StrengthSet(
                date=today,
                exercise_name="Squat",
                set_number=1,
                reps=5,
                weight_kg=100,
                performed_at=perf_mid,
                started_at=started,
                ended_at=ended,
            ),
            StrengthSet(
                date=today,
                exercise_name="Squat",
                set_number=2,
                reps=5,
                weight_kg=100,
                performed_at=perf_mid,
                started_at=started,
                ended_at=ended,
            ),
        ],
    )
    summary = await session_summary(db, today)
    assert summary is not None
    # 55 minutes = 3300s.
    assert summary["duration_sec"] == 55 * 60
    assert summary["started_at"] == started.isoformat()
    assert summary["ended_at"] == ended.isoformat()


async def test_session_summary_duration_fallback_to_performed_at_range(
    db: AsyncSession,
):
    """No started_at/ended_at → fall back to performed_at min/max."""
    today = date.today()
    t0 = datetime(today.year, today.month, today.day, 10, 0, 0)
    t1 = datetime(today.year, today.month, today.day, 10, 20, 30)
    await _seed(
        db,
        [
            StrengthSet(
                date=today,
                exercise_name="Bench",
                set_number=1,
                reps=5,
                weight_kg=80,
                performed_at=t0,
            ),
            StrengthSet(
                date=today,
                exercise_name="Bench",
                set_number=2,
                reps=5,
                weight_kg=80,
                performed_at=t1,
            ),
        ],
    )
    summary = await session_summary(db, today)
    assert summary is not None
    assert summary["duration_sec"] == 20 * 60 + 30
    # No session-level stamps were written.
    assert summary["started_at"] is None
    assert summary["ended_at"] is None


async def test_session_summary_duration_none_when_no_stamps(db: AsyncSession):
    """A single bare set → duration_sec is None (no derivable range)."""
    today = date.today()
    await _seed(
        db,
        [
            StrengthSet(
                date=today, exercise_name="Squat", set_number=1, reps=5, weight_kg=100,
            ),
        ],
    )
    summary = await session_summary(db, today)
    assert summary is not None
    assert summary["duration_sec"] is None


async def test_session_summary_session_aggregates(db: AsyncSession):
    """total_sets / total_reps / total_volume_kg / exercise_count.

    Mixes weighted and bodyweight (``weight_kg=None``) sets — reps and
    set counts include bodyweight; volume does not.
    """
    today = date.today()
    await _seed(
        db,
        [
            # Weighted compound.
            StrengthSet(
                date=today, exercise_name="Squat", set_number=1, reps=5, weight_kg=100,
            ),
            StrengthSet(
                date=today, exercise_name="Squat", set_number=2, reps=3, weight_kg=110,
            ),
            # Weighted accessory.
            StrengthSet(
                date=today, exercise_name="Row", set_number=1, reps=10, weight_kg=60,
            ),
            # Bodyweight set (no weight) — counted in reps + sets, not volume.
            StrengthSet(
                date=today, exercise_name="Pullup", set_number=1, reps=8, weight_kg=None,
            ),
        ],
    )
    summary = await session_summary(db, today)
    assert summary is not None
    assert summary["total_sets"] == 4
    assert summary["total_reps"] == 5 + 3 + 10 + 8
    assert summary["total_volume_kg"] == pytest.approx(
        5 * 100 + 3 * 110 + 10 * 60
    )
    assert summary["exercise_count"] == 3


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
