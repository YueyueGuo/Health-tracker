"""Elevation enrichment service.

Isolated module (mirrors ``eight_sleep_sync.py``) so edits here don't
collide with parallel work on ``services/sync.py``. Called by
``SyncEngine.sync_elevation``.

Sources for ``Activity.base_elevation_m`` in precedence order:

1. ``Activity.elev_low_m`` \u2014 already extracted from Strava detail by
   ``_apply_detail_to_activity``. Authoritative, watch-recorded.
2. ``Activity.location_id`` \u2014 user-attached ``UserLocation.elevation_m``.
3. Open-Meteo elevation API lookup by ``start_lat``/``start_lng``.
4. Default ``UserLocation`` \u2014 applies to activities with no coords and no
   explicit ``location_id`` (typical indoor session at the user's home gym).

The ``elevation_enriched`` boolean mirrors ``weather_enriched`` and is the
worklist key. Once set we don't re-process the row, even if
``base_elevation_m`` ended up as ``None`` (e.g. indoor with no default
location configured) \u2014 user can always manually attach a location later,
which calls :func:`recompute_for_activity` directly.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.clients.elevation import ElevationClient, ElevationRateLimitError
from backend.models import Activity, UserLocation

logger = logging.getLogger(__name__)


async def sync_elevation(
    db: AsyncSession,
    client: ElevationClient,
    *,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Enrich pending activities with ``base_elevation_m``.

    Returns ``{"enriched": n, "skipped": n, "failed": n, "remaining": n}``
    where ``remaining`` is the count of still-pending rows after this pass.
    """
    pending_q = (
        select(Activity)
        .where(Activity.elevation_enriched == False)  # noqa: E712
        .order_by(Activity.start_date.desc())
    )
    if limit is not None:
        pending_q = pending_q.limit(limit)

    activities = (await db.execute(pending_q)).scalars().all()

    if dry_run:
        remaining = await _pending_count(db)
        return {
            "enriched": 0,
            "skipped": len(activities),
            "failed": 0,
            "remaining": remaining,
        }

    default_loc = await _get_default_location(db)

    enriched = 0
    skipped = 0
    failed = 0

    # Eagerly load attached UserLocations in one query rather than N+1.
    loc_ids = {a.location_id for a in activities if a.location_id is not None}
    location_map: dict[int, UserLocation] = {}
    if loc_ids:
        rows = (await db.execute(
            select(UserLocation).where(UserLocation.id.in_(loc_ids))
        )).scalars().all()
        location_map = {loc.id: loc for loc in rows}

    for activity in activities:
        # Path 1: already have elev_low_m from Strava.
        if activity.elev_low_m is not None:
            activity.base_elevation_m = activity.elev_low_m
            activity.elevation_enriched = True
            enriched += 1
            continue

        # Path 2: explicit user-attached location.
        if activity.location_id is not None:
            loc = location_map.get(activity.location_id)
            if loc and loc.elevation_m is not None:
                activity.base_elevation_m = loc.elevation_m
                activity.elevation_enriched = True
                enriched += 1
                continue

        # Path 3: Open-Meteo lookup by coords.
        if activity.start_lat is not None and activity.start_lng is not None:
            try:
                elev = await client.get_elevation(
                    lat=activity.start_lat, lng=activity.start_lng
                )
            except ElevationRateLimitError:
                logger.warning(
                    "Elevation API rate-limited; stopping sync loop."
                )
                # Commit progress so far.
                await db.commit()
                break
            except Exception as e:
                logger.warning(
                    f"Elevation lookup failed for activity {activity.id}: {e}"
                )
                failed += 1
                continue

            if elev is not None:
                activity.base_elevation_m = elev
                activity.elevation_enriched = True
                enriched += 1
                continue

            skipped += 1
            continue

        # Path 4: indoor with no coords \u2014 fall back to the default location.
        if default_loc is not None and default_loc.elevation_m is not None:
            activity.base_elevation_m = default_loc.elevation_m
            activity.elevation_enriched = True
            enriched += 1
            continue

        # No path available. Mark enriched=True with base_elevation_m=None
        # so we stop re-evaluating this row every sync pass; attaching a
        # location later re-triggers via recompute_for_activity.
        activity.elevation_enriched = True
        skipped += 1

    await db.commit()
    remaining = await _pending_count(db)
    return {
        "enriched": enriched,
        "skipped": skipped,
        "failed": failed,
        "remaining": remaining,
    }


async def recompute_for_activity(
    db: AsyncSession,
    activity: Activity,
    *,
    client: ElevationClient | None = None,
) -> float | None:
    """Re-derive ``base_elevation_m`` for a single activity.

    Called when the user attaches/changes a ``location_id`` via the API, or
    clears the ``elevation_enriched`` flag to request a re-run. Mutates
    ``activity`` in place; the caller is responsible for committing.

    Returns the resolved ``base_elevation_m`` (may be ``None``).
    """
    # Reload the attached location if any (the caller may not have loaded
    # the relationship).
    location: UserLocation | None = None
    if activity.location_id is not None:
        location = (await db.execute(
            select(UserLocation).where(UserLocation.id == activity.location_id)
        )).scalar_one_or_none()

    # Prefer an explicit user-attached location for activities that
    # *don't* have their own GPS \u2014 the whole point of the attach flow is
    # to override the default for indoor sessions. For outdoor activities
    # with real Strava elevation we still defer to the watch data (1) since
    # that's the actual low-point of the activity.
    if activity.elev_low_m is not None:
        activity.base_elevation_m = activity.elev_low_m
    elif location is not None and location.elevation_m is not None:
        activity.base_elevation_m = location.elevation_m
    elif (
        activity.start_lat is not None
        and activity.start_lng is not None
        and client is not None
    ):
        try:
            elev = await client.get_elevation(
                lat=activity.start_lat, lng=activity.start_lng
            )
        except ElevationRateLimitError:
            logger.warning(
                "Elevation API rate-limited during recompute; leaving "
                "base_elevation_m unchanged."
            )
            return activity.base_elevation_m
        activity.base_elevation_m = elev
    else:
        default_loc = await _get_default_location(db)
        if default_loc is not None and default_loc.elevation_m is not None:
            activity.base_elevation_m = default_loc.elevation_m
        else:
            activity.base_elevation_m = None

    activity.elevation_enriched = True
    return activity.base_elevation_m


async def _get_default_location(db: AsyncSession) -> UserLocation | None:
    return (await db.execute(
        select(UserLocation)
        .where(UserLocation.is_default == True)  # noqa: E712
        .limit(1)
    )).scalar_one_or_none()


async def _pending_count(db: AsyncSession) -> int:
    return (await db.execute(
        select(func.count()).select_from(Activity).where(
            Activity.elevation_enriched == False,  # noqa: E712
        )
    )).scalar_one()


async def pending_count(db: AsyncSession) -> int:
    """Public accessor used by sync status endpoints."""
    return await _pending_count(db)


def extract_elev_from_raw(raw: dict | None) -> dict[str, Any]:
    """Pluck ``elev_high`` / ``elev_low`` from a cached Strava detail blob.

    Safe on missing / weird shapes \u2014 returns an empty dict when nothing
    usable is present. Used by the backfill script's Phase 1 to promote
    data we've already paid the API cost for.
    """
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    hi = raw.get("elev_high")
    lo = raw.get("elev_low")
    if hi is not None:
        try:
            out["elev_high_m"] = float(hi)
        except (TypeError, ValueError):
            pass
    if lo is not None:
        try:
            out["elev_low_m"] = float(lo)
        except (TypeError, ValueError):
            pass
    return out
