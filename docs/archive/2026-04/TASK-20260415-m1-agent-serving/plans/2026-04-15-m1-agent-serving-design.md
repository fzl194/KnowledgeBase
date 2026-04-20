# M1 Agent Serving 设计文档

> 版本: v2.0（v0.5 schema 泛化修订）
> 日期: 2026-04-15 / 更新: 2026-04-17
> 作者: Claude Serving
> 任务: TASK-20260415-m1-agent-serving
> 状态: v0.5 泛化实现完成，51/51 测试通过

## 修订说明

- v2.0 (2026-04-17): 从 command lookup 升级为 generic evidence retrieval；schema 从 v0.4 升级到 v0.5；引入 QueryPlan 作为中间协议；输出改为 EvidencePack
- v1.1 (2026-04-17): 初版实现，39/39 测试通过
- v1.0 (2026-04-15): 初版设计

## 1. 任务目标

实现面向 Agent 的通用知识检索与证据编排层：

```text
Agent/Skill 请求
  -> Query Understanding (intent/entities/scope)
  -> QueryPlan (受控检索计划)
  -> search_text 召回 + Python JSON 过滤
  -> drill down via L2 to L0 raw evidence
  -> 返回 EvidencePack (evidence/variants/conflicts/gaps)
```

命令查询只是 entity.type=command 的一种场景，不是系统主轴。

## 2. 设计决策

### 2.1 检索方式：search_text LIKE + Python JSON 过滤

- L1 用 `search_text LIKE` 召回 canonical 候选
- Python 端解析 `entity_refs_json` / `scope_json` 做过滤和排序
- L2 下钻按 `relation_type` 分离 evidence / variant / conflict
- M1 不做 vector 检索、JSONB SQL 优化

### 2.2 QueryPlan 作为稳定中间协议

```text
Normalizer -> NormalizedQuery -> build_plan() -> QueryPlan -> Repository
```

M1 用规则生成 QueryPlan，后续 M2+ 可替换为 LLM planner / ontology expansion。

### 2.3 Schema 使用方式

- 直接读取 `knowledge_assets/schemas/001_asset_core.sqlite.sql`，不动态转换
- 不再维护私有 PG→SQLite DDL 转换器
- 不修改 asset schema

### 2.4 测试数据策略

- SQLite in-memory + 共享 DDL 建表
- v0.5 seed data 覆盖 command + feature + troubleshooting 三类 entity
- 覆盖 scope_variant + conflict_candidate + require_scope

## 3. 总体架构

```text
Skill 请求
  ↓
FastAPI API 层 (api/)
  ├── /api/v1/search         — 通用检索主入口
  └── /api/v1/command-usage  — 兼容快捷入口 (intent=command_usage)
  ↓
Application 层 (application/)
  ├── QueryNormalizer   — 解析 intent/entities/scope/keywords
  ├── build_plan()      — 生成 QueryPlan
  └── EvidenceAssembler — 组装 EvidencePack
  ↓
Repository 层 (repositories/)
  ├── AssetRepository   — 接受 QueryPlan，只读 L1/L2/L0
  └── schema_adapter    — 加载共享 SQLite DDL
  ↓
SQLite (dev) / PostgreSQL (prod)
```

## 4. 模块与文件清单

| 文件 | 职责 |
|------|------|
| `agent_serving/serving/repositories/asset_repo.py` | QueryPlan 驱动的只读 L1/L2/L0 |
| `agent_serving/serving/repositories/schema_adapter.py` | 加载共享 SQLite DDL |
| `agent_serving/serving/application/normalizer.py` | entities/scope/intent 提取 + build_plan |
| `agent_serving/serving/application/assembler.py` | EvidencePack 组装 |
| `agent_serving/serving/schemas/models.py` | NormalizedQuery / QueryPlan / EvidencePack |
| `agent_serving/serving/api/search.py` | `/search` + `/command-usage` |
| `agent_serving/serving/api/health.py` | `GET /health` |
| `agent_serving/serving/main.py` | FastAPI app，lifespan DB 初始化 |
| `agent_serving/tests/conftest.py` | v0.5 seed data fixture |
| `agent_serving/tests/test_normalizer.py` | Normalizer + build_plan 测试 |
| `agent_serving/tests/test_asset_repo.py` | QueryPlan 检索测试 |
| `agent_serving/tests/test_assembler.py` | EvidencePack + conflict 分离测试 |
| `agent_serving/tests/test_schema_adapter.py` | 共享 DDL 加载测试 |
| `agent_serving/tests/test_models.py` | 新模型序列化测试 |
| `agent_serving/tests/test_api_integration.py` | 全链路集成测试 |

