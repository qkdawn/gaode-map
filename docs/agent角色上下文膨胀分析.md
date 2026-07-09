# Agent 角色上下文膨胀分析

本文按当前 Agent 角色检查每个 LLM / 工具阶段塞入的上下文，重点判断是否存在不必要的全量上下文导致 prompt 过大。结论基于当前代码结构。

## 总体结论

当前最容易触发上下文增长的是 **GIS Agent ReAct 工具循环** 和 **Synthesizer**。ReAct 工具回填已通过 `compact_for_llm` 做深度压缩，但每轮仍会把工具摘要、压缩后的 `result` 和 `evidence` 追加进模型消息；多轮调用时仍可能累积。Synthesizer 虽然做了 digest，但如果某些工具把大对象放在 `result` 而不是 `artifacts`，最终生成阶段仍可能变重。

旧版独立 Planner、Tool Selector、LLM Auditor 和 compact catalog 路径已经移除；后续优化不要围绕这些旧角色继续加兼容层，应直接收敛到当前的直答分支、ReAct 工具循环和最终综合阶段。

## 逐角色分析

| 角色 | 当前塞入上下文 | 是否可能塞了不必要的全量上下文 | 风险等级 | 主要问题 | 建议 |
| --- | --- | --- | --- | --- | --- |
| 门卫节点 Gatekeeper | 最近消息、latest user message、`snapshot_digest`、`context_summary`、可用 artifact 名称 | 基本没有 | 低 | `snapshot_digest` 已经只保留范围、摘要、计数和少量 filters；适合门卫判断 | 保持 digest 输入即可。门卫不需要完整 POI、H3 grid、frontend_analysis。 |
| 工具文档搜索员 Context Retriever | 当前 snapshot、artifacts、frontend_analysis、附件/知识片段 | 有潜在风险，但主要发生在它产出的 context 被后续角色使用时 | 中 | `build_context_bundle` 会把 `snapshot.frontend_analysis` 全量放入 `context.analysis`，虽然后续 `context_digest` 对它只取 keys，但内存中的 bundle 本身仍是全量 | ContextBundle 内部可以保留完整对象，但传给 LLM 必须统一走 digest。避免新增角色直接传 `context.model_dump()`。 |
| ReAct 初始决策 | 最近消息、`snapshot_digest`、`context_digest`、artifact catalog、可见工具简表 | 基本没有 | 低到中 | 已移除独立 Planner / Tool Selector / compact catalog 路径；初始输入由 `langgraph_react._initial_payload` 生成，只给 digest 和工具简表 | 保持单一 ReAct 编排，不恢复旧 planner catalog。后续如工具继续增长，应在 `chat_completion_tools` 前按问题域裁剪工具集合。 |
| 工具执行器 Executor | PlanStep、snapshot、memory.artifacts、工具参数 | 不属于 LLM prompt，但会产生过大的 memory | 中 | 执行器会把工具结果完整追加到 `memory.tool_results`，并把 `result.artifacts` 合并到 `memory.artifacts`；这本身合理，但后续如果全量传给 LLM 就危险 | 保留执行期全量 artifacts 可以，但需要增加专门的 `llm_digest` 或 `audit_digest`，禁止后续 LLM 直接 dump ToolResult 全量。 |
| 规则审计 Auditor | question、snapshot、context、memory、规则审计结果 | 中 | 当前审计是服务端规则逻辑，不再走独立 LLM 审计 payload；风险主要来自规则实现如果直接遍历大 artifacts | 保持 Auditor 不引入 LLM 全量 dump。需要给 LLM 时必须走 `audit_tool_results_digest`。 |
| 综合分析师 Synthesizer | 最近消息、`snapshot_digest`、`context_digest`、`synthesis_payload` | 部分可能 | 中 | `synthesis_payload` 已经结构化，但 `tool_results` 里仍把每个工具的 `result` 原样放入；如果某些工具把大对象放在 result 而不是 artifacts，也会膨胀 | Synthesizer 只需要最终 decision/support/evidence_matrix/actions/boundary。`tool_results` 建议保留摘要字符串或关键字段白名单，不传完整 result。 |
| GIS Agent ReAct 工具循环 | 初始 digest、可见工具 schema、每轮 assistant/tool 消息、压缩后的工具结果 payload | 是，尤其多轮工具调用时 | 中到高 | `_react_tool_result_payload` 已压缩 `result` / `evidence`，但多轮消息仍会累积；`chat_completion_tools` 仍会给可见工具的 input schema | 继续使用压缩工具结果；下一步重点是按问题域裁剪可见工具，而不是恢复旧 Tool Selector。 |
| 能力工具化层 Tool Registry | 工具定义、schema、元数据 | 可能，但取决于调用方 | 中 | 当前公开给 ReAct 的是 `chat_completion_tools` 生成的函数 schema；secondary 工具只有 runtime 显式允许时可见 | 保持隐藏工具不可见；后续在 `llm_visible_registry` 之前增加问题域过滤。 |
| 多层工作记忆 Working Memory | artifacts、tool_results、execution_trace、research_notes、audit_issues | 是，但问题不在存储，而在被全量传给 LLM | 高 | 工作记忆需要保存完整 artifacts 供工具复用，但不能直接作为 prompt payload | 明确区分 `runtime_memory` 和 `llm_memory_digest`。所有 LLM role 只能读取 digest。 |
| 控制平面 Control Plane | 阶段、治理、风险确认、终止条件 | 基本没有 | 低 | 控制信息很小，通常不会造成上下文膨胀 | 保持只传阶段、风险状态和简短原因。 |

