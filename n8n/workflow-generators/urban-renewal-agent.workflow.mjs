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

const [submitSource, statusSource, decisionSource] = await Promise.all([
  readComponent('agent-submit.json'),
  readComponent('agent-status.json'),
  readComponent('decision-step.json'),
]);

const decisionSourceForGeneration = structuredClone(decisionSource);
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
  submitQueryNode.parameters.query = submitQueryNode.parameters.query.replace(
    "jsonb_build_object('steps', '{}'::jsonb, 'evidence_index', '{}'::jsonb, 'conflicts', '[]'::jsonb, 'open_questions', '[]'::jsonb, 'revisions', '[]'::jsonb)",
    "jsonb_build_object('steps', '{}'::jsonb)",
  );
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
if (!reportForGeneration.nodes.some((node) => node.name === '准备报告总判断')) throw new Error('report_summary_node_missing');
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
    lease_expires_at = NOW() + INTERVAL '6 hours', started_at = COALESCE(r.started_at, NOW()), updated_at = NOW()
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
const definitions = [
  ['current_structure', '现状结构', '当前区位、资源、空间组织和使用基础如何影响项目选择？', [], '明确可利用的结构基础和需要主动改变的关系', '项目材料、道路、POI、人口、夜光及现状空间数据'],
  ['future_role', '未来角色', '项目在区域与城市中应主动承担什么角色？', ['current_structure'], '比较至少三个候选定位并选择推荐角色', '区域关系、供给结构、政策与场地资源'],
  ['users_and_scenarios', '使用者与场景', '优先服务谁，并希望形成哪些日常和组织化使用方式？', ['future_role'], '明确优先使用者、兼容客群和未来使用场景', '人口、可达性、周边节点、项目角色'],
  ['spatial_mechanisms', '空间机制', '入口、路径、建筑、院落和住宅界面如何促成未来使用？', ['users_and_scenarios'], '形成从现状到未来状态的空间改变机制', '路网、可达性、场地资源与刚性条件'],
  ['product_and_operation', '产品与运营', '哪些产品、内容和运营组合能够支撑所选角色与场景？', ['future_role', 'users_and_scenarios', 'spatial_mechanisms'], '形成相互配合的产品与运营组合', '供给、主题资源、场景和空间承载'],
  ['first_phase_actions', '首期行动', '首期应建设和组织什么，落在哪里，预期改变什么？', ['spatial_mechanisms', 'product_and_operation'], '形成可直接交给设计和运营团队的首期项目包', '前序方案、可确认空间与实施条件'],
  ['phasing', '后续分期', '首期之后如何按空间和运营逻辑继续推进？', ['first_phase_actions'], '明确后续建设顺序和每期目标', '首期项目包、资源条件和运营组合'],
];
const decisionUnits = definitions.map(([unit_id, title, question, depends_on, decision_output, evidence_focus]) => ({ unit_id, title, question, depends_on, decision_output, evidence_focus }));
return [{ json: { ...request, research_frame: '现状结构 → 未来角色 → 使用者与场景 → 空间机制 → 产品与运营 → 首期行动 → 后续分期', decision_units: decisionUnits, decision_state: { ...existingState, research_frame: existingState.research_frame || '现状结构 → 未来角色 → 使用者与场景 → 空间机制 → 产品与运营 → 首期行动 → 后续分期', decision_units: Array.isArray(existingState.decision_units) && existingState.decision_units.length === 7 ? existingState.decision_units : decisionUnits, steps: existingState.steps && typeof existingState.steps === 'object' ? existingState.steps : {} } } }];`, [1540, 1860], 'urban-agent-build-research-frame');
const validateResearchFrameNode = codeNode('确认整体研究框架', `const response = $input.first()?.json ?? {};
const researchFrame = String(response.research_frame ?? response.decision_state?.research_frame ?? '').trim();
const decisionUnits = Array.isArray(response.decision_state?.decision_units) ? response.decision_state.decision_units : response.decision_units;
const expected = ['current_structure', 'future_role', 'users_and_scenarios', 'spatial_mechanisms', 'product_and_operation', 'first_phase_actions', 'phasing'];
if (!researchFrame || !Array.isArray(decisionUnits) || decisionUnits.length !== expected.length || decisionUnits.some((unit, index) => String(unit?.unit_id ?? '') !== expected[index])) throw new Error('decision_units_must_follow_strategy_chain');
return [{ json: { ...response, research_frame: researchFrame, decision_units: decisionUnits, decision_state: { ...(response.decision_state ?? {}), research_frame: researchFrame, decision_units: decisionUnits } } }];`, [1780, 1860], 'urban-agent-validate-research-frame');
graph.nodes.push(researchFrameNode, validateResearchFrameNode);
connect(graph, '构建整体研究框架', '确认整体研究框架');

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
if (adaptiveSteps.length !== 7) throw new Error('decision_units_must_follow_strategy_chain');
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
const checkBlueprintRecoveryNode = codeNode(
  '检查综合方案恢复状态',
  `const row = $input.first()?.json ?? {};
