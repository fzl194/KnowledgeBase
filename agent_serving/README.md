# Agent Serving

`agent_serving` 是 CoreMasterKB 的在线知识使用层。它面向 Skill / Agent 提供 HTTP API，从 Mining 生成的知识资产数据库中读取唯一 active 版本，检索 L1 归并语料，下钻 L2 来源映射和 L0 原始片段，最后返回结构化的 `EvidencePack`。

它不负责解析文档、不做批量去重、不写入知识资产表，也不生成最终自然语言答案。它的输出是给上层 Agent 使用的证据包。

当前 M1 核心边界：

- Serving 只读 `asset_*` 知识资产表。
- Serving 不 import `knowledge_mining`。
- Mining 和 Serving 只通过 `knowledge_assets/schemas/001_asset_core.sqlite.sql` 对接。
- 查询主入口是 `/api/v1/search`。
- `/api/v1/command-usage` 只是兼容快捷入口，内部也走通用 QueryPlan 管线。
- M1 使用 `search_text LIKE` + Python 侧 JSON 容错过滤和打分，不做向量检索、LLM planner、ontology expansion。

## 整体架构

```text
Agent / Skill
  -> FastAPI API
  -> QueryNormalizer
  -> QueryPlan
  -> AssetRepository
  -> active SQLite asset DB
  -> EvidenceAssembler
  -> EvidencePack
```

代码分层：

| 层 | 目录 | 职责 |
|---|---|---|
| API 层 | `serving/api/` | HTTP 路由、请求校验、调用应用层 |
| Application 层 | `serving/application/` | query 归一化、QueryPlan 构建、EvidencePack 组装 |
| Repository 层 | `serving/repositories/` | 只读 SQLite asset tables，执行 L1/L2/L0 查询 |
| Schema 层 | `serving/schemas/` | Pydantic 请求、响应、中间协议模型和常量 |
| 预留能力层 | `serving/retrieval/`, `rerank/`, `expansion/`, `evidence/`, `observability/` | M2+ 扩展位 |
| 启动脚本 | `scripts/` | 本地启动 FastAPI |
| 测试 | `tests/` | 单元、API 集成、Mining DB 契约测试 |

## 如何启动

### 1. 使用 Mining 生成的 SQLite DB

推荐方式是先由 `knowledge_mining` 生成 SQLite 数据库，然后把路径通过环境变量交给 Serving：

```powershell
$env:COREMASTERKB_ASSET_DB_PATH="D:\mywork\KnowledgeBase\CoreMasterKB\data\m1_contract_corpus\m1_contract_asset.sqlite"
python -m agent_serving.scripts.run_serving --host 127.0.0.1 --port 8000
```

启动脚本等价于运行：

```powershell
uvicorn agent_serving.serving.main:app --host 127.0.0.1 --port 8000
```

### 2. Dev 空库模式

如果没有设置 `COREMASTERKB_ASSET_DB_PATH`，服务会创建一个 in-memory SQLite，并通过共享 DDL 建表：

```powershell
python -m agent_serving.scripts.run_serving
```

这个模式没有 seed 数据，`/health` 可用，但 `/search` 会因为没有 active version 返回 503。

## API

### `GET /health`

健康检查：

```powershell
curl http://127.0.0.1:8000/health
```

返回：

```json
{"status":"ok","version":"0.1.0"}
```

### `POST /api/v1/search`

通用检索主入口。

最小请求：

```powershell
curl -X POST http://127.0.0.1:8000/api/v1/search `
  -H "Content-Type: application/json" `
  -d "{\"query\":\"ADD APN 怎么写\"}"
```

带显式 scope：

```json
{
  "query": "ADD APN 参数说明",
  "scope": {
    "products": ["CloudCore"],
    "product_versions": ["V100R023C10"],
    "network_elements": ["PGW-C"],
    "scenarios": ["coldstart"]
  }
}
```

带显式 entities：

```json
{
  "query": "这个命令怎么配置",
  "entities": [
    {"type": "command", "name": "ADD APN", "normalized_name": "ADD APN"}
  ]
}
```

显式传入的 `scope` 和 `entities` 优先级高于 Normalizer 从 query 中抽取的结果。

### `POST /api/v1/command-usage`

命令查询兼容入口。它会强制 intent 为 `command_usage`，但底层仍然走通用 QueryPlan 和 EvidencePack。

