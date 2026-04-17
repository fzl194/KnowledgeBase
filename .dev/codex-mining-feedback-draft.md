# Codex Mining Feedback Draft

> 临时草稿文件。用于记录与管理员逐项讨论后的意见，等全部主题讨论完成后，再统一整理为给 Claude Mining 的正式修订意见。

## 主题 1：输入链路 / 语料接入

### 1. 结论

M1 Knowledge Mining 的输入链路不应围绕 `manifest.jsonl`、`html_to_md_mapping.json/csv` 或任何外部元数据文件设计。

M1 的基础输入模型应是：

```text
管理员 / 用户提供一个文件夹，后续也可以是压缩包
  -> Mining 递归扫描目录
  -> 发现其中的 md / html / pdf / doc / docx / txt 等 source artifacts
  -> 所有支持识别的文件都登记为 raw_documents
  -> 当前版本优先深度解析 Markdown / txt
  -> 其他格式先登记，能基础抽取则抽取，不能抽取则标记为未解析或低结构质量
```

M1 不考虑外部元数据文件的存在。`manifest.jsonl`、`html_to_md_mapping.json/csv` 既不是主入口，也不是可选增强项。Mining 只能基于文件夹递归扫描、文件自身、相对路径、目录结构和内容做识别与推断。

### 2. 他做了啥

Claude Mining 当前实现的输入链路是：

```text
如果输入目录下存在 manifest.jsonl：
    按 manifest.jsonl 中列出的 path 读取 Markdown 文件
否则：
    递归扫描 .md 文件
```

对应代码：

- `knowledge_mining/mining/ingestion/__init__.py`

当前能力：

| 项 | 当前实现 |
|---|---|
| 输入目录 | 支持 |
| `manifest.jsonl` | 支持，并且优先级最高；但这不符合当前目标 |
| 普通 Markdown 目录 | 支持 |
| Markdown frontmatter | 支持极简解析 |
| `.html` 独立文件 | 不支持 |
| `.pdf` | 不支持 |
| `.doc/.docx` | 不支持 |
| `.txt` | 不支持 |
| 压缩包 | 不支持 |
| `html_to_md_mapping.json/csv` | 不支持；当前目标也不要求支持 |
| 外部元数据文件 | 当前实现考虑了 manifest；但目标是不考虑任何外部元数据文件 |
| 文件发现基线 | 不是“递归发现所有 source artifacts”，而是“manifest 驱动或 md 扫描” |

这导致当前实现更适配 `cloud_core_coldstart_md` 这个样本场景，而不是通用语料接入场景。更关键的是，当前实现把外部元数据文件纳入了入口设计，而我们现在明确不应该依赖或考虑这类文件。

### 3. 我们的目标是啥

我们的目标不是做一个只服务某个产品文档样本包的定制导入器，而是做一个通用的语料接入层。

M1 的输入假设应调整为：

```text
输入 = 一个语料根目录
```

后续可以扩展为：

```text
输入 = 一个语料根目录 / 一个压缩包 / 一批文件
```

M1 需要覆盖的语料形态：

| 类型 | M1 目标处理方式 |
|---|---|
| `.md` / `.markdown` | 直接读取并做结构解析、切片、归并 |
| `.txt` | 读取纯文本，做基础段落切片 |
| `.html` / `.htm` | 至少登记为 raw document；如实现基础 HTML 文本抽取，则参与切片 |
| `.pdf` | 至少登记为 raw document；M1 不强制完整解析 |
| `.doc` / `.docx` | 至少登记为 raw document；M1 不强制完整解析 |
| 其他文件 | 可忽略或登记为 `other`，具体策略需要日志说明 |
| 压缩包 | 可以后续支持；M1 可先明确不做，或者解压到 staging 后扫描 |

M1 的关键不是“所有格式都解析完美”，而是：

| 目标 | 说明 |
|---|---|
| 文件发现完整 | 给定目录下支持识别的文档不要因为没有 manifest 就丢失 |
| 文档登记完整 | 即使暂时不能解析，也应该进入 `raw_documents` |
| 解析能力分层 | Markdown/txt 当前深度解析；HTML/PDF/DOC 可先降级 |
| 元数据来源 | 不考虑外部元数据文件；只使用文件自身、相对路径、目录结构和内容推断 |
| 不绑定产品文档 | 专家文档、项目文档、培训材料、标准文档都能进入同一流程 |
| 可追溯 | 如果有原始路径、转换路径、sidecar 信息，需要落库保留 |

### 4. 关键原则

#### 4.1 目录递归扫描是主路径

正确主路径应是：

```text
scan(input_dir)
  -> discover source artifacts
  -> classify file_type
  -> load optional metadata
  -> merge metadata
  -> parse supported content
  -> publish
```

而不是：

```text
manifest exists?
  -> yes: only import manifest files
  -> no: scan markdown
```

因为未来大量场景不会有 manifest。

#### 4.2 不考虑外部元数据文件

M1 不把外部元数据文件纳入输入模型。

| 文件 | M1 定位 |
|---|---|
| `manifest.jsonl` | 不考虑，不读取，不作为导入依据 |
| `html_to_md_mapping.json/csv` | 不考虑，不读取，不作为导入依据 |
| 其他外部 metadata 文件 | 不考虑，不读取，不作为导入依据 |

M1 可以使用的信息来源只有：

| 信息来源 | 用法 |
|---|---|
| 文件相对路径 | 生成 `document_key`，辅助推断文档类别 |
| 文件名 | 生成标题候选、辅助推断类别 |
| 文件后缀 | 判断 `file_type` |
| 目录结构 | 弱推断 scope / document_type / tags |
| 文件内容 | 解析标题、段落、命令、章节角色、结构类型 |
| Markdown frontmatter | 属于文件内容的一部分；如存在可以读取，但不能要求存在 |

原因：

| 风险 | 说明 |
|---|---|
| 元数据文件缺失 | 真实场景通常不会提供外部元数据文件 |
| 元数据文件不完整 | 即使偶尔存在，也可能漏文件或与文件系统不一致 |
| 格式绑定 | 会把系统做成特定语料生产工具的下游，而不是通用知识挖掘层 |
| 责任混乱 | Mining 应该从语料本身挖掘知识，而不是依赖额外清单告诉它语料是什么 |

#### 4.3 文件类型要先登记，再决定是否解析

M1 不要求一次性解析所有格式，但应该先有清晰状态。

建议文件处理策略：

| 文件类型 | 是否登记 `raw_documents` | 是否生成 `raw_segments` | `structure_quality` 建议 |
|---|---:|---:|---|
| Markdown | 是 | 是 | `markdown_native` 或 `markdown_converted` |
| txt | 是 | 是，基础段落切片 | `plain_text_only` |
| html | 是 | 可选，M1 可基础抽文本 | `full_html` / `mixed` / `unknown` |
| pdf | 是 | M1 可暂不生成 | `unknown` 或 `plain_text_only` |
| doc/docx | 是 | M1 可暂不生成 | `unknown` 或 `plain_text_only` |
| other | 可选 | 否 | `unknown` |

这里的重点是：

**不能因为 PDF/DOC 当前不会解析，就在系统里完全消失。**

### 5. 建议 Claude Mining 下一步怎么做

#### 5.1 重构 ingestion 主流程

把当前逻辑：

```text
manifest.jsonl 优先
否则扫描 .md
```

改成：

```text
递归扫描输入目录
  -> 发现支持的 source artifacts
  -> 基于相对路径 / 文件名 / 文件内容推断基础信息
  -> 输出统一的 RawDocumentData / SourceArtifactData
```

建议识别的后缀：

| 后缀 | `file_type` |
|---|---|
| `.md` | `markdown` |
| `.markdown` | `markdown` |
| `.html` | `html` |
| `.htm` | `html` |
| `.pdf` | `pdf` |
| `.doc` | `doc` |
| `.docx` | `docx` |
| `.txt` | `txt` |

#### 5.2 调整数据对象

当前 `RawDocumentData` 偏 Markdown：

```python
RawDocumentData(
    file_path,
    content,
    frontmatter,
    manifest_meta,
)
```

建议改成更通用的 source artifact 表达：

| 字段 | 说明 |
|---|---|
| `document_key` | 稳定文档键 |
| `source_uri` | 当前读取路径 |
| `relative_path` | 相对输入根目录路径 |
| `file_name` | 文件名 |
| `file_type` | `markdown/html/pdf/doc/docx/txt/other` |
| `raw_content` | 原始文本内容；二进制文件可为空 |
| `normalized_content` | 可解析文本；不可解析可为空 |
| `content_hash` | 文件内容 hash，不是路径 hash |
| `frontmatter` | 可选 |
| `raw_storage_uri` | 原始文件路径 |
| `normalized_storage_uri` | 转换后文本/Markdown 路径，可为空 |
| `parse_status` | `parsed/skipped/unsupported/failed` |
| `structure_quality` | 结构保留质量 |

如果不想一次改太大，也至少要在现有 `RawDocumentData` 中补：

| 字段 | 必要性 |
|---|---|
| `file_type` | 必须 |
| `relative_path` | 必须 |
| `content_hash` | 必须 |
| `parse_status` | 建议 |
| `raw_storage_uri` | 建议 |
| `normalized_storage_uri` | 建议 |

#### 5.3 修改 pipeline 统计

当前 summary 是：

```python
{
  "documents": len(docs),
  "segments": len(all_segments),
  "canonicals": len(canonicals),
  "mappings": len(mappings),
}
```

建议改成：

| 字段 | 说明 |
|---|---|
| `discovered_documents` | 扫描发现的文档数量 |
| `parsed_documents` | 实际解析并生成 segments 的文档数量 |
| `unparsed_documents` | 登记但未解析的文档数量 |
| `segments` | L0 数量 |
| `canonicals` | L1 数量 |
| `mappings` | L2 数量 |
| `skipped_files` | 被忽略文件数量 |
| `failed_files` | 解析失败文件数量 |

否则未来一个目录有 100 个文件，只有 20 个 Markdown，当前输出 `documents=20` 会误导我们以为只发现了 20 个。

#### 5.4 修改 publishing

只要 ingestion 改成通用 source artifact，publishing 就必须把这些字段落到 `raw_documents`：

| 字段 | 是否必须 |
|---|---|
| `document_key` | 必须 |
| `source_uri` | 必须 |
| `relative_path` | 必须 |
| `file_name` | 必须 |
| `file_type` | 必须 |
| `source_type` | 必须或默认 `folder_scan/other` |
| `raw_storage_uri` | 建议必须 |
| `normalized_storage_uri` | 可为空 |
| `document_type` | 能推断就写 |
| `content_hash` | 必须，且必须是文件内容 hash |
| `scope_json` | 必须，默认 `{}` |
| `tags_json` | 必须，默认 `[]` |
| `conversion_profile_json` | 默认 `{}` |
| `structure_quality` | 必须 |
| `metadata_json` | 存 parse_status、skip_reason、推断依据等 |

#### 5.5 修改测试

Claude Mining 需要补这些测试：

| 测试 | 目标 |
|---|---|
| 目录下同时有 md/html/pdf/docx/txt | 所有支持类型都进入 `raw_documents` |
| 无 manifest、无 mapping | 仍能正常发现文件 |
| 目录中存在 manifest/mapping | 作为普通文件忽略或跳过，不影响扫描其他语料文件 |
| PDF/DOC 暂不解析 | 仍登记 raw document，parse_status 标记正确 |
| txt 基础切片 | 能生成 raw segment |
| content_hash | 使用文件内容，而不是路径 |
| pipeline summary | 区分 discovered/parsed/unparsed |

