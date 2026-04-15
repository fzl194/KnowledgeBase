# TASK-20260415-cloud-core-architecture 消息记录

## MSG-20260415-145000-codex
- 时间：2026-04-15 14:50
- From：Codex
- To：Claude
- 类型：architecture-handoff
- 关联文件：
  - `docs/architecture/2026-04-15-cloud-core-agent-knowledge-architecture.md`
  - `CoreMaster.md`
  - `agent_graph_rag_backend_design.md`
  - `TEAM.md`
- 内容：
  用户已确认新系统采用 Agent → Skill → Agent Serving → Knowledge Assets ← Knowledge Mining ← Raw Documents 的分层架构。请不要继续沿用旧项目“大一统 pipeline + API + ontology governance”的组织方式。旧代码已经放在 `old/`，只作为参考，不允许新代码直接 `import old.*`。

  本轮已沉淀正式架构基线文档：`docs/architecture/2026-04-15-cloud-core-agent-knowledge-architecture.md`。该文档定义了分层职责、推荐目录结构、数据库 schema 边界、Phase 1A 范围、Graph-RAG 第一阶段定义、运行态 API 初版、old 代码剥离策略和建议里程碑。

  后续请 Claude 先基于该架构文档产出实现计划，而不是直接写代码。计划应优先覆盖：
  1. 项目目录骨架。
  2. `asset.* / mining.* / serving.*` schema 初版。
  3. Phase 1A 的最小任务拆解。
  4. `/api/v1/command/usage`、`/api/v1/search`、`/api/v1/context/assemble` 的 request/response 契约。
  5. `skills/cloud_core_knowledge/` 的 Skill 初版文档。

  关键边界：
  - `agent_serving` 只能读取已发布 `knowledge_assets`，不得依赖 `knowledge_mining`。
  - Phase 1A 不做完整 ontology、facts/triples、Neo4j、复杂 PDF/Word 解析、Dashboard。
  - 第一目标是让 Agent 能通过 Skill 查询云核心网命令写法、参数、示例、注意事项和来源证据。
- 预期动作：
  Claude 读取架构文档后，按 `CLAUDE.md` 和 `TEAM.md` 的规则创建 `docs/plans/YYYY-MM-DD-<task-slug>-impl-plan.md`，先写计划并等待用户确认，再进入代码实现。

