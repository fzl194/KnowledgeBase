明白了，这次我直接按**实施蓝图**来写，不再讲抽象原则。

你现在要的是阶段 1 的**工程落地方案**，而且核心分两块：

1. **pipeline 要提取什么，产出什么**
2. **API 服务怎么组织给 Agent / Skill 用**

我下面全部按表来写，并且把你前面提到、但之前回答里没展开的细节补齐。
先把阶段 1 的目标再钉一下：**先做最小 Agent 可用闭环，重点解决命令、参数、示例、注意事项和来源证据；核心建设内容是文档导入、Stage 1/2 类能力、segment embedding、RST 扩展、命令检索 API、上下文组装 API 和 Skill 初版。**
同时阶段 1 应坚持 Evidence-first：先以原始文档、段落、标题、RST、向量和关键词为主，分类和对象类型只是增强信号，不是系统成立前提。 

---

## 表 1：阶段 1 总体范围

| 项目         | 阶段 1 要做                                                              | 阶段 1 不做                                    |
| ---------- | -------------------------------------------------------------------- | ------------------------------------------ |
| 目标         | Agent 能回答命令写法、参数含义、配置示例、注意事项、来源依据                                    | 不追求全流程自动结构化，不做影响分析，不做专家级推理                 |
| 知识来源       | 云核心网产品文档、MML 命令手册、特性说明、配置指南                                          | 不依赖 FAQ/工单/案例库作为主数据源                       |
| 主数据单元      | Document / Section / Segment / SegmentEdge / CommandIndex / Evidence | 不强制先构建完整 ontology / facts / triples        |
| 在线核心能力     | 命令检索、混合召回、上下文扩展、证据打包、context pack                                    | 不做复杂多跳图查询，不让 Agent 碰底层表和图                  |
| Agent 接入方式 | Skill 调业务语义化 API                                                     | 不暴露 semantic_search / SQL / Cypher 给 Agent |

这和你原文档里“后端 API 要业务语义化”“先聚焦命令检索和上下文组装”“后续再逐步增强”的路线一致。 

---

# 一、Pipeline：阶段 1 具体提取什么

你说得对：**原来的 pipeline 不能直接复用**。
因为云核心网产品文档的核心不是一般领域文档，而是：

* 文档结构很强
* 命令章节和参数表很多
* 示例和注意事项有固定文风
* 不同厂家格式差异大
* “业务理解”跨章节、跨网元，但阶段 1 先不做深结构化

所以阶段 1 的 pipeline 不应该按“通用知识抽取”设计，而应该按**命令和证据优先**设计。

---

## 表 2：Pipeline 总体模块

| 模块                 | 输入                    | 输出                               | 这一层必须解决什么            | 阶段 1 是否必做 |
| ------------------ | --------------------- | -------------------------------- | -------------------- | --------- |
| P1 文档接入            | PDF/Word/HTML/压缩包     | 原始文档记录                           | 把异构文档统一入库并留原件        | 是         |
| P2 文档识别            | 原始文档                  | 文档类型、厂家、产品、版本候选                  | 先把文档分清类型和上下文         | 是         |
| P3 结构恢复            | 文档文本/版面               | section tree、块级对象                | 恢复章节、标题、表格、列表、命令块    | 是         |
| P4 segment 切分      | section tree、块级对象     | segments                         | 形成可检索证据单元            | 是         |
| P5 segment 标注      | segments              | segment_type、signal flags        | 标出命令段、参数段、示例段、注意事项段等 | 是         |
| P6 命令抽取            | segments              | command candidates、command index | 为命令类问题提供精确召回入口       | 是         |
| P7 关系构建            | segments、section tree | segment edges                    | 为上下文扩展服务             | 是         |
| P8 embedding/index | segments、titles       | 向量、关键词、标题索引                      | 支撑混合检索               | 是         |
| P9 质量门控            | 全部中间结果                | publishable dataset              | 防止脏数据进入在线层           | 是         |
| P10 发布             | 结构化产物                 | online serving store             | 把离线产物投递到在线库          | 是         |

