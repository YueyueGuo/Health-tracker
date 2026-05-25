"""Tests for the HAE payload parser + datetime / unit validators."""
from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from backend.services.apple_health_parser import (
    HAEBatch,
    HAEQty,
    HAEWorkout,
    flatten_hae_workout,
    parse_hae_datetime,
)


# ── parse_hae_datetime ──────────────────────────────────────────────


def test_parse_hae_datetime_converts_offset_to_naive_utc():
    # 13:14 EDT (-0400) → 17:14 UTC, then tzinfo stripped.
    dt = parse_hae_datetime("2026-05-24 13:14:00 -0400")
    assert dt == datetime(2026, 5, 24, 17, 14, 0)
    assert dt.tzinfo is None


def test_parse_hae_datetime_utc_zero_offset():
    dt = parse_hae_datetime("2026-05-24 13:14:00 +0000")
    assert dt == datetime(2026, 5, 24, 13, 14, 0)
    assert dt.tzinfo is None


def test_parse_hae_datetime_positive_offset():
    # Sydney winter — +1100. 09:00 there → 22:00 UTC the previous day.
    dt = parse_hae_datetime("2026-07-04 09:00:00 +1100")
    assert dt == datetime(2026, 7, 3, 22, 0, 0)


def test_parse_hae_datetime_rejects_iso_with_T_separator():
    # HAE format is space-separated; anything else explodes loudly.
    with pytest.raises(ValueError, match="unparseable HAE datetime"):
        parse_hae_datetime("2026-05-24T13:14:00-04:00")


def test_parse_hae_datetime_rejects_naive():
    with pytest.raises(ValueError):
        parse_hae_datetime("2026-05-24 13:14:00")


def test_parse_hae_datetime_rejects_none():
    with pytest.raises(ValueError):
        parse_hae_datetime(None)  # type: ignore[arg-type]


# ── HAEQty.as_unit ──────────────────────────────────────────────────


def test_qty_as_unit_returns_value_when_units_match():
    assert HAEQty(qty=42.5, units="kcal").as_unit("kcal") == 42.5


def test_qty_as_unit_accepts_set_of_aliases():
    # HAE writes "kcal" / "Cal" interchangeably; the helper accepts either.
    assert HAEQty(qty=12.0, units="Cal").as_unit({"kcal", "Cal"}) == 12.0


def test_qty_as_unit_raises_on_mismatch():
    with pytest.raises(ValueError, match="unexpected HAE units"):
        HAEQty(qty=1.0, units="km").as_unit("m")


# ── HAEBatch validation ─────────────────────────────────────────────


_SAMPLE_PAYLOAD = {
    "data": {
        "workouts": [
            {
                "id": "B6D2A7F1-3C8E-4A21-9F0B-1E5C7D8A2B3F",
                "name": "Running",
                "start": "2026-05-24 13:14:00 -0400",
                "end": "2026-05-24 14:02:35 -0400",
                "duration": 2915.0,
                "activeEnergyBurned": {"qty": 412.3, "units": "kcal"},
                "totalEnergy": {"qty": 488.0, "units": "kcal"},
                "distance": {"qty": 8043.6, "units": "m"},
                "avgHeartRate": {"qty": 154, "units": "count/min"},
                "maxHeartRate": {"qty": 178, "units": "count/min"},
                "avgSpeed": {"qty": 2.76, "units": "m/s"},
                "maxSpeed": {"qty": 4.21, "units": "m/s"},
                "elevationUp": {"qty": 64.0, "units": "m"},
                "stepCount": {"qty": 7821, "units": "count"},
                "location": "Outdoor",
                "heartRateData": [
                    {"date": "2026-05-24 13:14:01 -0400", "qty": 124, "units": "count/min"},
                ],
                "route": [{"lat": 40.7128, "lon": -74.006}],
            }
        ]
    }
}


def test_batch_parses_full_sample():
    batch = HAEBatch.model_validate(_SAMPLE_PAYLOAD)
    assert len(batch.data.workouts) == 1
    w = batch.data.workouts[0]
    assert w.id.startswith("B6D2A7F1")
    assert w.name == "Running"
    assert w.activeEnergyBurned.qty == 412.3


