# M1 Agent Serving Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the online query pipeline: Agent/Skill request -> query constraint recognition -> search L1 canonical_segments -> drill down via L2 to L0 raw_segments -> return context pack.

**Architecture:** Three-layer FastAPI service — API routes call Application layer (Normalizer → Assembler), which delegates data access to Repository layer. SQLite dev mode with schema adapter from shared contract. Pure SQL retrieval (FTS/LIKE), no vector search in M1.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, aiosqlite, pytest + pytest-asyncio + httpx

**Design doc:** `docs/plans/2026-04-15-m1-agent-serving-design.md`
**Schema contract:** `knowledge_assets/schemas/001_asset_core.sql`
**Schema README:** `knowledge_assets/schemas/README.md`
**Codex review:** `docs/analysis/2026-04-16-m1-agent-serving-codex-review.md`
**Commit prefix:** `[claude-serving]:`

**修订记录:**
- v1.0 初版
- v1.1 修订：修复 Codex review P1-P2（schema fixture 契约、dev 启动闭环、conflict candidate、文件清单同步）

---

### Task 1: Add aiosqlite dependency

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add aiosqlite to dependencies**

```toml
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "aiosqlite>=0.20",
]
```

**Step 2: Install**

Run: `pip install -e ".[dev]"`
Expected: success

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "[claude-serving]: add aiosqlite dependency for dev mode SQLite"
```

---

### Task 2: Schema adapter — PostgreSQL → SQLite DDL generator

> **Codex review P1 fix:** 测试 fixture 不允许维护私有 asset DDL。所有 SQLite 测试表结构必须从共享 schema `001_asset_core.sql` 转换生成。

**Files:**
- Create: `agent_serving/serving/repositories/schema_adapter.py`
- Create: `agent_serving/tests/test_schema_adapter.py`

**Step 1: Write test**

Create `agent_serving/tests/test_schema_adapter.py`:

```python
"""Tests for schema adapter — PostgreSQL to SQLite DDL conversion."""
import os
import pytest
import aiosqlite
from agent_serving.serving.repositories.schema_adapter import (
    build_sqlite_ddl_from_asset_schema,
    create_asset_tables_sqlite,
)


SCHEMA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "knowledge_assets", "schemas", "001_asset_core.sql",
)


def test_build_sqlite_ddl_produces_all_tables():
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        pg_sql = f.read()
    ddl = build_sqlite_ddl_from_asset_schema(pg_sql)
    assert "asset_publish_versions" in ddl
    assert "asset_raw_documents" in ddl
    assert "asset_raw_segments" in ddl
    assert "asset_canonical_segments" in ddl
    assert "asset_canonical_segment_sources" in ddl


def test_no_pg_specific_syntax():
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        pg_sql = f.read()
    ddl = build_sqlite_ddl_from_asset_schema(pg_sql)
    assert "CREATE EXTENSION" not in ddl
    assert "CREATE SCHEMA" not in ddl
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
    assert "asset_publish_versions" in tables
    assert "asset_raw_documents" in tables
    assert "asset_raw_segments" in tables
    assert "asset_canonical_segments" in tables
    assert "asset_canonical_segment_sources" in tables
    await db.close()
```

**Step 2: Run test to verify it fails**

Run: `pytest agent_serving/tests/test_schema_adapter.py -v`
Expected: FAIL — module not found

**Step 3: Write implementation**

Create `agent_serving/serving/repositories/schema_adapter.py`:

```python
"""Schema adapter: convert PostgreSQL asset DDL to SQLite-compatible DDL.

This module reads the shared schema contract at
`knowledge_assets/schemas/001_asset_core.sql` and produces
SQLite-compatible DDL. It is the ONLY place where asset table
structure is defined for dev/test mode.

No other code in agent_serving should maintain private asset DDL.
"""
from __future__ import annotations

import os
import re

import aiosqlite

_SCHEMA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "knowledge_assets", "schemas", "001_asset_core.sql",
)


def load_asset_schema_sql() -> str:
    with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
        return f.read()


def build_sqlite_ddl_from_asset_schema(pg_sql: str) -> str:
    """Convert PostgreSQL asset DDL to SQLite-compatible DDL.

    Transformations:
    - Strip CREATE EXTENSION / CREATE SCHEMA
    - Strip partial / unique indexes and GIN indexes
    - Replace `asset.tablename` with `asset_tablename`
    - UUID → TEXT, TIMESTAMPTZ → TEXT, JSONB → TEXT
    - Remove gen_random_uuid() defaults
    - Remove PostgreSQL-specific CHECK constraints on JSONB
    - Remove `::jsonb` casts
    """
    lines = pg_sql.split("\n")
    output_lines: list[str] = []
    skip_block = False

    for line in lines:
        stripped = line.strip()

        # Skip empty schema/extension creation
        if stripped.startswith("CREATE EXTENSION") or stripped.startswith("CREATE SCHEMA"):
            continue

        # Skip index creation (SQLite handles indexing differently)
        if stripped.startswith("CREATE ") and "INDEX" in stripped.upper():
            skip_block = True
            continue

        # End of skipped index block
        if skip_block and not stripped.endswith(";"):
            continue
        if skip_block and stripped.endswith(";"):
            skip_block = False
            continue

        # Transform table references: asset.name → asset_name
        line = re.sub(r'\basset\.', "asset_", line)

        # Type conversions
        line = line.replace("UUID", "TEXT")
        line = line.replace("JSONB", "TEXT")
        line = line.replace("TIMESTAMPTZ", "TEXT")
        line = line.replace("NUMERIC(5,4)", "REAL")
        line = re.sub(r"DEFAULT gen_random_uuid\(\)", "", line)
        line = line.replace("'[]'::jsonb", "'[]'")
        line = line.replace("'{}'::jsonb", "'{}'")

        # Remove JSONB typeof check (SQLite can't do this)
        if "jsonb_typeof" in line:
            continue

        output_lines.append(line)

    return "\n".join(output_lines)


