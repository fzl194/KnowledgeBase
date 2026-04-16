# M1 Knowledge Mining Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现离线知识挖掘最小闭环：Markdown → L0 raw_segments → L1 canonical_segments → L2 canonical_segment_sources，写入 SQLite staging publish version。

**Architecture:** 6 模块 pipeline（ingestion → document_profile → structure → segmentation → canonicalization → publishing），内部用 dataclass 传递数据，SQLite dev 模式，三层 hash 去重。

**Tech Stack:** Python 3.11+, markdown-it-py, SQLite, pytest

---

### Task 1: 添加依赖

**Files:**
- Modify: `pyproject.toml`

**Step 1: 添加 markdown-it-py 依赖**

```toml
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "markdown-it-py>=3.0",
]
```

**Step 2: 安装依赖**

Run: `pip install -e ".[dev]"`

**Step 3: 验证安装**

Run: `python -c "import markdown_it; print(markdown_it.__version__)"`
Expected: 版本号输出，无报错

**Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "[claude-mining]: add markdown-it-py dependency for M1 mining"
```

---

### Task 2: 数据对象定义

**Files:**
- Create: `knowledge_mining/mining/models.py`
- Test: `knowledge_mining/tests/test_models.py`

**Step 1: 写测试**

```python
# knowledge_mining/tests/test_models.py
"""Verify data models can be instantiated and fields are correct."""
from knowledge_mining.mining.models import (
    RawDocumentData,
    DocumentProfile,
    SectionNode,
    ContentBlock,
    RawSegmentData,
    CanonicalSegmentData,
    SourceMappingData,
)


def test_raw_document_data():
    doc = RawDocumentData(
        file_path="UDG/OM参考.md",
        content="# ADD APN\n",
        frontmatter={"product": "UDG"},
    )
    assert doc.file_path == "UDG/OM参考.md"
    assert doc.frontmatter["product"] == "UDG"


def test_document_profile():
    profile = DocumentProfile(
        file_path="UDG/OM参考.md",
        product="UDG",
        product_version="V100R023C10",
        network_element=None,
        document_type="command_manual",
    )
    assert profile.product == "UDG"
    assert profile.document_type == "command_manual"


def test_section_node():
    block = ContentBlock(block_type="paragraph", text="hello")
    node = SectionNode(
        path=["OM参考", "ADD APN"],
        level=2,
        title="ADD APN",
        blocks=[block],
        children=[],
    )
    assert node.path == ["OM参考", "ADD APN"]
    assert len(node.blocks) == 1


def test_raw_segment_data():
    seg = RawSegmentData(
        document_file_path="UDG/OM参考.md",
        segment_index=0,
        section_path=["OM参考", "ADD APN"],
        section_title="ADD APN",
        heading_level=2,
        segment_type="paragraph",
        raw_text="some text",
        normalized_text="some text",
        content_hash="abc123",
        normalized_hash="abc123",
        token_count=2,
        command_name=None,
    )
    assert seg.segment_type == "paragraph"
    assert seg.token_count == 2


def test_canonical_segment_data():
    cs = CanonicalSegmentData(
        canonical_key="C001",
        segment_type="paragraph",
        title="ADD APN",
        canonical_text="merged text",
        search_text="ADD APN merged text",
        has_variants=False,
        variant_policy="none",
        command_name=None,
        raw_segment_refs=["seg1", "seg2"],
    )
    assert cs.has_variants is False


def test_source_mapping_data():
    sm = SourceMappingData(
        canonical_key="C001",
        raw_segment_document_path="UDG/OM参考.md",
        raw_segment_index=0,
        relation_type="primary",
        is_primary=True,
        priority=100,
        similarity_score=None,
        diff_summary=None,
    )
    assert sm.relation_type == "primary"
```

**Step 2: 运行测试确认失败**

Run: `cd D:/mywork/KnowledgeBase/CoreMasterKB && python -m pytest knowledge_mining/tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: 写实现**

