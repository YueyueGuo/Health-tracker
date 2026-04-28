from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import SleepSession
from backend.services.metrics import get_sleep_trends
from backend.services.sleep_analytics import (
    get_best_worst_nights,
    get_consistency_metrics,
    get_rolling_averages,
    get_sleep_debt,
)
from backend.services.time_utils import local_today

router = APIRouter()


@router.get("")
async def list_sleep_sessions(
    days: int = Query(30, ge=1, le=365),
    source: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List sleep sessions."""
    from datetime import timedelta

    query = select(SleepSession).order_by(SleepSession.date.desc())

    cutoff = local_today() - timedelta(days=days)
    query = query.where(SleepSession.date >= cutoff)

    if source:
        query = query.where(SleepSession.source == source)

    result = await db.execute(query)
    sessions = result.scalars().all()

    return [_sleep_dict(s) for s in sessions]


@router.get("/trends")
async def sleep_trends(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """Get sleep trend data."""
    return await get_sleep_trends(db, days=days)


@router.get("/analytics/rolling")
async def sleep_rolling_averages(
    days: int = Query(30, ge=7, le=365),
    db: AsyncSession = Depends(get_db),
):
    """7-day and N-day rolling averages of key sleep metrics."""
    return await get_rolling_averages(db, days=days)


@router.get("/analytics/debt")
async def sleep_debt(
    target_hours: float = Query(8.0, gt=0, le=24),
    days: int = Query(14, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """Per-night and cumulative sleep debt vs a target sleep duration."""
    return await get_sleep_debt(db, target_hours=target_hours, days=days)


@router.get("/analytics/best-worst")
async def sleep_best_worst(
    days: int = Query(90, ge=1, le=365),
    top_n: int = Query(5, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Top N best and worst nights in the window, ranked by sleep_score."""
    return await get_best_worst_nights(db, days=days, top_n=top_n)


@router.get("/analytics/consistency")
async def sleep_consistency(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """Stdev of bed time, wake time, and total sleep duration."""
    return await get_consistency_metrics(db, days=days)


@router.get("/latest")
async def latest_sleep(
    source: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Get the most recent sleep session, optionally filtered by source.

    The ``source`` filter is the contract the comparison card relies on:
    callers fetch ``/sleep/latest?source=whoop`` and ``?source=eight_sleep``
    in parallel so each column on the side-by-side card binds to the
    correct provider. Without the filter we'd return whichever provider
    happens to have the newer ``date``, which makes Whoop stats invisible
    most days (Eight Sleep usually wins by one calendar day).
    """
    query = select(SleepSession).order_by(SleepSession.date.desc()).limit(1)
    if source:
        query = query.where(SleepSession.source == source)
    result = await db.execute(query)
    session = result.scalar_one_or_none()
    if not session:
        return None
    return _sleep_dict(session)


def _sleep_dict(s: SleepSession) -> dict:
    return {
        "id": s.id,
        "source": s.source,
        "external_id": s.external_id,
        "date": s.date.isoformat(),
        "bed_time": s.bed_time.isoformat() if s.bed_time else None,
        "wake_time": s.wake_time.isoformat() if s.wake_time else None,
        "total_duration": s.total_duration,
        "deep_sleep": s.deep_sleep,
        "rem_sleep": s.rem_sleep,
        "light_sleep": s.light_sleep,
        "awake_time": s.awake_time,
        "sleep_score": s.sleep_score,
        "sleep_fitness_score": s.sleep_fitness_score,
        "avg_hr": s.avg_hr,
        "hrv": s.hrv,
        "respiratory_rate": s.respiratory_rate,
        "bed_temp": s.bed_temp,
        "tnt_count": s.tnt_count,
        "latency": s.latency,
        "wake_count": s.wake_count,
        "waso_duration": s.waso_duration,
        "out_of_bed_count": s.out_of_bed_count,
        "out_of_bed_duration": s.out_of_bed_duration,
        "wake_events": s.wake_events,
        # Whoop-only extras (null on Eight Sleep rows).
        "sleep_efficiency": s.sleep_efficiency,
        "sleep_consistency": s.sleep_consistency,
        "sleep_need_baseline_min": s.sleep_need_baseline_min,
        "sleep_debt_min": s.sleep_debt_min,
    }
