"""Training goals CRUD.

Powers the GoalsSection in the Settings page. Exactly one goal may be
``is_primary=True`` at a time — enforced in code rather than a partial
unique index so SQLite doesn't fight us.
"""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import Goal

logger = logging.getLogger(__name__)
router = APIRouter()


class GoalOut(BaseModel):
    id: int
    race_type: str
    description: str | None
    target_date: date
    is_primary: bool
    status: str


class GoalCreate(BaseModel):
    race_type: str = Field(min_length=1, max_length=64)
    description: str | None = None
    target_date: date
    is_primary: bool = False
    status: str = Field(default="active", pattern="^(active|completed|abandoned)$")


class GoalPatch(BaseModel):
    race_type: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = None
    target_date: date | None = None
    is_primary: bool | None = None
    status: str | None = Field(default=None, pattern="^(active|completed|abandoned)$")


def _to_out(g: Goal) -> GoalOut:
    return GoalOut(
        id=g.id,
        race_type=g.race_type,
        description=g.description,
        target_date=g.target_date,
        is_primary=g.is_primary,
        status=g.status,
    )


async def _clear_other_primaries(db: AsyncSession, keep_id: int | None) -> None:
    stmt = update(Goal).values(is_primary=False)
    if keep_id is not None:
        stmt = stmt.where(Goal.id != keep_id)
    await db.execute(stmt)


@router.get("", response_model=list[GoalOut])
async def list_goals(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(Goal).order_by(Goal.is_primary.desc(), Goal.target_date.asc())
    )).scalars().all()
    return [_to_out(r) for r in rows]


@router.post("", response_model=GoalOut, status_code=201)
async def create_goal(payload: GoalCreate, db: AsyncSession = Depends(get_db)):
    goal = Goal(
        race_type=payload.race_type,
        description=payload.description,
        target_date=payload.target_date,
        is_primary=payload.is_primary,
        status=payload.status,
    )
    db.add(goal)
    await db.flush()
    if payload.is_primary:
        await _clear_other_primaries(db, keep_id=goal.id)
    await db.commit()
    await db.refresh(goal)
    return _to_out(goal)


@router.patch("/{goal_id}", response_model=GoalOut)
async def update_goal(
    goal_id: int, payload: GoalPatch, db: AsyncSession = Depends(get_db)
):
    goal = (await db.execute(
        select(Goal).where(Goal.id == goal_id)
    )).scalar_one_or_none()
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")

    fields_set = payload.model_fields_set

    if "race_type" in fields_set and payload.race_type is not None:
        goal.race_type = payload.race_type
    if "description" in fields_set:
        goal.description = payload.description
    if "target_date" in fields_set and payload.target_date is not None:
        goal.target_date = payload.target_date
    if "status" in fields_set and payload.status is not None:
        goal.status = payload.status

    if "is_primary" in fields_set and payload.is_primary is True:
        goal.is_primary = True
        await _clear_other_primaries(db, keep_id=goal.id)
    elif "is_primary" in fields_set and payload.is_primary is False:
        goal.is_primary = False

    await db.commit()
    await db.refresh(goal)
    return _to_out(goal)


@router.delete("/{goal_id}", status_code=204)
async def delete_goal(goal_id: int, db: AsyncSession = Depends(get_db)):
    goal = (await db.execute(
        select(Goal).where(Goal.id == goal_id)
    )).scalar_one_or_none()
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    await db.delete(goal)
    await db.commit()
    return None


@router.post("/{goal_id}/set-primary", response_model=GoalOut)
async def set_primary_goal(goal_id: int, db: AsyncSession = Depends(get_db)):
    goal = (await db.execute(
        select(Goal).where(Goal.id == goal_id)
    )).scalar_one_or_none()
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    goal.is_primary = True
    await _clear_other_primaries(db, keep_id=goal.id)
    await db.commit()
    await db.refresh(goal)
    return _to_out(goal)