### 6. 给 Claude Mining 的最终要求文本草稿

```text
主题 1：输入链路需要修订。

M1 Mining 的主输入不应是 manifest.jsonl，也不应是 html_to_md_mapping.json/csv。
M1 不考虑任何外部元数据文件的存在，这些文件既不是主入口，也不是可选增强项。

M1 的基础输入模型应改为：给定一个语料目录，递归发现 source artifacts。
当前至少识别 .md/.markdown/.txt/.html/.htm/.pdf/.doc/.docx。
所有识别到的文档都应登记到 raw_documents。
Markdown 和 txt 当前应生成 raw_segments；HTML/PDF/DOC/DOCX 可以先登记并标记 parse_status/structure_quality，后续再增强解析。

manifest.jsonl、html_to_md_mapping.json/csv 或其他外部 metadata 文件不应被读取或依赖。
Mining 只能基于文件夹递归扫描、文件后缀、相对路径、目录结构、文件名和文件内容做识别与推断。

请重构 ingestion，使其流程变为：
1. 递归扫描输入目录，发现 source artifacts。
2. 基于文件后缀、相对路径、目录结构、文件名和内容推断 file_type/document_type/scope/tags。
3. 对可解析文本生成 normalized content。
4. 对不可解析类型仍输出 raw document，并标记 parse_status。
5. publishing 必须把 document_key/source_uri/relative_path/file_name/file_type/content_hash/raw_storage_uri/normalized_storage_uri/document_type/scope_json/tags_json/structure_quality/metadata_json 写入 raw_documents。
6. pipeline summary 需要区分 discovered_documents、parsed_documents、unparsed_documents、segments、canonicals、mappings、skipped_files、failed_files。
```

### 7. 当前判断

主题 1 必须要求 Claude Mining 修。

否则系统会被 `manifest.jsonl` 这类外部元数据文件牵着走，和我们要的“给一个文件夹就能接入通用语料”的目标不一致。

## 主题 2：`raw_documents` 文档级落库

### 1. 结论

`raw_documents` 应该表达“一批语料中每个源文件的文档级资产记录”。

它不应该只服务 Markdown，也不应该只记录已经成功解析的文件。M1 的正确目标是：

```text
给定一个 source_batch
  -> 该批次有自己的 input_root / storage_root_uri
  -> Mining 递归扫描该批次目录
  -> 每个识别到的源文件都写入 raw_documents
  -> Markdown / txt 等可解析文件继续生成 raw_segments
  -> PDF / DOC / DOCX / HTML 等即使暂时不能完整解析，也要登记 raw_documents，并记录 parse_status
```

`raw_documents` 的核心职责不是存知识片段，而是回答：

| 问题 | 说明 |
|---|---|
| 这个文件是谁 | `document_key`、`title` |
| 它在哪里 | `source_uri`、`relative_path`、`file_name` |
| 它是什么 | `file_type`、`document_type`、`source_type` |
| 它属于什么上下文 | `scope_json`、`tags_json` |
| 它是否被处理成功 | `content_hash`、`structure_quality`、`processing_profile_json`、`metadata_json` |

### 2. 他做了啥

Claude Mining 当前已经能把 Markdown 文档写入 `raw_documents`，但字段使用还比较薄。

当前实现位置：

| 文件 | 作用 |
|---|---|
| `knowledge_mining/mining/db.py` | `insert_raw_document()` 执行 SQL insert |
| `knowledge_mining/mining/publishing/__init__.py` | 调用 `insert_raw_document()` 写文档记录 |

当前实际写入：

| 字段 | 当前是否写入 | 当前来源 |
|---|---:|---|
| `id` | 是 | 自动 UUID |
| `publish_version_id` | 是 | 当前版本 |
| `document_key` | 是 | `profile.file_path` |
| `source_uri` | 是 | `profile.file_path` |
| `file_name` | 是 | `Path(profile.file_path).name` |
| `file_type` | 是 | 写死为 `markdown` |
| `content_hash` | 是 | 错误地使用 `content_hash(profile.file_path)` |
| `source_type` | 是 | `profile.source_type` |
| `scope_json` | 是 | `profile.scope_json` |
| `tags_json` | 是 | `profile.tags_json` |
| `structure_quality` | 是 | `profile.structure_quality` |
| `metadata_json` | 是 | 固定 `{}` |

当前主要问题：

| 问题 | 影响 |
|---|---|
| `file_type` 写死为 `markdown` | 不能支持通用文件夹中的 html/pdf/doc/docx/txt |
| `content_hash` 用路径 hash | 内容变化无法识别，路径变化会误判内容变化 |
| `relative_path` 没写 | 无法保存批次根目录下的稳定相对路径 |
| `document_type` 没写 | command/feature/procedure 等分类无法给 Serving 使用 |
| `title` 没写 | 文档标题无法展示和检索 |
| `metadata_json` 固定 `{}` | parse_status、skip_reason、推断依据都丢失 |
| 产品/网元兼容字段未处理 | 后续应该统一进入 `scope_json`，不再放外层 |
| 不可解析文件没有登记 | PDF/DOC/DOCX/HTML 等会直接消失 |

真实语料验证时，38 个文档里：

| 检查项 | 结果 |
|---|---:|
| `document_type IS NULL` | 38 |
| `relative_path IS NULL` | 38 |
| `normalized_storage_uri IS NULL` | 38 |

这说明当前实现只是“能跑通 Markdown demo”，还不是完整的文档级资产登记。

### 3. 我们的目标是啥

#### 3.1 `source_batch` 和路径模型

每个批次都是独立输入，不要求来自同一个大目录。

```text
source_batch A:
  input_root = D:/upload/batch_a

source_batch B:
  input_root = E:/tmp/new_docs
```

对每个文件：

| 字段 | 定义 |
|---|---|
| `source_uri` | 后端实际读取这个文件的位置 |
| `relative_path` | 文件相对本批次 input_root 的路径 |
| `document_key` | M1 先使用规范化后的 `relative_path` |
| `content_hash` | 文件内容 hash，不是路径 hash |

例子：

```text
input_root = D:/upload/batch_001
file = D:/upload/batch_001/commands/add_apn.md
```

对应：

| 字段 | 值 |
|---|---|
| `source_uri` | `D:/upload/batch_001/commands/add_apn.md` |
| `relative_path` | `commands/add_apn.md` |
| `file_name` | `add_apn.md` |
| `document_key` | `commands/add_apn.md` |
| `content_hash` | 文件内容 hash |

未来后端上传文件夹时：

```text
storage_root_uri = storage://uploads/batch_20260417_001
relative_path = commands/add_apn.md
source_uri = storage://uploads/batch_20260417_001/commands/add_apn.md
```

这样不会依赖用户本地绝对路径。

#### 3.2 批次级默认信息

用户在前端填写的：

```text
这一批属于命令
这一批属于某个网元
这一批属于某个项目
```

不需要外部元数据文件，应该作为本次 Mining 请求参数，并写入 `source_batches.metadata_json`。

建议 `source_batches.metadata_json` 结构：

```json
{
  "ingest_mode": "folder_scan",
  "storage_root_uri": "storage://uploads/batch_20260417_001",
  "original_root_name": "核心网命令资料",
  "default_document_type": "command",
  "default_source_type": "manual_upload",
  "batch_scope": {
    "product": "CloudCore",
    "product_version": "V100R023",
    "network_elements": ["SMF", "UPF"],
    "project": "某项目"
  },
  "tags": ["command", "core_network"]
}
```

每个 `raw_documents` 可以继承这些默认值：

| 批次字段 | 文档字段 |
|---|---|
| `default_document_type` | `raw_documents.document_type` 默认值 |
| `default_source_type` | `raw_documents.source_type` 默认值 |
| `batch_scope` | 合并进 `raw_documents.scope_json` |
| `tags` | 合并进 `raw_documents.tags_json` |

#### 3.3 产品 / 版本 / 网元统一进入 `scope_json`

`raw_documents` 外层不再保留：

```text
product
product_version
network_element
```

统一放进：

```json
{
  "product": "CloudCore",
  "product_version": "V100R023",
  "network_elements": ["SMF", "UPF"],
  "project": "某项目",
  "scenario": "N4 interface"
}
```

原因：

| 原因 | 说明 |
|---|---|
| 更通用 | 专家文档、项目文档、培训材料也能表达 |
| 避免冗余 | 不会同一信息写两份 |
| 避免冲突 | 不会外层和 JSON 不一致 |
| 方便扩展 | 后续新增 `region/site/vendor/domain` 不用改表 |

### 4. 建议 `raw_documents` 最终字段

我建议 `raw_documents` 收敛为下面这些字段。

| 字段 | 是否保留 | 说明 |
|---|---:|---|
| `id` | 是 | 主键 |
| `publish_version_id` | 是 | 所属发布版本 |
| `document_key` | 是 | 稳定文档身份；M1 使用规范化 `relative_path` |
| `source_uri` | 是 | 后端实际读取位置 |
| `relative_path` | 是 | 相对本批次 input_root 的路径 |
| `file_name` | 是 | 文件名 |
| `file_type` | 是 | 物理格式：markdown/html/pdf/doc/docx/txt/other |
| `source_type` | 是 | 来源方式：manual_upload/folder_scan/official_vendor 等 |
| `title` | 是 | 文档标题，可从 H1、HTML title、文件名推断 |
| `document_type` | 是 | 内容类型：command/feature/procedure/troubleshooting 等 |
| `content_hash` | 是 | 文件内容 hash |
| `copied_from_document_id` | 是 | 物理快照复制来源 |
| `origin_batch_id` | 是 | 来源批次 |
| `created_at` | 是 | 创建时间 |
| `scope_json` | 是 | 产品、版本、网元、项目、场景等上下文 |
| `tags_json` | 是 | 标签 |
| `structure_quality` | 是 | 结构质量 |
| `processing_profile_json` | 是 | 解析/处理过程信息 |
| `metadata_json` | 是 | 其他扩展信息 |

建议从外层删除，或至少 M1 不使用：

| 字段 | 处理建议 | 原因 |
|---|---|---|
| `product` | 删除 | 进入 `scope_json.product` |
| `product_version` | 删除 | 进入 `scope_json.product_version` |
| `network_element` | 删除 | 进入 `scope_json.network_elements` |
| `raw_storage_uri` | 删除或 M1 不使用 | 和 `source_uri` 容易混淆 |
| `normalized_storage_uri` | 删除或 M1 不使用 | M1 不生成稳定规范化文件 |
| `conversion_profile_json` | 改名为 `processing_profile_json` | 不只表示转换，也表示解析/抽取 |

### 5. 字段语义说明

#### 5.1 `source_uri` vs `relative_path`

| 字段 | 含义 | 稳定性 | 用途 |
|---|---|---:|---|
| `source_uri` | 后端实际读取位置 | 不稳定 | 后台读取、调试、溯源 |
| `relative_path` | 相对本批次 input_root 的路径 | 相对稳定 | 展示、生成 `document_key`、版本比较 |

它们不是重复。

例子：

| 环境 | `source_uri` | `relative_path` |
|---|---|---|
| 本地扫描 | `D:/upload/batch001/commands/add_apn.md` | `commands/add_apn.md` |
| 后端上传 | `storage://uploads/batch001/commands/add_apn.md` | `commands/add_apn.md` |
| 临时解压 | `/tmp/batch001/commands/add_apn.md` | `commands/add_apn.md` |