```python
# knowledge_mining/mining/models.py
"""Data objects for the knowledge mining pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RawDocumentData:
    """Output of ingestion: raw Markdown file content."""
    file_path: str
    content: str
    frontmatter: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentProfile:
    """Output of document_profile: identified product/version/NE."""
    file_path: str
    product: str | None = None
    product_version: str | None = None
    network_element: str | None = None
    document_type: str | None = None


@dataclass(frozen=True)
class ContentBlock:
    """A content block within a section (paragraph, table, code, etc.)."""
    block_type: str  # paragraph, table, fence, bullet_list, ordered_list, blockquote
    text: str
    language: str | None = None  # for fence blocks


@dataclass(frozen=True)
class SectionNode:
    """A section in the document structure tree."""
    path: list[str]
    level: int
    title: str
    blocks: list[ContentBlock]
    children: list[SectionNode] = field(default_factory=list)


@dataclass(frozen=True)
class RawSegmentData:
    """Output of segmentation: one L0 raw segment."""
    document_file_path: str
    segment_index: int
    section_path: list[str]
    section_title: str | None
    heading_level: int | None
    segment_type: str  # command, parameter, example, note, table, paragraph, concept, other
    raw_text: str
    normalized_text: str
    content_hash: str
    normalized_hash: str
    token_count: int | None
    command_name: str | None = None


@dataclass(frozen=True)
class CanonicalSegmentData:
    """Output of canonicalization: one L1 canonical segment."""
    canonical_key: str
    segment_type: str
    title: str | None
    canonical_text: str
    search_text: str
    has_variants: bool
    variant_policy: str  # none, prefer_latest, require_version, require_product_version, require_ne
    command_name: str | None
    raw_segment_refs: list[str]  # list of "document_path::segment_index" identifiers


@dataclass(frozen=True)
class SourceMappingData:
    """Output of canonicalization: one L2 source mapping."""
    canonical_key: str
    raw_segment_document_path: str
    raw_segment_index: int
    relation_type: str  # primary, exact_duplicate, near_duplicate, version_variant, product_variant, ne_variant, conflict_candidate
    is_primary: bool
    priority: int
    similarity_score: float | None
    diff_summary: str | None
```

**Step 4: 运行测试确认通过**

Run: `cd D:/mywork/KnowledgeBase/CoreMasterKB && python -m pytest knowledge_mining/tests/test_models.py -v`
Expected: 6 passed

**Step 5: Commit**

```bash
git add knowledge_mining/mining/models.py knowledge_mining/tests/test_models.py
git commit -m "[claude-mining]: add pipeline data models"
```

---

### Task 3: SQLite Schema Adapter

**Files:**
- Create: `knowledge_mining/mining/db.py`
- Test: `knowledge_mining/tests/test_db.py`

**Step 1: 写测试**

```python
# knowledge_mining/tests/test_db.py
"""Verify SQLite schema creation and basic CRUD."""
import sqlite3
import tempfile
from pathlib import Path

from knowledge_mining.mining.db import MiningDB


def test_create_tables():
    with tempfile.TemporaryDirectory() as tmp:
        db = MiningDB(Path(tmp) / "test.sqlite")
        db.create_tables()
        conn = db.connect()
        # Verify all 6 tables exist
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor]
        assert "source_batches" in tables
        assert "publish_versions" in tables
        assert "raw_documents" in tables
        assert "raw_segments" in tables
        assert "canonical_segments" in tables
        assert "canonical_segment_sources" in tables
        conn.close()


def test_insert_and_query_publish_version():
    with tempfile.TemporaryDirectory() as tmp:
        db = MiningDB(Path(tmp) / "test.sqlite")
        db.create_tables()
        conn = db.connect()
        pv_id = db.create_publish_version(conn, version_code="v1", status="staging")
        cursor = conn.execute(
            "SELECT version_code, status FROM publish_versions WHERE id = ?",
            (pv_id,),
        )
        row = cursor.fetchone()
        assert row == ("v1", "staging")
        conn.close()
```

**Step 2: 运行测试确认失败**

Run: `cd D:/mywork/KnowledgeBase/CoreMasterKB && python -m pytest knowledge_mining/tests/test_db.py -v`
Expected: FAIL

**Step 3: 写实现**

