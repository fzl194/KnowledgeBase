# M1 Agent Serving v0.5 Codex Review

## 审查背景

本轮审查对象是 Claude Serving 提交的 v0.5 泛化修订实现，主要提交为：

```text
ac03d20 [claude-serving]: upgrade to v0.5 generic evidence retrieval — 51/51 tests
```

审查依据包括：

- `docs/architecture/2026-04-15-mining-serving-parallel-design.md`
- `knowledge_assets/schemas/README.md`
- `docs/handoffs/2026-04-17-m1-agent-serving-claude-handoff.md`
- `docs/messages/TASK-20260415-m1-agent-serving.md`
- `agent_serving/serving/**`
- `agent_serving/tests/**`

总体判断：Serving 已经从旧的 command lookup 改为 `NormalizedQuery -> QueryPlan -> AssetRepository -> EvidenceAssembler -> EvidencePack`，架构方向正确。但当前实现仍有明显定制化残留，并且与 Mining v0.5 的真实产物存在契约错位。M1 需要统一为：Mining 尽力抽取结构化信息，Serving 灵活读取且不能强依赖 JSON 必含字段。

## 审查范围

本次审查覆盖：

- QueryNormalizer / QueryPlan 泛化程度
- AssetRepository 对 v0.5 asset 表的读取路径
- EvidencePack 证据组织
- scope/entity JSON 读取兼容性
- variants/conflicts/gaps 行为
- 运行态 DB 接入方式
- 测试覆盖有效性

未覆盖：

- 生产 PostgreSQL 接入
- 与真实 Agent/Skill 的运行验证
- Mining 生成 SQLite DB 后的完整契约测试

## M1 统一口径

本轮不改全局表结构。M1 继续使用六张 asset 表：

```text
source_batches
publish_versions
raw_documents
raw_segments
canonical_segments
canonical_segment_sources
```

需要统一的是 JSON 字段语义和 Serving 读取原则：

| 方向 | 要求 |
|---|---|
| Mining | 尽量抽取 `scope_json/entity_refs_json/structure_json/source_offsets_json/processing_profile_json`，支持不同意图检索。 |
| Serving | 不得强依赖 JSON 子字段必有；JSON 只作为增强信号，基础召回必须能退回文本字段。 |
| 契约 | `scope_json` 推荐 plural 数组，Serving 兼容 singular/plural；`entity_refs_json.normalized_name` 推荐写，Serving 缺失时 fallback 到 `name`。 |
| Evidence | Serving 必须返回 `structure_json/source_offsets_json`，不能把 Mining 保留的表格/list/code 结构再次压成纯文本。 |

## 发现的问题

### P1: 运行态只创建空内存 DB，没有读取 Mining 产物

`agent_serving/serving/main.py` 当前启动时连接：

```python
aiosqlite.connect(":memory:")
```

只加载共享 DDL，不加载 Mining 生成的 SQLite DB。测试能查到数据，是因为测试 fixture 手工把 seeded DB 放入 `app.state.db`。

影响：

- 真实启动后 `/api/v1/search` 默认读空库。
- Mining -> Serving 契约无法在运行态闭环。

建议：

- 增加配置化 DB 路径，例如 `COREMASTERKB_ASSET_DB_PATH`。
- 设置路径时以只读方式连接 Mining 生成 SQLite：

  ```text
  file:<path>?mode=ro
  ```

- 未设置路径时只允许 dev/test in-memory，并在没有 active version 时返回明确错误。
- 增加测试：Serving 指向一个文件 SQLite DB，能读取 active version 和 canonical evidence。

### P1: EvidencePack 丢失 `structure_json` 和 `source_offsets_json`

当前 `EvidenceItem` 只包含：

```text
id, block_type, semantic_role, raw_text, section_path, section_title, entity_refs
```

`AssetRepository.drill_down()` 也没有 select：

```text
rs.structure_json
rs.source_offsets_json
```

影响：

- Mining 即使保留 Markdown table rows/columns，Serving 也会丢掉。
- Agent 仍只能看到纯文本，无法可靠回答参数表、列表步骤、代码示例。

建议：

- `EvidenceItem` 增加：

  ```python
  structure: dict = Field(default_factory=dict)
  source_offsets: dict = Field(default_factory=dict)
  ```

