"""Purge cached Strava streams and reclaim SQLite file space.

This script is safe to re-run. It:
  1. Backs up the active SQLite file to `<db>.bak` (unless --skip-backup).
  2. Deletes all rows from `activity_streams`.
  3. Marks every activity as `enrichment_status='pending'` so the next
     sync pass will re-enrich them with laps + zones via the detail endpoint.
  4. Runs VACUUM to reclaim on-disk space.
  5. Prints before/after file sizes.

Usage:
    python scripts/purge_streams.py            # with backup
    python scripts/purge_streams.py --skip-backup
    python scripts/purge_streams.py --yes      # skip confirmation prompt
"""
from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from backend.config import settings


def _resolve_sqlite_path(url: str) -> Path | None:
    """Return the absolute path of the SQLite file, or None if not SQLite."""
    prefix = "sqlite+aiosqlite:///"
    if not url.startswith(prefix):
        return None
    rel = url[len(prefix):]
    return Path(rel).resolve()


def _fmt_size(bytes_: int) -> str:
    if bytes_ < 1024:
        return f"{bytes_} B"
    for unit in ("KB", "MB", "GB"):
        bytes_ /= 1024
        if bytes_ < 1024:
            return f"{bytes_:.1f} {unit}"
    return f"{bytes_:.1f} TB"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-backup", action="store_true", help="Skip the DB backup step."
    )
    parser.add_argument(
        "--yes", "-y", action="store_true", help="Skip the confirmation prompt."
    )
    args = parser.parse_args()

    db_path = _resolve_sqlite_path(settings.database_url)
    if db_path is None:
        print(
            f"Database URL is not SQLite ({settings.database_url}); "
            "this script only supports SQLite.",
            file=sys.stderr,
        )
        return 1

    if not db_path.exists():
        print(f"Database file not found at {db_path}.", file=sys.stderr)
        return 1

    size_before = db_path.stat().st_size
    print(f"Database: {db_path}")
    print(f"Size before: {_fmt_size(size_before)}")

    if not args.yes:
        resp = input(
            "Delete all activity_streams rows, reset enrichment_status, and VACUUM? [y/N] "
        ).strip().lower()
        if resp not in ("y", "yes"):
            print("Aborted.")
            return 0

    if not args.skip_backup:
        backup_path = db_path.with_suffix(db_path.suffix + ".bak")
        print(f"Backing up to {backup_path}...")
        shutil.copy2(db_path, backup_path)

    # Use a short-lived engine so the script doesn't hold a lock afterwards.
    engine = create_async_engine(settings.database_url, echo=False)

    async with engine.begin() as conn:
        result = await conn.execute(text("SELECT COUNT(*) FROM activity_streams"))
        stream_rows = result.scalar_one()
        print(f"Deleting {stream_rows} rows from activity_streams...")
        await conn.execute(text("DELETE FROM activity_streams"))

        result = await conn.execute(text("SELECT COUNT(*) FROM activities"))
        activity_rows = result.scalar_one()
        print(f"Resetting enrichment_status on {activity_rows} activities to 'pending'...")
        await conn.execute(
            text(
                "UPDATE activities "
                "SET enrichment_status='pending', enriched_at=NULL, enrichment_error=NULL"
            )
        )

    # VACUUM cannot run inside a transaction.
    async with engine.connect() as conn:
        print("Running VACUUM (this may take a few seconds)...")
        await conn.execute(text("VACUUM"))

    await engine.dispose()

    size_after = db_path.stat().st_size
    delta = size_before - size_after
    print(f"Size after:  {_fmt_size(size_after)}")
    print(f"Reclaimed:   {_fmt_size(delta)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
