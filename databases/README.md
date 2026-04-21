# Databases

本目录统一放 CoreMasterKB 当前三类数据库契约。

## 目录结构

```text
databases/
  asset_core/         # Mining 写、Serving 读的知识资产库
  mining_runtime/     # Mining 自身运行态与断点续跑状态库
  agent_llm_runtime/  # 独立 LLM 服务运行态库
```

## 当前决定

### 1. 三个库逻辑上分开

当前正式设计不合并为一个总库。

原因：

1. `asset_core` 是发布后、可服务、相对稳定的知识资产。
2. `mining_runtime` 是挖掘过程状态，带有大量中间态、失败态、重试态。
3. `agent_llm_runtime` 是独立服务的任务队列、请求、attempt、结果和审计日志。

三者职责不同、生命周期不同、读写模式也不同。

### 2. Mining 涉及的两个 DB 不合并为正式设计

Mining 同时会碰到：

- `asset_core`
- `mining_runtime`

这两个库**逻辑上必须分开**，不建议把它们定义成一个正式数据库。

原因：

1. Serving 只应该看到发布后的资产，不应该看到 Mining 运行态噪音表。
2. `mining_runtime` 的写入频率、失败重试、清理策略和 `asset_core` 完全不同。
3. 后续如果要保留 active 资产包或做发布回退，`asset_core` 需要尽量稳定。

### 3. 物理层面的折中

如果将来为了本地开发方便，短期把 `asset_core` 和 `mining_runtime` 放进**同一个 SQLite 文件**，可以接受，但只应视为：

```text
dev / 单机调试便利
```

不能把这种做法当成正式架构基线，也不能影响表命名和职责边界。

## 当前推荐

| 数据库 | 正式建议 |
|---|---|
| `asset_core` | 单独数据库 |
| `mining_runtime` | 单独数据库 |
| `agent_llm_runtime` | 单独数据库，由 claude-llm 独立维护 |

如果只看 1.1 当前阶段，最稳妥的结论就是：

```text
逻辑分库必须坚持；
物理合库只允许作为 dev 便利，不作为正式设计。
```
