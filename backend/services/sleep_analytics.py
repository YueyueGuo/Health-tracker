"""Derived analytics over the Eight Sleep `SleepSession` table.

Pure async functions that query the DB and return plain ``dict`` payloads
suitable for direct JSON serialization by the FastAPI router. Each function
scopes its query to ``source = "eight_sleep"`` so that future Whoop rows
don't pollute Eight Sleep-specific analytics.
"""
from __future__ import annotations

import math
import statistics
from datetime import date, timedelta
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import SleepSession


EIGHT_SLEEP = "eight_sleep"

# Metrics exposed by the rolling-averages endpoint.
_ROLLING_METRICS = (
    "sleep_score",
    "total_duration",
    "deep_sleep",
    "rem_sleep",
    "hrv",
    "wake_count",
)


# ── Query helpers ───────────────────────────────────────────────────


async def _fetch_sessions(
    db: AsyncSession, days: int
) -> list[SleepSession]:
    """Return Eight Sleep sessions in the last ``days`` days (inclusive)."""
    cutoff = date.today() - timedelta(days=days - 1)
    result = await db.execute(
        select(SleepSession)
        .where(SleepSession.source == EIGHT_SLEEP)
        .where(SleepSession.date >= cutoff)
        .order_by(SleepSession.date.asc())
    )
    return list(result.scalars().all())


def _avg(values: Iterable[float | int | None]) -> float | None:
    xs = [v for v in values if v is not None]
    if not xs:
        return None
    return sum(xs) / len(xs)


def _round(v: float | None, ndigits: int = 2) -> float | None:
    return round(v, ndigits) if v is not None else None


def _hour_of_day(dt) -> float | None:
    """Return the fractional hour-of-day for a datetime, or None."""
    if dt is None:
        return None
    return dt.hour + dt.minute / 60 + dt.second / 3600


def _circular_std_hours(hours: list[float]) -> float | None:
    """Circular standard deviation (in hours) over the 24h clock.

    Properly handles wrap-around at midnight (e.g. 23:30 and 00:30 are
    considered close together). Returns None if fewer than 2 samples or
    if the data is perfectly uniform around the clock.
    """
    if len(hours) < 2:
        return None
    thetas = [2 * math.pi * h / 24 for h in hours]
    sin_mean = sum(math.sin(t) for t in thetas) / len(thetas)
    cos_mean = sum(math.cos(t) for t in thetas) / len(thetas)
    r = math.sqrt(sin_mean * sin_mean + cos_mean * cos_mean)
    if r <= 0:
        return None
    # σ_circular (radians) = sqrt(-2 ln R); convert radians → hours.
    return math.sqrt(-2 * math.log(r)) * 24 / (2 * math.pi)


# ── Public analytics functions ──────────────────────────────────────


async def get_rolling_averages(db: AsyncSession, days: int = 30) -> dict:
    """Return 7-day and ``days``-day rolling averages for a set of metrics.

    The 7-day average always covers the most-recent 7 days; the long-window
    average covers the most-recent ``days`` days (default 30). Both windows
    are computed from the same DB query so we can return them together.
    """
    sessions = await _fetch_sessions(db, days=max(days, 7))
    today = date.today()
    short_cutoff = today - timedelta(days=6)   # last 7 days (inclusive)
    long_cutoff = today - timedelta(days=days - 1)

    short = [s for s in sessions if s.date >= short_cutoff]
    long_ = [s for s in sessions if s.date >= long_cutoff]

    def summarize(rows: list[SleepSession]) -> dict:
        return {
            m: _round(_avg(getattr(s, m) for s in rows), 2)
            for m in _ROLLING_METRICS
        }

    return {
        "window_days": days,
        "rolling_7_day": {
            "sample_size": len(short),
            "metrics": summarize(short),
        },
        "rolling_long": {
            "days": days,
            "sample_size": len(long_),
            "metrics": summarize(long_),
        },
    }


async def get_sleep_debt(
    db: AsyncSession, target_hours: float = 8.0, days: int = 14
) -> dict:
    """Compute per-night and cumulative sleep debt over the window.

    Debt is expressed in hours: ``target_hours - actual_hours``. Positive
    values mean the user slept less than the target.
    """
    sessions = await _fetch_sessions(db, days=days)

    per_night: list[dict] = []
    cumulative = 0.0
    for s in sessions:
        if s.total_duration is None:
            continue
        actual = s.total_duration / 60.0
        debt = target_hours - actual
        cumulative += debt
        per_night.append(
            {
                "date": s.date.isoformat(),
                "actual_hours": round(actual, 2),
                "debt_hours": round(debt, 2),
            }
        )

    avg_debt = _avg(n["debt_hours"] for n in per_night)
    return {
        "target_hours": target_hours,
        "window_days": days,
        "sample_size": len(per_night),
        "cumulative_debt_hours": round(cumulative, 2),
        "average_debt_hours": _round(avg_debt, 2),
        "per_night": per_night,
    }


async def get_best_worst_nights(
    db: AsyncSession, days: int = 90, top_n: int = 5
) -> dict:
    """Return the top-N best and worst nights (by sleep_score) in the window."""
    sessions = await _fetch_sessions(db, days=days)
    scored = [s for s in sessions if s.sleep_score is not None]

    # Sort copies so we don't mutate the original list's order.
    best = sorted(scored, key=lambda s: s.sleep_score, reverse=True)[:top_n]
    worst = sorted(scored, key=lambda s: s.sleep_score)[:top_n]

    return {
        "window_days": days,
        "top_n": top_n,
        "sample_size": len(scored),
        "best": [_night_stats(s) for s in best],
        "worst": [_night_stats(s) for s in worst],
    }


def _night_stats(s: SleepSession) -> dict:
    return {
        "date": s.date.isoformat(),
        "sleep_score": s.sleep_score,
        "total_duration": s.total_duration,
        "deep_sleep": s.deep_sleep,
        "rem_sleep": s.rem_sleep,
        "hrv": s.hrv,
        "avg_hr": s.avg_hr,
        "wake_count": s.wake_count,
    }


async def get_consistency_metrics(db: AsyncSession, days: int = 30) -> dict:
    """Standard deviations of bed_time, wake_time, and total_duration.

    - ``bed_time_std_hours`` / ``wake_time_std_hours`` use circular statistics
      on the 24-hour clock so that midnight-crossing times are handled
      correctly (23:30 and 00:30 are close, not 23 hours apart).
    - ``total_duration_std_minutes`` is the population stdev of total sleep
      duration across nights with data.

    Lower stdev → more consistent.
    """
    sessions = await _fetch_sessions(db, days=days)

    bed_hours = [h for h in (_hour_of_day(s.bed_time) for s in sessions) if h is not None]
    wake_hours = [h for h in (_hour_of_day(s.wake_time) for s in sessions) if h is not None]
    durations = [s.total_duration for s in sessions if s.total_duration is not None]

    return {
        "window_days": days,
        "sample_size": len(sessions),
        "bed_time": {
            "sample_size": len(bed_hours),
            "std_hours": _round(_circular_std_hours(bed_hours), 3),
        },
        "wake_time": {
            "sample_size": len(wake_hours),
            "std_hours": _round(_circular_std_hours(wake_hours), 3),
        },
        "total_duration": {
            "sample_size": len(durations),
            "std_minutes": _round(
                statistics.pstdev(durations) if len(durations) >= 2 else None, 2
            ),
            "mean_minutes": _round(_avg(durations), 2),
        },
    }
