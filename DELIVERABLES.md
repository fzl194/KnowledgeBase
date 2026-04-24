# CoreMasterKB v2 各模块交付件定义

> 创建时间：2026-04-24
> 状态：讨论稿，待管理员决策
> 前提：新成员加入，分别承担 Mining 和 Serving 的演进开发

---

## 一、总体原则

### 1.1 热插拔算子架构

每个 Pipeline 阶段定义一个算子接口（Protocol / ABC），具体实现可替换。
当前已有算子接口的阶段：

| 阶段 | 模块 | 算子接口 | 已有实现 |
|------|------|---------|---------|
| S2 Parse | Mining | `DocumentParser` Protocol | `MarkdownParser`, `PlainTextParser`, `PassthroughParser` |
| S4 Enrich | Mining | `Enricher` Protocol（含 `enrich_batch`） | `RuleBasedEnricher` |
| S4 Enrich（子算子） | Mining | `EntityExtractor` Protocol | `RuleBasedEntityExtractor` |
| S4 Enrich（子算子） | Mining | `RoleClassifier` Protocol | `DefaultRoleClassifier` |
| S6 Retrieval Units | Mining | `QuestionGenerator` Protocol | `LlmQuestionGenerator`（已实现，通过 llm_service 调用） |
| Recall | Serving | `Retriever` ABC | `FTS5BM25Retriever` |
| Rerank | Serving | `Reranker` | `ScoreReranker` |
| Query Plan | Serving | `PlannerProvider` Protocol | `RulePlannerProvider`, `LLMPlannerProvider`（已实现） |
| Query Normalize | Serving | `QueryNormalizer`（LLM+rule 双层） | 已实现 `anormalize()` |

**缺少算子接口的阶段（v2 需补齐）：**

| 阶段 | 需要的接口 |
|------|-----------|
| S3 Segment | `Segmenter` Protocol |
| S5 Relations | `RelationBuilder` Protocol |
| S6 Embedding | `EmbeddingGenerator` Protocol（新增） |

### 1.2 协同开发结构

```
CoreMasterKB/
├── knowledge_mining/          ← 管理员维护（v1.1 现有）
├── knowledge_mining_v2/       ← Mining 负责人 A 独立开发
├── agent_serving/             ← 管理员维护（v1.1 现有）
├── agent_serving_v2/          ← Serving 负责人 B 独立开发
├── llm_service/               ← 管理员维护
├── databases/                 ← 共享 SQL schema（弱合同）
│   ├── asset_core/schemas/
│   ├── mining_runtime/schemas/
│   └── agent_llm_runtime/schemas/
└── shared/                    ← 共享数据类定义（待建）
    └── contracts/             ← 枚举、模型基类
```

**接口合同层（管理员维护）：**
- `databases/` 下的 SQL schema —— Mining 写、Serving 读的表结构
- 共享枚举值：`block_type`（9 种）、`semantic_role`（11 种）、`unit_type`（4 种→v2 扩展）、`relation_type`（4 种→v2 扩展 RST）
- `asset_retrieval_embeddings` 表结构 —— Mining 写向量、Serving 读向量

### 1.3 当前 v1.1 代码规模

| 模块 | 源码文件 | 测试文件 | 核心数据 |
|------|---------|---------|---------|
| Mining | 20 个 .py | 3 个 | 9 阶段 Pipeline、11 表 asset_core、3 表 mining_runtime |
| Serving | 31 个 .py | 13 个 | FTS5 BM25 + Graph BFS、ContextPack 组装 |
| LLM Service | 9 个 .py | 17 个（79 用例） | 6 表 agent_llm_runtime、双模式调用 |

---

## 二、Mining Pipeline 交付件

### 2.1 各阶段现状 → v2 目标

#### S1 Ingest（文件采集）

**现状：** `ingestion/` 递归扫描 .md/.txt/.html/.pdf/.docx，计算 raw_content_hash + normalized_content_hash，跳过未变文件。

