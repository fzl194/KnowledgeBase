# M1 Knowledge Mining v0.5 Codex Review

## 审查背景

本轮审查对象是 Claude Mining 提交的 v0.5 修订实现，主要提交为：

```text
c32568f [claude-mining]: align M1 Mining pipeline to schema v0.5 — full revision
```

审查依据包括：

- `knowledge_assets/schemas/001_asset_core.sqlite.sql`
- `knowledge_assets/schemas/README.md`
- `.dev/codex-mining-feedback-draft.md`
- `docs/messages/TASK-20260415-m1-knowledge-mining.md`
- `knowledge_mining/mining/**`
- `knowledge_mining/tests/**`

总体判断：Claude Mining 已经把实现从 v0.4 的定制 Markdown / manifest 思路，调整为 v0.5 的普通文件夹输入、MD/TXT parser、通用 raw/canonical 字段和 active publish version 架构。主方向基本正确，但当前实现还不能闭环为可验收版本，主要问题集中在 Markdown 结构保真、canonicalization、发布版本生命周期和测试有效性。

## 审查范围

本次审查覆盖：

- 输入扫描与 `raw_documents` 登记
- Markdown/TXT parser 与 `raw_segments` 生成
- JSON 字段职责边界
- canonicalization 与 `canonical_segment_sources`
- publish version 生命周期
- v0.5 schema 对齐
- 测试覆盖与验收缺口

未覆盖：

- Serving v0.5 实现审查
- 管理员正式混合测试文件夹验收
- Mining -> Serving 端到端契约测试运行

## 发现的问题

### P1: Markdown section tree 构建会造成重复切片

当前 `knowledge_mining/mining/structure/__init__.py` 的 `_build_section_tree()` 把第一个 heading 同时作为 root，又把所有 heading 作为 root children 构造 section。随后 `_make_section()` 又会把子 heading 下的 blocks 纳入父 section 处理。

这会导致形如：

```md
# ADD APN

intro

## 参数说明

| 参数 | 说明 |
|---|---|
| POOLNAME | 地址池 |

## 维护备注

remark
```

被遍历成多份重复 segment。表格和维护备注可能同时出现在 H1 section、H1 的 H2 child、root 的 H2 child 中。

影响：

- `raw_segments` 被重复内容污染。
- canonicalization 会把 parser 重复误认为来源重复。
- conflict / scope variant / Serving evidence 组装都会被重复切片干扰。

建议：

- Markdown section tree 必须是单一父子树，不要把同一 heading 同时挂到 root 和父 section。
- H1 应作为文档根节点或第一级 section 二选一，不能重复进入 children。
- H2/H3 只挂在最近的上级 heading 下。
- 增加回归测试：同一个 table / paragraph 在 `raw_segments.raw_text` 中只出现一次，`section_path` 精确为 `H1 -> H2`。

### P1: Markdown table 结构被压扁，`structure_json` 没有保留可用行列信息

当前 table 解析把 inline token 内容拼接为：

```text
cell1 | cell2 | cell3 | ...
```

segmentation 再用 `split(" | ")` 粗略统计 `col_count`，没有保留：

- columns
- rows
- row_count
- col_count
- 单元格与表头的映射关系

这违背了 Markdown parser 的核心价值。Markdown 解析不只是为了切成文本，而是为了保留结构，让 Serving 和后续差异检测知道这是表格、列表、代码或段落。

建议不改表，但明确 JSON 边界：

- 表格结构统一写入 `raw_segments.structure_json`。
- 不新增字段，不写入 `metadata_json`。
- `raw_text` 可以保留 Markdown 原文或可读文本，但 `structure_json` 必须机器可读。

最低结构建议：

```json
{
  "kind": "markdown_table",
  "columns": ["参数标识", "参数名称", "参数说明"],
  "rows": [
    {
      "参数标识": "APNNAME",
      "参数名称": "APN 名称",
      "参数说明": "必选参数。指定 APN 标识。"
    }
  ],
  "row_count": 1,
  "col_count": 3
}
```

对于参数表，可由 extractor 额外生成：

```json
[
  {"type": "parameter", "name": "APNNAME"},
  {"type": "parameter", "name": "POOLNAME"}
]
```

但实体引用属于 `entity_refs_json`，不能代替 `structure_json.rows`。

### P1: canonicalization 三层归并实际失效

当前 `canonicalize()` 的 exact layer 对所有 `content_hash` group 都直接创建 canonical，包括单元素 group，并把所有 segment 标记为 assigned。

结果：

- normalized layer 没有剩余 segment 可处理。
- near duplicate layer 基本没有剩余 segment 可处理。
- 大小写、空白、标点规范化后的重复不会合并。

定向验证：

```text
"Hello World"
"hello world"
```

当前结果是 2 个 canonical，且两个 mapping 都是 primary；预期应归并为 1 个 canonical，第二个来源为 `normalized_duplicate`。

建议：

