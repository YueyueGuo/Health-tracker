"""Link a manual strength session to a single device-recorded workout.

Backs the "linked workout HR sets" feature
(``docs/specs/linked-workout-hr-sets.md`` /
``docs/plans/linked-workout-hr-sets.md``).

Public surface:

* :func:`list_candidates` — candidate device workouts (Strava + Apple)
  in ``[date-1d, date+1d]``.
* :func:`set_link` — persist a 1:1 link row, fetch streams, run
  segmentation, persist the resulting payload. Raises
  :class:`LinkConflictError` (translated to HTTP 409 by the router) if
  the target device workout is already linked elsewhere.
* :func:`clear_link` — drop the link row.
* :func:`ensure_streams_loaded` — pull streams for the linked device
  workout (Strava lazy fetch / Apple raw_payload).
* :func:`run_segmentation_for_link` — recompute segmentation against
  the current link (used by :func:`set_link` and the ``/resegment``
  endpoint).
"""
from __future__ import annotations

import logging
from datetime import date as date_type, datetime, time, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    Activity,
    ActivityStream,
    HealthDataPoint,
    StrengthSessionLink,
    StrengthSet,
    Workout,
)
from backend.services.strength_segmentation import (
    SegmentationResult,
    segment_hr_stream,
)

logger = logging.getLogger(__name__)


# Sources known to the link table. Enum-ish; app-enforced.
LinkSource = Literal["strava", "apple_health"]
_VALID_SOURCES: tuple[str, ...] = ("strava", "apple_health")


class LinkConflictError(Exception):
    """Target device workout is already linked to another session date.

    Router translates to HTTP 409.
    """


class CandidateNotFoundError(Exception):
    """The chosen ``(source, ref_id)`` doesn't exist in the DB.

    Router translates to HTTP 422.
    """


class InvalidLinkSourceError(Exception):
    """Unknown ``source`` value. Router translates to HTTP 422."""


# ── Candidate listing ─────────────────────────────────────────────


async def list_candidates(
    db: AsyncSession, session_date: date_type
) -> list[dict[str, Any]]:
    """Return Strava + Apple device-workout rows near ``session_date``.

    Window is ``[session_date - 1d, session_date + 1d]`` (inclusive),
    matching the spec's ±1 day default. Sorted by start time ascending.

    Each row dict::

        {
          "source": "strava" | "apple_health",
          "ref_id": int,                # activities.id / workouts.id
          "name": str | None,
          "sport": str | None,
          "start_local": str | None,    # ISO
          "duration_s": int | None,
          "avg_hr": float | None,
          "max_hr": float | None,
          "distance_m": float | None,
          "hr_stream_available": bool,  # True if HR series cached / lazy-fetchable
        }
    """
    window_start = datetime.combine(session_date - timedelta(days=1), time.min).replace(
        tzinfo=timezone.utc
    )
    window_end = datetime.combine(session_date + timedelta(days=1), time.max).replace(
        tzinfo=timezone.utc
    )

    # Strava activities. Filter on start_date (UTC) since start_date_local
    # is just a wall-clock copy in this repo (see Activity.start_date_local).
    strava_rows = (
        (
            await db.execute(
                select(Activity)
                .where(
                    Activity.start_date >= window_start,
                    Activity.start_date <= window_end,
                )
                .order_by(Activity.start_date)
            )
        )
        .scalars()
        .all()
    )

    # Which Strava activities have cached HR streams? Lazy-fetchable when
    # the activity is fully enriched.
    cached_hr_activity_ids: set[int] = set()
    if strava_rows:
        ids = [a.id for a in strava_rows]
        stream_rows = (
            (
                await db.execute(
                    select(ActivityStream.activity_id).where(
                        ActivityStream.activity_id.in_(ids),
                        ActivityStream.stream_type == "heartrate",
                    )
                )
            )
            .scalars()
            .all()
        )
        cached_hr_activity_ids = set(stream_rows)

    # Apple workouts (joined on health_data_points for start_time).
    apple_rows = (
        await db.execute(
            select(Workout, HealthDataPoint)
            .join(HealthDataPoint, Workout.id == HealthDataPoint.id)
            .where(
                HealthDataPoint.source == "apple_health",
                HealthDataPoint.data_type == "workout",
                HealthDataPoint.start_time >= window_start,
                HealthDataPoint.start_time <= window_end,
            )
            .order_by(HealthDataPoint.start_time)
        )
    ).all()

    out: list[dict[str, Any]] = []
    for a in strava_rows:
        lazy_ok = (a.enrichment_status == "complete") or (a.id in cached_hr_activity_ids)
        out.append(
            {
                "source": "strava",
                "ref_id": a.id,
                "name": a.name,
                "sport": a.sport_type,
                "start_local": (a.start_date_local or a.start_date).isoformat()
                if (a.start_date_local or a.start_date)
                else None,
                "duration_s": a.elapsed_time,
                "avg_hr": a.average_hr,
                "max_hr": a.max_hr,
                "distance_m": a.distance,
                "hr_stream_available": bool(lazy_ok),
            }
        )

    for row in apple_rows:
        workout: Workout = row[0]
        dp: HealthDataPoint = row[1]
        payload = dp.raw_payload or {}
        hr_series = payload.get("heartRateData")
        has_series = isinstance(hr_series, list) and len(hr_series) > 1
        out.append(
            {
                "source": "apple_health",
                "ref_id": workout.id,
                "name": payload.get("name") or workout.activity_type,
                "sport": workout.activity_type,
                "start_local": dp.start_time.isoformat() if dp.start_time else None,
                "duration_s": workout.duration_s,
                "avg_hr": workout.avg_hr,
                "max_hr": workout.max_hr,
                "distance_m": workout.distance_m,
                "hr_stream_available": has_series,
            }
        )

    # Final sort by start time across both sources.
    out.sort(key=lambda r: r.get("start_local") or "")
    return out