**v2 目标：** 保持不变。Ingest 是纯 I/O 操作，不涉及理解。

---

#### S2 Parse（文档解析）

**现状：** `DocumentParser` Protocol + 工厂模式。`MarkdownParser`（markdown-it AST）、`PlainTextParser`、`PassthroughParser`。输出 `SectionNode` 树，保留 heading/table/list/code 结构。

**v2 目标：** 保持不变。已有算子接口，可热插拔。

---

#### S3 Segment（结构化分块）

**现状：** 无 Protocol。硬编码实现：heading 独立成段，paragraph 连续合并（无 token 上限），9 种 `block_type` + 11 种 `semantic_role`。

**v2 交付件：**

| 项 | 说明 |
|----|------|
| `Segmenter` Protocol | 定义 `segment(tree, profile) → list[RawSegmentData]` |
| 当前实现迁移 | 将现有逻辑包装为 `StructuralSegmenter`（默认算子） |
| 新增算子 slot | 预留 `SemanticSegmenter`（基于 embedding 相似度断点），不要求 v2 实现 |

**事实依据：** EVO-12（多 paragraph 合并无上限）和 EVO-23（语义分块）来自 `.dev/2026-04-22-v12-evolution-backlog.md`。

---

#### S4 Enrich（内容增强）

**现状：** `Enricher` Protocol 已定义（含 `enrich_batch`）。唯一实现 `RuleBasedEnricher`：
- `RuleBasedEntityExtractor`：正则提取命令和网元实体
- `DefaultRoleClassifier`：基于关键词的语义角色分类（11 种）
- table metadata 解析：列数、是否有参数列

**v2 交付件：**

| 项 | 说明 |
|----|------|
| `LlmEnricher` 算子 | 一次 LLM 调用返回：entities[] + semantic_role + document_type + confidence。使用 `mining-segment-understanding` 模板 |
| batch 模式 | 利用 `enrich_batch()` 接口，一次提交多个 segments 给 LLM，降低 HTTP 往返 |
| 降级策略 | LLM 不可用时 fallback 到 `RuleBasedEnricher`，与当前 `LlmQuestionGenerator` 的降级模式一致 |
| document_type 填充 | 基于文档内容自动分类（command / feature / procedure / troubleshooting / constraint），替代当前始终为 NULL 的状态 |

**事实依据：** `.dev/2026-04-22-v12-next-wave-implementation-plan-codex.md` 第 4 节明确规划了 LLM Enrich 接入主链。EVO-04（document_type 自动分类）来自 backlog。

---

#### S5 Relations（关系构建）

**现状：** 无 Protocol。硬编码 4 种结构关系：
- `previous` / `next`：相邻段落（distance=1）
- `same_section`：同一 section 下所有段落两两建关系（**无距离限制，O(n²)**）
- `section_header_of`：标题→内容
- `same_parent_section`：同一父级 section

写入 `asset_raw_segment_relations` 表（weight / confidence / distance 三维评估）。

**v2 交付件：**

| 项 | 说明 |
|----|------|
| `RelationBuilder` Protocol | 定义 `build(segments, snapshot_id) → list[SegmentRelationData]` |
| 当前实现迁移 | 包装为 `StructuralRelationBuilder`（默认算子），补齐 same_section distance ≤ 5 限制 |
| **`DiscourseRelationBuilder` 算子** | RST 语篇关系提取。24 种关系标签空间（elaboration / cause_effect / contrast / condition / temporal / background / summary 等），LLM 零样本提取 |
| Pipeline 编排 | run.py 中按开关注册：结构关系算子（必跑）+ 语篇关系算子（LLM 可用时追加） |

**同步合同：** Mining 写入的 RST `relation_type` 值，Serving 的 `GraphExpander` 自动消费（因为 GraphExpander 遍历时不过滤 relation_type，或仅按 `relation_types` 参数过滤）。

**事实依据：** `.dev/2026-04-22-v12-evolution-backlog.md` EVO-05（same_section 距离限制）和 EVO-17~19（语篇关系提取）。`README.md` 中 relations 部分明确提到 "v1.2: 24 种 RST 语义关系"。

