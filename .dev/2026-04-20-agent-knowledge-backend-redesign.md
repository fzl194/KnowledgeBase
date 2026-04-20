# Agent Knowledge Backend 重写设计草案

- 日期：2026-04-20
- 作者：Codex
- 状态：讨论草案
- 目的：沉淀当前关于 Mining 后半段与 Serving 重写方向的统一思想，后续用于给 Mining / Serving 两侧拆任务。

## 1. 核心判断

当前系统已经验证了一个重要前提：Mining 前三步是可以保留的。

1. 给定一个文件夹，递归发现文档。
2. 将 Markdown / TXT 等原始文档解析成结构块。
3. 将结构块切成 raw segment，并落入 raw 相关表。

问题主要出现在第四步之后：当前 canonical 化把“内容相同”当成了主要合并依据，这在知识库场景里风险很高。

典型例子是：

```text
该特性无告警信息。
```

这句话可能出现在很多不同特性的“告警信息”章节下。文本完全一样，但语义依赖所在章节、所在文档、所在特性。如果把它们合并成一个 canonical segment，这个 canonical 片段就会同时关联很多底层特性。查询时它既可能被错误召回，也很难解释它到底属于哪个业务对象。

因此，当前阶段不应该把“去重合并”放在主路径上。更合理的方向是：

```text
raw segment 是事实源
retrieval unit 是检索封装
relation 是上下文扩展机制
dedup / canonical 只是未来可选的辅助能力
```

## 2. 当前主路径建议

新的 Mining 主路径建议调整为：

```text
input folder
  -> raw_documents
  -> raw_segments
  -> raw_segment_relations
  -> retrieval_units
  -> optional embeddings / indexes
  -> publish active version
```

其中：

- `raw_documents`：保存原始文档级事实。
- `raw_segments`：保存从原文解析、切片得到的原始片段，是后续所有检索、引用、证据回溯的事实源。
- `raw_segment_relations`：保存 raw segment 之间的文档结构关系、邻接关系、解释关系、条件关系等，用于召回后的上下文扩展。
- `retrieval_units`：保存面向检索的索引单元。它不是去重结果，而是 raw segment / section / summary / generated question 等对象的检索视图。
- `embeddings / indexes`：后续可以接入向量库、全文索引、BM25、稀疏向量、重排模型等。

## 3. 为什么不用 canonical 作为主路径

当前 `asset_canonical_segments` / `asset_canonical_segment_sources` 的设计更像“归并后的知识片段”。它适合处理强等价内容，但不适合作为 M1 的主要检索单元。

主要问题：

| 问题 | 说明 | 影响 |
|---|---|---|
| 上下文依赖被削弱 | 相同文本在不同章节、不同特性下可能含义不同 | 容易误召回、误解释 |
| 合并依据过于单一 | 当前主要基于文本归一化 hash | 只能发现文本相同，不能判断语义等价 |
| 查询解释困难 | 一个 canonical 片段可能关联多个不同 raw 来源 | Agent 很难判断应该引用哪个来源 |
| 与未来复杂知识冲突 | 未来会有专家文档、方案文档、问答、PDF、Word 等 | 不能假设内容天然可以稳定归并 |

所以建议：

- 保留 canonical / dedup 代码，但 M1 主 pipeline 不调用。
- 不删除已实现代码，避免浪费已有工作。
- 后续如需去重，改成 `duplicate_groups` 一类的旁路能力，而不是替代 raw / retrieval unit 的主链路。

## 4. Raw Segment 的定位

`raw_segments` 是事实层，不是检索层。

它应该尽量忠实表达原文中一个片段的内容、结构位置和可回溯信息。它不应该承担过多“为了查询更好搜”的职责。

raw segment 需要保留的信息包括：

