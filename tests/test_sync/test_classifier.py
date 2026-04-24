"""Tests for backend.services.classifier.

Covers the rule-based branches for runs and rides, flag orthogonality,
artifact-lap filtering, auto-split detection, and persistence.

Altitude tier coverage lives in ``test_classifier_altitude.py``.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.models import Activity, ActivityLap
from backend.services import classifier as classifier_mod
from backend.services.classifier import (
    Classification,
    _detect_auto_splits,
    classify,
    classify_and_persist,
    describe,
    dump,
)


# ── Fixtures / builders ──────────────────────────────────────────────


def _run(**kwargs) -> Activity:
    defaults = dict(
        strava_id=1,
        name="Run",
        sport_type="Run",
        start_date=datetime(2026, 4, 1, 12, 0, 0),
        moving_time=40 * 60,
        distance=8_000,
        base_elevation_m=None,
    )
    defaults.update(kwargs)
    return Activity(**defaults)


def _ride(**kwargs) -> Activity:
    defaults = dict(
        strava_id=2,
        name="Ride",
        sport_type="Ride",
        start_date=datetime(2026, 4, 1, 12, 0, 0),
        moving_time=60 * 60,
        distance=30_000,
        base_elevation_m=None,
    )
    defaults.update(kwargs)
    return Activity(**defaults)


def _lap(
    idx: int,
    *,
    avg_speed: float = 3.0,
    pace_zone: int | None = 2,
    moving_time: int = 300,
    distance: float = 900.0,
    hr: float | None = None,
) -> ActivityLap:
    return ActivityLap(
        lap_index=idx,
        moving_time=moving_time,
        distance=distance,
        average_speed=avg_speed,
        pace_zone=pace_zone,
        average_heartrate=hr,
    )


# ── Sport dispatch ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "sport", ["WeightTraining", "Yoga", "Swim", "Hike", "", None]
)
def test_classify_returns_none_for_unsupported_sports(sport):
    activity = Activity(
        strava_id=9,
        name="Session",
        sport_type=sport,
        start_date=datetime(2026, 4, 1),
    )
    assert classify(activity, []) is None


@pytest.mark.parametrize("sport", ["Run", "TrailRun", "VirtualRun"])
def test_run_dispatch_includes_trail_and_virtual(sport):
    """Anything with 'run' in the sport_type routes to the run classifier."""
    activity = _run(sport_type=sport)
    laps = [_lap(i) for i in range(4)]
    result = classify(activity, laps)
    assert result is not None
    assert result.type in {"easy", "tempo", "intervals", "race"}


@pytest.mark.parametrize("sport", ["Ride", "VirtualRide", "EBikeRide"])
def test_ride_dispatch_includes_virtual_and_ebike(sport):
    activity = _ride(sport_type=sport, average_hr=140.0)
    result = classify(activity, [])
    assert result is not None
    assert result.type in {"recovery", "endurance", "tempo", "mixed", "race"}


# ── Run: race short-circuit ──────────────────────────────────────────


def test_run_race_via_workout_type_trumps_heuristics():
    """workout_type=1 (Strava race marker) short-circuits to race even
    when the lap shape would otherwise say intervals."""
    activity = _run(workout_type=1)
    # Lap shape that would otherwise classify as intervals.
    laps = [
        _lap(0, avg_speed=3.0, pace_zone=2),
        _lap(1, avg_speed=5.0, pace_zone=5),
        _lap(2, avg_speed=3.0, pace_zone=2),
        _lap(3, avg_speed=5.0, pace_zone=5),
    ]
    result = classify(activity, laps)
    assert result.type == "race"
    assert result.confidence == 0.95


# ── Run: intervals ──────────────────────────────────────────────────


def test_run_intervals_primary_signal():
    """Max pace zone >= 4, not auto-splits, >=3 usable laps → intervals."""
    activity = _run()
    laps = [
        _lap(0, avg_speed=2.8, pace_zone=2, distance=800),
        _lap(1, avg_speed=5.0, pace_zone=5, distance=400, moving_time=80),
        _lap(2, avg_speed=2.8, pace_zone=2, distance=800),
        _lap(3, avg_speed=5.0, pace_zone=5, distance=400, moving_time=80),
        _lap(4, avg_speed=2.8, pace_zone=2, distance=800),
    ]
    result = classify(activity, laps)
    assert result.type == "intervals"
    assert result.confidence == 0.9


def test_run_intervals_fallback_via_cv_and_zone3():
    """High speed CV + at least one zone-3 lap also trips intervals at
    lower confidence, even without a zone-4+ lap."""
    activity = _run()
    # max_pace_zone=3 (disqualifies primary branch) but speed_cv >= 0.15
    laps = [
        _lap(0, avg_speed=2.5, pace_zone=2),
        _lap(1, avg_speed=3.8, pace_zone=3),
        _lap(2, avg_speed=2.5, pace_zone=2),
        _lap(3, avg_speed=3.8, pace_zone=3),
    ]
    result = classify(activity, laps)
    assert result.type == "intervals"
    assert result.confidence == 0.7


def test_run_walk_with_high_cv_but_only_zone1_is_not_intervals():
    """A stop-and-go walk has high speed CV but never leaves zone 1 —
    the ``max_pace_zone >= 3`` gate on the CV-fallback stops it being
    miscalled as intervals. Bug-regression test for the classifier
    tuning noted in CLAUDE.md."""
    activity = _run(moving_time=30 * 60, distance=3_000)
    laps = [
        _lap(0, avg_speed=1.2, pace_zone=1),
        _lap(1, avg_speed=0.3, pace_zone=1),
        _lap(2, avg_speed=1.5, pace_zone=1),
        _lap(3, avg_speed=0.4, pace_zone=1),
    ]
    result = classify(activity, laps)
    assert result.type != "intervals"


def test_run_intervals_rejected_when_auto_splits():
    """Auto-mile splits with a slightly faster final split should NOT be
    called intervals — the primary branch is blocked by the auto-splits
    gate, and the CV fallback is blocked by the low speed variance."""
    activity = _run(distance=10_000, moving_time=50 * 60)
    laps = [
        _lap(0, avg_speed=3.4, pace_zone=2, distance=1609.34, moving_time=475),
        _lap(1, avg_speed=3.4, pace_zone=2, distance=1609.34, moving_time=475),
        _lap(2, avg_speed=3.4, pace_zone=2, distance=1609.34, moving_time=475),
        _lap(3, avg_speed=4.0, pace_zone=4, distance=800.0, moving_time=200),
    ]
    result = classify(activity, laps)
    assert result.type != "intervals"


# ── Run: tempo vs easy ──────────────────────────────────────────────


def test_run_tempo_requires_steady_elevated_pace():
    """Low CV + mean pace zone >= 3 → tempo."""
    activity = _run()
    laps = [
        _lap(0, avg_speed=3.6, pace_zone=3),
        _lap(1, avg_speed=3.6, pace_zone=3),
        _lap(2, avg_speed=3.6, pace_zone=3),
        _lap(3, avg_speed=3.6, pace_zone=3),
    ]
    result = classify(activity, laps)
    assert result.type == "tempo"
    assert result.confidence == 0.85


def test_run_easy_when_steady_and_low_zone():
    activity = _run()
    laps = [
        _lap(0, avg_speed=2.8, pace_zone=2),
        _lap(1, avg_speed=2.8, pace_zone=2),
        _lap(2, avg_speed=2.8, pace_zone=2),
        _lap(3, avg_speed=2.8, pace_zone=2),
    ]
    result = classify(activity, laps)
    assert result.type == "easy"
    assert result.confidence == 0.85


def test_run_unknown_shape_falls_through_to_low_confidence_easy():
    """No usable laps → all features are None → falls through."""
    activity = _run()
    result = classify(activity, [])
    assert result.type == "easy"
    assert result.confidence == 0.4


# ── Run: artifact filtering ─────────────────────────────────────────


def test_artifact_laps_dropped_from_feature_calculation():
    """Laps with both moving_time < 30s AND distance < 50m are filtered.

    Here we add a 10s / 5m artifact lap alongside four real laps; the
    artifact's wildly different speed should not pollute speed_cv, so
    the result should still be 'easy' (steady).
    """
    activity = _run()
    real = [_lap(i, avg_speed=2.8, pace_zone=2) for i in range(4)]
    artifact = _lap(99, avg_speed=0.1, pace_zone=1, moving_time=10, distance=5.0)
    result = classify(activity, real + [artifact])
    assert result.type == "easy"
    assert result.features["usable_lap_count"] == 4


def test_short_lap_kept_when_distance_is_long_enough():
    """OR semantics — a lap with short moving_time but long distance
    (e.g. a high-speed surge) is NOT an artifact and should be kept."""
    activity = _run()
    laps = [
        _lap(0, avg_speed=2.8, pace_zone=2),
        _lap(1, avg_speed=6.0, pace_zone=5, moving_time=10, distance=60),
        _lap(2, avg_speed=2.8, pace_zone=2),
        _lap(3, avg_speed=2.8, pace_zone=2),
    ]
    result = classify(activity, laps)
    assert result.features["usable_lap_count"] == 4


# ── Run flags ───────────────────────────────────────────────────────


def test_run_is_long_by_duration():
    activity = _run(moving_time=95 * 60, distance=12_000)
    laps = [_lap(i) for i in range(4)]
    assert "is_long" in classify(activity, laps).flags


def test_run_is_long_by_distance():
    activity = _run(moving_time=60 * 60, distance=16_500)
    laps = [_lap(i) for i in range(4)]
    assert "is_long" in classify(activity, laps).flags


def test_run_has_speed_component_only_on_easy_runs():
    """Easy run with a zone-4 lap gets `has_speed_component` but stays
    easy. Auto-mile splits block the primary intervals branch; low
    speed variance blocks the CV fallback; mean pace zone < 3 blocks
    tempo — so the run falls through to easy with the flag set."""
    activity = _run(distance=10_000, moving_time=50 * 60)
    laps = [
        _lap(0, avg_speed=3.2, pace_zone=2, distance=1609.34, moving_time=500),
        _lap(1, avg_speed=3.2, pace_zone=2, distance=1609.34, moving_time=500),
        _lap(2, avg_speed=3.2, pace_zone=2, distance=1609.34, moving_time=500),
        _lap(3, avg_speed=3.4, pace_zone=4, distance=800.0, moving_time=235),
    ]
    result = classify(activity, laps)
    assert result.type == "easy"
    assert "has_speed_component" in result.flags


def test_run_no_speed_component_on_tempo():
    """Tempo runs never get has_speed_component, only easy runs do."""
    activity = _run()
    laps = [_lap(i, avg_speed=3.6, pace_zone=3) for i in range(4)]
    result = classify(activity, laps)
    assert result.type == "tempo"
    assert "has_speed_component" not in result.flags


def test_run_has_warmup_cooldown_detected():
    """First and last laps noticeably slower than the middle."""
    activity = _run()
    laps = [
        _lap(0, avg_speed=2.4, pace_zone=1),    # slow warmup
        _lap(1, avg_speed=3.4, pace_zone=3),
        _lap(2, avg_speed=3.4, pace_zone=3),
        _lap(3, avg_speed=3.4, pace_zone=3),
        _lap(4, avg_speed=2.3, pace_zone=1),    # slow cooldown
    ]
    result = classify(activity, laps)
    assert "has_warmup_cooldown" in result.flags


def test_run_warmup_cooldown_not_flagged_without_both_ends_slow():
    activity = _run()
    laps = [
        _lap(0, avg_speed=3.3),
        _lap(1, avg_speed=3.4),
        _lap(2, avg_speed=3.4),
        _lap(3, avg_speed=3.3),
    ]
    result = classify(activity, laps)
    assert "has_warmup_cooldown" not in result.flags


# ── Auto-split detection (pure) ─────────────────────────────────────


def test_detect_auto_splits_mile_laps():
    assert _detect_auto_splits([1609.34, 1609.34, 1609.34, 900.0]) is True


def test_detect_auto_splits_km_laps():
    assert _detect_auto_splits([1000.0, 1000.0, 1000.0, 250.0]) is True


def test_detect_auto_splits_false_for_mixed_distances():
    assert _detect_auto_splits([1609.34, 1200.0, 1609.34, 900.0]) is False


def test_detect_auto_splits_false_with_fewer_than_two_laps():
    assert _detect_auto_splits([1609.34]) is False
    assert _detect_auto_splits([]) is False


# ── Ride: race + recovery ───────────────────────────────────────────


def test_ride_race_via_workout_type():
    activity = _ride(workout_type=11, average_power=250.0, device_watts=True)
    result = classify(activity, [])
    assert result.type == "race"
    assert result.confidence == 0.95


def test_ride_recovery_short_no_power():
    """Short ride with no power meter → recovery (spin-down case)."""
    activity = _ride(
        moving_time=30 * 60,
        distance=15_000,
        average_power=None,
        device_watts=None,
    )
    result = classify(activity, [])
    assert result.type == "recovery"


def test_ride_recovery_short_low_power():
    """Short ride WITH power meter but avg < 100W → recovery."""
    activity = _ride(
        moving_time=30 * 60,
        distance=12_000,
        average_power=85.0,
        weighted_avg_power=90.0,
        device_watts=True,
    )
    result = classify(activity, [])
    assert result.type == "recovery"


def test_ride_not_recovery_when_short_but_high_power():
    """Short + high power → NOT recovery; should fall through to
    endurance/mixed/tempo depending on VI."""
    activity = _ride(
        moving_time=30 * 60,
        distance=15_000,
        average_power=200.0,
        weighted_avg_power=205.0,  # VI ~1.025
        device_watts=True,
        average_hr=150.0,
    )
    result = classify(activity, [])
    assert result.type != "recovery"


# ── Ride: mixed / tempo / endurance ─────────────────────────────────


def test_ride_mixed_via_high_vi():
    """VI >= 1.10 → mixed."""
    activity = _ride(
        average_power=200.0,
        weighted_avg_power=230.0,   # VI = 1.15
        device_watts=True,
        average_hr=155.0,
    )
    result = classify(activity, [])
    assert result.type == "mixed"
    assert result.confidence == 0.75


def test_ride_tempo_requires_power_signal():
    """VI in tempo band AND avg_power >= 180 → tempo."""
    activity = _ride(
        average_power=200.0,
        weighted_avg_power=210.0,  # VI ~ 1.05
        device_watts=True,
        average_hr=150.0,
    )
    result = classify(activity, [])
    assert result.type == "tempo"
    assert result.confidence == 0.7


def test_ride_endurance_default_with_signal():
    """VI in tempo band but low avg_power → endurance (not tempo)."""
    activity = _ride(
        average_power=140.0,
        weighted_avg_power=145.0,
        device_watts=True,
        average_hr=130.0,
    )
    result = classify(activity, [])
    assert result.type == "endurance"
    assert result.confidence == 0.7


def test_ride_endurance_low_confidence_without_signals():
    """No power, no HR → endurance at 0.4 confidence."""
    activity = _ride(
        average_power=None,
        weighted_avg_power=None,
        device_watts=None,
        average_hr=None,
        moving_time=75 * 60,
    )
    result = classify(activity, [])
    assert result.type == "endurance"
    assert result.confidence == 0.4


# ── Ride flags ──────────────────────────────────────────────────────


def test_ride_is_long_by_duration():
    activity = _ride(
        moving_time=3 * 3600,
        distance=40_000,
        average_power=160.0,
        weighted_avg_power=165.0,
        device_watts=True,
    )
    result = classify(activity, [])
    assert "is_long" in result.flags


def test_ride_is_long_by_distance():
    activity = _ride(
        moving_time=90 * 60,
        distance=55_000,
        average_power=160.0,
        weighted_avg_power=165.0,
        device_watts=True,
    )
    result = classify(activity, [])
    assert "is_long" in result.flags


def test_ride_is_hilly_threshold():
    """Elevation gain / distance >= 15 m/km → is_hilly."""
    activity = _ride(
        distance=30_000,
        total_elevation=500.0,       # ~16.7 m/km
        average_power=180.0,
        weighted_avg_power=185.0,
        device_watts=True,
    )
    result = classify(activity, [])
    assert "is_hilly" in result.flags


def test_ride_flat_not_hilly():
    activity = _ride(
        distance=30_000,
        total_elevation=200.0,       # ~6.7 m/km
        average_power=180.0,
        weighted_avg_power=185.0,
        device_watts=True,
    )
    result = classify(activity, [])
    assert "is_hilly" not in result.flags


# ── Persistence / helpers ───────────────────────────────────────────


def test_classify_and_persist_mutates_activity():
    activity = _run()
    laps = [_lap(i, avg_speed=2.8, pace_zone=2) for i in range(4)]
    before = activity.classification_type
    result = classify_and_persist(activity, laps)
    assert before is None
    assert result is not None
    assert activity.classification_type == result.type
    assert activity.classification_flags == result.flags
    assert activity.classified_at is not None


def test_classify_and_persist_noop_for_unsupported_sport():
    activity = Activity(
        strava_id=77,
        name="Yoga",
        sport_type="Yoga",
        start_date=datetime(2026, 4, 1),
    )
    result = classify_and_persist(activity, [])
    assert result is None
    assert activity.classification_type is None
    assert activity.classified_at is None


def test_describe_and_dump_round_trip():
    c = Classification(type="tempo", flags=["is_long"], confidence=0.85)
    text = describe(c)
    assert "tempo" in text and "is_long" in text and "0.85" in text

    d = dump(c)
    assert d["type"] == "tempo"
    assert d["flags"] == ["is_long"]
    assert d["confidence"] == 0.85


def test_classification_to_persist_shape(monkeypatch):
    classified_at = datetime(2026, 4, 24, 13, 14, 15, tzinfo=timezone.utc)
    monkeypatch.setattr(classifier_mod, "utc_now", lambda: classified_at)

    c = Classification(type="easy", flags=["is_long"], confidence=0.8)
    payload = c.to_persist()
    assert payload["classification_type"] == "easy"
    assert payload["classification_flags"] == ["is_long"]
    assert payload["classified_at"] == classified_at
