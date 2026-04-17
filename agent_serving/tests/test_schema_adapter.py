"""Tests for schema adapter — direct SQLite DDL loading."""
import pytest
import aiosqlite
from agent_serving.serving.repositories.schema_adapter import (
    load_sqlite_ddl,
    create_asset_tables_sqlite,
)


def test_load_sqlite_ddl_contains_all_tables():
    ddl = load_sqlite_ddl()
    assert "asset_source_batches" in ddl
    assert "asset_publish_versions" in ddl
    assert "asset_raw_documents" in ddl
    assert "asset_raw_segments" in ddl
    assert "asset_canonical_segments" in ddl
    assert "asset_canonical_segment_sources" in ddl


def test_sqlite_ddl_has_no_pg_syntax():
    ddl = load_sqlite_ddl()
    assert "JSONB" not in ddl
    assert "TIMESTAMPTZ" not in ddl
    assert "gen_random_uuid" not in ddl


@pytest.mark.asyncio
async def test_create_tables_in_sqlite():
    db = await aiosqlite.connect(":memory:")
    await create_asset_tables_sqlite(db)
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = [row[0] for row in await cursor.fetchall()]
    assert "asset_source_batches" in tables
    assert "asset_publish_versions" in tables
    assert "asset_raw_documents" in tables
    assert "asset_raw_segments" in tables
    assert "asset_canonical_segments" in tables
    assert "asset_canonical_segment_sources" in tables
    await db.close()


@pytest.mark.asyncio
async def test_sqlite_ddl_has_v05_fields():
    """Verify v0.5 fields exist in the created tables."""
    db = await aiosqlite.connect(":memory:")
    await create_asset_tables_sqlite(db)

    # raw_documents should have scope_json, not product
    cursor = await db.execute("PRAGMA table_info(asset_raw_documents)")
    cols = {row[1] for row in await cursor.fetchall()}
    assert "scope_json" in cols
    assert "product" not in cols
    assert "entity_refs_json" not in cols  # that's in segments, not docs

    # raw_segments should have entity_refs_json, not command_name
    cursor = await db.execute("PRAGMA table_info(asset_raw_segments)")
    cols = {row[1] for row in await cursor.fetchall()}
    assert "entity_refs_json" in cols
    assert "block_type" in cols
    assert "semantic_role" in cols
    assert "command_name" not in cols
    assert "segment_type" not in cols

    # canonical_segments should have entity_refs_json, scope_json
    cursor = await db.execute("PRAGMA table_info(asset_canonical_segments)")
    cols = {row[1] for row in await cursor.fetchall()}
    assert "entity_refs_json" in cols
    assert "scope_json" in cols
    assert "block_type" in cols
    assert "semantic_role" in cols

    await db.close()
