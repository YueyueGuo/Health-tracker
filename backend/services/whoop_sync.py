"""Whoop v2 sync logic.

Isolated from ``backend/services/sync.py`` for the same reason Eight Sleep
is: it keeps long-running pipeline rewrites from trampling each other when
multiple agents work in parallel.

Handles four Whoop v2 resources:

* ``/cycle``           → cycles, used ONLY to derive dates for recovery
* ``/recovery``        → maps to ``Recovery`` rows (source="whoop")
* ``/activity/sleep``  → maps to ``SleepSession`` rows (source="whoop")
* ``/activity/workout``→ maps to ``WhoopWorkout`` rows

Each resource is upserted independently so a partial failure on one
doesn't block the others. Idempotent keys:
* Recovery: (source, date) — unique on ``Recovery.date`` today
* SleepSession: (source="whoop", date) — unique constraint
* WhoopWorkout: ``whoop_id`` — unique column
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.clients.whoop import WhoopAuthError, WhoopClient, WhoopRateLimitError
from backend.models import Recovery, SleepSession, WhoopWorkout
from backend.services.time_utils import utc_now

logger = logging.getLogger(__name__)


def _parse_dt(value: str | None) -> datetime | None:
    """Parse Whoop's ISO-8601 ``...Z`` strings into naive-UTC datetimes."""
    if not value:
        return None
    s = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s).astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def _cycle_start_date(cycle: dict) -> date | None:
    dt = _parse_dt(cycle.get("start"))
    return dt.date() if dt else None


def _sleep_wake_date(record: dict) -> date | None:
    """Associate a sleep record with its WAKE date (same convention as Eight Sleep)."""
    end = _parse_dt(record.get("end")) or _parse_dt(record.get("start"))
    return end.date() if end else None


async def sync_whoop(
    db: AsyncSession,
    client: WhoopClient,
    *,
    days: int = 30,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, int]:
    """Pull recovery + sleep + workouts (+ cycles, for date derivation).

    Returns a dict with per-resource insert/update counts so the caller
    can log a concise summary. Never raises on per-record errors — those
    are counted as ``failed``. Does raise on auth/rate-limit failures so
    the caller can stop cleanly.
    """
    if not client.is_enabled:
        logger.info("Whoop client not enabled; skipping sync.")
        return {
            "recovery_new": 0, "recovery_updated": 0,
            "sleep_new": 0, "sleep_updated": 0,
            "workouts_new": 0, "workouts_updated": 0,
            "failed": 0,
        }

    end = end or utc_now()
    start = start or (end - timedelta(days=days))

    stats = {
        "recovery_new": 0, "recovery_updated": 0,
        "sleep_new": 0, "sleep_updated": 0,
        "workouts_new": 0, "workouts_updated": 0,
        "failed": 0,
    }

    # Cycles first — we need them to map recovery records to dates.
    cycles = await client.get_cycles(start, end)
    cycle_by_id: dict[int, dict] = {
        int(c["id"]): c for c in cycles if c.get("id") is not None
    }
    logger.info("Whoop: got %d cycles", len(cycle_by_id))

    # Recovery
    try:
        recoveries = await client.get_recovery(start, end)
    except (WhoopAuthError, WhoopRateLimitError):
        raise
    for rec in recoveries:
        try:
            stats_key = await _upsert_recovery(db, rec, cycle_by_id)
            if stats_key:
                stats[stats_key] += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("Whoop recovery upsert failed: %s", e)
            stats["failed"] += 1

    # Sleep
    try:
        sleeps = await client.get_sleep(start, end)
    except (WhoopAuthError, WhoopRateLimitError):
        raise
    for s in sleeps:
        try:
            stats_key = await _upsert_sleep(db, s)
            if stats_key:
                stats[stats_key] += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("Whoop sleep upsert failed: %s", e)
            stats["failed"] += 1

    # Workouts
    try:
        workouts = await client.get_workouts(start, end)
    except (WhoopAuthError, WhoopRateLimitError):
        raise
    for w in workouts:
        try:
            stats_key = await _upsert_workout(db, w)
            if stats_key:
                stats[stats_key] += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("Whoop workout upsert failed: %s", e)
            stats["failed"] += 1

    await db.commit()
    logger.info(
        "Whoop sync: recovery+%d/upd%d, sleep+%d/upd%d, workouts+%d/upd%d, failed=%d",
        stats["recovery_new"], stats["recovery_updated"],
        stats["sleep_new"], stats["sleep_updated"],
        stats["workouts_new"], stats["workouts_updated"],
        stats["failed"],
    )
    return stats


# ── Upsert helpers ──────────────────────────────────────────────────


async def _upsert_recovery(
    db: AsyncSession, rec: dict, cycle_by_id: dict[int, dict]
) -> str | None:
    cycle_id = rec.get("cycle_id")
    cycle = cycle_by_id.get(int(cycle_id)) if cycle_id is not None else None
    rec_date = _cycle_start_date(cycle) if cycle else None
    if rec_date is None:
        logger.debug("Whoop recovery without cycle → skipping: %s", rec.get("cycle_id"))
        return None

    score = rec.get("score") or {}
    fields: dict[str, Any] = {
        "recovery_score": score.get("recovery_score"),
        "resting_hr": score.get("resting_heart_rate"),
        "hrv": score.get("hrv_rmssd_milli"),
        "spo2": score.get("spo2_percentage"),
        "skin_temp": score.get("skin_temp_celsius"),
        "raw_data": rec,
    }

    existing = (
        await db.execute(select(Recovery).where(Recovery.date == rec_date))
    ).scalar_one_or_none()
    if existing:
        dirty = False
        for k, v in fields.items():
            if getattr(existing, k) != v:
                setattr(existing, k, v)
                dirty = True
        return "recovery_updated" if dirty else None

    db.add(Recovery(source="whoop", date=rec_date, **fields))
    return "recovery_new"