```python
# knowledge_mining/mining/db.py
"""SQLite schema adapter for the mining pipeline (dev mode)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
import sqlite3


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS source_batches (
    id              TEXT PRIMARY KEY,
    batch_code      TEXT NOT NULL UNIQUE,
    source_type     TEXT NOT NULL,
    description     TEXT,
    created_by      TEXT,
    created_at      TEXT NOT NULL,
    metadata_json   TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS publish_versions (
    id                      TEXT PRIMARY KEY,
    version_code            TEXT NOT NULL UNIQUE,
    status                  TEXT NOT NULL,
    base_publish_version_id TEXT,
    source_batch_id         TEXT,
    description             TEXT,
    build_started_at        TEXT NOT NULL,
    build_finished_at       TEXT,
    activated_at            TEXT,
    build_error             TEXT,
    metadata_json           TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS raw_documents (
    id                      TEXT PRIMARY KEY,
    publish_version_id      TEXT NOT NULL,
    document_key            TEXT NOT NULL,
    source_uri              TEXT NOT NULL,
    file_name               TEXT NOT NULL,
    file_type               TEXT NOT NULL,
    title                   TEXT,
    product                 TEXT,
    product_version         TEXT,
    network_element         TEXT,
    document_type           TEXT,
    content_hash            TEXT NOT NULL,
    copied_from_document_id TEXT,
    origin_batch_id         TEXT,
    created_at              TEXT NOT NULL,
    metadata_json           TEXT NOT NULL DEFAULT '{}',
    UNIQUE(publish_version_id, document_key)
);

CREATE TABLE IF NOT EXISTS raw_segments (
    id                     TEXT PRIMARY KEY,
    publish_version_id     TEXT NOT NULL,
    raw_document_id        TEXT NOT NULL,
    segment_key            TEXT NOT NULL,
    segment_index          INTEGER NOT NULL,
    section_path           TEXT NOT NULL DEFAULT '[]',
    section_title          TEXT,
    heading_level          INTEGER,
    segment_type           TEXT NOT NULL,
    command_name           TEXT,
    raw_text               TEXT NOT NULL,
    normalized_text        TEXT NOT NULL,
    content_hash           TEXT NOT NULL,
    normalized_hash        TEXT NOT NULL,
    token_count            INTEGER,
    copied_from_segment_id TEXT,
    metadata_json          TEXT NOT NULL DEFAULT '{}',
    UNIQUE(publish_version_id, raw_document_id, segment_key)
);

CREATE TABLE IF NOT EXISTS canonical_segments (
    id                 TEXT PRIMARY KEY,
    publish_version_id TEXT NOT NULL,
    canonical_key      TEXT NOT NULL,
    segment_type       TEXT NOT NULL,
    title              TEXT,
    command_name       TEXT,
    canonical_text     TEXT NOT NULL,
    summary            TEXT,
    search_text        TEXT NOT NULL,
    has_variants       INTEGER NOT NULL DEFAULT 0,
    variant_policy     TEXT NOT NULL DEFAULT 'none',
    quality_score      REAL,
    created_at         TEXT NOT NULL,
    metadata_json      TEXT NOT NULL DEFAULT '{}',
    UNIQUE(publish_version_id, canonical_key)
);

CREATE TABLE IF NOT EXISTS canonical_segment_sources (
    id                   TEXT PRIMARY KEY,
    publish_version_id   TEXT NOT NULL,
    canonical_segment_id TEXT NOT NULL,
    raw_segment_id       TEXT NOT NULL,
    relation_type        TEXT NOT NULL,
    is_primary           INTEGER NOT NULL DEFAULT 0,
    priority             INTEGER NOT NULL DEFAULT 100,
    similarity_score     REAL,
    diff_summary         TEXT,
    metadata_json        TEXT NOT NULL DEFAULT '{}',
    UNIQUE(canonical_segment_id, raw_segment_id)
);

CREATE INDEX IF NOT EXISTS idx_raw_segments_publish_document
    ON raw_segments(publish_version_id, raw_document_id);

CREATE INDEX IF NOT EXISTS idx_raw_segments_normalized_hash
    ON raw_segments(publish_version_id, normalized_hash);

CREATE INDEX IF NOT EXISTS idx_canonical_segments_search_text
    ON canonical_segments(publish_version_id, segment_type);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


class MiningDB:
    """SQLite adapter for the mining pipeline."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def create_tables(self) -> None:
        conn = self.connect()
        conn.executescript(_SCHEMA_SQL)
        conn.close()

    def create_publish_version(
        self,
        conn: sqlite3.Connection,
        version_code: str,
        status: str = "staging",
        description: str | None = None,
    ) -> str:
        pv_id = _new_id()
        conn.execute(
            """INSERT INTO publish_versions
               (id, version_code, status, build_started_at, description)
               VALUES (?, ?, ?, ?, ?)""",
            (pv_id, version_code, status, _now_iso(), description),
        )
        conn.commit()
        return pv_id
```

