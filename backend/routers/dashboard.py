from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from importlib.util import find_spec

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import Activity, SleepSession
from backend.routers.activities import _activity_summary
from backend.routers.sleep import _sleep_dict
from backend.services import sleep_recovery_snapshot, training_load_snapshot
from backend.services.metrics import (
    get_recovery_trends,
    get_sleep_trends,
    get_training_load,
    get_weekly_stats,
)
from backend.services.snapshot_models import EnvironmentTodaySnapshot
from backend.services.strength import list_sessions, progression, search_exercises
from backend.services.time_utils import local_today, utc_now_naive

if find_spec("backend.services.environment"):
    from backend.services.environment import fetch_environment_today
else:  # pragma: no cover - replaced by the environment chunk.
    async def fetch_environment_today(db: AsyncSession) -> dict | None:
        return None


router = APIRouter()
logger = logging.getLogger(__name__)


class DashboardTileModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DashboardSleepToday(DashboardTileModel):
    last_night_score: int | None
    last_night_duration_min: int | None
    last_night_deep_min: int | None
    last_night_rem_min: int | None
    last_night_date: str | None


class DashboardRecoveryToday(DashboardTileModel):
    today_hrv: float | None
    today_resting_hr: float | None
    hrv_baseline_7d: float | None
    hrv_trend: str | None
    hrv_source: str | None


class DashboardTrainingToday(DashboardTileModel):
    yesterday_stress: float
    week_to_date_load: float
    acwr: float | None
    acwr_band: str | None
    days_since_hard: int | None


class DashboardToday(DashboardTileModel):
    as_of: str
    sleep: DashboardSleepToday
    recovery: DashboardRecoveryToday
    training: DashboardTrainingToday
    environment: EnvironmentTodaySnapshot | None


@router.get("/overview")
async def dashboard_overview(db: AsyncSession = Depends(get_db)):
    """Get dashboard overview data: recent stats, sleep, recovery, training load."""
    weekly = await get_weekly_stats(db, weeks=4)
    sleep = await get_sleep_trends(db, days=7)
    recovery = await get_recovery_trends(db, days=7)
    training = await get_training_load(db, days=42)

    return {
        "weekly_stats": weekly,
        "recent_sleep": sleep,
        "recent_recovery": recovery,
        "training_load": training,
    }


@router.get("/history")
async def dashboard_history(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(200, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Bundle the History page's cold-load data into one API request."""
    cutoff = utc_now_naive() - timedelta(days=days)
    activities_result = await db.execute(
        select(Activity)
        .where(Activity.start_date >= cutoff)
        .order_by(Activity.start_date.desc())
        .limit(limit)
    )
    activities = activities_result.scalars().all()
    sleep_result = await db.execute(
        select(SleepSession)
        .where(SleepSession.date >= local_today() - timedelta(days=days))
        .order_by(SleepSession.date.desc())
    )
    sleep = sleep_result.scalars().all()

    return {
        "activities": [_activity_summary(a) for a in activities],
        "sleep": [_sleep_dict(s) for s in sleep],
        "strength": await list_sessions(db, limit=200),
    }


@router.get("/training-trends")
async def dashboard_training_trends(
    days: int = Query(90, ge=1, le=365),
    limit: int = Query(200, ge=1, le=200),
    exercise: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Bundle the Trends page's cold-load data into one API request.

    The frontend still asks for a new bundle when the selected exercise
    changes, but the initial page load avoids six independent Railway
    round trips.
    """
    cutoff = utc_now_naive() - timedelta(days=days)
    activities_result = await db.execute(
        select(Activity)
        .where(Activity.start_date >= cutoff)
        .order_by(Activity.start_date.desc())
        .limit(limit)
    )
    activities = activities_result.scalars().all()
    exercises = await search_exercises(db, q=None, limit=20)
    selected_exercise = exercise or (exercises[0] if exercises else None)

    return {
        "activities": [_activity_summary(a) for a in activities],
        "recovery": await get_recovery_trends(db, days=days, today=local_today()),
        "sleep": await get_sleep_trends(db, days=days, today=local_today()),
        "strength_sessions": await list_sessions(db, limit=200),
        "strength_exercises": exercises,
        "selected_exercise": selected_exercise,
        "strength_progression": (
            await progression(db, exercise_name=selected_exercise, days=days)
            if selected_exercise
            else []
        ),
    }


def _parse_dashboard_date(raw: str | None) -> date:
    """Parse ?date= for the dashboard. Empty -> today; future -> 400."""
    today = local_today()
    if not raw:
        return today
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid date; expected YYYY-MM-DD") from exc
    if parsed > today:
        raise HTTPException(status_code=400, detail="Future dates are not supported")
    return parsed


@router.get("/today", response_model=DashboardToday)
async def dashboard_today(
    date: str | None = Query(None, description="YYYY-MM-DD; defaults to today"),
    db: AsyncSession = Depends(get_db),
):
    """Get the dashboard's sleep, recovery, load, and environment for a given date.

    Defaults to today. Past dates re-anchor sleep/recovery/training but skip
    environment (no historical forecast). Future dates return 400.
    """
    target = _parse_dashboard_date(date)
    sleep = await sleep_recovery_snapshot.get_sleep_snapshot(db, days=14, today=target)
    recovery = await sleep_recovery_snapshot.get_recovery_snapshot(
        db, days=7, today=target
    )
    training = await training_load_snapshot.get_training_load_snapshot(
        db, days=42, today=target
    )

    if target == local_today():
        try:
            environment = await fetch_environment_today(db)
        except Exception:
            logger.exception("Failed to fetch dashboard environment snapshot")
            environment = None
    else:
        environment = None

    return {
        "as_of": datetime.now().astimezone().isoformat(),
        "sleep": {
            "last_night_score": sleep["last_night_score"],
            "last_night_duration_min": sleep["last_night_duration_min"],
            "last_night_deep_min": sleep.get("last_night_deep_min"),
            "last_night_rem_min": sleep.get("last_night_rem_min"),
            "last_night_date": sleep.get("last_night_date"),
        },
        "recovery": {
            "today_hrv": recovery["today_hrv"],
            "today_resting_hr": recovery["today_resting_hr"],
            "hrv_baseline_7d": recovery["hrv_baseline_7d"],
            "hrv_trend": recovery["hrv_trend"],
            "hrv_source": recovery["hrv_source"],
        },
        "training": _dashboard_training_payload(training, target),
        "environment": environment,
    }


def _dashboard_training_payload(training: dict, today: date) -> dict:
    daily_loads = {
        date.fromisoformat(point["date"]): point["value"]
        for point in training["daily_loads"]
    }
    week_start = today - timedelta(days=today.weekday())
    week_to_date = sum(
        load for day, load in daily_loads.items() if week_start <= day <= today
    )
    yesterday = today - timedelta(days=1)
    acwr = training["acwr"]

    return {
        "yesterday_stress": daily_loads.get(yesterday, 0.0),
        "week_to_date_load": round(week_to_date, 1),
        "acwr": acwr,
        "acwr_band": training_load_snapshot.acwr_band(acwr),
        "days_since_hard": training["days_since_hard"],
    }