## 具体证据点

| 位置 | 现象 | 风险 |
| --- | --- | --- |
| `modules/agent/llm_digest.py` 的 digest helpers | 已提供 `audit_tool_results_digest` / `tool_results_llm_digest` | 后续新增 LLM 审计或总结时必须复用这些 digest，避免回到全量 dump |
| `modules/agent/tool_adapters/result_tools.py` 的 `read_current_results` | artifacts 包含 `current_pois`、`current_poi_h3_grid`、`current_road`、`current_population`、`current_nightlight`、`current_frontend_analysis` | 一次 `read_current_results` 就可能把完整分析 payload 进入 memory |
| `modules/agent/providers/langgraph_react.py` 的 `_react_tool_result_payload` | 工具消息回填包含压缩后的 `result.result` 和 `result.evidence` | 单轮可控，多轮仍会累积；需要继续约束工具 result 形状 |
| `modules/agent/providers/tool_loop.py` 的 `chat_completion_tools` | ReAct 工具循环使用可见工具 schema 绑定模型 | 工具数量增长时会增加固定上下文成本 |
| `modules/agent/synthesizer.py` 的 `build_synthesis_payload` | `tool_results` digest 保留完整 `result` | 如果工具 result 放入大对象，最终综合阶段也会变大 |
| `modules/agent/context_builder.py` 的 `build_context_bundle` | `context.analysis.frontend_analysis` 保存全量 frontend_analysis | 当前通过 `context_digest` 消化后传 LLM，暂时可控；但调用方若直接 dump context 会有风险 |

## 优先修复顺序

1. **先裁剪 ReAct 可见工具**
   - 根据问题类型、selected sources、map search context 和数据集需求裁剪工具 schema。
   - 保持 runtime 调用 `run_langgraph_react_loop` 的接口简单，裁剪策略放在 provider 内部。

2. **收紧 Synthesizer**
   - `synthesis_payload.tool_results` 不再传完整 `result`。
   - 只传结构化结论所需的关键指标、工具链、warnings 和证据矩阵。

3. **建立统一上下文预算**
   - 每个角色定义输入预算和允许字段。
   - 所有 LLM payload 走统一 compact/digest 层。
   - 对超长字段保留 shape、count、sample，而不是原文全量。

## 建议的角色输入边界

| 角色 | 应该看什么 | 不应该看什么 |
| --- | --- | --- |
| Gatekeeper | 问题、范围是否存在、可用结果列表 | 完整 POI、完整 grid、完整报告 |
| ReAct 初始决策 | 问题、范围 digest、artifact catalog、必要工具 schema | 无关 domain 的工具 schema、大型 snapshot |
| Auditor | 计划是否执行、证据是否覆盖、关键指标摘要、缺口 | `ToolResult.artifacts` 全量、完整 frontend_analysis、完整 POI/grid |
| Synthesizer | 审计通过的证据矩阵、关键指标、边界和建议材料 | 原始 features、完整工具 payload、重复 trace |
| Tool Loop | 当前目标、必要工具、上一步工具摘要 | 多轮完整工具输出、完整工具全集 schema |
