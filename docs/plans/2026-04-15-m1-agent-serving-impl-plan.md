# M1 Agent Serving Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the online query pipeline: Agent/Skill request -> query constraint recognition -> search L1 canonical_segments -> drill down via L2 to L0 raw_segments -> return context pack.

**Architecture:** Three-layer FastAPI service — API routes call Application layer (Normalizer → Planner → Assembler), which delegates data access to Repository layer. SQLite dev mode with in-memory test fixtures. Pure SQL retrieval (FTS/LIKE), no vector search in M1.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, aiosqlite, pytest + pytest-asyncio + httpx

**Design doc:** `docs/plans/2026-04-15-m1-agent-serving-design.md`
**Schema contract:** `knowledge_assets/schemas/001_asset_core.sql`
**Commit prefix:** `[claude-serving]:`

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

### Task 2: Pydantic request/response models

**Files:**
- Create: `agent_serving/serving/schemas/models.py`

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
    SourceRef,
    Uncertainty,
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


class ContextAssembleRequest(BaseModel):
    canonical_segment_ids: list[str] = Field(default_factory=list)
    raw_segment_ids: list[str] = Field(default_factory=list)


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

**Step 4: Run test to verify it passes**

Run: `pytest agent_serving/tests/test_models.py -v`
Expected: 4 passed

**Step 5: Commit**

```bash
git add agent_serving/serving/schemas/models.py agent_serving/tests/test_models.py
git commit -m "[claude-serving]: add Pydantic request/response models"
```

---

### Task 3: SQLite test fixtures with seed data

**Files:**
- Create: `agent_serving/tests/conftest.py`

**Step 1: Write fixture**

Create `agent_serving/tests/conftest.py`:

```python
"""Shared test fixtures: in-memory SQLite with asset schema and seed data."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio

# Fixed UUIDs for deterministic tests
ACTIVE_PV_ID = "11111111-1111-1111-1111-111111111111"
DOC_UDG_ID = "22222222-2222-2222-2222-222222222222"
DOC_UNC_ID = "33333333-3333-3333-3333-333333333333"
RAW_SEG_ADD_APN_UDG = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
RAW_SEG_ADD_APN_UNC = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RAW_SEG_5G_CONCEPT = "cccccccc-cccc-cccc-cccc-cccccccccccc"
CANON_ADD_APN = "dddddddd-dddd-dddd-dddd-dddddddddddd"
CANON_5G = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
SOURCE_ADD_APN_UDG = "ffffffff-ffff-ffff-ffff-ffffffffffff"
SOURCE_ADD_APN_UNC = "00000000-0000-0000-0000-000000000001"

# Expose IDs for tests
SEED_IDS = {
    "active_pv_id": ACTIVE_PV_ID,
    "doc_udg_id": DOC_UDG_ID,
    "doc_unc_id": DOC_UNC_ID,
    "raw_seg_add_apn_udg": RAW_SEG_ADD_APN_UDG,
    "raw_seg_add_apn_unc": RAW_SEG_ADD_APN_UNC,
    "raw_seg_5g_concept": RAW_SEG_5G_CONCEPT,
    "canon_add_apn": CANON_ADD_APN,
    "canon_5g": CANON_5G,
    "source_add_apn_udg": SOURCE_ADD_APN_UDG,
    "source_add_apn_unc": SOURCE_ADD_APN_UNC,
}


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS asset_publish_versions (
    id TEXT PRIMARY KEY,
    version_code TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    base_publish_version_id TEXT,
    source_batch_id TEXT,
    description TEXT,
    build_started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    build_finished_at TEXT,
    activated_at TEXT,
    build_error TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS asset_raw_documents (
    id TEXT PRIMARY KEY,
    publish_version_id TEXT NOT NULL,
    document_key TEXT NOT NULL,
    source_uri TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_type TEXT NOT NULL,
    title TEXT,
    product TEXT,
    product_version TEXT,
    network_element TEXT,
    document_type TEXT,
    content_hash TEXT NOT NULL,
    copied_from_document_id TEXT,
    origin_batch_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (publish_version_id, document_key)
);

CREATE TABLE IF NOT EXISTS asset_raw_segments (
    id TEXT PRIMARY KEY,
    publish_version_id TEXT NOT NULL,
    raw_document_id TEXT NOT NULL,
    segment_key TEXT NOT NULL,
    segment_index INTEGER NOT NULL,
    section_path TEXT NOT NULL DEFAULT '[]',
    section_title TEXT,
    heading_level INTEGER,
    segment_type TEXT NOT NULL,
    command_name TEXT,
    raw_text TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    normalized_hash TEXT NOT NULL,
    token_count INTEGER,
    copied_from_segment_id TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (publish_version_id, raw_document_id, segment_key)
);

CREATE TABLE IF NOT EXISTS asset_canonical_segments (
    id TEXT PRIMARY KEY,
    publish_version_id TEXT NOT NULL,
    canonical_key TEXT NOT NULL,
    segment_type TEXT NOT NULL,
    title TEXT,
    command_name TEXT,
    canonical_text TEXT NOT NULL,
    summary TEXT,
    search_text TEXT NOT NULL,
    has_variants INTEGER NOT NULL DEFAULT 0,
    variant_policy TEXT NOT NULL DEFAULT 'none',
    quality_score REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (publish_version_id, canonical_key)
);

CREATE TABLE IF NOT EXISTS asset_canonical_segment_sources (
    id TEXT PRIMARY KEY,
    publish_version_id TEXT NOT NULL,
    canonical_segment_id TEXT NOT NULL,
    raw_segment_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    is_primary INTEGER NOT NULL DEFAULT 0,
    priority INTEGER NOT NULL DEFAULT 100,
    similarity_score REAL,
    diff_summary TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (canonical_segment_id, raw_segment_id)
);
"""

SEED_SQL = f"""
INSERT INTO asset_publish_versions (id, version_code, status, description)
VALUES ('{ACTIVE_PV_ID}', 'PV-2026-04-15-v1', 'active', 'M1 test seed');

INSERT INTO asset_raw_documents (id, publish_version_id, document_key, source_uri, file_name, file_type, product, product_version, network_element, document_type, content_hash)
VALUES
  ('{DOC_UDG_ID}', '{ACTIVE_PV_ID}', 'UDG_OM_REF', 'file:///docs/udg_om.md', 'udg_om.md', 'markdown', 'UDG', 'V100R023C10', 'UDM', 'command_manual', 'hash_udg_om'),
  ('{DOC_UNC_ID}', '{ACTIVE_PV_ID}', 'UNC_OM_REF', 'file:///docs/unc_om.md', 'unc_om.md', 'markdown', 'UNC', 'V100R023C20', 'AMF', 'command_manual', 'hash_unc_om');

INSERT INTO asset_raw_segments (id, publish_version_id, raw_document_id, segment_key, segment_index, section_path, section_title, segment_type, command_name, raw_text, normalized_text, content_hash, normalized_hash)
VALUES
  ('{RAW_SEG_ADD_APN_UDG}', '{ACTIVE_PV_ID}', '{DOC_UDG_ID}', 'UDG_ADD_APN', 0, '["OM参考","MML命令","ADD APN"]', 'ADD APN', 'command', 'ADD APN 命令用于在UDG上新增APN配置。语法：ADD APN=<apn-name>,[参数列表]', 'add apn 命令用于在udg上新增apn配置', 'hash_udg_add_apn', 'nhash_udg_add_apn'),
  ('{RAW_SEG_ADD_APN_UNC}', '{ACTIVE_PV_ID}', '{DOC_UNC_ID}', 'UNC_ADD_APN', 0, '["OM参考","MML命令","ADD APN"]', 'ADD APN', 'command', 'ADD APN 命令用于在UNC上新增APN配置。语法与UDG版本有差异：ADD APN=<name>,TYPE=<type>,[参数列表]', 'add apn 命令用于在unc上新增apn配置', 'hash_unc_add_apn', 'nhash_unc_add_apn'),
  ('{RAW_SEG_5G_CONCEPT}', '{ACTIVE_PV_ID}', '{DOC_UDG_ID}', 'UDG_5G_INTRO', 1, '["基础知识","5G概述"]', '5G概述', 'concept', NULL, '5G是第五代移动通信技术，支持增强移动宽带、海量机器通信和超高可靠低时延通信三大场景。', '5g是第五代移动通信技术', 'hash_5g', 'nhash_5g');

INSERT INTO asset_canonical_segments (id, publish_version_id, canonical_key, segment_type, title, command_name, canonical_text, summary, search_text, has_variants, variant_policy)
VALUES
  ('{CANON_ADD_APN}', '{ACTIVE_PV_ID}', 'CANON_ADD_APN', 'command', 'ADD APN 命令', 'ADD APN', 'ADD APN 命令用于新增APN配置。不同产品的参数列表有差异。', 'ADD APN 归并命令参考', 'ADD APN 命令 新增 APN 配置 参数', 1, 'require_product_version'),
  ('{CANON_5G}', '{ACTIVE_PV_ID}', 'CANON_5G_CONCEPT', 'concept', '5G概述', NULL, '5G是第五代移动通信技术，支持增强移动宽带、海量机器通信和超高可靠低时延通信三大场景。', '5G概念归并', '5G 第五代 移动通信 eMBB mMTC URLLC', 0, 'none');

INSERT INTO asset_canonical_segment_sources (id, publish_version_id, canonical_segment_id, raw_segment_id, relation_type, is_primary, priority, similarity_score, diff_summary, metadata_json)
VALUES
  ('{SOURCE_ADD_APN_UDG}', '{ACTIVE_PV_ID}', '{CANON_ADD_APN}', '{RAW_SEG_ADD_APN_UDG}', 'version_variant', 1, 100, 0.95, 'UDG版本参数列表与UNC不同', '{{\"product\": \"UDG\", \"product_version\": \"V100R023C10\", \"network_element\": \"UDM\"}}'),
  ('{SOURCE_ADD_APN_UNC}', '{ACTIVE_PV_ID}', '{CANON_ADD_APN}', '{RAW_SEG_ADD_APN_UNC}', 'version_variant', 0, 100, 0.92, 'UNC版本语法与UDG有差异', '{{\"product\": \"UNC\", \"product_version\": \"V100R023C20\", \"network_element\": \"AMF\"}}'),
  ('{ACTIVE_PV_ID}', '{ACTIVE_PV_ID}', '{CANON_5G}', '{RAW_SEG_5G_CONCEPT}', 'primary', 1, 100, 1.0, NULL, '{{}}');
"""


@pytest_asyncio.fixture
async def db_connection():
    """In-memory SQLite with schema and seed data."""
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    await db.executescript(SCHEMA_SQL)
    await db.executescript(SEED_SQL)
    await db.commit()
    yield db
    await db.close()


@pytest.fixture
def seed_ids():
    return SEED_IDS
```

