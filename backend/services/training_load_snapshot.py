"""Training-load snapshot assembly for dashboard insights."""

from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Activity
from backend.services.snapshot_models import TrainingLoadSnapshot, validate_snapshot
from backend.services.time_utils import local_today

HARD_CLASSIFICATIONS = {"intervals", "tempo", "race", "mixed"}


def _stress_score(a: Activity) -> float:
    """TRIMP-ish training stress proxy, scaled to Strava's suffer_score.

    Three tiers of fidelity; all intended to land in roughly the same
    0-200 range for typical sessions so ACWR / monotony don't get skewed
    when HR is unavailable (e.g. strength sessions, indoor spin):

    1. Strava ``suffer_score`` (watch-derived) -- preferred; 0-300.
    2. HR-based: ``duration_min * (avg_hr / 180) * 1.2`` -- 60 min @
       140 bpm ~= 56, matching Strava's RE for a typical aerobic run.
    3. Duration-only: ``duration_min``. Assumes moderate effort
       (~=140 bpm). A 60-min strength session scores 60, comparable to
       the HR-based path; previously this was ``duration_min / 2`` which
       underweighted unlogged-HR sessions by ~2x and tilted ACWR.
    """
    if a.suffer_score:
        return float(a.suffer_score)
    if a.moving_time and a.average_hr:
        return (a.moving_time / 60.0) * (a.average_hr / 180.0) * 1.2
    if a.moving_time:
        return a.moving_time / 60.0
    return 0.0


async def get_training_load_snapshot(
    db: AsyncSession, days: int = 42, today: date | None = None
) -> dict:
    """Snapshot of recent training load for the LLM recommendation input."""
    today = today or local_today()
    window_start = today - timedelta(days=days)
    cutoff_dt = datetime.combine(window_start, datetime.min.time())

    rows = await db.execute(
        select(Activity)
        .where(Activity.start_date >= cutoff_dt)
        .order_by(Activity.start_date.asc())
    )
    activities = list(rows.scalars().all())

    daily: dict[date, float] = {}
    class_7d: dict[str, int] = {}
    class_28d: dict[str, int] = {}
    last_hard_date: date | None = None

    for a in activities:
        day = (a.start_date_local or a.start_date).date()
        daily[day] = daily.get(day, 0.0) + _stress_score(a)

        if a.classification_type:
            if (today - day).days < 28:
                class_28d[a.classification_type] = class_28d.get(a.classification_type, 0) + 1
            if (today - day).days < 7:
                class_7d[a.classification_type] = class_7d.get(a.classification_type, 0) + 1
            if a.classification_type in HARD_CLASSIFICATIONS:
                if last_hard_date is None or day > last_hard_date:
                    last_hard_date = day

    def _sum_window(days_back: int) -> float:
        total = 0.0
        for i in range(days_back):
            d = today - timedelta(days=i)
            total += daily.get(d, 0.0)
        return total

    acute_7d = _sum_window(7)
    chronic_28d = _sum_window(28)

    acute_avg = acute_7d / 7.0
    chronic_avg = chronic_28d / 28.0
    acwr = acute_avg / chronic_avg if chronic_avg > 0 else None

    last_7_values = [daily.get(today - timedelta(days=i), 0.0) for i in range(7)]
    monotony: float | None = None
    strain: float | None = None
    if any(v > 0 for v in last_7_values):
        m = statistics.mean(last_7_values)
        s = statistics.pstdev(last_7_values)
        if s > 0:
            monotony = m / s
            strain = acute_7d * monotony

    days_since_hard = (today - last_hard_date).days if last_hard_date else None

    daily_series = [
        {
            "date": (today - timedelta(days=27 - i)).isoformat(),
            "value": round(daily.get(today - timedelta(days=27 - i), 0.0), 1),
        }
        for i in range(28)
    ]

    payload = {
        "acute_load_7d": round(acute_7d, 1),
        "chronic_load_28d": round(chronic_28d, 1),
        "acwr": round(acwr, 2) if acwr is not None else None,
        "monotony": round(monotony, 2) if monotony is not None else None,
        "strain": round(strain, 1) if strain is not None else None,
        "days_since_hard": days_since_hard,
        "last_hard_date": last_hard_date.isoformat() if last_hard_date else None,
        "classification_counts_7d": class_7d,
        "classification_counts_28d": class_28d,
        "daily_loads": daily_series,
        "activity_count_7d": sum(
            1
            for a in activities
            if (today - (a.start_date_local or a.start_date).date()).days < 7
        ),
    }
    return validate_snapshot(payload, TrainingLoadSnapshot)
