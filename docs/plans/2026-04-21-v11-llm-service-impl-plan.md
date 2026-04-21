# v1.1 LLM Service 实现计划

> 任务：TASK-20260421-v11-agent-llm-runtime
> 版本：v1.1
> 日期：2026-04-21
> 作者：Claude LLM
> 状态：待审查

## 1. 目标

从零建设独立的 LLM Service，统一承接 Mining / Serving 的模型调用需求。

核心定位：**统一调用与审计的 LLM 能力平台**，不嵌入业务逻辑。

## 2. 交付形态

**独立 FastAPI 服务进程**，与 Mining / Serving 平级。

```text
llm_service/              # 独立服务包
databases/agent_llm_runtime/  # 独立数据库（表前缀保持 agent_llm_*）
```

Mining / Serving 通过 HTTP API 调用，不直接操作 LLM 数据库。

## 3. 目录结构

```text
llm_service/
├── __init__.py
├── main.py                    # FastAPI 应用入口 + uvicorn 启动
├── config.py                  # 配置管理（provider / DB path / 服务端口）
├── client.py                  # 正式 Client（Mining/Serving 接入的唯一推荐方式）
├── db.py                      # agent_llm_runtime SQLite 连接与 DDL 初始化
├── models.py                  # Pydantic 模型（请求/响应/内部实体）
│
├── runtime/                   # 核心运行时逻辑
│   ├── __init__.py
│   ├── service.py             # LLMService 主类（编排 task -> request -> attempt -> result）
│   ├── task_manager.py        # task 生命周期：submit / claim / complete / fail / cancel
│   ├── executor.py            # provider 调用 + attempt 管理 + 重试逻辑
│   ├── parser.py              # 输出解析 + JSON schema 校验
│   ├── event_bus.py           # 事件记录（agent_llm_events 写入）
│   └── idempotency.py         # 幂等控制（idempotency_key 去重）
│
├── providers/                 # LLM provider 抽象层
│   ├── __init__.py
│   ├── base.py                # ProviderProtocol 定义
│   ├── openai_compatible.py   # OpenAI-compatible provider（支持自定义 URL/KEY/Header）
│   └── mock.py                # 测试用 mock provider
│
├── templates/                 # Prompt template 管理
│   ├── __init__.py
│   └── registry.py            # template CRUD + 版本管理
│
├── api/                       # HTTP API 层
│   ├── __init__.py
│   ├── tasks.py               # task 提交 / 查询 / 取消
│   ├── templates.py           # prompt template 管理
│   ├── results.py             # 结果查询
│   ├── health.py              # 健康检查
│   └── dashboard.py           # 看板数据 API
│
├── dashboard/                 # 可视化看板
│   ├── __init__.py
│   ├── views.py               # Jinja2 页面渲染
│   └── templates/             # HTML 模板
│       ├── base.html
│       ├── index.html         # 总览页
│       ├── tasks.html         # 任务列表页
│       ├── task_detail.html   # 单任务详情（含 attempt 历史）
│       ├── templates_mgmt.html # 模板管理页
│       └── components/        # 可复用组件
│           ├── navbar.html
│           ├── task_table.html
│           └── stats_cards.html
│
├── static/                    # 静态资源
│   └── css/
│       └── dashboard.css
│
└── tests/                     # 测试
    ├── __init__.py
    ├── conftest.py            # 共享 fixture（test DB、mock provider）
    ├── test_service.py        # LLMService 集成测试
    ├── test_task_manager.py   # task 生命周期测试
    ├── test_executor.py       # provider 调用 + 重试测试
    ├── test_parser.py         # 输出解析 + schema 校验测试
    ├── test_idempotency.py    # 幂等提交测试
    ├── test_api.py            # API 端点测试
    ├── test_templates.py      # template 管理测试
    └── test_dashboard.py      # 看板 API 测试
```

## 4. API 设计

### 4.1 Task 管理