**Step 4: 运行测试确认通过**

Run: `cd D:/mywork/KnowledgeBase/CoreMasterKB && python -m pytest knowledge_mining/tests/test_db.py -v`
Expected: 2 passed

**Step 5: Commit**

```bash
git add knowledge_mining/mining/db.py knowledge_mining/tests/test_db.py
git commit -m "[claude-mining]: add SQLite schema adapter for dev mode"
```

---

### Task 4: Text Utilities (hash, normalize, simhash, token_count)

**Files:**
- Create: `knowledge_mining/mining/text_utils.py`
- Test: `knowledge_mining/tests/test_text_utils.py`

**Step 1: 写测试**

```python
# knowledge_mining/tests/test_text_utils.py
"""Verify text utility functions."""
from knowledge_mining.mining.text_utils import (
    content_hash,
    normalize_text,
    normalized_hash,
    simhash_fingerprint,
    hamming_distance,
    jaccard_similarity,
    token_count,
)


def test_content_hash_deterministic():
    h1 = content_hash("hello world")
    h2 = content_hash("hello world")
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_content_hash_different():
    h1 = content_hash("hello")
    h2 = content_hash("world")
    assert h1 != h2


def test_normalize_text():
    result = normalize_text("  Hello   World  ")
    assert result == "hello world"


def test_normalize_text_cjk():
    result = normalize_text("５Ｇ　网络")
    assert "5g" in result
    assert "网络" in result


def test_normalized_hash():
    h = normalized_hash("  Hello   World  ")
    assert len(h) == 64


def test_simhash_similar():
    fp1 = simhash_fingerprint("ADD APN命令用于配置APN")
    fp2 = simhash_fingerprint("ADD APN命令用于配置APN。")
    dist = hamming_distance(fp1, fp2)
    assert dist <= 3


def test_simhash_different():
    fp1 = simhash_fingerprint("ADD APN命令用于配置APN")
    fp2 = simhash_fingerprint("网络切片是一种5G核心技术")
    dist = hamming_distance(fp1, fp2)
    assert dist > 10


def test_jaccard():
    s = jaccard_similarity("hello world foo", "hello world bar")
    assert 0.3 < s < 0.7


def test_jaccard_identical():
    assert jaccard_similarity("a b c", "a b c") == 1.0


def test_token_count_ascii():
    assert token_count("hello world") == 2


def test_token_count_cjk():
    assert token_count("５Ｇ网络配置") == 5  # 5G=2, 网络=2, 配置=2 → 6 tokens CJK chars
```

**Step 2: 运行测试确认失败**

Run: `cd D:/mywork/KnowledgeBase/CoreMasterKB && python -m pytest knowledge_mining/tests/test_text_utils.py -v`
Expected: FAIL

**Step 3: 写实现**