const state = row.decision_state && typeof row.decision_state === 'object' ? row.decision_state : {};
const blueprint = state.report_blueprint && typeof state.report_blueprint === 'object' ? state.report_blueprint : {};
const blueprintComplete = String(blueprint.executive_summary ?? '').trim().length > 0
  && String(blueprint.recommended_position ?? '').trim().length > 0
  && String(blueprint.future_state ?? '').trim().length > 0
  && Array.isArray(blueprint.change_mechanisms) && blueprint.change_mechanisms.length > 0
  && Array.isArray(blueprint.action_plan) && blueprint.action_plan.length > 0
  && Array.isArray(blueprint.sections) && blueprint.sections.length === 5;
return [{ json: { ...row, decision_state: state, report_blueprint_complete: blueprintComplete } }];`,
  [2300, 1780],
  'urban-agent-check-blueprint-recovery',
);
const blueprintCompleteNode = {
  parameters: {
    conditions: {
      options: { caseSensitive: true, leftValue: '', typeValidation: 'strict', version: 2 },
      conditions: [{
        id: 'report-blueprint-complete',
        leftValue: '={{ $json.report_blueprint_complete === true }}',
        rightValue: true,
        operator: { type: 'boolean', operation: 'true', singleValue: true },
      }],
      combinator: 'and',
    },
    options: {},
  },
  id: 'urban-agent-blueprint-complete',
  name: '综合方案已完成？',
  type: 'n8n-nodes-base.if',
  typeVersion: 2.2,
  position: [2540, 1780],
};
graph.nodes.push(checkBlueprintRecoveryNode, blueprintCompleteNode);
const buildBlueprintNode = codeNode(
  '构建跨单元综合请求',
  `const row = $input.first()?.json ?? {};
const state = row.decision_state && typeof row.decision_state === 'object' ? row.decision_state : {};
const request = $('合并项目上下文').first().json;
const units = Array.isArray(state.decision_units) ? state.decision_units : [];
const steps = state.steps && typeof state.steps === 'object' ? state.steps : {};
const completedUnitIds = new Set(Object.entries(steps)
  .filter(([, value]) => value?.decision_memo && typeof value.decision_memo === 'object')
  .map(([unitId]) => String(unitId)));
if (!units.length || units.some((unit) => !completedUnitIds.has(String(unit?.unit_id ?? '')))) throw new Error('report_blueprint_requires_all_decisions');
return [{ json: {
  run_id: String(row.run_id ?? request.run_id),
  tenant_id: String(request.tenant_id ?? 'default'),
  project_question: String(request.project_question ?? ''),
  state,
} }];`,
  [2380, 1500],
  'urban-agent-build-report-blueprint',
);
const blueprintModelPlaceholder = {
  parameters: {
    method: 'POST',
    url: '=__SPATIAL_API_BASE_URL__/analysis/spatial-strategy/harness/synthesize',
    authentication: 'genericCredentialType',
    genericAuthType: 'httpHeaderAuth',
    sendBody: true,
    contentType: 'json',
    specifyBody: 'json',
    jsonBody: '={{ JSON.stringify({ run_id: $json.run_id, project_question: $json.project_question }) }}',
    options: { timeout: 3600000, response: { response: { responseFormat: 'json' } } },
  },
  id: 'urban-agent-report-blueprint-model',
  name: '调用 Codex Harness 综合方案',
  type: 'n8n-nodes-base.httpRequest',
  typeVersion: 4.5,
  position: [2640, 1500],
  credentials: { httpHeaderAuth: { id: 'n8n-webhook-client', name: 'N8N Webhook Client' } },
  onError: 'continueErrorOutput',
};
const validateBlueprintNode = codeNode(
  '校验报告蓝图',
  `const request = $('构建跨单元综合请求').first().json;
