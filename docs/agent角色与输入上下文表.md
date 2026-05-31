# Agent 角色与输入上下文表

本文整理当前 Agent 编排链路中的角色、对应实现、主要输入上下文与输出。当前实现是单一 orchestrator 的多阶段流水线，不是真正并发自治 Agent。

| 角色 | 对应阶段 / 模块 | 主要输入上下文 | 主要输出 | 说明 |
| --- | --- | --- | --- | --- |
| 门卫节点 Gatekeeper | `gating` / `modules/agent/gate.py`、`modules/agent/providers/prompts.py` | 用户最新问题、会话消息、当前 analysis snapshot、范围状态、已有结果摘要 | `pass`、`clarify` 或 `block`；问题类型；缺失信息；澄清问题与选项 | 判断问题是否足够清晰，是否可以进入规划阶段。缺少关键输入时优先追问，不直接编造范围或结论。 |
| 工具文档搜索员 Context Retriever | `context_ready` / `modules/agent/context_builder.py`、`modules/retrieval/` | 当前 analysis 快照、已有 artifacts、前端面板 payload、上传附件、知识片段、历史结果摘要 | 压缩后的上下文包、可用证据摘要、附件证据片段、当前能力状态 | 负责把分散的地图状态和分析结果整理成可供 Planner、Tool Selector、Auditor 使用的上下文。 |
| 规划师 Planner | `planning` / `modules/agent/planner.py`、`modules/agent/providers/prompts.py` | 用户问题、上下文包、已有 artifacts、审计反馈、证据缺口、问题类型信号 | 目标、问题类型、是否需要工具、证据关注点、工具选择简报、停止条件 | 规划师不直接选择具体工具，而是给出最小必要、证据驱动的分析意图。 |
| 工具选择 Agent Tool Selector | `planning` / `modules/agent/providers/tool_loop.py`、`modules/agent/providers/prompts.py` | Planner 意图、轻量工具目录、fallback step hints、当前证据摘要、工具治理信息 | 工具步骤列表、参数、执行原因、证据目标、预期 artifacts、警告 | 根据规划意图选择最小必要工具。默认优先场景工具，其次能力工具，最后基础工具。 |
| 工具执行器 Executor | `executing` / `modules/agent/executor.py`、`modules/agent/tool_service.py` | 已确认的 PlanStep、工具注册表、工具参数、当前 snapshot、治理检查结果 | 工具执行结果、trace、artifacts、错误或跳过原因 | 只调用白名单工具，并把执行轨迹回注给后续审计和综合阶段。 |
| 审计员 Auditor | `auditing` / `modules/agent/auditor.py`、`modules/agent/providers/prompts.py` | 用户问题、Planner 目标、工具执行结果、证据摘要、review contract、已有诊断 | `pass`、`replan` 或 `fail`；问题列表；缺失证据；重规划指令；是否可以回答 | 检查证据是否真的覆盖问题。证据不足时要求 replan，无法可靠回答时 fail。 |
| 综合分析师 Synthesizer | `synthesizing` / `modules/agent/synthesizer.py`、`modules/agent/providers/prompts.py` | 审计通过的证据、工具结果、上下文摘要、review contract、引用信息、用户问题 | 结构化决策、证据矩阵、反证 / 缺口、行动建议、边界说明、summary/evidence/recommendation 卡片 | 负责最终回答与报告卡片。只能使用给定证据，不把 GIS 指标直接推断成客流、消费能力、营业额或收益。 |
| GIS Agent 工具调度器 Tool Loop | `executing` / `modules/agent/react_orchestrator.py`、`modules/agent/providers/tool_loop.py`、`modules/agent/providers/prompts.py` | 用户问题、当前 snapshot 摘要、可用工具、上下文限制、工具调用历史、审计反馈 | thought/action/observation/final 事件、工具调用意图、继续或停止决策 | ReAct/tool loop 中的调度角色，决定是否继续补证据或停止调用工具。 |
| 能力工具化层 Tool Registry | 工具基础设施 / `modules/agent/tools.py`、`modules/agent/tool_definitions/`、`modules/agent/tool_adapters/` | 后端业务能力、工具定义、参数提示、成本等级、UI tier、数据域、治理模式 | 可调用工具目录、工具 schema、工具适配器、工具元数据 | 不是独立 LLM 角色，而是把 POI、H3、人口、夜光、路网、场景分析等能力封装为统一工具接口。 |
| 多层工作记忆 Working Memory | 运行时上下文 / `modules/agent/memory.py` | 会话状态、研究笔记、关键证据、任务状态、执行轨迹 | 当前轮可用记忆、证据记录、任务过程信息 | 帮助一次 Agent turn 内保持证据和中间状态，不等同于跨会话长期记忆。 |
| 控制平面 Control Plane | 状态机与治理 / `modules/agent/state_machine.py`、`modules/agent/governance.py` | 当前阶段、工具风险、成本等级、自动执行边界、风险确认状态、终止条件 | 阶段迁移、风险确认请求、失败状态、是否允许执行 | 负责让 Agent 执行过程可控，避免高成本或高风险工具被无约束调用。 |

## 阶段状态

| 状态 | 含义 |
| --- | --- |
| `gating` | 门卫判断 |
| `clarifying` | 生成追问 |
| `context_ready` | 整理上下文 |
| `planning` | 规划分析步骤 |
| `executing` | 执行工具 |
| `auditing` | 审计结果 |
| `replanning` | 根据审计重新规划 |
| `synthesizing` | 综合分析 |
| `answered` | 已完成 |
| `requires_clarification` | 需要补充信息 |
| `requires_risk_confirmation` | 等待风险确认 |
| `failed` | 失败 |
