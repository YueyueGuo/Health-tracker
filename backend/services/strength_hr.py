"""Map manual strength sets to HR samples recorded by a linked Strava activity.

A strength session is linked to a Strava WeightTraining activity via
``strength_sets.activity_id``. That activity's ``activity_streams`` rows
(populated lazily by ``GET /api/activities/{id}/streams``) contain a
``time`` array (seconds since activity start) and a ``heartrate`` array
(bpm) of equal length. Each set carries an optional ``performed_at``
naive-local timestamp — the moment the user tapped "Log set". We compute
(performed_at - activity.start_date_local) → seconds offset, then slice a
``[offset - window_sec, offset]`` window out of the HR array to get the
working-HR for that set.

**Key invariant**: this module is read-only against `activity_streams`.
If streams aren't cached, we return empty / None — we never trigger a
Strava fetch. Keeps the session_summary endpoint cheap.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Activity, ActivityStream, StrengthSet

# Default window size: user taps "Log set" at the end of the set, so we
# look backward N seconds to capture the working HR during the lift.
# 45s comfortably covers a typical compound set (10 reps @ ~3-4s/rep).
DEFAULT_WINDOW_SEC = 45

# Curve decimation target. Raw streams are 1Hz (1 sample/sec) so a 60-min
# workout is 3600 points — way too many for Recharts to render smoothly.
# ~300 points keeps the JSON payload small while still preserving enough
# resolution for the eye to see spikes during each set.
CURVE_TARGET_POINTS = 300


def _slice_hr_for_set(
    performed_at: datetime,
    activity_start: datetime,
    time_stream: list,
    hr_stream: list,
    window_sec: int = DEFAULT_WINDOW_SEC,
) -> tuple[float | None, float | None]:
    """Return ``(avg_hr, max_hr)`` for the window ending at ``performed_at``.

    Args:
        performed_at: Wall-clock time the set ended (naive local, same tz
            as ``activity_start``).
        activity_start: ``Activity.start_date_local`` — anchor for the
            time stream's seconds offsets.
        time_stream: list[int] — seconds-since-activity-start.
        hr_stream: list[float|int|None] — bpm samples, aligned to
            ``time_stream`` by index. Zero/None values are treated as
            dropouts and skipped.
        window_sec: Lookback window. Default 45s.

    Returns ``(None, None)`` if the window falls outside the stream, or
    if no valid HR samples land in it (all zero / None).
    """
    if not time_stream or not hr_stream:
        return (None, None)
    if len(time_stream) != len(hr_stream):
        # Defensive: Strava occasionally returns mismatched lengths for
        # stripped activities. Fall back to the shorter length.
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

    avg = round(sum(samples) / len(samples), 1)
    mx = round(max(samples), 1)
    return (avg, mx)


def _decimate(
    time_stream: list, hr_stream: list, target_points: int = CURVE_TARGET_POINTS
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


async def attach_hr_to_sets(
    db: AsyncSession,
    activity_id: int,
    sets: list[StrengthSet],
    window_sec: int = DEFAULT_WINDOW_SEC,
) -> dict[str, Any]:
    """Compute per-set HR stats + a decimated curve for a session.

    Reads cached ``activity_streams`` rows only — never triggers a
    Strava fetch. Returns an empty dict when:

    * No sets have ``performed_at`` (nothing to map).
    * Activity has no cached ``time`` or ``heartrate`` stream.
    * Activity row missing (stale FK).

    Otherwise returns:

    ```python
    {
      "hr_by_set_id": {set_id: {"avg_hr": 145.2, "max_hr": 160.0}, ...},
      "hr_curve": [[offset_sec, bpm], ...],
      "activity_start_iso": "2026-04-21T09:00:00",
    }
    ```
    """
    if not any(s.performed_at is not None for s in sets):
        return {}

    # Fetch the activity row for its start_date_local anchor.
    activity = (
        await db.execute(select(Activity).where(Activity.id == activity_id))
    ).scalar_one_or_none()
    if activity is None:
        return {}
    start = activity.start_date_local or activity.start_date
    if start is None:
        return {}

    # Fetch both streams in one query.
    stream_rows = (
        await db.execute(
            select(ActivityStream).where(
                ActivityStream.activity_id == activity_id,
                ActivityStream.stream_type.in_(("time", "heartrate")),
            )
        )
    ).scalars().all()
    by_type = {r.stream_type: r.data for r in stream_rows}
    time_stream = by_type.get("time")
    hr_stream = by_type.get("heartrate")
    if not time_stream or not hr_stream:
        return {}

    hr_by_set_id: dict[int, dict[str, float]] = {}
    for s in sets:
        if s.performed_at is None or s.id is None:
            continue
        avg, mx = _slice_hr_for_set(
            s.performed_at, start, time_stream, hr_stream, window_sec=window_sec
        )
        if avg is None:
            continue
        hr_by_set_id[s.id] = {"avg_hr": avg, "max_hr": mx}

    return {
        "hr_by_set_id": hr_by_set_id,
        "hr_curve": _decimate(time_stream, hr_stream),
        "activity_start_iso": start.isoformat(),
    }
