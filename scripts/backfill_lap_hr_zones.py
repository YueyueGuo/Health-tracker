"""Backfill ``activity_laps.hr_zone`` from cached ``activities.zones_data``.

One-shot, fully offline (no API calls). Walks every lap with
``hr_zone IS NULL AND average_heartrate IS NOT NULL``, looks up the parent
activity's ``zones_data``, and persists the assigned 1-indexed HR zone.

Idempotent and resumable (state lives in ``activity_laps.hr_zone``).

Usage::

    python scripts/backfill_lap_hr_zones.py
    python scripts/backfill_lap_hr_zones.py --dry-run
    python scripts/backfill_lap_hr_zones.py --batch 500
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, select

from backend.database import async_session
from backend.models import Activity, ActivityLap
from backend.services.hr_zones import assign_lap_hr_zone


async def _pending_count() -> int:
    async with async_session() as db:
        return (await db.execute(
            select(func.count()).select_from(ActivityLap).where(
                ActivityLap.hr_zone.is_(None),
                ActivityLap.average_heartrate.is_not(None),
            )
        )).scalar_one()


async def _run(batch: int, dry_run: bool) -> None:
    pending = await _pending_count()
    print(f"laps with HR but no hr_zone: {pending}")
    if pending == 0:
        return

    assigned = 0
    skipped_no_zones = 0
    processed = 0
    last_progress = 0

    while True:
        async with async_session() as db:
            laps = (await db.execute(
                select(ActivityLap).where(
                    ActivityLap.hr_zone.is_(None),
                    ActivityLap.average_heartrate.is_not(None),
                ).limit(batch)
            )).scalars().all()
            if not laps:
                break

            activity_ids = {lap.activity_id for lap in laps}
            activities = (await db.execute(
                select(Activity).where(Activity.id.in_(activity_ids))
            )).scalars().all()
            zones_by_aid = {a.id: a.zones_data for a in activities}

            for lap in laps:
                zones = zones_by_aid.get(lap.activity_id)
                zone = assign_lap_hr_zone(lap.average_heartrate, zones)
                if zone is None:
                    skipped_no_zones += 1
                    # Mark with 0 to skip on future runs? No — leave NULL
                    # so a future zones_data fetch can pick it up.
                    continue
                if not dry_run:
                    lap.hr_zone = zone
                assigned += 1

            processed += len(laps)
            if not dry_run:
                await db.commit()

        if dry_run:
            # Without persistence we'd loop forever; one batch is enough
            # for a sample.
            break

        if processed - last_progress >= 1000:
            print(
                f"  processed={processed} assigned={assigned} "
                f"skipped_no_zones={skipped_no_zones}"
            )
            last_progress = processed

    print(
        f"done. processed={processed} assigned={assigned} "
        f"skipped_no_zones={skipped_no_zones}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=int, default=500, help="laps per iteration")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="count only; don't persist",
    )
    args = parser.parse_args()
    asyncio.run(_run(batch=args.batch, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
