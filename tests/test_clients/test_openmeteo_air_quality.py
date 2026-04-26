"""Tests for the forecast + air-quality / pollen methods on OpenMeteoClient.

Mirrors the patching style in ``tests/test_clients/test_openmeteo.py`` and
``tests/test_clients/test_elevation.py`` — uses ``httpx.MockTransport`` to
stub HTTP, no real network required.
"""
from __future__ import annotations

import httpx
import pytest

from backend.clients import openmeteo as openmeteo_mod
from backend.clients.openmeteo import OpenMeteoClient
from backend.clients.weather import WeatherRateLimitError


@pytest.fixture(autouse=True)
def _reset_openmeteo_state(monkeypatch):
    """Reset module-level quota and disable the throttle for fast tests."""
    openmeteo_mod._quota_state["calls_today"] = 0
    openmeteo_mod._quota_state["last_call_at"] = None
    openmeteo_mod._quota_state["last_429_at"] = None
    monkeypatch.setattr(openmeteo_mod, "_MIN_CALL_INTERVAL", 0.0)


def _build_client(handler) -> OpenMeteoClient:
    client = OpenMeteoClient()
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


# ── get_forecast_today ──────────────────────────────────────────────


def _forecast_response() -> dict:
    return {
        "latitude": 40.71,
        "longitude": -74.01,
        "current": {
            "temperature_2m": 18.4,
            "weather_code": 2,
            "wind_speed_10m": 3.2,
        },
        "daily": {
            "temperature_2m_max": [22.1],
            "temperature_2m_min": [11.8],
            "weather_code": [3],
            "wind_speed_10m_max": [5.0],
        },
    }


async def test_get_forecast_today_happy_path():
    seen_url = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.open-meteo.com"
        assert request.url.path == "/v1/forecast"
        seen_url["params"] = dict(request.url.params)
        return httpx.Response(200, json=_forecast_response())

    client = _build_client(handler)
    try:
        result = await client.get_forecast_today(lat=40.71, lng=-74.01)
    finally:
        await client.close()

    assert result is not None
    assert result["temp_c"] == pytest.approx(18.4)
    assert result["high_c"] == pytest.approx(22.1)
    assert result["low_c"] == pytest.approx(11.8)
    assert result["wind_ms"] == pytest.approx(3.2)
    # WMO code 3 = overcast (daily preferred over current).
    assert result["conditions"] == "overcast"

    # Quota incremented and the right query params went out.
    assert OpenMeteoClient.quota_usage()["calls_today"] == 1
    assert seen_url["params"]["forecast_days"] == "1"
    assert seen_url["params"]["timezone"] == "auto"


async def test_get_forecast_today_unknown_code_maps_to_unknown():
    payload = _forecast_response()
    payload["current"]["weather_code"] = 999  # not in WMO map
    payload["daily"]["weather_code"] = [999]

    def handler(request):
        return httpx.Response(200, json=payload)

    client = _build_client(handler)
    try:
        result = await client.get_forecast_today(lat=0.0, lng=0.0)
    finally:
        await client.close()

    assert result is not None
    assert result["conditions"] == "unknown"


async def test_get_forecast_today_429_raises():
    def handler(request):
        return httpx.Response(
            429, headers={"retry-after": "11"}, text="slow down"
        )

    client = _build_client(handler)
    try:
        with pytest.raises(WeatherRateLimitError) as exc:
            await client.get_forecast_today(lat=1.0, lng=2.0)
        assert exc.value.status_code == 429
        assert exc.value.retry_after == 11
    finally:
        await client.close()


async def test_get_forecast_today_empty_response_returns_none():
    def handler(request):
        return httpx.Response(200, json={})

    client = _build_client(handler)
    try:
        assert await client.get_forecast_today(lat=0.0, lng=0.0) is None
    finally:
        await client.close()


