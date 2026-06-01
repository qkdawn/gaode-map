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
| `Tool Loop` | `langgraph_react.py` 中的 `run_langgraph_react_loop(...)` | `question`、`analysis_snapshot_digest`、`context_digest`、`tool_catalog`、工具历史观察、`thinking_mode`、当前治理状态 | 是否继续调用工具、工具调用轨迹、工具结果、停止原因、风险确认请求 | 它是当前主链路内部的 ReAct 风格工具循环，不是独立产品入口；目标是按需补证据，不是无限扩展分析链。 |
| `Rule Audit` | `runtime.py` 中的规则审查逻辑与 `audit_execution(...)` | 用户问题、`snapshot`、`context`、`memory.artifacts`、工具结果摘要、缺失证据、问题边界 | `issues`、`missing_evidence`、`required_evidence`、能否支持更稳妥的回答表达 | 它是规则层证据检查，不是旧式 LLM 审计员；不再承担 replan 主导角色，也不向用户输出独立审查栏目。 |
| `Finalizer` | `llm_provider.py` 中的 `generate_answer_output_with_llm(...)`，以及 `synthesizer.py` 的证据整理逻辑 | `messages`、`analysis_snapshot_digest`、`context_digest`、`answer_evidence_payload`、`thinking_mode` | 自然语言主回答 `answer`，以及必要的引用、研究笔记、面板增强信息 | 最终只负责自然回答，不再产出结构化 answered 契约，也不再按固定四段或固定栏目交卷。 |
| `Session / Attachment Evidence Layer` | `session_service.py`、`retrieval/attachments.py`、附件检索工具 | 会话消息、assistant canonical message、已上传附件 ID、附件检索结果、当前 `conversation_id` | 会话持久化、assistant 消息恢复、附件状态、可被 Tool Loop 调用的附件证据 | 它是上下文输入层，不是主决策节点；附件只在需要时通过 `search_uploaded_attachment_context` / `read_uploaded_attachment_context` 进入工具循环。 |

## 各节点当前怎么衔接

当前主链路可以概括为：

```text
用户问题
-> Gatekeeper
-> Tool Loop
-> Rule Audit
-> Finalizer
-> Session / Attachment Evidence Layer 持久化与恢复
```

这条链路的产品语义很明确：

- `Gatekeeper` 负责决定能不能继续分析
- `Tool Loop` 负责按需补证据
- `Rule Audit` 负责收紧证据边界
- `Finalizer` 负责把证据翻译成自然回答
- `Session / Attachment Evidence Layer` 负责让对话和附件证据可恢复、可继续引用

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

- `thinking_mode` 只影响执行深度和工具轮次，不决定节点模板
- `deep` 不是报告模式，只是允许多做一轮证据检查和边界校验
- answered 最终主契约只有自然回答 `answer`

## 附件证据如何进入上下文

当前附件能力是上下文输入来源之一，但不会默认全文通读。

它的进入方式是：

```text
用户上传附件
-> uploaded / processing / ready / failed
-> ready 后进入当前会话附件列表
-> Tool Loop 在用户提到文件、报告、图纸、图片、表格时按需检索
-> 命中片段后作为证据进入回答
```

这意味着附件在当前架构里是“证据补充层”，而不是独立文件问答主链路。

## 为什么不再拆成更多角色

当前 Agent 已经不再按“规划角色 + 审查角色 + 独立工具选择角色 + 旁路线程”的方式拆成更长的多角色流水线。

这样收敛后的价值是：

- 主链路更短
- 用户问题和最终回答之间的路径更清楚
- 内部仍保留工具轨迹、风险确认和证据边界
- 用户最终只看到自然回答，而不是系统把内部审查结构直接暴露出来