async def create_asset_tables_sqlite(db: aiosqlite.Connection) -> None:
    """Create all asset tables in a SQLite database using shared schema."""
    pg_sql = load_asset_schema_sql()
    sqlite_ddl = build_sqlite_ddl_from_asset_schema(pg_sql)
    await db.executescript(sqlite_ddl)
    await db.commit()
```

**Step 4: Run tests**

Run: `pytest agent_serving/tests/test_schema_adapter.py -v`
Expected: 3 passed

**Step 5: Commit**

```bash
git add agent_serving/serving/repositories/schema_adapter.py agent_serving/tests/test_schema_adapter.py
git commit -m "[claude-serving]: add schema adapter to generate SQLite DDL from shared asset schema"
```

---

### Task 3: Pydantic request/response models

**Files:**
- Create: `agent_serving/serving/schemas/models.py`
- Create: `agent_serving/tests/test_models.py`

**Step 1: Write test**

Create `agent_serving/tests/test_models.py`:

```python
"""Verify Pydantic models serialize/deserialize correctly."""
import pytest
from agent_serving.serving.schemas.models import (
    SearchRequest,
    CommandUsageRequest,
    ContextPack,
    NormalizedQuery,
    KeyObjects,
    AnswerMaterials,
)


def test_search_request_defaults():
    req = SearchRequest(query="ADD APN 怎么写")
    assert req.query == "ADD APN 怎么写"


def test_command_usage_request():
    req = CommandUsageRequest(query="UDG V100R023C10 ADD APN")
    assert req.query == "UDG V100R023C10 ADD APN"


def test_normalized_query_missing_constraints():
    nq = NormalizedQuery(
        command="ADD APN",
        product=None,
        product_version=None,
        network_element=None,
        keywords=[],
        missing_constraints=["product", "product_version"],
    )
    assert "product" in nq.missing_constraints


def test_context_pack_serialization():
    pack = ContextPack(
        query="ADD APN",
        intent="command_usage",
        normalized_query="ADD APN",
        key_objects=KeyObjects(command="ADD APN"),
        answer_materials=AnswerMaterials(canonical_segments=[], raw_segments=[]),
        sources=[],
        uncertainties=[],
        suggested_followups=[],
    )
    data = pack.model_dump()
    assert data["intent"] == "command_usage"
    assert data["answer_materials"]["canonical_segments"] == []
```

**Step 2: Run test to verify it fails**

Run: `pytest agent_serving/tests/test_models.py -v`
Expected: FAIL — module not found

**Step 3: Write implementation**

Create `agent_serving/serving/schemas/models.py`:

```python
"""Pydantic models for Agent Serving request/response."""
from __future__ import annotations

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str


class CommandUsageRequest(BaseModel):
    query: str


class KeyObjects(BaseModel):
    command: str | None = None
    product: str | None = None
    product_version: str | None = None
    network_element: str | None = None


class NormalizedQuery(BaseModel):
    command: str | None = None
    product: str | None = None
    product_version: str | None = None
    network_element: str | None = None
    keywords: list[str] = Field(default_factory=list)
    missing_constraints: list[str] = Field(default_factory=list)


class CanonicalSegmentRef(BaseModel):
    id: str
    segment_type: str
    title: str | None = None
    canonical_text: str
    command_name: str | None = None
    has_variants: bool = False
    variant_policy: str = "none"


class RawSegmentRef(BaseModel):
    id: str
    segment_type: str
    raw_text: str
    command_name: str | None = None
    section_path: list[str] = Field(default_factory=list)
    section_title: str | None = None


class AnswerMaterials(BaseModel):
    canonical_segments: list[CanonicalSegmentRef] = Field(default_factory=list)
    raw_segments: list[RawSegmentRef] = Field(default_factory=list)


class SourceRef(BaseModel):
    document_key: str
    section_path: list[str] = Field(default_factory=list)
    segment_type: str
    product: str | None = None
    product_version: str | None = None
    network_element: str | None = None


class Uncertainty(BaseModel):
    field: str
    reason: str
    suggested_options: list[str] = Field(default_factory=list)


