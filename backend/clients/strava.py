from __future__ import annotations

import time
from datetime import datetime

import httpx

from backend.config import settings


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
        return await self._get(f"/activities/{activity_id}")

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
