"""User-defined locations (``user_locations``).

Powers the frontend ``LocationPicker`` and Settings page. Uses Open-Meteo
for free geocoding + elevation lookups so the user never has to know raw
lat/lng.

Endpoints:
    GET  /api/locations                     \u2014 list saved places
    GET  /api/locations/search?q=Boulder    \u2014 Open-Meteo geocoding proxy
    POST /api/locations                     \u2014 create (explicit or from-activity)
    PATCH /api/locations/{id}               \u2014 rename / move / set/clear default
    DELETE /api/locations/{id}
    POST /api/locations/{id}/set-default    \u2014 atomic default swap
    POST /api/activities/{id}/location      \u2014 attach a location to an activity
                                              (also exposed here so the activities
                                              router stays focused).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.clients.elevation import ElevationClient, ElevationRateLimitError
from backend.database import get_db
from backend.models import Activity, UserLocation
from backend.services.elevation_sync import recompute_for_activity

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request / response schemas ─────────────────────────────────────────


class LocationOut(BaseModel):
    id: int
    name: str
    lat: float
    lng: float
    elevation_m: float | None
    is_default: bool


class LocationCreate(BaseModel):
    """Create payload.

    Provide EITHER ``lat``+``lng`` OR ``from_activity_id``. ``elevation_m``
    is optional \u2014 when missing we resolve it via Open-Meteo.
    """
    name: str = Field(min_length=1, max_length=120)
    lat: float | None = None
    lng: float | None = None
    elevation_m: float | None = None
    from_activity_id: int | None = None
    is_default: bool = False


class LocationPatch(BaseModel):
    name: str | None = None
    lat: float | None = None
    lng: float | None = None
    elevation_m: float | None = None
    is_default: bool | None = None


class SearchHit(BaseModel):
    name: str | None
    lat: float
    lng: float
    elevation_m: float | None
    country: str | None = None
    admin1: str | None = None
    admin2: str | None = None
    population: int | None = None


class AttachLocationRequest(BaseModel):
    location_id: int


# ── Helpers ────────────────────────────────────────────────────────────


def _to_out(loc: UserLocation) -> LocationOut:
    return LocationOut(
        id=loc.id,
        name=loc.name,
        lat=loc.lat,
        lng=loc.lng,
        elevation_m=loc.elevation_m,
        is_default=loc.is_default,
    )


async def _clear_other_defaults(db: AsyncSession, keep_id: int | None) -> None:
    """Clear ``is_default`` on every row except ``keep_id`` (if any).

    Invariant: at most one default at a time. We enforce it in code rather
    than a partial unique index so SQLite doesn't fight us.
    """
    stmt = update(UserLocation).values(is_default=False)
    if keep_id is not None:
        stmt = stmt.where(UserLocation.id != keep_id)
    await db.execute(stmt)


# ── Routes ─────────────────────────────────────────────────────────────


@router.get("", response_model=list[LocationOut])
async def list_locations(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(UserLocation).order_by(
            UserLocation.is_default.desc(), UserLocation.name.asc()
        )
    )).scalars().all()
    return [_to_out(r) for r in rows]


@router.get("/search", response_model=list[SearchHit])
async def search_locations(
    q: str = Query(..., min_length=1, max_length=120),
    count: int = Query(5, ge=1, le=10),
):
    """Proxy to Open-Meteo's free geocoding API. Not persisted."""
    client = ElevationClient()
    try:
        try:
            results = await client.search_places(q, count=count)
        except ElevationRateLimitError as e:
            raise HTTPException(
                status_code=429,
                detail=f"Geocoding rate-limited: {e}",
            ) from e
        except Exception as e:
            logger.warning(f"Geocoding failed for q={q!r}: {e}")
            raise HTTPException(
                status_code=502, detail=f"Geocoding failed: {e}"
            ) from e
    finally:
        await client.close()

    return [SearchHit(**r) for r in results]


@router.post("", response_model=LocationOut, status_code=201)
async def create_location(
    payload: LocationCreate, db: AsyncSession = Depends(get_db)
):
    lat = payload.lat
    lng = payload.lng
    elevation_m = payload.elevation_m

    # Derive coords from an existing activity when requested.
    if payload.from_activity_id is not None:
        act = (await db.execute(
            select(Activity).where(Activity.id == payload.from_activity_id)
        )).scalar_one_or_none()
        if act is None:
            raise HTTPException(
                status_code=404,
                detail=f"Activity {payload.from_activity_id} not found",
            )
        if act.start_lat is None or act.start_lng is None:
            raise HTTPException(
                status_code=400,
                detail="That activity has no GPS coordinates; "
                       "pick another or enter coords directly.",
            )
        lat = act.start_lat
        lng = act.start_lng
        # Prefer the activity's own recorded elevation when available.
        if elevation_m is None and act.base_elevation_m is not None:
            elevation_m = act.base_elevation_m

    if lat is None or lng is None:
        raise HTTPException(
            status_code=400,
            detail="Must provide either {lat, lng} or {from_activity_id}.",
        )

    # Enforce unique names (friendlier message than a DB IntegrityError).
    clash = (await db.execute(
        select(UserLocation).where(UserLocation.name == payload.name)
    )).scalar_one_or_none()
    if clash is not None:
        raise HTTPException(
            status_code=409, detail=f"A location named {payload.name!r} already exists."
        )

    # Resolve elevation via Open-Meteo if the caller didn't provide one.
    if elevation_m is None:
        client = ElevationClient()
        try:
            try:
                elevation_m = await client.get_elevation(lat=lat, lng=lng)
            except ElevationRateLimitError:
                # Non-fatal \u2014 save the location without elevation and let
                # the user retry later.
                logger.warning(
                    "Elevation API rate-limited while creating location; "
                    "saving with elevation_m=None."
                )
                elevation_m = None
        finally:
            await client.close()

    loc = UserLocation(
        name=payload.name,
        lat=lat,
        lng=lng,
        elevation_m=elevation_m,
        is_default=payload.is_default,
    )
    db.add(loc)
    await db.flush()  # populate loc.id
    if payload.is_default:
        await _clear_other_defaults(db, keep_id=loc.id)
    await db.commit()
    await db.refresh(loc)
    return _to_out(loc)


