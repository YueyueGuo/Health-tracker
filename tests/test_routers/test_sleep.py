"""Tests for sleep route date-window behavior."""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

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


async def test_eight_sleep_bed_time_iso_roundtrips_to_user_local_clock(client, db):
    """Integration regression for docs/bugs/eight-sleep-timezone-bug.md.

    Insert an Eight Sleep row with the *post-fix* tz-aware UTC value
    (matching the WHOOP path), fetch it through the router, and confirm
    that parsing the emitted ISO string in the user's local tz yields
    the original wall-clock time.

    Pre-fix, ``bed_time`` was a naive-local datetime mis-labelled as
    UTC, so this round-trip would land four hours earlier than reality.

    Note: SQLite's ``DateTime`` storage doesn't preserve tzinfo on
    round-trip (it stores ISO strings as naive). The router serialises
    via ``isoformat()``, so on SQLite the emitted string has no offset
    suffix. We assert on the wall-clock value, which is what asyncpg
    has been storing implicitly all along, and which is what the
    frontend sees when interpreting the ISO string as UTC (which it
    does via ``new Date(iso)`` when no offset is present and the
    Postgres column carries the explicit ``+00:00`` suffix).
    """
    # 23:18 EDT on May 16 == 03:18Z on May 17 (UTC-4 in May).
    bed_utc = datetime(2026, 5, 17, 3, 18, tzinfo=timezone.utc)
    wake_utc = datetime(2026, 5, 17, 11, 17, tzinfo=timezone.utc)
    db.add(
        SleepSession(
            source="eight_sleep",
            date=date(2026, 5, 17),
            external_id="abc",
            bed_time=bed_utc,
            wake_time=wake_utc,
            total_duration=479,
        )
    )
    await db.commit()

    resp = await client.get("/api/sleep/latest?source=eight_sleep")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload is not None
    assert payload["source"] == "eight_sleep"

    # Parse the emitted ISO. If tzinfo is missing (SQLite drops it on
    # round-trip), the value is implicit-UTC by the project's contract.
    ny = ZoneInfo("America/New_York")
    bed_parsed = datetime.fromisoformat(payload["bed_time"])
    wake_parsed = datetime.fromisoformat(payload["wake_time"])
    if bed_parsed.tzinfo is None:
        bed_parsed = bed_parsed.replace(tzinfo=timezone.utc)
    if wake_parsed.tzinfo is None:
        wake_parsed = wake_parsed.replace(tzinfo=timezone.utc)
    # The instant must equal what we wrote.
    assert bed_parsed == bed_utc
    assert wake_parsed == wake_utc
    # Projected to NY (EDT, UTC-4) the wall-clock is the user's actual
    # bedtime / wake — the exact contract pre-fix violated.
    assert bed_parsed.astimezone(ny).strftime("%H:%M") == "23:18"
    assert wake_parsed.astimezone(ny).strftime("%H:%M") == "07:17"