async def test_get_forecast_today_all_null_returns_none():
    """If every field came back null we don't bother caching the husk."""

    def handler(request):
        return httpx.Response(
            200,
            json={
                "current": {
                    "temperature_2m": None,
                    "weather_code": None,
                    "wind_speed_10m": None,
                },
                "daily": {
                    "temperature_2m_max": [None],
                    "temperature_2m_min": [None],
                    "weather_code": [None],
                    "wind_speed_10m_max": [None],
                },
            },
        )

    client = _build_client(handler)
    try:
        assert await client.get_forecast_today(lat=0.0, lng=0.0) is None
    finally:
        await client.close()


# ── get_air_quality_and_pollen ──────────────────────────────────────


def _aq_response() -> dict:
    return {
        "latitude": 40.71,
        "longitude": -74.01,
        "current": {
            "european_aqi": 32,
            "us_aqi": 41,
            "alder_pollen": 0.5,
            "birch_pollen": 1.2,
            "grass_pollen": 0.0,
            "mugwort_pollen": 0.1,
            "olive_pollen": 0.0,
            "ragweed_pollen": 2.7,
        },
    }


async def test_get_air_quality_and_pollen_happy_path():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "air-quality-api.open-meteo.com"
        assert request.url.path == "/v1/air-quality"
        # All six pollen vars + both AQI metrics requested.
        current = request.url.params["current"]
        for var in (
            "us_aqi",
            "european_aqi",
            "alder_pollen",
            "birch_pollen",
            "grass_pollen",
            "mugwort_pollen",
            "olive_pollen",
            "ragweed_pollen",
        ):
            assert var in current, f"missing {var} in current= param"
        return httpx.Response(200, json=_aq_response())

    client = _build_client(handler)
    try:
        result = await client.get_air_quality_and_pollen(lat=40.71, lng=-74.01)
    finally:
        await client.close()

    assert result is not None
    assert result["us_aqi"] == 41
    assert result["european_aqi"] == 32
    pollen = result["pollen"]
    assert pollen is not None
    assert pollen == {
        "alder": pytest.approx(0.5),
        "birch": pytest.approx(1.2),
        "grass": pytest.approx(0.0),
        "mugwort": pytest.approx(0.1),
        "olive": pytest.approx(0.0),
        "ragweed": pytest.approx(2.7),
    }


async def test_get_air_quality_all_null_pollen_collapses_to_none():
    payload = _aq_response()
    for k in (
        "alder_pollen",
        "birch_pollen",
        "grass_pollen",
        "mugwort_pollen",
        "olive_pollen",
        "ragweed_pollen",
    ):
        payload["current"][k] = None

    def handler(request):
        return httpx.Response(200, json=payload)

    client = _build_client(handler)
    try:
        result = await client.get_air_quality_and_pollen(lat=0.0, lng=0.0)
    finally:
        await client.close()

    assert result is not None
    assert result["us_aqi"] == 41
    assert result["pollen"] is None


async def test_get_air_quality_429_raises():
    def handler(request):
        return httpx.Response(429, headers={"retry-after": "5"}, text="slow")

    client = _build_client(handler)
    try:
        with pytest.raises(WeatherRateLimitError) as exc:
            await client.get_air_quality_and_pollen(lat=1.0, lng=2.0)
        assert exc.value.status_code == 429
        assert exc.value.retry_after == 5
    finally:
        await client.close()


async def test_get_air_quality_empty_response_returns_none():
    def handler(request):
        return httpx.Response(200, json={})

    client = _build_client(handler)
    try:
        assert (
            await client.get_air_quality_and_pollen(lat=0.0, lng=0.0)
        ) is None
    finally:
        await client.close()


async def test_get_air_quality_malformed_returns_none():
    """Non-JSON / 5xx body should produce ``None``, not bubble up."""

    def handler(request):
        return httpx.Response(500, text="upstream is sad")

    client = _build_client(handler)
    try:
        assert (
            await client.get_air_quality_and_pollen(lat=0.0, lng=0.0)
        ) is None
    finally:
        await client.close()
