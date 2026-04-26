"""Tests for the dashboard /today endpoint."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from backend.models import Activity, Recovery, SleepSession
import backend.routers.dashboard as dashboard_router_module

from .conftest import make_client


@pytest.fixture
async def client(db_and_sessionmaker):
    _, Session = db_and_sessionmaker
    async with make_client(
        dashboard_router_module.router, "/api/dashboard", Session
    ) as c:
        yield c


def _activity(strava_id: int, day: date, suffer_score: int = 10) -> Activity:
    start = datetime.combine(day, datetime.min.time())
    return Activity(
        strava_id=strava_id,
        name=f"Activity {strava_id}",
        sport_type="Run",
        start_date=start,
        start_date_local=start,
        elapsed_time=1800,
        moving_time=1800,
        distance=5000,
        suffer_score=suffer_score,
        classification_type="easy",
        enrichment_status="complete",
    )


async def test_dashboard_today_returns_current_tile_payload(
    client, db, monkeypatch
):
    today = date(2026, 1, 8)
    monkeypatch.setattr(dashboard_router_module, "local_today", lambda: today)

    async def fake_environment(_db):
        return {
            "forecast": {"temp_c": 7.2},
            "air_quality": {"us_aqi": 22},
        }

    monkeypatch.setattr(
        dashboard_router_module, "fetch_environment_today", fake_environment
    )

    db.add_all(
        [
            *[
                _activity(i + 1, today - timedelta(days=i), suffer_score=10)
                for i in range(28)
            ],
            SleepSession(
                source="eight_sleep",
                date=today,
                sleep_score=89,
                total_duration=500,
                deep_sleep=92,
                rem_sleep=118,
                hrv=80,
                avg_hr=49,
            ),
            SleepSession(source="eight_sleep", date=today - timedelta(days=1), hrv=70),
            SleepSession(source="eight_sleep", date=today - timedelta(days=2), hrv=70),
            SleepSession(source="eight_sleep", date=today - timedelta(days=3), hrv=70),
            Recovery(source="whoop", date=today, recovery_score=72, hrv=50),
        ]
    )
    await db.commit()

    response = await client.get("/api/dashboard/today")

    assert response.status_code == 200
    payload = response.json()
    assert payload["as_of"]
    assert payload["sleep"] == {
        "last_night_score": 89,
        "last_night_duration_min": 500,
        "last_night_deep_min": 92,
        "last_night_rem_min": 118,
        "last_night_date": "2026-01-08",
    }
    assert payload["recovery"] == {
        "today_hrv": 80.0,
        "today_resting_hr": 49.0,
        "hrv_baseline_7d": 72.5,
        "hrv_trend": "up",
        "hrv_source": "eight_sleep",
    }
    assert payload["training"] == {
        "yesterday_stress": 10.0,
        "week_to_date_load": 40.0,
        "acwr": 1.0,
        "acwr_band": "optimal",
        "days_since_hard": None,
    }
    assert payload["environment"] == {
        "forecast": {
            "temp_c": 7.2,
            "high_c": None,
            "low_c": None,
            "conditions": None,
            "wind_ms": None,
        },
        "air_quality": {
            "us_aqi": 22,
            "european_aqi": None,
            "pollen": None,
        },
    }


async def test_dashboard_today_tolerates_environment_failure(
    client, db, monkeypatch
):
    today = date(2026, 1, 8)
    monkeypatch.setattr(dashboard_router_module, "local_today", lambda: today)

    async def broken_environment(_db):
        raise RuntimeError("weather down")

    monkeypatch.setattr(
        dashboard_router_module, "fetch_environment_today", broken_environment
    )
    db.add(SleepSession(source="eight_sleep", date=today, sleep_score=80))
    await db.commit()

    response = await client.get("/api/dashboard/today")

    assert response.status_code == 200
    assert response.json()["environment"] is None
