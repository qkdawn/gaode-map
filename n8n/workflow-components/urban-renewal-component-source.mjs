const node = (name, type, parameters, position, id) => ({
  parameters,
  id,
  name,
  type,
  typeVersion: type === 'n8n-nodes-base.code' ? 2 : type === 'n8n-nodes-base.postgres' ? 2.7 : type === 'n8n-nodes-base.httpRequest' ? 4.5 : 1.3,
  position,
});

const nodes = [
  node(
    'When Called By API',
    'n8n-nodes-base.executeWorkflowTrigger',
    { inputSource: 'passthrough' },
    [180, 300],
    '0c1fd6ff-8f66-4df8-9ecb-a243fb16c1f3',
  ),
  node(
    'Normalize Analysis Request',
    'n8n-nodes-base.code',
    {
      mode: 'runOnceForAllItems',
      jsCode: `const input = $input.first()?.json ?? {};
const question = String(input.project_question ?? input.question ?? '').trim();
if (!question) throw new Error('project_question is required');
const list = (value) => Array.isArray(value) ? value.map(String).filter(Boolean) : [];
const tenantId = String(input.tenant_id ?? '').trim();
if (!tenantId) throw new Error('tenant_id is required');
const runId = String(input.run_id ?? '').trim();
if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(runId)) throw new Error('run_id must be a UUID');
const accessGroups = list(input.access_groups);
return [{ json: {
  run_id: runId,
  project_question: question,
  history_id: String(input.history_id ?? ''),
  tenant_id: tenantId,
  access_groups: accessGroups,
  project_types: list(input.project_types),
  geography: list(input.geography),
  metadata_filter: input.metadata_filter && typeof input.metadata_filter === 'object' ? input.metadata_filter : {},
  requested_at: new Date().toISOString(),
} }];`,
    },
    [420, 300],
    '33669941-b452-4edf-805b-3b6c9d9e158b',
  ),
  {
    ...node(
      'Load Project Context',
      'n8n-nodes-base.httpRequest',
      {
        method: 'POST',
        url: '=__SPATIAL_API_BASE_URL__/analysis/spatial-strategy/project-data/context',
        authentication: 'genericCredentialType',
        genericAuthType: 'httpHeaderAuth',
        sendBody: true,
        contentType: 'json',
        specifyBody: 'json',
        jsonBody: '={{ JSON.stringify({ history_id: $json.history_id, tenant_id: $json.tenant_id }) }}',
        options: { timeout: 600000, response: { response: { responseFormat: 'json' } } },
      },
      [660, 300],
      'load-project-context-000000000000000000000',
    ),
    credentials: { httpHeaderAuth: { id: 'n8n-webhook-client', name: 'n8n Webhook Client' } },
    onError: 'continueErrorOutput',
    retryOnFail: true,
    maxTries: 2,
    waitBetweenTries: 3000,
  },
  node(
    'Attach Project Context',
    'n8n-nodes-base.code',
    {
      mode: 'runOnceForAllItems',
      jsCode: `const request = $('Normalize Analysis Request').first().json;
const response = $input.first()?.json ?? {};
const context = response.project && Array.isArray(response.datasets) ? response : {};
const resolvedHistoryId = String(response.history_id ?? response.project?.history_id ?? request.history_id ?? '').trim();
return [{ json: {
  ...request,
  history_id: resolvedHistoryId,
  project_context: context,
  project_context_status: context.project ? 'available' : 'unavailable',
  project_context_error: context.project ? '' : String(response.error?.message ?? response.message ?? response.error ?? 'project_context_unavailable'),
} }];`,
    },
    [900, 300],
    'attach-project-context-0000000000000000000',
  ),
];

const connections = {
  'When Called By API': { main: [[{ node: 'Normalize Analysis Request', type: 'main', index: 0 }]] },
  'Normalize Analysis Request': { main: [[{ node: 'Load Project Context', type: 'main', index: 0 }]] },
  'Load Project Context': { main: [[{ node: 'Attach Project Context', type: 'main', index: 0 }], [{ node: 'Attach Project Context', type: 'main', index: 0 }]] },
};