class ContextPack(BaseModel):
    query: str
    intent: str
    normalized_query: str
    key_objects: KeyObjects = Field(default_factory=KeyObjects)
    answer_materials: AnswerMaterials = Field(default_factory=AnswerMaterials)
    sources: list[SourceRef] = Field(default_factory=list)
    uncertainties: list[Uncertainty] = Field(default_factory=list)
    suggested_followups: list[str] = Field(default_factory=list)
    debug_trace: dict | None = None
```

**Step 4: Run test**

Run: `pytest agent_serving/tests/test_models.py -v`
Expected: 4 passed

**Step 5: Commit**

```bash
git add agent_serving/serving/schemas/models.py agent_serving/tests/test_models.py
git commit -m "[claude-serving]: add Pydantic request/response models"
```

---

### Task 4: Test fixtures — seed data only, schema from shared contract

> **Codex review P1 fix:** Fixture 不维护私有 DDL。Schema 由 schema adapter 从 `001_asset_core.sql` 生成。Fixture 只插入 seed 数据。

**Files:**
- Create: `agent_serving/tests/conftest.py`

**Step 1: Write fixture**

Create `agent_serving/tests/conftest.py`:

```python
"""Shared test fixtures: SQLite from shared schema + seed data.

Schema tables are created by schema_adapter from the shared
`knowledge_assets/schemas/001_asset_core.sql`. This file only
inserts test data — no private DDL.
"""
from __future__ import annotations

import pytest_asyncio
import aiosqlite

from agent_serving.serving.repositories.schema_adapter import create_asset_tables_sqlite

# Fixed IDs for deterministic tests
ACTIVE_PV_ID = "11111111-1111-1111-1111-111111111111"
DOC_UDG_ID = "22222222-2222-2222-2222-222222222222"
DOC_UNC_ID = "33333333-3333-3333-3333-333333333333"
RAW_SEG_ADD_APN_UDG = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
RAW_SEG_ADD_APN_UNC = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RAW_SEG_5G_CONCEPT = "cccccccc-cccc-cccc-cccc-cccccccccccc"
RAW_SEG_CONFLICT = "44444444-4444-4444-4444-444444444444"
CANON_ADD_APN = "dddddddd-dddd-dddd-dddd-dddddddddddd"
CANON_5G = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
CANON_PARAM = "55555555-5555-5555-5555-555555555555"
SOURCE_ADD_APN_UDG = "ffffffff-ffff-ffff-ffff-ffffffffffff"
SOURCE_ADD_APN_UNC = "00000000-0000-0000-0000-000000000001"
SOURCE_5G = "00000000-0000-0000-0000-000000000002"
SOURCE_CONFLICT = "00000000-0000-0000-0000-000000000003"

SEED_IDS = {
    "active_pv_id": ACTIVE_PV_ID,
    "doc_udg_id": DOC_UDG_ID,
    "doc_unc_id": DOC_UNC_ID,
    "raw_seg_add_apn_udg": RAW_SEG_ADD_APN_UDG,
    "raw_seg_add_apn_unc": RAW_SEG_ADD_APN_UNC,
    "raw_seg_5g_concept": RAW_SEG_5G_CONCEPT,
    "raw_seg_conflict": RAW_SEG_CONFLICT,
    "canon_add_apn": CANON_ADD_APN,
    "canon_5g": CANON_5G,
    "canon_param": CANON_PARAM,
    "source_add_apn_udg": SOURCE_ADD_APN_UDG,
    "source_add_apn_unc": SOURCE_ADD_APN_UNC,
    "source_5g": SOURCE_5G,
    "source_conflict": SOURCE_CONFLICT,
}

