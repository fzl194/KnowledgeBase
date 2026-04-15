# TEAM.md

> 本文件是 Claude Code、Codex 和管理员三方共享的团队协议。所有 Agent 必须遵守。

## 1. 目标

本协议只解决三件事：

1. 三方如何分工
2. 文件由谁负责、谁可以修改
3. 多人并行协作时如何避免文档和 Git 冲突

个人行为偏好、个人输出风格、个人审查习惯，不写在这里，分别写入 `CLAUDE.md` 和 `AGENTS.md`。

## 2. 默认角色

- 管理员：负责任务编排、优先级、范围裁剪、流程监督、共享规则维护。
- Claude Code：负责需求澄清、实现计划、代码修改、验证、交付。
- Codex：负责审查、风险分析、回归排查、设计质疑、分析文档输出。

若用户在某个任务中重新分配职责，以用户指令为准。

## 3. 任务分级

| 级别 | 适用场景 | 最低产物 |
|---|---|---|
| 轻量 | 小修复、配置调整、快速问答 | `COLLAB_TASKS.md` 登记 + 必要时消息记录 |
| 标准 | 功能开发、API 变更、插件扩展 | `COLLAB_TASKS.md` + plan + review |
| 正式 | 架构调整、跨模块重构、数据结构变更 | `COLLAB_TASKS.md` + plan + handoff + review + fix（如需） |

## 4. 执行流程

非琐碎任务默认按以下顺序执行：

1. 在 `COLLAB_TASKS.md` 创建任务记录并分配 `task-id`
2. 管理员确认优先级、级别、协作方式
3. Claude 产出或更新 plan
4. Claude 实现代码并验证
5. Claude 交接给 Codex
6. Codex 审查并产出 review
7. 如有问题，Claude 修复并产出 fix
8. Codex 确认闭环
9. Claude 面向用户最终交付

轻量任务可省略正式文档，但仍应登记任务并保留必要消息记录。

## 5. 文件归属

### 5.1 独占文件

| 路径模式 | 归属方 | 规则 |
|---|---|---|
| `CLAUDE.md` | Claude | 仅 Claude 维护 |
| `AGENTS.md` | Codex | 仅 Codex 维护 |
| `docs/plans/*` | Claude | 仅 Claude 创建和修改 |
| `docs/handoffs/*claude-handoff.md` 初始内容 | Claude | Codex 不改初始正文 |
| `docs/handoffs/*claude-fix.md` | Claude | 仅 Claude 创建和修改 |
| `docs/analysis/*-codex-review.md` | Codex | 仅 Codex 创建和修改 |
| `docs/admin/*` | 管理员 | 仅管理员创建和修改 |
| `backend/`、`frontend/` | Claude | Codex 不直接改代码；管理员如改需留痕 |

### 5.2 共享文件

| 文件 | 用途 | 写入方式 |
|---|---|---|
| `TEAM.md` | 团队共享规则 | 管理员主维护，其他人提出修改建议后再改 |
| `COLLAB_TASKS.md` | 任务索引 | 多方共享，但按字段分权 |
| `AGENT_MESSAGES.md` | 消息索引 / 最近消息摘要 | 多方共享，只追加摘要，不写完整对话 |
| `docs/messages/<task-id>.md` | 单任务对话记录 | 多方共享，只追加，不改历史正文 |

### 5.3 管理员文档

管理员文档路径约定：

- `docs/admin/YYYY-MM-DD-<topic-slug>-admin-note.md`

建议至少包含：

- 背景
- 决策事项
- 影响范围
- 相关任务或文档
- 直接执行的操作
- 需要 Claude 或 Codex 跟进的事项

## 6. 共享文件并发规则

这是避免多人同时编辑同一文件导致信息错误的核心规则。

### 6.1 `COLLAB_TASKS.md`

每个任务只有一条记录。字段按职责分权：

