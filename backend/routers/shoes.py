"""Running-shoe CRUD + tagged-activity views.

Mounted at ``/api/shoes``. Cumulative distance + percent used are
computed on read (no stored counter); see
``backend/services/shoe_mileage.py``.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import Activity, HealthDataPoint, Shoe, Workout
from backend.services.shoe_mileage import (
    cumulative_distance_bulk,
    cumulative_distance_m,
    percent_used,
)

router = APIRouter()


SHOE_TYPE_PATTERN = r"^(everyday|workout|race|long_run|trail)$"


# ── Pydantic schemas ────────────────────────────────────────────────


class ShoeBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    brand: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=120)
    shoe_type: str = Field(default="everyday", pattern=SHOE_TYPE_PATTERN)
    total_usable_distance_m: float | None = Field(default=None, gt=0)
    purchased_on: date | None = None
    notes: str | None = None


class ShoeCreate(ShoeBase):
    pass


class ShoePatch(BaseModel):
    """All fields optional. ``status`` is intentionally absent —
    retire / unretire are dedicated verb endpoints so they can stamp
    ``retired_at`` as a side effect."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    brand: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=120)
    shoe_type: str | None = Field(default=None, pattern=SHOE_TYPE_PATTERN)
    total_usable_distance_m: float | None = Field(default=None, gt=0)
    purchased_on: date | None = None
    notes: str | None = None


class ShoeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    brand: str | None
    model: str | None
    shoe_type: str
    status: str
    total_usable_distance_m: float | None
    purchased_on: date | None
    retired_at: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    cumulative_distance_m: float
    percent_used: float | None


class ShoeDetailOut(ShoeOut):
    tagged_activity_count: int


class ActivityShoePatch(BaseModel):
    shoe_id: int | None = None


# ── Helpers ─────────────────────────────────────────────────────────


def _to_out(
    shoe: Shoe, cumulative: float, *, include_count: int | None = None
) -> ShoeOut | ShoeDetailOut:
    pct = percent_used(shoe.total_usable_distance_m, cumulative)
    base = {
        "id": shoe.id,
        "name": shoe.name,
        "brand": shoe.brand,
        "model": shoe.model,
        "shoe_type": shoe.shoe_type,
        "status": shoe.status,
        "total_usable_distance_m": shoe.total_usable_distance_m,
        "purchased_on": shoe.purchased_on,
        "retired_at": shoe.retired_at,
        "notes": shoe.notes,
        "created_at": shoe.created_at,
        "updated_at": shoe.updated_at,
        "cumulative_distance_m": cumulative,
        "percent_used": pct,
    }
    if include_count is not None:
        return ShoeDetailOut(**base, tagged_activity_count=include_count)
    return ShoeOut(**base)


async def _load_shoe_or_404(db: AsyncSession, shoe_id: int) -> Shoe:
    shoe = (
        await db.execute(select(Shoe).where(Shoe.id == shoe_id))
    ).scalar_one_or_none()
    if shoe is None:
        raise HTTPException(status_code=404, detail="Shoe not found")
    return shoe


# ── Endpoints ───────────────────────────────────────────────────────


@router.get("", response_model=list[ShoeOut])
async def list_shoes(
    status: Literal["active", "retired", "all"] = "active",
    db: AsyncSession = Depends(get_db),
):
    """List shoes. Default ``status=active``.

    Cumulative distance + percent used are batched via
    ``cumulative_distance_bulk`` so listing N shoes is two queries, not
    2N.
    """
    query = select(Shoe).order_by(Shoe.created_at.desc(), Shoe.id.desc())
    if status != "all":
        query = query.where(Shoe.status == status)
    shoes = (await db.execute(query)).scalars().all()
    if not shoes:
        return []

    ids = [s.id for s in shoes]
    totals = await cumulative_distance_bulk(db, ids)
    return [_to_out(s, totals.get(s.id, 0.0)) for s in shoes]


@router.get("/{shoe_id}", response_model=ShoeDetailOut)
async def get_shoe(shoe_id: int, db: AsyncSession = Depends(get_db)):
    shoe = await _load_shoe_or_404(db, shoe_id)
    cumulative = await cumulative_distance_m(db, shoe_id)

    strava_count = (
        await db.execute(
            select(func.count())
            .select_from(Activity)
            .where(Activity.shoe_id == shoe_id)
        )
    ).scalar_one()
    apple_count = (
        await db.execute(
            select(func.count())
            .select_from(Workout)
            .where(Workout.shoe_id == shoe_id)
        )
    ).scalar_one()
    tagged_count = int(strava_count) + int(apple_count)

    return _to_out(shoe, cumulative, include_count=tagged_count)


