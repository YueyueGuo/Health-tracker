"""Postgres-only test for the autoincrement + timezone migration.

Skipped when ``TEST_POSTGRES_URL`` is unset — local SQLite test runs
remain unaffected. CI sets ``TEST_POSTGRES_URL`` (see
``.github/workflows/ci.yml``).

The test:

1. Creates a pristine schema on a fresh database in the test Postgres
   container WITHOUT any auto-increment defaults and with TIMESTAMP
   WITHOUT TIME ZONE columns — mirroring the broken Railway state that
   the migration is designed to repair.
2. Stamps Alembic to the pre-fix head, then runs ``upgrade`` through
   the new migration.
3. Asserts every affected table accepts an INSERT without supplying
   ``id`` (i.e. IDENTITY is in place).
4. Asserts a tz-aware datetime round-trips through one of the converted
   columns without losing tzinfo.
5. Asserts the migration is idempotent (re-running upgrade is a no-op).
6. Tests the downgrade.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

MIGRATION_REVISION = "a9d2f6c1e3b7"
PRE_MIGRATION_REVISION = "f9c2e1a45b80"


def _load_migration_module():
    """Load the migration module directly from its file path.

    ``alembic/versions/`` isn't a Python package (no ``__init__.py``),
    so we can't ``import alembic.versions.a9d2f...``. Loading via
    importlib gives us access to the ``IDENTITY_TABLES`` and
    ``TIMEZONE_COLUMNS`` constants without duplicating them here.
    """
    repo_root = Path(__file__).resolve().parent.parent
    path = repo_root / "alembic" / "versions" / "a9d2f6c1e3b7_pg_identity_and_tz.py"
    spec = importlib.util.spec_from_file_location(
        "migration_a9d2f6c1e3b7", path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_MIGRATION = _load_migration_module()
IDENTITY_TABLES = _MIGRATION.IDENTITY_TABLES
TIMEZONE_COLUMNS = _MIGRATION.TIMEZONE_COLUMNS


pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES_URL"),
    reason="TEST_POSTGRES_URL not set; Postgres-only migration test",
)


# Each table's minimum-viable INSERT — exactly the NOT NULL columns the
# model declares (other than id, which is what we're testing). Values
# are dialect-neutral and won't collide with each other across the
# test run.
INSERT_FIXTURES: dict[str, str] = {
    "activities": (
        "INSERT INTO activities (strava_id, name, sport_type, start_date, "
        "enrichment_status, weather_enriched, elevation_enriched) "
        "VALUES (9001, 'test', 'Run', NOW(), 'pending', FALSE, FALSE) "
        "RETURNING id"
    ),
    "activity_laps": (
        "INSERT INTO activity_laps (activity_id, lap_index) "
        "VALUES ((SELECT id FROM activities ORDER BY id DESC LIMIT 1), 1) "
        "RETURNING id"
    ),
    "activity_streams": (
        "INSERT INTO activity_streams (activity_id, stream_type, data) "
        "VALUES ((SELECT id FROM activities ORDER BY id DESC LIMIT 1), "
        "'heartrate', '[]') "
        "RETURNING id"
    ),
    "analysis_cache": (
        "INSERT INTO analysis_cache (query_hash, query_text, response_text, model) "
        "VALUES ('h1', 'q', 'r', 'm') RETURNING id"
    ),
    "goals": (
        "INSERT INTO goals (race_type, target_date) "
        "VALUES ('5k', CURRENT_DATE) RETURNING id"
    ),
    "recommendation_feedback": (
        "INSERT INTO recommendation_feedback (recommendation_date, vote) "
        "VALUES (CURRENT_DATE, 'up') RETURNING id"
    ),
    "recovery_metrics": (
        "INSERT INTO recovery_metrics (source, date) "
        "VALUES ('whoop', CURRENT_DATE) RETURNING id"
    ),
    "sleep_sessions": (
        "INSERT INTO sleep_sessions (source, date) "
        "VALUES ('whoop', CURRENT_DATE) RETURNING id"
    ),
    "strength_sets": (
        "INSERT INTO strength_sets (date, exercise_name, set_number, reps) "
        "VALUES (CURRENT_DATE, 'squat', 1, 5) RETURNING id"
    ),
    "sync_log": (
        # records_synced has a Python-side default (0) but no server
        # default, so Postgres requires it on raw INSERT.
        "INSERT INTO sync_log (source, sync_type, status, records_synced) "
        "VALUES ('strava', 'incremental', 'running', 0) RETURNING id"
    ),
    "user_locations": (
        "INSERT INTO user_locations (name, lat, lng) "
        "VALUES ('home', 37.7, -122.4) RETURNING id"
    ),
    "user_profile": (
        # user_profile uses an explicit id=1 in production code so its
        # autoincrement is only exercised when id is omitted, which we
        # test here. payload is a plain object → cast to jsonb via ::jsonb.
        "INSERT INTO user_profile (payload) VALUES ('{}'::jsonb) RETURNING id"
    ),
    "weather_snapshots": (
        "INSERT INTO weather_snapshots (activity_id) "
        "VALUES ((SELECT id FROM activities ORDER BY id DESC LIMIT 1)) "
        "RETURNING id"
    ),
    "whoop_workouts": (
        "INSERT INTO whoop_workouts (whoop_id, start) "
        "VALUES ('w-9001', NOW()) RETURNING id"
    ),
}


def _async_pg_url() -> str:
    """asyncpg URL for direct SQLAlchemy use."""
    url = os.environ["TEST_POSTGRES_URL"]
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


async def _drop_all_objects(engine) -> None:
    """Reset the schema so the migration starts on bare ground.

    Drops every table in the public schema. Safer than DROP SCHEMA
    because we don't need to re-grant privileges on the CI role.
    """
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                DO $$
                DECLARE
                    r record;
                BEGIN
                    FOR r IN (
                        SELECT tablename FROM pg_tables
                        WHERE schemaname = current_schema()
                    ) LOOP
                        EXECUTE format(
                            'DROP TABLE IF EXISTS %I CASCADE',
                            r.tablename
                        );
                    END LOOP;
                END
                $$;
                """
            )
        )