---

## 表 3：P1 文档接入模块

| 子项       | 设计                                                                              |
| -------- | ------------------------------------------------------------------------------- |
| 模块名      | `doc_ingest`                                                                    |
| 输入       | PDF、DOCX、HTML、TXT、ZIP 内文档                                                       |
| 输出       | `raw_documents`                                                                 |
| 核心字段     | `doc_id`, `source_path`, `file_type`, `checksum`, `ingest_time`, `raw_blob_uri` |
| 关键逻辑     | 去重、解压、文件类型识别、原件留存                                                               |
| 为什么必须单独做 | 你后续需要可追溯证据，原件必须保留                                                               |
| 注意点      | 不同厂家手册可能同名不同版本，不能只按文件名去重，要加 checksum                                            |

---

## 表 4：P2 文档识别模块

| 子项      | 设计                                                                                                                  |
| ------- | ------------------------------------------------------------------------------------------------------------------- |
| 模块名     | `doc_classifier`                                                                                                    |
| 输入      | `raw_documents`                                                                                                     |
| 输出      | `document_profiles`                                                                                                 |
| 输出字段    | `doc_type`, `vendor`, `product`, `version`, `language`, `is_command_manual`, `is_feature_manual`, `is_config_guide` |
| 识别方式    | 文件名规则 + 首页/前几页标题规则 + 章节关键词规则                                                                                        |
| 阶段 1 目标 | 不要求 100% 准确，但要把命令手册和特性说明先分出来                                                                                        |
| 为什么重要   | 后续召回和排序必须显式处理厂家、产品、版本、文档类型，这也是你设计里强调的上下文维度。                                                                         |

建议文档类型第一版只分 5 类：

| doc_type                   | 含义      |
| -------------------------- | ------- |
| `mml_command_manual`       | 命令手册    |
| `feature_description`      | 特性说明    |
| `configuration_guide`      | 配置指南    |
| `alarm_or_troubleshooting` | 告警/故障文档 |
| `generic_reference`        | 通用参考文档  |

---

## 表 5：P3 结构恢复模块

| 子项                      | 设计                                                                                       |
| ----------------------- | ---------------------------------------------------------------------------------------- |
| 模块名                     | `structure_rebuilder`                                                                    |
| 输入                      | 文档解析文本、版面块                                                                               |
| 输出                      | `sections`, `raw_blocks`                                                                 |
| 目标                      | 恢复文档章节树和块级对象                                                                             |
| 块类型                     | `title`, `heading`, `paragraph`, `list`, `table`, `code_like`, `note_box`, `warning_box` |
| 核心逻辑                    | 标题层级识别、表格边界识别、列表项恢复、命令块/示例块识别                                                            |
| 阶段 1 为什么比旧 pipeline 更重要 | 云核心网文档价值往往藏在章节、参数表、示例和注意事项里，只切自然段不够                                                      |
| 风险点                     | PDF 中表格和标题层级易错；不同厂家章节格式差异大                                                               |
| 建议策略                    | 结构恢复按“文档类型”走不同解析模板，而不是一套规则吃全场                                                            |

这里的关键不是做得很智能，而是**要按文档类型定模板**。
比如命令手册的结构恢复规则和特性说明文档就不该一样。

---

## 表 6：P4 Segment 切分模块

| 子项         | 设计                                                                                                     |
| ---------- | ------------------------------------------------------------------------------------------------------ |
| 模块名        | `segment_builder`                                                                                      |
| 输入         | `sections`, `raw_blocks`                                                                               |
| 输出         | `segments`                                                                                             |
| Segment 原则 | 一个 segment 必须是“可独立引用、可参与检索、长度可控”的证据单元                                                                  |
| 推荐切分粒度     | 标题段、说明段、参数表块、示例块、注意事项块、条件块                                                                             |
| 不建议        | 按固定 token 长度硬切，会破坏命令/参数/示例的完整性                                                                         |
| 核心字段       | `segment_id`, `doc_id`, `section_id`, `segment_type`, `content`, `order_no`, `heading_path`, `page_no` |

