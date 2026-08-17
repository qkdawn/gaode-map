import projectContextComponent from '../workflow-components/project-context.mjs';
import failureHandlingComponent from '../workflow-components/failure-handling.mjs';
import visualsComponent from '../workflow-components/data-visuals.mjs';
import reportComponent from '../workflow-components/report-generation.mjs';
import {
  assertFormalWorkflow,
  codeNode,
  connect,
  localizeComponent,
  mergeGraph,
  postgresNode,
  readComponent,
  replaceNodeWithFragment,
  sticky,
} from './workflow-builder.mjs';

const [submitSource, statusSource, decisionSource, responsesSource] = await Promise.all([
  readComponent('agent-submit.json'),
  readComponent('agent-status.json'),
  readComponent('decision-step.json'),
  readComponent('responses.json'),
]);

// Previous chapter bodies stay in the run state. The chapter model receives only
// a directory and can request a specific body through the guarded read tool.
const decisionSourceForGeneration = structuredClone(decisionSource);
const markRunningNode = decisionSourceForGeneration.nodes.find((node) => node.name === 'Mark Step Running');
if (markRunningNode) {
  markRunningNode.parameters.query = markRunningNode.parameters.query.replace(
    "UPDATE analysis_runs SET status = 'running', current_step = $2::text, started_at = COALESCE(started_at, NOW()), updated_at = NOW()",
    "UPDATE analysis_runs SET status = 'running', current_step = $2::text, started_at = COALESCE(started_at, NOW()), heartbeat_at = NOW(), lease_expires_at = NOW() + INTERVAL '45 minutes', updated_at = NOW()",
  );
}
const validateStepRequestNode = decisionSourceForGeneration.nodes.find((node) => node.name === 'Validate Step Request');
if (validateStepRequestNode?.parameters?.jsCode) {
  validateStepRequestNode.parameters.jsCode = validateStepRequestNode.parameters.jsCode
    .replace('stepOrder > 12', 'stepOrder > 32')
    .replace('between 1 and 12', 'between 1 and 32');
}
const buildDecisionRequestNode = decisionSourceForGeneration.nodes.find((node) => node.name === 'Build Structured Decision Request');
if (buildDecisionRequestNode?.parameters?.jsCode) {
  buildDecisionRequestNode.parameters.jsCode = buildDecisionRequestNode.parameters.jsCode.replace(
    "const state = $('Validate Step Request').first().json;",
    "const state = $input.first()?.json ?? $('Validate Step Request').first().json;",
  );
  buildDecisionRequestNode.parameters.jsCode = buildDecisionRequestNode.parameters.jsCode.replace(
    "  project_documents: projectDocuments,\n});",
    "  project_documents: projectDocuments,\n  project_document_prefetch: state.project_document_prefetch ?? null,\n});",
  );
  buildDecisionRequestNode.parameters.jsCode = buildDecisionRequestNode.parameters.jsCode.replace(
    '先理解 research_brief，再根据判断所需证据自主选择工具；没有相关证据需求时不要为了形式调用工具。',
    '先理解 research_brief。项目存在文档时，首段正文已经由工作流预读并注入；涉及项目事实、场地、主题或约束时，必须继续使用 read_project_document 分页读取原文，不能只依据目录。当前任务明确依赖某类证据、但 evidence_brief 里还没有该类工具的实际结果时，不得仅凭数据目录、记录总量或方法常识直接 finish。',
  );
  buildDecisionRequestNode.parameters.jsCode = buildDecisionRequestNode.parameters.jsCode.replace(
    '严格区分事实、代理和未知。未知只降低结论强度，不自动阻塞结论，也不自动生成“必须补齐证据”清单。',
    '检查工具结果是否足以让后续研究 Agent 回答当前 research_brief；不要替后续研究 Agent 形成结论。数据目录、字段说明、记录总量和工具可用状态不等于分析结果。',
  );
  buildDecisionRequestNode.parameters.jsCode = buildDecisionRequestNode.parameters.jsCode.replace(
    '正文使用普通读者能理解的表达，直接说明判断、依据、候选路径取舍、反证、不确定性和成立条件。内容长度由证据复杂度决定。',
    '正文使用普通读者能理解的表达，直接说明判断、依据、候选路径取舍和当前证据中的反例。内容长度由证据复杂度决定。',
  );
  buildDecisionRequestNode.parameters.jsCode = buildDecisionRequestNode.parameters.jsCode.replace(
    '本次分析边界是已提供的项目文档、POI、人口、路网、夜光、H3 网格、文献知识库和可按需取得的公开网页。',
    '可用证据包括项目文档、POI、人口、路网、夜光、H3 网格、文献知识库和公开网页；只选择当前研究任务真正需要的工具。',
  );
  buildDecisionRequestNode.parameters.jsCode = buildDecisionRequestNode.parameters.jsCode.replace(
    '分析关系和机制，检验能否用另一种解释说明同一证据。没有真实取舍时不要强造选项，也不要从代理指标直接跳到因果结论。',
    '选择能够回答当前证据缺口的最小下一次调用；不要为了遍历工具而调用，也不要在路由阶段解释证据关系。',
  );
  buildDecisionRequestNode.parameters.jsCode = buildDecisionRequestNode.parameters.jsCode.replace(
    '成稿前挑战当前判断最脆弱的环节、可能改判的事实及其对下一章节的约束，并写入自由文本 decision_brief。',
    '成稿前比较当前证据中最支持和最削弱本章判断的信号，并把对下一章节的约束写入自由文本 decision_brief。',
  );
  buildDecisionRequestNode.parameters.jsCode = buildDecisionRequestNode.parameters.jsCode.replace(
    '项目事实使用 read_project_document 读取原文，返回 complete=false 且结论依赖后文时继续读取。',
    '项目事实使用 read_project_document 读取原文；返回 complete=false 且结论依赖后文时，使用 next_start_block 继续读取。不要一次读取全部文档。',
  );
  buildDecisionRequestNode.parameters.jsCode = buildDecisionRequestNode.parameters.jsCode.replace(
    "Use scope with empty metric_ids to discover available metrics.",
    "Use scope with empty metric_ids to discover available spatial metrics when discovery is needed. Do not mix catalog and native metrics in one request.",
  );
  buildDecisionRequestNode.parameters.jsCode = buildDecisionRequestNode.parameters.jsCode.replace(
    '空间事实只通过 analyze_spatial_evidence 获取。先用 scope 和空 metric_ids 发现指标，再按需选择范围、距离、方向、邻域、排序、关系或个案检查。不得自行重算 GIS 公式或要求完整几何。',
    '空间事实只通过 analyze_spatial_evidence 获取。你是证据路由 Agent，每轮可以返回一至三个参数已经完整确定、彼此不依赖的工具请求，或返回 finish；是否展开、展开到什么粒度完全由你根据当前任务和已取得结果判断。scope 且 metric_ids=[] 只是指标发现，永远不构成空间分析结果；执行 scope 后，若本章问题涉及区域结构、功能差异或机会判断，必须继续选择一个能返回 groups、highlights 或 relationship 的具体分析。若 working_research_brief 只有项目文档或 scope 目录而没有具体空间结果，不得 finish，必须自行选择 rank、relationship、distance、direction、neighborhood 或 inspect 等具体模式。previous_decisions 只帮助避免重复写作，不代替当前章节取证；当当前 research_brief 明确询问 POI、人口、夜光、路网、H3、距离、方向、热点、功能差异或机会错配时，至少取得一次与该问题直接对应的非 scope 空间结果后才能 finish。不得自行重算 GIS 公式或要求完整几何。',
  );
  buildDecisionRequestNode.parameters.jsCode = buildDecisionRequestNode.parameters.jsCode
    .replace("reasoning: { effort: 'medium' },", "reasoning: { effort: 'low' },");

  // Research routing and writing are separate model calls. The router sees tool
  // contracts but cannot invoke them directly; N8N validates and executes its JSON decision.
  buildDecisionRequestNode.parameters.jsCode = buildDecisionRequestNode.parameters.jsCode
    .replace(
      "properties: { decision_brief: { type: 'string', minLength: 1 }, reader_chapter: { type: 'string', minLength: 1 } },\n  required: ['decision_brief', 'reader_chapter'],",
      "properties: { research_summary: { type: 'string', minLength: 1 }, key_findings: { type: 'array', maxItems: 12, items: { type: 'string', minLength: 1 } }, tensions: { type: 'array', maxItems: 8, items: { type: 'string', minLength: 1 } }, ready_to_write: { type: 'boolean' } },\n  required: ['research_summary', 'key_findings', 'tensions', 'ready_to_write'],",
    )
    .replace(
      "properties: { research_summary: { type: 'string', minLength: 1 }, key_findings: { type: 'array', maxItems: 12, items: { type: 'string', minLength: 1 } }, tensions: { type: 'array', maxItems: 8, items: { type: 'string', minLength: 1 } }, ready_to_write: { type: 'boolean' } },\n  required: ['research_summary', 'key_findings', 'tensions', 'ready_to_write'],",
      "properties: { decision: { type: 'string', enum: ['continue', 'finish'] }, reason: { type: 'string', minLength: 1, maxLength: 1200 }, next_tools: { type: 'array', maxItems: 3, items: { type: 'object', properties: { name: { type: 'string', enum: ['analyze_spatial_evidence', 'read_project_document', 'read_previous_chapter', 'search_literature_evidence', 'search_public_web', 'fetch_public_web_page'] }, arguments: { type: 'object', properties: { analysis: { type: ['string', 'null'] }, metric_ids: { type: ['array', 'null'], items: { type: 'string' } }, selectors: { type: ['array', 'null'] }, distance_bands_m: { type: ['array', 'null'] }, neighbor_steps: { type: ['integer', 'null'] }, rank_order: { type: ['string', 'null'] }, top_k: { type: ['integer', 'null'] }, record_refs: { type: ['array', 'null'], items: { type: 'string' } }, document_id: { type: ['string', 'null'] }, start_block: { type: ['integer', 'null'] }, max_blocks: { type: ['integer', 'null'] }, page_start: { type: ['integer', 'null'] }, page_end: { type: ['integer', 'null'] }, question: { type: ['string', 'null'] }, mode: { type: ['string', 'null'] }, query: { type: ['string', 'null'] }, provider: { type: ['string', 'null'] }, limit: { type: ['integer', 'null'] }, urls: { type: ['array', 'null'], items: { type: 'string' } }, max_characters: { type: ['integer', 'null'] }, step_key: { type: ['string', 'null'] }, step_order: { type: ['integer', 'null'] } }, additionalProperties: false } }, required: ['name', 'arguments'], additionalProperties: false } }, research_summary: { type: 'string' }, key_findings: { type: 'array', maxItems: 12, items: { type: 'string' } }, tensions: { type: 'array', maxItems: 8, items: { type: 'string' } }, ready_to_write: { type: 'boolean' } },\n  required: ['decision', 'reason', 'next_tools', 'research_summary', 'key_findings', 'tensions', 'ready_to_write'],",
    )
    .replace("selectors: { type: ['array', 'null'] },", "selectors: { type: ['array', 'null'], items: { type: 'object', properties: { dimension: { type: 'string' }, values: { type: 'array', items: { anyOf: [{ type: 'string' }, { type: 'integer' }] } } }, required: ['dimension', 'values'], additionalProperties: false } },")
    .replace("distance_bands_m: { type: ['array', 'null'] },", "distance_bands_m: { type: ['array', 'null'], items: { type: 'array', minItems: 2, maxItems: 2, items: { type: 'number' } } },")
    .replace("step_order: { type: ['integer', 'null'] } }, additionalProperties: false } }, required: ['name', 'arguments']", "step_order: { type: ['integer', 'null'] } }, required: ['analysis', 'metric_ids', 'selectors', 'distance_bands_m', 'neighbor_steps', 'rank_order', 'top_k', 'record_refs', 'document_id', 'start_block', 'max_blocks', 'page_start', 'page_end', 'question', 'mode', 'query', 'provider', 'limit', 'urls', 'max_characters', 'step_key', 'step_order'], additionalProperties: false } }, required: ['name', 'arguments']")
    .replace(" }, research_summary: { type: 'string' }, key_findings: { type: 'array', maxItems: 12, items: { type: 'string' } }, tensions: { type: 'array', maxItems: 8, items: { type: 'string' } }, ready_to_write: { type: 'boolean' } },\n  required: ['decision', 'reason', 'next_tools', 'research_summary', 'key_findings', 'tensions', 'ready_to_write'],", " } },\n  required: ['decision', 'reason', 'next_tools'],")
    .replace("'为当前分析方向撰写一章可直接发表在项目报告中的中文正文。读者是项目甲方、政府决策者、投资人和非技术评审者。',", "'你是一个独立的证据路由 Agent，不写最终报告正文。根据当前任务和已有证据，决定是否继续取证以及下一步调用哪个工具。',")
    .replace("'正文使用普通读者能理解的表达，直接说明判断、依据、候选路径取舍和当前证据中的反例。内容长度由证据复杂度决定。',", "'reason 只用简洁中文说明为什么继续调用这一批工具，或为什么现有证据已经足够开始分析。不得声称尚未调用的工具已经执行。',")
    .replace("'成稿前比较当前证据中最支持和最削弱本章判断的信号，并把对下一章节的约束写入自由文本 decision_brief。',", "'continue 时 next_tools 必须包含一至三个相互独立的工具请求；finish 时 next_tools 必须为空数组。不要输出研究摘要、关键发现、冲突判断或章节正文。',")
    .replace("'reader_chapter 是面向甲方的完整正文。只返回 decision_brief 与 reader_chapter，不解释工作流或工具调用过程。',", "'只返回 decision、reason 和 next_tools。你只负责证据路由，不负责形成研究结论或撰写研究摘要。',")
    .replace("'任何工具不可用时不得编造结果；继续使用已取得证据完成尺度相称的条件性判断。',", "'工具不可用时，不得假装取得结果；只有存在明确替代证据入口时才选择其他工具，否则 finish。',")
    .replace("'优先推进本章新的决策边界，不重复前文，也不提前替后续章节完成核心判断。',", "'路由决策只服务当前 research_brief；不评价最终论证质量，也不规定后续研究和写作结构。只有参数在本轮开始前已经完整确定的请求才能放进同一批。search_public_web→fetch_public_web_page、scope→具体指标、rank→inspect 和文档分页必须跨轮串行。',")
    .replace("text: { format: { type: 'json_schema', name: 'reader_chapter', strict: true, schema } },", "tool_choice: 'none',\n  text: { format: { type: 'json_schema', name: 'evidence_route', strict: true, schema } },")
    .replace("  tool_result_fingerprints: [],", "  initial_context_items: conversationItems,\n  working_research_brief: { version: 1, cards: [] },\n  research_result_store: [],\n  tool_request_fingerprints: [],\n  tool_result_fingerprints: [],")
    .replace("  tool_evidence: [],", "  tool_evidence: [],\n  tool_call_limit: 12,\n  max_parallel_tools: 3,");

  buildDecisionRequestNode.parameters.jsCode = buildDecisionRequestNode.parameters.jsCode.replace(
    "  project_documents: projectDocuments,\n  project_document_prefetch: state.project_document_prefetch ?? null,\n});",
    "  project_documents: projectDocuments,\n  project_document_prefetch: state.project_document_prefetch ?? null,\n  available_spatial_metrics: availableSpatialMetrics,\n  execution_budget: { max_parallel: 3, remaining_tool_calls: 12 },\n});",
  );
  buildDecisionRequestNode.parameters.jsCode = buildDecisionRequestNode.parameters.jsCode.replace(
    'const schema = {',
    `const datasetIds = new Set((Array.isArray(state.project_context?.datasets) ? state.project_context.datasets : []).map((item) => String(item?.dataset_id ?? '')));
const availableSpatialMetrics = [
  ...(datasetIds.has('poi') ? ['poi.grid_density', 'poi.local_entropy_normalized', 'poi.lq', 'poi.supply_structure'] : []),
  ...(datasetIds.has('population') ? ['population.total', 'population.age_structure'] : []),
  ...(datasetIds.has('nightlight') ? ['nightlight.mean_radiance', 'nightlight.hotspot_ratio', 'nightlight.spatial_profile'] : []),
  ...(datasetIds.has('road_edges') || datasetIds.has('road_nodes') ? ['road.integration', 'road.choice', 'road.connectivity', 'road.orientation'] : []),
];
const schema = {`,
  );
}
const selectInitialDocumentNode = decisionSourceForGeneration.nodes.find((node) => node.name === 'Select Initial Project Document');
if (selectInitialDocumentNode?.parameters?.jsCode) {
  selectInitialDocumentNode.parameters.jsCode = selectInitialDocumentNode.parameters.jsCode.replace(
    "const state = $input.first()?.json ?? {};",
    "const state = $('Validate Step Request').first().json;",
  );
  selectInitialDocumentNode.parameters.jsCode = selectInitialDocumentNode.parameters.jsCode.replace(
    "['parsed', 'ready', 'uploaded']",
    "['parsed', 'ready']",
  );
}
const initialDocumentReadNode = decisionSourceForGeneration.nodes.find((node) => node.name === 'Read Initial Project Document');
if (initialDocumentReadNode?.parameters?.jsonBody) {
  initialDocumentReadNode.parameters.jsonBody = initialDocumentReadNode.parameters.jsonBody.replace('max_blocks: 8', 'max_blocks: 4');
}
const prepareToolCallNode = decisionSourceForGeneration.nodes.find((node) => node.name === 'Prepare MCP Agent Tool Call');
if (prepareToolCallNode?.parameters?.jsCode) {
  prepareToolCallNode.parameters.jsCode = prepareToolCallNode.parameters.jsCode.replace(
    "    mcp_call_id: String(call.call_id),",
    "    mcp_call_id: String(call.call_id),\n    batch_index: Number(call.batch_index ?? 0),\n    batch_size: Number(call.batch_size ?? calls.length),",
  );
}
const followUpNode = decisionSourceForGeneration.nodes.find((node) => node.name === 'Build MCP Agent Follow-up');
if (!followUpNode) throw new Error('follow_up_node_missing');
if (followUpNode.parameters?.jsCode) {
  followUpNode.parameters.jsCode = followUpNode.parameters.jsCode.replace(
    'const normalizedResults = items.map((item, index) => {',
    'let normalizedResults = items.map((item, index) => {',
  );
  followUpNode.parameters.jsCode = followUpNode.parameters.jsCode
    .replace(
      "    is_error: toolResult.is_error === true,\n    result: toolResult.structured_content ?? toolResult.content ?? toolResult,",
      "    is_error: toolResult.is_error === true || Boolean(toolResult.error),\n    batch_index: Number(itemPrior.batch_index ?? index),\n    result: toolResult.structured_content ?? toolResult.content ?? (toolResult.error ? { status: 'error', message: String(toolResult.error?.message ?? toolResult.error) } : toolResult),",
    )
    .replace(
      "  };\n});\nconst priorRequestFingerprints",
      "  };\n}).sort((left, right) => left.batch_index - right.batch_index);\nconst priorRequestFingerprints",
    );
  followUpNode.parameters.jsCode = followUpNode.parameters.jsCode.replace(
    'const newEvidence = normalizedResults.flatMap((entry) => {',
    `normalizedResults = normalizedResults.sort((left, right) => left.batch_index - right.batch_index);
const priorRequestFingerprints = Array.isArray(prior.tool_request_fingerprints) ? prior.tool_request_fingerprints : [];
const projectSpatialValue = (value, key = '') => {
  const forbidden = new Set(['geometry', 'coordinates', 'features', 'featurecollection', 'database', 'connection', 'file_path', 'path']);
  if (forbidden.has(String(key).toLowerCase())) return undefined;
  if (typeof value === 'string') {
    const lower = value.trim().toLowerCase();
    const hasGeometryKey = ['"geometry"', "'geometry'", '"coordinates"', "'coordinates'", '"features"', "'features'"].some((marker) => lower.includes(marker));
    const hasGeometryType = ['polygon', 'multipolygon', 'linestring', 'multilinestring', 'point', 'multipoint'].some((token) => lower.includes(token));
    if (lower.startsWith('polygon(') || lower.startsWith('multipolygon(') || lower.startsWith('linestring(') || lower.startsWith('multilinestring(') || lower.startsWith('point(') || (hasGeometryKey && hasGeometryType) || ((lower.includes('"type"') || lower.includes("'type'")) && hasGeometryType)) return undefined;
    return value.slice(0, 1200);
  }
  if (Array.isArray(value)) return value.slice(0, 20).map((item) => projectSpatialValue(item, key)).filter((item) => item !== undefined);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([childKey, childValue]) => [childKey, projectSpatialValue(childValue, childKey)]).filter(([, childValue]) => childValue !== undefined));
  return value;
};
normalizedResults = normalizedResults.map((entry) => entry.tool_name === 'analyze_spatial_evidence' ? { ...entry, result: projectSpatialValue(entry.result) } : entry);
const modelResultLimit = (toolName) => toolName === 'analyze_spatial_evidence' ? 5200 : toolName === 'read_project_document' ? 6000 : 4800;
const clippedText = (value, limit) => String(value ?? '').replace(/\\s+/g, ' ').trim().slice(0, limit);
const compactSpatialIdentity = (identity) => {
  if (!identity || typeof identity !== 'object' || Array.isArray(identity)) return {};
  const allowed = ['dataset_id', 'display_name', 'name', 'road_name', 'category', 'subcategory', 'typecode', 'address', 'road_class', 'year', 'source'];
  return Object.fromEntries(allowed.filter((key) => identity[key] !== undefined && identity[key] !== null && identity[key] !== '').map((key) => {
    const limit = key === 'address' ? 240 : key === 'display_name' || key === 'name' || key === 'road_name' ? 180 : 120;
    return [key, typeof identity[key] === 'string' ? clippedText(identity[key], limit) : identity[key]];
  }));
};
const projectNamedSpatialRecords = (highlights) => (Array.isArray(highlights) ? highlights : []).flatMap((item) => {
  if (!item || typeof item !== 'object') return [];
  const identity = compactSpatialIdentity(item.identity);
  const recordRef = clippedText(item.record_ref, 360);
  const name = clippedText(item.title ?? identity.name ?? identity.road_name ?? identity.display_name, 220);
  if (!recordRef || !name) return [];
  return [{
    record_ref: recordRef,
    name,
    identity,
    centroid_wgs84: Array.isArray(item.centroid_wgs84) ? item.centroid_wgs84.slice(0, 2) : undefined,
    distance_m: item.distance_m ?? null,
    direction: clippedText(item.direction, 40),
    values: item.values && typeof item.values === 'object' ? item.values : {},
    reason: clippedText(item.reason, 160),
  }];
});
const boundNamedSpatialRecords = (records, characterLimit = 3000, itemLimit = 20) => {
  const bounded = [];
  let characters = 0;
  for (const record of records.slice(0, itemLimit)) {
    const recordCharacters = JSON.stringify(record).length;
    if (bounded.length && characters + recordCharacters > characterLimit) break;
    bounded.push(record);
    characters += recordCharacters;
  }
  return bounded;
};
const compactSpatialResult = (value, limit) => {
  const namedRecords = projectNamedSpatialRecords(value.highlights);
  const metrics = (Array.isArray(value.metrics) ? value.metrics : []).slice(0, 12).map((item) => ({
    metric_id: item?.metric_id,
    label: item?.label ?? item?.name,
    unit: item?.unit,
    status: item?.status,
  }));
  const base = {
    status: value.status,
    analysis: value.analysis,
    summary: value.summary,
    metrics,
    groups: Array.isArray(value.groups) ? value.groups.slice(0, 8) : [],
    named_records: boundNamedSpatialRecords(namedRecords),
    relationship: value.relationship,
    coverage: value.coverage,
    limitations: Array.isArray(value.limitations) ? value.limitations.slice(0, 6).map((item) => clippedText(item, 360)) : [],
    method: value.method,
  };
  if (JSON.stringify(base).length <= limit) return base;
  const reduced = {
    ...base,
    summary: typeof value.summary === 'string' ? clippedText(value.summary, 900) : clippedText(JSON.stringify(value.summary ?? {}), 900),
    groups: base.groups.slice(0, 4),
    named_records: boundNamedSpatialRecords(namedRecords, 2800, 16),
    relationship: value.relationship ? projectSpatialValue(value.relationship) : undefined,
    method: value.method && typeof value.method === 'object' ? { kind: value.method.kind } : undefined,
  };
  if (JSON.stringify(reduced).length <= limit) return reduced;
  return {
    status: value.status,
    analysis: value.analysis,
    summary: typeof value.summary === 'string' ? clippedText(value.summary, 600) : clippedText(JSON.stringify(value.summary ?? {}), 600),
    metrics: metrics.slice(0, 6),
    named_records: boundNamedSpatialRecords(namedRecords, Math.max(1200, limit - 1800), 12),
    coverage: value.coverage,
    limitations: base.limitations.slice(0, 3),
  };
};
const compactForModel = (entry) => {
  const limit = modelResultLimit(entry.tool_name);
  const value = entry.result && typeof entry.result === 'object' ? entry.result : {};
  if (entry.tool_name === 'analyze_spatial_evidence') {
    return { ...entry, result: compactSpatialResult(value, limit) };
  }
  const keep = ['status', 'analysis', 'mode', 'question', 'answer', 'summary', 'metrics', 'groups', 'highlights', 'relationship', 'coverage', 'limitations', 'method', 'provenance', 'blocks', 'next_start_block', 'complete', 'evidence'];
  const result = Object.fromEntries(keep.filter((key) => Object.prototype.hasOwnProperty.call(value, key)).map((key) => [key, value[key]]));
  if (Array.isArray(result.groups)) result.groups = result.groups.slice(0, 8);
  if (Array.isArray(result.highlights)) result.highlights = result.highlights.slice(0, 12);
  if (Array.isArray(result.evidence)) result.evidence = result.evidence.slice(0, 10).map((item) => ({ ...item, content: typeof item?.content === 'string' ? item.content.slice(0, 700) : item?.content }));
  if (Array.isArray(result.blocks)) result.blocks = result.blocks.slice(0, 4).map((item) => ({ ...item, text: typeof item?.text === 'string' ? item.text.slice(0, 1200) : item?.text }));
  let candidate = { ...entry, result };
  if (JSON.stringify(candidate).length > limit) {
    candidate = { tool_name: entry.tool_name, call_id: entry.call_id, is_error: entry.is_error, batch_index: entry.batch_index, result: { status: entry.is_error ? 'error' : 'available', summary: String(value.summary ?? value.answer ?? '').slice(0, 1200), coverage: value.coverage, limitations: value.limitations, method: value.method } };
  }
  return candidate;
};
const modelResults = normalizedResults.map(compactForModel);
const requestFingerprint = (entry) => stable({ tool_name: entry.tool_name, arguments: entry.arguments });
const newRequestFingerprints = normalizedResults.map(requestFingerprint).filter((fingerprint) => !priorRequestFingerprints.includes(fingerprint));
const newEvidence = normalizedResults.flatMap((entry) => {
  if (priorRequestFingerprints.includes(requestFingerprint(entry))) return [];`,
  );
  followUpNode.parameters.jsCode = followUpNode.parameters.jsCode.replace(
    'const isNewEvidence = newFingerprints.length > 0;',
    'const isNewEvidence = newFingerprints.length > 0;',
  );
  followUpNode.parameters.jsCode = followUpNode.parameters.jsCode
    .replace(
      "const toolDiagnostics = [...(Array.isArray(prior.tool_diagnostics) ? prior.tool_diagnostics : []), ...normalizedResults.filter((entry) => entry.is_error).map((entry) => ({ kind: 'tool_error', tool_name: entry.tool_name, message: String(entry.result?.message ?? entry.result?.error ?? 'tool_call_failed') })), ...providerDiagnostics];",
      "const routeDiagnostics = Array.isArray(prior.route_diagnostics) ? prior.route_diagnostics : [];\nconst toolDiagnostics = [...(Array.isArray(prior.tool_diagnostics) ? prior.tool_diagnostics : []), ...routeDiagnostics, ...normalizedResults.filter((entry) => entry.is_error).map((entry) => ({ kind: 'tool_error', tool_name: entry.tool_name, message: String(entry.result?.message ?? entry.result?.error ?? 'tool_call_failed') })), ...providerDiagnostics];",
    )
    .replace(
      "const toolErrorCount = normalizedResults.some((entry) => entry.is_error) ? Number(prior.tool_error_count ?? 0) + 1 : 0;",
      "const failedStatuses = new Set(['unavailable', 'invalid_request', 'not_found', 'error']);\nconst batchAllFailed = normalizedResults.length > 0 && normalizedResults.every((entry) => entry.is_error || failedStatuses.has(String(entry.result?.status ?? '').toLowerCase()));\nconst toolErrorCount = batchAllFailed ? Number(prior.tool_error_count ?? 0) + 1 : 0;",
    );
  followUpNode.parameters.jsCode = followUpNode.parameters.jsCode.replace(
    'tool_result_fingerprints: [...fingerprints, ...newFingerprints].slice(-32),',
    'tool_result_fingerprints: [...fingerprints, ...newFingerprints].slice(-32),\n  tool_request_fingerprints: [...priorRequestFingerprints, ...newRequestFingerprints].slice(-32),',
  );
  followUpNode.parameters.jsCode = followUpNode.parameters.jsCode
    .replace(
      "const keep = ['status', 'analysis', 'mode', 'question', 'answer', 'summary', 'metrics', 'groups', 'highlights', 'relationship', 'coverage', 'limitations', 'method', 'provenance', 'blocks', 'next_start_block', 'complete', 'evidence'];",
      "const keep = ['status', 'analysis', 'mode', 'question', 'answer', 'summary', 'metrics', 'groups', 'highlights', 'relationship', 'coverage', 'limitations', 'method', 'provenance', 'blocks', 'next_start_block', 'complete', 'evidence', 'results', 'content', 'urls'];",
    )
    .replace(
      `const nextItems = [
  ...conversationItems,
  ...responseItems,
  ...normalizedResults.map((entry) => ({ type: 'function_call_output', call_id: entry.call_id, output: JSON.stringify(entry) })),
];`,
      `const compactText = (value, limit = 900) => String(value ?? '').replace(/\\s+/g, ' ').trim().slice(0, limit);
const shortHash = (value) => {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16).padStart(8, '0');
};
const resultRef = (entry) => 'run-result:' + entry.tool_name + ':' + shortHash(stable({ tool_name: entry.tool_name, arguments: entry.arguments }));
const briefCard = (entry) => {
  const compactEntry = compactForModel(entry);
  const value = compactEntry.result && typeof compactEntry.result === 'object' ? compactEntry.result : {};
  const card = { result_ref: resultRef(entry), tool_name: entry.tool_name, status: entry.is_error ? 'error' : String(value.status ?? 'available') };
  if (entry.tool_name === 'analyze_spatial_evidence') {
    card.analysis = String(value.analysis ?? entry.arguments.analysis ?? '');
    card.summary = value.summary;
    card.metrics = Array.isArray(value.metrics) ? value.metrics.slice(0, 12) : [];
    card.groups = Array.isArray(value.groups) ? value.groups.slice(0, 6) : [];
    card.named_records = Array.isArray(value.named_records) ? value.named_records : [];
    card.relationship = value.relationship;
    card.coverage = value.coverage;
    card.limitations = value.limitations;
  } else if (entry.tool_name === 'read_project_document') {
    card.document_id = String(value.document_id ?? entry.arguments.document_id ?? '');
    card.complete = value.complete === true;
    card.next_start_block = value.next_start_block ?? null;
    card.blocks = Array.isArray(value.blocks) ? value.blocks.slice(0, 4).map((block) => ({ heading: block?.heading, page: block?.page, text: compactText(block?.text, 1200) })) : [];
  } else if (entry.tool_name === 'search_literature_evidence') {
    card.answer = compactText(value.answer, 1400);
    card.evidence = Array.isArray(value.evidence) ? value.evidence.slice(0, 6).map((item) => ({ title: item?.title, page_start: item?.page_start, content: compactText(item?.content, 700) })) : [];
  } else if (entry.tool_name === 'fetch_public_web_page') {
    card.urls = Array.isArray(value.urls) ? value.urls.slice(0, 5) : [];
    card.content = Array.isArray(value.content) ? value.content.slice(0, 3).map((item) => compactText(item, 900)) : compactText(value.content, 900);
  } else if (entry.tool_name === 'read_previous_chapter') {
    card.summary = compactText(value.reader_chapter ?? value.content ?? value.summary, 1200);
  } else {
    card.summary = compactText(value.summary ?? value.answer ?? value.message, 1000);
  }
  return projectSpatialValue(card);
};
const priorBrief = prior.working_research_brief && typeof prior.working_research_brief === 'object' ? prior.working_research_brief : {};
const priorCards = Array.isArray(priorBrief.cards) ? priorBrief.cards : [];
const newCards = normalizedResults.map(briefCard);
const uniqueCards = [...priorCards, ...newCards].filter((item, index, all) => item?.result_ref && all.findIndex((candidate) => candidate.result_ref === item.result_ref) === index);
const priorNamedSpatialRecords = Array.isArray(priorBrief.named_spatial_records) ? priorBrief.named_spatial_records : [];
const newNamedSpatialRecords = newCards.flatMap((card) => Array.isArray(card.named_records) ? card.named_records : []);
const uniqueNamedSpatialRecords = [...priorNamedSpatialRecords, ...newNamedSpatialRecords]
  .filter((item, index, all) => item?.record_ref && item?.name && all.findIndex((candidate) => candidate.record_ref === item.record_ref) === index);
const namedSpatialRecords = boundNamedSpatialRecords(uniqueNamedSpatialRecords.slice().reverse(), 4200, 20).reverse();
const cardsForBudget = uniqueCards.map((card) => {
  if (card.tool_name !== 'analyze_spatial_evidence') return card;
  const refs = Array.isArray(card.named_records) ? card.named_records.map((item) => item?.record_ref).filter(Boolean).slice(0, 20) : [];
  const { named_records: _namedRecords, ...rest } = card;
  return { ...rest, named_record_refs: refs };
});
const boundedCards = [];
let briefCharacters = JSON.stringify(namedSpatialRecords).length;
for (const card of cardsForBudget.slice().reverse()) {
  const cardCharacters = JSON.stringify(card).length;
  if (boundedCards.length && briefCharacters + cardCharacters > 14000) continue;
  boundedCards.push(card);
  briefCharacters += cardCharacters;
  if (boundedCards.length >= 16) break;
}
const cards = boundedCards.reverse();
const workingBrief = {
  version: 1,
  named_spatial_records: namedSpatialRecords,
  cards,
};
const researchResultStore = [...(Array.isArray(prior.research_result_store) ? prior.research_result_store : []), ...normalizedResults.map((entry) => ({ result_ref: resultRef(entry), tool_name: entry.tool_name, arguments: entry.arguments, is_error: entry.is_error, batch_index: entry.batch_index, result: entry.result }))]
  .filter((item, index, all) => item.result_ref && all.findIndex((candidate) => candidate.result_ref === item.result_ref) === index)
  .slice(-24);
const latestToolResults = modelResults.map((entry) => priorRequestFingerprints.includes(requestFingerprint(entry))
  ? { tool_name: entry.tool_name, status: 'duplicate_request', message: '相同工具请求已经返回，请直接使用工作简报。' }
  : entry);
const toolCallLimit = Math.max(1, Number(prior.tool_call_limit ?? 12));
const executionBudget = {
  max_parallel: Math.max(1, Math.min(3, Number(prior.max_parallel_tools ?? 3))),
  remaining_tool_calls: Math.max(0, toolCallLimit - Number(prior.tool_call_count ?? 0)),
};
const nextItems = [
  ...(Array.isArray(prior.initial_context_items) ? prior.initial_context_items : conversationItems.slice(0, 1)),
  { role: 'user', content: [{ type: 'input_text', text: JSON.stringify({ working_research_brief: workingBrief, latest_tool_results: latestToolResults, execution_budget: executionBudget }) }] },
];`,
    )
    .replace(
      "const contextTokens = measuredTokens > 0\n  ? measuredTokens + Math.ceil(normalizedResults.reduce((total, entry) => total + JSON.stringify(entry).length, 0) / 4)\n  : Math.ceil(JSON.stringify({ input: nextItems, instructions: prior.instructions, tools: prior.tools, text: prior.text }).length / 4);",
      "const contextTokens = Math.ceil(JSON.stringify({ input: nextItems, instructions: prior.instructions, tools: prior.tools, text: prior.text }).length / 4);",
    )
    .replace("const measuredTokens = Number(usage.total_tokens ?? 0);\n", "")
    .replace(
      "const resolvedStopReason = contextTokens >= Math.max(1, budget - reserve)\n  ? 'context_budget'\n  : toolErrorCount >= Number(prior.tool_error_limit ?? 2)\n    ? 'tool_errors'\n    : staleToolTurns >= Number(prior.no_new_evidence_limit ?? 2)\n    ? 'no_new_evidence'\n    : null;",
      "const resolvedStopReason = contextTokens >= Math.max(1, budget - reserve)\n  ? 'context_budget'\n  : Number(prior.tool_call_count ?? 0) >= Number(prior.tool_call_limit ?? 12)\n    ? 'tool_call_limit'\n    : toolErrorCount >= Number(prior.tool_error_limit ?? 2)\n    ? 'tool_errors'\n    : staleToolTurns >= Number(prior.no_new_evidence_limit ?? 2)\n    ? 'no_new_evidence'\n    : null;",
    )
    .replace(
      "  tool_evidence: toolEvidence,\n  tool_diagnostics: toolDiagnostics,",
      "  tool_evidence: toolEvidence,\n  tool_diagnostics: toolDiagnostics,\n  route_diagnostics: [],\n  working_research_brief: workingBrief,\n  research_result_store: researchResultStore,",
    )
    .replace(
      "请立即基于已获得的项目证据输出完整 reader_chapter，不要再调用工具。",
      "请返回 decision=finish，不要形成研究结论或写最终章节。",
    )
    .replace("tool_choice: resolvedStopReason ? 'none' : undefined,", "tool_choice: 'none',");
}
const refreshLeaseNode = postgresNode('刷新分析任务租约', `UPDATE analysis_runs
SET heartbeat_at = NOW(), lease_expires_at = NOW() + INTERVAL '45 minutes', updated_at = NOW()
WHERE id = $1::uuid AND tenant_id = $2::text AND status = 'running';
SELECT $1::text AS run_id;`, "={{ [$('准备证据路由工具调用').first().json.state.run_id, $('准备证据路由工具调用').first().json.state.tenant_id] }}", [4960, 2040], 'urban-agent-refresh-lease');
const restoreToolLoopNode = codeNode('恢复章节工具上下文', `return [{ json: $('Build MCP Agent Follow-up').first().json }];`, [5180, 2040], 'urban-agent-restore-tool-context');
decisionSourceForGeneration.nodes.push(refreshLeaseNode, restoreToolLoopNode);
decisionSourceForGeneration.connections['Build MCP Agent Follow-up'] = { main: [[{ node: '刷新分析任务租约', type: 'main', index: 0 }]] };
decisionSourceForGeneration.connections['刷新分析任务租约'] = { main: [[{ node: '恢复章节工具上下文', type: 'main', index: 0 }]] };
decisionSourceForGeneration.connections['恢复章节工具上下文'] = { main: [[{ node: 'Call Codex For Decision', type: 'main', index: 0 }]] };
const validateDecisionOutputNode = decisionSourceForGeneration.nodes.find((node) => node.name === 'Validate Decision Output');
if (validateDecisionOutputNode?.parameters?.jsCode) {
  validateDecisionOutputNode.parameters.jsCode = validateDecisionOutputNode.parameters.jsCode
    .replace(
      "  /(?:page|block|chunk)[ _:-]?\\d+/i, /\\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\\b/i,\n  /\\b(?:phase\\s*\\d+|[GDP]\\d+)\\b/i,\n",
      '',
    )
    .replace(
      "const citations = citationSources.filter((item) => item && typeof item === 'object').map((item) => ({ ...item, citation_id: String(item.citation_id ?? item.chunk_key ?? item.document_id ?? '').trim(), document_id: String(item.document_id ?? '').trim(), chunk_id: String(item.chunk_id ?? '').trim(), title: String(item.title ?? '').trim(), source_type: String(item.source_type ?? '').trim(), source_url: String(item.source_url ?? '').trim(), page_start: item.page_start ?? null, page_end: item.page_end ?? null, section: String(item.section ?? '').trim() })).filter((item, index, items) => item.citation_id && items.findIndex((candidate) => candidate.citation_id === item.citation_id) === index);",
      `const citations = citationSources.filter((item) => item && typeof item === 'object').map((item) => ({
  citation_id: String(item.citation_id ?? item.chunk_key ?? item.document_id ?? '').trim(),
  document_id: String(item.document_id ?? '').trim(),
  title: String(item.title ?? '').trim(),
  source_type: String(item.source_type ?? '').trim(),
  source_url: String(item.source_url ?? '').trim(),
  source_locator: String(item.source_locator ?? '').trim(),
  page_start: item.page_start ?? null,
  page_end: item.page_end ?? null,
  section: String(item.section ?? '').trim(),
  dataset_id: String(item.dataset_id ?? '').trim(),
  snapshot_id: String(item.snapshot_id ?? '').trim(),
})).filter((item, index, items) => item.citation_id && items.findIndex((candidate) => candidate.citation_id === item.citation_id) === index);`,
    )
    .replace(
      "const diagnostics = (Array.isArray(response.tool_diagnostics) ? response.tool_diagnostics : []).filter((item) => item && typeof item === 'object');",
      "const diagnostics = [];",
    )
    .replace(
      "const nextDecisionState = {\n  ...state.decision_state,",
      "const { evidence_index: _discardedEvidenceIndex, ...retainedDecisionState } = state.decision_state && typeof state.decision_state === 'object' ? state.decision_state : {};\nconst nextDecisionState = {\n  ...retainedDecisionState,",
    )
    .replace("  evidence_index: { ...(state.decision_state.evidence_index ?? {}), [state.step_key]: output.citations },\n", '');
}
const stepPersistNode = decisionSourceForGeneration.nodes.find((node) => node.name === 'Persist Decision State');
if (stepPersistNode) {
  stepPersistNode.parameters.query = stepPersistNode.parameters.query
    .replace("citations = '[]'::jsonb, diagnostics = '[]'::jsonb, quality_gate = '{}'::jsonb", "citations = COALESCE(payload.value->'output'->'citations', '[]'::jsonb), diagnostics = COALESCE(payload.value->'output'->'diagnostics', '[]'::jsonb), quality_gate = COALESCE(payload.value->'output'->'quality_gate', '{}'::jsonb)");
  if (!stepPersistNode.parameters.query.includes('heartbeat_at = NOW()')) {
    stepPersistNode.parameters.query = stepPersistNode.parameters.query.replace(
      "UPDATE analysis_runs SET current_step = payload.value->>'step_key', decision_state = payload.value->'decision_state',",
      "UPDATE analysis_runs SET current_step = payload.value->>'step_key', decision_state = payload.value->'decision_state', heartbeat_at = NOW(), lease_expires_at = NOW() + INTERVAL '45 minutes',",
    );
  }
}
const graph = { nodes: [], connections: {} };

