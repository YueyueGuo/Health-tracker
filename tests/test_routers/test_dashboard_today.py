"""Tests for the dashboard /today endpoint."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from backend.models import Activity, Recovery, SleepSession, StrengthSet
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


async def test_dashboard_history_bundles_full_timeline_payload(
    client, db, monkeypatch
):
    today = date(2026, 1, 8)
    monkeypatch.setattr(dashboard_router_module, "local_today", lambda: today)
    monkeypatch.setattr(
        dashboard_router_module,
        "utc_now_naive",
        lambda: datetime.combine(today, datetime.min.time()),
    )

    activity = _activity(101, today - timedelta(days=1), suffer_score=20)
    sleep = SleepSession(
        source="eight_sleep",
        date=today - timedelta(days=1),
        wake_time=datetime(2026, 1, 7, 6, 45),
        sleep_score=82,
        sleep_fitness_score=76,
        total_duration=470,
    )
    strength = StrengthSet(
        date=today - timedelta(days=1),
        exercise_name="Back Squat",
        set_number=1,
        reps=5,
        weight_kg=100,
    )
    db.add_all([activity, sleep, strength])
    await db.commit()

    response = await client.get("/api/dashboard/history?days=30")

    assert response.status_code == 200
    payload = response.json()
    assert payload["activities"][0]["name"] == "Activity 101"
    assert payload["sleep"][0]["id"] == sleep.id
    assert payload["sleep"][0]["wake_time"] == "2026-01-07T06:45:00"
    assert payload["strength"][0]["date"] == "2026-01-07"
    assert payload["strength"][0]["total_sets"] == 1


async def test_dashboard_training_trends_bundles_initial_trends(
    client, db, monkeypatch
):
    today = date(2026, 1, 8)
    monkeypatch.setattr(dashboard_router_module, "local_today", lambda: today)
    monkeypatch.setattr(
        dashboard_router_module,
        "utc_now_naive",
        lambda: datetime.combine(today, datetime.min.time()),
    )

    db.add_all(
        [
            _activity(201, today - timedelta(days=1), suffer_score=20),
            Recovery(source="whoop", date=today - timedelta(days=1), recovery_score=70),
            SleepSession(
                source="eight_sleep",
                date=today - timedelta(days=1),
                sleep_score=82,
            ),
            StrengthSet(
                date=today - timedelta(days=1),
                exercise_name="Back Squat",
                set_number=1,
                reps=5,
                weight_kg=100,
            ),
        ]
    )
    await db.commit()

    response = await client.get("/api/dashboard/training-trends?days=30")

    assert response.status_code == 200
    payload = response.json()
    assert payload["activities"][0]["strava_id"] == 201
    assert payload["recovery"][0]["recovery_score"] == 70.0
    assert payload["sleep"][0]["sleep_score"] == 82.0
    assert payload["strength_sessions"][0]["total_sets"] == 1
    assert payload["strength_exercises"] == ["Back Squat"]
    assert payload["selected_exercise"] == "Back Squat"
    assert isinstance(payload["strength_progression"], list)
