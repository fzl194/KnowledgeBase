# M1 Asset Core Schema

> 当前版本：v0.4
> PostgreSQL SQL 定义：`knowledge_assets/schemas/001_asset_core.sql`
> SQLite dev SQL 定义：`knowledge_assets/schemas/001_asset_core.sqlite.sql`
> 适用任务：`TASK-20260415-m1-knowledge-mining`、`TASK-20260415-m1-agent-serving`

## 目标

`knowledge_assets/schemas/` 是 Knowledge Mining 和 Agent Serving 的唯一数据库契约来源。

M1 阶段采用物理快照模型：每个 `publish_version` 都是一份完整可服务知识资产快照。Mining 写入 `staging` 版本，校验通过后切换为 `active`；Serving 只读唯一 `active` 版本。

本 schema 不定义 ontology、fact、evidence。L2 表命名为 `canonical_segment_sources`，表示 L1 归并段到 L0 原始段的来源映射和差异关系，不是旧项目里的 fact evidence。

v0.4 开始，schema 不再把产品、版本、网元视为唯一语料主轴。产品文档、专家文档、项目交付文档、培训材料、规范文档等都应进入同一套资产模型。产品、版本、网元只是一类可选 scope/facet，优先放入 `raw_documents.scope_json`；保留 `product`、`product_version`、`network_element` 只是为了兼容云核心网产品文档的高频过滤。

## 表总览

| 表 | 层级 | 作用 | Mining | Serving |
|---|---:|---|---|---|
| `asset.source_batches` | 输入批次 | 记录一次导入输入，不代表可服务版本 | 写入 | 审计可读 |
| `asset.publish_versions` | 发布控制 | 记录一次完整资产快照，`active` 是 Serving 入口 | 写入 / 激活 | 读取 active |
| `asset.raw_documents` | L0 文档 | 发布版本内的原始文档记录，保留原始/归一化来源路径与通用 scope | 写入 | 来源展示可读 |
| `asset.raw_segments` | L0 段落 | 文档切分后的原始段落，保留 block 形态与章节语义角色 | 写入 | 下钻读取 |
| `asset.canonical_segments` | L1 归并段 | 去重归并后的主检索对象 | 写入 | 主检索 |
| `asset.canonical_segment_sources` | L2 映射 | L1 到 L0 的来源与差异映射 | 写入 | 下钻选择 |

SQLite dev mode 使用同语义前缀表名：

| PostgreSQL 表 | SQLite dev 表 |
|---|---|
| `asset.source_batches` | `asset_source_batches` |
| `asset.publish_versions` | `asset_publish_versions` |
| `asset.raw_documents` | `asset_raw_documents` |
| `asset.raw_segments` | `asset_raw_segments` |
| `asset.canonical_segments` | `asset_canonical_segments` |
| `asset.canonical_segment_sources` | `asset_canonical_segment_sources` |

## 版本模型

`source_batch` 和 `publish_version` 是两个不同概念。

| 概念 | 含义 |
|---|---|
| `source_batch` | 这次新来了哪些输入文件或目录，以及批次级上下文 |
| `publish_version` | 这次发布后，Serving 可读取的完整知识库快照 |

M1 版本生成规则：

| 步骤 | 动作 |
|---|---|
| 1 | 读取当前唯一 `active` 版本，第一次发布时为空 |
| 2 | 创建新的 `staging` publish version，记录 `base_publish_version_id` |
| 3 | 用 `document_key + content_hash` 判断文档新增、修改、保留、删除 |
| 4 | 未变化文档可复制 L0 到新版本，记录 `copied_from_document_id` / `copied_from_segment_id` |
| 5 | 新增或修改文档重新解析生成 L0 |
| 6 | 基于新版本完整 L0 全量重建 L1 `canonical_segments` |
| 7 | 基于新版本 L1/L0 全量重建 L2 `canonical_segment_sources` |
| 8 | 校验 L0/L1/L2 完整性 |
| 9 | 事务切换旧 `active` 为 `archived`，新 `staging` 为 `active` |

同一逻辑文档在不同版本之间必须保持相同 `document_key`。`document_key` 表示“这是谁”，`content_hash` 表示“内容有没有变”。唯一约束是 `publish_version_id + document_key`，不是全局 `document_key` 唯一。

## 输入来源

M1 Mining 当前可以直接使用上游处理好的 Markdown 文件，但 schema 必须支持原始语料来自 HTML、PDF、DOC/DOCX、TXT 或混合来源。

产品文档转换链路建议作为一种上游输入适配器：

```text
HDX/HWICS
  -> productdoc_to_md.py
  -> Markdown 输出目录
  -> html_to_md_mapping.json / html_to_md_mapping.csv
  -> Mining ingestion
```

Mining 应优先读取 `html_to_md_mapping.json` 中的 topic 元数据，并写入 `raw_documents.metadata_json`：

| mapping 字段 | 建议落库位置 |
|---|---|
| `topic_id` | `metadata_json.topic_id`，也可作为 `document_key` 候选 |
| `parent_id` | `metadata_json.parent_id` |
| `topic_path_text` / `topic_path` | `metadata_json.topic_path`，也可参与 `scope_json` |
| `html_rel_path` / `html_abs_path` | `raw_storage_uri` |
| `md_rel_path` / `md_abs_path` | `relative_path` / `normalized_storage_uri` |
| `mode` | `metadata_json.mode` |
| `child_count` | `metadata_json.child_count` |

