"""Round-trip tz-aware datetimes through the columns the audit-001
timezone sweep converted.

Context
-------
Commits ``e87220f`` and ``35d648f`` added ``timezone=True`` to every
``DateTime`` column declaration in ``backend/models/``. Four of those
columns were documented in ``docs/audit-001-initial.md`` as
intentionally naive-local:

* ``Activity.start_date_local``
* ``SleepSession.bed_time`` / ``SleepSession.wake_time``
* ``StrengthSet.performed_at``

This test module locks in the post-sweep contract: a tz-aware UTC
datetime can be written to each of those columns and read back without
loss of tzinfo (Postgres) or without raising (SQLite — which doesn't
enforce a tz type but should still accept the value).

See ``docs/audit-001-datetime-sweep-audit.md`` for the full audit.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.database import Base
from backend.models import Activity, SleepSession, StrengthSet


SAMPLE_TZ_AWARE = datetime(2026, 4, 16, 12, 34, 56, tzinfo=timezone.utc)


def _async_pg_url() -> str | None:
    """Return a Postgres asyncpg URL if ``TEST_POSTGRES_URL`` is set."""
    url = os.environ.get("TEST_POSTGRES_URL")
    if not url:
        return None
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def _sqlite_url() -> str:
    return "sqlite+aiosqlite:///:memory:"


async def _make_session(url: str) -> tuple[AsyncSession, "create_async_engine"]:
    engine = create_async_engine(url, future=True)
    async with engine.begin() as conn:
        # Drop tables first when running against the shared Postgres test
        # DB so previous test runs don't leak rows / leftover constraints.
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    return Session, engine


def _engines_to_test() -> list[tuple[str, str]]:
    """Return ``(name, url)`` pairs for each engine we should round-trip on."""
    engines: list[tuple[str, str]] = [("sqlite", _sqlite_url())]
    pg = _async_pg_url()
    if pg is not None:
        engines.append(("postgres", pg))
    return engines


# Parametrize each round-trip on every available engine so the SQLite
# branch always runs and the Postgres branch runs when configured. We
# use ids= so xfailing or running a single backend is easy from pytest.
ENGINE_IDS = [name for name, _ in _engines_to_test()]
ENGINE_URLS = [url for _, url in _engines_to_test()]


@pytest.mark.parametrize("engine_url", ENGINE_URLS, ids=ENGINE_IDS)
async def test_activity_start_date_local_accepts_tz_aware(engine_url: str):
    """``Activity.start_date_local`` round-trips a tz-aware datetime.

    Strava's sync code parses ``raw["start_date_local"]`` via
    ``datetime.fromisoformat(...).replace("Z", "+00:00")``, which already
    yields a tz-aware datetime. This test pins that contract.
    """
    Session, engine = await _make_session(engine_url)
    try:
        async with Session() as session:
            row = Activity(
                strava_id=987_654,
                name="audit round-trip",
                sport_type="Run",
                start_date=SAMPLE_TZ_AWARE,
                start_date_local=SAMPLE_TZ_AWARE,
                enrichment_status="pending",
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)

            assert row.start_date_local is not None
            # On SQLite tzinfo is not always preserved (SQLite stores ISO
            # strings); the numeric wall-clock value must match.
            if engine_url.startswith("postgresql"):
                assert row.start_date_local.tzinfo is not None
            assert row.start_date_local.replace(tzinfo=None) == \
                SAMPLE_TZ_AWARE.replace(tzinfo=None)
    finally:
        await engine.dispose()


@pytest.mark.parametrize("engine_url", ENGINE_URLS, ids=ENGINE_IDS)
async def test_sleep_session_bed_wake_time_accept_tz_aware(engine_url: str):
    """``SleepSession.bed_time`` / ``wake_time`` round-trip tz-aware values.

    The Eight Sleep sync path now attaches UTC tzinfo to the naive-local
    output of ``_to_local`` at the write boundary; the Whoop sync path's
    ``_parse_dt`` returns tz-aware UTC. Both lead here.
    """
    Session, engine = await _make_session(engine_url)
    try:
        async with Session() as session:
            row = SleepSession(
                source="eight_sleep",
                date=date(2026, 4, 16),
                bed_time=SAMPLE_TZ_AWARE,
                wake_time=SAMPLE_TZ_AWARE,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)

            assert row.bed_time is not None
            assert row.wake_time is not None
            if engine_url.startswith("postgresql"):
                assert row.bed_time.tzinfo is not None
                assert row.wake_time.tzinfo is not None
            assert row.bed_time.replace(tzinfo=None) == \
                SAMPLE_TZ_AWARE.replace(tzinfo=None)
            assert row.wake_time.replace(tzinfo=None) == \
                SAMPLE_TZ_AWARE.replace(tzinfo=None)
    finally:
        await engine.dispose()


@pytest.mark.parametrize("engine_url", ENGINE_URLS, ids=ENGINE_IDS)
async def test_strength_set_performed_at_accepts_tz_aware(engine_url: str):
    """``StrengthSet.performed_at`` round-trips a tz-aware datetime.

    The strength router (``_normalize_performed_at``) tags the
    frontend's naive-local ISO with UTC before INSERT; this test verifies
    the column accepts that shape.
    """
    Session, engine = await _make_session(engine_url)
    try:
        async with Session() as session:
            row = StrengthSet(
                date=date(2026, 4, 16),
                exercise_name="squat",
                set_number=1,
                reps=5,
                weight_kg=100.0,
                performed_at=SAMPLE_TZ_AWARE,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)

            assert row.performed_at is not None
            if engine_url.startswith("postgresql"):
                assert row.performed_at.tzinfo is not None
            assert row.performed_at.replace(tzinfo=None) == \
                SAMPLE_TZ_AWARE.replace(tzinfo=None)
    finally:
        await engine.dispose()
