# PPT AI 当前架构

下面这张图按当前代码实现梳理：PPT 不是一次性让 AI 直接生成 PPTX，而是“来源与证据先收敛，再分阶段生成目录、叙事方案、指令文件和逐页内容”。来源问答是旁路 mini loop，服务用户追问，不负责生成整套 PPT。

<style scoped>
.ppt-arch{font-family:Inter,Arial,sans-serif;background:#f8fafc;border:1px solid #cbd5e1;border-radius:10px;padding:16px;color:#0f172a;max-width:1180px}
.ppt-title{font-size:20px;font-weight:800;margin-bottom:6px}
.ppt-subtitle{font-size:12px;color:#475569;margin-bottom:14px}
.ppt-grid{display:grid;grid-template-columns:1fr 1.35fr 1fr;gap:12px;align-items:start}
.ppt-col{display:flex;flex-direction:column;gap:10px}
.ppt-layer{border-radius:9px;border:1px solid #cbd5e1;background:white;padding:10px}
.ppt-layer.user{border-color:#93c5fd;background:#eff6ff}
.ppt-layer.api{border-color:#86efac;background:#f0fdf4}
.ppt-layer.ai{border-color:#c4b5fd;background:#f5f3ff}
.ppt-layer.data{border-color:#fbbf24;background:#fffbeb}
.ppt-layer.agent{border-color:#67e8f9;background:#ecfeff}
.ppt-layer-title{font-weight:800;font-size:13px;margin-bottom:8px;color:#111827}
.ppt-box{border:1px solid rgba(15,23,42,.14);background:rgba(255,255,255,.78);border-radius:7px;padding:8px;margin-top:6px;font-size:12px;line-height:1.35}
.ppt-box strong{display:block;font-size:12px;margin-bottom:2px}
.ppt-box small{display:block;color:#475569;font-size:11px}
.ppt-arrow{text-align:center;color:#64748b;font-weight:700;font-size:12px;padding:4px 0}
.ppt-pipeline{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}
.ppt-step{border:1px solid #c4b5fd;background:white;border-radius:8px;padding:8px;font-size:11px;line-height:1.3;min-height:82px}
.ppt-step strong{display:block;color:#4c1d95;margin-bottom:4px}
.ppt-note{margin-top:12px;border-left:4px solid #0ea5e9;background:#f0f9ff;padding:9px 10px;font-size:12px;color:#0f172a}
@media (max-width:960px){.ppt-grid{grid-template-columns:1fr}.ppt-pipeline{grid-template-columns:1fr 1fr}.ppt-arch{padding:12px}}
</style>
<div class="ppt-arch">
<div class="ppt-title">PPT AI 当前架构：来源驱动的分阶段生成</div>
<div class="ppt-subtitle">主线不是一次性生成 PPTX，而是先生成可审核的目录、叙事方案和逐页指令，再按页补视觉资产。</div>
<div class="ppt-grid">
<div class="ppt-col">
<div class="ppt-layer user">
<div class="ppt-layer-title">前端工作台</div>
<div class="ppt-box"><strong>PPT Planning Tab</strong><small>frontend/src/features/agent/ppt-planning-tabs.js</small><small>创建策划 PPT tab、维护来源、触发生成目录/叙事/指令/逐页页面。</small></div>
<div class="ppt-box"><strong>PptPlanningWorkbench</strong><small>frontend/src/features/ppt-planning/</small><small>来源区 + 指令文件工作区；用户选择来源、编辑生成结果、触发重生成。</small></div>
<div class="ppt-box"><strong>Context Ask</strong><small>/analysis/agent/context-ask</small><small>用户点 PPT 已选来源追问时进入来源问答链。</small></div>
</div>
<div class="ppt-arrow">请求 payload</div>
<div class="ppt-layer api">
<div class="ppt-layer-title">HTTP API 边界</div>
<div class="ppt-box"><strong>/api/v1/analysis/ppt/*</strong><small>router/domains/ppt_planning.py</small><small>sources、source-manifest、data packages、spec、narrative-plan、deck-brief、slide、visual-artifacts。</small></div>
<div class="ppt-box"><strong>/api/v1/analysis/agent/context-ask</strong><small>router/domains/agent.py</small><small>PPT 来源追问入口，转到 context_ask_service。</small></div>
</div>
</div>
<div class="ppt-col">
<div class="ppt-layer data">
<div class="ppt-layer-title">来源与证据层</div>
<div class="ppt-box"><strong>PptSource / Source Manifest</strong><small>modules/ppt_planning/schemas.py + data_tools.py</small><small>统一描述 current analysis、dataset、package、document、image、web、database source。</small></div>
<div class="ppt-box"><strong>EvidenceNode</strong><small>modules/evidence_index / evidence_retrieval</small><small>文档页、网页段落、图片解析、数据库记录、空间资料包都投影成可检索证据节点。</small></div>
<div class="ppt-box"><strong>Metric Context</strong><small>modules/ppt_planning/metric_context.py</small><small>把已选来源里的 POI、H3、人口、夜光、路网等 ready metric 压缩给 PPT LLM。</small></div>
</div>
<div class="ppt-arrow">_build_ppt_context_bundle()</div>
<div class="ppt-layer ai">
<div class="ppt-layer-title">PPT 生成 AI 主链</div>
<div class="ppt-pipeline">
<div class="ppt-step"><strong>1. Source Group</strong>classify_ppt_source_groups：把来源分组，判断材料角色。</div>
<div class="ppt-step"><strong>2. Outline</strong>generate_ppt_spec：生成目录/章节骨架。</div>
<div class="ppt-step"><strong>3. Narrative</strong>generate_narrative_plan：生成叙事节奏、证据桶、每页角色。</div>
<div class="ppt-step"><strong>4. Directive</strong>generate_deck_brief：生成 PPT 指令文件和逐页 brief。</div>
<div class="ppt-step"><strong>5. Page Assets</strong>regenerate slide / visual artifacts：逐页修补内容、生成地图/图表资产请求。</div>
</div>
<div class="ppt-box"><strong>LLM 输入</strong><small>sources + source_manifest + metric_context + evidence_context + deck_config + outline/narrative_plan</small></div>
<div class="ppt-box"><strong>LLM 输出</strong><small>PptSpecResponse、DeckNarrativePlanResponse、DeckBriefResponse、DeckSlideBrief、PptVisualArtifactResponse</small></div>
</div>
</div>
<div class="ppt-col">
<div class="ppt-layer agent">
<div class="ppt-layer-title">PPT 来源问答链</div>
<div class="ppt-box"><strong>context_ask_service</strong><small>modules/agent/context_ask_service.py</small><small>如果 target.type=ppt_sources，优先进入来源问答 mini loop。</small></div>
<div class="ppt-box"><strong>run_source_qa_loop</strong><small>modules/agent/source_qa_loop.py</small><small>只允许围绕已选 PPT 来源检索；不会访问未选来源。</small></div>
<div class="ppt-box"><strong>只读工具</strong><small>list_selected_sources、search/read_selected_source_evidence_node、list/query/aggregate/read_scope_dataset</small></div>
<div class="ppt-box"><strong>回答产物</strong><small>自然回答 + evidence + citations + warnings；不再固定四段模板。</small></div>
</div>
<div class="ppt-arrow">可进入主 Agent</div>
<div class="ppt-layer agent">
<div class="ppt-layer-title">主 Agent 关联</div>
<div class="ppt-box"><strong>selected_sources_context</strong><small>modules/agent/runtime.py</small><small>主 Agent 深度分析时可接收 PPT 已选来源上下文。</small></div>
<div class="ppt-box"><strong>证据边界</strong><small>只能通过来源工具读取 EvidenceNode；不能引用未选来源或聊天临时附件。</small></div>
</div>
</div>
</div>
<div class="ppt-note">一句话：PPT AI 的核心数据面是“已选来源 -> EvidenceNode / Metric Context -> Context Bundle”。核心生成面是“目录 -> 叙事方案 -> 指令文件 -> 逐页 brief/视觉资产”。来源问答是旁路 mini loop，服务用户追问，不负责生成整套 PPT。</div>
</div>

## 流程说明

- 前端在 PPT tab 里维护 `pptPlanningState`，用户选来源、配置页数/类型/主题，然后调用 `frontend/src/features/ppt-planning/api.js` 里的接口。
- 后端 `router/domains/ppt_planning.py` 只是 HTTP 边界，真正的编排在 `modules/ppt_planning/service.py`。
- `service.py` 每次生成前都会构建 `_build_ppt_context_bundle()`，把 `sources`、`source_manifest`、`metric_context`、`evidence_context` 压缩成 LLM 可用上下文。
- 生成不是一步到位：`generate_ppt_spec()` 先出目录，`generate_narrative_plan()` 出叙事方案，`generate_deck_brief()` 出整套 PPT 指令文件，`regenerate_deck_brief_slide()` 可逐页重生成，`generate_visual_artifacts_for_slide()` 处理图表、地图快照等视觉资产请求。
- 用户问“这个来源说明什么 / 下一步怎么分析”时，不走 PPT 生成主链，而是 `context_ask_service -> run_source_qa_loop`，只读已选来源和当前范围数据。
