# CoreMasterKB 1.1 版本与存储简化方案

- 日期：2026-04-21
- 作者：Codex
- 状态：讨论草案
- 目的：在不引入过度复杂 Git 式版本系统的前提下，给出一套满足“最低限度回溯 + 数据不重复存储 + Serving 查询不复杂”的数据库版本方案。

## 1. 问题收敛

当前我们已经明确：

1. `publish` 更像一个“发布视图”，不是物理备份。
2. 不希望每个版本把所有数据再存一遍。
3. 不希望在 `doc / segment / retrieval_unit` 等多张主表上重复挂 `start/end version`。
4. 也不希望完全做成 Git 那种纯增量 commit/delta 模型，因为查询当前版本会变复杂。

因此，目标不是“最强版本系统”，而是：

```text
足够回溯
+ 不重复存储正文和对象
+ 当前版本查询简单
```

## 2. 结论：采用“对象去重 + 文档修订 + 发布视图”三层模型

这是我当前推荐的折中方案。

### 核心思想

1. 主资产对象只存一份，按内容去重。
2. 版本不精确到 segment/retrieval unit 的逐条 start/end。
3. 版本切换粒度提升到“文档修订”。
4. `publish_version` 只记录当前发布视图采用了哪些文档修订。
5. Serving 查询当前 active version 时，只需要基于“当前版本采用的文档修订集合”工作，不需要回放全量历史。

这个方案借了一点 Git 的“对象复用”思想，但不做纯 delta commit 图。

## 3. 方案总览

```text
source_batch
  -> mining_run
  -> document_revision
  -> publish_version

对象层（只存一份）：
  raw_document
  raw_segment
  raw_segment_relation
  retrieval_unit

修订层（文档级）：
  document_revision
  document_revision_segments
  document_revision_relations
  document_revision_retrieval_units

发布层（当前视图）：
  publish_version
  publish_version_documents
```

## 4. 为什么选择“文档修订”作为版本粒度

### 不选 segment 粒度

如果版本可见性精确到 segment：

- `publish_version_segments`
- `publish_version_retrieval_units`
- `publish_version_relations`

这些表会很大，而且每个版本都要挂很多行。

### 不选纯 Git delta 粒度

如果 `publish_version` 只记录变化：

- 当前 active version 查询要不断向父版本回溯
- Serving 读取复杂
- SQLite dev 模式下也不好维护

### 选 document revision 粒度

这是更平衡的做法：

- 一个文档如果没变，直接复用旧 revision
- 一个文档如果变了，只重建这个文档对应的 revision
- publish 只决定“每个 document_key 当前采用哪个 revision”

这样避免了：

- 全量复制正文
- 全量 segment 级版本挂载
- 复杂的 commit 回放逻辑

## 5. 建议的数据模型

## 5.1 输入与发布控制

### `asset_source_batches`

保留。

作用：记录一次输入批次的身份，而不是运行态流程。

| 字段 | 含义 |
|---|---|
| `id` | 批次 ID |
| `batch_code` | 批次编码 |
| `source_type` | 来源类型 |
| `description` | 描述 |
| `created_by` | 创建者 |
| `created_at` | 创建时间 |
| `metadata_json` | 上传入口、批次标签、外部说明等 |

### `asset_publish_versions`

保留。

作用：记录一次发布视图，不是数据物理副本。

| 字段 | 含义 |
|---|---|
| `id` | 发布版本 ID |
| `version_code` | 版本编码 |
| `status` | `staging/active/archived/failed` |
| `base_publish_version_id` | 基础版本，可为空 |
| `source_batch_id` | 主要来源批次 |
| `description` | 发布说明 |
| `build_started_at` | 构建开始 |
| `build_finished_at` | 构建结束 |
| `activated_at` | 激活时间 |
| `build_error` | 失败摘要 |
| `metadata_json` | 统计信息、质量门控、变更摘要 |

说明：

- `publish_version` 不直接挂 full copy 数据。
- `publish_version` 只表达一个可读视图。

## 5.2 主资产对象层

这些表尽量不带版本字段。

### `asset_raw_documents`

记录文档对象本身。

| 字段 | 含义 |
|---|---|
| `id` | 文档对象 ID |
| `document_key` | 稳定文档键 |
| `source_uri` | 实际读取位置 |
| `relative_path` | 相对输入根目录路径 |
| `file_name` | 文件名 |
| `file_type` | `markdown/txt/html/pdf/doc/docx/other` |
| `title` | 标题 |
| `document_type` | 文档类型 |
| `content_hash` | 文档内容 hash |
| `origin_batch_id` | 最初来源批次 |
| `scope_json` | 适用范围 |
| `tags_json` | 标签 |
| `structure_quality` | 结构质量 |
| `processing_profile_json` | 处理过程 |
| `metadata_json` | 扩展信息 |