| 信息 | 说明 |
|---|---|
| 原始文本 | 来自文档解析和切片后的片段正文 |
| block_type | 段落、列表、表格、代码、引用等结构类型 |
| semantic_role | 参数说明、步骤、限制、示例、告警、描述等语义角色 |
| section_path | 片段所在章节路径 |
| entity_refs_json | Mining 尽可能抽取出的实体引用，如命令、特性、参数、指标等 |
| structure_json | 结构化残留信息，例如表格列、列表层级、代码语言等 |
| metadata_json | 低频、非主契约、暂不稳定的信息 |
| source offsets | 行号、字符偏移、页码等可回溯位置 |

关键原则：

```text
raw segment 尽量保存“原文事实”
不要为了某个查询意图把 raw segment 变成定制化答案材料
```

## 5. Relation 的定位

需要增加 raw segment 之间的关系表。这里的关系不是本体关系，也不是业务实体图，而是“文档片段之间的上下文关系”。

它主要服务于召回后的上下文扩展。

例如：

- 命中一个参数说明片段后，自动扩展到同章节的命令描述。
- 命中一个步骤后，扩展到前后步骤。
- 命中一个“该特性无告警信息”后，扩展到它所在的特性章节标题和父章节。
- 命中一个约束条件后，扩展到被约束的配置项。

建议表：

```sql
asset_raw_segment_relations
```

建议字段：

| 字段 | 说明 |
|---|---|
| id | 关系 ID |
| publish_version_id | 发布版本 |
| source_raw_segment_id | 起点 raw segment |
| target_raw_segment_id | 终点 raw segment |
| relation_type | 关系类型 |
| weight | 关系权重 |
| confidence | 关系置信度 |
| distance | 文档距离，例如相邻距离、章节距离 |
| metadata_json | 其他解释信息 |

M1 可支持的关系类型：

| relation_type | 说明 |
|---|---|
| previous | 前一个片段 |
| next | 后一个片段 |
| same_section | 同一章节 |
| same_parent_section | 同一父章节 |
| section_header_of | 某章节标题是某片段的标题上下文 |
| has_parameter | 描述片段包含参数说明 |
| has_example | 描述片段关联示例 |
| has_constraint | 描述片段关联约束 |
| has_procedure_step | 描述片段关联步骤 |
| has_troubleshooting | 描述片段关联排障信息 |
| references | 文本显式引用另一片段或实体 |
| elaborates | 进一步解释 |
| condition | 条件关系 |
| contrast | 对比或冲突候选关系 |

这些关系不要求 M1 全部做准。M1 最少应先做：

1. `previous`
2. `next`
3. `same_section`
4. `same_parent_section`
5. `section_header_of`

这样 Serving 至少可以从命中片段扩展出局部上下文。

## 6. Retrieval Unit 的定位

`retrieval_units` 是检索层，不是事实层，也不是去重层。

它的作用是：把 raw segment 或其他上层对象包装成适合搜索的文本单元。

一个 raw segment 可以对应多个 retrieval unit，例如：

| unit_type | 说明 |
|---|---|
| raw_text | 直接用 raw segment 文本检索 |
| contextual_text | 拼接章节路径、标题、实体、标签后的检索文本 |
| generated_question | 针对片段生成可能的问题 |
| summary | 对一个章节或多个片段生成摘要 |
| entity_card | 围绕一个实体聚合出来的检索卡片 |
| table_row | 从表格或列表中拆出来的行级检索单元 |

建议表：

```sql
asset_retrieval_units
```

建议字段：

| 字段 | 说明 |
|---|---|
| id | 检索单元 ID |
| publish_version_id | 发布版本 |
| unit_key | 稳定键，用于重建和幂等写入 |
| unit_type | raw_text / contextual_text / summary / generated_question 等 |
| target_type | raw_segment / section / document / entity / synthetic |
| target_id | 指向被封装对象的 ID |
| text | 返回给上层的主要文本 |
| search_text | 用于全文索引和 embedding 的检索文本 |
| title | 检索单元标题 |
| role | seed / context / support / summary 等角色 |
| facets_json | 动态过滤维度，例如领域、来源批次、用户上传标签 |
| entity_refs_json | 检索单元关联实体 |
| source_refs_json | 回溯来源，通常指向 raw segment / document |
| weight | 静态权重 |
| metadata_json | 其他扩展信息 |

