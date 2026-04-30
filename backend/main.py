from __future__ import annotations

import asyncio
import logging
import pathlib
import time
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.database import init_db
from backend.scheduler import create_scheduler

logger = logging.getLogger(__name__)

FRONTEND_DIR = pathlib.Path(__file__).resolve().parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    scheduler = create_scheduler()
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info("Scheduler started")

    if settings.sync_on_startup:
        # Fire-and-forget so startup isn't blocked by API latency / rate limits.
        from backend.scheduler import _run_sync

        async def _startup_sync():
            try:
                await _run_sync("all")
            except Exception:
                logger.exception("Startup sync failed")

        app.state.startup_sync_task = asyncio.create_task(_startup_sync())
        logger.info("Startup sync scheduled")

    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        startup_sync_task = getattr(app.state, "startup_sync_task", None)
        if startup_sync_task and not startup_sync_task.done():
            startup_sync_task.cancel()
            with suppress(asyncio.CancelledError):
                await startup_sync_task
        logger.info("Scheduler stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Health Tracker",
        description="Personal health & fitness analytics platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    origins = ["http://localhost:5173", "http://localhost:3000"]
    if settings.tailscale_hostname:
        host = settings.tailscale_hostname
        origins.extend([f"http://{host}", f"https://{host}", f"http://{host}:{settings.port}"])
    origins.extend(settings.cors_origins)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def log_api_request_timing(request: Request, call_next):
        """Log API latency and set cache headers for immutable Vite assets."""
        if not request.url.path.startswith("/api"):
            response = await call_next(request)
            if request.url.path.startswith("/assets/"):
                response.headers["Cache-Control"] = (
                    "public, max-age=31536000, immutable"
                )
            return response

        started_at = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started_at) * 1000
            logger.exception(
                "api.request method=%s path=%s status=500 duration_ms=%.1f failed=true",
                request.method,
                request.url.path,
                duration_ms,
            )
            raise

        duration_ms = (time.perf_counter() - started_at) * 1000
        response.headers["X-Process-Time-Ms"] = f"{duration_ms:.1f}"
        response.headers["Server-Timing"] = f"app;dur={duration_ms:.1f}"
        message = (
            "api.request method=%s path=%s status=%s duration_ms=%.1f "
            "server_timing=true"
        )
        args = (request.method, request.url.path, response.status_code, duration_ms)
        if response.status_code >= 500 or duration_ms >= 1000:
            logger.warning(message, *args)
        else:
            logger.info(message, *args)
        return response

    # Import and register routers
    from backend.routers import (
        activities,
        auth,
        chat,
        correlations,
        dashboard,
        goals,
        insights,
        locations,
        profile,
        recovery,
        sleep,
        strength,
        summary,
        sync,
        weather,
    )

    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(activities.router, prefix="/api/activities", tags=["activities"])
    # Activity location-attach endpoints live in routers/locations.py but are
    # mounted under /api/activities for a consistent REST surface.
    app.include_router(
        locations.attach_router, prefix="/api/activities", tags=["activities"]
    )
    app.include_router(sleep.router, prefix="/api/sleep", tags=["sleep"])
    app.include_router(strength.router, prefix="/api/strength", tags=["strength"])
    app.include_router(recovery.router, prefix="/api/recovery", tags=["recovery"])
    app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
    app.include_router(summary.router, prefix="/api/summary", tags=["summary"])
    app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
    app.include_router(sync.router, prefix="/api/sync", tags=["sync"])
    app.include_router(correlations.router, prefix="/api/correlations", tags=["correlations"])
    app.include_router(weather.router, prefix="/api/weather", tags=["weather"])
    app.include_router(insights.router, prefix="/api/insights", tags=["insights"])
    app.include_router(locations.router, prefix="/api/locations", tags=["locations"])
    app.include_router(goals.router, prefix="/api/goals", tags=["goals"])
    app.include_router(profile.router, prefix="/api/profile", tags=["profile"])

    @app.get("/api/health")
    async def health_check():
        return {"status": "ok", "version": "0.1.0"}

    # Serve the built React frontend from the same server.
    #
    # Hashed files under /assets are safe to cache forever (each Vite build
    # rewrites the filename), but index.html MUST NOT be cached by the
    # browser — otherwise a stale index.html keeps pointing at an old JS
    # bundle filename and any backend change (like a new router) never gets
    # picked up. Real users hit this as "Unexpected token '<'" errors when
    # the cached JS calls an endpoint that didn't exist in the old deploy.
    if FRONTEND_DIR.exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="static")

        @app.get("/{full_path:path}")
        async def serve_frontend(request: Request, full_path: str):
            # Serve index.html for all non-API routes (SPA client-side routing)
            return FileResponse(
                FRONTEND_DIR / "index.html",
                headers={
                    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )

    return app


app = create_app()
