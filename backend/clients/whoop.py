from __future__ import annotations

import time
from datetime import date

import httpx

from backend.config import settings


class WhoopClient:
    """Whoop API client (developer.whoop.com).

    OAuth2 scopes: read:recovery, read:sleep, read:workout, read:cycles, read:profile

    Currently stubbed — implementations return empty results until the device arrives
    and OAuth2 tokens are configured.
    """

    BASE_URL = "https://api.prod.whoop.com/developer/v1"
    AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
    TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"

    def __init__(self):
        self._access_token = settings.whoop.access_token
        self._refresh_token = settings.whoop.refresh_token
        self._client_id = settings.whoop.client_id
        self._client_secret = settings.whoop.client_secret
        self._token_expires_at: int = 0
        self._enabled = settings.whoop.enabled
        self._http = httpx.AsyncClient(timeout=30)

    async def close(self):
        await self._http.aclose()

    @property
    def is_enabled(self) -> bool:
        return self._enabled and bool(self._access_token)

    # ── OAuth2 ──────────────────────────────────────────────────────

    def get_authorization_url(self, redirect_uri: str) -> str:
        return (
            f"{self.AUTH_URL}?client_id={self._client_id}"
            f"&redirect_uri={redirect_uri}"
            f"&response_type=code"
            f"&scope=read:recovery+read:sleep+read:workout+read:cycles+read:profile"
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
        self._token_expires_at = int(time.time()) + data.get("expires_in", 3600)
        self._enabled = True
        return data

    async def _ensure_token(self):
        if not self._enabled:
            return
        if self._token_expires_at and time.time() < self._token_expires_at - 60:
            return
        if not self._refresh_token:
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
        self._token_expires_at = int(time.time()) + data.get("expires_in", 3600)

    async def _get(self, path: str, params: dict | None = None) -> dict:
        if not self.is_enabled:
            return {}
        await self._ensure_token()
        resp = await self._http.get(
            f"{self.BASE_URL}{path}",
            headers={"Authorization": f"Bearer {self._access_token}"},
            params=params or {},
        )
        resp.raise_for_status()
        return resp.json()

    # ── Data endpoints (stubbed) ────────────────────────────────────

    async def get_recovery(self, start: date, end: date) -> list[dict]:
        if not self.is_enabled:
            return []
        data = await self._get(
            "/recovery",
            params={"start": start.isoformat(), "end": end.isoformat()},
        )
        return data.get("records", [])

    async def get_sleep(self, start: date, end: date) -> list[dict]:
        if not self.is_enabled:
            return []
        data = await self._get(
            "/activity/sleep",
            params={"start": start.isoformat(), "end": end.isoformat()},
        )
        return data.get("records", [])

    async def get_cycles(self, start: date, end: date) -> list[dict]:
        if not self.is_enabled:
            return []
        data = await self._get(
            "/cycle",
            params={"start": start.isoformat(), "end": end.isoformat()},
        )
        return data.get("records", [])