@router.post("", response_model=ShoeOut, status_code=201)
async def create_shoe(payload: ShoeCreate, db: AsyncSession = Depends(get_db)):
    shoe = Shoe(
        name=payload.name,
        brand=payload.brand,
        model=payload.model,
        shoe_type=payload.shoe_type,
        total_usable_distance_m=payload.total_usable_distance_m,
        purchased_on=payload.purchased_on,
        notes=payload.notes,
    )
    db.add(shoe)
    await db.commit()
    await db.refresh(shoe)
    return _to_out(shoe, 0.0)


@router.patch("/{shoe_id}", response_model=ShoeOut)
async def update_shoe(
    shoe_id: int, payload: ShoePatch, db: AsyncSession = Depends(get_db)
):
    shoe = await _load_shoe_or_404(db, shoe_id)

    # ``exclude_unset=True`` already gates on "the field was present in
    # the request body", so we honor explicit ``null`` clears for the
    # nullable columns (``brand``, ``model``, ``notes``,
    # ``total_usable_distance_m``, ``purchased_on``). Pydantic's
    # ``min_length`` / ``pattern`` validators do NOT reject ``None`` when
    # the field type is ``str | None``, so we must guard the two
    # non-nullable model columns (``name`` and ``shoe_type``) explicitly.
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        if value is None and field in {"name", "shoe_type"}:
            raise HTTPException(
                status_code=422, detail=f"{field} cannot be null"
            )
        setattr(shoe, field, value)

    await db.commit()
    await db.refresh(shoe)
    cumulative = await cumulative_distance_m(db, shoe_id)
    return _to_out(shoe, cumulative)


@router.post("/{shoe_id}/retire", response_model=ShoeOut)
async def retire_shoe(shoe_id: int, db: AsyncSession = Depends(get_db)):
    """Mark a shoe retired. Idempotent — already-retired shoes return
    their current state without re-stamping ``retired_at``."""
    shoe = await _load_shoe_or_404(db, shoe_id)
    if shoe.status != "retired":
        shoe.status = "retired"
        shoe.retired_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(shoe)
    cumulative = await cumulative_distance_m(db, shoe_id)
    return _to_out(shoe, cumulative)


@router.post("/{shoe_id}/unretire", response_model=ShoeOut)
async def unretire_shoe(shoe_id: int, db: AsyncSession = Depends(get_db)):
    """Reactivate a retired shoe. Idempotent."""
    shoe = await _load_shoe_or_404(db, shoe_id)
    if shoe.status != "active":
        shoe.status = "active"
        shoe.retired_at = None
        await db.commit()
        await db.refresh(shoe)
    cumulative = await cumulative_distance_m(db, shoe_id)
    return _to_out(shoe, cumulative)


@router.get("/{shoe_id}/activities")
async def list_shoe_activities(
    shoe_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Tagged activities (Strava) + workouts (Apple) for one shoe.

    Returns a merged, ``start_date``-descending list. Each row is a
    minimal serializer: id, source, start_date, distance_m,
    sport_type/activity_type, name. The activities router has fuller
    serializers but they pull weather / classification / zones blobs
    we don't need here — keep this lean.
    """
    await _load_shoe_or_404(db, shoe_id)

    strava_total = (
        await db.execute(
            select(func.count())
            .select_from(Activity)
            .where(Activity.shoe_id == shoe_id)
        )
    ).scalar_one()
    apple_total = (
        await db.execute(
            select(func.count())
            .select_from(Workout)
            .where(Workout.shoe_id == shoe_id)
        )
    ).scalar_one()
    total = int(strava_total) + int(apple_total)

    # Over-fetch then Python-merge: Strava ``start_date`` and Apple
    # ``HealthDataPoint.start_time`` live in separate tables with
    # different shapes — same approach as ``activity_feed.py``.
    strava_rows = (
        (
            await db.execute(
                select(Activity)
                .where(Activity.shoe_id == shoe_id)
                .order_by(Activity.start_date.desc())
                .limit(limit + offset)
            )
        )
        .scalars()
        .all()
    )
    apple_rows = (
        (
            await db.execute(
                select(Workout, HealthDataPoint)
                .join(HealthDataPoint, Workout.id == HealthDataPoint.id)
                .where(Workout.shoe_id == shoe_id)
                .order_by(HealthDataPoint.start_time.desc())
                .limit(limit + offset)
            )
        )
        .all()
    )

    items: list[dict] = []
    for a in strava_rows:
        items.append(
            {
                "id": a.id,
                "source": "strava",
                "name": a.name,
                "sport_type": a.sport_type,
                "start_date": a.start_date.isoformat() if a.start_date else None,
                "distance_m": a.distance,
            }
        )
    for w, dp in apple_rows:
        items.append(
            {
                "id": dp.id,
                "source": "apple",
                "name": (dp.raw_payload or {}).get("name") or w.activity_type,
                "sport_type": w.activity_type,
                "start_date": dp.start_time.isoformat() if dp.start_time else None,
                "distance_m": w.distance_m,
            }
        )
    items.sort(key=lambda r: r.get("start_date") or "", reverse=True)
    paged = items[offset : offset + limit]
    return {"items": paged, "total": total}
