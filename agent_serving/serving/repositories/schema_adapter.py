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
    """Create all asset tables in a SQLite database using shared DDL.

    After loading the shared DDL, applies v1.2 migrations that Mining
    will eventually write to the canonical schema. This keeps Serving
    tests ahead of the shared DDL without forking it.
    """
    ddl = load_sqlite_ddl()
    await db.executescript(ddl)

    # v1.2 migration: source_segment_id bridge column on retrieval_units
    # Mining will add this to the canonical DDL; until then, ALTER here.
    try:
        await db.execute(
            "ALTER TABLE asset_retrieval_units "
            "ADD COLUMN source_segment_id TEXT NULL "
            "REFERENCES asset_raw_segments(id) ON DELETE SET NULL"
        )
    except Exception:
        pass  # Column already exists —Mining's DDL caught up

    await db.commit()