```json
{"query": "ADD APN 怎么写"}
```

如果 query 中识别不到命令，会返回 400。

## 返回结构：EvidencePack

Serving 不直接生成“最终答案”，而是返回证据包：

| 字段 | 含义 |
|---|---|
| `query` | 原始查询 |
| `intent` | 识别出的意图 |
| `normalized_query` | 归一化摘要字符串，方便调试 |
| `query_plan` | 执行计划 |
| `canonical_items` | L1 canonical 命中 |
| `evidence_items` | 可作为普通证据使用的 L0 raw segments |
| `sources` | evidence 对应的文档来源、章节、scope、处理状态 |
| `matched_entities` | 命中的实体 |
| `matched_scope` | 命中结果聚合出的 scope |
| `variants` | 因 scope 不充分或不匹配而未进入 evidence 的变体 |
| `conflicts` | `conflict_candidate`，永远不进入普通 evidence |
| `gaps` | 缺少的约束或存在的变体提示 |
| `suggested_followups` | 建议用户补充的问题 |
| `unparsed_documents` | 已登记但未解析出 raw_segments 的文档，用于 source audit |

典型使用方式：

- Agent 用 `evidence_items` 组织回答材料。
- Agent 用 `sources` 给出出处。
- Agent 发现 `variants/gaps` 时追问用户补充产品、版本、网元、场景等约束。
- Agent 发现 `conflicts` 时提示存在冲突候选，不把冲突内容当普通答案。
- Agent 做来源审计时查看 `unparsed_documents` 和 `processing_profile`。

## 查询执行流程

### 1. API 接收请求

文件：`serving/api/search.py`

`/search` 会：

1. 调用 `QueryNormalizer.normalize()`。
2. 合并请求中显式传入的 `scope/entities`。
3. 调用 `build_plan()` 生成 `QueryPlan`。
4. 调用 `_execute_plan()` 执行检索。

`/command-usage` 会：

1. 先执行 normalizer。
2. 要求识别到 `type=command` 的实体。
3. 强制 `intent=command_usage`。
4. 继续走 `_execute_plan()`。

### 2. Normalizer 做轻量理解

文件：

- `serving/application/normalizer.py`
- `serving/application/normalizer_config.py`

Normalizer 当前是规则实现，不调用 LLM。

它会抽取：

| 输出 | 说明 |
|---|---|
| `intent` | `command_usage`、`troubleshooting`、`concept_lookup`、`procedure`、`general` 等 |
| `entities` | 目前主要识别 command，后续可扩展 feature/term/alarm |
| `scope` | products、product_versions、network_elements |
| `keywords` | 去停用词后的关键词 |
| `desired_semantic_roles` | 根据 intent 给出偏好的 semantic_role |
| `missing_constraints` | 比如命令查询缺少 product 或 product_version |

默认配置在 `normalizer_config.py`：

| 配置 | 作用 |
|---|---|
| `DEFAULT_PRODUCTS` | 默认产品名 |
| `DEFAULT_NETWORK_ELEMENTS` | 默认网元 |
| `DEFAULT_VERSION_PATTERN` | 版本正则 |
| `DEFAULT_OP_MAP` | 中文操作词到命令前缀的映射 |
| `DEFAULT_INTENT_*_KEYWORDS` | 意图识别关键词 |
| `DEFAULT_STOPWORDS_ZH/EN` | 关键词停用词 |

可以通过环境变量指定 YAML 配置覆盖默认值：

```powershell
$env:NORMALIZER_CONFIG_PATH="D:\path\to\normalizer_config.yaml"
```

如果未设置，它会尝试读取项目根目录下的 `normalizer_config.yaml`。

### 3. QueryPlan 作为中间协议

文件：`serving/schemas/models.py`

`QueryPlan` 是 Normalizer 和 Repository 之间的稳定协议。M1 由规则生成，M2+ 可以替换成 LLM planner、ontology planner 或更复杂的查询规划器。

主要字段：

| 字段 | 作用 |
|---|---|
| `intent` | 查询意图 |
| `retrieval_targets` | 当前默认 `["canonical_segments"]` |
| `entity_constraints` | 实体约束 |
| `scope_constraints` | scope 约束 |
| `semantic_role_preferences` | 偏好的语义角色 |
| `block_type_preferences` | 偏好的结构类型 |
| `variant_policy` | 变体处理策略 |
| `conflict_policy` | 冲突处理策略 |
| `evidence_budget` | canonical 和 raw evidence 数量预算 |
| `expansion` | ontology/graph expansion 预留 |
| `keywords` | 关键词召回词 |

