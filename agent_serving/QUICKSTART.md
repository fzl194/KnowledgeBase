# Agent Serving 快速上手指南

## 概述

Agent 知识检索服务，FastAPI 进程，端口 8000。
- 读取 Mining 产出的 Asset Core SQLite 数据库（只读）
- 唯一 `/search` 端点，返回 `ContextPack`
- 可插拔 Pipeline：Normalizer → QueryPlanner → RetrieverManager → Fusion → Reranker → Assembler
- 支持 FTS5 全文检索 + Graph 关系扩展
- Debug 模式可查看内部 Pipeline 状态

## 目录结构

```
agent_serving/
├── serving/
│   ├── main.py                 # FastAPI 入口，DB 连接管理
│   ├── api/
│   │   ├── health.py           # /health 健康检查
│   │   └── search.py           # /api/v1/search 主端点
│   ├── application/
│   │   ├── normalizer.py       # 查询归一化（规则 + LLM slot）
│   │   ├── normalizer_config.py # 归一化停用词/别名配置
│   │   ├── assembler.py        # ContextPack 组装
│   │   └── planner.py          # LLM Runtime HTTP client
│   ├── pipeline/
│   │   ├── retriever_manager.py # 多路召回管理 + 并发执行
│   │   ├── fusion.py           # IdentityFusion + RRFFusion
│   │   ├── reranker.py         # ScoreReranker（角色/块类型偏好 + 截断）
│   │   ├── query_planner.py    # QueryPlanner facade + RulePlannerProvider
│   │   └── llm_providers.py    # LLM 插件接口（Normalizer/Reranker/Planner）
│   ├── retrieval/
│   │   ├── retriever.py        # Retriever 抽象基类
│   │   ├── bm25_retriever.py   # FTS5 BM25 检索器
│   │   └── graph_expander.py   # 关系图 BFS 扩展器
│   ├── repositories/
│   │   ├── asset_repo.py       # Asset Core 数据访问（Active Scope / Source）
│   │   └── schema_adapter.py   # 建表 DDL（dev/test 模式用）
│   └── schemas/
│       ├── models.py           # 数据模型（SearchRequest / ContextPack / QueryPlan）
│       ├── constants.py        # 常量定义
│       └── json_utils.py       # 共享 JSON 解析工具
├── scripts/
│   └── run_serving.py          # 启动脚本
└── tests/                      # 测试
```

## 1. 安装依赖

在项目根目录执行：

```bash
pip install fastapi uvicorn aiosqlite pydantic
```

或者如果项目有 pyproject.toml：

```bash
pip install -e .
```

## 2. 配置数据库

Agent Serving 是只读服务，需要 Mining 产出的 SQLite 数据库文件。

### 环境变量

| 环境变量 | 必填 | 说明 |
|---------|------|------|
| `COREMASTERKB_ASSET_DB_PATH` | 是 | Mining 产出的 SQLite 数据库路径 |
| `AGENT_SERVING_HOST` | 否 | 监听地址，默认 `127.0.0.1` |
| `AGENT_SERVING_PORT` | 否 | 服务端口，默认 `8000` |

### 设置数据库路径

**Linux/macOS：**
```bash
export COREMASTERKB_ASSET_DB_PATH=/path/to/m1_realistic_asset.sqlite
```

**Windows (PowerShell)：**
```powershell
$env:COREMASTERKB_ASSET_DB_PATH = "D:\path\to\m1_realistic_asset.sqlite"
```

**Windows (CMD)：**
```cmd
set COREMASTERKB_ASSET_DB_PATH=D:\path\to\m1_realistic_asset.sqlite
```

### 数据库来源

数据库文件由 `knowledge_mining` 模块产出，典型路径：

```
data/m1_realistic_corpus/m1_realistic_asset.sqlite
data/m1_contract_corpus/m1_contract_asset.sqlite
```

