from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Activity, SleepSession, Recovery
from backend.services.time_utils import local_today


async def get_weekly_stats(
    db: AsyncSession, weeks: int = 4, today: date | None = None
) -> list[dict]:
    """Get weekly training volume stats."""
    results = []
    today = today or local_today()

    for i in range(weeks):
        week_end = today - timedelta(days=today.weekday()) - timedelta(weeks=i)
        week_start = week_end - timedelta(days=6)

        activities = await db.execute(
            select(Activity).where(
                Activity.start_date >= datetime.combine(week_start, datetime.min.time()),
                Activity.start_date < datetime.combine(week_end + timedelta(days=1), datetime.min.time()),
            )
        )
        acts = activities.scalars().all()

        total_distance = sum(a.distance or 0 for a in acts)
        total_time = sum(a.moving_time or 0 for a in acts)
        total_calories = sum(a.calories or 0 for a in acts)
        sport_breakdown = {}
        for a in acts:
            sport_breakdown[a.sport_type] = sport_breakdown.get(a.sport_type, 0) + 1

        results.append({
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "total_activities": len(acts),
            "total_distance_km": round(total_distance / 1000, 1),
            "total_time_minutes": total_time // 60,
            "total_calories": round(total_calories),
            "sport_breakdown": sport_breakdown,
        })

    return results


async def get_sleep_trends(
    db: AsyncSession, days: int = 30, today: date | None = None
) -> list[dict]:
    """Get sleep trend data for the last N days."""
    today = today or local_today()
    cutoff = today - timedelta(days=days)
    result = await db.execute(
        select(SleepSession)
        .where(SleepSession.date >= cutoff)
        .order_by(SleepSession.date.asc())
    )
    sessions = result.scalars().all()

    return [
        {
            "date": s.date.isoformat(),
            "source": s.source,
            "sleep_score": s.sleep_score,
            "total_duration": s.total_duration,
            "deep_sleep": s.deep_sleep,
            "rem_sleep": s.rem_sleep,
            "light_sleep": s.light_sleep,
            "awake_time": s.awake_time,
            "hrv": s.hrv,
            "avg_hr": s.avg_hr,
            "respiratory_rate": s.respiratory_rate,
        }
        for s in sessions
    ]


async def get_recovery_trends(
    db: AsyncSession, days: int = 30, today: date | None = None
) -> list[dict]:
    """Get recovery trend data."""
    today = today or local_today()
    cutoff = today - timedelta(days=days)
    result = await db.execute(
        select(Recovery)
        .where(Recovery.date >= cutoff)
        .order_by(Recovery.date.asc())
    )
    records = result.scalars().all()

    return [
        {
            "date": r.date.isoformat(),
            "recovery_score": r.recovery_score,
            "resting_hr": r.resting_hr,
            "hrv": r.hrv,
            "spo2": r.spo2,
            "strain_score": r.strain_score,
        }
        for r in records
    ]


async def get_training_load(
    db: AsyncSession, days: int = 42, today: date | None = None
) -> dict:
    """Calculate training load metrics (simplified CTL/ATL/TSB)."""
    today = today or local_today()
    cutoff = datetime.combine(today - timedelta(days=days), datetime.min.time())
    result = await db.execute(
        select(Activity)
        .where(Activity.start_date >= cutoff)
        .order_by(Activity.start_date.asc())
    )
    activities = result.scalars().all()

    # Use suffer_score (relative effort) as training stress proxy
    # Fall back to duration * avg_hr as rough TRIMP estimate
    daily_load: dict[str, float] = {}
    for a in activities:
        day = a.start_date.strftime("%Y-%m-%d")
        stress = a.suffer_score or 0
        if not stress and a.moving_time and a.average_hr:
            stress = (a.moving_time / 60) * (a.average_hr / 180)  # Simplified TRIMP
        daily_load[day] = daily_load.get(day, 0) + stress

    # Calculate rolling averages
    ctl_data = []  # Chronic (42-day)
    atl_data = []  # Acute (7-day)
    tsb_data = []  # Training stress balance

    for i in range(days):
        d = today - timedelta(days=days - 1 - i)
        day_str = d.isoformat()

        # 7-day rolling avg (ATL)
        atl_days = [(d - timedelta(days=j)).isoformat() for j in range(7)]
        atl = sum(daily_load.get(dd, 0) for dd in atl_days) / 7

        # 42-day rolling avg (CTL)
        ctl_days = [(d - timedelta(days=j)).isoformat() for j in range(42)]
        ctl = sum(daily_load.get(dd, 0) for dd in ctl_days) / 42

        ctl_data.append({"date": day_str, "value": round(ctl, 1)})
        atl_data.append({"date": day_str, "value": round(atl, 1)})
        tsb_data.append({"date": day_str, "value": round(ctl - atl, 1)})

    return {
        "ctl": ctl_data,
        "atl": atl_data,
        "tsb": tsb_data,
        "daily_load": [
            {"date": k, "value": round(v, 1)}
            for k, v in sorted(daily_load.items())
        ],
    }
