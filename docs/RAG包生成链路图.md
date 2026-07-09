# RAG 包生成链路图

这张图把经典 RAG 流程和当前 `/analysis` 的真实实现对齐。读图顺序按标准 RAG 阶段走：**Ingest -> Parse/Chunk -> Index -> Retrieve/Recall -> Rerank -> Read/Hydrate -> Context Pack -> LLM**。每一层同时标明当前项目基于什么输入、做什么处理、生成哪个包。

<style scoped>
.rag-arch{font-family:Inter,"Microsoft YaHei",Arial,sans-serif;background:#f8fafc;border:1px solid #cbd5e1;border-radius:10px;padding:16px;color:#0f172a;max-width:1320px}
.rag-title{font-size:22px;font-weight:800;text-align:center;margin-bottom:4px;color:#0f172a}
.rag-subtitle{text-align:center;font-size:12px;color:#475569;margin-bottom:14px}
.rag-layer{border:1px solid #cbd5e1;border-radius:9px;background:#fff;padding:10px;margin-top:10px}
.rag-layer.raw{background:#f8fbff;border-color:#93c5fd}
.rag-layer.ingest{background:#f0fdf4;border-color:#86efac}
.rag-layer.parse{background:#ecfeff;border-color:#67e8f9}
.rag-layer.index{background:#faf5ff;border-color:#c4b5fd}
.rag-layer.retrieve{background:#fff7ed;border-color:#fdba74}
.rag-layer.rerank{background:#fffbeb;border-color:#facc15}
.rag-layer.read{background:#f0f9ff;border-color:#7dd3fc}
.rag-layer.pack{background:#fdf2f8;border-color:#f9a8d4}
.rag-layer.consume{background:#f5f3ff;border-color:#a78bfa}
.rag-layer-title{font-size:14px;font-weight:800;margin-bottom:8px}
.rag-grid{display:grid;gap:8px}
.rag-grid-2{grid-template-columns:repeat(2,1fr)}
.rag-grid-3{grid-template-columns:repeat(3,1fr)}
.rag-grid-4{grid-template-columns:repeat(4,1fr)}
.rag-grid-5{grid-template-columns:repeat(5,1fr)}
.rag-box{border:1px solid rgba(15,23,42,.14);background:rgba(255,255,255,.84);border-radius:7px;padding:8px;min-height:72px;font-size:12px;line-height:1.35}
.rag-box strong{display:block;font-size:12px;margin-bottom:3px;color:#111827}
.rag-box small{display:block;color:#475569;font-size:11px;margin-top:2px}
.rag-box.highlight{border-color:#2563eb;background:#eff6ff}
.rag-box.package{border-color:#16a34a;background:#f0fdf4}
.rag-box.warn{border-color:#f97316;background:#fff7ed}
.rag-box.light{border-color:#d97706;background:#fffbeb}
.rag-arrow{text-align:center;color:#64748b;font-weight:800;font-size:13px;padding:5px 0 0}
.rag-flow{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;align-items:stretch}
.rag-step{border:1px solid #d1d5db;border-radius:8px;background:white;padding:9px;font-size:12px;line-height:1.35}
.rag-step strong{display:block;color:#0f172a;margin-bottom:4px}
.rag-step b{color:#0369a1}
.rag-note{margin-top:12px;border-left:4px solid #2563eb;background:#eff6ff;padding:9px 10px;font-size:12px;color:#0f172a}
@media (max-width:980px){.rag-grid-5,.rag-grid-4,.rag-grid-3,.rag-flow{grid-template-columns:1fr 1fr}.rag-grid-2{grid-template-columns:1fr}.rag-arch{padding:12px}}
@media (max-width:640px){.rag-grid-5,.rag-grid-4,.rag-grid-3,.rag-flow{grid-template-columns:1fr}}
</style>
<div class="rag-arch">
<div class="rag-title">RAG Evidence Pipeline：经典步骤与当前实现映射</div>
<div class="rag-subtitle">当前系统不是单一向量库 RAG，而是多来源 native index + Source Manifest + Evidence Pack + Metric Context + Visual/Data Package。</div>
<div class="rag-layer raw">
<div class="rag-layer-title">1. Raw Sources 原始来源</div>
<div class="rag-grid rag-grid-5">
<div class="rag-box"><strong>文档 / PDF / PPTX</strong>用户上传项目资料<small>项目说明、服务建议书、已有成果、政策文本</small></div>
<div class="rag-box"><strong>图片 / 照片</strong>用户上传或地图截图<small>现场照片、规划图、效果图、已有页面截图</small></div>
<div class="rag-box"><strong>网页 / Web</strong>SearXNG 搜索或 URL<small>政策、案例、竞品、商圈背景</small></div>
<div class="rag-box"><strong>分析结果 / 成果包</strong>analysis snapshot / history / artifact<small>POI、H3、人口、夜光、路网、当前项目成果包</small></div>
<div class="rag-box"><strong>当前范围数据源</strong>history_id 下的明细数据<small>POI 列表、H3 cell、人口 cell、夜光 cell、路网 feature</small></div>
</div>
</div>
<div class="rag-arrow">↓ Ingest & Normalize：接入、清洗、坐标/年份/来源归一</div>
<div class="rag-layer ingest">
<div class="rag-layer-title">2. Ingest & Normalize 来源接入与归一</div>
<div class="rag-flow">
<div class="rag-step"><strong>Document Ingest</strong><b>基于：</b>上传文件<br><b>处理：</b>保存文档、解析状态、文件元数据<br><b>生成：</b>document source seed</div>
<div class="rag-step"><strong>Web Ingest</strong><b>基于：</b>搜索词或 URL<br><b>处理：</b>SearXNG 检索、Crawl4AI 抓取 Markdown、记录 URL<br><b>生成：</b>web source seed</div>
<div class="rag-step"><strong>Image Ingest</strong><b>基于：</b>图片/截图<br><b>处理：</b>登记 asset、caption、locator、后续 OCR/视觉索引 contract<br><b>生成：</b>image source seed</div>
<div class="rag-step"><strong>Analysis Ingest</strong><b>基于：</b>snapshot / artifacts<br><b>处理：</b>提取摘要、年份、data_version、scope_fingerprint<br><b>生成：</b>current analysis / 当前项目成果包 seed</div>
<div class="rag-step"><strong>Scope Dataset Ingest</strong><b>基于：</b>poi_results / analysis_artifacts<br><b>处理：</b>按 history_id 限定范围，收敛白名单字段<br><b>生成：</b>scope dataset source seed</div>
<div class="rag-step"><strong>Package Ingest</strong><b>基于：</b>已选来源 + 资料意图<br><b>处理：</b>创建 POI 样例、夜生活、空间载体资料包请求<br><b>生成：</b>ppt_data_package seed</div>
</div>
</div>
<div class="rag-arrow">↓ Parse / Chunk / Node Build：切分、节点化、结构化</div>
<div class="rag-layer parse">
<div class="rag-layer-title">3. Parse / Chunk / Node Build 解析、切片与节点构建</div>
<div class="rag-grid rag-grid-3">
<div class="rag-box highlight"><strong>Docling -> PageIndex</strong><small>基于：document source seed</small><small>生成：document_blocks、document_index_nodes、页码/章节 locator</small></div>
<div class="rag-box highlight"><strong>Crawl4AI -> markdown chunks</strong><small>基于：web source seed</small><small>生成：web evidence nodes、URL、domain、抓取诊断</small></div>
<div class="rag-box highlight"><strong>ImageVisualIndex contract</strong><small>基于：image source seed</small><small>生成：OCR/caption/asset nodes 目标形态；当前保留图片 asset 和投影节点</small></div>
<div class="rag-box highlight"><strong>scope_datasets records</strong><small>基于：当前范围数据源</small><small>生成：query/aggregate/read 可访问的 POI、cell、road records</small></div>
<div class="rag-box highlight"><strong>history/artifact/summary nodes</strong><small>基于：当前项目成果包</small><small>生成：structured EvidenceNode、summary node、年份/版本 metadata</small></div>
<div class="rag-box highlight"><strong>ppt_data_package nodes</strong><small>基于：资料包请求</small><small>生成：items、groups、carriers、evidence_refs、package nodes</small></div>
</div>
</div>
<div class="rag-arrow">↓ Index & Source Registry：建立索引登记和可检索边界</div>
<div class="rag-layer index">
<div class="rag-layer-title">4. Index & Source Registry 索引与来源登记</div>
<div class="rag-grid rag-grid-4">
<div class="rag-box package"><strong>PptSource</strong><small>基于：标准化来源和节点预览</small><small>生成：id、title、status、source_kind、summary、evidence_count、meta.aiPayload</small></div>
<div class="rag-box package"><strong>source_index_manifest</strong><small>基于：native index 状态</small><small>生成：pageindex / webpage_index / image_visual_index / database_record_index / spatial_package_index</small></div>
<div class="rag-box package"><strong>selected_sources_context</strong><small>基于：用户本轮已选来源</small><small>生成：Agent 本轮 source guard，只允许检索已选来源</small></div>
<div class="rag-box package"><strong>native indexes</strong><small>基于：各来源自己的结构</small><small>生成：PageIndex、payload index、scope dataset index、package index</small></div>
</div>
</div>
<div class="rag-arrow">↓ Retrieve / Recall：从已选来源或运行时上下文召回候选证据</div>
<div class="rag-layer retrieve">
<div class="rag-layer-title">5. Retrieve / Recall 召回候选证据</div>
<div class="rag-grid rag-grid-3">
<div class="rag-box"><strong>EvidenceIndexService.search</strong><small>基于：EvidenceSearchQuery + SourceRecord</small><small>处理：registry 选择 adapter，adapter.recall 返回 EvidenceIndexRecord</small></div>
<div class="rag-box"><strong>adapter recall</strong><small>基于：native_index_kind</small><small>处理：DocumentPageIndex、WebPage、ImageVisual、DatabaseRecord、SpatialPackage adapter 各自召回</small></div>
<div class="rag-box"><strong>rank_chunks</strong><small>基于：RuntimeKnowledgeIndex chunks</small><small>处理：BM25-like token scoring，用于当前 analysis/report runtime context</small></div>
<div class="rag-box"><strong>scope dataset query</strong><small>基于：history_id + source_id + filters</small><small>处理：query_scope_dataset / aggregate_scope_dataset / read_scope_record</small></div>
<div class="rag-box"><strong>selected source tools</strong><small>基于：selected_sources_context</small><small>处理：search_selected_source_evidence 只查本轮已选来源</small></div>
<div class="rag-box"><strong>analysis/report tools</strong><small>基于：运行时上下文</small><small>处理：search_analysis_context / search_report_context 召回上下文节点</small></div>
</div>
</div>
<div class="rag-arrow">↓ Rerank / Filter / Guard：排序、过滤、边界约束</div>
<div class="rag-layer rerank">
<div class="rag-layer-title">6. Rerank / Filter / Guard 重排、过滤与保护</div>
<div class="rag-grid rag-grid-4">
<div class="rag-box light"><strong>score sort</strong><small>基于：adapter recall score / rank_chunks score</small><small>当前：按 score 降序排序</small></div>
<div class="rag-box light"><strong>top_k limit</strong><small>基于：query.top_k / 工具 limit</small><small>当前：限制候选数量，避免上下文膨胀</small></div>
<div class="rag-box light"><strong>source guard</strong><small>基于：selected_sources_context / allowed_source_ids</small><small>当前：不访问未选来源，不查询全库</small></div>
<div class="rag-box light"><strong>year warnings</strong><small>基于：time_scope / selected_year / artifact year</small><small>当前：年份缺失提示，禁止跨年比较</small></div>
</div>
<div class="rag-note">当前 rerank 是轻量实现：关键词/结构召回 + score 排序 + top_k + 来源边界过滤。完整 hybrid rerank、向量重排、trust/freshness rerank 仍是后续增强，不应在汇报中说已经完成。</div>
</div>
<div class="rag-arrow">↓ Read / Hydrate Evidence：读取完整节点、补齐 locator/citation/metadata</div>
<div class="rag-layer read">
<div class="rag-layer-title">7. Read / Hydrate Evidence 读取与证据补全</div>
<div class="rag-grid rag-grid-3">
<div class="rag-box"><strong>read_selected_source_evidence_node</strong><small>基于：search 命中的 node_id</small><small>生成：完整已选来源 EvidenceNode</small></div>
<div class="rag-box"><strong>read_analysis_evidence_node</strong><small>基于：analysis_context node_id</small><small>生成：完整分析上下文 EvidenceNode</small></div>
<div class="rag-box"><strong>read_report_evidence_node</strong><small>基于：report_context node_id</small><small>生成：完整报告上下文 EvidenceNode</small></div>
<div class="rag-box"><strong>read_scope_record</strong><small>基于：record_id + source_id + history_id</small><small>生成：单条 POI/cell/road EvidenceNode</small></div>
<div class="rag-box"><strong>PageIndex read</strong><small>基于：document node/page locator</small><small>生成：章节/页内容和 citation</small></div>
<div class="rag-box"><strong>package read</strong><small>基于：item_id / carrier_id / node_id</small><small>生成：资料包样本、空间载体、metric refs</small></div>
</div>
</div>
<div class="rag-arrow">↓ Context Pack：把证据、指标、视觉资产按消费场景组包</div>
<div class="rag-layer pack">
<div class="rag-layer-title">8. Context Pack 上下文组合包</div>
<div class="rag-grid rag-grid-5">
<div class="rag-box package"><strong>Source Manifest</strong><small>基于：PptSource + source_index_manifest + aiPayload.counts</small><small>生成：来源清单、状态、证据数量、排除项、policy</small></div>
<div class="rag-box package"><strong>Evidence Pack</strong><small>基于：hydrated EvidenceNode</small><small>生成：evidence_context / selected_source_evidence_nodes / finalizer evidence pack</small></div>
<div class="rag-box package"><strong>Metric Context</strong><small>基于：ready metrics + metric_gaps</small><small>生成：metric_context，PPT 数字图和 AI 指标解释依据</small></div>
<div class="rag-box package"><strong>Visual / Data Package</strong><small>基于：visual_assets + ppt_data_package + visual_specs</small><small>生成：visual_artifacts、POI 样例、夜生活包、空间载体包</small></div>
<div class="rag-box package"><strong>PPT / Agent Bundle</strong><small>基于：前四类包</small><small>生成：PPT Context Bundle 或 Agent Context Bundle</small></div>
</div>
</div>
<div class="rag-arrow">↓ LLM Consumers：同一批 RAG 包进入不同 AI 链路</div>
<div class="rag-layer consume">
<div class="rag-layer-title">9. LLM Consumers 大模型消费链路</div>
<div class="rag-grid rag-grid-2">
<div class="rag-box warn"><strong>PPT 生成链</strong><small>基于：PPT Context Bundle</small><small>动作：generate_ppt_spec -> generate_narrative_plan -> generate_deck_brief -> regenerate_deck_brief_slide -> visual artifacts</small><small>产物：目录、叙事方案、PPT 指令文件、逐页 brief、页面视觉资产</small></div>
<div class="rag-box warn"><strong>AI 分析链</strong><small>基于：Agent Context Bundle + 工具注册表</small><small>动作：快速模式 source_qa_loop；深度模式 ReAct 工具循环 + Auditor + Finalizer</small><small>产物：自然语言分析、证据引用、warnings、下一步动作</small></div>
</div>
</div>
<div class="rag-note">读图口径：经典 RAG 的 Retrieve/Rerank/Read 阶段在当前系统里既包括 EvidenceIndexService，也包括 selected source tools、scope dataset tools 和 runtime context retrieval。PPT 额外需要 Metric Context 与 Visual/Data Package，这是普通文本 RAG 图里通常没有的展示生成层。</div>
</div>

## 包生成速查表

| 经典 RAG 阶段 | 当前实现 | 生成包 | 是否已完整实现 / 过渡状态 |
| --- | --- | --- | --- |
| Ingest & Normalize | 文档上传、网页抓取、图片登记、history/artifact 读取、scope dataset 发现 | source seed、标准化来源对象 | 已实现；图片 OCR/视觉索引仍是 contract 优先 |
| Parse / Chunk / Node Build | Docling -> PageIndex；Crawl4AI -> markdown chunks；history/artifact -> summary nodes；ppt_data_package -> items/groups/carriers | PageIndex nodes、web evidence nodes、package nodes、scope records | 文档较完整；web/package 使用 payload/artifact 过渡；图片待增强 |
| Index & Source Registry | `PptSource`、`source_index_manifest`、`selected_sources_context`、native adapter manifest | `PptSource`、`source_index_manifest`、`selected_sources_context` | Manifest/artifact 版已实现；部分 native node 物理表待增强 |
| Retrieve / Recall | `EvidenceIndexService.search`、adapter recall、`rank_chunks`、`search_selected_source_evidence`、`query_scope_dataset` | EvidenceIndexRecord、SearchHit、scope records | 已实现轻量召回；向量召回不是主链 |
| Rerank / Filter / Guard | score sort、top_k、source guard、allowed_source_ids、year warnings、selected-source boundary | 排序后的候选 EvidenceNode / records | 当前是轻量 rerank；hybrid rerank、trust/freshness rerank 待增强 |
| Read / Hydrate Evidence | `read_selected_source_evidence_node`、`read_analysis_evidence_node`、`read_report_evidence_node`、`read_scope_record`、PageIndex read | hydrated EvidenceNode、locator、citation、metadata | 已实现；不同来源 read 能力深度不同 |
| Context Pack | `_build_ppt_context_bundle()`、`build_context_bundle()`、finalizer evidence pack | Source Manifest、Evidence Pack、Metric Context、Visual/Data Package、PPT/Agent Bundle | 已实现；PPT 与 Agent 使用不同 bundle |
| LLM Consumers | PPT 生成链、快速来源问答、深度 ReAct + Auditor + Finalizer | PPT 指令文件、逐页 brief、自然语言分析、引用和 warnings | 已实现主链；最终 PPTX/完整视觉渲染是后续阶段 |

## 和标准 RAG 的差异

- 当前不是单一向量库 RAG：不同来源保留自己的 native index，例如 PageIndex、scope dataset records、package nodes 和 artifact payload。
- 文档保留 PageIndex，不退化成普通 chunk；空间资料包和当前项目成果包也不强行塞进同一个文本向量表。
- Rerank 当前偏轻量，主要是关键词/结构召回、score 排序、top_k、来源边界过滤和年份提示；完整 hybrid rerank 后续再增强。
- PPT 不是普通文本问答消费端，它额外需要 `Metric Context` 和 `Visual/Data Package`，用于指标卡、图表、地图截图、空间载体和逐页视觉指令。
- AI 分析和 PPT 使用同一套来源与证据，但组合包不同：PPT 使用 `PPT Context Bundle`，主 Agent 使用 `Agent Context Bundle` 和工具调用循环。
