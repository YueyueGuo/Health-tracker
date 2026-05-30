"""Lazy on-demand fetch + cache of Strava per-sample streams.

Factored out of ``backend/routers/activities.py:get_activity_streams``
(the old inline implementation lived around lines 327-379 of that file)
so both the router endpoint and the strength-link service can share a
single code path. Behaviour is unchanged from the original implementation:

* If ``activity_streams`` rows exist for the given activity, return the
  cached mapping ``{stream_type: data}`` directly.
* Otherwise hit ``StravaClient.get_activity_streams`` (which propagates
  the shared module-level 429 quota state), insert one
  ``ActivityStream`` row per non-empty series, and flush.

Errors propagate as :class:`StravaStreamFetchError` carrying the
underlying exception. The router endpoint translates that into HTTP
502; the strength-link service catches it and persists a link row with
``segmentation_status="no_stream"``.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Activity, ActivityStream

logger = logging.getLogger(__name__)


class StravaStreamFetchError(Exception):
    """Wraps any failure from ``StravaClient.get_activity_streams``.

    Carries the original exception via ``__cause__`` so callers can
    distinguish rate-limit (``StravaRateLimitError``) from generic
    network failures when shaping their response.
    """


async def fetch_and_cache_streams(
    db: AsyncSession,
    activity: Activity,
    strava_client: Any,
) -> dict[str, list[Any]]:
    """Fetch streams from Strava and cache as ``ActivityStream`` rows.

    Accepts an already-authenticated ``StravaClient`` instance so callers
    (e.g. the Phase B enrichment loop) can reuse their existing client.

    Returns ``{stream_type: data}`` for the activity. If streams are
    already cached, returns them immediately without calling Strava.

    Does NOT catch exceptions internally -- callers are responsible for
    error handling (rate limits, network failures, etc.).
    """
    # Check cache first.
    cached = (
        (
            await db.execute(
                select(ActivityStream).where(ActivityStream.activity_id == activity.id)
            )
        )
        .scalars()
        .all()
    )
    if cached:
        return {s.stream_type: s.data for s in cached}

    # Cache miss: hit Strava.
    streams = await strava_client.get_activity_streams(activity.strava_id)

    for stream_type, data in streams.items():
        if data:
            db.add(
                ActivityStream(
                    activity_id=activity.id,
                    stream_type=stream_type,
                    data=data,
                )
            )
    await db.flush()
    return streams


async def load_streams_for_activity(
    db: AsyncSession, activity: Activity
) -> dict[str, list[Any]]:
    """Return ``{stream_type: data}`` for a Strava ``Activity``.

    Reads ``activity_streams`` first; on a miss, calls
    ``StravaClient.get_activity_streams`` and persists non-empty
    series. The mapping returned on a miss is exactly what Strava
    returned, in the same shape the router endpoint emits.
    """
    from backend.clients.strava import StravaClient

    client = StravaClient()
    try:
        result = await fetch_and_cache_streams(db, activity, client)
        await db.commit()
        return result
    except Exception as e:
        # Surface the underlying exception via ``__cause__`` so callers
        # can do ``isinstance(e.__cause__, StravaRateLimitError)``.
        raise StravaStreamFetchError(str(e)) from e
    finally:
        await client.close()