- Claude 可更新：
  - `计划文档`
  - `交接文档`
  - `修复文档`
- Codex 可更新：
  - `审查文档`
- 管理员可更新：
  - `状态`
  - `当前阶段`
  - `备注`
  - 任务级决策说明
- 三方都可更新：
  - `最新消息`
  - 自己名字对应的责任字段

禁止：

- 同时重写整条任务记录
- 覆盖他人刚刚更新的字段
- 为同一任务创建多条记录

### 6.2 `AGENT_MESSAGES.md`

`AGENT_MESSAGES.md` 不再承担完整留言板职责，只作为“消息索引 / 最近消息摘要”。

规则：

- 只追加一行摘要
- 不写长消息正文
- 每条摘要必须指向 `docs/messages/<task-id>.md`
- 消息 ID 使用时间戳 + 发送方，避免撞号

推荐格式：

```md
- MSG-20260402-153012-codex | task-id | From: Codex | To: Claude | 类型 | 详情见 docs/messages/<task-id>.md
```

### 6.3 `docs/messages/<task-id>.md`

这是正式的“任务级对话文件”，替代单一根目录留言板。

规则：

- 一个任务一个文件
- 只追加，不修改历史消息正文
- 如需修正，新增 follow-up
- 每条消息必须带时间、From、To、类型
- 长沟通优先写这里，不写到 `AGENT_MESSAGES.md`

### 6.4 handoff 状态流转

为了保证 Claude 与 Codex 的协作闭环可追踪，`docs/handoffs/*claude-handoff.md` 需要保留明确状态流转：

- Claude 创建 handoff 时，状态标记为：`待 Codex 审查`
- Codex 完成审查后，状态更新为：`已审查`
- Claude 根据 review 完成修复后，不回写 handoff 状态，只新增 fix 文档
- Codex 确认修复闭环后，状态更新为：`已处置` 或 `部分处置`

补充规则：

- handoff 的初始正文由 Claude 维护
- handoff 的状态回写和最终处置结论由 Codex 维护
- 如管理员介入影响结论，应通过管理员文档或相关文档中的“管理员介入记录”说明，不直接替代 Claude/Codex 的专属结论

## 7. 文档膨胀控制

- 短沟通写 `docs/messages/<task-id>.md`
- 根目录 `AGENT_MESSAGES.md` 只放摘要索引
- 正式结论只写 plan / handoff / review / fix / admin-note
- 同一任务未进入新阶段时，优先更新原文档，不新增新文档
- `COLLAB_TASKS.md` 负责告诉所有人“当前这个任务该看哪些文件”
- `COLLAB_TASKS.md` 的字段和记录格式以该文件内模板为准，不在 `TEAM.md` 中重复维护一份副本

## 8. Git 规则

- 开工前先看 `git status --short`
- 审查默认基于当前任务相关 diff，而不是整个仓库
- 禁止 `git add .`、`git add -A`，必须逐文件暂存
- 不覆盖、不回退、不重写其他协作者未明确要求处理的改动
- Claude 和 Codex 每次完成本轮有效修改后，都应自动提交自己本次修改的内容，不需要再向管理员单独申请提交许可
- 提交时只暂存并提交自己本轮负责的文件，不得顺手带上其他协作者的未处置改动
- 提交信息必须显式标注 Agent 身份，统一使用 `[claude]: ...` 或 `[codex]: ...` 开头
- 若用户要求 push，则继续 push

## 9. 冲突处理

- 当共享文件发生冲突时，优先保留双方信息，再人工整理，不允许简单覆盖
- 当个人规则与共享规则冲突时，以 `TEAM.md` 为准
- 当用户指令与 `TEAM.md` 冲突时，以用户指令为准

## 10. 优先级

冲突时按以下顺序处理：

1. 用户直接指令
2. 任务对应设计文档 / 实现计划
3. 本 `TEAM.md`
4. `CLAUDE.md` / `AGENTS.md`
