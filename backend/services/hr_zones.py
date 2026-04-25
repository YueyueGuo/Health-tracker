"""HR zone summaries, per-lap zone assignment, and cardiac-drift metrics.

Three pure helpers operate on Strava's ``zones_data`` JSON (already cached
on ``activities.zones_data`` during Phase B enrichment):

* :func:`summarize_hr_zones` — compact LLM-friendly time-in-zone summary.
* :func:`assign_lap_hr_zone` — map a lap's average HR to a 1-indexed zone.
* :func:`_find_hr_buckets` — internal: pull the HR entry's buckets out of
  ``zones_data`` (which can also contain pace and power entries).

Three async helpers compute drift metrics from cached stream rows:

* :func:`compute_hr_drift` — relative change in average HR between halves.
* :func:`compute_pace_hr_decoupling` — efficiency-factor drift (runs).
* :func:`compute_power_hr_decoupling` — efficiency-factor drift (rides).

**Invariant**: this module is read-only against ``activity_streams``. If
streams aren't cached, the compute_* functions return ``None`` — they
never trigger a Strava fetch. This preserves the lazy-stream architecture
called out in CLAUDE.md.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import ActivityStream

MIN_DRIFT_DURATION_S = 600
MIN_DECOUPLING_DURATION_S = 1200


def _find_hr_buckets(zones_data: list | None) -> list[dict] | None:
    """Return the ``distribution_buckets`` list from the HR zone entry, or None."""
    if not zones_data:
        return None
    for entry in zones_data:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") == "heartrate":
            buckets = entry.get("distribution_buckets")
            if isinstance(buckets, list) and buckets:
                return buckets
    return None


def summarize_hr_zones(zones_data: list | None) -> dict | None:
    """Compact summary of time-in-HR-zone, suitable for LLM prompts.

    Returns ``None`` when no HR zone data is present. Otherwise returns::

        {
          "z1_pct": 12, "z2_pct": 45, ..., "z5_pct": 8,  # rounded ints
          "dominant_zone": 2,
          "total_minutes": 62,
          "bucket_count": 5,
          "ranges": [{"zone": 1, "min": 0, "max": 124}, ...],
        }

    Handles 5-bucket (default Strava) and 7-bucket (custom) profiles. The
    open-top sentinel ``max == -1`` is preserved in ``ranges`` so callers
    can render it as e.g. "185+".
    """
    buckets = _find_hr_buckets(zones_data)
    if not buckets:
        return None

    times = [float(b.get("time") or 0) for b in buckets]
    total_seconds = sum(times)
    if total_seconds <= 0:
        return None

    pct_by_zone: dict[str, int] = {}
    dominant_idx = 0
    dominant_time = -1.0
    for i, t in enumerate(times):
        zone = i + 1
        pct = round(100 * t / total_seconds)
        pct_by_zone[f"z{zone}_pct"] = pct
        if t > dominant_time:
            dominant_time = t
            dominant_idx = i

    ranges = [
        {"zone": i + 1, "min": int(b.get("min", 0)), "max": int(b.get("max", 0))}
        for i, b in enumerate(buckets)
    ]

    return {
        **pct_by_zone,
        "dominant_zone": dominant_idx + 1,
        "total_minutes": round(total_seconds / 60),
        "bucket_count": len(buckets),
        "ranges": ranges,
    }


def assign_lap_hr_zone(
    lap_avg_hr: float | None, zones_data: list | None
) -> int | None:
    """Map a lap's average HR to a 1-indexed zone using the activity's HR buckets.

    Returns ``None`` if HR or zones are missing. HR below the lowest
    bucket's min clamps to zone 1. ``max == -1`` denotes the open-top
    bucket (anything ≥ that bucket's min). Boundary HR exactly equal to a
    bucket's ``max`` lands in the next zone — Strava buckets are
    half-open ``[min, max)`` except for the top zone which is ``[min, ∞)``.
    """
    if lap_avg_hr is None:
        return None
    buckets = _find_hr_buckets(zones_data)
    if not buckets:
        return None

    hr = float(lap_avg_hr)
    for i, b in enumerate(buckets):
        bmax_raw = b.get("max", 0)
        bmax = float(bmax_raw)
        if bmax == -1:
            return i + 1
        if hr < bmax:
            return max(1, i + 1)  # clamp below-z1 to z1
    return len(buckets)  # above declared range — top zone


async def _load_streams(
    db: AsyncSession, activity_id: int, types: tuple[str, ...]
) -> dict[str, list]:
    """Read cached stream rows. Returns ``{stream_type: data}`` for what's present."""
    rows = (
        (
            await db.execute(
                select(ActivityStream).where(
                    ActivityStream.activity_id == activity_id,
                    ActivityStream.stream_type.in_(types),
                )
            )
        )
        .scalars()
        .all()
    )
    return {r.stream_type: r.data for r in rows if isinstance(r.data, list)}


def _trim_to_min_length(*streams: list) -> tuple[list, ...]:
    n = min(len(s) for s in streams)
    return tuple(s[:n] for s in streams)


def _split_halves_by_time(
    time_stream: list, *value_streams: list
) -> tuple[list[list], list[list]] | None:
    """Split aligned streams at the midpoint of elapsed time.

    Returns ``(first_half_streams, second_half_streams)`` where each entry
    is a list of stream slices. Returns ``None`` when streams are too
    short to split or contain no usable time data.
    """
    if not time_stream or len(time_stream) < 4:
        return None
    last_t = time_stream[-1]
    if last_t is None or last_t <= 0:
        return None
    midpoint = last_t / 2.0
    split_idx = 0
    for i, t in enumerate(time_stream):
        if t is not None and t >= midpoint:
            split_idx = i
            break
    if split_idx < 2 or split_idx > len(time_stream) - 2:
        return None
    first = [s[:split_idx] for s in value_streams]
    second = [s[split_idx:] for s in value_streams]
    return first, second


def _mean_excluding_zero(samples: list) -> float | None:
    valid = [float(v) for v in samples if v is not None and v > 0]
    if not valid:
        return None
    return sum(valid) / len(valid)


async def compute_hr_drift(
    db: AsyncSession,
    activity_id: int,
    *,
    min_duration_s: int = MIN_DRIFT_DURATION_S,
) -> float | None:
    """Relative HR delta between the second half and first half of an activity.

    Returns a unitless float, e.g. ``0.042`` = HR rose 4.2%. Negative
    values mean HR fell (recovery, cool-down dominated workout).

    Returns ``None`` when:

    * Cached ``time`` or ``heartrate`` streams are missing.
    * Activity duration < ``min_duration_s`` (default 10 min — drift is
      too noisy below this).
    * First-half average HR is zero (all dropouts).

    Read-only against ``activity_streams``; never fetches.
    """
    streams = await _load_streams(db, activity_id, ("time", "heartrate"))
    time_stream = streams.get("time")
    hr_stream = streams.get("heartrate")
    if not time_stream or not hr_stream:
        return None
    time_stream, hr_stream = _trim_to_min_length(time_stream, hr_stream)
    if not time_stream:
        return None
    if (time_stream[-1] or 0) < min_duration_s:
        return None

    split = _split_halves_by_time(time_stream, hr_stream)
    if split is None:
        return None
    (first_hr,), (second_hr,) = split
    avg1 = _mean_excluding_zero(first_hr)
    avg2 = _mean_excluding_zero(second_hr)
    if avg1 is None or avg2 is None or avg1 == 0:
        return None
    return round((avg2 - avg1) / avg1, 4)


async def _compute_efficiency_decoupling(
    db: AsyncSession,
    activity_id: int,
    value_stream_type: str,
    min_duration_s: int,
) -> float | None:
    """Generic Pa:HR / Pw:HR decoupling.

    Efficiency = mean(value) / mean(HR) for each half. Decoupling =
    (EF_first - EF_second) / EF_first. Positive when efficiency drops
    (HR rose for the same value, i.e. cardiac drift under steady effort).
    """
    streams = await _load_streams(
        db, activity_id, ("time", "heartrate", value_stream_type)
    )
    time_stream = streams.get("time")
    hr_stream = streams.get("heartrate")
    val_stream = streams.get(value_stream_type)
    if not time_stream or not hr_stream or not val_stream:
        return None
    time_stream, hr_stream, val_stream = _trim_to_min_length(
        time_stream, hr_stream, val_stream
    )
    if not time_stream:
        return None
    if (time_stream[-1] or 0) < min_duration_s:
        return None

    split = _split_halves_by_time(time_stream, hr_stream, val_stream)
    if split is None:
        return None
    (hr1, val1), (hr2, val2) = split
    hr1_mean = _mean_excluding_zero(hr1)
    hr2_mean = _mean_excluding_zero(hr2)
    val1_mean = _mean_excluding_zero(val1)
    val2_mean = _mean_excluding_zero(val2)
    if not all((hr1_mean, hr2_mean, val1_mean, val2_mean)):
        return None
    ef1 = val1_mean / hr1_mean
    ef2 = val2_mean / hr2_mean
    if ef1 == 0:
        return None
    return round((ef1 - ef2) / ef1, 4)


async def compute_pace_hr_decoupling(
    db: AsyncSession,
    activity_id: int,
    *,
    min_duration_s: int = MIN_DECOUPLING_DURATION_S,
) -> float | None:
    """Pa:HR efficiency-factor decoupling for runs.

    Uses ``velocity_smooth`` (m/s) and ``heartrate``. Higher velocity per
    HR = more efficient. Positive return = efficiency dropped over the
    workout (pace held while HR rose).

    Default ``min_duration_s`` of 20 min — pace streams are noisier than
    raw HR, so the metric needs more samples to stabilize.
    """
    return await _compute_efficiency_decoupling(
        db, activity_id, "velocity_smooth", min_duration_s
    )


async def compute_power_hr_decoupling(
    db: AsyncSession,
    activity_id: int,
    *,
    min_duration_s: int = MIN_DECOUPLING_DURATION_S,
) -> float | None:
    """Pw:HR efficiency-factor decoupling for rides.

    Uses ``watts`` and ``heartrate``. Standard TrainingPeaks-style
    decoupling: positive = efficiency dropped (power held, HR rose).
    """
    return await _compute_efficiency_decoupling(
        db, activity_id, "watts", min_duration_s
    )
