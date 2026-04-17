from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

# Module-level quota state. OpenWeatherMap's One Call 3.0 free tier is
# 1000 calls/day + 60 calls/min. They don't always return rate-limit
# headers, so we self-throttle (~1 call/sec) and track usage locally
# across every client instance in the process.
_quota_state: dict[str, int | float | None] = {
    "calls_today": 0,            # incremented on each successful request
    "daily_limit": 1000,
    "last_call_at": None,        # monotonic timestamp of the most recent call
    "last_429_at": None,         # wall-clock time we last saw a 429
}

# Minimum seconds between calls to stay under 60/min.
_MIN_CALL_INTERVAL = 1.05


class WeatherRateLimitError(Exception):
    """Raised when OpenWeatherMap returns HTTP 429 (or an invalid-key 401).

    Signals the backfill loop to stop cleanly.
    """

    def __init__(self, status_code: int, retry_after: int | None = None):
        self.status_code = status_code
        self.retry_after = retry_after
        super().__init__(
            f"OpenWeatherMap rate limit / auth failure "
            f"(status={status_code}, retry_after={retry_after})"
        )


class WeatherClient:
    """OpenWeatherMap API client for historical weather data.

    Uses the One Call API 3.0 `timemachine` endpoint. Self-throttles at
    ~1 call/sec to stay under the 60/min free-tier limit and tracks daily
    usage in a module-level counter shared across instances.
    """

    BASE_URL = "https://api.openweathermap.org/data/3.0"

    def __init__(self):
        self._api_key = settings.weather.api_key
        self._http = httpx.AsyncClient(timeout=30)

    async def close(self):
        await self._http.aclose()

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    # ── Rate limit state ────────────────────────────────────────────

    @staticmethod
    def quota_usage() -> dict[str, int | float | None]:
        """Return the process-local call counter + timing state."""
        return dict(_quota_state)

    @staticmethod
    def _record_call() -> None:
        _quota_state["calls_today"] = int(_quota_state.get("calls_today") or 0) + 1
        _quota_state["last_call_at"] = time.monotonic()

    @staticmethod
    def _update_limit_from_headers(headers: httpx.Headers) -> None:
        # OpenWeatherMap doesn't consistently expose rate-limit headers, but
        # handle them if present so local state tracks reality.
        remaining = headers.get("x-ratelimit-remaining")
        limit = headers.get("x-ratelimit-limit")
        if limit:
            try:
                _quota_state["daily_limit"] = int(limit)
            except ValueError:
                pass
        if remaining is not None and _quota_state.get("daily_limit"):
            try:
                _quota_state["calls_today"] = max(
                    int(_quota_state["daily_limit"]) - int(remaining),
                    int(_quota_state.get("calls_today") or 0),
                )
            except ValueError:
                pass

    async def _throttle(self) -> None:
        last = _quota_state.get("last_call_at")
        if last is None:
            return
        elapsed = time.monotonic() - float(last)
        if elapsed < _MIN_CALL_INTERVAL:
            await asyncio.sleep(_MIN_CALL_INTERVAL - elapsed)

    async def get_historical_weather(
        self, lat: float, lng: float, dt: datetime
    ) -> dict | None:
        """Fetch historical weather for a location and timestamp.

        Uses the One Call API 3.0 timemachine endpoint.

        Returns ``None`` when the client has no API key configured.

        Raises:
            WeatherRateLimitError: on 429 or invalid-key 401 responses.
            httpx.HTTPStatusError: on other non-2xx responses (per-activity
                error; callers typically catch and mark the row failed).
        """
        if not self.is_configured:
            return None

        await self._throttle()

        resp = await self._http.get(
            f"{self.BASE_URL}/onecall/timemachine",
            params={
                "lat": lat,
                "lon": lng,
                "dt": int(dt.timestamp()),
                "appid": self._api_key,
                "units": "metric",
            },
        )

        self._update_limit_from_headers(resp.headers)

        if resp.status_code == 429:
            retry_after_hdr = resp.headers.get("retry-after")
            retry_after = (
                int(retry_after_hdr)
                if retry_after_hdr and retry_after_hdr.isdigit()
                else None
            )
            _quota_state["last_429_at"] = int(time.time())
            logger.warning(
                "OpenWeatherMap 429 (retry_after=%s); quota=%s",
                retry_after, _quota_state,
            )
            raise WeatherRateLimitError(
                status_code=429, retry_after=retry_after
            )

        if resp.status_code == 401:
            # Invalid API key or unsubscribed to One Call 3.0.
            logger.warning("OpenWeatherMap 401 — check OPENWEATHERMAP_API_KEY.")
            raise WeatherRateLimitError(status_code=401)

        resp.raise_for_status()
        self._record_call()
        data = resp.json()

        # The timemachine endpoint returns data in a list
        weather_data = data.get("data", [{}])
        if not weather_data:
            return None

        w = weather_data[0] if isinstance(weather_data, list) else weather_data
        weather_info = w.get("weather", [{}])
        conditions = weather_info[0] if weather_info else {}

        return {
            "temp_c": w.get("temp"),
            "feels_like_c": w.get("feels_like"),
            "humidity": w.get("humidity"),
            "wind_speed": w.get("wind_speed"),
            "wind_gust": w.get("wind_gust"),
            "wind_deg": w.get("wind_deg"),
            "conditions": conditions.get("main"),
            "description": conditions.get("description"),
            "pressure": w.get("pressure"),
            "uv_index": w.get("uvi"),
            "raw_data": data,
        }