---

#### S6 Retrieval Units（检索单元构建）

**现状：** 产出 4 种 unit_type：

| unit_type | 生成方式 | 数量（41 文档真实数据） |
|-----------|---------|---------------------|
| `raw_text` | 1:1 映射 segment | 711 |
| `contextual_text` | section 路径前缀 + 内容 | 349 |
| `entity_card` | 聚合同一实体引用 | 119 |
| `generated_question` | LLM 生成（`LlmQuestionGenerator`，通过 llm_service submit+poll） | 0（v1.1 未启用 LLM 时） |

同时产出：`search_text`（FTS5 索引，jieba 预分词）、`facets_json`（过滤维度）、`source_refs_json`（溯源链）。

**v2 交付件：**

| 项 | 说明 |
|----|------|
| **`EmbeddingGenerator` 算子** | 对每个 retrieval_unit 生成 BGE-M3 多语言向量，写入 `asset_retrieval_embeddings` 表（表已存在）。与 Serving 的 `VectorRetriever` 配对 |
| **`ContextualRetriever` 算子** | Anthropic Contextual Retrieval 模式：LLM 为每个 chunk 生成上下文前缀，拼接到原始文本前。产出新 unit_type 或增强现有 `contextual_text` |
| `generated_question` 主链启用 | 当前 `LlmQuestionGenerator` 已实现，需确认在 llm_service 正常运行时自动启用 |

**同步合同：** Mining 写入的 embedding 向量（模型=BGE-M3），Serving 的 `VectorRetriever` 必须用同一模型读取。

**事实依据：** `asset_retrieval_embeddings` 表已在 SQL schema 中定义（`databases/asset_core/schemas/001_asset_core.sqlite.sql`）。`.dev/2026-04-22-serving-retrieval-evolution-notes.md` 中研究了 BGE-M3 + cosine 相似度方案。EVO-21（父子层级分块）和 EVO-22（上下文增强检索）来自 backlog。

---

#### S7 Snapshot（共享快照）

**现状：** 三层模型：document（逻辑身份）→ snapshot（内容快照，SHA256 去重）→ link（映射）。归一化策略：CRLF→LF → 去尾空白 → 去空行 → SHA256。

**v2 目标：** 保持不变。补齐 UPDATE 场景旧 segments 清理（EVO-07）。

---

#### S8 Build（构建）

**现状：** 全量/增量两种模式。incremental 模式对比新旧快照 hash，标记 NEW/UPDATE/SKIP。`validate_build()` 当前为空操作。

**v2 目标：** 补齐：空 build 拦截、REMOVE 语义（检测被删除文件）、snapshot 有效性检查（EVO-02, EVO-06）。

---

#### S9 Release（发布）

**现状：** staging → active → retired 状态流转。同一 channel 只有一个 active release。Serving 通过 `asset_publish_releases` 表读取。

**v2 目标：** 保持不变。

---

### 2.2 Mining v2 核心交付件清单

| # | 交付件 | 性质 | 依赖 |
|---|--------|------|------|
| M1 | Pipeline 算子框架 | S3/S5 补齐 Protocol，run.py 改为算子注册表编排 | 无 |
| M2 | `LlmEnricher` 算子 | 替换/增强 S4 Enrich 阶段 | LLM Service 模板注册 bug 修复 |
| M3 | `DiscourseRelationBuilder` 算子 | S5 阶段新增 RST 语篇关系 | LLM Service |
| M4 | `EmbeddingGenerator` 算子 | S6 阶段向量化 | BGE-M3 模型部署 |
| M5 | `ContextualRetriever` 算子 | S6 阶段上下文增强 | LLM Service |
| M6 | same_section distance 限制 | S5 阶段补丁 | 无 |
| M7 | Build validate 真校验 + REMOVE 语义 | S8 阶段补丁 | 无 |

---

