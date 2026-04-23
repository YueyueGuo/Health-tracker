"""Tests for backend.routers.chat.

After the chat/insights consolidation pass, only free-form Q&A
(``/ask``) and the model listing (``/models``) remain. The legacy
``/daily-briefing`` and ``/workout/{id}`` endpoints were folded into
``/api/insights/daily-recommendation`` and ``/api/insights/latest-workout``.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from backend.routers.chat import router as chat_router
from backend.services import analysis as analysis_module

from .conftest import make_client


@dataclass
class _FakeResponse:
    text: str
    model: str
    tokens_used: int | None = 42


class _FakeProvider:
    def __init__(self, model_key: str | None = None):
        self.model_key = model_key or "fake-model"
        self.last_system: str | None = None
        self.last_user: str | None = None

    async def query(self, system_prompt: str, user_message: str) -> _FakeResponse:
        self.last_system = system_prompt
        self.last_user = user_message
        return _FakeResponse(
            text="fake answer about your health data",
            model=self.model_key,
        )

    async def close(self) -> None:  # pragma: no cover - trivial
        return None


@pytest.fixture
async def client(db_and_sessionmaker, monkeypatch):
    _, Session = db_and_sessionmaker

    captured: dict[str, _FakeProvider] = {}

    def _fake_get_provider(model_key: str | None = None):
        provider = _FakeProvider(model_key=model_key)
        captured["last"] = provider
        return provider

    monkeypatch.setattr(analysis_module, "get_provider", _fake_get_provider)

    async with make_client(chat_router, "/api/chat", Session) as c:
        c._captured = captured  # type: ignore[attr-defined]
        yield c


async def test_ask_returns_answer(client):
    resp = await client.post(
        "/api/chat/ask",
        json={"question": "how did I sleep last night?"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "fake answer about your health data"
    assert body["model"] == "fake-model"
    assert body["tokens_used"] == 42


async def test_ask_passes_question_and_model(client):
    resp = await client.post(
        "/api/chat/ask",
        json={"question": "am I overtraining?", "model": "gpt-4o"},
    )
    assert resp.status_code == 200
    provider = client._captured["last"]  # type: ignore[attr-defined]
    assert provider.model_key == "gpt-4o"
    assert provider.last_user is not None
    assert "am I overtraining?" in provider.last_user


async def test_models_lists_available(client, monkeypatch):
    from backend.routers import chat as chat_module

    monkeypatch.setattr(
        chat_module,
        "list_available_models",
        lambda: ["gpt-4o", "claude-sonnet"],
    )
    resp = await client.get("/api/chat/models")
    assert resp.status_code == 200
    assert resp.json() == {"models": ["gpt-4o", "claude-sonnet"]}


async def test_legacy_daily_briefing_removed(client):
    resp = await client.get("/api/chat/daily-briefing")
    assert resp.status_code == 404


async def test_legacy_workout_analysis_removed(client):
    resp = await client.get("/api/chat/workout/123")
    assert resp.status_code == 404