# ── Stream loading ────────────────────────────────────────────────


async def ensure_streams_loaded(
    db: AsyncSession, link: StrengthSessionLink
) -> dict[str, Any]:
    """Load HR + time streams for the link's device workout.

    Returns::

        {
          "time_stream": list[float] | None,
          "hr_stream": list[float] | None,
          "has_curve": bool,
          "activity_start": datetime | None,  # session-local anchor
        }

    For Strava sources this uses the shared lazy-fetch path
    (:func:`backend.services.strava_streams.load_streams_for_activity`),
    which writes a row in ``activity_streams`` on first hit. On fetch
    failure (rate limit, token expired, no series available) returns
    ``has_curve=False`` with streams unset — the caller marks the link
    as ``no_stream``.

    For Apple sources reads ``heartRateData`` from the workout's
    ``raw_payload``. When that series is absent or scalar-only,
    ``has_curve=False`` and the caller marks the link as ``no_curve``.
    """
    if link.source == "strava":
        return await _load_strava_streams(db, link)
    if link.source == "apple_health":
        return await _load_apple_streams(db, link)
    raise InvalidLinkSourceError(f"unknown link.source={link.source!r}")


async def _load_strava_streams(
    db: AsyncSession, link: StrengthSessionLink
) -> dict[str, Any]:
    from backend.services.strava_streams import (
        StravaStreamFetchError,
        load_streams_for_activity,
    )

    if link.activity_id is None:
        return {
            "time_stream": None,
            "hr_stream": None,
            "has_curve": False,
            "activity_start": None,
        }

    activity = (
        await db.execute(select(Activity).where(Activity.id == link.activity_id))
    ).scalar_one_or_none()
    if activity is None:
        return {
            "time_stream": None,
            "hr_stream": None,
            "has_curve": False,
            "activity_start": None,
        }

    activity_start = activity.start_date_local or activity.start_date

    try:
        streams = await load_streams_for_activity(db, activity)
    except StravaStreamFetchError as exc:
        # Caller will set segmentation_status="no_stream"; log here so
        # the failure is captured next to the link operation.
        logger.warning(
            "strength_link.ensure_streams_loaded: Strava fetch failed "
            "(session_date=%s, activity_id=%s, exc=%s)",
            link.session_date,
            link.activity_id,
            type(exc.__cause__ or exc).__name__,
        )
        return {
            "time_stream": None,
            "hr_stream": None,
            "has_curve": False,
            "activity_start": activity_start,
        }

    time_stream = streams.get("time")
    hr_stream = streams.get("heartrate")
    has_curve = bool(time_stream and hr_stream)
    return {
        "time_stream": time_stream if has_curve else None,
        "hr_stream": hr_stream if has_curve else None,
        "has_curve": has_curve,
        "activity_start": activity_start,
    }