## 三、Serving Pipeline 交付件

### 3.1 各阶段现状 → v2 目标

#### Query Normalize（查询理解）

**现状：** `QueryNormalizer` 已实现双层架构：
- LLM 路径：通过 `llm_service` 的 `execute()` 同步调用 `serving-query-understanding` 模板
- Rule 路径：正则命令检测 + scope 提取 + intent 分类 + jieba 分词

**问题：** `/search` 主链当前调用同步 `normalize()`，不走 `anormalize()`。用户请求感知不到 LLM。

**v2 交付件：**

| 项 | 说明 |
|----|------|
| 主链切换 | `/search` 改为调用 `anormalize()` |
| 配置开关 | `SERVING_ENABLE_LLM_NORMALIZER` 环境变量 |
| Debug 观测 | ContextPack.debug 中标记实际 provider（llm / rule） |

**事实依据：** `.dev/2026-04-22-v12-next-wave-implementation-plan-codex.md` 第 3 节完整列出了 Serving 主链启用的必做项和验收标准。

---

#### Query Plan（查询规划）

**现状：** `PlannerProvider` Protocol 已定义。`LLMPlannerProvider` 已实现（通过 `LLMRuntimeClient`），但 `/search` 主链使用 `RulePlannerProvider`。

`QueryPlan` 模型已预留：
- `RetrieverConfig.enabled_retrievers`：默认 `["fts_bm25"]`
- `RetrieverConfig.fusion_method`：默认 `"identity"`（预留 `"rrf"`）
- `RerankerConfig.reranker_type`：默认 `"score"`（预留 `"llm"` / `"cross_encoder"`）

**v2 交付件：**

| 项 | 说明 |
|----|------|
| 主链切换 | `/search` 改为调用 `abuild_plan()` |
| 配置开关 | `SERVING_ENABLE_LLM_PLANNER` 环境变量 |
| enabled_retrievers 扩展 | 默认改为 `["fts_bm25", "vector"]`（vector 算子就绪后） |
| fusion_method 切换 | 从 `"identity"` 改为 `"rrf"` |

---

#### Recall（多路召回）

**现状：** `Retriever` ABC 已定义（`retrieve(query, plan, scope) → list[Candidate]`）。唯一实现 `FTS5BM25Retriever`：
- jieba 中文分词 → FTS5 OR 查询 → BM25 评分
- 范围约束：`snapshot_id IN (...)`
- LIKE fallback：FTS5 失败时降级
- 召回倍率：top N×5

`RetrieverManager` 已实现多路管理框架，按 `QueryPlan.retriever_config` 选择激活哪些 Retriever。

**v2 交付件：**

| 项 | 说明 |
|----|------|
| **`VectorRetriever` 算子** | 读取 `asset_retrieval_embeddings` 表，cosine 相似度匹配。与 Mining 的 `EmbeddingGenerator` 配对（同一模型 BGE-M3） |
| `GraphExpander` 消费 RST | 当前已实现 BFS 遍历。Mining 端新增 RST 关系类型后自动扩展到 Graph 遍历，无需额外改造 |

**同步合同：** `asset_retrieval_embeddings` 表 Mining 写、Serving 读。embedding 模型必须一致。

---

#### Fusion（多路融合）

**现状：** `RetrieverManager` 中 `fusion_method = "identity"`（直通，不做融合）。

**v2 交付件：**

| 项 | 说明 |
|----|------|
| **RRF Fusion** | Reciprocal Rank Fusion，k=60。多路召回结果合并后统一排序。在 `RetrieverManager` 中实现 |

**事实依据：** `.dev/2026-04-22-serving-retrieval-evolution-notes.md` 中记录了标准 RAG Pipeline 工业标准：`BM25 + Vector + Graph → RRF k=60 → Cross-Encoder Rerank`。`RetrieverConfig.fusion_method` 已预留 `"rrf"` slot。

---

#### Rerank（重排序）

