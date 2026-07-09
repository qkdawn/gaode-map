# AI 分析快速模式与深度模式架构图

当前 AI 分析有两条主链路：**快速模式**用于围绕当前分析范围、已选来源和已有结果做低成本问答；**深度模式**用于主 Agent 多轮工具循环，适合需要补证据、查范围数据、调用 ESRI 方法论或生成更完整结论的分析任务。

<style scoped>
.ai-arch{font-family:Inter,"Segoe UI",Arial,"Microsoft YaHei",sans-serif;color:#172033;background:#f8fafc;border:1px solid #d8e0ea;border-radius:12px;padding:18px;margin:18px 0}
.ai-title{font-size:20px;font-weight:800;letter-spacing:0;margin-bottom:6px;color:#0f172a}
.ai-subtitle{font-size:13px;color:#526173;margin-bottom:16px;line-height:1.6}
.ai-shared{background:#eef6ff;border:1px solid #b9d7f5;border-radius:10px;padding:12px;margin-bottom:14px}
.ai-shared-title{font-size:14px;font-weight:800;color:#164e80;margin-bottom:10px}
.ai-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px}
.ai-grid-2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.ai-col{background:#ffffff;border:1px solid #d8e0ea;border-radius:10px;padding:12px}
.ai-col.quick{border-top:5px solid #0ea5a3}
.ai-col.deep{border-top:5px solid #6366f1}
.ai-col-title{font-size:16px;font-weight:850;margin-bottom:4px;color:#111827}
.ai-col-desc{font-size:12px;line-height:1.55;color:#64748b;margin-bottom:12px}
.ai-stage{border:1px solid #dbe4ef;border-radius:8px;background:#fbfdff;padding:10px;margin-bottom:10px}
.ai-stage:last-child{margin-bottom:0}
.ai-stage-title{font-size:13px;font-weight:800;color:#1f2937;margin-bottom:6px}
.ai-stage small,.ai-box small{display:block;font-size:11px;line-height:1.45;color:#64748b;margin-top:3px}
.ai-flow{font-size:11px;font-weight:800;color:#64748b;text-align:center;margin:-4px 0 6px 0}
.ai-box{background:#ffffff;border:1px solid #e2e8f0;border-radius:7px;padding:8px;min-height:58px}
.ai-box strong{display:block;font-size:12px;color:#111827;margin-bottom:2px}
.ai-box.highlight{background:#ecfdf5;border-color:#7dd3fc}
.ai-box.warn{background:#fff7ed;border-color:#fed7aa}
.ai-box.deepmark{background:#eef2ff;border-color:#c7d2fe}
.ai-box.guard{background:#fef2f2;border-color:#fecaca}
.ai-box.output{background:#f0fdf4;border-color:#bbf7d0}
.ai-mini-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:8px}
.ai-tools{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:8px}
.ai-pill{font-size:11px;line-height:1.35;background:#f1f5f9;border:1px solid #dbe4ef;border-radius:999px;padding:6px 8px;color:#334155;text-align:center}
.ai-loop{border:1px dashed #a5b4fc;border-radius:8px;background:#f5f7ff;padding:9px;margin-top:8px}
.ai-loop-title{font-size:12px;font-weight:800;color:#3730a3;margin-bottom:6px}
.ai-loop-row{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.ai-node{font-size:11px;background:#ffffff;border:1px solid #c7d2fe;border-radius:7px;padding:6px 8px;color:#312e81}
.ai-arrow{font-size:12px;color:#64748b;font-weight:800}
@media(max-width:900px){.ai-grid,.ai-grid-2,.ai-tools{grid-template-columns:1fr}.ai-mini-grid{grid-template-columns:1fr}}
</style>
<div class="ai-arch">
<div class="ai-title">当前 AI 分析双链路总图</div>
<div class="ai-subtitle">同一个分析工作台输入，按用户选择分流：快速追问进入 context-ask；深度模式进入主 Agent 流式循环。快速模式直接传递前后端整理好的轻量上下文，不做模型工具循环；深度模式始终开放受控工具循环，已选来源只作为 EvidenceNode 检索源。</div>
<div class="ai-shared">
<div class="ai-shared-title">共享输入层：来自 /analysis 工作台</div>
<div class="ai-grid">
<div class="ai-box"><strong>用户问题</strong><small>分析面板输入框、选中的上下文追问、PPT/来源追问。</small></div>
<div class="ai-box"><strong>analysis snapshot</strong><small>当前范围、地图状态、指标摘要、已生成分析结果。</small></div>
<div class="ai-box"><strong>selected sources</strong><small>用户当前选中的文档、网页、图片、项目成果或 PPT 数据包来源。</small></div>
<div class="ai-box"><strong>scope datasets</strong><small>当前范围数据集，可被 query / aggregate / read 工具读取。</small></div>
<div class="ai-box"><strong>visual snapshots</strong><small>深度模式可用的地图、图层、可视化快照上下文。</small></div>
</div>
</div>
<div class="ai-grid-2">
<div class="ai-col quick">
<div class="ai-col-title">快速模式 Quick Analysis</div>
<div class="ai-col-desc">目标是快速回答“这个结果/来源说明什么、当前范围有什么、能否简单比较”。它只做确定性预处理和一次 LLM JSON 调用；不适合长链路规划和跨来源深挖。</div>
<div class="ai-stage">
<div class="ai-stage-title">1 Frontend 分流</div>
<div class="ai-box highlight"><strong>submitAgentAnalysisQuickAsk</strong><small>frontend/src/features/agent/analysis-ask.js</small><small>当处于 analysis workspace 且不是 deep mode 时触发。</small></div>
</div>
<div class="ai-flow">↓</div>
<div class="ai-stage">
<div class="ai-stage-title">2 API 入口</div>
<div class="ai-box"><strong>POST /api/v1/analysis/agent/context-ask</strong><small>router/domains/agent.py</small><small>统一进入 `answer_context_ask(payload)`。</small></div>
</div>
<div class="ai-flow">↓</div>
<div class="ai-stage">
<div class="ai-stage-title">3 Direct Context Ask</div>
<div class="ai-box"><strong>answer_context_ask</strong><small>modules/agent/context_ask_service.py</small><small>校验问题、准备 target / snapshot / selected sources 的紧凑上下文。</small></div>
</div>
<div class="ai-flow">↓</div>
<div class="ai-stage">
<div class="ai-stage-title">4 轻量上下文包</div>
<div class="ai-box highlight"><strong>_build_user_payload</strong><small>modules/agent/context_ask_service.py</small><small>把问题、target、analysis snapshot、selected sources summary 和 scoped dataset context 合成一次性输入包。</small></div>
<div class="ai-tools">
<div class="ai-pill">_compact_target</div>
<div class="ai-pill">_compact_snapshot</div>
<div class="ai-pill">_compact_selected_sources</div>
<div class="ai-pill">build_scoped_dataset_context</div>
<div class="ai-pill">compact_value</div>
<div class="ai-pill">compact_evidence_nodes</div>
</div>
</div>
<div class="ai-flow">↓</div>
<div class="ai-stage">
<div class="ai-stage-title">5 一次 LLM JSON 调用</div>
<div class="ai-box warn"><strong>client.chat_json</strong><small>phase = context_ask</small><small>模型只看到预处理包和快速模式 prompt，不看到工具 schema，也不会进入 ReAct 循环。</small></div>
</div>
<div class="ai-flow">↓</div>
<div class="ai-stage">
<div class="ai-stage-title">6 快速输出</div>
<div class="ai-box output"><strong>answer + evidence + citations + warnings</strong><small>直接返回前端，用于当前面板问答、来源解释和轻量复盘。</small></div>
</div>
</div>
<div class="ai-col deep">
<div class="ai-col-title">深度模式 Deep Analysis</div>
<div class="ai-col-desc">目标是完成更完整的分析任务：先判断问题是否可答，再多轮调用工具补证据，最后经过规则审计和最终 LLM 综合输出。</div>
<div class="ai-stage">
<div class="ai-stage-title">1 Frontend 深度模式</div>
<div class="ai-box deepmark"><strong>composer mode = deep</strong><small>frontend/src/features/agent/runtime.js</small><small>深度模式请求进入主 Agent 流式接口。</small></div>
</div>
<div class="ai-flow">↓</div>
<div class="ai-stage">
<div class="ai-stage-title">2 API 入口</div>
<div class="ai-box"><strong>POST /api/v1/analysis/agent/main-loop/stream</strong><small>router/domains/agent.py</small><small>`stream_main_agent_loop(payload)` 启动流式主循环。</small></div>
</div>
<div class="ai-flow">↓</div>
<div class="ai-stage">
<div class="ai-stage-title">3 Context Assembly</div>
<div class="ai-box"><strong>build_context_bundle(snapshot)</strong><small>modules/agent/runtime.py</small><small>汇总分析快照、frontend_map_search_context、selected_sources_context、visual_snapshots，并写入 memory/context。</small></div>
</div>
<div class="ai-flow">↓</div>
<div class="ai-stage">
<div class="ai-stage-title">4 Gate 判断</div>
<div class="ai-box guard"><strong>run_gate_with_llm</strong><small>判断继续、澄清或阻断。</small><small>用于守住输入边界、证据缺口和不可答场景。</small></div>
</div>
<div class="ai-flow">↓ continue</div>
<div class="ai-stage">
<div class="ai-stage-title">5 LangGraph ReAct Tool Loop</div>
<div class="ai-box deepmark"><strong>run_langgraph_react_loop</strong><small>modules/agent/providers/langgraph_react.py</small><small>模型通过 bind_tools 看到工具 schema，按需要发起工具调用。</small></div>
<div class="ai-loop">
<div class="ai-loop-title">循环节点</div>
<div class="ai-loop-row"><span class="ai-node">preflight</span><span class="ai-arrow">→</span><span class="ai-node">think</span><span class="ai-arrow">→</span><span class="ai-node">act_tools</span><span class="ai-arrow">→</span><span class="ai-node">assess</span><span class="ai-arrow">↺</span><span class="ai-node">finalize</span></div>
</div>
<div class="ai-mini-grid">
<div class="ai-box"><strong>当前范围工具</strong><small>read_current_scope、read_current_results、list/query/aggregate/read scope datasets。</small></div>
<div class="ai-box"><strong>证据检索工具</strong><small>selected source、analysis context、report context 的 search/read 工具。</small></div>
<div class="ai-box"><strong>ESRI 方法工具</strong><small>plan_business_analyst_analysis 用于规划商业地理分析路径。</small></div>
<div class="ai-box"><strong>执行器</strong><small>execute_tool_call_step 负责落地每次工具调用并回写 observation。</small></div>
</div>
</div>
<div class="ai-flow">↓</div>
<div class="ai-stage">
<div class="ai-stage-title">6 Audit + Evidence Pack</div>
<div class="ai-mini-grid">
<div class="ai-box guard"><strong>audit_execution</strong><small>规则审查工具结果、缺失证据、问题边界和回答风险。</small></div>
<div class="ai-box"><strong>build_finalizer_evidence_pack</strong><small>把工具结果、证据节点和审计信息整理成最终回答证据包。</small></div>
</div>
</div>
<div class="ai-flow">↓</div>
<div class="ai-stage">
<div class="ai-stage-title">7 Finalizer LLM</div>
<div class="ai-box output"><strong>generate_answer_output_with_llm</strong><small>modules/agent/providers/llm_provider.py</small><small>输入 messages、context_digest、answer_evidence_payload 和可选视觉快照，生成最终自然语言回答。</small></div>
</div>
<div class="ai-flow">↓</div>
<div class="ai-stage">
<div class="ai-stage-title">8 深度输出</div>
<div class="ai-box output"><strong>streamed answer + diagnostics + timeline + session</strong><small>流式返回前端，可展示思考轨迹、工具观察、引用、缺口和最终建议，并沉淀到会话。</small></div>
</div>
</div>
</div>
</div>

## 两种模式的核心区别

| 维度 | 快速模式 Quick Analysis | 深度模式 Deep Analysis |
|---|---|---|
| 主要用途 | 快速解释已选来源、当前范围、已有分析结果 | 多轮补证据、规划分析路径、综合判断和生成完整结论 |
| 前端触发 | analysis workspace 非 deep mode 的 quick ask | composer mode = `deep` |
| API 入口 | `POST /api/v1/analysis/agent/context-ask` | `POST /api/v1/analysis/agent/main-loop/stream` |
| 后端入口 | `answer_context_ask` | `stream_main_agent_loop` / `_run_main_agent_loop` |
| 上下文形态 | target、snapshot、selected sources、scope datasets 的一次性预处理包 | `build_context_bundle` 形成完整 context/memory，并追加地图检索、已选来源、可视化快照 |
| 工具循环 | 无；只做确定性 scoped dataset 预处理 | `run_langgraph_react_loop`，preflight / think / act_tools / assess / finalize |
| 工具范围 | 不向模型暴露工具 schema；后端可预聚合当前范围数据 | 当前范围、分析结果、ESRI 规划、已选来源、分析上下文、报告上下文、范围数据工具 |
| 风险控制 | 来源边界、当前范围边界、紧凑上下文和 prompt 约束 | gate 澄清/阻断、工具 registry、执行审计、finalizer evidence pack |
| 输出形态 | `answer`、`evidence`、`citations`、`warnings` | 流式回答、诊断、工具轨迹、证据包、审计结果、会话沉淀 |
| 成本和延迟 | 低成本、低延迟，适合随手问 | 成本和延迟更高，适合正式分析和复盘 |

## 深度模式工具注册关系

深度模式不是模型直接访问数据库或文件系统，而是通过工具 schema 调用受控工具。`get_tool_registry()` 提供工具目录，`chat_completion_tools(registry, include_secondary=...)` 转成模型可见 schema，`ChatOpenAI(...).bind_tools(tool_schemas)` 让模型在 ReAct 循环里选择工具，最终由 `execute_tool_call_step` 执行。

| 工具组 | 典型工具 | 用途 |
|---|---|---|
| 当前分析状态 | `read_current_scope`、`read_current_results` | 读取当前范围、已有指标和分析结果 |
| ESRI 方法论 | `plan_business_analyst_analysis` | 根据问题规划商业地理分析模型、证据需求和边界 |
| 已选来源 RAG | `list_selected_sources`、`search_selected_source_evidence`、`read_selected_source_evidence_node` | 在用户已选来源内召回和读取证据 |
| 分析成果 RAG | `search_analysis_context`、`read_analysis_evidence_node` | 读取当前项目已保存的分析产物和结构化 EvidenceNode |
| 报告上下文 RAG | `search_report_context`、`read_report_evidence_node` | 读取报告/PPT 相关证据节点 |
| 当前范围数据 | `list_scope_datasets`、`query_scope_dataset`、`aggregate_scope_dataset`、`read_scope_record` | 查询、聚合和读取当前范围内的数据记录 |

## 代码位置速查

| 模块 | 文件 | 说明 |
|---|---|---|
| 快速前端提交 | `frontend/src/features/agent/analysis-ask.js` | `submitAgentAnalysisQuickAsk` 构造快速问答请求 |
| 快速 API | `router/domains/agent.py` | `/api/v1/analysis/agent/context-ask` |
| 快速编排 | `modules/agent/context_ask_service.py` | `answer_context_ask` 构造预处理包并一次调用 LLM |
| 快速范围数据预处理 | `modules/agent/context_ask_datasets.py` | `build_scoped_dataset_context` 读取、聚合和压缩当前范围数据 |
| 深度前端请求 | `frontend/src/features/agent/main-loop-request.js` | 主 Agent 流式请求地址 |
| 深度 API | `router/domains/agent.py` | `/api/v1/analysis/agent/main-loop/stream` |
| 深度编排 | `modules/agent/runtime.py` | context bundle、gate、tool loop、audit、finalizer 总编排 |
| 深度工具循环 | `modules/agent/providers/langgraph_react.py` | `run_langgraph_react_loop` |
| 深度审计 | `modules/agent/auditor.py` | `audit_execution` |
| 最终证据包 | `modules/agent/finalizer_evidence.py` | `build_finalizer_evidence_pack` |
| 最终回答 | `modules/agent/providers/llm_provider.py` | `generate_answer_output_with_llm` |

## 读图口径

- 快速模式是“直接上下文问答链”：后端先把已选来源、分析快照和当前范围数据压成预处理包，再一次性传给 LLM。
- 深度模式是“主 Agent 工具循环链”：先组装完整上下文并过 gate，再由模型在受控工具 registry 中选择工具，多轮执行后做审计和最终综合。带已选来源也不会走快速直答短路。
- 两者都不是让模型直接读所有数据；快速模式模型只看到预处理包，深度模式模型看到受控工具 schema、工具 observation 和最终证据包。
- 快速模式强调低延迟和边界清楚；深度模式强调证据完整度、执行轨迹和最终结论质量。
