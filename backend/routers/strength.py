"""Manual strength-training logging endpoints.

CRUD + aggregation for sets/reps/weight entries. Sessions are an
implicit grouping by `date` (see `backend/services/strength.py`).
"""
from __future__ import annotations

import logging
from datetime import date as date_type, datetime

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

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Pydantic schemas ────────────────────────────────────────────────


class StrengthSetInput(BaseModel):
    """One set in a bulk-insert payload.

    ``performed_at`` is a naive-local wall-clock timestamp stamped when
    the set is logged. Optional for legacy rows created before
    Live-only entry mode; new sets always carry it.
    """

    exercise_name: str = Field(..., min_length=1, max_length=100)
    set_number: int = Field(..., ge=1)
    reps: int = Field(..., ge=1)
    weight_kg: float | None = Field(None, ge=0)
    rpe: float | None = Field(None, ge=0, le=10)
    notes: str | None = None
    performed_at: datetime | None = None


class StrengthSessionCreate(BaseModel):
    """Bulk-insert payload: one date, many sets."""

    date: date_type
    activity_id: int | None = None
    sets: list[StrengthSetInput]


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


# ── Endpoints ───────────────────────────────────────────────────────


@router.get("/sessions")
async def get_sessions(
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Newest-first list of strength sessions (grouped by date)."""
    return await list_sessions(db, limit=limit)


@router.get("/session/{session_date}")
async def get_session(
    session_date: date_type,
    db: AsyncSession = Depends(get_db),
):
    """Full detail for one session (keyed by `YYYY-MM-DD`).

    Returns 404 when no sets logged on that date.
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
    """Bulk-insert sets for a single date. Returns count + session summary."""
    if not payload.sets:
        raise HTTPException(status_code=400, detail="At least one set required")

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
            performed_at=s.performed_at,
        )
        db.add(row)
        created.append(row)
    await db.commit()
    for row in created:
        await db.refresh(row)

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
