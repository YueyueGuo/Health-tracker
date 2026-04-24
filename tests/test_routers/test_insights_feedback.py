"""Tests for the POST /feedback + GET /feedback/stats endpoints in
backend.routers.insights."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from backend.models import RecommendationFeedback
import backend.routers.insights as insights_router_module
from backend.routers.insights import router as insights_router

from .conftest import make_client


@pytest.fixture
async def client(db_and_sessionmaker):
    _, Session = db_and_sessionmaker
    async with make_client(insights_router, "/api/insights", Session) as c:
        yield c


async def test_post_feedback_inserts(client, db):
    resp = await client.post(
        "/api/insights/feedback",
        json={
            "recommendation_date": date.today().isoformat(),
            "cache_key": "abc1234567890def",
            "vote": "up",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["vote"] == "up"
    assert body["cache_key"] == "abc1234567890def"

    rows = (await db.execute(select(RecommendationFeedback))).scalars().all()
    assert len(rows) == 1


async def test_post_feedback_validates_vote(client):
    resp = await client.post(
        "/api/insights/feedback",
        json={"recommendation_date": date.today().isoformat(), "vote": "meh"},
    )
    assert resp.status_code == 422


async def test_post_feedback_upsert_same_day(client, db):
    today_iso = date.today().isoformat()
    r1 = await client.post(
        "/api/insights/feedback",
        json={"recommendation_date": today_iso, "vote": "up"},
    )
    r2 = await client.post(
        "/api/insights/feedback",
        json={
            "recommendation_date": today_iso,
            "vote": "down",
            "reason": "too hard",
        },
    )
    assert r1.status_code == 200
    assert r2.status_code == 200
    # Same row: updates, no duplicate.
    rows = (await db.execute(select(RecommendationFeedback))).scalars().all()
    assert len(rows) == 1
    assert rows[0].vote == "down"
    assert rows[0].reason == "too hard"


async def test_feedback_stats_counts_and_window(client, db):
    today = date.today()
    db.add_all(
        [
            RecommendationFeedback(recommendation_date=today, vote="up"),
            RecommendationFeedback(
                recommendation_date=today - timedelta(days=2),
                vote="down",
                reason="legs dead",
            ),
            RecommendationFeedback(
                recommendation_date=today - timedelta(days=60), vote="up"
            ),
        ]
    )
    await db.commit()

    resp = await client.get("/api/insights/feedback/stats?days=30")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert body["up"] == 1
    assert body["down"] == 1
    assert body["window_days"] == 30
    assert len(body["recent"]) == 2


async def test_feedback_stats_uses_local_today_at_midnight_boundary(
    client, db, monkeypatch
):
    monkeypatch.setattr(
        insights_router_module, "local_today", lambda: date(2026, 1, 2)
    )
    db.add_all(
        [
            RecommendationFeedback(recommendation_date=date(2026, 1, 2), vote="up"),
            RecommendationFeedback(recommendation_date=date(2026, 1, 1), vote="down"),
            RecommendationFeedback(recommendation_date=date(2025, 12, 31), vote="up"),
        ]
    )
    await db.commit()

    resp = await client.get("/api/insights/feedback/stats?days=1")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert [row["recommendation_date"] for row in body["recent"]] == [
        "2026-01-02",
        "2026-01-01",
    ]


async def test_feedback_stats_empty(client):
    resp = await client.get("/api/insights/feedback/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["up"] == 0
    assert body["down"] == 0
    assert body["recent"] == []
