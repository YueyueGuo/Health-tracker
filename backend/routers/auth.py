from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse

from backend.clients.strava import StravaClient
from backend.clients.whoop import WhoopClient
from backend.config import settings

router = APIRouter()


@router.get("/strava")
async def strava_auth(request: Request):
    """Initiate Strava OAuth2 flow."""
    client = StravaClient()
    redirect_uri = f"http://{settings.host}:{settings.port}/api/auth/strava/callback"
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
    """Initiate Whoop OAuth2 flow."""
    client = WhoopClient()
    redirect_uri = f"http://{settings.host}:{settings.port}/api/auth/whoop/callback"
    url = client.get_authorization_url(redirect_uri)
    await client.close()
    return RedirectResponse(url)


@router.get("/whoop/callback")
async def whoop_callback(code: str = Query(...)):
    """Handle Whoop OAuth2 callback."""
    client = WhoopClient()
    try:
        tokens = await client.exchange_code(code)
        return {
            "status": "success",
            "message": "Whoop connected! Add these to your .env file:",
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
        }
    finally:
        await client.close()