#### 5.2 `file_type` / `source_type` / `document_type`

这三个字段都保留，因为它们是三个不同维度。

| 字段 | 问题 | 例子 |
|---|---|---|
| `file_type` | 文件物理格式是什么 | `markdown`、`html`、`pdf`、`docx` |
| `source_type` | 资料来源方式是什么 | `manual_upload`、`folder_scan`、`official_vendor` |
| `document_type` | 文档内容语义是什么 | `command`、`feature`、`procedure`、`expert_note` |

例子：

| 文件 | `file_type` | `source_type` | `document_type` |
|---|---|---|---|
| `commands/add_apn.md` | `markdown` | `manual_upload` | `command` |
| `专家经验.docx` | `docx` | `manual_upload` | `expert_note` |
| `N4接口说明.html` | `html` | `folder_scan` | `feature` |
| `厂家手册.pdf` | `pdf` | `official_vendor` | `reference` |

#### 5.3 `document_key` vs `content_hash`

| 字段 | 含义 | 是否随内容变化 |
|---|---|---:|
| `document_key` | 文档身份 | 不应该因为内容变化而变化 |
| `content_hash` | 内容指纹 | 内容变化必须变化 |

M1 策略：

```text
document_key = normalized(relative_path)
content_hash = hash(file bytes or text content)
```

判断规则：

| 情况 | 判断 |
|---|---|
| `relative_path` 一样，`content_hash` 一样 | 同一文档，未变化 |
| `relative_path` 一样，`content_hash` 不一样 | 同一文档，有更新 |
| `relative_path` 不一样，`content_hash` 一样 | 可能是移动/重命名，M1 暂不强判 |
| `relative_path` 不一样，`content_hash` 不一样 | 默认不同文档 |

### 6. 他下一步应该怎么做

#### 6.1 修 `RawDocumentData`

当前对象偏 Markdown：

```python
RawDocumentData(
    file_path,
    content,
    frontmatter,
    manifest_meta,
)
```

建议改成：

| 字段 | 说明 |
|---|---|
| `document_key` | 稳定 key |
| `source_uri` | 实际读取路径 |
| `relative_path` | 相对批次根目录路径 |
| `file_name` | 文件名 |
| `file_type` | 文件类型 |
| `content_hash` | 文件内容 hash |
| `content` | 可读文本内容；二进制不可读时可为空 |
| `parse_status` | `parsed/skipped/unsupported/failed` |
| `structure_quality` | 结构质量 |
| `title` | 标题 |
| `metadata_json` | 推断依据、错误原因等 |

#### 6.2 修 `content_hash`

必须改掉：

```python
content_hash(profile.file_path)
```

改为：

| 文件类型 | hash 来源 |
|---|---|
| 文本文件 | 文件原始文本或 bytes |
| 二进制文件 | 文件 bytes |
| 读取失败 | 不伪造 hash，记录失败状态 |

#### 6.3 修 `file_type`

不能写死：

```python
file_type = "markdown"
```

应该按后缀识别：

| 后缀 | `file_type` |
|---|---|
| `.md/.markdown` | `markdown` |
| `.txt` | `txt` |
| `.html/.htm` | `html` |
| `.pdf` | `pdf` |
| `.doc` | `doc` |
| `.docx` | `docx` |
| 其他 | `other` |

#### 6.4 修 `document_type` 和 `scope_json`

`document_type` 来源优先级建议：

| 优先级 | 来源 |
|---:|---|
| 1 | 用户本次上传时指定的 `default_document_type` |
| 2 | 目录结构 / 文件名强规则 |
| 3 | 文档标题 / 内容弱推断 |
| 4 | 无法判断则 `other` 或 `NULL`，这个需要我们后续定 |

`scope_json` 来源：

| 来源 | 进入字段 |
|---|---|
| 用户上传时填写的产品/版本/网元/项目 | `scope_json` |
| 目录结构推断出的上下文 | `scope_json` |
| 内容中弱推断出的上下文 | `scope_json` |

外层不再写 `product/product_version/network_element`。

#### 6.5 修 publishing

`raw_documents` 写入时必须覆盖：

| 字段 | 要求 |
|---|---|
| `document_key` | 写 |
| `source_uri` | 写 |
| `relative_path` | 写 |
| `file_name` | 写 |
| `file_type` | 写 |
| `source_type` | 写 |
| `title` | 能推断就写 |
| `document_type` | 写默认值或推断值 |
| `content_hash` | 文件内容 hash |
| `origin_batch_id` | 写 source batch id |
| `scope_json` | 写 |
| `tags_json` | 写 |
| `structure_quality` | 写 |
| `processing_profile_json` | 写 |
| `metadata_json` | 写 parse_status / skip_reason / inferred_by |

#### 6.6 补测试

| 测试 | 目标 |
|---|---|
| Markdown 文档落库 | `relative_path/file_type/content_hash/document_type` 正确 |
| txt 文档落库 | `file_type=txt`，可解析 |
| html 文档落库 | `file_type=html`，至少登记 |
| pdf/docx 文档落库 | 不解析也登记，`parse_status=unsupported` |
| hash 测试 | 内容变则 `content_hash` 变 |
| 路径测试 | 路径变但内容不变时，`content_hash` 不变 |
| 批次默认类型 | 用户传 `default_document_type=command` 时文档继承 |
| scope 测试 | 产品/版本/网元进入 `scope_json` |
| 真实语料落库检查 | 不再出现所有 `document_type` 都是 NULL |

### 7. 给 Claude Mining 的要求草稿

```text
主题 2：raw_documents 文档级落库需要修订。

raw_documents 不是 Markdown demo 的最小登记表，而是 source artifact 的文档级资产表。
每个 source_batch 有自己的 input_root/storage_root_uri，relative_path 是相对该批次根目录的稳定路径，source_uri 是后端实际读取位置。

请修正以下问题：
1. file_type 不得写死为 markdown，必须按文件后缀识别 markdown/html/pdf/doc/docx/txt/other。
2. content_hash 必须来自文件内容或文件 bytes，不得使用路径字符串 hash。
3. relative_path 必须写入 raw_documents。
4. document_type/title/source_type/scope_json/tags_json 必须按批次默认参数、路径、文件名和内容推断后写入。
5. 产品、版本、网元等上下文不得写入 raw_documents 外层字段，统一进入 scope_json。
6. source_batches.metadata_json 需要记录批次级默认信息，例如 default_document_type、default_source_type、batch_scope、tags、storage_root_uri、original_root_name。
7. raw_documents.metadata_json 需要记录 parse_status、skip_reason、inferred_by 等处理状态。
8. conversion_profile_json 建议改为 processing_profile_json，用于记录 parser、normalization、extraction quality 等处理过程。
9. PDF/DOC/DOCX/HTML 即使暂不解析，也应登记 raw_documents，并标记 parse_status=unsupported/skipped。
```

### 8. 当前判断

主题 2 也属于必须修。

否则即使主题 1 做到了递归发现文件，入库时仍然会丢失文档级身份、路径、类型、内容 hash、处理状态和 scope 信息。后续 Serving、版本比较、问题追溯都会受到影响。

## 主题 3：文件解析与 `raw_segments` 切片

### 1. 当前讨论结论

管理员确认：

```text
不同文件类型应该走不同解析器。
M1 只做 Markdown 和 TXT 的解析与切片。
HTML / PDF / DOC / DOCX 当前只登记 raw_documents，不生成 raw_segments。
```

同时，管理员认可 `raw_segments` 当前字段存在定制化和混淆问题，倾向现在改表。

主题 3 的核心结论：

```text
最终入库的是切片后的 raw_segments。
结构化阶段不作为单独服务对象，而是为切片服务。
不同结构有不同切片方法，并给切片附带不同 structure_json/source_offsets_json/entity_refs_json 等元数据。
```

### 2. 他做了啥

Claude Mining 当前已经实现了 Markdown 解析和基础切片。

当前流程：

```text
Markdown content
  -> markdown-it-py tokens
  -> ContentBlock
  -> SectionNode tree
  -> RawSegmentData
  -> asset_raw_segments
```

当前实现位置：

| 模块 | 文件 | 作用 |
|---|---|---|
| structure parser | `knowledge_mining/mining/structure/__init__.py` | 把 Markdown 解析成 `SectionNode` 和 `ContentBlock` |
| segmentation | `knowledge_mining/mining/segmentation/__init__.py` | 把 Section / Block 切成 `RawSegmentData` |
| models | `knowledge_mining/mining/models.py` | 定义 `ContentBlock`、`SectionNode`、`RawSegmentData` |
| publishing | `knowledge_mining/mining/publishing/__init__.py` | 把 segment 写入 `asset_raw_segments` |

当前 Markdown parser 能识别：

| Markdown 内容 | 当前识别 |
|---|---|
| 标题 | `heading` |
| 普通段落 | `paragraph` |
| Markdown 表格 | `table` |
| Markdown 内 HTML table | `html_table` |
| 代码块 | `code` |
| 列表 | `list` |
| 引用块 | `blockquote` |
| 其他 HTML | `raw_html` |

当前切片规则：

| 内容块 | 当前怎么切 |
|---|---|
| `table` | 单独切一个 segment |
| `html_table` | 单独切一个 segment |
| `code` | 单独切一个 segment |
| 普通段落 | 和同章节下连续普通内容合并 |
| `list` | 当前也会和普通内容合并 |
| `blockquote` | 当前也会和普通内容合并 |
| `raw_html` | 当前也会和普通内容合并 |
| child section | 递归处理，`section_path` 带父章节 |

当前实现方向基本是：

```text
结构化 = 先识别章节、段落、表格、列表、代码块。
切片 = 再决定哪些内容块组合成一个 raw_segment。
```

这个方向是对的，但字段设计和落库细节需要收敛。

### 3. 结构化与切片如何协同

结构化回答：

```text
文档有哪些章节？
每段内容属于哪个章节？
每个内容块是什么形态？
```

切片回答：

```text
哪些内容块应该作为一个知识单元入库？
```

示例：

```md
# ADD APN 命令

## 参数说明

| 参数 | 说明 |
|---|---|
| APN | 接入点名称 |

## 示例

```mml
ADD APN: APN="internet";
```
```

结构化后大致是：

```text
ADD APN 命令
  参数说明
    table
  示例
    code
```

切片后入库：

| segment | `section_path` | `block_type` | `raw_text` |
|---|---|---|---|
| 1 | `["ADD APN 命令", "参数说明"]` | `table` | 参数表格 |
| 2 | `["ADD APN 命令", "示例"]` | `code` | 示例命令 |

所以最终入库的是 raw segment，而不是完整结构树。

结构化结果用于：

| 用途 | 说明 |
|---|---|
| 指导切片 | 表格/代码/列表等结构采用不同切法 |
| 提供上下文 | 给 segment 附带 `section_path`、`section_title` |
| 提供结构元数据 | 给 segment 附带 `structure_json` |
| 提供位置元数据 | 给 segment 附带 `source_offsets_json` |

### 4. 当前主要问题

#### 4.1 字段混淆：`segment_type` / `block_type` / `section_role`

当前三个字段容易打架。

| 字段 | 当前想表达 | 问题 |
|---|---|---|
| `block_type` | 结构类型，如 paragraph/table/code/list | 清楚，应该保留 |
| `section_role` | 所在章节语义，如 parameter/example/note | 还可以，但名字不够准确 |
| `segment_type` | 片段语义，如 command/parameter/example/table/paragraph | 容易和前两个重复 |

