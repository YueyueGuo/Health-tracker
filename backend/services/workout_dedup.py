"""Cross-source workout dedup.

Apple Health is the canonical source whenever the same workout exists
in both Apple and Strava. Dedup runs in both directions:

* When a new Apple Health workout lands, look for a matching Strava
  ``Activity`` in the ±10-minute window and flag it as superseded.
* When Strava sync inserts a new ``Activity``, look for a matching
  Apple Health ``Workout`` in the same window and flag the *Strava*
  row as superseded immediately.

Match criteria: window on start time AND normalized sport equality
(``sport_mapping.same_activity``). Both checks are conservative so we
don't accidentally collapse an Apple "Walk" onto a Strava "Run" that
just happened to start in the same window.

Caller-managed commits: these helpers mutate session-attached rows
but never commit. Callers (ingest, Strava sync) decide when to flush.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Activity, HealthDataPoint, Workout
from backend.services.sport_mapping import normalize_strava

logger = logging.getLogger(__name__)

# Loose window: watches and phone clocks drift, and Apple/Strava don't
# always agree on whether the warmup is part of the workout.
_DEDUP_WINDOW = timedelta(minutes=10)


def _strip_tz(dt):
    """Compare apples-to-apples: drop tzinfo for naive-DB columns."""
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _normalized_match(apple_activity_type: str, strava_sport_type: str) -> bool:
    """``Workout.activity_type`` is ALREADY normalized (set at ingest time
    via ``normalize_apple``). We only need to normalize the Strava side
    and compare. ``other`` / ``None`` never match — same conservative
    rule as ``sport_mapping.same_activity``.
    """
    if not apple_activity_type or apple_activity_type == "other":
        return False
    strava_norm = normalize_strava(strava_sport_type)
    if strava_norm is None:
        return False
    return apple_activity_type == strava_norm


async def match_apple_against_strava(
    db: AsyncSession, workout: Workout
) -> Activity | None:
    """Find a Strava activity that this Apple workout supersedes.

    On hit, sets ``activity.superseded_by_id`` to the workout's
    ``health_data_points.id`` and links the workout back to the
    activity (``workout.activity_id``). Returns the matched activity
    or ``None``.
    """
    data_point = workout.data_point
    if data_point is None:
        # Defensive — the ingest service always attaches the parent
        # before calling us, but a stand-alone Workout has no anchor.
        return None

    start = _strip_tz(data_point.start_time)
    if start is None:
        return None
    low = start - _DEDUP_WINDOW
    high = start + _DEDUP_WINDOW

    candidates = (
        await db.execute(
            select(Activity).where(
                Activity.start_date >= low,
                Activity.start_date <= high,
                Activity.superseded_by_id.is_(None),
            )
        )
    ).scalars().all()

    for activity in candidates:
        if not _normalized_match(workout.activity_type, activity.sport_type):
            # Normalizers are conservative — "TrailRun" vs "Walking" stays
            # unmatched even when start_time aligns within 10 min.
            continue
        activity.superseded_by_id = data_point.id
        workout.activity_id = activity.id
        logger.info(
            "Apple workout %s supersedes Strava activity %s "
            "(sport=%s/%s, start delta=%s)",
            data_point.external_id,
            activity.strava_id,
            workout.activity_type,
            activity.sport_type,
            (start - _strip_tz(activity.start_date)),
        )
        return activity

    return None


async def match_strava_against_apple(
    db: AsyncSession, activity: Activity
) -> Workout | None:
    """Find an Apple Health workout that supersedes this Strava activity.

    On hit, sets ``activity.superseded_by_id`` to the workout's
    ``health_data_points.id`` and links the workout back to the
    activity. Returns the matched workout or ``None``.
    """
    start = _strip_tz(activity.start_date)
    if start is None:
        return None
    low = start - _DEDUP_WINDOW
    high = start + _DEDUP_WINDOW

    # Join workouts to their backing health_data_points so we can
    # filter on start_time without lazy-loading each parent.
    # Skip Apple workouts that already point at a Strava activity:
    # an existing link wins. The alternative (let a new Strava row
    # steal the orphan when the previous Strava row is gone) would
    # silently rewrite history — keep the link, surface the orphan
    # in tooling instead.
    candidates = (
        await db.execute(
            select(Workout, HealthDataPoint)
            .join(HealthDataPoint, Workout.id == HealthDataPoint.id)
            .where(
                HealthDataPoint.data_type == "workout",
                HealthDataPoint.start_time >= low,
                HealthDataPoint.start_time <= high,
                Workout.activity_id.is_(None),
            )
        )
    ).all()

    for workout, data_point in candidates:
        if not _normalized_match(workout.activity_type, activity.sport_type):
            continue
        activity.superseded_by_id = data_point.id
        workout.activity_id = activity.id
        logger.info(
            "Strava activity %s superseded by Apple workout %s "
            "(sport=%s/%s, start delta=%s)",
            activity.strava_id,
            data_point.external_id,
            activity.sport_type,
            workout.activity_type,
            (_strip_tz(data_point.start_time) - start),
        )
        return workout

    return None
