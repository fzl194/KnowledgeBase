# M1 Knowledge Mining v0.5 Schema Revision Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 M1 Knowledge Mining Pipeline 从 v0.4 schema 对齐到 v0.5 schema，包括输入模型简化、字段重组、Plugin 架构引入、发布生命周期补齐。

**Architecture:** 保留 6 模块 pipeline 骨架（ingestion → profile → parsers → segmentation → canonicalization → publishing），引入 Plugin 模式处理内容理解能力（entity extraction, role classification, segment enrichment），按文件类型分发解析器（MD/TXT/Passthrough），补齐 staging→active 原子发布。

**Tech Stack:** Python, markdown-it-py, SQLite (shared DDL)

---

## Phase 1: 基础层

### Task 1: models.py — 数据模型对齐 v0.5

**Files:**
- Modify: `knowledge_mining/mining/models.py`

**Changes:**
- RawDocumentData: 删除 product/product_version/network_element/conversion_profile_json，新增 file_type/file_name/relative_path/source_uri/processing_profile_json
- RawSegmentData: 删除 segment_type/command_name/heading_level，section_role→semantic_role，新增 entity_refs_json
- CanonicalSegmentData: 删除 segment_type/command_name，section_role→semantic_role，新增 summary/quality_score/entity_refs_json/scope_json
- SourceMappingData: relation_type 改为 primary/exact_duplicate/normalized_duplicate/near_duplicate/scope_variant/conflict_candidate
- 新增 BatchParams dataclass（default_document_type/default_source_type/batch_scope/tags 等）

**Verification:** `python -c "from knowledge_mining.mining.models import *; print('models OK')"`

### Task 2: extractors.py — Plugin 接口定义

**Files:**
- Create: `knowledge_mining/mining/extractors.py`

**Changes:**
- 定义 Protocol: EntityExtractor, RoleClassifier, SegmentEnricher
- 默认实现: NoOpEntityExtractor, DefaultRoleClassifier, NoOpSegmentEnricher

**Verification:** `python -c "from knowledge_mining.mining.extractors import *; print('extractors OK')"`

### Task 3: text_utils.py — 确认兼容

**Files:**
- Read: `knowledge_mining/mining/text_utils.py`

**Changes:** 无预期改动，确认 API 兼容新模型。如果 token_count 函数可复用则保留。

**Verification:** 确认 content_hash, normalize_text, simhash_fingerprint, hamming_distance, jaccard_similarity, token_count 全部可用。

---

## Phase 2: 解析层

### Task 4: ingestion/ — 纯文件夹递归扫描

**Files:**
- Rewrite: `knowledge_mining/mining/ingestion/__init__.py`

**Changes:**
- 删除 manifest.jsonl 和 frontmatter 逻辑
- 递归扫描目录，识别 md/txt/html/htm/pdf/doc/docx
- 每个文件生成 RawDocumentData（file_type 按扩展名映射，content_hash 来自文件内容）
- document_key = 规范化 relative_path
- 所有文件都登记，不跳过任何识别到的文件
- 输出 summary: discovered_documents, parsed_documents, unparsed_documents, skipped_files, failed_files

**Verification:** 单元测试覆盖 md/txt/html/pdf/docx 混合目录，manifest.jsonl 存在时被忽略。

### Task 5: parsers/ — MD + TXT + Passthrough

**Files:**
- Create: `knowledge_mining/mining/parsers/__init__.py`
- Create: `knowledge_mining/mining/parsers/markdown_parser.py`
- Create: `knowledge_mining/mining/parsers/plaintext_parser.py`
- Create: `knowledge_mining/mining/parsers/passthrough_parser.py`

**Changes:**
- DocumentParser Protocol: parse(content, file_name, context) → list[RawSegmentData]
- MarkdownParser: 从现有 structure/ 迁移，基于 markdown-it-py
- PlainTextParser: Token-based chunking (GraphRAG 方式)，chunk_size=300, chunk_overlap=30，block_type=paragraph
- PassthroughParser: 返回空列表（HTML/PDF/DOCX）
- ParserFactory: 根据 file_type 选择 parser

**Verification:** 单元测试覆盖 MD 标题/表格/代码、TXT 切分粒度、Passthrough 空返回。

### Task 6: document_profile/ — 批次参数继承

**Files:**
- Rewrite: `knowledge_mining/mining/document_profile/__init__.py`

