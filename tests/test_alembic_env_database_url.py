"""Regression test for alembic/env.py honoring DATABASE_URL.

Before this fix, env.py ignored the DATABASE_URL env var and only read
``sqlalchemy.url`` from alembic.ini (hardcoded to SQLite). That meant
``alembic upgrade head`` against Railway Postgres couldn't be run from
the deploy container without editing alembic.ini, which is why the
Apple Health migration (PR #42) never made it to production. See
``docs/bugs/apple-health-prod-migration.md``.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_alembic_offline_sql(env_extra: dict[str, str]) -> tuple[str, str]:
    """Invoke ``alembic upgrade head:head --sql`` in a subprocess.

    Subprocess isolation matters: env.py runs at import time and we don't
    want its module-level alembic context to leak into other tests.
    """
    env = {**os.environ, **env_extra}
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head:head", "--sql"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"alembic exited {proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    return proc.stdout, proc.stderr


def test_env_py_picks_up_postgres_database_url():
    """A `postgresql://` DATABASE_URL drives the Postgres dialect."""
    _, stderr = _run_alembic_offline_sql(
        {"DATABASE_URL": "postgresql://u:p@host.invalid:5432/db"}
    )
    assert "PostgresqlImpl" in stderr, stderr
    assert "SQLiteImpl" not in stderr, stderr


def test_env_py_rewrites_heroku_style_postgres_scheme():
    """`postgres://` (Heroku/Railway legacy) also drives Postgres dialect."""
    _, stderr = _run_alembic_offline_sql(
        {"DATABASE_URL": "postgres://u:p@host.invalid:5432/db"}
    )
    assert "PostgresqlImpl" in stderr, stderr


def test_env_py_falls_back_to_sqlite_when_database_url_unset():
    """Without DATABASE_URL, env.py uses settings.database_url (SQLite)."""
    env = {k: v for k, v in os.environ.items() if k not in {"DATABASE_URL", "DATABASE_PUBLIC_URL"}}
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head:head", "--sql"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "SQLiteImpl" in proc.stderr, proc.stderr
