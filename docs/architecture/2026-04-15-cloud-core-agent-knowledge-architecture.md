# 云核心网 Agent Knowledge Backend 总体架构设计

## 1. 文档目的

本文档沉淀当前项目的新架构基线，供 Claude Code 后续制定实现计划和开发使用。

当前仓库已将旧项目完整代码移动到 `old/`。旧代码不再作为新系统的直接运行入口，只作为参考实现和可剥离资产来源。新系统不应继续沿用旧项目“大一统 pipeline + API + ontology governance”的组织方式，而应按真实业务使用链路重新设计。

本项目的新目标是构建一套面向云核心网知识使用的后端体系，使 Agent 能通过 Skill 调用后端服务，查询云核心网产品文档、命令手册、配置指南中的命令写法、参数含义、配置示例、注意事项、前置条件和来源证据。

## 2. 核心共识

整体架构按以下链路组织：

```text
Agent
  ↓
Skill
  ↓
Agent Serving / 运行态服务
  ↓
Knowledge Assets / 知识资产层
  ↑
Knowledge Mining / 挖掘态服务
  ↑
Raw Documents / 原始资料
```

关键原则：

- Agent 层依赖已有 Agent 框架，不在本项目内重做。
- Skill 层保持轻量，只负责工具封装、调用策略、回答格式和追问规则。
- Agent Serving 是运行态，只读已发布知识资产，面向 Skill 提供业务语义化 API。
- Knowledge Assets 是中间产物契约，挖掘态写入，运行态读取。
- Knowledge Mining 是设计态/挖掘态，负责从原始资料生产知识资产。
- `old/` 只读参考，新代码不得 `import old.*`。

## 3. 分层职责

### 3.1 Agent 层

Agent 层由外部已有 Agent 框架承载。

职责：

- 理解用户问题。
- 判断是否需要调用云核心网知识 Skill。
- 根据 Skill 返回的 context pack 组织最终答案。
- 在厂家、产品、版本、EPC/5GC 场景缺失时追问或提示不确定性。

不负责：

- 直接查询数据库。
- 直接访问向量索引。
- 直接执行图遍历。
- 理解挖掘 pipeline 的内部实现。

### 3.2 Skill 层

Skill 是 Agent 与后端服务之间的轻量契约。

职责：

- 定义可调用工具。
- 描述何时调用哪个工具。
- 约束回答模板。
- 处理缺失上下文的追问规则。
- 将 Agent 的自然语言意图转为后端 API 请求。

第一版 Skill 至少包含：

```text
get_command_usage
search_cloud_core_knowledge
assemble_cloud_core_context
```

Skill 不做：

- 文档检索实现。
- 重排序。
- 图扩展。
- 数据库访问。
- 批量知识加工。

### 3.3 Agent Serving / 运行态服务

运行态服务是 Skill 调用的在线后端。

职责：

- 查询归一化。
- 简单意图判断。
- 检索计划生成。
- 多路召回。
- 上下文扩展。
- 重排序。
- context pack 组装。
- 证据返回。
- 检索日志和调试解释。

运行态服务只读 `Knowledge Assets` 中 active publish version 的数据。

运行态服务只允许写：

```text
retrieval_logs
feedback_logs
```

运行态不做：

- 文档解析。
- 命令抽取。
- 批量 embedding 生成。
- 质量门控。
- 发布版本切换。
- 人工修正。

### 3.4 Knowledge Assets / 知识资产层

知识资产层是系统最关键的中间契约。

它承载挖掘态产出的可发布数据，并为运行态提供稳定读取模型。

阶段 1A 的核心资产包括：

```text
publish_versions
documents
document_profiles
sections
segments
segment_annotations
commands
command_aliases
command_segment_links
segment_edges
segment_embeddings
alias_dictionary
quality_reports
```

核心要求：

- 所有在线查询必须基于某个 publish version。
- 默认读取 `status = active` 的版本。
- 挖掘态不得直接覆盖线上 active 资产。
- 新资产先进入 staging，通过质量检查后再激活。

### 3.5 Knowledge Mining / 挖掘态服务