确认数据库有数据：
```bash
sqlite3 data/m1_realistic_corpus/m1_realistic_asset.sqlite

# 检查 active release
SELECT id, channel, status FROM asset_releases WHERE status = 'active';

# 检查 retrieval units 数量
SELECT count(*) FROM asset_retrieval_units;

# 检查 raw segments 数量
SELECT count(*) FROM asset_raw_segments;

.quit
```

> **注意**：必须存在至少一个 `status = 'active'` 的 release，否则 `/search` 会返回 503。

## 3. 启动服务

```bash
# 方式一：直接启动
python -m agent_serving.scripts.run_serving

# 方式二：指定端口和监听地址
python -m agent_serving.scripts.run_serving --host 0.0.0.0 --port 8000

# 方式三：开发模式（自动重载）
python -m agent_serving.scripts.run_serving --reload
```

看到以下输出说明启动成功：

```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

### 验证启动

```bash
curl http://localhost:8000/health
# 返回：{"status":"ok"}
```

### 无数据库时启动（Dev 模式）

不设置 `COREMASTERKB_ASSET_DB_PATH` 时，服务会使用内存 SQLite 并自动建表。此时调用 `/search` 会返回 503（No active release），但可用于 API 格式验证和集成测试。

## 4. 搜索 API

### 基本搜索

```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "ADD APN"
  }'
```

### 带作用域过滤

```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "基站配置",
    "scope": {
      "products": ["LTE"],
      "scenarios": ["baseline"]
    }
  }'
```

### 带实体标注

```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "如何修改小区最大发射功率",
    "entities": [
      {"type": "parameter", "name": "最大发射功率"}
    ]
  }'
```

### Debug 模式

在请求中加 `"debug": true` 可以看到内部 Pipeline 状态：

```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "ADD APN",
    "debug": true
  }'
