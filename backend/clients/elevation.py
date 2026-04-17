"""Open-Meteo elevation + geocoding client.

Two endpoints, both free and no-key:

* **Elevation** (``GET /v1/elevation``) \u2014 returns elevation in meters for
  a given lat/lng. Used for:
    - fallback enrichment of activities that have ``start_lat``/``start_lng``
      but no Strava-recorded altitude (indoor/no-watch-GPS sessions on the
      phone);
    - resolving ``elevation_m`` when the user creates a ``UserLocation``
      without providing one.

* **Geocoding** (``GET /v1/search``) \u2014 free-text name \u2192 list of candidate
  places with lat/lng AND elevation in the same response. Powers the
  ``LocationPicker`` search flow.

Shaped to mirror the weather client pattern (``is_configured``,
``quota_usage()``, ``close()``, module-level quota state, 429 \u2192 custom
``ElevationRateLimitError``) so the sync/backfill code feels identical.

Docs:
  https://open-meteo.com/en/docs/elevation-api
  https://open-meteo.com/en/docs/geocoding-api
"""
from __future__ import annotations

import asyncio
import logging
import time

import httpx

logger = logging.getLogger(__name__)

# Module-level quota state. Open-Meteo is generous and we self-throttle
# at ~4 req/sec to stay politely within fair-use.
_quota_state: dict[str, int | float | None] = {
    "calls_today": 0,
    "daily_limit": 10000,
    "last_call_at": None,
    "last_429_at": None,
}

_MIN_CALL_INTERVAL = 0.25  # seconds between calls


class ElevationRateLimitError(Exception):
    """Raised when Open-Meteo responds with HTTP 429.

    Mirrors ``WeatherRateLimitError``; signals the backfill loop to stop
    cleanly rather than hammering the API.
    """

    def __init__(self, status_code: int, retry_after: int | None = None):
        self.status_code = status_code
        self.retry_after = retry_after
        super().__init__(
            f"Open-Meteo elevation rate limit "
            f"(status={status_code}, retry_after={retry_after})"
        )


class ElevationClient:
    """Async client against Open-Meteo's elevation + geocoding APIs."""

    ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
    GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"

    def __init__(self):
        self._http = httpx.AsyncClient(timeout=30)

    async def close(self):
        await self._http.aclose()

    @property
    def is_configured(self) -> bool:
        # No API key required.
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

    # ── Elevation lookup ────────────────────────────────────────────

    async def get_elevation(self, lat: float, lng: float) -> float | None:
        """Return elevation in meters for ``(lat, lng)``, or ``None``.

        Raises:
            ElevationRateLimitError: on HTTP 429.
        """
        await self._throttle()

        resp = await self._http.get(
            self.ELEVATION_URL,
            params={"latitude": lat, "longitude": lng},
        )

        if resp.status_code == 429:
            retry_after = resp.headers.get("retry-after")
            retry_after_i = (
                int(retry_after) if retry_after and retry_after.isdigit() else None
            )
            _quota_state["last_429_at"] = int(time.time())
            logger.warning(
                "Open-Meteo elevation 429 (retry_after=%s); quota=%s",
                retry_after_i, _quota_state,
            )
            raise ElevationRateLimitError(
                status_code=429, retry_after=retry_after_i
            )

        resp.raise_for_status()
        self._record_call()
        data = resp.json() or {}

        # Response shape: {"elevation": [<meters>]}. Guard for missing / empty.
        elevations = data.get("elevation")
        if not elevations:
            return None
        first = elevations[0]
        try:
            return float(first) if first is not None else None
        except (TypeError, ValueError):
            return None

    # ── Geocoding (name search) ─────────────────────────────────────

    async def search_places(
        self, name: str, *, count: int = 5, language: str = "en"
    ) -> list[dict]:
        """Search for named places, returning candidate dicts.

        Each candidate carries ``name``, ``lat``, ``lng``, ``elevation_m``,
        ``country``, ``admin1`` where available. Returns ``[]`` on empty
        matches or any transport hiccup \u2014 callers treat this as an
        advisory lookup, not a required one.

        Raises:
            ElevationRateLimitError: on HTTP 429 (same as elevation).
        """
        q = (name or "").strip()
        if not q:
            return []

        await self._throttle()

        resp = await self._http.get(
            self.GEOCODING_URL,
            params={
                "name": q,
                "count": count,
                "language": language,
                "format": "json",
            },
        )

        if resp.status_code == 429:
            retry_after = resp.headers.get("retry-after")
            retry_after_i = (
                int(retry_after) if retry_after and retry_after.isdigit() else None
            )
            _quota_state["last_429_at"] = int(time.time())
            raise ElevationRateLimitError(
                status_code=429, retry_after=retry_after_i
            )

        resp.raise_for_status()
        self._record_call()
        data = resp.json() or {}

        results = data.get("results") or []
        out: list[dict] = []
        for r in results:
            try:
                out.append(
                    {
                        "name": r.get("name"),
                        "lat": float(r["latitude"]),
                        "lng": float(r["longitude"]),
                        "elevation_m": (
                            float(r["elevation"])
                            if r.get("elevation") is not None
                            else None
                        ),
                        "country": r.get("country"),
                        "admin1": r.get("admin1"),
                        "admin2": r.get("admin2"),
                        "population": r.get("population"),
                    }
                )
            except (KeyError, TypeError, ValueError):
                # Skip malformed records rather than failing the whole search.
                continue
        return out