M1 的关键点：QueryPlan 已经存在，但 planner 本身仍是简单规则，不代表已经有复杂 Agent 推理。

### 4. Repository 只读资产库

文件：`serving/repositories/asset_repo.py`

`AssetRepository` 是唯一直接读 asset tables 的模块。

主要方法：

| 方法 | 作用 |
|---|---|
| `get_active_publish_version_id()` | 查询唯一 active publish version，返回 `(id, error)` |
| `search_canonical()` | 在 L1 `asset_canonical_segments` 中召回和排序 |
| `drill_down()` | 从 L1 通过 L2 下钻到 L0，分离 evidence、variants、conflicts |
| `get_unparsed_documents()` | 找出已登记但没有 raw_segments 的文档 |
| `get_conflict_sources()` | 单独读取某个 canonical 的 conflict candidates |

#### active version 规则

每次查询都必须先确认 active version：

| 情况 | 行为 |
|---|---|
| 0 个 active | API 返回 503 |
| 1 个 active | 正常查询 |
| 多个 active | API 返回 500，表示数据完整性错误 |

Serving 不自己选择“最新版本”，也不跨版本查询。版本切换由 Mining publish 生命周期控制。

#### L1 召回

`search_canonical()` 当前逻辑：

1. 取 entity names；如果没有 entity，就取 keywords。
2. 用 `asset_canonical_segments.search_text LIKE ?` 召回候选。
3. 召回数量大于最终数量，默认至少取 50 个候选。
4. 如果 `entity_refs_json` 有数据，则做实体过滤；没有则保留文本匹配路径。
5. 按 semantic_role / block_type 偏好重排。
6. 按关键词命中数、quality_score、variant penalty 打分截断。

这是 M1 的轻量检索方案，不是最终检索质量形态。

#### L2 下钻

`drill_down()` 读取：

```text
asset_canonical_segment_sources
  -> asset_raw_segments
  -> asset_raw_documents
```

并按 relation_type 分类：

| relation_type | 分类 |
|---|---|
| `primary` | 普通 evidence，前提是 scope 匹配 |
| `exact_duplicate` | 普通 evidence，前提是 scope 匹配 |
| `normalized_duplicate` | 普通 evidence，前提是 scope 匹配 |
| `near_duplicate` | 普通 evidence，前提是 scope 匹配 |
| `scope_variant` | scope 足够且匹配才进 evidence，否则进 variants |
| `conflict_candidate` | 永远进 conflicts，不进 evidence |

scope 匹配遵循容错读取原则：

- 支持 plural 和 singular JSON 字段，例如 `products/product`。
- 支持 `products/product_versions/network_elements/projects/domains/scenarios/authors`。
- 如果用户没有给 scope 约束，则不过滤。
- 如果用户显式约束了某个维度，而文档没有该维度，当前会保守地视为不匹配。

### 5. Assembler 组装 EvidencePack

文件：`serving/application/assembler.py`

`EvidenceAssembler` 把 repo 的 raw dict 转成 Pydantic 响应模型：

| 输入 | 输出 |
|---|---|
| canonical hits | `canonical_items` |
| evidence rows | `evidence_items` + `sources` |
| variant rows | `variants` + `gaps` |
| conflict rows | `conflicts` |
| normalized query | `matched_entities`、`matched_scope`、`normalized_query` |
| unparsed docs | `unparsed_documents` |

Assembler 还负责 JSON 容错解析：

- `entity_refs_json` 解析失败时返回空列表。
- `scope_json` 解析失败时返回空 `QueryScope`。
- `section_path` 支持字符串 JSON 和 list。
- `structure_json` 和 `source_offsets_json` 解析失败时返回空 dict。

## 数据库连接和 schema

文件：

- `serving/main.py`
- `serving/repositories/schema_adapter.py`

### 生产 / 联调模式

设置：

```powershell
$env:COREMASTERKB_ASSET_DB_PATH="D:\path\to\asset.sqlite"
```

Serving 会用只读 URI 打开：

```text
file:<db_path>?mode=ro
```

这意味着 Serving 不应修改 asset DB。如果 DB 不存在、没有 active version 或 schema 不匹配，请回到 Mining 或 `knowledge_assets` 侧处理。

