# CoreMasterKB v1.2 Agent Serving 实施计划

- 日期：2026-04-22
- 作者：Claude Serving
- 状态：待审批
- 任务：TASK-20260421-v11-agent-serving
- 依赖：Codex v1.2 Retrieval View Layer 架构方案（`docs/analysis/2026-04-22-v12-retrieval-view-architecture-codex-review.md`）

---

## 1. 需求来源

Codex 于 2026-04-22 发布的 v1.2 Retrieval View 架构方案 Section 9 明确了 Serving 侧职责。

### P1 必做项（4 项）

1. source drill-down 优先走 `source_segment_id`
2. FTS query 改 OR 语义
3. normalizer 改 jieba 分词
4. 对 raw_text / contextual_text 做重复压制

### P2 同期优化项（3 项）

1. 低价值 heading/TOC/link 做降权
2. 在现有 reranker 插槽中补 rule rerank 策略
3. build scope 下 source attribution 继续收紧与验证

### LLM 接入项（2 项）

1. query understanding / rewrite（normalizer LLM slot）
2. planner enrichment（planner LLM slot）

### 明确不做

vector retrieval、multi-retriever full parallel rollout、Cross-Encoder rerank、GraphRAG community summary、discourse relation、full evaluation platform

---

## 2. 依赖图

```
Step 1.1 (schema + conftest)
    ├──→ Step 1.2 (assembler bridge)
    ├──→ Step 1.3 (retriever OR + source_segment_id)
    │        └──→ Step 1.5 (去重压制)
    └──→ Step 2.3 (source attribution 收紧)

Step 1.4 (normalizer jieba) ──→ Step 1.3 (jieba tokens 进入 FTS query)

Step 2.1 (降权) ──→ Step 2.2 (rule rerank 增强)

Phase 1 + 2 ──→ Phase 3 (LLM 接入) ──→ Phase 4 (测试)
```

---

## 3. 执行顺序

1. **Step 1.4** — normalizer jieba（独立无依赖）
2. **Step 1.1** — schema + conftest seed data 更新
3. **Step 1.3** — retriever OR 语义 + source_segment_id SELECT
4. **Step 1.2** — assembler source_segment_id 优先桥接
5. **Step 2.1** — 低价值 block_type 降权（独立可并行）
6. **Step 1.5** — raw_text / contextual_text 去重压制
7. **Step 2.2** — rule rerank 策略增强
8. **Step 2.3** — source attribution 收紧
9. **Step 3.1** — LLM client 接入层（LLMClient 包装）
10. **Step 3.2** — LLM Normalizer（query understanding / rewrite）
11. **Step 3.3** — LLM Planner（planner enrichment）
12. **Phase 4** — 测试覆盖

---

## 4. Phase 1：P1 核心修正

### Step 1.1：Schema DDL 适配 + conftest seed data 更新

**文件：** `agent_serving/tests/conftest.py`

**动作：**
- conftest 的 retrieval_unit INSERT 增加 `source_segment_id` 列，指向对应 raw_segment ID
- 增加 contextual_text 类型的 retrieval_unit（用于后续去重测试）
- 增加 heading/TOC 类型的 retrieval_unit（用于后续降权测试）
- `schema_adapter.py` 的 dev DDL 增加 `source_segment_id` 列和索引

**风险：** 低 — Mining 侧负责实际 DDL 变更，Serving conftest 和查询对齐即可。fallback 链保证兼容性。

---

### Step 1.2：Assembler source_segment_id 优先桥接

**文件：** `agent_serving/serving/application/assembler.py`

**动作：** 重写 `_resolve_candidate_sources` 优先级为 4 级链：

1. `source_segment_id`（新增，最高优先级）
2. `source_refs_json.raw_segment_ids`
3. `target_ref_json`
4. 空兜底

```python
def _resolve_candidate_sources(self, candidate: RetrievalCandidate) -> list[str]:
    # Layer 1: source_segment_id (primary bridge)
    seg_id = candidate.metadata.get("source_segment_id")
    if seg_id:
        return [seg_id]

    # Layer 2: source_refs_json.raw_segment_ids
    source_refs = candidate.metadata.get("source_refs_json", "{}")
    seg_ids = parse_source_refs(source_refs)
    if seg_ids:
        return seg_ids

    # Layer 3: target_ref_json
    target_type = candidate.metadata.get("target_type", "")
    target_ref = candidate.metadata.get("target_ref_json", "{}")
    if target_type and target_ref and target_ref != "{}":
        seg_ids = parse_target_ref(target_ref)
        if seg_ids:
            return seg_ids

    # Layer 4: fallback
    return []
```

