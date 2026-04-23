"""Compatibility facade for dashboard insight snapshot assembly.

The focused builders live in sibling modules; this file keeps the historic
``backend.services.training_metrics`` import path stable and composes the
full snapshot used by daily recommendations.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Activity
from backend.services.goals_feedback_snapshot import (
    get_baselines,
    get_feedback_summary,
    get_goals_snapshot,
    get_recent_rpe,
)
from backend.services.sleep_recovery_snapshot import (
    get_environmental_snapshot,
    get_recovery_snapshot,
    get_sleep_snapshot,
)
from backend.services.snapshot_models import (
    FullSnapshot,
    RecentActivitySnapshot,
    validate_snapshot,
    validate_snapshot_list,
)
from backend.services.time_utils import local_today
from backend.services.training_load_snapshot import (
    HARD_CLASSIFICATIONS,
    _stress_score,
    get_training_load_snapshot,
)
from backend.services.workout_snapshot import (
    _get_latest_completed_activity,
    _pace_str,
    get_latest_workout_snapshot,
)


async def get_full_snapshot(db: AsyncSession, today: date | None = None) -> dict:
    today = today or local_today()
    training = await get_training_load_snapshot(db, today=today)
    sleep = await get_sleep_snapshot(db, today=today)
    recovery = await get_recovery_snapshot(db, today=today)
    latest = await get_latest_workout_snapshot(db)
    goals = await get_goals_snapshot(db, today=today)
    baselines = await get_baselines(db, today=today)
    recent_rpe = await get_recent_rpe(db, today=today)
    feedback = await get_feedback_summary(db, today=today)
    environmental = await get_environmental_snapshot(db)

    rows = await db.execute(
        select(Activity)
        .where(Activity.enrichment_status == "complete")
        .order_by(Activity.start_date.desc())
        .limit(10)
    )
    recent = []
    for a in rows.scalars().all():
        recent.append(
            {
                "date": (a.start_date_local or a.start_date).strftime("%Y-%m-%d"),
                "sport": a.sport_type,
                "classification": a.classification_type,
                "duration_min": (a.moving_time // 60) if a.moving_time else None,
                "distance_km": round(a.distance / 1000, 2) if a.distance else None,
                "avg_hr": round(a.average_hr) if a.average_hr else None,
                "suffer_score": a.suffer_score,
                "pace": _pace_str(a.average_speed) if a.sport_type.endswith("Run") else None,
            }
        )

    validate_snapshot_list(recent, RecentActivitySnapshot)

    payload = {
        "today": today.isoformat(),
        "training_load": training,
        "sleep": sleep,
        "recovery": recovery,
        "latest_workout": latest,
        "recent_activities": recent,
        "goals": goals,
        "baselines": baselines,
        "recent_rpe": recent_rpe,
        "feedback_summary": feedback,
        "environmental": environmental,
    }
    return validate_snapshot(payload, FullSnapshot)


__all__ = [
    "HARD_CLASSIFICATIONS",
    "_get_latest_completed_activity",
    "_pace_str",
    "_stress_score",
    "get_baselines",
    "get_environmental_snapshot",
    "get_feedback_summary",
    "get_full_snapshot",
    "get_goals_snapshot",
    "get_latest_workout_snapshot",
    "get_recent_rpe",
    "get_recovery_snapshot",
    "get_sleep_snapshot",
    "get_training_load_snapshot",
]
