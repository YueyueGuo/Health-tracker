"""Tests for the Apple-Health-side hr_zones helpers.

Two pure functions are under test here:

* ``synthesize_hr_zones_from_samples`` — turns a raw HR sample list
  into the ``zones_data``-shaped 5-bucket distribution we expose to
  the frontend.
* ``derive_hr_samples_from_raw_payload`` — extracts a flat float list
  from a HAE workout ``raw_payload`` (handles both the scalar-``qty``
  and per-time-series shapes that HAE emits depending on the user's
  "Aggregate workout data" toggle).
"""
from __future__ import annotations

from backend.services.hr_zones import (
    derive_hr_samples_from_raw_payload,
    synthesize_hr_zones_from_samples,
)


# ── synthesize_hr_zones_from_samples ───────────────────────────────


def test_synthesize_returns_none_for_empty_samples():
    assert synthesize_hr_zones_from_samples([], max_hr=190) is None


def test_synthesize_returns_none_when_max_hr_unset():
    # max_hr is required; treat 0 / negative as unusable.
    assert synthesize_hr_zones_from_samples([130.0], max_hr=0) is None


def test_synthesize_returns_none_when_all_samples_invalid():
    """All-zero / all-None samples produce no usable buckets."""
    out = synthesize_hr_zones_from_samples([0, 0, None, -1], max_hr=190)
    assert out is None


def test_synthesize_emits_five_buckets_summing_to_sample_count():
    # 60 samples, max_hr=200 → breakpoints at 100/120/140/160/180.
    samples = (
        [90] * 5      # z1 (< 120)
        + [130] * 10  # z2 (120..139)
        + [150] * 20  # z3 (140..159)
        + [170] * 15  # z4 (160..179)
        + [190] * 10  # z5 (≥ 180)
    )
    out = synthesize_hr_zones_from_samples(samples, max_hr=200)
    assert out is not None
    assert out["type"] == "heartrate"
    assert out["sensor_based"] is False
    assert out["points"] == 60
    buckets = out["distribution_buckets"]
    assert len(buckets) == 5
    times = [b["time"] for b in buckets]
    assert sum(times) == 60
    assert times == [5, 10, 20, 15, 10]


def test_synthesize_top_bucket_uses_open_top_sentinel():
    out = synthesize_hr_zones_from_samples([180, 200, 220], max_hr=200)
    assert out is not None
    assert out["distribution_buckets"][-1]["max"] == -1
    # All three samples are ≥ 180 (= 0.9 × 200) → land in z5.
    assert out["distribution_buckets"][-1]["time"] == 3


def test_synthesize_breakpoints_use_max_hr_fractions():
    """Boundaries are 0.5/0.6/0.7/0.8/0.9 of max HR (Strava-style 5-zone)."""
    out = synthesize_hr_zones_from_samples([100], max_hr=200)
    assert out is not None
    buckets = out["distribution_buckets"]
    # Z2 floor at 0.6 × 200 = 120; Z3 floor at 140; Z4 at 160; Z5 at 180.
    assert buckets[1]["min"] == 120
    assert buckets[2]["min"] == 140
    assert buckets[3]["min"] == 160
    assert buckets[4]["min"] == 180


def test_synthesize_lthr_variant_uses_lthr_fractions():
    """LTHR present → breakpoints anchor at 65/81/89/94/99 % of LTHR."""
    out = synthesize_hr_zones_from_samples(
        [120, 140, 160, 170, 175], max_hr=200, lthr=170
    )
    assert out is not None
    buckets = out["distribution_buckets"]
    # 0.65*170 = 110.5 → 111; 0.81 → 138; 0.89 → 151; 0.94 → 160; 0.99 → 168.
    assert buckets[1]["min"] == 138
    assert buckets[2]["min"] == 151
    assert buckets[3]["min"] == 160
    assert buckets[4]["min"] == 168
    # Distribution check: 120 → z1 (<138), 140 → z2, 160 → z4, 170,175 → z5.
    times = [b["time"] for b in buckets]
    assert times == [1, 1, 0, 1, 2]


def test_synthesize_skips_zero_and_none_samples_but_counts_others():
    out = synthesize_hr_zones_from_samples(
        [0, None, 150, "bogus", 160], max_hr=200
    )
    assert out is not None
    # Only the two numeric > 0 samples are counted.
    assert out["points"] == 2
    times = [b["time"] for b in out["distribution_buckets"]]
    assert sum(times) == 2


# ── derive_hr_samples_from_raw_payload ─────────────────────────────


def test_derive_returns_none_for_missing_payload():
    assert derive_hr_samples_from_raw_payload(None) is None
    assert derive_hr_samples_from_raw_payload({}) is None


def test_derive_returns_none_when_field_missing():
    assert derive_hr_samples_from_raw_payload({"name": "Running"}) is None


def test_derive_handles_scalar_qty_shape():
    """HAE "Aggregate workout data = ON" emits a single scalar."""
    payload = {"heartRateData": {"qty": 142, "units": "count/min"}}
    out = derive_hr_samples_from_raw_payload(payload)
    assert out == [142.0]


def test_derive_handles_series_shape():
    """HAE "Aggregate workout data = OFF" emits one entry per sample."""
    payload = {
        "heartRateData": [
            {"date": "2026-05-24 13:14:01 -0400", "qty": 124, "units": "count/min"},
            {"date": "2026-05-24 13:15:01 -0400", "qty": 130, "units": "count/min"},
            {"date": "2026-05-24 13:16:01 -0400", "qty": 145, "units": "count/min"},
        ]
    }
    out = derive_hr_samples_from_raw_payload(payload)
    assert out == [124.0, 130.0, 145.0]


def test_derive_skips_non_dict_entries_and_missing_qty():
    payload = {
        "heartRateData": [
            {"qty": 124},
            None,
            "garbage",
            {"date": "x", "no_qty": True},
            {"qty": "bogus"},
            {"qty": 145},
        ]
    }
    out = derive_hr_samples_from_raw_payload(payload)
    assert out == [124.0, 145.0]


def test_derive_returns_none_when_series_empty():
    out = derive_hr_samples_from_raw_payload({"heartRateData": []})
    assert out is None
