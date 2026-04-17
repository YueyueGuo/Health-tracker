"""Full-history elevation backfill.

Two phases, both safe to ctrl-C and re-run (state lives in
``activities.elevation_enriched`` + ``activities.base_elevation_m``):

1. **Strava promotion** \u2014 re-read ``Activity.raw_data`` for every row
   with ``elevation_enriched=False`` and populate ``elev_high_m`` /
   ``elev_low_m`` / ``base_elevation_m`` from the cached detail blob.
   No network calls. Fast. Covers every already-enriched outdoor
   activity immediately.

2. **Open-Meteo fallback** \u2014 for remaining rows that still lack
   ``base_elevation_m`` but have ``start_lat``/``start_lng``, call the
   Open-Meteo elevation API. Self-throttled at ~4 req/sec. Stops
   cleanly on ``ElevationRateLimitError``.

Activities with no coords at all are handled in Phase 2 too \u2014 if the
user has a default ``UserLocation`` configured its elevation is applied;
otherwise the row is marked ``elevation_enriched=True`` with
``base_elevation_m=NULL`` so we stop re-visiting it.

Usage::

    python scripts/backfill_elevation.py                    # full run
    python scripts/backfill_elevation.py --phase1-only      # no API calls
    python scripts/backfill_elevation.py --dry-run          # count only
    python scripts/backfill_elevation.py --batch 100        # per-iter cap
    python scripts/backfill_elevation.py --max-calls 500    # tighter budget
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, select

from backend.clients.elevation import ElevationClient, ElevationRateLimitError
from backend.database import async_session
from backend.models import Activity
from backend.services.elevation_sync import (
    extract_elev_from_raw,
    sync_elevation as _run_sync_elevation,
)


def _fmt_quota(q: dict) -> str:
    calls = q.get("calls_today") or 0
    limit = q.get("daily_limit") or 0
    return f"calls_today={calls}/{limit}"


async def _pending_count() -> int:
    async with async_session() as db:
        return (await db.execute(
            select(func.count()).select_from(Activity).where(
                Activity.elevation_enriched == False,  # noqa: E712
            )
        )).scalar_one()


async def _phase1_promote() -> dict[str, int]:
    """Pure DB pass: promote elev_high/low from each activity's cached raw_data.

    For rows where ``elev_low`` is present, also seed ``base_elevation_m`` and
    flip ``elevation_enriched=True`` so Phase 2 skips them.
    """
    promoted = 0
    base_seeded = 0
    scanned = 0
    async with async_session() as db:
        # Process in chunks so we don't hold a huge transaction open.
        # IMPORTANT: do NOT use OFFSET here — the WHERE clause filters on
        # ``elevation_enriched == False`` and we flip that flag as we go,
        # so the same OFFSET would skip unprocessed rows. Instead we
        # re-query the first ``page_size`` rows each iteration and rely on
        # the WHERE to narrow the worklist.
        page_size = 500
        while True:
            rows = (await db.execute(
                select(Activity)
                .where(Activity.elevation_enriched == False)  # noqa: E712
                .where(Activity.raw_data.isnot(None))
                .order_by(Activity.id)
                .limit(page_size)
            )).scalars().all()
            if not rows:
                break

            progress_made = False
            for activity in rows:
                scanned += 1
                extracted = extract_elev_from_raw(activity.raw_data)
                did_promote = False
                if extracted:
                    if (
                        "elev_high_m" in extracted
                        and activity.elev_high_m is None
                    ):
                        activity.elev_high_m = extracted["elev_high_m"]
                        did_promote = True
                    if (
                        "elev_low_m" in extracted
                        and activity.elev_low_m is None
                    ):
                        activity.elev_low_m = extracted["elev_low_m"]
                        did_promote = True
                if did_promote:
                    promoted += 1
                # Flip enriched=True for any row where we now have
                # elev_low_m available. If raw_data lacked it (indoor
                # activities), we leave enriched=False so Phase 2 /
                # default-location logic can handle it.
                if activity.elev_low_m is not None and (
                    activity.base_elevation_m is None
                    or not activity.elevation_enriched
                ):
                    activity.base_elevation_m = activity.elev_low_m
                    activity.elevation_enriched = True
                    base_seeded += 1
                    progress_made = True

            await db.commit()

            # If a full page passed without any row being flipped, the
            # remaining rows in the worklist have no usable elev_low
            # (indoor / no-GPS). Stop to avoid an infinite loop re-fetching
            # the same page.
            if not progress_made:
                break

    return {
        "scanned": scanned,
        "promoted": promoted,
        "base_seeded": base_seeded,
    }


async def _phase2_run_once(client, batch: int, *, dry_run: bool) -> dict:
    async with async_session() as db:
        return await _run_sync_elevation(
            db, client, limit=batch, dry_run=dry_run
        )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--batch", type=int, default=50,
        help="Phase 2 activities per iteration (default: 50).",
    )
    parser.add_argument(
        "--max-calls", type=int, default=5000,
        help="Hard cap on Open-Meteo calls this run (default: 5000).",
    )
    parser.add_argument(
        "--phase1-only", action="store_true",
        help="Run only the Strava-promotion phase; skip all API calls.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Count candidates without writes or API calls.",
    )
    args = parser.parse_args()

    start_pending = await _pending_count()
    print(f"Starting elevation backfill: pending={start_pending}")

    if args.dry_run:
        # Just count what Phase 2 would do next.
        client = ElevationClient()
        try:
            result = await _phase2_run_once(
                client, batch=args.batch, dry_run=True
            )
        finally:
            await client.close()
        print(
            f"\n[dry-run] pending={start_pending}  "
            f"Phase 2 would process up to {args.batch} of "
            f"{result['remaining']} pending activities."
        )
        return 0

    # ── Phase 1: pure DB promotion ─────────────────────────────────
    phase1 = await _phase1_promote()
    mid_pending = await _pending_count()
    print(
        f"\nPhase 1 (Strava promotion) done: "
        f"scanned={phase1['scanned']}  "
        f"promoted={phase1['promoted']}  "
        f"base_seeded={phase1['base_seeded']}  "
        f"pending now={mid_pending}"
    )

    if args.phase1_only or mid_pending == 0:
        print(f"\nDone. pending={mid_pending}")
        return 0

    # ── Phase 2: Open-Meteo fallback + default-location apply ─────
    client = ElevationClient()
    try:
        iteration = 0
        total_enriched = 0
        stopped_reason: str | None = None

        while True:
            iteration += 1
            pending = await _pending_count()
            if pending == 0:
                stopped_reason = "complete"
                break

            quota = client.quota_usage()
            calls = int(quota.get("calls_today") or 0)
            if calls >= args.max_calls:
                stopped_reason = (
                    f"max-calls cap reached ({calls}/{args.max_calls})"
                )
                break

            remaining_budget = args.max_calls - calls
            effective_batch = min(args.batch, max(1, remaining_budget))

            print(
                f"\n=== Phase 2 iter {iteration} | "
                f"pending={pending}  "
                f"quota={_fmt_quota(quota)}  "
                f"batch={effective_batch} ==="
            )

            try:
                result = await _phase2_run_once(
                    client, batch=effective_batch, dry_run=False
                )
            except ElevationRateLimitError as e:
                stopped_reason = f"open-meteo rate limit: {e}"
                break

            enriched = result["enriched"]
            total_enriched += enriched
            print(
                f"  enriched={enriched}  skipped={result['skipped']}  "
                f"failed={result['failed']}  remaining={result['remaining']}"
            )

            if enriched == 0 and result["skipped"] == 0:
                stopped_reason = "no activities processed in last iteration"
                break

        end_pending = await _pending_count()
        end_quota = client.quota_usage()
        print(
            f"\nDone ({stopped_reason or 'complete'}). "
            f"phase2_enriched={total_enriched}  "
            f"pending={end_pending}  "
            f"quota={_fmt_quota(end_quota)}"
        )
        return 0
    finally:
        await client.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