推荐的 `segment_type` 第一版：

| segment_type       | 说明      |
| ------------------ | ------- |
| `heading`          | 标题      |
| `command_def`      | 命令定义段   |
| `parameter_block`  | 参数说明    |
| `example_block`    | 示例      |
| `note_block`       | 注意事项    |
| `condition_block`  | 前置条件/限制 |
| `procedure_step`   | 步骤段     |
| `normal_paragraph` | 普通说明    |
| `table_block`      | 表格类块    |

注意：
这些不是 ontology，只是**运行时检索增强标签**。你前面的设计也明确说过，类别不应是硬依赖，而应该是增强信号。

---

## 表 7：P5 Segment 标注模块

| 子项      | 设计                                                                                                                       |
| ------- | ------------------------------------------------------------------------------------------------------------------------ |
| 模块名     | `segment_annotator`                                                                                                      |
| 输入      | `segments`                                                                                                               |
| 输出      | `segment_annotations`                                                                                                    |
| 目标      | 给每个 segment 打轻量信号，方便后续检索和扩展                                                                                              |
| 典型信号    | `has_command_pattern`, `has_param_table`, `has_example_marker`, `has_note_marker`, `has_version_marker`, `has_nf_marker` |
| 方法      | 规则为主，少量模型辅助                                                                                                              |
| 阶段 1 原则 | 只做高价值信号，不追求全标签体系                                                                                                         |

推荐的轻量标注字段：

| 字段                          | 含义                           |
| --------------------------- | ---------------------------- |
| `has_command_pattern`       | 含 ADD/MOD/DEL/SET/SHOW 等命令模式 |
| `has_parameter_like_lines`  | 含参数说明格式                      |
| `has_example_marker`        | 含 Example / 示例 / 如下配置        |
| `has_note_marker`           | 含 注意 / Note / Warning        |
| `has_version_marker`        | 含版本适用性                       |
| `has_vendor_product_marker` | 含厂家/产品上下文                    |
| `mentioned_nf`              | 命中的网元名，如 SMF/UPF             |

---

## 表 8：P6 命令抽取模块

这块是阶段 1 的核心增强，不要拖到后面。

| 子项      | 设计                                                     |
| ------- | ------------------------------------------------------ |
| 模块名     | `command_extractor`                                    |
| 输入      | `segments`, `segment_annotations`                      |
| 输出      | `commands`, `command_aliases`, `command_segment_links` |
| 阶段 1 目标 | 提取“命令入口”和“命令相关段落”，不做完整命令知识图                            |
| 抽取对象    | 命令名、命令别名、命令所属 segment、命令关联参数段/示例段/注意事项段                |
| 方法      | 标题规则 + 行首命令模式 + 表格命令列 + 相邻段聚合                          |
| 为什么必须做  | 设计稿里已经明确命令检索是第一优先级能力。                                  |

推荐的数据表：

### `commands`

| 字段               | 说明                |
| ---------------- | ----------------- |
| `command_id`     | 主键                |
| `canonical_name` | 标准命令名，如 `ADD APN` |
| `vendor`         | 厂家                |
| `product`        | 产品                |
| `version`        | 版本                |
| `confidence`     | 抽取置信度             |

### `command_aliases`

| 字段           | 说明             |
| ------------ | -------------- |
| `command_id` | 关联命令           |
| `alias`      | 别名，如“新增 APN”   |
| `alias_type` | 标题别名/中文别名/缩写别名 |

### `command_segment_links`

| 字段           | 说明                                                            |
| ------------ | ------------------------------------------------------------- |
| `command_id` | 命令                                                            |
| `segment_id` | 相关 segment                                                    |
| `link_type`  | `definition` / `parameter` / `example` / `note` / `condition` |