- `drill_down()` SQL select `rs.structure_json, rs.source_offsets_json`。
- assembler 解析 JSON 后原样返回；缺失时返回 `{}`。
- 测试覆盖 table evidence，断言返回 `structure.columns/rows`。

### P1: `scope_json` 读取过窄，只支持 plural 数组

Serving 当前只识别：

```json
{"products": [...], "product_versions": [...], "network_elements": [...]}
```

但历史文档和 Mining 早期实现可能写：

```json
{"product": "CloudCore", "product_version": "V100R023", "network_elements": ["SMF"]}
```

影响：

- Mining 写 singular 时，Serving 的 `_parse_scope()` / `_matches_scope()` 会过滤失败。

建议：

- Mining 后续统一写 plural 数组。
- Serving 必须兼容 singular/plural：

  ```text
  product -> products
  product_version -> product_versions
  project -> projects
  domain -> domains
  scenario -> scenarios
  author -> authors
  ```

- scope 缺失不阻断基础召回，只影响过滤和排序。

### P1: entity 匹配强依赖 `normalized_name`

当前 `_filter_by_entities()` 用：

```python
ref.get("normalized_name", "").lower() == constraint.normalized_name.lower()
```

如果 Mining 只写：

```json
{"type": "command", "name": "ADD APN"}
```

则 Serving 过滤失败。

建议：

- Mining 推荐写 `normalized_name`。
- Serving 不得强依赖：

  ```text
  ref_norm = ref.normalized_name or normalize(ref.name)
  constraint_norm = constraint.normalized_name or normalize(constraint.name)
  ```

- 增加测试：entity ref 缺少 `normalized_name` 仍能匹配。

### P1: 无 scope 查询时 `scope_variant` 混入普通 evidence

当前 `_matches_scope()` 在没有 scope constraints 时返回 True。因此查询：

```text
ADD APN 怎么写
```

会把 `scope_variant` 也放进普通 evidence。

影响：

- `variant_policy=require_scope` 失效。
- Agent 可能把多个产品/版本变体混在一起回答。

建议：

| relation_type | scope 充分且匹配 | scope 不充分 |
|---|---|---|
| `primary` | evidence | evidence，但 gaps 提示有变体 |
| `exact_duplicate/normalized_duplicate/near_duplicate` | evidence | evidence |
| `scope_variant` | evidence | variants，不进 evidence |
| `conflict_candidate` | conflicts | conflicts |

判断 scope 是否充分时至少看：

```text
products/product_versions/network_elements/projects/domains/scenarios/authors
```

### P1: active version 查询应检测 0/1/>1

当前：

```sql
SELECT id FROM asset_publish_versions WHERE status = 'active' LIMIT 1
```

建议：

- 查询所有 active。
- 0 个：返回资产未发布。
- 1 个：正常。
- 多个：返回数据一致性错误，不静默选第一个。

### P1: `projects/domains` 等 scope 字段没有参与过滤

模型里有：

```text
projects
domains
```

但 `_matches_scope()` 只处理：

```text
products/product_versions/network_elements
```

建议：

- `_matches_scope()` 改为遍历所有非空 scope constraints。
- 至少支持 `projects/domains`；如果 schema README 定义 `scenarios/authors`，也应按数组交集处理。

### P2: Normalizer 仍明显定制云核心网命令场景

当前 `PRODUCT_RE` 和 `NE_RE` 大量重叠，`AMF ADD APN` 会解析为：

```text
products=["AMF"]
network_elements=[]
```

这不符合实际语义。

建议：

- 产品规则只识别明确产品或资料域，例如 `CloudCore/UDG/UNC`。
- `AMF/SMF/UPF/UDM/PCF/NRF` 优先作为 `network_elements`。
- 未知大写词不要强放 product，可作为 `term` entity 或 keyword。
- 后续改为可配置字典，不硬编码在代码中。

### P2: CloudCore / V100R023 识别不完整

当前版本正则只识别 `V100R023C10` 这类带 C 的版本；`CloudCore` 不在 product regex 中。

建议：

- 版本正则兼容：

  ```text
  V\d{3}R\d{3}(C\d{2})?
  ```

- 支持显式 request scope，且显式 scope 优先级高于 query 正则。

### P2: 中文关键词召回过弱

当前 `CPU过载告警怎么排查` 可能作为一个 keyword。LIKE 检索对中文长句很脆弱。

建议 M1 先做轻量规则：

