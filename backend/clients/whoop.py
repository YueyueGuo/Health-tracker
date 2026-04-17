"""Whoop developer API client (v2).

Whoop retired the v1 API; all endpoints now live under ``/developer/v2``.
The v2 shape differs from v1 in three important ways:

* **Datetime params**: ``start`` / ``end`` are ISO-8601 UTC datetime strings
  (``YYYY-MM-DDTHH:MM:SSZ``), NOT date strings. Passing a bare date yields
  400. We accept ``date`` or ``datetime`` at the call site and coerce.
* **Pagination**: responses return ``{records: [...], next_token: "..."}``.
  Pass ``next_token`` back in as ``nextToken`` to get the next page.
  Iterate until ``next_token`` is null/absent.
* **Record shape**: each record carries ``start`` / ``end`` / ``score_state``
  / ``score`` (a nested object of typed metrics). There is no top-level
  ``date`` field — derive it from ``start`` (or ``end`` for sleep).

OAuth: authorization-code grant with ``offline`` scope for refresh tokens.
We persist refreshed tokens back to ``.env`` using the Eight Sleep helper
so the app doesn't need the user to re-authenticate every hour.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone

import httpx

from backend.clients.eight_sleep import _default_env_path, _persist_env_var
from backend.config import settings

logger = logging.getLogger(__name__)


class WhoopRateLimitError(Exception):
    """Raised on HTTP 429 from Whoop. Signals sync loops to back off."""

    def __init__(self, retry_after: int | None = None):
        self.retry_after = retry_after
        super().__init__(f"Whoop rate limit hit (retry_after={retry_after}s)")


class WhoopAuthError(Exception):
    """Raised on HTTP 401 from Whoop when refresh cannot recover the token."""


class WhoopClient:
    """Async client against the Whoop developer v2 API."""

    BASE_URL = "https://api.prod.whoop.com/developer/v2"
    AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
    TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"

    # Whoop doesn't publish a stable per-second rate limit but historically
    # tolerates ~4 req/sec sustained. Self-throttle just in case.
    _MIN_REQUEST_INTERVAL_SEC = 0.25

    def __init__(self):
        self._access_token: str | None = settings.whoop.access_token or None
        self._refresh_token: str | None = settings.whoop.refresh_token or None
        self._client_id = settings.whoop.client_id
        self._client_secret = settings.whoop.client_secret
        self._token_expires_at: float = 0.0
        self._enabled = settings.whoop.enabled
        self._http = httpx.AsyncClient(timeout=30)
        self._last_request_ts: float = 0.0

    async def close(self):
        await self._http.aclose()

    @property
    def is_enabled(self) -> bool:
        return self._enabled and bool(self._access_token)

    # ── OAuth2 ──────────────────────────────────────────────────────

    def get_authorization_url(self, redirect_uri: str, state: str) -> str:
        # Whoop requires `state` >= 8 chars (CSRF guard). The `offline`
        # scope triggers Whoop to return a refresh token on code exchange.
        return (
            f"{self.AUTH_URL}?client_id={self._client_id}"
            f"&redirect_uri={redirect_uri}"
            f"&response_type=code"
            f"&scope=offline+read:recovery+read:sleep+read:workout+read:cycles+read:profile"
            f"&state={state}"
        )

    async def exchange_code(self, code: str, redirect_uri: str | None = None) -> dict:
        """Exchange an authorization code for tokens.

        Whoop requires the same ``redirect_uri`` used to request the code.
        """
        body = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "code": code,
            "grant_type": "authorization_code",
        }
        if redirect_uri:
            body["redirect_uri"] = redirect_uri
        resp = await self._http.post(self.TOKEN_URL, data=body)
        resp.raise_for_status()
        tokens = resp.json()
        self._access_token = tokens.get("access_token")
        self._refresh_token = tokens.get("refresh_token")
        if "expires_in" in tokens:
            self._token_expires_at = time.time() + int(tokens["expires_in"])
        self._enabled = bool(self._access_token)
        return tokens

    async def _refresh_access_token(self) -> None:
        if not self._refresh_token:
            raise WhoopAuthError(
                "No refresh_token available; re-authorize at /api/auth/whoop"
            )
        resp = await self._http.post(
            self.TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        )
        if resp.status_code >= 400:
            raise WhoopAuthError(
                f"Whoop refresh failed (HTTP {resp.status_code}): {resp.text[:300]}. "
                "Re-authorize at /api/auth/whoop."
            )
        tokens = resp.json()
        self._access_token = tokens["access_token"]
        if tokens.get("refresh_token"):
            self._refresh_token = tokens["refresh_token"]
            _persist_env_var(_default_env_path(), "WHOOP_REFRESH_TOKEN", self._refresh_token)
        self._token_expires_at = time.time() + int(tokens.get("expires_in", 3600))
        _persist_env_var(_default_env_path(), "WHOOP_ACCESS_TOKEN", self._access_token)

    async def _ensure_token(self) -> None:
        if not self._enabled:
            return
        if self._token_expires_at and time.time() < self._token_expires_at - 60:
            return
        if not self._refresh_token:
            return
        await self._refresh_access_token()

    # ── Request plumbing ────────────────────────────────────────────

    async def _throttle(self) -> None:
        import asyncio
        elapsed = time.time() - self._last_request_ts
        if elapsed < self._MIN_REQUEST_INTERVAL_SEC:
            await asyncio.sleep(self._MIN_REQUEST_INTERVAL_SEC - elapsed)
        self._last_request_ts = time.time()

    async def _get(self, path: str, params: dict | None = None) -> dict:
        """Single GET against the v2 API. Handles 401 → refresh → retry once."""
        if not self.is_enabled:
            return {}
        await self._ensure_token()
        await self._throttle()
        resp = await self._http.get(
            f"{self.BASE_URL}{path}",
            headers={"Authorization": f"Bearer {self._access_token}"},
            params=params or {},
        )
        if resp.status_code == 401 and self._refresh_token:
            logger.info("Whoop returned 401 on %s; refreshing access token", path)
            await self._refresh_access_token()
            await self._throttle()
            resp = await self._http.get(
                f"{self.BASE_URL}{path}",
                headers={"Authorization": f"Bearer {self._access_token}"},
                params=params or {},
            )
        if resp.status_code == 429:
            retry_after = resp.headers.get("retry-after")
            retry_after_i = int(retry_after) if retry_after and retry_after.isdigit() else None
            raise WhoopRateLimitError(retry_after=retry_after_i)
        if resp.status_code == 401:
            raise WhoopAuthError(
                f"Whoop auth failed on {path}: {resp.text[:200]}. "
                "Re-authorize at /api/auth/whoop."
            )
        resp.raise_for_status()
        return resp.json()

    async def _paginate(
        self,
        path: str,
        *,
        params: dict,
        limit_per_page: int = 25,
    ) -> list[dict]:
        """Fetch all pages of a ``{records, next_token}`` endpoint."""
        out: list[dict] = []
        page_params = dict(params)
        page_params["limit"] = limit_per_page
        while True:
            data = await self._get(path, params=page_params)
            records = data.get("records") or []
            out.extend(records)
            next_token = data.get("next_token")
            if not next_token:
                break
            page_params = dict(params)
            page_params["limit"] = limit_per_page
            page_params["nextToken"] = next_token
        return out

    # ── Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _fmt_dt(value: date | datetime) -> str:
        """Coerce a date or datetime to the ISO-8601 UTC string v2 expects."""
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    # ── Data endpoints ──────────────────────────────────────────────

    async def get_profile(self) -> dict:
        if not self.is_enabled:
            return {}
        return await self._get("/user/profile/basic")

    async def get_recovery(self, start: date | datetime, end: date | datetime) -> list[dict]:
        if not self.is_enabled:
            return []
        return await self._paginate(
            "/recovery",
            params={"start": self._fmt_dt(start), "end": self._fmt_dt(end)},
        )

    async def get_sleep(self, start: date | datetime, end: date | datetime) -> list[dict]:
        if not self.is_enabled:
            return []
        return await self._paginate(
            "/activity/sleep",
            params={"start": self._fmt_dt(start), "end": self._fmt_dt(end)},
        )

    async def get_workouts(self, start: date | datetime, end: date | datetime) -> list[dict]:
        if not self.is_enabled:
            return []
        return await self._paginate(
            "/activity/workout",
            params={"start": self._fmt_dt(start), "end": self._fmt_dt(end)},
        )

    async def get_cycles(self, start: date | datetime, end: date | datetime) -> list[dict]:
        if not self.is_enabled:
            return []
        return await self._paginate(
            "/cycle",
            params={"start": self._fmt_dt(start), "end": self._fmt_dt(end)},
        )
