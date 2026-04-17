"""Tests for backend.clients.elevation.

Covers both Open-Meteo endpoints used by the app:
  * /v1/elevation (point-lookup)
  * geocoding-api.open-meteo.com/v1/search (name search)

Uses ``httpx.MockTransport`` to stub HTTP, mirroring the pattern in
``tests/test_clients/test_openmeteo.py``.
"""
from __future__ import annotations

import httpx
import pytest

from backend.clients import elevation as elevation_mod
from backend.clients.elevation import ElevationClient, ElevationRateLimitError


@pytest.fixture(autouse=True)
def _reset_elevation_state(monkeypatch):
    elevation_mod._quota_state["calls_today"] = 0
    elevation_mod._quota_state["last_call_at"] = None
    elevation_mod._quota_state["last_429_at"] = None
    monkeypatch.setattr(elevation_mod, "_MIN_CALL_INTERVAL", 0.0)


def _build_client(handler) -> ElevationClient:
    client = ElevationClient()
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


# ── get_elevation ───────────────────────────────────────────────────


async def test_get_elevation_happy_path():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.open-meteo.com"
        assert request.url.path == "/v1/elevation"
        assert request.url.params["latitude"] == "39.7392"
        assert request.url.params["longitude"] == "-104.9903"
        return httpx.Response(200, json={"elevation": [1609.3]})

    client = _build_client(handler)
    try:
        elev = await client.get_elevation(lat=39.7392, lng=-104.9903)
    finally:
        await client.close()

    assert elev == pytest.approx(1609.3)
    assert ElevationClient.quota_usage()["calls_today"] == 1


async def test_get_elevation_empty_list_returns_none():
    def handler(request):
        return httpx.Response(200, json={"elevation": []})

    client = _build_client(handler)
    try:
        assert await client.get_elevation(lat=0.0, lng=0.0) is None
    finally:
        await client.close()


async def test_get_elevation_missing_key_returns_none():
    def handler(request):
        # Some edge case responses don't include "elevation" at all.
        return httpx.Response(200, json={})

    client = _build_client(handler)
    try:
        assert await client.get_elevation(lat=0.0, lng=0.0) is None
    finally:
        await client.close()


async def test_get_elevation_429_raises():
    def handler(request):
        return httpx.Response(
            429,
            headers={"retry-after": "17"},
            text="slow down",
        )

    client = _build_client(handler)
    try:
        with pytest.raises(ElevationRateLimitError) as exc:
            await client.get_elevation(lat=1.0, lng=2.0)
        assert exc.value.status_code == 429
        assert exc.value.retry_after == 17
    finally:
        await client.close()


# ── search_places ───────────────────────────────────────────────────


async def test_search_places_happy_path():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "geocoding-api.open-meteo.com"
        assert request.url.path == "/v1/search"
        assert request.url.params["name"] == "Boulder"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "name": "Boulder",
                        "latitude": 40.015,
                        "longitude": -105.2705,
                        "elevation": 1655.0,
                        "country": "United States",
                        "admin1": "Colorado",
                        "admin2": "Boulder",
                        "population": 108250,
                    },
                    {
                        "name": "Boulder City",
                        "latitude": 35.978,
                        "longitude": -114.832,
                        "elevation": 776.0,
                        "country": "United States",
                        "admin1": "Nevada",
                    },
                ]
            },
        )

    client = _build_client(handler)
    try:
        results = await client.search_places("Boulder")
    finally:
        await client.close()

    assert len(results) == 2
    assert results[0]["name"] == "Boulder"
    assert results[0]["lat"] == pytest.approx(40.015)
    assert results[0]["lng"] == pytest.approx(-105.2705)
    assert results[0]["elevation_m"] == pytest.approx(1655.0)
    assert results[0]["admin1"] == "Colorado"
    assert results[1]["population"] is None  # not present in second result


async def test_search_places_empty_query_no_request():
    """Empty / whitespace queries short-circuit without hitting the API."""

    def handler(request):  # should not be called
        raise AssertionError("no HTTP request expected")

    client = _build_client(handler)
    try:
        assert await client.search_places("") == []
        assert await client.search_places("   ") == []
    finally:
        await client.close()


async def test_search_places_missing_results_returns_empty():
    def handler(request):
        return httpx.Response(200, json={})

    client = _build_client(handler)
    try:
        assert await client.search_places("Nowheresville") == []
    finally:
        await client.close()


async def test_search_places_skips_malformed_records():
    """A record missing lat/lng shouldn't blow up the whole search."""

    def handler(request):
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "name": "Good",
                        "latitude": 10.0,
                        "longitude": 20.0,
                        "elevation": 5.0,
                    },
                    {"name": "Bad (no coords)"},
                ]
            },
        )

    client = _build_client(handler)
    try:
        results = await client.search_places("mixed")
    finally:
        await client.close()

    assert [r["name"] for r in results] == ["Good"]


async def test_search_places_429_raises_same_error_type():
    def handler(request):
        return httpx.Response(429, text="slow down")

    client = _build_client(handler)
    try:
        with pytest.raises(ElevationRateLimitError):
            await client.search_places("Anywhere")
    finally:
        await client.close()