def test_batch_accepts_empty_workouts_list():
    batch = HAEBatch.model_validate({"data": {"workouts": []}})
    assert batch.data.workouts == []


def test_batch_rejects_missing_required_workout_fields():
    bad = {"data": {"workouts": [{"id": "x"}]}}  # no name/start/end/duration
    with pytest.raises(ValidationError):
        HAEBatch.model_validate(bad)


def test_workout_preserves_extra_series_via_model_dump():
    w = HAEWorkout.model_validate(_SAMPLE_PAYLOAD["data"]["workouts"][0])
    dumped = w.model_dump()
    # heart-rate samples + route ride along in raw_payload territory.
    assert "heartRateData" in dumped
    assert "route" in dumped


# Regression: HAE's "Aggregate workout data = OFF" config sends declared
# metric fields (stepCount, heart rate, etc.) as time-series arrays
# rather than scalar {qty, units} objects. A real prod HAE export hit
# this against PR #46 with all-metric-array shapes and got a 422 for
# every workout. The model must accept either shape.
_SERIES_WORKOUT = {
    "id": "C9F4E3D2-A1B0-4567-89AB-CDEF01234567",
    "name": "Running",
    "start": "2026-05-23 17:00:00 -0400",
    "end": "2026-05-23 18:00:00 -0400",
    "duration": 3600.0,
    "stepCount": [
        {
            "date": "2026-05-23 17:22:14 -0400",
            "qty": 17.92905971749749,
            "source": "Yueyue’s iphone 14",
            "units": "steps",
        },
        {
            "date": "2026-05-23 17:23:14 -0400",
            "qty": 17.07094028250251,
            "source": "Yueyue’s iphone 14",
            "units": "steps",
        },
    ],
}


def test_batch_accepts_series_shape_metric():
    """Series-shaped metrics must validate (was 422 before the fix)."""
    batch = HAEBatch.model_validate({"data": {"workouts": [_SERIES_WORKOUT]}})
    w = batch.data.workouts[0]
    assert isinstance(w.stepCount, list)
    assert len(w.stepCount) == 2
    assert w.stepCount[0]["qty"] == 17.92905971749749


def test_flatten_series_shape_returns_none_scalar_and_preserves_raw():
    """Series-shaped metric → scalar attr is ``None``; series rides in
    ``raw_payload`` so we don't lose data."""
    w = HAEWorkout.model_validate(_SERIES_WORKOUT)
    parsed = flatten_hae_workout(w)
    assert parsed.external_id == _SERIES_WORKOUT["id"]
    # No aggregation today — the series is non-scalar, so the typed
    # scalar attr is None. (Aggregation is a feature, not this fix.)
    assert parsed.active_energy_kcal is None
    # Series data still reaches the DB via raw_payload.
    assert isinstance(parsed.raw_payload["stepCount"], list)
    assert parsed.raw_payload["stepCount"][0]["qty"] == 17.92905971749749


# ── flatten_hae_workout ─────────────────────────────────────────────


def test_flatten_full_workout_maps_all_fields():
    w = HAEWorkout.model_validate(_SAMPLE_PAYLOAD["data"]["workouts"][0])
    parsed = flatten_hae_workout(w)

    assert parsed.external_id == "B6D2A7F1-3C8E-4A21-9F0B-1E5C7D8A2B3F"
    assert parsed.activity_type == "run"
    assert parsed.start_time == datetime(2026, 5, 24, 17, 14, 0)
    assert parsed.end_time == datetime(2026, 5, 24, 18, 2, 35)
    assert parsed.duration_s == 2915
    assert parsed.active_energy_kcal == 412.3
    assert parsed.distance_m == 8043.6
    assert parsed.avg_hr == 154.0
    assert parsed.max_hr == 178.0
    assert parsed.avg_speed_mps == 2.76
    assert parsed.total_elevation_m == 64.0
    assert parsed.raw_payload["heartRateData"][0]["qty"] == 124