async def _upsert_sleep(db: AsyncSession, rec: dict) -> str | None:
    # Skip naps. Whoop returns naps via the same /activity/sleep endpoint with
    # nap=true, but a nap on the same wake date as a main sleep would collide
    # with the (source, date) unique constraint and fail the upsert. We don't
    # surface naps in the UI today; treat them as no-ops.
    if rec.get("nap"):
        return None

    sleep_date = _sleep_wake_date(rec)
    if sleep_date is None:
        return None

    score = rec.get("score") or {}
    stages = score.get("stage_summary") or {}
    sleep_needed = score.get("sleep_needed") or {}

    def _ms_to_min(ms: int | None) -> int | None:
        return int(ms // 60_000) if isinstance(ms, (int, float)) else None

    total_in_bed = _ms_to_min(stages.get("total_in_bed_time_milli"))
    total_awake = _ms_to_min(stages.get("total_awake_time_milli"))
    total_duration = (total_in_bed - total_awake) if total_in_bed and total_awake else total_in_bed

    fields: dict[str, Any] = {
        "external_id": str(rec.get("id")) if rec.get("id") is not None else None,
        "bed_time": _parse_dt(rec.get("start")),
        "wake_time": _parse_dt(rec.get("end")),
        "total_duration": total_duration,
        "deep_sleep": _ms_to_min(stages.get("total_slow_wave_sleep_time_milli")),
        "rem_sleep": _ms_to_min(stages.get("total_rem_sleep_time_milli")),
        "light_sleep": _ms_to_min(stages.get("total_light_sleep_time_milli")),
        "awake_time": total_awake,
        "sleep_score": score.get("sleep_performance_percentage"),
        "respiratory_rate": score.get("respiratory_rate"),
        "wake_count": stages.get("disturbance_count"),
        # Whoop-only extras. Eight Sleep doesn't surface these.
        "sleep_efficiency": score.get("sleep_efficiency_percentage"),
        "sleep_consistency": score.get("sleep_consistency_percentage"),
        "sleep_need_baseline_min": _ms_to_min(sleep_needed.get("baseline_milli")),
        "sleep_debt_min": _ms_to_min(sleep_needed.get("need_from_sleep_debt_milli")),
        "raw_data": rec,
    }

    existing = (
        await db.execute(
            select(SleepSession).where(
                SleepSession.source == "whoop",
                SleepSession.date == sleep_date,
            )
        )
    ).scalar_one_or_none()
    if existing:
        dirty = False
        for k, v in fields.items():
            if getattr(existing, k) != v:
                setattr(existing, k, v)
                dirty = True
        return "sleep_updated" if dirty else None

    db.add(SleepSession(source="whoop", date=sleep_date, **fields))
    return "sleep_new"


async def _upsert_workout(db: AsyncSession, rec: dict) -> str | None:
    whoop_id = rec.get("id")
    if whoop_id is None:
        return None

    score = rec.get("score") or {}
    zones = score.get("zone_durations") or {}
    start_dt = _parse_dt(rec.get("start"))
    if start_dt is None:
        return None

    fields: dict[str, Any] = {
        "start": start_dt,
        "end": _parse_dt(rec.get("end")),
        "timezone_offset": rec.get("timezone_offset"),
        "sport_id": rec.get("sport_id"),
        "sport_name": rec.get("sport_name"),
        "score_state": rec.get("score_state"),
        "strain": score.get("strain"),
        "average_heart_rate": score.get("average_heart_rate"),
        "max_heart_rate": score.get("max_heart_rate"),
        "kilojoule": score.get("kilojoule"),
        "percent_recorded": score.get("percent_recorded"),
        "distance_meter": score.get("distance_meter"),
        "altitude_gain_meter": score.get("altitude_gain_meter"),
        "altitude_change_meter": score.get("altitude_change_meter"),
        "zone_zero_ms": zones.get("zone_zero_milli"),
        "zone_one_ms": zones.get("zone_one_milli"),
        "zone_two_ms": zones.get("zone_two_milli"),
        "zone_three_ms": zones.get("zone_three_milli"),
        "zone_four_ms": zones.get("zone_four_milli"),
        "zone_five_ms": zones.get("zone_five_milli"),
        "raw_data": rec,
    }

    existing = (
        await db.execute(
            select(WhoopWorkout).where(WhoopWorkout.whoop_id == str(whoop_id))
        )
    ).scalar_one_or_none()
    if existing:
        dirty = False
        for k, v in fields.items():
            if getattr(existing, k) != v:
                setattr(existing, k, v)
                dirty = True
        return "workouts_updated" if dirty else None

    db.add(WhoopWorkout(whoop_id=str(whoop_id), **fields))
    return "workouts_new"
