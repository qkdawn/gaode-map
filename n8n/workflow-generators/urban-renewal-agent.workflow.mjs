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
    "'{}'::jsonb",
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
if (!reportForGeneration.nodes.some((node) => node.name === '准备顺序组装报告')) throw new Error('report_chapters_node_missing');
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
const definitions = [
  ['project_basis', '项目材料与项目基础', '当前项目已有材料实际说明了哪些会改变方案选择的对象、数字、关系和设想？', [], '形成当前材料对项目方向和行动选择的实际影响', '当前项目已提供的原始材料', []],
  ['regional_role', '项目类型与区域角色', '项目与区域节点、道路、公共服务和居住片区形成什么分工？', ['project_basis'], '比较候选区域角色并确定主次角色', '具名节点、道路、公共服务、居住背景与场地能力', ['基于项目目录中可用的具名区域节点、道路层级、公共服务和居住背景，判断项目更适合承担社区服务点、街坊协同节点还是更高层级角色；不要把客流、来源转换或真实步行圈作为必需证据。', '请求 regional_anchor 具名POI候选，展开决定区域角色的设施与道路；用方向和网格指标说明空间背景，但不把代理指标写成客流或跨区域到达关系。']],
  ['supply_gap', '具名供给与服务空位', '现有具名设施已经解决什么，项目还能提供什么增量价值？', ['regional_role'], '识别真实服务空位和不应复制的供给', '分类供给、具名设施、替代与协同对象', ['对可用H3或网格指标识别供给高低值、人口与服务错位，以及POI、路网、人口或夜光的共同高值、共同低值和信号冲突。', '请求 regional_anchor 和 daily_service 具名POI候选，展开优先与排除单元中的相交道路和邻近对象，说明真实替代、协同和连接缺口。']],
  ['audience_use', '客群与使用', '项目优先服务哪些客群，他们分别在什么情境下使用？', ['supply_gap'], '比较核心、次级和暂不选择客群，明确使用情境与验证方式', '统一年度人口底盘、客群任务、使用情境、替代选择和行为验证', ['人口总量与年龄结构使用项目目录中的同一年度确定性汇总；方向和等时圈只解释内部空间分布，不另行形成项目人口总量。结合年龄结构、公共服务供给和项目材料推导居民日常复访、机构预约等行为、时段与付费意愿假设，同时写明访谈、预约、到场或价格验证方式；不要把假设写成已观测客流或消费事实，也不要求来源转换或跨区域到达数据。', '请求 daily_service 具名POI候选，只把它们作为需要核实的替代环境或候选接洽清单；不得根据POI类别或距离推断客群来源、招募价值、合作意愿或到访关系。无法从现有数据确认的到达方式，直接标记为待现场验证。']],
  ['theme_resources', '地方资源与共同机制', '哪些真实资源关系能够转成持续使用的主题和场景？', ['project_basis', 'audience_use'], '比较主题路径并提炼共同机制', '项目原文、历史关系、场地资源和使用任务', []],
  ['positioning', '候选定位比较', '哪一种定位最能同时回应区域空位、使用者任务和场地能力？', ['regional_role', 'supply_gap', 'audience_use', 'theme_resources'], '以同一标准比较至少三个候选定位并选出唯一推荐', '前序领域判断及候选定位能力要求', []],
  ['product_mix', '场景与产品组合', '如何把资源机制和定位转成具体故事、场景、服务与产品？', ['positioning', 'theme_resources', 'audience_use'], '形成资源到产品的转译链和最小产品组合', '主题机制、用户任务、空间载体与价值交换', []],
  ['spatial_layout', '空间组织与具体落位', '产品和运行流程应落到当前项目已知的哪些空间对象与连接关系？', ['product_mix', 'project_basis', 'supply_gap'], '比较布局方案并形成具名空间配置', '当前材料和空间数据中的具名对象、连接关系与使用流程', ['读取供给空位单元及其相邻空间单元，判断高值、错位或机会信号能否形成连续联系，识别断点和缓冲边界。', '请求 regional_anchor 和 daily_service 具名POI候选，展开重点单元、入口方向和连接对象中的具名道路及邻近关系，把外部到达、内部使用和居民界面落到具体路径。']],
  ['operating_model', '运营组织与合作关系', '谁负责开放、内容、活动、维护、居民协同和合作运营？', ['product_mix', 'spatial_layout'], '比较运营模式并明确主体、接口和协同关系', '产品流程、空间节点、业主与合作关系', []],
  ['investment_operation', '投入与运营判断', '根据当前已有材料和空间方案，哪种相对投入和运营方式更适合项目？', ['product_mix', 'spatial_layout', 'operating_model'], '比较相对投入强弱、实施难度、运营复杂度、资金承担与可持续运行方式', '当前项目材料、空间动作、产品组合与运营方式', []],
  ['phasing', '首期闭环与后续分期', '首期做哪些建设和运营动作才能形成完整闭环，之后如何推进？', ['investment_operation'], '形成首期项目包、责任主体、实施顺序和后续分期', '前序定位、产品、空间、运营与投资判断', []],
];
const decisionUnits = definitions.map(([unit_id, title, question, depends_on, decision_output, evidence_focus, spatial_questions]) => ({ unit_id, title, question, depends_on, decision_output, evidence_focus, spatial_questions }));
const researchFrame = '项目材料与项目基础 → 区域角色 → 供给空位 → 客群与使用 → 地方机制 → 定位 → 产品 → 空间落位 → 运营 → 投入与运营 → 分期';
return [{ json: { ...request, research_frame: researchFrame, decision_units: decisionUnits, decision_state: { research_frame: researchFrame, decision_units: decisionUnits } } }];`, [1540, 1860], 'urban-agent-build-research-frame');
const validateResearchFrameNode = codeNode('确认整体研究框架', `const response = $input.first()?.json ?? {};
const researchFrame = String(response.research_frame ?? response.decision_state?.research_frame ?? '').trim();
const decisionUnits = Array.isArray(response.decision_state?.decision_units) ? response.decision_state.decision_units : response.decision_units;
const expected = ['project_basis', 'regional_role', 'supply_gap', 'audience_use', 'theme_resources', 'positioning', 'product_mix', 'spatial_layout', 'operating_model', 'investment_operation', 'phasing'];
if (!researchFrame || !Array.isArray(decisionUnits) || decisionUnits.length !== expected.length || decisionUnits.some((unit, index) => String(unit?.unit_id ?? '') !== expected[index] || !Array.isArray(unit?.spatial_questions))) throw new Error('decision_units_must_follow_strategy_chain');
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
    spatial_questions: Array.isArray(item?.spatial_questions) ? item.spatial_questions.map(String).filter(Boolean) : [],
  },
})).filter((item) => item.step_key && item.step_title && item.research_brief);
if (adaptiveSteps.length !== 11) throw new Error('decision_units_must_follow_strategy_chain');
const steps = adaptiveSteps;
const decisionUnits = steps.map((item) => item.decision_unit);
return steps.map(({ step_key, step_title, research_brief, decision_unit }, index) => ({ json: {
  run_id: String(claimed.run_id ?? request.run_id), tenant_id: request.tenant_id,
  history_id: request.history_id, project_question: request.project_question,
  access_groups: request.access_groups, project_types: request.project_types,
  geography: request.geography, metadata_filter: request.metadata_filter,
  project_context: request.project_context, research_frame: request.research_frame,
  decision_units: decisionUnits,
  decision_state: { research_frame: request.research_frame, decision_units: decisionUnits },
  step_key, step_title, research_brief, decision_unit, step_order: index + 1,
} }));`, [1540, 1860], 'urban-agent-build-step-queue');
const loopNode = {
  parameters: { batchSize: 1, options: {} },
  id: 'urban-agent-step-loop', name: '逐项执行分析方向',
  type: 'n8n-nodes-base.splitInBatches', typeVersion: 3, position: [1800, 1860],
};
const readStateNode = postgresNode('读取最新分析状态', `SELECT $1::jsonb AS step_input, r.decision_state,
(
  SELECT step.output
  FROM analysis_step_outputs AS step
  WHERE step.run_id = r.id AND step.step = $1::jsonb->>'step_key' AND step.status = 'completed'
) AS completed_output
FROM analysis_runs AS r WHERE r.id = ($1::jsonb->>'run_id')::uuid AND r.tenant_id = $1::jsonb->>'tenant_id';`,
  '={{ [JSON.stringify($json)] }}', [2060, 1940], 'urban-agent-read-current-state');
const attachStateNode = codeNode('合并当前分析方向状态', `const row = $input.first()?.json ?? {};
const input = row.step_input && typeof row.step_input === 'object' ? row.step_input : {};
const stored = row.decision_state && typeof row.decision_state === 'object' ? row.decision_state : {};
const existingOutput = row.completed_output && typeof row.completed_output === 'object' ? row.completed_output : null;
return [{ json: { ...input, existing_output: existingOutput, decision_state: stored } }];`,
  [2300, 1940], 'urban-agent-attach-step-state');
const readCompleteStateNode = postgresNode('读取完整分析状态', `SELECT r.id::text AS run_id, r.status, r.current_step, r.decision_state,
COALESCE((
  SELECT jsonb_agg(step.output ORDER BY step.step_order, step.step)
  FROM analysis_step_outputs AS step
  WHERE step.run_id = r.id AND step.status = 'completed'
), '[]'::jsonb) AS chapters
FROM analysis_runs AS r WHERE r.id = $1::uuid AND r.tenant_id = $2::text;`,
  "={{ [$('合并项目上下文').first().json.run_id, $('合并项目上下文').first().json.tenant_id] }}",
  [2060, 1780], 'urban-agent-read-complete-state');
graph.nodes.push(queueNode, loopNode, readStateNode, attachStateNode, readCompleteStateNode);
connect(graph, '读取完整分析状态', '构建图件设计请求');
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
  'Validate Decision Output': '校验策略章节',
  'Persist Decision State': '保存策略章节',
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

const visualHarnessNode = {
  parameters: {
    method: 'POST', url: '=__SPATIAL_API_BASE_URL__/analysis/spatial-strategy/harness/design-visuals',
    authentication: 'genericCredentialType', genericAuthType: 'httpHeaderAuth', sendBody: true,
    contentType: 'json', specifyBody: 'json',
    jsonBody: '={{ JSON.stringify({ run_id: $json.run_id, project_question: $json.project_question, visual_task: $json.visual_task }) }}',
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
const chapters = Array.isArray(completed.chapters) ? completed.chapters : [];
const expectedIds = ['project_basis', 'regional_role', 'supply_gap', 'audience_use', 'theme_resources', 'positioning', 'product_mix', 'spatial_layout', 'operating_model', 'investment_operation', 'phasing'];
if (chapters.length !== expectedIds.length || chapters.some((chapter, index) => {
  const keys = chapter && typeof chapter === 'object' ? Object.keys(chapter).sort() : [];
  return String(chapter?.unit_id ?? '') !== expectedIds[index]
    || !String(chapter?.title ?? '').trim()
    || !String(chapter?.content ?? '').trim()
    || !Array.isArray(chapter?.citations)
    || JSON.stringify(keys) !== JSON.stringify(['citations', 'content', 'title', 'unit_id']);
})) throw new Error('strategy_report_requires_all_chapters');
return [{ json: {
  ...completed, history_id: request.history_id, project_question: request.project_question,
  project_context: projectContext,
  chapters,
  visual_task: '为11个策略章节选择3到5张最能解释方案取舍的数据图或表，并指定每张图所属策略单元。',
} }];`;
graph.connections['构建图件设计请求'] = { main: [[{ node: '调用 Codex Harness 设计图件', type: 'main', index: 0 }]] };
graph.connections['调用 Codex Harness 设计图件'] = { main: [[{ node: '校验图件设计', type: 'main', index: 0 }]] };
graph.nodes = graph.nodes.filter((node) => node.name !== '调用图件设计模型');
delete graph.connections['调用图件设计模型'];
const normalizeFinalReportNode = codeNode(
  '规范化最终报告响应',
  `const report = $input.first()?.json ?? {};
const fallback = $('准备顺序组装报告').first()?.json ?? {};
if (report.error || report.detail) throw new Error('report_compose_failed:' + String(report.error?.message ?? report.detail ?? report.error));
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
  chapters: Array.isArray(report.chapters) ? report.chapters : (Array.isArray(fallback.chapters) ? fallback.chapters : []),
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
  chapters: Array.isArray(delivered.chapters) ? delivered.chapters : (composed.chapters ?? []),
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
const retainedState = {
  research_frame: String(state.research_frame ?? ''),
  decision_units: Array.isArray(state.decision_units) ? state.decision_units : [],
};
return [{ json: {
  run_id: String(input.run_id ?? ''),
  history_id: String(input.history_id ?? ''),
  tenant_id: String(input.tenant_id ?? ''),
  title: String(input.title ?? ''),
  summary: String(input.summary ?? ''),
  markdown: String(input.markdown ?? ''),
  citations: Array.isArray(input.citations) ? input.citations : [],
  chapters: Array.isArray(input.chapters) ? input.chapters : [],
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
connect(graph, '恢复报告图件上下文', '准备顺序组装报告');

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
  sticky('策略章节说明', '## 11 章策略链\n章节按项目基础、区域角色、供给空位、客群与使用、地方机制、定位、产品、空间、运营、投入与分期依赖执行；已成功章节直接复用。', [1040, 1560], [5700, 1500], 'urban-agent-note-loop'),
  sticky('报告生成说明', '## 图件与最终报告\n11 个已完成章节直接装配成报告；另行设计 3 至 5 张真实数据图件，生成 Markdown/DOCX 并按需发送飞书。', [1040, 3140], [4700, 980], 'urban-agent-note-report'),
);

export default assertFormalWorkflow({
  id: 'urbanRenewalDecisionSupportAgent',
  name: '城市更新决策支持 Agent', active: true,
  nodes: graph.nodes, connections: graph.connections,
  settings: { executionOrder: 'v1', executionTimeout: 14400 },
  versionId: 'ad07173c-d412-4859-8924-265ed2aedc18',
  meta: { templateCredsSetupCompleted: true }, tags: [],
});