def test_flatten_unknown_activity_falls_through_to_other():
    w = HAEWorkout(
        id="x",
        name="Hopscotch",
        start="2026-05-24 12:00:00 +0000",
        end="2026-05-24 12:30:00 +0000",
        duration=1800.0,
    )
    parsed = flatten_hae_workout(w)
    assert parsed.activity_type == "other"


def test_flatten_rejects_truly_unknown_units():
    bad = HAEWorkout(
        id="x",
        name="Running",
        start="2026-05-24 12:00:00 +0000",
        end="2026-05-24 12:30:00 +0000",
        duration=1800.0,
        distance=HAEQty(qty=5.0, units="parsec"),  # not a HAE unit we'd ever see
    )
    with pytest.raises(ValueError, match="unexpected HAE units"):
        flatten_hae_workout(bad)


# Regression: HAE → Settings → Units defaults to imperial on US accounts,
# producing 'mi' for distance, 'mph' for speed, 'ft' for elevation in
# real exports. Pre-fix _opt_qty rejected anything that wasn't the
# canonical SI unit and dropped 6/9 workouts per batch on the floor.
# Each conversion factor is exact (international yard / mile definition).


def test_flatten_converts_imperial_distance_mi_to_m():
    w = HAEWorkout(
        id="x",
        name="Running",
        start="2026-05-24 12:00:00 +0000",
        end="2026-05-24 12:30:00 +0000",
        duration=1800.0,
        distance=HAEQty(qty=3.10685596119, units="mi"),  # ≈5000 m
    )
    parsed = flatten_hae_workout(w)
    assert parsed.distance_m == pytest.approx(5000.0, rel=1e-9)


def test_flatten_converts_metric_distance_km_to_m():
    w = HAEWorkout(
        id="x",
        name="Running",
        start="2026-05-24 12:00:00 +0000",
        end="2026-05-24 12:30:00 +0000",
        duration=1800.0,
        distance=HAEQty(qty=5.0, units="km"),
    )
    parsed = flatten_hae_workout(w)
    assert parsed.distance_m == pytest.approx(5000.0, rel=1e-12)


def test_flatten_converts_imperial_speed_mph_to_mps():
    w = HAEWorkout(
        id="x",
        name="Running",
        start="2026-05-24 12:00:00 +0000",
        end="2026-05-24 12:30:00 +0000",
        duration=1800.0,
        avgSpeed=HAEQty(qty=10.0, units="mph"),  # 10 mph = 4.4704 m/s
    )
    parsed = flatten_hae_workout(w)
    assert parsed.avg_speed_mps == pytest.approx(4.4704, rel=1e-12)


def test_flatten_converts_imperial_elevation_ft_to_m():
    w = HAEWorkout(
        id="x",
        name="Hiking",
        start="2026-05-24 12:00:00 +0000",
        end="2026-05-24 13:00:00 +0000",
        duration=3600.0,
        elevationUp=HAEQty(qty=100.0, units="ft"),  # 100 ft = 30.48 m
    )
    parsed = flatten_hae_workout(w)
    assert parsed.total_elevation_m == pytest.approx(30.48, rel=1e-12)


def test_flatten_accepts_bpm_alias_for_heart_rate():
    w = HAEWorkout(
        id="x",
        name="Running",
        start="2026-05-24 12:00:00 +0000",
        end="2026-05-24 12:30:00 +0000",
        duration=1800.0,
        avgHeartRate=HAEQty(qty=154.0, units="bpm"),
    )
    parsed = flatten_hae_workout(w)
    assert parsed.avg_hr == 154.0


def test_flatten_handles_missing_optional_fields():
    w = HAEWorkout(
        id="x",
        name="Walking",
        start="2026-05-24 12:00:00 +0000",
        end="2026-05-24 12:30:00 +0000",
        duration=1800.0,
    )
    parsed = flatten_hae_workout(w)
    assert parsed.distance_m is None
    assert parsed.active_energy_kcal is None
    assert parsed.avg_hr is None
