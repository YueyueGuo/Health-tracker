import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from backend.database import Base, _database_url  # _database_url is intentionally imported here so migrations resolve the URL the same way the app does
from backend.models import *  # noqa: F401, F403 — ensure all models are registered

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Mirror runtime URL resolution (DATABASE_URL / DATABASE_PUBLIC_URL → asyncpg)
# so `alembic upgrade head` works in the Railway container, where alembic.ini's
# hardcoded sqlite URL is wrong. Gated on the env vars actually being set so
# tests that pass a custom URL via `Config().set_main_option(...)` still win.
if os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL"):
    config.set_main_option("sqlalchemy.url", _database_url())

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