```python
# knowledge_mining/mining/text_utils.py
"""Text hashing, normalization, and similarity utilities."""
from __future__ import annotations

import hashlib
import re
import unicodedata


def content_hash(text: str) -> str:
    """SHA-256 hex digest of raw text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_text(text: str) -> str:
    """Normalize text for dedup: CJK fullwidth→halfwidth, lowercase, collapse whitespace."""
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    # Fullwidth ASCII → halfwidth
    text = unicodedata.normalize("NFKC", text)
    # Remove punctuation variations
    text = re.sub(r"[^\w\s\u4e00-\u9fff]", "", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalized_hash(text: str) -> str:
    """SHA-256 hex digest of normalized text."""
    return content_hash(normalize_text(text))


def _tokenize(text: str) -> list[str]:
    """Split text into tokens for similarity computation. CJK-aware."""
    tokens: list[str] = []
    buf = ""
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            if buf:
                tokens.append(buf.lower())
                buf = ""
            tokens.append(ch)
        elif ch.isalnum():
            buf += ch
        else:
            if buf:
                tokens.append(buf.lower())
                buf = ""
    if buf:
        tokens.append(buf.lower())
    return tokens


def token_count(text: str) -> int:
    """Count tokens (CJK-aware). CJK chars count individually."""
    return len(_tokenize(text))


def simhash_fingerprint(text: str, bits: int = 64) -> int:
    """Compute SimHash fingerprint for near-duplicate detection."""
    tokens = _tokenize(text)
    if not tokens:
        return 0
    v = [0] * bits
    for token in tokens:
        h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
        for i in range(bits):
            if h & (1 << i):
                v[i] += 1
            else:
                v[i] -= 1
    fingerprint = 0
    for i in range(bits):
        if v[i] > 0:
            fingerprint |= (1 << i)
    return fingerprint


def hamming_distance(fp1: int, fp2: int, bits: int = 64) -> int:
    """Count differing bits between two fingerprints."""
    x = fp1 ^ fp2
    count = 0
    while x and count < bits:
        count += x & 1
        x >>= 1
    return count


def jaccard_similarity(text1: str, text2: str) -> float:
    """Jaccard similarity of token sets."""
    s1 = set(_tokenize(text1))
    s2 = set(_tokenize(text2))
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    return len(s1 & s2) / len(s1 | s2)
```

**Step 4: 运行测试确认通过**

Run: `cd D:/mywork/KnowledgeBase/CoreMasterKB && python -m pytest knowledge_mining/tests/test_text_utils.py -v`
Expected: 全部 passed

**Step 5: Commit**

```bash
git add knowledge_mining/mining/text_utils.py knowledge_mining/tests/test_text_utils.py
git commit -m "[claude-mining]: add text hashing, normalization, and simhash utilities"
```

---

### Task 5: Ingestion Module

**Files:**
- Modify: `knowledge_mining/mining/ingestion/__init__.py`
- Test: `knowledge_mining/tests/test_ingestion.py`

**Step 1: 写测试**

```python
# knowledge_mining/tests/test_ingestion.py
"""Verify Markdown ingestion."""
import tempfile
from pathlib import Path

from knowledge_mining.mining.ingestion import ingest_directory


def test_ingest_single_file():
    with tempfile.TemporaryDirectory() as tmp:
        md_file = Path(tmp) / "test.md"
        md_file.write_text("# Title\nHello world\n", encoding="utf-8")
        docs = ingest_directory(Path(tmp))
        assert len(docs) == 1
        assert docs[0].file_path == str(md_file)
        assert "# Title" in docs[0].content


def test_ingest_skips_non_markdown():
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "readme.txt").write_text("not md", encoding="utf-8")
        (Path(tmp) / "doc.md").write_text("# Doc\n", encoding="utf-8")
        docs = ingest_directory(Path(tmp))
        assert len(docs) == 1


def test_ingest_frontmatter():
    with tempfile.TemporaryDirectory() as tmp:
        md_file = Path(tmp) / "doc.md"
        md_file.write_text(
            "---\nproduct: UDG\nversion: V100R023C10\n---\n# Title\n",
            encoding="utf-8",
        )
        docs = ingest_directory(Path(tmp))
        assert docs[0].frontmatter["product"] == "UDG"
        assert docs[0].frontmatter["version"] == "V100R023C10"
        assert "# Title" in docs[0].content


def test_ingest_empty_directory():
    with tempfile.TemporaryDirectory() as tmp:
        docs = ingest_directory(Path(tmp))
        assert docs == []


def test_ingest_recursive():
    with tempfile.TemporaryDirectory() as tmp:
        sub = Path(tmp) / "sub"
        sub.mkdir()
        (sub / "a.md").write_text("# A\n", encoding="utf-8")
        (Path(tmp) / "b.md").write_text("# B\n", encoding="utf-8")
        docs = ingest_directory(Path(tmp))
        assert len(docs) == 2
```

**Step 2: 运行测试确认失败**

**Step 3: 写实现** 到 `knowledge_mining/mining/ingestion/__init__.py`，实现 `ingest_directory(path) -> list[RawDocumentData]`，包含 YAML frontmatter 解析（用 `---` 分隔符）。