const blueprint = $input.first()?.json ?? {};
if (blueprint.error || blueprint.detail) throw new Error('codex_harness_failed:' + String(blueprint.error?.message ?? blueprint.detail ?? blueprint.error));
const sections = Array.isArray(blueprint.sections) ? blueprint.sections : [];
const actionPlan = Array.isArray(blueprint.action_plan) ? blueprint.action_plan : [];
if (!String(blueprint.executive_summary ?? '').trim() || !String(blueprint.recommended_position ?? '').trim() || !String(blueprint.future_state ?? '').trim() || !Array.isArray(blueprint.change_mechanisms) || !blueprint.change_mechanisms.length || !actionPlan.length || sections.length !== 5) throw new Error('report_blueprint_empty');
const sectionIds = new Set();
for (const section of sections) {
  const id = String(section?.section_id ?? '').trim();
  if (!/^[a-z][a-z0-9_]*$/.test(id) || sectionIds.has(id)) throw new Error('report_blueprint_section_id_invalid');
  sectionIds.add(id);
}
const state = { ...request.state, report_blueprint: blueprint, report_sections: [] };
return [{ json: { ...request, state, decision_state: state } }];`,
  [2900, 1500],
  'urban-agent-validate-report-blueprint',
);
const saveBlueprintNode = postgresNode(
  '保存报告蓝图',
  `UPDATE analysis_runs SET decision_state = $2::jsonb, current_step = 'report_blueprint', heartbeat_at = NOW(), lease_expires_at = NOW() + INTERVAL '6 hours', updated_at = NOW()
WHERE id = $1::uuid AND tenant_id = $3::text;
SELECT $1::text AS run_id;`,
  "={{ [$json.run_id, JSON.stringify($json.decision_state ?? $json.state ?? {}), $json.tenant_id] }}",
  [3160, 1500],
  'urban-agent-save-report-blueprint',
);
const expandReportSectionsNode = codeNode(
  '展开报告章节队列',
  `const input = $input.first()?.json ?? {};
const state = input.decision_state && typeof input.decision_state === 'object' ? input.decision_state : {};
const blueprint = input.state?.report_blueprint ?? input.decision_state?.report_blueprint;
const sections = Array.isArray(blueprint?.sections) ? blueprint.sections : [];
if (!sections.length) throw new Error('report_sections_empty');
const completedIds = new Set((Array.isArray(state.report_sections) ? state.report_sections : [])
  .filter((item) => String(item?.content ?? '').trim())
  .map((item) => String(item?.section_id ?? '')));
