# Agent 节点与输入上下文说明

本文说明当前 `/analysis` Agent 主链路里的关键节点、它们实际接收的输入上下文，以及各自输出什么。

这不是旧多 Agent 架构表，也不是早期“长链路多角色审查流水线”的遗留说明。当前 Agent 已经收敛成单一路径：前段做轻量门卫判断，中段进入受控工具循环，后段做规则审查和自然回答生成。

对评审或汇报读者来说，可以把它理解为一条受控分析链，而不是一组并行自治角色。当前最关键的实现锚点是：

- [modules/agent/runtime.py](/D:/Coding/map_analyse/gaode-map/modules/agent/runtime.py)
- [modules/agent/providers/langgraph_react.py](/D:/Coding/map_analyse/gaode-map/modules/agent/providers/langgraph_react.py)
- [modules/agent/providers/llm_provider.py](/D:/Coding/map_analyse/gaode-map/modules/agent/providers/llm_provider.py)

## 当前核心节点

| 节点 / 职责角色 | 当前实现锚点 | 主要输入上下文 | 主要输出 | 当前边界 / 不做什么 |
| --- | --- | --- | --- | --- |
| `Gatekeeper` | `runtime.py`、`llm_provider.py` 中的 `run_gate_with_llm(...)` | `messages`、`latest_user_message`、`analysis_snapshot_digest`、`context_summary`、`available_artifacts` | `pass / clarify / block`、`summary`、`clarification_question`、`clarification_options` | 只判断问题是否清晰、当前上下文是否足够进入后续分析；不负责规划完整步骤，也不直接产出最终结论。 |
| `Tool Loop` | `langgraph_react.py` 中的 `run_langgraph_react_loop(...)` | `question`、`analysis_snapshot_digest`、`context_digest`、`tool_catalog`、工具历史观察、当前治理状态 | 是否继续调用工具、工具调用轨迹、工具结果、停止原因、风险确认请求 | 它是当前主链路内部的 ReAct 风格工具循环，不是独立产品入口；目标是按需补证据，不是无限扩展分析链。 |
| `Rule Audit` | `runtime.py` 中的规则审查逻辑与 `audit_execution(...)` | 用户问题、`snapshot`、`context`、`memory.artifacts`、工具结果摘要、缺失证据、问题边界 | `issues`、`missing_evidence`、`required_evidence`、能否支持更稳妥的回答表达 | 它是规则层证据检查，不是旧式 LLM 审计员；不再承担 replan 主导角色，也不向用户输出独立审查栏目。 |
| `Finalizer` | `llm_provider.py` 中的 `generate_answer_output_with_llm(...)`，以及 `synthesizer.py` 的证据整理逻辑 | `messages`、`analysis_snapshot_digest`、`context_digest`、`answer_evidence_payload` | 自然语言主回答 `answer`，以及必要的引用、研究笔记、面板增强信息 | 最终只负责自然回答，不再产出结构化 answered 契约，也不再按固定四段或固定栏目交卷。 |
| `Session / Evidence Source Context` | `session_service.py`、`modules/evidence_retrieval/`、来源区选择状态 | 会话消息、assistant canonical message、已选 `source_ids`、统一证据节点、当前 `conversation_id` | 会话持久化、assistant 消息恢复、来源选择恢复、可被 Tool Loop / Finalizer 使用的证据包 | 它是上下文输入层，不是主决策节点；外部材料必须先成为来源，再由统一证据层召回，不能通过独立附件工具进入工具循环。 |

## 各节点当前怎么衔接

当前主链路可以概括为：

```text
用户问题
-> Gatekeeper
-> Tool Loop
-> Rule Audit
-> Finalizer
-> Session / Evidence Source Context 持久化与恢复
```

这条链路的产品语义很明确：

- `Gatekeeper` 负责决定能不能继续分析
- `Tool Loop` 负责按需补证据
- `Rule Audit` 负责收紧证据边界
- `Finalizer` 负责把证据翻译成自然回答
- `Session / Evidence Source Context` 负责让对话、已选来源和证据节点可恢复、可继续引用

## 阶段状态

当前主链路实际使用的阶段状态如下：

| 状态 | 含义 |
| --- | --- |
| `gating` | 门卫判断 |
| `clarifying` | 生成追问 |
| `executing` | 执行工具循环 |
| `synthesizing` | 整理证据并生成最终回答 |
| `answered` | 已完成 |
| `requires_clarification` | 需要补充信息 |
| `requires_risk_confirmation` | 等待风险确认 |
| `failed` | 失败 |

其中：

