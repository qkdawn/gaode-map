# Agent 角色上下文膨胀分析

本文按当前 Agent 角色检查每个 LLM / 工具阶段塞入的上下文，重点判断是否存在不必要的全量上下文导致 prompt 过大。结论基于当前代码结构。

## 总体结论

当前最容易触发上下文超限的是 **Auditor**。它会把 `memory.tool_results` 全量 `model_dump` 后传给 LLM，而 `ToolResult` 内包含 `artifacts` 字段；部分工具会把完整 POI、H3 grid、路网、人口、夜光、frontend_analysis 都放进 artifacts，导致审计阶段一次性吃进大量结构化数据。

其次需要关注 **GIS Agent 工具调度器 / Tool Loop** 和 **Synthesizer**。Tool Loop 的工具回填会把 `result` 和 `evidence` 原样塞回模型消息；Synthesizer 虽然做了 digest，但仍可能把工具 `result` 原样带入最终生成阶段。

## 逐角色分析

| 角色 | 当前塞入上下文 | 是否可能塞了不必要的全量上下文 | 风险等级 | 主要问题 | 建议 |
| --- | --- | --- | --- | --- | --- |
| 门卫节点 Gatekeeper | 最近消息、latest user message、`snapshot_digest`、`context_summary`、可用 artifact 名称 | 基本没有 | 低 | `snapshot_digest` 已经只保留范围、摘要、计数和少量 filters；适合门卫判断 | 保持 digest 输入即可。门卫不需要完整 POI、H3 grid、frontend_analysis。 |
| 工具文档搜索员 Context Retriever | 当前 snapshot、artifacts、frontend_analysis、附件/知识片段 | 有潜在风险，但主要发生在它产出的 context 被后续角色使用时 | 中 | `build_context_bundle` 会把 `snapshot.frontend_analysis` 全量放入 `context.analysis`，虽然后续 `context_digest` 对它只取 keys，但内存中的 bundle 本身仍是全量 | ContextBundle 内部可以保留完整对象，但传给 LLM 必须统一走 digest。避免新增角色直接传 `context.model_dump()`。 |
| 规划师 Planner | 最近消息、问题类型、`snapshot_digest`、`context_digest`、`context_summary`、`artifact_digest`、可用 artifact 名称、audit feedback | 基本没有 | 低 | Planner 输入主要是 digest；`artifact_digest` 只列 readiness、key、artifact 名称，不传 artifact 内容 | 继续保持 Planner 只看证据目标和 readiness。不要让 Planner 直接看 `memory.artifacts` 全量。 |
| 工具选择 Agent Tool Selector | 最近消息、Planner 意图、`snapshot_digest`、`artifact_digest`、`compact_tool_catalog`、工具路由提示、fallback step hints、audit feedback | 基本没有 | 低到中 | 工具目录使用 compact 版本，风险可控；但如果工具数量持续增长，`tool_routing_hints` 和 catalog 会变长 | 按问题类型过滤工具目录，只给相关 domain / scenario 工具，不必每次给全部 primary 工具。 |
| 工具执行器 Executor | PlanStep、snapshot、memory.artifacts、工具参数 | 不属于 LLM prompt，但会产生过大的 memory | 中 | 执行器会把工具结果完整追加到 `memory.tool_results`，并把 `result.artifacts` 合并到 `memory.artifacts`；这本身合理，但后续如果全量传给 LLM 就危险 | 保留执行期全量 artifacts 可以，但需要增加专门的 `llm_digest` 或 `audit_digest`，禁止后续 LLM 直接 dump ToolResult 全量。 |
| 审计员 Auditor | question、`snapshot_digest`、`context_digest`、plan、`memory.tool_results` 全量、`memory.execution_trace`、artifact 名称、rule audit、replan count | 是，且是当前最高风险点 | 高 | `memory.tool_results` 全量包含 `ToolResult.artifacts`。`read_current_results` 这类工具会把 `current_pois`、`current_poi_h3_grid`、`current_road`、`current_population`、`current_nightlight`、`current_frontend_analysis` 放进 artifacts。审计只需要证据覆盖状态、关键摘要、缺口和工具状态，不需要完整 features/grid/payload | 把 Auditor 输入改为 `tool_result_digest`：仅保留 tool_name、status、result 摘要、evidence 前 N 条、warnings、artifact keys、artifact shape。不要传 `artifacts` 内容。必要时只给场景 pack 的 report-level summary。 |
| 综合分析师 Synthesizer | 最近消息、`snapshot_digest`、`context_digest`、`synthesis_payload` | 部分可能 | 中 | `synthesis_payload` 已经结构化，但 `tool_results` 里仍把每个工具的 `result` 原样放入；如果某些工具把大对象放在 result 而不是 artifacts，也会膨胀 | Synthesizer 只需要最终 decision/support/evidence_matrix/actions/boundary。`tool_results` 建议保留摘要字符串或关键字段白名单，不传完整 result。 |
| GIS Agent 工具调度器 Tool Loop | 初始 digest、完整工具 schema、每轮 assistant/tool 消息、`tool_output_payload(result)` | 是，尤其多轮工具调用时 | 高 | `tool_output_payload` 把 `result.result` 和 `result.evidence` 原样塞回对话。虽然没传 `artifacts`，但 result/evidence 如果大，多轮叠加会快速膨胀；另外 `tool_catalog` 会给完整工具 schema | 改成 `tool_output_digest`：只返回工具摘要、关键指标、warnings、artifact keys、必要证据样本。工具 schema 也应按场景过滤，并优先用 compact catalog 做选择。 |
| 能力工具化层 Tool Registry | 工具定义、schema、元数据 | 可能，但取决于调用方 | 中 | `compact_tool_catalog` 风险低；`tool_catalog` / `chat_completion_tools` 会暴露完整 input_schema，工具多后会变大 | Tool Selector 用 compact catalog；ReAct 工具调用用按问题类型裁剪后的 tools。隐藏 secondary 工具是对的，但还可以进一步按 route 裁剪 primary 工具。 |
| 多层工作记忆 Working Memory | artifacts、tool_results、execution_trace、research_notes、audit_issues | 是，但问题不在存储，而在被全量传给 LLM | 高 | 工作记忆需要保存完整 artifacts 供工具复用，但不能直接作为 prompt payload | 明确区分 `runtime_memory` 和 `llm_memory_digest`。所有 LLM role 只能读取 digest。 |
| 控制平面 Control Plane | 阶段、治理、风险确认、终止条件 | 基本没有 | 低 | 控制信息很小，通常不会造成上下文膨胀 | 保持只传阶段、风险状态和简短原因。 |