const failureNode = {
  ...node(
    '记录任务失败',
    'n8n-nodes-base.postgres',
    {
      operation: 'executeQuery',
      query: `WITH failed_run AS (
  UPDATE analysis_runs
  SET status = 'failed', error = $2::text, finished_at = NOW(), updated_at = NOW()
  WHERE id = $1::uuid AND status NOT IN ('completed', 'cancelled')
  RETURNING id, status, current_step, error, finished_at
), failed_step AS (
  UPDATE analysis_step_outputs AS step
  SET status = 'failed',
    diagnostics = COALESCE(step.diagnostics, '[]'::jsonb) || jsonb_build_array(jsonb_build_object('kind', 'execution_error', 'message', $2::text)),
    updated_at = NOW()
  FROM failed_run
  WHERE step.run_id = failed_run.id AND step.step = failed_run.current_step AND step.status = 'running'
  RETURNING step.step
)
SELECT id::text AS run_id, status, current_step, error, finished_at FROM failed_run;`,
      options: { queryReplacement: '={{ [String($(\'展开领取任务请求\').first().json.run_id || $(\'合并项目上下文\').first().json.run_id || ""), String($json.error?.message || (typeof $json.error === "string" ? $json.error : JSON.stringify($json.error || {})) || $json.message || JSON.stringify($json))] }}' },
    },
    [12180, 540],
    '15d4ef40-a51a-48d6-b0d1-06049065a187',
  ),
  credentials: { postgres: { id: 'rag-postgres', name: 'RAG PostgreSQL' } },
};
nodes.push(failureNode);

nodes.push({
  ...node(
    'Build Visual Agent Request',
    'n8n-nodes-base.code',
    {
      mode: 'runOnceForAllItems',
      jsCode: `const completed = $input.first()?.json ?? {};
const request = $('Attach Project Context').first().json;
const projectContext = request.project_context && typeof request.project_context === 'object' ? request.project_context : {};
return [{ json: {
  ...completed,
  history_id: request.history_id,
  project_question: request.project_question,
  project_context: projectContext,
  visual_task: '为11个策略章节选择3到5张最能解释方案取舍的数据图或表，并指定每张图所属策略单元。',
} }];`,
    },
    [11940, 300],
    'build-visual-agent-request-000000000000000000000',
  ),
});

nodes.push({
  ...node(
    '生成项目数据图件 Agent',
    'n8n-nodes-base.httpRequest',
    {
      method: 'POST',
      url: '=__SPATIAL_API_BASE_URL__/analysis/spatial-strategy/harness/design-visuals',
      authentication: 'genericCredentialType',
      genericAuthType: 'httpHeaderAuth',
      sendBody: true,
      contentType: 'json',
      specifyBody: 'json',
      jsonBody: '={{ JSON.stringify({ run_id: $json.run_id, project_question: $json.project_question, visual_task: $json.visual_task }) }}',
      options: { timeout: 3600000, response: { response: { responseFormat: 'json' } } },
    },
    [12180, 300],
    'generate-visual-agent-000000000000000000000000',
  ),
  credentials: { httpHeaderAuth: { id: 'n8n-webhook-client', name: 'N8N Webhook Client' } },
  onError: 'continueErrorOutput',
});

nodes.push({
  ...node(
    'Validate Visual Design',
    'n8n-nodes-base.code',
    {
      mode: 'runOnceForAllItems',
      jsCode: `const request = $('Build Visual Agent Request').first().json;
const response = $input.first()?.json ?? {};
if (response.error || response.detail) throw new Error('codex_harness_failed:' + String(response.error?.message ?? response.detail ?? response.error));
const visuals = Array.isArray(response.visuals) ? response.visuals : [];
if (visuals.length < 3 || visuals.length > 5) throw new Error('visual plan requires three to five visuals');
const availableIds = new Set((request.project_context?.datasets ?? []).map((item) => String(item.dataset_id ?? '')));
const sectionIds = new Set(['project_basis', 'regional_role', 'supply_gap', 'audience_use', 'theme_resources', 'positioning', 'product_mix', 'spatial_layout', 'operating_model', 'investment_operation', 'phasing']);
const titles = new Set();
const signatures = new Set();
let chartCount = 0;
let specializedContextCount = 0;
for (const visual of visuals) {
  if (!sectionIds.has(String(visual.section_id ?? ''))) throw new Error('visual plan section is invalid');
  const title = String(visual.title ?? '').trim();
  const rationale = String(visual.rationale ?? '').trim();
  const decisionQuestion = String(visual.decision_question ?? '').trim();
  const caption = String(visual.caption ?? '').trim();
  if (title.length < 4 || rationale.length < 8 || decisionQuestion.length < 8 || caption.length < 12) throw new Error('visual plan lacks decision context');
  if (titles.has(title)) throw new Error('visual plan contains duplicate titles');
  titles.add(title);
  const format = String(visual.format ?? '');
  const layers = Array.isArray(visual.layers) ? visual.layers : [];
  const layerIds = layers.map((layer) => String(layer.dataset_id ?? '')).filter(Boolean);
  if (layerIds.includes('road_nodes')) throw new Error('visual plan must not render all road nodes');
  const signature = [format, visual.map_variant ?? '', visual.chart_variant ?? '', visual.dataset_id ?? '', [...layerIds].sort().join('+'), visual.group_by ?? '', visual.metric_field ?? ''].join('|');
  if (signatures.has(signature)) throw new Error('visual plan contains duplicate evidence views');
  signatures.add(signature);
  if (format === 'chart') chartCount += 1;
  if (format === 'map') {
    const hasPoi = layerIds.includes('poi');
    const hasRoad = layerIds.includes('road_edges');
    if (hasPoi && !hasRoad) throw new Error('poi map requires road context');
    if (hasPoi && !String(visual.map_variant ?? '')) throw new Error('poi map requires a decision map variant');
    if (['poi_access', 'context_full', 'regional_role'].includes(String(visual.map_variant ?? ''))) specializedContextCount += 1;
  }
}
if ((availableIds.has('poi') || availableIds.has('population')) && chartCount < 1) throw new Error('visual plan requires an explanatory chart');
if (availableIds.has('poi') && availableIds.has('road_edges') && specializedContextCount < 1) throw new Error('visual plan requires a specialized context map');
return [{ json: { ...request, visual_plan: visuals } }];`,
    },
    [12660, 300],
    'validate-visual-design-00000000000000000000000',
  ),
  onError: 'continueErrorOutput',
  retryOnFail: true,
  maxTries: 2,
  waitBetweenTries: 5000,
});