## 5. 数据流

### 5.1 通用检索流

```text
请求 {query: "UDG V100R023C10 ADD APN 怎么写"}
  → Normalizer: intent=command_usage, entities=[{type:command, name:ADD APN}], scope={products:[UDG], versions:[V100R023C10]}
  → build_plan(): QueryPlan(intent=command_usage, entity_constraints=[...], scope_constraints={...})
  → AssetRepo.search_canonical(plan): search_text LIKE + entity_refs_json filter
  → L1 命中 canonical
  → AssetRepo.drill_down(canonical_id, plan): 分离 evidence / variant / conflict
  → EvidenceAssembler: 组装 EvidencePack
  → 返回 {evidence_items, conflicts, variants, gaps, ...}
```

### 5.2 关键词搜索流

```text
请求 {query: "5G 移动通信"}
  → Normalizer: intent=concept_lookup, keywords=["5G"]
  → build_plan(): QueryPlan(intent=concept_lookup, keywords=["5G"])
  → search_text LIKE "%5G%"
  → EvidencePack 返回
```

### 5.3 约束不足流

```text
请求 {query: "ADD APN 怎么写"}
  → Normalizer: missing_constraints=["product"]
  → build_plan(): variant_policy=require_disambiguation
  → EvidencePack.gaps 包含 {field:"product", reason:"该知识在不同产品上有差异"}
  → suggested_followups 提示补充约束
```

## 6. Query Normalizer 规则

M1 使用硬编码规则，输出映射到 `entities[] + scope{} + intent`：

- 操作词映射：`新增→ADD, 修改→MOD, 删除→DEL, 查询→SHOW, 设置→SET`
- 命令正则：`ADD|MOD|DEL|SET|SHOW|LST|DSP\s+[A-Z]+`
- 产品识别：`UDG|UNC|UPF|AMF|SMF|PCF|UDM`
- 版本识别：`V\d+R\d+C\d+`
- 网元识别：`AMF|SMF|UPF|UDM|PCF|NRF`
- 意图检测：关键词匹配 command_usage / troubleshooting / concept_lookup / procedure

## 7. EvidencePack 结构

```json
{
  "query": "str",
  "intent": "str",
  "normalized_query": "str",
  "query_plan": { "intent", "entity_constraints", "scope_constraints", "variant_policy", ... },
  "canonical_items": [{ "id", "canonical_key", "block_type", "semantic_role", "title", "canonical_text", "entity_refs", "scope", "has_variants", "variant_policy" }],
  "evidence_items": [{ "id", "block_type", "semantic_role", "raw_text", "section_path", "entity_refs" }],
  "sources": [{ "document_key", "relative_path", "section_path", "block_type", "scope" }],
  "matched_entities": [{ "type", "name", "normalized_name" }],
  "matched_scope": { "products", "product_versions", "network_elements", "projects", "domains" },
  "variants": [{ "raw_segment_id", "relation_type", "diff_summary", "scope" }],
  "conflicts": [{ "raw_text", "diff_summary", "scope" }],
  "gaps": [{ "field", "reason", "suggested_options" }],
  "suggested_followups": ["str"]
}
```

## 8. entity_refs_json 和 scope_json 最小格式

### entity_refs_json

```json
[{"type": "command", "name": "ADD APN", "normalized_name": "ADD APN"}]
```

type 包括: command / feature / term / alarm / network_element 等。

### scope_json

```json
{"products": ["UDG"], "product_versions": ["V100R023C10"], "network_elements": ["UDM"], "projects": [], "domains": []}
```

## 9. 不做的内容

- vector 检索 / embedding
- LLM planner
- ontology / graph expansion
- 复杂 JSONB SQL 优化
- 自动最终答案生成
- 修改 asset schema

## 10. 演进路径

```text
M1: generic evidence retrieval 最小闭环 (当前)
M2: QueryPlan 明确化 + 多路召回 + ranking/filters
M3: embedding/vector + rerank
M4: ontology/graph expansion + multi-hop retrieval
M5: LLM/Agent planner 生成 QueryPlan，Serving 校验并执行
```

## 11. 与 Mining 任务的接口边界

| 接口 | 方向 | 说明 |
|------|------|------|
| `knowledge_assets/schemas/001_asset_core.sql` | 共享只读 | PostgreSQL 契约 |
| `knowledge_assets/schemas/001_asset_core.sqlite.sql` | 共享只读 | SQLite 契约，dev/test 用 |
| 数据库 asset_* 表 | Mining 写，Serving 读 | 通过数据库对接 |
| Mining→Serving 契约测试 | 后续必须项 | Mining 产出 DB 后 Serving 读取验证 |