const submitNames = {
  'Receive Spatial Strategy Request': '接收分析任务',
  'Normalize Trusted Request': '校验并规范分析任务',
  'Request Is Valid': '分析任务有效？',
  'Return Validation Error': '返回分析任务校验错误',
  'Create Queued Analysis Run': '创建或恢复分析任务',
  'Build Orchestration Request': '构建分析执行上下文',
  'Start Async Decision Run': '启动异步分析',
  'Return Queued Response': '返回任务已接收',
};
const submitForGeneration = structuredClone(submitSource);
const submitQueryNode = submitForGeneration.nodes.find((node) => node.name === 'Create Queued Analysis Run');
if (submitQueryNode) {
  const resumableResultSql = `SELECT id::text AS run_id, status, current_step, created_at, request, 202 AS http_status, '' AS error_code FROM resumed
UNION ALL
SELECT id::text AS run_id, status, current_step, created_at, request, 202 AS http_status, '' AS error_code FROM created
UNION ALL
SELECT NULL::text AS run_id, NULL::text AS status, NULL::text AS current_step, NULL::timestamptz AS created_at, '{}'::jsonb AS request,
  CASE WHEN EXISTS (SELECT 1 FROM analysis_runs r WHERE r.id = NULLIF((SELECT value->>'resume_run_id' FROM payload), '')::uuid AND r.tenant_id <> (SELECT value->>'tenant_id' FROM payload)) THEN 404
    WHEN EXISTS (SELECT 1 FROM analysis_runs r WHERE r.id = NULLIF((SELECT value->>'resume_run_id' FROM payload), '')::uuid AND r.status <> 'failed') THEN 409 ELSE 404 END AS http_status,
  CASE WHEN EXISTS (SELECT 1 FROM analysis_runs r WHERE r.id = NULLIF((SELECT value->>'resume_run_id' FROM payload), '')::uuid AND r.status <> 'failed') THEN 'analysis_run_not_resumable' ELSE 'analysis_run_not_found' END AS error_code
WHERE COALESCE((SELECT value->>'resume_run_id' FROM payload), '') <> '' AND NOT EXISTS (SELECT 1 FROM resumed);`;
  submitQueryNode.parameters.query = submitQueryNode.parameters.query.replace(/SELECT id::text AS run_id, status, current_step, created_at, request FROM resumed\s+UNION ALL\s+SELECT id::text AS run_id, status, current_step, created_at, request FROM created;/, resumableResultSql);
}
const submit = localizeComponent(submitForGeneration, {
  names: submitNames,
  idPrefix: 'urban-agent-submit',
  anchor: [100, 260],
  triggerName: '__没有触发器__',
});
mergeGraph(graph, submit);
const orchestrationNode = graph.nodes.find((node) => node.name === '构建分析执行上下文');
if (orchestrationNode) {
  orchestrationNode.parameters.jsCode = orchestrationNode.parameters.jsCode.replace(
    "if (!runId) throw new Error('analysis_run_not_resumable');",
    "if (!runId) return [{ json: { response_status: Number(run.http_status ?? 500), error_code: String(run.error_code ?? 'analysis_run_not_found') } }];",
  );
}
const responseNode = graph.nodes.find((node) => node.name === '返回任务已接收');
if (responseNode) {
  responseNode.parameters.responseBody = "={{ JSON.stringify($json.response_status ? { accepted: false, status: 'error', detail: $json.error_code } : { accepted: true, run_id: $('创建或恢复分析任务').first().json.run_id, status: 'queued', current_step: 'queued', status_url: '/api/v1/analysis/spatial-strategy/runs/' + $('创建或恢复分析任务').first().json.run_id }) }}";
  responseNode.parameters.options = { responseCode: "={{ $json.response_status ?? 202 }}" };
}
const asyncNode = graph.nodes.find((node) => node.name === '启动异步分析');
if (asyncNode) {
  graph.nodes = graph.nodes.filter((node) => node !== asyncNode);
  delete graph.connections['启动异步分析'];
}
graph.connections['构建分析执行上下文'] = { main: [[{ node: '返回任务已接收', type: 'main', index: 0 }]] };

