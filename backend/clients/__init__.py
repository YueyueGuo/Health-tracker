"""Client factory helpers.

The only thing living here today is ``get_weather_client()`` which picks
between ``WeatherClient`` (OpenWeatherMap) and ``OpenMeteoClient`` based
on the ``WEATHER_PROVIDER`` setting. Both implement the same duck-typed
interface (``is_configured``, ``quota_usage()``, ``close()``,
``get_historical_weather(lat, lng, dt)``) and both raise
``WeatherRateLimitError`` for rate-limit-like failures.

Call-site usage:

    from backend.clients import get_weather_client
    weather = get_weather_client()     # respects WEATHER_PROVIDER
    # ...
    await weather.close()
"""
from __future__ import annotations

import logging

from backend.config import settings

logger = logging.getLogger(__name__)


def get_weather_client():
    """Return a configured weather client based on ``settings.weather_provider``.

    Defaults to Open-Meteo when the setting is missing or unrecognized.
    OpenWeatherMap is kept available for a fallback flip if Open-Meteo
    ever proves insufficient — no need to change any call-site code, just
    flip ``WEATHER_PROVIDER=openweathermap`` in ``.env``.
    """
    provider = (settings.weather_provider or "openmeteo").strip().lower()
    if provider == "openweathermap":
        from backend.clients.weather import WeatherClient
        return WeatherClient()
    if provider not in ("openmeteo", ""):
        logger.warning(
            "Unknown WEATHER_PROVIDER=%r, falling back to Open-Meteo.", provider
        )
    from backend.clients.openmeteo import OpenMeteoClient
    return OpenMeteoClient()


__all__ = ["get_weather_client"]