# Fixture only contains INSERT statements — no DDL.
SEED_SQL = f"""
-- Active publish version
INSERT INTO asset_publish_versions (id, version_code, status, description)
VALUES ('{ACTIVE_PV_ID}', 'PV-2026-04-15-v1', 'active', 'M1 test seed');

-- L0 Documents (product/version/ne constraints live here per schema README)
INSERT INTO asset_raw_documents (id, publish_version_id, document_key, source_uri, file_name, file_type, product, product_version, network_element, document_type, content_hash)
VALUES
  ('{DOC_UDG_ID}', '{ACTIVE_PV_ID}', 'UDG_OM_REF', 'file:///docs/udg_om.md', 'udg_om.md', 'markdown', 'UDG', 'V100R023C10', 'UDM', 'command_manual', 'hash_udg_om'),
  ('{DOC_UNC_ID}', '{ACTIVE_PV_ID}', 'UNC_OM_REF', 'file:///docs/unc_om.md', 'unc_om.md', 'markdown', 'UNC', 'V100R023C20', 'AMF', 'command_manual', 'hash_unc_om');

-- L0 Raw Segments
INSERT INTO asset_raw_segments (id, publish_version_id, raw_document_id, segment_key, segment_index, section_path, section_title, segment_type, command_name, raw_text, normalized_text, content_hash, normalized_hash)
VALUES
  ('{RAW_SEG_ADD_APN_UDG}', '{ACTIVE_PV_ID}', '{DOC_UDG_ID}', 'UDG_ADD_APN', 0, '["OM参考","MML命令","ADD APN"]', 'ADD APN', 'command', 'ADD APN', 'ADD APN 命令用于在UDG上新增APN配置。语法：ADD APN=<apn-name>,[参数列表]', 'add apn 命令用于在udg上新增apn配置', 'hash_udg_add_apn', 'nhash_udg_add_apn'),
  ('{RAW_SEG_ADD_APN_UNC}', '{ACTIVE_PV_ID}', '{DOC_UNC_ID}', 'UNC_ADD_APN', 0, '["OM参考","MML命令","ADD APN"]', 'ADD APN', 'command', 'ADD APN', 'ADD APN 命令用于在UNC上新增APN配置。语法与UDG版本有差异：ADD APN=<name>,TYPE=<type>,[参数列表]', 'add apn 命令用于在unc上新增apn配置', 'hash_unc_add_apn', 'nhash_unc_add_apn'),
  ('{RAW_SEG_5G_CONCEPT}', '{ACTIVE_PV_ID}', '{DOC_UDG_ID}', 'UDG_5G_INTRO', 1, '["基础知识","5G概述"]', '5G概述', 'concept', NULL, '5G是第五代移动通信技术，支持增强移动宽带、海量机器通信和超高可靠低时延通信三大场景。', '5g是第五代移动通信技术', 'hash_5g', 'nhash_5g'),
  ('{RAW_SEG_CONFLICT}', '{ACTIVE_PV_ID}', '{DOC_UNC_ID}', 'UNC_ADD_APN_CONFLICT', 1, '["OM参考","MML命令","ADD APN"]', 'ADD APN', 'command', 'ADD APN 参数冲突版本：APN=<name>是必填参数，与UDG版本完全不同。', 'add apn 参数冲突版本', 'hash_conflict', 'nhash_conflict');

-- L1 Canonical Segments
INSERT INTO asset_canonical_segments (id, publish_version_id, canonical_key, segment_type, title, command_name, canonical_text, summary, search_text, has_variants, variant_policy)
VALUES
  ('{CANON_ADD_APN}', '{ACTIVE_PV_ID}', 'CANON_ADD_APN', 'command', 'ADD APN 命令', 'ADD APN', 'ADD APN 命令用于新增APN配置。不同产品的参数列表有差异。', 'ADD APN 归并命令参考', 'ADD APN 命令 新增 APN 配置 参数', 1, 'require_product_version'),
  ('{CANON_5G}', '{ACTIVE_PV_ID}', 'CANON_5G_CONCEPT', 'concept', '5G概述', NULL, '5G是第五代移动通信技术，支持增强移动宽带、海量机器通信和超高可靠低时延通信三大场景。', '5G概念归并', '5G 第五代 移动通信 eMBB mMTC URLLC', 0, 'none'),
  ('{CANON_PARAM}', '{ACTIVE_PV_ID}', 'CANON_SET_PARAM', 'parameter', 'SET PARAM 命令参数', 'SET PARAM', 'SET PARAM 用于配置系统参数。', 'SET PARAM 参考', 'SET PARAM 配置 参数', 0, 'none');

-- L2 Canonical Segment Sources (including conflict_candidate)
INSERT INTO asset_canonical_segment_sources (id, publish_version_id, canonical_segment_id, raw_segment_id, relation_type, is_primary, priority, similarity_score, diff_summary, metadata_json)
VALUES
  ('{SOURCE_ADD_APN_UDG}', '{ACTIVE_PV_ID}', '{CANON_ADD_APN}', '{RAW_SEG_ADD_APN_UDG}', 'version_variant', 1, 100, 0.95, 'UDG版本参数列表与UNC不同', '{{}}'),
  ('{SOURCE_ADD_APN_UNC}', '{ACTIVE_PV_ID}', '{CANON_ADD_APN}', '{RAW_SEG_ADD_APN_UNC}', 'version_variant', 0, 100, 0.92, 'UNC版本语法与UDG有差异', '{{}}'),
  ('{SOURCE_5G}', '{ACTIVE_PV_ID}', '{CANON_5G}', '{RAW_SEG_5G_CONCEPT}', 'primary', 1, 100, 1.0, NULL, '{{}}'),
  ('{SOURCE_CONFLICT}', '{ACTIVE_PV_ID}', '{CANON_ADD_APN}', '{RAW_SEG_CONFLICT}', 'conflict_candidate', 0, 50, 0.70, '同一命令在UNC上的参数描述存在矛盾', '{{}}');
"""


@pytest_asyncio.fixture
async def db_connection():
    """In-memory SQLite with schema from shared contract + seed data."""
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    # Schema from shared contract — no private DDL
    await create_asset_tables_sqlite(db)
    # Seed data only
    await db.executescript(SEED_SQL)
    await db.commit()
    yield db
    await db.close()


@pytest.fixture
def seed_ids():
    return SEED_IDS
