"""Tests for backend.services.insights.

All LLM calls are stubbed via monkeypatching `get_provider` so tests are
deterministic and never hit a real API.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models import Activity, Recovery, SleepSession
from backend.services import insights


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


async def _seed_basic(db: AsyncSession) -> None:
    today = date.today()
    now = datetime.utcnow()
    db.add(
        Activity(
            strava_id=1,
            name="Easy Run",
            sport_type="Run",
            start_date=now - timedelta(days=1),
            start_date_local=now - timedelta(days=1),
            moving_time=1800,
            distance=5000,
            average_hr=140,
            average_speed=2.8,
            suffer_score=40,
            enrichment_status="complete",
            classification_type="easy",
        )
    )
    db.add(SleepSession(source="eight_sleep", date=today, sleep_score=80, total_duration=450, hrv=55))
    db.add(Recovery(source="whoop", date=today, recovery_score=72))
    await db.commit()


# ── Stub providers ────────────────────────────────────────────────────


class _StubProvider:
    """Generic stub that returns a pre-canned dict for query_structured."""

    def __init__(self, response: dict | list[dict] | Exception):
        self._response = response
        self._calls: list[dict] = []
        self._idx = 0

    async def query_structured(self, **kwargs) -> dict:  # noqa: D401
        self._calls.append(kwargs)
        resp = self._response
        if isinstance(resp, list):
            item = resp[self._idx]
            self._idx = min(self._idx + 1, len(resp) - 1)
            resp = item
        if isinstance(resp, Exception):
            raise resp
        return resp

    async def close(self) -> None:
        pass


def _install_provider(monkeypatch, mapping: dict[str, Any]) -> None:
    """Register `mapping` from model_key -> _StubProvider/Exception factory."""

    def _factory(model_key: str | None = None):
        target = mapping.get(model_key)
        if target is None:
            raise ValueError(f"Unknown model: {model_key}")
        if isinstance(target, Exception):
            raise target
        return target

    monkeypatch.setattr(insights, "get_provider", _factory)


VALID_REC = {
    "intensity": "easy",
    "suggestion": "Run 5–7 km at a conversational pace.",
    "rationale": [
        "ACWR is in the optimal range",
        "Last session was tempo, so today should be easy",
    ],
    "concerns": [],
    "confidence": "high",
}

VALID_WORKOUT_INSIGHT = {
    "headline": "Solid easy aerobic run.",
    "takeaway": "HR stayed in zone 2. Pace was consistent across all laps.",
    "notable_segments": [],
    "vs_history": "Faster than your median easy run over the last 90 days.",
    "flags": ["consistent pacing"],
}


# ── daily_recommendation ──────────────────────────────────────────────


async def test_daily_recommendation_happy_path(db, monkeypatch):
    await _seed_basic(db)
    stub = _StubProvider(VALID_REC)
    _install_provider(monkeypatch, {"claude-haiku": stub})

    result = await insights.get_daily_recommendation(db, model="claude-haiku")
    assert result.cached is False
    assert result.model == "claude-haiku"
    assert result.recommendation.intensity == "easy"
    assert len(result.recommendation.rationale) == 2


async def test_daily_recommendation_cache_hit(db, monkeypatch):
    await _seed_basic(db)
    stub = _StubProvider(VALID_REC)
    _install_provider(monkeypatch, {"claude-haiku": stub})

    first = await insights.get_daily_recommendation(db, model="claude-haiku")
    assert first.cached is False

    # Second call should hit cache, not call the provider again.
    second = await insights.get_daily_recommendation(db, model="claude-haiku")
    assert second.cached is True
    assert len(stub._calls) == 1  # only one LLM call total


async def test_daily_recommendation_refresh_bypasses_cache(db, monkeypatch):
    await _seed_basic(db)
    stub = _StubProvider(VALID_REC)
    _install_provider(monkeypatch, {"claude-haiku": stub})

    await insights.get_daily_recommendation(db, model="claude-haiku")
    result = await insights.get_daily_recommendation(db, model="claude-haiku", refresh=True)
    assert result.cached is False
    assert len(stub._calls) == 2


async def test_daily_recommendation_fallback_chain(db, monkeypatch):
    await _seed_basic(db)
    # Primary fails, fallback succeeds.
    primary_error = Exception("rate limit")
    stub_primary = _StubProvider(primary_error)
    stub_fallback = _StubProvider(VALID_REC)
    _install_provider(
        monkeypatch,
        {"claude-haiku": stub_primary, "claude-sonnet": stub_fallback, "gpt-4o-mini": None},
    )

    result = await insights.get_daily_recommendation(db, model="claude-haiku")
    assert result.model == "claude-sonnet"
    assert result.recommendation.intensity == "easy"


async def test_daily_recommendation_all_fail_raises(db, monkeypatch):
    await _seed_basic(db)
    err = Exception("boom")
    _install_provider(
        monkeypatch,
        {
            "claude-haiku": _StubProvider(err),
            "claude-sonnet": _StubProvider(err),
            "gpt-4o-mini": _StubProvider(err),
        },
    )
    with pytest.raises(Exception):
        await insights.get_daily_recommendation(db, model="claude-haiku")


async def test_daily_recommendation_invalid_json_triggers_retry(db, monkeypatch):
    await _seed_basic(db)
    # First call returns incomplete data (missing required fields); retry returns valid.
    bad = {"intensity": "easy"}  # missing suggestion/rationale/etc
    stub = _StubProvider([bad, VALID_REC])
    _install_provider(monkeypatch, {"claude-haiku": stub})

    result = await insights.get_daily_recommendation(db, model="claude-haiku")
    assert result.recommendation.intensity == "easy"
    assert len(stub._calls) == 2  # original + self-correcting retry


# ── latest_workout_insight ────────────────────────────────────────────


async def test_workout_insight_none_when_no_activities(db, monkeypatch):
    # No data → None (no LLM call made either)
    called = {"n": 0}

    def _factory(model_key=None):
        called["n"] += 1
        return _StubProvider(VALID_WORKOUT_INSIGHT)

    monkeypatch.setattr(insights, "get_provider", _factory)

    result = await insights.get_latest_workout_insight(db)
    assert result is None
    assert called["n"] == 0


async def test_workout_insight_happy_path(db, monkeypatch):
    await _seed_basic(db)
    stub = _StubProvider(VALID_WORKOUT_INSIGHT)
    _install_provider(monkeypatch, {"claude-haiku": stub})

    result = await insights.get_latest_workout_insight(db, model="claude-haiku")
    assert result is not None
    assert result.insight.headline == VALID_WORKOUT_INSIGHT["headline"]
    assert result.cached is False


async def test_workout_insight_caches_per_activity_id(db, monkeypatch):
    await _seed_basic(db)
    stub = _StubProvider(VALID_WORKOUT_INSIGHT)
    _install_provider(monkeypatch, {"claude-haiku": stub})

    first = await insights.get_latest_workout_insight(db, model="claude-haiku")
    second = await insights.get_latest_workout_insight(db, model="claude-haiku")
    assert first is not None and second is not None
    assert first.cached is False and second.cached is True
    assert len(stub._calls) == 1


async def test_workout_insight_user_message_includes_hr_signals(db, monkeypatch):
    """The snapshot JSON sent to the LLM must include hr_zones and hr_drift
    so the model can reason about zone distribution and cardiac drift."""
    # Seed an activity with zones_data so summarize_hr_zones has something
    # to work with.
    now = datetime.utcnow()
    act = Activity(
        strava_id=42,
        name="Tempo",
        sport_type="Run",
        start_date=now,
        start_date_local=now,
        moving_time=2400,
        distance=8000,
        average_hr=155,
        average_speed=3.3,
        suffer_score=75,
        enrichment_status="complete",
        classification_type="tempo",
        zones_data=[
            {
                "type": "heartrate",
                "distribution_buckets": [
                    {"min": 0, "max": 120, "time": 60},
                    {"min": 120, "max": 140, "time": 600},
                    {"min": 140, "max": 160, "time": 1200},
                    {"min": 160, "max": 180, "time": 500},
                    {"min": 180, "max": -1, "time": 40},
                ],
            }
        ],
    )
    db.add(act)
    await db.commit()

    stub = _StubProvider(VALID_WORKOUT_INSIGHT)
    _install_provider(monkeypatch, {"claude-haiku": stub})

    result = await insights.get_latest_workout_insight(db, model="claude-haiku")
    assert result is not None
    # The stub captured kwargs (system_prompt, user_message, ...).
    assert len(stub._calls) == 1
    user_msg = stub._calls[0]["user_message"]
    assert '"hr_zones"' in user_msg
    assert '"hr_drift"' in user_msg
    assert '"dominant_zone": 3' in user_msg  # middle bucket is largest


# ── Schema preparation ────────────────────────────────────────────────


def test_pydantic_schema_tightens_every_object():
    """Every `object` in the schema must have additionalProperties=false
    and list all its properties under `required` — OpenAI strict mode
    rejects the payload otherwise."""
    schema = insights._pydantic_schema(insights.WorkoutInsight)

    def _walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                assert node.get("additionalProperties") is False, node
                assert set(node["required"]) == set(node["properties"].keys()), node
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)

    _walk(schema)


# ── Explicit-id enrichment gate ───────────────────────────────────────


async def test_workout_insight_skips_pending_activity_by_id(db, monkeypatch):
    """If the caller passes an activity_id that is `pending`, return None
    rather than feeding the LLM a half-populated snapshot."""
    # Seed a pending activity — no laps, no suffer_score, etc.
    pending = Activity(
        strava_id=999,
        name="Pending",
        sport_type="Run",
        start_date=datetime.utcnow(),
        start_date_local=datetime.utcnow(),
        enrichment_status="pending",
    )
    db.add(pending)
    await db.commit()
    await db.refresh(pending)

    called = {"n": 0}

    def _factory(model_key=None):
        called["n"] += 1
        return _StubProvider(VALID_WORKOUT_INSIGHT)

    monkeypatch.setattr(insights, "get_provider", _factory)

    result = await insights.get_latest_workout_insight(
        db, activity_id=pending.id, model="claude-haiku"
    )
    assert result is None
    assert called["n"] == 0
