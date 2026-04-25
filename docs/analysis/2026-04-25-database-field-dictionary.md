# CoreMasterKB 数据库字段字典

- 日期：2026-04-25
- 作者：Codex
- 主题：当前正式数据库中每张表、每个字段的定义、获取方式和用途说明

---

## 1. 文档范围

本文档覆盖当前正式三库：

- `asset_core`
- `mining_runtime`
- `agent_llm_runtime`

说明原则：

- “定义”描述字段在业务上的语义，不重复抄 SQL 约束全文。
- “怎么获取”描述这个字段通常由谁写、从哪里来、如何形成。
- “有啥用”描述这个字段被哪些链路消费，或在系统中承担什么职责。
- 对辅助对象（FTS 虚表、trigger、索引）单独说明，不混入业务字段表。

正式基线来源：

- `databases/asset_core/schemas/001_asset_core.sqlite.sql`
- `databases/mining_runtime/schemas/001_mining_runtime.sqlite.sql`
- `databases/agent_llm_runtime/schemas/001_agent_llm_runtime.sqlite.sql`
- `docs/architecture/2026-04-21-coremasterkb-v1.1-architecture.md`

---

## 2. asset_core

## 2.1 库职责

`asset_core` 是正式知识资产库，负责保存：

- 输入批次
- 逻辑文档
- 共享内容快照
- 文档到快照的映射
- 原始片段
- 片段关系
- 检索单元
- 检索向量
- build
- release

Serving 只读这套库；Mining 负责写入这套库中的正式资产数据。

---

## 2.2 `asset_source_batches`

输入批次表，记录一轮资料导入或目录扫描的批次身份。

| 字段 | 定义 | 怎么获取 | 有啥用 |
|---|---|---|---|
| `id` | 批次主键 ID | 由 Mining 在创建批次时生成 UUID | 作为其它表引用该批次的稳定主键 |
| `batch_code` | 批次的人类可读编码 | 通常由 Mining 按 run 生成，如 `batch-<run_id前缀>` | 方便排查、展示和跨日志定位 |
| `source_type` | 这批资料的来源类型 | 来自 `BatchParams.default_source_type` 或导入入口配置 | 用于区分资料来源场景，如 folder scan、manual upload |
| `description` | 批次描述 | 由发起方或 Mining 写入说明文本 | 用于调试、展示批次用途 |
| `created_by` | 批次创建者 | 由外部调用方或运维入口写入，当前可为空 | 用于审计谁触发了这批导入 |
| `created_at` | 批次创建时间 | 插入时由代码写当前时间 | 用于排序、审计和排查 |
| `metadata_json` | 批次附加元数据 | 由写入方按需补充 JSON | 预留扩展字段，不改表结构也能带附加信息 |

---

## 2.3 `asset_documents`

逻辑文档表，表示“这是不是同一个文档身份”。

| 字段 | 定义 | 怎么获取 | 有啥用 |
|---|---|---|---|
| `id` | 逻辑文档主键 ID | 由 Mining 在 `upsert_document` 时生成或读回 | 被 link、build 选择映射等下游表引用 |
| `document_key` | 逻辑文档唯一键 | 通常由路径或业务身份拼成，例如 `doc:/relative/path.md` | 这是判断“是否同一逻辑文档”的核心键 |
| `document_name` | 文档显示名 | 来自文档标题、文件名或外部元信息 | 用于展示与人工识别 |
| `document_type` | 文档类型 | 来自 profile、规则识别或外部配置 | 为 Serving 和分析链路提供粗粒度语义分类 |
| `metadata_json` | 文档级附加元数据 | 由 Mining 根据 profile 或补充信息写入 | 存放不适合单独建列的文档附加属性 |
| `created_at` | 逻辑文档首次入库时间 | 文档第一次被创建时写入 | 用于审计和时间排序 |

---

## 2.4 `asset_document_snapshots`

共享内容快照表，表示不可变内容对象。多个逻辑文档可共享同一快照。

| 字段 | 定义 | 怎么获取 | 有啥用 |
|---|---|---|---|
| `id` | 快照主键 ID | 由 Mining 在创建 snapshot 时生成 UUID | 被 links、segments、retrieval units、build 映射引用 |
| `normalized_content_hash` | 归一化内容哈希 | 由 Mining 对内容做保守归一化后计算 | 这是 shared snapshot 复用的核心判断依据 |
| `raw_content_hash` | 原始内容哈希 | 由 Mining 对原始输入内容计算 | 用于区分原文变化与归一化变化，辅助排查 |
| `mime_type` | 文档内容 MIME 类型 | 来自解析器识别或文件类型映射 | 决定解析策略与后续处理能力 |
| `title` | 快照级标题 | 来自文档标题或解析结果 | 用于 Serving attribution 和人类识别 |
| `scope_json` | 快照级作用域信息 | 由 Mining 从 profile、解析结果或外部元数据提取 | 为检索过滤和来源展示提供结构化范围 |
| `tags_json` | 快照级标签列表 | 由 Mining 从 profile 或输入元数据生成 | 用于分类、过滤或统计 |
| `parser_profile_json` | 解析配置快照 | 由解析阶段记录使用的 parser / profile 信息 | 便于回溯这份 snapshot 是如何被解析出来的 |
| `metadata_json` | 快照级附加元数据 | 由 Mining 按需写入 JSON | 存储其它不稳定扩展信息 |
| `created_at` | 快照创建时间 | 插入时由代码写当前时间 | 用于审计和排序 |