说明：

- 这里的 `id` 更像“文档内容对象”。
- 相同 `document_key` 在不同时间可以有不同修订，但某个具体文档内容对象只存一份。

### `asset_raw_segments`

记录片段对象本身。

| 字段 | 含义 |
|---|---|
| `id` | raw segment ID |
| `raw_document_id` | 所属文档对象 |
| `segment_key` | 文档内稳定片段键 |
| `segment_index` | 顺序 |
| `section_path` | 章节路径 |
| `section_title` | 当前标题 |
| `block_type` | 结构类型 |
| `semantic_role` | 语义角色 |
| `raw_text` | 原文 |
| `normalized_text` | 归一化文本 |
| `content_hash` | 原文 hash |
| `normalized_hash` | 归一化 hash |
| `token_count` | token 数 |
| `structure_json` | 结构信息 |
| `source_offsets_json` | 来源定位 |
| `entity_refs_json` | 实体引用 |
| `metadata_json` | 扩展信息 |

### `asset_raw_segment_relations`

记录片段关系对象本身。

| 字段 | 含义 |
|---|---|
| `id` | relation ID |
| `source_raw_segment_id` | 起点 segment |
| `target_raw_segment_id` | 终点 segment |
| `relation_type` | 关系类型 |
| `weight` | 权重 |
| `confidence` | 置信度 |
| `distance` | 文档距离 |
| `metadata_json` | 扩展信息 |

### `asset_retrieval_units`

记录检索单元对象本身。

| 字段 | 含义 |
|---|---|
| `id` | retrieval unit ID |
| `unit_key` | 稳定键 |
| `unit_type` | `raw_text/contextual_text/summary/generated_question/entity_card/table_row` |
| `target_type` | `raw_segment/section/document/entity/synthetic` |
| `target_id` | 指向对象 ID |
| `title` | 标题 |
| `text` | 返回文本 |
| `search_text` | 检索文本 |
| `block_type` | 结构类型 |
| `semantic_role` | 语义角色 |
| `facets_json` | 动态过滤维度 |
| `entity_refs_json` | 实体引用 |
| `source_refs_json` | 来源引用 |
| `llm_result_refs_json` | LLM 弱引用 |
| `weight` | 静态权重 |
| `created_at` | 创建时间 |
| `metadata_json` | 扩展信息 |

### `asset_retrieval_embeddings`

可选。

挂在 retrieval unit 上，不直接跟版本绑定。

## 5.3 文档修订层

这是本方案的关键。

### `asset_document_revisions`

记录某个 `document_key` 的一次修订版本。

| 字段 | 含义 |
|---|---|
| `id` | document revision ID |
| `document_key` | 稳定文档键 |
| `raw_document_id` | 指向文档对象 |
| `revision_no` | 文档修订号 |
| `content_hash` | 该修订文档内容 hash |
| `parent_revision_id` | 上一个修订，可为空 |
| `source_batch_id` | 这次修订来自哪批输入 |
| `created_by_run_id` | 哪次 mining run 生成 |
| `created_at` | 创建时间 |
| `metadata_json` | 扩展信息 |

说明：

- 如果同一个 `document_key` 内容没变化，就不需要新建 revision。
- 如果内容变化，才创建新 revision。

### `asset_document_revision_segments`

记录某次文档修订包含哪些 raw segments。

| 字段 | 含义 |
|---|---|
| `document_revision_id` | 文档修订 ID |
| `raw_segment_id` | segment ID |

### `asset_document_revision_relations`

记录某次文档修订包含哪些片段关系。

| 字段 | 含义 |
|---|---|
| `document_revision_id` | 文档修订 ID |
| `relation_id` | relation ID |

### `asset_document_revision_retrieval_units`

记录某次文档修订包含哪些 retrieval units。

| 字段 | 含义 |
|---|---|
| `document_revision_id` | 文档修订 ID |
| `retrieval_unit_id` | retrieval unit ID |

说明：

- 这三张表把“文档修订”和底层对象关联起来。
- 这样版本切换只需要切文档修订，不需要逐 segment 管版本。

## 5.4 发布视图层

### `asset_publish_version_documents`