```

Debug 模式会在返回的 `debug` 字段中包含：
- `plan`：QueryPlan 完整配置（intent、keywords、retriever_config 等）
- `scope`：ActiveScope 信息（release_id、build_id、snapshot_ids）
- `candidate_count`：Rerank 后的候选数量
- `fusion_method`：使用的融合策略

## 5. 返回结构说明

### ContextPack 结构

```json
{
  "query": {
    "original": "ADD APN",
    "normalized": "add apn",
    "intent": "command_usage",
    "entities": [],
    "scope": {},
    "keywords": ["add", "apn"]
  },
  "items": [
    {
      "id": "ru-uuid-001",
      "kind": "retrieval_unit",
      "role": "seed",
      "text": "ADD APN: 用于新增APN配置...",
      "score": 0.92,
      "title": "APN配置命令",
      "block_type": "command_block",
      "semantic_role": "command",
      "source_id": "doc-uuid-001",
      "relation_to_seed": null,
      "source_refs": {"raw_segment_ids": ["seg-001", "seg-002"]},
      "metadata": {}
    }
  ],
  "relations": [
    {
      "id": "rel-001",
      "from_id": "ru-uuid-001",
      "to_id": "ru-uuid-002",
      "relation_type": "next",
      "distance": 1
    }
  ],
  "sources": [
    {
      "id": "doc-uuid-001",
      "document_key": "23501-k10",
      "title": "LTE 基站配置指南",
      "relative_path": "lte/config-guide.md",
      "scope_json": {"products": ["LTE"]},
      "metadata": {}
    }
  ],
  "issues": [],
  "suggestions": [],
  "debug": null
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `query` | ContextQuery | 查询信息（原始、归一化、意图、关键词） |
| `items` | ContextItem[] | 检索结果列表，每个 item 包含 text、score、role、source |
| `relations` | ContextRelation[] | 结果间的关系链（previous/next/same_section 等） |
| `sources` | SourceRef[] | 涉及的文档来源 |
| `issues` | Issue[] | 处理过程中的提示信息 |
| `suggestions` | string[] | 建议信息 |
| `debug` | dict/null | Debug 信息（仅 debug=true 时） |

### Item 的 role 字段

| role | 说明 |
|------|------|
| `seed` | 主召回结果 |
| `expanded` | 通过关系图扩展的结果 |
| `context` | 上下文补充 |

## 6. Postman 测试指南

### 步骤一：确认服务运行

1. 打开 Postman
2. 新建 GET 请求：`http://<服务器IP>:8000/health`
3. 应返回 `{"status": "ok"}`

### 步骤二：确认数据库有数据

在服务器上执行：
```bash
sqlite3 $COREMASTERKB_ASSET_DB_PATH \
  "SELECT count(*) FROM asset_releases WHERE status='active';"
```
结果应 >= 1。如果为 0，说明 Mining 还没有发布 release。

### 步骤三：搜索测试

1. 新建 POST 请求：`http://<服务器IP>:8000/api/v1/search`
2. Headers 添加：`Content-Type: application/json`
3. Body 选择 `raw` → `JSON`，填入：

```json
{
  "query": "ADD APN",
  "debug": true
}
```

4. 点击 Send，查看返回的 ContextPack

### 步骤四：验证不同查询类型

**命令类查询：**
```json
{"query": "ADD APN"}
```

**概念类查询：**
```json
{"query": "什么是小区功率控制"}
```

**参数类查询：**
```json
{"query": "PmaxMax 参数怎么配"}
```

**带 scope 过滤：**
```json
{
  "query": "基站配置",
  "scope": {"products": ["LTE"]}
}
```

### 步骤五：检查结果质量

重点关注：
1. `items` 是否有内容（空数组说明召回失败）
2. `items[0].score` 分数是否合理
3. `sources` 是否有对应的文档来源
4. `debug.scope.snapshot_ids` 是否非空（空说明 release/build 链路断了）

## 7. 通过数据库验证

```bash
sqlite3 data/m1_realistic_corpus/m1_realistic_asset.sqlite

# 1. 检查 release -> build -> snapshot 链路
SELECT r.id, r.channel, r.status, b.id as build_id
FROM asset_releases r
LEFT JOIN asset_builds b ON b.id = r.build_id
WHERE r.status = 'active';

# 2. 检查当前 build 的 snapshot
SELECT ds.id, ds.document_id, ds.selection_status
FROM asset_build_document_snapshots ds
WHERE ds.build_id = '<上面查到的build_id>'
  AND ds.selection_status = 'active';

# 3. 检查 retrieval units
SELECT ru.id, ru.block_type, ru.semantic_role, substr(ru.canonical_text, 1, 80)
FROM asset_retrieval_units ru
WHERE ru.document_snapshot_id IN (
  SELECT id FROM asset_build_document_snapshots
  WHERE build_id = '<build_id>' AND selection_status = 'active'
)
LIMIT 10;

# 4. 检查 FTS 索引是否正常
SELECT ru.id, rank
FROM asset_retrieval_units ru
JOIN asset_retrieval_units_fts fts ON fts.rowid = ru.rowid
WHERE asset_retrieval_units_fts MATCH '"add apn"'
LIMIT 5;

# 5. 检查关系数据
SELECT count(*), relation_type
FROM asset_raw_segment_relations
GROUP BY relation_type;

.quit
```

## 8. Pipeline 架构

### 处理流程

```
SearchRequest
    │
    ▼
┌──────────┐  规则归一化（LLM slot 预留）
│ Normalizer │  → NormalizedQuery
└──────────┘
    │
    ▼
┌──────────┐  RulePlannerProvider（LLMPlannerProvider slot 预留）
│ Planner  │  → QueryPlan
└──────────┘
    │
    ▼
┌──────────┐  release → build → snapshots
│ ActiveScope│  → ActiveScope
└──────────┘
    │
    ▼
┌──────────────┐  并发多路召回，当前仅 fts_bm25
│ RetrieverMgr  │  → RetrievalCandidate[]
└──────────────┘
    │
    ▼
┌──────────┐  IdentityFusion（单路）/ RRFFusion（多路）
│ Fusion   │  → RetrievalCandidate[]（去重）
└──────────┘
    │
    ▼
┌──────────┐  ScoreReranker：角色偏好 + 预算截断
│ Reranker │  → RetrievalCandidate[]（排序）
└──────────┘
    │
    ▼
┌──────────┐  组装 ContextPack：source 下钻 + graph 扩展
│ Assembler│  → ContextPack
└──────────┘
```

### 当前实现 vs 演进方向

| Pipeline 阶段 | 当前实现 | 演进方向 |
|--------------|---------|---------|
| Normalizer | 规则归一化（停用词、别名表） | LLM 归一化（意图识别、实体提取） |
| QueryPlanner | RulePlannerProvider | LLMPlannerProvider（LLM 生成 QueryPlan） |
| Retriever | FTS5 BM25 单路 | + Vector Retriever（向量召回） |
| Fusion | IdentityFusion | RRFFusion（多路 RRF 融合） |
| Reranker | ScoreReranker（规则偏好） | LLM Reranker / CrossEncoder |
| GraphExpander | BFS 关系扩展（已实现） | 同当前，性能优化 |
| LLM 接入 | 无（slot 已预留） | 通过 LLMClient Protocol 统一接入 agent_llm_runtime |

## 9. 常见问题

### Q: 启动后 /search 返回 503 "No active release"

数据库中没有 `status = 'active'` 的 release。检查：
1. `COREMASTERKB_ASSET_DB_PATH` 指向的文件是否正确
2. Mining 是否已完成发布流程（`publish` 阶段）
3. 执行 `sqlite3 <db> "SELECT count(*) FROM asset_releases WHERE status='active'"` 确认

### Q: /search 返回空 items（200 但 items=[]）

1. 检查 FTS 索引是否正常：`sqlite3 <db> "SELECT count(*) FROM asset_retrieval_units_fts"`
2. 检查 retrieval units 是否在 active snapshot 下
3. 尝试换一个查询词，确认不是查询问题
4. 打开 debug 模式查看 `debug.candidate_count`，如果为 0 说明召回阶段就没结果

### Q: 返回 500 "Data integrity error: multiple active releases"

同一个 channel 有多个 active release，属于数据完整性错误。修复：
```sql
-- 查看当前 active releases
SELECT id, channel FROM asset_releases WHERE status = 'active';

-- 保留最新一个，其余改为 archived
UPDATE asset_releases SET status = 'archived' WHERE id != '<要保留的id>' AND status = 'active';
```

### Q: 返回 422 Unprocessable Entity

请求体格式不对。确认：
1. Content-Type 是 `application/json`
2. Body 包含必填字段 `query`（字符串）
3. `scope` 和 `entities` 是可选的，格式参考上面的示例

### Q: 中文查询召回率低

FTS5 中文分词依赖 Mining 端的 jieba 分词。如果 Mining 没有正确配置分词器，中文短查询可能召回不理想。可以：
1. 用更完整的中文短语查询
2. 在 debug 模式下查看 `query.keywords` 确认分词结果

### Q: 如何在远程服务器上部署

```bash
# 1. 上传代码和数据库到服务器
scp -r agent_serving/ user@server:/path/to/project/
scp data/m1_realistic_asset.sqlite user@server:/path/to/data/

# 2. 在服务器上设置环境变量
export COREMASTERKB_ASSET_DB_PATH=/path/to/data/m1_realistic_asset.sqlite

# 3. 启动（监听所有网卡）
python -m agent_serving.scripts.run_serving --host 0.0.0.0 --port 8000

# 4. 从本地用 Postman 测试
# POST http://<server-ip>:8000/api/v1/search
```

### Q: API 文档

服务启动后访问：`http://localhost:8000/docs`（Swagger UI）
