# Knowledge Mining v1.1

`knowledge_mining` 是 CoreMasterKB 的离线知识挖掘模块。它把一个普通文件夹中的原始资料扫描、解析、切片、增强、构建关系和检索单元，并通过 shared snapshot -> build -> release 发布到 `asset_core.sqlite`，供 `agent_serving` 只读检索。

## 两阶段 Pipeline

### Phase 1: Document Mining（文档级，每文档独立执行）

```
ingest → parse → segment → enrich → build_relations → build_retrieval_units → select_snapshot
```

### Phase 2: Build & Publish（全局操作）

```
assemble_build → validate_build → publish_release
```

## 整体架构

```text
input folder
  → ingestion (递归扫描，产出 RawFileData)
  → parsers (MarkdownParser / PlainTextParser / PassthroughParser)
  → structure (Markdown → SectionNode 树)
  → segmentation (SectionNode → RawSegmentData，heading 独立成段)
  → enrich (规则增强：entity_refs、heading_role、table metadata)
  → relations (结构关系：previous/next、same_section、section_header_of)
  → retrieval_units (raw_text + contextual_text + entity_card)
  → snapshot (共享快照：document + snapshot + link 三层模型)
  → publishing (build 合并 + release 激活)
  → asset_core.sqlite + mining_runtime.sqlite
```

## 数据库边界

| 数据库 | 职责 | Mining 写入 |
|--------|------|-------------|
| `asset_core.sqlite` | 内容资产（documents, snapshots, segments, relations, retrieval_units, builds, releases） | 是 |
| `mining_runtime.sqlite` | 过程状态（runs, run_documents, stage_events） | 是 |
| `agent_llm_runtime.sqlite` | LLM 调用审计 | 否（LLM Runtime 独立管理） |

## Shared Snapshot 模型

v1.1 的核心内容复用机制：

- `asset_documents`：逻辑文档身份（document_key 唯一）
- `asset_document_snapshots`：共享内容快照（normalized_content_hash 唯一）
- `asset_document_snapshot_links`：文档到快照的映射

不同文档如果内容归一化后相同，可以共享同一个 snapshot，减少存储和重复处理。

归一化策略（保守）：
1. CRLF → LF
2. 每行去除尾部空白
3. 去除空行
4. SHA256

## 如何运行

```python
from knowledge_mining.mining.jobs.run import run, publish
from knowledge_mining.mining.models import BatchParams

# 完整 pipeline（Phase 1 + Phase 2）
result = run(
    "/path/to/input/folder",
    asset_core_db_path="asset_core.sqlite",
    mining_runtime_db_path="mining_runtime.sqlite",
    batch_params=BatchParams(
        default_source_type="folder_scan",
        default_document_type="command",
        batch_scope={"products": ["CloudCore"]},
        tags=["coldstart"],
    ),
)

# 仅 Phase 1（不构建 build/release）
result = run("/path/to/input", phase1_only=True)

# 对已完成的 run 发布 release
publish(result["run_id"])
```

## 模块说明

| 模块 | 职责 |
|------|------|
| `models.py` | 12 frozen dataclass + 11 frozenset 常量，对齐 v1.1 SQL schema |
| `db.py` | AssetCoreDB + MiningRuntimeDB 双库适配器，DDL 从共享 SQL 文件加载 |
| `hash_utils.py` | 保守 snapshot 归一化 + SHA256 |
| `text_utils.py` | CJK-aware tokenization、归一化、相似度 |
| `ingestion/` | 递归文件夹扫描 → RawFileData |
| `parsers/` | MarkdownParser / PlainTextParser / PassthroughParser 工厂 |
| `structure/` | markdown-it → SectionNode 树（table/list/code 结构保留） |
| `segmentation/` | SectionNode → RawSegmentData（heading 独立成段） |
| `extractors.py` | RuleBasedEntityExtractor + DefaultRoleClassifier |
| `enrich/` | 规则增强（entity context、heading role、table metadata） |
| `relations/` | 结构关系（previous/next、same_section、section_header_of、same_parent_section） |
| `retrieval_units/` | raw_text + contextual_text + entity_card 检索单元 |
| `snapshot/` | 共享快照选择/创建（document/snapshot/link 三层） |
| `publishing/` | build 组装（增量合并）+ release 激活 |
| `runtime/` | RuntimeTracker：阶段事件跟踪 + 断点续跑计划 |
| `jobs/run.py` | Pipeline 编排器（run + publish 两个入口） |

## 测试

```bash
python -m pytest knowledge_mining/tests/test_v11_pipeline.py -v
```

30 个测试覆盖：models、DB adapters、hash utils、ingestion、structure、segmentation、extractors、enrich、relations、retrieval_units、snapshot、publishing、端到端 pipeline。

## 当前限制与演进方向

### v1.1 限制
- HTML/PDF/DOC/DOCX 只登记，不解析正文
- enrich 是规则增强，非 LLM
- relations 只有结构关系（previous/next、same_section 等）
- 断点续跑未在 jobs/run.py 中实现自动恢复入口

### v1.2 演进（工业级参考）
- LLM 替换 enrich（summary、generated_question、实体关系）
- 语义关系加入 relations（LLM-driven）
- 跨文档实体合并 + 社区检测
- 向量嵌入写入 asset_retrieval_embeddings

### v1.3+
- 持续演进：知识图谱构建、本体对齐、主动学习
