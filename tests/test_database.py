from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from backend.database import _ensure_compat_schema


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
