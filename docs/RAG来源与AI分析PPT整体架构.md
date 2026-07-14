# RAG 来源、AI 分析与 PPT 生成整体架构

本文用产品和工程都能对齐的口径说明当前 `/analysis` 中 RAG 来源、处理后的组合包、PPT 生成和 AI 分析两种模式如何衔接。

## 1. 总览

整体链路不是“把所有资料塞给大模型”，而是：

```text
原始来源
-> 来源区 Source
-> EvidenceNode / Metric Context / Data Package / Visual Asset
-> PPT 生成或 AI 分析
-> 带证据、引用、缺口说明的结果
```

核心原则：

- 所有资料先成为来源区里的 `Source`，再被 AI 使用。
- 大模型默认只看紧凑上下文，不直接读取完整 POI、网格、路网、文档全文或原始表。
- 需要具体对象、TopN、局部差异、文档段落或资料包明细时，通过受控工具按需检索。
- 对外口径避免叫“数据库来源”。更准确的产品名称是**当前项目成果包**或**分析成果来源**；底层可以仍使用 `database` 作为内部 source kind。

## 2. RAG 来源

| 来源 | 输入方式 | 处理后形态 | 主要用途 |
| --- | --- | --- | --- |
| 当前分析结果 | 用户在 `/analysis` 里完成 POI、H3、人口、夜光、路网、选址等分析 | `current:analysis:*` source、结构化摘要、指标、诊断文本 | 解释已算好的结论，支撑 PPT 数据页 |
| 当前范围数据源 | 当前 `history_id` 下保存的 POI、H3 cell、人口 cell、夜光 cell、路网 feature | `current:dataset:*`，通过 scoped dataset 工具分页/聚合/读取 | 查询明细、TopN、分组统计、单条对象 |
| 文档来源 | 上传 PDF、DOCX、PPTX、项目资料、服务建议书、已有成果 | Docling 解析、PageIndex、`document_index_nodes`、EvidenceNode | 项目事实、诉求、历史文化、政策和已有表达 |
| 图片来源 | 上传现场照片、规划图、效果图、截图 | ImageVisualIndex contract、图片 asset、OCR/视觉节点目标形态 | PPT 视觉素材、图像证据、后续页面资产 |
| 网页来源 | SearXNG 搜索或用户添加 URL | Crawl4AI Markdown、网页段落 EvidenceNode、URL 引用 | 政策、案例、竞品、商圈和外部背景 |
| 当前项目成果包 | 已保存 history、artifact、POI summary、分析摘要 | 结构化成果 EvidenceNode，内部 source kind 可为 `database` | 复盘当前项目已沉淀的成果，不代表全库查询 |
| 空间资料包 | 用户选择来源和资料意图后生成 | `package:*` source，包含 items、groups、carriers、evidence_nodes | 为 PPT 某几页准备代表性样本或空间载体 |
| 地图视觉资产 | 前端捕获地图总览和图层状态 | visual assets、map snapshots | PPT 页面中的地图、图层图、空间证据画面 |

## 3. 处理后的四种组合包

当前 RAG 处理后给 AI 和 PPT 使用的主要不是单一 chunk，而是四类组合包。

### 3.1 Source Manifest 包

说明“本轮选了哪些来源、每个来源是什么状态、有哪些证据、怎么读取”。

典型内容：

```text
source_id
title
source_kind
status / availability
evidence_count
native_index_kind
retrieval_modes
read_modes
diagnostics
```

作用：

- PPT 生成知道有哪些资料可以使用。
- AI 分析知道只能检索已选来源，不能访问未选来源或全库。
- 后续排查可以看到来源是否为空、是否解析失败、是否只传了摘要。

### 3.2 Evidence Pack 包

把不同来源投影成统一 `EvidenceNode`。

典型内容：

```text
id
source_id
source_type
title
content / summary
metadata
locator
citation
evidence_level
```

来源映射：

- 文档 PageIndex 节点 -> EvidenceNode
- 网页段落 -> EvidenceNode
- 图片 OCR/caption/视觉节点 -> EvidenceNode
- 当前项目成果摘要 -> EvidenceNode
- 空间资料包 item/carrier/metric ref -> EvidenceNode

