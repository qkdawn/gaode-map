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

const [submitSource, statusSource, decisionSource, retrievalSource, embeddingSource, rerankSource, responsesSource] = await Promise.all([
  readComponent('agent-submit.json'),
  readComponent('agent-status.json'),
  readComponent('decision-step.json'),
  readComponent('kb-retrieve.json'),
  readComponent('embedding.json'),
  readComponent('rerank.json'),
  readComponent('responses.json'),
]);

// Previous chapter bodies stay in the run state. The chapter model receives only
// a directory and can request a specific body through the guarded read tool.
const decisionSourceForGeneration = structuredClone(decisionSource);
const markRunningNode = decisionSourceForGeneration.nodes.find((node) => node.name === 'Mark Step Running');
if (markRunningNode) {
  markRunningNode.parameters.query = markRunningNode.parameters.query.replace(
    "UPDATE analysis_runs SET status = 'running', current_step = $2::text, started_at = COALESCE(started_at, NOW()), updated_at = NOW()",
    "UPDATE analysis_runs SET status = 'running', current_step = $2::text, started_at = COALESCE(started_at, NOW()), heartbeat_at = NOW(), lease_expires_at = NOW() + INTERVAL '15 minutes', updated_at = NOW()",
  );
}
const validateStepRequestNode = decisionSourceForGeneration.nodes.find((node) => node.name === 'Validate Step Request');
if (validateStepRequestNode?.parameters?.jsCode) {
  validateStepRequestNode.parameters.jsCode = validateStepRequestNode.parameters.jsCode
    .replace('stepOrder > 12', 'stepOrder > 32')
    .replace('between 1 and 12', 'between 1 and 32');
}
const requestNode = decisionSourceForGeneration.nodes.find((node) => node.name === 'Build Structured Decision Request');
if (requestNode) {
  requestNode.parameters.jsCode = requestNode.parameters.jsCode
    .replace("Object.entries(state.decision_state.steps ?? {}).map(([, value]) => ({", "Object.entries(state.decision_state.steps ?? {}).map(([stepKey, value]) => ({")
    .replace("title: String(value?.title ?? '前一章节'),\n  reader_chapter: String(value?.reader_chapter ?? '').slice(0, 2400),", "step_key: stepKey,\n  step_order: Number(value?.step_order ?? 0),\n  title: String(value?.title ?? '前一章节'),\n  decision_brief: String(value?.decision_brief ?? '').trim(),\n  content_available: Boolean(String(value?.reader_chapter ?? '').trim()),")
    .replace("const schema = {", "const previousChapters = previous.filter((item) => item.content_available && item.step_order < state.step_order);\nconst schema = {")
    .replace("properties: { reader_chapter: { type: 'string', minLength: 1 } },\n  required: ['reader_chapter'],", "properties: { decision_brief: { type: 'string', minLength: 1 }, reader_chapter: { type: 'string', minLength: 1 } },\n  required: ['decision_brief', 'reader_chapter'],")
    .replace("  tool_result_fingerprints: [],", "  tool_result_fingerprints: [],\n  tool_evidence: [],\n  tool_diagnostics: [],")
    .replace("  parallel_tool_calls: false,", "  parallel_tool_calls: true,")
    .replace("maximum: 12 } }, additionalProperties: false } },\n    { type: 'function', name: 'read_project_document'", "maximum: 32 } }, additionalProperties: false } },\n    { type: 'function', name: 'read_project_document'")
    .replace("chapter_title: state.step_title, previous_chapters: previous", "chapter_title: state.step_title, previous_chapters: previousChapters")
    .replace("const userPayload = JSON.stringify({ project_question: state.project_question, chapter_title: state.step_title, previous_chapters: previousChapters, source_context: contexts });", "const userPayload = JSON.stringify({ project_question: state.project_question, research_frame: state.research_frame || state.decision_state?.research_frame || '', chapter_title: state.step_title, research_brief: state.research_brief, previous_decisions: previousChapters, source_context: contexts });")
    .replace("  '只返回完整章节正文，不要解释写作过程，不要另附审计数据。',", "  '研究过程先于写作：先把当前研究任务改写成一个真正需要作出判断的问题，提出可能成立的解释或路径，再寻找能够区分它们的证据。不要从已有指标直接跳到建议。',\n  '分析关系和机制：说明对象之间如何发生作用、哪些条件是必要前提、相关性为何可能不是因果。检验是否存在能解释同一现象的替代解释；如果没有有意义的替代解释，说明为什么，而不是为了形式制造方案。',\n  '优先推进一个新的决策边界：把 previous_decisions 当作上游待检验前提，先说明哪些问题已经由上游处理、哪些仍未解决，再把证据用于本章的新选择。如果本章证据不足以改变选择，就明确保留未决边界；不要把上游的完整论证重新改写成背景综述，也不要提前替后续章节完成它们的核心判断。',\n  '成稿前做一次自我挑战：当前判断最脆弱的环节是什么，什么事实会推翻它，它对下一章节究竟形成了什么约束。把这段阶段性结论写入 decision_brief，供后续章节直接承接；decision_brief 是自由文本，不使用固定模板。',\n  'reader_chapter 是面向甲方的完整正文，可以自由组织，但应让读者看清本章新增的问题、关系、取舍和决定，而不只是数据摘要后接建议。只返回 decision_brief 与 reader_chapter。',")
    .replace("  'previous_chapters 只提供前文的位置和可用性，不包含正文。前文是已完成的分析文段及其阶段性判断；需要承接时，使用 read_previous_chapter 按 step_key 或 step_order 读取完整正文。不要假设没有读取的前文，也不要重复已读取章节已经完成的分析。',\n  `当前章节：${state.step_title}。`,", "  'previous_decisions 包含前文自由表达的阶段性结论。把它们当作待继续检验的上游判断，不当作不可质疑的事实；需要核对完整论证时，再使用 read_previous_chapter。后续结论如果改变上游判断，必须在正文中解释原因。',\n  `当前研究任务：${state.research_brief || state.step_title}。`,")
    .replace("{ type: 'function', name: 'read_project_document', description:", "{ type: 'function', name: 'read_previous_chapter', description: 'Read one completed earlier chapter by step_key or step_order.', parameters: { type: 'object', properties: { step_key: { type: 'string' }, step_order: { type: 'integer', minimum: 1, maximum: 32 } }, additionalProperties: false } },\n    { type: 'function', name: 'read_project_document', description:");
}
const followUpNode = decisionSourceForGeneration.nodes.find((node) => node.name === 'Build MCP Agent Follow-up');
if (followUpNode) {
  followUpNode.parameters.jsCode = followUpNode.parameters.jsCode
    .replace(
      "const items = $input.all();\nconst prior = $('Prepare MCP Agent Tool Call').first().json;",
      "const items = $input.all();\nconst preparedItems = typeof $('Prepare MCP Agent Tool Call').all === 'function' ? $('Prepare MCP Agent Tool Call').all() : [{ json: $('Prepare MCP Agent Tool Call').first().json }];\nconst prior = preparedItems[0]?.json ?? {};",
    )
    .replace(
      "const normalizedResults = items.map((item) => {\n  const toolResult = item.json ?? {};\n  return {\n    tool_name: String(toolResult.tool_name ?? ''),\n    call_id: String(toolResult.mcp_call_id ?? ''),",
      "const normalizedResults = items.map((item, index) => {\n  const itemPrior = preparedItems[index]?.json ?? prior;\n  const toolResult = item.json ?? {};\n  return {\n    tool_name: String(toolResult.tool_name ?? itemPrior.mcp_tool_name ?? ''),\n    call_id: String(toolResult.mcp_call_id ?? itemPrior.mcp_call_id ?? ''),\n    arguments: itemPrior.mcp_arguments && typeof itemPrior.mcp_arguments === 'object' ? itemPrior.mcp_arguments : {},",
    )
    .replace("const fingerprints = Array.isArray(prior.tool_result_fingerprints) ? prior.tool_result_fingerprints : [];", `const newEvidence = normalizedResults.flatMap((entry) => {
  const source = entry.result && typeof entry.result === 'object' ? entry.result : {};
  const requested = entry.arguments;
  if (entry.is_error) return [];
  if (entry.tool_name === 'project_context') {
    const snapshotId = String(source.snapshot_id ?? source.context_snapshot_id ?? source.history_id ?? requested.history_id ?? 'offline_snapshot');
    return (Array.isArray(source.computed_results) ? source.computed_results : []).flatMap((resultItem) => {
      if (!resultItem || typeof resultItem !== 'object') return [];
      const resultId = String(resultItem.result_id ?? resultItem.id ?? resultItem.metric_key ?? resultItem.metric_id ?? '').trim();
      if (!resultId) return [];
      return [{ citation_id: resultId, document_id: '', title: String(resultItem.title ?? resultItem.name ?? resultItem.metric_key ?? resultId), source_type: 'project_snapshot', source_url: '', source_locator: 'offline_snapshot:' + resultId, page_start: null, page_end: null, section: String(resultItem.metric_key ?? resultItem.metric_id ?? 'computed_result'), dataset_id: String(resultItem.dataset_id ?? ''), snapshot_id: snapshotId, dataset_checksum: String(resultItem.dataset_checksum ?? resultItem.checksum ?? ''), complete: resultItem.complete !== false, content: JSON.stringify(resultItem.data ?? resultItem.result ?? resultItem) }];
    });
  }
  if (entry.tool_name === 'read_project_document') {
    return (Array.isArray(source.blocks) ? source.blocks : []).flatMap((block) => {
      if (!block || typeof block !== 'object') return [];
      const page = Number(block.page ?? 0) || null;
      const locator = String(block.source_locator ?? (page ? 'page:' + page : 'block:' + String(block.chunk_id ?? '')));
      return [{ citation_id: String(block.chunk_id ?? source.selection_checksum ?? source.document_checksum ?? locator), document_id: String(source.document_id ?? requested.document_id ?? ''), title: String(block.filename ?? requested.document_id ?? '项目文档'), source_type: 'project_document', source_url: String(source.original_resource_uri ?? ''), source_locator: locator, page_start: page, page_end: page, section: String(block.heading ?? ''), content: String(block.text ?? '') }];
    });
  }
  if (entry.tool_name === 'query_data') {
    const datasetId = String(source.dataset_id ?? requested.dataset_id ?? '');
    const locator = 'project_data:' + datasetId + ':' + String(source.operation ?? requested.operation ?? 'records') + ':' + String(source.result_checksum ?? source.query_checksum ?? source.snapshot_id ?? 'result');
    return [{ citation_id: String(source.result_checksum ?? source.query_checksum ?? source.snapshot_id ?? locator), document_id: '', title: datasetId || '项目空间数据', source_type: 'project_data', source_url: '', source_locator: locator, page_start: null, page_end: null, section: String(source.operation ?? requested.operation ?? 'records'), dataset_id: datasetId, snapshot_id: String(source.snapshot_id ?? ''), dataset_checksum: String(source.dataset_checksum ?? ''), complete: source.complete === true, content: JSON.stringify({ total_count: source.total_count ?? null, records: source.records ?? [], computed_results: source.computed_results ?? [], spatial_diagnostics: source.spatial_diagnostics ?? {}, warnings: source.warnings ?? [] }) }];
  }
  return [];
});
const toolEvidence = [...(Array.isArray(prior.tool_evidence) ? prior.tool_evidence : []), ...newEvidence].filter((item, index, collection) => item.citation_id && collection.findIndex((candidate) => candidate.citation_id === item.citation_id) === index);
const toolDiagnostics = [...(Array.isArray(prior.tool_diagnostics) ? prior.tool_diagnostics : []), ...normalizedResults.filter((entry) => entry.is_error).map((entry) => ({ kind: 'tool_error', tool_name: entry.tool_name, message: String(entry.result?.message ?? entry.result?.error ?? 'tool_call_failed') }))];
const fingerprints = Array.isArray(prior.tool_result_fingerprints) ? prior.tool_result_fingerprints : [];`)
    .replace("  tool_result_fingerprints: [...fingerprints, ...newFingerprints].slice(-32),", "  tool_result_fingerprints: [...fingerprints, ...newFingerprints].slice(-32),\n  tool_evidence: toolEvidence,\n  tool_diagnostics: toolDiagnostics,");
}
const refreshLeaseNode = postgresNode('刷新分析任务租约', `UPDATE analysis_runs
SET heartbeat_at = NOW(), lease_expires_at = NOW() + INTERVAL '15 minutes', updated_at = NOW()
WHERE id = $1::uuid AND tenant_id = $2::text AND status = 'running';
SELECT $1::text AS run_id;`, "={{ [$('准备项目工具调用').first().json.state.run_id, $('准备项目工具调用').first().json.state.tenant_id] }}", [4960, 2040], 'urban-agent-refresh-lease');
const restoreToolLoopNode = codeNode('恢复章节工具上下文', `return [{ json: $('Build MCP Agent Follow-up').first().json }];`, [5180, 2040], 'urban-agent-restore-tool-context');
decisionSourceForGeneration.nodes.push(refreshLeaseNode, restoreToolLoopNode);
decisionSourceForGeneration.connections['Build MCP Agent Follow-up'] = { main: [[{ node: '刷新分析任务租约', type: 'main', index: 0 }]] };
decisionSourceForGeneration.connections['刷新分析任务租约'] = { main: [[{ node: '恢复章节工具上下文', type: 'main', index: 0 }]] };
decisionSourceForGeneration.connections['恢复章节工具上下文'] = { main: [[{ node: 'Call Codex For Decision', type: 'main', index: 0 }]] };
const stepPersistNode = decisionSourceForGeneration.nodes.find((node) => node.name === 'Persist Decision State');
if (stepPersistNode) {
  stepPersistNode.parameters.query = stepPersistNode.parameters.query
    .replace("citations = '[]'::jsonb, diagnostics = '[]'::jsonb, quality_gate = '{}'::jsonb", "citations = COALESCE(payload.value->'output'->'citations', '[]'::jsonb), diagnostics = COALESCE(payload.value->'output'->'diagnostics', '[]'::jsonb), quality_gate = COALESCE(payload.value->'output'->'quality_gate', '{}'::jsonb)");
  if (!stepPersistNode.parameters.query.includes('heartbeat_at = NOW()')) {
    stepPersistNode.parameters.query = stepPersistNode.parameters.query.replace(
      "UPDATE analysis_runs SET current_step = payload.value->>'step_key', decision_state = payload.value->'decision_state',",
      "UPDATE analysis_runs SET current_step = payload.value->>'step_key', decision_state = payload.value->'decision_state', heartbeat_at = NOW(), lease_expires_at = NOW() + INTERVAL '15 minutes',",
    );
  }
}
const validationNode = decisionSourceForGeneration.nodes.find((node) => node.name === 'Validate Decision Output');
if (validationNode) {
  validationNode.parameters.jsCode = validationNode.parameters.jsCode
    .replace("const evidenceSignals = ['项目材料', '项目数据', '空间数据', '公开资料', '现场', '核验', '证据', '数据显示', '材料显示'];\nif (!evidenceSignals.some((signal) => readerChapter.includes(signal))) throw new Error('reader_chapter_missing_evidence_context');\n", '')
    .replace("const conditionSignals = ['条件', '前提', '尚未', '不能', '需要', '待核验', '不确定', '若', '如果'];\nif (!conditionSignals.some((signal) => readerChapter.includes(signal))) throw new Error('reader_chapter_missing_conditions');\n", '');
validationNode.parameters.jsCode = validationNode.parameters.jsCode.replace(
    "const output = { title: state.step_title, reader_chapter: readerChapter };",
    "const decisionBrief = String(parsed.decision_brief ?? '').trim();\nif (!decisionBrief) throw new Error('decision_brief_empty');\nconst citationSources = [...(Array.isArray(request.retrieval?.citations) ? request.retrieval.citations : []), ...(Array.isArray(response.tool_evidence) ? response.tool_evidence : [])];\nconst citations = citationSources.filter((item) => item && typeof item === 'object').map((item) => ({ ...item, citation_id: String(item.citation_id ?? item.chunk_key ?? item.document_id ?? '').trim(), document_id: String(item.document_id ?? '').trim(), chunk_id: String(item.chunk_id ?? '').trim(), title: String(item.title ?? '').trim(), source_type: String(item.source_type ?? '').trim(), source_url: String(item.source_url ?? '').trim(), page_start: item.page_start ?? null, page_end: item.page_end ?? null, section: String(item.section ?? '').trim() })).filter((item, index, items) => item.citation_id && items.findIndex((candidate) => candidate.citation_id === item.citation_id) === index);\nconst diagnostics = (Array.isArray(response.tool_diagnostics) ? response.tool_diagnostics : []).filter((item) => item && typeof item === 'object');\nconst qualityGate = { evidence_count: citations.length, public_context_count: Array.isArray(request.retrieval?.contexts) ? request.retrieval.contexts.length : 0, project_evidence_count: Array.isArray(response.tool_evidence) ? response.tool_evidence.length : 0, evidence_status: citations.length > 0 ? 'grounded' : 'insufficient_evidence' };\nconst output = { step_key: state.step_key, step_order: state.step_order, title: state.step_title, research_brief: String(state.research_brief ?? ''), decision_brief: decisionBrief, reader_chapter: readerChapter, citations, diagnostics, quality_gate: qualityGate };",
  );
  validationNode.parameters.jsCode = validationNode.parameters.jsCode.replace(
    "steps: { ...(state.decision_state.steps ?? {}), [state.step_key]: output },\n  current_step: state.step_key,",
    "steps: { ...(state.decision_state.steps ?? {}), [state.step_key]: output },\n  evidence_index: { ...(state.decision_state.evidence_index ?? {}), [state.step_key]: output.citations },\n  research_frame: String(state.research_frame ?? state.decision_state.research_frame ?? ''),\n  research_plan: Array.isArray(state.research_plan) ? state.research_plan : (Array.isArray(state.decision_state.research_plan) ? state.decision_state.research_plan : []),\n  current_step: state.step_key,",
  );
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
    lease_expires_at = NOW() + INTERVAL '15 minutes', started_at = COALESCE(r.started_at, NOW()), updated_at = NOW()
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
  '先判断用户真正需要作出的选择是什么，以及哪些事实只是背景、哪些未知会改变选择。提出少量真正互相竞争的解释或路径，并说明需要什么证据才能区分；不要为了形式凑假设。',
  'research_plan 只列会改变项目路径的决策边界，每个节点用自然语言写一个标题和待回答的问题。可以合并、跳过或改写常见的政策、市场、客群、定位、产品、空间、运营、财务和分期视角；不相关的视角不要为了凑数量保留。节点数量由问题复杂度决定，只保留必要的节点并避免重复。节点应能按依赖关系排列，但不要把它写成固定章节模板。',
  '明确节点之间的关键依赖关系，特别指出最容易发生的因果跳跃和最值得反驳的直觉。',
  '研究框架是开放式工作备忘录，不是审计表，不使用固定字段、编号模板或预设答案。信息不足时写明应如何判断，不要提前给出结论。',
].join('\\n');
return [{ json: {
  ...request,
  instructions,
  input: JSON.stringify({ project_question: request.project_question, project, available_documents: documents, available_datasets: datasets }),
  max_output_tokens: 2400,
  reasoning: { effort: 'high' },
  text: { format: { type: 'json_schema', name: 'research_frame', strict: true, schema } },
} }];`, [1460, 1660], 'urban-agent-build-research-frame');
graph.nodes.push(researchFrameNode);
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
connect(graph, '构建整体研究框架', researchFrameModel.entries[0]);
const validateResearchFrameNode = codeNode('确认整体研究框架', `const response = $input.first()?.json ?? {};
let parsed;
try { parsed = JSON.parse(String(response.output_text ?? '')); } catch { throw new Error('research_frame_invalid_json'); }
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
for (const terminal of researchFrameModel.terminals) connect(graph, terminal, '确认整体研究框架');

