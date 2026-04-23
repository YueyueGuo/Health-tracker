"""Shared fixtures for router tests.

Spins up an in-memory SQLite for each test, wires `get_db` override into
a minimal FastAPI app that mounts just the router under test, and yields
an httpx AsyncClient bound to that app.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.database import Base, get_db


@pytest.fixture
async def db_and_sessionmaker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    yield engine, Session
    await engine.dispose()


@pytest.fixture
async def db(db_and_sessionmaker) -> AsyncIterator[AsyncSession]:
    _, Session = db_and_sessionmaker
    async with Session() as session:
        yield session


def make_client(router, prefix: str, sessionmaker) -> AsyncClient:
    """Mount ``router`` at ``prefix`` on a fresh FastAPI app with an
    in-memory DB override."""
    app = FastAPI()
    app.include_router(router, prefix=prefix)

    async def _override() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_db] = _override
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