```

**Step 2: Verify fixture loads**

Run: `pytest agent_serving/tests/test_schema_adapter.py agent_serving/tests/test_models.py -v`
Expected: all pass (no import errors from conftest)

**Step 3: Commit**

```bash
git add agent_serving/tests/conftest.py
git commit -m "[claude-serving]: add test fixtures with schema from shared contract and conflict_candidate seed"
```

---

### Task 5: AssetRepository (TDD)

**Files:**
- Create: `agent_serving/serving/repositories/asset_repo.py`
- Create: `agent_serving/tests/test_asset_repo.py`

**Step 1: Write tests**

Create `agent_serving/tests/test_asset_repo.py`:

```python
"""Tests for AssetRepository — read-only L1/L2/L0 access."""
import pytest
import pytest_asyncio
from agent_serving.serving.repositories.asset_repo import AssetRepository
from agent_serving.tests.conftest import ACTIVE_PV_ID, SEED_IDS


@pytest_asyncio.fixture
async def repo(db_connection):
    return AssetRepository(db_connection)


@pytest.mark.asyncio
async def test_get_active_publish_version_id(repo):
    pv_id = await repo.get_active_publish_version_id()
    assert pv_id == ACTIVE_PV_ID


@pytest.mark.asyncio
async def test_search_canonical_by_command_name(repo):
    results = await repo.search_canonical(command_name="ADD APN")
    assert len(results) == 1
    assert results[0]["command_name"] == "ADD APN"
    assert results[0]["has_variants"] == 1


@pytest.mark.asyncio
async def test_search_canonical_by_keyword(repo):
    results = await repo.search_canonical(keyword="5G")
    assert len(results) == 1
    assert "5G" in results[0]["canonical_text"]


@pytest.mark.asyncio
async def test_search_canonical_empty_result(repo):
    results = await repo.search_canonical(command_name="NOTEXIST")
    assert results == []


@pytest.mark.asyncio
async def test_drill_down_with_product_version(repo):
    """Product/version constraints go through raw_documents per schema README."""
    raw_segs = await repo.drill_down(
        canonical_segment_id=SEED_IDS["canon_add_apn"],
        product="UDG",
        product_version="V100R023C10",
    )
    assert len(raw_segs) == 1
    assert "UDG" in raw_segs[0]["raw_text"]


@pytest.mark.asyncio
async def test_drill_down_without_constraint_returns_all_variants(repo):
    raw_segs = await repo.drill_down(
        canonical_segment_id=SEED_IDS["canon_add_apn"],
    )
    # 2 version_variants + 1 conflict_candidate = 3
    assert len(raw_segs) == 3


@pytest.mark.asyncio
async def test_drill_down_excludes_conflict_candidates(repo):
    raw_segs = await repo.drill_down(
        canonical_segment_id=SEED_IDS["canon_add_apn"],
        exclude_conflict=True,
    )
    assert len(raw_segs) == 2
    assert all(r["relation_type"] != "conflict_candidate" for r in raw_segs)


@pytest.mark.asyncio
async def test_get_conflict_sources(repo):
    conflicts = await repo.get_conflict_sources(
        canonical_segment_id=SEED_IDS["canon_add_apn"],
    )
    assert len(conflicts) == 1
    assert conflicts[0]["relation_type"] == "conflict_candidate"


@pytest.mark.asyncio
async def test_get_raw_segments_by_ids(repo):
    segs = await repo.get_raw_segments_by_ids([SEED_IDS["raw_seg_5g_concept"]])
    assert len(segs) == 1
    assert "5G" in segs[0]["raw_text"]


@pytest.mark.asyncio
async def test_get_document_for_segment(repo):
    doc = await repo.get_document_for_segment(SEED_IDS["raw_seg_add_apn_udg"])
    assert doc["product"] == "UDG"
    assert doc["product_version"] == "V100R023C10"
```

**Step 2: Run tests to verify they fail**

Run: `pytest agent_serving/tests/test_asset_repo.py -v`
Expected: FAIL — module not found

**Step 3: Write implementation**

Create `agent_serving/serving/repositories/asset_repo.py`:

```python
"""Read-only repository for asset tables (L0/L1/L2).

All queries enforce publish_version_id = active version per schema README.
Document-level constraints (product/product_version/network_element) are
obtained by joining raw_segments -> raw_documents, not from L2 metadata.
"""
from __future__ import annotations

from typing import Any

import aiosqlite


class AssetRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def get_active_publish_version_id(self) -> str | None:
        cursor = await self._db.execute(
            "SELECT id FROM asset_publish_versions WHERE status = 'active' LIMIT 1"
        )
        row = await cursor.fetchone()
        return row["id"] if row else None

    async def search_canonical(
        self,
        *,
        command_name: str | None = None,
        keyword: str | None = None,
        pv_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if pv_id is None:
            pv_id = await self.get_active_publish_version_id()
        if pv_id is None:
            return []

        if command_name:
            cursor = await self._db.execute(
                "SELECT * FROM asset_canonical_segments "
                "WHERE publish_version_id = ? AND command_name = ?",
                (pv_id, command_name),
            )
        elif keyword:
            cursor = await self._db.execute(
                "SELECT * FROM asset_canonical_segments "
                "WHERE publish_version_id = ? AND search_text LIKE ?",
                (pv_id, f"%{keyword}%"),
            )
        else:
            return []

        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def drill_down(
        self,
        *,
        canonical_segment_id: str,
        product: str | None = None,
        product_version: str | None = None,
        network_element: str | None = None,
        exclude_conflict: bool = False,
        pv_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """L2 drill-down: canonical -> sources -> raw_segments -> raw_documents.

        Returns raw segments with document-level constraints joined in.
        """
        if pv_id is None:
            pv_id = await self.get_active_publish_version_id()
        if pv_id is None:
            return []

        query = (
            "SELECT rs.*, rd.product, rd.product_version, rd.network_element, "
            "  rd.document_key, "
            "  csources.relation_type, csources.diff_summary "
            "FROM asset_canonical_segment_sources csources "
            "JOIN asset_raw_segments rs ON csources.raw_segment_id = rs.id "
            "JOIN asset_raw_documents rd ON rs.raw_document_id = rd.id "
            "WHERE csources.canonical_segment_id = ? "
            "AND csources.publish_version_id = ?"
        )
        params: list[Any] = [canonical_segment_id, pv_id]

        if exclude_conflict:
            query += " AND csources.relation_type != 'conflict_candidate'"

        if product:
            query += " AND rd.product = ?"
            params.append(product)
        if product_version:
            query += " AND rd.product_version = ?"
            params.append(product_version)
        if network_element:
            query += " AND rd.network_element = ?"
            params.append(network_element)

        query += " ORDER BY csources.is_primary DESC, csources.priority ASC"

        cursor = await self._db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_conflict_sources(
        self,
        *,
        canonical_segment_id: str,
        pv_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get conflict_candidate L2 mappings for a canonical segment."""
        if pv_id is None:
            pv_id = await self.get_active_publish_version_id()
        if pv_id is None:
            return []

        cursor = await self._db.execute(
            "SELECT rs.raw_text, rs.segment_type, rs.command_name, "
            "  rd.product, rd.product_version, rd.network_element, "
            "  csources.relation_type, csources.diff_summary "
            "FROM asset_canonical_segment_sources csources "
            "JOIN asset_raw_segments rs ON csources.raw_segment_id = rs.id "
            "JOIN asset_raw_documents rd ON rs.raw_document_id = rd.id "
            "WHERE csources.canonical_segment_id = ? "
            "AND csources.publish_version_id = ? "
            "AND csources.relation_type = 'conflict_candidate'",
            (canonical_segment_id, pv_id),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_raw_segments_by_ids(
        self, ids: list[str]
    ) -> list[dict[str, Any]]:
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        cursor = await self._db.execute(
            f"SELECT * FROM asset_raw_segments WHERE id IN ({placeholders})",
            ids,
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_document_for_segment(
        self, raw_segment_id: str
    ) -> dict[str, Any] | None:
        cursor = await self._db.execute(
            "SELECT rd.* FROM asset_raw_documents rd "
            "JOIN asset_raw_segments rs ON rs.raw_document_id = rd.id "
            "WHERE rs.id = ?",
            (raw_segment_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
```

**Step 4: Run tests**

Run: `pytest agent_serving/tests/test_asset_repo.py -v`
Expected: 10 passed

**Step 5: Commit**

```bash
git add agent_serving/serving/repositories/asset_repo.py agent_serving/tests/test_asset_repo.py
git commit -m "[claude-serving]: add AssetRepository with conflict source detection"
```

---

### Task 6: QueryNormalizer (TDD)

Same as v1.0 plan. See previous Task 5 for details.

Files:
- `agent_serving/serving/application/normalizer.py`
- `agent_serving/tests/test_normalizer.py`

---

### Task 7: ContextAssembler with conflict handling (TDD)

> **Codex review P1 fix:** conflict_candidate 必须转为 uncertainty/conflict source，不作为普通答案材料。

**Files:**
- Create: `agent_serving/serving/application/assembler.py`
- Create: `agent_serving/tests/test_assembler.py`

**Step 1: Write tests**

Create `agent_serving/tests/test_assembler.py`:

```python
"""Tests for ContextAssembler — context pack + conflict handling."""
import pytest
from agent_serving.serving.application.assembler import ContextAssembler
from agent_serving.serving.schemas.models import NormalizedQuery


def _make_canon(**overrides):
    base = {
        "id": "c1", "segment_type": "command", "title": "ADD APN",
        "canonical_text": "ADD APN 归并文本", "command_name": "ADD APN",
        "has_variants": 1, "variant_policy": "require_product_version",
    }
    base.update(overrides)
    return base


def _make_raw(**overrides):
    base = {
        "id": "r1", "segment_type": "command", "raw_text": "ADD APN 原始文本",
        "command_name": "ADD APN",
        "section_path": '["OM参考","ADD APN"]', "section_title": "ADD APN",
        "product": "UDG", "product_version": "V100R023C10",
        "network_element": "UDM", "document_key": "UDG_OM_REF",
        "relation_type": "version_variant", "diff_summary": None,
    }
    base.update(overrides)
    return base


def test_assemble_no_variants():
    asm = ContextAssembler()
    pack = asm.assemble(
        query="5G是什么", intent="general",
        normalized=NormalizedQuery(keywords=["5G"]),
        canonical_hits=[_make_canon(has_variants=0, variant_policy="none")],
        drill_results=[], conflict_sources=[],
    )
    assert len(pack.answer_materials.canonical_segments) == 1
    assert len(pack.uncertainties) == 0


def test_assemble_with_variants_and_constraints_met():
    asm = ContextAssembler()
    pack = asm.assemble(
        query="UDG V100R023C10 ADD APN", intent="command_usage",
        normalized=NormalizedQuery(command="ADD APN", product="UDG", product_version="V100R023C10"),
        canonical_hits=[_make_canon()],
        drill_results=[_make_raw()], conflict_sources=[],
    )
    assert len(pack.answer_materials.raw_segments) == 1
    assert len(pack.uncertainties) == 0


def test_assemble_variants_but_missing_constraints():
    asm = ContextAssembler()
    pack = asm.assemble(
        query="ADD APN 怎么写", intent="command_usage",
        normalized=NormalizedQuery(command="ADD APN", missing_constraints=["product", "product_version"]),
        canonical_hits=[_make_canon()],
        drill_results=[], conflict_sources=[],
    )
    assert len(pack.uncertainties) > 0
    assert any(u.field == "product" for u in pack.uncertainties)


def test_assemble_conflict_candidates_become_uncertainties():
    """conflict_candidate must NOT appear as regular answer material."""
    asm = ContextAssembler()
    conflict = {
        "raw_text": "冲突版本文本", "segment_type": "command",
        "command_name": "ADD APN", "product": "UNC",
        "product_version": "V100R023C20", "network_element": "AMF",
        "relation_type": "conflict_candidate",
        "diff_summary": "同一命令在UNC上的参数描述存在矛盾",
    }
    pack = asm.assemble(
        query="ADD APN 参数说明", intent="command_usage",
        normalized=NormalizedQuery(command="ADD APN"),
        canonical_hits=[_make_canon()],
        drill_results=[], conflict_sources=[conflict],
    )
    # Conflict should be in uncertainties, NOT in raw_segments
    assert len(pack.answer_materials.raw_segments) == 0
    assert any("冲突" in u.reason or "conflict" in u.reason.lower() for u in pack.uncertainties)
```

**Step 2: Run tests to verify they fail**

Run: `pytest agent_serving/tests/test_assembler.py -v`
Expected: FAIL — module not found

**Step 3: Write implementation**

Create `agent_serving/serving/application/assembler.py`:

```python
"""ContextAssembler — build context pack with conflict handling."""
from __future__ import annotations

import json

from agent_serving.serving.schemas.models import (
    AnswerMaterials,
    CanonicalSegmentRef,
    ContextPack,
    KeyObjects,
    NormalizedQuery,
    RawSegmentRef,
    SourceRef,
    Uncertainty,
)


class ContextAssembler:
    def assemble(
        self,
        *,
        query: str,
        intent: str,
        normalized: NormalizedQuery,
        canonical_hits: list[dict],
        drill_results: list[dict],
        conflict_sources: list[dict],
    ) -> ContextPack:
        key_objects = KeyObjects(
            command=normalized.command,
            product=normalized.product,
            product_version=normalized.product_version,
            network_element=normalized.network_element,
        )

        canon_refs = [
            CanonicalSegmentRef(
                id=str(h["id"]),
                segment_type=h["segment_type"],
                title=h.get("title"),
                canonical_text=h["canonical_text"],
                command_name=h.get("command_name"),
                has_variants=bool(h.get("has_variants")),
                variant_policy=h.get("variant_policy", "none"),
            )
            for h in canonical_hits
        ]

        raw_refs = [
            RawSegmentRef(
                id=str(r["id"]),
                segment_type=r["segment_type"],
                raw_text=r["raw_text"],
                command_name=r.get("command_name"),
                section_path=_parse_section_path(r.get("section_path", "[]")),
                section_title=r.get("section_title"),
            )
            for r in drill_results
        ]

        sources = self._build_sources(drill_results)
        uncertainties = self._build_uncertainties(normalized, canonical_hits)
        # Add conflict uncertainties
        conflict_uncertainties = self._build_conflict_uncertainties(conflict_sources)
        uncertainties.extend(conflict_uncertainties)

        followups = self._build_followups(uncertainties)

        return ContextPack(
            query=query,
            intent=intent,
            normalized_query=self._build_normalized_str(normalized),
            key_objects=key_objects,
            answer_materials=AnswerMaterials(
                canonical_segments=canon_refs,
                raw_segments=raw_refs,
            ),
            sources=sources,
            uncertainties=uncertainties,
            suggested_followups=followups,
        )

    def _build_sources(self, drill_results: list[dict]) -> list[SourceRef]:
        return [
            SourceRef(
                document_key=r.get("document_key", ""),
                section_path=_parse_section_path(r.get("section_path", "[]")),
                segment_type=r["segment_type"],
                product=r.get("product"),
                product_version=r.get("product_version"),
                network_element=r.get("network_element"),
            )
            for r in drill_results
        ]

    def _build_uncertainties(
        self, normalized: NormalizedQuery, hits: list[dict]
    ) -> list[Uncertainty]:
        uncertainties: list[Uncertainty] = []
        has_variants_hit = any(h.get("has_variants") for h in hits)

        if has_variants_hit and normalized.missing_constraints:
            if "product" in normalized.missing_constraints:
                uncertainties.append(
                    Uncertainty(
                        field="product",
                        reason="该命令在不同产品上有差异，需要指定产品",
                        suggested_options=["UDG", "UNC", "UPF"],
                    )
                )
            if "product_version" in normalized.missing_constraints:
                uncertainties.append(
                    Uncertainty(
                        field="product_version",
                        reason="该命令参数在不同版本间可能有差异",
                        suggested_options=[],
                    )
                )
        return uncertainties

    def _build_conflict_uncertainties(
        self, conflict_sources: list[dict]
    ) -> list[Uncertainty]:
        """Convert conflict_candidate sources into uncertainties.

        Conflict candidates are NOT returned as answer materials.
        They become uncertainty items telling the Agent there's contradictory info.
        """
        uncertainties: list[Uncertainty] = []
        for cs in conflict_sources:
            product = cs.get("product", "未知产品")
            diff = cs.get("diff_summary", "存在内容矛盾")
            uncertainties.append(
                Uncertainty(
                    field="conflict",
                    reason=f"知识库中存在冲突来源（{product}）：{diff}",
                    suggested_options=[product],
                )
            )
        return uncertainties

    def _build_followups(self, uncertainties: list[Uncertainty]) -> list[str]:
        if not uncertainties:
            return []
        conflict_fields = [u.field for u in uncertainties if u.field != "conflict"]
        conflict_count = sum(1 for u in uncertainties if u.field == "conflict")
        parts = []
        if conflict_fields:
            parts.append(f"请确认{'/'.join(conflict_fields)}以获取精确答案")
        if conflict_count > 0:
            parts.append(f"发现 {conflict_count} 处知识冲突，建议核实产品版本后重新查询")
        return parts

    def _build_normalized_str(self, normalized: NormalizedQuery) -> str:
        parts: list[str] = []
        if normalized.command:
            parts.append(normalized.command)
        if normalized.product:
            parts.append(normalized.product)
        if normalized.product_version:
            parts.append(normalized.product_version)
        if normalized.network_element:
            parts.append(normalized.network_element)
        parts.extend(normalized.keywords)
        return " ".join(parts)


def _parse_section_path(raw: str | list) -> list[str]:
    if isinstance(raw, list):
        return raw
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []
```

**Step 4: Run tests**

Run: `pytest agent_serving/tests/test_assembler.py -v`
Expected: 4 passed

**Step 5: Commit**

```bash
git add agent_serving/serving/application/assembler.py agent_serving/tests/test_assembler.py
git commit -m "[claude-serving]: add ContextAssembler with conflict candidate handling"
```

---

### Task 8: Serving schema + LogRepository

> **Codex review P2 fix:** 统一 serving 表名。M1 保留日志功能但 API 暂不调用（避免伪完成），标注为可选。

**Files:**
- Create: `knowledge_assets/schemas/init_serving.sql`
- Create: `agent_serving/serving/repositories/log_repo.py`
- Create: `agent_serving/tests/test_log_repo.py`

Same as v1.0 plan with table name fix (use `serving_retrieval_logs` consistently).

---

### Task 9: API endpoints with DB injection + dev startup

> **Codex review P1 fix:** Dev mode 启动时检查 active publish version，不存在时 health 降级。Smoke test 必须覆盖查询级闭环。

**Files:**
- Create: `agent_serving/serving/api/command_usage.py`
- Create: `agent_serving/serving/api/search.py`
- Modify: `agent_serving/serving/main.py`

**Key changes from v1.0:**
- `main.py` lifespan: 初始化 SQLite 后用 `schema_adapter` 建表，检查 active PV
- `/health` 返回 db_status: "ok" | "no_data" 反映数据库状态
- API routes inject repo + assembler via app state

---

### Task 10: API integration tests (including conflict candidate)

**Files:**
- Create: `agent_serving/tests/test_command_usage_api.py`
- Create: `agent_serving/tests/test_search_api.py`

**New tests:**
- conflict candidate query → uncertainty with "冲突" in reason
- health check reflects DB state

---

### Task 11: Smoke test — full query pipeline

> **Codex review P1 fix:** Smoke test must cover actual query path, not just `/health`.

**Step 1:** Run full test suite: `pytest agent_serving/tests/ -v`
**Step 2:** Start dev server, verify `/health` returns db_status
**Step 3:** Post a real `/api/v1/search` request with seed data loaded

---

### Task 12: Update design doc and write handoff

> **Codex review P2 fix:** Sync design doc file list — remove Planner and context_assemble from M1 scope (标注 M2+)。

**Files:**
- Modify: `docs/plans/2026-04-15-m1-agent-serving-design.md`
- Create: `docs/handoffs/2026-04-16-m1-agent-serving-claude-serving-handoff.md`
- Modify: `COLLAB_TASKS.md`
- Modify: `AGENT_MESSAGES.md`
- Modify: `docs/messages/TASK-20260415-m1-agent-serving.md`
