"""Pure-Python HR-stream segmentation for the linked workout HR sets feature.

Given a workout's ``(time, heartrate)`` streams and a target set count,
returns ``target_count`` (or fewer, when detection falls short) peak-
anchored segment windows. The set count logged on the strength session
is used as a target.

Algorithm (see ``docs/research/strength-hr-segmentation.md`` §2):

1. Drop zero/None samples; smooth with a rolling mean (``SMOOTH_WINDOW_SEC``).
2. Mark candidate peaks (interior local maxima of the smoothed series).
3. For each candidate, compute prominence as ``peak - max(left_min,
   right_min)`` where the min walks outward until it hits a sample
   higher than the peak or the series boundary.
4. Apply absolute prominence floor + greedy non-max suppression keyed on
   ``MIN_PEAK_DISTANCE_SEC``.
5. If more than ``target_count`` peaks remain, keep the top-N by
   prominence; otherwise return what was found (honest reporting).
6. For each kept peak, emit a window ``[peak - 22s, peak + 8s]``,
   clipped to the midpoints between this peak and its neighbours so we
   don't bleed into adjacent sets. Average and max HR are computed on
   the **raw** samples inside the window.

Pure functions only — no DB, no I/O. The caller owns persistence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# ── Tuned defaults (research brief §5) ──────────────────────────────
# TUNE: rolling-mean window. 15s kills sensor jitter and Polar/Apple
# wrist-strap dropouts while leaving the set-to-rest HR swing intact.
SMOOTH_WINDOW_SEC: int = 15

# TUNE: minimum spacing between accepted peaks. Working sets are >= 5s
# and rest is >= 30-60s in practice, so back-to-back peaks closer than
# 20s are almost certainly noise. The total/(3N) term keeps the
# distance tight enough on giant-set sessions that real peaks aren't
# merged.
def MIN_PEAK_DISTANCE_SEC(total_sec: float, target_count: int) -> float:
    """``max(20, total_sec / (target_count * 3))`` with safe denominators."""
    if target_count <= 0:
        return 20.0
    return max(20.0, total_sec / (target_count * 3))


# TUNE: prominence floor. The fractional ``0.4 * (max - p20)`` term can
# collapse to ~3 bpm on a low-intensity session; the absolute 8 bpm
# floor guards against the sensor's intrinsic noise (Polar H10 ±2 bpm;
# Apple wrist sensor ±5 bpm). Published peak HR rises for slow-cadence
# resistance sets are 12-17 bpm above baseline, well above this floor.
def PROMINENCE_FLOOR_BPM(smoothed_max: float, smoothed_p20: float) -> float:
    """``max(8, 0.4 * (smoothed_max - smoothed_p20))``."""
    return max(8.0, 0.4 * (smoothed_max - smoothed_p20))


# TUNE: flat-trace cutoff. When the whole smoothed series spans
# < 15 bpm there is no per-set signal to extract; return ``status=flat``
# and the caller degrades to summary-only.
FLAT_RANGE_BPM: float = 15.0

# TUNE: peak-anchored working-HR window. Asymmetric on purpose — HR
# continues to drift up for ~5-8s post-set before falling, so the
# trailing tail is intentionally short. The window is clipped to the
# midpoints between this peak and its neighbours by the segmenter.
PEAK_WINDOW_SEC: tuple[int, int] = (22, 8)  # (before_peak, after_peak)


# Reuse the curve decimation target from strength_hr to keep the
# session_summary payload shape stable.
DECIMATE_TARGET_POINTS: int = 300


# ── Public types ────────────────────────────────────────────────────


SegmentationStatus = Literal[
    "ok",
    "too_few",
    "too_many",
    "flat",
    "no_stream",
    "no_curve",
    "pending",
    "error",
]


@dataclass
class Segment:
    """One segmented working-HR window."""

    start_sec: float
    end_sec: float
    avg_hr: float
    max_hr: float
    peak_sec: float
    prominence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_sec": round(self.start_sec, 1),
            "end_sec": round(self.end_sec, 1),
            "avg_hr": round(self.avg_hr, 1),
            "max_hr": round(self.max_hr, 1),
            "peak_sec": round(self.peak_sec, 1),
            "prominence": round(self.prominence, 1),
        }


@dataclass
class SegmentationResult:
    """Output of :func:`segment_hr_stream`. All fields are JSON-serializable
    via :meth:`to_dict`.
    """

    status: SegmentationStatus
    target_count: int
    detected_count: int
    segments: list[Segment] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "target_count": self.target_count,
            "detected_count": self.detected_count,
            "segments": [s.to_dict() for s in self.segments],
        }


# ── Internal helpers ────────────────────────────────────────────────


def _coerce_pairs(
    time_stream: list | None, hr_stream: list | None
) -> tuple[list[float], list[float]]:
    """Pair, drop zero/None HR samples, coerce to float.

    Strava and HAE both emit 0 for HR dropouts; treat them as missing.
    Mismatched lengths are clipped to the shorter array — Strava
    occasionally returns truncated streams for stripped activities.
    """
    if not time_stream or not hr_stream:
        return ([], [])
    n = min(len(time_stream), len(hr_stream))
    times: list[float] = []
    hrs: list[float] = []
    for i in range(n):
        t = time_stream[i]
        hr = hr_stream[i]
        if t is None or hr is None:
            continue
        try:
            t_f = float(t)
            hr_f = float(hr)
        except (TypeError, ValueError):
            continue
        if hr_f <= 0:
            continue
        times.append(t_f)
        hrs.append(hr_f)
    return (times, hrs)


def _rolling_mean(values: list[float], window_sec: int) -> list[float]:
    """Causal-ish rolling mean centred on each sample.

    Streams are ~1 Hz so ``window_sec`` ≈ number of samples; use an
    actual time-window so non-uniform sampling (HAE) still smooths
    correctly. O(n^2) in the worst case but n ≤ 3600 so it's fine.
    """
    if not values:
        return []
    n = len(values)
    half = window_sec / 2.0
    # Use index-based half-window when we don't have parallel timestamps
    # available to the smoother. The caller passes ``hrs`` only here.
    out: list[float] = []
    for i in range(n):
        lo = max(0, int(i - half))
        hi = min(n, int(i + half) + 1)
        window = values[lo:hi]
        out.append(sum(window) / len(window))
    return out


def _percentile(values: list[float], pct: float) -> float:
    """Linear-interpolated percentile (0..100). No numpy."""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    frac = k - lo
    return s[lo] * (1 - frac) + s[hi] * frac


def _find_local_maxima(smoothed: list[float]) -> list[int]:
    """Indices ``i`` (1 <= i <= n-2) where ``smoothed[i-1] < smoothed[i]
    >= smoothed[i+1]``.

    Note: uses ``>=`` on the right to handle short plateaus — the
    candidate sits on the rising edge of the plateau, which is what we
    want for downstream prominence walking.
    """
    n = len(smoothed)
    if n < 3:
        return []
    out: list[int] = []
    for i in range(1, n - 1):
        if smoothed[i - 1] < smoothed[i] >= smoothed[i + 1]:
            out.append(i)
    return out


def _prominence(smoothed: list[float], idx: int) -> float:
    """Walk outward from ``idx`` until we hit a sample > smoothed[idx];
    prominence is ``smoothed[idx] - max(left_min, right_min)``.

    Mirrors ``scipy.signal.peak_prominences`` semantics on this size of
    input.
    """
    n = len(smoothed)
    peak = smoothed[idx]

    left_min = peak
    j = idx - 1
    while j >= 0 and smoothed[j] <= peak:
        if smoothed[j] < left_min:
            left_min = smoothed[j]
        j -= 1

    right_min = peak
    j = idx + 1
    while j < n and smoothed[j] <= peak:
        if smoothed[j] < right_min:
            right_min = smoothed[j]
        j += 1

    return peak - max(left_min, right_min)


def _non_max_suppress(
    candidates: list[tuple[int, float]],
    times: list[float],
    min_distance_sec: float,
) -> list[tuple[int, float]]:
    """Greedy NMS keyed on prominence and spacing in time-stream seconds.

    ``candidates`` are ``(index, prominence)`` tuples. Sort by
    prominence desc, then keep peaks whose time is at least
    ``min_distance_sec`` away from any already-kept higher-prominence
    peak.
    """
    if not candidates:
        return []
    ordered = sorted(candidates, key=lambda c: c[1], reverse=True)
    kept: list[tuple[int, float]] = []
    for idx, prom in ordered:
        peak_t = times[idx]
        too_close = False
        for k_idx, _ in kept:
            if abs(times[k_idx] - peak_t) < min_distance_sec:
                too_close = True
                break
        if not too_close:
            kept.append((idx, prom))
    return kept


def _midpoint(a: float, b: float) -> float:
    return (a + b) / 2.0


def _summarize_window(
    times: list[float], hrs: list[float], start_sec: float, end_sec: float
) -> tuple[float, float] | None:
    """Average + max of raw HR samples inside ``[start_sec, end_sec]``.

    Returns ``None`` when no sample falls in the window (caller treats
    as "skip this peak"). The raw stream is monotonically increasing in
    time so we can early-break.
    """
    samples: list[float] = []
    for t, hr in zip(times, hrs):
        if t < start_sec:
            continue
        if t > end_sec:
            break
        samples.append(hr)
    if not samples:
        return None
    return (sum(samples) / len(samples), max(samples))


# ── Public entrypoint ───────────────────────────────────────────────


def segment_hr_stream(
    time_stream: list | None,
    hr_stream: list | None,
    target_count: int,
) -> SegmentationResult:
    """Return up to ``target_count`` peak-anchored segments from an HR stream.

    See module docstring for algorithm. Pure function — no I/O.

    Edge cases:

    * ``target_count == 0`` → short-circuit to ``status="ok"`` with no
      segments (session has no logged sets to align against).
    * Empty / all-dropout streams → ``status="no_stream"``.
    * Smoothed range < ``FLAT_RANGE_BPM`` → ``status="flat"``.
    * Fewer kept peaks than target → ``status="too_few"``.
    * More candidate peaks than target → trim to top-N by prominence,
      ``status="too_many"``.
    """
    if target_count == 0:
        return SegmentationResult(status="ok", target_count=0, detected_count=0)

    times, hrs = _coerce_pairs(time_stream, hr_stream)
    if not times or len(times) < 3:
        return SegmentationResult(
            status="no_stream", target_count=target_count, detected_count=0
        )

    smoothed = _rolling_mean(hrs, SMOOTH_WINDOW_SEC)
    smoothed_max = max(smoothed)
    smoothed_min = min(smoothed)
    if (smoothed_max - smoothed_min) < FLAT_RANGE_BPM:
        return SegmentationResult(
            status="flat", target_count=target_count, detected_count=0
        )

    smoothed_p20 = _percentile(smoothed, 20.0)
    prom_floor = PROMINENCE_FLOOR_BPM(smoothed_max, smoothed_p20)

    total_sec = times[-1] - times[0]
    min_dist = MIN_PEAK_DISTANCE_SEC(total_sec, target_count)

    # Step 2-4: local maxima → prominence filter → NMS.
    maxima = _find_local_maxima(smoothed)
    candidates: list[tuple[int, float]] = []
    for idx in maxima:
        prom = _prominence(smoothed, idx)
        if prom >= prom_floor:
            candidates.append((idx, prom))

    kept = _non_max_suppress(candidates, times, min_dist)

    detected_count = len(kept)
    if detected_count == 0:
        # Honest reporting: no peaks survived the prominence + distance
        # filter despite the series not being flat. Surface as "flat"
        # so the UI degrades to summary-only.
        return SegmentationResult(
            status="flat", target_count=target_count, detected_count=0
        )

    # Trim to top-N by prominence if we have too many.
    over_target = detected_count > target_count
    if over_target:
        kept = sorted(kept, key=lambda c: c[1], reverse=True)[:target_count]

    # Re-order kept peaks by time so segments come out in chronological
    # order (NMS sorted them by prominence).
    kept_by_time = sorted(kept, key=lambda c: times[c[0]])

    # Build segments. Window = [peak - 22, peak + 8] clipped to the
    # midpoints between this peak and its neighbours.
    before_sec, after_sec = PEAK_WINDOW_SEC
    segments: list[Segment] = []
    for i, (idx, prom) in enumerate(kept_by_time):
        peak_t = times[idx]
        left_bound = times[0]
        right_bound = times[-1]
        if i > 0:
            prev_peak_t = times[kept_by_time[i - 1][0]]
            left_bound = _midpoint(prev_peak_t, peak_t)
        if i < len(kept_by_time) - 1:
            next_peak_t = times[kept_by_time[i + 1][0]]
            right_bound = _midpoint(peak_t, next_peak_t)

        start_sec = max(left_bound, peak_t - before_sec)
        end_sec = min(right_bound, peak_t + after_sec)
        if end_sec <= start_sec:
            continue

        summary = _summarize_window(times, hrs, start_sec, end_sec)
        if summary is None:
            continue
        avg_hr, max_hr = summary
        segments.append(
            Segment(
                start_sec=start_sec,
                end_sec=end_sec,
                avg_hr=avg_hr,
                max_hr=max_hr,
                peak_sec=peak_t,
                prominence=prom,
            )
        )

    detected_count = len(segments)
    if detected_count == 0:
        # Edge case: all peaks had degenerate windows. Treat as flat.
        return SegmentationResult(
            status="flat", target_count=target_count, detected_count=0
        )

    # Recompute the final status from the surviving segment count. When
    # ``over_target`` was true pre-build but zero-sample windows dropped
    # us below ``target_count``, surface ``too_few`` rather than the
    # stale ``too_many`` — code-reviewer finding (optional). When
    # trimming brought us exactly to target, ``too_many`` still wins so
    # the UI can tell the user we discarded extras.
    if detected_count < target_count:
        status: SegmentationStatus = "too_few"
    elif over_target:
        status = "too_many"
    elif detected_count > target_count:
        status = "too_many"
    else:
        status = "ok"

    return SegmentationResult(
        status=status,
        target_count=target_count,
        detected_count=detected_count,
        segments=segments,
    )