**风险：** 低 — 纯逻辑变更，fallback 链完整不破坏现有行为。

---

### Step 1.3：BM25 Retriever — OR 语义 + source_segment_id

**文件：** `agent_serving/serving/retrieval/bm25_retriever.py`

**动作：**

1. 删除 `_escape_fts_query`，替换为 `_build_fts_or_query`：

```python
def _build_fts_or_query(tokens: list[str]) -> str:
    escaped = []
    for t in tokens:
        t = t.strip()
        if not t:
            continue
        escaped.append('"' + t.replace('"', '""') + '"')
    return " OR ".join(escaped)
```

2. SQL SELECT 增加 `ru.source_segment_id` 和 `ru.unit_type`
3. `_row_to_candidate` metadata 增加 `source_segment_id` 和 `unit_type`
4. LIKE fallback SQL 同步增加新列

**风险：** 中 — OR 语义增加召回量，reranker 截断控制最终结果数。

---

### Step 1.4：Normalizer 接入 jieba 分词

**文件：** `agent_serving/serving/application/normalizer.py`

**动作：** 重写 `_extract_keywords` 使用 jieba：

```python
def _extract_keywords(self, query: str) -> list[str]:
    cleaned = _DEFAULT_COMMAND_RE.sub("", query)
    try:
        import jieba
        tokens = list(jieba.cut(cleaned))
    except ImportError:
        tokens = [t for t in re.split(r"[\s,，、？?。.！!]+", cleaned) if t]
    return [
        t for t in tokens
        if t not in _ALL_STOPWORDS and (len(t) >= 2 or _is_cjk(t))
    ]
```

增加模块级 `_is_cjk` 辅助函数（与 bm25_retriever 中的一致）。

**风险：** 低 — jieba 是纯 Python 包，ImportError fallback 保留。

---

### Step 1.5：raw_text / contextual_text 去重压制

**文件：** `agent_serving/serving/pipeline/reranker.py`

**动作：** 在 `ScoreReranker` 中增加去重方法，在截断前调用。策略：同一 `source_segment_id` 的 raw_text + contextual_text 仅保留高分者；无 source_segment_id 时按 text 前 200 字符 hash 去重。其他 unit_type（entity_card、generated_question 等）不去重。

**依赖：** Step 1.3（retriever 需传递 source_segment_id 和 unit_type）

**风险：** 中 — 仅对 raw_text/contextual_text 生效，entity_card 等不受影响。

---

## 5. Phase 2：P2 同期优化

### Step 2.1：低价值 heading/TOC/link 降权

**文件：** `agent_serving/serving/pipeline/reranker.py`

**动作：** 定义降权 block_type 集合，对这些类型施加分数惩罚（×0.3），自然排到高价值结果之后。

```python
_LOW_VALUE_BLOCK_TYPES = frozenset({"heading", "toc", "link"})
_DOWNWEIGHT_FACTOR = 0.3
```

**风险：** 低 — 降权不排除结果，只影响排序。

---

### Step 2.2：Rule Rerank 策略增强

**文件：** `agent_serving/serving/pipeline/reranker.py`

**动作：** 将当前的"偏好移到前面"逻辑替换为真正的分数重算：

- Intent-role 匹配加分 +0.3
- Scope 匹配加分 +0.2
- Entity 匹配加分 +0.25
- 加分后按分数排序

这替代了当前的 `preferred + other` 两段排序，更精细。

**依赖：** Step 2.1（降权先执行，在此基础上加分）

**风险：** 中 — 权重作为模块常量易调整，初始版本用保守值。

---

### Step 2.3：Source Attribution 收紧

**文件：** `agent_serving/serving/repositories/asset_repo.py`、`agent_serving/serving/retrieval/graph_expander.py`

**动作：**

1. AssetRepo 增加 `resolve_segments_by_ids(segment_ids, snapshot_ids)` 方法，按 ID 列表直接查询，不经过 JSON 构造
2. Assembler 调整为当有 source_segment_id 时使用新方法
3. GraphExpander 的 `fetch_expanded_segments` 增加 snapshot_ids 约束

**依赖：** Step 1.1 + Step 1.2

**风险：** 低 — 增加约束不破坏正确性。

---

