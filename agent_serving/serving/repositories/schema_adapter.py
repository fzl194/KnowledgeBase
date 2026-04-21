"""Schema adapter: load shared SQLite DDL for dev/test.

Reads the shared `databases/asset_core/schemas/001_asset_core.sqlite.sql`
directly — no dynamic PG→SQLite conversion. This is the ONLY place
where asset table structure is loaded for dev/test mode.

No other code in agent_serving should maintain private asset DDL.
"""
from __future__ import annotations

import os

import aiosqlite

_SCHEMA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "databases", "asset_core", "schemas", "001_asset_core.sqlite.sql",
)


def load_sqlite_ddl() -> str:
    with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
        return f.read()


async def create_asset_tables_sqlite(db: aiosqlite.Connection) -> None:
    """Create all asset tables in a SQLite database using shared DDL."""
    ddl = load_sqlite_ddl()
    await db.executescript(ddl)
    await db.commit()