nodes.push({
  ...node(
    'Render Designed Data Visuals',
    'n8n-nodes-base.httpRequest',
    {
      method: 'POST',
      url: '=__SPATIAL_API_BASE_URL__/analysis/spatial-strategy/visuals',
      authentication: 'genericCredentialType',
      genericAuthType: 'httpHeaderAuth',
      sendBody: true,
      contentType: 'json',
      specifyBody: 'json',
      jsonBody: '={{ JSON.stringify({ run_id: $json.run_id, history_id: $json.history_id, project_context: $json.project_context, visual_plan: $json.visual_plan }) }}',
      options: { timeout: 600000, response: { response: { responseFormat: 'json' } } },
    },
    [12900, 300],
    'render-designed-visuals-0000000000000000000000',
  ),
  credentials: { httpHeaderAuth: { id: 'n8n-webhook-client', name: 'n8n Webhook Client' } },
  onError: 'continueErrorOutput',
  retryOnFail: true,
  maxTries: 2,
  waitBetweenTries: 5000,
});

nodes.push({
  ...node(
    'Return Visual Assets',
    'n8n-nodes-base.code',
    {
      mode: 'runOnceForAllItems',
      jsCode: `const request = $('Validate Visual Design').first().json;
const rendered = $input.first()?.json ?? {};
if (rendered.status !== 'ready') throw new Error('project visual rendering failed');
const assets = Array.isArray(rendered.assets) ? rendered.assets : [];
if (assets.length < 3 || assets.length > 5) throw new Error('project visual rendering requires three to five assets');
return [{ json: { ...request, ...rendered, assets } }];`,
    },
    [13140, 300],
    'return-visual-assets-000000000000000000000000',
  ),
});

nodes.push({
  ...node(
    'Build Report Editorial Request',
    'n8n-nodes-base.code',
    {
      mode: 'runOnceForAllItems',
      jsCode: `const rendered = $input.first()?.json ?? {};
const chapters = Array.isArray(rendered.chapters) ? rendered.chapters : [];
const expectedIds = ['project_basis', 'regional_role', 'supply_gap', 'audience_use', 'theme_resources', 'positioning', 'product_mix', 'spatial_layout', 'operating_model', 'investment_operation', 'phasing'];
if (chapters.length !== expectedIds.length || chapters.some((chapter, index) => String(chapter?.unit_id ?? '') !== expectedIds[index])) throw new Error('report_requires_ordered_strategy_chapters');
return [{ json: {
  ...rendered,
  chapters,
} }];`,
    },
    [13400, 300],
    'build-report-editorial-request-00000000000000000',
  ),
  onError: 'continueErrorOutput',
  retryOnFail: true,
  maxTries: 2,
  waitBetweenTries: 5000,
});