## 6. Phase 3：LLM 接入

### Step 3.1：LLM Client 接入层

**文件：** `agent_serving/serving/pipeline/llm_providers.py`（已存在，修改）

**动作：**
在现有 `LLMClientProtocol` 基础上，实现真实 `LLMRuntimeClient`，封装 `llm_service.client.LLMClient`：

```python
from llm_service.client import LLMClient

class LLMRuntimeClient:
    """Serving 的 LLM Runtime 统一接入。"""

    def __init__(self, base_url: str = "http://localhost:8900"):
        self._client = LLMClient(base_url=base_url)

    async def execute(
        self,
        pipeline_stage: str,
        template_key: str | None = None,
        input: dict | None = None,
        messages: list[dict] | None = None,
        expected_output_type: str = "json_object",
    ) -> dict:
        result = await self._client.execute(
            caller_domain="serving",
            pipeline_stage=pipeline_stage,
            template_key=template_key,
            input=input,
            messages=messages,
            expected_output_type=expected_output_type,
        )
        if result.get("status") != "succeeded":
            raise LLMCallError(result.get("error", {}))
        return result["result"]
```

**风险：** 低 — 封装层，llm_service 不可用时 fallback 到 rule-based。

---

### Step 3.2：LLM Normalizer（query understanding / rewrite）

**文件：** `agent_serving/serving/application/normalizer.py`、`agent_serving/serving/pipeline/llm_providers.py`

**动作：**

1. 在 `llm_service` 中创建 prompt 模板 `serving-query-understanding`：
   - system prompt：定义意图分类（command_usage / concept_lookup / procedure / troubleshooting / general）+ 实体类型（command / parameter / feature）
   - user prompt template：`${query}`
   - expected_output_type：json_object
   - output schema：`{intent, entities: [{type, name, normalized_name}], rewritten_query, keywords}`

2. 实现 `LLMNormalizerProvider`：
   - 调用 `LLMRuntimeClient.execute(pipeline_stage="normalizer", template_key="serving-query-understanding", input={"query": query})`
   - 解析 parsed_output 得到 intent、entities、keywords
   - LLM 不可用时 fallback 到 RuleNormalizer

3. Normalizer facade 调整为：有 LLM client 时用 LLM，否则用 rule-based

```python
class Normalizer:
    def __init__(self, llm_client: LLMRuntimeClient | None = None):
        self._llm = llm_client

    async def normalize(self, request: SearchRequest) -> NormalizedQuery:
        if self._llm:
            try:
                return await self._normalize_via_llm(request)
            except LLMCallError:
                pass
        return self._normalize_via_rules(request)
```

**依赖：** Step 1.4（jieba 已接入，LLM 降级时仍走 jieba）

**风险：** 中 — LLM 延迟（~500ms），需设超时；fallback 保证可用性。

---

### Step 3.3：LLM Planner（planner enrichment）

**文件：** `agent_serving/serving/pipeline/query_planner.py`、`agent_serving/serving/pipeline/llm_providers.py`

**动作：**

1. 在 `llm_service` 中创建 prompt 模板 `serving-planner`：
   - system prompt：基于 intent、entities、scope 生成 QueryPlan
   - user prompt template：`${intent} | ${entities_json} | ${scope_json} | ${keywords_json}`
   - expected_output_type：json_object
   - output schema：`{desired_roles, desired_block_types, retriever_config, budget: {max_items, recall_multiplier}}`

2. 实现 `LLMPlannerProvider`：
   - 调用 `LLMRuntimeClient.execute(pipeline_stage="planner", template_key="serving-planner", input={...})`
   - 解析 parsed_output 构造 QueryPlan
   - LLM 不可用时 fallback 到 RulePlannerProvider

3. QueryPlanner facade 调整为：有 LLM client 时用 LLM，否则用 rule-based

**依赖：** Step 3.2（复用 LLM client 接入层）

**风险：** 中 — QueryPlan 字段较多，LLM 输出需严格解析；fallback 保证可用性。

---

## 7. Phase 4：测试覆盖

### Step 4.1：更新 conftest seed data
- 为 retrieval_units INSERT 增加 source_segment_id
- 增加 contextual_text / heading / TOC 类型的 retrieval_unit

### Step 4.2：P1 单元测试
- `test_source_segment_id_primary_bridge` — 验证优先于 source_refs_json
- `test_source_segment_id_fallback_chain` — 验证 fallback
- `test_chinese_jieba_segmentation` — 验证中文分词
- `test_deduplicate_same_source_segment` — 验证去重
- `test_fts_or_semantics` — 验证 OR 查询

