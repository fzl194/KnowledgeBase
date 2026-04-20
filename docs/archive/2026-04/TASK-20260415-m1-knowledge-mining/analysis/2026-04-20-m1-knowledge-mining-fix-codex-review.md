# M1 Knowledge Mining v0.5 Fix Codex Review

## 审查背景

本轮审查对象是 Claude Mining 在上一轮 Codex v0.5 review 之后提交的修复链，重点提交为：

```text
1f43dab [claude-mining]: fix Codex v0.5 review P1-P9 — MD tree, table structure, canonicalization, publish lifecycle
ec82ccc [claude-mining]: fix self-review bugs in structure/parsers/canonicalization/publishing
0bb08e4 [claude-mining]: append self-review fix message and update task status
```

审查依据：

- `docs/architecture/2026-04-15-mining-serving-parallel-design.md`
- `docs/messages/TASK-20260415-m1-knowledge-mining.md`
- `docs/handoffs/2026-04-17-m1-knowledge-mining-claude-v05-revision.md`
- `knowledge_assets/schemas/001_asset_core.sqlite.sql`
- `knowledge_mining/mining/**`
- `knowledge_mining/tests/**`
- `data/m1_contract_corpus/corpus`

总体结论：Claude Mining 的主架构方向已经基本符合当前 M1 统一契约，尤其是普通文件夹输入、MD/TXT 解析、HTML/PDF/DOCX 只登记、三层资产表写入、表格结构保真和 canonical/source mapping 基线均已有落地。但本轮修复仍存在 P1 问题，不能直接验收。

## 审查范围

本次审查覆盖：

- Markdown structure parser 的 section tree、table、list 处理
- TXT parser 长段切片与 token 边界
- segmentation 的结构块切片与 `source_offsets_json`
- canonicalization 的 exact / normalized / near / singleton 流程
- publishing 的 active version 生命周期与失败隔离
- contract corpus 实际构建结果
- Claude 新增回归测试的有效性

未覆盖：

- Serving 对 Mining DB 的完整端到端契约测试
- 正式用户上传文件夹流程
- HTML/PDF/DOCX 深度解析能力，该能力不属于 M1

## 发现的问题

### P1: 激活阶段失败仍会导致旧 active 丢失

位置：

- `knowledge_mining/mining/publishing/__init__.py:223`
- `knowledge_mining/mining/publishing/__init__.py:249`

当前 `publish()` 在校验通过后调用 `db.activate_version(conn, pv_id)`，该方法会把旧 active 改为 archived，再把新版本改为 active。问题是如果 `activate_version()` 之后、最终 `conn.commit()` 之前发生异常，异常处理没有先 `rollback()`，而是继续调用 `db.fail_version(conn, pv_id)` 并 `commit()`。

我做了故障注入验证：

```text
1. 第一次 publish 成功，DB 有 1 个 active。
2. 第二次 publish 在 activate_version() 之后抛 RuntimeError。
3. 最终版本状态为 archived=1、failed=1、active=0。
```

这违反 M1 发布契约：

```text
构建失败或激活失败时，新版本不能影响旧 active 可读。
```

建议修复：

- 在 `except` 中先判断事务阶段并执行 `conn.rollback()`，不能在未 rollback 的激活事务上直接 `fail_version + commit`。
- 将 staging 写入失败和 activation 失败分开处理：
  - staging 写入/校验失败：可以标记新版本 failed。
  - activation 事务失败：必须 rollback，保留旧 active；如需记录失败，可在 rollback 后开启独立事务标记新版本 failed，且不能 archive 旧 active。
- 增加故障注入测试：在 `activate_version()` 后、metadata 更新前抛异常，断言旧 active 仍存在。

### P1: Markdown 跳级 heading 会被混入正文，section_path 不可信

位置：

- `knowledge_mining/mining/structure/__init__.py:315`

当前 `_split_sub_sections()` 只把 `parent_level + 1` 当作直接子章节。如果文档出现跳级标题，例如：

```md
# H1

a

### H3

b

## H2

c
```

解析结果会把 `H3` 当成普通 paragraph 内容，生成类似：

```text
a

H3

b
```

影响：

- `section_path` 缺失真实 H3 层级。
- heading 文本污染 `raw_text` 和 canonical text。
- Serving 下钻展示章节路径时会不准确。

