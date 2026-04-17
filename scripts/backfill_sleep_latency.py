"""Recompute sleep latency from existing raw_data.interval.stages.

For every SleepSession where source == 'eight_sleep' AND raw_data carries
an interval with a stages array, recompute latency using the new
first-awake-chunk logic in `_wake_stats`. Falls back gracefully when
stages data is missing.

Idempotent — safe to re-run.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from backend.database import async_session
from backend.models.sleep import SleepSession
from backend.services.eight_sleep_sync import _wake_stats


async def main():
    updated = 0
    skipped_no_stages = 0
    unchanged = 0

    async with async_session() as db:
        rows = (
            await db.scalars(
                select(SleepSession).where(SleepSession.source == "eight_sleep")
            )
        ).all()

        for row in rows:
            interval = (row.raw_data or {}).get("interval")
            if not interval or not interval.get("stages"):
                skipped_no_stages += 1
                continue

            stats = _wake_stats(interval)
            new_latency = stats.get("latency_sec")
            if new_latency is None:
                continue

            if row.latency == new_latency:
                unchanged += 1
                continue

            print(
                f"{row.date} src={row.source} "
                f"old_latency={row.latency}s new_latency={new_latency}s "
                f"(waso_min={stats.get('waso_duration')})"
            )
            row.latency = new_latency
            updated += 1

        await db.commit()

    print()
    print(f"updated:            {updated}")
    print(f"unchanged:          {unchanged}")
    print(f"skipped (no stages):{skipped_no_stages}")


if __name__ == "__main__":
    asyncio.run(main())