const statusNames = {
  'Receive Run Status Request': '接收任务状态查询',
  'Validate Status Request': '校验任务状态查询',
  'Status Request Is Valid': '状态查询有效？',
  'Return Invalid Status Request': '返回状态查询错误',
  'Read Tenant Scoped Run': '读取租户范围任务状态',
  'Return Run Status': '返回任务状态',
};
const status = localizeComponent(statusSource, {
  names: statusNames,
  idPrefix: 'urban-agent-status',
  anchor: [100, 980],
  triggerName: '__没有触发器__',
});
const statusQueryNode = status.nodes.find((node) => node.name === '读取租户范围任务状态');
if (statusQueryNode?.parameters?.query) {
  statusQueryNode.parameters.query = statusQueryNode.parameters.query.replace(
    "'total_steps', 12",
    "'total_steps', COALESCE(jsonb_array_length(r.decision_state->'research_plan'), 12)",
  );
}
mergeGraph(graph, status);

mergeGraph(graph, projectContextComponent);
const projectContextAttachNode = graph.nodes.find((node) => node.name === '合并项目上下文');
if (projectContextAttachNode) {
  projectContextAttachNode.parameters.jsCode = projectContextAttachNode.parameters.jsCode.replace(
    "const request = $('构建分析执行上下文').first().json;",
    "const request = $('展开领取任务请求').first()?.json ?? $('构建分析执行上下文').first().json;",
  );
}
mergeGraph(graph, failureHandlingComponent);
mergeGraph(graph, visualsComponent);
mergeGraph(graph, reportComponent);
const consumerTrigger = { parameters: { rule: { interval: [{ field: 'minutes', minutesInterval: 1 }] } }, id: 'urban-agent-consumer-trigger', name: '定时领取分析任务', type: 'n8n-nodes-base.scheduleTrigger', typeVersion: 1.2, position: [700, 1680] };
const claimQueuedNode = postgresNode('领取排队分析任务', `WITH candidate AS (
  SELECT id FROM analysis_runs
  WHERE status = 'queued' OR (status = 'running' AND lease_expires_at < NOW())
  ORDER BY CASE WHEN status = 'queued' THEN 0 ELSE 1 END, created_at
  FOR UPDATE SKIP LOCKED LIMIT 1
), claimed AS (
  UPDATE analysis_runs r SET status = 'running', workflow_execution_id = $1::text,
    current_step = COALESCE(NULLIF(r.current_step, ''), 'step_01_policy_site'), heartbeat_at = NOW(),
    lease_expires_at = NOW() + INTERVAL '45 minutes', started_at = COALESCE(r.started_at, NOW()), updated_at = NOW()
  FROM candidate WHERE r.id = candidate.id
  RETURNING r.id::text AS run_id, r.tenant_id, r.request, r.history_id, r.access_groups, r.decision_state
)
SELECT run_id, tenant_id, request, history_id, access_groups, decision_state FROM claimed;`, '={{ [$execution.id] }}', [940, 1680], 'urban-agent-claim-queued');
graph.nodes.push(consumerTrigger, claimQueuedNode);
const expandClaimNode = codeNode('展开领取任务请求', `const row = $input.first()?.json ?? {};
const request = row.request && typeof row.request === 'object' ? row.request : {};
 return [{ json: { ...request, run_id: String(row.run_id ?? request.run_id ?? ''), tenant_id: String(row.tenant_id ?? request.tenant_id ?? ''), history_id: String(row.history_id ?? request.history_id ?? ''), decision_state: row.decision_state && typeof row.decision_state === 'object' ? row.decision_state : (request.decision_state && typeof request.decision_state === 'object' ? request.decision_state : {}) } }];`, [1080, 1680], 'urban-agent-expand-claim');