例如“参数说明”章节里的表格：

| 字段 | 可能值 |
|---|---|
| `block_type` | `table` |
| `section_role` | `parameter` |
| `segment_type` | `table` 或 `parameter` |

`segment_type` 到底表达结构还是语义，会变得不清楚。

#### 4.2 `command_name` 偏定制

`command_name` 明显偏通信命令文档。

问题：

| 问题 | 说明 |
|---|---|
| 定制化 | 只适合命令类语料 |
| 不通用 | 专家文档、项目文档、标准文档不一定有 command |
| 容易扩散 | 以后可能又要加 `feature_name`、`alarm_name`、`procedure_name` |

建议改为通用实体引用：

```json
entity_refs_json = [
  {"type": "command", "name": "ADD APN"},
  {"type": "network_element", "name": "SMF"},
  {"type": "feature", "name": "N4 interface"}
]
```

#### 4.3 `heading_level` 可并入结构化章节路径

当前有：

| 字段 | 作用 |
|---|---|
| `section_path` | 完整章节路径 |
| `section_title` | 当前章节标题 |
| `heading_level` | 当前标题级别 |

建议后续让 `section_path` 变成结构化数组：

```json
[
  {"title": "ADD APN", "level": 1},
  {"title": "参数说明", "level": 2}
]
```

这样 `heading_level` 可以删除或不再作为外层字段。

#### 4.4 `structure_json` 和 `source_offsets_json` 需要规范

这两个字段方向正确，但必须规定写法。

`structure_json` 应保存不同结构的细节：

| `block_type` | `structure_json` 最少内容 |
|---|---|
| `paragraph` | `paragraph_count` |
| `list` | `items`、`ordered` |
| `table` | `columns`、`rows` 或至少 `row_count/col_count` |
| `code` | `language` |
| `html_table` | `raw_html_preserved`、`row_count/col_count` |
| `raw_html` | `raw_html_preserved=true` |

`source_offsets_json` 应保存来源位置：

```json
{
  "parser": "markdown-it-py",
  "block_index": 5,
  "start_line": 20,
  "end_line": 28
}
```

M1 可以不做到字符级精确，但不能长期为空。

#### 4.5 当前实现问题

| 问题 | 影响 |
|---|---|
| 真实验证里 620 个 segment 全是 `paragraph` | 真实风格结构覆盖不足 |
| 表格内容被压扁 | 行列关系丢失 |
| 列表内容被压扁 | 条目和层级丢失 |
| `source_offsets_json` 基本为空 | 后续引用定位弱 |
| `normalized_text` 和 `normalized_hash` 使用的规范化规则不一致 | 去重和调试不一致 |
| 没有最大长度控制 | 长章节可能生成超长 segment |
| TXT parser 缺失 | M1 目标要求 MD + TXT，但当前只有 Markdown |

### 5. 我们的目标是啥

#### 5.1 解析器边界

M1 解析器边界：

| 文件类型 | M1 行为 |
|---|---|
| `.md/.markdown` | 解析并生成 raw_segments |
| `.txt` | 解析并生成 raw_segments |
| `.html/.htm` | 只登记 raw_documents，不生成 raw_segments |
| `.pdf` | 只登记 raw_documents，不生成 raw_segments |
| `.doc/.docx` | 只登记 raw_documents，不生成 raw_segments |
| other | 可登记或跳过，记录原因 |

即：

```text
raw_documents 不一定都有 raw_segments。
只有 M1 支持的 parser 才生成 raw_segments。
```

#### 5.2 最终入库的是切片

M1 不把完整结构树作为服务对象入库。

结构化阶段用于指导切片，并把结构信息沉淀到每个 raw_segment：

| 信息 | 落库字段 |
|---|---|
| 原始文本 | `raw_text` |
| 规范化文本 | `normalized_text` |
| 所属章节 | `section_path`、`section_title` |
| 内容结构 | `block_type`、`structure_json` |
| 语义角色 | `semantic_role` |
| 来源位置 | `source_offsets_json` |
| 识别实体 | `entity_refs_json` |

#### 5.3 改表目标

管理员建议现在改 `raw_segments` 表，减少定制化和混淆。

目标：

```text
raw_segments 保留“结构 + 语义 + 实体 + 溯源”四类信息。
```

建议删除或废弃：

| 字段 | 原因 |
|---|---|
| `segment_type` | 和 `block_type/section_role` 混淆 |
| `command_name` | 太定制 |
| `heading_level` | 可进入结构化 `section_path` |

建议保留或新增：

| 字段 | 含义 |
|---|---|
| `block_type` | 结构类型 |
| `semantic_role` | 语义角色，替代 `section_role` |
| `entity_refs_json` | 识别出的命令、网元、术语等实体 |
| `structure_json` | 结构细节 |
| `source_offsets_json` | 原文位置 |

### 6. 建议 `raw_segments` 最终字段

| 字段 | 说明 |
|---|---|
| `id` | 主键 |
| `publish_version_id` | 所属版本 |
| `raw_document_id` | 来源文档 |
| `segment_key` | 稳定切片 key |
| `segment_index` | 文档内顺序 |
| `section_path` | 结构化章节路径 |
| `section_title` | 当前章节标题 |
| `block_type` | 结构类型 |
| `semantic_role` | 语义角色 |
| `raw_text` | 原文 |
| `normalized_text` | 规范化文本 |
| `content_hash` | 原文 hash |
| `normalized_hash` | 规范化 hash |
| `token_count` | token 数 |
| `copied_from_segment_id` | 快照复制来源 |
| `structure_json` | 表格/列表/代码等结构元数据 |
| `source_offsets_json` | 原文位置 |
| `entity_refs_json` | 识别出的命令、网元、术语等实体 |
| `metadata_json` | 其他扩展 |

`block_type` 建议值：

```text
paragraph
table
list
code
blockquote
html_table
raw_html
unknown
```

`semantic_role` 建议值：

```text
concept
parameter
example
note
procedure_step
troubleshooting_step
constraint
alarm
checklist
unknown
```

### 7. 他下一步应该怎么做

#### 7.1 改 schema

需要同步修改：

| 文件 | 动作 |
|---|---|
| `knowledge_assets/schemas/001_asset_core.sql` | 调整 `raw_segments` 字段 |
| `knowledge_assets/schemas/001_asset_core.sqlite.sql` | 同步 SQLite DDL |
| `knowledge_assets/schemas/README.md` | 更新字段说明和结构 JSON 约定 |
| 架构/数据文档 | 同步 raw_segments 新语义 |

调整建议：

| 当前字段 | 处理 |
|---|---|
| `segment_type` | 删除或废弃 |
| `section_role` | 改为 `semantic_role` |
| `command_name` | 删除，迁移到 `entity_refs_json` |
| `heading_level` | 删除或放入结构化 `section_path` |
| `entity_refs_json` | 新增 |

#### 7.2 改实现

Claude Mining 需要改：

| 当前 | 改成 |
|---|---|
| `segment_type` | 不再作为主要字段 |
| `section_role` | 输出 `semantic_role` |
| `command_name` | 输出到 `entity_refs_json` |
| `section_path` | 尽量输出结构化路径 |
| `structure_json` | 按 `block_type` 输出稳定结构 |
| `source_offsets_json` | 至少填 parser/block_index/line range |
| Markdown 切片 | 输出 block_type + semantic_role + structure_json |
| TXT 切片 | 新增，输出 block_type=paragraph，semantic_role=concept/unknown |
| 非 MD/TXT | 不进入 raw_segments |

#### 7.3 修规范化

`normalized_text` 和 `normalized_hash` 必须使用同一套规范化逻辑：

```text
normalized_text = normalize_text(raw_text)
normalized_hash = hash(normalized_text)
```

#### 7.4 增加长度控制

对普通段落或连续文本增加最大长度阈值：

```text
max_segment_chars
max_segment_tokens
```

超过阈值后按段落或 block 拆分。

#### 7.5 补测试

| 测试 | 目标 |
|---|---|
| Markdown 表格 | `block_type=table`，`structure_json` 有 columns/rows 或 row_count/col_count |
| Markdown 列表 | `block_type=list`，`structure_json.items` 存在 |
| Markdown 代码块 | `block_type=code`，`structure_json.language` 存在 |
| Markdown HTML table | `block_type=html_table`，保留 raw html 信息 |
| TXT 文件 | 生成 paragraph segments |
| PDF/DOCX/HTML 文件 | 只登记 raw_documents，不生成 raw_segments |
| entity refs | 命令名进入 `entity_refs_json`，不是 `command_name` |
| offsets | `source_offsets_json` 非空 |
| normalization | `normalized_text` 与 `normalized_hash` 一致 |

### 8. 给 Claude Mining 的要求草稿

```text
主题 3：文件解析与 raw_segments 切片需要修订，并需要调整 raw_segments 表结构。

M1 只做 Markdown 和 TXT parser。
HTML/PDF/DOC/DOCX 当前只登记 raw_documents，不生成 raw_segments。

结构化阶段不作为单独服务对象入库，而是为切片服务。
最终入库的是 raw_segments。不同结构采用不同切片策略，并把结构信息写入 structure_json，把来源位置写入 source_offsets_json，把识别出的命令/网元/术语等写入 entity_refs_json。

raw_segments 当前字段存在混淆和定制化：
1. segment_type 与 block_type/section_role 容易混淆，建议删除或废弃。
2. section_role 改名为 semantic_role。
3. command_name 太定制，删除，改为 entity_refs_json。
4. heading_level 可放入结构化 section_path，外层字段删除或废弃。

请同步修改 PostgreSQL/SQLite schema、schema README、架构/数据文档和 Mining 实现。
同时补 TXT parser、source_offsets_json、structure_json 规范、normalized_text/hash 一致性、最大 segment 长度控制和对应测试。
```

### 9. 当前判断

主题 3 属于必须修，且管理员倾向现在改表。

当前 `raw_segments` 的方向是对的，但字段设计仍带有命令文档定制化，并且 `segment_type/block_type/section_role/command_name` 容易混淆。

应趁 M1 早期把表收敛为：

```text
block_type = 结构
semantic_role = 语义
entity_refs_json = 实体
structure_json = 结构细节
source_offsets_json = 来源位置
```

## 主题 4：`canonical_segments` 去重归并与表结构优化

### 1. 当前讨论结论

主题 4 不只是 Claude Mining 实现要修，表也需要优化。

原因：

```text
raw_segments 已决定去定制化，改成 block_type + semantic_role + entity_refs_json。
canonical_segments 和 canonical_segment_sources 必须同步对齐。
否则 raw 层一套概念，canonical 层另一套概念，Serving 会很难使用。
```

当前涉及两张表：

| 表 | 作用 |
|---|---|
| `canonical_segments` | 归并后的标准知识片段 |
| `canonical_segment_sources` | canonical 片段与 raw segment 的来源关系 |

### 2. 他做了啥

Claude Mining 当前实现了 `canonicalization` 模块：

| 文件 | 作用 |
|---|---|
| `knowledge_mining/mining/canonicalization.py` | raw segments 去重归并，生成 canonical + source mappings |

当前声称三层去重：

| 层 | 规则 |
|---|---|
| 第 1 层 | `content_hash` 相同，认为完全重复 |
| 第 2 层 | `normalized_hash` 相同，认为归一化重复 |
| 第 3 层 | `simhash + jaccard` 相似，认为近似重复 |

真实语料验证结果：