**Step 2: Run to verify fixture loads**

Run: `python -c "import asyncio; from agent_serving.tests.conftest import SCHEMA_SQL, SEED_SQL; db = asyncio.run(aiosqlite.connect(':memory:')); asyncio.run(db.executescript(SCHEMA_SQL)); asyncio.run(db.executescript(SEED_SQL)); print('OK')"`
Expected: OK

**Step 3: Commit**

```bash
git add agent_serving/tests/conftest.py
git commit -m "[claude-serving]: add SQLite test fixtures with seed data"
```

---

### Task 4: AssetRepository (TDD)

**Files:**
- Create: `agent_serving/serving/repositories/asset_repo.py`
- Create: `agent_serving/tests/test_asset_repo.py`

**Step 1: Write tests**

Create `agent_serving/tests/test_asset_repo.py`:

```python
"""Tests for AssetRepository — read-only data access."""
import pytest
import pytest_asyncio
from agent_serving.serving.repositories.asset_repo import AssetRepository
from agent_serving.tests.conftest import SEED_IDS, ACTIVE_PV_ID


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
    assert len(raw_segs) == 2


@pytest.mark.asyncio
async def test_get_raw_segments_by_ids(repo):
    segs = await repo.get_raw_segments_by_ids([SEED_IDS["raw_seg_5g_concept"]])
    assert len(segs) == 1
    assert "5G" in segs[0]["raw_text"]


@pytest.mark.asyncio
async def test_get_document_for_segment(repo, db_connection):
    doc = await repo.get_document_for_segment(SEED_IDS["raw_seg_add_apn_udg"])
    assert doc["product"] == "UDG"
```

**Step 2: Run tests to verify they fail**

Run: `pytest agent_serving/tests/test_asset_repo.py -v`
Expected: FAIL — module not found

**Step 3: Write implementation**

Create `agent_serving/serving/repositories/asset_repo.py`:

```python
"""Read-only repository for asset tables (L0/L1/L2)."""
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
        pv_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if pv_id is None:
            pv_id = await self.get_active_publish_version_id()
        if pv_id is None:
            return []

        query = (
            "SELECT rs.*, rd.product, rd.product_version, rd.network_element, "
            "  csources.relation_type, csources.diff_summary, csources.metadata_json "
            "FROM asset_canonical_segment_sources csources "
            "JOIN asset_raw_segments rs ON csources.raw_segment_id = rs.id "
            "JOIN asset_raw_documents rd ON rs.raw_document_id = rd.id "
            "WHERE csources.canonical_segment_id = ? "
            "AND csources.publish_version_id = ?"
        )
        params: list[Any] = [canonical_segment_id, pv_id]

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
Expected: 8 passed

**Step 5: Commit**

```bash
git add agent_serving/serving/repositories/asset_repo.py agent_serving/tests/test_asset_repo.py
git commit -m "[claude-serving]: add AssetRepository with read-only L1/L2/L0 access"
```

---

### Task 5: QueryNormalizer (TDD)

**Files:**
- Create: `agent_serving/serving/application/normalizer.py`
- Create: `agent_serving/tests/test_normalizer.py`

**Step 1: Write tests**

Create `agent_serving/tests/test_normalizer.py`:

```python
"""Tests for QueryNormalizer — constraint extraction from natural language."""
import pytest
from agent_serving.serving.application.normalizer import QueryNormalizer


