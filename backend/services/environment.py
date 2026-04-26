"""Compose today's environmental snapshot for the dashboard tile.

Reads the user's default ``UserLocation``, fans out to two Open-Meteo
endpoints (forecast + air quality / pollen) in parallel, and assembles
a payload matching ``EnvironmentTodaySnapshot``.

In-memory TTL cache (1 hour) keyed on ``(lat, lng, hour_bucket)`` keeps
us comfortably inside Open-Meteo's free fair-use guidance even if the
dashboard endpoint is hit aggressively.

Intentionally non-persistent — there's no schema or migration tied to
this. If the process restarts the cache simply rewarms.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.clients.openmeteo import OpenMeteoClient
from backend.clients.weather import WeatherRateLimitError
from backend.models.user_location import UserLocation
from backend.services.snapshot_models import EnvironmentTodaySnapshot

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 3600  # 1 hour

# (lat, lng, hour_bucket) -> (cached_at_monotonic, payload)
_cache: dict[tuple[float, float, int], tuple[float, dict[str, Any]]] = {}


def _hour_bucket() -> int:
    """Stable integer bucket that flips every wall hour of monotonic time."""
    return int(time.monotonic() // _CACHE_TTL_SECONDS)


def _cache_get(key: tuple[float, float, int]) -> dict[str, Any] | None:
    entry = _cache.get(key)
    if entry is None:
        return None
    cached_at, payload = entry
    if (time.monotonic() - cached_at) > _CACHE_TTL_SECONDS:
        _cache.pop(key, None)
        return None
    return payload


def _cache_put(key: tuple[float, float, int], payload: dict[str, Any]) -> None:
    _cache[key] = (time.monotonic(), payload)


def _clear_cache() -> None:
    """Test/diagnostic helper — clears the module-level cache."""
    _cache.clear()


async def _safe_call(coro):
    """Run ``coro`` and return ``(ok, value_or_none)``.

    Per-endpoint failures should produce a partial payload, not poison
    the whole snapshot. Rate-limit errors are *intentionally* swallowed:
    the env tile is a soft requirement, the 1h cache prevents pathological
    re-hammering, and surfacing 429s to the dashboard router would just
    blank the whole dashboard rather than degrade gracefully.
    """
    try:
        return True, await coro
    except WeatherRateLimitError as exc:
        logger.warning("Open-Meteo rate-limited environment fetch: %s", exc)
        return False, None
    except Exception as exc:  # pragma: no cover - logged below
        logger.warning("environment sub-call failed: %s", exc)
        return False, None


async def fetch_environment_today(db: AsyncSession) -> dict | None:
    """Return today's environment snapshot, or ``None`` when unavailable.

    ``None`` is returned when:
      * no default ``UserLocation`` is set, or
      * both sub-calls failed and we have nothing to render.
    """
    result = await db.execute(
        select(UserLocation).where(UserLocation.is_default.is_(True)).limit(1)
    )
    location = result.scalar_one_or_none()
    if location is None:
        return None

    lat = float(location.lat)
    lng = float(location.lng)
    cache_key = (lat, lng, _hour_bucket())

    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    client = OpenMeteoClient()
    try:
        results = await asyncio.gather(
            _safe_call(client.get_forecast_today(lat, lng)),
            _safe_call(client.get_air_quality_and_pollen(lat, lng)),
        )
    finally:
        await client.close()

    (forecast_ok, forecast), (aq_ok, air_quality) = results

    if not forecast_ok and not aq_ok:
        # Both legs blew up — nothing to show. Don't cache failure;
        # next request will retry.
        return None

    if forecast is None and air_quality is None:
        # Both legs succeeded but had no data (e.g. coverage gap) —
        # render-empty would be misleading; treat as unavailable. Skip
        # cache so a transient upstream null doesn't stick for an hour.
        return None

    payload = {
        "forecast": forecast,
        "air_quality": air_quality,
    }

    # Validate shape against the contract before caching/returning so
    # any drift surfaces immediately in tests.
    EnvironmentTodaySnapshot.model_validate(payload)

    _cache_put(cache_key, payload)
    return payload