graph.nodes.push(expandClaimNode);
graph.connections['定时领取分析任务'] = { main: [[{ node: '领取排队分析任务', type: 'main', index: 0 }]] };
graph.connections['领取排队分析任务'] = { main: [[{ node: '展开领取任务请求', type: 'main', index: 0 }]] };
graph.connections['展开领取任务请求'] = { main: [[{ node: '读取项目上下文', type: 'main', index: 0 }]] };
graph.connections['返回任务已接收'] = { main: [[]] };

const researchFrameNode = codeNode('构建整体研究框架', `const request = $input.first()?.json ?? {};
const existingState = request.decision_state && typeof request.decision_state === 'object' ? request.decision_state : {};
const existingFrame = String(existingState.research_frame ?? '').trim();
const existingPlan = Array.isArray(existingState.research_plan) ? existingState.research_plan : [];
if (existingFrame && existingPlan.length) {
  return [{ json: { ...request, reuse_research_frame: true, output_text: JSON.stringify({ research_frame: existingFrame, research_plan: existingPlan }) } }];
}
const context = request.project_context && typeof request.project_context === 'object' ? request.project_context : {};
const project = context.project && typeof context.project === 'object' ? context.project : {};
const documents = Array.isArray(context.documents) ? context.documents.map((item) => ({ document_id: String(item?.document_id ?? ''), title: String(item?.title ?? item?.file_name ?? ''), role: String(item?.document_role ?? '') })) : [];
const datasets = Array.isArray(context.datasets) ? context.datasets.map((item) => ({ dataset_id: String(item?.dataset_id ?? ''), title: String(item?.title ?? ''), total_count: item?.total_count ?? null })) : [];
const schema = { type: 'object', properties: {
  research_frame: { type: 'string', minLength: 1 },
  research_plan: { type: 'array', minItems: 1, maxItems: 32, items: { type: 'object', properties: {
    title: { type: 'string', minLength: 1 },
    question: { type: 'string', minLength: 1 },
  }, required: ['title', 'question'], additionalProperties: false } },
}, required: ['research_frame', 'research_plan'], additionalProperties: false };
const instructions = [
  '你是城市更新项目的首席研究设计师。此时不要写报告、定位或建议，只建立一段开放的研究框架，并列出本项目真正需要作出的决策节点。',
  '先判断用户真正需要作出的选择是什么，以及现有项目文档和空间数据库已经能支持哪些判断。提出少量真正互相竞争的解释或路径，并用现有事实和代理指标区分；不要为了形式凑假设。',
  'research_plan 只列会改变项目路径的决策边界，每个节点用自然语言写一个标题和待回答的问题。可以合并、跳过或改写常见的政策、市场、客群、定位、产品、空间、运营、财务和分期视角；不相关的视角不要为了凑数量保留。节点数量由问题复杂度决定，只保留必要的节点并避免重复。节点应能按依赖关系排列，但不要把它写成固定章节模板。',
  '明确节点之间的关键依赖关系，让后续证据能够逐步缩小候选解释并形成项目选择。',
  '研究框架是开放式工作备忘录，不是审计表，不使用固定字段、编号模板或预设答案。只围绕现有证据能够回答的项目问题组织研究，不输出缺失信息、不能证明事项或“必须补齐证据”清单。',
].join('\\n');
return [{ json: {
  ...request,
  instructions,
  input: JSON.stringify({ project_question: request.project_question, project, available_documents: documents, available_datasets: datasets }),
  max_output_tokens: 10000,
  reasoning: { effort: 'high' },
  text: { format: { type: 'json_schema', name: 'research_frame', strict: true, schema } },
} }];`, [1460, 1660], 'urban-agent-build-research-frame');
graph.nodes.push(researchFrameNode);
const reuseResearchFrameNode = {
  parameters: {
    conditions: {
      options: { caseSensitive: true, leftValue: '', typeValidation: 'strict', version: 2 },
      conditions: [{
        id: 'reuse-existing-research-frame',
        leftValue: '={{ $json.reuse_research_frame === true }}',
        rightValue: true,
        operator: { type: 'boolean', operation: 'true', singleValue: true },
      }],
      combinator: 'and',
    },
    options: {},
  },
  id: 'urban-agent-reuse-research-frame',
  name: '复用已有研究框架？',
  type: 'n8n-nodes-base.if',
  typeVersion: 2.2,
  position: [1680, 1660],
};
graph.nodes.push(reuseResearchFrameNode);
const researchFrameModel = localizeComponent(responsesSource, {
  names: {
    'Build Responses Request': '构建研究框架请求体',
    'Call Codex Relay': '请求研究框架模型',
    'Normalize Responses Output': '解析研究框架响应',
  },
  idPrefix: 'urban-agent-research-frame-model',
  anchor: [1700, 1660],
  triggerName: 'When Called By Agent',
});
mergeGraph(graph, researchFrameModel);
connect(graph, '构建整体研究框架', '复用已有研究框架？');
const validateResearchFrameNode = codeNode('确认整体研究框架', `const response = $input.first()?.json ?? {};
let parsed;
const raw = String(response.output_text ?? '').trim();
const candidates = [raw];
const fenced = raw.match(/^\\s*\`\`\`(?:json)?\\s*([\\s\\S]*?)\\s*\`\`\`\\s*$/i);
if (fenced?.[1]) candidates.push(fenced[1].trim());
const firstBrace = raw.indexOf('{');
const lastBrace = raw.lastIndexOf('}');
if (firstBrace >= 0 && lastBrace > firstBrace) candidates.push(raw.slice(firstBrace, lastBrace + 1));
for (const candidate of candidates) {
  if (!candidate) continue;
  try { parsed = JSON.parse(candidate); break; } catch {}
}
if (!parsed) throw new Error('research_frame_invalid_json');
const existingState = response.decision_state && typeof response.decision_state === 'object' ? response.decision_state : {};
const researchFrame = String(existingState.research_frame ?? parsed.research_frame ?? '').trim();
if (!researchFrame) throw new Error('research_frame_empty');
const parsedPlan = (Array.isArray(parsed.research_plan) ? parsed.research_plan : []).map((item) => ({
  title: String(item?.title ?? '').trim(),
  question: String(item?.question ?? '').trim(),
})).filter((item) => item.title && item.question).slice(0, 32);
const existingPlan = Array.isArray(existingState.research_plan) ? existingState.research_plan.map((item) => ({ title: String(item?.title ?? '').trim(), question: String(item?.question ?? '').trim(), step_key: String(item?.step_key ?? '').trim() })).filter((item) => item.title && item.question) : [];
const researchPlan = existingPlan.length ? existingPlan : parsedPlan;
if (!researchPlan.length) throw new Error('research_plan_empty');
return [{ json: { ...response, research_frame: researchFrame, research_plan: researchPlan } }];`, [2460, 1660], 'urban-agent-validate-research-frame');
graph.nodes.push(validateResearchFrameNode);
graph.connections['复用已有研究框架？'] = { main: [
  [{ node: '确认整体研究框架', type: 'main', index: 0 }],
  [{ node: researchFrameModel.entries[0], type: 'main', index: 0 }],
] };
for (const terminal of researchFrameModel.terminals) connect(graph, terminal, '确认整体研究框架');