return sections.filter((section) => !completedIds.has(String(section?.section_id ?? ''))).map((section, index) => ({ json: {
  run_id: input.run_id,
  tenant_id: String(input.tenant_id ?? $('合并项目上下文').first().json.tenant_id ?? 'default'),
  project_question: String(input.project_question ?? $('合并项目上下文').first().json.project_question ?? ''),
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
  `return [{ json: $input.first()?.json ?? {} }];`,
  [4200, 1580],
  'urban-agent-build-report-section-request',
);
const reportSectionModelPlaceholder = codeNode('调用报告章节写作模型', 'return $input.all();', [4440, 1580], 'urban-agent-report-section-model');
const validateReportSectionNode = codeNode(
  '校验报告章节正文',
  `const request = $('构建报告章节写作请求').first().json;
const sectionOutput = $input.first()?.json ?? {};
if (sectionOutput.error || sectionOutput.detail) throw new Error('codex_harness_failed:' + String(sectionOutput.error?.message ?? sectionOutput.detail ?? sectionOutput.error));
const content = String(sectionOutput.content ?? '').trim();
if (!content || String(sectionOutput.section_id ?? '').trim() !== String(request.section?.section_id ?? '').trim()) throw new Error('report_section_identity_mismatch');
const state = request.state && typeof request.state === 'object' ? request.state : {};
const existing = Array.isArray(state.report_sections) ? state.report_sections.filter((item) => item?.section_id !== request.section.section_id) : [];
const reportSection = { section_id: request.section.section_id, title: String(sectionOutput.title ?? request.section.title), content, section_order: Number(request.section_order ?? 0) };
const nextState = { ...state, report_sections: [...existing, reportSection].sort((left, right) => Number(left.section_order ?? 0) - Number(right.section_order ?? 0)) };
return [{ json: { ...request, decision_state: nextState, report_section: reportSection } }];`,
  [4680, 1580],
  'urban-agent-validate-report-section',
);
const saveReportSectionNode = postgresNode(
  '保存报告章节状态',
  `UPDATE analysis_runs SET decision_state = $2::jsonb, current_step = 'report_sections', heartbeat_at = NOW(), lease_expires_at = NOW() + INTERVAL '6 hours', updated_at = NOW()
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
const checkReportSectionsNode = codeNode(
  '检查报告章节恢复状态',
  `const row = $input.first()?.json ?? {};
const state = row.decision_state && typeof row.decision_state === 'object' ? row.decision_state : {};
const blueprint = state.report_blueprint && typeof state.report_blueprint === 'object' ? state.report_blueprint : {};
const expectedIds = (Array.isArray(blueprint.sections) ? blueprint.sections : []).map((item) => String(item?.section_id ?? '')).filter(Boolean);
const completedIds = new Set((Array.isArray(state.report_sections) ? state.report_sections : [])
  .filter((item) => String(item?.content ?? '').trim())
  .map((item) => String(item?.section_id ?? '')));
const sectionsComplete = expectedIds.length === 5 && expectedIds.every((sectionId) => completedIds.has(sectionId));
return [{ json: { ...row, decision_state: state, report_sections_complete: sectionsComplete } }];`,
  [3220, 1780],
  'urban-agent-check-report-sections',
);
const reportSectionsCompleteNode = {
  parameters: {
    conditions: {
      options: { caseSensitive: true, leftValue: '', typeValidation: 'strict', version: 2 },
      conditions: [{
        id: 'report-sections-complete',
        leftValue: '={{ $json.report_sections_complete === true }}',
        rightValue: true,
        operator: { type: 'boolean', operation: 'true', singleValue: true },
      }],
      combinator: 'and',
    },
    options: {},
  },
  id: 'urban-agent-report-sections-complete',
  name: '报告章节已完成？',
  type: 'n8n-nodes-base.if',
  typeVersion: 2.2,
  position: [3420, 1780],
};
graph.nodes.push(buildBlueprintNode, blueprintModelPlaceholder, validateBlueprintNode, saveBlueprintNode, expandReportSectionsNode, reportSectionLoopNode, readReportSectionStateNode, buildReportSectionRequestNode, reportSectionModelPlaceholder, validateReportSectionNode, saveReportSectionNode, readCompletedReportSectionsNode, checkReportSectionsNode, reportSectionsCompleteNode);
connect(graph, '读取完整分析状态', '检查综合方案恢复状态');
connect(graph, '检查综合方案恢复状态', '综合方案已完成？');
graph.connections['综合方案已完成？'] = { main: [
  [{ node: '检查报告章节恢复状态', type: 'main', index: 0 }],
  [{ node: '构建跨单元综合请求', type: 'main', index: 0 }],
] };
connect(graph, '构建跨单元综合请求', '调用 Codex Harness 综合方案');
connect(graph, '调用 Codex Harness 综合方案', '校验报告蓝图');
connect(graph, '校验报告蓝图', '保存报告蓝图');
connect(graph, '保存报告蓝图', '读取报告章节完成状态');
connect(graph, '读取报告章节完成状态', '检查报告章节恢复状态');
connect(graph, '检查报告章节恢复状态', '报告章节已完成？');
graph.connections['报告章节已完成？'] = { main: [
  [{ node: '构建图件设计请求', type: 'main', index: 0 }],
  [{ node: '展开报告章节队列', type: 'main', index: 0 }],
] };
connect(graph, '展开报告章节队列', '逐节生成统一报告');
graph.connections['逐节生成统一报告'] = { main: [
  [{ node: '读取报告章节完成状态', type: 'main', index: 0 }],
  [{ node: '读取报告章节状态', type: 'main', index: 0 }],
] };
connect(graph, '读取报告章节状态', '构建报告章节写作请求');
connect(graph, '校验报告章节正文', '保存报告章节状态');
connect(graph, '保存报告章节状态', '逐节生成统一报告');
graph.connections['合并项目上下文'] = { main: [[{ node: '构建整体研究框架', type: 'main', index: 0 }], [{ node: '记录任务失败', type: 'main', index: 0 }]] };
connect(graph, '确认整体研究框架', '建立自适应分析队列');
connect(graph, '建立自适应分析队列', '逐项执行分析方向');
graph.connections['逐项执行分析方向'] = { main: [
  [{ node: '读取完整分析状态', type: 'main', index: 0 }],
  [{ node: '读取最新分析状态', type: 'main', index: 0 }],
] };
connect(graph, '读取最新分析状态', '合并当前分析方向状态');

const decisionNames = {
  'Validate Step Request': '校验当前分析方向',
  'Step Already Completed': '当前方向已完成？',
  'Return Existing Step Result': '复用已完成章节',
  'Mark Step Running': '标记当前方向执行中',
  'Call Codex Harness': '调用 Codex Harness 分析单元',
  'Validate Decision Output': '校验决策备忘录',
  'Persist Decision State': '保存决策备忘录与分析状态',
  'Return Step Result': '完成当前决策单元',
};
const decision = localizeComponent(decisionSourceForGeneration, {
  names: decisionNames,
  idPrefix: 'urban-agent-decision',
  anchor: [2560, 1940],
  triggerName: 'When Called By Orchestrator',
});
mergeGraph(graph, decision);
connect(graph, '合并当前分析方向状态', decision.entries[0]);
connect(graph, '复用已完成章节', '逐项执行分析方向');
connect(graph, '完成当前决策单元', '逐项执行分析方向');

const sectionHarnessNode = {
  parameters: {
    method: 'POST', url: '=__SPATIAL_API_BASE_URL__/analysis/spatial-strategy/harness/write-section',
    authentication: 'genericCredentialType', genericAuthType: 'httpHeaderAuth', sendBody: true,
    contentType: 'json', specifyBody: 'json',
    jsonBody: '={{ JSON.stringify({ project_question: $json.project_question, solution: $json.solution, section: $json.current_section }) }}',
    options: { timeout: 3600000, response: { response: { responseFormat: 'json' } } },
  },
  id: 'urban-agent-section-codex-harness', name: '调用 Codex Harness 撰写章节',
  type: 'n8n-nodes-base.httpRequest', typeVersion: 4.5, position: [4440, 1580],
  credentials: { httpHeaderAuth: { id: 'n8n-webhook-client', name: 'N8N Webhook Client' } }, onError: 'continueErrorOutput',
};
graph.nodes.push(sectionHarnessNode);
const sectionRequest = graph.nodes.find((node) => node.name === '构建报告章节写作请求');
sectionRequest.parameters.jsCode = `const row = $input.first()?.json ?? {};
const input = row.section_input && typeof row.section_input === 'object' ? row.section_input : {};
const state = row.decision_state && typeof row.decision_state === 'object' ? row.decision_state : {};
const section = input.section && typeof input.section === 'object' ? input.section : {};
const blueprint = state.report_blueprint && typeof state.report_blueprint === 'object' ? state.report_blueprint : {};
const solution = {
  executive_summary: blueprint.executive_summary,
  recommended_position: blueprint.recommended_position,
  future_state: blueprint.future_state,
  named_entities: Array.isArray(blueprint.named_entities) ? blueprint.named_entities : [],
  change_mechanisms: blueprint.change_mechanisms,
  target_users: blueprint.target_users,
  use_scenarios: blueprint.use_scenarios,
  function_mix: blueprint.function_mix,
  rejected_alternatives: blueprint.rejected_alternatives,
  action_plan: blueprint.action_plan,
};
const currentSection = {
  section_id: String(section.section_id ?? ''), title: String(section.title ?? ''), judgment: String(section.judgment ?? ''),
  current_basis: Array.isArray(section.current_basis) ? section.current_basis : [], future_goal: String(section.future_goal ?? ''),
  actions: Array.isArray(section.actions) ? section.actions : [], intended_effect: String(section.intended_effect ?? ''),
};
return [{ json: { ...input, state, section, project_question: String(input.project_question ?? ''), solution, current_section: currentSection } }];`;
graph.connections['构建报告章节写作请求'] = { main: [[{ node: '调用 Codex Harness 撰写章节', type: 'main', index: 0 }]] };
graph.connections['调用 Codex Harness 撰写章节'] = { main: [[{ node: '校验报告章节正文', type: 'main', index: 0 }]] };
graph.nodes = graph.nodes.filter((node) => node.name !== '调用报告章节写作模型');
delete graph.connections['调用报告章节写作模型'];


const visualHarnessNode = {
  parameters: {
    method: 'POST', url: '=__SPATIAL_API_BASE_URL__/analysis/spatial-strategy/harness/design-visuals',
    authentication: 'genericCredentialType', genericAuthType: 'httpHeaderAuth', sendBody: true,
    contentType: 'json', specifyBody: 'json',
    jsonBody: '={{ JSON.stringify({ project_question: $json.project_question, solution: $json.solution, available_datasets: $json.available_datasets }) }}',
    options: { timeout: 3600000, response: { response: { responseFormat: 'json' } } },
  },
  id: 'urban-agent-visual-codex-harness', name: '调用 Codex Harness 设计图件',
  type: 'n8n-nodes-base.httpRequest', typeVersion: 4.5, position: [1800, 3300],
  credentials: { httpHeaderAuth: { id: 'n8n-webhook-client', name: 'N8N Webhook Client' } }, onError: 'continueErrorOutput',
};
graph.nodes.push(visualHarnessNode);
const visualRequest = graph.nodes.find((node) => node.name === '构建图件设计请求');
visualRequest.parameters.jsCode = `const completed = $input.first()?.json ?? {};
const request = $('合并项目上下文').first().json;
const projectContext = request.project_context && typeof request.project_context === 'object' ? request.project_context : {};
const blueprint = completed.decision_state?.report_blueprint && typeof completed.decision_state.report_blueprint === 'object' ? completed.decision_state.report_blueprint : {};
const datasets = (Array.isArray(projectContext.datasets) ? projectContext.datasets : [])
  .filter((item) => item && !String(item.dataset_id ?? '').startsWith('document:') && String(item.dataset_id ?? '') !== 'road_nodes')
  .map((item) => ({ dataset_id: String(item.dataset_id ?? ''), title: String(item.title ?? ''), total_count: Number(item.total_count ?? 0), geometry_type: String(item.geometry_type ?? ''), fields: Array.isArray(item.fields) ? item.fields : [] }))
  .filter((item) => item.dataset_id);
return [{ json: {
  ...completed, history_id: request.history_id, project_question: request.project_question,
  project_context: projectContext, available_datasets: datasets,
  solution: { recommended_position: blueprint.recommended_position, future_state: blueprint.future_state, named_entities: Array.isArray(blueprint.named_entities) ? blueprint.named_entities : [], change_mechanisms: blueprint.change_mechanisms, target_users: blueprint.target_users, use_scenarios: blueprint.use_scenarios, function_mix: blueprint.function_mix, action_plan: blueprint.action_plan },
} }];`;
graph.connections['构建图件设计请求'] = { main: [[{ node: '调用 Codex Harness 设计图件', type: 'main', index: 0 }]] };
graph.connections['调用 Codex Harness 设计图件'] = { main: [[{ node: '校验图件设计', type: 'main', index: 0 }]] };
graph.nodes = graph.nodes.filter((node) => node.name !== '调用图件设计模型');
delete graph.connections['调用图件设计模型'];
const normalizeFinalReportNode = codeNode(
  '规范化最终报告响应',
  `const report = $input.first()?.json ?? {};
const fallback = $('准备报告总判断').first()?.json ?? {};
const markdown = String(report.markdown ?? '').trim();
if (!markdown) throw new Error('final_report_markdown_missing');
const assetManifest = report.asset_manifest && typeof report.asset_manifest === 'object' ? report.asset_manifest : {};
if (String(assetManifest.kind ?? '') !== 'docx_report' || !String(assetManifest.filename ?? '').toLowerCase().endsWith('.docx')) throw new Error('final_report_docx_missing');
return [{ json: {
  ...fallback,
  ...report,
  run_id: String(report.run_id ?? fallback.run_id ?? ''),
  markdown,
  citations: Array.isArray(report.citations) ? report.citations : (Array.isArray(fallback.citations) ? fallback.citations : []),
  decision_state: report.decision_state && typeof report.decision_state === 'object' ? report.decision_state : (fallback.decision_state ?? {}),
  asset_manifest: assetManifest,
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
  `const delivered = $input.first()?.json ?? {};
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
const state = input.decision_state && typeof input.decision_state === 'object' ? input.decision_state : {};
const steps = Object.fromEntries(Object.entries(state.steps && typeof state.steps === 'object' ? state.steps : {}).map(([unitId, value]) => {
  const item = value && typeof value === 'object' ? value : {};
  return [unitId, {
    unit_id: String(item.unit_id ?? unitId),
    step_order: Number(item.step_order ?? 0),
    title: String(item.title ?? ''),
    question: String(item.question ?? ''),
    depends_on: Array.isArray(item.depends_on) ? item.depends_on : [],
    decision_output: String(item.decision_output ?? ''),
    evidence_focus: String(item.evidence_focus ?? ''),
    decision_memo: item.decision_memo ?? null,
    citations: Array.isArray(item.citations) ? item.citations : [],
  }];
}));
const retainedState = {
  research_frame: String(state.research_frame ?? ''),
  decision_units: Array.isArray(state.decision_units) ? state.decision_units : [],
  steps,
  report_blueprint: state.report_blueprint && typeof state.report_blueprint === 'object' ? state.report_blueprint : {},
  report_sections: Array.isArray(state.report_sections) ? state.report_sections : [],
};
return [{ json: {
  run_id: String(input.run_id ?? ''),
  history_id: String(input.history_id ?? ''),
  tenant_id: String(input.tenant_id ?? ''),
  title: String(input.title ?? ''),
  summary: String(input.summary ?? ''),
  markdown: String(input.markdown ?? ''),
  citations: Array.isArray(input.citations) ? input.citations : [],
  asset_manifest: input.asset_manifest && typeof input.asset_manifest === 'object' ? input.asset_manifest : {},
  visual_assets: Array.isArray(input.visual_assets) ? input.visual_assets : [],
  decision_state: retainedState,
} }];`,
  [4720, 3500],
  'urban-agent-cleanup-completed-run',
);
graph.nodes.push(cleanupCompletedRunNode);
connect(graph, '生成 Word 报告并发送飞书', '恢复已发送报告上下文');
connect(graph, '恢复已发送报告上下文', '清理成功执行过程数据');
connect(graph, '清理成功执行过程数据', '完成分析任务');

const finalLeaseNode = postgresNode('刷新报告阶段租约', `UPDATE analysis_runs
SET heartbeat_at = NOW(), lease_expires_at = NOW() + INTERVAL '6 hours', updated_at = NOW()
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
connect(graph, '恢复报告图件上下文', '准备报告总判断');

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
