"""Full-history Eight Sleep backfill.

Walks backwards 90 days at a time pulling trends + intervals and upserting
into ``sleep_sessions``. Stops after two consecutive empty windows (which
means we've walked past the first night on the Pod).

Safe to ctrl-C and re-run — incremental passes only update rows whose
fields changed, and the unique (source, date) constraint prevents dupes.

Usage:
    python scripts/backfill_eight_sleep.py
    python scripts/backfill_eight_sleep.py --days 180   # bounded window
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.clients.eight_sleep import EightSleepClient
from backend.database import async_session
from backend.services.eight_sleep_sync import sync_eight_sleep


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="If set, only pull the last N days (incremental). "
             "Omit for full history.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Log each 90-day chunk as it's fetched.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s  %(levelname)s  %(message)s",
    )

    client = EightSleepClient()
    try:
        async with async_session() as db:
            if args.days is not None:
                print(f"Pulling Eight Sleep data for the last {args.days} days...")
                count = await sync_eight_sleep(db, client, days=args.days)
            else:
                print("Backfilling full Eight Sleep history (may take a minute)...")
                count = await sync_eight_sleep(db, client, full_history=True)

        print(f"Done. {count} sleep session rows inserted or updated.")
        return 0
    finally:
        await client.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
