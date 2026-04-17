"""Sleep vs. next-day activity performance correlations.

Read-only analytics: pair each qualifying activity with the Eight Sleep
`SleepSession` whose `date` equals the activity's `start_date_local.date()`
(Eight's `date` is the wake-up date, which is the same calendar day as the
activity performed that day), then compute Pearson correlation coefficients
for a curated matrix of sleep metrics × activity metrics.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from statistics import StatisticsError, correlation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Activity, SleepSession

# Sleep metrics to correlate against (attribute names on SleepSession).
SLEEP_METRICS: tuple[str, ...] = (
    "sleep_score",
    "hrv",
    "total_duration",
    "deep_sleep",
    "waso_duration",
)

# Activity metrics to correlate against (attribute names on Activity).
ACTIVITY_METRICS: tuple[str, ...] = (
    "average_hr",
    "average_power",
    "moving_time",
    "suffer_score",
    "average_speed",
)

# Noise filters.
MIN_MOVING_TIME_SEC = 600  # 10 minutes
MIN_PAIRED_SAMPLES = 8


async def sleep_vs_activity(
    db: AsyncSession,
    *,
    days: int = 60,
    sport_type: str | None = None,
) -> dict[str, Any]:
    """Correlate prior-night sleep metrics against same-day activity metrics.

    Args:
        db: Async SQLAlchemy session.
        days: Look back window in days (based on `Activity.start_date_local`).
        sport_type: Optional filter on `Activity.sport_type` (e.g. "Run").

    Returns:
        A dict with:
          - `days`: window in days (echoed)
          - `sport_type`: filter (echoed)
          - `pair_count`: number of activities paired with a sleep session
          - `pairs`: list of paired records (activity id/date + raw metric
            values for sleep & activity)
          - `correlations`: nested dict {sleep_metric: {activity_metric: r|null}}.
            `null` returned when fewer than MIN_PAIRED_SAMPLES non-null pairs.
    """
    cutoff_dt = datetime.combine(date.today() - timedelta(days=days), datetime.min.time())

    activity_q = (
        select(Activity)
        .where(Activity.start_date_local.is_not(None))
        .where(Activity.start_date_local >= cutoff_dt)
        .where(Activity.moving_time.is_not(None))
        .where(Activity.moving_time >= MIN_MOVING_TIME_SEC)
        .where(Activity.average_hr.is_not(None))
        .order_by(Activity.start_date_local.asc())
    )
    if sport_type:
        activity_q = activity_q.where(Activity.sport_type == sport_type)
    activities = (await db.execute(activity_q)).scalars().all()

    if not activities:
        return _empty_response(days, sport_type)

    # Fetch all relevant Eight Sleep sessions in one query, keyed by date.
    activity_dates = {a.start_date_local.date() for a in activities}
    sleep_q = select(SleepSession).where(
        SleepSession.source == "eight_sleep",
        SleepSession.date.in_(activity_dates),
    )
    sleep_rows = (await db.execute(sleep_q)).scalars().all()
    sleep_by_date: dict[date, SleepSession] = {s.date: s for s in sleep_rows}

    pairs: list[dict[str, Any]] = []
    for act in activities:
        sleep = sleep_by_date.get(act.start_date_local.date())
        if sleep is None:
            continue
        pairs.append(
            {
                "activity_id": act.id,
                "date": act.start_date_local.date().isoformat(),
                "sport_type": act.sport_type,
                "sleep": {m: getattr(sleep, m) for m in SLEEP_METRICS},
                "activity": {m: getattr(act, m) for m in ACTIVITY_METRICS},
            }
        )

    correlations = _compute_correlations(pairs)

    return {
        "days": days,
        "sport_type": sport_type,
        "pair_count": len(pairs),
        "pairs": pairs,
        "correlations": correlations,
    }


def _empty_response(days: int, sport_type: str | None) -> dict[str, Any]:
    return {
        "days": days,
        "sport_type": sport_type,
        "pair_count": 0,
        "pairs": [],
        "correlations": {
            sm: {am: None for am in ACTIVITY_METRICS} for sm in SLEEP_METRICS
        },
    }


def _compute_correlations(
    pairs: list[dict[str, Any]],
) -> dict[str, dict[str, float | None]]:
    """For each (sleep_metric, activity_metric), compute Pearson r or None."""
    result: dict[str, dict[str, float | None]] = {}
    for sm in SLEEP_METRICS:
        result[sm] = {}
        for am in ACTIVITY_METRICS:
            xs: list[float] = []
            ys: list[float] = []
            for p in pairs:
                x = p["sleep"].get(sm)
                y = p["activity"].get(am)
                if x is None or y is None:
                    continue
                # Guard against non-numeric inputs.
                try:
                    xs.append(float(x))
                    ys.append(float(y))
                except (TypeError, ValueError):
                    continue
            if len(xs) < MIN_PAIRED_SAMPLES:
                result[sm][am] = None
                continue
            try:
                r = correlation(xs, ys)
            except StatisticsError:
                # Zero variance in one of the series → undefined.
                result[sm][am] = None
                continue
            # Round to 4 dp for stable JSON output.
            result[sm][am] = round(r, 4)
    return result
