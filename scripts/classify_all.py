"""Classify all enriched activities that don't yet have a classification.

Safe to re-run. Only touches rows where enrichment_status='complete'. Can
be invoked after rule tweaks with --force to reclassify everything.

Usage:
    python scripts/classify_all.py
    python scripts/classify_all.py --force       # reclassify ALL complete rows
    python scripts/classify_all.py --sport Run   # limit by sport_type
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from backend.database import async_session
from backend.models import Activity, ActivityLap
from backend.services.classifier import classify_and_persist


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true",
        help="Reclassify activities that already have a classification.",
    )
    parser.add_argument(
        "--sport", default=None,
        help="Only classify activities matching this sport_type (e.g. Run, Ride).",
    )
    args = parser.parse_args()

    async with async_session() as db:
        q = select(Activity).where(Activity.enrichment_status == "complete")
        if not args.force:
            q = q.where(Activity.classification_type.is_(None))
        if args.sport:
            q = q.where(Activity.sport_type == args.sport)
        q = q.order_by(Activity.start_date.desc())

        activities = (await db.execute(q)).scalars().all()
        print(f"Classifying {len(activities)} activities...\n")

        counts: Counter = Counter()
        skipped = 0
        for a in activities:
            laps = (await db.execute(
                select(ActivityLap)
                .where(ActivityLap.activity_id == a.id)
                .order_by(ActivityLap.lap_index)
            )).scalars().all()
            result = classify_and_persist(a, list(laps))
            if result is None:
                skipped += 1
            else:
                counts[result.type] += 1

        await db.commit()

        print("Type distribution:")
        for t, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"  {t}: {n}")
        if skipped:
            print(f"\nSkipped (no classifier for sport): {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