nodes.push({
  ...node(
    '编排空间策略报告',
    'n8n-nodes-base.httpRequest',
    {
      method: 'POST',
      url: '=__SPATIAL_API_BASE_URL__/analysis/spatial-strategy/reports/compose',
      authentication: 'genericCredentialType',
      genericAuthType: 'httpHeaderAuth',
      sendBody: true,
      contentType: 'json',
      specifyBody: 'json',
      jsonBody: `={{ JSON.stringify({
        run_id: $json.run_id,
        history_id: $('Attach Project Context').first().json.history_id,
        project_question: $('Attach Project Context').first().json.project_question,
        project_context: $('Attach Project Context').first().json.project_context,
        chapters: $json.chapters,
        visual_assets: $json.assets ?? [],
      }) }}`,
      options: { timeout: 600000, response: { response: { responseFormat: 'json' } } },
    },
    [14140, 300],
    'compose-spatial-report-000000000000000000000000',
  ),
  credentials: { httpHeaderAuth: { id: 'n8n-webhook-client', name: 'n8n Webhook Client' } },
  onError: 'continueErrorOutput',
  retryOnFail: true,
  maxTries: 2,
  waitBetweenTries: 5000,
});

nodes.push({
  ...node(
    '发送报告到飞书？',
    'n8n-nodes-base.if',
    {
      conditions: {
        options: { caseSensitive: true, leftValue: '', typeValidation: 'strict', version: 2 },
        conditions: [{ id: 'deliver-report-to-feishu', leftValue: "={{ $('Attach Project Context').first().json.deliver_to_feishu === true }}", rightValue: true, operator: { type: 'boolean', operation: 'true', singleValue: true } }],
        combinator: 'and',
      },
      options: {},
    },
    [14400, 300],
    'deliver-report-to-feishu-choice-000000000000',
  ),
  typeVersion: 2.2,
});

nodes.push({
  ...node(
    '生成 Word 报告并发送到飞书',
    'n8n-nodes-base.httpRequest',
    {
      method: 'POST',
      url: '=__SPATIAL_API_BASE_URL__/analysis/spatial-strategy/reports/deliver',
      authentication: 'genericCredentialType',
      genericAuthType: 'httpHeaderAuth',
      sendBody: true,
      contentType: 'json',
      specifyBody: 'json',
      jsonBody: '={{ JSON.stringify({ run_id: $json.run_id, title: $json.title, summary: $json.summary, markdown: $json.markdown, citations: $json.citations, chapters: $json.chapters, visual_assets: $json.visual_assets ?? [] }) }}',
      options: { timeout: 600000, response: { response: { responseFormat: 'json' } } },
    },
    [14640, 220],
    'deliver-spatial-report-feishu-000000000000',
  ),
  credentials: { httpHeaderAuth: { id: 'n8n-webhook-client', name: 'n8n Webhook Client' } },
  onError: 'continueErrorOutput',
  retryOnFail: true,
  maxTries: 2,
  waitBetweenTries: 5000,
});

nodes.push({
  ...node(
    'Complete Analysis Run',
    'n8n-nodes-base.postgres',
    {
      operation: 'executeQuery',
      query: `WITH completed AS (
  UPDATE analysis_runs SET status = 'completed', current_step = 'completed', decision_state = $2::jsonb,
    finished_at = NOW(), updated_at = NOW() WHERE id = $1::uuid
  RETURNING id, status, current_step, decision_state, finished_at
), persisted AS (
  INSERT INTO analysis_reports (run_id, status, markdown, citations, asset_manifest, created_at, updated_at)
  SELECT id, 'ready', $3::text, $4::jsonb, $5::jsonb, NOW(), NOW() FROM completed
  ON CONFLICT (run_id) DO UPDATE SET status = EXCLUDED.status, markdown = EXCLUDED.markdown,
    citations = EXCLUDED.citations, asset_manifest = EXCLUDED.asset_manifest, updated_at = NOW()
  RETURNING run_id
)
SELECT c.id::text AS run_id, c.status, c.current_step, c.decision_state, c.finished_at
FROM completed c;`,
      options: { queryReplacement: '={{ [$json.run_id, JSON.stringify($json.decision_state ?? {}), $json.markdown, JSON.stringify($json.citations ?? []), JSON.stringify($json.asset_manifest ?? {})] }}' },
    },
    [14880, 300],
    'c28a69ea-081f-4eef-b1c8-06a0580757d5',
  ),
  credentials: { postgres: { id: 'rag-postgres', name: 'RAG PostgreSQL' } },
});
connections['Build Visual Agent Request'] = {
  main: [
    [{ node: '生成项目数据图件 Agent', type: 'main', index: 0 }],
    [{ node: '记录任务失败', type: 'main', index: 0 }],
  ],
};
connections['生成项目数据图件 Agent'] = {
  main: [
    [{ node: 'Validate Visual Design', type: 'main', index: 0 }],
    [{ node: '记录任务失败', type: 'main', index: 0 }],
  ],
};
connections['Validate Visual Design'] = {
  main: [
    [{ node: 'Render Designed Data Visuals', type: 'main', index: 0 }],
    [{ node: '记录任务失败', type: 'main', index: 0 }],
  ],
};
connections['Render Designed Data Visuals'] = {
  main: [
    [{ node: 'Return Visual Assets', type: 'main', index: 0 }],
    [{ node: '记录任务失败', type: 'main', index: 0 }],
  ],
};
connections['Return Visual Assets'] = {
  main: [
    [{ node: 'Build Report Editorial Request', type: 'main', index: 0 }],
    [{ node: '记录任务失败', type: 'main', index: 0 }],
  ],
};
connections['Build Report Editorial Request'] = {
  main: [[{ node: '编排空间策略报告', type: 'main', index: 0 }]],
};
connections['编排空间策略报告'] = {
  main: [
    [{ node: '发送报告到飞书？', type: 'main', index: 0 }],
    [{ node: '记录任务失败', type: 'main', index: 0 }],
  ],
};
connections['发送报告到飞书？'] = {
  main: [
    [{ node: '生成 Word 报告并发送到飞书', type: 'main', index: 0 }],
    [{ node: '完成分析任务', type: 'main', index: 0 }],
  ],
};
connections['生成 Word 报告并发送到飞书'] = {
  main: [
    [{ node: '完成分析任务', type: 'main', index: 0 }],
    [{ node: '记录任务失败', type: 'main', index: 0 }],
  ],
};

