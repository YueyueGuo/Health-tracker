"""User profile/preferences (singleton, single-user).

GET returns merged defaults plus stored JSON.

PATCH merges partial updates and validates the merged document.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import UserProfile

logger = logging.getLogger(__name__)
router = APIRouter()

FOCUS_VALUES = frozenset(
    {
        "General Fitness",
        "Endurance Base",
        "Event Prep",
        "Strength & Size",
        "Active Recovery",
    }
)
FREQUENCY_VALUES = frozenset(
    {"1-2 Days/wk", "3 Days/wk", "4-5 Days/wk", "6+ Days/wk"}
)
DURATION_VALUES = frozenset(["< 45m", "45-60m", "60-90m", "90m+"])
EQUIPMENT_VALUES = frozenset(
    {
        "Full Gym",
        "Dumbbells",
        "Kettlebells",
        "Pull-up Bar",
        "Running Shoes",
        "Bicycle",
        "Pool",
    }
)
LIMITATION_VALUES = frozenset(
    {
        "None",
        "Knee Pain",
        "Lower Back",
        "Shoulder",
        "Ankle/Foot",
        "Low Impact Only",
    }
)

PROFILE_DEFAULTS: dict[str, Any] = {
    "displayName": "",
    "email": "",
    "focus": "Event Prep",
    "frequency": "4-5 Days/wk",
    "duration": "45-60m",
    "equipment": ["Full Gym", "Running Shoes", "Bicycle"],
    "limitations": ["Low Impact Only"],
    "vitals": {
        "age": "32",
        "weight": "175",
        "height": "5'10\"",
        "maxHr": "192",
        "lthr": "174",
    },
}


def normalize_limitations(items: list[str]) -> list[str]:
    if not items:
        return ["None"]
    if "None" in items:
        return ["None"]
    return items


def merged_payload(stored: dict[str, Any] | None) -> dict[str, Any]:
    base = copy.deepcopy(PROFILE_DEFAULTS)
    if not stored:
        return base
    out = dict(base)
    out.update(stored)

    vb = isinstance(stored.get("vitals"), dict)
    out["vitals"] = (
        {**base["vitals"], **stored["vitals"]} if vb else dict(base["vitals"])
    )

    equip = stored.get("equipment")
    out["equipment"] = (
        list(equip)
        if isinstance(equip, list)
        else list(base["equipment"])
    )

    lim = stored.get("limitations")
    out["limitations"] = normalize_limitations(
        list(lim)
        if isinstance(lim, list)
        else list(base["limitations"])
    )
    return out


class VitalsPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    age: str = ""
    weight: str = ""
    height: str = ""
    max_hr: str = Field("", alias="maxHr")
    lthr: str = ""

    @field_validator("age", "weight", "height", "max_hr", "lthr", mode="before")
    @classmethod
    def coerce_str(cls, v: Any) -> str:
        return "" if v is None else str(v)


class ProfilePayload(BaseModel):
    """Full profile document with camelCase JSON aliases."""

    model_config = ConfigDict(populate_by_name=True)

    display_name: str = Field(alias="displayName")
    email: str = Field(alias="email")
    focus: str = Field(alias="focus")
    frequency: str = Field(alias="frequency")
    duration: str = Field(alias="duration")
    equipment: list[str]
    limitations: list[str]
    vitals: VitalsPayload

    @field_validator("focus")
    @classmethod
    def validate_focus(cls, v: str) -> str:
        if v not in FOCUS_VALUES:
            raise ValueError(f"invalid focus: {v!r}")
        return v

    @field_validator("frequency")
    @classmethod
    def validate_frequency(cls, v: str) -> str:
        if v not in FREQUENCY_VALUES:
            raise ValueError(f"invalid frequency: {v!r}")
        return v

    @field_validator("duration")
    @classmethod
    def validate_duration(cls, v: str) -> str:
        if v not in DURATION_VALUES:
            raise ValueError(f"invalid duration: {v!r}")
        return v

    @field_validator("equipment")
    @classmethod
    def validate_equipment(cls, v: list[str]) -> list[str]:
        for item in v:
            if item not in EQUIPMENT_VALUES:
                raise ValueError(f"invalid equipment: {item!r}")
        # stable unique order
        seen: set[str] = set()
        out: list[str] = []
        for item in v:
            if item not in seen:
                seen.add(item)
                out.append(item)
        return out

    @field_validator("limitations")
    @classmethod
    def validate_limitations(cls, v: list[str]) -> list[str]:
        for item in v:
            if item not in LIMITATION_VALUES:
                raise ValueError(f"invalid limitation: {item!r}")
        return normalize_limitations(list(v))


class VitalsPatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    age: str | None = None
    weight: str | None = None
    height: str | None = None
    max_hr: str | None = Field(default=None, alias="maxHr")
    lthr: str | None = None


class ProfilePatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    display_name: str | None = Field(default=None, alias="displayName", max_length=512)
    email: str | None = Field(default=None, alias="email", max_length=512)
    focus: str | None = Field(default=None, alias="focus")
    frequency: str | None = Field(default=None, alias="frequency")
    duration: str | None = Field(default=None, alias="duration")
    equipment: list[str] | None = None
    limitations: list[str] | None = None
    vitals: VitalsPatch | None = None


async def ensure_profile_row(db: AsyncSession) -> UserProfile:
    row = (
        await db.execute(select(UserProfile).where(UserProfile.id == 1))
    ).scalar_one_or_none()

    if row is not None:
        if not isinstance(row.payload, dict):
            row.payload = merged_payload(None)
            await db.commit()
            await db.refresh(row)
        return row

    merged = merged_payload(None)
    created = UserProfile(id=1, payload=merged)
    db.add(created)
    await db.commit()
    await db.refresh(created)
    return created


def _apply_patch(existing: dict[str, Any], patch: ProfilePatch) -> dict[str, Any]:
    result = merged_payload(existing)
    data = patch.model_dump(exclude_unset=True, by_alias=True)

    for key in ("displayName", "email", "focus", "frequency", "duration"):
        if key in data and data[key] is not None:
            result[key] = data[key]

    if data.get("equipment") is not None:
        result["equipment"] = data["equipment"]

    if data.get("limitations") is not None:
        result["limitations"] = normalize_limitations(list(data["limitations"]))

    vitals_partial = patch.vitals
    if vitals_partial is not None:
        vv = vitals_partial.model_dump(exclude_unset=True, by_alias=True)
        base_vitals = dict(result["vitals"])
        for kk, val in vv.items():
            if val is not None:
                base_vitals[kk] = val
        result["vitals"] = base_vitals

    validated = ProfilePayload.model_validate(result)
    return validated.model_dump(mode="json", by_alias=True)


@router.get("", response_model=dict)
async def get_profile(db: AsyncSession = Depends(get_db)):
    row = await ensure_profile_row(db)
    merged = merged_payload(row.payload)
    try:
        validated = ProfilePayload.model_validate(merged)
    except Exception as exc:
        logger.warning("repairing corrupted profile payload: %s", exc)
        repaired = merged_payload(None)
        row.payload = repaired
        await db.commit()
        validated = ProfilePayload.model_validate(repaired)
    return validated.model_dump(mode="json", by_alias=True)


@router.patch("", response_model=dict)
async def patch_profile(payload: ProfilePatch, db: AsyncSession = Depends(get_db)):
    row = await ensure_profile_row(db)
    try:
        new_payload = _apply_patch(row.payload if isinstance(row.payload, dict) else {}, payload)
    except Exception as exc:
        logger.info("profile validation failed: %s", exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    row.payload = new_payload
    await db.commit()
    await db.refresh(row)
    validated = ProfilePayload.model_validate(row.payload)
    return validated.model_dump(mode="json", by_alias=True)
