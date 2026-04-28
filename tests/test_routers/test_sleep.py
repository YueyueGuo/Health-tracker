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


async def test_latest_sleep_filters_by_source(client, db):
    # Seed an Eight Sleep row a day ahead of the Whoop row. Without the
    # ?source= filter, /sleep/latest would always return Eight Sleep here,
    # which is the original bug that hid Whoop sleep on the comparison card.
    db.add_all(
        [
            SleepSession(
                source="eight_sleep",
                date=date(2026, 4, 27),
                sleep_score=90,
            ),
            SleepSession(
                source="whoop",
                date=date(2026, 4, 26),
                sleep_score=86,
                sleep_efficiency=95.5,
                sleep_debt_min=30,
            ),
        ]
    )
    await db.commit()

    eight = (await client.get("/api/sleep/latest?source=eight_sleep")).json()
    whoop = (await client.get("/api/sleep/latest?source=whoop")).json()
    fallback = (await client.get("/api/sleep/latest")).json()

    assert eight["source"] == "eight_sleep"
    assert eight["date"] == "2026-04-27"
    assert whoop["source"] == "whoop"
    assert whoop["date"] == "2026-04-26"
    # Whoop-only extras round-trip via _sleep_dict.
    assert whoop["sleep_efficiency"] == 95.5
    assert whoop["sleep_debt_min"] == 30
    assert eight["sleep_efficiency"] is None
    # No filter: most-recent-by-date wins regardless of source.
    assert fallback["date"] == "2026-04-27"