记录某个发布版本采用了哪些文档修订。

| 字段 | 含义 |
|---|---|
| `publish_version_id` | 发布版本 ID |
| `document_key` | 稳定文档键 |
| `document_revision_id` | 当前版本采用的文档修订 |
| `metadata_json` | 扩展信息 |

这是整个方案最关键的一张“视图挂载表”。

说明：

- `publish_version` 不需要挂 segments / relations / retrieval_units 全量集合。
- 只需要决定“每个文档在这个版本里采用哪个 revision”。

然后通过：

```text
publish_version
  -> document_revision
  -> revision_segments / revision_relations / revision_retrieval_units
```

就能得到当前版本的有效资产集合。

## 6. 查询时怎么工作

Serving 查询 active version 时，逻辑可以是：

1. 读取当前 active `publish_version`
2. 找到该版本对应的 `asset_publish_version_documents`
3. 根据这些 `document_revision_id`，拿到其对应的 `retrieval_units`
4. 在这些 retrieval units 上做 FTS / BM25 / embedding 检索
5. 命中后通过 `source_refs_json` 或 `document_revision_*` 反查 raw segments 和 raw documents

也就是说：

```text
Serving 的主查询入口仍然是 retrieval_units
publish_version 只是先限制“当前可见的 document revision 集合”
```

## 7. 为什么这比前面几种方案更平衡

### 比“每版全量复制”好

- 不重复存正文和对象
- 新版本只新增变更文档对应的新 revision

### 比“每表 start/end version”好

- 主资产表没有重复的版本区间字段
- 版本逻辑集中在 revision 和 publish 视图层

### 比“完全 Git delta”好

- 不需要从父版本一路回放 change
- 当前 active version 查询简单

### 比“每版挂全量 segment / retrieval unit”好

- 版本挂载规模降到文档修订粒度
- 增长更可控

## 8. 一个例子

假设：

### v1

有两个文档：

- `A -> revision A1`
- `B -> revision B1`

那么：

```text
publish_version v1
  -> A:A1
  -> B:B1
```

### v2

第二批数据来了：

- A 没变化
- B 内容更新，生成 `B2`
- C 新增，生成 `C1`

则：

```text
publish_version v2
  -> A:A1
  -> B:B2
  -> C:C1
```

此时：

- A1 复用
- B1 保留供回溯，但当前 active 不再引用
- 不需要复制 A 的 segments / retrieval_units

## 9. 回溯能力满足到什么程度

这个方案满足“最低限度回溯”的需求：

1. 能知道某个发布版本采用了哪些文档修订。
2. 能知道某个文档修订下有哪些 segment / relation / retrieval_unit。
3. 能回溯某个 retrieval unit 最终来自哪些 raw segments / raw documents。
4. 能比较同一个 `document_key` 在不同 revision 间的变化。

它不追求：

- 任意 segment 的细粒度历史演化图
- 纯 delta commit 回放
- Git 那种对象树完全泛化版本控制

这些都不是 1.1 必需。

## 10. 仍然需要的 Mining Runtime 表

这个版本方案不替代 Mining 运行态表。

仍建议保留：

### `mining_runs`

记录一次 Mining 执行。

### `mining_run_documents`

记录每个文档在本次运行中的阶段状态。

### `mining_stage_events`

记录阶段事件流。

原因：

- `publish_version` 只是发布视图
- `document_revision` 只是资产修订
- 真正的运行过程状态仍应放在 Mining Runtime 表里

## 11. 当前推荐方案

### 必留

```text
asset_source_batches
asset_publish_versions

asset_raw_documents
asset_raw_segments
asset_raw_segment_relations
asset_retrieval_units

asset_document_revisions
asset_document_revision_segments
asset_document_revision_relations
asset_document_revision_retrieval_units

asset_publish_version_documents

mining_runs
mining_run_documents
mining_stage_events
```

### 可后置

```text
asset_retrieval_embeddings
```

### 保留但不作为 1.1 主路径

```text
asset_canonical_segments
asset_canonical_segment_sources
```

## 12. 最终结论

当前最合适的 1.1 版本方案不是：

- 物理全量快照
- 也不是每表 start/end version
- 也不是纯 Git 式 delta commit

而是：

```text
对象去重存储
+ 文档修订作为版本切换粒度
+ 发布版本只选择 document revision 集合
+ Serving 查询当前 active version 时保持简单
```

这套方案足以满足：

- 不重复存储
- 版本可回溯
- Serving 可实现
- 后续还能继续演进

