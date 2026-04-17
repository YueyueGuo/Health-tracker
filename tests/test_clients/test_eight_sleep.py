"""Tests for backend.clients.eight_sleep.

Uses httpx.MockTransport to stub the auth + app APIs without hitting the
network. Covers:

* password grant on first auth (no refresh_token configured)
* refresh grant on subsequent auths and token rotation persistence
* fallback to password grant when refresh token has expired
* trends + intervals request shape (repeated scope params, user_id in path)
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from backend.clients import eight_sleep as es_mod
from backend.clients.eight_sleep import (
    AUTH_URL,
    CLIENT_API_BASE,  # noqa: F401  (kept so tests can evolve without import churn)
    EightSleepAuthError,
    EightSleepClient,
)
from backend.config import settings


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def tmp_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "EIGHT_SLEEP_EMAIL=test@example.com\n"
        "EIGHT_SLEEP_PASSWORD=hunter2\n"
        "EIGHT_SLEEP_REFRESH_TOKEN=\n"
    )
    return env_file


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings.eight_sleep, "email", "test@example.com")
    monkeypatch.setattr(settings.eight_sleep, "password", "hunter2")
    monkeypatch.setattr(settings.eight_sleep, "refresh_token", "")
    # Clear any real user_id that may have leaked from the user's .env so
    # tests deterministically exercise the "learn userId from auth response"
    # path rather than the cache.
    monkeypatch.setattr(settings.eight_sleep, "user_id", "")
    monkeypatch.setattr(settings.eight_sleep, "client_id", "cid")
    monkeypatch.setattr(settings.eight_sleep, "client_secret", "csec")


def _build_client(handler, tmp_env: Path) -> EightSleepClient:
    client = EightSleepClient(env_path=tmp_env)
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


# ── Auth ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_password_grant_persists_refresh_token(configured, tmp_env):
    calls: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        calls.append((str(request.url), body))
        if str(request.url) == AUTH_URL:
            assert body["grant_type"] == "password"
            assert body["username"] == "test@example.com"
            return httpx.Response(
                200,
                json={
                    "access_token": "access-1",
                    "refresh_token": "refresh-1",
                    "expires_in": 3600,
                    "userId": "u-123",
                },
            )
        pytest.fail(f"unexpected request: {request.url}")

    client = _build_client(handler, tmp_env)
    try:
        await client._ensure_token()
        assert client._access_token == "access-1"
        assert client._user_id == "u-123"
        assert "EIGHT_SLEEP_REFRESH_TOKEN=refresh-1" in tmp_env.read_text()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_refresh_grant_rotates_and_persists(configured, tmp_env):
    # Seed an existing refresh token so we skip the password grant.
    tmp_env.write_text("EIGHT_SLEEP_REFRESH_TOKEN=old-refresh\n")

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["grant_type"] == "refresh_token"
        assert body["refresh_token"] == "old-refresh"
        return httpx.Response(
            200,
            json={
                "access_token": "access-2",
                "refresh_token": "rotated-refresh",
                "expires_in": 3600,
                "userId": "u-123",
            },
        )

    client = _build_client(handler, tmp_env)
    client._refresh_token = "old-refresh"
    try:
        await client._ensure_token()
        assert client._refresh_token == "rotated-refresh"
        assert "EIGHT_SLEEP_REFRESH_TOKEN=rotated-refresh" in tmp_env.read_text()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_refresh_failure_falls_back_to_password(configured, tmp_env):
    step = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        step["n"] += 1
        if step["n"] == 1:
            # First call: refresh grant — reject as expired.
            assert body["grant_type"] == "refresh_token"
            return httpx.Response(401, text="refresh expired")
        # Second call: password grant.
        assert body["grant_type"] == "password"
        return httpx.Response(
            200,
            json={
                "access_token": "access-new",
                "refresh_token": "fresh-refresh",
                "expires_in": 3600,
                "userId": "u-123",
            },
        )

    client = _build_client(handler, tmp_env)
    client._refresh_token = "dead-refresh"
    try:
        await client._ensure_token()
        assert client._access_token == "access-new"
        assert client._refresh_token == "fresh-refresh"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_auth_raises_when_no_creds(monkeypatch, tmp_env):
    monkeypatch.setattr(settings.eight_sleep, "email", "")
    monkeypatch.setattr(settings.eight_sleep, "password", "")
    monkeypatch.setattr(settings.eight_sleep, "refresh_token", "")

    def handler(request):  # pragma: no cover
        pytest.fail("should not make a network call")

    client = _build_client(handler, tmp_env)
    try:
        with pytest.raises(EightSleepAuthError):
            await client._ensure_token()
    finally:
        await client.close()


# ── API calls ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_trends_sends_repeated_scope_params(configured, tmp_env):
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == AUTH_URL:
            return httpx.Response(
                200,
                json={
                    "access_token": "access",
                    "refresh_token": "r",
                    "expires_in": 3600,
                    "userId": "u-7",
                },
            )
        assert request.url.path == "/v1/users/u-7/trends"
        assert request.url.host == "client-api.8slp.net"
        # Multi-value params preserved by httpx as a list.
        scopes = request.url.params.get_list("scope")
        assert "sleepQualityScore" in scopes
        assert "sleepDuration" in scopes
        assert request.url.params["from"] == "2026-04-01"
        assert request.url.params["to"] == "2026-04-07"
        return httpx.Response(200, json={"days": [{"day": "2026-04-06"}]})

    client = _build_client(handler, tmp_env)
    try:
        rows = await client.get_trends(date(2026, 4, 1), date(2026, 4, 7))
        assert rows == [{"day": "2026-04-06"}]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_get_intervals_uses_utc_iso_bounds(configured, tmp_env):
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == AUTH_URL:
            return httpx.Response(
                200,
                json={
                    "access_token": "a",
                    "refresh_token": "r",
                    "expires_in": 3600,
                    "userId": "u-9",
                },
            )
        assert request.url.path == "/v1/users/u-9/intervals"
        assert request.url.host == "client-api.8slp.net"
        assert request.url.params["from"].endswith("Z")
        return httpx.Response(200, json={"intervals": []})

    client = _build_client(handler, tmp_env)
    try:
        await client.get_intervals(date(2026, 4, 1), date(2026, 4, 2))
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_401_triggers_reauth_once(configured, tmp_env):
    call_count = {"auth": 0, "trends": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == AUTH_URL:
            call_count["auth"] += 1
            return httpx.Response(
                200,
                json={
                    "access_token": f"tok-{call_count['auth']}",
                    "refresh_token": "r",
                    "expires_in": 3600,
                    "userId": "u-1",
                },
            )
        call_count["trends"] += 1
        if call_count["trends"] == 1:
            return httpx.Response(401, text="stale token")
        return httpx.Response(200, json={"days": []})

    client = _build_client(handler, tmp_env)
    try:
        await client.get_trends(date(2026, 4, 1), date(2026, 4, 2))
        assert call_count["auth"] == 2
        assert call_count["trends"] == 2
    finally:
        await client.close()


# ── Persistence helper ─────────────────────────────────────────────


def test_persist_refresh_token_replaces_existing_line(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "STRAVA_CLIENT_ID=abc\n"
        "EIGHT_SLEEP_REFRESH_TOKEN=old\n"
        "OTHER=1\n"
    )
    es_mod._persist_refresh_token(env, "new-token")
    content = env.read_text()
    assert "EIGHT_SLEEP_REFRESH_TOKEN=new-token" in content
    assert "STRAVA_CLIENT_ID=abc" in content
    assert "OTHER=1" in content
    # Only one refresh-token line present.
    assert content.count("EIGHT_SLEEP_REFRESH_TOKEN=") == 1


def test_persist_refresh_token_appends_when_missing(tmp_path):
    env = tmp_path / ".env"
    env.write_text("STRAVA_CLIENT_ID=abc\n")
    es_mod._persist_refresh_token(env, "brand-new")
    content = env.read_text()
    assert "EIGHT_SLEEP_REFRESH_TOKEN=brand-new" in content


def test_persist_refresh_token_noop_when_file_absent(tmp_path, caplog):
    env = tmp_path / "does-not-exist" / ".env"
    # Should not raise.
    es_mod._persist_refresh_token(env, "abc")