@pytest.fixture
def normalizer():
    return QueryNormalizer()


def test_extract_command_with_product_and_version(normalizer):
    result = normalizer.normalize("UDG V100R023C10 ADD APN 怎么写")
    assert result.command == "ADD APN"
    assert result.product == "UDG"
    assert result.product_version == "V100R023C10"
    assert "product" not in result.missing_constraints


def test_extract_command_only(normalizer):
    result = normalizer.normalize("ADD APN 怎么写")
    assert result.command == "ADD APN"
    assert "product" in result.missing_constraints
    assert "product_version" in result.missing_constraints


def test_extract_with_chinese_operation_word(normalizer):
    result = normalizer.normalize("新增APN怎么配置")
    assert result.command == "ADD APN"


def test_extract_with_network_element(normalizer):
    result = normalizer.normalize("SMF上ADD APN怎么写")
    assert result.command == "ADD APN"
    assert result.network_element == "SMF"


def test_general_query_no_command(normalizer):
    result = normalizer.normalize("5G是什么")
    assert result.command is None
    assert "5G" in result.keywords


def test_mod_command(normalizer):
    result = normalizer.normalize("修改APN的参数")
    assert result.command == "MOD APN"


def test_del_command(normalizer):
    result = normalizer.normalize("删除APN配置")
    assert result.command == "DEL APN"


def test_show_command(normalizer):
    result = normalizer.normalize("查询APN配置")
    assert result.command in ("SHOW APN", "LST APN", "DSP APN")


def test_version_extraction(normalizer):
    result = normalizer.normalize("UPF V200R001C00 SET PROFILE 怎么配")
    assert result.product == "UPF"
    assert result.product_version == "V200R001C00"
    assert result.command == "SET PROFILE"
```

**Step 2: Run tests to verify they fail**

Run: `pytest agent_serving/tests/test_normalizer.py -v`
Expected: FAIL — module not found

**Step 3: Write implementation**

Create `agent_serving/serving/application/normalizer.py`:

```python
"""Query Normalizer — extract constraints from natural language queries."""
from __future__ import annotations

import re

from agent_serving.serving.schemas.models import NormalizedQuery

# Operation word mapping (Chinese → command prefix)
OP_MAP = {
    "新增": "ADD",
    "添加": "ADD",
    "创建": "ADD",
    "修改": "MOD",
    "更改": "MOD",
    "编辑": "MOD",
    "删除": "DEL",
    "移除": "DEL",
    "查询": "SHOW",
    "查看": "DSP",
    "显示": "LST",
    "设置": "SET",
    "配置": "SET",
}

COMMAND_RE = re.compile(
    r"\b(ADD|MOD|DEL|SET|SHOW|LST|DSP)\s+([A-Z][A-Z0-9_]*)\b", re.IGNORECASE
)

PRODUCT_RE = re.compile(
    r"\b(UDG|UNC|UPF|AMF|SMF|PCF|UDM|NRF|AUSF|BSF|NSSF)\b", re.IGNORECASE
)

VERSION_RE = re.compile(r"\b(V\d{3}R\d{3}C\d{2})\b")

NE_RE = re.compile(
    r"\b(AMF|SMF|UPF|UDM|PCF|NRF|AUSF|BSF|NSSF|SCP|UDSF|UDR)\b", re.IGNORECASE
)

# Products that are also NEs — prefer product when both match
PRODUCT_NAMES = {"UDG", "UNC", "UPF", "AMF", "SMF", "PCF", "UDM"}


class QueryNormalizer:
    def normalize(self, query: str) -> NormalizedQuery:
        command = self._extract_command(query)
        product = self._extract_product(query)
        product_version = self._extract_version(query)
        network_element = self._extract_ne(query, product)
        keywords = self._extract_keywords(query)
        missing = self._find_missing(command, product, product_version, network_element)

        return NormalizedQuery(
            command=command,
            product=product,
            product_version=product_version,
            network_element=network_element,
            keywords=keywords,
            missing_constraints=missing,
        )

    def _extract_command(self, query: str) -> str | None:
        # Try direct command pattern first
        match = COMMAND_RE.search(query)
        if match:
            return f"{match.group(1).upper()} {match.group(2).upper()}"

        # Try Chinese operation word + target
        for cn_word, cmd_prefix in OP_MAP.items():
            if cn_word in query:
                # Look for a target word after the operation word
                after = query.split(cn_word, 1)[-1]
                target_match = re.match(r"\s*([A-Za-z][A-Za-z0-9_]*)", after)
                if target_match:
                    target = target_match.group(1).upper()
                    return f"{cmd_prefix} {target}"
                # Operation word alone
                return cmd_prefix

        return None

    def _extract_product(self, query: str) -> str | None:
        match = PRODUCT_RE.search(query)
        return match.group(1).upper() if match else None

    def _extract_version(self, query: str) -> str | None:
        match = VERSION_RE.search(query)
        return match.group(1) if match else None

    def _extract_ne(self, query: str, product: str | None) -> str | None:
        # Avoid double-counting product as NE
        for match in NE_RE.finditer(query):
            ne = match.group(1).upper()
            if ne != product:
                return ne
        return None

    def _extract_keywords(self, query: str) -> list[str]:
        # Strip known patterns, return remaining meaningful tokens
        cleaned = query
        for pattern in [COMMAND_RE, PRODUCT_RE, VERSION_RE, NE_RE]:
            cleaned = pattern.sub("", cleaned)
        tokens = [t for t in re.split(r"[\s,，、？?。.！!]+", cleaned) if len(t) > 0]
        return tokens

    def _find_missing(
        self,
        command: str | None,
        product: str | None,
        product_version: str | None,
        network_element: str | None,
    ) -> list[str]:
        missing: list[str] = []
        if command and not product:
            missing.append("product")
        if product and not product_version:
            missing.append("product_version")
        return missing