建议修复：

- section tree 构建不要假设标题层级连续。
- 当 H1 下直接出现 H3 时，应把 H3 挂到最近可用上级 heading 下，或作为 H1 的直接 child，不能作为正文。
- 增加测试覆盖 H1 -> H3、H2 -> H4 等跳级标题。

### P1: 嵌套 list depth 计数对有序/无序混合嵌套不正确

位置：

- `knowledge_mining/mining/structure/__init__.py:66`

当前 list parser 在遇到 `bullet_list_open` 或 `ordered_list_open` 时统一 `depth += 1`，但关闭时只匹配当前外层 `close_type`。对于混合嵌套：

```md
- outer 1
  1. inner a
  2. inner b
- outer 2

After list.
```

实测结果会丢失 `outer 2`，并把 `After list.` 吞进 list segment。

影响：

- list items 不完整。
- list 与后续 paragraph 边界被破坏。
- `structure_json.items` 不能作为 Serving 结构化 evidence 使用。

建议修复：

- depth 递减应同时识别 `bullet_list_close` 和 `ordered_list_close`，不能只匹配外层类型。
- 解析 list item 时建议基于 `list_item_open/list_item_close` 组织外层 item，而不是只收集 depth=1 的 inline。
- 增加测试：
  - bullet list 嵌套 bullet list。
  - bullet list 嵌套 ordered list。
  - ordered list 嵌套 bullet list。
  - list 后接 paragraph，不应被吞进 list。

### P2: list 没有独立切片，容易和 paragraph 混成一个 segment

位置：

- `knowledge_mining/mining/segmentation/__init__.py:79`

当前 segmentation 只把 `table/html_table/code` 作为结构块独立切片，`list` 会进入 `current_group`。这会产生：

```text
block_type = list
raw_text = list 内容 + 后续普通段落
structure_json = list items + paragraph_count
```

这与当前 JSON 字段边界不一致。`structure_json` 应描述当前片段内部结构，但一个 `block_type=list` 的 segment 不应混入普通 paragraph。

建议修复：

- 将 `list` 也作为独立结构块切片，和 table/code 一样 flush pending group。
- paragraph 可以继续合并；table/list/code/html_table/raw_html 应尽量保持结构边界清晰。

### P2: paragraph 的 source_offsets_json 缺少 line_start/line_end

位置：

- `knowledge_mining/mining/structure/__init__.py:126`
- `knowledge_mining/mining/segmentation/__init__.py:137`

Claude 声明 `source_offsets_json` 已补充 `parser/line_start/line_end`，但 contract corpus 中不少 paragraph 实际只有：

```json
{"parser": "markdown", "block_index": 0}
```

原因是 Markdown paragraph 的 line map 在 `paragraph_open` token 上，当前 parser 直接处理 `inline` token，未读取 `paragraph_open.map`。

影响：

- Serving 下钻无法定位到行。
- 用户追溯“来自哪个文件哪个位置”时只能给章节，不能给行范围。

建议修复：

- 处理 `paragraph_open` 时读取其 `map`，再读取随后的 `inline` 内容生成 paragraph block。
- TXT parser 也应按段落记录 line_start/line_end，至少保证段落级定位。
- 测试应断言普通 paragraph、list、table、code 都有可用 line_start/line_end；如果某些 parser 确实无法拿到，需要明确例外。

### P2: semantic_role 和 entity_refs_json 仍然几乎为空，Mining 对 Serving 的增强信号不足

当前 contract corpus 构建结果中：

```text
raw_segments.semantic_role = unknown
entity_refs_json 基本为空
```

这不违反 Serving 容错读取原则。Serving 不能强依赖这些字段。但 M1 最新架构也要求 Mining “尽可能将结构化信息抽取出来，支持不同意图的检索”。当前实现还停留在结构解析层，语义增强不足。

建议在 M1 增加轻量规则，不做 LLM，不做命令专用强模型：

