"""Map manual strength sets to HR samples recorded by a linked device workout.

Replaces the legacy timestamp-driven slicer with an HR-stream
**segmentation**-driven approach. The "linked workout HR sets" feature
(``docs/specs/linked-workout-hr-sets.md``) introduces an explicit
``strength_session_links`` row that links one strength session date to
exactly one device workout (Strava activity or Apple Health workout).
Once a link exists, the segmentation service
(``backend/services/strength_segmentation.py``) infers per-set HR
windows from peaks/valleys in the smoothed HR curve, rather than
depending on each set's ``performed_at``.

Invariant: this module is read-only against ``activity_streams`` — the
caller (``strength_link.ensure_streams_loaded``) is responsible for any
on-demand fetch. Keeps ``session_summary`` cheap on the no-link path.

The legacy ``_slice_hr_for_set`` helper is preserved as a private
fallback invoked only when (a) segmentation returned ``flat`` / ``error``
AND (b) every set carries a ``performed_at`` timestamp. Removed in v2.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.models import StrengthSet
from backend.services.strength_segmentation import SegmentationResult

# User taps "Log set" at the end of the set, so we look backward N seconds
# to capture the working HR during the lift. 45s comfortably covers a
# typical compound set (10 reps @ ~3-4s/rep).
#
# LEGACY: only used by the timestamp-driven fallback path below.
DEFAULT_WINDOW_SEC = 45

# Raw streams are ~1Hz so a 60-min workout is ~3600 points — too many for
# Recharts to render smoothly. ~300 keeps the JSON payload small while
# preserving enough resolution to see per-set spikes.
CURVE_TARGET_POINTS = 300


def _slice_hr_for_set(
    performed_at: datetime,
    activity_start: datetime,
    time_stream: list,
    hr_stream: list,
    window_sec: int = DEFAULT_WINDOW_SEC,
) -> tuple[float | None, float | None]:
    """LEGACY: timestamp-driven per-set HR window.

    Kept as a private fallback for sessions where every set has
    ``performed_at`` populated AND segmentation returned ``flat`` /
    ``error``. The segmentation path is the primary mechanism going
    forward — this exists purely for back-compat with sessions logged
    before the link feature shipped.

    Returns ``(avg_hr, max_hr)`` for the window ending at
    ``performed_at``. Returns ``(None, None)`` if the window falls
    outside the stream, or if every HR sample in the window is zero /
    None (dropout).
    """
    if not time_stream or not hr_stream:
        return (None, None)
    if len(time_stream) != len(hr_stream):
        # Strava occasionally returns mismatched lengths for stripped
        # activities — fall back to the shorter length.
        n = min(len(time_stream), len(hr_stream))
        time_stream = time_stream[:n]
        hr_stream = hr_stream[:n]

    offset_sec = (performed_at - activity_start).total_seconds()
    window_start = offset_sec - window_sec
    window_end = offset_sec

    samples: list[float] = []
    for t, hr in zip(time_stream, hr_stream):
        if t is None:
            continue
        if t < window_start:
            continue
        if t > window_end:
            break  # time_stream is monotonically increasing
        if hr is None or hr == 0:
            continue
        samples.append(float(hr))

    if not samples:
        return (None, None)
    return (round(sum(samples) / len(samples), 1), round(max(samples), 1))


def _decimate(
    time_stream: list,
    hr_stream: list,
    target_points: int = CURVE_TARGET_POINTS,
) -> list[list]:
    """Return ``[[offset_sec, bpm], ...]`` with roughly ``target_points`` entries.

    Skips zero/None HR samples (dropouts). When the stream is shorter
    than the target, returns every valid sample.
    """
    if not time_stream or not hr_stream:
        return []
    n = min(len(time_stream), len(hr_stream))
    step = max(1, n // target_points)
    out: list[list] = []
    for i in range(0, n, step):
        t = time_stream[i]
        hr = hr_stream[i]
        if t is None or hr is None or hr == 0:
            continue
        out.append([int(t), round(float(hr), 1)])
    return out


def attach_hr_to_sets(
    sets: list[StrengthSet],
    segmentation: SegmentationResult,
    time_stream: list | None,
    hr_stream: list | None,
    activity_start: datetime | None,
) -> dict[str, Any]:
    """Compute per-set HR + a decimated session-wide curve from a segmentation.

    Pure-ish (reads no DB) — the caller passes the streams already
    loaded by ``strength_link.ensure_streams_loaded``. ``sets`` is the
    session's set list in *logged order*; segments are mapped to sets
    1:1 in that order (set 1 → segment 1, set 2 → segment 2, ...).
    When ``segmentation.detected_count < len(sets)`` the trailing sets
    are left without HR — the UI surfaces this via the segmentation
    status. When ``detected_count > target_count`` the segmentation
    service has already trimmed to the top-N by prominence; we re-check
    here defensively.

    Returns::

        {
          "hr_by_set_id": {set_id: {"avg_hr": 145.2, "max_hr": 160.0}, ...},
          "hr_curve": [[offset_sec, bpm], ...],
          "segment_markers": [{set_number, start_sec, end_sec}, ...],
          "activity_start_iso": "2026-04-21T09:00:00" | None,
        }

    Returns an empty dict when there's nothing useful to attach (no
    stream, segmentation said flat, etc.). The legacy timestamp-driven
    fallback is engaged only when:

    * ``segmentation.status in {"flat", "error"}`` AND
    * every set has a non-null ``performed_at``.
    """
    if not sets:
        return {}

    # Defensive trim — segmentation service is supposed to have already
    # trimmed to target_count, but we keep this guard in case of test
    # fakes or future algorithm variations.
    segments = list(segmentation.segments)
    if len(segments) > len(sets):
        segments = sorted(segments, key=lambda s: s.prominence, reverse=True)[
            : len(sets)
        ]
        segments.sort(key=lambda s: s.peak_sec)

    hr_by_set_id: dict[int, dict[str, float]] = {}
    segment_markers: list[dict[str, Any]] = []
    for set_obj, seg in zip(sets, segments):
        if set_obj.id is None:
            continue
        hr_by_set_id[set_obj.id] = {
            "avg_hr": round(seg.avg_hr, 1),
            "max_hr": round(seg.max_hr, 1),
        }
        segment_markers.append(
            {
                "set_number": set_obj.set_number,
                "start_sec": round(seg.start_sec, 1),
                "end_sec": round(seg.end_sec, 1),
            }
        )

    # Legacy timestamp fallback: only engage when segmentation failed
    # AND every set has a timestamp. Removed in v2.
    fallback_engaged = False
    if (
        not hr_by_set_id
        and segmentation.status in {"flat", "error"}
        and all(s.performed_at is not None for s in sets)
        and activity_start is not None
        and time_stream
        and hr_stream
    ):
        fallback_engaged = True
        for s in sets:
            if s.id is None or s.performed_at is None:
                continue
            avg, mx = _slice_hr_for_set(
                s.performed_at, activity_start, time_stream, hr_stream
            )
            if avg is None:
                continue
            hr_by_set_id[s.id] = {"avg_hr": avg, "max_hr": mx}

    hr_curve = _decimate(time_stream or [], hr_stream or [])
    if not hr_curve and not hr_by_set_id and not fallback_engaged:
        return {}

    return {
        "hr_by_set_id": hr_by_set_id,
        "hr_curve": hr_curve,
        "segment_markers": segment_markers,
        "activity_start_iso": activity_start.isoformat() if activity_start else None,
    }