const queueNode = codeNode('建立自适应分析队列', `const claimed = $input.first()?.json ?? {};
const request = $('确认整体研究框架').first().json;
const fallbackSteps = [
  ['step_01_policy_site', '政策与场地', '项目必须解决的真实公共任务是什么，场地资源、权属、保护、居民和建设条件分别允许或排除哪些路径？'],
  ['step_02_regional_role', '区域角色', '项目与区域中心、交通节点、景区、商圈、社区和同类设施是什么关系；它有资格承担什么角色，又不应声称什么角色？'],
  ['step_03_market_flow', '市场与流动', '哪些人可能在什么时间、通过什么到达机制进入项目；区域流量、项目可达性与实际到访之间还缺少哪些因果环节？'],
  ['step_04_supply_gap', '供给与空位', '周边现有供给、替代方案和竞争项目满足了什么、遗漏了什么；所谓空位是真实未满足需求，还是数据分类与观察范围造成的假象？'],
  ['step_05_audience_use', '客群与使用', '比较候选客群的服务需要、到达机制、时间预算、替代供给与使用阻碍；分析客群之间的互补和冲突，并判断一期最值得验证谁，而不是给人群贴标签。'],
  ['step_06_theme_resources', '主题与资源', '哪些真实地方资源之间存在可持续的关系，哪些只是孤立符号；主题能否转化为反复发生的使用和运营机制？'],
  ['step_07_positioning', '项目定位', '基于上游判断比较可行定位：每种定位为谁创造什么价值、依赖什么能力、与替代供给有何差异，为什么当前选择优于竞争性解释？'],
  ['step_08_product_mix', '产品组合', '把定位转成可运行的产品组合，解释不同客群、场景和产品之间如何互相导流或争夺资源，并找出一期最小可运行组合。'],
  ['step_09_spatial_layout', '空间布局', '由真实使用流程和运营责任反推入口、集散、体验、服务、后勤、居民与安全边界；空间关系如何支持或破坏产品承诺？'],
  ['step_10_operating_model', '运营模式', '谁负责获客、内容、场地、社区协调和数据记录；各方的激励、能力与责任关系能否让一期样板持续运行？'],
  ['step_11_financial_check', '财务校验', '哪些投入和收入假设真正决定可行性，需求、容量、采购价格与资金条件如何联动；在证据不足时给出条件范围而非伪精确结论。'],
  ['step_12_phasing', '分期实施', '怎样把当前选择组织为可学习的一期部署；记录什么结果、在什么时间窗判断继续、调整、扩大或停止？'],
];
const candidatePlan = Array.isArray(request.decision_state?.research_plan) && request.decision_state.research_plan.length
  ? request.decision_state.research_plan
  : (Array.isArray(request.research_plan) ? request.research_plan : []);
const adaptiveSteps = candidatePlan.map((item, index) => ({
  step_key: String(item?.step_key ?? 'decision_' + String(index + 1).padStart(2, '0')),
  step_title: String(item?.title ?? '').trim(),
  research_brief: String(item?.question ?? '').trim(),
})).filter((item) => item.step_title && item.research_brief).slice(0, 32);
const steps = adaptiveSteps.length ? adaptiveSteps : fallbackSteps.map(([step_key, step_title, research_brief]) => ({ step_key, step_title, research_brief }));
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
// The scheduled consumer has already claimed the run before loading project
// context; bypass the legacy queued-claim node for that path.
graph.connections['合并项目上下文'] = { main: [[{ node: '构建整体研究框架', type: 'main', index: 0 }], [{ node: '记录任务失败', type: 'main', index: 0 }]] };
graph.connections['认领待执行分析任务'] = { main: [[{ node: '构建整体研究框架', type: 'main', index: 0 }]] };
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
  'Build Retrieval Request': '构建公共证据检索请求', 'Retrieve Cited Source Text': '检索公共证据原文',
  'Build Structured Decision Request': '构建章节分析请求', 'Call Codex For Decision': '调用章节分析模型',
  'Agent Has Tool Calls': '章节模型请求工具？', 'Prepare MCP Agent Tool Call': '准备项目工具调用',
  'Call Spatial MCP Tool': '读取项目原文或空间数据', 'Build MCP Agent Follow-up': '将项目工具结果交回模型',
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
    .replace("$('构建章节分析请求').item.json", "$('构建章节分析请求').first().json")
    .replace("$('准备项目工具调用').item.json", "$('准备项目工具调用').first().json");
}
mergeGraph(graph, decision);
connect(graph, '合并当前分析方向状态', decision.entries[0]);
connect(graph, '复用已完成章节', '逐项执行分析方向');
connect(graph, '完成当前分析方向', '逐项执行分析方向');

const deepenChapterNode = codeNode('深化章节判断', `const draftResponse = $input.first()?.json ?? {};
let draft;
try { draft = JSON.parse(String(draftResponse.output_text ?? '')); } catch { throw new Error('chapter_draft_invalid_json'); }
const state = draftResponse.state && typeof draftResponse.state === 'object' ? draftResponse.state : {};
const priorDecisions = Object.values(state.decision_state?.steps ?? {}).filter((item) => item && typeof item === 'object' && Number(item.step_order ?? 0) < Number(state.step_order ?? 0)).map((item) => ({ title: String(item.title ?? ''), decision_brief: String(item.decision_brief ?? '') })).filter((item) => item.decision_brief);
const evidence = [...(Array.isArray(draftResponse.retrieval?.contexts) ? draftResponse.retrieval.contexts : []), ...(Array.isArray(draftResponse.tool_evidence) ? draftResponse.tool_evidence : [])].map((item) => ({ title: String(item?.title ?? ''), source_type: String(item?.source_type ?? ''), section: String(item?.section ?? ''), content: String(item?.content ?? '').slice(0, 2600) })).filter((item) => item.content).slice(0, 16);
const schema = { type: 'object', properties: { decision_brief: { type: 'string', minLength: 1 }, reader_chapter: { type: 'string', minLength: 1 } }, required: ['decision_brief', 'reader_chapter'], additionalProperties: false };
const instructions = [
  '你是同一章节的资深决策分析师。初稿已经完成，现在只做一次实质性深化，不做格式审计，也不要机械添加小标题。',
  '重新检查研究问题是否真正被回答；哪些证据只是相关性或代理，是否被误写成需求、客流、支付或因果；对象、客群、空间、产品和运营主体之间的关系是否说清。',
  '尝试用另一种解释说明同一证据。若替代解释同样成立，应降低结论强度或说明如何区分；若存在真实方案取舍，应解释当前选择为何胜出以及什么事实会改判。没有真实取舍时不要强造选项。',
  '检查本章是否承接前序判断并对后续选择形成明确约束。客群分析尤其要区分服务对象、使用者、付费者和到达机制，分析客群之间的互补、冲突与替代供给。',
  '在不增加未经证实事实的前提下重写 decision_brief 和 reader_chapter。保留初稿中成立的具体证据、反证和不确定性；删掉空泛总结。表达形式保持自由。',
].join('\\n');
return [{ json: {
  ...draftResponse,
  instructions,
  input: JSON.stringify({ project_question: state.project_question, research_frame: state.research_frame || state.decision_state?.research_frame || '', research_brief: state.research_brief, prior_decisions: priorDecisions, evidence, draft }),
  max_output_tokens: 6000,
  reasoning: { effort: 'high' },
  tools: [],
  tool_choice: 'none',
  text: { format: { type: 'json_schema', name: 'deepened_decision_chapter', strict: true, schema } },
} }];`, [4800, 2140], 'urban-agent-deepen-chapter');
graph.nodes.push(deepenChapterNode);
const chapterChoiceConnections = graph.connections['章节模型请求工具？']?.main ?? [];
if (chapterChoiceConnections[1]) chapterChoiceConnections[1] = [{ node: '深化章节判断', type: 'main', index: 0 }];
graph.connections['章节模型请求工具？'] = { ...(graph.connections['章节模型请求工具？'] ?? {}), main: chapterChoiceConnections };

const deepenModel = localizeComponent(responsesSource, {
  names: {
    'Build Responses Request': '构建深化请求体',
    'Call Codex Relay': '请求深化分析模型',
    'Normalize Responses Output': '解析深化分析响应',
  },
  idPrefix: 'urban-agent-deepen-model',
  anchor: [5060, 2140],
  triggerName: 'When Called By Agent',
});
mergeGraph(graph, deepenModel);
connect(graph, '深化章节判断', deepenModel.entries[0]);
for (const terminal of deepenModel.terminals) connect(graph, terminal, '校验章节正文');

const retrievalNames = {
  'Normalize Recall Request': '规范公共证据检索条件', 'Embed Recall Query': '生成公共证据查询向量',
  'Attach Query Embedding': '合并公共证据查询向量', 'Hybrid Keyword Vector Recall': '混合检索公共证据',
  'Build Rerank Input': '构建公共证据重排输入', 'Recall Has Candidates': '检索到候选证据？',
  'Rerank Candidates With Codex': '重排公共证据', 'Skip Empty Rerank': '跳过空证据重排',
  'Prepare Context Expansion': '准备扩展证据上下文', 'Expand And Read Source Chunks': '读取相邻公共证据原文',
  'Return Cited Context': '整理可引用公共证据',
};
const retrieval = localizeComponent(retrievalSource, {
  names: retrievalNames, idPrefix: 'urban-agent-retrieval', anchor: [3500, 2480], triggerName: 'When Called By Agent',
});
replaceNodeWithFragment(graph, '检索公共证据原文', retrieval);

const embeddingNames = {
  'Build Embedding Request': '构建公共证据向量请求', 'Generate Embeddings': '生成公共证据查询向量',
  'Validate Embeddings': '校验公共证据查询向量',
};
const embedding = localizeComponent(embeddingSource, {
  names: embeddingNames, idPrefix: 'urban-agent-query-embedding', anchor: [4100, 2480], triggerName: 'When Called By RAG',
});
replaceNodeWithFragment(graph, '生成公共证据查询向量', embedding);

const rerankNames = {
  'Build Rerank Request': '构建模型重排请求', 'Call Codex Responses': '调用公共证据重排模型',
  'Apply Model Ranking': '应用公共证据排序',
};
const rerank = localizeComponent(rerankSource, {
  names: rerankNames, idPrefix: 'urban-agent-rerank', anchor: [5300, 2420], triggerName: 'When Called By Retrieval',
});
replaceNodeWithFragment(graph, '重排公共证据', rerank);

function inlineResponses(targetName, prefix, anchor, labels) {
  const names = {
    'Build Responses Request': labels[0], 'Call Codex Relay': labels[1], 'Normalize Responses Output': labels[2],
  };
  const fragment = localizeComponent(responsesSource, {
    names, idPrefix: prefix, anchor, triggerName: 'When Called By Agent',
  });
  replaceNodeWithFragment(graph, targetName, fragment);
}
inlineResponses('调用公共证据重排模型', 'urban-agent-rerank-model', [5800, 2420], ['构建重排模型请求体', '请求重排模型', '解析重排模型响应']);
inlineResponses('调用章节分析模型', 'urban-agent-chapter-model', [5000, 1760], ['构建章节模型请求体', '请求章节分析模型', '解析章节模型响应']);
inlineResponses('调用图件设计模型', 'urban-agent-visual-model', [1800, 3300], ['构建图件模型请求体', '请求图件设计模型', '解析图件模型响应']);
inlineResponses('调用报告叙事模型', 'urban-agent-editorial-model', [3000, 3300], ['构建叙事模型请求体', '请求报告叙事模型', '解析叙事模型响应']);
graph.connections['需要发送飞书？'] = { main: [
  [{ node: '生成 Word 报告并发送飞书', type: 'main', index: 0 }],
  [{ node: '完成分析任务', type: 'main', index: 0 }],
] };
for (const nodeName of ['请求图件设计模型', '请求报告叙事模型']) {
  const node = graph.nodes.find((item) => item.name === nodeName);
  if (!node) continue;
  node.maxTries = 3;
  node.waitBetweenTries = 120000;
}
const finalLeaseNode = postgresNode('刷新报告阶段租约', `UPDATE analysis_runs
SET heartbeat_at = NOW(), lease_expires_at = NOW() + INTERVAL '15 minutes', updated_at = NOW()
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
  node.onError = 'continueErrorOutput';
  const main = graph.connections[node.name]?.main ?? [];
  while (main.length < 2) main.push([]);
  if ((main[1] ?? []).length === 0) {
    main[1] = [...(main[1] ?? []), { node: failNodeName, type: 'main', index: 0 }];
  }
  graph.connections[node.name] = { ...(graph.connections[node.name] ?? {}), main };
}

const legacyClaim = graph.nodes.find((node) => node.name === '认领待执行分析任务');
if (legacyClaim) {
  graph.nodes = graph.nodes.filter((node) => node !== legacyClaim);
  delete graph.connections['认领待执行分析任务'];
}

for (const node of graph.nodes) {
  if (node.name === '读取项目上下文') node.position = [1120, 1860];
  if (node.name === '合并项目上下文') node.position = [1300, 1860];
  if (node.name === '认领待执行分析任务') node.position = [1420, 1980];
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
