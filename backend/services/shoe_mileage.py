"""Compute cumulative shoe mileage on demand.

We deliberately avoid a stored counter on ``shoes``: the source of
truth is the tagged Strava ``Activity`` rows + Apple Health ``Workout``
rows. Mileage is reported as the SUM of their ``distance`` /
``distance_m`` columns (meters in both cases).
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Activity, Workout


async def cumulative_distance_m(db: AsyncSession, shoe_id: int) -> float:
    """Return the cumulative tagged distance (in meters) for one shoe.

    Two scalar selects merged at the Python layer — one query per
    source table — coalescing NULLs to ``0.0``. Returning a float (not
    ``Decimal``) keeps the value JSON-serializable straight out of the
    router.
    """
    strava_sum = (
        await db.execute(
            select(func.coalesce(func.sum(Activity.distance), 0.0)).where(
                Activity.shoe_id == shoe_id
            )
        )
    ).scalar_one()
    apple_sum = (
        await db.execute(
            select(func.coalesce(func.sum(Workout.distance_m), 0.0)).where(
                Workout.shoe_id == shoe_id
            )
        )
    ).scalar_one()
    return float(strava_sum) + float(apple_sum)


async def cumulative_distance_bulk(
    db: AsyncSession, shoe_ids: Iterable[int]
) -> dict[int, float]:
    """Grouped variant — two queries total regardless of how many shoes.

    Shoes with no tagged activities won't appear in the returned dict;
    callers should default-fill from the input ``shoe_ids`` if they
    want a value for every requested shoe.
    """
    ids = list(shoe_ids)
    if not ids:
        return {}

    out: dict[int, float] = {}

    strava_rows = (
        await db.execute(
            select(
                Activity.shoe_id,
                func.coalesce(func.sum(Activity.distance), 0.0),
            )
            .where(Activity.shoe_id.in_(ids))
            .group_by(Activity.shoe_id)
        )
    ).all()
    for shoe_id, total in strava_rows:
        if shoe_id is None:
            continue
        out[shoe_id] = out.get(shoe_id, 0.0) + float(total)

    apple_rows = (
        await db.execute(
            select(
                Workout.shoe_id,
                func.coalesce(func.sum(Workout.distance_m), 0.0),
            )
            .where(Workout.shoe_id.in_(ids))
            .group_by(Workout.shoe_id)
        )
    ).all()
    for shoe_id, total in apple_rows:
        if shoe_id is None:
            continue
        out[shoe_id] = out.get(shoe_id, 0.0) + float(total)

    return out


def percent_used(total_usable_m: float | None, cumulative_m: float) -> float | None:
    """Percent of the user-configured lifespan that's been consumed.

    Returns ``None`` when the user hasn't set a target (the UI then
    omits the progress bar). Values above 100 are allowed — overdue
    shoes are a frontend styling decision, not a backend cap.
    """
    if total_usable_m is None or total_usable_m <= 0:
        return None
    return 100.0 * cumulative_m / total_usable_m
