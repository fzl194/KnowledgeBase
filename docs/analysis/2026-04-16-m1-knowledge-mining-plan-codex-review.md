# M1 Knowledge Mining Plan Codex Review

> 任务：TASK-20260415-m1-knowledge-mining
> 审查人：Codex
> 日期：2026-04-16
> 范围：Claude Mining 设计文档与实现计划；用户补充的 `productdoc_to_md.py` 上游转换器；schema v0.4 调整

## 审查背景

Claude Mining 已产出：

- `docs/plans/2026-04-16-m1-knowledge-mining-design.md`
- `docs/plans/2026-04-16-m1-knowledge-mining-impl-plan.md`

用户随后补充两个关键前提：

1. 当前 M1 可以直接使用上游处理好的 Markdown 文件。
2. 上游 `cloud_core_coldstart_md/productdoc_to_md.py` 已能在内网将产品 HTML 文档转换为 Markdown，并输出 `html_to_md_mapping.json/csv`。
3. 未来语料不一定是产品文档，可能是专家文档、项目文档、培训材料或其他格式；原始来源也可能是 HTML、PDF、DOC/DOCX、TXT。

因此，本轮审查不仅判断 Claude 计划是否能跑通 Markdown demo，还要判断其是否符合最新数据来源和长期资产模型。

## 审查范围

- Claude Mining 的 6 模块 pipeline：ingestion、document_profile、structure、segmentation、canonicalization、publishing。
- 12 个实现 Task 的边界、测试覆盖和 schema 使用方式。
- 与 `knowledge_assets/schemas/001_asset_core.sql` 的契约一致性。
- 与上游 `productdoc_to_md.py` 输出的适配关系。

未审查内容：

- Claude 尚未提交 Mining 实现代码。
- 未执行计划中的测试。
- 未评估 Serving 当前未跟踪实现代码。

## 发现的问题

### P1：计划仍绑定“Markdown 产品文档”假设，不符合最新通用语料模型

Claude 计划的核心画像仍是：

```text
product / product_version / network_element / command_manual / feature_guide
```

这与最新方向不一致。产品、版本、网元只能作为可选 scope/facet；未来专家文档和项目文档可能完全没有这些字段。

已同步调整 schema 至 v0.4：

- `raw_documents.scope_json`
- `raw_documents.tags_json`
- `raw_documents.source_type`
- `raw_documents.file_type`
- `raw_documents.structure_quality`

Claude Mining 必须基于这些通用字段修订 `DocumentProfile`，不能把产品字段写成核心必填路径。

### P1：计划未纳入 `productdoc_to_md.py` 上游转换器产物

用户补充的上游转换器会输出：

- Markdown 目录
- `html_to_md_mapping.json`
- `html_to_md_mapping.csv`

mapping 中包含 `topic_id`、`parent_id`、`topic_path`、`html_rel_path`、`md_rel_path`、`mode`、`child_count` 等关键元数据。

Claude 当前计划只扫描 Markdown 文件，未读取 mapping。这会丢失原始 HTML 来源、导航路径和 HTML/MD 对应关系，削弱溯源、document_key 稳定性和后续回读 HTML 的能力。

### P1：SQLite dev schema 不应由 Mining 私有代码内嵌

Claude Task 3 计划在 `knowledge_mining/mining/db.py` 内维护一份 `_SCHEMA_SQL`。这会导致 PostgreSQL DDL、Mining SQLite DDL、Serving SQLite DDL 三套 schema 漂移。

已补充共享 SQLite DDL：

- `knowledge_assets/schemas/001_asset_core.sqlite.sql`

Claude Mining 和 Claude Serving 都应引用该文件。Mining 可以封装初始化逻辑，但不应在 `knowledge_mining/**` 中复制 asset schema 正文。

### P2：Structure Parser 只覆盖标准 Markdown block，不足以覆盖转换产物

`productdoc_to_md.py` 能将简单 HTML table 转成 Markdown table，但复杂 `rowspan/colspan` 表格会保留为原始 HTML table。Claude 计划只列出 Markdown AST 中的 table/fence/list/paragraph，未要求识别 raw HTML table。

Mining parser 至少需要：

- 标准 Markdown table -> `block_type = table`
- 原始 HTML table -> `block_type = html_table`
- fenced code -> `block_type = code`
- list/ordered list -> `block_type = list`
- 解析失败 -> 保留 `raw_text`，使用 `block_type = unknown` 或 `paragraph`

### P2：`segment_type` 混用了结构形态和语义角色