```text
POST   /api/v1/tasks                  # 提交 LLM task
GET    /api/v1/tasks/{task_id}        # 查询 task 状态
GET    /api/v1/tasks                  # 列表查询（支持 status / caller_domain 筛选）
POST   /api/v1/tasks/{task_id}/cancel # 取消 task
```

#### 提交 task 请求体

```json
{
  "caller_domain": "mining",
  "pipeline_stage": "summary_generation",
  "template_key": "section-summary-v1",
  "input": {
    "section_title": "MML命令概述",
    "section_text": "..."
  },
  "params": {
    "temperature": 0.3,
    "max_tokens": 512
  },
  "ref_type": "raw_segment",
  "ref_id": "seg-001",
  "build_id": "build-001",
  "release_id": null,
  "idempotency_key": "mining:summary:seg-001:v1",
  "max_attempts": 3
}
```

#### 提交 task 响应体

```json
{
  "task_id": "task-uuid",
  "status": "queued",
  "idempotency_key": "mining:summary:seg-001:v1",
  "created_at": "2026-04-21T10:00:00Z"
}
```

### 4.2 同步执行（简化接口）

```text
POST   /api/v1/execute                # 提交并同步等待结果
```

用于 Mining/Serving 的在线增强场景（query rewrite 等），内部走 task -> execute -> return result 流程，但不要求调用方轮询。

响应体直接返回解析后的结果：

```json
{
  "task_id": "task-uuid",
  "status": "succeeded",
  "result": {
    "parse_status": "succeeded",
    "parsed_output": { "summary": "..." },
    "confidence": 0.92
  },
  "attempts": 1,
  "total_tokens": 350,
  "latency_ms": 1200
}
```

### 4.3 Result 查询

```text
GET    /api/v1/tasks/{task_id}/result  # 查询 task 最终结果
GET    /api/v1/tasks/{task_id}/attempts # 查询 task 的所有 attempt
GET    /api/v1/tasks/{task_id}/events   # 查询 task 的事件流
```

### 4.4 Template 管理

```text
POST   /api/v1/templates              # 创建 prompt template
GET    /api/v1/templates              # 列表查询
GET    /api/v1/templates/{key}/{version} # 查询特定版本
PATCH  /api/v1/templates/{key}/{version}/status # 更新状态（draft/active/archived）
```

### 4.5 Dashboard API

```text
GET    /api/v1/dashboard/stats        # 总览统计
GET    /api/v1/dashboard/token-usage  # Token 消耗统计
GET    /api/v1/dashboard/latency      # 延迟统计
```

### 4.6 看板页面

```text
GET    /dashboard/                    # 总览页
GET    /dashboard/tasks               # 任务列表
GET    /dashboard/tasks/{task_id}     # 任务详情
GET    /dashboard/templates           # 模板管理
```

## 5. 核心流程

### 5.1 唯一执行引擎

**铁律：系统中只有一条执行路径。**

`/api/v1/tasks`（异步）和 `/api/v1/execute`（同步）共享完全相同的内部引擎：

```text
task_manager.submit()  →  executor.run()  →  parser.parse()  →  event_bus.emit()
```

区别仅在调用方接口层面：

| 入口 | 调用方行为 | 内部路径 |
|------|-----------|---------|
| POST /tasks | 提交后立即返回 task_id，调用方自行轮询 | submit → 后台 worker claim → run |
| POST /execute | 提交后阻塞等待，直到完成或超时直接返回结果 | submit → **同一 worker** 同步 run → 返回 |

`/execute` **不是**第二条执行引擎。它必须落 task / request / attempt / result / event 全套记录。
不允许为同步场景绕过 task_manager / executor 单独写 provider 调用逻辑。

### 5.2 Worker 调度规则

#### v1 调度模型

v1 是**单进程 FastAPI 服务**。后台 worker 是 asyncio Task，不是分布式进程。
`lease_expires_at` 的作用是**崩溃恢复**，不是多节点并发控制。