const queueNode = codeNode('建立自适应分析队列', `const claimed = $input.first()?.json ?? {};
const request = $('确认整体研究框架').first().json;
const candidatePlan = Array.isArray(request.decision_state?.research_plan) && request.decision_state.research_plan.length
  ? request.decision_state.research_plan
  : (Array.isArray(request.research_plan) ? request.research_plan : []);
const adaptiveSteps = candidatePlan.map((item, index) => ({
  step_key: String(item?.step_key ?? 'decision_' + String(index + 1).padStart(2, '0')),
  step_title: String(item?.title ?? '').trim(),
  research_brief: String(item?.question ?? '').trim(),
})).filter((item) => item.step_title && item.research_brief).slice(0, 32);
if (!adaptiveSteps.length) throw new Error('research_plan_empty');
const steps = adaptiveSteps;
const researchPlan = steps.map(({ step_key, step_title, research_brief }) => ({ step_key, title: step_title, question: research_brief }));
return steps.map(({ step_key, step_title, research_brief }, index) => ({ json: {
  run_id: String(claimed.run_id ?? request.run_id), tenant_id: request.tenant_id,
  history_id: request.history_id, project_question: request.project_question,
  access_groups: request.access_groups, project_types: request.project_types,
  geography: request.geography, metadata_filter: request.metadata_filter,
  project_context: request.project_context, research_frame: request.research_frame,
  research_plan: researchPlan,
  decision_state: { ...(request.decision_state && typeof request.decision_state === 'object' ? request.decision_state : {}), research_frame: request.research_frame, research_plan: researchPlan },
  step_key, step_title, research_brief, step_order: index + 1,
} }));`, [1540, 1860], 'urban-agent-build-step-queue');
const loopNode = {
  parameters: { batchSize: 1, options: {} },
  id: 'urban-agent-step-loop', name: '逐项执行分析方向',
  type: 'n8n-nodes-base.splitInBatches', typeVersion: 3, position: [1800, 1860],
};
const readStateNode = postgresNode('读取最新分析状态', `SELECT $1::jsonb AS step_input, decision_state
FROM analysis_runs WHERE id = ($1::jsonb->>'run_id')::uuid AND tenant_id = $1::jsonb->>'tenant_id';`,
  '={{ [JSON.stringify($json)] }}', [2060, 1940], 'urban-agent-read-current-state');