| 表 | 数量 |
|---|---:|
| `raw_segments` | 620 |
| `canonical_segments` | 284 |
| `canonical_segment_sources` | 620 |

### 3. 当前实现问题

#### 3.1 三层去重逻辑实际被第一层短路

当前第一层逻辑会对所有 `content_hash` 分组都创建 canonical，不区分 group size。

问题：

```text
即使某个 content_hash 分组只有 1 个 segment，也会立即创建 canonical 并标记 assigned。
因此所有 segments 在第一层就被处理掉。
normalized_hash 和 simhash+jaccard 后两层基本没有机会生效。
```

合理逻辑应该是：

```text
content_hash 分组：
  group size > 1 -> 合并 exact_duplicate
  group size = 1 -> 留给下一层 normalized_hash / near duplicate
```

#### 3.2 variant 逻辑依赖旧字段

当前变体判断依赖：

```text
profile.product
profile.product_version
profile.network_element
```

但前面已经决定：

```text
产品 / 版本 / 网元统一进入 scope_json。
外层不再保留 product/product_version/network_element。
```

因此 canonicalization 应改为基于 `scope_json` 判断 scope 差异。

#### 3.3 canonical 字段仍偏定制

当前 `canonical_segments` 里存在：

| 字段 | 问题 |
|---|---|
| `segment_type` | 和 raw_segments 的新模型冲突，概念混乱 |
| `section_role` | 应统一改为 `semantic_role` |
| `command_name` | 偏命令文档定制，不通用 |
| `variant_policy` | `require_product_version`、`require_ne` 偏产品/网元 |

### 4. 我们的目标是啥

#### 4.1 canonical 层的作用

canonical 层需要保留。

原因：

| 原因 | 说明 |
|---|---|
| raw 是来源视角 | 同一知识可能出现在多个文件 |
| canonical 是服务视角 | Serving 不应该每次面对大量重复片段 |
| canonical 能选主 | 多个来源里选择一个主文本 |
| canonical 能表示变体 | scope 不同时提示用户补条件 |
| canonical 能做质量控制 | 后续可人工审核或 LLM 优化 |

关系模型：

```text
raw_segments
  多个相同 / 相近 / 同义 / 同 scope 知识片段
      ↓
canonical_segments
  一个服务用标准片段
      ↓
canonical_segment_sources
  记录这个 canonical 来自哪些 raw segments，以及关系是什么
```

#### 4.2 canonicalization 目标

M1 目标：

| 目标 | 说明 |
|---|---|
| 完全重复合并 | `content_hash` 一样 |
| 规范化重复合并 | `normalized_hash` 一样 |
| 近似重复谨慎处理 | simhash/jaccard 可做候选或高阈值合并 |
| 来源映射完整 | 每个 canonical 能追到所有 raw segment |
| 变体识别通用 | 基于 `scope_json`，不绑定 product/ne |
| 冲突先标记 | 不要乱合并冲突内容 |
| Serving 读取稳定 | canonical 是服务主入口 |

### 5. 表结构优化建议

#### 5.1 `canonical_segments` 建议字段

建议 `canonical_segments` 和新 `raw_segments` 模型对齐：

| 字段 | 说明 |
|---|---|
| `id` | 主键 |
| `publish_version_id` | 所属版本 |
| `canonical_key` | 稳定 canonical key |
| `block_type` | 主结构类型，如 paragraph/table/list/code |
| `semantic_role` | 语义角色，如 concept/parameter/example/note |
| `title` | 标题 |
| `canonical_text` | 标准正文 |
| `summary` | 摘要 |
| `search_text` | 检索文本 |
| `entity_refs_json` | 聚合实体，如 command/network_element/feature/term |
| `scope_json` | 该 canonical 适用的 scope 或合并后的 scope |
| `has_variants` | 是否有变体 |
| `variant_policy` | 变体选择策略 |
| `quality_score` | 质量分 |
| `created_at` | 创建时间 |
| `metadata_json` | 扩展信息 |

建议删除或废弃：

| 当前字段 | 处理 |
|---|---|
| `segment_type` | 删除 |
| `section_role` | 改为 `semantic_role` |
| `command_name` | 删除，进入 `entity_refs_json` |

建议新增：

| 新字段 | 原因 |
|---|---|
| `block_type` | canonical 也要知道自己是表格/代码/段落 |
| `entity_refs_json` | 通用实体表达 |
| `scope_json` | 表达适用范围或合并后的 scope |

#### 5.2 `variant_policy` 通用化

当前偏定制：

```text
none
prefer_latest
require_version
require_product_version
require_ne
```

建议改成：

```text
none
prefer_latest
require_scope
require_disambiguation
manual_review
```

| 值 | 含义 |
|---|---|
| `none` | 无变体 |
| `prefer_latest` | 默认选最新版本或最新来源 |
| `require_scope` | 必须按 scope 匹配 |
| `require_disambiguation` | 需要用户补充限定条件 |
| `manual_review` | 需要人工确认 |

#### 5.3 `canonical_segment_sources` relation_type 通用化

当前 relation_type：

```text
primary
exact_duplicate
near_duplicate
version_variant
product_variant
ne_variant
conflict_candidate
```

问题：

| 值 | 问题 |
|---|---|
| `product_variant` | 产品定制 |
| `ne_variant` | 网元定制 |
| `version_variant` | 可以保留，但更通用地说也是 scope 差异 |

建议改成：

```text
primary
exact_duplicate
normalized_duplicate
near_duplicate
scope_variant
conflict_candidate
```

具体差异维度放到 `metadata_json`：

```json
{
  "variant_dimensions": ["product_version", "network_elements"],
  "primary_scope": {
    "product_version": "V1",
    "network_elements": ["SMF"]
  },
  "source_scope": {
    "product_version": "V2",
    "network_elements": ["UPF"]
  }
}
```

#### 5.4 `canonical_segment_sources` 字段保留

当前字段大体可保留：

| 字段 | 说明 |
|---|---|
| `id` | 主键 |
| `publish_version_id` | 所属版本 |
| `canonical_segment_id` | canonical |
| `raw_segment_id` | raw segment |
| `relation_type` | 来源关系 |
| `is_primary` | 是否主来源 |
| `priority` | 来源优先级 |
| `similarity_score` | 相似度 |
| `diff_summary` | 差异摘要 |
| `metadata_json` | 变体维度、scope 差异、算法信息 |

主要优化：

| 项 | 处理 |
|---|---|
| `relation_type` 枚举 | 改通用 |
| `priority` | 当前全 100，要真正使用 |
| `metadata_json` | 规范写 variant/similarity 信息 |

### 6. 他下一步应该怎么做

#### 6.1 修三层去重逻辑

合理流程：

```text
unassigned = all raw segments

第 1 层：content_hash
  只处理 group size > 1
  合并 exact_duplicate
  标记 assigned

第 2 层：normalized_hash
  在剩余 unassigned 中处理 group size > 1
  合并 normalized_duplicate
  标记 assigned

第 3 层：near duplicate
  在剩余 unassigned 中做相似度判断
  M1 可选择：
    A. 只标记 conflict_candidate / near_duplicate candidate
    B. 在高阈值下合并 near_duplicate

最后：
  所有仍未 assigned 的 segment
  各自生成 canonical primary
```

关键：

```text
单例不能在第一层就被吃掉。
```

#### 6.2 同步修改 schema

需要同步：

| 文件 | 动作 |
|---|---|
| `knowledge_assets/schemas/001_asset_core.sql` | 修改 canonical 相关字段/枚举 |
| `knowledge_assets/schemas/001_asset_core.sqlite.sql` | 同步 SQLite DDL |
| `knowledge_assets/schemas/README.md` | 更新 canonical 字段说明 |
| 架构/数据文档 | 同步 canonical 新语义 |

#### 6.3 修 canonical 字段映射

如果 `raw_segments` 改成：

```text
block_type
semantic_role
entity_refs_json
scope_json
```

那 `canonical_segments` 也要同步：

| 当前字段 | 建议 |
|---|---|
| `segment_type` | 删除或废弃 |
| `section_role` | 改为 `semantic_role` |
| `command_name` | 删除，改用 `entity_refs_json` |
| 新增 `block_type` | canonical 保留主结构类型 |
| 新增 `entity_refs_json` | 聚合 raw entities |
| 新增 `scope_json` | 适用 scope |

#### 6.4 主来源选择

M1 可以先简单，但必须显式：

```text
每个 canonical 有且只有一个 primary source。
canonical_segment_sources.is_primary = true。
primary priority = 0。
其他来源 priority > 0。
```

当前 priority 全是 100，需要修正。

#### 6.5 补测试

| 测试 | 目标 |
|---|---|
| exact duplicate | 相同 `content_hash` 合并 |
| normalized duplicate | 内容只差空格/大小写/标点时合并 |
| singletons | 单例不要阻断后续 normalized/simhash |
| scope variant | `scope_json` 不同但内容相同，标记 `scope_variant` |
| conflict candidate | scope 相同但文本冲突，标记候选或不合并 |
| primary source | 每个 canonical 只有一个 primary |
| relation metadata | `metadata_json.variant_dimensions` 正确 |
| canonical field alignment | 和 raw_segments 使用同一套 `semantic_role/entity_refs_json` |

### 7. 给 Claude Mining 的要求草稿

```text
主题 4：canonical_segments 去重归并需要修订，并同步优化 canonical 相关表结构。

canonical_segments 是 Serving 的主读取层，必须和 raw_segments 的新模型对齐。

请修正：
1. 三层去重逻辑目前被第一层 content_hash 短路，必须改成只处理 group size > 1，单例进入下一层。
2. normalized_hash 层需要新增 normalized_duplicate relation。
3. near_duplicate 在 M1 要谨慎，可高阈值合并或先标记候选。
4. variant 判断必须基于 scope_json，不再依赖 product/product_version/network_element 外层字段。
5. canonical_segments 删除/废弃 segment_type、command_name，section_role 改为 semantic_role，新增 block_type、entity_refs_json、scope_json。
6. variant_policy 改为通用枚举：none/prefer_latest/require_scope/require_disambiguation/manual_review。
7. canonical_segment_sources relation_type 改为：primary/exact_duplicate/normalized_duplicate/near_duplicate/scope_variant/conflict_candidate。
8. 具体 scope 差异维度写入 metadata_json.variant_dimensions。
9. 每个 canonical 必须有且只有一个 primary source，priority 要真实使用。
10. 同步修改 PostgreSQL/SQLite schema、schema README、架构/数据文档、Mining 实现和测试。
```

### 8. 当前判断

主题 4 属于必须修，且需要改表。

一句话结论：

```text
canonical_segments 要和新的 raw_segments 对齐，统一使用 block_type / semantic_role / entity_refs_json / scope_json。
canonical_segment_sources 要把产品/网元定制枚举改成通用 scope_variant，具体差异维度放进 metadata_json。
```

## 主题 5：`publish_versions` 发布版本控制

### 1. 当前讨论结论

主题 5 的结论：

```text
publish_versions 表本身基本够用，不需要大改。
但 Claude Mining 当前发布实现只是 demo，必须修。
```

M1 发布模型应为：

```text
每次 Mining run 创建一个新的 staging publish_version。
构建成功并校验通过后，原 active 归档，新 staging 原子切换为 active。
构建失败时，新版本标记 failed，旧 active 保持不变。
Serving 永远只读唯一 active 版本。
```

M1 可以继续使用全量物理快照，不要求本轮实现未变化文档复制。