@router.patch("/{location_id}", response_model=LocationOut)
async def update_location(
    location_id: int,
    payload: LocationPatch,
    db: AsyncSession = Depends(get_db),
):
    loc = (await db.execute(
        select(UserLocation).where(UserLocation.id == location_id)
    )).scalar_one_or_none()
    if loc is None:
        raise HTTPException(status_code=404, detail="Location not found")

    if payload.name is not None and payload.name != loc.name:
        clash = (await db.execute(
            select(UserLocation).where(
                UserLocation.name == payload.name,
                UserLocation.id != location_id,
            )
        )).scalar_one_or_none()
        if clash is not None:
            raise HTTPException(
                status_code=409,
                detail=f"A location named {payload.name!r} already exists.",
            )
        loc.name = payload.name

    coord_changed = False
    if payload.lat is not None:
        loc.lat = payload.lat
        coord_changed = True
    if payload.lng is not None:
        loc.lng = payload.lng
        coord_changed = True

    # Accept explicit elevation_m on PATCH; if coords changed but no elevation
    # was provided, nudge it to None so a later re-save resolves it.
    if payload.elevation_m is not None:
        loc.elevation_m = payload.elevation_m
    elif coord_changed:
        loc.elevation_m = None

    if payload.is_default is True:
        loc.is_default = True
        await _clear_other_defaults(db, keep_id=loc.id)
    elif payload.is_default is False:
        loc.is_default = False

    await db.commit()
    await db.refresh(loc)
    return _to_out(loc)


@router.delete("/{location_id}", status_code=204)
async def delete_location(
    location_id: int, db: AsyncSession = Depends(get_db)
):
    loc = (await db.execute(
        select(UserLocation).where(UserLocation.id == location_id)
    )).scalar_one_or_none()
    if loc is None:
        raise HTTPException(status_code=404, detail="Location not found")
    await db.delete(loc)
    await db.commit()
    return None


@router.post("/{location_id}/set-default", response_model=LocationOut)
async def set_default_location(
    location_id: int, db: AsyncSession = Depends(get_db)
):
    loc = (await db.execute(
        select(UserLocation).where(UserLocation.id == location_id)
    )).scalar_one_or_none()
    if loc is None:
        raise HTTPException(status_code=404, detail="Location not found")
    loc.is_default = True
    await _clear_other_defaults(db, keep_id=loc.id)
    await db.commit()
    await db.refresh(loc)
    return _to_out(loc)


# ── Activity attach endpoint ───────────────────────────────────────────
# Lives here rather than in ``routers/activities.py`` to keep all location-
# related surface in one file. Registered under /api/activities via main.


attach_router = APIRouter()


@attach_router.post("/{activity_id}/location")
async def attach_location_to_activity(
    activity_id: int,
    payload: AttachLocationRequest = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """Attach a saved location to an activity and recompute base_elevation_m."""
    activity = (await db.execute(
        select(Activity).where(Activity.id == activity_id)
    )).scalar_one_or_none()
    if activity is None:
        raise HTTPException(status_code=404, detail="Activity not found")

    loc = (await db.execute(
        select(UserLocation).where(UserLocation.id == payload.location_id)
    )).scalar_one_or_none()
    if loc is None:
        raise HTTPException(status_code=404, detail="Location not found")

    activity.location_id = loc.id
    # Use a local client so the recompute doesn't share the request event
    # loop for potentially slow external I/O.
    client = ElevationClient()
    try:
        resolved = await recompute_for_activity(db, activity, client=client)
    finally:
        await client.close()
    await db.commit()

    return {
        "activity_id": activity.id,
        "location_id": loc.id,
        "base_elevation_m": resolved,
    }


@attach_router.delete("/{activity_id}/location", status_code=204)
async def detach_location_from_activity(
    activity_id: int, db: AsyncSession = Depends(get_db)
):
    """Clear the location attachment and recompute base_elevation_m."""
    activity = (await db.execute(
        select(Activity).where(Activity.id == activity_id)
    )).scalar_one_or_none()
    if activity is None:
        raise HTTPException(status_code=404, detail="Activity not found")

    activity.location_id = None
    client = ElevationClient()
    try:
        await recompute_for_activity(db, activity, client=client)
    finally:
        await client.close()
    await db.commit()
    return None
