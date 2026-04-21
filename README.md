# CoreMasterKB

## 一、这个项目是干什么的

CoreMasterKB 不是一个“文档搜索小工具”，也不是一个“只查命令”的定制系统。

它的目标是构建一套能被 Agent 作为 Skill 调用的知识后台，也就是：

```text
Agent Knowledge Backend
```

这个后台要解决的是：

1. 原始资料来源复杂  
   未来不只是产品文档，还会有专家文档、项目文档、Markdown、TXT、HTML、PDF、DOCX 等多种来源。

2. 查询意图复杂  
   不只是“某命令怎么写”，还包括概念解释、参数说明、操作步骤、注意事项、故障处理、适用范围、差异比较和上下文扩展。

3. 系统要适合 Agent 调用  
   输出不能是写死的页面字段，也不能只是字符串搜索结果，而应该是可被 Agent 消化的上下文包、证据材料和来源信息。

4. 系统会持续快速演进  
   当前 1.1 的重点不是一次做完，而是把主干方向定对，让后续演进不会反复推翻基础结构。

### 当前统一目标态

当前 1.1 的主干链路是：

```text
原始资料
  -> Mining 解析与结构化
  -> asset_core 知识资产库
  -> Serving 检索与上下文扩展
  -> Agent Skill 消费

同时：
Mining / Serving 可以调用独立的 LLM Runtime 服务
```

### 当前数据库边界

当前正式数据库边界是三套：

```text
databases/
  asset_core/
  mining_runtime/
  agent_llm_runtime/
```

含义分别是：

- `asset_core`：知识资产库，Mining 写，Serving 读，保存共享内容快照、build、release 以及其下游检索资产
- `mining_runtime`：Mining 自身运行态库，保存 run、断点续跑、阶段状态、失败定位
- `agent_llm_runtime`：独立 LLM 服务运行态库，保存 prompt、task、request、attempt、result、event

### 当前关键原则

1. `asset_core` 是稳定知识资产库 + build/release 控制面，不保存复杂运行态噪音。
2. `mining_runtime` 是过程状态库，不作为 Serving 读取入口。
3. `agent_llm_runtime` 是独立服务库，不与资产库混表。
4. Serving 只读 active `release` 对应的 `build`。
5. `snapshot` 是共享内容快照，不是文档专属快照。
6. `build` 定义“这次知识视图里每个 document 采用哪个 snapshot”。
7. `publish` 的正式语义是 `release -> build`，不是换文件，也不是日志。
8. Serving 1.1 主路径不再围绕 canonical，而应围绕：

```text
shared snapshots
  -> raw_segments
  -> raw_segment_relations
  -> retrieval_units
```

9. LLM 是增强器，不是事实源。

### 当前 `asset_core` 主链

```text
source_batch
  -> document
  -> shared snapshot
  -> document_snapshot_link
  -> raw_segments / relations / retrieval_units
  -> build
  -> release
  -> serving
```

### 关于 Mining 涉及两个 DB 是否合并

当前已经明确：

```text
正式设计不合并
```

也就是：

- `asset_core` 和 `mining_runtime` 逻辑上必须分开
- 如果未来为了本地调试方便，临时放进同一个 SQLite 文件，只能视为 dev 便利
- 不能把“物理同文件”当成“正式合库设计”

原因很直接：

1. `asset_core` 要稳定、干净、可发布、可被 Serving 长期只读
2. `mining_runtime` 天然包含中间态、失败态、重试态、诊断信息
3. 两者生命周期、清理策略、读写模式完全不同

---

## 二、三个开发者各自的完整上下文

这部分不是任务拆解，而是三位执行人进入工作前必须先对齐的上下文、边界和目标态。

### 共同上下文

三个人都必须先知道下面这些前提。

#### 1. 当前不是做“最终正确实现”，而是做“正确主干”

当前更看重的是：

1. 边界是否正确
2. 中间契约是否稳定
3. 后续扩展是否顺滑

当前不追求的是：

1. 一次把检索质量做到最终态
2. 一次把 LLM 接入做到最强
3. 一次把所有文件类型解析完
4. 一次把版本系统做成完整 Git 模型

#### 2. 当前系统会继续演进

后续系统会继续演进到：

- hybrid retrieval
- embedding / vector search
- rerank
- LLM query rewrite
- LLM retrieval planning
- relation-based context expansion
- 更复杂的数据源解析
- 更复杂的图关系

所以三个人都必须避免把自己的模块写成只能服务当前单一场景的定制实现。

#### 3. 当前最重要的统一抽象

这几个抽象要尽量稳住：

1. `raw segment` 是事实单元
2. `retrieval unit` 是检索单元
3. `raw segment relation` 是上下文关系
4. `shared snapshot` 是内容复用边界
5. `build / release` 是知识视图与发布边界
6. `ContextPack / EvidencePack` 是 Serving 输出
7. `LLM Runtime Task` 是 LLM 调用抽象