---

## 2.5 `asset_document_snapshot_links`

文档到快照的引用表，记录某个逻辑文档在某次输入下引用了哪份 snapshot。

| 字段 | 定义 | 怎么获取 | 有啥用 |
|---|---|---|---|
| `id` | link 主键 ID | 由 Mining 创建 link 时生成 UUID | 作为该映射关系的稳定主键 |
| `document_id` | 逻辑文档 ID | 由 `asset_documents.id` 引用得到 | 表示是哪份逻辑文档引用了快照 |
| `document_snapshot_id` | 快照 ID | 由 `asset_document_snapshots.id` 引用得到 | 表示文档引用的是哪份共享内容 |
| `source_batch_id` | 来源批次 ID | 来自本轮 source batch | 把这次 link 挂到具体导入批次上 |
| `relative_path` | 批次内相对路径 | 来自目录扫描结果 | 记录文档在本批输入中的位置 |
| `source_uri` | 原始来源 URI | 来自输入路径或外部来源标识 | 便于回溯外部来源 |
| `title` | link 层标题 | 来自文档本轮导入时的标题信息 | 允许同一 snapshot 在不同文档语境下带不同显示标题 |
| `scope_json` | link 层作用域 | 来自文档 profile 或本轮导入上下文 | 存放文档专属 scope，而不污染共享 snapshot |
| `tags_json` | link 层标签 | 来自本轮导入的文档专属标签 | 允许同一 snapshot 在不同文档链路下带不同标签 |
| `linked_at` | link 建立时间 | 创建 link 时写入 | 用于识别最新 link 或历史引用链 |
| `metadata_json` | link 附加元数据 | 由 Mining 按需写入 | 用于存放路径外的补充上下文 |

---

## 2.6 `asset_raw_segments`

原始片段表，是 snapshot 下的事实片段真相源。

| 字段 | 定义 | 怎么获取 | 有啥用 |
|---|---|---|---|
| `id` | 片段主键 ID | 由 Mining 在写 segment 时生成 UUID | 作为 relations、retrieval units 强桥接的目标 |
| `document_snapshot_id` | 所属 snapshot ID | 来自当前处理的 snapshot | 把 segment 挂到具体内容快照下 |
| `segment_key` | 片段业务键 | 通常由 `document_key + segment_index` 组成 | 用于幂等写入和定位片段 |
| `segment_index` | 片段序号 | 来自 segmentation 阶段 | 表示片段在文档中的顺序 |
| `section_path` | 所在章节路径 | 由结构解析得到 | 支撑上下文、分段层级、contextual retrieval |
| `section_title` | 当前最直接节标题 | 从 `section_path` 或结构树提取 | 用于展示、上下文增强和生成检索单元 |
| `block_type` | 片段块类型 | 由 parser / segmenter 判断，例如 paragraph、table | 影响 Serving 排序、过滤和 unit 生成策略 |
| `semantic_role` | 片段语义角色 | 由 enrich 阶段规则或 LLM 分类得到 | 支撑 query intent 匹配和 rerank |
| `raw_text` | 原始文本内容 | 由 segmenter 从解析树中提取 | 是内容真相文本和 drill-down 主体 |
| `normalized_text` | 归一化文本 | 由 Mining 对 raw_text 做标准化处理得到 | 用于 hash、比较和稳定处理 |
| `content_hash` | 原始文本哈希 | 对 `raw_text` 计算 | 用于去重、排查和变化判断 |
| `normalized_hash` | 归一化文本哈希 | 对 `normalized_text` 计算 | 用于更稳的相似判断 |
| `token_count` | token 数量 | 由文本工具统计 | 用于过滤、question generation 门槛等 |
| `structure_json` | 结构化块信息 | 由 parser / segmenter 解析得到，如表格列、列表层级 | 支撑表格行级 unit、结构检索和上下文增强 |
| `source_offsets_json` | 源文定位信息 | 由 parser 记录行号、offset 等 | 用于精确回溯原文位置 |
| `entity_refs_json` | 片段提到的实体列表 | 由 enrich 阶段规则或 LLM 提取 | 支撑 entity_card 生成、Serving entity boost |
| `metadata_json` | 片段附加元数据 | 由 Mining 按需写入 | 存储稳定字段之外的补充信息 |