---

## 表 9：P7 关系构建模块

阶段 1 的 Graph-RAG，本质不是大图，而是**上下文扩展边**。你设计稿也明确说，Graph-RAG 的价值在于命中后自动扩展参数段、示例段、注意事项段、前置条件段等。

| 子项     | 设计                                                                                                                                                                                           |
| ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 模块名    | `edge_builder`                                                                                                                                                                               |
| 输入     | `sections`, `segments`, `commands`                                                                                                                                                           |
| 输出     | `segment_edges`                                                                                                                                                                              |
| 作用     | 支撑 expansion engine                                                                                                                                                                          |
| 第一版边类型 | `prev_next`, `same_section`, `heading_child`, `command_to_parameter`, `command_to_example`, `command_to_note`, `command_to_condition`, `rst_explanation`, `rst_condition`, `rst_elaboration` |

推荐 `segment_edges` 表：

| 字段          | 说明                    |
| ----------- | --------------------- |
| `src_id`    | 起点 segment 或 command  |
| `dst_id`    | 终点 segment            |
| `src_type`  | `segment` / `command` |
| `dst_type`  | `segment`             |
| `edge_type` | 关系类型                  |
| `weight`    | 置信度/扩展权重              |

---

## 表 10：P8 Embedding 与索引模块

| 子项        | 设计                                                                                           |
| --------- | -------------------------------------------------------------------------------------------- |
| 模块名       | `index_builder`                                                                              |
| 输入        | `segments`, `commands`, `sections`                                                           |
| 输出        | 向量索引、标题索引、关键词索引、命令索引                                                                         |
| 阶段 1 必建索引 | `segment_vector`, `segment_fts`, `title_fts`, `command_exact_index`, `metadata_filter_index` |
| 为什么要多索引   | 你设计稿明确要求召回不能只靠向量，要组合命令精确匹配、标题、关键词、向量、图邻居和同义词扩展。                                              |

建议在线查询优先级：

1. `command_exact_index`
2. `title_fts`
3. `segment_fts`
4. `segment_vector`
5. `edge expansion`

---

## 表 11：P9 质量门控模块

| 子项     | 设计                                       |
| ------ | ---------------------------------------- |
| 模块名    | `publish_guard`                          |
| 输入     | 全部离线结果                                   |
| 输出     | 可发布版本                                    |
| 检查项    | 文档元数据完整率、命令抽取成功率、空 segment 比例、异常重复、边数量异常 |
| 为什么必须做 | 阶段 1 靠规则很多，容易脏；不做门控，在线返回会很不稳定            |

最低门槛建议：

| 指标                              | 阈值   |
| ------------------------------- | ---- |
| 文档 `vendor/product/version` 识别率 | >70% |
| `mml_command_manual` 的命令抽取命中率   | >80% |
| 空内容 segment 比例                  | <2%  |
| 无 section 归属的 segment 比例        | <5%  |

---

## 表 12：Pipeline 最终产物表清单

| 表名                      | 用途             | 阶段 1 是否核心 |
| ----------------------- | -------------- | --------- |
| `raw_documents`         | 原始文档登记         | 是         |
| `document_profiles`     | 文档类型/厂家/版本识别结果 | 是         |
| `sections`              | 章节树            | 是         |
| `segments`              | 可检索证据单元        | 是         |
| `segment_annotations`   | 轻量增强信号         | 是         |
| `commands`              | 命令索引主表         | 是         |
| `command_aliases`       | 命令别名           | 是         |
| `command_segment_links` | 命令到段落关联        | 是         |
| `segment_edges`         | 上下文扩展边         | 是         |
| `segment_embeddings`    | 向量             | 是         |
| `alias_dictionary`      | 术语归一化          | 是         |
| `publish_versions`      | 发布版本           | 建议有       |

---

# 二、API 服务：阶段 1 怎么给 Agent / Skill 用