作用：

- 给 AI 回答提供可引用证据。
- 给 PPT 每页的 `evidence_explanation`、`required_sources`、`citation` 提供依据。
- 避免模型直接消费原始 payload。

### 3.3 Metric Context 包

把 POI、H3、人口、夜光、路网等可用指标压缩成 PPT/AI 可读的指标上下文。

典型内容：

```text
metric_id
title
value
unit
domain
source_ids
status
metric_gaps
policy
```

例子：

- `analysis:poi:poi_count`
- `analysis:h3:avg_density_poi_per_km2`
- `analysis:population:total_population`
- `analysis:nightlight:max_radiance`
- `analysis:road:avg_choice`

作用：

- PPT 数字页、指标卡、表格和图表只能绑定 ready metric。
- 缺失指标进入 `metric_gaps`，不让 AI 编造。
- AI 分析可以把指标转译为空间现象、商业含义和风险边界。

### 3.4 Visual / Data Package 包

这是为展示材料和具体页面准备的组合包。

包括：

- `ppt_data_package`：POI 样例包、夜生活资料包、空间载体包。
- `visual_assets`：地图截图、POI 图层、H3 图层、人口图层、夜光图层、路网图层。
- `visual_specs`：某页需要的图、表、矩阵、地图或既有素材说明。
- `carriers`：POI × 路网 × 人口 × 夜光共同支撑的街区、廊道、路段等空间载体。

作用：

- PPT 指令文件可以明确“这一页用什么图、什么地图、什么表、什么资料包”。
- 后续 HTML/PPTX 渲染可以按 `visual_specs` 找资产，而不是重新理解所有来源。

## 4. 给 PPT 的使用方式

PPT AI 主链路是分阶段生成，不直接一步生成 PPTX。

```text
已选 Source
-> _build_ppt_context_bundle()
-> source_manifest + metric_context + evidence_context + scope_brief
-> generate_ppt_spec()
-> generate_narrative_plan()
-> generate_deck_brief()
-> regenerate_deck_brief_slide()
-> generate_visual_artifacts_for_slide()
```

各阶段职责：

| 阶段 | 输入 | 输出 | 作用 |
| --- | --- | --- | --- |
| 来源整理 | 已选 Source、当前区域、用户配置 | `source_manifest`、`metric_context`、`evidence_context` | 确认本次 PPT 可用材料 |
| 目录生成 | 主题、受众、页数、来源摘要 | `PptSpecResponse` | 决定章节和页码 |
| 叙事方案 | 目录、证据桶、指标上下文 | `DeckNarrativePlanResponse` | 决定每页角色、章节节奏和证据桶 |
| 指令文件 | 叙事方案、证据、指标、视觉资产 | `DeckBriefResponse` | 生成逐页 brief |
| 逐页修补 | 单页 brief、前后页摘要、修改要求 | `DeckSlideBrief` | 只改某一页 |
| 视觉资产 | `visual_specs`、metric context、现有 assets | `PptVisualArtifactResponse` | 生成或绑定地图、图表、表格、素材 |

PPT 每页最终关注这些字段：

```text
title
purpose
key_message
insight
evidence_explanation
required_sources
metric_claims
metric_gaps
visual_specs
visual_artifacts
```

## 5. 给 AI 分析的使用方式

AI 分析分成快速模式和深度模式。两者使用同一批来源和证据，但循环深度不同。

### 5.1 快速模式

入口：

```text
answer_context_ask()
```

直接路径：

```text
用户问题
-> target / analysis_snapshot / selected sources
-> build_scoped_dataset_context()
-> _build_user_payload()
-> client.chat_json(phase="context_ask")
-> 返回 answer + evidence + citations + warnings
```

适合：

- “这个来源说明什么？”
- “这个范围餐饮结构怎么样？”
- “某个 PPT 来源能支撑哪几页？”
- “当前数据里 TopN 是哪些？”
- “快速解释某个指标或图层。”

特点：