---

## 2.7 `asset_raw_segment_relations`

片段关系表，保存 segment 之间的结构关系和扩展语义关系。

| 字段 | 定义 | 怎么获取 | 有啥用 |
|---|---|---|---|
| `id` | 关系主键 ID | 由 Mining 写 relation 时生成 UUID | 作为关系对象稳定 ID |
| `document_snapshot_id` | 所属 snapshot ID | 来自当前 snapshot | 把关系约束在单份 snapshot 内 |
| `source_segment_id` | 源片段 ID | 由 segment_key -> segment_id 映射得到 | 表示关系起点 |
| `target_segment_id` | 目标片段 ID | 同上 | 表示关系终点 |
| `relation_type` | 关系类型 | 由 relations builder 生成，如 previous、same_section | 支撑 graph expansion 和上下文拼装 |
| `weight` | 关系权重 | 通常由 builder 给默认值或估计值 | 预留未来按强弱排序关系 |
| `confidence` | 关系置信度 | 规则关系通常为 1.0，LLM 关系可更细 | 方便后续过滤低置信关系 |
| `distance` | 距离信息 | 常由 segment index 差值或层级距离得到 | 支撑近邻扩展和上下文控制 |
| `metadata_json` | 关系附加信息 | 由 builder 按需写入 | 记录关系来源或其它补充属性 |

---

## 2.8 `asset_retrieval_units`

检索单元表，是 Serving 的主检索对象层。

| 字段 | 定义 | 怎么获取 | 有啥用 |
|---|---|---|---|
| `id` | retrieval unit 主键 ID | 由 Mining 写 unit 时生成 UUID | 作为检索结果的实体 ID |
| `document_snapshot_id` | 所属 snapshot ID | 来自当前 snapshot | 保证检索范围可按 snapshot 限定 |
| `unit_key` | unit 业务键 | 由 Mining 根据 unit 类型和来源生成 | 用于幂等写入和业务定位 |
| `unit_type` | 检索单元类型 | 由 builder 决定，如 raw_text、contextual_text、entity_card | 决定 unit 语义、Serving 去重和排序策略 |
| `target_type` | 该 unit 面向的目标对象类型 | 由 builder 决定，如 raw_segment、entity、section | 为 Serving fallback 和解释 unit 语义 |
| `target_ref_json` | 目标对象引用 | 由 builder 按 unit 语义写入 JSON | 在没有强桥接时提供结构化回溯路径 |
| `title` | unit 标题 | 由 segment 标题、entity 名称或问题标题生成 | 提升检索展示与 FTS 命中效果 |
| `text` | unit 主文本 | 由 Mining 生成，可是原文、上下文文本、问题文本等 | Serving 实际召回和展示的主体内容 |
| `search_text` | 供检索使用的预处理文本 | 由 Mining 对 text 做预分词或增强 | 提升 FTS/BM25 召回质量，尤其中文场景 |
| `block_type` | 来源片段块类型 | 继承自 segment | 供 Serving 做低价值块降权等策略 |
| `semantic_role` | 来源片段语义角色 | 继承或映射自 segment | 供 QueryPlan / rerank 做 intent 匹配 |
| `facets_json` | 可过滤/加权的 facet 信息 | 由 builder 从 segment 元数据整理得到 | Serving 可用它做 scope 匹配和过滤 |
| `entity_refs_json` | unit 关联实体 | 由 segment enrich 结果继承或派生 | Serving 可据此做 entity boost |
| `source_refs_json` | provenance 溯源信息 | 由 builder 根据来源 segment 写 JSON | 作为 `source_segment_id` 之外的 fallback 来源链 |
| `llm_result_refs_json` | LLM 结果引用 | 由 LLM 生成型 unit 写入，例如 generated_question | 把 unit 与 llm runtime 结果做弱引用关联 |
| `source_segment_id` | 强桥接原始片段 ID | 由当前 unit 来源 segment 的 ID 写入 | 是 Mining -> Serving 当前最稳的 source bridge |
| `weight` | unit 权重 | 由 builder 为不同 unit 类型设初始值 | 供后续检索和排序策略使用 |
| `created_at` | unit 创建时间 | 插入时写当前时间 | 用于审计和排序 |
| `metadata_json` | unit 附加元数据 | 由 builder 按需补充 | 存储 question index、section titles 等扩展信息 |

---

## 2.9 `asset_retrieval_embeddings`

检索向量表，为 retrieval units 提供向量检索支撑。

