# M1 Agent Serving — Claude Serving 交接文档 (v0.5 泛化修订)

> 日期: 2026-04-17
> 任务: TASK-20260415-m1-agent-serving
> 状态: **v0.5 泛化实现完成**，51/51 测试通过

## 任务目标

从 command lookup 升级为面向 Agent 的通用知识检索与证据编排层：

```text
Agent/Skill 请求
  → Query Understanding (intent/entities/scope)
  → QueryPlan (受控检索计划)
  → search_text 召回 + Python JSON 过滤
  → drill down via L2 分离 evidence/variant/conflict
  → 返回 EvidencePack
```

## 核心架构变更（相比 v1.1）

| v1.1 (command lookup) | v2.0 (generic evidence retrieval) |
|---|---|
| `NormalizedQuery(command, product, version, NE)` | `NormalizedQuery(intent, entities[], scope{}, keywords)` |
| `AssetRepo.search_canonical(command_name=)` | `AssetRepo.search_canonical(plan: QueryPlan)` |
| `ContextAssembler` → `ContextPack` | `EvidenceAssembler` → `EvidencePack` |
| `KeyObjects + AnswerMaterials` | `canonical_items + evidence_items + conflicts + gaps + variants` |
| `schema_adapter` 动态 PG→SQLite | 直接加载共享 `001_asset_core.sqlite.sql` |
| seed data 用 v0.4 字段 (command_name, product...) | seed data 用 v0.5 字段 (entity_refs_json, scope_json, block_type, semantic_role) |
| 只测 command 场景 | 测 command + feature + troubleshooting + conflict + scope_variant |

## 改动文件清单

### 全部重写
- `agent_serving/serving/repositories/schema_adapter.py` — 直接加载共享 SQLite DDL
- `agent_serving/serving/repositories/asset_repo.py` — QueryPlan 驱动，scope_json 过滤
- `agent_serving/serving/application/normalizer.py` — entities/scope/intent + build_plan()
- `agent_serving/serving/application/assembler.py` — EvidenceAssembler + EvidencePack
- `agent_serving/serving/schemas/models.py` — 新模型（EntityRef, QueryScope, QueryPlan, EvidencePack 等）
- `agent_serving/serving/api/search.py` — 统一 QueryPlan 管线
- `agent_serving/tests/conftest.py` — v0.5 seed data
- `agent_serving/tests/test_normalizer.py` — 15 tests
- `agent_serving/tests/test_asset_repo.py` — 9 tests
- `agent_serving/tests/test_assembler.py` — 7 tests
- `agent_serving/tests/test_api_integration.py` — 10 tests
- `agent_serving/tests/test_models.py` — 6 tests

### 未修改
- `agent_serving/serving/main.py`
- `agent_serving/serving/api/health.py`
- `agent_serving/tests/test_health.py`
- `agent_serving/tests/test_install_smoke.py`
- `agent_serving/tests/test_schema_adapter.py`

## 关键设计决策

1. **QueryPlan 是接口/扩展点**：M1 用 rule-based `build_plan()`，后续 M2+ 可替换为 LLM planner
2. **command 只是 entity 的一种**：`entity_refs_json` 中 `type=command`，不再是专用 SQL 路径
3. **`/command-usage` 是兼容快捷入口**：内部强制 intent=command_usage，走同一套 QueryPlan 管线
4. **conflict 分离**：conflict_candidate 只进 `conflicts[]`，不进 `evidence_items[]`
5. **直接用共享 SQLite DDL**：不再动态转换 PG DDL
6. **scope 过滤在 Python 端做**：`search_text LIKE` 召回 + Python 解析 `scope_json` / `entity_refs_json` 过滤

## 已执行验证

```
51/51 tests passed:
- 4 schema adapter tests (包含 v0.5 字段验证)
- 6 model tests
- 9 asset repo tests (QueryPlan 驱动)
- 15 normalizer tests (entities/scope/intent/build_plan)
- 7 assembler tests (conflict 分离/gaps/variants)
- 10 API integration tests (全链路 + troubleshooting + scope filter)
- 2 smoke tests (health, import)
```

## 未验证项

- 生产 PostgreSQL 连接
- Mining 产出 DB 后的端到端契约测试（后续必须项）
- 高并发连接池
- LLM planner 接入（M2+）

## 已知风险

1. **LIKE 性能**：大数据量下需优化为 FTS 或 embedding
2. **keyword 提取**：中文分词依赖空格/标点，对无空格短句效果差
3. **scope 过滤是 Python 端**：全量召回后过滤，数据量大时效率低
4. **entity_refs 匹配是精确匹配**：不支持模糊/同义词

## 指定给 Codex 的审查重点

1. **v0.5 字段对齐**：确认所有读取路径已从旧字段迁移到 entity_refs_json/scope_json/block_type/semantic_role
2. **QueryPlan 接口是否足够**：是否能支持后续 LLM planner 接入
3. **conflict 分离是否完整**：确认 conflict_candidate 不出现在 evidence_items
4. **seed data 是否模拟了合理的 Mining v0.5 产出**：scope_json/entity_refs_json 结构是否符合 Mining 写入格式
5. **`/command-usage` 是否正确走了通用路径**：不是独立 SQL 路径