对于普通 Markdown 目录或专家手写文档，没有 mapping 文件也必须可导入。此时 `document_key` 可由批次上下文和相对路径生成，`raw_storage_uri` 可为空或等于 `source_uri`。

## 通用文档画像

`raw_documents` 使用以下字段表达输入来源与通用语料范围：

| 字段 | 说明 |
|---|---|
| `file_type` | 原始或主输入格式：`markdown/html/pdf/doc/docx/txt/mixed/other` |
| `source_type` | 来源类型：`productdoc_export/official_vendor/expert_authored/user_import/synthetic_coldstart/...` |
| `relative_path` | 相对导入根目录路径 |
| `raw_storage_uri` | 原始文件位置，例如原始 HTML/PDF/DOC |
| `normalized_storage_uri` | 归一化文件位置，例如转换后的 Markdown |
| `scope_json` | 适用范围，例如产品/版本/网元、项目、作者、环境、客户、专题等 |
| `tags_json` | 主题、场景、对象标签 |
| `conversion_profile_json` | 上游转换工具、规则、版本、结构保留策略 |
| `structure_quality` | `full_html/markdown_converted/markdown_native/plain_text_only/mixed/unknown` |

示例：

```json
{
  "product": "UDG",
  "product_version": "V100R023C10",
  "network_elements": ["SMF", "UPF"]
}
```

专家文档可以使用：

```json
{
  "author": "expert_a",
  "team": "core_network_delivery",
  "scenario": "PDU session troubleshooting"
}
```

## Serving 读取规则

Serving 不读取多个版本拼接结果，也不读取 `staging`。

每次请求先确定唯一 active version：

```sql
SELECT id
FROM asset.publish_versions
WHERE status = 'active'
LIMIT 1;
```

之后所有资产查询都必须带 `publish_version_id = :active_publish_version_id`。

主路径：

```text
active publish_version
  -> asset.canonical_segments
  -> asset.canonical_segment_sources
  -> asset.raw_segments
  -> asset.raw_documents
```

产品、版本、网元、项目、作者、场景等文档级约束保存在 `raw_documents.scope_json` 和兼容字段中。Serving 在 L2 下钻时通过 `raw_segments.raw_document_id -> raw_documents.id` 获取这些约束，不在 L2 中重复存储。

## 字段设计边界

为避免 M1 过度冗余，当前 schema 做了以下取舍：

| 取舍 | 说明 |
|---|---|
| 文档级元信息只放 `raw_documents` | 产品/版本/网元/项目/作者/场景等 scope 不在 `raw_segments` 和 L2 重复存储 |
| 产品字段不是核心主轴 | `product`、`product_version`、`network_element` 是兼容字段；通用语料范围进入 `scope_json` |
| 原始来源和归一化来源都可记录 | HTML/PDF/DOC 等原始来源进入 `raw_storage_uri`，转换后 Markdown 进入 `normalized_storage_uri` |
| block 形态与语义角色分离 | `block_type` 表示 paragraph/table/html_table/list/code 等，`section_role` 表示 parameter/example/procedure_step 等 |
| L1/L2 每个版本全量重建 | 新文档可能改变归并关系和 `has_variants` |
| L0 可物理复制 | 未变化文档可复制到新版本，保留 lineage 字段 |
| 每张资产表显式带 `publish_version_id` | 简化 Serving 查询，防止跨版本 join |
| 每张核心表保留 `metadata_json` | 给解析细节、统计、规则命中、差异详情留扩展口 |
| 不建 embedding 和 terms 表 | `segment_embeddings`、`asset_terms` 后续按需要新增，不进入 M1 core |

## 关键约束

| 约束 | 目的 |
|---|---|
| 全局最多一个 `active` publish version | Serving 始终有唯一读取入口 |
| `raw_documents(publish_version_id, document_key)` 唯一 | 同一版本内文档身份唯一 |
| `raw_segments(publish_version_id, raw_document_id, segment_key)` 唯一 | 同一文档内段落身份唯一 |
| `canonical_segments(publish_version_id, canonical_key)` 唯一 | 同一版本内 L1 归并对象唯一 |
| L2 复合外键带 `publish_version_id` | 防止 L1/L0 跨版本映射 |

## 解析要求

Mining 不能假设 Markdown 一定来自手写规范格式。M1 主输入可以是上游转换后的 Markdown，但 parser 必须容忍以下情况：

| 情况 | 要求 |
|---|---|
| 标准 Markdown table | 解析为 `block_type = table` |
| 上游保留的 HTML table | 解析为 `block_type = html_table`，至少保留 raw HTML |
| 列表或嵌套列表 | 解析为 `block_type = list` |
| fenced code | 解析为 `block_type = code` |
| 转换失败或未知结构 | 不丢文本，使用 `block_type = unknown` 或 `paragraph` |
| 标题表达章节语义 | 通过弱规则生成 `section_role`，例如 parameter/example/precondition/troubleshooting_step |

## 后续扩展

M1 core 稳定后，可以新增扩展表，但不应破坏现有六张表语义：

```text
asset.segment_embeddings(canonical_segment_id, embedding_model, embedding_dim, embedding, ...)
asset.asset_terms(publish_version_id, term, normalized_term, term_type, ...)
asset.publish_validation_reports(publish_version_id, check_name, status, details_json, ...)
```

任何 schema 变更都必须先更新本目录文档，并在 Mining 与 Serving 两个任务消息文件中说明兼容性影响。