```

**Step 4: Run tests**

Run: `pytest agent_serving/tests/test_normalizer.py -v`
Expected: 9 passed

**Step 5: Commit**

```bash
git add agent_serving/serving/application/normalizer.py agent_serving/tests/test_normalizer.py
git commit -m "[claude-serving]: add QueryNormalizer with Chinese/English rule engine"
```

---

### Task 6: ContextAssembler (TDD)

**Files:**
- Create: `agent_serving/serving/application/assembler.py`
- Create: `agent_serving/tests/test_assembler.py`

**Step 1: Write tests**

Create `agent_serving/tests/test_assembler.py`:

```python
"""Tests for ContextAssembler — context pack assembly logic."""
import pytest
from agent_serving.serving.application.assembler import ContextAssembler
from agent_serving.serving.schemas.models import NormalizedQuery, ContextPack


def _make_canon(**overrides):
    base = {
        "id": "c1",
        "segment_type": "command",
        "title": "ADD APN",
        "canonical_text": "ADD APN 归并文本",
        "command_name": "ADD APN",
        "has_variants": 1,
        "variant_policy": "require_product_version",
    }
    base.update(overrides)
    return base


def _make_raw(**overrides):
    base = {
        "id": "r1",
        "segment_type": "command",
        "raw_text": "ADD APN 原始文本",
        "command_name": "ADD APN",
        "section_path": '["OM参考","ADD APN"]',
        "section_title": "ADD APN",
        "product": "UDG",
        "product_version": "V100R023C10",
        "network_element": "UDM",
    }
    base.update(overrides)
    return base


def test_assemble_no_variants():
    assembler = ContextAssembler()
    canon = _make_canon(has_variants=0, variant_policy="none")
    pack = assembler.assemble(
        query="5G是什么",
        intent="general",
        normalized=NormalizedQuery(keywords=["5G"]),
        canonical_hits=[canon],
        drill_results=[],
    )
    assert pack.intent == "general"
    assert len(pack.answer_materials.canonical_segments) == 1
    assert len(pack.uncertainties) == 0


def test_assemble_with_variants_and_constraints_met():
    assembler = ContextAssembler()
    canon = _make_canon()
    raw = _make_raw()
    pack = assembler.assemble(
        query="UDG V100R023C10 ADD APN",
        intent="command_usage",
        normalized=NormalizedQuery(command="ADD APN", product="UDG", product_version="V100R023C10"),
        canonical_hits=[canon],
        drill_results=[raw],
    )
    assert len(pack.answer_materials.raw_segments) == 1
    assert pack.answer_materials.raw_segments[0].raw_text == "ADD APN 原始文本"
    assert len(pack.uncertainties) == 0


def test_assemble_variants_but_missing_constraints():
    assembler = ContextAssembler()
    canon = _make_canon()
    pack = assembler.assemble(
        query="ADD APN 怎么写",
        intent="command_usage",
        normalized=NormalizedQuery(command="ADD APN", missing_constraints=["product", "product_version"]),
        canonical_hits=[canon],
        drill_results=[],
    )
    assert len(pack.uncertainties) > 0
    assert any(u.field == "product" for u in pack.uncertainties)
    assert len(pack.suggested_followups) > 0
```

**Step 2: Run tests to verify they fail**

Run: `pytest agent_serving/tests/test_assembler.py -v`
Expected: FAIL — module not found

**Step 3: Write implementation**

Create `agent_serving/serving/application/assembler.py`:

```python
"""ContextAssembler — build context pack from search results."""
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

    def _build_followups(self, uncertainties: list[Uncertainty]) -> list[str]:
        if not uncertainties:
            return []
        fields = [u.field for u in uncertainties]
        return [f"请确认{'/'.join(fields)}以获取精确答案"]

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
Expected: 3 passed