#### claim 规则

```text
worker 挑任务条件：
  status = 'queued'
  AND available_at <= now
  ORDER BY priority DESC, created_at ASC
  LIMIT 1
```

单进程内调度器串行 claim，不存在多 worker 竞争问题。

claim 时更新：
```text
status         = 'running'
started_at     = now
lease_expires_at = now + lease_duration（默认 300 秒）
```

#### 租约与崩溃恢复

```text
租约设置时机：claim 时设置 lease_expires_at = now + 300s
租约续租：v1 不续租。单进程内 task 要么跑完要么进程挂掉。
崩溃恢复：服务启动时，扫描 status='running' AND lease_expires_at < now 的 task：
  -> attempt_count < max_attempts：status='queued', available_at=now（允许重试）
  -> attempt_count >= max_attempts：status='dead_letter'（不再重试）
  -> 写 event（recovered）
```

#### retry 与 available_at

```text
attempt 失败后：
  -> attempt_count < max_attempts：
       task 保持 status='queued'
       available_at = now + backoff（指数退避：2^attempt_no * base，上限 60s）
       写 event（retried）
  -> attempt_count >= max_attempts：
       task status='dead_letter'
       写 event（dead_letter）
```

### 5.3 异步 Task 流程（Mining 批量场景）

```text
调用方 POST /api/v1/tasks
  -> idempotency 检查（见 5.5）
  -> 创建 agent_llm_tasks（status=queued, available_at=now）
  -> 创建 agent_llm_requests（展开 template + input）
  -> 写 agent_llm_events（submitted）
  -> 返回 task_id

后台 worker claim task（见 5.2 pick 规则）
  -> 更新 task（status=running, started_at, lease_expires_at）
  -> 写 event（claimed）
  -> 创建 agent_llm_attempts（attempt_no=N）
  -> 调用 provider
    -> 成功：
      -> 更新 attempt（status=succeeded, raw_output_text, tokens, latency）
      -> 解析输出（parser.py）
      -> 创建 agent_llm_results
      -> 更新 task（status=succeeded, finished_at）
      -> 写 event（succeeded）
    -> 失败：
      -> 更新 attempt（status=failed/timeout/rate_limited, error_type, error_message）
      -> 写 event（retried）
      -> 如 attempt_count < max_attempts：task 回 queued，设置 available_at
      -> 否则：task status=dead_letter，写 event（dead_letter）
```

### 5.4 同步 Execute 流程（Serving 在线场景）

```text
调用方 POST /api/v1/execute
  -> 调用 task_manager.submit()（同一条入口）
  -> 调用 executor.run()（同一条执行路径）
  -> 阻塞等待直到 task 终态（succeeded/failed/dead_letter）或超时
  -> 超时时：task 保持 running 状态（交给 lease recovery），返回超时响应
  -> 正常完成：直接返回结果
```

注意：execute 超时不取消 task。task 可能仍在后台执行中。
调用方如果想取消，应调用 POST /tasks/{id}/cancel。

### 5.5 幂等规则

#### 语义定义

**idempotency_key 保证的是"成功结果复用"，不是"逻辑请求唯一"。**

含义：
- 如果同 key 已有 succeeded 的 task → 调用方直接拿到已有结果，不会重复执行
- 如果同 key 已有 running 的 task → 调用方拿到已有 task_id，不会重复提交
- 如果同 key 只有 failed/dead_letter 的 task → 允许新建 task（允许重试）

#### 同 key 多条 task 共存时的查询优先级

```text
查 agent_llm_tasks WHERE idempotency_key = ? ORDER BY：

优先级 1：status='succeeded' 的最新一条（created_at DESC）
优先级 2：status='running' 的最新一条
优先级 3：无（允许新建）

注意：status='failed'/'dead_letter'/'cancelled'/'queued' 的记录不影响判定。
```

#### 调用方行为总结

