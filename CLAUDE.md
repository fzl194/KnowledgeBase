# CLAUDE.md

> 本文件是 Claude Code 的个人行为准则。其他 Agent 读取时请无视。

## 1. 先看哪里

Claude 在进入任务时，按以下顺序获取上下文：

1. 用户当前指令
2. `TEAM.md`
3. `COLLAB_TASKS.md` 中对应 `task-id` 的任务记录
4. 该任务关联的正式文档
5. `docs/messages/<task-id>.md` 中的最近协作消息
6. `README.md` 中的项目说明与开发命令

## 2. Claude 的核心职责

- 理解需求并澄清实现边界
- 产出实现计划
- 修改代码和相关实现文档
- 执行验证
- 向 Codex 交接
- 在审查问题解决后向用户交付

## 3. Claude 负责写哪些文件

- `docs/plans/*`
- `docs/handoffs/*claude-handoff.md`
- `docs/handoffs/*claude-fix.md`
- `backend/`、`frontend/` 中的实现代码

Claude 不负责创建或修改：

- `docs/analysis/*`
- `AGENTS.md`
- 管理员专属文档

## 4. Claude 如何使用共享文件

### 4.1 `COLLAB_TASKS.md`

Claude 只更新这些字段：

- `计划文档`
- `交接文档`
- `修复文档`
- 自己的责任字段
- `最新消息`（仅在自己刚发消息后更新）

Claude 不应主动覆盖：

- `状态`
- `当前阶段`
- `审查文档`
- 管理员备注

### 4.2 `AGENT_MESSAGES.md`

**铁律：Claude 每次向 `docs/messages/<task-id>.md` 追加消息后，必须立即同步在 `AGENT_MESSAGES.md` 追加对应的摘要索引行。**

这是一个两步操作，缺一不可：
1. 写 `docs/messages/<task-id>.md`（完整消息正文）
2. 写 `AGENT_MESSAGES.md`（追加一行摘要索引）

如果只做了第 1 步而忘了第 2 步，等于消息对外不可见，Codex 和管理员在索引中看不到新消息。这是 Claude 反复犯的错误，**必须杜绝**。

Claude 不在这里写长消息。这里只追加摘要索引。

### 4.3 `docs/messages/<task-id>.md`

Claude 的短沟通、补充说明、交接提醒、阻塞、问题，都写到任务消息文件里。

推荐格式：

```md
## MSG-20260402-153012-claude
- 时间：2026-04-02 15:30
- From：Claude
- To：Codex
- 类型：handoff-note
- 关联文件：
- 内容：
- 预期动作：
```

规则：

- 只追加，不改历史消息正文
- 若内容已沉淀为正式文档，追加一条 follow-up 说明去向

## 5. 正式交付要求

### 5.1 plan

路径：

- `docs/plans/YYYY-MM-DD-<task-slug>-impl-plan.md`

### 5.2 handoff

路径：

- `docs/handoffs/YYYY-MM-DD-<task-slug>-claude-handoff.md`

至少包含：

- 任务目标
- 本次实现范围
- 明确不在本次范围内的内容
- 改动文件清单
- 关键设计决策
- 已执行验证
- 未验证项
- 已知风险
- 指定给 Codex 的审查重点
- 管理员本轮直接介入记录

### 5.3 fix

路径：

- `docs/handoffs/YYYY-MM-DD-<task-slug>-claude-fix.md`

Claude 在修复审查问题后，必须单独写 fix，不得回写 review 结论。

## 6. Git 工作方式

- 开始实现前至少执行 `git status --short`
- 必要时查看相关文件 diff
- 暂存时必须逐文件 `git add <path>`
- 不使用 `git add .` 或 `git add -A`
- 不覆盖 Codex 或管理员未明确要求处理的改动
- 每次完成本轮有效修改后，自动提交自己本次修改的内容，不需要向管理员单独申请
- 提交时只提交自己负责的文件，不夹带 Codex 或管理员的未处置改动
- Claude 的 commit message 必须以 `[claude]:` 开头

## 6.1 测试与验证

- Claude 有权自主运行测试（包括 `pytest`、`npm run build`、`vue-tsc` 等），无需管理员额外授权
- 代码修改完成后必须自行运行全量回归测试确认无破坏，不应等待管理员手动验证
- 将此视为标准工作流的一部分：改代码 → 自行测试 → 确认通过 → 提交

## 7. 协作原则

- 不把短沟通塞进正式文档
- 不在共享文件中重写整块内容，尽量做局部更新
- 不擅自修改 Codex 的 review 文档
- 不在问题未处置前宣称任务完成
- 若共享文件刚被别人更新，先重新读取再写入

## 8. 文档演进准则

- 正式文档默认在原路径上持续增量修订，不为每一轮小修正随意新建 `v2`、`v3` 或平行文件
- 同一主题若已有正式文档，优先在该文件内追加“修订说明 / 日期 / 消息来源 / 章节更新”，而不是再开新文件
- 只有在“主题语义已经明显切换”或“必须长期并行保留旧版基线供比较”时，才允许新建并行文档
- `docs/messages/<task-id>.md` 继续承担协作历史沉淀；正式 plan / handoff / fix 文档应保持单一路径上的当前有效版本
- Claude 在修订设计、计划、handoff、fix 时，应优先回写原文件并更新修订说明，避免在仓库中生成大量零散版本文件

## 9. Skill 使用规范

Claude 拥有丰富的 Skill 库，应灵活运用而非机械照搬。核心原则：

- **主动判断，按需调用**：根据任务实际情况自行决定是否调用 Skill，不要求每个阶段都走固定 Skill 流程
- **流程型优先于实现型**：当多个 Skill 可能适用时，先调用决定"怎么做"的流程型 Skill（如 brainstorming、systematic-debugging），再调用指导执行的实现型 Skill（如 frontend-design）
- **不跳过关键环节**：灵活不等于省略。需求澄清、测试验证、交付检查等关键环节仍需完成，只是完成方式由 Claude 根据上下文自行选择最合适的 Skill 或直接执行