**Step 5: Commit**

```bash
git add agent_serving/serving/application/assembler.py agent_serving/tests/test_assembler.py
git commit -m "[claude-serving]: add ContextAssembler with uncertainty builder"
```

---

### Task 7: Serving schema (init_serving.sql)

**Files:**
- Create: `knowledge_assets/schemas/init_serving.sql`

**Step 1: Create serving schema**

Create `knowledge_assets/schemas/init_serving.sql`:

```sql
-- CoreMasterKB M1 Serving Schema
--
-- Purpose:
--   Runtime tables for Agent Serving: retrieval logs and feedback.
--   Serving reads asset.* tables (defined in 001_asset_core.sql).
--   Serving writes only to serving.* tables.

CREATE SCHEMA IF NOT EXISTS serving;

CREATE TABLE IF NOT EXISTS serving.retrieval_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query           TEXT NOT NULL,
    intent          TEXT,
    normalized_query TEXT,
    key_objects     JSONB NOT NULL DEFAULT '{}'::jsonb,
    hit_count       INTEGER NOT NULL DEFAULT 0,
    drill_down_used BOOLEAN NOT NULL DEFAULT FALSE,
    has_uncertainty BOOLEAN NOT NULL DEFAULT FALSE,
    latency_ms      INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata_json   JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_retrieval_logs_created
    ON serving.retrieval_logs(created_at);

CREATE INDEX IF NOT EXISTS idx_retrieval_logs_intent
    ON serving.retrieval_logs(intent);
```

**Step 2: Commit**

```bash
git add knowledge_assets/schemas/init_serving.sql
git commit -m "[claude-serving]: add serving schema for retrieval_logs"
```

---

### Task 8: LogRepository

**Files:**
- Create: `agent_serving/serving/repositories/log_repo.py`
- Create: `agent_serving/tests/test_log_repo.py`

**Step 1: Write test**

Create `agent_serving/tests/test_log_repo.py`:

```python
"""Tests for LogRepository — retrieval log writing."""
import pytest
import pytest_asyncio
import aiosqlite
from agent_serving.serving.repositories.log_repo import LogRepository


SCHEMA = """
CREATE TABLE IF NOT EXISTS serving_retrieval_logs (
    id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    intent TEXT,
    normalized_query TEXT,
    key_objects TEXT NOT NULL DEFAULT '{}',
    hit_count INTEGER NOT NULL DEFAULT 0,
    drill_down_used INTEGER NOT NULL DEFAULT 0,
    has_uncertainty INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
"""


@pytest_asyncio.fixture
async def log_db():
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    await db.executescript(SCHEMA)
    await db.commit()
    yield db
    await db.close()


@pytest_asyncio.fixture
async def log_repo(log_db):
    return LogRepository(log_db)


@pytest.mark.asyncio
async def test_write_retrieval_log(log_repo, log_db):
    await log_repo.log(
        query="ADD APN 怎么写",
        intent="command_usage",
        normalized_query="ADD APN",
        hit_count=1,
        drill_down_used=True,
        has_uncertainty=True,
        latency_ms=50,
    )
    cursor = await log_db.execute("SELECT * FROM serving_retrieval_logs")
    rows = await cursor.fetchall()
    assert len(rows) == 1
    assert rows[0]["query"] == "ADD APN 怎么写"
    assert rows[0]["intent"] == "command_usage"
```

**Step 2: Run test to verify it fails**

Run: `pytest agent_serving/tests/test_log_repo.py -v`
Expected: FAIL — module not found

**Step 3: Write implementation**

Create `agent_serving/serving/repositories/log_repo.py`:

```python
"""LogRepository — write retrieval logs."""
from __future__ import annotations

import json
import uuid

import aiosqlite


class LogRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def log(
        self,
        *,
        query: str,
        intent: str | None = None,
        normalized_query: str | None = None,
        key_objects: dict | None = None,
        hit_count: int = 0,
        drill_down_used: bool = False,
        has_uncertainty: bool = False,
        latency_ms: int | None = None,
    ) -> str:
        log_id = str(uuid.uuid4())
        await self._db.execute(
            "INSERT INTO serving_retrieval_logs "
            "(id, query, intent, normalized_query, key_objects, "
            "hit_count, drill_down_used, has_uncertainty, latency_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                log_id,
                query,
                intent,
                normalized_query,
                json.dumps(key_objects or {}),
                hit_count,
                int(drill_down_used),
                int(has_uncertainty),
                latency_ms,
            ),
        )
        await self._db.commit()
        return log_id
```

**Step 4: Run test**

Run: `pytest agent_serving/tests/test_log_repo.py -v`
Expected: 1 passed

**Step 5: Commit**

```bash
git add agent_serving/serving/repositories/log_repo.py agent_serving/tests/test_log_repo.py
git commit -m "[claude-serving]: add LogRepository for retrieval logs"
```