### 2. 他做了啥

Claude Mining 当前发布流程在：

| 文件 | 作用 |
|---|---|
| `knowledge_mining/mining/publishing/__init__.py` | 写入 source_batch、publish_version、raw/canonical 数据并激活 |

当前流程：

```text
create source_batch
create publish_version(status=staging)
insert raw_documents
insert raw_segments
insert canonical_segments
insert canonical_segment_sources
update publish_version status = active
```

当前固定值：

| 字段 | 当前值 |
|---|---|
| `version_code` | 固定 `v1` |
| `batch_code` | 固定 `batch-001` |
| `status` | 先 `staging`，最后直接 `active` |
| 旧 active | 没有处理 |
| build error | 没有处理 |
| 多次运行 | 同一个 DB 大概率因唯一约束失败 |

### 3. 当前主要问题

#### 3.1 `version_code` 固定为 `v1`

`publish_versions.version_code` 是唯一的。

如果同一个数据库再跑一次，固定 `v1` 会冲突。

应自动生成或由 API 传入：

```text
pv_YYYYMMDD_HHMMSS
```

#### 3.2 `batch_code` 固定为 `batch-001`

`source_batches.batch_code` 也是唯一的。

固定 `batch-001` 会导致重复运行失败。

应自动生成或由 API 传入：

```text
batch_YYYYMMDD_HHMMSS
```

#### 3.3 激活新版本时没有归档旧 active

schema 约束要求同一时间只有一个 active。

当前逻辑只做：

```text
UPDATE current version SET status='active'
```

如果已经存在旧 active，会违反唯一 active 约束。

正确逻辑：

```text
BEGIN
  UPDATE old active SET status='archived'
  UPDATE new staging SET status='active'
COMMIT
```

#### 3.4 失败时没有标记 failed

如果中途写入失败，可能留下半成品 staging。

应记录：

| 字段 | 写入 |
|---|---|
| `status` | `failed` |
| `build_error` | 错误摘要 |
| `build_finished_at` | 失败时间 |
| `metadata_json` | 可选记录阶段、文件、异常类型 |

旧 active 不应受影响。

#### 3.5 物理快照链路字段未使用

当前全量重建一版，基本符合 M1 最简物理快照。

但尚未使用：

| 字段 | 当前情况 |
|---|---|
| `base_publish_version_id` | 未写 |
| `copied_from_document_id` | 未用 |
| `copied_from_segment_id` | 未用 |

M1 本轮可以不实现未变化文档复制，但建议写 `base_publish_version_id=旧 active id`，保留版本链。

### 4. 我们的目标是啥

M1 发布模型：

```text
old active 继续服务
      ↓
new staging 构建
      ↓
构建成功 + 校验通过
      ↓
old active -> archived
new staging -> active
```

失败时：

```text
old active 保持 active
new staging -> failed
```

最低要求：

| 要求 | 说明 |
|---|---|
| 每次 run 生成唯一 `batch_code` | 不能固定 `batch-001` |
| 每次 run 生成唯一 `version_code` | 不能固定 `v1` |
| 支持批次参数 | 用户前端输入的批次默认信息写入 `source_batches.metadata_json` |
| staging 完成后再激活 | 不能边写边 active |
| 激活时归档旧 active | 保证全库唯一 active |
| 失败可追踪 | 新版本 failed，旧 active 不变 |
| 写入构建 summary | 写入 `publish_versions.metadata_json` |
| 记录版本链 | 新版本可写 `base_publish_version_id=旧 active id` |

### 5. 表结构判断

`publish_versions` 表本身基本够用。

已有字段：

| 字段 | 用途 |
|---|---|
| `version_code` | 版本编码 |
| `status` | `staging/active/archived/failed` |
| `base_publish_version_id` | 基于哪个旧版本构建 |
| `source_batch_id` | 来源批次 |
| `build_started_at` | 构建开始 |
| `build_finished_at` | 构建结束 |
| `activated_at` | 激活时间 |
| `build_error` | 失败原因 |
| `metadata_json` | 构建 summary / pipeline 信息 |

不建议本轮大改表。

但要补文档约束：

| 字段 | 规则 |
|---|---|
| `version_code` | 全局唯一，不能固定 |
| `batch_code` | 全局唯一，不能固定 |
| `source_batches.metadata_json` | 记录输入批次参数 |
| `publish_versions.metadata_json` | 记录 pipeline 版本、parser 版本、构建 summary |

建议 `source_batches.metadata_json` 示例：

```json
{
  "storage_root_uri": "storage://uploads/batch_001",
  "original_root_name": "核心网命令资料",
  "default_document_type": "command",
  "default_source_type": "manual_upload",
  "batch_scope": {
    "network_elements": ["SMF", "UPF"]
  },
  "tags": ["command"]
}
```

建议 `publish_versions.metadata_json` 示例：

```json
{
  "pipeline_version": "m1",
  "parser_versions": {
    "markdown": "markdown-it-py",
    "txt": "plain-text-v1"
  },
  "summary": {
    "discovered_documents": 100,
    "parsed_documents": 60,
    "unparsed_documents": 40,
    "raw_segments": 500,
    "canonicals": 300
  }
}
```

### 6. 他下一步应该怎么做

#### 6.1 改 publishing API

当前：

```python
publish(..., version_code="v1", batch_code="batch-001")
```

应改成：

```python
publish(
    ...,
    version_code: str | None = None,
    batch_code: str | None = None,
    source_type: str = "manual_upload",
    batch_metadata: dict | None = None,
)
```

如果没传，就自动生成唯一值。

#### 6.2 改激活流程

新增：

```text
activate_publish_version(conn, publish_version_id)
```

逻辑：

```text
BEGIN
  archive old active
  activate new version
COMMIT
```

必须保证不会出现：

| 错误状态 |
|---|
| 没有 active |
| 多个 active |
| 新版本半激活 |
| 旧 active 被归档但新 active 激活失败 |

#### 6.3 加失败处理

pipeline 外层：

```text
try:
  create staging version
  write data
  validate
  activate
except Exception:
  mark failed
  raise
```

旧 active 不能受影响。

#### 6.4 加版本校验

M1 基础校验：

| 校验 |
|---|
| `publish_version.status == staging` 才能 activate |
| 不能 activate failed version |
| activate 后全库只有一个 active |
| canonical source primary 唯一 |
| raw/canonical/source 数量和 summary 对得上 |

#### 6.5 补测试

| 测试 | 目标 |
|---|---|
| 连续运行两次 | 不因 `v1/batch-001` 冲突 |
| 第二次激活 | 旧 active 变 archived，新版本 active |
| 构建失败 | 新版本 failed，旧 active 不变 |
| active 唯一 | 永远只有一个 active |
| version metadata | summary 写入 metadata_json |
| source_batch metadata | 批次参数写入 metadata_json |
| base_publish_version_id | 新版本指向旧 active |

### 7. 给 Claude Mining 的要求草稿

```text
主题 5：publish_versions 发布版本控制需要修订。

当前 publishing 固定 version_code=v1、batch_code=batch-001，并在写完后直接把当前版本设为 active。
这只是 demo 流程，不能支持重复运行、旧 active 归档、失败恢复和后端批次参数。

M1 发布模型应为：
1. 每次 Mining run 创建一个新的 staging publish_version。
2. version_code 和 batch_code 必须唯一，不能固定。
3. source_batches.metadata_json 记录本次输入参数，如 storage_root_uri、original_root_name、default_document_type、default_source_type、batch_scope、tags。
4. publish_versions.metadata_json 记录 pipeline 版本、parser 版本和构建 summary。
5. 构建成功并校验通过后，原 active 归档，新 staging 原子切换为 active。
6. 构建失败时，新版本标记 failed，写 build_error，旧 active 保持不变。
7. 每次新版本可记录 base_publish_version_id=旧 active id。
8. M1 可以继续全量物理快照，不要求本轮实现未变化文档复制，但字段 copied_from_document_id/copied_from_segment_id 后续保留。
```

### 8. 当前判断

| 项 | 判断 |
|---|---|
| 表是否大改 | 不需要 |
| 实现是否要修 | 必须 |
| 文档是否要补 | 必须 |
| `version_code/batch_code` 固定值 | 必须修 |
| active 切换 | 必须修 |
| failed 状态 | 必须修 |
| 物理快照增量复制 | 可后续 |

一句话结论：

```text
publish_versions 表基本够用，但 Claude 当前发布实现只是 demo。
M1 必须至少支持唯一版本号、staging 构建、成功后原子激活、失败不影响旧 active、批次参数和构建 summary 入 metadata。
```

## 主题 6：Serving 兼容性

### 1. 当前讨论结论

主题 6 本身不新增额外表。

它的核心是：

```text
Mining 输出和 Serving 读取必须锁成同一个契约。
前面主题 2/3/4 改表后，Serving 必须同步读取新字段。
Serving 主入口是 active publish_version 下的 canonical_segments。
Serving 不读 staging/failed 版本，不依赖文件系统，不依赖外部元数据文件。
```

后续需要统一出一份修改后的表结构，再分别给 Claude Mining 和 Claude Serving 发送最新协作消息。

### 2. 他做了啥

Claude Mining 当前已能写入 SQLite 这些表：

| 表 | 是否写入 |
|---|---:|
| `asset_source_batches` | 是 |
| `asset_publish_versions` | 是 |
| `asset_raw_documents` | 是 |
| `asset_raw_segments` | 是 |
| `asset_canonical_segments` | 是 |
| `asset_canonical_segment_sources` | 是 |

理论读取链路：

```text
active publish_version
  -> canonical_segments
  -> canonical_segment_sources
  -> raw_segments
  -> raw_documents
```

当前真实语料验证结果：

| 表 | 数量 |
|---|---:|
| `publish_versions` | 1 |
| `raw_documents` | 38 |
| `raw_segments` | 620 |
| `canonical_segments` | 284 |
| `canonical_segment_sources` | 620 |

数据链路能写通，但 Serving 兼容性还不完整。

### 3. 当前 Serving 兼容性问题

#### 3.1 Mining 写入字段和 Serving 读取字段可能不一致

前面主题已经倾向修改这些字段：

| 旧字段 | 新方向 |
|---|---|
| `raw_documents.product/product_version/network_element` | 删除，进入 `scope_json` |
| `raw_documents.conversion_profile_json` | 改为 `processing_profile_json` |
| `raw_segments.segment_type` | 删除或废弃 |
| `raw_segments.section_role` | 改为 `semantic_role` |
| `raw_segments.command_name` | 删除，进入 `entity_refs_json` |
| `canonical_segments.segment_type` | 删除或废弃 |
| `canonical_segments.section_role` | 改为 `semantic_role` |
| `canonical_segments.command_name` | 删除，进入 `entity_refs_json` |
| `relation_type=product_variant/ne_variant` | 改为 `scope_variant` |

这会影响 Serving 的 repository、normalizer、assembler 和测试。

#### 3.2 active version 依赖发布流程正确

Serving 每次请求应该先找到唯一 active version：

```sql
SELECT id FROM publish_versions WHERE status = 'active'
```

如果 Mining 发布流程不正确，Serving 会遇到：

| 状态 | Serving 问题 |
|---|---|
| 没有 active | 无法查询 |
| 多个 active | 查询不确定 |
| active 数据不完整 | 回答缺失 |
| staging 被误读 | 读到半成品 |

因此主题 5 的发布修复是 Serving 兼容性的前提。

#### 3.3 Serving 应主要读取 canonical

