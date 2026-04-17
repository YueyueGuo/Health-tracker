from __future__ import annotations

import secrets

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from backend.clients.eight_sleep import _default_env_path, _persist_env_var
from backend.clients.strava import StravaClient
from backend.clients.whoop import WhoopClient
from backend.config import settings

router = APIRouter()


def _oauth_redirect_host() -> str:
    """Return a browser-resolvable host for OAuth redirect URIs.

    `settings.host` is a **bind** address (e.g. "0.0.0.0" to listen on all
    interfaces). It is NOT what a browser can resolve — OAuth providers
    like Whoop and Strava reject 0.0.0.0 as an invalid redirect_uri. Use
    localhost for loopback binds; anything else is kept as-is so a real
    deployment can use a real hostname.
    """
    host = (settings.host or "").strip()
    if host in ("", "0.0.0.0", "127.0.0.1"):
        return "localhost"
    return host


@router.get("/strava")
async def strava_auth(request: Request):
    """Initiate Strava OAuth2 flow."""
    client = StravaClient()
    redirect_uri = f"http://{_oauth_redirect_host()}:{settings.port}/api/auth/strava/callback"
    url = client.get_authorization_url(redirect_uri)
    await client.close()
    return RedirectResponse(url)


@router.get("/strava/callback")
async def strava_callback(code: str = Query(...)):
    """Handle Strava OAuth2 callback."""
    client = StravaClient()
    try:
        tokens = await client.exchange_code(code)
        return {
            "status": "success",
            "message": "Strava connected! Add these to your .env file:",
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "expires_at": tokens["expires_at"],
        }
    finally:
        await client.close()


@router.get("/whoop")
async def whoop_auth(request: Request):
    """Initiate Whoop OAuth2 flow.

    Whoop requires the OAuth2 `state` parameter (>=8 chars) as CSRF
    protection. For a single-user local app we generate a fresh random
    state per request; strict echo-verification is optional and skipped.
    """
    client = WhoopClient()
    redirect_uri = f"http://{_oauth_redirect_host()}:{settings.port}/api/auth/whoop/callback"
    state = secrets.token_urlsafe(16)  # ~22 chars, comfortably >= 8
    url = client.get_authorization_url(redirect_uri, state=state)
    await client.close()
    return RedirectResponse(url)


@router.get("/whoop/callback")
async def whoop_callback(
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
):
    """Handle Whoop OAuth2 callback.

    Surfaces upstream OAuth errors (invalid_state, access_denied, etc.)
    as a readable JSON body instead of a generic 422.
    """
    if error:
        raise HTTPException(
            status_code=400,
            detail={
                "error": error,
                "error_description": error_description or "(none)",
                "hint": (
                    "Whoop returned an OAuth error. Common causes: "
                    "redirect_uri mismatch, missing/short state, or "
                    "user denied access."
                ),
            },
        )
    if not code:
        raise HTTPException(status_code=400, detail="Missing ?code parameter")

    client = WhoopClient()
    try:
        # Must match the redirect_uri used in /whoop exactly, or Whoop's
        # token endpoint returns invalid_grant.
        redirect_uri = (
            f"http://{_oauth_redirect_host()}:{settings.port}/api/auth/whoop/callback"
        )
        try:
            tokens = await client.exchange_code(code, redirect_uri=redirect_uri)
        except Exception as e:  # noqa: BLE001 — surface all upstream errors clearly
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "token_exchange_failed",
                    "error_description": str(e),
                    "hint": (
                        "OAuth codes are single-use. If you retried the "
                        "callback, restart from /api/auth/whoop to get a "
                        "fresh code."
                    ),
                },
            )
        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")

        # Auto-persist to .env so no manual copy/paste is required.
        # Following the Eight Sleep pattern, we rewrite the matching lines
        # in place. Failures are logged and swallowed.
        env_path = _default_env_path()
        persisted: list[str] = []
        if access_token:
            _persist_env_var(env_path, "WHOOP_ACCESS_TOKEN", access_token)
            persisted.append("WHOOP_ACCESS_TOKEN")
        if refresh_token:
            _persist_env_var(env_path, "WHOOP_REFRESH_TOKEN", refresh_token)
            persisted.append("WHOOP_REFRESH_TOKEN")
        _persist_env_var(env_path, "WHOOP_ENABLED", "true")
        persisted.append("WHOOP_ENABLED")

        # Immediately verify the token works against the v2 profile endpoint
        # so the user sees green/red status right in the callback response.
        verify: dict = {"attempted": False}
        if access_token:
            verify["attempted"] = True
            async with httpx.AsyncClient(timeout=15) as vc:
                vr = await vc.get(
                    "https://api.prod.whoop.com/developer/v2/user/profile/basic",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            verify["status_code"] = vr.status_code
            verify["ok"] = vr.is_success
            if vr.is_success:
                try:
                    profile = vr.json()
                    verify["user_id"] = profile.get("user_id") or profile.get("id")
                    verify["email"] = profile.get("email")
                except Exception:
                    pass
            else:
                verify["body"] = vr.text[:300]

        return {
            "status": (
                "success"
                if refresh_token and verify.get("ok")
                else "partial"
            ),
            "message": (
                "Whoop connected and verified. Tokens auto-persisted to .env; "
                "WHOOP_ENABLED set to true. You can close this tab."
                if refresh_token and verify.get("ok")
                else (
                    "Tokens were issued but verification failed — "
                    "see `verify` in the response. "
                    "Re-initiate at /api/auth/whoop if needed."
                )
            ),
            "persisted_env_keys": persisted,
            "expires_in": tokens.get("expires_in"),
            "scope": tokens.get("scope"),
            "state_echoed": state,
            "verify": verify,
        }
    finally:
        await client.close()