**Step 4: 运行测试确认通过**

**Step 5: Commit**

```bash
git add knowledge_mining/mining/ingestion/__init__.py knowledge_mining/tests/test_ingestion.py
git commit -m "[claude-mining]: add Markdown ingestion with frontmatter parsing"
```

---

### Task 6: Document Profile Module

**Files:**
- Modify: `knowledge_mining/mining/document_profile/__init__.py`
- Test: `knowledge_mining/tests/test_document_profile.py`

**Step 1: 写测试**

覆盖：
1. frontmatter 显式声明优先
2. 路径推断（`UDG/V100R023C10/OM参考.md`）
3. 内容模式匹配（包含 MML 命令 → command_manual）
4. 无法判断 → other
5. NE 识别（文件名包含 AMF/SMF/UPF 等）

**Step 2-5: 同上 TDD 流程**

实现要点：
- `profile_document(doc: RawDocumentData) -> DocumentProfile`
- 从 frontmatter 提取 product/version/NE
- 从路径中用正则提取 product（目录名）、version（V\d+R\d+C\d+）
- 从内容中检测 MML 命令模式（ADD/MOD/DEL/SET/DSP/LST/SHOW）→ command_manual

---

### Task 7: Structure Parser (Markdown AST)

**Files:**
- Modify: `knowledge_mining/mining/structure/__init__.py`
- Test: `knowledge_mining/tests/test_structure.py`

**Step 1: 写测试**

覆盖：
1. 简单标题 + 段落 → SectionNode with path
2. 嵌套标题（h1 > h2 > h3）→ 正确的树结构
3. 表格 → ContentBlock(block_type="table")
4. 代码块 → ContentBlock(block_type="fence", language="mml")
5. 列表 → ContentBlock(block_type="bullet_list")
6. 无标题的纯段落 → root level section

测试用合成 Markdown string。

**Step 2-5: 同上 TDD 流程**

实现要点：
- `parse_structure(content: str) -> list[SectionNode]`
- 用 `markdown_it.MarkdownIt().parse(content)` 获取 token 流
- 遍历 tokens 构建 SectionNode 树
- heading tokens 创建新 section level
- table/fence/paragraph/bullet_list/ordered_list tokens 收集为 ContentBlock

---

### Task 8: Segmentation Module

**Files:**
- Modify: `knowledge_mining/mining/segmentation/__init__.py`
- Test: `knowledge_mining/tests/test_segmentation.py`

**Step 1: 写测试**

覆盖：
1. 单个 section → 单个 segment
2. 表格独立 segment（segment_type="table"）
3. 代码块独立 segment（segment_type="example"）
4. 包含 MML 命令名（如 ADD APN）→ command_name 设置
5. content_hash / normalized_hash 正确计算
6. token_count 正确计算
7. section_path 正确传递

**Step 2-5: 同上 TDD 流程**

实现要点：
- `segment_sections(sections: list[SectionNode], profile: DocumentProfile) -> list[RawSegmentData]`
- 遍历 SectionNode 树，每个 section 按规则切分
- 表格和代码块独立成 segment
- 其余内容合并为一个 segment
- 使用 text_utils 计算 hash/normalize/token_count
- 用正则检测 command_name：`r'\b(ADD|MOD|DEL|SET|DSP|LST|SHOW)\s+\w+'`

---

### Task 9: Canonicalization Module

**Files:**
- Create: `knowledge_mining/mining/canonicalization.py`
- Test: `knowledge_mining/tests/test_canonicalization.py`

**Step 1: 写测试**

覆盖：
1. 单个 segment → 创建 canonical（relation=primary）
2. 完全重复（content_hash 相同）→ exact_duplicate，合并
3. 归一重复（normalized_hash 相同）→ near_duplicate，合并
4. 近似重复（simhash ≤ 3 且 Jaccard ≥ 0.85）→ near_duplicate
5. 不同 product 同内容 → product_variant，has_variants=true
6. 不同 version 同内容 → version_variant，has_variants=true
7. 无重复的 segment 各自独立成 canonical

**Step 2-5: 同上 TDD 流程**