Serving 查询主入口应是：

```text
canonical_segments
```

需要溯源时再 join：

```text
canonical_segment_sources -> raw_segments -> raw_documents
```

如果 canonical 层字段不完整，Serving 会变弱：

| 缺失 | Serving 影响 |
|---|---|
| `semantic_role` | 难以优先找参数/示例/注意事项 |
| `block_type` | 难以优先找表格/代码块 |
| `entity_refs_json` | 难以按命令/网元/术语过滤 |
| `scope_json` | 难以按产品/网元/项目/批次上下文过滤 |
| `source mappings` | 难以解释答案来源 |
| `is_primary/priority` | 难以选可信来源 |

#### 3.4 raw_documents 信息弱会影响 Serving 展示和过滤

当前真实库中：

| 检查项 | 结果 |
|---|---:|
| `document_type IS NULL` | 38 |
| `relative_path IS NULL` | 38 |
| `normalized_storage_uri IS NULL` | 38 |

影响：

| 缺失 | Serving 影响 |
|---|---|
| `document_type` | 不能按命令/特性/流程过滤 |
| `relative_path` | 来源路径展示弱 |
| `scope_json` 不完整 | 上下文筛选弱 |
| `title` 缺失 | 结果展示不友好 |
| `metadata_json.parse_status` 缺失 | 无法解释为什么某些文件没内容 |

### 4. 我们的目标是啥

Serving 兼容性的目标：

```text
Mining 产出的 active version，Serving 能稳定用统一字段读取、过滤、排序、组装、溯源。
```

#### 4.1 Serving 依赖的主表

| 表 | Serving 用途 |
|---|---|
| `publish_versions` | 找唯一 active |
| `canonical_segments` | 检索和候选答案主入口 |
| `canonical_segment_sources` | 找来源关系 |
| `raw_segments` | 展示原文片段和结构上下文 |
| `raw_documents` | 展示来源文档和 scope |

#### 4.2 Serving 不应依赖

| 不应依赖 | 原因 |
|---|---|
| staging version | 半成品 |
| failed version | 构建失败 |
| raw_documents 外层 product/ne 字段 | 这些应进入 `scope_json` |
| command_name 外层字段 | 应进入 `entity_refs_json` |
| manifest/mapping | M1 不考虑外部元数据文件 |
| 文件系统原始路径可访问 | Serving 不一定能读源文件，只应读 DB |

#### 4.3 最小 Serving contract

`canonical_segments` 至少要给 Serving：

| 字段 | 用途 |
|---|---|
| `id` | 主键 |
| `publish_version_id` | 版本过滤 |
| `canonical_key` | 稳定标识 |
| `block_type` | 结构过滤 |
| `semantic_role` | 语义过滤 |
| `canonical_text` | 回答正文 |
| `summary` | 摘要 |
| `search_text` | 检索文本 |
| `entity_refs_json` | 实体过滤 |
| `scope_json` | 上下文过滤 |
| `has_variants` | 是否存在变体 |
| `variant_policy` | 是否需要补充 scope |
| `quality_score` | 排序 |

`raw_segments` 至少要给 Serving：

| 字段 | 用途 |
|---|---|
| `raw_text` | 原文片段 |
| `section_path` | 来源章节 |
| `block_type` | 原文结构 |
| `semantic_role` | 原文语义 |
| `structure_json` | 表格/列表/代码结构 |
| `source_offsets_json` | 原文位置 |
| `entity_refs_json` | 原文实体 |

`raw_documents` 至少要给 Serving：

| 字段 | 用途 |
|---|---|
| `title` | 来源标题 |
| `relative_path` | 来源路径展示 |
| `file_type` | 来源文件类型 |
| `document_type` | 文档类型过滤 |
| `scope_json` | 上下文 |
| `tags_json` | 标签 |
| `metadata_json.parse_status` | 是否解析成功 |

### 5. 他下一步应该怎么做

#### 5.1 Mining 和 Serving 共享同一份 schema

不允许：

```text
Mining 用一套字段
Serving 自己猜一套字段
```

如果 schema 修改，Claude Mining 必须同步更新：

| 文件 |
|---|
| PostgreSQL schema |
| SQLite schema |
| schema README |
| Mining models |
| Mining publishing |
| Mining tests |

Claude Serving 必须同步更新：

| 文件 |
|---|
| repository 查询 |
| normalizer |
| assembler |
| Serving tests |

#### 5.2 增加 contract tests

建议增加：

```text
Mining 生成一个 SQLite DB
Serving 直接读取这个 DB
验证能查到答案和来源
```

测试至少覆盖：

| 场景 |
|---|
| active version 读取 |
| canonical 查询 |
| 按 `semantic_role=parameter` 过滤 |
| 按 `block_type=code/table` 过滤 |
| 通过 `entity_refs_json` 找命令 |
| 通过 `scope_json` 过滤网元/项目 |
| source drilldown 到 raw segment |
| source drilldown 到 raw document relative_path |
| `variant_policy=require_scope` 时返回需要补充条件 |
| 只有 raw_document 没有 raw_segment 的 PDF 不影响 Serving |

#### 5.3 Serving 只读 active

Serving 查询必须强制：

```text
WHERE publish_version_id = active_version_id
```

没有 active 时返回明确错误：

```text
knowledge asset not published
```

多个 active 时返回数据一致性错误。

#### 5.4 Serving 不读文件系统

Serving M1 不应依赖 `raw_documents.source_uri` 去读取原文件。

原因：

| 原因 |
|---|
| 后端部署后文件可能不在同一机器 |
| 权限不稳定 |
| Serving 应该依赖已发布资产 |
| 安全边界更清楚 |

Serving 只读 DB 中已经发布的：

| 内容 |
|---|
| `canonical_text` |
| `raw_text` |
| `structure_json` |
| `source_offsets_json` |
| `relative_path` |

#### 5.5 更新 Serving 字段映射

如果 schema 改成：

```text
semantic_role
entity_refs_json
scope_json
block_type
```

Serving 应对应更新：

| 查询意图 | Serving 应使用 |
|---|---|
| 查命令 | `entity_refs_json` 中 `type=command` |
| 查参数 | `semantic_role=parameter` |
| 查示例 | `semantic_role=example` 或 `block_type=code` |
| 查表格 | `block_type=table/html_table` |
| 查网元 | `scope_json.network_elements` |
| 查某批次 | `source_batch_id` 或 `scope_json/project/tags` |

### 6. 是否要改表

主题 6 本身不新增额外表。

但前面主题的表改动必须同步给 Serving：

| 表 | 对应主题 |
|---|---|
| `raw_documents` | 主题 2 已建议改 |
| `raw_segments` | 主题 3 已建议改 |
| `canonical_segments` | 主题 4 已建议改 |
| `canonical_segment_sources` | 主题 4 已建议改 |
| `publish_versions` | 主题 5 表不大改，但实现要修 |

主题 6 需要新增或补充：

| 项 | 要求 |
|---|---|
| 契约文档 | 说明 Serving 如何读 active/canonical/source |
| 契约测试 | 验证 Mining 产出的 DB 能被 Serving 读取 |

### 7. 给 Claude Mining / Serving 的要求草稿

```text
主题 6：Serving 兼容性需要明确契约。

Mining 改 schema 和写库逻辑后，Serving 必须同步读取同一套字段。
Serving 的主入口是 active publish_version 下的 canonical_segments。
Serving 不应读取 staging/failed 版本，不应依赖文件系统原始路径，不应依赖 manifest/mapping，不应依赖 product/network_element/command_name 等已废弃外层字段。

请建立最小 Serving contract：
1. Serving 每次请求先解析唯一 active publish_version。
2. 查询主入口为 canonical_segments。
3. 溯源通过 canonical_segment_sources -> raw_segments -> raw_documents。
4. 过滤和组装使用 block_type、semantic_role、entity_refs_json、scope_json、relative_path、document_type。
5. 变体处理使用 has_variants、variant_policy、relation_type=scope_variant、metadata_json.variant_dimensions。
6. 增加 Mining -> SQLite DB -> Serving 读取的契约测试。
7. schema README 和架构文档必须说明 Serving 只读 active version，且不读文件系统。
```

### 8. 当前判断

| 项 | 判断 |
|---|---|
| 是否单独改表 | 不新增额外表 |
| 是否需要同步 schema | 必须 |
| 是否需要同步 Serving 实现 | 必须 |
| 是否需要契约测试 | 必须 |
| Serving 是否读文件系统 | 不应该 |
| Serving 是否读 raw 为主 | 不应该，canonical 为主 |
| Serving 是否依赖 active version | 必须 |

一句话：

```text
主题 6 的重点是把 Mining 输出和 Serving 读取锁成同一个契约。
前面主题 2/3/4 改表后，Serving 必须同步使用 canonical_segments 作为主入口，并通过 source mappings 下钻到 raw。
```

## 主题 7：测试与真实语料验证

### 1. 当前讨论结论

M1 修完后，不能只看单元测试通过，也不能只看某个合成 Markdown 样本跑通。

验收应分三层：

```text
单元测试
  -> 各模块逻辑正确

端到端测试
  -> Mining 从文件夹到 SQLite DB 全链路正确

契约测试
  -> Mining 产出的 SQLite DB 能被 Serving 正确读取
```

管理员会安排专人准备一个混合测试文件夹。

Claude Mining 必须基于该测试文件夹进行端到端验证，不能继续只用 `manifest.jsonl` 场景或旧 `cloud_core_coldstart_md` 样本证明完成。

### 2. 当前测试问题

Claude Mining 当前有 71 个测试通过，但只能证明旧实现跑通，不能证明新目标达成。

当前主要问题：

| 问题 | 说明 |
|---|---|
| 样本偏 Markdown | 主要围绕 Markdown 和 `manifest.jsonl` 场景 |
| 入口假设旧 | 没覆盖普通文件夹递归扫描所有 source artifacts |
| 文件类型不全 | 没完整覆盖 md/txt/html/pdf/doc/docx 混合目录 |
| 表结构旧 | 没覆盖准备修改的新字段 |
| Serving 契约缺失 | 没有验证 Mining 产出的 DB 能被 Serving 使用 |
| 真实结构覆盖不足 | 真实语料跑出来 620 个 segment 全是 paragraph |
| 发布版本弱 | 没覆盖连续运行、旧 active 归档、失败恢复 |

### 3. 专人准备的混合测试文件夹要求

管理员会安排专人准备一个普通语料文件夹，不包含 `manifest.jsonl`、`html_to_md_mapping.json/csv` 或其他外部元数据文件。

建议目录结构：

```text
mixed_corpus/
  commands/
    add_apn.md
    delete_apn.txt
  features/
    n4_interface.md
  procedures/
    config_steps.md
  tables/
    parameters.md
  html/
    n4_reference.html
  pdf/
    vendor_manual.pdf
  docx/
    expert_note.docx
```

文件内容要求：

| 文件类型 | 内容要求 | M1 期望 |
|---|---|---|
| Markdown | 标题、段落、列表、表格、代码块 | 登记 raw_documents，并生成 raw_segments |
| TXT | 多段纯文本，最好包含类似标题的行 | 登记 raw_documents，并生成 raw_segments |
| HTML | 可以是真 HTML，小样本即可 | 只登记 raw_documents，不生成 raw_segments |
| PDF | 小样本或占位文件 | 只登记 raw_documents，不生成 raw_segments |
| DOCX | 小样本或占位文件 | 只登记 raw_documents，不生成 raw_segments |