---

### Task 9: API endpoints (command/usage + search)

**Files:**
- Create: `agent_serving/serving/api/command_usage.py`
- Create: `agent_serving/serving/api/search.py`
- Modify: `agent_serving/serving/main.py`

**Step 1: Create command_usage route**

Create `agent_serving/serving/api/command_usage.py`:

```python
"""POST /api/v1/command/usage — command usage query."""
from __future__ import annotations

from fastapi import APIRouter

from agent_serving.serving.application.assembler import ContextAssembler
from agent_serving.serving.application.normalizer import QueryNormalizer
from agent_serving.serving.schemas.models import CommandUsageRequest, ContextPack

router = APIRouter(prefix="/api/v1", tags=["command"])

_normalizer = QueryNormalizer()
_assembler = ContextAssembler()


@router.post("/command/usage", response_model=ContextPack)
async def command_usage(req: CommandUsageRequest) -> ContextPack:
    normalized = _normalizer.normalize(req.query)
    # Repository injection happens at app level via dependency;
    # for M1, direct import is sufficient.
    from agent_serving.serving.main import get_asset_repo

    repo = get_asset_repo()

    canonical_hits = await repo.search_canonical(command_name=normalized.command)

    drill_results: list[dict] = []
    if canonical_hits:
        hit = canonical_hits[0]
        if hit["has_variants"] and not normalized.missing_constraints:
            drill_results = await repo.drill_down(
                canonical_segment_id=hit["id"],
                product=normalized.product,
                product_version=normalized.product_version,
                network_element=normalized.network_element,
            )

    return _assembler.assemble(
        query=req.query,
        intent="command_usage",
        normalized=normalized,
        canonical_hits=canonical_hits,
        drill_results=drill_results,
    )
```

**Step 2: Create search route**

Create `agent_serving/serving/api/search.py`:

```python
"""POST /api/v1/search — general knowledge search."""
from __future__ import annotations

from fastapi import APIRouter

from agent_serving.serving.application.assembler import ContextAssembler
from agent_serving.serving.application.normalizer import QueryNormalizer
from agent_serving.serving.schemas.models import ContextPack, SearchRequest

router = APIRouter(prefix="/api/v1", tags=["search"])

_normalizer = QueryNormalizer()
_assembler = ContextAssembler()


@router.post("/search", response_model=ContextPack)
async def search(req: SearchRequest) -> ContextPack:
    normalized = _normalizer.normalize(req.query)
    from agent_serving.serving.main import get_asset_repo

    repo = get_asset_repo()

    # If command detected, search by command name
    if normalized.command:
        hits = await repo.search_canonical(command_name=normalized.command)
    else:
        # Keyword search using remaining tokens
        keywords = normalized.keywords
        hits = []
        for kw in keywords[:3]:
            results = await repo.search_canonical(keyword=kw)
            hits.extend(results)
        # Deduplicate by id
        seen = set()
        unique_hits = []
        for h in hits:
            if h["id"] not in seen:
                seen.add(h["id"])
                unique_hits.append(h)
        hits = unique_hits

    drill_results: list[dict] = []
    for hit in hits:
        if hit["has_variants"] and not normalized.missing_constraints:
            drilled = await repo.drill_down(
                canonical_segment_id=hit["id"],
                product=normalized.product,
                product_version=normalized.product_version,
                network_element=normalized.network_element,
            )
            drill_results.extend(drilled)

    intent = "command_usage" if normalized.command else "general_search"

    return _assembler.assemble(
        query=req.query,
        intent=intent,
        normalized=normalized,
        canonical_hits=hits,
        drill_results=drill_results,
    )
```

**Step 3: Update main.py with routes and DB setup**

Replace `agent_serving/serving/main.py`:

```python
"""Cloud Core Knowledge Backend — FastAPI application."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

import aiosqlite
from fastapi import FastAPI

from agent_serving.serving.api.command_usage import router as command_router
from agent_serving.serving.api.health import router as health_router
from agent_serving.serving.api.search import router as search_router
from agent_serving.serving.repositories.asset_repo import AssetRepository

_asset_repo: AssetRepository | None = None

SCHEMA_SQL_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "knowledge_assets", "schemas", "001_asset_core.sql",
)


def get_asset_repo() -> AssetRepository:
    if _asset_repo is None:
        raise RuntimeError("Database not initialized. Start the app first.")
    return _asset_repo


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _asset_repo
    env = os.getenv("APP_ENV", "dev")
    if env == "dev":
        db_path = os.getenv("SQLITE_PATH", ".dev/agent_kb.sqlite")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        db = await aiosqlite.connect(db_path)
        db.row_factory = aiosqlite.Row
        _asset_repo = AssetRepository(db)
    yield
    if _asset_repo is not None:
        await _asset_repo._db.close()


app = FastAPI(
    title="Cloud Core Knowledge Backend",
    version="0.2.0",
    description="Agent Knowledge Backend for cloud core network.",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(command_router)
app.include_router(search_router)
```