**现状：** `Reranker` 基类已定义。唯一实现 `ScoreReranker`：去重 → heading 降权 → 规则打分 → 截断。`RerankerConfig.reranker_type` 已预留 `"llm"` / `"cross_encoder"` slot。

**v2 交付件：**

| 项 | 说明 |
|----|------|
| **`CrossEncoderReranker` 算子** | 基于 BGE-reranker-v2-m3 精排。替换 `ScoreReranker` 作为默认 |
| `LLMRerankerProvider` | 已有 slot（`llm_providers.py` 中 `LLMRerankerProvider` 类已存在，标注为 "future slot"），可选择性实现 |

**事实依据：** `.dev/2026-04-22-serving-retrieval-evolution-notes.md` 明确推荐 BAAI/bge-reranker-v2-m3 作为自部署中文精排模型，Cross-Encoder 是单次最大提升环节（+7.6pp）。

---

#### Assemble（结果组装）

**现状：** `ContextAssembler` 组装 seed（BM25 命中）+ context（source_refs 下钻）+ support（Graph BFS 扩展）为 `ContextPack`。

**v2 目标：** 保持不变。Mining 端新增的 embedding 和 RST 关系自动被消费。

---

### 3.2 Serving v2 核心交付件清单

| # | 交付件 | 性质 | 依赖 |
|---|--------|------|------|
| S1 | Normalizer + Planner 主链启用 | 挂进 /search，加开关 | LLM Service 可用 |
| S2 | **`VectorRetriever` 算子** | 读取 embedding 做向量召回 | Mining M4（EmbeddingGenerator）|
| S3 | **RRF Fusion** | 多路召回结果合并 | S2 完成 |
| S4 | **`CrossEncoderReranker` 算子** | 精排替换 ScoreReranker | BGE-reranker-v2-m3 模型部署 |
| S5 | RST 关系消费验证 | GraphExpander + RST 关系的 E2E 验证 | Mining M3（DiscourseRelationBuilder）|
| S6 | LLM on/off/timeout 集成测试 | 三种场景的 API 集成测试 | S1 |

---

## 四、LLM Service 交付件（管理员维护）

| # | 交付件 | 说明 | 优先级 |
|---|--------|------|--------|
| L1 | 修复模板注册 500 错误 | 当前 POST /api/v1/templates 返回 500，阻塞 Mining/Serving 的模板注册 | HIGH |
| L2 | 批量 API | 一次提交多个任务，减少 HTTP 往返 | MEDIUM |
| L3 | 流式输出（SSE） | 逐 token 返回 | MEDIUM |
| L4 | 成本统计 | token 用量聚合 + 费用追踪 | LOW |

---

## 五、Mining 与 Serving 同步合同

以下是对两个模块的硬性约束，任何一方修改需通知另一方：

### 5.1 SQL Schema（`databases/asset_core/schemas/`）

| 表 | Mining 操作 | Serving 操作 | v2 变更 |
|----|-----------|-------------|--------|
| `asset_raw_segments` | 写 | 读（source drill-down） | 无 |
| `asset_raw_segment_relations` | 写 | 读（Graph BFS） | 新增 RST relation_type 值 |
| `asset_retrieval_units` | 写 | 读（FTS5 + 主召回） | 可能新增 unit_type |
| `asset_retrieval_embeddings` | 写（M4: EmbeddingGenerator） | 读（S2: VectorRetriever） | v2 核心新增 |
| `asset_builds` | 写 | 读（Resolve Build） | 无 |
| `asset_publish_releases` | 写 | 读（Active Release） | 无 |

### 5.2 共享枚举

当前枚举值定义在 `knowledge_mining/mining/models.py`（frozenset 常量）。

v2 需扩展：

| 枚举 | 当前值 | v2 新增 |
|------|-------|--------|
| `relation_type` | previous, next, same_section, same_parent_section, section_header_of | +24 种 RST 标签（elaboration, cause_effect, contrast, condition 等） |
| `unit_type` | raw_text, contextual_text, entity_card, generated_question | 可能新增 contextual_enhanced |
| `semantic_role` | 11 种 | 可能由 LLM Enricher 调整 |

