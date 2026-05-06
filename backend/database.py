from __future__ import annotations

import os
import pathlib

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from backend.config import settings


def _database_url() -> str:
    """Return an async SQLAlchemy URL for local SQLite or Railway Postgres."""
    url = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("DATABASE_PUBLIC_URL")
        or settings.database_url
    )
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


db_url = _database_url()

def _ensure_sqlite_dir(url: str) -> None:
    prefix = "sqlite+aiosqlite:///"
    if url.startswith(prefix):
        db_path = pathlib.Path(url[len(prefix):])
        db_path.parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_dir(db_url)

connect_args = {"timeout": 30} if db_url.startswith("sqlite") else {}

engine = create_async_engine(
    db_url,
    echo=False,
    connect_args=connect_args,
)

if db_url.startswith("sqlite"):
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    """Dependency for FastAPI routes."""
    async with async_session() as session:
        yield session


async def init_db() -> None:
    """Create all tables (used by setup script and tests)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_compat_schema(conn)


async def _ensure_compat_schema(conn) -> None:
    """Apply tiny compatibility fixes create_all cannot make.

    Existing databases may predate nullable Alembic columns. SQLAlchemy's
    ``create_all`` leaves those tables untouched, so add safe nullable columns
    here before the app accepts writes. This is intentionally narrow; Alembic
    remains the canonical migration history.
    """
    dialect = conn.dialect.name
    if dialect == "sqlite":
        rows = (
            await conn.execute(text("PRAGMA table_info(strength_sets)"))
        ).mappings()
        columns = {row["name"] for row in rows}
        column_type = "DATETIME"
    elif dialect == "postgresql":
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'strength_sets'
                    """
                )
            )
        ).mappings()
        columns = {row["column_name"] for row in rows}
        column_type = "TIMESTAMP"
    else:
        return

    if columns and "performed_at" not in columns:
        await conn.execute(
            text(f"ALTER TABLE strength_sets ADD COLUMN performed_at {column_type}")
        )
