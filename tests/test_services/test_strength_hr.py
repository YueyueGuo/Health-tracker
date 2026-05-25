"""Tests for backend.services.strength_hr.

The primary path is now segmentation-driven — :func:`attach_hr_to_sets`
takes a :class:`SegmentationResult` plus the already-loaded streams and
returns per-set HR plus a decimated curve. The legacy timestamp slicer
(:func:`_slice_hr_for_set`) is kept as a private fallback and retains a
focused regression test under the ``_legacy_fallback`` group at the
bottom of the file.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from backend.models import StrengthSet
from backend.services.strength_hr import (
    CURVE_TARGET_POINTS,
    _decimate,
    _slice_hr_for_set,
    attach_hr_to_sets,
)
from backend.services.strength_segmentation import Segment, SegmentationResult


# ── _decimate ──────────────────────────────────────────────────────


def test_decimate_respects_target_points():
    n = 3600  # 1Hz for 60 minutes
    time_stream = list(range(n))
    hr_stream = [140] * n
    out = _decimate(time_stream, hr_stream, target_points=300)
    assert len(out) == 300
    assert out[0] == [0, 140.0]
    assert out[-1][0] == 3588


def test_decimate_skips_dropouts():
    time_stream = list(range(10))
    hr_stream = [0, 140, None, 150, 0, 160, 0, 170, 180, 0]
    out = _decimate(time_stream, hr_stream, target_points=10)
    assert out == [[1, 140.0], [3, 150.0], [5, 160.0], [7, 170.0], [8, 180.0]]


def test_decimate_short_stream_returns_all_valid():
    time_stream = [0, 1, 2]
    hr_stream = [140, 145, 150]
    out = _decimate(time_stream, hr_stream, target_points=CURVE_TARGET_POINTS)
    assert out == [[0, 140.0], [1, 145.0], [2, 150.0]]


def test_decimate_empty():
    assert _decimate([], []) == []
    assert _decimate([0], []) == []


# ── attach_hr_to_sets (segmentation-driven) ────────────────────────


def _seg(
    start: float,
    end: float,
    avg: float,
    mx: float,
    peak: float,
    prom: float = 30.0,
) -> Segment:
    return Segment(
        start_sec=start, end_sec=end, avg_hr=avg, max_hr=mx, peak_sec=peak, prominence=prom
    )


def _set(id_: int, set_number: int = 1) -> StrengthSet:
    return StrengthSet(
        id=id_,
        date=date(2026, 5, 1),
        exercise_name="Squat",
        set_number=set_number,
        reps=5,
        weight_kg=100,
    )


def test_attach_maps_segments_to_sets_in_logged_order():
    sets = [_set(1, 1), _set(2, 2), _set(3, 3)]
    result = SegmentationResult(
        status="ok",
        target_count=3,
        detected_count=3,
        segments=[
            _seg(60, 90, avg=140, mx=160, peak=80),
            _seg(180, 210, avg=150, mx=170, peak=200),
            _seg(300, 330, avg=155, mx=175, peak=320),
        ],
    )
    out = attach_hr_to_sets(
        sets,
        result,
        time_stream=list(range(400)),
        hr_stream=[140] * 400,
        activity_start=datetime(2026, 5, 1, 9, 0, 0),
    )
    assert set(out["hr_by_set_id"].keys()) == {1, 2, 3}
    assert out["hr_by_set_id"][1] == {"avg_hr": 140.0, "max_hr": 160.0}
    assert out["hr_by_set_id"][2] == {"avg_hr": 150.0, "max_hr": 170.0}
    assert out["hr_by_set_id"][3] == {"avg_hr": 155.0, "max_hr": 175.0}
    assert out["activity_start_iso"] == "2026-05-01T09:00:00"
    # Segment markers carry the set_number ordinal.
    assert [m["set_number"] for m in out["segment_markers"]] == [1, 2, 3]


def test_attach_too_few_leaves_trailing_sets_without_hr():
    """``detected_count < target_count`` → trailing sets unmapped."""
    sets = [_set(1, 1), _set(2, 2), _set(3, 3)]
    result = SegmentationResult(
        status="too_few",
        target_count=3,
        detected_count=1,
        segments=[_seg(60, 90, avg=140, mx=160, peak=80)],
    )
    out = attach_hr_to_sets(
        sets, result, time_stream=list(range(100)), hr_stream=[140] * 100,
        activity_start=datetime(2026, 5, 1, 9, 0, 0),
    )
    assert set(out["hr_by_set_id"].keys()) == {1}
    assert 2 not in out["hr_by_set_id"]
    assert 3 not in out["hr_by_set_id"]


def test_attach_too_many_extras_are_trimmed_by_prominence():
    """Defensive guard: if the segmenter handed us more segments than
    sets, the helper drops the lowest-prominence extras and re-sorts by
    time before assigning to sets.
    """
    sets = [_set(1, 1), _set(2, 2)]
    result = SegmentationResult(
        status="too_many",
        target_count=2,
        detected_count=3,
        segments=[
            # Time order: A < B < C. Prominence order: C > A > B.
            _seg(60, 90, avg=140, mx=160, peak=80, prom=20),    # A
            _seg(180, 210, avg=130, mx=145, peak=200, prom=5),  # B (low prom)
            _seg(300, 330, avg=150, mx=170, peak=320, prom=40), # C
        ],
    )
    out = attach_hr_to_sets(
        sets, result, time_stream=list(range(400)), hr_stream=[140] * 400,
        activity_start=datetime(2026, 5, 1, 9, 0, 0),
    )
    # Set 1 maps to the earliest-by-time *surviving* segment (A),
    # set 2 maps to the next (C — B was dropped).
    assert out["hr_by_set_id"][1] == {"avg_hr": 140.0, "max_hr": 160.0}
    assert out["hr_by_set_id"][2] == {"avg_hr": 150.0, "max_hr": 170.0}


def test_attach_flat_with_no_timestamps_returns_curve_only():
    """``flat`` segmentation + no per-set timestamps → no hr_by_set_id,
    but the decimated curve is still emitted if streams are present.
    """
    sets = [_set(1, 1), _set(2, 2)]
    result = SegmentationResult(
        status="flat", target_count=2, detected_count=0, segments=[]
    )
    out = attach_hr_to_sets(
        sets,
        result,
        time_stream=list(range(100)),
        hr_stream=[140] * 100,
        activity_start=datetime(2026, 5, 1, 9, 0, 0),
    )
    assert out["hr_by_set_id"] == {}
    assert out["hr_curve"]


def test_attach_no_streams_returns_empty_dict():
    sets = [_set(1, 1)]
    result = SegmentationResult(
        status="no_stream", target_count=1, detected_count=0, segments=[]
    )
    assert attach_hr_to_sets(
        sets, result, time_stream=None, hr_stream=None, activity_start=None
    ) == {}


def test_attach_no_sets_returns_empty_dict():
    result = SegmentationResult(
        status="ok", target_count=0, detected_count=0, segments=[]
    )
    assert attach_hr_to_sets([], result, [0, 1, 2], [140, 145, 150], None) == {}


# ── _legacy_fallback: timestamp-driven path ────────────────────────


def test_legacy_fallback_engages_when_segmentation_flat_and_all_sets_timestamped():
    """When every set has ``performed_at`` AND segmentation returned
    ``flat``, the legacy timestamp-window slicer fills in per-set HR."""
    start = datetime(2026, 5, 1, 9, 0, 0)
    sets = [
        StrengthSet(
            id=1,
            date=date(2026, 5, 1),
            exercise_name="Squat",
            set_number=1,
            reps=5,
            weight_kg=100,
            performed_at=datetime(2026, 5, 1, 9, 1, 0),  # offset 60s
        ),
    ]
    result = SegmentationResult(
        status="flat", target_count=1, detected_count=0, segments=[]
    )
    time_stream = list(range(100))
    hr_stream = [100 + t for t in time_stream]  # 100..199
    out = attach_hr_to_sets(sets, result, time_stream, hr_stream, start)
    # Legacy slicer engaged → set 1 gets HR.
    assert out
    assert 1 in out["hr_by_set_id"]


def test_legacy_slice_picks_window_ending_at_performed_at():
    """Bare regression coverage of :func:`_slice_hr_for_set`."""
    start = datetime(2026, 4, 21, 9, 0, 0)
    time_stream = list(range(0, 101))
    hr_stream = [100 + t for t in time_stream]
    avg, mx = _slice_hr_for_set(
        performed_at=datetime(2026, 4, 21, 9, 1, 0),
        activity_start=start,
        time_stream=time_stream,
        hr_stream=hr_stream,
        window_sec=45,
    )
    assert mx == 160.0
    assert avg == pytest.approx(137.5, abs=0.1)