| 场景 | 返回 |
|------|------|
| 首次提交（无同 key task） | 新 task，status=queued |
| 已有 succeeded 的同 key task | 已有 task_id + result（不重新执行） |
| 已有 running 的同 key task | 已有 task_id（不重复提交） |
| 已有 failed/dead_letter 但无 succeeded/running | 新 task，status=queued（允许重试） |
| 已有 succeeded 和 failed 共存 | 返回 succeeded 的结果（忽略 failed） |

## 6. Provider 设计

### 6.1 ProviderProtocol

```python
class ProviderProtocol(Protocol):
    async def complete(
        self,
        messages: list[dict],
        params: dict,
    ) -> ProviderResponse: ...

    @property
    def provider_name(self) -> str: ...
    @property
    def default_model(self) -> str: ...
```

### 6.2 OpenAI-compatible Provider

配置通过环境变量或 config 文件：

```yaml
providers:
  default:
    base_url: "https://api.openai.com/v1"
    api_key: "${OPENAI_API_KEY}"
    model: "gpt-4o"
    headers: {}
    timeout: 30
    max_retries: 0          # Runtime 自己管理重试，provider 层不重试
```

关键特性：
- `base_url` 可指向任意 OpenAI 兼容端点（Azure OpenAI、vLLM、Ollama 等）
- `api_key` 支持环境变量引用
- `headers` 支持用户自定义（X-Custom-Auth 等）
- provider 层不管理重试，由 runtime executor 统一控制

### 6.3 Mock Provider

测试用，返回预设响应，不发起真实 HTTP 请求。

## 7. 输出解析与 Schema 校验

### 7.1 解析流程

```text
raw_output_text
  -> 按 expected_output_type 解析（json_object / json_array / text）
  -> json_object / json_array：JSON.parse
  -> text：直接保留
  -> 解析失败：parse_status=failed, parse_error 记录
```

### 7.2 Schema 校验

```text
parsed_output
  -> 对照 output_schema_json（JSON Schema draft-07）校验
  -> 校验通过：parse_status=succeeded
  -> 校验失败：parse_status=schema_invalid, validation_errors_json 记录
```

注意：schema_invalid 不等于 task failed。task status 仍为 succeeded（provider 调用成功），但 result 中 parse_status 标记了 schema 问题。由调用方决定如何处理。

## 8. 配置管理

```python
# config.py
class LLMServiceConfig:
    # 服务配置
    host: str = "0.0.0.0"
    port: int = 8900

    # 数据库
    db_path: str = "data/llm_service.sqlite"

    # Provider
    provider_base_url: str = "https://api.openai.com/v1"
    provider_api_key: str = ""
    provider_model: str = "gpt-4o"
    provider_headers: dict = {}
    provider_timeout: int = 30

    # Worker
    worker_concurrency: int = 4
    default_max_attempts: int = 3
    retry_backoff_base: float = 2.0     # 指数退避基数（秒）
    retry_backoff_max: float = 60.0     # 最大退避时间

    # 同步执行超时
    execute_timeout: int = 60
```

配置来源优先级：环境变量 > .env 文件 > 默认值。

## 9. Dashboard 看板

### 9.1 页面结构

**总览页** (`/dashboard/`)
- 状态分布卡片（queued / running / succeeded / failed / dead_letter）
- 今日调用量 + 成功率
- Token 消耗趋势（最近 7 天）
- 按 caller_domain 分组的调用统计
- 最近 20 条任务快照

**任务列表页** (`/dashboard/tasks`)
- 可按 status / caller_domain / pipeline_stage 筛选
- HTMX 动态刷新
- 点击进入任务详情

**任务详情页** (`/dashboard/tasks/{task_id}`)
- 任务基本信息 + 调用方上下文
- 所有 attempt 记录（时间线视图）
- 原始输出 / 解析结果 / 错误信息（可展开）
- 事件流（时间线）

**模板管理页** (`/dashboard/templates`)
- Prompt template 列表
- 版本管理
- 状态切换（draft / active / archived）