**Changes:**
- 删除内容推断逻辑（MML 命令检测等）
- scope_json / tags_json / document_type / source_type 全部从 BatchParams 继承
- title: MD 从 H1 提取，其他从文件名
- structure_quality: 按扩展名映射（md→markdown_native, txt→plain_text_only, html→full_html, pdf/doc/docx→unknown）

**Verification:** 单元测试覆盖批次参数继承、title 提取、structure_quality 映射。

### Task 7: segmentation/ — 字段对齐 + Plugin 注入

**Files:**
- Modify: `knowledge_mining/mining/segmentation/__init__.py`

**Changes:**
- 输出字段对齐 v0.5（semantic_role, entity_refs_json, structure_json, source_offsets_json）
- 注入 RoleClassifier 和 EntityExtractor
- 删除 segment_type/command_name/heading_level 逻辑
- section_path 改为 JSON array（含 title + level）

**Verification:** 单元测试覆盖 block_type 映射、semantic_role 默认 unknown、entity_refs 默认 []。

---

## Phase 3: 归并 + 发布

### Task 8: canonicalization.py — 字段对齐 + primary source

**Files:**
- Modify: `knowledge_mining/mining/canonicalization.py`

**Changes:**
- 字段对齐 v0.5（block_type, semantic_role, summary=NULL, quality_score=NULL, entity_refs_json, scope_json）
- 确保 singleton 也生成 canonical
- 每个 canonical 有且仅有 1 个 primary source
- relation_type: primary/exact_duplicate/normalized_duplicate/near_duplicate/scope_variant/conflict_candidate
- 注入 SegmentEnricher

**Verification:** 单元测试覆盖 singleton canonical、primary source 唯一性、三层去重。

### Task 9: publishing/ — 完整生命周期

**Files:**
- Rewrite: `knowledge_mining/mining/publishing/__init__.py`

**Changes:**
- version_code: pv-YYYYMMDD-HHmmss, batch_code: batch-YYYYMMDD-HHmmss
- 流程: staging → 写入全部 L0/L1/L2 → 校验 → 事务原子激活
- 校验: 至少 1 raw_document、至少 1 canonical、每个 canonical 有 1 primary source
- 旧 active → archived，新 staging → active（同一事务）
- 失败时新 version → failed，旧 active 不动
- metadata_json 记录统计 summary

**Verification:** 单元测试覆盖连续两次发布（active 唯一）、失败隔离。

### Task 10: db.py — INSERT 对齐

**Files:**
- Modify: `knowledge_mining/mining/db.py`

**Changes:**
- INSERT 语句字段对齐 v0.5（raw_documents 新字段、raw_segments 新字段、canonical_segments 新字段、canonical_segment_sources 新 relation_type）
- 仍读共享 DDL

**Verification:** 单元测试覆盖新字段写入和读取。

### Task 11: jobs/run.py — Pipeline 编排 + CLI

**Files:**
- Rewrite: `knowledge_mining/mining/jobs/run.py`

**Changes:**
- CLI 参数: --input, --db, --scope (JSON), --default-document-type, --default-source-type, --chunk-size, --chunk-overlap
- Plugin 注入: entity_extractor, role_classifier, segment_enricher
- Pipeline 编排: scan → profile → parse → segment → canonicalize → publish
- Summary 输出: discovered_documents, parsed_documents, unparsed_documents, skipped_files, failed_files, raw_segments, canonical_segments, source_mappings, active_version_id

**Verification:** 端到端测试覆盖临时测试目录。

---

## Phase 4: 测试

### Task 12: 测试重写

**Files:**
- Rewrite all: `knowledge_mining/tests/test_*.py`

**Changes:**
- 全部按 v0.5 schema 重写
- 临时测试数据（tempfile），用完删除
- 覆盖: 文件夹递归扫描、文件类型分发、batch 参数继承、token chunking、canonical 归并、发布生命周期
- 等另一个人提供正式测试数据后补充契约测试

**Verification:** `python -m pytest knowledge_mining/tests/ -v` 全部通过。

### Task 13: 文档更新 + 提交

**Files:**
- Update: `docs/plans/2026-04-16-m1-knowledge-mining-design.md`
- Update: `docs/plans/2026-04-16-m1-knowledge-mining-impl-plan.md`
- Create: `docs/handoffs/2026-04-17-m1-knowledge-mining-claude-v05-revision.md`
- Update: `docs/messages/TASK-20260415-m1-knowledge-mining.md`
- Update: `AGENT_MESSAGES.md`
- Update: `COLLAB_TASKS.md`

**Verification:** 提交并推送。