## 具体证据点

| 位置 | 现象 | 风险 |
| --- | --- | --- |
| `modules/agent/providers/llm_provider.py` 的 `audit_with_llm` | Auditor payload 中传入 `[item.model_dump(mode="json") for item in memory.tool_results]` | 会把 `ToolResult.artifacts` 全量传给审计员 |
| `modules/agent/tool_adapters/result_tools.py` 的 `read_current_results` | artifacts 包含 `current_pois`、`current_poi_h3_grid`、`current_road`、`current_population`、`current_nightlight`、`current_frontend_analysis` | 一次 `read_current_results` 就可能把完整分析 payload 进入 memory |
| `modules/agent/providers/tool_loop.py` 的 `tool_output_payload` | 工具消息回填包含完整 `result.result` 和 `result.evidence` | 多轮工具调用时 prompt 会线性甚至超线性膨胀 |
| `modules/agent/providers/llm_provider.py` 的 `run_llm_tool_loop` | 初始工具循环使用 `tool_catalog(...)` 给模型完整工具 schema | 工具数量增长时会增加固定上下文成本 |
| `modules/agent/synthesizer.py` 的 `build_synthesis_payload` | `tool_results` digest 保留完整 `result` | 如果工具 result 放入大对象，最终综合阶段也会变大 |
| `modules/agent/context_builder.py` 的 `build_context_bundle` | `context.analysis.frontend_analysis` 保存全量 frontend_analysis | 当前通过 `context_digest` 消化后传 LLM，暂时可控；但调用方若直接 dump context 会有风险 |

## 优先修复顺序

1. **先修 Auditor**
   - 新增 `audit_tool_result_digest(result)`。
   - Auditor payload 只传 `tool_name`、`status`、`result_summary`、`evidence_sample`、`warning_count`、`artifact_keys`、`artifact_shapes`。
   - 禁止传 `ToolResult.artifacts` 内容。

2. **再修 Tool Loop**
   - 新增 `tool_output_digest(result)` 替代 `tool_output_payload(result)`。
   - 每个工具回填给 LLM 的内容加长度和列表数量上限。
   - 对 read/search 类工具保留命中摘要，不回填完整 chunk / 大 payload。

3. **收紧 Synthesizer**
   - `synthesis_payload.tool_results` 不再传完整 `result`。
   - 只传结构化结论所需的关键指标、工具链、warnings 和证据矩阵。

4. **建立统一上下文预算**
   - 每个角色定义输入预算和允许字段。
   - 所有 LLM payload 走统一 compact/digest 层。
   - 对超长字段保留 shape、count、sample，而不是原文全量。

## 建议的角色输入边界

| 角色 | 应该看什么 | 不应该看什么 |
| --- | --- | --- |
| Gatekeeper | 问题、范围是否存在、可用结果列表 | 完整 POI、完整 grid、完整报告 |
| Planner | 问题类型、readiness、证据缺口、artifact 名称 | 完整工具结果、完整 artifacts |
| Tool Selector | Planner 意图、相关工具 compact catalog、依赖状态 | 无关 domain 的工具 schema、大型 snapshot |
| Auditor | 计划是否执行、证据是否覆盖、关键指标摘要、缺口 | `ToolResult.artifacts` 全量、完整 frontend_analysis、完整 POI/grid |
| Synthesizer | 审计通过的证据矩阵、关键指标、边界和建议材料 | 原始 features、完整工具 payload、重复 trace |
| Tool Loop | 当前目标、必要工具、上一步工具摘要 | 多轮完整工具输出、完整工具全集 schema |
