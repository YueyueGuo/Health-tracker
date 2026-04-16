from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    yield
    # Shutdown


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
    from backend.routers import activities, auth, chat, dashboard, recovery, sleep, sync

    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(activities.router, prefix="/api/activities", tags=["activities"])
    app.include_router(sleep.router, prefix="/api/sleep", tags=["sleep"])
    app.include_router(recovery.router, prefix="/api/recovery", tags=["recovery"])
    app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
    app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
    app.include_router(sync.router, prefix="/api/sync", tags=["sync"])

    @app.get("/api/health")
    async def health_check():
        return {"status": "ok", "version": "0.1.0"}

    return app


app = create_app()