const rename = (value, names) => {
  if (Array.isArray(value)) return value.map((item) => rename(item, names));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, rename(item, names)]));
  if (typeof value !== 'string') return value;
  return Object.entries(names).sort((a, b) => b[0].length - a[0].length).reduce((result, [from, to]) => result.replaceAll(from, to), value);
};

function component(nodeNames, idPrefix, anchor = [0, 0], replacements = {}) {
  const names = { ...replacements, ...Object.fromEntries(nodeNames.map(([from, to]) => [from, to])) };
  const selected = nodes.filter((item) => nodeNames.some(([from]) => item.name === from));
  const selectedNames = new Set(selected.map((item) => item.name));
  const minX = Math.min(...selected.map((item) => Number(item.position?.[0] ?? 0)));
  const minY = Math.min(...selected.map((item) => Number(item.position?.[1] ?? 0)));
  const localized = selected.map((item, index) => ({
    ...rename(item, names),
    id: `${idPrefix}-${String(index + 1).padStart(2, '0')}`,
    name: names[item.name],
    position: [anchor[0] + Number(item.position[0]) - minX, anchor[1] + Number(item.position[1]) - minY],
  }));
  const localizedConnections = {};
  for (const [source, definition] of Object.entries(connections)) {
    if (!selectedNames.has(source)) continue;
    localizedConnections[names[source]] = rename({ main: (definition.main ?? []).map((output) => (output ?? []).filter((edge) => selectedNames.has(edge.node))) }, names).main;
    localizedConnections[names[source]] = { main: localizedConnections[names[source]] };
  }
  return { nodes: localized, connections: localizedConnections };
}

export const projectContextComponent = component([
  ['Load Project Context', '读取项目上下文'],
  ['Attach Project Context', '合并项目上下文'],
], 'urban-agent-context', [0, 0], { 'Normalize Analysis Request': '构建分析执行上下文' });

export const failureHandlingComponent = component([
  ['记录任务失败', '记录任务失败'],
], 'urban-agent-failure', [0, 0]);

export const visualsComponent = component([
  ['Build Visual Agent Request', '构建图件设计请求'],
  ['生成项目数据图件 Agent', '调用图件设计模型'],
  ['Validate Visual Design', '校验图件设计'],
  ['Render Designed Data Visuals', '生成项目数据图件'],
  ['Return Visual Assets', '整理项目图件'],
], 'urban-agent-visuals', [0, 0], { 'Attach Project Context': '合并项目上下文' });

export const reportComponent = component([
  ['Build Report Editorial Request', '准备顺序组装报告'],
  ['编排空间策略报告', '生成最终报告'],
  ['发送报告到飞书？', '需要发送飞书？'],
  ['生成 Word 报告并发送到飞书', '生成 Word 报告并发送飞书'],
  ['Complete Analysis Run', '完成分析任务'],
], 'urban-agent-report', [0, 0], { 'Attach Project Context': '合并项目上下文' });
