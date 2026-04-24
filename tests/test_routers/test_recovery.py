"""Tests for recovery route date-window behavior."""
from __future__ import annotations

from datetime import date

import pytest

from backend.models import Recovery
import backend.routers.recovery as recovery_router_module

from .conftest import make_client


@pytest.fixture
async def client(db_and_sessionmaker):
    _, Session = db_and_sessionmaker
    async with make_client(recovery_router_module.router, "/api/recovery", Session) as c:
        yield c


async def test_today_recovery_uses_local_today_at_midnight_boundary(
    client, db, monkeypatch
):
    monkeypatch.setattr(
        recovery_router_module, "local_today", lambda: date(2026, 1, 2)
    )
    db.add_all(
        [
            Recovery(date=date(2026, 1, 2), recovery_score=82),
            Recovery(date=date(2026, 1, 1), recovery_score=60),
        ]
    )
    await db.commit()

    response = await client.get("/api/recovery/today")

    assert response.status_code == 200
    assert response.json()["date"] == "2026-01-02"
    assert response.json()["recovery_score"] == 82


async def test_list_recovery_uses_local_today_for_window(client, db, monkeypatch):
    monkeypatch.setattr(
        recovery_router_module, "local_today", lambda: date(2026, 1, 2)
    )
    db.add_all(
        [
            Recovery(date=date(2026, 1, 2), recovery_score=82),
            Recovery(date=date(2026, 1, 1), recovery_score=60),
            Recovery(date=date(2025, 12, 31), recovery_score=50),
        ]
    )
    await db.commit()

    response = await client.get("/api/recovery?days=1")

    assert response.status_code == 200
    assert [row["date"] for row in response.json()] == [
        "2026-01-02",
        "2026-01-01",
    ]