| 字段 | 定义 | 怎么获取 | 有啥用 |
|---|---|---|---|
| `id` | 向量记录主键 ID | 由 Mining 在生成 embedding 时生成 UUID | 作为向量记录的稳定主键 |
| `retrieval_unit_id` | 关联的 retrieval unit ID | 来自 `asset_retrieval_units.id` | 指明这条向量属于哪条检索单元 |
| `embedding_model` | 使用的 embedding 模型 | 来自 embedding generator 配置 | 区分不同模型生成的向量 |
| `embedding_provider` | 向量服务提供方 | 来自 embedding generator 实现 | 用于审计和兼容多 provider |
| `text_kind` | 向量对应的文本种类 | 由生成器指定，如 full | 区分同一 unit 不同文本视角的向量 |
| `embedding_dim` | 向量维度 | 由 embedding 结果长度得出 | 供存储、校验和后续索引使用 |
| `embedding_vector` | 向量内容 | 由 embedding generator 返回后序列化写入 | 后续向量检索的主体数据 |
| `content_hash` | 生成向量时对应文本哈希 | 由生成器或写入方计算 | 便于判断向量是否过期 |
| `created_at` | 向量创建时间 | 插入时写当前时间 | 用于审计和版本比较 |
| `metadata_json` | 向量附加元数据 | 由写入方补充 | 用于记录 provider 响应或参数快照 |

---

## 2.10 `asset_builds`

build 表，表示一次完整知识视图构建。

| 字段 | 定义 | 怎么获取 | 有啥用 |
|---|---|---|---|
| `id` | build 主键 ID | 由 Mining assemble_build 时生成 UUID | 被 build-document 映射和 release 引用 |
| `build_code` | build 可读编码 | 由 Mining 按规则生成 | 用于展示、日志和排查 |
| `status` | build 当前状态 | 由 build 流程推进时更新，如 building、validated、published | 控制发布状态流转 |
| `build_mode` | build 模式 | 由 assemble_build 根据有无 parent build 及变更集决定 | 区分 full 与 incremental 构建 |
| `source_batch_id` | 来源批次 ID | 来自本轮 batch | 把 build 追溯回哪轮原始输入 |
| `parent_build_id` | 父 build ID | 来自当前 active build 或上一个 build | 支撑增量构建和版本链 |
| `mining_run_id` | 对应的 mining run ID | 由调用方写入本轮 run_id | 把正式 build 和运行态 run 关联起来 |
| `summary_json` | build 摘要 | 由 assemble_build 汇总写入 | 记录文档变更摘要和构建结果概览 |
| `validation_json` | build 校验结果 | 由 validate 阶段生成 | 记录 build 是否通过校验及原因 |
| `created_at` | build 创建时间 | build 初始化时写入 | 用于时间排序和审计 |
| `finished_at` | build 完成时间 | 构建完成或失败时写入 | 用于计算耗时和状态判定 |

---

## 2.11 `asset_build_document_snapshots`

build 内文档选择映射表，表示某个 build 中每个逻辑文档采用哪份 snapshot。

| 字段 | 定义 | 怎么获取 | 有啥用 |
|---|---|---|---|
| `build_id` | 所属 build ID | 来自 `asset_builds.id` | 指明这条映射属于哪个 build |
| `document_id` | 逻辑文档 ID | 来自 `asset_documents.id` | 指明是哪个逻辑文档 |
| `document_snapshot_id` | 被选中的 snapshot ID | 来自 snapshot decision 结果 | 指明 build 中该文档当前采用的内容版本 |
| `selection_status` | 该文档在 build 中的选择状态 | 由 build 组装逻辑计算，如 active、removed | Serving 只应消费 active 选择 |
| `reason` | 选择原因 | 由 classify_documents 决定，如 add、update、retain、remove | 解释这条映射为何进入 build |
| `metadata_json` | 映射附加元数据 | 由 build 流程补充 | 存储变化细节、诊断信息等 |

---

## 2.12 `asset_publish_releases`

release 表，定义哪个 build 当前在某个 channel 上生效。

| 字段 | 定义 | 怎么获取 | 有啥用 |
|---|---|---|---|
| `id` | release 主键 ID | 由 publish_release 时生成 UUID | 作为当前发布实例的稳定 ID |
| `release_code` | release 可读编码 | 由发布逻辑生成 | 用于展示、日志和排查 |
| `build_id` | 被发布的 build ID | 来自 `asset_builds.id` | 指定这个 release 发布的是哪版知识视图 |
| `channel` | 发布通道 | 由发布入口指定，如 `default` | 支撑多 channel 发布 |
| `status` | release 状态 | 由发布流程维护，如 staging、active、retired | Serving 读取 active release 作为入口 |
| `previous_release_id` | 上一个 release ID | 由发布逻辑在切换 active 时写入 | 形成发布链和回退线索 |
| `released_by` | 发布者 | 由 run 或人工发布入口写入 | 用于审计是谁发布了该版本 |
| `release_notes` | 发布说明 | 由发布流程或调用方写入 | 说明本次发布内容 |
| `activated_at` | 激活时间 | release 变为 active 时写入 | 供 Serving 和审计识别当前生效时间 |
| `deactivated_at` | 退役时间 | release 退役时写入 | 记录它何时不再生效 |
| `metadata_json` | release 附加元数据 | 由发布逻辑补充 | 存放发布附加信息 |