### Step 4.3：P2 单元测试
- `test_low_value_block_type_downweight` — 验证降权
- `test_rule_scoring_intent_boost` — 验证加分
- `test_rule_scoring_scope_boost`
- `test_rule_scoring_entity_boost`

### Step 4.4：LLM 接入测试
- `test_llm_normalizer_success` — mock LLM 返回，验证 intent + entities + keywords
- `test_llm_normalizer_fallback` — LLM 失败时 fallback 到 rule-based
- `test_llm_planner_success` — mock LLM 返回，验证 QueryPlan 构建
- `test_llm_planner_fallback` — LLM 失败时 fallback 到 RulePlanner

### Step 4.5：集成测试
- 中文查询端到端检索（jieba + OR + 去重全链路）
- heading 排在 paragraph 之后
- source_segment_id 全 pipeline 传递
- LLM normalizer → planner → retriever → reranker → assembler 全链路

### Step 4.6：Contract test 骨架
- 验证 source_segment_id 列存在
- 验证 FTS5 中文查询有效
- 保留 skip 标记等 Mining v1.2 DB 产出

---

## 8. 文件变更清单

| 文件 | 变更类型 | 涉及 Step |
|------|---------|----------|
| `agent_serving/serving/application/assembler.py` | 修改 | 1.2, 2.3 |
| `agent_serving/serving/retrieval/bm25_retriever.py` | 修改 | 1.3 |
| `agent_serving/serving/application/normalizer.py` | 修改 | 1.4, 3.2 |
| `agent_serving/serving/pipeline/reranker.py` | 修改 | 1.5, 2.1, 2.2 |
| `agent_serving/serving/pipeline/llm_providers.py` | 修改 | 3.1, 3.2, 3.3 |
| `agent_serving/serving/pipeline/query_planner.py` | 修改 | 3.3 |
| `agent_serving/serving/repositories/asset_repo.py` | 修改 | 2.3 |
| `agent_serving/serving/repositories/schema_adapter.py` | 修改 | 1.1 |
| `agent_serving/serving/retrieval/graph_expander.py` | 修改 | 2.3 |
| `agent_serving/tests/conftest.py` | 修改 | 1.1, 4.1 |
| `agent_serving/tests/test_assembler.py` | 修改 | 4.2 |
| `agent_serving/tests/test_normalizer.py` | 修改 | 4.2, 4.4 |
| `agent_serving/tests/test_mining_contract.py` | 修改 | 4.6 |
| `agent_serving/tests/test_api_integration.py` | 修改 | 4.5 |

---

## 9. 风险与缓解

| 风险 | 级别 | 缓解 |
|------|------|------|
| Mining 未写入 source_segment_id | 中 | fallback 链完整，两种路径都能工作 |
| jieba 分词粒度不准 | 低 | 支持用户词典，当前远优于无分词 |
| OR 语义召回噪音增加 | 中 | reranker 三层过滤（降权+加分+截断） |
| 去重误去有价值变体 | 中 | 仅 raw_text/contextual_text，其他类型不受影响 |
| rule rerank 权重不合理 | 低 | 模块常量，易调整 |
| LLM 不可用或超时 | 中 | 每个环节都有 rule-based fallback；LLM 调用设超时（3s） |

---

## 10. 验收标准

| 能力 | 验收标准 |
|------|---------|
| Source drill-down | Assembler 优先 source_segment_id；无时 fallback 到 source_refs_json |
| FTS OR 语义 | 不再双引号短语匹配；每个 token 独立 OR |
| jieba 分词 | "什么是业务感知" 产出有效 keywords |
| 去重压制 | 同 source_segment_id 的 raw_text+contextual_text 仅保留高分者 |
| 降权 | heading/TOC/link 排在同分 paragraph 之后 |
| Rule rerank | desired_roles/scope/entity 匹配获可见分数提升 |
| Source attribution | graph expansion 和 source drill-down 被 snapshot_ids 约束 |
| LLM Normalizer | 调用 llm_service 做意图+实体+改写；不可用时 fallback 到 rule+jieba |
| LLM Planner | 调用 llm_service 生成 QueryPlan；不可用时 fallback 到 RulePlanner |
| 不超范围 | 无 vector / Cross-Encoder / GraphRAG / discourse 代码 |
