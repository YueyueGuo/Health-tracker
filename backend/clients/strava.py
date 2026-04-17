from __future__ import annotations

import logging
import time
from datetime import datetime

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

# Module-level quota state. Shared across all client instances in the process
# so a scheduler-spawned StravaClient can see quota used by a request-handler's
# client. Updated from response headers on every API call.
_quota_state: dict[str, int | None] = {
    "short_used": None,   # X-Ratelimit-Usage[0]  (15-min window)
    "short_limit": 100,
    "long_used": None,    # X-Ratelimit-Usage[1]  (daily)
    "long_limit": 1000,
    "updated_at": None,
}


class StravaRateLimitError(Exception):
    """Raised when Strava returns HTTP 429. Signals the sync loop to stop."""

    def __init__(self, retry_after: int | None = None):
        self.retry_after = retry_after
        super().__init__(
            f"Strava rate limit hit (retry_after={retry_after}s)"
        )


class StravaClient:
    """Strava API v3 client with OAuth2 token management."""

    BASE_URL = "https://www.strava.com/api/v3"
    AUTH_URL = "https://www.strava.com/oauth/authorize"
    TOKEN_URL = "https://www.strava.com/oauth/token"

    def __init__(self):
        self._access_token = settings.strava.access_token
        self._refresh_token = settings.strava.refresh_token
        self._client_id = settings.strava.client_id
        self._client_secret = settings.strava.client_secret
        self._token_expires_at: int = 0
        self._http = httpx.AsyncClient(timeout=30)

    async def close(self):
        await self._http.aclose()

    # ── Rate limit state ────────────────────────────────────────────

    @staticmethod
    def quota_usage() -> dict[str, int | None]:
        """Return the last-seen rate limit usage counters."""
        return dict(_quota_state)

    @staticmethod
    def _update_quota_from_headers(headers: httpx.Headers) -> None:
        usage = headers.get("x-ratelimit-usage")
        limit = headers.get("x-ratelimit-limit")
        if usage:
            try:
                short, long = [int(x) for x in usage.split(",")]
                _quota_state["short_used"] = short
                _quota_state["long_used"] = long
                _quota_state["updated_at"] = int(time.time())
            except ValueError:
                pass
        if limit:
            try:
                short, long = [int(x) for x in limit.split(",")]
                _quota_state["short_limit"] = short
                _quota_state["long_limit"] = long
            except ValueError:
                pass

    @staticmethod
    def quota_exhausted(fraction: float = 0.95) -> bool:
        """True if usage is at/above `fraction` of either reported limit.

        Uses whatever Strava reports via `X-Ratelimit-Limit` (defaults to
        100/1000 before the first response, but modern apps see 200/2000).
        """
        short_used = _quota_state.get("short_used") or 0
        long_used = _quota_state.get("long_used") or 0
        short_limit = _quota_state.get("short_limit") or 100
        long_limit = _quota_state.get("long_limit") or 1000
        return (
            short_used >= short_limit * fraction
            or long_used >= long_limit * fraction
        )

    # ── OAuth2 ──────────────────────────────────────────────────────

    def get_authorization_url(self, redirect_uri: str) -> str:
        return (
            f"{self.AUTH_URL}?client_id={self._client_id}"
            f"&redirect_uri={redirect_uri}"
            f"&response_type=code"
            f"&scope=read,activity:read_all"
        )

    async def exchange_code(self, code: str) -> dict:
        resp = await self._http.post(
            self.TOKEN_URL,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "code": code,
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._refresh_token = data["refresh_token"]
        self._token_expires_at = data["expires_at"]
        return data

    async def _ensure_token(self):
        if not self._refresh_token:
            return
        # Always refresh if we don't know the expiry, or if token is about to expire
        if self._token_expires_at and time.time() < self._token_expires_at - 60:
            return
        resp = await self._http.post(
            self.TOKEN_URL,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._refresh_token = data["refresh_token"]
        self._token_expires_at = data["expires_at"]

    async def _get(self, path: str, params: dict | None = None) -> dict | list:
        await self._ensure_token()
        resp = await self._http.get(
            f"{self.BASE_URL}{path}",
            headers={"Authorization": f"Bearer {self._access_token}"},
            params=params or {},
        )
        self._update_quota_from_headers(resp.headers)
        if resp.status_code == 429:
            retry_after_hdr = resp.headers.get("retry-after")
            retry_after = int(retry_after_hdr) if retry_after_hdr and retry_after_hdr.isdigit() else None
            logger.warning(
                f"Strava 429 on {path}; quota={_quota_state}, retry_after={retry_after}"
            )
            raise StravaRateLimitError(retry_after=retry_after)
        resp.raise_for_status()
        return resp.json()

    # ── Activities ──────────────────────────────────────────────────

    async def get_activities(
        self,
        after: datetime | None = None,
        before: datetime | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> list[dict]:
        params: dict = {"page": page, "per_page": per_page}
        if after:
            params["after"] = int(after.timestamp())
        if before:
            params["before"] = int(before.timestamp())
        return await self._get("/athlete/activities", params)

    async def get_all_activities(
        self, after: datetime | None = None
    ) -> list[dict]:
        all_activities = []
        page = 1
        while True:
            batch = await self.get_activities(after=after, page=page, per_page=100)
            if not batch:
                break
            all_activities.extend(batch)
            page += 1
        return all_activities

    async def get_activity(self, activity_id: int) -> dict:
        """Alias for get_activity_detail (kept for backwards compatibility)."""
        return await self.get_activity_detail(activity_id)

    async def get_activity_detail(self, activity_id: int) -> dict:
        """Fetch full activity detail. Response includes embedded `laps` array.

        Costs 1 Strava API call. Also populates fields absent from the list
        endpoint: suffer_score, weighted_average_watts, kilojoules, calories,
        workout_type, available_zones, device_watts.
        """
        return await self._get(f"/activities/{activity_id}")

    async def get_activity_zones(self, activity_id: int) -> list[dict]:
        """Fetch time-in-zone distribution buckets for an activity.

        Returns a list of zone objects (HR, power, or both depending on sensors).
        Empty list when no zones are computable. Costs 1 API call.
        """
        data = await self._get(f"/activities/{activity_id}/zones")
        if isinstance(data, list):
            return data
        return []

    async def get_activity_streams(
        self, activity_id: int, stream_types: list[str] | None = None
    ) -> dict[str, list]:
        if stream_types is None:
            stream_types = [
                "time", "distance", "heartrate", "cadence",
                "watts", "altitude", "velocity_smooth", "latlng",
            ]
        keys = ",".join(stream_types)
        data = await self._get(
            f"/activities/{activity_id}/streams",
            params={"keys": keys, "key_by_type": "true"},
        )
        if isinstance(data, list):
            return {s["type"]: s["data"] for s in data}
        return {k: v.get("data", []) for k, v in data.items()} if isinstance(data, dict) else {}

    async def get_athlete(self) -> dict:
        return await self._get("/athlete")