这里不是一个通用 RAG 服务，而是一个**Agent Knowledge Backend**。
你设计稿中也明确建议新增这一层，负责面向 Agent 的 API、查询归一化、混合检索、图扩展、上下文组装和证据打包。

---

## 表 13：在线服务总体模块

| 模块                   | 作用              | 输入                  | 输出                  |
| -------------------- | --------------- | ------------------- | ------------------- |
| A1 API Gateway       | 接收 Skill 请求     | HTTP JSON           | 标准请求对象              |
| A2 Query Normalizer  | 做术语和命令归一化       | query + filters     | normalized query    |
| A3 Planner           | 决定走哪些检索器        | normalized query    | retrieval plan      |
| A4 Retrievers        | 执行多路召回          | retrieval plan      | candidates          |
| A5 Expansion Engine  | 做上下文扩展          | candidates          | expanded candidates |
| A6 Reranker          | 根据命令类问题重排       | expanded candidates | ranked candidates   |
| A7 Context Assembler | 组装 context pack | ranked candidates   | context pack        |
| A8 Evidence Builder  | 生成可引用证据         | ranked candidates   | evidence list       |
| A9 Skill Adapter     | 输出 Agent 友好响应   | context pack        | API response        |

---

## 表 14：阶段 1 在线服务目录结构建议

| 目录             | 内容                                                    | 阶段 1 要点                   |
| -------------- | ----------------------------------------------------- | ------------------------- |
| `api/`         | 路由与请求响应模型                                             | 只保留 3 个主接口                |
| `application/` | 归一化、planner、组装编排                                      | 规则优先，不上复杂 agentic planner |
| `retrieval/`   | exact / title / keyword / vector / expansion / rerank | 命令类优先                     |
| `domain/`      | context pack、evidence、request/response schema         | 先把契约定稳                    |
| `infra/`       | DB、向量、缓存、日志                                           | 尽量简单                      |
| `eval/`        | benchmark、回放、指标                                       | 从第一天就建                    |

---

## 表 15：阶段 1 API 清单

| API                                 | 作用         | 给谁用         | 阶段 1 是否必做 |
| ----------------------------------- | ---------- | ----------- | --------- |
| `POST /get_command_usage`           | 命令类问题主入口   | Skill/Agent | 是         |
| `POST /search_cloud_core_knowledge` | 通用兜底检索     | Skill/Agent | 是         |
| `POST /assemble_cloud_core_context` | 对召回结果做二次组装 | Skill/Agent | 是         |
| `GET /health`                       | 健康检查       | 平台          | 是         |
| `POST /debug/retrieve`              | 检索调试       | 内部评测        | 建议有       |
| `POST /debug/explain`               | 返回召回/排序解释  | 内部评测        | 建议有       |

---

## 表 16：`/get_command_usage` 详细定义

| 项目       | 设计                                                                                |
| -------- | --------------------------------------------------------------------------------- |
| 作用       | 处理“ADD APN 命令怎么写”“某参数什么意思”“有没有示例”                                                 |
| 输入       | query + filters                                                                   |
| 典型 query | `ADD APN 命令怎么写`                                                                   |
| filters  | `vendor`, `product`, `version`, `network_mode`, `scenario`                        |
| 查询主干     | `normalize -> plan -> exact/title/keyword/vector -> expand -> rerank -> assemble` |
| 输出重点     | 命令候选、参数、示例、注意事项、前置条件、证据、不确定性                                                      |

请求字段建议：

| 字段             | 必填 | 说明        |
| -------------- | -- | --------- |
| `query`        | 是  | 用户原始问题    |
| `vendor`       | 否  | 厂家        |
| `product`      | 否  | 产品        |
| `version`      | 否  | 版本        |
| `network_mode` | 否  | EPC/5GC   |
| `scenario`     | 否  | 新开局/现网变更等 |
| `top_k`        | 否  | 候选数量      |