M1 可以先做到“一段 raw segment 至少生成一个 contextual_text retrieval unit”。

例如 raw 文本是：

```text
该特性无告警信息。
```

如果它位于：

```text
业务感知 / 告警信息
```

那么 `search_text` 不应该只有原句，而应该类似：

```text
业务感知 告警信息 该特性无告警信息。
```

如果 Mining 抽取出了实体，也可以继续补充：

```text
特性: 业务感知。章节: 告警信息。正文: 该特性无告警信息。
```

这样可以降低短句、泛化句、指代句在检索中的歧义。

## 7. Serving 的新定位

Serving 不应该继续做“命令查询专用后端”。它应该是 Agent Skill 调用的通用知识库后台。

建议主流程：

```text
Agent Skill Request
  -> Query Understanding
  -> Retrieval Plan
  -> Multi-index Retrieval
  -> Candidate Fusion & Rerank
  -> Context Expansion
  -> ContextPack Assembly
  -> Agent / LLM
```

其中：

| 阶段 | 说明 |
|---|---|
| Query Understanding | 识别查询文本、核心实体、可能意图、过滤条件、追问需求 |
| Retrieval Plan | 选择 keyword / vector / entity / structure / relation 等检索策略 |
| Multi-index Retrieval | 同时使用 FTS、BM25、embedding、实体索引、结构过滤等 |
| Candidate Fusion & Rerank | 合并多路候选并重排 |
| Context Expansion | 基于 raw_segment_relations 扩展上下文 |
| ContextPack Assembly | 输出 Agent 可消费的上下文包 |

M1 不需要实现复杂 Planner，但接口和数据结构要留出来。

M1 的 QueryPlan 可以是规则生成：

```text
normalized query
  -> entities
  -> facets
  -> desired roles
  -> retrieval strategies
```

后续 M2 / M3 可以替换为 LLM 生成或 LLM 辅助生成。

## 8. 当前查询问题的解释

目前出现了一个典型问题：

```text
问：业务感知
能查到。

问：业务感知是啥
查不到。
```

这说明当前检索链路对自然语言问题的处理太弱，可能把“业务感知是啥”整体当成关键词，无法回退到核心实体“业务感知”。

新架构下应由 Query Understanding 处理这类问题：

| 原始问法 | 归一化核心 |
|---|---|
| 业务感知是啥 | 业务感知 |
| 业务感知是什么 | 业务感知 |
| 介绍一下业务感知 | 业务感知 |
| 业务感知有什么用 | 业务感知 |

M1 可以先用规则处理中文常见疑问后缀：

```text
是啥、是什么、什么意思、有啥用、有什么用、介绍一下、说明一下、怎么配置、如何配置
```

未来可以由 LLM 做 query rewrite 和意图识别。

## 9. Serving 输出应改成 ContextPack

当前输出里有太多 command / product / version / NE 等定制化字段，不适合作为通用 Agent Skill 后台。

建议改成通用 `ContextPack`。

顶层结构：

| 模块 | 说明 |
|---|---|
| query | 原始查询、归一化结果、识别出的实体、意图、过滤条件 |
| items | 返回给 Agent 的主要上下文片段 |
| relations | items 之间的上下文关系 |
| sources | 来源文档和位置 |
| issues | 检索过程中的风险、缺口、冲突、低置信提示 |
| suggestions | 可选追问或缩小范围建议 |
| debug | 可选调试信息，默认不面向最终 Agent 展示 |

`items` 建议字段：

| 字段 | 说明 |
|---|---|
| id | item ID |
| kind | raw_segment / retrieval_unit / section_summary / entity_card 等 |
| role | seed / context / support / summary / conflict_candidate |
| text | 给 Agent 使用的文本 |
| score | 综合得分 |
| block | block_type、semantic_role、structure 摘要 |
| source_id | 对应 sources 中的来源 ID |
| metadata | 扩展信息 |

