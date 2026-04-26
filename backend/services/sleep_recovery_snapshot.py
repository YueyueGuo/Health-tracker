"""Sleep, recovery, and environmental snapshot assembly."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Recovery, SleepSession
from backend.services.snapshot_models import (
    EnvironmentalSnapshot,
    RecoverySnapshot,
    SleepSnapshot,
    validate_snapshot,
)
from backend.services.time_utils import local_today


async def get_sleep_snapshot(
    db: AsyncSession,
    days: int = 14,
    target_hours: float = 8.0,
    today: date | None = None,
) -> dict:
    today = today or local_today()
    cutoff = today - timedelta(days=days)
    rows = await db.execute(
        select(SleepSession)
        .where(SleepSession.date >= cutoff)
        .where(SleepSession.date <= today)
        .order_by(SleepSession.date.desc())
    )
    sessions = list(rows.scalars().all())

    if not sessions:
        payload = {
            "last_night_score": None,
            "last_night_duration_min": None,
            "last_night_hrv": None,
            "avg_score_7d": None,
            "avg_duration_min_7d": None,
            "avg_hrv_7d": None,
            "sleep_debt_min": None,
            "nights_of_data": 0,
        }
        return validate_snapshot(payload, SleepSnapshot)

    last = sessions[0]
    last_7 = sessions[:7]

    def _avg(attr: str, items: list[SleepSession]) -> float | None:
        values = [getattr(s, attr) for s in items if getattr(s, attr) is not None]
        return round(sum(values) / len(values), 1) if values else None

    target_min = int(target_hours * 60)
    durations_7 = [s.total_duration for s in last_7 if s.total_duration is not None]
    sleep_debt = sum(max(0, target_min - d) for d in durations_7) if durations_7 else None

    payload = {
        "last_night_date": last.date.isoformat(),
        "last_night_score": last.sleep_score,
        "last_night_duration_min": last.total_duration,
        "last_night_deep_min": last.deep_sleep,
        "last_night_rem_min": last.rem_sleep,
        "last_night_hrv": last.hrv,
        "last_night_resting_hr": last.avg_hr,
        "avg_score_7d": _avg("sleep_score", last_7),
        "avg_duration_min_7d": _avg("total_duration", last_7),
        "avg_hrv_7d": _avg("hrv", last_7),
        "sleep_debt_min": sleep_debt,
        "nights_of_data": len(sessions),
    }
    return validate_snapshot(payload, SleepSnapshot)


async def get_recovery_snapshot(
    db: AsyncSession, days: int = 7, today: date | None = None
) -> dict:
    today = today or local_today()
    cutoff = today - timedelta(days=max(days, 1) - 1)
    rows = await db.execute(
        select(Recovery)
        .where(Recovery.date >= cutoff)
        .where(Recovery.date <= today)
        .order_by(Recovery.date.desc())
    )
    records = list(rows.scalars().all())

    sleep_rows = await db.execute(
        select(SleepSession)
        .where(SleepSession.date >= cutoff)
        .where(SleepSession.date <= today)
        .order_by(SleepSession.date.desc())
    )
    sleep_sessions = list(sleep_rows.scalars().all())

    eight_sleep_sessions = [
        s for s in sleep_sessions if s.source == "eight_sleep"
    ]
    today_r = records[0] if records else None
    current_recovery = next((r for r in records if r.date == today), None)
    primary_sleep = next(
        (s for s in eight_sleep_sessions if s.date == today),
        None,
    )

    def _avg_values(values: list[float | None]) -> float | None:
        present = [v for v in values if v is not None]
        return round(sum(present) / len(present), 1) if present else None

    eight_hrvs = [s.hrv for s in eight_sleep_sessions[:7]]
    whoop_hrvs = [r.hrv for r in records[:7]]

    hrv_source = None
    if primary_sleep and primary_sleep.hrv is not None:
        hrv_source = "eight_sleep"
        today_hrv = primary_sleep.hrv
        hrv_baseline = _avg_values(eight_hrvs)
    else:
        today_hrv = current_recovery.hrv if current_recovery else None
        hrv_source = "whoop" if today_hrv is not None else None
        hrv_baseline = _avg_values(whoop_hrvs)

    hrv_trend = None
    if today_hrv is not None and hrv_baseline is not None:
        diff = today_hrv - hrv_baseline
        if diff >= 3:
            hrv_trend = "up"
        elif diff <= -3:
            hrv_trend = "down"
        else:
            hrv_trend = "flat"

    today_resting_hr = (
        primary_sleep.avg_hr
        if primary_sleep and primary_sleep.avg_hr is not None
        else (current_recovery.resting_hr if current_recovery else None)
    )

    if not records:
        payload = {
            "today_date": primary_sleep.date.isoformat() if primary_sleep else None,
            "today_score": None,
            "today_hrv": today_hrv,
            "today_resting_hr": today_resting_hr,
            "avg_score_7d": None,
            "trend": None,
            "hrv_baseline_7d": hrv_baseline,
            "hrv_trend": hrv_trend,
            "hrv_source": hrv_source,
        }
        return validate_snapshot(payload, RecoverySnapshot)

    def _avg(attr: str) -> float | None:
        values = [getattr(r, attr) for r in records if getattr(r, attr) is not None]
        return round(sum(values) / len(values), 1) if values else None

    avg_7 = _avg("recovery_score")
    trend = None
    if today_r.recovery_score is not None and avg_7 is not None:
        diff = today_r.recovery_score - avg_7
        if diff > 5:
            trend = "improving"
        elif diff < -5:
            trend = "declining"
        else:
            trend = "stable"

    payload = {
        "today_date": today_r.date.isoformat(),
        "today_score": today_r.recovery_score,
        "today_hrv": today_hrv,
        "today_resting_hr": today_resting_hr,
        "avg_score_7d": avg_7,
        "trend": trend,
        "hrv_baseline_7d": hrv_baseline,
        "hrv_trend": hrv_trend,
        "hrv_source": hrv_source,
    }
    return validate_snapshot(payload, RecoverySnapshot)


async def get_environmental_snapshot(db: AsyncSession) -> dict | None:
    """Environmental context for today: last-night bed-temp.

    Returns ``None`` when we have no useful signal. Intentionally small:
    the LLM doesn't need a full weather forecast, just a nudge when
    conditions are unusual.
    """
    last_sleep = (
        await db.execute(select(SleepSession).order_by(SleepSession.date.desc()).limit(1))
    ).scalar_one_or_none()
    bed_temp_c = last_sleep.bed_temp if last_sleep else None
    if bed_temp_c is None:
        return None
    payload = {
        "last_night_bed_temp_c": bed_temp_c,
        "last_night_date": last_sleep.date.isoformat() if last_sleep else None,
    }
    return validate_snapshot(payload, EnvironmentalSnapshot)