---

### claude-mining 的完整上下文

#### 他的角色

`claude-mining` 负责的是：

```text
把复杂原始资料变成结构化、可检索、可追溯的知识资产
```

他的价值不在于“把文本存进数据库”，而在于：

1. 把原始资料整理成稳定资产
2. 把篇章结构和来源定位保留下来
3. 把对检索有价值的结构化信息尽量抽出来
4. 为 Serving 提供通用而不是定制化的检索基础

#### 他面对的问题本质

原始资料未来不会稳定：

- 可能是 Markdown
- 可能是 TXT
- 可能是 HTML
- 可能是 PDF / DOCX
- 可能是专家文档
- 可能没有产品、网元这些字段

所以 Mining 的目标不是：

```text
把某一种文档喂给某一种规则，然后满足某一种查询
```

而是：

```text
把“文档 -> 结构 -> 片段 -> 关系 -> 检索单元”这条通用生产链做好
```

#### 当前他应该对齐的目标态

##### A. 原始事实层

把每个输入文件先归到：

- `asset_documents`
- `asset_document_snapshots`
- `asset_document_snapshot_links`

再把可解析内容落到 `asset_raw_segments`。

关键要求：

- 文档身份可回溯
- 内容快照可复用
- 片段可回溯
- `section_path` 稳定
- `structure_json` 尽量保真
- `source_offsets_json` 可定位

##### B. 上下文关系层

生成 `asset_raw_segment_relations`。

这是当前 Mining 必须重视的重点，不是可有可无的增强。

最少要稳定生成：

- `previous`
- `next`
- `same_section`
- `same_parent_section`
- `section_header_of`

##### C. 检索单元层

生成 `asset_retrieval_units`。

这里最关键的思想是：

```text
retrieval_unit 不是去重结果
retrieval_unit 是面向检索的封装视图
```

也就是说：

- raw segment 是事实源
- retrieval unit 是检索入口

同一个 raw segment 可以生成多个 retrieval unit，例如：

- `raw_text`
- `contextual_text`
- `summary`
- `generated_question`
- `table_row`
- `entity_card`

第一版不要求全部做完，但设计必须朝这个方向走。

#### 他不该做什么

1. 不要把 Serving 当前某个查询逻辑写死到 schema 中
2. 不要要求未来语料必须带 manifest 或固定元数据文件
3. 不要再保留或强化 canonical 主路径
4. 不要把 LLM 结果当原始事实
5. 不要为了某个命令场景造一堆命令专用外层列

#### 他需要和其他人怎样对接

对 Serving，他提供的是：

- active `asset_core`
- active `release -> build`
- 稳定的 `retrieval_units`
- 可下钻的 `raw_segments`
- 可扩展的 `raw_segment_relations`

他不应该依赖 Serving 的具体 SQL 写法。

对 LLM，他应该把 LLM 看成一个可选增强器，可以用在：

- generated question 生成
- summary 生成
- 语义角色候选增强
- 实体候选增强

但这些输出都必须：

- 可追溯
- 只保留到 LLM runtime 的弱引用
- 不能覆盖原始事实

#### 给他的评价标准

不是“是不是把文档都处理完了”，而是：

1. 资产是否稳定
2. 结构是否保住
3. 来源是否可回溯
4. 关系是否足够支撑上下文扩展
5. retrieval unit 抽象是否走对

---

### claude-serving 的完整上下文

#### 他的角色

`claude-serving` 负责的是：

```text
把知识资产变成 Agent 能消费的上下文服务
```

他不负责：

- 解析文档
- 生产资产
- 发布版本
- 重写数据库事实

#### 他面对的问题本质

Serving 不是做一个固定问答接口，而是在做：

```text
Agent Skill 的知识调用后端
```

这意味着：

1. 查询意图会越来越复杂
2. 上层 Agent 可能会传 `scope`、`entity`、`intent`，也可能什么都不传
3. 后续完全可能把部分理解和规划交给 LLM
4. 输出不能被某一个单场景绑死

#### 当前他应该对齐的目标态

##### A. 以 retrieval_units 为主检索入口

当前 1.1 主路径不应该再围绕 canonical。

主检索入口应是：

```text
asset_retrieval_units
```

然后：

```text
retrieval_units
  -> source_refs_json
  -> raw_segments
  -> document_snapshot_links / documents
  -> raw_segment_relations
```

##### B. 输出通用 ContextPack

Serving 返回的东西要适合 Agent 消费，而不是适合某一个前端页面。

返回结构应是通用的 Evidence / Context 包，核心模块应包括：

- query understanding 结果
- items / evidence
- sources
- relations
- variants
- conflicts
- gaps
- suggestions
- debug（可选）

##### C. 设计成可插入 LLM 的查询链

Serving 当前不能强依赖 LLM，但要预留这些插点：

- query rewrite
- intent extraction
- entity enrichment
- retrieval planning
- rerank
- context compression

也就是说当前就要有：