async def _seed_prefix_schema(engine) -> None:
    """Build the pre-migration schema the way Railway's was broken.

    Uses ``Base.metadata.create_all`` to lay down current model shape,
    then ALTERs every ``id`` to drop its identity and every tz-aware
    DateTime to ``TIMESTAMP WITHOUT TIME ZONE``. This is the minimal
    fixture that resembles what the v1 → Railway migration left behind.
    """
    # Import here so the skipif at module load doesn't have to import
    # the whole backend on SQLite-only runs. Importing the package is
    # enough to register every model on Base.metadata.
    import backend.models  # noqa: F401

    from backend.database import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with engine.begin() as conn:
        # Strip IDENTITY off id columns (create_all on Postgres gives
        # them GENERATED BY DEFAULT AS IDENTITY automatically — peel it
        # off to mimic the broken state).
        for table in IDENTITY_TABLES:
            await conn.execute(
                text(
                    f'ALTER TABLE "{table}" '
                    "ALTER COLUMN id DROP IDENTITY IF EXISTS"
                )
            )
            # Also drop any DEFAULT (e.g. nextval from a leftover
            # serial) so the column reproduces the Railway "no default
            # at all" state. Wrap in try/except to ignore missing
            # default (Postgres raises NoData otherwise).
            try:
                await conn.execute(
                    text(f'ALTER TABLE "{table}" ALTER COLUMN id DROP DEFAULT')
                )
            except Exception:  # noqa: BLE001
                pass

        # Flip tz-aware columns back to naive timestamps. Quote
        # identifiers because some column names (``end``) are reserved.
        for table, columns in TIMEZONE_COLUMNS.items():
            for column in columns:
                await conn.execute(
                    text(
                        f'ALTER TABLE "{table}" '
                        f'ALTER COLUMN "{column}" TYPE TIMESTAMP WITHOUT TIME ZONE '
                        f'USING "{column}" AT TIME ZONE \'UTC\''
                    )
                )


def _alembic_config(url: str) -> Config:
    # Pass config_file_name=None so Alembic doesn't call
    # logging.config.fileConfig() — that would reset the root
    # logger and break other tests' caplog assertions when the
    # migration test runs before them.
    cfg = Config()
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.set_main_option(
        "script_location",
        os.path.join(os.path.dirname(__file__), "..", "alembic"),
    )
    return cfg