`sources` 建议字段：

| 字段 | 说明 |
|---|---|
| id | source ID |
| document_key | 文档稳定键 |
| uri | 文档 URI |
| relative_path | 相对输入根目录的路径 |
| title | 文档标题 |
| file_type | md / txt / html / pdf / docx 等 |
| facets | 领域、来源批次、用户输入标签等动态信息 |
| location | section_path、line_start、line_end、page 等 |
| processing | 解析器、转换器、抽取版本等 |

`issues` 不应该写死成命令场景，而应该是通用风险类型：

| issue type | 说明 |
|---|---|
| no_result | 没有召回 |
| low_confidence | 召回置信度低 |
| ambiguous_scope | 查询范围不明确 |
| conflict_candidate | 可能存在冲突材料 |
| source_unparsed | 来源解析不完整 |
| partial_context | 只返回了局部上下文 |
| stale_index | 索引版本可能不是最新 |

## 10. LLM 在查询侧的角色

查询侧不能只靠写死规则。未来 Serving 可以引入 LLM，但 LLM 不应替代底层检索。

更合理的分工是：

| LLM 能力 | 作用 |
|---|---|
| query rewrite | 把自然语言问题改写成多个检索 query |
| intent extraction | 判断用户想查定义、配置、约束、故障、对比还是流程 |
| entity / facet extraction | 抽取实体和动态过滤条件 |
| retrieval planning | 选择 keyword / vector / structure / relation 等组合 |
| rerank | 对候选片段进行语义重排 |
| context compression | 将多个片段压缩成适合 Agent 使用的上下文 |
| answer drafting | 可选。默认建议由调用方 Agent 完成最终回答 |

第一版 Serving 可以不接 LLM，但接口要允许后续插入。

## 11. Embedding 与索引预留

第一版不需要完整向量库，但设计上要预留：

```text
EmbeddingProvider
VectorIndex
VectorRetriever
HybridRetriever
Reranker
```

embedding 的对象不建议直接是 raw segment，而应该优先是 retrieval unit。

原因：

- raw segment 是事实层，文本可能太短或缺上下文。
- retrieval unit 可以生成 contextual text，更适合 embedding。
- 同一 raw segment 可以有多个向量表示，例如原文、上下文化文本、摘要、生成问题。

未来可支持的向量存储：

| 存储 | 说明 |
|---|---|
| SQLite vec / sqlite-vss | 本地轻量验证 |
| FAISS / LanceDB | 单机向量检索 |
| Qdrant / Milvus | 服务化向量库 |
| pgvector | 与 PostgreSQL 集成 |

## 12. 与工业实践的对应关系

这套设计对应几类常见工业 RAG / Graph RAG 做法：

| 工业做法 | 对应到本项目 |
|---|---|
| Parent-child retrieval | retrieval unit 命中小片段，relation 扩展父章节或邻近片段 |
| Contextual Retrieval | `search_text` 拼接章节、实体、上下文后再索引 |
| Hybrid Search | FTS / BM25 / embedding / entity / structure 多路召回 |
| Reranking | 对多路候选做二次排序 |
| GraphRAG local search | 基于实体和关系扩展局部上下文 |
| GraphRAG global search | 后续可基于实体社区或主题摘要回答全局问题 |

需要注意：

```text
raw_segment_relations 不是本体图
entity graph / ontology graph 是未来另一层
```

二者可以关联，但不能混为一谈。

## 13. Mining 侧改造建议

Mining 下一步不建议继续强化 canonical，而应改为：

1. 保留 ingestion / parsing / segmentation。
2. 暂停默认调用 canonicalization。
3. 新增 raw segment relation 构建。
4. 新增 retrieval unit 构建。
5. 可选生成 FTS 索引。
6. 为 embedding 预留接口，但 M1 可不实现。

M1 最小实现：