const attachStateNode = codeNode('合并当前分析方向状态', `const row = $input.first()?.json ?? {};
const input = row.step_input && typeof row.step_input === 'object' ? row.step_input : {};
const stored = row.decision_state && typeof row.decision_state === 'object' ? row.decision_state : {};
const queued = input.decision_state && typeof input.decision_state === 'object' ? input.decision_state : {};
return [{ json: { ...input, decision_state: { ...queued, ...stored, research_plan: Array.isArray(stored.research_plan) ? stored.research_plan : queued.research_plan, research_frame: String(stored.research_frame ?? queued.research_frame ?? '') } } }];`,
  [2300, 1940], 'urban-agent-attach-step-state');
const readCompleteStateNode = postgresNode('读取完整分析状态', `SELECT id::text AS run_id, status, current_step, decision_state
FROM analysis_runs WHERE id = $1::uuid AND tenant_id = $2::text;`,
  "={{ [$('合并项目上下文').first().json.run_id, $('合并项目上下文').first().json.tenant_id] }}",
  [2060, 1780], 'urban-agent-read-complete-state');
graph.nodes.push(queueNode, loopNode, readStateNode, attachStateNode, readCompleteStateNode);
graph.connections['合并项目上下文'] = { main: [[{ node: '构建整体研究框架', type: 'main', index: 0 }], [{ node: '记录任务失败', type: 'main', index: 0 }]] };
connect(graph, '确认整体研究框架', '建立自适应分析队列');
connect(graph, '建立自适应分析队列', '逐项执行分析方向');
graph.connections['逐项执行分析方向'] = { main: [
  [{ node: '读取完整分析状态', type: 'main', index: 0 }],
  [{ node: '读取最新分析状态', type: 'main', index: 0 }],
] };
connect(graph, '读取最新分析状态', '合并当前分析方向状态');
connect(graph, '读取完整分析状态', '构建图件设计请求');

const decisionNames = {
  'Validate Step Request': '校验当前分析方向', 'Step Already Completed': '当前方向已完成？',
  'Return Existing Step Result': '复用已完成章节', 'Mark Step Running': '标记当前方向执行中',
  'Select Initial Project Document': '选择首个项目文档', 'Has Initial Project Document': '存在项目文档？',
  'Read Initial Project Document': '预读项目文档正文', 'Attach Initial Project Document': '注入项目文档正文',
  'Build Structured Decision Request': '构建证据路由请求', 'Call Codex For Decision': '调用证据路由 Agent',
  'Agent Has Tool Calls': '路由 Agent 请求工具？', 'Prepare MCP Agent Tool Call': '准备证据路由工具调用',
  'Call Spatial MCP Tool': '执行证据工具', 'Build MCP Agent Follow-up': '更新证据简报',
  'Fail MCP Agent Tool Call': '记录项目工具调用失败', 'Validate Decision Output': '校验章节正文',
  'Persist Decision State': '保存章节与分析状态', 'Return Step Result': '完成当前分析方向',
};
const decision = localizeComponent(decisionSourceForGeneration, {
  names: decisionNames, idPrefix: 'urban-agent-decision', anchor: [2560, 1940], triggerName: 'When Called By Orchestrator',
});
for (const node of decision.nodes) {
  if (typeof node.parameters?.jsCode !== 'string') continue;
  node.parameters.jsCode = node.parameters.jsCode
    .replace("$('Build Structured Decision Request').item.json", "$('Build Structured Decision Request').first().json")
    .replace("$('Prepare MCP Agent Tool Call').item.json", "$('Prepare MCP Agent Tool Call').first().json")
    .replace("$('构建证据路由请求').item.json", "$('构建证据路由请求').first().json")
    .replace("$('准备证据路由工具调用').item.json", "$('准备证据路由工具调用').first().json");
}
mergeGraph(graph, decision);
graph.nodes = graph.nodes.filter((node) => node.name !== '记录项目工具调用失败');
delete graph.connections['记录项目工具调用失败'];
graph.connections['执行证据工具'] = { main: [[{ node: '更新证据简报', type: 'main', index: 0 }]] };
connect(graph, '合并当前分析方向状态', decision.entries[0]);
connect(graph, '复用已完成章节', '逐项执行分析方向');
connect(graph, '完成当前分析方向', '逐项执行分析方向');