---

## 2.13 辅助对象

### `asset_retrieval_units_fts`

这是 FTS5 虚表，不是业务真相表。它镜像 `asset_retrieval_units` 中的三类检索字段：

- `title`
- `text`
- `search_text`

字段含义：

| 字段 | 定义 | 怎么获取 | 有啥用 |
|---|---|---|---|
| `retrieval_unit_id` | 对应业务表中的 retrieval unit ID | 由 trigger 从 `asset_retrieval_units.id` 同步写入 | 检索命中后能回到业务表 |
| `title` | 索引标题文本 | 由 trigger 同步 `asset_retrieval_units.title` | 提升标题命中 |
| `text` | 索引正文文本 | 由 trigger 同步 `asset_retrieval_units.text` | 主体 FTS 检索字段 |
| `search_text` | 索引预处理文本 | 由 trigger 同步 `asset_retrieval_units.search_text` | 支撑预分词和增强检索 |

### 触发器

- `trg_asset_retrieval_units_ai`
- `trg_asset_retrieval_units_au`
- `trg_asset_retrieval_units_ad`

用途：

- 在 insert / update / delete 时自动维护 FTS 虚表
- 保证 Serving 不需要自己维护索引同步逻辑

---

## 3. mining_runtime

## 3.1 库职责

`mining_runtime` 是 Mining 运行态库，只记录：

- run 总状态
- run 内文档状态
- stage 事件流水

它不承载正式知识资产，不被 Serving 直接读取。

---

## 3.2 `mining_runs`

整次 Mining run 的总控制面。

| 字段 | 定义 | 怎么获取 | 有啥用 |
|---|---|---|---|
| `id` | run 主键 ID | 由 `run()` 开始时预先生成 UUID | 作为整次挖掘流程的总追踪键 |
| `source_batch_id` | 对应的 source batch ID | 来自 asset_core 中本轮创建的 batch | 把运行态 run 和正式资产批次关联起来 |
| `input_path` | 本轮输入目录/入口路径 | 来自 `run(input_path=...)` 参数 | 用于排查本轮处理的是哪批输入 |
| `status` | run 状态 | 由 runtime tracker 维护，如 queued、running、completed、failed | 控制 run 生命周期和恢复逻辑 |
| `build_id` | 本轮生成的 build ID | 在 assemble_build 成功后写入 | 让 run 可以追溯到正式 build 结果 |
| `total_documents` | 本轮发现的文档总数 | 由 ingest 统计后写入 | 用于展示和进度计算 |
| `new_count` | 本轮判定为 NEW 的文档数 | 由文档分类逻辑累计写入 | 用于构建摘要和统计 |
| `updated_count` | 本轮判定为 UPDATE 的文档数 | 同上 | 标识内容变化规模 |
| `skipped_count` | 本轮跳过文档数 | 由 SKIP 或无可处理内容的情况累计 | 反映复用情况和无效输入情况 |
| `failed_count` | 本轮失败文档数 | 由文档失败时累计 | 用于判断 run 是否部分失败 |
| `committed_count` | 成功落到正式资产的文档数 | 文档 commit 成功后累计 | 反映实际产出量 |
| `started_at` | run 开始时间 | create_run 时写入 | 用于审计和耗时统计 |
| `finished_at` | run 结束时间 | complete / fail / interrupt 时写入 | 用于状态收口和耗时计算 |
| `error_summary` | run 级错误摘要 | 全局失败时写入截断错误信息 | 方便快速查看失败原因 |
| `metadata_json` | run 附加元数据 | 当前会写入 ingest summary，后续可扩展 | 用于记录输入统计和其它附加信息 |

---

## 3.3 `mining_run_documents`

每篇文档在本轮 run 中的状态机。