### Dev / Test 空库模式

未设置 `COREMASTERKB_ASSET_DB_PATH` 时，Serving 创建 `:memory:` SQLite，并执行共享 DDL：

```text
knowledge_assets/schemas/001_asset_core.sqlite.sql
```

注意：这只建表，不插数据。

## 模型说明

文件：`serving/schemas/models.py`

### 请求模型

| 模型 | 用途 |
|---|---|
| `SearchRequest` | `/api/v1/search` 请求 |
| `CommandUsageRequest` | `/api/v1/command-usage` 请求 |

### 中间模型

| 模型 | 用途 |
|---|---|
| `EntityRef` | command/feature/term/alarm/network_element 等实体 |
| `QueryScope` | scope 约束 |
| `NormalizedQuery` | Normalizer 输出 |
| `QueryPlan` | Repository 执行计划 |
| `EvidenceBudget` | 结果数量预算 |
| `ExpansionConfig` | ontology/graph 扩展预留 |

### 响应模型

| 模型 | 用途 |
|---|---|
| `CanonicalItem` | L1 命中 |
| `EvidenceItem` | 可用于回答的 L0 证据 |
| `SourceRef` | evidence 来源 |
| `VariantInfo` | scope 变体 |
| `ConflictInfo` | 冲突候选 |
| `UnparsedDocument` | 已登记但未解析的文档 |
| `Gap` | 缺失约束或变体提示 |
| `EvidencePack` | 总响应 |

## 测试

运行 Serving 测试：

```powershell
python -m pytest agent_serving/tests -q
```

如果本机安装烟测或临时目录权限有问题，可以先排除安装烟测：

```powershell
python -m pytest agent_serving/tests -q --ignore=agent_serving/tests/test_install_smoke.py
```

常用测试文件：

| 文件 | 覆盖点 |
|---|---|
| `tests/test_health.py` | health endpoint |
| `tests/test_models.py` | Pydantic 模型序列化 |
| `tests/test_normalizer.py` | query 归一化和 QueryPlan |
| `tests/test_asset_repo.py` | L1/L2/L0 repository 读取和分类 |
| `tests/test_assembler.py` | EvidencePack 组装 |
| `tests/test_api_integration.py` | FastAPI 全链路 |
| `tests/test_schema_adapter.py` | 共享 SQLite DDL 加载 |
| `tests/test_mining_contract.py` | 读取真实 Mining 生成的 SQLite DB |
| `tests/conftest.py` | in-memory SQLite seed data |

## 当前 M1 边界和已知限制

当前 Serving 是 M1 通用 evidence retrieval 骨架，不是最终智能问答系统。

已知边界：

- 不做最终答案生成，只返回 evidence pack。
- 不做 embedding / vector search。
- 不做 rerank model。
- 不做 ontology / graph expansion。
- 不调用 LLM planner。
- Normalizer 仍是规则抽取，泛化能力有限。
- SQL 检索仍是 LIKE 召回，真实数据下召回质量依赖关键词和 `search_text`。
- Serving 必须容错读取 JSON，不能要求 Mining 一定写满所有 JSON 子字段。

## 和 Mining 的边界

Mining 做：

- 扫描输入文件夹。
- 解析 MD/TXT。
- 写入 raw/canonical/source mapping。
- 维护 publish version 生命周期。

Serving 做：

- 读取唯一 active version。
- 检索 canonical。
- 下钻 raw evidence。
- 分离 evidence / variants / conflicts / gaps。
- 返回 EvidencePack。

Serving 不做：

- 重新解析文档。
- 重新切片。
- 批量去重或归并。
- 写入 asset tables。
- 修改 publish version 状态。

## 开发入口速查

| 想改什么 | 优先看哪里 |
|---|---|
| 新增 API | `serving/api/` |
| 修改查询理解规则 | `serving/application/normalizer.py` |
| 调整产品/网元/意图配置 | `serving/application/normalizer_config.py` |
| 修改 QueryPlan 或响应结构 | `serving/schemas/models.py` |
| 修改检索召回和排序 | `serving/repositories/asset_repo.py` |
| 修改 evidence/variant/conflict/gap 组装 | `serving/application/assembler.py` |
| 修改 DB 初始化 | `serving/main.py`, `serving/repositories/schema_adapter.py` |
| 增加真实 Mining DB 契约测试 | `tests/test_mining_contract.py` |