响应字段建议：

| 字段                    | 说明               |
| --------------------- | ---------------- |
| `query`               | 原始问题             |
| `intent`              | `command_usage`  |
| `normalized`          | 归一化结果            |
| `answer_materials`    | 命令模板、参数、示例、注意事项等 |
| `evidence`            | 证据片段             |
| `uncertainties`       | 缺失上下文            |
| `suggested_followups` | 建议追问             |

---

## 表 17：`/search_cloud_core_knowledge` 详细定义

| 项目      | 设计                               |
| ------- | -------------------------------- |
| 作用      | 通用兜底检索，不限命令类                     |
| 场景      | 术语解释、模糊问题、命令索引没覆盖的问题             |
| 输入      | query + filters + retrieval_mode |
| 输出      | 相关段落、章节、文档、可选 context pack 简版    |
| 阶段 1 重点 | 不是直接给用户看，而是给 Skill 用作 fallback   |

---

## 表 18：`/assemble_cloud_core_context` 详细定义

| 项目    | 设计                              |
| ----- | ------------------------------- |
| 作用    | 把一组候选结果二次组装成稳定上下文包              |
| 适用    | Skill 先走 search，再要求后端帮忙收束上下文    |
| 输入    | query + candidate_ids + filters |
| 输出    | 完整 context pack                 |
| 为什么需要 | 把“召回”和“回答材料组装”解耦，后续流程类/故障类也能复用  |

---

## 表 19：Query Normalizer 要做什么

这块是很多系统看起来“能搜”，但不稳定的根源。

| 功能     | 阶段 1 实现方式        | 例子                     |
| ------ | ---------------- | ---------------------- |
| 操作词归一化 | 规则字典             | 新增 → ADD，修改 → MOD      |
| 术语归一化  | alias dictionary | APN ↔ DNN，N4 ↔ PFCP    |
| 命令实体识别 | 模式 + dictionary  | 识别 `ADD APN`           |
| 过滤条件抽取 | query rule       | 识别版本、厂家、EPC/5GC        |
| 缺失项识别  | 规则               | 没有厂家/版本时返回 uncertainty |

你设计稿中明确提到查询归一化要维护领域同义词、命令别名和版本映射。

---

## 表 20：Planner 在阶段 1 具体做什么

阶段 1 的 planner 不要太复杂，但也不能省。

| 功能     | 阶段 1 做法                                                     |
| ------ | ----------------------------------------------------------- |
| 主意图判断  | 规则判断是不是命令类                                                  |
| 检索路径决定 | 命令类优先 exact + title + keyword + vector                      |
| 过滤策略   | 有 vendor/version 时前置过滤；没有则保留并在结果中提示                         |
| 扩展策略   | 命中 command definition 后自动扩 parameter/example/note/condition |
| 排序策略选择 | 命令类排序函数                                                     |

也就是你前面定下来的主干：`query intake -> normalization -> planning -> retrieval -> expansion -> rerank -> context assembly`。

---

## 表 21：Retrieval 具体由哪些检索器组成

| 检索器                     | 数据源                                      | 作用          | 阶段 1 是否必做 |
| ----------------------- | ---------------------------------------- | ----------- | --------- |
| Exact Command Retriever | `commands`, `command_aliases`            | 精确命中命令      | 是         |
| Title Retriever         | `sections`, `segments.heading_path`      | 标题增强召回      | 是         |
| Keyword Retriever       | `segments` FTS                           | 关键词/BM25 召回 | 是         |
| Vector Retriever        | `segment_embeddings`                     | 语义召回        | 是         |
| Metadata Filter         | `document_profiles`                      | 厂家/版本/产品过滤  | 是         |
| Expansion Retriever     | `segment_edges`, `command_segment_links` | 上下文扩展       | 是         |

---

## 表 22：命令类排序函数建议