### 9.2 技术实现

- 服务端：Jinja2 模板渲染
- 交互：HTMX（动态局部刷新，无需 SPA 框架）
- 样式：简洁 CSS（无外部依赖）
- 数据获取：直接读 `agent_llm_runtime` DB

## 10. Runtime Client（正式交付项）

### 10.1 定位

`llm_service/client.py` 是 Mining / Serving 接入 LLM Runtime 的**唯一推荐方式**。
不鼓励调用方直接用 httpx 拼 HTTP 请求。

### 10.2 文件位置

```text
llm_service/
├── client.py          # 正式 client
```

Mining / Serving 通过 `from llm_service.client import LLMClient` 使用。
v1 三个模块在同一仓库同一 Python 环境，直接 import。

### 10.3 Client 接口

```python
class LLMClient:
    def __init__(self, base_url: str = "http://localhost:8900", timeout: int = 60): ...

    async def submit_task(
        self,
        *,
        caller_domain: str,
        pipeline_stage: str,
        template_key: str | None = None,
        input: dict | None = None,
        messages: list[dict] | None = None,
        params: dict | None = None,
        expected_output_type: str = "json_object",
        output_schema: dict | None = None,
        ref_type: str | None = None,
        ref_id: str | None = None,
        build_id: str | None = None,
        release_id: str | None = None,
        idempotency_key: str | None = None,
        max_attempts: int = 3,
        priority: int = 100,
    ) -> TaskSubmitResponse:
        """提交异步 task，立即返回 task_id。"""
        ...

    async def execute(
        self,
        *,
        caller_domain: str,
        pipeline_stage: str,
        template_key: str | None = None,
        input: dict | None = None,
        messages: list[dict] | None = None,
        params: dict | None = None,
        expected_output_type: str = "json_object",
        output_schema: dict | None = None,
        ref_type: str | None = None,
        ref_id: str | None = None,
        build_id: str | None = None,
        release_id: str | None = None,
        idempotency_key: str | None = None,
        max_attempts: int = 3,
        timeout: int | None = None,
    ) -> ExecuteResponse:
        """同步执行，阻塞返回结果。"""
        ...

    async def get_task(self, task_id: str) -> TaskDetail:
        """查询 task 状态。"""
        ...

    async def get_result(self, task_id: str) -> TaskResult:
        """查询 task 最终结果。"""
        ...

    async def get_attempts(self, task_id: str) -> list[AttemptDetail]:
        """查询 task 的所有 attempt。"""
        ...

    async def cancel_task(self, task_id: str) -> None:
        """取消 task。"""
        ...
```

### 10.4 响应模型

```python
@dataclass
class TaskSubmitResponse:
    task_id: str
    status: str            # queued | running（幂等命中时）
    idempotency_key: str | None
    created_at: str

@dataclass
class ExecuteResponse:
    task_id: str
    status: str            # succeeded | failed | timeout
    result: ParsedResult | None
    attempts: int
    total_tokens: int | None
    latency_ms: int | None
    error: ErrorInfo | None

@dataclass
class ParsedResult:
    parse_status: str      # succeeded | failed | schema_invalid
    parsed_output: dict | list | None
    text_output: str | None
    confidence: float | None
    validation_errors: list[str]

@dataclass
class ErrorInfo:
    error_type: str
    error_message: str
```

### 10.5 Client 层职责

| 职责 | 说明 |
|------|------|
| HTTP 连接管理 | 复用 httpx.AsyncClient，连接池 |
| HTTP 超时 | 区分连接超时 / 读取超时 |
| HTTP 重试 | 网络级重试（5xx、连接失败），不是 LLM 级重试 |
| 错误映射 | HTTP 状态码 → 统一异常类 |
| 响应解析 | JSON → 类型安全的 dataclass |
| 语义透明 | 不改变 task/exeucte 的语义，只是封装传输层 |

### 10.6 Mining 接入示例

