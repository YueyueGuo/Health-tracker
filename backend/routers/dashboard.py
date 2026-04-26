from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from importlib.util import find_spec

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.services import sleep_recovery_snapshot, training_load_snapshot
from backend.services.metrics import (
    get_recovery_trends,
    get_sleep_trends,
    get_training_load,
    get_weekly_stats,
)
from backend.services.snapshot_models import EnvironmentTodaySnapshot
from backend.services.time_utils import local_today

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


@router.get("/today", response_model=DashboardToday)
async def dashboard_today(db: AsyncSession = Depends(get_db)):
    """Get the dashboard's current sleep, recovery, load, and environment state."""
    today = local_today()
    sleep = await sleep_recovery_snapshot.get_sleep_snapshot(db, days=14, today=today)
    recovery = await sleep_recovery_snapshot.get_recovery_snapshot(
        db, days=7, today=today
    )
    training = await training_load_snapshot.get_training_load_snapshot(
        db, days=42, today=today
    )

    try:
        environment = await fetch_environment_today(db)
    except Exception:
        logger.exception("Failed to fetch dashboard environment snapshot")
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
        "training": _dashboard_training_payload(training, today),
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
