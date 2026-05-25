"""Helpers for the manual strength training module.

Pure logic (1RM estimation) + DB query helpers used by
`backend/routers/strength.py`. Keep it thin — the router is where
response shaping happens.
"""
from __future__ import annotations

from collections import Counter
from datetime import date as date_type, timedelta
from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import StrengthSessionLink, StrengthSet
from backend.services.strength_hr import attach_hr_to_sets
from backend.services.strength_link import (
    ensure_streams_loaded,
    get_link,
    link_summary_dict,
    run_segmentation_for_link,
)
from backend.services.strength_segmentation import Segment, SegmentationResult


# ── 1RM estimation ──────────────────────────────────────────────────


def estimate_1rm(weight_kg: float, reps: int) -> float | None:
    """Epley 1RM estimate: ``weight * (1 + reps / 30)``.

    * ``reps == 1`` → return the lifted weight (no extrapolation).
    * ``reps > 12`` → ``None`` (Epley is only meaningful in the 2–12 range).
    * ``weight_kg == 0`` → ``0`` (useful for bodyweight / placeholder rows).
    * ``reps <= 0`` → ``None`` (nonsensical input; we refuse to extrapolate).
    """
    if reps is None or reps <= 0:
        return None
    if reps > 12:
        return None
    if weight_kg == 0:
        return 0.0
    if reps == 1:
        return float(weight_kg)
    return float(weight_kg) * (1.0 + reps / 30.0)


# ── DB helpers ──────────────────────────────────────────────────────


