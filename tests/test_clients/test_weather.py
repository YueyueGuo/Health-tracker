"""Tests for backend.clients.weather.

Uses httpx.MockTransport to stub the OpenWeatherMap One Call 3.0
timemachine endpoint without hitting the network. Mirrors the patterns
in tests/test_clients/test_eight_sleep.py.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from backend.clients import weather as weather_mod
from backend.clients.weather import WeatherClient, WeatherRateLimitError
from backend.config import settings


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_weather_state(monkeypatch):
    """Clear the module-level quota counter between tests and disable
    the 1-call/sec throttle so the suite runs instantly."""
    weather_mod._quota_state["calls_today"] = 0
    weather_mod._quota_state["last_call_at"] = None
    weather_mod._quota_state["last_429_at"] = None
    weather_mod._quota_state["daily_limit"] = 1000
    monkeypatch.setattr(weather_mod, "_MIN_CALL_INTERVAL", 0.0)


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings.weather, "api_key", "test-key")


def _build_client(handler) -> WeatherClient:
    client = WeatherClient()
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


def _sample_response() -> dict:
    return {
        "lat": 40.71,
        "lon": -74.01,
        "timezone": "America/New_York",
        "data": [
            {
                "dt": 1714564800,
                "temp": 18.3,
                "feels_like": 17.6,
                "pressure": 1012,
                "humidity": 58,
                "uvi": 4.2,
                "wind_speed": 3.1,
                "wind_gust": 5.4,
                "wind_deg": 210,
                "weather": [
                    {
                        "id": 800,
                        "main": "Clear",
                        "description": "clear sky",
                        "icon": "01d",
                    }
                ],
            }
        ],
    }


# ── Tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parses_response_fields(configured):
    """Feeds a stubbed JSON response; asserts the returned dict shape."""
    sample = _sample_response()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.openweathermap.org"
        assert request.url.path == "/data/3.0/onecall/timemachine"
        assert request.url.params["appid"] == "test-key"
        assert request.url.params["units"] == "metric"
        assert request.url.params["lat"] == "40.71"
        assert request.url.params["lon"] == "-74.01"
        # dt should be a Unix epoch int
        int(request.url.params["dt"])
        return httpx.Response(200, json=sample)

    client = _build_client(handler)
    try:
        result = await client.get_historical_weather(
            lat=40.71,
            lng=-74.01,
            dt=datetime(2024, 5, 1, 12, 0, tzinfo=timezone.utc),
        )
    finally:
        await client.close()

    assert result is not None
    assert result["temp_c"] == 18.3
    assert result["feels_like_c"] == 17.6
    assert result["humidity"] == 58
    assert result["wind_speed"] == 3.1
    assert result["wind_gust"] == 5.4
    assert result["wind_deg"] == 210
    assert result["conditions"] == "Clear"
    assert result["description"] == "clear sky"
    assert result["pressure"] == 1012
    assert result["uv_index"] == 4.2
    # raw_data carries the full OpenWeatherMap payload for icon extraction
    assert result["raw_data"] == sample
    # Quota counter bumps on a successful call
    assert WeatherClient.quota_usage()["calls_today"] == 1


@pytest.mark.asyncio
async def test_not_configured_returns_none(monkeypatch):
    """If no API key is configured, get_historical_weather short-circuits."""
    monkeypatch.setattr(settings.weather, "api_key", "")

    def handler(request):  # pragma: no cover — should not be reached
        pytest.fail("should not make a network call when unconfigured")

    client = _build_client(handler)
    try:
        assert client.is_configured is False
        result = await client.get_historical_weather(
            lat=0.0, lng=0.0, dt=datetime(2024, 1, 1, tzinfo=timezone.utc)
        )
        assert result is None
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_429_raises(configured):
    """429 responses raise WeatherRateLimitError with retry_after."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"retry-after": "42"},
            text="rate limit exceeded",
        )

    client = _build_client(handler)
    try:
        with pytest.raises(WeatherRateLimitError) as exc_info:
            await client.get_historical_weather(
                lat=40.0,
                lng=-74.0,
                dt=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        assert exc_info.value.status_code == 429
        assert exc_info.value.retry_after == 42
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_401_raises(configured):
    """401 (invalid API key / unsubscribed) is surfaced as a rate-limit
    error so the backfill loop stops instead of spinning on failures."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401, json={"cod": 401, "message": "Invalid API key."}
        )

    client = _build_client(handler)
    try:
        with pytest.raises(WeatherRateLimitError) as exc_info:
            await client.get_historical_weather(
                lat=40.0,
                lng=-74.0,
                dt=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        assert exc_info.value.status_code == 401
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_empty_data_array_returns_none(configured):
    """An empty ``data`` array means OpenWeatherMap had no reading for
    that timestamp — we swallow it as None rather than error."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    client = _build_client(handler)
    try:
        result = await client.get_historical_weather(
            lat=0.0, lng=0.0, dt=datetime(2024, 1, 1, tzinfo=timezone.utc)
        )
        assert result is None
    finally:
        await client.close()
