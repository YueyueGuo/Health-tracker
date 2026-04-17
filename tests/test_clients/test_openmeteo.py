"""Tests for backend.clients.openmeteo and the weather-provider factory.

Uses httpx.MockTransport to stub the Open-Meteo archive endpoint. Mirrors
tests/test_clients/test_weather.py.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from backend.clients import get_weather_client
from backend.clients import openmeteo as openmeteo_mod
from backend.clients.openmeteo import OpenMeteoClient
from backend.clients.weather import WeatherClient, WeatherRateLimitError
from backend.config import settings


@pytest.fixture(autouse=True)
def _reset_openmeteo_state(monkeypatch):
    """Clear the module-level quota counter and disable the throttle."""
    openmeteo_mod._quota_state["calls_today"] = 0
    openmeteo_mod._quota_state["last_call_at"] = None
    openmeteo_mod._quota_state["last_429_at"] = None
    monkeypatch.setattr(openmeteo_mod, "_MIN_CALL_INTERVAL", 0.0)


def _build_client(handler) -> OpenMeteoClient:
    client = OpenMeteoClient()
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


def _sample_response() -> dict:
    # Hourly time series for 2024-05-01 UTC. Target hour in the test is 12:00,
    # so index 12 is the expected match.
    hours = [f"2024-05-01T{h:02d}:00" for h in range(24)]
    return {
        "latitude": 40.71,
        "longitude": -74.01,
        "hourly": {
            "time": hours,
            "temperature_2m": [10 + h * 0.1 for h in range(24)],
            "apparent_temperature": [9 + h * 0.1 for h in range(24)],
            "relative_humidity_2m": [50 + h for h in range(24)],
            "wind_speed_10m": [1.0 + h * 0.05 for h in range(24)],
            "wind_gusts_10m": [2.0 + h * 0.05 for h in range(24)],
            "wind_direction_10m": [180 + h for h in range(24)],
            "pressure_msl": [1010 + h for h in range(24)],
            "cloud_cover": [20 + h for h in range(24)],
            # Clear sky at hour 12 so we can assert the WMO mapping.
            "weather_code": [0] * 24,
        },
    }


# ── OpenMeteoClient ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parses_closest_hour():
    sample = _sample_response()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "archive-api.open-meteo.com"
        assert request.url.path == "/v1/archive"
        assert request.url.params["latitude"] == "40.71"
        assert request.url.params["longitude"] == "-74.01"
        assert request.url.params["start_date"] == "2024-05-01"
        assert request.url.params["end_date"] == "2024-05-01"
        # Ensure we pass the hourly variable list and UTC timezone.
        assert "temperature_2m" in request.url.params["hourly"]
        assert request.url.params["timezone"] == "UTC"
        return httpx.Response(200, json=sample)

    client = _build_client(handler)
    try:
        # 12:15 UTC should round to the 12:00 bucket (index 12).
        result = await client.get_historical_weather(
            lat=40.71,
            lng=-74.01,
            dt=datetime(2024, 5, 1, 12, 15, tzinfo=timezone.utc),
        )
    finally:
        await client.close()

    assert result is not None
    assert result["temp_c"] == pytest.approx(10 + 12 * 0.1)
    assert result["feels_like_c"] == pytest.approx(9 + 12 * 0.1)
    assert result["humidity"] == 62
    assert result["wind_speed"] == pytest.approx(1.0 + 12 * 0.05)
    assert result["wind_gust"] == pytest.approx(2.0 + 12 * 0.05)
    assert result["wind_deg"] == 192
    assert result["pressure"] == 1022
    assert result["conditions"] == "Clear"
    assert result["description"] == "clear sky"
    assert result["uv_index"] is None  # archive has no UV
    assert result["raw_data"] == sample
    assert OpenMeteoClient.quota_usage()["calls_today"] == 1


@pytest.mark.asyncio
async def test_maps_wmo_rain_code():
    """weather_code=63 → conditions=Rain, description=moderate rain."""
    sample = _sample_response()
    sample["hourly"]["weather_code"] = [63] * 24

    def handler(request):
        return httpx.Response(200, json=sample)

    client = _build_client(handler)
    try:
        result = await client.get_historical_weather(
            lat=1.0, lng=2.0, dt=datetime(2024, 5, 1, 12, tzinfo=timezone.utc)
        )
    finally:
        await client.close()

    assert result["conditions"] == "Rain"
    assert result["description"] == "moderate rain"


@pytest.mark.asyncio
async def test_empty_hourly_returns_none():
    """A response with no time entries yields None rather than raising."""
    def handler(request):
        return httpx.Response(200, json={"hourly": {"time": []}})

    client = _build_client(handler)
    try:
        result = await client.get_historical_weather(
            lat=0.0, lng=0.0, dt=datetime(2024, 1, 1, tzinfo=timezone.utc)
        )
        assert result is None
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_429_raises_weather_rate_limit_error():
    """Open-Meteo almost never 429s but we honor it if it happens."""
    def handler(request):
        return httpx.Response(
            429, headers={"retry-after": "30"}, text="rate limit exceeded"
        )

    client = _build_client(handler)
    try:
        with pytest.raises(WeatherRateLimitError) as exc:
            await client.get_historical_weather(
                lat=0.0, lng=0.0, dt=datetime(2024, 1, 1, tzinfo=timezone.utc)
            )
        assert exc.value.status_code == 429
        assert exc.value.retry_after == 30
    finally:
        await client.close()


# ── Factory ────────────────────────────────────────────────────────


def test_factory_defaults_to_openmeteo(monkeypatch):
    monkeypatch.setattr(settings, "weather_provider", "openmeteo")
    client = get_weather_client()
    assert isinstance(client, OpenMeteoClient)


def test_factory_returns_openweathermap_when_selected(monkeypatch):
    monkeypatch.setattr(settings, "weather_provider", "openweathermap")
    client = get_weather_client()
    assert isinstance(client, WeatherClient)


def test_factory_falls_back_to_openmeteo_on_unknown_value(monkeypatch):
    monkeypatch.setattr(settings, "weather_provider", "notarealprovider")
    client = get_weather_client()
    assert isinstance(client, OpenMeteoClient)