| 信号                             | 加分建议 | 说明        |
| ------------------------------ | ---: | --------- |
| 命令精确匹配                         |  +10 | 最重要       |
| 命令别名匹配                         |   +7 | 如“新增 APN” |
| 标题命中                           |   +6 | 章节标题很重要   |
| `segment_type=command_def`     |   +5 | 命令定义段     |
| `segment_type=parameter_block` |   +4 | 参数段       |
| `segment_type=example_block`   |   +4 | 示例段       |
| `segment_type=note_block`      |   +3 | 注意事项段     |
| vendor match                   |   +3 | 厂家匹配      |
| product match                  |   +2 | 产品匹配      |
| version match                  |   +2 | 版本匹配      |
| 来自 command manual              |   +2 | 文档类型加权    |
| 同章节扩展得到                        |   +1 | 扩展段轻加分    |

---

## 表 23：Context Pack 主契约

这个契约要尽量稳定。你前面的设计里也强调了：对 Agent 的返回契约要稳定，始终保留原始问题、检测意图、归一化结果、关键对象、证据、不确定性、建议追问等。

| 字段                    | 含义          | 阶段 1 必须 |
| --------------------- | ----------- | ------- |
| `query`               | 原始问题        | 是       |
| `intent`              | 当前主意图       | 是       |
| `normalized`          | 归一化结果       | 是       |
| `key_objects`         | 命中的命令/术语/对象 | 是       |
| `answer_materials`    | 回答素材        | 是       |
| `evidence`            | 证据列表        | 是       |
| `source_documents`    | 文档来源摘要      | 是       |
| `uncertainties`       | 不确定性        | 是       |
| `suggested_followups` | 建议追问        | 是       |
| `debug_trace`         | 召回/排序解释     | 内部可选    |

---

## 表 24：`answer_materials` 内部结构

| 子字段                  | 含义             |
| -------------------- | -------------- |
| `command_candidates` | 候选命令           |
| `template`           | 命令模板/格式        |
| `parameters`         | 参数说明列表         |
| `examples`           | 示例             |
| `notes`              | 注意事项           |
| `preconditions`      | 前置条件           |
| `applicability`      | 适用厂家/产品/版本     |
| `related_terms`      | 相关术语，如 APN/DNN |
| `confidence_summary` | 回答材料的整体可信度概述   |

---

## 表 25：Skill 第一版怎么设计

Skill 必须保持轻量，你的原设计稿里也已经明确了这点。

| Skill 工具                      | 后端 API                         | 什么时候调用      | Skill 负责什么             | Skill 不负责什么 |
| ----------------------------- | ------------------------------ | ----------- | ---------------------- | ----------- |
| `get_command_usage`           | `/get_command_usage`           | 用户问命令、参数、示例 | 选择工具、传 filters、按模板组织回答 | 不做检索和排序     |
| `search_cloud_core_knowledge` | `/search_cloud_core_knowledge` | 模糊查询、兜底     | fallback               | 不做复杂语义拼装    |
| `assemble_cloud_core_context` | `/assemble_cloud_core_context` | 二次组装上下文     | 让回答更稳                  | 不自己做图扩展     |

Skill 需要内置的最小规则：

| 规则   | 内容                                     |
| ---- | -------------------------------------- |
| 工具选择 | 含“命令/参数/示例/怎么写”优先走 `get_command_usage` |
| 结果表达 | 固定输出“适用场景/命令模板/参数说明/示例/注意事项/来源/需要确认信息” |
| 追问规则 | 缺厂家/版本/EPC-5GC 时先给通用答案，再提示补充信息         |

这和你原稿中对 Skill 的工具选择、答案格式、追问规则的定义一致。

---

# 三、端到端使用流

## 表 26：Agent → Skill → Backend 的真实链路

以“ADD APN 命令怎么写？”为例。