| 能力 | 最小要求 |
|---|---|
| raw documents | 已有，继续保留 |
| raw segments | 已有，继续保留 |
| relations | 先做 previous / next / same_section / section_header_of |
| retrieval units | 每个 raw segment 至少一个 contextual_text unit |
| FTS | 对 retrieval_units.search_text 建全文索引 |
| canonical | 代码保留，但 pipeline 默认不调用 |

## 14. Serving 侧改造建议

Serving 下一步应以重写检索链路为主，不要继续在当前 command lookup 上补丁式扩展。

M1 最小实现：

| 模块 | 最小要求 |
|---|---|
| Query Understanding | 规则化识别核心 query、常见中文疑问后缀、简单实体 |
| QueryPlan | 保留结构，但由规则生成 |
| Keyword Retriever | 基于 retrieval_units.search_text 做 FTS / LIKE fallback |
| Relation Expander | 从命中 raw segment 扩展 previous / next / same_section / section_header_of |
| Context Assembler | 输出通用 ContextPack |
| Compatibility API | 如保留 `/command-usage`，内部也必须走通用检索链路 |

Serving 不应强依赖某个 JSON 字段一定存在。

更合理的顺序是：

1. 先用 query text 做全文召回。
2. 有 entity_refs_json 就加权，不存在也能查。
3. 有 facets_json 就过滤或加权，不存在也能查。
4. 有 relation 就扩展，没有 relation 就退回邻接或同 section。
5. 有 embedding 就混合召回，没有 embedding 就 keyword-only。

## 15. 表设计边界

当前不一定要立刻大改全部表，但需要明确边界：

| 表 / 对象 | 当前建议 |
|---|---|
| raw_documents | 保留，作为文档事实源 |
| raw_segments | 保留，作为片段事实源 |
| canonical_segments | 不作为 M1 主查询路径 |
| canonical_segment_sources | 不作为 M1 主查询路径 |
| raw_segment_relations | 建议新增 |
| retrieval_units | 建议新增 |
| embeddings | 预留，后续新增 |
| duplicate_groups | 预留，替代当前强 canonical 思路 |
| entities / entity_mentions | 预留，后续支持实体图和本体 |

## 16. 对“检索单元”的一句话定义

检索单元不是去重后的知识点。

它是为了让搜索系统更容易命中、排序和解释而构造出来的“索引视图”。

同一个 raw segment 可以有多个检索单元；多个 raw segment 也可以组成一个章节摘要检索单元。但最终引用和证据回溯必须能回到 raw segment 和 raw document。

## 17. 当前阶段建议的最终原则

1. raw segment 是事实源。
2. retrieval unit 是索引视图，不是 canonical。
3. relation 是上下文扩展机制，不是本体图。
4. canonical / dedup 降级为可选旁路能力。
5. Serving 面向 Agent Skill 输出 ContextPack，而不是输出命令专用结果。
6. 查询侧要支持自然语言问题，不应要求用户输入刚好等于文档关键词。
7. Serving 不强依赖 JSON 中某个字段必须存在。
8. Mining 尽可能抽取结构化信息，但 Serving 要能在结构化不足时退化运行。
9. embedding、hybrid search、rerank、LLM planner 要预留接口。
10. 第一版可以简单，但主方向必须和工业 RAG / Graph RAG 的演进路径一致。

## 18. 建议的下一步

建议后续拆成两组任务。

Mining：

1. 将 pipeline 默认出口从 canonical 改为 retrieval units。
2. 新增 raw segment relations。
3. 生成 contextual search_text。
4. 保留 canonical 代码但不默认调用。
5. 构造 M1 测试数据库供 Serving 使用。

Serving：

1. 放弃 command lookup 作为主模型。
2. 以 retrieval_units 为主检索入口。
3. 用 raw_segment_relations 做上下文扩展。
4. 输出通用 ContextPack。
5. 保留 `/command-usage` 只作为兼容快捷入口，内部走通用链路。

