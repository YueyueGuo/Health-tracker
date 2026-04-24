"""Tests for backend.services.whoop_sync."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.database import Base
from backend.services import whoop_sync
from backend.services.whoop_sync import sync_whoop


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


class StubWhoopClient:
    is_enabled = True

    def __init__(self) -> None:
        self.windows: list[tuple[datetime, datetime]] = []

    async def get_cycles(self, start: datetime, end: datetime) -> list[dict]:
        self.windows.append((start, end))
        return []

    async def get_recovery(self, start: datetime, end: datetime) -> list[dict]:
        self.windows.append((start, end))
        return []

    async def get_sleep(self, start: datetime, end: datetime) -> list[dict]:
        self.windows.append((start, end))
        return []

    async def get_workouts(self, start: datetime, end: datetime) -> list[dict]:
        self.windows.append((start, end))
        return []


async def test_sync_whoop_default_window_uses_utc_now(db, monkeypatch):
    now = datetime(2026, 4, 24, 16, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(whoop_sync, "utc_now", lambda: now)
    client = StubWhoopClient()

    stats = await sync_whoop(db, client, days=3)

    assert stats["failed"] == 0
    assert client.windows
    expected_start = datetime(2026, 4, 21, 16, 30, tzinfo=timezone.utc)
    assert all(start == expected_start for start, _ in client.windows)
    assert all(end == now for _, end in client.windows)
