"""Tests for the altitude tier flag in backend.services.classifier.

The altitude flag is orthogonal to workout type: any run/ride at
``base_elevation_m`` above a threshold gets one of
``altitude_low`` / ``altitude_moderate`` / ``altitude_high``.
"""
from __future__ import annotations

from datetime import datetime

from backend.models import Activity, ActivityLap
from backend.services.classifier import _altitude_flag, classify


# ── Pure threshold check ────────────────────────────────────────────


def test_altitude_flag_tier_boundaries():
    assert _altitude_flag(None) is None
    assert _altitude_flag(0.0) is None
    assert _altitude_flag(609.9) is None
    # Inclusive at each boundary \u2014 "starts mattering at" semantics.
    assert _altitude_flag(610) == "altitude_low"
    assert _altitude_flag(1499.9) == "altitude_low"
    assert _altitude_flag(1500) == "altitude_moderate"
    assert _altitude_flag(2499.9) == "altitude_moderate"
    assert _altitude_flag(2500) == "altitude_high"
    assert _altitude_flag(3500) == "altitude_high"


# ── Integration with the run classifier ────────────────────────────


def _run_activity(**kwargs) -> Activity:
    defaults = dict(
        strava_id=1,
        name="Run",
        sport_type="Run",
        start_date=datetime(2026, 4, 1, 12, 0, 0),
        moving_time=40 * 60,        # 40 min
        distance=8000,              # 8 km
        base_elevation_m=None,
    )
    defaults.update(kwargs)
    return Activity(**defaults)


def _lap(idx: int, *, avg_speed=3.0, pace_zone=2, moving_time=300, distance=900) -> ActivityLap:
    return ActivityLap(
        lap_index=idx,
        moving_time=moving_time,
        distance=distance,
        average_speed=avg_speed,
        pace_zone=pace_zone,
    )


def test_run_at_sea_level_no_altitude_flag():
    activity = _run_activity(base_elevation_m=50.0)
    laps = [_lap(i) for i in range(4)]
    result = classify(activity, laps)
    assert result is not None
    assert not any(f.startswith("altitude_") for f in result.flags)


def test_run_at_low_altitude_adds_low_flag():
    activity = _run_activity(base_elevation_m=800.0)
    laps = [_lap(i) for i in range(4)]
    result = classify(activity, laps)
    assert result is not None
    assert "altitude_low" in result.flags


def test_run_at_moderate_altitude_adds_moderate_flag():
    activity = _run_activity(base_elevation_m=2000.0)
    laps = [_lap(i) for i in range(4)]
    result = classify(activity, laps)
    assert "altitude_moderate" in result.flags
    # Doesn't accidentally add the low tier too.
    assert "altitude_low" not in result.flags


def test_run_at_high_altitude_adds_high_flag_only():
    activity = _run_activity(base_elevation_m=3000.0)
    laps = [_lap(i) for i in range(4)]
    result = classify(activity, laps)
    assert "altitude_high" in result.flags
    assert "altitude_low" not in result.flags
    assert "altitude_moderate" not in result.flags


def test_long_run_at_altitude_keeps_both_flags():
    """is_long + altitude_moderate should coexist."""
    activity = _run_activity(
        base_elevation_m=2100.0,
        moving_time=95 * 60,  # triggers is_long
        distance=18_000,
    )
    laps = [_lap(i) for i in range(6)]
    result = classify(activity, laps)
    assert "is_long" in result.flags
    assert "altitude_moderate" in result.flags


# ── Integration with the ride classifier ───────────────────────────


def _ride_activity(**kwargs) -> Activity:
    defaults = dict(
        strava_id=2,
        name="Ride",
        sport_type="Ride",
        start_date=datetime(2026, 4, 1, 12, 0, 0),
        moving_time=60 * 60,
        distance=30_000,
        base_elevation_m=None,
        average_power=180,
        weighted_avg_power=180,
        device_watts=True,
        average_hr=140.0,
    )
    defaults.update(kwargs)
    return Activity(**defaults)


def test_ride_at_altitude_adds_flag():
    activity = _ride_activity(base_elevation_m=1800.0)
    result = classify(activity, [])
    assert result is not None
    assert "altitude_moderate" in result.flags


def test_hilly_ride_at_altitude_keeps_both():
    activity = _ride_activity(
        base_elevation_m=2700.0,
        total_elevation=700,        # 700 m / 30 km = ~23 m/km (hilly)
        distance=30_000,
    )
    result = classify(activity, [])
    assert "is_hilly" in result.flags
    assert "altitude_high" in result.flags
