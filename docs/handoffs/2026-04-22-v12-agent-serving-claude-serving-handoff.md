# v1.2 Agent Serving Retrieval View Layer — Claude Serving Handoff

- 日期：2026-04-22
- 作者：Claude Serving
- 任务：TASK-20260421-v11-agent-serving
- 依赖：Codex v1.2 Retrieval View Layer 架构方案（`docs/analysis/2026-04-22-v12-retrieval-view-architecture-codex-review.md`）

---

## 任务目标

基于 Codex 发布的 v1.2 Retrieval View Layer 架构方案，对 Serving 侧进行全面修正与增强，包括 P1 核心修正（4 项）、P2 同期优化（3 项）和 LLM 接入（3 项）。

## 本次实现范围

### Phase 1：P1 核心修正（5 项）

1. **Step 1.1** — schema_adapter 增加 `source_segment_id` 列迁移，conftest seed data 增加该列 + contextual_text / heading 类型 retrieval_unit
2. **Step 1.2** — assembler source_segment_id 4 层优先桥接（source_segment_id > source_refs_json > target_ref_json > 空）
3. **Step 1.3** — BM25 Retriever OR 语义查询，SELECT 增加 source_segment_id / unit_type
4. **Step 1.4** — Normalizer jieba 中文分词接入，ImportError fallback 保留
5. **Step 1.5** — raw_text / contextual_text 去重（同 source_segment_id 仅保留高分者，entity_card 等不受影响）

### Phase 2：P2 同期优化（3 项）

6. **Step 2.1** — heading / TOC / link 降权 ×0.3
7. **Step 2.2** — rule scoring 三层加分（intent-role +0.3, scope +0.2, entity +0.25）
8. **Step 2.3** — AssetRepo 新增 `resolve_segments_by_ids` 直接查询；GraphExpander `fetch_expanded_segments` 增加 snapshot_ids 约束

### Phase 3：LLM 接入（3 项）

9. **Step 3.1** — `LLMRuntimeClient` 封装 `llm_service.client.LLMClient.execute()`
10. **Step 3.2** — Normalizer 增加 `anormalize()` 异步方法，LLM 不可用时 fallback 到 rule+jieba
11. **Step 3.3** — `LLMPlannerProvider` 增加 `abuild_plan()` 异步方法，LLM 不可用时 fallback 到 RulePlanner

## 不在本次范围内的内容

- vector retrieval
- Cross-Encoder rerank
- GraphRAG community summary
- discourse relation
- full evaluation platform
- FTS5 中文 tokenizer（需 Mining 侧 search_text 预分词配合）

## 改动文件清单

| 文件 | 变更类型 |
|------|---------|
| `docs/plans/2026-04-22-v12-agent-serving-impl-plan.md` | 新建 |
| `agent_serving/serving/repositories/schema_adapter.py` | 修改 |
| `agent_serving/serving/retrieval/bm25_retriever.py` | 修改 |
| `agent_serving/serving/application/assembler.py` | 修改 |
| `agent_serving/serving/application/normalizer.py` | 修改 |
| `agent_serving/serving/application/planner.py` | 修改 |
| `agent_serving/serving/pipeline/reranker.py` | 修改 |
| `agent_serving/serving/pipeline/llm_providers.py` | 修改 |
| `agent_serving/serving/pipeline/query_planner.py` | 修改 |
| `agent_serving/serving/repositories/asset_repo.py` | 修改 |
| `agent_serving/serving/retrieval/graph_expander.py` | 修改 |
| `agent_serving/tests/conftest.py` | 修改 |
| `agent_serving/tests/test_pipeline.py` | 修改 |

## 关键设计决策

1. **source_segment_id 迁移策略**：在 schema_adapter 中用 ALTER TABLE 添加（Mining DDL 尚未包含），try/except 处理"列已存在"情况
2. **OR 查询构建**：每个 token 独立双引号包裹，OR 连接，避免 phrase query
3. **去重范围**：仅 raw_text + contextual_text 且有 source_segment_id 时去重，entity_card / summary / generated_question 不受影响
4. **不可变性**：reranker 使用 `model_copy(update={...})` 而非就地修改 score
5. **LLM 同步/异步双路径**：`normalize()` / `plan()` 保持同步走 rule-based；`anormalize()` / `abuild_plan()` 异步走 LLM-first
6. **graph_expander UNION ALL 修复**：type_filter / snapshot_filter 应用到两个 SELECT 分支，参数计数对齐

## 已执行验证

- 全量回归：112 passed, 1 skipped（原 92 passed）
- 新增 v1.2 测试覆盖：
  - 去重（3 项）
  - 降权（2 项）
  - Rule scoring（3 项）
  - source_segment_id 4 层桥接（4 项）
  - FTS OR 查询构建（4 项）
  - LLM Normalizer fallback（2 项）
  - LLM Planner fallback（2 项）
- 自查修复（code-reviewer 发现 3 个 HIGH 级问题，已全部修复）

## 未验证项

- LLM runtime 实际可用时的端到端调用（需要 llm_service 运行 + prompt template 注册）
- 真实 Mining v1.2 产出的数据库（source_segment_id 实际填充后的行为）
- FTS5 中文分词效果（需 Mining 侧 search_text 预分词配合）

## 已知风险

| 风险 | 缓解 |
|------|------|
| Mining 未写入 source_segment_id | 4 层 fallback 链完整，两种路径都能工作 |
| OR 语义召回噪音增加 | reranker 三层过滤（降权 + 加分 + 截断） |
| jieba 分词粒度不准 | 支持用户词典，远优于无分词 |
| LLM 不可用或超时 | 每个环节都有 rule-based fallback |
| LIKE fallback 无排序 | 仅在 FTS5 不可用时触发，非主路径 |

## 指定给 Codex 的审查重点

1. `graph_expander._get_neighbors` 的 UNION ALL 参数计数是否正确（两个 SELECT 各自独立参数集）
2. `LLMRuntimeClient.execute()` 的 error handling 是否与 llm_service 的 response 格式对齐
3. reranker `model_copy` 是否正确处理 Pydantic v2 的 deep copy
4. normalizer `anormalize()` 的 `desired_roles` 为空列表是否需要从 intent 推导
5. conftest seed data 的 source_segment_id 是否与预期 raw_segment IDs 一致