| 规则来源 | 建议输出 |
|---|---|
| section title 包含 参数/参数说明 | `semantic_role=parameter` |
| section title 包含 使用实例/命令格式/示例 | `semantic_role=example` |
| section title 包含 操作步骤/流程/检查项 | `semantic_role=procedure_step` 或 `checklist` |
| section title 包含 排障/故障 | `semantic_role=troubleshooting_step` |
| section title 包含 注意事项/限制 | `semantic_role=note` 或 `constraint` |
| table columns 包含 参数名/参数标识 | 抽取 `entity_refs_json` 中的 parameter |
| 文本命中 `ADD <WORD>` / `SHOW <WORD>` 等模式 | 抽取 command entity |
| 文本命中常见 NF 缩写 SMF/UPF/AMF/PCF | 抽取 network_element entity |

注意：这些字段是增强信号，不允许 Serving 因其缺失而无法检索。

## 已确认的修复

以下上一轮问题已有实质改善：

- Markdown H1/H2 重复切片问题大体修复，普通 H1 -> H2 场景不再重复。
- Markdown table 已能写入 `structure_json.columns/rows/row_count/col_count`。
- canonicalization 不再在 exact layer 把 singleton 全部 assigned，normalized/near/singleton 流程基本恢复。
- `version_code` / `batch_code` 已加短 UUID，连续发布碰撞风险降低。
- source mapping 缺失 id 时不再写空字符串外键，而是显式报错。
- validation 已用 LEFT JOIN 检测 zero-primary canonical。
- contract corpus 可构建出 active SQLite：11 docs、28 raw_segments、22 canonical_segments、28 mappings。
- HTML/PDF/DOCX 在 contract corpus 中只登记 raw_documents，不生成 raw_segments。

## 测试缺口

Claude 声明 197 tests passed，但本地直接运行全量 `python -m pytest knowledge_mining/tests -q` 时，当前环境的 `tempfile.TemporaryDirectory()` 无法在用户 Temp 目录写入，导致大量权限噪声，不能作为实现失败结论。

我使用定向验证发现上述 P1/P2 问题。后续需要补充以下测试：

- activation 失败后旧 active 仍存在。
- H1 -> H3 跳级 heading 不进入 paragraph。
- 混合嵌套 list 不丢 item、不吞后续 paragraph。
- list 独立切片，不与 paragraph 混合。
- paragraph/list/table/code 的 `source_offsets_json` 至少含 parser、block_index、line_start、line_end。
- contract corpus 构建后，至少部分参数表产生 `semantic_role=parameter` 和 parameter entity refs。
- Mining 生成的 SQLite DB 由 Serving 读取的端到端契约测试。

## 回归风险

如果当前版本直接给 Serving 使用，主要风险是：

- 发布失败后 DB 可能没有 active version，Serving 启动或请求时找不到可读资产。
- 跳级 heading 和嵌套 list 会污染 raw/canonical 文本，导致下钻路径和结构化 evidence 不可信。
- `source_offsets_json` 不完整，Serving 虽能返回来源文件和章节，但难以定位原文位置。
- semantic/entity 信号缺失会迫使 Serving 退回全文匹配，降低多意图检索质量。

## 建议修复项

建议 Claude Mining 按以下顺序处理：

1. 修复 publish 激活失败事务边界，确保旧 active 不丢失。
2. 修复 Markdown heading tree，支持跳级标题。
3. 修复混合嵌套 list parser，保证 list item 完整且不吞后续段落。
4. segmentation 将 list 独立切片。
5. paragraph/TXT 补齐 source_offsets_json 的 line_start/line_end。
6. 增加轻量 semantic_role/entity_refs 规则。
7. 补充上述回归测试和 contract corpus 验证说明。

## 无法确认的残余风险

- 当前环境的 tempfile 权限问题导致无法可信复现全量 197 测试。
- 未完成 Serving 读取 Mining DB 的完整端到端契约验证。
- 未验证更复杂 Markdown 表格、HTML table、blockquote、code fence 在大规模真实资料中的表现。

## 管理员介入影响

管理员确认本轮审查先不直接回复 Claude，需要 Codex 先和管理员讨论。管理员认可上述问题判断后，要求形成正式 review 和后续修复指令。

## 最终评估

本轮修复方向正确，但仍不能验收。最核心的阻塞是发布失败会破坏 active version，这是直接影响 Serving 可用性的 P1 问题。Markdown 跳级 heading 和混合嵌套 list 也会破坏原始语料结构保真，需要在 M1 内修掉。

表结构不需要调整。问题应通过 Mining 实现修复、测试补充和轻量结构/语义抽取增强来解决。