const validateEvidenceRoute = codeNode(
  '校验证据路由决策',
  `const response = $input.first()?.json ?? {};
const raw = String(response.output_text ?? '').trim();
let route;
const candidates = [raw];
const fenced = raw.match(/^\\s*\`\`\`(?:json)?\\s*([\\s\\S]*?)\\s*\`\`\`\\s*$/i);
if (fenced?.[1]) candidates.push(fenced[1].trim());
const firstBrace = raw.indexOf('{');
const lastBrace = raw.lastIndexOf('}');
if (firstBrace >= 0 && lastBrace > firstBrace) candidates.push(raw.slice(firstBrace, lastBrace + 1));
for (const candidate of candidates) {
  if (!candidate) continue;
  try { route = JSON.parse(candidate); break; } catch {}
}
if (!route) {
  const incompleteReason = String(response.incomplete_details?.reason ?? response.error?.message ?? response.status ?? 'unknown').slice(0, 120);
  const outputTypes = (Array.isArray(response.output_types) ? response.output_types : []).map((item) => String(item?.type ?? '') + '[' + (Array.isArray(item?.content_types) ? item.content_types.join(',') : '') + ']').join('|').slice(0, 240);
  throw new Error('evidence_route_invalid_json_' + incompleteReason + '_chars_' + String(raw.length) + '_types_' + (outputTypes || 'none'));
}
if (!['continue', 'finish'].includes(route.decision)) throw new Error('evidence_route_invalid_decision');
if (!String(route.reason ?? '').trim()) throw new Error('evidence_route_reason_empty');
const allowed = new Set(['analyze_spatial_evidence', 'read_project_document', 'read_previous_chapter', 'search_literature_evidence', 'search_public_web', 'fetch_public_web_page']);
const required = { analyze_spatial_evidence: ['analysis'], read_project_document: ['document_id'], search_literature_evidence: ['question'], search_public_web: ['query'], fetch_public_web_page: ['urls'] };
const allowedKeys = {
  analyze_spatial_evidence: new Set(['analysis', 'metric_ids', 'selectors', 'distance_bands_m', 'neighbor_steps', 'rank_order', 'top_k', 'record_refs']),
  read_project_document: new Set(['document_id', 'start_block', 'max_blocks', 'page_start', 'page_end']),
  read_previous_chapter: new Set(['step_key', 'step_order']),
  search_literature_evidence: new Set(['question', 'mode', 'top_k']),
  search_public_web: new Set(['query', 'provider', 'limit']),
  fetch_public_web_page: new Set(['urls', 'provider', 'max_characters']),
};
if (Object.prototype.hasOwnProperty.call(route, 'next_tool')) throw new Error('evidence_route_legacy_next_tool_forbidden');
if (!Array.isArray(route.next_tools)) throw new Error('evidence_route_next_tools_invalid');
const nextTools = route.next_tools;
const stable = (value) => {
  if (Array.isArray(value)) return '[' + value.map(stable).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.keys(value).sort().map((key) => JSON.stringify(key) + ':' + stable(value[key])).join(',') + '}';
  return JSON.stringify(value);
};
if (route.decision === 'continue') {
  if (response.stop_reason) throw new Error('evidence_route_continue_after_stop:' + String(response.stop_reason));
  const maxParallel = Math.max(1, Math.min(3, Number(response.max_parallel_tools ?? 3)));
  // Keep research strategy in the router. An empty continue batch is sent back to
  // the same router with a concise contract correction instead of selecting a tool
  // in workflow code or failing the whole chapter.
  if (nextTools.length === 0) {
    const retryCount = Math.max(0, Number(response.route_format_retry_count ?? 0));
    if (retryCount >= 4) throw new Error('evidence_route_empty_continue_after_retry');
    const priorInput = Array.isArray(response.input) ? response.input : [];
    const correctedInput = [...priorInput, { role: 'user', content: [{ type: 'input_text', text: '你的 decision=continue，但 next_tools 为空。请重新路由：若仍需取证，返回一至三个参数完整且相互独立的请求；若证据已经足够，返回 decision=finish 且 next_tools=[]。如果当前 research_brief 涉及区域结构、功能差异或机会判断，而 working_research_brief 只有项目文档或 scope 指标目录、尚无 groups/highlights/relationship 等具体空间结果，你必须自行选择一个具体的 analyze_spatial_evidence 模式（例如 rank、relationship、distance、direction、neighborhood 或 inspect）并返回完整参数。不要写研究结论。' }] }];
    const routeDiagnostics = [...(Array.isArray(response.route_diagnostics) ? response.route_diagnostics : []), { kind: 'empty_continue_batch_retry', attempt: retryCount + 1 }];
    return [{ json: { ...response, route_retry_required: true, route_format_retry_count: retryCount + 1, route_decision: null, route_diagnostics: routeDiagnostics, input: correctedInput, conversation_items: correctedInput, tool_calls: [], output: [], output_text: '', response_id: '', error: null, tool_choice: 'none' } }];
  }
  const seen = new Set();
  let validated;
  try {
    validated = nextTools.map((next, index) => {
    if (!next || typeof next !== 'object' || Array.isArray(next) || !allowed.has(String(next.name))) throw new Error('evidence_route_tool_missing');
    for (const key of Object.keys(next)) if (!['name', 'arguments'].includes(key)) throw new Error('evidence_route_tool_field_not_allowed:' + key);
    const name = String(next.name);
    const args = next.arguments && typeof next.arguments === 'object' && !Array.isArray(next.arguments) ? Object.fromEntries(Object.entries(next.arguments).filter(([, value]) => value !== null && value !== undefined)) : {};
    const optionalIntegerKeys = ['start_block', 'max_blocks', 'page_start', 'page_end', 'neighbor_steps', 'top_k', 'limit', 'max_characters', 'step_order'];
    for (const key of optionalIntegerKeys) {
      if (!Object.prototype.hasOwnProperty.call(args, key)) continue;
      const value = args[key];
      if (Number.isInteger(value)) continue;
      if (typeof value === 'string' && /^\\d+$/.test(value.trim())) { args[key] = Number(value.trim()); continue; }
      delete args[key];
    }
    if (Object.prototype.hasOwnProperty.call(args, 'history_id')) throw new Error('history_id_must_be_injected');
    for (const key of Object.keys(args)) if (!allowedKeys[name].has(key)) throw new Error('evidence_route_argument_not_allowed:' + key);
    for (const key of (required[name] ?? [])) if (args[key] === undefined || args[key] === null || (typeof args[key] === 'string' && !args[key].trim()) || (Array.isArray(args[key]) && args[key].length === 0)) throw new Error('evidence_route_argument_missing:' + key);
    const fingerprint = stable({ name, arguments: args });
    if (seen.has(fingerprint)) throw new Error('evidence_route_duplicate_tool_request');
    seen.add(fingerprint);
    return { name, arguments: args, requested_index: index };
    });
  } catch (error) {
    const message = String(error?.message ?? error);
    const recoverable = message.startsWith('evidence_route_argument_missing:') || message.startsWith('evidence_route_argument_not_allowed:');
    const retryCount = Math.max(0, Number(response.route_format_retry_count ?? 0));
    if (!recoverable || retryCount >= 4) throw error;
    const priorInput = Array.isArray(response.input) ? response.input : [];
    const correctedInput = [...priorInput, { role: 'user', content: [{ type: 'input_text', text: '上一批工具请求参数不完整或包含未允许字段（' + message + '）。请重新输出 decision：continue 时只返回一至三个参数完整、彼此独立且符合工具契约的请求；finish 时 next_tools=[]。不要猜测缺失的 urls、query、metric_ids 或 record_refs。' }] }];
    const routeDiagnostics = [...(Array.isArray(response.route_diagnostics) ? response.route_diagnostics : []), { kind: 'invalid_tool_arguments_retry', message, attempt: retryCount + 1 }];
    return [{ json: { ...response, route_retry_required: true, route_format_retry_count: retryCount + 1, route_decision: null, route_diagnostics: routeDiagnostics, input: correctedInput, conversation_items: correctedInput, tool_calls: [], output: [], output_text: '', response_id: '', error: null, tool_choice: 'none' } }];
  }
  const callLimit = Math.max(1, Number(response.tool_call_limit ?? 12));
  const remainingCalls = Math.max(0, callLimit - Number(response.tool_call_count ?? 0));
  if (remainingCalls < 1) throw new Error('evidence_route_tool_call_limit_reached');
  const selected = validated.slice(0, Math.min(maxParallel, remainingCalls));
  const trimmedCount = validated.length - selected.length;
  const turn = Number(response.agent_turn ?? 0);
  const toolCalls = selected.map((next, index) => ({
    call_id: 'route-' + String(turn) + '-' + String(index) + '-' + next.name,
    name: next.name,
    arguments: next.arguments,
    batch_index: index,
    batch_size: selected.length,
    status: 'completed',
  }));
  const routeDiagnostics = [...(Array.isArray(response.route_diagnostics) ? response.route_diagnostics : [])];
  if (validated.length > maxParallel) routeDiagnostics.push({ kind: 'batch_trimmed_to_max_parallel', requested: validated.length, executed: Math.min(maxParallel, remainingCalls) });
  if (trimmedCount > 0 && validated.length <= maxParallel) routeDiagnostics.push({ kind: 'batch_trimmed_to_remaining_budget', requested: validated.length, executed: selected.length });
  return [{ json: { ...response, route_decision: route, route_diagnostics: routeDiagnostics, tool_calls: toolCalls, output: [], output_text: JSON.stringify(route), tool_choice: 'none' } }];
}
if (nextTools.length !== 0) throw new Error('evidence_route_finish_has_tool');
return [{ json: { ...response, route_retry_required: false, route_decision: route, tool_calls: [], output: [], output_text: JSON.stringify(route), tool_choice: 'none' } }];`,
  [4240, 1940],
  'urban-agent-validate-evidence-route',
);
const researchAnalysisRequest = codeNode(
  '构建章节研究分析请求',
  `const routed = $input.first()?.json ?? {};
const route = routed.route_decision && typeof routed.route_decision === 'object' ? routed.route_decision : null;
if (!route || route.decision !== 'finish') throw new Error('evidence_route_finish_missing');
const request = $('构建证据路由请求').first().json;
const state = request.state && typeof request.state === 'object' ? request.state : {};
const brief = routed.working_research_brief && typeof routed.working_research_brief === 'object' ? routed.working_research_brief : { version: 1, cards: [] };
const previousDecisions = Object.entries(state.decision_state?.steps ?? {}).map(([stepKey, value]) => ({
  step_key: stepKey,
  step_order: Number(value?.step_order ?? 0),
  title: String(value?.title ?? ''),
  decision_brief: String(value?.decision_brief ?? '').slice(0, 2000),
})).filter((item) => item.decision_brief && item.step_order < Number(state.step_order ?? 0));
const input = [{ role: 'user', content: [{ type: 'input_text', text: JSON.stringify({
  project_question: state.project_question,
  research_frame: state.research_frame || state.decision_state?.research_frame || '',
  chapter_title: state.step_title,
  research_brief: state.research_brief,
  previous_decisions: previousDecisions,
  project_document_prefetch: state.project_document_prefetch ?? null,
  evidence_brief: brief,
}) }] }];
return [{ json: {
  ...routed,
  state,
  input,
  conversation_items: input,
  instructions: '你是当前章节的研究分析 Agent。证据获取已经结束；现在独立、完整地分析输入中的项目任务、项目文档正文、空间数据、文献和网页证据。你不受证据路由 Agent 的简短 JSON、低推理配置或工具调用规则约束。自由选择最适合问题的分析结构，比较证据、解释关系、识别取舍并形成可供写作 Agent 使用的深入研究备忘录。只讨论现有证据实际支持且会改变本章判断的内容；与本章结论无关的缺失信息、不能证明事项或补数清单直接省略。不要写工具调用建议，不要讨论工作流，也不要套固定章节模板。输出自由文本研究备忘录。',
  tools: [],
  tool_choice: 'none',
  parallel_tool_calls: false,
  text: undefined,
  max_output_tokens: 10000,
  reasoning: { effort: 'medium' },
  output: [],
  output_text: '',
  tool_calls: [],
} }];`,
  [4480, 2180],
  'urban-agent-research-analysis-request',
);
const researchAnalysisPlaceholder = codeNode(
  '调用章节研究分析模型',
  'return $input.all();',
  [4740, 2180],
  'urban-agent-research-analysis',
);
const independentDraftRequest = codeNode(
  '构建独立章节成稿请求',
  `const researchResponse = $input.first()?.json ?? {};
const request = $('构建证据路由请求').first().json;
const researchMemo = String(researchResponse.output_text ?? '').trim();
if (!researchMemo) throw new Error('chapter_research_memo_empty');
const schema = {
  type: 'object',
  properties: { decision_brief: { type: 'string', minLength: 1 }, reader_chapter: { type: 'string', minLength: 1 } },
  required: ['decision_brief', 'reader_chapter'],
  additionalProperties: false,
};
const brief = researchResponse.working_research_brief && typeof researchResponse.working_research_brief === 'object' ? researchResponse.working_research_brief : {};
const previousDecisions = Object.entries(request.state.decision_state?.steps ?? {}).map(([stepKey, value]) => ({
  step_key: stepKey,
  step_order: Number(value?.step_order ?? 0),
  title: String(value?.title ?? ''),
  decision_brief: String(value?.decision_brief ?? '').slice(0, 1600),
})).filter((item) => item.decision_brief && item.step_order < Number(request.state.step_order ?? 0));
const input = [{ role: 'user', content: [{ type: 'input_text', text: JSON.stringify({
  project_question: request.state.project_question,
  research_frame: request.state.research_frame || request.state.decision_state?.research_frame || '',
  chapter_title: request.state.step_title,
  research_brief: request.state.research_brief,
  previous_decisions: previousDecisions,
  project_document_prefetch: request.state.project_document_prefetch ?? null,
  working_research_brief: brief,
  research_memo: researchMemo,
}) }] }];
return [{ json: {
  ...researchResponse,
  state: request.state,
  input,
  conversation_items: input,
  initial_context_items: input,
  instructions: '你是独立的章节写作 Agent。根据输入中的研究备忘录及其证据背景，撰写面向项目甲方、政府决策者、投资人和非技术评审者的完整中文章节。自由组织最适合内容的结构，清楚呈现本章的新判断、依据、关系和取舍。只写会改变判断的证据边界；与结论无关的缺失信息和“不能证明什么”不写，也不生成补数清单。不要提及工具、工作流、上下文或研究阶段；不要原样输出 record_ref、metric_id、数据库字段名或其他内部标识，把它们改写为普通中文指标名称。只返回 decision_brief 与 reader_chapter。',
  tools: [],
  tool_choice: 'none',
  parallel_tool_calls: false,
  text: { format: { type: 'json_schema', name: 'reader_chapter', strict: true, schema } },
  max_output_tokens: 10000,
  reasoning: { effort: 'high' },
} }];`,
  [5260, 2260],
  'urban-agent-independent-draft-request',
);
const independentDraftPlaceholder = codeNode(
  '调用独立章节成稿模型',
  'return $input.all();',
  [5520, 2260],
  'urban-agent-independent-draft',
);
graph.nodes.push(validateEvidenceRoute, researchAnalysisRequest, researchAnalysisPlaceholder, independentDraftRequest, independentDraftPlaceholder);
const routeRetryDecision = {
  parameters: {
    conditions: {
      options: { caseSensitive: true, leftValue: '', typeValidation: 'strict', version: 2 },
      conditions: [{
        id: 'evidence-route-retry-required',
        leftValue: '={{ $json.route_retry_required === true }}',
        rightValue: true,
        operator: { type: 'boolean', operation: 'true', singleValue: true },
      }],
      combinator: 'and',
    },
    options: {},
  },
  id: 'urban-agent-evidence-route-retry-required',
  name: '证据路由需要修正？',
  type: 'n8n-nodes-base.if',
  typeVersion: 2.2,
  position: [4460, 1940],
};
graph.nodes.push(routeRetryDecision);
const agentToolDecision = graph.connections['路由 Agent 请求工具？']?.main ?? [[], []];
agentToolDecision[1] = [{ node: '构建章节研究分析请求', type: 'main', index: 0 }];
graph.connections['路由 Agent 请求工具？'] = { main: agentToolDecision };
graph.connections['构建章节研究分析请求'] = { main: [[{ node: '调用章节研究分析模型', type: 'main', index: 0 }]] };
graph.connections['调用章节研究分析模型'] = { main: [[{ node: '构建独立章节成稿请求', type: 'main', index: 0 }]] };
graph.connections['构建独立章节成稿请求'] = { main: [[{ node: '调用独立章节成稿模型', type: 'main', index: 0 }]] };
graph.connections['调用独立章节成稿模型'] = { main: [[{ node: '校验章节正文', type: 'main', index: 0 }]] };