- exact layer 只先处理 `len(group) > 1` 的 exact duplicate。
- 单元素 group 不应立即 assigned，应进入 normalized / near 候选池。
- normalized layer 处理 `normalized_hash` 相同且 `content_hash` 不同的 group。
- near layer 再处理剩余未归并 segment。
- 最后只对仍未 assigned 的 segment 生成 singleton canonical。
- 增加测试覆盖：
  - content hash 不同但 normalized hash 相同。
  - normalized hash 不同但 simhash/Jaccard 达阈值。
  - 完全无重复时才生成多个 singleton。

### P1: `version_code` / `batch_code` 秒级时间戳不保证唯一

当前发布使用：

```text
batch-YYYYMMDD-HHmmss
pv-YYYYMMDD-HHmmss
```

同一秒内连续运行会撞唯一键。测试中使用 `time.sleep(1.1)` 规避，说明测试绕开了真实风险。

建议：

- 改为微秒时间戳 + 短 UUID，或直接使用 UUID 派生。
- 测试必须覆盖同一秒连续发布两次，不允许靠 sleep。

### P1: 发布事务边界存在 active 丢失风险

当前流程在插入完成后调用 `activate_version()`，再更新 `metadata_json/build_finished_at`，最后 commit。如果 activate 后、commit 前发生异常，失败处理可能把新版本标为 failed，同时旧 active 已被 archived，存在没有 active version 的风险。

建议：

- 把所有 staging 写入和校验放在事务中。
- 激活步骤应是最后一个极小事务：旧 active -> archived，新 staging -> active，必要 metadata 同步完成。
- 如果激活事务失败，必须 rollback，旧 active 不应变化。
- 增加故障注入测试：激活前失败、激活中失败、激活后 metadata 更新失败。

### P1: primary source 校验漏掉 zero-primary canonical

当前 validation SQL 只检查：

```sql
GROUP BY canonical_segment_id
HAVING cnt != 1
```

但查询范围是 `WHERE is_primary = 1`，这会漏掉“某 canonical 完全没有 primary mapping”的情况，因为该 canonical 根本不会出现在分组结果中。

建议：

- 从 `asset_canonical_segments` left join `asset_canonical_segment_sources` 聚合。
- 校验每个 canonical 恰好有一个 `is_primary = 1`。
- 同时校验每个 canonical 至少有一个 source mapping。

### P2: `source_offsets_json` 太弱

当前只记录：

```json
{
  "block_index": 0,
  "section_title": "参数说明"
}
```

这不足以支持 Serving 下钻定位和调试。

建议不改表，补 JSON 约定：

```json
{
  "parser": "markdown",
  "block_index": 3,
  "line_start": 7,
  "line_end": 11,
  "char_start": 120,
  "char_end": 260
}
```

M1 如暂时拿不到 char offset，至少应有：

```json
{
  "parser": "markdown",
  "block_index": 3,
  "line_start": 7,
  "line_end": 11
}
```

### P2: TXT parser 会丢失标点和原文格式

当前 TXT parser 的 tokenizer 只保留 alnum、CJK 和空白，重组时会丢标点，并且用空格重组。这样生成的 `raw_text` 不再是原文片段。

建议：

- `raw_text` 必须尽量保持原文片段。
- token counting 可以单独做，但不能用 token 重组结果替代原文。
- TXT 可先按段落/空行切片，超长段再按窗口切，但窗口应该基于原文 offset。

### P2: `processing_profile_json` 与 `metadata_json` 职责需要收口

本轮不改表，但必须明确 JSON 字段边界，避免后续互相打架。

建议边界：

| 字段 | 只放什么 | 不放什么 |
|---|---|---|
| `source_batches.metadata_json` | 批次级请求参数、默认 scope/tags/input 信息 | 单个文件解析结果 |
| `raw_documents.scope_json` | 文档业务上下文：产品、版本、网元、项目、领域、作者、场景 | parser 状态、表格结构 |
| `raw_documents.tags_json` | 松散标签 | 结构化 scope |
| `raw_documents.processing_profile_json` | 文件级处理状态：`parse_status/parser/skip_reason/errors/quality` | 业务上下文、结构内容 |
| `raw_documents.metadata_json` | 兜底扩展，尽量少用 | 不重复 scope/tags/processing |
| `raw_segments.section_path` | 章节路径 | 表格/list/code 内容 |
| `raw_segments.structure_json` | 片段内部结构：table columns/rows、list items、code language | scope、parser 错误 |
| `raw_segments.source_offsets_json` | 来源定位：parser、block_index、line/char offset | 表格内容 |
| `raw_segments.entity_refs_json` | 实体引用：command、parameter、term、feature 等 | 表格 rows |
| `raw_segments.metadata_json` | 算法补充信息，能不用就不用 | 不重复上述字段 |
| `canonical_segments.scope_json` | 来源文档 scope 聚合 | source mapping 差异 |
| `canonical_segments.entity_refs_json` | 来源 segment 实体聚合 | raw 表格完整结构 |
| `canonical_segments.metadata_json` | canonicalization 方法、主来源、scope merge 冲突摘要 | raw 结构全文 |
| `canonical_segment_sources.metadata_json` | L1-L0 关系差异：variant_dimensions、diff/conflict 摘要 | canonical 正文 |

