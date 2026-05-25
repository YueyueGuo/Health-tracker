"""Tests for backend.services.strength_segmentation.

Pure-function tests over synthetic HR traces. Covers each
``SegmentationResult.status`` outcome and the trimming/clipping
edge cases called out in
``docs/research/strength-hr-segmentation.md``.
"""
from __future__ import annotations

import math

import pytest

from backend.services.strength_segmentation import (
    FLAT_RANGE_BPM,
    PROMINENCE_FLOOR_BPM,
    SegmentationResult,
    segment_hr_stream,
)


def _synth_peaks(
    n_peaks: int,
    *,
    baseline: float = 110.0,
    peak: float = 160.0,
    rest_sec: int = 90,
    set_sec: int = 30,
    sample_hz: int = 1,
) -> tuple[list[int], list[float]]:
    """Build a 1Hz synthetic HR trace with ``n_peaks`` clean Gaussian-ish
    peaks separated by ``rest_sec`` of baseline HR.

    Returns ``(time_stream, hr_stream)``.
    """
    times: list[int] = []
    hrs: list[float] = []
    t = 0
    # Initial baseline rest.
    for _ in range(rest_sec):
        times.append(t)
        hrs.append(baseline)
        t += 1
    for i in range(n_peaks):
        # Set: HR rises to peak then falls.
        center = t + set_sec // 2
        for k in range(set_sec):
            x = t + k
            # Gaussian-ish bell.
            d = (x - center) / (set_sec / 4.0)
            val = baseline + (peak - baseline) * math.exp(-(d * d) / 2.0)
            times.append(x)
            hrs.append(val)
        t += set_sec
        # Rest.
        for k in range(rest_sec):
            times.append(t + k)
            hrs.append(baseline)
        t += rest_sec
    assert len(times) == len(hrs)
    return (times, hrs)


# ── Happy path ─────────────────────────────────────────────────────


def test_clean_5_peak_trace_detects_all_5():
    """Synthetic 5-peak trace → status="ok", 5 segments, chronologically ordered."""
    time_stream, hr_stream = _synth_peaks(5)

    result = segment_hr_stream(time_stream, hr_stream, target_count=5)

    assert isinstance(result, SegmentationResult)
    assert result.status == "ok"
    assert result.detected_count == 5
    assert result.target_count == 5
    assert len(result.segments) == 5
    # Chronological order.
    peak_times = [s.peak_sec for s in result.segments]
    assert peak_times == sorted(peak_times)
    # Each segment's HR average sits above baseline (=110) and ≤ peak (=160).
    for seg in result.segments:
        assert 110.0 < seg.avg_hr <= 160.0
        assert seg.max_hr >= seg.avg_hr
        # Default window is [peak-22, peak+8] but may be clipped.
        assert seg.start_sec < seg.peak_sec <= seg.end_sec


def test_over_target_trace_trims_to_top_n():
    """5 clean peaks with target_count=3 → keeps 3, status="too_many"."""
    time_stream, hr_stream = _synth_peaks(5)

    result = segment_hr_stream(time_stream, hr_stream, target_count=3)

    assert result.status == "too_many"
    assert result.detected_count == 3
    assert result.target_count == 3
    assert len(result.segments) == 3
    # Trimmed peaks should still come out chronologically ordered.
    peak_times = [s.peak_sec for s in result.segments]
    assert peak_times == sorted(peak_times)


def test_under_target_trace_reports_too_few():
    """Trace with 2 clean peaks but target_count=5 → status="too_few"."""
    time_stream, hr_stream = _synth_peaks(2)

    result = segment_hr_stream(time_stream, hr_stream, target_count=5)

    assert result.status == "too_few"
    assert result.detected_count == 2
    assert result.target_count == 5
    assert len(result.segments) == 2


# ── Failure-mode statuses ───────────────────────────────────────────


def test_flat_trace_reports_flat():
    """Smoothed range < FLAT_RANGE_BPM → status="flat", no segments."""
    time_stream = list(range(600))
    # Tiny oscillation well under FLAT_RANGE_BPM (=15).
    hr_stream = [120.0 + (i % 3) for i in time_stream]

    result = segment_hr_stream(time_stream, hr_stream, target_count=4)

    assert result.status == "flat"
    assert result.detected_count == 0
    assert result.segments == []
    # Sanity-check the floor still applies on this trace.
    assert (max(hr_stream) - min(hr_stream)) < FLAT_RANGE_BPM


