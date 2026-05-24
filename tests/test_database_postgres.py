"""Postgres-branch coverage for ``_ensure_compat_schema``.

The SQLite branch is exercised by ``tests/test_database.py``; the
Postgres branch (``backend/database.py:90-103``) was previously
untested. This module is gated on ``TEST_POSTGRES_URL`` so local SQLite
test runs still pass — CI sets the env var via the Postgres service
container declared in ``.github/workflows/ci.yml``.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from backend.database import _ensure_compat_schema


TEST_POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    not TEST_POSTGRES_URL,
    reason="TEST_POSTGRES_URL not set; skipping Postgres compat-schema test",
)


@pytest.fixture
async def pg_engine():
    """Async engine bound to ``TEST_POSTGRES_URL``.

    Drops the ``strength_sets`` table on entry AND exit so the test
    module is hermetic across re-runs.

    .. warning::
        This fixture mutates shared Postgres state on the
        ``TEST_POSTGRES_URL`` database. It is safe under default pytest
        execution (modules run sequentially), but it must not run
        concurrently with other modules that touch ``strength_sets``
        (e.g. ``tests/test_migrations_autoincrement_timezone.py``,
        which drops/recreates the entire public schema). If
        ``pytest-xdist`` is ever added, each test will need its own
        schema (``SET search_path TO test_strength_<pid>``) to remain
        hermetic.
    """
    engine = create_async_engine(TEST_POSTGRES_URL)
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS strength_sets CASCADE"))
    yield engine
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS strength_sets CASCADE"))
    await engine.dispose()


async def test_compat_schema_adds_strength_performed_at_column_on_postgres(
    pg_engine,
):
    """Mirror of the SQLite test: create a stripped-down strength_sets
    table without ``performed_at``, run ``_ensure_compat_schema``,
    assert the column is added.
    """
    async with pg_engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE strength_sets (
                    id SERIAL PRIMARY KEY,
                    reps INTEGER NOT NULL
                )
                """
            )
        )

        # Idempotency check: running twice must not raise.
        await _ensure_compat_schema(conn)
        await _ensure_compat_schema(conn)

        rows = (
            await conn.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'strength_sets'
                    """
                )
            )
        ).mappings()
        columns = {row["column_name"] for row in rows}

    assert "performed_at" in columns


async def test_compat_schema_noop_when_performed_at_already_present(
    pg_engine,
):
    """If ``performed_at`` is already on the table, the helper must be
    a no-op (no error, no duplicate column).
    """
    async with pg_engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE strength_sets (
                    id SERIAL PRIMARY KEY,
                    reps INTEGER NOT NULL,
                    performed_at TIMESTAMP
                )
                """
            )
        )

        await _ensure_compat_schema(conn)

        rows = (
            await conn.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'strength_sets'
                    """
                )
            )
        ).mappings()
        column_names = [row["column_name"] for row in rows]

    assert column_names.count("performed_at") == 1