- 去除疑问/意图词：`怎么/如何/是什么/排查/处理/配置/说明/用法`。
- 保留技术词、告警词、实体词。
- 生成多个 keyword，而不是整句一个 keyword。

### P2: `block_type_preferences` 没有执行

QueryPlan 有 `block_type_preferences`，但 Repo 没使用。

建议：

- M1 至少作为排序偏好使用。
- 例如“参数表”偏好 `table/html_table`，“示例”偏好 `code/paragraph`，“步骤”偏好 `list/paragraph`。

### P2: `semantic_role_preferences` 是排序不是过滤，语义需明确

当前 `_filter_by_semantic_roles()` 实际只是前置排序。

建议：

- 文档和代码命名明确它是 preference，不是 hard filter。
- 后续可拆为 `required_semantic_roles` 和 `preferred_semantic_roles`。

### P2: `/search` 请求模型过薄

`SearchRequest` 只有 `query`，导致 Serving 必须从自然语言中猜所有 scope/entity/filter。

建议兼容扩展：

```python
class SearchRequest(BaseModel):
    query: str
    scope: QueryScope | None = None
    entities: list[EntityRef] | None = None
    debug: bool = False
```

合并规则：

```text
显式 request scope/entities > normalizer 抽取 > 空
```

### P2: SourceRef / ConflictInfo 信息不足

SourceRef 缺：

```text
file_type/document_type/tags_json/processing_profile_json
```

ConflictInfo 缺：

```text
raw_segment_id/relation_type/entity_refs/source/section_path
```

建议：

- Repo drilldown join `raw_documents` 时 select `file_type/document_type/tags_json/processing_profile_json`。
- EvidenceAssembler 将这些字段放入 SourceRef / ConflictInfo。
- conflict 必须能说明冲突来自哪里，而不仅是冲突文本。

### P2: 排序过弱

当前 canonical 排序主要靠 SQL 返回顺序和 semantic role 前置。

建议 M1 使用轻量 scoring：

```text
score =
  exact_entity_match
  + scope_match
  + semantic_role_preference
  + block_type_preference
  + quality_score
  - variants_without_scope_penalty
```

不需要复杂 rerank，但要比无序更稳定。

### P3: 测试仍是 Serving 自造 seed，未证明 Mining 契约

当前 seed data 与代码假设高度一致：

- scope 全是 plural。
- entity 都有 `normalized_name`。
- 未测试 `structure_json/source_offsets_json` 返回。
- 未测试 no-scope 时 scope_variant 不进 evidence。

建议新增契约测试：

```text
Mining 生成 SQLite DB
Serving 用 COREMASTERKB_ASSET_DB_PATH 指向该 DB
查询 active version
查询 canonical
下钻 raw_segments/raw_documents
验证 structure_json/source_offsets_json/scope_json/entity_refs_json
```

在 Mining 修复完成前，可以先使用一份 Mining 输出 fixture DB，但最终必须跑真实 Mining pipeline。

## 测试结果

本地运行：

```text
python -m pytest agent_serving/tests -q
```

结果：

```text
50 passed, 1 error
```

唯一 error 来自当前沙箱临时目录权限：

```text
test_import_from_outside_repo
PermissionError: C:\Users\fuzhi\AppData\Local\Temp\pytest-of-fuzhi
```

其余 50 个测试通过。该错误不作为 Serving 业务实现失败，但测试覆盖仍存在上述契约缺口。

## 建议修复顺序

1. 支持配置化读取 Mining 生成 SQLite DB。
2. EvidencePack 返回 `structure_json/source_offsets_json`。
3. scope parser/filter 兼容 singular/plural，并支持 projects/domains。
4. entity match fallback 到 `name`。
5. no-scope 时 `scope_variant` 不进入普通 evidence。
6. active version 0/1/>1 明确处理。
7. SourceRef / ConflictInfo 补来源和处理状态。
8. 修正常见产品/网元误判，支持显式 request scope/entities。
9. block_type/semantic_role preference 进入排序。
10. 补 Mining -> Serving 契约测试。

## 最终评估

Serving v0.5 架构方向正确，可以保留 QueryPlan + EvidencePack 主线。但当前实现还不能称为完整泛化闭环：它仍有命令/网元定制化残留，并且对 JSON 子字段过度依赖。下一步不要推翻重做，而是在不改表的前提下补齐运行态 DB 接入、JSON 容错读取、结构化 evidence 返回、scope variant 策略和契约测试。
