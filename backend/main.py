from __future__ import annotations

import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from backend.database import init_db
from backend.scheduler import create_scheduler

FRONTEND_DIR = pathlib.Path(__file__).resolve().parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    scheduler = create_scheduler()
    scheduler.start()
    app.state.scheduler = scheduler
    yield
    # Shutdown
    scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Health Tracker",
        description="Personal health & fitness analytics platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Import and register routers
    from backend.routers import (
        activities,
        auth,
        chat,
        correlations,
        dashboard,
        insights,
        locations,
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