| 步骤 | 参与方             | 输入                  | 处理                            | 输出                  |
| -- | --------------- | ------------------- | ----------------------------- | ------------------- |
| 1  | 用户 → Agent      | 自然语言问题              | Agent 识别为命令类                  | 工具调用意图              |
| 2  | Agent → Skill   | 问题 + 已知上下文          | Skill 选择 `get_command_usage`  | API 请求              |
| 3  | Skill → Backend | query + filters     | Backend normalize             | normalized query    |
| 4  | Backend         | normalized query    | exact/title/keyword/vector 召回 | candidates          |
| 5  | Backend         | candidates          | expansion                     | expanded candidates |
| 6  | Backend         | expanded candidates | rerank                        | ranked results      |
| 7  | Backend         | ranked results      | context assembly              | context pack        |
| 8  | Skill           | context pack        | 按模板组织回答                       | Agent answer draft  |
| 9  | Agent           | answer draft        | 最终自然语言表达                      | 用户可读答案              |

---

# 四、阶段 1 推荐的表结构总览

## 表 27：在线 + 离线核心表

| 表名                      | 关键主键                                  | 作用            |
| ----------------------- | ------------------------------------- | ------------- |
| `raw_documents`         | `doc_id`                              | 原始文件          |
| `document_profiles`     | `doc_id`                              | 厂家/产品/版本/文档类型 |
| `sections`              | `section_id`                          | 章节树           |
| `segments`              | `segment_id`                          | 证据单元          |
| `segment_annotations`   | `segment_id`                          | 轻量标签和信号       |
| `commands`              | `command_id`                          | 命令主表          |
| `command_aliases`       | `(command_id, alias)`                 | 命令别名          |
| `command_segment_links` | `(command_id, segment_id, link_type)` | 命令到证据关联       |
| `segment_edges`         | `(src_id, dst_id, edge_type)`         | 上下文扩展边        |
| `segment_embeddings`    | `segment_id`                          | 向量            |
| `alias_dictionary`      | `term`                                | 术语归一化         |
| `retrieval_logs`        | `request_id`                          | 调试与评测         |
| `publish_versions`      | `publish_id`                          | 发布版本控制        |

---

# 五、最适合你的实施顺序

## 表 28：阶段 1 建设顺序

| 里程碑         | 先做什么                                                                       | 完成标志                     |
| ----------- | -------------------------------------------------------------------------- | ------------------------ |
| M1 文档底座     | `raw_documents + document_profiles + sections + segments`                  | 能把云核心网文档稳定拆成章节和段落        |
| M2 命令增强     | `segment_annotations + commands + command_aliases + command_segment_links` | 命令类问题可以精确召回              |
| M3 图扩展      | `segment_edges`                                                            | 命中命令后能自动补齐参数/示例/注意事项     |
| M4 混合检索     | exact/title/keyword/vector/filter                                          | `get_command_usage` 基本可用 |
| M5 上下文组装    | context pack + evidence builder                                            | 后端输出稳定上下文包               |
| M6 Skill 接入 | 3 个工具 + 模板回答                                                               | Agent 能端到端回答命令类问题        |

---

# 六、我替你收束成一句“可开工定义”

你现在的阶段 1，不应该写成“做一个通用 RAG 服务”，而应该写成：

> **面向云核心网产品文档，新建一条命令与证据优先的 pipeline，产出文档画像、章节树、segment、轻量标注、命令索引和上下文扩展边；同时建设一个 `agent_knowledge` 在线服务，通过查询归一化、命令精确匹配、标题/关键词/向量混合召回、章节/RST/命令关联扩展、规则重排序和 context pack 组装，为 Skill 提供 `get_command_usage`、`search_cloud_core_knowledge`、`assemble_cloud_core_context` 三类业务语义化 API。**

这个定义和你已有设计里“新增 Agent Knowledge Backend 层、API 业务语义化、先做最小命令闭环、证据和 context pack 要稳定”的主线是一致的。  

如果你愿意，下一轮我就直接继续往下写两张你最需要的东西：
**1）字段级表结构草案**，**2）3 个 API 的 request/response JSON 契约**。