### P2: 只含未解析文件的批次是否允许 active 需要明确

当前 validation 要求至少一个 canonical。若输入目录只有 HTML/PDF/DOCX，M1 只登记 raw_documents，不生成 raw_segments/canonical，因此发布失败。

建议 M1 暂保持：

```text
没有可服务 canonical 的版本不能成为 active。
```

但需要把结果表达清楚：

- raw document 可以被登记到 failed/staging 版本用于审计。
- 返回 summary 明确 `unparsed_documents > 0`、`canonical_segments = 0`。
- 不要让 Serving 看到一个 active 但不可检索的空资产版本。

### P2: `conflict_candidate` 没有实际生成路径

v0.5 schema 允许 `conflict_candidate`，但当前 canonicalization 只看 exact/normalized/near/scope_variant，没有明确 same-scope 内容冲突候选生成逻辑。

建议 M1 可以先不做复杂冲突判断，但要：

- 明确当前不会自动生成 `conflict_candidate`。
- 测试不要暗示该能力已经完成。
- 若要支持，先做保守规则：同一 `entity_refs_json + scope_json + semantic_role` 下，文本差异显著但指向同一对象的来源，标为 `conflict_candidate`，且不作为普通答案材料。

### P3: v0.5 handoff 文件缺失

`COLLAB_TASKS.md` 中引用了：

```text
docs/handoffs/2026-04-17-m1-knowledge-mining-claude-v05-revision.md
```

但该文件当前不存在。消息文件里已有 v0.5 完成说明，但正式 handoff 缺失。

建议补齐 handoff，至少包含：

- 本轮改动范围
- 已知未完成项
- 测试命令与结果
- 未使用管理员正式测试文件夹的说明
- Mining -> Serving 契约测试待补说明

## 测试缺口

当前测试数量多，但仍缺关键断言：

- Markdown H1/H2 section tree 不重复。
- Markdown table `structure_json.columns/rows` 保真。
- normalized duplicate：content hash 不同但 normalized hash 相同。
- near duplicate：simhash/Jaccard 生效。
- 同一秒连续发布两次不冲突。
- 激活事务失败不影响旧 active。
- zero-primary canonical validation。
- TXT raw_text 不丢标点。
- `processing_profile_json.parse_status=parsed/skipped/failed` 全路径。
- Mining 生成 SQLite DB 后由 Serving 读取 active canonical 并下钻 raw/document。

本地尝试运行 `python -m pytest knowledge_mining/tests -q` 时，受当前沙箱临时目录权限影响，pytest/tempfile 无法写入临时目录，因此未把全量测试失败计入实现结论。上述 P1/P2 主要来自代码阅读和定向函数验证。

## 回归风险

如果只修局部测试而不修结构问题，会有以下风险：

- raw segment 数量膨胀，重复内容进入 L1。
- 表格参数信息丢失，Serving 只能模糊全文检索。
- normalized/near duplicate 失效，canonical 层不可信。
- 发布版本偶发冲突或 active 丢失。
- conflict/scope variant 被重复切片噪声污染。

## 建议修复项

建议 Claude Mining 按以下顺序修：

1. 修 Markdown section tree，先保证不重复切片。
2. 修 Markdown table/list/code 结构保真，表格 rows/columns 写入 `structure_json`。
3. 修 canonicalization 分层归并流程，补 normalized/near/singleton 正确测试。
4. 修 publish version 唯一性和激活事务边界。
5. 修 validation，覆盖 zero-primary / no-source canonical。
6. 补 `source_offsets_json` 和 `processing_profile_json` 最低 JSON 契约。
7. 补正式 handoff。
8. 等管理员正式混合测试文件夹到位后，补端到端验收和 Mining -> Serving 契约测试。

## 无法确认的残余风险

- 未使用管理员正式混合测试文件夹验证。
- 未验证 Serving 当前 v0.5 是否能读取 Mining 生成 DB。
- 未完整确认 raw HTML table、嵌套 list、blockquote、code fence 在真实样本中的保真度。
- 未确认正式运行环境下 pytest 184 通过结果。

## 管理员介入影响

管理员本轮明确要求：

- 不改全局表结构。
- 需要明确 JSON 字段职责边界，避免 `structure_json/metadata_json/entity_refs_json/processing_profile_json` 混用。
- 给 Claude Mining 的反馈必须包含修复建议，不只是指出错误。

本 review 已按该要求收口为：不改 schema，修实现与 JSON 契约。

## 最终评估

Claude Mining v0.5 修订的总体架构方向符合我们讨论后的目标，但当前实现不能直接验收。需要先处理 P1 问题，尤其是 Markdown 重复切片、表格结构丢失、canonicalization 分层归并失效、发布唯一性和事务边界。

表结构 v0.5 暂不需要修改；应通过实现修复和 JSON 字段职责约定完成收敛。