| 字段 | 定义 | 怎么获取 | 有啥用 |
|---|---|---|---|
| `id` | run-document 主键 ID | 由每篇文档注册时生成 UUID | 作为单文档处理实例的稳定 ID |
| `run_id` | 所属 run ID | 来自 `mining_runs.id` | 指明该记录属于哪轮 run |
| `document_key` | 文档逻辑身份键 | 由相对路径等生成 | 用于在本轮 run 中识别是哪篇逻辑文档 |
| `raw_content_hash` | 文档原始内容哈希 | 来自 ingest 阶段 | 用于判断文档原始内容是否变化 |
| `normalized_content_hash` | 文档归一化内容哈希 | 由 Mining 归一化后得到 | 用于 shared snapshot 和 NEW/UPDATE/SKIP 判定 |
| `action` | 本轮对该文档的动作 | 由与历史 document 对比后计算，如 NEW、UPDATE、SKIP、REMOVE | 决定下游 build merge 语义 |
| `status` | 该文档在 run 中的处理状态 | 由 tracker 在处理过程中维护 | 支撑断点续跑和错误定位 |
| `document_id` | 正式逻辑文档 ID | 文档 commit 成功后回写 | 把运行态文档记录连到资产文档 |
| `document_snapshot_id` | 正式 snapshot ID | select/create snapshot 成功后回写 | 把运行态文档记录连到资产快照 |
| `error_message` | 文档级错误信息 | 文档处理失败时写入 | 用于精准定位失败文档原因 |
| `started_at` | 文档开始处理时间 | 文档进入 processing 时写入 | 用于单文档耗时统计 |
| `finished_at` | 文档处理结束时间 | committed / failed / skipped 时写入 | 用于状态收口 |
| `metadata_json` | 文档附加元数据 | 由运行过程补充 | 可记录恢复信息、上下文等 |

---

## 3.4 `mining_run_stage_events`

阶段事件流水表，既支持文档级阶段，也支持 run 级阶段。

| 字段 | 定义 | 怎么获取 | 有啥用 |
|---|---|---|---|
| `id` | stage event 主键 ID | 由 tracker 在开始阶段时生成 UUID | 作为一条阶段事件的稳定 ID |
| `run_id` | 所属 run ID | 来自 `mining_runs.id` | 让事件挂到整轮 run |
| `run_document_id` | 所属 run-document ID，可空 | 文档级阶段时写入；run 级阶段为空 | 区分这是文档级还是 run 级事件 |
| `stage` | 阶段名 | 由调用方显式传入，如 parse、assemble_build | 表示当前执行到哪个阶段 |
| `status` | 阶段事件状态 | start / end / fail 时分别写 started、completed、failed、skipped | 记录阶段生命周期 |
| `duration_ms` | 阶段耗时毫秒 | 在结束阶段时由 tracker 计算 | 用于性能分析和瓶颈定位 |
| `output_summary` | 阶段输出摘要 | 由调用方在结束阶段时传入，如 `34 units` | 快速查看阶段产出 |
| `error_message` | 阶段错误信息 | 阶段失败时写入 | 用于细粒度排错 |
| `created_at` | 事件创建时间 | 写入事件时记录当前时间 | 用于阶段顺序和时序分析 |
| `metadata_json` | 阶段附加信息 | 由 tracker 或调用方补充 | 用于扩展记录上下文 |

---

## 4. agent_llm_runtime

## 4.1 库职责

`agent_llm_runtime` 是统一 LLM 运行态库，负责：

- prompt template
- llm task
- request
- attempt
- result
- event

Mining 和 Serving 都通过 LLM Runtime 间接使用它，而不是自己各建一套调用日志表。

---

## 4.2 `agent_llm_prompt_templates`

Prompt 模板表，定义可复用的模板版本。

| 字段 | 定义 | 怎么获取 | 有啥用 |
|---|---|---|---|
| `id` | 模板主键 ID | 注册模板时生成 UUID | 作为模板记录稳定主键 |
| `template_key` | 模板业务键 | 由调用方定义，如 `mining-question-gen`、`serving-planner` | 作为跨系统引用模板的核心名字 |
| `template_version` | 模板版本号 | 由注册方显式指定 | 允许同一模板多版本并存 |
| `purpose` | 模板用途说明 | 由模板注册内容填写 | 便于人类理解模板作用 |
| `system_prompt` | system prompt 文本 | 由模板定义提供 | 给模型设定全局行为边界 |
| `user_prompt_template` | user prompt 模板文本 | 由模板定义提供 | 运行时按输入参数渲染 |
| `expected_output_type` | 期望输出类型 | 由模板定义指定，受约束为 json_object/json_array/text | 指导后续解析和校验流程 |
| `output_schema_json` | 输出 schema | 由模板定义写 JSON Schema 或结构说明 | 用于校验 LLM 输出是否符合预期 |
| `status` | 模板状态 | 由模板管理流程维护，如 draft、active、archived | 控制模板是否可正式使用 |
| `created_at` | 模板创建时间 | 注册模板时写入 | 用于审计和版本排序 |
| `metadata_json` | 模板附加元数据 | 由注册方补充 | 记录说明、兼容信息等 |

---

## 4.3 `agent_llm_tasks`

LLM 任务表，是运行时任务队列与状态机的核心。