async def list_sessions(
    db: AsyncSession, limit: int = 20
) -> list[dict[str, Any]]:
    """Newest-first list of sessions (one row per `date`).

    Returns: ``[{date, exercise_count, total_sets, total_volume_kg,
    activity_id, hr_linked}, ...]``.

    * ``total_volume_kg = sum(reps * weight_kg)`` across sets with
      non-null weight.
    * ``activity_id`` is whichever FK is attached to any row on that
      date (legacy back-compat — pre-link feature; preserved so
      ``frontend/src/components/activity/ActivityDetailStrength.tsx``
      keeps working when source is Strava).
    * ``hr_linked`` is True when a ``strength_session_links`` row exists
      for that date.
    """
    # Group strength_sets → one row per date, LEFT JOIN to
    # strength_session_links so we can emit the hr_linked flag without
    # a second round-trip.
    stmt = (
        select(
            StrengthSet.date,
            func.count(distinct(StrengthSet.exercise_name)).label("exercise_count"),
            func.count(StrengthSet.id).label("total_sets"),
            func.sum(StrengthSet.reps * StrengthSet.weight_kg).label("total_volume_kg"),
            func.max(StrengthSet.activity_id).label("activity_id"),
        )
        .group_by(StrengthSet.date)
        .order_by(StrengthSet.date.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.all()
    if not rows:
        return []

    dates = [r.date for r in rows]
    link_rows = (
        (
            await db.execute(
                select(StrengthSessionLink.session_date).where(
                    StrengthSessionLink.session_date.in_(dates)
                )
            )
        )
        .scalars()
        .all()
    )
    linked_dates = set(link_rows)

    return [
        {
            "date": row.date.isoformat(),
            "exercise_count": int(row.exercise_count or 0),
            "total_sets": int(row.total_sets or 0),
            "total_volume_kg": float(row.total_volume_kg) if row.total_volume_kg else 0.0,
            "activity_id": row.activity_id,
            "hr_linked": row.date in linked_dates,
        }
        for row in rows
    ]


async def session_summary(
    db: AsyncSession, target: date_type
) -> dict[str, Any] | None:
    """Full detail for one session (a single `date`).

    Returns ``None`` if no sets logged on that date. Otherwise::

        {
          "date": "YYYY-MM-DD",
          "activity_id": int | None,       # back-compat (Strava source only)
          "sets": [...],
          "exercises": [...],
          "total_sets": int,
          "total_reps": int,
          "total_volume_kg": float,
          "exercise_count": int,
          "duration_sec": int | None,
          "started_at": "..." | None,
          "ended_at": "..." | None,
          "link": {...} | None,
          "segmentation": {...} | None,
          "hr_curve": [[off, bpm], ...] | None,
          "segment_markers": [
              {set_number, exercise_name, per_exercise_set_number,
               start_sec, end_sec}, ...
          ] | None,
          "activity_start_iso": "..." | None,
        }

    **Display ordering** (drives ``sets`` + ``exercises``): exercises
    are ordered by ``min(order_index)`` per exercise (when recorded by
    the strength workout-detail flow), falling back to
    ``min(performed_at)``, then alphabetical ``exercise_name``. Each
    exercise carries its modal ``superset_group_id`` across that
    exercise's sets (``None`` when no set has one) and the min
    ``order_index`` for the exercise.

    ``duration_sec`` prefers ``max(ended_at) - min(started_at)`` across
    the date's rows (the recorder denormalizes the session-level stamps
    onto every row), falling back to ``max(performed_at) -
    min(performed_at)`` across rows that carry a stamp, else ``None``.

    Top-level aggregates (``total_sets``, ``total_reps``,
    ``total_volume_kg``, ``exercise_count``) match the per-exercise
    totals and include bodyweight (``weight_kg = None``) rows in reps /
    set counts; volume only counts weighted sets.

    **Link / HR (segmentation-driven)**: when a
    ``strength_session_links`` row exists, segmentation runs lazily on
    first GET if the link is in ``pending`` state (the bulk-insert
    POST writes ``pending`` rather than running segmentation inline).
    The chronological set→segment mapping used for HR attachment is a
    **separate concern** from the alphabetical-then-order_index
    display ordering: sets are re-sorted chronologically
    (``performed_at ASC NULLS LAST, id ASC``) only when assigning
    segments, and the per-set ``avg_hr`` / ``max_hr`` are then merged
    back into the alphabetical ``sets_payload`` / ``exercises`` by set
    id so the display order stays stable.

    All additions are *additive* — existing keys are unchanged so
    older consumers (e.g. ``ExercisesTable.tsx``,
    ``ActivityDetailStrength.tsx``) keep working.
    """
    stmt = (
        select(StrengthSet)
        .where(StrengthSet.date == target)
        .order_by(StrengthSet.exercise_name, StrengthSet.set_number)
    )
    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        return None

    sets_payload: list[dict[str, Any]] = []
    by_exercise: dict[str, list[StrengthSet]] = {}

    for s in rows:
        sets_payload.append(_set_dict(s))
        by_exercise.setdefault(s.exercise_name, []).append(s)

    exercises: list[dict[str, Any]] = []
    for name, sets in by_exercise.items():
        weights = [s.weight_kg for s in sets if s.weight_kg is not None]
        max_weight = max(weights) if weights else None
        total_volume = sum(
            (s.reps or 0) * (s.weight_kg or 0.0) for s in sets if s.weight_kg is not None
        )
        # Best single-set 1RM estimate across the session.
        best_1rm: float | None = None
        for s in sets:
            if s.weight_kg is None:
                continue
            est = estimate_1rm(s.weight_kg, s.reps)
            if est is not None and (best_1rm is None or est > best_1rm):
                best_1rm = est

        # Modal superset_group_id across the exercise's sets; None if no
        # set on this exercise has one. Ties resolve to the smallest id
        # (Counter.most_common is order-stable, but smallest-on-tie is
        # more intuitive for the UI grouping).
        group_ids = [
            s.superset_group_id for s in sets if s.superset_group_id is not None
        ]
        if group_ids:
            counts = Counter(group_ids)
            top_count = max(counts.values())
            superset_group_id: int | None = min(
                g for g, c in counts.items() if c == top_count
            )
        else:
            superset_group_id = None

        order_indices = [s.order_index for s in sets if s.order_index is not None]
        ex_order_index: int | None = min(order_indices) if order_indices else None

        ex_performed_ats = [s.performed_at for s in sets if s.performed_at is not None]
        ex_first_performed = min(ex_performed_ats) if ex_performed_ats else None

        exercises.append(
            {
                "name": name,
                "sets": [_set_dict(s) for s in sets],
                "max_weight": max_weight,
                "total_volume": total_volume,
                "est_1rm": best_1rm,
                "superset_group_id": superset_group_id,
                "order_index": ex_order_index,
                "_first_performed_at": ex_first_performed,
            }
        )

    # Ordering: min(order_index) per exercise → min(performed_at) →
    # exercise_name. ``None`` sorts after concrete values so legacy rows
    # without order_index fall through to the performed_at / name
    # fallbacks. Drop the private sort key before emitting.
    exercises.sort(
        key=lambda ex: (
            ex["order_index"] is None,
            ex["order_index"] if ex["order_index"] is not None else 0,
            ex["_first_performed_at"] is None,
            ex["_first_performed_at"] or 0,
            ex["name"],
        )
    )
    for ex in exercises:
        ex.pop("_first_performed_at", None)

    # ── Session-level aggregates / duration ────────────────────────
    total_sets = len(rows)
    total_reps = sum((s.reps or 0) for s in rows)
    total_volume_kg = sum(
        (s.reps or 0) * (s.weight_kg or 0.0) for s in rows if s.weight_kg is not None
    )
    exercise_count = len(by_exercise)

    started_at_vals = [s.started_at for s in rows if s.started_at is not None]
    ended_at_vals = [s.ended_at for s in rows if s.ended_at is not None]
    session_started_at = min(started_at_vals) if started_at_vals else None
    session_ended_at = max(ended_at_vals) if ended_at_vals else None

    duration_sec: int | None = None
    if session_started_at is not None and session_ended_at is not None:
        delta = session_ended_at - session_started_at
        if delta.total_seconds() >= 0:
            duration_sec = int(delta.total_seconds())
    if duration_sec is None:
        perf_vals = [s.performed_at for s in rows if s.performed_at is not None]
        if len(perf_vals) >= 2:
            delta = max(perf_vals) - min(perf_vals)
            if delta.total_seconds() > 0:
                duration_sec = int(delta.total_seconds())

    # Back-compat ``activity_id``: only emit when source is Strava and
    # the link still resolves. Legacy ``strength_sets.activity_id`` is
    # ignored here — the link table is the new source of truth.
    link = await get_link(db, target)
    activity_id: int | None = None
    if link is not None and link.source == "strava":
        activity_id = link.activity_id

    payload: dict[str, Any] = {
        "date": target.isoformat(),
        "activity_id": activity_id,
        "sets": sets_payload,
        "exercises": exercises,
        "total_sets": total_sets,
        "total_reps": total_reps,
        "total_volume_kg": total_volume_kg,
        "exercise_count": exercise_count,
        "duration_sec": duration_sec,
        "started_at": session_started_at.isoformat() if session_started_at else None,
        "ended_at": session_ended_at.isoformat() if session_ended_at else None,
        "link": None,
        "segmentation": None,
        "hr_curve": None,
        "segment_markers": None,
        "activity_start_iso": None,
    }

    if link is None:
        return payload

    # Lazy resegment on first GET when the bulk POST left it pending.
    if link.segmentation_status == "pending":
        await run_segmentation_for_link(db, link)
        await db.commit()
        await db.refresh(link)

    payload["link"] = await link_summary_dict(db, link)
    payload["segmentation"] = {
        "status": link.segmentation_status,
        "detected_count": link.segmentation_detected_count or 0,
        "target_count": link.segmentation_target_count or 0,
    }

    # Attach HR to sets when segmentation produced segments. We need
    # streams again here for the decimated curve; ``ensure_streams_loaded``
    # is cheap on the second call (Strava streams are now cached;
    # Apple parsing is in-process).
    if link.segmentation_status in {"ok", "too_few", "too_many"}:
        streams = await ensure_streams_loaded(db, link)
        segments = _segments_from_payload(link.segmentation_payload)
        result = SegmentationResult(
            status=link.segmentation_status,  # type: ignore[arg-type]
            target_count=link.segmentation_target_count or 0,
            detected_count=link.segmentation_detected_count or 0,
            segments=segments,
        )
        hr = attach_hr_to_sets(
            list(rows),
            result,
            streams["time_stream"],
            streams["hr_stream"],
            streams["activity_start"],
        )
        if hr:
            by_id = hr.get("hr_by_set_id") or {}
            for s in sets_payload:
                stats = by_id.get(s["id"])
                if stats:
                    s["avg_hr"] = stats["avg_hr"]
                    s["max_hr"] = stats["max_hr"]
            for ex in exercises:
                for s in ex["sets"]:
                    stats = by_id.get(s["id"])
                    if stats:
                        s["avg_hr"] = stats["avg_hr"]
                        s["max_hr"] = stats["max_hr"]
            payload["hr_curve"] = hr.get("hr_curve")
            payload["segment_markers"] = hr.get("segment_markers")
            payload["activity_start_iso"] = hr.get("activity_start_iso")

    return payload


def _segments_from_payload(payload: Any) -> list[Segment]:
    """Re-hydrate :class:`Segment` instances from the JSON-cached payload."""
    if not payload:
        return []
    raw = payload.get("segments") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return []
    out: list[Segment] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            out.append(
                Segment(
                    start_sec=float(entry["start_sec"]),
                    end_sec=float(entry["end_sec"]),
                    avg_hr=float(entry["avg_hr"]),
                    max_hr=float(entry["max_hr"]),
                    peak_sec=float(entry["peak_sec"]),
                    prominence=float(entry["prominence"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


async def progression(
    db: AsyncSession, exercise_name: str, days: int = 180
) -> list[dict[str, Any]]:
    """Per-date aggregates for a single exercise over the last ``days``.

    For each date we return: ``max_weight_kg``, ``est_1rm_kg`` (the best
    single-set Epley estimate across all sets that day, or plain max
    weight when none of that day's sets are in the Epley-valid range),
    ``total_volume_kg``, and ``top_set_reps`` (reps on the heaviest set).
    """
    cutoff = date_type.today() - timedelta(days=days)
    stmt = (
        select(StrengthSet)
        .where(StrengthSet.exercise_name == exercise_name)
        .where(StrengthSet.date >= cutoff)
        .order_by(StrengthSet.date)
    )
    rows = (await db.execute(stmt)).scalars().all()

    by_date: dict[date_type, list[StrengthSet]] = {}
    for s in rows:
        by_date.setdefault(s.date, []).append(s)

    out: list[dict[str, Any]] = []
    for d in sorted(by_date.keys()):
        day_sets = by_date[d]
        weighted = [s for s in day_sets if s.weight_kg is not None]
        if not weighted:
            continue
        max_weight = max(s.weight_kg for s in weighted)
        top_set = max(weighted, key=lambda s: s.weight_kg or 0.0)
        top_set_reps = top_set.reps

        best_1rm: float | None = None
        for s in weighted:
            est = estimate_1rm(s.weight_kg, s.reps)
            if est is not None and (best_1rm is None or est > best_1rm):
                best_1rm = est
        if best_1rm is None:
            # Fallback: report the day's heaviest lift when every set is
            # beyond Epley's meaningful range.
            best_1rm = max_weight

        total_volume = sum((s.reps or 0) * (s.weight_kg or 0.0) for s in weighted)

        out.append(
            {
                "date": d.isoformat(),
                "max_weight_kg": max_weight,
                "est_1rm_kg": best_1rm,
                "total_volume_kg": total_volume,
                "top_set_reps": top_set_reps,
            }
        )
    return out


async def search_exercises(
    db: AsyncSession, q: str | None, limit: int = 20
) -> list[str]:
    """Case-insensitive prefix match on exercise_name (autocomplete)."""
    stmt = select(distinct(StrengthSet.exercise_name)).order_by(
        StrengthSet.exercise_name
    )
    if q:
        stmt = stmt.where(func.lower(StrengthSet.exercise_name).like(f"{q.lower()}%"))
    stmt = stmt.limit(limit)
    rows = (await db.execute(stmt)).all()
    return [r[0] for r in rows]


def _set_dict(s: StrengthSet) -> dict[str, Any]:
    return {
        "id": s.id,
        "activity_id": s.activity_id,
        "date": s.date.isoformat(),
        "exercise_name": s.exercise_name,
        "set_number": s.set_number,
        "reps": s.reps,
        "weight_kg": s.weight_kg,
        "rpe": s.rpe,
        "notes": s.notes,
        "performed_at": s.performed_at.isoformat() if s.performed_at else None,
        "superset_group_id": s.superset_group_id,
        "order_index": s.order_index,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }
