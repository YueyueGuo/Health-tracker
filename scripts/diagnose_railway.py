"""Read-only diagnostics against the Railway Postgres database.

Run from your laptop with the Railway DATABASE_URL injected, e.g.:

    railway run python scripts/diagnose_railway.py

or:

    DATABASE_URL='postgresql://...' python scripts/diagnose_railway.py

Emits the six queries from docs/audit-001-initial.md §3 plus a
strength_sets schema check (Bug B) and a presence check for the env
vars called out in the migration-debt section. Token values are never
printed in full — only provider, expiry, and a redacted preview.

Each check uses its own connection so one failed query (e.g. a missing
table) does not poison the rest of the diagnostic.

Output is plain text; pipe to a file or copy into
docs/audit-001-findings.md.
"""
from __future__ import annotations

import asyncio
import os
import sys
import traceback
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


RELEVANT_ENV_VARS = (
    "DATABASE_URL",
    "DATABASE_PUBLIC_URL",
    "PUBLIC_BASE_URL",
    "SYNC_ON_STARTUP",
    "SYNC_INTERVAL_HOURS",
    "STRAVA_CLIENT_ID",
    "STRAVA_CLIENT_SECRET",
    "STRAVA_ACCESS_TOKEN",
    "STRAVA_REFRESH_TOKEN",
    "EIGHT_SLEEP_EMAIL",
    "EIGHT_SLEEP_PASSWORD",
    "EIGHT_SLEEP_USER_ID",
    "EIGHT_SLEEP_REFRESH_TOKEN",
    "WHOOP_ENABLED",
    "WHOOP_CLIENT_ID",
    "WHOOP_CLIENT_SECRET",
    "WHOOP_ACCESS_TOKEN",
    "WHOOP_REFRESH_TOKEN",
    "OPENWEATHERMAP_API_KEY",
    "WEATHER_PROVIDER",
)

EXPECTED_TABLES = (
    "activities",
    "activity_laps",
    "activity_streams",
    "sleep_sessions",
    "recovery_records",
    "whoop_workouts",
    "strength_sets",
    "weather_snapshots",
    "user_locations",
    "user_profile",
    "goal",
    "recommendation_feedback",
    "oauth_tokens",
    "sync_log",
    "analysis_cache",
    "alembic_version",
)


def _async_db_url() -> str:
    url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")
    if not url:
        sys.exit(
            "DATABASE_URL is not set. Run with `railway run ...` or export the "
            "URL explicitly."
        )
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def _redact(value: str | None) -> str:
    if not value:
        return "<null>"
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}…{value[-4:]} (len={len(value)})"


def _section(title: str) -> None:
    print()
    print(f"## {title}")
    print()


async def _check_tables_present(engine: AsyncEngine) -> None:
    _section("Tables present in schema")
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = current_schema() "
                    "ORDER BY table_name"
                )
            )
        ).mappings().all()
    present = {row["table_name"] for row in rows}
    missing = [t for t in EXPECTED_TABLES if t not in present]
    extra = sorted(present - set(EXPECTED_TABLES))
    print(f"Present ({len(present)}): {', '.join(sorted(present))}")
    print()
    if missing:
        print(f">>> MISSING expected tables ({len(missing)}): "
              f"{', '.join(missing)} <<<")
    else:
        print("All expected tables present.")
    if extra:
        print(f"Extra tables not in audit list: {', '.join(extra)}")


async def _check_oauth_tokens(engine: AsyncEngine) -> None:
    _section("oauth_tokens")
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT provider, access_token, refresh_token, expires_at, "
                    "updated_at FROM oauth_tokens ORDER BY provider"
                )
            )
        ).mappings().all()
    if not rows:
        print("(no rows) — Strava and Whoop tokens have NOT been persisted to "
              "the DB. Re-run OAuth from the Railway-hosted app.")
        return
    now = datetime.now(timezone.utc)
    for row in rows:
        expires_at = row["expires_at"]
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        expired = (
            "EXPIRED" if expires_at and expires_at < now
            else "valid" if expires_at else "no-expiry"
        )
        print(
            f"- {row['provider']}: access={_redact(row['access_token'])} "
            f"refresh={_redact(row['refresh_token'])} "
            f"expires_at={expires_at} ({expired}) "
            f"updated_at={row['updated_at']}"
        )


async def _check_sync_log(engine: AsyncEngine) -> None:
    _section("sync_log — last 30 rows")
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT source, status, started_at, completed_at, "
                    "records_synced, error_message FROM sync_log "
                    "ORDER BY started_at DESC LIMIT 30"
                )
            )
        ).mappings().all()
    if not rows:
        print("(no rows) — scheduler may not have run.")
        return
    for row in rows:
        err = row["error_message"]
        # Bumped from 200 → 600 to capture full HTTP error bodies.
        err_str = f" error={err[:600]!r}" if err else ""
        print(
            f"- {row['started_at']} {row['source']:<14} "
            f"status={row['status']:<8} "
            f"records={row['records_synced']}{err_str}"
        )