挖掘态服务负责从原始资料生产知识资产。

阶段 1A 只聚焦命令与证据优先，不做完整本体抽取。

职责：

- 原始文档接入。
- 文档画像识别。
- 章节结构恢复。
- segment 切分。
- 轻量 segment 标注。
- 命令入口抽取。
- 命令到参数/示例/注意事项/前置条件段落的关联。
- segment edge 构建。
- embedding 批量生成。
- 质量检查。
- 发布版本生成。

阶段 1A 优先支持：

```text
Markdown
HTML
TXT
```

PDF、Word、ZIP、多厂家复杂版式解析后置。

## 4. 推荐目录结构

建议根目录组织如下：

```text
Self_Knowledge_Evolve/
  docs/
    architecture/
    messages/
    plans/
    handoffs/
    analysis/

  old/
    ...旧项目完整代码，只读参考...

  knowledge_mining/
    README.md
    pyproject.toml
    mining/
      ingestion/
      document_profile/
      structure/
      segmentation/
      annotation/
      command_extraction/
      edge_building/
      embedding/
      quality/
      publishing/
      jobs/
    scripts/
    tests/

  knowledge_assets/
    README.md
    schemas/
    migrations/
    dictionaries/
    manifests/
    samples/

  agent_serving/
    README.md
    pyproject.toml
    serving/
      api/
      application/
      retrieval/
      expansion/
      rerank/
      assembly/
      evidence/
      repositories/
      schemas/
      observability/
    scripts/
    tests/

  skills/
    cloud_core_knowledge/
      SKILL.md
      tools.md
      answer_templates.md
      examples.md
```

如果 Claude 第一轮需要降低工程复杂度，可以先创建目录骨架和 README，不必一次性填满所有模块。

## 5. 数据库边界

阶段 1A 建议使用同一个 PostgreSQL，通过 schema 隔离职责：

```text
mining.*
asset.*
serving.*
```

建议：

- `mining.*` 放挖掘过程中的 staging/intermediate 数据。
- `asset.*` 放发布后的稳定知识资产。
- `serving.*` 放运行态日志和反馈。

不建议第一阶段拆多个数据库，避免运维复杂度过高。

## 6. Phase 1A 范围

Phase 1A 是最小可用闭环，不是完整系统。

目标：

```text
用少量云核心网文档，让 Agent 通过 Skill 查询命令写法、参数、示例、注意事项和来源证据。
```

必做：

- 项目目录骨架。
- Asset schema 初版。
- Markdown/HTML/TXT 文档导入。
- section/segment 生成。
- 命令入口索引。
- command 到 parameter/example/note/condition segment 的关联。
- segment_edges。
- segment embedding。
- `/api/v1/command/usage`。
- `/api/v1/search`。
- `/api/v1/context/assemble`。
- Skill 初版文档。
- 30-50 个真实问题评测集。

不做：

- 复杂 PDF/Word 解析。
- 完整 ontology。
- facts/triples。
- Neo4j 依赖。
- 影响分析。
- 故障专家推理。
- 人工审批流。
- Dashboard。
- 旧项目完整 worker 机制。

## 7. Graph-RAG 第一阶段定义

阶段 1A 的 Graph-RAG 不使用大图作为强依赖，也不要求 Neo4j。

它通过关系表实现：

```text
asset.segment_edges
asset.command_segment_links
asset.sections
```

典型扩展逻辑：

```text
命中 command_def
  → 扩展 command_to_parameter
  → 扩展 command_to_example
  → 扩展 command_to_note
  → 扩展 command_to_condition
  → 扩展 same_section / prev_next
```

阶段 1A 中 Graph-RAG 的价值不是展示图，而是让 Agent 获取完整上下文和证据组合。

## 8. 运行态 API 初版

### 8.1 `POST /api/v1/command/usage`

处理：

```text
ADD APN 命令怎么写？
ADD APN 的参数是什么意思？
有没有配置示例？
这个命令有什么注意事项？
```

返回 context pack，而不是裸搜索结果。

### 8.2 `POST /api/v1/search`

