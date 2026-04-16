from __future__ import annotations

from datetime import date, timedelta

import httpx

from backend.config import settings


class EightSleepClient:
    """Eight Sleep API client (unofficial / community-documented)."""

    BASE_URL = "https://client-api.8slp.net/v1"

    def __init__(self):
        self._email = settings.eight_sleep.email
        self._password = settings.eight_sleep.password
        self._token: str | None = None
        self._user_id: str | None = None
        self._http = httpx.AsyncClient(timeout=30)

    async def close(self):
        await self._http.aclose()

    async def authenticate(self) -> None:
        resp = await self._http.post(
            f"{self.BASE_URL}/login",
            json={"email": self._email, "password": self._password},
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["session"]["token"]
        self._user_id = data["session"]["userId"]

    async def _ensure_auth(self):
        if not self._token:
            await self.authenticate()

    async def _get(self, path: str, params: dict | None = None) -> dict:
        await self._ensure_auth()
        resp = await self._http.get(
            f"{self.BASE_URL}{path}",
            headers={"Authorization": f"Bearer {self._token}"},
            params=params or {},
        )
        resp.raise_for_status()
        return resp.json()

    async def get_user_info(self) -> dict:
        return await self._get(f"/users/{self._user_id}")

    async def get_sleep_data(self, sleep_date: date) -> dict | None:
        """Fetch sleep data for a specific night."""
        data = await self._get(
            f"/users/{self._user_id}/trends",
            params={
                "tz": settings.eight_sleep.timezone,
                "from": sleep_date.isoformat(),
                "to": (sleep_date + timedelta(days=1)).isoformat(),
            },
        )
        days = data.get("days", [])
        return days[0] if days else None

    async def get_recent_sleep(self, days: int = 7) -> list[dict]:
        """Fetch sleep data for the last N days."""
        end = date.today()
        start = end - timedelta(days=days)
        data = await self._get(
            f"/users/{self._user_id}/trends",
            params={
                "tz": settings.eight_sleep.timezone,
                "from": start.isoformat(),
                "to": end.isoformat(),
            },
        )
        return data.get("days", [])