async def _check_freshness_activities(engine: AsyncEngine) -> None:
    _section("Data freshness — activities (Strava)")
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT MAX(start_date) AS latest, COUNT(*) AS n "
                    "FROM activities"
                )
            )
        ).mappings().one()
    print(f"- latest={row['latest']} count={row['n']}")


async def _check_freshness_sleep(engine: AsyncEngine) -> None:
    _section("Data freshness — sleep_sessions")
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT source, MAX(date) AS latest, COUNT(*) AS n "
                    "FROM sleep_sessions GROUP BY source ORDER BY source"
                )
            )
        ).mappings().all()
    if not rows:
        print("(empty)")
        return
    for row in rows:
        print(f"- [{row['source']}] latest={row['latest']} count={row['n']}")


async def _check_freshness_recovery(engine: AsyncEngine) -> None:
    _section("Data freshness — recovery_records (Whoop)")
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT MAX(date) AS latest, COUNT(*) AS n FROM recovery_records")
            )
        ).mappings().one()
    print(f"- latest={row['latest']} count={row['n']}")


async def _check_strength_schema(engine: AsyncEngine) -> None:
    _section("strength_sets schema (Bug B)")
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT column_name, data_type, is_nullable "
                    "FROM information_schema.columns "
                    "WHERE table_schema = current_schema() "
                    "AND table_name = 'strength_sets' "
                    "ORDER BY ordinal_position"
                )
            )
        ).mappings().all()
    if not rows:
        print(">>> SMOKING GUN: strength_sets table does NOT exist. <<<")
        print(">>> This guarantees Bug B (saves would always 500). <<<")
        return
    columns = {row["column_name"] for row in rows}
    for row in rows:
        print(
            f"- {row['column_name']}: {row['data_type']} "
            f"nullable={row['is_nullable']}"
        )
    print()
    if "performed_at" not in columns:
        print(">>> SMOKING GUN: `performed_at` column is MISSING. <<<")
        print(">>> This is the likely cause of Bug B. <<<")
    else:
        print("`performed_at` is present — Bug B is NOT a missing-column issue.")


async def _check_alembic_version(engine: AsyncEngine) -> None:
    _section("alembic_version")
    async with engine.connect() as conn:
        rows = (
            await conn.execute(text("SELECT version_num FROM alembic_version"))
        ).mappings().all()
    if not rows:
        print("(empty) — Alembic table exists but no version recorded. "
              "Schema was likely created via `create_all`.")
    else:
        for row in rows:
            print(f"- version_num={row['version_num']}")


def _check_env_vars() -> None:
    _section("Railway env-var presence (values NOT printed)")
    for name in RELEVANT_ENV_VARS:
        value = os.environ.get(name)
        if value is None:
            mark = "UNSET"
        elif value == "":
            mark = "SET (empty string)"
        else:
            mark = f"SET (len={len(value)})"
        print(f"- {name}: {mark}")


async def _run_check(name, coro_factory, engine):
    try:
        await coro_factory(engine)
    except Exception as exc:  # noqa: BLE001 — diagnostic catch
        _section(f"{name} — ERROR")
        print(f"check raised: {type(exc).__name__}: {exc}")
        # Compact traceback for context without overwhelming output.
        tb = traceback.format_exception_only(type(exc), exc)
        print("".join(tb).strip())


async def main() -> None:
    print(f"# Railway diagnostics — {datetime.now(timezone.utc).isoformat()}")
    url = _async_db_url()
    if not url.startswith("postgresql"):
        sys.exit(
            f"This script targets Postgres; got {url.split('://', 1)[0]}://. "
            "Set DATABASE_URL to the Railway Postgres URL and rerun."
        )
    engine = create_async_engine(url, echo=False)
    try:
        await _run_check("Tables present", _check_tables_present, engine)
        await _run_check("oauth_tokens", _check_oauth_tokens, engine)
        await _run_check("sync_log", _check_sync_log, engine)
        await _run_check(
            "Data freshness — activities", _check_freshness_activities, engine
        )
        await _run_check(
            "Data freshness — sleep_sessions", _check_freshness_sleep, engine
        )
        await _run_check(
            "Data freshness — recovery_records", _check_freshness_recovery, engine
        )
        await _run_check(
            "strength_sets schema", _check_strength_schema, engine
        )
        await _run_check("alembic_version", _check_alembic_version, engine)
    finally:
        await engine.dispose()
    _check_env_vars()


if __name__ == "__main__":
    asyncio.run(main())