```text
query understanding
-> query plan
-> retrieval
-> expansion
-> assembly
```

即便第一版 planner 很简单，也不能没有这个抽象。

#### 他不该做什么

1. 不要继续把 Serving 写成 command-only 系统
2. 不要强依赖 JSON 里必须存在某个子字段才能检索
3. 不要把 Mining 的当前实现细节当成长期契约
4. 不要把查询逻辑固化成一堆 endpoint 特判
5. 不要把最终答案生成混进 Serving 主职责

#### 他需要和其他人怎样对接

对 Mining，他必须把 Mining 输出看成：

```text
尽力结构化，但不完美
```

所以 Serving 读取时必须：

- 允许字段缺失
- 允许 JSON 形态不完美
- 保留 fallback 路径

对 LLM，他应该把 LLM 看成在线增强器，而不是基础依赖：

- 有 LLM 时增强理解和排序
- 没有 LLM 时基础检索仍然可用

#### 给他的评价标准

不是“某条命令能不能查到”，而是：

1. 查询链路抽象是否通用
2. 对数据契约是否足够宽容
3. 输出是否适合 Agent 使用
4. 是否已经把 LLM 插点留好
5. 是否走向 hybrid retrieval，而不是继续写死规则问答

---

### claude-llm 的完整上下文

#### 他的角色

`claude-llm` 不是来写业务逻辑的。

他负责的是：

```text
把 LLM 能力抽象成一个独立、稳定、可追踪、可审计的 runtime 服务
```

他的目标不是回答业务问题，而是给 Mining 和 Serving 提供统一 LLM 能力底座。

#### 他面对的问题本质

如果 LLM 不独立抽象，后面一定会出现：

- Mining 自己写一套 prompt / retry / parse
- Serving 再写一套 prompt / retry / parse
- 两边日志、幂等、模板、schema 验证全面分裂

所以他要解决的是：

```text
LLM 调用能力的平台化
```

#### 当前他应该对齐的目标态

##### A. 统一任务模型

核心抽象是：

- prompt template
- logical task
- request
- attempt
- result
- event

这几层必须明确分开。

##### B. 同时服务 Mining 和 Serving

他不是只给 Serving 用，也不是只给 Mining 用，两边都要能调用。

典型场景：

Mining 侧：

- summary generation
- generated question generation
- semantic enrichment
- entity enrichment

Serving 侧：

- query rewrite
- intent extraction
- retrieval planning
- rerank
- context compression

##### C. 强调幂等、追溯、审计

因为后面只要 LLM 接入变深，就一定会遇到：

- 失败重试
- provider 波动
- JSON 解析失败
- schema 不匹配
- 重复提交
- 成本统计

所以 runtime 设计里必须把这些前置考虑进去。

#### 他不该做什么

1. 不要把业务逻辑耦合进 runtime
2. 不要直接写 `asset_core` 表
3. 不要假设只有一个 provider 或一个模型
4. 不要只做“调用一下 API”的轻封装
5. 不要把 prompt 版本和结果追溯省掉

#### 他需要和其他人怎样对接

对 Mining / Serving，他提供的是：

- 一个 runtime 服务
- 一套任务表
- 一个清晰的 client 接口
- 一套输出 schema 校验机制

他不负责决定：

- 哪个业务点一定要调用 LLM
- LLM 结果如何写回 `asset_core`
- Serving 的检索排序策略

#### 给他的评价标准

不是“能不能调通模型”，而是：

1. runtime 抽象是否完整
2. 是否适合两边复用
3. 是否有足够的追溯和幂等能力
4. 是否能承接后续 provider / template / schema 演进

---

### 三个人之间真正的接口

#### Mining -> Serving

接口不是 Python 代码，不是函数调用，而是：

```text
asset_core 数据契约
```

主要就是：

- `documents`
- `document_snapshots`
- `document_snapshot_links`
- `raw_segments`
- `raw_segment_relations`
- `retrieval_units`
- `builds`
- `publish_releases`

#### Mining / Serving -> LLM

接口不是共享表写入，而是：

```text
LLM Runtime client / service
```

返回结果后，业务侧只保留弱引用。

#### 管理员真正要控制的事情

后面正式分任务时，最重要的不是把代码切太细，而是把下面四件事切清楚：

1. 每个人负责的数据库边界
2. 每个人负责的抽象层
3. 每个人不应该跨过去做的事
4. 每个人产出后谁消费、怎么验证

### 当前建议的发任务口径

给 Mining：

```text
围绕 raw -> relations -> retrieval_units 这条主链，
把离线知识资产生产路径拉到 1.1 正轨。
```

给 Serving：

```text
围绕 retrieval_units + relations + ContextPack，
把在线知识服务重写成 Agent 可消费的通用检索后台。
```

给 LLM：

```text
围绕 prompt / task / request / attempt / result / event，
做一个可被 Mining 和 Serving 共同调用的独立 LLM Runtime。
```
