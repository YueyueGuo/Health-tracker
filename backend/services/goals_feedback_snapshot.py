"""Goals, baselines, RPE, and recommendation-feedback snapshots."""

from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Activity, Goal, RecommendationFeedback
from backend.services.snapshot_models import (
    FeedbackSummarySnapshot,
    GoalsSnapshot,
    RecentRpeSnapshot,
    validate_baselines,
    validate_snapshot,
    validate_snapshot_list,
)
from backend.services.time_utils import local_today


def _periodization_phase(weeks_until: int) -> str:
    """Map weeks-until-goal to a training phase."""
    if weeks_until <= 2:
        return "peak"
    if weeks_until <= 4:
        return "taper"
    if weeks_until <= 12:
        return "build"
    return "base"


def _goal_to_dict(g: Goal, today: date) -> dict:
    days_until = (g.target_date - today).days
    weeks_until = max(0, days_until // 7)
    return {
        "id": g.id,
        "race_type": g.race_type,
        "description": g.description,
        "target_date": g.target_date.isoformat(),
        "days_until": days_until,
        "weeks_until": weeks_until,
        "phase": _periodization_phase(weeks_until) if days_until >= 0 else "post",
        "is_primary": g.is_primary,
        "status": g.status,
    }


async def get_goals_snapshot(db: AsyncSession, today: date | None = None) -> dict:
    """Return the user's active goals, split into primary + secondary."""
    today = today or local_today()
    rows = await db.execute(
        select(Goal)
        .where(Goal.status == "active")
        .order_by(Goal.is_primary.desc(), Goal.target_date.asc())
    )
    goals = list(rows.scalars().all())
    primary = next((g for g in goals if g.is_primary), None)
    secondary = [g for g in goals if not g.is_primary]
    payload = {
        "primary": _goal_to_dict(primary, today) if primary else None,
        "secondary": [_goal_to_dict(g, today) for g in secondary],
    }
    return validate_snapshot(payload, GoalsSnapshot)


def _mean_sd(values: list[float]) -> tuple[float, float] | None:
    clean = [v for v in values if v is not None]
    if len(clean) < 2:
        return None
    return statistics.mean(clean), statistics.pstdev(clean)


async def get_baselines(
    db: AsyncSession, days: int = 90, today: date | None = None
) -> dict:
    """Mean + stdev of pace / HR / power per sport over the last ``days``."""
    today = today or local_today()
    cutoff_dt = datetime.combine(today - timedelta(days=days), datetime.min.time())
    rows = await db.execute(
        select(Activity).where(
            Activity.start_date >= cutoff_dt,
            Activity.enrichment_status == "complete",
        )
    )
    by_sport: dict[str, list[Activity]] = {}
    for a in rows.scalars().all():
        by_sport.setdefault(a.sport_type, []).append(a)

    out: dict[str, dict | None] = {}
    for sport, items in by_sport.items():
        if len(items) < 10:
            out[sport] = None
            continue

        def _round_pair(pair):
            if pair is None:
                return None
            return {"mean": round(pair[0], 2), "sd": round(pair[1], 2)}

        pace_values = [1000.0 / a.average_speed for a in items if a.average_speed]
        hr_values = [a.average_hr for a in items if a.average_hr]
        power_values = [a.average_power for a in items if a.average_power]
        out[sport] = {
            "sample_size": len(items),
            "pace_s_per_km": _round_pair(_mean_sd(pace_values)),
            "avg_hr": _round_pair(_mean_sd(hr_values)),
            "avg_power_w": _round_pair(_mean_sd(power_values)),
        }
    return validate_baselines(out)


async def get_recent_rpe(
    db: AsyncSession,
    days: int = 14,
    limit: int = 10,
    today: date | None = None,
) -> list[dict]:
    """Compact list of recent workouts where the user rated perceived effort."""
    today = today or local_today()
    cutoff_dt = datetime.combine(today - timedelta(days=days), datetime.min.time())
    rows = await db.execute(
        select(Activity)
        .where(
            Activity.start_date >= cutoff_dt,
            Activity.rpe.is_not(None),
        )
        .order_by(Activity.start_date.desc())
        .limit(limit)
    )
    out: list[dict] = []
    for a in rows.scalars().all():
        out.append(
            {
                "activity_id": a.id,
                "date": (a.start_date_local or a.start_date).strftime("%Y-%m-%d"),
                "sport_type": a.sport_type,
                "classification": a.classification_type,
                "rpe": a.rpe,
                "notes": a.user_notes,
                "avg_hr": round(a.average_hr) if a.average_hr else None,
                "suffer_score": a.suffer_score,
            }
        )
    return validate_snapshot_list(out, RecentRpeSnapshot)


async def get_feedback_summary(
    db: AsyncSession, days: int = 30, today: date | None = None
) -> dict:
    today = today or local_today()
    cutoff = today - timedelta(days=days)
    rows = await db.execute(
        select(RecommendationFeedback)
        .where(RecommendationFeedback.recommendation_date >= cutoff)
        .order_by(RecommendationFeedback.recommendation_date.desc())
    )
    items = list(rows.scalars().all())
    up = sum(1 for r in items if r.vote == "up")
    down = sum(1 for r in items if r.vote == "down")
    recent_declines = [
        {
            "date": r.recommendation_date.isoformat(),
            "reason": r.reason,
        }
        for r in items
        if r.vote == "down"
    ][:5]
    payload = {
        "accepted": up,
        "declined": down,
        "total": len(items),
        "recent_declines": recent_declines,
    }
    return validate_snapshot(payload, FeedbackSummarySnapshot)
