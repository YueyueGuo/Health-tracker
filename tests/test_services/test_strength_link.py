"""Tests for backend.services.strength_link.

Covers :func:`list_candidates`, :func:`set_link`, :func:`clear_link`,
and :func:`ensure_streams_loaded` against an in-memory SQLite DB.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models import (
    Activity,
    ActivityStream,
    HealthDataPoint,
    StrengthSessionLink,
    Workout,
)
from backend.services.strength_link import (
    CandidateNotFoundError,
    LinkConflictError,
    clear_link,
    ensure_streams_loaded,
    get_link,
    list_candidates,
    run_segmentation_for_link,
    set_link,
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


_strava_id_counter = [50_000]


def _next_strava_id() -> int:
    _strava_id_counter[0] += 1
    return _strava_id_counter[0]


async def _seed_strava_activity(
    db: AsyncSession,
    *,
    start_utc: datetime,
    sport_type: str = "WeightTraining",
    name: str = "Lift",
    duration_s: int = 3600,
    avg_hr: float | None = 132.0,
) -> Activity:
    activity = Activity(
        strava_id=_next_strava_id(),
        name=name,
        sport_type=sport_type,
        start_date=start_utc,
        start_date_local=start_utc.replace(tzinfo=None),
        elapsed_time=duration_s,
        moving_time=duration_s,
        average_hr=avg_hr,
        max_hr=(avg_hr + 30) if avg_hr else None,
        enrichment_status="complete",
    )
    db.add(activity)
    await db.flush()
    return activity


async def _seed_apple_workout(
    db: AsyncSession,
    *,
    start_utc: datetime,
    sport: str = "strength",
    duration_s: int = 3600,
    hr_series: list | None = None,
    external_id: str | None = None,
) -> Workout:
    payload: dict = {"name": f"Apple {sport}"}
    if hr_series is not None:
        payload["heartRateData"] = hr_series
    dp = HealthDataPoint(
        source="apple_health",
        data_type="workout",
        external_id=external_id or f"apple-{int(start_utc.timestamp())}",
        start_time=start_utc,
        end_time=start_utc + timedelta(seconds=duration_s),
        raw_payload=payload,
    )
    db.add(dp)
    await db.flush()
    workout = Workout(
        id=dp.id,
        activity_type=sport,
        duration_s=duration_s,
        avg_hr=125.0,
        max_hr=155.0,
    )
    db.add(workout)
    await db.flush()
    return workout


# ── list_candidates ────────────────────────────────────────────────


async def test_list_candidates_cross_source_within_window(db: AsyncSession):
    """±1 day window pulls Strava + Apple rows; ordered by start time."""
    target = date(2026, 5, 15)
    # Strava activity on target day.
    strava_a = await _seed_strava_activity(
        db,
        start_utc=datetime(2026, 5, 15, 17, 0, 0, tzinfo=timezone.utc),
        name="Garage lift",
    )
    # Apple workout on day before — within ±1.
    apple = await _seed_apple_workout(
        db, start_utc=datetime(2026, 5, 14, 18, 0, 0, tzinfo=timezone.utc)
    )
    # Strava activity 2 days before — outside window.
    await _seed_strava_activity(
        db,
        start_utc=datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc),
        name="Old ride",
    )
    await db.commit()

    out = await list_candidates(db, target)

    sources = {r["source"] for r in out}
    assert sources == {"strava", "apple_health"}
    ref_ids = {r["ref_id"] for r in out}
    assert strava_a.id in ref_ids
    assert apple.id in ref_ids
    # Ordered ascending by start time.
    starts = [r["start_local"] for r in out]
    assert starts == sorted(starts)
    # Strava with enrichment_status=complete is flagged lazy-fetchable.
    strava_row = next(r for r in out if r["source"] == "strava" and r["ref_id"] == strava_a.id)
    assert strava_row["hr_stream_available"] is True


async def test_list_candidates_empty(db: AsyncSession):
    """No rows in window → empty list."""
    out = await list_candidates(db, date(2030, 1, 1))
    assert out == []


async def test_list_candidates_apple_flags_hr_series_present(db: AsyncSession):
    """Apple workout with a real series → ``hr_stream_available=True``."""
    target = date(2026, 5, 15)
    hr_series = [
        {"date": "2026-05-15 17:00:00 +0000", "qty": 120},
        {"date": "2026-05-15 17:00:01 +0000", "qty": 125},
        {"date": "2026-05-15 17:00:02 +0000", "qty": 130},
    ]
    await _seed_apple_workout(
        db,
        start_utc=datetime(2026, 5, 15, 17, 0, 0, tzinfo=timezone.utc),
        hr_series=hr_series,
    )
    await db.commit()
    out = await list_candidates(db, target)
    apple_row = next(r for r in out if r["source"] == "apple_health")
    assert apple_row["hr_stream_available"] is True


async def test_list_candidates_apple_no_series(db: AsyncSession):
    """Apple workout missing heartRateData → ``hr_stream_available=False``."""
    target = date(2026, 5, 15)
    await _seed_apple_workout(
        db, start_utc=datetime(2026, 5, 15, 17, 0, 0, tzinfo=timezone.utc)
    )
    await db.commit()
    out = await list_candidates(db, target)
    apple_row = next(r for r in out if r["source"] == "apple_health")
    assert apple_row["hr_stream_available"] is False


# ── set_link / clear_link ─────────────────────────────────────────


async def test_set_link_persists_and_runs_segmentation_when_streams_cached(
    db: AsyncSession,
):
    """Happy path: Strava streams cached, segmentation runs and persists."""
    start = datetime(2026, 5, 15, 9, 0, 0, tzinfo=timezone.utc)
    activity = await _seed_strava_activity(db, start_utc=start)
    # Synthetic 2-peak HR trace.
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
        d = (x - (t + 15)) / 7.5
        hr_stream.append(110.0 + 50.0 * _math.exp(-(d * d) / 2))
        time_stream.append(x)
    t += 30
    for _ in range(120):
        time_stream.append(t)
        hr_stream.append(110.0)
        t += 1
    for k in range(30):
        x = t + k
        d = (x - (t + 15)) / 7.5
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
    # No logged sets → target_count=0 → status=ok with 0 segments.
    await db.commit()

    link = await set_link(db, date(2026, 5, 15), "strava", activity.id)
    assert link.session_date == date(2026, 5, 15)
    assert link.source == "strava"
    assert link.activity_id == activity.id
    # target_count=0 because no strength_sets seeded.
    assert link.segmentation_status == "ok"
    assert link.segmentation_target_count == 0


async def test_set_link_enforces_one_to_one_on_target(db: AsyncSession):
    """Linking the same Strava activity to two different dates raises."""
    activity = await _seed_strava_activity(
        db, start_utc=datetime(2026, 5, 15, 9, 0, 0, tzinfo=timezone.utc)
    )
    await db.commit()
    await set_link(db, date(2026, 5, 15), "strava", activity.id, run_segmentation=False)
    with pytest.raises(LinkConflictError):
        await set_link(
            db, date(2026, 5, 16), "strava", activity.id, run_segmentation=False
        )


async def test_set_link_idempotent_on_same_target(db: AsyncSession):
    """Re-linking the same session to the same device workout is a no-op."""
    activity = await _seed_strava_activity(
        db, start_utc=datetime(2026, 5, 15, 9, 0, 0, tzinfo=timezone.utc)
    )
    await db.commit()
    link1 = await set_link(
        db, date(2026, 5, 15), "strava", activity.id, run_segmentation=False
    )
    link2 = await set_link(
        db, date(2026, 5, 15), "strava", activity.id, run_segmentation=False
    )
    assert link1.id == link2.id


async def test_set_link_unknown_candidate_raises(db: AsyncSession):
    with pytest.raises(CandidateNotFoundError):
        await set_link(
            db, date(2026, 5, 15), "strava", 999_999, run_segmentation=False
        )


async def test_clear_link_removes_row(db: AsyncSession):
    activity = await _seed_strava_activity(
        db, start_utc=datetime(2026, 5, 15, 9, 0, 0, tzinfo=timezone.utc)
    )
    await db.commit()
    await set_link(db, date(2026, 5, 15), "strava", activity.id, run_segmentation=False)
    assert (await get_link(db, date(2026, 5, 15))) is not None
    removed = await clear_link(db, date(2026, 5, 15))
    assert removed is True
    assert (await get_link(db, date(2026, 5, 15))) is None


async def test_clear_link_no_op_when_missing(db: AsyncSession):
    assert (await clear_link(db, date(2026, 5, 15))) is False


# ── ensure_streams_loaded ─────────────────────────────────────────


async def test_ensure_streams_apple_no_series_returns_has_curve_false(
    db: AsyncSession,
):
    """Apple workout without heartRateData → ``has_curve=False``."""
    workout = await _seed_apple_workout(
        db, start_utc=datetime(2026, 5, 15, 9, 0, 0, tzinfo=timezone.utc)
    )
    await db.commit()
    link = StrengthSessionLink(
        session_date=date(2026, 5, 15),
        source="apple_health",
        workout_id=workout.id,
        segmentation_status="pending",
    )
    db.add(link)
    await db.commit()
    out = await ensure_streams_loaded(db, link)
    assert out["has_curve"] is False
    assert out["time_stream"] is None
    assert out["hr_stream"] is None
    assert out["activity_start"] is not None


async def test_ensure_streams_apple_with_series_returns_streams(db: AsyncSession):
    """Apple workout with heartRateData → ``has_curve=True``."""
    hr_series = [
        {"date": "2026-05-15 09:00:00 +0000", "qty": 100},
        {"date": "2026-05-15 09:00:01 +0000", "qty": 110},
        {"date": "2026-05-15 09:00:02 +0000", "qty": 120},
    ]
    workout = await _seed_apple_workout(
        db,
        start_utc=datetime(2026, 5, 15, 9, 0, 0, tzinfo=timezone.utc),
        hr_series=hr_series,
    )
    await db.commit()
    link = StrengthSessionLink(
        session_date=date(2026, 5, 15),
        source="apple_health",
        workout_id=workout.id,
        segmentation_status="pending",
    )
    db.add(link)
    await db.commit()
    out = await ensure_streams_loaded(db, link)
    assert out["has_curve"] is True
    assert len(out["hr_stream"]) == 3


async def test_ensure_streams_strava_uses_cached_rows(db: AsyncSession):
    """Cached ``activity_streams`` rows are returned without hitting the API."""
    start = datetime(2026, 5, 15, 9, 0, 0, tzinfo=timezone.utc)
    activity = await _seed_strava_activity(db, start_utc=start)
    db.add(ActivityStream(activity_id=activity.id, stream_type="time", data=[0, 1, 2]))
    db.add(
        ActivityStream(activity_id=activity.id, stream_type="heartrate", data=[120, 130, 140])
    )
    await db.commit()
    link = StrengthSessionLink(
        session_date=date(2026, 5, 15),
        source="strava",
        activity_id=activity.id,
        segmentation_status="pending",
    )
    db.add(link)
    await db.commit()
    out = await ensure_streams_loaded(db, link)
    assert out["has_curve"] is True
    assert out["time_stream"] == [0, 1, 2]
    assert out["hr_stream"] == [120, 130, 140]


# ── run_segmentation_for_link ────────────────────────────────────


async def test_run_segmentation_apple_no_curve(db: AsyncSession):
    """Apple workout summary-only → status=no_curve, detected=0."""
    workout = await _seed_apple_workout(
        db, start_utc=datetime(2026, 5, 15, 9, 0, 0, tzinfo=timezone.utc)
    )
    await db.commit()
    link = StrengthSessionLink(
        session_date=date(2026, 5, 15),
        source="apple_health",
        workout_id=workout.id,
        segmentation_status="pending",
    )
    db.add(link)
    await db.commit()
    await run_segmentation_for_link(db, link)
    assert link.segmentation_status == "no_curve"
    assert link.segmentation_detected_count == 0


async def test_run_segmentation_strava_no_cached_streams_no_stream(db: AsyncSession):
    """Strava activity without cached streams and no network reachable in
    the test env → fetch raises → ``status=no_stream``."""
    start = datetime(2026, 5, 15, 9, 0, 0, tzinfo=timezone.utc)
    activity = await _seed_strava_activity(db, start_utc=start)
    await db.commit()
    link = StrengthSessionLink(
        session_date=date(2026, 5, 15),
        source="strava",
        activity_id=activity.id,
        segmentation_status="pending",
    )
    db.add(link)
    await db.commit()
    # Monkey-patch the Strava fetch to simulate an outage so we don't
    # touch the real API from a unit test.
    from backend.services import strava_streams as ss

    async def _boom(_db, _activity):
        raise ss.StravaStreamFetchError("simulated outage")

    original = ss.load_streams_for_activity
    ss.load_streams_for_activity = _boom  # type: ignore[assignment]
    try:
        await run_segmentation_for_link(db, link)
    finally:
        ss.load_streams_for_activity = original  # type: ignore[assignment]

    assert link.segmentation_status == "no_stream"
    assert link.segmentation_detected_count == 0
