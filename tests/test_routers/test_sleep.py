"""Tests for sleep route date-window behavior."""
from __future__ import annotations

from datetime import date

import pytest

from backend.models import SleepSession
import backend.routers.sleep as sleep_router_module

from .conftest import make_client


@pytest.fixture
async def client(db_and_sessionmaker):
    _, Session = db_and_sessionmaker
    async with make_client(sleep_router_module.router, "/api/sleep", Session) as c:
        yield c


async def test_list_sleep_sessions_uses_local_today_at_midnight_boundary(
    client, db, monkeypatch
):
    monkeypatch.setattr(
        sleep_router_module, "local_today", lambda: date(2026, 1, 2)
    )
    db.add_all(
        [
            SleepSession(source="eight_sleep", date=date(2026, 1, 2), sleep_score=90),
            SleepSession(source="eight_sleep", date=date(2026, 1, 1), sleep_score=80),
            SleepSession(source="eight_sleep", date=date(2025, 12, 31), sleep_score=70),
        ]
    )
    await db.commit()

    response = await client.get("/api/sleep?days=1")

    assert response.status_code == 200
    assert [row["date"] for row in response.json()] == [
        "2026-01-02",
        "2026-01-01",
    ]
