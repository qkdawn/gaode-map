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

const CORE_AGENT_PROMPT = '基于已有项目材料和空间数据完成用户任务，给出明确判断及行动建议。不要虚构信息；无法完成时直接说明原因。';
const agentPrompt = (...instructions) => [CORE_AGENT_PROMPT, ...instructions].join('\n');

// Keep the planning/research model configurable while giving the high-volume
// evidence router a fast model without changing the normal analysis agents.
const responsesSourceForGeneration = structuredClone(responsesSource);
const responsesRequestBuilder = responsesSourceForGeneration.nodes.find((node) => node.name === 'Build Responses Request');
if (responsesRequestBuilder?.parameters?.jsCode) {
  responsesRequestBuilder.parameters.jsCode = responsesRequestBuilder.parameters.jsCode.replace(
    "model: '__CODEX_RELAY_MODEL__'",
    "model: String(input.model ?? '__CODEX_RELAY_MODEL__')",
  );
}

// The planner creates dynamic decision units. Evidence routing, unit analysis,
// cross-unit synthesis, and report-section writing are separate stages.
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
if (buildDecisionRequestNode) {
  buildDecisionRequestNode.parameters.jsCode = `const state = $('Validate Step Request').first().json;
const decisionUnit = state.decision_unit && typeof state.decision_unit === 'object' ? state.decision_unit : null;
if (!decisionUnit || !String(decisionUnit.unit_id ?? '').trim() || !String(decisionUnit.question ?? '').trim() || !String(decisionUnit.decision_output ?? '').trim() || !String(decisionUnit.evidence_focus ?? '').trim()) throw new Error('decision_unit_required');
const previousDecisionMemos = Object.entries(state.decision_state?.steps ?? {}).map(([unitId, value]) => ({
  unit_id: unitId,
  step_order: Number(value?.step_order ?? 0),
  title: String(value?.title ?? ''),
  decision_output: String(value?.decision_output ?? ''),
  decision_memo: value?.decision_memo && typeof value.decision_memo === 'object' ? value.decision_memo : null,
  evidence_directory: {
    key_facts: Array.isArray(value?.decision_memo?.key_facts) ? value.decision_memo.key_facts : [],
    named_entities: Array.isArray(value?.decision_memo?.named_entities) ? value.decision_memo.named_entities : [],
    sources: Array.isArray(value?.citations) ? value.citations.map((item) => ({ title: String(item?.title ?? ''), source_type: String(item?.source_type ?? ''), source_locator: String(item?.source_locator ?? '') })) : [],
  },
})).filter((item) => item.decision_memo && item.step_order < Number(state.step_order ?? 0)).sort((left, right) => left.step_order - right.step_order);
const dependencyIds = new Set(Array.isArray(decisionUnit.depends_on) ? decisionUnit.depends_on.map(String) : []);
const dependencyMemos = previousDecisionMemos.filter((item) => dependencyIds.has(item.unit_id));
const projectDocuments = (Array.isArray(state.project_context?.documents) ? state.project_context.documents : []).map((item) => ({
  document_id: String(item?.document_id ?? ''),
  title: String(item?.title ?? item?.file_name ?? ''),
  document_role: String(item?.document_role ?? ''),
  status: String(item?.status ?? ''),
})).filter((item) => item.document_id);
const datasetIds = new Set((Array.isArray(state.project_context?.datasets) ? state.project_context.datasets : [])
  .map((item) => String(item?.dataset_id ?? item?.source_id ?? '').replace(/^current:dataset:/, '').replace(/^dataset:/, '').trim())
  .filter(Boolean));
const metricGroups = {
  poi: [
    'poi.count', 'poi.category_count', 'poi.grid_count', 'poi.grid_density', 'poi.category_density',
    'poi.multi_year_count', 'poi.local_entropy_normalized', 'poi.supply_structure',
    'poi.focused_accessibility', 'poi.kernel_density', 'poi.open_close_rate',
  ],
  h3: ['poi.local_entropy', 'poi.neighbor_mean_density', 'poi.neighbor_mean_entropy', 'poi.lq', 'spatial.gi_star', 'spatial.lisa', 'spatial.neighbor_density_delta', 'grid.opportunity_flag'],
  population: ['population.total', 'population.age_structure', 'population.sex_structure', 'population.selected_ratio', 'timeseries.population_change', 'timeseries.population_density_change', 'timeseries.age_shift'],
  nightlight: ['nightlight.mean_radiance', 'nightlight.total_radiance', 'nightlight.max_radiance', 'nightlight.p90', 'nightlight.lit_pixel_ratio', 'nightlight.hotspot_class', 'nightlight.hotspot_ratio', 'nightlight.spatial_profile', 'nightlight.sector_profile', 'nightlight.activity_level', 'timeseries.nightlight_change', 'timeseries.hotspot_shift'],
  road_edges: ['road.network_size', 'road.integration', 'road.choice', 'road.connectivity', 'road.control', 'road.mean_depth', 'road.degree', 'road.node_degree', 'road.orientation', 'road.intelligibility', 'poi.supply_structure', 'poi.focused_accessibility'],
  road_nodes: ['road.degree', 'road.node_degree'],
  road_grid: ['road.network_size', 'road.integration', 'road.choice', 'road.connectivity', 'road.control', 'road.mean_depth', 'road.orientation', 'road.intelligibility'],
};
const availableSpatialMetrics = [...new Set(Object.entries(metricGroups)
  .filter(([datasetId]) => datasetIds.has(datasetId))
  .flatMap(([, metrics]) => metrics))];
if (datasetIds.has('h3') || datasetIds.has('poi_grid')) availableSpatialMetrics.push('spatial.global_moran_i_density', 'gwr.nightlight_spatial_model', 'gwr.model_fit');
if (datasetIds.has('road_edges')) availableSpatialMetrics.push('isochrone.reachable_area', 'access.network_reachable_area');
if (['poi', 'population', 'nightlight', 'road_edges'].every((datasetId) => datasetIds.has(datasetId))) availableSpatialMetrics.push('regional.directional_evidence_matrix');
const nullableString = { type: ['string', 'null'] };
const nullableInteger = { type: ['integer', 'null'] };
const requiredObject = (properties) => ({ type: 'object', properties, required: Object.keys(properties), additionalProperties: false });
const spatialArguments = requiredObject({
  analysis: { type: 'string', enum: ['scope', 'accessibility', 'direction', 'neighborhood', 'rank', 'relationship', 'inspect'] },
  metric_ids: { type: ['array', 'null'], maxItems: 4, items: { type: 'string' } },
  selectors: { type: ['array', 'null'], maxItems: 8, items: { type: 'object', properties: { dimension: { type: 'string', enum: ['poi.category', 'poi.subcategory', 'road.class', 'year'] }, values: { type: 'array', minItems: 1, maxItems: 20, items: { anyOf: [{ type: 'string' }, { type: 'integer' }] } } }, required: ['dimension', 'values'], additionalProperties: false } },
  travel_time_bands_min: { type: ['array', 'null'], maxItems: 6, items: { type: 'array', minItems: 2, maxItems: 2, items: { type: 'number' } } },
  neighbor_steps: { type: ['integer', 'null'], minimum: 1, maximum: 3 },
  rank_order: { type: ['string', 'null'], enum: ['highest', 'lowest', null] },
  top_k: { type: ['integer', 'null'], minimum: 1, maximum: 20 },
  record_refs: { type: ['array', 'null'], maxItems: 20, items: { type: 'string' } },
});
const documentArguments = requiredObject({ document_id: { type: 'string', minLength: 1 }, start_block: nullableInteger, max_blocks: nullableInteger, page_start: nullableInteger, page_end: nullableInteger });
const literatureArguments = requiredObject({ question: { type: 'string', minLength: 1 }, mode: { type: ['string', 'null'], enum: ['focused', 'synthesis', null] }, top_k: nullableInteger });
const searchArguments = requiredObject({ query: { type: 'string', minLength: 1 }, provider: { type: ['string', 'null'], enum: ['anysearch', 'exa', null] }, limit: nullableInteger });
const fetchArguments = requiredObject({ urls: { type: 'array', minItems: 1, items: { type: 'string', minLength: 8 } }, provider: { type: ['string', 'null'], enum: ['anysearch', 'exa', null] }, max_characters: nullableInteger });
const toolVariant = (name, argumentsSchema) => ({ type: 'object', properties: { name: { type: 'string', enum: [name] }, arguments: argumentsSchema }, required: ['name', 'arguments'], additionalProperties: false });
const toolVariants = [
  toolVariant('analyze_spatial_evidence', spatialArguments),
  toolVariant('read_project_document', documentArguments),
  toolVariant('search_literature_evidence', literatureArguments),
  toolVariant('search_public_web', searchArguments),
  toolVariant('fetch_public_web_page', fetchArguments),
];
const schema = { type: 'object', properties: {
  decision: { type: 'string', enum: ['continue', 'finish'] },
  reason: { type: 'string', minLength: 1, maxLength: 1200 },
  next_tools: { type: 'array', maxItems: 3, items: { anyOf: toolVariants } },
}, required: ['decision', 'reason', 'next_tools'], additionalProperties: false };
const instructions = ${JSON.stringify(agentPrompt(
  '你只判断当前分析问题是否需要补充材料或空间数据，并选择下一批查询；不形成研究结论，不写报告。',
  '优先复用输入中已有的项目材料和分析结果。没有新的查询需求时直接 finish，不为了遍历工具而调用。',
  '根据当前问题选择项目原文、空间分析、规划文献或公开网页查询。查询参数遵守输出 schema；需要前序结果才能确定参数的查询留到下一轮。',
  'continue 时返回一至三个相互独立的查询；finish 时 next_tools 为空。reason 只说明查询需求。',
))};
const userPayload = {
  project_question: state.project_question,
  research_frame: state.research_frame || state.decision_state?.research_frame || '',
  decision_unit: decisionUnit,
  dependency_memos: dependencyMemos,
  previous_decision_memos: previousDecisionMemos,
  available_evidence_directory: previousDecisionMemos.map((item) => ({ unit_id: item.unit_id, ...item.evidence_directory })),
  project_documents: projectDocuments,
  working_research_brief: state.working_research_brief ?? null,
  latest_tool_results: state.latest_tool_results ?? null,
  available_spatial_metrics: availableSpatialMetrics,
  execution_budget: {
    max_parallel: Math.max(1, Math.min(3, Number(state.max_parallel_tools ?? 3))),
    remaining_tool_calls: Math.max(0, Number(state.tool_call_limit ?? 12) - Number(state.tool_call_count ?? 0)),
  },
};
const conversationItems = [{ role: 'user', content: [{ type: 'input_text', text: JSON.stringify(userPayload) }] }];
return [{ json: {
  state,
  instructions,
  input: conversationItems,
  conversation_items: conversationItems,
  initial_context_items: conversationItems,
  model: 'gpt-5.6-terra',
  max_output_tokens: 1800,
  reasoning: { effort: 'low' },
  agent_turn: Number(state.agent_turn ?? 0),
  parallel_tool_calls: false,
  context_budget_tokens: 24000,
  context_reserve_tokens: 6000,
  no_new_evidence_limit: 2,
  stale_tool_turns: Number(state.stale_tool_turns ?? 0),
  tool_call_count: Number(state.tool_call_count ?? 0),
  tool_call_limit: Number(state.tool_call_limit ?? 12),
  max_parallel_tools: Number(state.max_parallel_tools ?? 3),
  working_research_brief: state.working_research_brief ?? { version: 1, cards: [], named_spatial_records: [] },
  research_result_store: Array.isArray(state.research_result_store) ? state.research_result_store : [],
  latest_tool_results: Array.isArray(state.latest_tool_results) ? state.latest_tool_results : [],
  tool_request_fingerprints: Array.isArray(state.tool_request_fingerprints) ? state.tool_request_fingerprints : [],
  tool_result_fingerprints: Array.isArray(state.tool_result_fingerprints) ? state.tool_result_fingerprints : [],
  tool_evidence: Array.isArray(state.tool_evidence) ? state.tool_evidence : [],
  tool_diagnostics: Array.isArray(state.tool_diagnostics) ? state.tool_diagnostics : [],
  route_diagnostics: Array.isArray(state.route_diagnostics) ? state.route_diagnostics : [],
  stop_reason: state.stop_reason ?? null,
  tools: [],
  tool_choice: 'none',
  text: { format: { type: 'json_schema', name: 'evidence_route', strict: true, schema } },
  output: [],
  output_text: '',
  tool_calls: [],
} }];`;
}
const prepareToolCallNode = decisionSourceForGeneration.nodes.find((node) => node.name === 'Prepare MCP Agent Tool Call');
if (prepareToolCallNode?.parameters?.jsCode) {
  prepareToolCallNode.parameters.jsCode = prepareToolCallNode.parameters.jsCode.replace(
    /  const toolArguments = mcpToolName === '[^']+'[\s\S]*?    : mcpArguments;/,
    '  const toolArguments = mcpArguments;',
  );
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
const failedTool = normalizedResults.find((entry) => entry.is_error);
if (failedTool) throw new Error('evidence_tool_execution_failed:' + String(failedTool.tool_name ?? 'unknown') + ':' + String(failedTool.result?.message ?? failedTool.result?.error ?? 'tool_call_failed').slice(0, 240));
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
const compactSpatialAttributes = (attributes) => {
  if (!attributes || typeof attributes !== 'object' || Array.isArray(attributes)) return {};
  return Object.fromEntries(Object.entries(attributes).slice(0, 12).map(([key, value]) => [
    clippedText(key, 120),
    typeof value === 'string' ? clippedText(value, 240) : projectSpatialValue(value, key),
  ]));
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
    attributes: compactSpatialAttributes(item.attributes),
    centroid_wgs84: Array.isArray(item.centroid_wgs84) ? item.centroid_wgs84.slice(0, 2) : undefined,
    straight_line_distance_m: item.straight_line_distance_m ?? null,
    travel_time_band_min: Array.isArray(item.travel_time_band_min) ? item.travel_time_band_min.slice(0, 2) : undefined,
    travel_time_upper_bound_min: item.travel_time_upper_bound_min ?? null,
    travel_time_source: clippedText(item.travel_time_source, 80),
    direction: clippedText(item.direction, 40),
    values: item.values && typeof item.values === 'object' ? item.values : {},
    reason: clippedText(item.reason, 160),
    relation_to_target: item.relation_to_target && typeof item.relation_to_target === 'object' ? {
      target_record_ref: clippedText(item.relation_to_target.target_record_ref, 360),
      kind: clippedText(item.relation_to_target.kind, 80),
      distance_m: item.relation_to_target.distance_m ?? null,
    } : undefined,
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
      "const resolvedStopReason = contextTokens >= Math.max(1, budget - reserve)\n  ? 'context_budget'\n  : Number(prior.tool_call_count ?? 0) >= Number(prior.tool_call_limit ?? 12)\n    ? 'tool_call_limit'\n    : staleToolTurns >= Number(prior.no_new_evidence_limit ?? 2)\n    ? 'no_new_evidence'\n    : null;",
    )
    .replace(
      "  tool_evidence: toolEvidence,\n  tool_diagnostics: toolDiagnostics,",
      "  tool_evidence: toolEvidence,\n  tool_diagnostics: toolDiagnostics,\n  route_diagnostics: [],\n  working_research_brief: workingBrief,\n  research_result_store: researchResultStore,\n  latest_tool_results: latestToolResults,",
    )
    .replace(/请立即基于已获得的项目证据输出完整 [^。]+。/, '请返回 decision=finish，不要形成研究结论或写最终章节。')
    .replace("tool_choice: resolvedStopReason ? 'none' : undefined,", "tool_choice: 'none',");
}
const restoreToolLoopNode = codeNode('恢复章节工具上下文', `const current = $('Build MCP Agent Follow-up').first().json;
const baseState = current.state && typeof current.state === 'object' ? current.state : {};
const state = {
  ...baseState,
  working_research_brief: current.working_research_brief ?? baseState.working_research_brief,
  research_result_store: current.research_result_store ?? baseState.research_result_store,
  latest_tool_results: current.latest_tool_results ?? baseState.latest_tool_results,
  stop_reason: current.stop_reason ?? baseState.stop_reason,
  tool_evidence: current.tool_evidence ?? baseState.tool_evidence,
  tool_diagnostics: current.tool_diagnostics ?? baseState.tool_diagnostics,
  route_diagnostics: current.route_diagnostics ?? baseState.route_diagnostics,
  tool_request_fingerprints: current.tool_request_fingerprints ?? baseState.tool_request_fingerprints,
  tool_result_fingerprints: current.tool_result_fingerprints ?? baseState.tool_result_fingerprints,
  tool_call_count: current.tool_call_count ?? baseState.tool_call_count,
  tool_call_limit: current.tool_call_limit ?? baseState.tool_call_limit,
  agent_turn: current.agent_turn ?? baseState.agent_turn,
  stale_tool_turns: current.stale_tool_turns ?? baseState.stale_tool_turns,
};
return [{ json: { ...current, state, decision_state: state } }];`, [4960, 2040], 'urban-agent-restore-tool-context');
const refreshLeaseNode = postgresNode('刷新分析任务租约', `UPDATE analysis_runs AS run
SET heartbeat_at = NOW(), lease_expires_at = NOW() + INTERVAL '45 minutes', updated_at = NOW()
WHERE id = $1::uuid AND tenant_id = $2::text AND status = 'running';
SELECT $3::jsonb AS payload;`, "={{ [$('恢复章节工具上下文').first().json.state.run_id, $('恢复章节工具上下文').first().json.state.tenant_id, JSON.stringify($('恢复章节工具上下文').first().json)] }}", [5180, 2040], 'urban-agent-refresh-lease');
const restoreRouteRequestNode = codeNode('恢复路由请求上下文', `const row = $input.first()?.json ?? {};
const payload = row.payload && typeof row.payload === 'object' ? row.payload : null;
if (!payload || payload.input === undefined) throw new Error('route_request_context_missing_after_lease_refresh');
return [{ json: payload }];`, [5420, 2040], 'urban-agent-restore-route-request');
decisionSourceForGeneration.nodes.push(refreshLeaseNode, restoreToolLoopNode, restoreRouteRequestNode);
decisionSourceForGeneration.connections['Build MCP Agent Follow-up'] = { main: [[{ node: '恢复章节工具上下文', type: 'main', index: 0 }]] };
decisionSourceForGeneration.connections['恢复章节工具上下文'] = { main: [[{ node: '刷新分析任务租约', type: 'main', index: 0 }]] };
decisionSourceForGeneration.connections['刷新分析任务租约'] = { main: [[{ node: '恢复路由请求上下文', type: 'main', index: 0 }]] };
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
if (validateDecisionOutputNode) {
  validateDecisionOutputNode.parameters.jsCode = `const request = $('Build Structured Decision Request').first().json;
const response = $input.first()?.json ?? {};
const raw = String(response.output_text ?? '').trim();
let parsed;
for (const candidate of [raw, raw.slice(raw.indexOf('{'), raw.lastIndexOf('}') + 1)]) {
  if (!candidate) continue;
  try { parsed = JSON.parse(candidate); break; } catch {}
}
if (!parsed || typeof parsed !== 'object') throw new Error('decision_memo_model_failed:' + String(response.error?.message ?? 'invalid_json').slice(0, 240));
const list = (value, limit) => Array.isArray(value) ? value.map((item) => String(item ?? '').trim()).filter(Boolean).slice(0, limit) : [];
const namedEntities = (Array.isArray(parsed.named_entities) ? parsed.named_entities : []).map((item) => ({
  name: String(item?.name ?? '').trim(),
  entity_type: String(item?.entity_type ?? '').trim(),
  relationship: String(item?.relationship ?? '').trim(),
  fact: String(item?.fact ?? '').trim(),
})).filter((item) => item.name && item.entity_type && item.relationship && item.fact).slice(0, 20);
const decisionMemo = {
  decision: String(parsed.decision ?? '').trim(),
  alternatives_considered: list(parsed.alternatives_considered, 12),
  reasoning: String(parsed.reasoning ?? '').trim(),
  key_facts: list(parsed.key_facts, 20),
  named_entities: namedEntities,
  implications: list(parsed.implications, 12),
};
if (!decisionMemo.decision || !decisionMemo.reasoning || !decisionMemo.implications.length) throw new Error('decision_memo_required_content_missing');
const state = request.state;
const unit = state.decision_unit && typeof state.decision_unit === 'object' ? state.decision_unit : null;
if (!unit || !String(unit.unit_id ?? '').trim() || !String(unit.decision_output ?? '').trim() || !String(unit.evidence_focus ?? '').trim()) throw new Error('decision_unit_required');
const citationSources = Array.isArray(response.tool_evidence) ? response.tool_evidence : [];
const citations = citationSources.filter((item) => item && typeof item === 'object').map((item) => ({
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
})).filter((item, index, items) => item.citation_id && items.findIndex((candidate) => candidate.citation_id === item.citation_id) === index);
const toolEvidence = Array.isArray(response.tool_evidence) ? response.tool_evidence : [];
const output = {
  unit_id: String(unit.unit_id),
  step_key: state.step_key,
  step_order: state.step_order,
  title: String(unit.title),
  question: String(unit.question),
  depends_on: Array.isArray(unit.depends_on) ? unit.depends_on.map(String) : [],
  decision_output: String(unit.decision_output ?? ''),
  evidence_focus: String(unit.evidence_focus ?? ''),
  decision_memo: decisionMemo,
  citations,
  diagnostics: [],
  quality_gate: {
    evidence_count: citations.length,
    named_entity_count: namedEntities.length,
    literature_evidence_count: toolEvidence.filter((item) => String(item?.source_type ?? '') === 'public_knowledge_graphrag').length,
    live_web_fulltext_count: toolEvidence.filter((item) => String(item?.source_type ?? '') === 'public_web_fulltext').length,
    project_evidence_count: toolEvidence.filter((item) => String(item?.source_type ?? '').startsWith('project_')).length,
    generation_status: 'completed',
  },
};
const retainedState = state.decision_state && typeof state.decision_state === 'object' ? state.decision_state : {};
const nextDecisionState = {
  ...retainedState,
  steps: { ...(retainedState.steps ?? {}), [state.step_key]: output },
  research_frame: String(state.research_frame ?? retainedState.research_frame ?? ''),
  decision_units: Array.isArray(state.decision_units) ? state.decision_units : (Array.isArray(retainedState.decision_units) ? retainedState.decision_units : []),
  current_step: state.step_key,
};
return [{ json: { result: {
  run_id: state.run_id,
  step_key: state.step_key,
  step_order: state.step_order,
  status: 'completed',
  output,
  decision_state: nextDecisionState,
} } }];`;
}
const stepPersistNode = decisionSourceForGeneration.nodes.find((node) => node.name === 'Persist Decision State');
if (stepPersistNode) {
  stepPersistNode.parameters.query = stepPersistNode.parameters.query
    .replace("citations = '[]'::jsonb, diagnostics = '[]'::jsonb, quality_gate = '{}'::jsonb", "citations = COALESCE(payload.value->'output'->'citations', '[]'::jsonb), diagnostics = COALESCE(payload.value->'output'->'diagnostics', '[]'::jsonb), quality_gate = COALESCE(payload.value->'output'->'quality_gate', '{}'::jsonb)");
  stepPersistNode.parameters.query = stepPersistNode.parameters.query
    .replace('UPDATE analysis_runs SET current_step = payload.value->>\'step_key\', decision_state = payload.value->\'decision_state\',', 'UPDATE analysis_runs AS run SET current_step = payload.value->>\'step_key\', decision_state = jsonb_set(COALESCE(run.decision_state, \'{}\'::jsonb) || COALESCE(payload.value->\'decision_state\', \'{}\'::jsonb), \'{steps}\', COALESCE(payload.value->\'decision_state\'->\'steps\', \'{}\'::jsonb) || COALESCE(run.decision_state->\'steps\', \'{}\'::jsonb), true),');
  if (!stepPersistNode.parameters.query.includes('heartbeat_at = NOW()')) {
    stepPersistNode.parameters.query = stepPersistNode.parameters.query.replace(
      "UPDATE analysis_runs AS run SET current_step = payload.value->>'step_key', decision_state = jsonb_set(COALESCE(run.decision_state, '{}'::jsonb) || COALESCE(payload.value->'decision_state', '{}'::jsonb), '{steps}', COALESCE(payload.value->'decision_state'->'steps', '{}'::jsonb) || COALESCE(run.decision_state->'steps', '{}'::jsonb), true),",
      "UPDATE analysis_runs AS run SET current_step = payload.value->>'step_key', decision_state = jsonb_set(COALESCE(run.decision_state, '{}'::jsonb) || COALESCE(payload.value->'decision_state', '{}'::jsonb), '{steps}', COALESCE(payload.value->'decision_state'->'steps', '{}'::jsonb) || COALESCE(run.decision_state->'steps', '{}'::jsonb), true), heartbeat_at = NOW(), lease_expires_at = NOW() + INTERVAL '45 minutes',",
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
    "'total_steps', COALESCE(jsonb_array_length(r.decision_state->'decision_units'), 1)",
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
const visualsForGeneration = structuredClone(visualsComponent);
const visualRequestNode = visualsForGeneration.nodes.find((node) => node.name === '构建图件设计请求');
if (!visualRequestNode) throw new Error('visual_request_node_missing');
mergeGraph(graph, visualsForGeneration);
const reportForGeneration = structuredClone(reportComponent);
const reportEditorialRequestNode = reportForGeneration.nodes.find((node) => node.name === '构建报告叙事请求');
if (reportEditorialRequestNode?.parameters?.jsCode) {
  reportEditorialRequestNode.parameters.jsCode = `const rendered = $input.first()?.json ?? {};
const state = rendered.decision_state && typeof rendered.decision_state === 'object' ? rendered.decision_state : {};
const blueprint = state.report_blueprint && typeof state.report_blueprint === 'object' ? state.report_blueprint : {};
const sections = Array.isArray(state.report_sections) ? state.report_sections : [];
if (!blueprint.overall_thesis || !sections.length) throw new Error('report_narrative_requires_blueprint_and_sections');
const schema = { type: 'object', properties: { narrative: { type: 'string', minLength: 1 } }, required: ['narrative'], additionalProperties: false };
const reportSections = sections.map((section) => ({
  title: String(section?.title ?? ''),
  content: String(section?.content ?? ''),
}));
return [{ json: {
  ...rendered,
  instructions: ${JSON.stringify(agentPrompt('为报告撰写开头总判断，输出判断、依据和行动建议。'))},
  input: JSON.stringify({ project_question: rendered.project_question ?? '', overall_thesis: String(blueprint.overall_thesis), sections: reportSections }),
  max_output_tokens: 3000,
  reasoning: { effort: 'high' },
  text: { format: { type: 'json_schema', name: 'spatial_report_narrative', strict: true, schema } },
} }];`;
}
const reportEditorialValidateNode = reportForGeneration.nodes.find((node) => node.name === '校验报告叙事');
if (reportEditorialValidateNode?.parameters?.jsCode) {
  reportEditorialValidateNode.parameters.jsCode = `const request = $('构建报告叙事请求').first().json;
const response = $input.first()?.json ?? {};
const raw = String(response.output_text ?? '').trim();
let parsed;
for (const candidate of [raw, raw.slice(raw.indexOf('{'), raw.lastIndexOf('}') + 1)]) {
  if (!candidate) continue;
  try { parsed = JSON.parse(candidate); break; } catch {}
}
if (!parsed || typeof parsed !== 'object') throw new Error('report_narrative_invalid_json');
const narrative = String(parsed.narrative ?? '').trim();
if (!narrative) throw new Error('report_narrative_empty');
return [{ json: { ...request, editorial_narrative: narrative } }];`;
}
mergeGraph(graph, reportForGeneration);
const consumerTrigger = { parameters: { rule: { interval: [{ field: 'minutes', minutesInterval: 1 }] } }, id: 'urban-agent-consumer-trigger', name: '定时领取分析任务', type: 'n8n-nodes-base.scheduleTrigger', typeVersion: 1.2, position: [700, 1680] };
const claimQueuedNode = postgresNode('领取排队分析任务', `WITH candidate AS (
  SELECT id FROM analysis_runs
  WHERE status = 'queued' OR (status = 'running' AND lease_expires_at < NOW())
  ORDER BY CASE WHEN status = 'queued' THEN 0 ELSE 1 END, created_at
  FOR UPDATE SKIP LOCKED LIMIT 1
), claimed AS (
  UPDATE analysis_runs r SET status = 'running', workflow_execution_id = $1::text,
    current_step = COALESCE(NULLIF(r.current_step, ''), 'planning'), heartbeat_at = NOW(),
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
const existingUnits = Array.isArray(existingState.decision_units) ? existingState.decision_units : [];
if (existingFrame && existingUnits.length) {
  return [{ json: { ...request, reuse_research_frame: true, output_text: JSON.stringify({ research_frame: existingFrame, decision_units: existingUnits }) } }];
}
const context = request.project_context && typeof request.project_context === 'object' ? request.project_context : {};
const project = context.project && typeof context.project === 'object' ? context.project : {};
const documents = Array.isArray(context.documents) ? context.documents.map((item) => ({ document_id: String(item?.document_id ?? ''), title: String(item?.title ?? item?.file_name ?? ''), role: String(item?.document_role ?? '') })) : [];
const datasets = Array.isArray(context.datasets) ? context.datasets.map((item) => ({ dataset_id: String(item?.dataset_id ?? ''), title: String(item?.title ?? ''), total_count: item?.total_count ?? null })) : [];
const schema = { type: 'object', properties: {
  research_frame: { type: 'string', minLength: 1 },
  decision_units: { type: 'array', minItems: 1, maxItems: 32, items: { type: 'object', properties: {
    unit_id: { type: 'string', minLength: 1, maxLength: 64, pattern: '^[a-z][a-z0-9_]*$' },
    title: { type: 'string', minLength: 1 },
    question: { type: 'string', minLength: 1 },
    depends_on: { type: 'array', maxItems: 31, items: { type: 'string', minLength: 1, maxLength: 64 } },
    decision_output: { type: 'string', minLength: 1 },
    evidence_focus: { type: 'string', minLength: 1 },
  }, required: ['unit_id', 'title', 'question', 'depends_on', 'decision_output', 'evidence_focus'], additionalProperties: false } },
}, required: ['research_frame', 'decision_units'], additionalProperties: false };
const instructions = ${JSON.stringify(agentPrompt(
  '为城市空间分析建立研究框架，并按真实决策需要拆分分析单元；此阶段不写报告正文。',
  '每个单元只回答一个会改变项目行动的判断。按依赖顺序输出，depends_on 只能引用前面的单元。',
  'decision_output 说明本单元要形成的判断，evidence_focus 说明需要分析的项目材料或空间问题。单元数量由任务决定，不套用固定章节。',
))};
return [{ json: {
  ...request,
  instructions,
  input: JSON.stringify({ project_question: request.project_question, project, available_documents: documents, available_datasets: datasets }),
  model: 'gpt-5.6-terra',
  max_output_tokens: 10000,
  reasoning: { effort: 'high' },
  text: { format: { type: 'json_schema', name: 'decision_units', strict: true, schema } },
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
const researchFrameModel = localizeComponent(responsesSourceForGeneration, {
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
if (!parsed) {
  const status = String(response.status ?? 'unknown').slice(0, 80);
  const shape = String(response.relay_response_shape ?? 'unknown').slice(0, 80);
  const outputTypes = (Array.isArray(response.output_types) ? response.output_types : [])
    .map((item) => String(item?.type ?? '') + '[' + (Array.isArray(item?.content_types) ? item.content_types.join(',') : '') + ']')
    .join('|').slice(0, 240);
  const errorMessage = String(response.error?.message ?? response.error ?? response.incomplete_details?.reason ?? '')
    .replace(/\\s+/g, ' ').trim().slice(0, 240);
  throw new Error('research_frame_invalid_json_status_' + status + '_shape_' + shape + '_chars_' + raw.length + '_types_' + (outputTypes || 'none') + (errorMessage ? '_error_' + errorMessage : ''));
}
const existingState = response.decision_state && typeof response.decision_state === 'object' ? response.decision_state : {};
const researchFrame = String(existingState.research_frame ?? parsed.research_frame ?? '').trim();
if (!researchFrame) throw new Error('research_frame_empty');
const normalizeUnit = (item) => ({
  unit_id: String(item?.unit_id ?? '').trim(),
  title: String(item?.title ?? '').trim(),
  question: String(item?.question ?? '').trim(),
  depends_on: Array.isArray(item?.depends_on) ? [...new Set(item.depends_on.map((value) => String(value ?? '').trim()).filter(Boolean))] : [],
  decision_output: String(item?.decision_output ?? '').trim(),
  evidence_focus: String(item?.evidence_focus ?? '').trim(),
});
const existingUnits = Array.isArray(existingState.decision_units) ? existingState.decision_units.map(normalizeUnit) : [];
const parsedUnits = (Array.isArray(parsed.decision_units) ? parsed.decision_units : []).map(normalizeUnit);
const decisionUnits = existingUnits.length ? existingUnits : parsedUnits;
if (!decisionUnits.length) throw new Error('decision_units_empty');
// This is an operational payload guard, not a prescribed number of research stages.
// Reject an oversized plan instead of silently dropping units and changing the plan.
if (decisionUnits.length > 32) throw new Error('decision_units_exceed_safety_limit');
const seen = new Set();
for (const unit of decisionUnits) {
  if (!/^[a-z][a-z0-9_]{0,63}$/.test(unit.unit_id)) throw new Error('decision_unit_id_invalid:' + unit.unit_id);
  if (seen.has(unit.unit_id)) throw new Error('decision_unit_id_duplicate:' + unit.unit_id);
  if (!unit.title || !unit.question || !unit.decision_output || !unit.evidence_focus) throw new Error('decision_unit_fields_empty:' + unit.unit_id);
  for (const dependency of unit.depends_on) {
    if (dependency === unit.unit_id) throw new Error('decision_unit_self_dependency:' + unit.unit_id);
    if (!seen.has(dependency)) throw new Error('decision_unit_dependency_must_precede:' + unit.unit_id + ':' + dependency);
  }
  seen.add(unit.unit_id);
}
return [{ json: { ...response, research_frame: researchFrame, decision_units: decisionUnits } }];`, [2460, 1660], 'urban-agent-validate-research-frame');
graph.nodes.push(validateResearchFrameNode);
graph.connections['复用已有研究框架？'] = { main: [
  [{ node: '确认整体研究框架', type: 'main', index: 0 }],
  [{ node: researchFrameModel.entries[0], type: 'main', index: 0 }],
] };
for (const terminal of researchFrameModel.terminals) connect(graph, terminal, '确认整体研究框架');

const queueNode = codeNode('建立自适应分析队列', `const claimed = $input.first()?.json ?? {};
const request = $('确认整体研究框架').first().json;
const candidateUnits = Array.isArray(request.decision_state?.decision_units) && request.decision_state.decision_units.length
  ? request.decision_state.decision_units
  : (Array.isArray(request.decision_units) ? request.decision_units : []);
const adaptiveSteps = candidateUnits.map((item) => ({
  step_key: String(item?.unit_id ?? '').trim(),
  step_title: String(item?.title ?? '').trim(),
  research_brief: String(item?.question ?? '').trim(),
  decision_unit: {
    unit_id: String(item?.unit_id ?? '').trim(),
    title: String(item?.title ?? '').trim(),
    question: String(item?.question ?? '').trim(),
    depends_on: Array.isArray(item?.depends_on) ? item.depends_on.map(String) : [],
    decision_output: String(item?.decision_output ?? '').trim(),
    evidence_focus: String(item?.evidence_focus ?? '').trim(),
  },
})).filter((item) => item.step_key && item.step_title && item.research_brief);
if (!adaptiveSteps.length) throw new Error('decision_units_empty');
if (adaptiveSteps.length > 32) throw new Error('decision_units_exceed_safety_limit');
const steps = adaptiveSteps;
const decisionUnits = steps.map((item) => item.decision_unit);
return steps.map(({ step_key, step_title, research_brief, decision_unit }, index) => ({ json: {
  run_id: String(claimed.run_id ?? request.run_id), tenant_id: request.tenant_id,
  history_id: request.history_id, project_question: request.project_question,
  access_groups: request.access_groups, project_types: request.project_types,
  geography: request.geography, metadata_filter: request.metadata_filter,
  project_context: request.project_context, research_frame: request.research_frame,
  decision_units: decisionUnits,
  decision_state: { ...(request.decision_state && typeof request.decision_state === 'object' ? request.decision_state : {}), research_frame: request.research_frame, decision_units: decisionUnits },
  step_key, step_title, research_brief, decision_unit, step_order: index + 1,
} }));`, [1540, 1860], 'urban-agent-build-step-queue');
const loopNode = {
  parameters: { batchSize: 1, options: {} },
  id: 'urban-agent-step-loop', name: '逐项执行分析方向',
  type: 'n8n-nodes-base.splitInBatches', typeVersion: 3, position: [1800, 1860],
};
const readStateNode = postgresNode('读取最新分析状态', `SELECT $1::jsonb AS step_input, decision_state,
COALESCE((
  SELECT jsonb_object_agg(step.step, step.output)
  FROM analysis_step_outputs AS step
  WHERE step.run_id = r.id AND step.status = 'completed'
), '{}'::jsonb) AS completed_steps
FROM analysis_runs AS r WHERE r.id = ($1::jsonb->>'run_id')::uuid AND r.tenant_id = $1::jsonb->>'tenant_id';`,
  '={{ [JSON.stringify($json)] }}', [2060, 1940], 'urban-agent-read-current-state');
const attachStateNode = codeNode('合并当前分析方向状态', `const row = $input.first()?.json ?? {};
const input = row.step_input && typeof row.step_input === 'object' ? row.step_input : {};
const stored = row.decision_state && typeof row.decision_state === 'object' ? row.decision_state : {};
const queued = input.decision_state && typeof input.decision_state === 'object' ? input.decision_state : {};
const completedSteps = row.completed_steps && typeof row.completed_steps === 'object' ? row.completed_steps : {};
return [{ json: { ...input, decision_state: {
  ...queued,
  ...stored,
  steps: { ...completedSteps, ...(queued.steps ?? {}), ...(stored.steps ?? {}) },
  decision_units: Array.isArray(stored.decision_units) ? stored.decision_units : queued.decision_units,
  research_frame: String(stored.research_frame ?? queued.research_frame ?? ''),
} } }];`,
  [2300, 1940], 'urban-agent-attach-step-state');
const readCompleteStateNode = postgresNode('读取完整分析状态', `SELECT r.id::text AS run_id, r.status, r.current_step,
jsonb_set(
  COALESCE(r.decision_state, '{}'::jsonb),
  '{steps}',
  COALESCE(r.decision_state->'steps', '{}'::jsonb) || COALESCE((
    SELECT jsonb_object_agg(step.step, step.output)
    FROM analysis_step_outputs AS step
    WHERE step.run_id = r.id AND step.status = 'completed'
  ), '{}'::jsonb),
  true
) AS decision_state
FROM analysis_runs AS r WHERE r.id = $1::uuid AND r.tenant_id = $2::text;`,
  "={{ [$('合并项目上下文').first().json.run_id, $('合并项目上下文').first().json.tenant_id] }}",
  [2060, 1780], 'urban-agent-read-complete-state');
graph.nodes.push(queueNode, loopNode, readStateNode, attachStateNode, readCompleteStateNode);
const buildBlueprintNode = codeNode(
  '构建跨单元综合请求',
  `const row = $input.first()?.json ?? {};
const state = row.decision_state && typeof row.decision_state === 'object' ? row.decision_state : {};
const request = $('合并项目上下文').first().json;
const units = Array.isArray(state.decision_units) ? state.decision_units : [];
const steps = state.steps && typeof state.steps === 'object' ? state.steps : {};
const completedMemos = Object.entries(steps).map(([unitId, value]) => ({
  unit_id: unitId,
  step_order: Number(value?.step_order ?? 0),
  title: String(value?.title ?? ''),
  decision_output: String(value?.decision_output ?? ''),
  depends_on: Array.isArray(value?.depends_on) ? value.depends_on : [],
  decision_memo: value?.decision_memo ?? null,
})).filter((item) => item.decision_memo);
const memoByUnitId = new Map(completedMemos.map((item) => [String(item.unit_id), item]));
const decisionMemos = units.map((unit) => memoByUnitId.get(String(unit?.unit_id ?? ''))).filter(Boolean);
if (!units.length || decisionMemos.length !== units.length) throw new Error('report_blueprint_requires_all_decision_memos');
const schema = { type: 'object', properties: {
  overall_thesis: { type: 'string', minLength: 1 },
  decision_logic: { type: 'array', minItems: 1, maxItems: 32, items: { type: 'object', properties: { unit_id: { type: 'string', minLength: 1 }, conclusion: { type: 'string', minLength: 1 }, depends_on: { type: 'array', items: { type: 'string' } }, transition: { type: 'string', minLength: 1 } }, required: ['unit_id', 'conclusion', 'depends_on', 'transition'], additionalProperties: false } },
  sections: { type: 'array', minItems: 1, maxItems: 32, items: { type: 'object', properties: {
    section_id: { type: 'string', minLength: 1, pattern: '^[a-z][a-z0-9_]*$' },
    title: { type: 'string', minLength: 1 },
    purpose: { type: 'string', minLength: 1 },
    source_unit_ids: { type: 'array', minItems: 1, items: { type: 'string' } },
  }, required: ['section_id', 'title', 'purpose', 'source_unit_ids'], additionalProperties: false } },
  conflicts: { type: 'array', maxItems: 20, items: { type: 'string' } },
}, required: ['overall_thesis', 'decision_logic', 'sections', 'conflicts'], additionalProperties: false };
const input = [{ role: 'user', content: [{ type: 'input_text', text: JSON.stringify({ project_question: request.project_question, research_frame: state.research_frame ?? '', decision_units: units, decision_memos: decisionMemos }) }] }];
return [{ json: {
  run_id: String(row.run_id ?? request.run_id),
  tenant_id: String(request.tenant_id ?? 'default'),
  state,
  instructions: ${JSON.stringify(agentPrompt('综合各分析单元，形成报告总判断、决策逻辑和章节安排；此阶段不写正式正文。每个分析单元至少由一个章节覆盖。'))},
  input,
  conversation_items: input,
  text: { format: { type: 'json_schema', name: 'report_blueprint', strict: true, schema } },
  max_output_tokens: 9000,
  reasoning: { effort: 'high' },
} }];`,
  [2380, 1500],
  'urban-agent-build-report-blueprint',
);
const blueprintModelPlaceholder = codeNode('调用跨单元综合模型', 'return $input.all();', [2640, 1500], 'urban-agent-report-blueprint-model');
const validateBlueprintNode = codeNode(
  '校验报告蓝图',
  `const request = $('构建跨单元综合请求').first().json;
const response = $input.first()?.json ?? {};
const raw = String(response.output_text ?? '').trim();
let blueprint;
for (const candidate of [raw, raw.slice(raw.indexOf('{'), raw.lastIndexOf('}') + 1)]) {
  if (!candidate) continue;
  try { blueprint = JSON.parse(candidate); break; } catch {}
}
if (!blueprint || typeof blueprint !== 'object') throw new Error('report_blueprint_invalid_json');
const units = Array.isArray(request.state.decision_units) ? request.state.decision_units : [];
const unitIds = new Set(units.map((item) => String(item?.unit_id ?? '')).filter(Boolean));
const unitById = new Map(units.map((item) => [String(item?.unit_id ?? ''), item]));
const sections = Array.isArray(blueprint.sections) ? blueprint.sections : [];
if (!blueprint.overall_thesis || !sections.length) throw new Error('report_blueprint_empty');
const rawDecisionLogic = Array.isArray(blueprint.decision_logic) ? blueprint.decision_logic : [];
const logicByUnitId = new Map();
for (const item of rawDecisionLogic) {
  const unitId = String(item?.unit_id ?? '').trim();
  if (unitIds.has(unitId) && !logicByUnitId.has(unitId)) logicByUnitId.set(unitId, item);
}
const decisionLogic = units.map((unit) => {
  const unitId = String(unit?.unit_id ?? '').trim();
  const candidate = logicByUnitId.get(unitId) ?? {};
  const memo = request.state.steps?.[unitId]?.decision_memo ?? {};
  const conclusion = String(candidate?.conclusion ?? memo?.decision ?? '').trim();
  if (!conclusion) throw new Error('report_blueprint_decision_logic_incomplete:' + unitId);
  const dependsOn = Array.isArray(unit?.depends_on) ? unit.depends_on.map(String) : [];
  const transition = String(candidate?.transition ?? '').trim() || (dependsOn.length
    ? '承接前序判断，形成当前单元的新增结论。'
    : '建立后续分析的基础判断。');
  return { unit_id: unitId, conclusion, depends_on: dependsOn, transition };
});
blueprint.decision_logic = decisionLogic;
const sectionIds = new Set();
const covered = new Set();
for (const section of sections) {
  const id = String(section?.section_id ?? '').trim();
  if (!/^[a-z][a-z0-9_]*$/.test(id) || sectionIds.has(id)) throw new Error('report_blueprint_section_id_invalid');
  sectionIds.add(id);
  const sourceIds = Array.isArray(section.source_unit_ids) ? [...new Set(section.source_unit_ids.map(String).filter(Boolean))] : [];
  if (!sourceIds.length || sourceIds.some((unitId) => !unitIds.has(unitId))) throw new Error('report_blueprint_unknown_source_unit');
  section.source_unit_ids = sourceIds;
  sourceIds.forEach((unitId) => covered.add(unitId));
}
if ([...unitIds].some((unitId) => !covered.has(unitId))) throw new Error('report_blueprint_missing_unit_coverage');
const state = { ...request.state, report_blueprint: blueprint, report_sections: [] };
return [{ json: { ...request, state, decision_state: state } }];`,
  [2900, 1500],
  'urban-agent-validate-report-blueprint',
);
const saveBlueprintNode = postgresNode(
  '保存报告蓝图',
  `UPDATE analysis_runs SET decision_state = $2::jsonb, current_step = 'report_blueprint', heartbeat_at = NOW(), lease_expires_at = NOW() + INTERVAL '45 minutes', updated_at = NOW()
WHERE id = $1::uuid AND tenant_id = $3::text;
SELECT $1::text AS run_id;`,
  "={{ [$json.run_id, JSON.stringify($json.decision_state ?? $json.state ?? {}), $json.tenant_id] }}",
  [3160, 1500],
  'urban-agent-save-report-blueprint',
);
const expandReportSectionsNode = codeNode(
  '展开报告章节队列',
  `const input = $('校验报告蓝图').first().json;
const blueprint = input.state?.report_blueprint ?? input.decision_state?.report_blueprint;
const sections = Array.isArray(blueprint?.sections) ? blueprint.sections : [];
if (!sections.length) throw new Error('report_sections_empty');
return sections.map((section, index) => ({ json: {
  run_id: input.run_id,
  tenant_id: input.tenant_id,
  project_question: input.project_question,
  section,
  section_order: index + 1,
} }));`,
  [3420, 1500],
  'urban-agent-expand-report-sections',
);
const reportSectionLoopNode = { parameters: { batchSize: 1, options: {} }, id: 'urban-agent-report-section-loop', name: '逐节生成统一报告', type: 'n8n-nodes-base.splitInBatches', typeVersion: 3, position: [3660, 1500] };
const readReportSectionStateNode = postgresNode(
  '读取报告章节状态',
  `SELECT $1::jsonb AS section_input, decision_state FROM analysis_runs WHERE id = ($1::jsonb->>'run_id')::uuid AND tenant_id = $1::jsonb->>'tenant_id';`,
  '={{ [JSON.stringify($json)] }}',
  [3920, 1580],
  'urban-agent-read-report-section-state',
);
const buildReportSectionRequestNode = codeNode(
  '构建报告章节写作请求',
  `const row = $input.first()?.json ?? {};
const input = row.section_input && typeof row.section_input === 'object' ? row.section_input : {};
const state = row.decision_state && typeof row.decision_state === 'object' ? row.decision_state : {};
const section = input.section && typeof input.section === 'object' ? input.section : {};
const steps = state.steps && typeof state.steps === 'object' ? state.steps : {};
const sourceMemos = (Array.isArray(section.source_unit_ids) ? section.source_unit_ids : [])
  .map((unitId) => steps[unitId]?.decision_memo)
  .filter((memo) => memo && typeof memo === 'object');
const sourceAnalyses = sourceMemos.map((memo) => ({
  judgment: String(memo.decision ?? ''),
  basis: Array.isArray(memo.key_facts) ? memo.key_facts : [],
  reasoning: String(memo.reasoning ?? ''),
  actions: Array.isArray(memo.implications) ? memo.implications : [],
  spatial_entities: Array.isArray(memo.named_entities) ? memo.named_entities : [],
}));
const schema = { type: 'object', properties: { section_id: { type: 'string', minLength: 1 }, title: { type: 'string', minLength: 1 }, content: { type: 'string', minLength: 1 } }, required: ['section_id', 'title', 'content'], additionalProperties: false };
const payload = {
  overall_thesis: String(state.report_blueprint?.overall_thesis ?? ''),
  current_section: {
    section_id: String(section.section_id ?? ''),
    title: String(section.title ?? ''),
    purpose: String(section.purpose ?? ''),
  },
  source_analyses: sourceAnalyses,
};
const conversationItems = [{ role: 'user', content: [{ type: 'input_text', text: JSON.stringify(payload) }] }];
return [{ json: {
  ...input,
  state,
  section,
  instructions: ${JSON.stringify(agentPrompt('只撰写当前报告章节，围绕章节目的输出明确判断、依据和行动建议。'))},
  input: conversationItems,
  conversation_items: conversationItems,
  text: { format: { type: 'json_schema', name: 'report_section', strict: true, schema } },
  max_output_tokens: 9000,
  reasoning: { effort: 'high' },
} }];`,
  [4180, 1580],
  'urban-agent-build-report-section',
);
const reportSectionModelPlaceholder = codeNode('调用报告章节写作模型', 'return $input.all();', [4440, 1580], 'urban-agent-report-section-model');
const validateReportSectionNode = codeNode(
  '校验报告章节正文',
  `const request = $('构建报告章节写作请求').first().json;
const response = $input.first()?.json ?? {};
const raw = String(response.output_text ?? '').trim();
let sectionOutput;
for (const candidate of [raw, raw.slice(raw.indexOf('{'), raw.lastIndexOf('}') + 1)]) {
  if (!candidate) continue;
  try { sectionOutput = JSON.parse(candidate); break; } catch {}
}
if (!sectionOutput || typeof sectionOutput !== 'object') throw new Error('report_section_invalid_json');
let content = String(sectionOutput.content ?? '').trim();
if (!content || String(sectionOutput.section_id ?? '').trim() !== String(request.section?.section_id ?? '')) throw new Error('report_section_identity_mismatch');
const state = request.state && typeof request.state === 'object' ? request.state : {};
const existing = Array.isArray(state.report_sections) ? state.report_sections.filter((item) => item?.section_id !== request.section.section_id) : [];
const reportSection = { section_id: request.section.section_id, title: String(sectionOutput.title ?? request.section.title), content, source_unit_ids: request.section.source_unit_ids, section_order: Number(request.section_order ?? 0) };
const nextState = { ...state, report_sections: [...existing, reportSection].sort((left, right) => Number(left.section_order ?? 0) - Number(right.section_order ?? 0)) };
return [{ json: { run_id: request.run_id, tenant_id: request.tenant_id, decision_state: nextState, report_section: reportSection } }];`,
  [4700, 1580],
  'urban-agent-validate-report-section',
);
const saveReportSectionNode = postgresNode(
  '保存报告章节状态',
  `UPDATE analysis_runs SET decision_state = $2::jsonb, current_step = 'report_sections', heartbeat_at = NOW(), lease_expires_at = NOW() + INTERVAL '45 minutes', updated_at = NOW()
WHERE id = $1::uuid AND tenant_id = $3::text;
SELECT $1::text AS run_id;`,
  "={{ [$json.run_id, JSON.stringify($json.decision_state ?? {}), $json.tenant_id] }}",
  [4960, 1580],
  'urban-agent-save-report-section',
);
const readCompletedReportSectionsNode = postgresNode(
  '读取报告章节完成状态',
  `SELECT id::text AS run_id, status, current_step, decision_state FROM analysis_runs WHERE id = $1::uuid AND tenant_id = $2::text;`,
  "={{ [$('合并项目上下文').first().json.run_id, $('合并项目上下文').first().json.tenant_id] }}",
  [3920, 1420],
  'urban-agent-read-report-sections-complete',
);
graph.nodes.push(buildBlueprintNode, blueprintModelPlaceholder, validateBlueprintNode, saveBlueprintNode, expandReportSectionsNode, reportSectionLoopNode, readReportSectionStateNode, buildReportSectionRequestNode, reportSectionModelPlaceholder, validateReportSectionNode, saveReportSectionNode, readCompletedReportSectionsNode);
connect(graph, '读取完整分析状态', '构建跨单元综合请求');
connect(graph, '构建跨单元综合请求', '调用跨单元综合模型');
connect(graph, '调用跨单元综合模型', '校验报告蓝图');
connect(graph, '校验报告蓝图', '保存报告蓝图');
connect(graph, '保存报告蓝图', '展开报告章节队列');
connect(graph, '展开报告章节队列', '逐节生成统一报告');
graph.connections['逐节生成统一报告'] = { main: [
  [{ node: '读取报告章节完成状态', type: 'main', index: 0 }],
  [{ node: '读取报告章节状态', type: 'main', index: 0 }],
] };
connect(graph, '读取报告章节状态', '构建报告章节写作请求');
connect(graph, '构建报告章节写作请求', '调用报告章节写作模型');
connect(graph, '调用报告章节写作模型', '校验报告章节正文');
connect(graph, '校验报告章节正文', '保存报告章节状态');
connect(graph, '保存报告章节状态', '逐节生成统一报告');
connect(graph, '读取报告章节完成状态', '构建图件设计请求');
graph.connections['合并项目上下文'] = { main: [[{ node: '构建整体研究框架', type: 'main', index: 0 }], [{ node: '记录任务失败', type: 'main', index: 0 }]] };
connect(graph, '确认整体研究框架', '建立自适应分析队列');
connect(graph, '建立自适应分析队列', '逐项执行分析方向');
graph.connections['逐项执行分析方向'] = { main: [
  [{ node: '读取完整分析状态', type: 'main', index: 0 }],
  [{ node: '读取最新分析状态', type: 'main', index: 0 }],
] };
connect(graph, '读取最新分析状态', '合并当前分析方向状态');

const decisionNames = {
  'Validate Step Request': '校验当前分析方向', 'Step Already Completed': '当前方向已完成？',
  'Return Existing Step Result': '复用已完成章节', 'Mark Step Running': '标记当前方向执行中',
  'Build Structured Decision Request': '构建证据路由请求', 'Call Codex For Decision': '调用证据路由 Agent',
  'Agent Has Tool Calls': '路由 Agent 请求工具？', 'Prepare MCP Agent Tool Call': '准备证据路由工具调用',
  'Call Spatial MCP Tool': '执行证据工具', 'Build MCP Agent Follow-up': '更新证据简报',
  'Fail MCP Agent Tool Call': '记录项目工具调用失败', 'Validate Decision Output': '校验决策备忘录',
  'Persist Decision State': '保存决策备忘录与分析状态', 'Return Step Result': '完成当前决策单元',
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
const parallelToolNode = graph.nodes.find((node) => node.name === '执行证据工具');
if (parallelToolNode) {
  // The native HTTP Request node already runs all input items through
  // Promise.allSettled internally. It is also the only supported place for
  // n8n credential-aware HTTP helpers; Code nodes cannot access those helpers.
  parallelToolNode.type = 'n8n-nodes-base.httpRequest';
  parallelToolNode.typeVersion = 4.2;
  parallelToolNode.parameters = {
    method: 'POST',
    url: '=__SPATIAL_API_BASE_URL__/analysis/spatial-strategy/agent-tools/call',
    authentication: 'predefinedCredentialType',
    nodeCredentialType: 'httpHeaderAuth',
    sendBody: true,
    contentType: 'json',
    specifyBody: 'json',
    jsonBody: '={{ JSON.parse($json.mcp_request_body) }}',
    options: {
      timeout: 180000,
      response: { response: { responseFormat: 'json' } },
    },
  };
  parallelToolNode.credentials = { httpHeaderAuth: { id: 'n8n-webhook-client', name: 'N8N Webhook Client' } };
  parallelToolNode.onError = 'continueRegularOutput';
}
graph.connections['执行证据工具'] = { main: [[{ node: '更新证据简报', type: 'main', index: 0 }]] };
connect(graph, '合并当前分析方向状态', decision.entries[0]);
connect(graph, '复用已完成章节', '逐项执行分析方向');
connect(graph, '完成当前决策单元', '逐项执行分析方向');

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
  if (!raw) {
    const compact = (value, limit) => String(value ?? '').split(String.fromCharCode(13)).join(' ').split(String.fromCharCode(10)).join(' ').slice(0, limit);
    const status = String(response.status ?? 'unknown').slice(0, 80);
    const shape = String(response.relay_response_shape ?? 'unknown').slice(0, 80);
    const errorMessage = compact(response.error?.message ?? response.error ?? '', 160);
    const incompleteReason = compact(response.incomplete_details?.reason ?? '', 120);
    throw new Error('evidence_route_model_empty_output_status_' + status + '_shape_' + shape + (errorMessage ? '_error_' + errorMessage : '') + (incompleteReason ? '_incomplete_' + incompleteReason : ''));
  }
  const incompleteReason = String(response.incomplete_details?.reason ?? response.error?.message ?? response.status ?? 'unknown').slice(0, 120);
  const outputTypes = (Array.isArray(response.output_types) ? response.output_types : []).map((item) => String(item?.type ?? '') + '[' + (Array.isArray(item?.content_types) ? item.content_types.join(',') : '') + ']').join('|').slice(0, 240);
  const shape = String(response.relay_response_shape ?? 'unknown').slice(0, 80);
  throw new Error('evidence_route_invalid_json_' + incompleteReason + '_chars_' + String(raw.length) + '_types_' + (outputTypes || 'none') + '_shape_' + shape);
}
if (!['continue', 'finish'].includes(route.decision)) throw new Error('evidence_route_invalid_decision');
if (!String(route.reason ?? '').trim()) throw new Error('evidence_route_reason_empty');
const allowed = new Set(['analyze_spatial_evidence', 'read_project_document', 'search_literature_evidence', 'search_public_web', 'fetch_public_web_page']);
const required = { analyze_spatial_evidence: ['analysis'], read_project_document: ['document_id'], search_literature_evidence: ['question'], search_public_web: ['query'], fetch_public_web_page: ['urls'] };
const allowedKeys = {
  analyze_spatial_evidence: new Set(['analysis', 'metric_ids', 'selectors', 'travel_time_bands_min', 'neighbor_steps', 'rank_order', 'top_k', 'record_refs']),
  read_project_document: new Set(['document_id', 'start_block', 'max_blocks', 'page_start', 'page_end']),
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
  const maxParallel = Math.max(1, Math.min(3, Number(response.max_parallel_tools ?? 3)));
  // Keep research strategy in the router. An empty continue batch is sent back to
  // the same router with a concise contract correction instead of selecting a tool
  // in workflow code or failing the whole chapter.
  if (nextTools.length === 0) {
    const retryCount = Math.max(0, Number(response.route_format_retry_count ?? 0));
    if (retryCount >= 2) throw new Error('evidence_route_empty_continue_after_retry');
    const priorInput = Array.isArray(response.input) ? response.input : [];
    const correctedInput = [...priorInput, { role: 'user', content: [{ type: 'input_text', text: '你的 decision=continue，但 next_tools 为空。请重新路由：若仍需取证，返回一至三个参数完整且相互独立的请求；若当前单元的既有证据已经足够，返回 decision=finish 且 next_tools=[]。具体查什么、是否下钻由你根据 decision_unit、dependency_memos 和 working_research_brief 判断；不要写研究结论。' }] }];
    const routeDiagnostics = [...(Array.isArray(response.route_diagnostics) ? response.route_diagnostics : []), { kind: 'empty_continue_batch_retry', attempt: retryCount + 1 }];
    return [{ json: { ...response, route_retry_required: true, route_format_retry_count: retryCount + 1, route_decision: null, route_diagnostics: routeDiagnostics, input: correctedInput, conversation_items: correctedInput, tool_calls: [], output: [], output_text: '', response_id: '', error: null, tool_choice: 'none' } }];
  }
const seen = new Set();
const routeRetryCount = Math.max(0, Number(response.route_format_retry_count ?? 0));
const parameterDiagnostics = [];
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
    if (name === 'analyze_spatial_evidence') {
      const analysis = String(args.analysis ?? '');
      if (!new Set(['scope', 'accessibility', 'direction', 'neighborhood', 'rank', 'relationship', 'inspect']).has(analysis)) throw new Error('evidence_route_invalid_analysis');
      const metricIds = Array.isArray(args.metric_ids) ? args.metric_ids : [];
      const recordRefs = Array.isArray(args.record_refs) ? args.record_refs : [];
      const selectors = Array.isArray(args.selectors) ? args.selectors : [];
      if (metricIds.length > 4) throw new Error('evidence_route_invalid_metric_count');
      if (recordRefs.length > 20) throw new Error('evidence_route_invalid_record_ref_count');
      if (selectors.length > 8 || selectors.some((selector) => !selector || typeof selector !== 'object' || Array.isArray(selector) || !new Set(['poi.category', 'poi.subcategory', 'road.class', 'year']).has(String(selector.dimension ?? '')) || !Array.isArray(selector.values) || selector.values.length < 1 || selector.values.length > 20)) throw new Error('evidence_route_invalid_selector');
      if (args.travel_time_bands_min !== undefined) {
        if (analysis !== 'accessibility') throw new Error('evidence_route_invalid_travel_time_bands_for_analysis');
        if (Array.isArray(args.travel_time_bands_min)) {
          args.travel_time_bands_min = args.travel_time_bands_min.map((band) => Array.isArray(band)
            ? band.map((value) => (typeof value === 'string' && value.trim() !== '' && Number.isFinite(Number(value)) ? Number(value) : value))
            : band);
        }
        if (!Array.isArray(args.travel_time_bands_min) || args.travel_time_bands_min.length < 1 || args.travel_time_bands_min.length > 6 || args.travel_time_bands_min.some((band) => !Array.isArray(band) || band.length !== 2 || band.some((value) => typeof value !== 'number' || !Number.isFinite(value)))) throw new Error('evidence_route_invalid_travel_time_bands');
        let previousEnd = 0;
        for (const [index, band] of args.travel_time_bands_min.entries()) {
          if (band[0] < 0 || band[1] <= band[0] || (index === 0 && band[0] !== 0) || band[0] !== previousEnd) throw new Error('evidence_route_invalid_travel_time_bands');
          previousEnd = band[1];
        }
      }
      if (args.neighbor_steps !== undefined && (!Number.isInteger(args.neighbor_steps) || args.neighbor_steps < 1 || args.neighbor_steps > 3)) throw new Error('evidence_route_invalid_neighbor_steps');
      if (args.top_k !== undefined && (!Number.isInteger(args.top_k) || args.top_k < 1 || args.top_k > 20)) throw new Error('evidence_route_invalid_top_k');
      if (['accessibility', 'direction'].includes(analysis) && (metricIds.length < 1 || metricIds.length > 4)) throw new Error('evidence_route_invalid_' + analysis + '_metric_count');
      if (analysis === 'rank' && metricIds.length !== 1) throw new Error('evidence_route_invalid_rank_metric_count');
      if (analysis === 'relationship' && (metricIds.length < 2 || metricIds.length > 4)) throw new Error('evidence_route_invalid_relationship_metric_count');
      if (analysis === 'neighborhood' && (metricIds.length < 1 || metricIds.length > 4)) throw new Error('evidence_route_invalid_neighborhood_metric_count');
      if (['neighborhood', 'inspect'].includes(analysis) && (recordRefs.length < 1 || recordRefs.length > 20)) throw new Error('evidence_route_invalid_' + analysis + '_record_refs');
      if (!['neighborhood', 'inspect'].includes(analysis) && recordRefs.length) {
        if (routeRetryCount < 2) throw new Error('evidence_route_invalid_record_refs_for_' + analysis);
        // After two explicit router corrections, drop only this semantically
        // irrelevant parameter so a repeated formatting mistake cannot abort
        // an otherwise valid analysis request.
        delete args.record_refs;
        parameterDiagnostics.push({ kind: 'ignored_invalid_record_refs', analysis, count: recordRefs.length });
      }
      if (analysis === 'inspect' && metricIds.length > 4) throw new Error('evidence_route_invalid_inspect_metric_count');
    }
    if (name === 'analyze_spatial_evidence' && args.rank_order && !new Set(['highest', 'lowest']).has(String(args.rank_order))) throw new Error('evidence_route_invalid_rank_order');
    if (name === 'search_literature_evidence' && args.mode && !new Set(['focused', 'synthesis']).has(String(args.mode))) throw new Error('evidence_route_invalid_literature_mode');
    if (['search_public_web', 'fetch_public_web_page'].includes(name) && args.provider && !new Set(['anysearch', 'exa']).has(String(args.provider))) throw new Error('evidence_route_invalid_web_provider');
    const fingerprint = stable({ name, arguments: args });
    if (seen.has(fingerprint)) throw new Error('evidence_route_duplicate_tool_request');
    seen.add(fingerprint);
    return { name, arguments: args, requested_index: index };
    });
  } catch (error) {
    const message = String(error?.message ?? error);
    const recoverable = message.startsWith('evidence_route_argument_missing:') || message.startsWith('evidence_route_argument_not_allowed:') || message.startsWith('evidence_route_invalid_');
    const retryCount = Math.max(0, Number(response.route_format_retry_count ?? 0));
    if (!recoverable || retryCount >= 2) throw error;
    const priorInput = Array.isArray(response.input) ? response.input : [];
    const travelTimeBandCorrection = message.includes('travel_time_bands') ? 'travel_time_bands_min 只有在 accessibility 确实需要自定义时间带时才填写；必须从0开始、首尾相接且不重叠，例如 [[0,5],[5,10],[10,15]]，否则省略该字段。' : '';
    const correctedInput = [...priorInput, { role: 'user', content: [{ type: 'input_text', text: '上一批工具请求参数不完整或包含未允许字段（' + message + '）。请重新输出 decision：continue 时只返回一至三个参数完整、彼此独立且符合工具契约的请求；finish 时 next_tools=[]。不要猜测缺失的 urls、query、metric_ids 或 record_refs。空间工具中 record_refs 只允许出现在 neighborhood 或 inspect；scope、accessibility、direction、rank、relationship 必须省略 record_refs。' + travelTimeBandCorrection }] }];
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
  const routeDiagnostics = [
    ...(Array.isArray(response.route_diagnostics) ? response.route_diagnostics : []),
    ...parameterDiagnostics,
  ];
  if (validated.length > maxParallel) routeDiagnostics.push({ kind: 'batch_trimmed_to_max_parallel', requested: validated.length, executed: Math.min(maxParallel, remainingCalls) });
  if (trimmedCount > 0 && validated.length <= maxParallel) routeDiagnostics.push({ kind: 'batch_trimmed_to_remaining_budget', requested: validated.length, executed: selected.length });
  return [{ json: { ...response, route_decision: route, route_diagnostics: routeDiagnostics, tool_calls: toolCalls, output: [], output_text: JSON.stringify(route), tool_choice: 'none' } }];
}
if (nextTools.length !== 0) throw new Error('evidence_route_finish_has_tool');
const routeDiagnostics = Array.isArray(response.route_diagnostics) ? response.route_diagnostics : [];
return [{ json: { ...response, route_retry_required: false, route_decision: route, route_diagnostics: routeDiagnostics, tool_calls: [], output: [], output_text: JSON.stringify(route), tool_choice: 'none' } }];`,
  [4240, 1940],
  'urban-agent-validate-evidence-route',
);
const researchAnalysisRequest = codeNode(
  '构建章节研究分析请求',
  `const routed = $input.first()?.json ?? {};
const route = routed.route_decision && typeof routed.route_decision === 'object' ? routed.route_decision : null;
if (!route || route.decision !== 'finish') throw new Error('evidence_route_finish_missing');
const request = $('构建证据路由请求').first().json;
const state = routed.state && typeof routed.state === 'object'
  ? routed.state
  : (request.state && typeof request.state === 'object' ? request.state : {});
const brief = routed.working_research_brief && typeof routed.working_research_brief === 'object' ? routed.working_research_brief : { version: 1, cards: [] };
const unit = state.decision_unit && typeof state.decision_unit === 'object' ? state.decision_unit : null;
if (!unit || !String(unit.unit_id ?? '').trim() || !String(unit.question ?? '').trim() || !String(unit.decision_output ?? '').trim() || !String(unit.evidence_focus ?? '').trim()) throw new Error('decision_unit_required');
const previousMemos = Object.entries(state.decision_state?.steps ?? {}).map(([unitId, value]) => ({
  unit_id: unitId,
  step_order: Number(value?.step_order ?? 0),
  title: String(value?.title ?? ''),
  decision_memo: value?.decision_memo ?? null,
  implications: Array.isArray(value?.decision_memo?.implications) ? value.decision_memo.implications : [],
})).filter((item) => item.decision_memo && item.step_order < Number(state.step_order ?? 0));
const input = [{ role: 'user', content: [{ type: 'input_text', text: JSON.stringify({
  project_question: state.project_question,
  research_frame: state.research_frame || state.decision_state?.research_frame || '',
  decision_unit: unit,
  dependency_memos: previousMemos.filter((item) => (unit.depends_on ?? []).includes(item.unit_id)),
   previous_decision_memos: previousMemos,
   working_research_brief: brief,
 }) }] }];
return [{ json: {
  ...routed,
  state,
  input,
  conversation_items: input,
   instructions: ${JSON.stringify(agentPrompt('分析当前城市空间问题，只形成当前单元的明确判断、关键依据和行动建议。结合前序结论，但不重复分析已经完成的问题。按 decision_memo schema 输出。'))},
  tools: [],
  tool_choice: 'none',
  parallel_tool_calls: false,
  text: { format: { type: 'json_schema', name: 'decision_memo', strict: true, schema: {
    type: 'object',
    properties: {
      decision: { type: 'string', minLength: 1 },
      alternatives_considered: { type: 'array', maxItems: 12, items: { type: 'string', minLength: 1 } },
      reasoning: { type: 'string', minLength: 1 },
      key_facts: { type: 'array', maxItems: 20, items: { type: 'string', minLength: 1 } },
      named_entities: { type: 'array', maxItems: 20, items: { type: 'object', properties: { name: { type: 'string', minLength: 1 }, entity_type: { type: 'string', minLength: 1 }, relationship: { type: 'string', minLength: 1 }, fact: { type: 'string', minLength: 1 } }, required: ['name', 'entity_type', 'relationship', 'fact'], additionalProperties: false } },
      implications: { type: 'array', minItems: 1, maxItems: 12, items: { type: 'string', minLength: 1 } },
    },
    required: ['decision', 'alternatives_considered', 'reasoning', 'key_facts', 'named_entities', 'implications'],
    additionalProperties: false,
  } } },
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
graph.nodes.push(validateEvidenceRoute, researchAnalysisRequest, researchAnalysisPlaceholder);
const operationalToolStopNode = {
  parameters: {
    conditions: {
      options: { caseSensitive: true, leftValue: '', typeValidation: 'strict', version: 2 },
      conditions: [{
        id: 'tool-acquisition-operational-stop',
        leftValue: '={{ Boolean($json.stop_reason) }}',
        rightValue: true,
        operator: { type: 'boolean', operation: 'true', singleValue: true },
      }],
      combinator: 'and',
    },
    options: {},
  },
  id: 'urban-agent-tool-acquisition-stop',
  name: '工具获取达到运行边界？',
  type: 'n8n-nodes-base.if',
  typeVersion: 2.2,
  position: [5700, 2040],
};
graph.nodes.push(operationalToolStopNode);
graph.connections['恢复路由请求上下文'] = { main: [[{ node: '工具获取达到运行边界？', type: 'main', index: 0 }]] };
graph.connections['工具获取达到运行边界？'] = { main: [
  [{ node: '记录任务失败', type: 'main', index: 0 }],
  [{ node: '调用证据路由 Agent', type: 'main', index: 0 }],
] };
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
graph.connections['调用章节研究分析模型'] = { main: [[{ node: '校验决策备忘录', type: 'main', index: 0 }]] };

function inlineResponses(targetName, prefix, anchor, labels) {
  const names = {
    'Build Responses Request': labels[0], 'Call Codex Relay': labels[1], 'Normalize Responses Output': labels[2],
  };
  const fragment = localizeComponent(responsesSourceForGeneration, {
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
inlineResponses('调用跨单元综合模型', 'urban-agent-report-blueprint-model', [2640, 1500], ['构建报告蓝图模型请求体', '请求跨单元综合模型', '解析跨单元综合模型响应']);
inlineResponses('调用报告章节写作模型', 'urban-agent-report-section-model', [4440, 1580], ['构建报告章节模型请求体', '请求报告章节写作模型', '解析报告章节写作响应']);
inlineResponses('调用图件设计模型', 'urban-agent-visual-model', [1800, 3300], ['构建图件模型请求体', '请求图件设计模型', '解析图件模型响应']);
inlineResponses('调用报告叙事模型', 'urban-agent-editorial-model', [3000, 3300], ['构建叙事模型请求体', '请求报告叙事模型', '解析叙事模型响应']);
const normalizeFinalReportNode = codeNode(
  '规范化最终报告响应',
  `const raw = $input.first()?.json ?? {};
const parseObject = (value) => {
  if (value && typeof value === 'object' && !Array.isArray(value)) return value;
  if (typeof value !== 'string' || !value.trim()) return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
};
const unwrap = (value) => {
  let current = parseObject(value);
  for (let index = 0; index < 3; index += 1) {
    const nested = current.body ?? current.data ?? (current.report && !current.markdown ? current.report : null);
    if (nested === null || nested === undefined || nested === current) break;
    const next = parseObject(nested);
    if (!Object.keys(next).length) break;
    current = next;
  }
  return current;
};
const fallback = $('校验报告叙事').first()?.json ?? {};
const report = unwrap(raw);
const markdown = String(report.markdown ?? '').trim();
if (!markdown) throw new Error('final_report_markdown_missing');
return [{ json: {
  ...fallback,
  ...report,
  run_id: String(report.run_id ?? fallback.run_id ?? ''),
  markdown,
  citations: Array.isArray(report.citations) ? report.citations : (Array.isArray(fallback.citations) ? fallback.citations : []),
  decision_state: report.decision_state && typeof report.decision_state === 'object' ? report.decision_state : (fallback.decision_state ?? {}),
  asset_manifest: report.asset_manifest && typeof report.asset_manifest === 'object' ? report.asset_manifest : {},
} }];`,
  [4300, 3300],
  'urban-agent-normalize-final-report',
);
graph.nodes.push(normalizeFinalReportNode);
graph.connections['生成最终报告'] = { main: [[{ node: '规范化最终报告响应', type: 'main', index: 0 }]] };
connect(graph, '规范化最终报告响应', '需要发送飞书？');
graph.connections['需要发送飞书？'] = { main: [
  [{ node: '生成 Word 报告并发送飞书', type: 'main', index: 0 }],
  [{ node: '清理成功执行过程数据', type: 'main', index: 0 }],
] };
const restoreDeliveredReportNode = codeNode(
  '恢复已发送报告上下文',
  `const raw = $input.first()?.json ?? {};
const parseObject = (value) => {
  if (value && typeof value === 'object' && !Array.isArray(value)) return value;
  if (typeof value !== 'string' || !value.trim()) return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
};
const unwrap = (value) => {
  let current = parseObject(value);
  for (let index = 0; index < 3; index += 1) {
    const nested = current.body ?? current.data ?? (current.report && !current.markdown ? current.report : null);
    if (nested === null || nested === undefined || nested === current) break;
    const next = parseObject(nested);
    if (!Object.keys(next).length) break;
    current = next;
  }
  return current;
};
const delivered = unwrap(raw);
const composed = $('规范化最终报告响应').first()?.json ?? {};
const markdown = String(delivered.markdown ?? composed.markdown ?? '').trim();
if (!markdown) throw new Error('delivered_report_markdown_missing');
return [{ json: {
  ...composed,
  ...delivered,
  run_id: String(delivered.run_id ?? composed.run_id ?? ''),
  markdown,
  citations: Array.isArray(delivered.citations) ? delivered.citations : (composed.citations ?? []),
  decision_state: delivered.decision_state && typeof delivered.decision_state === 'object' ? delivered.decision_state : (composed.decision_state ?? {}),
  asset_manifest: delivered.asset_manifest && typeof delivered.asset_manifest === 'object' ? delivered.asset_manifest : (composed.asset_manifest ?? {}),
} }];`,
  [4480, 3500],
  'urban-agent-restore-delivered-report',
);
graph.nodes.push(restoreDeliveredReportNode);
const cleanupCompletedRunNode = codeNode(
  '清理成功执行过程数据',
  `const input = $input.first()?.json ?? {};
const transientKeys = new Set([
  'research_result_store', 'working_research_brief', 'latest_tool_results',
  'tool_evidence', 'tool_diagnostics', 'route_diagnostics',
  'tool_request_fingerprints', 'tool_result_fingerprints',
  'initial_context_items', 'conversation_items', 'input', 'output',
  'tools', 'tool_calls', 'usage', 'response_id', 'mcp_request_body',
]);
const strip = (value, key = '') => {
  if (Array.isArray(value)) return value.map((item) => strip(item, key));
  if (!value || typeof value !== 'object') return value;
  const result = {};
  for (const [name, item] of Object.entries(value)) {
    if (transientKeys.has(name)) continue;
    if (key === 'citations' && ['content', 'text', 'raw', 'body'].includes(name)) continue;
    result[name] = strip(item, name);
  }
  return result;
};
const state = input.decision_state && typeof input.decision_state === 'object' ? input.decision_state : {};
const steps = Object.fromEntries(Object.entries(state.steps && typeof state.steps === 'object' ? state.steps : {}).map(([unitId, value]) => {
  const item = value && typeof value === 'object' ? value : {};
  return [unitId, strip({
    unit_id: String(item.unit_id ?? unitId),
    step_order: Number(item.step_order ?? 0),
    title: String(item.title ?? ''),
    question: String(item.question ?? ''),
    depends_on: Array.isArray(item.depends_on) ? item.depends_on : [],
    decision_output: String(item.decision_output ?? ''),
    evidence_focus: String(item.evidence_focus ?? ''),
    decision_memo: item.decision_memo ?? null,
    citations: Array.isArray(item.citations) ? item.citations : [],
  })];
}));
const retainedState = {
  research_frame: String(state.research_frame ?? ''),
  decision_units: strip(Array.isArray(state.decision_units) ? state.decision_units : []),
  steps,
  report_blueprint: strip(state.report_blueprint && typeof state.report_blueprint === 'object' ? state.report_blueprint : {}),
  report_sections: strip(Array.isArray(state.report_sections) ? state.report_sections : []),
};
const citations = Array.isArray(input.citations) ? input.citations.map((item) => strip(item, 'citations')) : [];
return [{ json: { ...input, decision_state: retainedState, citations } }];`,
  [4720, 3500],
  'urban-agent-cleanup-completed-run',
);
graph.nodes.push(cleanupCompletedRunNode);
connect(graph, '生成 Word 报告并发送飞书', '恢复已发送报告上下文');
connect(graph, '恢复已发送报告上下文', '清理成功执行过程数据');
connect(graph, '清理成功执行过程数据', '完成分析任务');
for (const nodeName of ['请求跨单元综合模型', '请求报告章节写作模型', '请求图件设计模型', '请求报告叙事模型']) {
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
  completeNode.parameters.options.queryReplacement = "={{ [String($json.run_id ?? $('读取完整分析状态').first().json.run_id ?? $('合并项目上下文').first().json.run_id ?? ''), JSON.stringify($json.decision_state ?? {}), String($json.markdown ?? ''), JSON.stringify($json.citations ?? []), JSON.stringify($json.asset_manifest ?? {})] }}";
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
    node.onError = 'continueErrorOutput';
    graph.connections[node.name] = { ...(graph.connections[node.name] ?? {}), main: [
      [{ node: '更新证据简报', type: 'main', index: 0 }],
      [{ node: failNodeName, type: 'main', index: 0 }],
    ] };
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
