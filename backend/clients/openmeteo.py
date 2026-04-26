"""Open-Meteo historical weather client.

Duck-typed with ``WeatherClient``: same constructor, same ``is_configured``
property, same ``get_historical_weather(lat, lng, dt)`` signature, same
return shape, same ``WeatherRateLimitError`` on rate-limit-like failures,
same module-level quota snapshot via ``quota_usage()``.

Why this exists: OpenWeatherMap's One Call 3.0 requires a paid "One Call
by Call" subscription (credit card on file) even for the free 1000/day
tier, which is friction for a single-user local app. Open-Meteo
(https://open-meteo.com) is truly free, no key, no sign-up, and covers
historical weather going back to 1940 via ECMWF ERA5 reanalysis. For a
personal fitness tracker it's an obvious swap; the only tradeoff is ~5-7
day lag on the archive endpoint (recent activities may return null).

Endpoint docs: https://open-meteo.com/en/docs/historical-weather-api
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

import httpx

from backend.clients.weather import WeatherRateLimitError

logger = logging.getLogger(__name__)

# Module-level quota counter, mirroring the shape WeatherClient exposes so
# the sync/backfill code can keep its ``quota_usage()`` calls unchanged.
_quota_state: dict[str, int | float | None] = {
    "calls_today": 0,
    "daily_limit": 10000,   # Open-Meteo soft guidance for non-commercial use
    "last_call_at": None,
    "last_429_at": None,
}

# Open-Meteo is generous, but self-throttle to 4 req/sec anyway to stay
# politely within their fair-use guidance.
_MIN_CALL_INTERVAL = 0.25

# WMO weather interpretation codes → (conditions, description) pairs.
# Matches the OpenWeatherMap "main" / "description" split so the rest of
# the pipeline and frontend don't need to care which provider is active.
# https://open-meteo.com/en/docs#weathervariables
_WMO_CODES: dict[int, tuple[str, str]] = {
    0: ("Clear", "clear sky"),
    1: ("Clear", "mainly clear"),
    2: ("Clouds", "partly cloudy"),
    3: ("Clouds", "overcast"),
    45: ("Fog", "fog"),
    48: ("Fog", "depositing rime fog"),
    51: ("Drizzle", "light drizzle"),
    53: ("Drizzle", "moderate drizzle"),
    55: ("Drizzle", "dense drizzle"),
    56: ("Drizzle", "light freezing drizzle"),
    57: ("Drizzle", "dense freezing drizzle"),
    61: ("Rain", "slight rain"),
    63: ("Rain", "moderate rain"),
    65: ("Rain", "heavy rain"),
    66: ("Rain", "light freezing rain"),
    67: ("Rain", "heavy freezing rain"),
    71: ("Snow", "slight snow"),
    73: ("Snow", "moderate snow"),
    75: ("Snow", "heavy snow"),
    77: ("Snow", "snow grains"),
    80: ("Rain", "slight rain showers"),
    81: ("Rain", "moderate rain showers"),
    82: ("Rain", "violent rain showers"),
    85: ("Snow", "slight snow showers"),
    86: ("Snow", "heavy snow showers"),
    95: ("Thunderstorm", "thunderstorm"),
    96: ("Thunderstorm", "thunderstorm with slight hail"),
    99: ("Thunderstorm", "thunderstorm with heavy hail"),
}


class OpenMeteoClient:
    """Async client against the Open-Meteo historical weather archive.

    Also exposes the today-only forecast and air-quality/pollen endpoints
    used by the dashboard environment tile. All three endpoints share the
    same throttle/quota state, since they're all rate-limited as a single
    Open-Meteo identity.
    """

    BASE_URL = "https://archive-api.open-meteo.com/v1/archive"
    FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
    AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

    _HOURLY_VARS = (
        "temperature_2m",
        "apparent_temperature",
        "relative_humidity_2m",
        "wind_speed_10m",
        "wind_gusts_10m",
        "wind_direction_10m",
        "pressure_msl",
        "cloud_cover",
        "weather_code",
    )

    _POLLEN_VARS = (
        "alder_pollen",
        "birch_pollen",
        "grass_pollen",
        "mugwort_pollen",
        "olive_pollen",
        "ragweed_pollen",
    )

    def __init__(self):
        self._http = httpx.AsyncClient(timeout=30)

    async def close(self):
        await self._http.aclose()

    @property
    def is_configured(self) -> bool:
        # No API key required. Always configured.
        return True

    # ── Rate-limit / quota state ────────────────────────────────────

    @staticmethod
    def quota_usage() -> dict[str, int | float | None]:
        return dict(_quota_state)

    @staticmethod
    def _record_call() -> None:
        _quota_state["calls_today"] = int(_quota_state.get("calls_today") or 0) + 1
        _quota_state["last_call_at"] = time.monotonic()

    async def _throttle(self) -> None:
        last = _quota_state.get("last_call_at")
        if last is None:
            return
        elapsed = time.monotonic() - float(last)
        if elapsed < _MIN_CALL_INTERVAL:
            await asyncio.sleep(_MIN_CALL_INTERVAL - elapsed)

    # ── Fetch ───────────────────────────────────────────────────────

    async def get_historical_weather(
        self, lat: float, lng: float, dt: datetime
    ) -> dict | None:
        """Fetch the hourly reading closest to ``dt`` for ``(lat, lng)``.

        Returns a dict with the same keys as ``WeatherClient``:
        ``temp_c``, ``feels_like_c``, ``humidity``, ``wind_speed``,
        ``wind_gust``, ``wind_deg``, ``conditions``, ``description``,
        ``pressure``, ``uv_index`` (always None from archive),
        ``raw_data``.

        Returns ``None`` if Open-Meteo had no reading for that
        timestamp (e.g. activity in the last ~5 days that the archive
        hasn't backfilled yet).

        Raises:
            WeatherRateLimitError: on HTTP 429 (extremely rare for
                Open-Meteo but honored if it happens).
        """
        # Open-Meteo archive expects date-level start/end, then returns an
        # hourly timeseries. We request exactly the day of ``dt`` and pick
        # the closest hour from the response.
        target = dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        date_str = target.strftime("%Y-%m-%d")

        await self._throttle()

        resp = await self._http.get(
            self.BASE_URL,
            params={
                "latitude": lat,
                "longitude": lng,
                "start_date": date_str,
                "end_date": date_str,
                "hourly": ",".join(self._HOURLY_VARS),
                "timezone": "UTC",
                "wind_speed_unit": "ms",       # match OpenWeatherMap (m/s)
                "temperature_unit": "celsius",  # match OpenWeatherMap (°C)
            },
        )

        if resp.status_code == 429:
            retry_after = resp.headers.get("retry-after")
            retry_after_i = (
                int(retry_after) if retry_after and retry_after.isdigit() else None
            )
            _quota_state["last_429_at"] = int(time.time())
            logger.warning(
                "Open-Meteo 429 (retry_after=%s); quota=%s",
                retry_after_i, _quota_state,
            )
            raise WeatherRateLimitError(status_code=429, retry_after=retry_after_i)

        resp.raise_for_status()
        self._record_call()
        data = resp.json()

        hourly = data.get("hourly") or {}
        times: list[str] = hourly.get("time") or []
        if not times:
            return None

        # Find the hour whose timestamp is closest to `target`. Open-Meteo
        # returns local times (or UTC when timezone=UTC) without TZ info.
        target_naive = target.replace(tzinfo=None)
        try:
            times_dt = [datetime.fromisoformat(t) for t in times]
        except (ValueError, TypeError):
            return None
        idx = min(
            range(len(times_dt)),
            key=lambda i: abs((times_dt[i] - target_naive).total_seconds()),
        )

        def _at(var: str):
            vals = hourly.get(var) or []
            if idx >= len(vals):
                return None
            v = vals[idx]
            return v if v is not None else None

        code = _at("weather_code")
        conditions, description = _WMO_CODES.get(
            int(code) if isinstance(code, (int, float)) else -1,
            ("Unknown", "unknown"),
        )

        return {
            "temp_c": _at("temperature_2m"),
            "feels_like_c": _at("apparent_temperature"),
            "humidity": _at("relative_humidity_2m"),
            "wind_speed": _at("wind_speed_10m"),
            "wind_gust": _at("wind_gusts_10m"),
            "wind_deg": _at("wind_direction_10m"),
            "conditions": conditions,
            "description": description,
            "pressure": _at("pressure_msl"),
            "uv_index": None,  # Not exposed by the ERA5 archive endpoint
            "raw_data": data,
        }

    # ── Forecast (today) ────────────────────────────────────────────

    @staticmethod
    def _conditions_for_code(code) -> str:
        """Return a short human string for a WMO weather code, or 'unknown'."""
        try:
            key = int(code)
        except (TypeError, ValueError):
            return "unknown"
        pair = _WMO_CODES.get(key)
        if pair is None:
            return "unknown"
        # Use the description (lowercase phrase) — more specific than the
        # OpenWeatherMap-style "main" bucket and reads better in a tile.
        return pair[1]

    async def get_forecast_today(
        self, lat: float, lng: float
    ) -> dict | None:
        """Return today's forecast for ``(lat, lng)``, or ``None``.

        Shape matches ``EnvironmentForecastSnapshot``::

            {
                "temp_c": float | None,
                "high_c": float | None,
                "low_c": float | None,
                "conditions": str | None,
                "wind_ms": float | None,
            }

        Raises:
            WeatherRateLimitError: on HTTP 429.
        """
        await self._throttle()

        try:
            resp = await self._http.get(
                self.FORECAST_URL,
                params={
                    "latitude": lat,
                    "longitude": lng,
                    "current": "temperature_2m,weather_code,wind_speed_10m",
                    "daily": (
                        "temperature_2m_max,temperature_2m_min,"
                        "weather_code,wind_speed_10m_max"
                    ),
                    "forecast_days": 1,
                    "timezone": "auto",
                    "wind_speed_unit": "ms",
                    "temperature_unit": "celsius",
                },
            )
        except httpx.HTTPError as exc:
            logger.warning("Open-Meteo forecast transport error: %s", exc)
            return None

        if resp.status_code == 429:
            retry_after = resp.headers.get("retry-after")
            retry_after_i = (
                int(retry_after) if retry_after and retry_after.isdigit() else None
            )
            _quota_state["last_429_at"] = int(time.time())
            logger.warning(
                "Open-Meteo forecast 429 (retry_after=%s); quota=%s",
                retry_after_i, _quota_state,
            )
            raise WeatherRateLimitError(status_code=429, retry_after=retry_after_i)

        try:
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Open-Meteo forecast HTTP error: %s", exc)
            return None

        self._record_call()

        try:
            data = resp.json() or {}
        except ValueError:
            return None
        if not data:
            return None

        current = data.get("current") or {}
        daily = data.get("daily") or {}

        def _first(seq):
            if isinstance(seq, list) and seq:
                return seq[0]
            return None

        def _to_float(v):
            if v is None:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        # Prefer the daily weather_code when available (more
        # representative of "today" overall); fall back to current.
        code = _first(daily.get("weather_code"))
        if code is None:
            code = current.get("weather_code")
        conditions = (
            self._conditions_for_code(code) if code is not None else None
        )

        result = {
            "temp_c": _to_float(current.get("temperature_2m")),
            "high_c": _to_float(_first(daily.get("temperature_2m_max"))),
            "low_c": _to_float(_first(daily.get("temperature_2m_min"))),
            "conditions": conditions,
            "wind_ms": _to_float(current.get("wind_speed_10m")),
        }

        # If literally everything came back null, treat as no data so
        # callers can decide whether to omit the tile.
        if all(v is None for v in result.values()):
            return None
        return result

    # ── Air quality + pollen (today) ─────────────────────────────────

    async def get_air_quality_and_pollen(
        self, lat: float, lng: float
    ) -> dict | None:
        """Return today's air quality + pollen for ``(lat, lng)``, or ``None``.

        Shape matches ``EnvironmentAirQualitySnapshot``::

            {
                "us_aqi": int | None,
                "european_aqi": int | None,
                "pollen": {alder, birch, grass, mugwort, olive, ragweed} | None,
            }

        ``pollen`` collapses to ``None`` when all six values are null —
        common in regions where Open-Meteo's CAMS feed has no coverage.

        Raises:
            WeatherRateLimitError: on HTTP 429.
        """
        await self._throttle()

        params_current = ",".join(
            ("european_aqi", "us_aqi", *self._POLLEN_VARS)
        )

        try:
            resp = await self._http.get(
                self.AIR_QUALITY_URL,
                params={
                    "latitude": lat,
                    "longitude": lng,
                    "current": params_current,
                },
            )
        except httpx.HTTPError as exc:
            logger.warning("Open-Meteo air-quality transport error: %s", exc)
            return None

        if resp.status_code == 429:
            retry_after = resp.headers.get("retry-after")
            retry_after_i = (
                int(retry_after) if retry_after and retry_after.isdigit() else None
            )
            _quota_state["last_429_at"] = int(time.time())
            logger.warning(
                "Open-Meteo air-quality 429 (retry_after=%s); quota=%s",
                retry_after_i, _quota_state,
            )
            raise WeatherRateLimitError(status_code=429, retry_after=retry_after_i)

        try:
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Open-Meteo air-quality HTTP error: %s", exc)
            return None

        self._record_call()

        try:
            data = resp.json() or {}
        except ValueError:
            return None
        if not data:
            return None

        current = data.get("current") or {}

        def _to_int(v):
            if v is None:
                return None
            try:
                return int(round(float(v)))
            except (TypeError, ValueError):
                return None

        def _to_float(v):
            if v is None:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        pollen_vals = {
            "alder": _to_float(current.get("alder_pollen")),
            "birch": _to_float(current.get("birch_pollen")),
            "grass": _to_float(current.get("grass_pollen")),
            "mugwort": _to_float(current.get("mugwort_pollen")),
            "olive": _to_float(current.get("olive_pollen")),
            "ragweed": _to_float(current.get("ragweed_pollen")),
        }
        pollen = (
            None
            if all(v is None for v in pollen_vals.values())
            else pollen_vals
        )

        result = {
            "us_aqi": _to_int(current.get("us_aqi")),
            "european_aqi": _to_int(current.get("european_aqi")),
            "pollen": pollen,
        }

        if (
            result["us_aqi"] is None
            and result["european_aqi"] is None
            and pollen is None
        ):
            return None
        return result