| 字段 | 定义 | 怎么获取 | 有啥用 |
|---|---|---|---|
| `id` | task 主键 ID | 提交 LLM 任务时生成 UUID | 作为整次 LLM 调用单元的稳定 ID |
| `caller_domain` | 调用域 | 由调用方写入，如 mining、serving | 区分是哪个子系统发起了任务 |
| `pipeline_stage` | 调用阶段 | 由调用方写入，如 retrieval_units、planner | 用于审计和分流 |
| `idempotency_key` | 幂等键 | 由调用方按需生成 | 用于避免重复提交相同任务 |
| `status` | 任务状态 | 由 worker 和 runtime 维护，如 queued、running、succeeded | 是任务调度与观测的主状态字段 |
| `priority` | 调度优先级 | 提交任务时给定或使用默认值 | 控制队列处理先后 |
| `available_at` | 可领取时间 | 调度器或提交方写入 | 支撑延迟执行和重试回退 |
| `lease_expires_at` | 当前租约到期时间 | worker claim 任务时写入 | 避免任务被永久占用 |
| `attempt_count` | 已尝试次数 | 每次 attempt 时增加 | 用于控制重试和监控失败情况 |
| `max_attempts` | 最大尝试次数 | 任务提交时设定或默认 3 | 控制是否进入 dead letter |
| `created_at` | 任务创建时间 | 提交时写入 | 用于审计和调度排序 |
| `updated_at` | 最近更新时间 | 任务状态变化时更新 | 用于活跃性判断 |
| `started_at` | 任务开始执行时间 | 第一次真正执行时写入 | 用于耗时统计 |
| `finished_at` | 任务结束时间 | 成功、失败、取消时写入 | 用于生命周期收口 |
| `metadata_json` | 任务附加元数据 | 由调用方或 runtime 补充 | 可存储业务上下文、trace 信息等 |

---

## 4.4 `agent_llm_requests`

LLM 请求表，记录一次 task 对应的实际模型请求构造。

| 字段 | 定义 | 怎么获取 | 有啥用 |
|---|---|---|---|
| `id` | request 主键 ID | 创建 request 时生成 UUID | 作为具体请求对象的稳定 ID |
| `task_id` | 所属 task ID | 来自 `agent_llm_tasks.id` | 把 request 挂到任务上 |
| `provider` | 模型提供方 | 由 runtime 配置或调用方指定 | 区分不同模型服务 |
| `model` | 具体模型名 | 由 runtime 配置或请求参数确定 | 用于审计、路由和问题排查 |
| `prompt_template_key` | 使用的模板 key | 若使用模板调用则写模板名 | 让 request 可追溯到模板 |
| `messages_json` | 最终 messages 内容 | 由模板渲染或直接消息调用构造 | 是发给模型的消息序列快照 |
| `input_json` | 模板输入参数 | 由调用方提交 | 用于回溯模板渲染时的输入 |
| `params_json` | 模型参数 | 由 runtime 组装，如温度、超时等 | 用于回放和调优 |
| `expected_output_type` | 期望输出类型 | 从模板或请求指定值继承 | 驱动结果解析逻辑 |
| `output_schema_json` | 输出结构约束 | 从模板或请求带入 | 解析与校验结果时使用 |
| `created_at` | request 创建时间 | 写 request 时记录 | 用于审计和排序 |
| `metadata_json` | request 附加元数据 | 由调用方或 runtime 补充 | 记录 request 级额外上下文 |

---

## 4.5 `agent_llm_attempts`

LLM 尝试表，记录某个 task / request 的每次实际调用尝试。

| 字段 | 定义 | 怎么获取 | 有啥用 |
|---|---|---|---|
| `id` | attempt 主键 ID | 每次真正调用模型时生成 UUID | 作为一次实际尝试的稳定 ID |
| `task_id` | 所属 task ID | 来自 `agent_llm_tasks.id` | 指明属于哪个任务 |
| `request_id` | 所属 request ID | 来自 `agent_llm_requests.id` | 指明尝试的是哪份请求构造 |
| `attempt_no` | 第几次尝试 | 由 runtime 递增计算 | 区分重试序列 |
| `status` | 尝试状态 | 由调用结果更新，如 running、succeeded、timeout | 记录单次尝试的结局 |
| `raw_output_text` | 模型原始文本输出 | 由 provider 返回后保存 | 供解析、调试和审计 |
| `raw_response_json` | 原始响应 JSON | 由 provider 返回的完整响应序列化保存 | 用于深度排错和成本分析 |
| `error_type` | 错误类型 | 调用失败时由 runtime 归类 | 便于统计不同错误分布 |
| `error_message` | 错误信息 | 调用失败时写入 | 便于快速排错 |
| `prompt_tokens` | prompt token 数 | 从 provider 响应里提取 | 用于成本统计 |
| `completion_tokens` | completion token 数 | 同上 | 用于成本统计 |
| `total_tokens` | 总 token 数 | 同上或由前两者相加 | 用于成本汇总 |
| `latency_ms` | 本次调用耗时毫秒 | 由 runtime 计算 | 用于性能分析 |
| `started_at` | 尝试开始时间 | 真正调用模型前写入 | 用于耗时统计 |
| `finished_at` | 尝试结束时间 | 收到结果或失败时写入 | 生命周期收口 |
| `metadata_json` | attempt 附加元数据 | 由 runtime 补充 | 记录 provider 特定信息等 |

