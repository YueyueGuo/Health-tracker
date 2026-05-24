from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from backend.database import _ensure_compat_schema
from backend.models import Goal, Recovery


async def test_compat_schema_adds_strength_performed_at_column():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE strength_sets (
                    id INTEGER PRIMARY KEY,
                    reps INTEGER NOT NULL
                )
                """
            )
        )

        await _ensure_compat_schema(conn)
        await _ensure_compat_schema(conn)

        rows = (await conn.execute(text("PRAGMA table_info(strength_sets)"))).mappings()
        columns = {row["name"] for row in rows}

    await engine.dispose()

    assert "performed_at" in columns


def test_recovery_tablename_matches_railway_schema():
    """Regression guard for W1-schema-drift.

    The Railway Postgres database stores Whoop daily recovery rows in a
    table named ``recovery_metrics`` (per the initial-schema migration
    ``353259d46b97`` and ``docs/audit-001-findings.md``). At one point
    stale diagnostic / debug code referenced ``recovery_records``, which
    caused Whoop recovery writes to raise ``relation "recovery_records"
    does not exist``. Lock in the canonical DB name so the model never
    drifts from the migration history again.
    """
    assert Recovery.__tablename__ == "recovery_metrics"


def test_goal_tablename_matches_railway_schema():
    """Regression guard for W1-schema-drift.

    The Railway Postgres database stores training goals in a table named
    ``goals`` (per migration ``c1a4e8f27b10_goals_rpe_feedback``). At one
    point stale diagnostic code referenced ``goal``. Lock in the
    canonical DB name.
    """
    assert Goal.__tablename__ == "goals"