通用兜底检索。

适用：

- 命令索引未覆盖。
- 术语解释。
- 模糊问题。
- Skill fallback。

### 8.3 `POST /api/v1/context/assemble`

给定候选 command/segment/document，重新组装稳定上下文包。

适用：

- 多步 Skill 调用。
- 二次收束。
- 后续流程类/故障类接口复用。

### 8.4 Context Pack 最小字段

运行态返回给 Skill 的核心结构应稳定：

```text
query
intent
normalized
key_objects
answer_materials
evidence
source_documents
uncertainties
suggested_followups
debug_trace
```

`debug_trace` 默认仅 debug 模式返回。

## 9. old 代码剥离策略

`old/` 是参考库，不是运行依赖。

禁止：

```text
from old...
import old...
```

可参考或瘦身迁移：

```text
old/src/pipeline/preprocessing/extractor.py
old/src/pipeline/preprocessing/normalizer.py
old/src/utils/hashing.py
old/src/utils/text.py
old/src/utils/embedding.py
old/src/providers/postgres_store.py
old/src/providers/bge_m3_embedding.py
old/scripts/init_postgres.sql 中 documents / segments / t_rst_relation 思路
old/demo/run_text_to_ontology.py 的内存 demo 思路
```

暂不迁移：

```text
old/src/governance/*
old/src/stats/*
old/src/ontology/*
old/src/operators/*
old/src/api/semantic/*
old/src/pipeline/stages/stage3_align.py 之后的完整本体链路
old/worker.py
old/static/*
```

## 10. Claude 后续建议里程碑

Claude Code 后续计划建议按以下里程碑展开。

### M0 项目骨架

- 创建 `knowledge_mining/`、`knowledge_assets/`、`agent_serving/`、`skills/`。
- 建立最小 Python 项目配置。
- `agent_serving` 提供 `GET /health`。

### M1 资产表结构

- 创建 `asset.*` schema migration。
- 包含 publish_versions、documents、sections、segments、commands、command_aliases、command_segment_links、segment_edges、segment_embeddings、alias_dictionary。

### M2 最小挖掘链路

- 支持 Markdown/TXT/HTML 导入。
- 生成 document profile、section、segment。
- 写入 asset staging。

### M3 命令抽取

- 识别 `ADD/MOD/DEL/SET/SHOW/LST/DSP` 等命令。
- 生成 commands、command_aliases、command_segment_links。

### M4 边构建和 embedding

- 生成 prev_next、same_section、command_to_parameter、command_to_example、command_to_note 等边。
- 批量生成 segment embedding。

### M5 Serving 检索

- exact command retriever。
- keyword retriever。
- vector retriever。
- metadata filter。
- expansion。
- reranker。

### M6 Context Pack

- `/api/v1/command/usage` 输出稳定 context pack。
- 实现 evidence builder、uncertainties、suggested_followups。

### M7 Skill 初版

- `skills/cloud_core_knowledge/SKILL.md`。
- 工具定义、调用策略、回答模板、示例问题。

### M8 评测闭环

- 准备 30-50 个真实问题。
- 评估命令召回、证据覆盖、context pack 完整性。

## 11. 需要 Claude 重点避免的问题

- 不要把 mining pipeline 和 serving API 混在同一个运行服务里。
- 不要让 serving import mining。
- 不要把旧项目完整复制回来。
- 不要第一阶段引入完整 ontology / facts / Neo4j。
- 不要把 Skill 写成重型检索系统。
- 不要先做 PDF/Word 复杂解析而阻塞命令问答闭环。
- 不要返回裸搜索结果给 Agent，必须稳定 context pack。

## 12. 当前有效决策

- 第一阶段只做 Phase 1A 最小闭环。
- 第一阶段聚焦命令与证据优先。
- 第一阶段优先支持 Markdown/HTML/TXT。
- 第一阶段 Graph-RAG 使用关系表实现，不强依赖 Neo4j。
- 第一阶段使用同库不同 schema。
- `publish_versions` 是运行态读取入口。
- `old/` 不作为 import 依赖。