---

## 4.6 `agent_llm_results`

LLM 结果表，记录任务最终解析出的结构化结果。

| 字段 | 定义 | 怎么获取 | 有啥用 |
|---|---|---|---|
| `id` | result 主键 ID | 生成最终结果时创建 UUID | 作为最终结果对象稳定 ID |
| `task_id` | 所属 task ID | 来自 `agent_llm_tasks.id` | 指明是哪项任务的最终结果 |
| `attempt_id` | 来源 attempt ID | 来自成功或最终尝试的 `agent_llm_attempts.id` | 能回溯是哪次尝试产出了结果 |
| `parse_status` | 解析状态 | 由解析器根据输出校验结果给出 | 区分无需解析、解析成功、schema 不合法等 |
| `parsed_output_json` | 解析后的结构化结果 | 由 parser 从模型输出中解析得到 | 这是上层业务通常真正消费的结果 |
| `text_output` | 纯文本输出 | 若任务期望 text 或保留原文本则写入 | 支撑非结构化调用和人工查看 |
| `parse_error` | 解析错误信息 | 解析失败时写入 | 便于排查输出不符合预期的问题 |
| `validation_errors_json` | 校验错误列表 | schema 校验失败时写入 JSON 数组 | 提供结构化的校验问题信息 |
| `created_at` | 结果创建时间 | 生成 result 时写入 | 用于审计与排序 |
| `metadata_json` | result 附加元数据 | 由 runtime 补充 | 可记录后处理信息 |

---

## 4.7 `agent_llm_events`

LLM 事件流水表，用于记录任务生命周期中的关键事件。

| 字段 | 定义 | 怎么获取 | 有啥用 |
|---|---|---|---|
| `id` | event 主键 ID | 记录事件时生成 UUID | 作为事件稳定 ID |
| `task_id` | 所属 task ID | 来自 `agent_llm_tasks.id` | 把事件挂到具体任务上 |
| `event_type` | 事件类型 | 由 runtime 在关键状态变化时写入，如 submitted、claimed、retried | 描述任务发生了什么 |
| `message` | 事件说明 | 由 runtime 或调用方补充文本 | 便于人类快速理解事件 |
| `metadata_json` | 事件附加元数据 | 由 runtime 补充 | 记录结构化上下文 |
| `created_at` | 事件发生时间 | 写事件时记录 | 用于完整还原时序 |

---

## 5. 一句话索引

为了便于快速查阅，可以把三库理解成三层：

### `asset_core`

- 管正式知识资产
- Serving 只读这里
- 核心主线：`document -> snapshot -> segment / retrieval_unit -> build -> release`

### `mining_runtime`

- 管 Mining 执行过程
- 只记录 run、文档状态、阶段事件
- 不直接给 Serving 用

### `agent_llm_runtime`

- 管 LLM 模板、任务、请求、尝试、结果、事件
- 给 Mining / Serving 统一提供 LLM 调用底座
- 不直接存正式知识真相

---

## 6. 最终结论

当前三库的设计分工很明确：

- `asset_core` 存“最终被 Serving 消费的正式知识视图”
- `mining_runtime` 存“Mining 是怎么跑出来的过程态”
- `agent_llm_runtime` 存“LLM 是怎么被调用并产出结果的运行态”

如果从字段层面抓主干，最关键的几个字段是：

- `asset_documents.document_key`
- `asset_document_snapshots.normalized_content_hash`
- `asset_raw_segments.id`
- `asset_retrieval_units.source_segment_id`
- `asset_build_document_snapshots.selection_status`
- `asset_publish_releases.status`
- `mining_runs.status`
- `mining_run_documents.action`
- `agent_llm_tasks.status`
- `agent_llm_results.parsed_output_json`

它们分别决定了：

- 谁是同一逻辑文档
- 哪些内容可复用为同一 snapshot
- 原始片段如何被唯一标识
- retrieval unit 如何回到 raw segment
- build 当前选中了哪些 snapshot
- 哪个 release 当前生效
- mining run 当前状态如何
- 文档在本轮 run 中如何处理
- llm task 当前执行到哪
- llm 最终给了什么结构化结果

