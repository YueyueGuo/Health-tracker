"""Shared Strava + Apple Health activity feed.

Backs ``/api/activities``, ``/api/dashboard/history`` and
``/api/dashboard/training-trends``. All three endpoints surface the
same canonical row policy: Strava rows whose ``superseded_by_id`` is
NULL plus Apple ``Workout`` rows (either Apple-only, or Apple-wins-
dedup over a linked Strava row). ``include_superseded=True`` also
surfaces the Strava losers; the linked Apple winners still appear, so
callers will see two rows for the same conceptual workout — intentional
for the debug-style view.

Why this is a helper instead of a SQL union: column shapes differ
enough between Strava ``Activity`` and Apple ``Workout`` that a UNION
would be more code than a small Python sort-merge. Volumes are also
small (days-of-history scale), so a dict-shape merge is fine.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Activity, HealthDataPoint, Workout


async def list_activity_feed(
    db: AsyncSession,
    *,
    cutoff: datetime,
    limit: int,
    offset: int = 0,
    sport_type: str | None = None,
    include_superseded: bool = False,
    before: datetime | None = None,
) -> list[dict]:
    """Merged Strava + Apple feed shaped as ``ActivitySummary``.

    Parameters mirror the three callers' query params. ``cutoff`` is a
    timezone-aware UTC datetime; rows with ``start_date`` (Strava) or
    ``start_time`` (Apple) at or after the cutoff are eligible. The
    columns are ``timestamptz``, so the cutoff must be tz-aware to compare
    correctly on Postgres regardless of the session ``TimeZone`` setting.

    ``before`` (additive; default ``None`` preserves prior behavior) is an
    optional inclusive *upper* bound on the same timestamps — rows at or
    before it are eligible. It exists for the cursor-paginated history
    feed (``backend/services/history_feed.py``): keyset paging walks
    *backward* in time, so it needs the ``limit`` newest rows **at or
    before** the cursor, which a lower-bound ``cutoff`` alone cannot
    express. Existing callers (``/api/activities``, ``/api/dashboard/*``)
    pass ``None`` and are unaffected.
    """
    # Import lazily to avoid a circular import: ``activities.py``
    # imports from this module, but its row shape helpers live there.
    from backend.routers.activities import (
        _activity_summary,
        _apple_workout_summary,
    )

    # ── Strava (existing activities table) ──────────────────────────
    query = select(Activity).order_by(Activity.start_date.desc())
    query = query.where(Activity.start_date >= cutoff)
    if before is not None:
        query = query.where(Activity.start_date <= before)
    if not include_superseded:
        query = query.where(Activity.superseded_by_id.is_(None))
    if sport_type:
        query = query.where(Activity.sport_type == sport_type)
    # Over-fetch so the downstream Python merge can still respect ``limit``.
    query = query.limit(limit + offset)
    activities = (await db.execute(query)).scalars().all()
    strava_rows = [_activity_summary(a) for a in activities]

    # ── Apple workouts ──────────────────────────────────────────────
    # When the caller passes a ``sport_type`` filter we skip Apple rows
    # entirely — Apple's ``activity_type`` taxonomy is the normalized
    # one, not Strava's, so the filter wouldn't be meaningful here.
    apple_rows: list[dict] = []
    if not sport_type:
        # 1) Apple-only workouts (no Strava back-link). Always canonical.
        apple_only_q = (
            select(Workout, HealthDataPoint)
            .join(HealthDataPoint, Workout.id == HealthDataPoint.id)
            .where(
                HealthDataPoint.data_type == "workout",
                HealthDataPoint.source == "apple_health",
                HealthDataPoint.start_time >= cutoff,
                Workout.activity_id.is_(None),
            )
            .order_by(HealthDataPoint.start_time.desc())
            .limit(limit + offset)
        )
        if before is not None:
            apple_only_q = apple_only_q.where(HealthDataPoint.start_time <= before)
        for workout, dp in (await db.execute(apple_only_q)).all():
            apple_rows.append(_apple_workout_summary(workout, dp))

        # 2) Apple workouts that WON dedup over a linked Strava activity.
        # The linked Activity's superseded_by_id is non-NULL → Apple is
        # canonical. These would otherwise be hidden by the
        # ``activity_id IS NULL`` filter above AND by the Strava query's
        # default ``superseded_by_id IS NULL`` filter — so the canonical
        # workout would vanish entirely. This branch restores it.
        apple_winner_q = (
            select(Workout, HealthDataPoint)
            .join(HealthDataPoint, Workout.id == HealthDataPoint.id)
            .join(Activity, Workout.activity_id == Activity.id)
            .where(
                HealthDataPoint.data_type == "workout",
                HealthDataPoint.source == "apple_health",
                HealthDataPoint.start_time >= cutoff,
                Workout.activity_id.is_not(None),
                Activity.superseded_by_id.is_not(None),
            )
            .order_by(HealthDataPoint.start_time.desc())
            .limit(limit + offset)
        )
        if before is not None:
            apple_winner_q = apple_winner_q.where(HealthDataPoint.start_time <= before)
        for workout, dp in (await db.execute(apple_winner_q)).all():
            apple_rows.append(_apple_workout_summary(workout, dp))

    # Merge + sort by start_date, then page in Python.
    combined = strava_rows + apple_rows
    combined.sort(key=lambda r: r.get("start_date") or "", reverse=True)
    return combined[offset : offset + limit]
