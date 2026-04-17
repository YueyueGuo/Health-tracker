"""Full-history Strava backfill.

Runs in two phases, using the same code paths the scheduler uses:

  Phase A (once): list every activity on Strava and upsert summary rows
      with enrichment_status='pending'. Costs ~1 API call per 100 activities.

  Phase B (looped): enrich pending activities (detail + zones) most-recent-
      first. When Strava's rate limit nears exhaustion, sleeps 15 minutes
      (the short window resets then) and resumes. Exits when all pending
      rows are enriched or when the daily cap is hit.

Safe to ctrl-C and re-run: state lives in the `enrichment_status` column.

Usage:
    python scripts/backfill_strava.py
    python scripts/backfill_strava.py --no-list   # skip Phase A, only enrich
    python scripts/backfill_strava.py --batch 20  # cap per Phase B iteration
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, select

from backend.clients.eight_sleep import EightSleepClient
from backend.clients.strava import StravaClient
from backend.clients.weather import WeatherClient
from backend.clients.whoop import WhoopClient
from backend.database import async_session
from backend.models import Activity
from backend.services.sync import SyncEngine

SHORT_WINDOW_SLEEP_SECONDS = 15 * 60 + 30  # 15min + buffer


def _fmt_quota(q: dict) -> str:
    short = f"{q.get('short_used')}/{q.get('short_limit')}"
    long = f"{q.get('long_used')}/{q.get('long_limit')}"
    return f"short={short} daily={long}"


async def _phase_a(strava: StravaClient) -> int:
    """Run Phase A (list all activities). Returns new-row count."""
    async with async_session() as db:
        engine = SyncEngine(
            db, strava, EightSleepClient(), WhoopClient(), WeatherClient()
        )
        print("Phase A: listing all activities from Strava...")
        new_count = await engine._strava_phase_a(full_history=True)
        print(f"  -> {new_count} new activities listed.")
        return new_count


async def _phase_b_once(strava: StravaClient, batch: int) -> int:
    """Run one Phase B iteration. Returns enriched count."""
    async with async_session() as db:
        engine = SyncEngine(
            db, strava, EightSleepClient(), WhoopClient(), WeatherClient()
        )
        enriched = await engine._strava_phase_b(limit=batch)
        return enriched


async def _pending_count() -> int:
    async with async_session() as db:
        return (await db.execute(
            select(func.count()).select_from(Activity)
            .where(Activity.enrichment_status == "pending")
        )).scalar_one()


async def _completion_counts() -> dict[str, int]:
    async with async_session() as db:
        rows = (await db.execute(
            select(Activity.enrichment_status, func.count())
            .group_by(Activity.enrichment_status)
        )).all()
    return {row[0]: row[1] for row in rows}


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-list", action="store_true", help="Skip Phase A.")
    parser.add_argument(
        "--batch", type=int, default=40,
        help="Max activities to enrich per Phase B iteration (default: 40). "
             "Keeping this below the short-window limit leaves room for "
             "other Strava calls (like /athlete).",
    )
    args = parser.parse_args()

    strava = StravaClient()
    try:
        if not args.no_list:
            await _phase_a(strava)

        iteration = 0
        total_enriched = 0
        while True:
            iteration += 1
            pending = await _pending_count()
            if pending == 0:
                print("\nNo pending activities remaining. Done.")
                break

            counts = await _completion_counts()
            print(
                f"\n=== Iteration {iteration} | "
                f"pending={counts.get('pending', 0)} "
                f"complete={counts.get('complete', 0)} "
                f"failed={counts.get('failed', 0)} | "
                f"quota {_fmt_quota(strava.quota_usage())} ==="
            )

            enriched = await _phase_b_once(strava, batch=args.batch)
            total_enriched += enriched
            print(f"Iteration {iteration}: enriched {enriched} activities.")

            q = strava.quota_usage()
            long_used = q.get("long_used") or 0
            long_limit = q.get("long_limit") or 1000
            if long_used >= long_limit * 0.98:
                print(
                    f"\nDaily quota nearly exhausted ({long_used}/{long_limit}). "
                    f"Stop and rerun tomorrow to continue."
                )
                break

            if enriched == 0:
                # Either rate-limited or a bunch of hard errors. If there are
                # still pending rows, sleep one short-window and retry.
                if (await _pending_count()) > 0:
                    print(
                        f"Short-window quota likely hit; sleeping "
                        f"{SHORT_WINDOW_SLEEP_SECONDS}s until the 15-min "
                        f"window resets..."
                    )
                    time.sleep(SHORT_WINDOW_SLEEP_SECONDS)
                else:
                    break

        counts = await _completion_counts()
        print(
            f"\nFinal: complete={counts.get('complete', 0)} "
            f"pending={counts.get('pending', 0)} "
            f"failed={counts.get('failed', 0)} | "
            f"enriched this run: {total_enriched}"
        )
        return 0
    finally:
        await strava.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
