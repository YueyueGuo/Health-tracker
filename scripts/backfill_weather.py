"""Full-history OpenWeatherMap backfill.

Walks through activities that have start_lat/start_lng but
``weather_enriched=False`` and inserts a ``WeatherSnapshot`` per activity
using the One Call 3.0 timemachine endpoint.

Safe to ctrl-C and re-run — state lives in ``activities.weather_enriched``.

The free tier allows 1000 calls/day and 60 calls/min. The WeatherClient
self-throttles at ~1 call/sec, and this script caps total calls at
``--max-calls`` (default 900) so a single run stays well under the soft
daily cap. It also stops cleanly on 429 / invalid-key 401 responses.

Usage::

    python scripts/backfill_weather.py
    python scripts/backfill_weather.py --batch 100
    python scripts/backfill_weather.py --dry-run          # count only
    python scripts/backfill_weather.py --max-calls 300    # tighter safety
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, select

from backend.clients.eight_sleep import EightSleepClient
from backend.clients.strava import StravaClient
from backend.clients.weather import WeatherClient, WeatherRateLimitError
from backend.clients.whoop import WhoopClient
from backend.database import async_session
from backend.models import Activity, WeatherSnapshot
from backend.services.sync import SyncEngine


def _fmt_quota(q: dict) -> str:
    calls = q.get("calls_today") or 0
    limit = q.get("daily_limit") or 1000
    return f"calls_today={calls}/{limit}"


async def _snapshot_count() -> int:
    async with async_session() as db:
        return (await db.execute(
            select(func.count()).select_from(WeatherSnapshot)
        )).scalar_one()


async def _pending_count() -> int:
    async with async_session() as db:
        return (await db.execute(
            select(func.count()).select_from(Activity).where(
                Activity.weather_enriched == False,  # noqa: E712
                Activity.start_lat.isnot(None),
                Activity.start_lng.isnot(None),
            )
        )).scalar_one()


async def _run_once(weather: WeatherClient, batch: int, *, dry_run: bool) -> dict:
    """One iteration of sync_weather against a fresh DB session."""
    async with async_session() as db:
        engine = SyncEngine(
            db,
            StravaClient(),
            EightSleepClient(),
            WhoopClient(),
            weather,
        )
        return await engine.sync_weather(limit=batch, dry_run=dry_run)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--batch", type=int, default=50,
        help="Activities to enrich per iteration (default: 50).",
    )
    parser.add_argument(
        "--max-calls", type=int, default=900,
        help=(
            "Hard cap on total API calls this run. OpenWeatherMap's free "
            "tier is 1000 calls/day; 900 leaves headroom for the scheduler "
            "(default: 900)."
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Count candidates without hitting the API.",
    )
    args = parser.parse_args()

    weather = WeatherClient()
    if not weather.is_configured and not args.dry_run:
        print(
            "OPENWEATHERMAP_API_KEY is not set — aborting. "
            "Add it to .env or run with --dry-run."
        )
        await weather.close()
        return 1

    try:
        start_pending = await _pending_count()
        start_snaps = await _snapshot_count()
        start_quota = weather.quota_usage()
        print(
            f"Starting weather backfill: "
            f"pending={start_pending}  snapshots={start_snaps}  "
            f"quota={_fmt_quota(start_quota)}"
        )

        if args.dry_run:
            result = await _run_once(weather, batch=args.batch, dry_run=True)
            print(
                f"\n[dry-run] would process up to {args.batch} of "
                f"{result['remaining']} pending activities."
            )
            return 0

        iteration = 0
        total_enriched = 0
        stopped_reason: str | None = None

        while True:
            iteration += 1
            pending = await _pending_count()
            if pending == 0:
                stopped_reason = "complete"
                break

            quota = weather.quota_usage()
            calls = int(quota.get("calls_today") or 0)
            if calls >= args.max_calls:
                stopped_reason = (
                    f"max-calls cap reached ({calls}/{args.max_calls})"
                )
                break

            # Size this batch so we never exceed --max-calls on one pass.
            remaining_budget = args.max_calls - calls
            effective_batch = min(args.batch, max(1, remaining_budget))

            print(
                f"\n=== Iteration {iteration} | "
                f"pending={pending}  "
                f"quota={_fmt_quota(quota)}  "
                f"batch={effective_batch} ==="
            )

            try:
                result = await _run_once(
                    weather, batch=effective_batch, dry_run=False
                )
            except WeatherRateLimitError as e:
                stopped_reason = f"OpenWeatherMap rate limit / auth: {e}"
                break

            enriched = result["enriched"]
            total_enriched += enriched
            print(
                f"  enriched={enriched}  skipped={result['skipped']}  "
                f"failed={result['failed']}  remaining={result['remaining']}"
            )

            if enriched == 0:
                # Either all activities in this batch were skipped/failed
                # or we hit a rate limit inside sync_weather (which swallows
                # WeatherRateLimitError and commits). Don't loop forever.
                stopped_reason = "no activities enriched in last iteration"
                break

        end_snaps = await _snapshot_count()
        end_pending = await _pending_count()
        end_quota = weather.quota_usage()
        print(
            f"\nDone ({stopped_reason or 'complete'}). "
            f"enriched_this_run={total_enriched}  "
            f"snapshots={end_snaps} (+{end_snaps - start_snaps})  "
            f"pending={end_pending}  "
            f"quota={_fmt_quota(end_quota)}"
        )
        return 0
    finally:
        await weather.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
