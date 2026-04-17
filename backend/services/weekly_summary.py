"""Weekly training summary.

Produces a structured view of a training week: totals, per-sport breakdown,
per-classification run breakdown, a handful of useful flags (long run,
speed session present), and pointers to the "notable" activity IDs
(longest, hardest).

Week boundary is ISO (Monday → Sunday).

Public API:
    week_summary(db, week_start_date) -> dict
    weekly_summaries(db, weeks=4, end_date=None) -> list[dict]
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Activity


def iso_week_start(d: date) -> date:
    """Monday of the ISO week containing `d`."""
    return d - timedelta(days=d.weekday())


def _week_bounds(week_start: date) -> tuple[datetime, datetime]:
    """(inclusive start, exclusive end) as naive UTC datetimes."""
    # Activities are stored with tz-aware datetimes but naive comparisons work
    # because SQLAlchemy strips tz on SQLite. Keep naive here for portability.
    start_dt = datetime.combine(week_start, time.min)
    end_dt = datetime.combine(week_start + timedelta(days=7), time.min)
    return start_dt, end_dt


async def _activities_in_week(
    db: AsyncSession, week_start: date
) -> list[Activity]:
    start_dt, end_dt = _week_bounds(week_start)
    result = await db.execute(
        select(Activity)
        .where(Activity.start_date >= start_dt)
        .where(Activity.start_date < end_dt)
        .order_by(Activity.start_date.asc())
    )
    return list(result.scalars().all())


async def week_summary(db: AsyncSession, week_start: date) -> dict:
    """Summarize a single ISO week starting at `week_start` (a Monday)."""
    if week_start.weekday() != 0:
        week_start = iso_week_start(week_start)

    activities = await _activities_in_week(db, week_start)

    # Totals across everything.
    totals = {
        "activity_count": len(activities),
        "duration_s": sum(a.moving_time or 0 for a in activities),
        "distance_m": round(sum(a.distance or 0 for a in activities), 1),
        "total_elevation_m": round(
            sum(a.total_elevation or 0 for a in activities), 1
        ),
        "suffer_score": sum(a.suffer_score or 0 for a in activities),
        "kilojoules": round(sum(a.kilojoules or 0 for a in activities), 1),
        "calories": round(sum(a.calories or 0 for a in activities), 1),
    }

    # Per-sport breakdown (Run / Ride / WeightTraining / etc).
    by_sport: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "duration_s": 0, "distance_m": 0.0, "kilojoules": 0.0}
    )
    for a in activities:
        row = by_sport[a.sport_type or "Unknown"]
        row["count"] += 1
        row["duration_s"] += a.moving_time or 0
        row["distance_m"] += a.distance or 0
        row["kilojoules"] += a.kilojoules or 0
    # Round floats for presentation.
    for row in by_sport.values():
        row["distance_m"] = round(row["distance_m"], 1)
        row["kilojoules"] = round(row["kilojoules"], 1)

    # Classification breakdown for runs specifically. Skip if not a run.
    run_breakdown: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "duration_s": 0, "distance_m": 0.0}
    )
    for a in activities:
        if "run" not in (a.sport_type or "").lower():
            continue
        label = a.classification_type or "unclassified"
        row = run_breakdown[label]
        row["count"] += 1
        row["duration_s"] += a.moving_time or 0
        row["distance_m"] += a.distance or 0
    for row in run_breakdown.values():
        row["distance_m"] = round(row["distance_m"], 1)

    # Flags — quick answers to "what kind of week was this?"
    flags = _compute_flags(activities)

    notable = _notable_activities(activities)

    # How many of this week's activities are still waiting on
    # enrichment/classification? Useful UI signal during backfill.
    enrichment_pending = sum(
        1 for a in activities if a.enrichment_status != "complete"
    )
    classification_pending = sum(
        1 for a in activities
        if a.enrichment_status == "complete"
        and a.classification_type is None
        and _is_classifiable_sport(a.sport_type)
    )

    return {
        "week_start": week_start.isoformat(),
        "week_end": (week_start + timedelta(days=6)).isoformat(),
        "iso_week": f"{week_start.isocalendar().year}-W{week_start.isocalendar().week:02d}",
        "totals": totals,
        "by_sport": dict(by_sport),
        "run_breakdown": dict(run_breakdown),
        "flags": flags,
        "notable": notable,
        "enrichment_pending": enrichment_pending,
        "classification_pending": classification_pending,
    }


async def weekly_summaries(
    db: AsyncSession,
    weeks: int = 4,
    end_date: date | None = None,
) -> list[dict]:
    """Return `weeks` consecutive week summaries ending in the week containing `end_date`.

    Ordered newest-first. `end_date` defaults to today.
    """
    today = end_date or datetime.now(timezone.utc).date()
    anchor = iso_week_start(today)
    results = []
    for offset in range(weeks):
        week_start = anchor - timedelta(weeks=offset)
        results.append(await week_summary(db, week_start))
    return results


# ── Helpers ──────────────────────────────────────────────────────────────────


def _compute_flags(activities: list[Activity]) -> dict:
    has_long_run = False
    long_run_distance = 0.0
    has_speed_session = False
    has_tempo = False
    has_race = False
    has_long_ride = False

    for a in activities:
        flags = set(a.classification_flags or [])
        ctype = a.classification_type or ""
        sport = (a.sport_type or "").lower()

        if "run" in sport:
            if "is_long" in flags:
                has_long_run = True
                long_run_distance = max(long_run_distance, a.distance or 0)
            if ctype == "intervals":
                has_speed_session = True
            if ctype == "tempo":
                has_tempo = True
            if ctype == "race":
                has_race = True
        elif "ride" in sport:
            if "is_long" in flags:
                has_long_ride = True
            if ctype == "race":
                has_race = True

    return {
        "has_long_run": has_long_run,
        "long_run_distance_m": round(long_run_distance, 1) if has_long_run else 0.0,
        "has_speed_session": has_speed_session,
        "has_tempo": has_tempo,
        "has_race": has_race,
        "has_long_ride": has_long_ride,
    }


def _notable_activities(activities: list[Activity]) -> dict:
    if not activities:
        return {
            "longest_activity_id": None,
            "hardest_activity_id": None,
        }
    longest = max(activities, key=lambda a: a.moving_time or 0)
    # "Hardest" = max suffer_score, else max moving_time as fallback.
    with_stress = [a for a in activities if (a.suffer_score or 0) > 0]
    hardest = (
        max(with_stress, key=lambda a: a.suffer_score)
        if with_stress
        else longest
    )
    return {
        "longest_activity_id": longest.id,
        "hardest_activity_id": hardest.id,
    }


def _is_classifiable_sport(sport: str | None) -> bool:
    s = (sport or "").lower()
    return ("run" in s) or ("ride" in s) or ("cycle" in s) or ("bike" in s)