- 不进入工具循环。
- 主要围绕已选来源和后端预处理好的当前范围数据。
- 输出快，但不主动扩展复杂分析链。
- 仍必须带证据、引用和缺口说明。

### 5.2 深度模式

入口：

```text
主 Agent turn / thinking_mode = deep
```

核心循环：

```text
用户问题
-> Gate 判断是否需要澄清或风险确认
-> build_context_bundle()
-> ReAct Tool Loop
-> 工具执行和证据补齐
-> Auditor 检查证据缺口和风险
-> build_finalizer_evidence_pack()
-> Finalizer 生成最终回答
```

ReAct 工具循环会收到：

```text
analysis_snapshot_digest
context_digest
artifact_catalog
tool_catalog
selected_sources_context
business_analyst_skeleton
```

适合：

- “这个区域适合发展什么业态？”
- “为什么这里商业活力不足？”
- “结合 POI、人口、夜光、路网给出更新策略。”
- “做一版区域商业深度画像。”
- “继续分析并指出证据缺口和下一步动作。”

特点：

- 允许多轮工具调用。
- 会更严格检查证据缺口、冲突证据和解释边界。
- 可使用 Business Analyst skeleton / Model Graph 作为分析导航。
- deep 不是固定报告模板，只是更强的证据补齐和校验链路。

## 6. 快速模式与深度模式对比

| 维度 | 快速模式 | 深度模式 |
| --- | --- | --- |
| 主要入口 | `answer_context_ask` | 主 Agent turn / ReAct loop |
| 核心目标 | 快速回答来源问题和当前范围问题 | 多证据综合分析和策略判断 |
| 工具循环 | 无；只做后端确定性预处理 | ReAct 多轮工具循环 |
| 可用来源 | 已选来源、当前范围数据源 | 当前 analysis、已选来源、工具目录、BA skeleton |
| 证据策略 | 把已选来源摘要和 scoped dataset context 一次性传入 | 先规划，再补证据，再审计，再综合 |
| 输出 | 简洁专业回答、证据、引用、warnings | 更完整回答、推理边界、引用、下一步动作 |
| 风险 | 不适合复杂跨域推理 | 成本更高、耗时更长 |

## 7. 两条消费链路的关系

PPT 和 AI 分析共享同一套来源，但消费方式不同：

```text
Source / EvidenceNode / Metric Context / Data Package
        |                         |
        |                         +-> PPT：目录、叙事、逐页指令、视觉资产
        |
        +-> AI 分析：快速问答、深度 ReAct 分析、finalizer 综合回答
```

PPT 更关注：

- 每页讲什么。
- 每页用什么证据。
- 每页需要什么地图、图表、图片。
- 哪些指标能上图，哪些指标缺失。

AI 分析更关注：

- 用户问题该查哪些来源。
- 当前证据能支持什么判断。
- 哪些结论只能代表当前范围内部。
- 还缺什么数据、下一步该怎么验证。

## 8. 推荐对外术语

| 不推荐说法 | 推荐说法 | 原因 |
| --- | --- | --- |
| 数据库来源 | 当前项目成果包 / 分析成果来源 | 避免误解为 AI 可查全库或直接查 SQL |
| RAG 数据库 | 证据来源层 / 来源索引层 | 当前是多来源 native index，不是单一向量库 |
| AI 直接生成 PPT | AI 生成 PPT 指令文件 | 当前主产物是可审核的逐页 brief |
| deep 报告模式 | 深度分析模式 | deep 只是更强证据循环，不是固定报告模板 |
| 原始数据进 prompt | 来源证据包进入 LLM | 原始明细通过工具按需读取 |

## 9. 一句话架构口径

当前架构可以概括为：

```text
把地图分析、项目文档、图片、网页、当前项目成果和空间资料包统一收敛为 Source；
再投影成 EvidenceNode、Metric Context、Data Package 和 Visual Asset；
PPT 使用它们生成目录、叙事和逐页指令；
AI 分析使用它们执行快速来源问答或深度 ReAct 证据循环；
最终输出必须带来源、引用、证据边界和缺口说明。
```