测试文件夹应覆盖：

| 覆盖项 | 说明 |
|---|---|
| 命令类文档 | 用于验证 `document_type=command` 或批次默认值继承 |
| 特性类文档 | 用于验证 feature/procedure 等类型推断 |
| Markdown 表格 | 验证 `block_type=table` 与 `structure_json` |
| Markdown 列表 | 验证 `block_type=list` 与 `structure_json.items` |
| 代码块 | 验证 `block_type=code` 与 `entity_refs_json` |
| 纯文本 | 验证 TXT parser |
| 不可解析文件 | 验证 HTML/PDF/DOCX 只登记，不切片 |

Claude Mining 验收必须基于这个文件夹输出 summary。

### 4. 单元测试要求

| 模块 | 必测内容 |
|---|---|
| ingestion | 递归扫描普通文件夹，不读取/依赖外部元数据文件 |
| ingestion | 识别 `.md/.markdown/.txt/.html/.htm/.pdf/.doc/.docx` |
| ingestion | 生成稳定 `relative_path`、`document_key`、真实 `content_hash` |
| document profile | 批次默认参数能继承到文档 |
| document profile | 产品/版本/网元/项目进入 `scope_json` |
| document profile | `document_type` 可由批次默认值、路径、文件名、内容推断 |
| Markdown parser | 标题、段落、表格、列表、代码块、blockquote、raw html table |
| TXT parser | 按空行/段落切片，长段落拆分 |
| segmentation | 输出 `block_type`、`semantic_role`、`structure_json`、`source_offsets_json` |
| canonicalization | exact duplicate / normalized duplicate / scope variant / primary source |
| publishing | 写入新 schema 字段 |
| publish version | staging -> active，旧 active -> archived，失败 -> failed |

### 5. 端到端测试要求

端到端测试使用专人准备的普通混合文件夹。

不需要也不允许依赖：

```text
manifest.jsonl
html_to_md_mapping.json/csv
其他外部元数据文件
```

验证项：

| 验证项 | 期望 |
|---|---|
| discovered_documents | 包含 md/txt/html/pdf/docx |
| raw_documents | 所有支持识别的文件都登记 |
| raw_segments | 只有 md/txt 生成 |
| html/pdf/docx | 只登记，不切片 |
| file_type | 每个文件类型正确 |
| relative_path | 相对测试目录稳定 |
| content_hash | 来自文件内容 |
| document_type | 批次默认值/路径/内容推断正确 |
| scope_json | 批次 scope 正确继承 |
| structure_json | 表格、列表、代码块有结构信息 |
| source_offsets_json | 至少包含 parser/block_index/line 信息 |
| canonical_segments | 有去重归并结果 |
| canonical_segment_sources | 每个 canonical 有唯一 primary |
| publish_versions | 只有一个 active |

### 6. 契约测试要求

契约测试方式：

```text
Mining 生成 SQLite DB
Serving 使用同一个 SQLite DB
Serving 查询 active version
Serving 查询 canonical_segments
Serving 下钻 raw_segments/raw_documents
```

必须覆盖：

| 场景 | 期望 |
|---|---|
| active version | Serving 能找到唯一 active |
| canonical 查询 | 能返回 canonical_text |
| 参数查询 | 能使用 `semantic_role=parameter` |
| 示例查询 | 能使用 `semantic_role=example` 或 `block_type=code` |
| 表格查询 | 能使用 `block_type=table` |
| 实体查询 | 能从 `entity_refs_json` 找 command/term |
| scope 查询 | 能从 `scope_json.network_elements` 或项目字段过滤 |
| 溯源 | 能返回 raw_text、section_path、relative_path |
| 变体 | `variant_policy=require_scope` 时能提示需要补充条件 |
| 未解析文件 | PDF/DOCX 只在 raw_documents 中，不影响查询 |

### 7. 发布版本测试要求

| 测试 | 期望 |
|---|---|
| 连续运行两次 | 不因为固定 `v1/batch-001` 冲突 |
| 第二次运行成功 | 旧 active 变 archived，新版本 active |
| 构建失败 | 新版本 failed，旧 active 仍 active |
| active 唯一 | 永远只有一个 active |
| base version | 新版本记录 `base_publish_version_id` |
| summary | `publish_versions.metadata_json.summary` 正确 |
| batch metadata | `source_batches.metadata_json` 记录批次参数 |

### 8. 验证 summary 要求

真实/混合语料验证输出 summary 至少包括：

| 指标 |
|---|
| discovered_documents |
| parsed_documents |
| unparsed_documents |
| skipped_files |
| failed_files |
| raw_segments |
| canonical_segments |
| source_mappings |
| active_version_id |

并验证：

```text
discovered_documents = raw_documents 数量
parsed_documents = md + txt 成功解析数量
unparsed_documents = html + pdf + docx 等未解析数量
raw_segments 只来自 md/txt
```

### 9. 给 Claude 的要求草稿

```text
主题 7：测试与真实语料验证需要重做验收标准。

现有 71 个测试只能证明旧实现跑通，不能证明新目标达成。
管理员会安排专人提供一个普通混合测试文件夹。该文件夹不包含 manifest.jsonl、html_to_md_mapping.json/csv 或其他外部元数据文件。

请基于该测试文件夹补充并通过：
1. 单元测试覆盖 ingestion、document profile、MD parser、TXT parser、segmentation、canonicalization、publishing、publish version。
2. 端到端测试使用普通混合文件夹，至少包含 md/txt/html/pdf/docx。
3. MD/TXT 必须生成 raw_segments；HTML/PDF/DOCX 只登记 raw_documents。
4. 验证新 schema 字段：semantic_role、entity_refs_json、scope_json、processing_profile_json、structure_json、source_offsets_json。
5. 验证 canonicalization 的 exact/normalized/scope_variant/primary source。
6. 验证连续发布、active 切换、failed 不影响旧 active。
7. 增加 Mining 生成 SQLite DB 后由 Serving 读取的契约测试。
8. 测试输出必须包含 discovered/parsed/unparsed/skipped/failed 等 summary。
```

### 10. 当前判断

主题 7 属于必须做。

不是为了追求测试数量，而是因为当前设计已经变成：

```text
通用文件夹输入
多文件类型登记
MD/TXT parser
新 raw/canonical schema
Serving 共享契约
版本发布控制
```

这些都需要测试兜住。

## 主题 8：M1 边界收口

### 1. 当前讨论结论

M1 的目标应收敛为：

```text
给定一个普通语料文件夹
  -> 递归发现 source artifacts
  -> 登记 raw_documents
  -> 解析 MD/TXT 生成 raw_segments
  -> 归并生成 canonical_segments
  -> 建立 canonical_segment_sources
  -> 发布为唯一 active version
  -> Serving 能读取 active canonical 并下钻溯源
```

M1 不追求复杂智能抽取，也不追求所有文件格式都能解析。

核心：

```text
先把资产生产链路做对、表结构做干净、Mining/Serving 契约打通。
```

### 2. M1 必须做

| 模块 | M1 必须做 |
|---|---|
| 输入 | 给定文件夹递归扫描 |
| 文件类型 | 识别 md/txt/html/pdf/doc/docx |
| raw_documents | 所有识别文件登记 |
| scope | 产品/版本/网元/项目等进入 `scope_json` |
| 批次参数 | 用户填写的默认类型/scope/tags 进入 `source_batches.metadata_json` |
| MD parser | 支持标题、段落、表格、列表、代码块 |
| TXT parser | 支持基础段落切片 |
| raw_segments | 使用 `block_type/semantic_role/entity_refs_json` |
| structure_json | 保存表格/列表/代码结构 |
| source_offsets_json | 保存基础来源位置 |
| canonicalization | exact / normalized / scope variant 基础归并 |
| publishing | staging -> active，失败 -> failed |
| Serving | 读取 active canonical，支持溯源 |
| 测试 | 单元、端到端、契约测试 |

### 3. M1 明确不做

| 不做 | 原因 |
|---|---|
| HTML 深度解析 | 后续单独加 HTML parser |
| PDF 文本抽取 | 后续单独加 PDF parser |
| DOC/DOCX 文本抽取 | 后续单独加 DOCX parser |
| embedding 向量化 | M2 或后续检索增强 |
| LLM 自动抽取事实 | 当前先做结构化资产链路 |
| 复杂 ontology / graph | 后续知识图谱阶段 |
| 命令结构化抽取 | 后续可基于 `entity_refs_json` 扩展 |
| 参数级强结构化模型 | 后续可从 table/list/code 中抽取 |
| 复杂重命名识别 | M1 先用 `relative_path` 作为 `document_key` |
| 未变化文档复制 | M1 先全量物理快照 |
| 前端上传实现 | 当前只定义后端输入模型 |
| 外部元数据文件 | 不考虑 manifest/mapping |

### 4. M1 需要预留但不实现

| 预留点 | 当前怎么预留 |
|---|---|
| HTML/PDF/DOCX parser | `file_type` + `parse_status` |
| 更复杂实体抽取 | `entity_refs_json` |
| 产品/网元/项目过滤 | `scope_json` |
| 解析过程追踪 | `processing_profile_json` |
| 原文定位 | `source_offsets_json` |
| 版本增量复制 | `copied_from_document_id` / `copied_from_segment_id` |
| 变体处理 | `scope_variant` / `variant_policy` |
| Serving 溯源 | source mappings |

### 5. M1 成功标准

M1 成功不是“能回答所有问题”，而是下面这条链路稳定：

```text
普通文件夹
  -> 文件发现完整
  -> raw_documents 登记完整
  -> MD/TXT raw_segments 切片合理
  -> canonical 去重逻辑正确
  -> publish_version 发布可靠
  -> Serving 能读 active version
  -> Serving 能返回答案片段和来源
```

至少满足：

| 指标 | 要求 |
|---|---|
| raw_documents | 等于识别到的源文件数 |
| raw_segments | 只来自 MD/TXT |
| canonical_segments | 来自 raw_segments 归并 |
| canonical_segment_sources | 每个 canonical 至少一个 primary |
| active version | 全库唯一 |
| failed version | 不影响旧 active |
| Serving query | 能查 canonical |
| source drilldown | 能回到 raw segment 和 raw document |

### 6. 给 Claude 的要求草稿

```text
主题 8：M1 边界收口。

M1 不再扩大范围。
目标是打通通用语料文件夹 -> raw_documents -> MD/TXT raw_segments -> canonical_segments -> active publish_version -> Serving 读取与溯源。

M1 必须做：
1. 普通文件夹递归扫描，不考虑 manifest/mapping。
2. 所有识别文件登记 raw_documents。
3. 只对 MD/TXT 生成 raw_segments。
4. HTML/PDF/DOC/DOCX 只登记，标记 parse_status。
5. 使用新的通用 schema：scope_json、processing_profile_json、block_type、semantic_role、entity_refs_json、scope_variant。
6. 修正 canonicalization 和 publish_versions。
7. 补齐单元、端到端、Mining-Serving 契约测试。

M1 明确不做：
1. HTML/PDF/DOCX 深度解析。
2. embedding。
3. LLM 抽取事实。
4. ontology/graph。
5. 命令参数强结构化抽取。
6. 增量复制。
7. 前端上传实现。
8. 外部元数据文件适配。
```

### 7. 当前判断

主题 8 是最终收口，用来防止范围继续扩大。

重点：

```text
M1 做资产生产链路，不做复杂智能理解。
表结构和数据契约必须干净，后续能力才能稳步加。
```