```python
from llm_service.client import LLMClient

llm = LLMClient(base_url="http://localhost:8900")

async def generate_section_summary(section_title: str, section_text: str) -> dict | None:
    resp = await llm.execute(
        caller_domain="mining",
        pipeline_stage="summary_generation",
        template_key="section-summary-v1",
        input={"section_title": section_title, "section_text": section_text},
        params={"temperature": 0.3},
        ref_type="raw_segment",
        ref_id="seg-001",
    )
    if resp.status == "succeeded" and resp.result:
        return resp.result.parsed_output
    return None
```

### 10.7 Serving 接入示例

```python
from llm_service.client import LLMClient

llm = LLMClient(base_url="http://localhost:8900")

async def rewrite_query(original_query: str) -> str:
    resp = await llm.execute(
        caller_domain="serving",
        pipeline_stage="query_rewrite",
        template_key="query-rewrite-v1",
        input={"original_query": original_query},
        params={"temperature": 0.1},
    )
    if resp.status == "succeeded" and resp.result and resp.result.parsed_output:
        return resp.result.parsed_output.get("rewritten_query", original_query)
    return original_query  # fallback
```

## 11. 实现分阶段

### Phase 1: 骨架与核心链路（T1-T6）

| Task | 内容 | 产出 |
|------|------|------|
| T1 | 项目骨架：目录结构 + config + db + main.py | 服务可启动，DB 可初始化 |
| T2 | models.py：Pydantic 模型定义 | 请求/响应/内部数据模型 |
| T3 | provider 抽象层 + OpenAI-compatible + Mock | provider 可调用 |
| T4 | task_manager：task 生命周期管理 | submit/claim/complete/fail |
| T5 | executor：provider 调用 + attempt + 重试 | 完整执行链路 |
| T6 | parser：输出解析 + schema 校验 | result 可落库 |

### Phase 2: API 层、幂等与 Client（T7-T10）

| Task | 内容 | 产出 |
|------|------|------|
| T7 | API 端点：tasks + execute + results + health | HTTP 接口可用 |
| T8 | idempotency：幂等提交控制（5.5 规则实现） | 重复提交安全 |
| T9 | template registry：prompt template CRUD | 模板可管理 |
| T10 | client.py：正式 Client 封装 | Mining/Serving 接入的唯一推荐方式 |

### Phase 3: Dashboard 看板（T11-T12）

| Task | 内容 | 产出 |
|------|------|------|
| T11 | Dashboard 后端：views + API | 页面数据可获取 |
| T12 | Dashboard 前端：HTML + HTMX + CSS | 可视化看板可用 |

### Phase 4: 测试与文档（T13-T14）

| Task | 内容 | 产出 |
|------|------|------|
| T13 | 全量测试：task 提交、attempt 重试、结果解析、schema 校验、失败记录、上下文透传、client | 覆盖率 >= 80% |
| T14 | README + 接入文档 | 使用说明 |

## 12. 不在范围内

- 不直接写 `asset_core` 表
- 不嵌入 Mining / Serving 业务逻辑
- 不做多 provider 负载均衡（第一版只有 default provider）
- 不做 embedding / vector 调用
- 不做流式输出（第一版只做完整响应）
- 不做用户认证（第一版内网服务）

## 13. 已知风险

1. **DB 表前缀与服务名不一致**：DB 表前缀为 `agent_llm_*`，服务名为 `llm_service`。代码中需明确说明映射关系，不影响功能。
2. **同步 execute 的超时控制**：超时不取消 task，task 可能仍在后台执行。调用方需理解 execute 超时 ≠ task 失败。
3. **SQLite 并发写入**：v1 单进程，asyncio worker 串行调度，不存在写入冲突。但 SQLite 需启用 WAL 模式以支持 API 请求与 worker 的读写并发。
4. **client 与服务同仓库**：v1 client 通过 `from llm_service.client import LLMClient` 使用。如果未来拆仓库，client 需要单独抽包。
