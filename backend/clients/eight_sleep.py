"""Eight Sleep API client.

The official Eight Sleep API is not publicly documented, but the consumer
mobile app talks to two endpoints we mirror here:

    auth-api.8slp.net   → OAuth-ish token exchange (password + refresh grants)
    app-api.8slp.net    → intervals (per-night detail), trends (aggregates),
                          user profile

Token lifecycle
---------------
* First run: if no refresh_token is configured, we exchange the user's email
  + password for an access/refresh token pair (grant_type=password). The
  refresh token is persisted back to `.env` so subsequent runs never need
  the password again.
* Every subsequent run / token expiry: we use grant_type=refresh_token to
  mint a fresh access token. Eight Sleep rotates refresh tokens on use, so
  we re-persist the new one each time.

This deliberately mirrors the token-management style of ``StravaClient``
(in-memory state plus a thin persistence helper) so the two clients feel
the same.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

AUTH_URL = "https://auth-api.8slp.net/v1/tokens"
# Eight Sleep splits its backend across three hosts:
#   auth-api.8slp.net     → token exchange (password + refresh grants)
#   client-api.8slp.net   → sleep data: trends, intervals (v1, long-standing)
#   app-api.8slp.net      → newer profile / account endpoints (v1/v2)
CLIENT_API_BASE = "https://client-api.8slp.net/v1"
APP_API_BASE = "https://app-api.8slp.net"

# Generous default expiry buffer — refresh a minute before the token actually
# expires so a long-running call never fails mid-flight.
_TOKEN_REFRESH_MARGIN_SEC = 60

# The trends endpoint accepts a list of scopes; these are the ones the
# consumer app requests and the ones we actually read below. Note:
# ``sleepFitnessScore`` is NOT a supported scope on the trends endpoint even
# though the value sometimes shows up in the app — requesting it is a no-op.
_DEFAULT_TREND_SCOPES = (
    "sleepQualityScore",
    "sleepDuration",
    "presenceDuration",
    "sleepRoutine",
)


class EightSleepAuthError(RuntimeError):
    """Raised when Eight Sleep auth fails (bad creds / expired refresh)."""


class EightSleepClient:
    """Async client against the Eight Sleep consumer APIs."""

    def __init__(self, *, env_path: Path | None = None):
        self._email = settings.eight_sleep.email
        self._password = settings.eight_sleep.password
        self._client_id = settings.eight_sleep.client_id
        self._client_secret = settings.eight_sleep.client_secret
        self._refresh_token: str = settings.eight_sleep.refresh_token or ""
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0
        # user_id is cached in .env so refresh-grant-only runs don't need /me.
        self._user_id: str | None = settings.eight_sleep.user_id or None
        self._http = httpx.AsyncClient(timeout=30)
        # Used to rewrite EIGHT_SLEEP_REFRESH_TOKEN= in-place on refresh.
        self._env_path = env_path or _default_env_path()

    async def close(self):
        await self._http.aclose()

    # ── Auth ────────────────────────────────────────────────────────

    async def _password_grant(self) -> dict:
        if not self._email or not self._password:
            raise EightSleepAuthError(
                "Eight Sleep email/password not configured and no refresh token "
                "is available. Set EIGHT_SLEEP_EMAIL and EIGHT_SLEEP_PASSWORD."
            )
        resp = await self._http.post(
            AUTH_URL,
            json={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "password",
                "username": self._email,
                "password": self._password,
            },
        )
        if resp.status_code >= 400:
            raise EightSleepAuthError(
                f"password grant failed ({resp.status_code}): {resp.text[:200]}"
            )
        return resp.json()

    async def _refresh_grant(self) -> dict:
        resp = await self._http.post(
            AUTH_URL,
            json={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
            },
        )
        if resp.status_code >= 400:
            # Refresh tokens expire silently after a few months; fall back
            # to password grant on the next call.
            logger.warning(
                "Eight Sleep refresh grant failed (%s); will retry password grant",
                resp.status_code,
            )
            self._refresh_token = ""
            raise EightSleepAuthError(
                f"refresh grant failed ({resp.status_code}): {resp.text[:200]}"
            )
        return resp.json()

    async def _ensure_token(self) -> None:
        if self._access_token and time.time() < self._token_expires_at - _TOKEN_REFRESH_MARGIN_SEC:
            return

        # Snapshot before _refresh_grant() clears the field on failure, so
        # we can distinguish "refresh failed → fall back" from "no refresh
        # configured → genuine auth error".
        had_refresh = bool(self._refresh_token)
        try:
            if had_refresh:
                data = await self._refresh_grant()
            else:
                data = await self._password_grant()
        except EightSleepAuthError:
            if had_refresh:
                # Stale refresh token; retry with password grant once.
                data = await self._password_grant()
            else:
                raise

        self._access_token = data["access_token"]
        new_user_id = data.get("userId")
        if new_user_id and new_user_id != self._user_id:
            self._user_id = new_user_id
            _persist_env_var(self._env_path, "EIGHT_SLEEP_USER_ID", new_user_id)
        expires_in = int(data.get("expires_in") or 3600)
        self._token_expires_at = time.time() + expires_in

        new_refresh = data.get("refresh_token")
        if new_refresh and new_refresh != self._refresh_token:
            self._refresh_token = new_refresh
            _persist_env_var(self._env_path, "EIGHT_SLEEP_REFRESH_TOKEN", new_refresh)

    async def _authed_get(self, url: str, params: dict | list | None = None) -> dict:
        await self._ensure_token()
        resp = await self._http.get(
            url,
            headers={"Authorization": f"Bearer {self._access_token}"},
            params=params or {},
        )
        if resp.status_code == 401:
            # Access token rejected — force re-auth once.
            self._access_token = None
            self._token_expires_at = 0.0
            await self._ensure_token()
            resp = await self._http.get(
                url,
                headers={"Authorization": f"Bearer {self._access_token}"},
                params=params or {},
            )
        resp.raise_for_status()
        return resp.json()

    # ── User ────────────────────────────────────────────────────────

    async def get_me(self) -> dict:
        """Return the authenticated user profile (used for user_id + side)."""
        # v2/users/me occasionally disappears on app-api; fall back to the
        # long-standing client-api /users/{id} endpoint if we already have id.
        if self._user_id:
            data = await self._authed_get(
                f"{CLIENT_API_BASE}/users/{self._user_id}"
            )
        else:
            data = await self._authed_get(f"{APP_API_BASE}/v2/users/me")
        user = data.get("user") or data
        if not self._user_id:
            self._user_id = user.get("userId") or user.get("id")
        return user

    async def _get_user_id(self) -> str:
        if self._user_id:
            return self._user_id
        # Token exchange usually returns userId; try that first so we avoid
        # an extra /me round-trip on the happy path.
        await self._ensure_token()
        if self._user_id:
            return self._user_id

        # Refresh-grant responses don't echo userId back. If we got here via
        # refresh (and the cached .env user_id is missing), force a password
        # grant which *does* include it.
        if self._refresh_token and self._email and self._password:
            logger.info("No cached user_id; forcing password grant to obtain it")
            data = await self._password_grant()
            self._access_token = data["access_token"]
            self._token_expires_at = time.time() + int(data.get("expires_in") or 3600)
            new_user_id = data.get("userId")
            if new_user_id:
                self._user_id = new_user_id
                _persist_env_var(self._env_path, "EIGHT_SLEEP_USER_ID", new_user_id)
            new_refresh = data.get("refresh_token")
            if new_refresh and new_refresh != self._refresh_token:
                self._refresh_token = new_refresh
                _persist_env_var(
                    self._env_path, "EIGHT_SLEEP_REFRESH_TOKEN", new_refresh
                )
            if self._user_id:
                return self._user_id

        raise EightSleepAuthError("unable to determine Eight Sleep user id")

    # ── Trends & intervals ──────────────────────────────────────────

    async def get_trends(
        self,
        start: date,
        end: date,
        *,
        scopes: tuple[str, ...] = _DEFAULT_TREND_SCOPES,
    ) -> list[dict]:
        """Fetch aggregated per-day trend rows in [start, end] inclusive.

        Returns a list of day dicts (one per night) or an empty list.
        """
        user_id = await self._get_user_id()
        # Eight Sleep's trends endpoint uses a repeated scope query param.
        params: list[tuple[str, str]] = [
            ("tz", settings.eight_sleep.timezone),
            ("from", start.isoformat()),
            ("to", end.isoformat()),
        ]
        for scope in scopes:
            params.append(("scope", scope))

        data = await self._authed_get(
            f"{CLIENT_API_BASE}/users/{user_id}/trends",
            params=params,
        )
        return data.get("days") or []

    async def get_intervals(
        self,
        start: date,
        end: date,
    ) -> list[dict]:
        """Fetch the raw per-night intervals in [start, end].

        Contains richer data than ``get_trends`` (stages timeline, per-night
        HR/HRV/respiratory/tnt timeseries, bed temperature). Used to populate
        the ``raw_data`` JSON column.
        """
        user_id = await self._get_user_id()
        data = await self._authed_get(
            f"{CLIENT_API_BASE}/users/{user_id}/intervals",
            params={
                "from": _iso_utc(start),
                "to": _iso_utc(end + timedelta(days=1)),
            },
        )
        return data.get("intervals") or []

    async def get_recent_sleep(self, days: int = 30) -> list[dict]:
        """Convenience wrapper returning trend rows for the last N days."""
        end = date.today()
        start = end - timedelta(days=days)
        return await self.get_trends(start, end)


# ── Helpers ─────────────────────────────────────────────────────────


def _iso_utc(d: date) -> str:
    """Convert a date to a UTC ISO-8601 timestamp at 00:00Z."""
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def _default_env_path() -> Path:
    """Return the repo-root .env path (sibling of pyproject.toml)."""
    # clients/ → backend/ → repo root
    return Path(__file__).resolve().parent.parent.parent / ".env"


def _persist_env_var(env_path: Path, key: str, value: str) -> None:
    """Rewrite a single KEY=value line in .env, preserving the rest.

    Idempotent: if the key exists, its value is replaced; otherwise a new
    line is appended. Never raises — persistence failures are logged and
    swallowed so a sync can still succeed on a read-only filesystem.
    """
    try:
        if not env_path.exists():
            logger.debug(".env not found at %s; skipping %s persist", env_path, key)
            return
        content = env_path.read_text()
        new_line = f"{key}={value}"
        pattern = re.compile(rf"^{re.escape(key)}\s*=.*$", re.MULTILINE)
        if pattern.search(content):
            updated = pattern.sub(new_line, content)
        else:
            updated = content.rstrip() + "\n" + new_line + "\n"
        env_path.write_text(updated)
        logger.info("Persisted %s to %s", key, env_path)
    except Exception as e:  # never fail sync just because persistence broke
        logger.warning("Failed to persist %s to .env: %s", key, e)


# Back-compat alias so existing tests / callers keep working.
def _persist_refresh_token(env_path: Path, refresh_token: str) -> None:
    _persist_env_var(env_path, "EIGHT_SLEEP_REFRESH_TOKEN", refresh_token)