async def _load_apple_streams(
    db: AsyncSession, link: StrengthSessionLink
) -> dict[str, Any]:
    """Parse Apple Health workout streams from raw_payload.

    Mirrors :func:`backend.routers.activities._maybe_apple_streams` but
    skips the velocity branch (segmentation only needs HR + time) and
    is keyed on ``workouts.id`` rather than the polymorphic id.
    """
    if link.workout_id is None:
        return {
            "time_stream": None,
            "hr_stream": None,
            "has_curve": False,
            "activity_start": None,
        }
    row = (
        await db.execute(
            select(Workout, HealthDataPoint)
            .join(HealthDataPoint, Workout.id == HealthDataPoint.id)
            .where(Workout.id == link.workout_id)
        )
    ).first()
    if row is None:
        return {
            "time_stream": None,
            "hr_stream": None,
            "has_curve": False,
            "activity_start": None,
        }
    _, dp = row
    activity_start = dp.start_time
    payload = dp.raw_payload or {}
    hr_series = payload.get("heartRateData")
    if not isinstance(hr_series, list) or len(hr_series) < 2:
        return {
            "time_stream": None,
            "hr_stream": None,
            "has_curve": False,
            "activity_start": activity_start,
        }

    hr_values: list[float] = []
    time_values: list[float] = []
    base_ts: float | None = None
    for i, entry in enumerate(hr_series):
        if not isinstance(entry, dict):
            continue
        qty = entry.get("qty")
        if qty is None:
            continue
        try:
            hr_values.append(float(qty))
        except (TypeError, ValueError):
            continue
        ts: float | None = None
        date_raw = entry.get("date")
        if isinstance(date_raw, str):
            try:
                parsed = datetime.strptime(date_raw, "%Y-%m-%d %H:%M:%S %z")
                ts = parsed.timestamp()
            except ValueError:
                ts = None
        if ts is not None:
            if base_ts is None:
                base_ts = ts
            time_values.append(ts - base_ts)
        else:
            time_values.append(float(i))

    if not hr_values:
        return {
            "time_stream": None,
            "hr_stream": None,
            "has_curve": False,
            "activity_start": activity_start,
        }

    return {
        "time_stream": time_values,
        "hr_stream": hr_values,
        "has_curve": True,
        "activity_start": activity_start,
    }


# ── Link CRUD ─────────────────────────────────────────────────────


async def _validate_candidate_exists(
    db: AsyncSession, source: str, ref_id: int
) -> None:
    """Raise :class:`CandidateNotFoundError` if ``(source, ref_id)`` is
    not a real device workout."""
    if source == "strava":
        row = (
            await db.execute(select(Activity.id).where(Activity.id == ref_id))
        ).scalar_one_or_none()
        if row is None:
            raise CandidateNotFoundError(
                f"strava activity {ref_id} not found"
            )
        return
    if source == "apple_health":
        row = (
            await db.execute(select(Workout.id).where(Workout.id == ref_id))
        ).scalar_one_or_none()
        if row is None:
            raise CandidateNotFoundError(
                f"apple workout {ref_id} not found"
            )
        return
    raise InvalidLinkSourceError(f"unknown source={source!r}")


async def _existing_link_for_target(
    db: AsyncSession, source: str, ref_id: int
) -> StrengthSessionLink | None:
    """Find any link row that already owns this device workout."""
    if source == "strava":
        stmt = select(StrengthSessionLink).where(
            StrengthSessionLink.source == "strava",
            StrengthSessionLink.activity_id == ref_id,
        )
    elif source == "apple_health":
        stmt = select(StrengthSessionLink).where(
            StrengthSessionLink.source == "apple_health",
            StrengthSessionLink.workout_id == ref_id,
        )
    else:
        raise InvalidLinkSourceError(f"unknown source={source!r}")
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_link(
    db: AsyncSession, session_date: date_type
) -> StrengthSessionLink | None:
    """Fetch the link row for a given session date."""
    return (
        await db.execute(
            select(StrengthSessionLink).where(
                StrengthSessionLink.session_date == session_date
            )
        )
    ).scalar_one_or_none()


async def set_link(
    db: AsyncSession,
    session_date: date_type,
    source: str,
    ref_id: int,
    *,
    run_segmentation: bool = True,
) -> StrengthSessionLink:
    """Persist a 1:1 link from ``session_date`` to ``(source, ref_id)``.

    * If the same ``(source, ref_id)`` is already linked to this
      ``session_date``, this is idempotent — we re-run segmentation and
      keep the row.
    * If the target is linked to a different session date, raises
      :class:`LinkConflictError`.
    * If the target doesn't exist, raises :class:`CandidateNotFoundError`.

    When ``run_segmentation=False`` the link is saved with
    ``segmentation_status="pending"`` and no streams are loaded. The
    bulk POST path uses this to keep the request cheap; the first GET
    against the session triggers the resegment.
    """
    if source not in _VALID_SOURCES:
        raise InvalidLinkSourceError(f"unknown source={source!r}")
    await _validate_candidate_exists(db, source, ref_id)

    # 1:1 device-workout side check.
    existing = await _existing_link_for_target(db, source, ref_id)
    if existing is not None and existing.session_date != session_date:
        raise LinkConflictError(
            f"{source}:{ref_id} is already linked to session "
            f"{existing.session_date.isoformat()}"
        )

    # Upsert by session_date.
    link = await get_link(db, session_date)
    if link is None:
        link = StrengthSessionLink(
            session_date=session_date,
            source=source,
            activity_id=ref_id if source == "strava" else None,
            workout_id=ref_id if source == "apple_health" else None,
            segmentation_status="pending",
        )
        db.add(link)
    else:
        link.source = source
        link.activity_id = ref_id if source == "strava" else None
        link.workout_id = ref_id if source == "apple_health" else None
        link.segmentation_status = "pending"
        link.segmentation_detected_count = None
        link.segmentation_target_count = None
        link.segmentation_payload = None

    await db.flush()

    if run_segmentation:
        await run_segmentation_for_link(db, link)

    await db.commit()
    await db.refresh(link)
    return link