### 5.3 Embedding 对

Mining 的 `EmbeddingGenerator` 和 Serving 的 `VectorRetriever` 必须使用同一 embedding 模型。当前规划为 **BGE-M3**（多语言、支持中文）。

---

## 六、统一查询计划（v2 目标态）

```
用户查询
  ↓
[QueryNormalizer]           LLM 可用 → LLM understand；不可用 → rule fallback
  ↓                           输出：NormalizedQuery（intent, entities, keywords, scope）
[PlannerProvider]           LLM 可用 → LLM plan；不可用 → rule plan
  ↓                           输出：QueryPlan（RetrieverConfig, RerankerConfig）
[RetrieverManager]
  ├── FTS5BM25Retriever      关键词召回（已有）
  ├── VectorRetriever         向量召回（v2 新增）
  └── GraphExpander           关系图扩展（已有，自动消费 RST）
  ↓
[RRF Fusion]                k=60 多路合并（v2 新增）
  ↓
[CrossEncoderReranker]      精排（v2 新增，替换 ScoreReranker）
  ↓
[ContextAssembler]          seed + context + support → ContextPack（已有）
  ↓
ContextPack
```

**对应数据流：**

Mining 产出 → Serving 消费的完整链路：

```
S6 EmbeddingGenerator → asset_retrieval_embeddings → S2 VectorRetriever
S6 raw_text units     → asset_retrieval_units_fts  → FTS5BM25Retriever
S5 Relations          → asset_raw_segment_relations → GraphExpander
S6 contextual_text    → asset_retrieval_units      → ContextAssembler
S5 RST Relations      → asset_raw_segment_relations → GraphExpander（自动扩展）
```

---

## 七、开发节奏建议

基于 `.dev/2026-04-22-v12-next-wave-implementation-plan-codex.md` 的核心判断：
> "不要横向铺新能力，先把已有能力挂进主链。"

建议分三步：

### 第一步：主链打通
- Mining：算子框架改造（M1）+ Build 补丁（M6, M7）
- Serving：Normalizer + Planner 挂进主链（S1）+ 集成测试（S6）
- LLM Service：修复模板注册（L1）
- **验收标准：** Mining 跑通 LLM enrich，Serving `/search` 真正调用 LLM

### 第二步：检索能力升级
- Mining：EmbeddingGenerator（M4）+ ContextualRetriever（M5）
- Serving：VectorRetriever（S2）+ RRF Fusion（S3）
- **验收标准：** 多路召回（BM25 + Vector）工作，RRF 融合可用

### 第三步：语义深度增强
- Mining：DiscourseRelationBuilder（M3）
- Serving：CrossEncoderReranker（S4）+ RST 消费验证（S5）
- **验收标准：** RST 关系出现在 Graph 扩展中，Cross-Encoder 精排生效

---

## 八、参考文档索引

| 文档 | 路径 | 说明 |
|------|------|------|
| v1.2 演进 Backlog | `.dev/2026-04-22-v12-evolution-backlog.md` | 逐阶段改进项（EVO-01 ~ EVO-27） |
| 下一波实施计划 | `.dev/2026-04-22-v12-next-wave-implementation-plan-codex.md` | Codex 对 Mining/Serving 主链启用的详细规划 |
| Serving 检索演进研究 | `.dev/2026-04-22-serving-retrieval-evolution-notes.md` | GraphRAG、RRF、Reranker 工业级研究 |
| Mining README | `knowledge_mining/README.md` | 14 节方案设计文档 |
| Serving README | `agent_serving/README.md` | 架构设计文档 |
| LLM Service README | `llm_service/README.md` | 13 节方案设计文档 |
| SQL Schema | `databases/asset_core/schemas/001_asset_core.sqlite.sql` | 11 表建表语句 |
| 总体架构 HTML | `docs/architecture/coremasterkb-v1.2-architecture.html` | 领导汇报版 |