function inlineResponses(targetName, prefix, anchor, labels) {
  const names = {
    'Build Responses Request': labels[0], 'Call Codex Relay': labels[1], 'Normalize Responses Output': labels[2],
  };
  const fragment = localizeComponent(responsesSource, {
    names, idPrefix: prefix, anchor, triggerName: 'When Called By Agent',
  });
  replaceNodeWithFragment(graph, targetName, fragment);
}
inlineResponses('调用证据路由 Agent', 'urban-agent-evidence-router', [5000, 1760], ['构建证据路由请求体', '请求证据路由模型', '解析证据路由响应']);
const evidenceRouterModelNode = graph.nodes.find((node) => node.name === '请求证据路由模型');
if (evidenceRouterModelNode) {
  evidenceRouterModelNode.parameters.options = evidenceRouterModelNode.parameters.options ?? {};
  evidenceRouterModelNode.parameters.options.timeout = 120000;
  evidenceRouterModelNode.retryOnFail = true;
  evidenceRouterModelNode.maxTries = 2;
  evidenceRouterModelNode.waitBetweenTries = 2000;
}
graph.connections['解析证据路由响应'] = { main: [[{ node: '校验证据路由决策', type: 'main', index: 0 }]] };
graph.connections['校验证据路由决策'] = { main: [[{ node: '证据路由需要修正？', type: 'main', index: 0 }]] };
graph.connections['证据路由需要修正？'] = { main: [
  [{ node: '构建证据路由请求体', type: 'main', index: 0 }],
  [{ node: '路由 Agent 请求工具？', type: 'main', index: 0 }],
] };
inlineResponses('调用章节研究分析模型', 'urban-agent-research-analysis-model', [4740, 2180], ['构建章节研究模型请求体', '请求章节研究模型', '解析章节研究模型响应']);
inlineResponses('调用独立章节成稿模型', 'urban-agent-independent-draft-model', [5000, 2260], ['构建独立成稿请求体', '请求独立章节成稿模型', '解析独立章节成稿响应']);
inlineResponses('调用图件设计模型', 'urban-agent-visual-model', [1800, 3300], ['构建图件模型请求体', '请求图件设计模型', '解析图件模型响应']);
inlineResponses('调用报告叙事模型', 'urban-agent-editorial-model', [3000, 3300], ['构建叙事模型请求体', '请求报告叙事模型', '解析叙事模型响应']);
graph.connections['需要发送飞书？'] = { main: [
  [{ node: '生成 Word 报告并发送飞书', type: 'main', index: 0 }],
  [{ node: '完成分析任务', type: 'main', index: 0 }],
] };
const restoreDeliveredReportNode = codeNode(
  '恢复已发送报告上下文',
  `return [{ json: $('生成最终报告').first().json }];`,
  [4480, 3500],
  'urban-agent-restore-delivered-report',
);
graph.nodes.push(restoreDeliveredReportNode);
connect(graph, '生成 Word 报告并发送飞书', '恢复已发送报告上下文');
connect(graph, '恢复已发送报告上下文', '完成分析任务');
for (const nodeName of ['请求图件设计模型', '请求报告叙事模型']) {
  const node = graph.nodes.find((item) => item.name === nodeName);
  if (!node) continue;
  node.maxTries = 3;
  node.waitBetweenTries = 120000;
}
const finalLeaseNode = postgresNode('刷新报告阶段租约', `UPDATE analysis_runs
SET heartbeat_at = NOW(), lease_expires_at = NOW() + INTERVAL '45 minutes', updated_at = NOW()
WHERE id = $1::uuid AND tenant_id = $2::text AND status = 'running';
SELECT $1::text AS run_id;`, "={{ [$('读取完整分析状态').first().json.run_id, $('合并项目上下文').first().json.tenant_id] }}", [1280, 3180], 'urban-agent-refresh-report-lease');
const restoreVisualsNode = codeNode('恢复报告图件上下文', `return [{ json: $('整理项目图件').first().json }];`, [1500, 3180], 'urban-agent-restore-report-context');
graph.nodes.push(finalLeaseNode, restoreVisualsNode);
const completeNode = graph.nodes.find((node) => node.name === '完成分析任务');
if (completeNode) {
  completeNode.parameters.options = completeNode.parameters.options ?? {};
  completeNode.parameters.options.queryReplacement = "={{ [String($('读取完整分析状态').first().json.run_id ?? $('合并项目上下文').first().json.run_id ?? ''), JSON.stringify($('读取完整分析状态').first().json.decision_state ?? {}), String($json.markdown ?? ''), JSON.stringify($json.citations ?? []), JSON.stringify($json.asset_manifest ?? {})] }}";
}
connect(graph, '整理项目图件', '刷新报告阶段租约');
connect(graph, '刷新报告阶段租约', '恢复报告图件上下文');
connect(graph, '恢复报告图件上下文', '构建报告叙事请求');

const failNodeName = '记录任务失败';
const executionNodes = new Set();
const pendingExecutionNodes = ['读取项目上下文'];
while (pendingExecutionNodes.length) {
  const current = pendingExecutionNodes.pop();
  for (const output of graph.connections[current]?.main ?? []) {
    for (const edge of output ?? []) {
      if (edge.node === failNodeName || executionNodes.has(edge.node)) continue;
      executionNodes.add(edge.node);
      pendingExecutionNodes.push(edge.node);
    }
  }
}
for (const node of graph.nodes) {
  if (!executionNodes.has(node.name) || node.name === failNodeName) continue;
  if (!['n8n-nodes-base.code', 'n8n-nodes-base.httpRequest', 'n8n-nodes-base.postgres'].includes(node.type)) continue;
  if (node.name === '执行证据工具') {
    node.onError = 'continueRegularOutput';
    graph.connections[node.name] = { ...(graph.connections[node.name] ?? {}), main: [[{ node: '更新证据简报', type: 'main', index: 0 }]] };
    continue;
  }
  node.onError = 'continueErrorOutput';
  const main = graph.connections[node.name]?.main ?? [];
  while (main.length < 2) main.push([]);
  if ((main[1] ?? []).length === 0) {
    main[1] = [...(main[1] ?? []), { node: failNodeName, type: 'main', index: 0 }];
  }
  graph.connections[node.name] = { ...(graph.connections[node.name] ?? {}), main };
}

for (const node of graph.nodes) {
  if (node.name === '读取项目上下文') node.position = [1120, 1860];
  if (node.name === '合并项目上下文') node.position = [1300, 1860];
  if (node.name === '记录任务失败') node.position = [6600, 2200];
}

graph.nodes.push(
  sticky('任务入口说明', '## 提交与状态查询\n提交只创建队列项并立即返回 202；定时消费者独立领取任务。状态查询保持租户隔离。', [60, 40], [950, 1320], 'urban-agent-note-entry'),
  sticky('自适应循环说明', '## 自适应决策方向\n研究框架先提出本项目真正需要的决策节点；检索、Agent、工具调用和保存节点只保留一份。', [1040, 1560], [5700, 1500], 'urban-agent-note-loop'),
  sticky('报告生成说明', '## 图件与最终报告\n已完成的决策方向共同形成报告；设计真实数据图件、组织叙事并按需发送飞书。', [1040, 3140], [4700, 980], 'urban-agent-note-report'),
);

export default assertFormalWorkflow({
  id: 'urbanRenewalDecisionSupportAgent',
  name: '城市更新决策支持 Agent', active: true,
  nodes: graph.nodes, connections: graph.connections,
  settings: { executionOrder: 'v1', executionTimeout: 14400 },
  versionId: 'ad07173c-d412-4859-8924-265ed2aedc18',
  meta: { templateCredsSetupCompleted: true }, tags: [],
});
