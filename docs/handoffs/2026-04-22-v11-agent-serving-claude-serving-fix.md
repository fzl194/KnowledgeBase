# Handoff Fix: v1.1 Agent Serving — Pipeline & Consistency Fix

**Date:** 2026-04-22
**From:** Claude Serving
**To:** Codex
**Task:** TASK-20260421-v11-agent-serving
**Review:** docs/analysis/2026-04-22-v11-agent-serving-codex-review.md

---

## 修复范围

基于 Codex 审查的 4 项问题 (3×P1 + 1×P2)，额外执行自审修复。

### P1 修复

| # | 问题 | 修复 |
|---|------|------|
| P1-1 | 检索主链绑定单路 BM25，无多路召回/fusion/rerank pipeline | 新建 `pipeline/` 层：RetrieverManager、Fusion (Identity + RRF)、Reranker (Score)、QueryPlanner (Rule + LLM slot)。/search 走统一管线，BM25 通过 RetrieverManager 注册 |
| P1-2 | QueryPlan 和 LLM 接缝未成立 | 新建 QueryPlanner 独立阶段 + LLMPlannerProvider/LLMNormalizerProvider/LLMRerankerProvider 插件接口。LLMRuntimeClient 改为 HTTP client 协议，不访问 runtime DB |
| P1-3 | ActiveScope/source/graph 未受 build 视图约束 | resolve_active_scope 过滤 selection_status='active'；resolve_source_segments 接收 snapshot_ids；GraphExpander.expand 接收 snapshot_ids；assembler 全链传递 scope |

### P2 修复

| # | 问题 | 修复 |
|---|------|------|
| P2-1 | source_refs_json 只支持 raw_segment_ids | 3层优先级：source_refs_json → target_ref_json → snapshot fallback (slot)。新函数 parse_target_ref + 测试覆盖 |

### 自审修复

| # | 问题 | 修复 |
|---|------|------|
| SR-1 | FTS5 转义不完整 (*() 可注入) | 改用 phrase query wrapping: `"query"` |
| SR-2 | RetrieverManager 串行执行 retriever | 改为 asyncio.gather 并发 |
| SR-3 | 重复 JSON 解析 (asset_repo + graph_expander) | 提取 schemas/json_utils.py 共享模块 |
| SR-4 | _build_suggestions 魔法字符串 | 使用 ISSUE_* 常量 |

## 新增文件

| 文件 | 用途 |
|------|------|
| `serving/pipeline/__init__.py` | Pipeline 层入口 |
| `serving/pipeline/retriever_manager.py` | 多路召回管理 + 并发执行 |
| `serving/pipeline/fusion.py` | IdentityFusion + RRFFusion |
| `serving/pipeline/reranker.py` | ScoreReranker (角色/块类型偏好 + 截断) |
| `serving/pipeline/query_planner.py` | QueryPlanner facade + RulePlannerProvider + LLMPlannerProvider |
| `serving/pipeline/llm_providers.py` | LLMClient protocol + LLMNormalizerProvider + LLMRerankerProvider |
| `serving/schemas/json_utils.py` | parse_source_refs, parse_target_ref, safe_json_parse 共享工具 |
| `tests/test_pipeline.py` | Pipeline 组件单元测试 (21 用例) |

## 修改文件

| 文件 | 变更 |
|------|------|
| `api/search.py` | 重构为 pipeline 调用：RetrieverManager → Fusion → Reranker → Assembler |
| `retrieval/bm25_retriever.py` | 移除 _apply_post_filters (移至 ScoreReranker)，添加 target_type/target_ref_json 到 metadata，FTS5 短语查询转义 |
| `retrieval/graph_expander.py` | expand() 接收 snapshot_ids，_get_neighbors() 过滤 snapshot，parse 函数迁移到 json_utils |
| `repositories/asset_repo.py` | resolve_active_scope 过滤 selection_status='active'，resolve_source_segments 接收 snapshot_ids，get_document_sources 接收 snapshot_ids，_parse_segment_ids 迁移到 json_utils |
| `application/assembler.py` | 全链传递 scope.snapshot_ids，3层 source 解析，使用共享 json_utils 和常量 |
| `application/planner.py` | 重写为 HTTP client 协议 (endpoint + api_key)，不再访问 runtime DB |
| `schemas/models.py` | 新增 RetrieverConfig, RerankerConfig 到 QueryPlan |
| `tests/conftest.py` | 无变更 |
| `tests/test_asset_repo.py` | 新增 3 测试：removed selection 排除、snapshot 过滤、文档 snapshot 约束 |
| `tests/test_assembler.py` | 新增 2 测试：target_ref fallback、无 refs 时仅 seed |

## 测试结果

**92 passed, 1 skipped, 0 failed**

| 文件 | 用例数 |
|------|--------|
| test_models.py | 11 |
| test_normalizer.py | 20 |
| test_asset_repo.py | 15 (+3 build view) |
| test_assembler.py | 8 (+2 source fallback) |
| test_api_integration.py | 11 |
| test_schema_adapter.py | 4 |
| test_pipeline.py | 21 (new) |
| test_mining_contract.py | 1 skipped |

## 关键设计决策

1. **Pipeline 可插拔**: 每个阶段通过抽象接口 + 默认实现。BM25 通过 RetrieverManager 走完整链路，不是直接绑定
2. **LLM 插件接口**: LLMClient protocol 定义统一合同，Serving 不访问 runtime DB 细节。所有 provider 检查 is_available() 后 fallback
3. **Build 视图约束**: resolve_active_scope 过滤 selection_status='active'，全链传递 snapshot_ids
4. **3层 source 解析**: source_refs_json → target_ref_json → snapshot fallback (slot)
5. **FTS5 安全**: phrase query wrapping 防注入
6. **并发检索**: asyncio.gather 多 retriever 并发执行

## 已知残余风险

1. 契约测试仍 skipped，等 Mining v1.1 产出
2. LLM provider 全部 placeholder，等 agent_llm_runtime 收口
3. Vector retriever 未实现 (slot 已预留)
4. RerankerConfig.reranker_type 字段存在但未 dispatch (等 LLM/CrossEncoder 实现)
5. FTS5 中文召回率仍依赖 jieba + unicode61 对齐

## Codex 审查建议

1. 验证 RetrieverManager 并发安全性 (asyncio.gather + CancelledError 处理)
2. 验证 GraphExpander snapshot 过滤在 UNION ALL 两侧是否一致
3. 检查 RRFusion 在单源时的降级行为
4. 确认 LLMClient protocol 与 agent_llm_runtime 实际 API 合同对齐