def test_noisy_trace_with_microspikes_below_prominence_floor_returns_flat():
    """Many micro-peaks all below the prominence floor → no usable peaks → flat.

    The prominence floor (`max(8, 0.4*(max-p20))`) rejects sub-bpm
    jitter on an otherwise narrow trace.
    """
    time_stream = list(range(600))
    # 5-bpm micro-oscillations: range = 5, well below FLAT_RANGE_BPM.
    hr_stream = [120.0 + 2.0 * math.sin(i / 5.0) for i in time_stream]

    result = segment_hr_stream(time_stream, hr_stream, target_count=4)

    assert result.status == "flat"


def test_empty_streams_report_no_stream():
    result = segment_hr_stream([], [], target_count=4)
    assert result.status == "no_stream"
    assert result.detected_count == 0


def test_none_streams_report_no_stream():
    result = segment_hr_stream(None, None, target_count=4)
    assert result.status == "no_stream"


def test_zero_target_short_circuits_to_ok():
    """Session has no logged sets → status="ok", no segments, no work."""
    time_stream, hr_stream = _synth_peaks(3)

    result = segment_hr_stream(time_stream, hr_stream, target_count=0)

    assert result.status == "ok"
    assert result.detected_count == 0
    assert result.target_count == 0
    assert result.segments == []


# ── Robustness ─────────────────────────────────────────────────────


def test_mismatched_stream_lengths_are_truncated():
    """time_stream longer than hr_stream → falls back to shorter length."""
    time_stream, hr_stream = _synth_peaks(3)
    # Drop the tail of hr_stream so the lengths mismatch.
    short_hr = hr_stream[:-50]

    result = segment_hr_stream(time_stream, short_hr, target_count=3)

    # Service tolerated mismatch (didn't crash) and produced *something*.
    # Detection count depends on where the cut lands; just assert status
    # is one of the expected codes.
    assert result.status in {"ok", "too_few", "too_many"}


def test_zero_and_none_samples_are_dropped():
    """0/None HR samples (sensor dropouts) are skipped before smoothing.

    Build a baseline + one peak, sprinkle dropouts, confirm we still
    find the peak.
    """
    time_stream, hr_stream = _synth_peaks(1)
    # Replace every 7th sample with 0 or None.
    contaminated = [
        0 if i % 14 == 0 else (None if i % 14 == 7 else hr) for i, hr in enumerate(hr_stream)
    ]

    result = segment_hr_stream(time_stream, contaminated, target_count=1)

    assert result.status == "ok"
    assert result.detected_count == 1


def test_segment_clipping_keeps_windows_non_overlapping():
    """Adjacent peak windows must not overlap (clip to midpoint)."""
    time_stream, hr_stream = _synth_peaks(3, rest_sec=20)  # tight rest

    result = segment_hr_stream(time_stream, hr_stream, target_count=3)

    if result.detected_count >= 2:
        for prev, nxt in zip(result.segments, result.segments[1:]):
            assert prev.end_sec <= nxt.start_sec + 1e-6


def test_segments_have_valid_summary_fields():
    """Every emitted segment carries float avg_hr/max_hr with max >= avg."""
    time_stream, hr_stream = _synth_peaks(4)

    result = segment_hr_stream(time_stream, hr_stream, target_count=4)

    for seg in result.segments:
        assert seg.avg_hr > 0
        assert seg.max_hr >= seg.avg_hr
        d = seg.to_dict()
        assert set(d.keys()) == {
            "start_sec",
            "end_sec",
            "avg_hr",
            "max_hr",
            "peak_sec",
            "prominence",
        }


def test_prominence_floor_helper():
    """Floor stays at 8bpm when fractional term collapses."""
    # max = p20 → fractional = 0 → floor = 8.
    assert PROMINENCE_FLOOR_BPM(150.0, 150.0) == pytest.approx(8.0)
    # max - p20 = 50 → 0.4*50 = 20 → wins.
    assert PROMINENCE_FLOOR_BPM(150.0, 100.0) == pytest.approx(20.0)


def test_result_to_dict_is_json_safe():
    time_stream, hr_stream = _synth_peaks(2)
    result = segment_hr_stream(time_stream, hr_stream, target_count=2)
    d = result.to_dict()
    assert set(d.keys()) == {
        "status",
        "target_count",
        "detected_count",
        "segments",
    }
    assert isinstance(d["segments"], list)
    for seg in d["segments"]:
        assert isinstance(seg, dict)