Claude 计划中 `segment_type` 同时表示 `table/paragraph/example` 和 `parameter/note/concept`。这会造成参数表到底是 table 还是 parameter 的冲突。

schema v0.4 已拆分：

- `raw_segments.block_type`：结构形态。
- `raw_segments.section_role`：章节语义角色。
- `canonical_segments.section_role`：L1 归并后的语义角色。

Claude 的 dataclass、segmentation、canonicalization、tests 都需要跟随调整。

### P2：测试样例不足以覆盖真实输入风险

当前计划测试主要是合成标准 Markdown。需要补充：

- 无 frontmatter Markdown。
- `productdoc_to_md.py` 输出目录 + `html_to_md_mapping.json`。
- 带 raw HTML table 的 Markdown。
- 专家文档或非产品文档，产品/版本/网元为空但 scope/tags 有效。
- 普通 Markdown 目录无 mapping 时仍能导入。

## 测试缺口

Claude 修订计划后，最低应增加以下测试：

| 测试 | 目标 |
|---|---|
| `test_ingest_productdoc_mapping` | 读取 html_to_md_mapping.json 并生成稳定 document_key/source paths |
| `test_ingest_plain_markdown_without_metadata` | 普通 Markdown 无元数据也可导入 |
| `test_parse_html_table_block` | Markdown 中保留的 `<table>` 不丢失 |
| `test_segment_block_type_and_section_role` | block 形态和语义角色分离 |
| `test_expert_document_profile` | 专家文档不需要 product/version/network_element |
| `test_sqlite_schema_loaded_from_shared_file` | dev DB 使用 `knowledge_assets/schemas/001_asset_core.sqlite.sql` |

## 回归风险

- 如果继续按旧计划实现，M1 会跑通“标准 Markdown 产品文档 demo”，但对真实上游转换产物适配不足。
- 如果 Mining 私有维护 SQLite schema，Serving 与 Mining 会出现字段名、表名或约束漂移。
- 如果产品字段写死，未来专家文档和项目文档会被迫塞进 `other` 或 `metadata_json`，Serving 难以稳定过滤和追溯。
- 如果不保留 HTML/MD mapping，后续对转换失败的 30% 内容难以回读原始 HTML 重新解析。

## 建议修复项

1. 修订设计文档中的目标表述：从“Markdown 产品文档”改为“上游转换后的 Markdown / source artifacts”。
2. 修订 `DocumentProfile`：以 `source_type`、`document_type`、`scope_json`、`tags_json` 为核心，产品/版本/网元为可选 facet。
3. Ingestion 增加 `productdoc_to_md.py` 输出目录模式：读取 `html_to_md_mapping.json/csv`。
4. 数据模型增加 `relative_path`、`raw_storage_uri`、`normalized_storage_uri`、`conversion_profile_json`、`structure_quality`。
5. Segmentation 拆分 `block_type` 和 `section_role`。
6. SQLite 初始化改为读取 `knowledge_assets/schemas/001_asset_core.sqlite.sql`。
7. 测试样例覆盖 mapping、raw HTML table、无元数据 Markdown、非产品专家文档。

## 无法确认的残余风险

- `productdoc_to_md.py` 在真实内网数据上能覆盖约 70% 结构，但剩余未正确转换部分尚未有样本，M1 只能先保留 raw source 和 fallback。
- 当前 schema v0.4 尚未在 PostgreSQL 或 SQLite 中实际执行验证。
- Serving 已有未跟踪实现文件，可能仍基于 v0.3 字段，需要后续单独审查。

## 管理员介入影响

用户明确要求未来纳入上游 HTML->Markdown 转换器，但当前版本仍使用上游处理好的 Markdown；同时要求 schema、架构文档、数据文档和反馈意见保持一致。

因此本轮 Codex 已同步更新：

- `knowledge_assets/schemas/001_asset_core.sql`
- `knowledge_assets/schemas/001_asset_core.sqlite.sql`
- `knowledge_assets/schemas/README.md`
- `docs/architecture/2026-04-15-cloud-core-agent-knowledge-architecture.md`
- `docs/architecture/2026-04-15-mining-serving-parallel-design.md`

## 最终评估

Claude Mining 原计划不建议直接进入实现。

它的 pipeline 骨架可保留，但必须先基于 schema v0.4 和上游转换器产物修订计划。修订完成前，若直接开发，会在输入来源、schema 兼容、SQLite dev、通用语料支持和真实转换产物解析方面留下 P1/P2 风险。