async def clear_link(db: AsyncSession, session_date: date_type) -> bool:
    """Delete any link row for the given session date.

    Returns True if a row was deleted, False if there was nothing to do.
    """
    link = await get_link(db, session_date)
    if link is None:
        return False
    await db.delete(link)
    await db.commit()
    return True


# ── Segmentation runner ───────────────────────────────────────────


async def _count_logged_sets(
    db: AsyncSession, session_date: date_type
) -> int:
    rows = (
        await db.execute(
            select(StrengthSet.id).where(StrengthSet.date == session_date)
        )
    ).all()
    return len(rows)


async def run_segmentation_for_link(
    db: AsyncSession, link: StrengthSessionLink
) -> SegmentationResult | None:
    """Load streams, run segmentation, persist the result on ``link``.

    Mutates ``link`` in-place (caller commits). Returns the result for
    convenience — the persisted payload is also accessible via
    ``link.segmentation_payload``.

    Returns ``None`` only when the link source is malformed; in every
    other case ``segmentation_status`` is updated.
    """
    streams = await ensure_streams_loaded(db, link)
    target_count = await _count_logged_sets(db, link.session_date)

    ref_id = link.activity_id if link.source == "strava" else link.workout_id

    if not streams["has_curve"]:
        # Distinguish "Strava fetch failed / no series" from "Apple
        # workout summary-only".
        status = "no_curve" if link.source == "apple_health" else "no_stream"
        link.segmentation_status = status
        link.segmentation_detected_count = 0
        link.segmentation_target_count = target_count
        link.segmentation_payload = None
        logger.info(
            "strength_link.segmentation: session_date=%s source=%s "
            "ref_id=%s status=%s detected_count=0 target_count=%s",
            link.session_date,
            link.source,
            ref_id,
            status,
            target_count,
        )
        return None

    result = segment_hr_stream(
        streams["time_stream"], streams["hr_stream"], target_count
    )
    link.segmentation_status = result.status
    link.segmentation_detected_count = result.detected_count
    link.segmentation_target_count = result.target_count
    link.segmentation_payload = result.to_dict()
    logger.info(
        "strength_link.segmentation: session_date=%s source=%s ref_id=%s "
        "status=%s detected_count=%s target_count=%s",
        link.session_date,
        link.source,
        ref_id,
        result.status,
        result.detected_count,
        result.target_count,
    )
    return result


# ── Helpers for session_summary ──────────────────────────────────


async def link_summary_dict(
    db: AsyncSession, link: StrengthSessionLink
) -> dict[str, Any] | None:
    """Return the ``link`` block of the session_summary response.

    Pulls the device workout's summary fields (name, sport, duration,
    avg/max HR) so the frontend can render the linked-state panel
    without a second round-trip. Returns ``None`` when the linked
    device workout row has gone missing (data drift / upstream
    deletion).
    """
    if link.source == "strava":
        if link.activity_id is None:
            return None
        a = (
            await db.execute(
                select(Activity).where(Activity.id == link.activity_id)
            )
        ).scalar_one_or_none()
        if a is None:
            return None
        return {
            "source": "strava",
            "ref_id": a.id,
            "name": a.name,
            "sport": a.sport_type,
            "start_iso": (a.start_date_local or a.start_date).isoformat()
            if (a.start_date_local or a.start_date)
            else None,
            "duration_s": a.elapsed_time,
            "avg_hr": a.average_hr,
            "max_hr": a.max_hr,
        }
    if link.source == "apple_health":
        if link.workout_id is None:
            return None
        row = (
            await db.execute(
                select(Workout, HealthDataPoint)
                .join(HealthDataPoint, Workout.id == HealthDataPoint.id)
                .where(Workout.id == link.workout_id)
            )
        ).first()
        if row is None:
            return None
        workout, dp = row
        payload = dp.raw_payload or {}
        return {
            "source": "apple_health",
            "ref_id": workout.id,
            "name": payload.get("name") or workout.activity_type,
            "sport": workout.activity_type,
            "start_iso": dp.start_time.isoformat() if dp.start_time else None,
            "duration_s": workout.duration_s,
            "avg_hr": workout.avg_hr,
            "max_hr": workout.max_hr,
        }
    return None


