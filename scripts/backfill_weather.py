"""Full-history weather backfill.

Walks through activities that have start_lat/start_lng but
``weather_enriched=False`` and inserts a ``WeatherSnapshot`` per
activity using the currently-configured weather provider
(``WEATHER_PROVIDER`` in ``.env``).

Safe to ctrl-C and re-run — state lives in ``activities.weather_enriched``.

Provider notes:

* **Open-Meteo** (default): free, no key, no hard daily cap. ``--max-calls``
  is mostly a courtesy cap for politeness; the client self-throttles at
  ~4 req/sec.
* **OpenWeatherMap** (fallback): 1000 calls/day + 60/min free tier.
  ``--max-calls`` defaults to 900 to leave headroom for the scheduler.
  Stops cleanly on 429 / invalid-key 401.

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

from backend.clients import get_weather_client
from backend.clients.eight_sleep import EightSleepClient
from backend.clients.strava import StravaClient
from backend.clients.weather import WeatherRateLimitError
from backend.clients.whoop import WhoopClient
from backend.config import settings
from backend.database import async_session
from backend.models import Activity, WeatherSnapshot
from backend.services.sync import SyncEngine


def _fmt_quota(q: dict) -> str:
    calls = q.get("calls_today") or 0
    limit = q.get("daily_limit") or 0
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


async def _run_once(weather, batch: int, *, dry_run: bool) -> dict:
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
        "--max-calls", type=int, default=5000,
        help=(
            "Hard cap on total API calls this run. Open-Meteo has no "
            "strict daily cap (generous fair-use), so this defaults to "
            "5000. For OpenWeatherMap the 1000/day free tier makes 900 a "
            "safer value (default: 5000)."
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Count candidates without hitting the API.",
    )
    args = parser.parse_args()

    provider = settings.weather_provider
    weather = get_weather_client()
    print(f"Weather provider: {provider}")
    if not weather.is_configured and not args.dry_run:
        print(
            "Weather provider is not configured — aborting. "
            "For OpenWeatherMap, set OPENWEATHERMAP_API_KEY in .env; "
            "for Open-Meteo no key is required (set WEATHER_PROVIDER=openmeteo)."
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
                stopped_reason = f"{provider} rate limit / auth: {e}"
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