async def _run_alembic(action: str, cfg: Config, revision: str) -> None:
    """Run an Alembic command in a worker thread.

    ``alembic/env.py`` calls ``asyncio.run()`` internally, which cannot
    nest inside the pytest-asyncio event loop. Off-loading to a thread
    lets Alembic spin up its own loop in isolation.
    """
    fn = {
        "stamp": command.stamp,
        "upgrade": command.upgrade,
        "downgrade": command.downgrade,
    }[action]
    await asyncio.to_thread(fn, cfg, revision)


async def test_migration_makes_inserts_succeed_and_preserves_tz():
    """End-to-end: pre-fix schema → upgrade → INSERTs succeed; tz preserved."""
    base_url = _async_pg_url()
    engine = create_async_engine(base_url, future=True)

    try:
        await _drop_all_objects(engine)
        await _seed_prefix_schema(engine)

        # Stamp Alembic to the pre-migration head so `upgrade` runs
        # just our new migration.
        cfg = _alembic_config(base_url)
        await _run_alembic("stamp", cfg, PRE_MIGRATION_REVISION)
        await _run_alembic("upgrade", cfg, MIGRATION_REVISION)

        # Idempotency check: a second upgrade is a no-op.
        await _run_alembic("upgrade", cfg, MIGRATION_REVISION)

        # 1. Every IDENTITY_TABLES table accepts an INSERT without id.
        async with engine.begin() as conn:
            for table in IDENTITY_TABLES:
                stmt = INSERT_FIXTURES[table]
                result = await conn.execute(text(stmt))
                inserted_id = result.scalar_one()
                assert isinstance(inserted_id, int), (
                    f"{table}: expected int id, got {inserted_id!r}"
                )
                assert inserted_id > 0, (
                    f"{table}: expected positive id, got {inserted_id}"
                )

        # 2. Round-trip tz-aware datetime through sync_log.started_at,
        # the simplest column among those converted.
        tz_aware = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO sync_log "
                    "(source, sync_type, started_at, status, records_synced) "
                    "VALUES ('test_tz', 'incremental', :started, 'success', 0) "
                    "RETURNING id"
                ),
                {"started": tz_aware},
            )
            sync_id = result.scalar_one()

            row = (
                await conn.execute(
                    text("SELECT started_at FROM sync_log WHERE id = :i"),
                    {"i": sync_id},
                )
            ).mappings().one()
            roundtripped = row["started_at"]
            assert roundtripped.tzinfo is not None, (
                "sync_log.started_at should retain tzinfo after migration"
            )
            assert roundtripped == tz_aware

        # 3. Every TIMEZONE_COLUMNS entry is now `timestamp with time
        # zone` in information_schema.
        async with engine.begin() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT table_name, column_name, data_type
                        FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND data_type LIKE 'timestamp%'
                        """
                    )
                )
            ).mappings().all()
        type_by_key = {(r["table_name"], r["column_name"]): r["data_type"] for r in rows}
        for table, columns in TIMEZONE_COLUMNS.items():
            for column in columns:
                key = (table, column)
                assert key in type_by_key, f"{table}.{column} missing"
                assert type_by_key[key] == "timestamp with time zone", (
                    f"{table}.{column} is {type_by_key[key]!r}, expected tz-aware"
                )

        # 4. Downgrade returns to the pre-fix state.
        await _run_alembic("downgrade", cfg, PRE_MIGRATION_REVISION)
        async with engine.begin() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT table_name, column_name, data_type
                        FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND data_type LIKE 'timestamp%'
                        """
                    )
                )
            ).mappings().all()
        type_by_key = {(r["table_name"], r["column_name"]): r["data_type"] for r in rows}
        for table, columns in TIMEZONE_COLUMNS.items():
            for column in columns:
                key = (table, column)
                assert key in type_by_key, f"{table}.{column} missing post-downgrade"
                assert type_by_key[key] == "timestamp without time zone", (
                    f"{table}.{column} should be naive after downgrade, "
                    f"got {type_by_key[key]!r}"
                )

        # IDENTITY is also dropped.
        async with engine.begin() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT table_name, is_identity
                        FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND column_name = 'id'
                          AND table_name = ANY(:tables)
                        """
                    ),
                    {"tables": list(IDENTITY_TABLES)},
                )
            ).mappings().all()
        for r in rows:
            assert r["is_identity"] == "NO", (
                f"{r['table_name']}.id is still IDENTITY after downgrade"
            )
    finally:
        # Clean up so subsequent test runs (or other tests) start fresh.
        try:
            await _drop_all_objects(engine)
        finally:
            await engine.dispose()