实现要点：
- `canonicalize(segments: list[RawSegmentData], profiles: dict[str, DocumentProfile]) -> tuple[list[CanonicalSegmentData], list[SourceMappingData]]`
- 建立 `content_hash → [segment]` 索引
- 建立 `normalized_hash → [segment]` 索引
- 建立近重复候选（simhash bucket 或全量比较，M1 数据量小可用全量）
- 归并逻辑：
  1. 先按 content_hash 分组 → exact_duplicate
  2. 未匹配的按 normalized_hash 分组 → near_duplicate
  3. 未匹配的按 simhash + Jaccard 判断 → near_duplicate
  4. 每组生成一个 CanonicalSegment
  5. 组内按 profile 判断 variant 类型

---

### Task 10: Publishing Module

**Files:**
- Modify: `knowledge_mining/mining/publishing/__init__.py`
- Test: `knowledge_mining/tests/test_publishing.py`

**Step 1: 写测试**

覆盖：
1. 创建 source_batch 和 staging publish_version
2. 写入 raw_documents（带 profile 信息）
3. 写入 raw_segments
4. 写入 canonical_segments（has_variants 用 0/1 表示）
5. 写入 canonical_segment_sources
6. 查询验证数据完整

**Step 2-5: 同上 TDD 流程**

实现要点：
- `publish(profiles, segments, canonicals, sources, db_path)` 函数
- 使用 MiningDB 连接
- 将 pipeline 内存对象映射为 SQL INSERT
- section_path 序列化为 JSON 字符串
- has_variants 用 INTEGER 0/1

---

### Task 11: Pipeline 入口

**Files:**
- Create: `knowledge_mining/mining/jobs/run.py`
- Test: `knowledge_mining/tests/test_pipeline.py`

**Step 1: 写集成测试**

用合成 Markdown 样例（包含标题层级、表格、代码块、重复段落），验证端到端 pipeline：
1. 输入 → L0 raw_segments 非空
2. L0 中有正确的 segment_type（table, example, paragraph）
3. L1 canonical_segments 去重后数量 < L0
4. L2 source_mappings 正确关联 L1 → L0
5. SQLite 中可查询到完整数据

**Step 2-5: 同上 TDD 流程**

实现 `knowledge_mining/mining/jobs/run.py`：
- `run_pipeline(input_path, db_path)` 编排所有模块
- 支持 `python -m knowledge_mining.mining.jobs.run --input <path>` CLI 入口

---

### Task 12: 合成测试样例 + 最终验证

**Files:**
- Create: `knowledge_assets/samples/test_corpus/UDG/V100R023C10/OM参考.md`
- Create: `knowledge_assets/samples/test_corpus/UNC/V100R019C10/OM参考.md`
- Create: `knowledge_assets/samples/test_corpus/UDG/V100R023C10/基础知识.md`

**Step 1: 创建测试样例**

OM参考.md: 包含 ADD APN 命令定义、参数表格、代码示例、注意事项
基础知识.md: 包含 5G 概念介绍（与 UNC 版本有重复内容）
UNC OM参考.md: 包含类似命令（可产生 product_variant）

**Step 2: 运行端到端测试**

Run: `python -m knowledge_mining.mining.jobs.run --input knowledge_assets/samples/test_corpus/ --db .dev/test.sqlite`

验证:
- L0 segments 数量合理
- 5G 概念在不同文档中产生归并（L1 < L0）
- variant 检测正确

**Step 3: 运行全量测试**

Run: `cd D:/mywork/KnowledgeBase/CoreMasterKB && python -m pytest knowledge_mining/tests/ -v`
Expected: 全部 passed

**Step 4: Commit**

```bash
git add knowledge_assets/samples/test_corpus/ knowledge_mining/
git commit -m "[claude-mining]: complete M1 mining pipeline with test corpus"
```

---

## 验证清单

- [ ] `python -m pytest knowledge_mining/tests/ -v` 全部通过
- [ ] 合成 Markdown 样例能跑通完整 pipeline
- [ ] L0 每个 segment 有 section_path, raw_text, content_hash
- [ ] L1 去重正确，重复概念只生成一个 canonical segment
- [ ] L2 能表达 exact_duplicate / version_variant / product_variant
- [ ] SQLite staging publish version 可查询
- [ ] 不依赖 `agent_serving` 代码
