"""Manual strength-training logging endpoints.

CRUD + aggregation for sets/reps/weight entries. Sessions are an
implicit grouping by `date` (see `backend/services/strength.py`).
"""
from __future__ import annotations

import logging
from datetime import date as date_type, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import StrengthSet
from backend.services.strength import (
    list_sessions,
    progression,
    search_exercises,
    session_summary,
)
from backend.services.strength_link import (
    CandidateNotFoundError,
    InvalidLinkSourceError,
    LinkConflictError,
    clear_link,
    get_link,
    list_candidates,
    run_segmentation_for_link,
    set_link,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _normalize_performed_at(value: datetime | None) -> datetime | None:
    """Ensure ``performed_at`` is tz-aware before persisting.

    The frontend stamps sets with naive-local wall-clock ISO strings
    (see ``frontend/src/components/record/datetime.ts:toNaiveLocalIso``).
    The ``StrengthSet.performed_at`` column is now
    ``DateTime(timezone=True)`` (commit 35d648f); attach UTC tzinfo to
    naive inputs so the bind semantics are explicit. The numeric
    wall-clock value is preserved — asyncpg has been implicitly treating
    naive datetimes as UTC for this write for as long as the Postgres
    column has been ``timestamp with time zone``. See
    docs/audit-001-datetime-sweep-audit.md.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


# ── Pydantic schemas ────────────────────────────────────────────────


class StrengthSetInput(BaseModel):
    """One set in a bulk-insert payload.

    ``performed_at`` is a naive-local wall-clock timestamp stamped when
    the set is logged. Optional for legacy rows created before
    Live-only entry mode; new sets always carry it.

    ``superset_group_id`` and ``order_index`` are stamped by the
    recording flow (see ``docs/plans/strength-workout-detail.md``); a
    non-null ``superset_group_id`` means the set's exercise was
    performed back-to-back with other exercises sharing the same value.
    """

    exercise_name: str = Field(..., min_length=1, max_length=100)
    set_number: int = Field(..., ge=1)
    reps: int = Field(..., ge=1)
    weight_kg: float | None = Field(None, ge=0)
    rpe: float | None = Field(None, ge=0, le=10)
    notes: str | None = None
    performed_at: datetime | None = None
    superset_group_id: int | None = None
    order_index: int | None = None


class StrengthSessionCreate(BaseModel):
    """Bulk-insert payload: one date, many sets.

    ``started_at`` / ``ended_at`` are session-level timestamps stamped
    by the recorder's Start / Finish taps. They are denormalized onto
    every row of the session (cheap; avoids a parent table). See
    ``docs/plans/strength-workout-detail.md`` §6.
    """

    date: date_type
    activity_id: int | None = None
    sets: list[StrengthSetInput]
    started_at: datetime | None = None
    ended_at: datetime | None = None


class StrengthSetPatch(BaseModel):
    """Any subset of a set's fields. All optional."""

    exercise_name: str | None = Field(None, min_length=1, max_length=100)
    set_number: int | None = Field(None, ge=1)
    reps: int | None = Field(None, ge=1)
    weight_kg: float | None = Field(None, ge=0)
    rpe: float | None = Field(None, ge=0, le=10)
    notes: str | None = None
    performed_at: datetime | None = None
    activity_id: int | None = None
    superset_group_id: int | None = None
    order_index: int | None = None


class LinkWorkoutRequest(BaseModel):
    """``PUT /strength/session/{date}/link`` body."""

    source: Literal["strava", "apple_health"]
    ref_id: int = Field(..., ge=1)


# ── Endpoints ───────────────────────────────────────────────────────


@router.get("/sessions")
async def get_sessions(
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Newest-first list of strength sessions (grouped by date).

    Includes ``hr_linked`` per row (LEFT JOIN ``strength_session_links``).
    """
    return await list_sessions(db, limit=limit)


@router.get("/session/{session_date}")
async def get_session(
    session_date: date_type,
    db: AsyncSession = Depends(get_db),
):
    """Full detail for one session (keyed by `YYYY-MM-DD`).

    Returns 404 when no sets logged on that date. When a
    ``strength_session_links`` row exists with status ``pending`` (the
    bulk POST path leaves it pending to keep the request cheap), this
    GET runs segmentation lazily and persists the result.
    """
    summary = await session_summary(db, session_date)
    if summary is None:
        raise HTTPException(status_code=404, detail="No strength session on that date")
    return summary


@router.post("/sets", status_code=201)
async def create_sets(
    payload: StrengthSessionCreate,
    db: AsyncSession = Depends(get_db),
):
    """Bulk-insert sets for a single date. Returns count + session summary.

    Back-compat: when ``activity_id`` is provided in the payload, also
    write a ``strength_session_links`` row with ``source="strava"``.
    The link is left in ``segmentation_status="pending"`` so the first
    ``GET /session/{date}`` (or an explicit ``POST /resegment``) fires
    the actual segmentation run — keeps this POST cheap and avoids
    blocking the request on a lazy Strava stream fetch.
    """
    if not payload.sets:
        raise HTTPException(status_code=400, detail="At least one set required")

    started_at = _normalize_performed_at(payload.started_at)
    ended_at = _normalize_performed_at(payload.ended_at)

    created: list[StrengthSet] = []
    for s in payload.sets:
        row = StrengthSet(
            activity_id=payload.activity_id,
            date=payload.date,
            exercise_name=s.exercise_name.strip(),
            set_number=s.set_number,
            reps=s.reps,
            weight_kg=s.weight_kg,
            rpe=s.rpe,
            notes=s.notes,
            performed_at=_normalize_performed_at(s.performed_at),
            superset_group_id=s.superset_group_id,
            order_index=s.order_index,
            started_at=started_at,
            ended_at=ended_at,
        )
        db.add(row)
        created.append(row)
    await db.commit()
    for row in created:
        await db.refresh(row)

    # Legacy ``activity_id`` payload → seed the link row with
    # ``source="strava"``. We skip segmentation here on purpose; the
    # first GET will run it.
    if payload.activity_id is not None:
        try:
            await set_link(
                db,
                payload.date,
                "strava",
                payload.activity_id,
                run_segmentation=False,
            )
        except LinkConflictError as e:
            # Don't fail the whole POST on a link conflict — the sets
            # are already saved. Surface in the response so the
            # frontend can prompt the user to re-link manually.
            logger.warning(
                "POST /strength/sets: link conflict (date=%s, activity_id=%s): %s",
                payload.date,
                payload.activity_id,
                e,
            )
        except CandidateNotFoundError as e:
            logger.warning(
                "POST /strength/sets: activity %s not found, skipping link: %s",
                payload.activity_id,
                e,
            )

    summary = await session_summary(db, payload.date)
    return {
        "created": len(created),
        "session": summary,
    }


@router.patch("/sets/{set_id}")
async def update_set(
    set_id: int,
    patch: StrengthSetPatch,
    db: AsyncSession = Depends(get_db),
):
    """Update any subset of fields on a single set row."""
    row = (
        await db.execute(select(StrengthSet).where(StrengthSet.id == set_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Set not found")

    data = patch.model_dump(exclude_unset=True)
    for key, value in data.items():
        if key == "exercise_name" and value is not None:
            value = value.strip()
        elif key == "performed_at":
            value = _normalize_performed_at(value)
        setattr(row, key, value)
    await db.commit()
    await db.refresh(row)
    return {
        "id": row.id,
        "activity_id": row.activity_id,
        "date": row.date.isoformat(),
        "exercise_name": row.exercise_name,
        "set_number": row.set_number,
        "reps": row.reps,
        "weight_kg": row.weight_kg,
        "rpe": row.rpe,
        "notes": row.notes,
        "performed_at": row.performed_at.isoformat() if row.performed_at else None,
        "superset_group_id": row.superset_group_id,
        "order_index": row.order_index,
    }


@router.delete("/sets/{set_id}", status_code=204)
async def delete_set(
    set_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a single set row."""
    row = (
        await db.execute(select(StrengthSet).where(StrengthSet.id == set_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Set not found")
    await db.delete(row)
    await db.commit()
    return Response(status_code=204)


@router.get("/progression/{exercise_name}")
async def get_progression(
    exercise_name: str,
    days: int = Query(180, ge=1, le=3650),
    db: AsyncSession = Depends(get_db),
):
    """Per-date aggregates for an exercise (for the progression chart)."""
    return await progression(db, exercise_name=exercise_name, days=days)


@router.get("/exercises")
async def list_exercises(
    q: str | None = Query(None, description="Case-insensitive prefix match."),
    db: AsyncSession = Depends(get_db),
):
    """Distinct exercise names for autocomplete."""
    return await search_exercises(db, q=q, limit=20)


# ── Link endpoints (linked workout HR sets feature) ─────────────────


@router.get("/session/{session_date}/link-candidates")
async def get_link_candidates(
    session_date: date_type,
    db: AsyncSession = Depends(get_db),
):
    """Candidate device workouts in ``[date-1d, date+1d]``.

    Returns Strava activities + Apple Health workouts, ordered by
    start time. Empty list when no candidates exist (the frontend
    renders an explicit empty state on the picker).
    """
    return await list_candidates(db, session_date)


@router.put("/session/{session_date}/link")
async def put_link(
    session_date: date_type,
    payload: LinkWorkoutRequest,
    db: AsyncSession = Depends(get_db),
):
    """Persist (or update) the 1:1 link for a session.

    * 200 — link saved, returns the full session summary with
      segmentation results.
    * 404 — no strength session on that date.
    * 409 — target device workout already linked to another date.
    * 422 — chosen ``(source, ref_id)`` doesn't exist.
    """
    # Verify the session exists first so 404 wins over 422 / 409.
    summary = await session_summary(db, session_date)
    if summary is None:
        raise HTTPException(status_code=404, detail="No strength session on that date")

    try:
        await set_link(
            db,
            session_date,
            payload.source,
            payload.ref_id,
            run_segmentation=True,
        )
    except LinkConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except CandidateNotFoundError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except InvalidLinkSourceError as e:
        raise HTTPException(status_code=422, detail=str(e))

    summary = await session_summary(db, session_date)
    return summary


@router.delete("/session/{session_date}/link", status_code=204)
async def delete_link(
    session_date: date_type,
    db: AsyncSession = Depends(get_db),
):
    """Drop the link row for this session date (no-op if absent)."""
    await clear_link(db, session_date)
    return Response(status_code=204)


@router.post("/session/{session_date}/resegment")
async def post_resegment(
    session_date: date_type,
    db: AsyncSession = Depends(get_db),
):
    """Recompute segmentation against the currently linked workout.

    Useful when the link was first attempted before streams were
    available (e.g. lazy Strava fetch was rate-limited). Returns the
    full session summary on success; 404 when there's no session or no
    link.
    """
    link = await get_link(db, session_date)
    if link is None:
        raise HTTPException(
            status_code=404,
            detail="No link to resegment for this session date",
        )
    await run_segmentation_for_link(db, link)
    await db.commit()

    summary = await session_summary(db, session_date)
    if summary is None:
        raise HTTPException(status_code=404, detail="No strength session on that date")
    return summary
