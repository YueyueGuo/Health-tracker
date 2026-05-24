"""Print the Eight Sleep user_id for the configured email/password.

Eight Sleep's password-grant response includes a ``userId`` field that
gets cached in the Mac-mini's `.env`. On Railway that file doesn't
exist, so the user_id has to be set as a Railway env var manually.
This script does the password grant and prints just the user_id so
you can copy/paste it into Railway → Variables.

Run with the Railway CLI so EIGHT_SLEEP_EMAIL and EIGHT_SLEEP_PASSWORD
are injected from the backend service:

    railway run python scripts/get_eight_sleep_user_id.py

The script prints ONLY the user_id on success — nothing else, so you
can pipe it into pbcopy or use it as input to other commands.
"""
from __future__ import annotations

import asyncio
import os
import sys

import httpx

AUTH_URL = "https://auth-api.8slp.net/v1/tokens"
# The Eight Sleep "consumer-app" client id/secret are public defaults
# baked into the mobile app; not actual secrets.
CLIENT_ID = "0894c7f33bb94800a03f1f4df13a4f38"
CLIENT_SECRET = "f0954a3ed5763ba3d06834c73731a32f15f168f47d4f164751275def86bf2eed"


async def main() -> int:
    email = os.environ.get("EIGHT_SLEEP_EMAIL")
    password = os.environ.get("EIGHT_SLEEP_PASSWORD")
    if not email or not password:
        print(
            "EIGHT_SLEEP_EMAIL and EIGHT_SLEEP_PASSWORD must be set.\n"
            "Run with `railway run python scripts/get_eight_sleep_user_id.py`.",
            file=sys.stderr,
        )
        return 1

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            AUTH_URL,
            json={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "grant_type": "password",
                "username": email,
                "password": password,
            },
        )

    if resp.status_code >= 400:
        print(
            f"password grant failed ({resp.status_code}): {resp.text[:400]}",
            file=sys.stderr,
        )
        return 2

    data = resp.json()
    user_id = data.get("userId")
    if not user_id:
        print(
            "auth succeeded but response had no userId field. Full response:\n"
            f"{data}",
            file=sys.stderr,
        )
        return 3

    print(user_id)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