- 主 Agent 不再接收 `thinking_mode` 字段；执行深度由主链路内部的工具循环、证据缺口和风险治理共同决定
- 快速上下文问答是独立的 `context-ask` 链路，只消费预处理好的目标、来源和当前范围摘要，不进入工具循环
- answered 最终主契约只有自然回答 `answer`

## 来源证据如何进入上下文

当前外部材料不会以“附件工具”的形式直接进入 Agent。用户可见、Agent 可消费的资料对象统一叫来源。

它的进入方式是：

```text
来源区上传文档 / 图片，或添加网页 / 数据库 / 资料包
-> 后端解析、清洗、索引或构建
-> 形成 Source 条目，类型以顶层 source_kind 为准
-> Source 背后挂统一 EvidenceNode
-> Tool Loop / Finalizer 按已选 source_ids 召回证据
-> 命中节点后作为带来源证据进入回答
```

这意味着文档、图片、网页、数据库记录和资料包都是同一种来源语义。附件解析能力可以作为文档 / 图片来源构建的内部管线存在，但不再是用户可见或 Agent 工具可调用的独立产品入口。

### EvidenceNode 聚合规则

`EvidenceNode` 是来源进入 Agent 的统一证据层。它把不同材料的内部格式收敛成同一组字段：`id`、`source_id`、`source_type`、`title`、`content`、`summary`、`metadata`、`locator`、`evidence_level`、`citation` 和 `warnings`。

不同来源的聚合方式不同，但最终都落到这层：

| 来源 | 聚合入口 | EvidenceNode 内容 |
| --- | --- | --- |
| 文档 | PageIndex 章节节点、页码、章节摘要 | 章节标题、页码范围、章节摘要、文档定位信息 |
| 图片 | OCR、caption、视觉理解结果 | 图片说明、识别文本、视觉判断、置信度和错误信息 |
| 网页 | 抓取正文、页面分块、URL 元数据 | 网页标题、URL、段落摘要、引用链接 |
| 数据库 | 记录行、字段摘要、业务主键 | 记录标题、关键字段、record_id、表/数据集定位 |
| 资料包 | 包摘要、代表样本、空间载体、派生指标 | 资料包结论、样本或载体摘要、指标来源和省略说明 |
| 当前分析 | POI、H3、路网、人口、夜光等结构化结果 | 指标解释、空间对象、cell / feature / record 定位 |

聚合时系统不把完整原始 payload 直接塞进模型。文档全文、POI 明细、H3 features、路网 geometry、资料包完整 items 等重数据只留在领域模块或导出能力里。Agent 只拿轻量 EvidenceNode 和必要的 `metadata`。这样做有三个原因：

- 控制上下文体积。模型只看能支撑回答的证据片段，不吃整份原始数据。
- 保留来源边界。每个节点都带 `source_id`、`locator` 和 `evidence_level`，回答能追溯到文档章节、网页 URL、数据库记录或地图对象。
- 统一工具治理。检索工具只需要搜索和读取 EvidenceNode，不需要为文档、图片、网页、数据库和资料包各维护一套回答路径。

### 字段契约

当前后端输入契约以 snake_case 为准。来源类型读顶层 `source_kind`，证据节点读 `evidence_nodes`，来源 id 读 `source_id` / `source_ids`。`meta.sourceKind`、`sourceKind`、`sourceId`、`evidenceNodes` 这类 camelCase 字段只在部分前端展示状态、下载 payload 或旧 UI 状态中保留，不再作为 Agent 输入判断依据。

这条规则减少了调用方需要记住的兼容分支：后端、工具循环和 Finalizer 只理解一套 canonical 形状；前端如果需要展示旧字段，应该在 UI 层转换，而不是把旧字段继续传回后端当作契约。

### 快速上下文问答

快速上下文问答走独立的 `context-ask` 链路。它不进入 Tool Loop，也不做多轮工具补证据。前端先把当前问题、范围摘要、已选来源和可用 EvidenceNode 整理成目标 payload，再交给后端直接生成回答。

这个设计把“轻量追问”和“主 Agent 分析”分开：

- 轻量追问使用已经预处理好的证据，响应更短。
- 主 Agent 遇到证据缺口时，可以进入工具循环补读 EvidenceNode。
- 两条链路都共享 Source / EvidenceNode 语义，避免快速模式变成另一套附件或临时字段协议。

## 为什么不再拆成更多角色

当前 Agent 已经不再按“规划角色 + 审查角色 + 独立工具选择角色 + 旁路线程”的方式拆成更长的多角色流水线。

这样收敛后的价值是：

- 主链路更短
- 用户问题和最终回答之间的路径更清楚
- 内部仍保留工具轨迹、风险确认和证据边界
- 用户最终只看到自然回答，而不是系统把内部审查结构直接暴露出来