**Step 4: Commit**

```bash
git add agent_serving/serving/api/command_usage.py agent_serving/serving/api/search.py agent_serving/serving/main.py
git commit -m "[claude-serving]: add /command/usage and /search API endpoints"
```

---

### Task 10: API integration tests

**Files:**
- Create: `agent_serving/tests/test_command_usage_api.py`
- Create: `agent_serving/tests/test_search_api.py`

**Step 1: Write command_usage API test**

Create `agent_serving/tests/test_command_usage_api.py`:

```python
"""Integration test: POST /api/v1/command/usage."""
import pytest
from httpx import ASGITransport, AsyncClient

from agent_serving.serving.main import app
from agent_serving.serving.repositories.asset_repo import AssetRepository
from agent_serving.tests.conftest import SCHEMA_SQL, SEED_SQL


@pytest.mark.asyncio
async def test_command_usage_with_full_constraints(db_connection):
    # Inject repo into app
    import agent_serving.serving.main as main_mod
    main_mod._asset_repo = AssetRepository(db_connection)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/command/usage",
            json={"query": "UDG V100R023C10 ADD APN 怎么写"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["intent"] == "command_usage"
    assert body["key_objects"]["command"] == "ADD APN"
    assert body["key_objects"]["product"] == "UDG"
    assert len(body["answer_materials"]["raw_segments"]) >= 1


@pytest.mark.asyncio
async def test_command_usage_with_missing_constraints(db_connection):
    import agent_serving.serving.main as main_mod
    main_mod._asset_repo = AssetRepository(db_connection)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/command/usage",
            json={"query": "ADD APN 怎么写"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["uncertainties"]) > 0
```

**Step 2: Write search API test**

Create `agent_serving/tests/test_search_api.py`:

```python
"""Integration test: POST /api/v1/search."""
import pytest
from httpx import ASGITransport, AsyncClient

from agent_serving.serving.main import app
from agent_serving.serving.repositories.asset_repo import AssetRepository


@pytest.mark.asyncio
async def test_search_general_query(db_connection):
    import agent_serving.serving.main as main_mod
    main_mod._asset_repo = AssetRepository(db_connection)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/search",
            json={"query": "5G是什么"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["intent"] == "general_search"
    assert len(body["answer_materials"]["canonical_segments"]) >= 1


@pytest.mark.asyncio
async def test_search_no_results(db_connection):
    import agent_serving.serving.main as main_mod
    main_mod._asset_repo = AssetRepository(db_connection)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/search",
            json={"query": "完全不存在的关键词XYZ999"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["answer_materials"]["canonical_segments"]) == 0
```

**Step 3: Run all tests**

Run: `pytest agent_serving/tests/ -v --tb=short`
Expected: all tests pass (test_health + test_models + test_normalizer + test_asset_repo + test_assembler + test_log_repo + test_command_usage_api + test_search_api)

**Step 4: Commit**

```bash
git add agent_serving/tests/test_command_usage_api.py agent_serving/tests/test_search_api.py
git commit -m "[claude-serving]: add API integration tests for command/usage and search"
```

---

### Task 11: Smoke test — full pipeline

**Step 1: Verify health endpoint still works**

Run: `pytest agent_serving/tests/test_health.py -v`
Expected: 1 passed

**Step 2: Run full test suite**

Run: `pytest agent_serving/tests/ -v`
Expected: all pass

**Step 3: Verify serving starts**

Run: `python -m agent_serving.scripts.run_serving --port 8001 &` then `curl http://127.0.0.1:8001/health`
Expected: `{"status":"ok","version":"0.2.0"}`

---

### Task 12: Write handoff and update tracking

**Files:**
- Create: `docs/handoffs/2026-04-15-m1-agent-serving-claude-serving-handoff.md`
- Modify: `COLLAB_TASKS.md`
- Modify: `AGENT_MESSAGES.md`
- Modify: `docs/messages/TASK-20260415-m1-agent-serving.md`

**Step 1: Write handoff document**

Document all changes, files modified, design decisions, verification results, and items for Codex to review.

**Step 2: Update COLLAB_TASKS.md**

Set `交接文档` field.

**Step 3: Post message and update AGENT_MESSAGES**

**Step 4: Commit**

```bash
git add docs/handoffs/2026-04-15-m1-agent-serving-claude-serving-handoff.md COLLAB_TASKS.md AGENT_MESSAGES.md docs/messages/TASK-20260415-m1-agent-serving.md
git commit -m "[claude-serving]: M1 Agent Serving handoff and tracking update"
```
