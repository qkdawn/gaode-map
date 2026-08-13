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
  {
    ...node(
      'Claim Queued Analysis Run',
      'n8n-nodes-base.postgres',
      {
        operation: 'executeQuery',
        query: `UPDATE analysis_runs
SET workflow_execution_id = $3::text, status = 'running', current_step = 'step_01_policy_site',
  request = $2::jsonb, started_at = COALESCE(started_at, NOW()), heartbeat_at = NOW(),
  lease_expires_at = NOW() + INTERVAL '15 minutes', updated_at = NOW()
WHERE id = $1::uuid AND tenant_id = $4::text AND status = 'queued'
RETURNING id::text AS run_id, decision_state;`,
        options: { queryReplacement: '={{ [$json.run_id, JSON.stringify($json), $execution.id, $json.tenant_id] }}' },
      },
      [1140, 300],
      '5800374a-a2ca-4884-923f-fd9c25ec35b5',
    ),
    credentials: { postgres: { id: 'rag-postgres', name: 'RAG PostgreSQL' } },
  },
];

const connections = {
  'When Called By API': { main: [[{ node: 'Normalize Analysis Request', type: 'main', index: 0 }]] },
  'Normalize Analysis Request': { main: [[{ node: 'Load Project Context', type: 'main', index: 0 }]] },
  'Load Project Context': { main: [[{ node: 'Attach Project Context', type: 'main', index: 0 }], [{ node: 'Attach Project Context', type: 'main', index: 0 }]] },
  'Attach Project Context': { main: [[{ node: 'Claim Queued Analysis Run', type: 'main', index: 0 }]] },
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
      options: { queryReplacement: '={{ [String($(\'展开领取任务请求\').first().json.run_id || $(\'合并项目上下文\').first().json.run_id || ""), String($json.error?.message || $json.error || $json.message || JSON.stringify($json))] }}' },
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
const steps = completed.decision_state?.steps && typeof completed.decision_state.steps === 'object' ? completed.decision_state.steps : {};
const completedAnalyses = Object.entries(steps).map(([stepKey, value]) => ({ step_key: stepKey, step_order: Number(value?.step_order ?? 0), title: String(value?.title ?? ''), decision_brief: String(value?.decision_brief ?? '').trim(), reader_chapter: String(value?.reader_chapter ?? '').trim() })).filter((item) => item.reader_chapter).sort((left, right) => left.step_order - right.step_order);
const datasets = (Array.isArray(projectContext.datasets) ? projectContext.datasets : []).filter((item) => item && !String(item.dataset_id ?? '').startsWith('document:')).map((item) => ({ dataset_id: String(item.dataset_id ?? ''), title: String(item.title ?? ''), total_count: Number(item.total_count ?? 0), geometry_type: String(item.geometry_type ?? ''), fields: Array.isArray(item.fields) ? item.fields : [] })).filter((item) => item.dataset_id);
const layerSchema = { type: 'object', properties: { dataset_id: { type: 'string' }, role: { type: 'string', enum: ['line', 'point', 'polygon'] }, color: { type: 'string' }, metric_field: { type: 'string' } }, required: ['dataset_id', 'role', 'color', 'metric_field'], additionalProperties: false };
const visualSchema = { type: 'object', properties: {
  title: { type: 'string' }, format: { type: 'string', enum: ['map', 'chart', 'table'] },
  rationale: { type: 'string' }, decision_question: { type: 'string' }, caption: { type: 'string' },
  map_variant: { type: 'string', enum: ['', 'poi_access', 'context_full', 'regional_role'] },
  chart_variant: { type: 'string', enum: ['', 'poi_supply', 'population_profile'] },
  dataset_id: { type: 'string' }, layers: { type: 'array', items: layerSchema }, group_by: { type: 'string' },
  metric_op: { type: 'string', enum: ['count', 'sum', 'avg'] }, metric_field: { type: 'string' },
}, required: ['title', 'format', 'rationale', 'decision_question', 'caption', 'map_variant', 'chart_variant', 'dataset_id', 'layers', 'group_by', 'metric_op', 'metric_field'], additionalProperties: false };
const schema = { type: 'object', properties: { visuals: { type: 'array', minItems: 3, maxItems: 5, items: visualSchema } }, required: ['visuals'], additionalProperties: false };
const instructions = [
  '你是城市空间分析的图件设计 Agent。阅读十二项分析结论后，为本项目设计 3 到 5 张真正改变决策的数据图或表。',
  '每张图必须填写 decision_question 和 caption；caption 要说明证据如何改变定位、产品、空间或实施决策，不能只重复标题。',
  '优先使用专用版式：道路+POI 使用 context_full 或 poi_access；人口与公共节点使用 regional_role；供给结构使用 poi_supply；年龄结构使用 population_profile。',
  '禁止仅用 POI 单层绘制全量散点图；POI 地图必须叠加 road_edges。禁止使用 road_nodes 铺满节点。人口空间地图最多一张，第二个人口视觉应使用 population_profile 图表。',
  '夜光地图使用 nightlight.radiance，并可叠加 road_edges；道路图使用 road_edges 的道路层级。至少包含一张专用空间关系图和一张图表，避免全部输出数据集分布图。',
  '渲染器会读取每个指定数据集的完整项目数据包，再进行绘制或聚合。不得要求抽样、截断、AI 绘画或编造空间事实。',
].join('\\n');
return [{ json: {
  ...completed,
  history_id: request.history_id,
  project_question: request.project_question,
  project_context: projectContext,
  available_datasets: datasets,
  instructions,
  input: JSON.stringify({ project_question: request.project_question, completed_analyses: completedAnalyses, available_datasets: datasets }),
  max_output_tokens: 2400,
  reasoning: { effort: 'low' },
  text: { format: { type: 'json_schema', name: 'spatial_visual_design', strict: true, schema } },
} }];`,
    },
    [11940, 300],
    'build-visual-agent-request-000000000000000000000',
  ),
  onError: 'continueErrorOutput',
  retryOnFail: true,
  maxTries: 2,
  waitBetweenTries: 5000,
});

nodes.push({
  ...node(
    '生成项目数据图件 Agent',
    'n8n-nodes-base.executeWorkflow',
    {
      source: 'database',
      workflowId: { __rl: true, value: 'codexRelayResponse1', mode: 'id' },
      workflowInputs: { mappingMode: 'defineBelow', value: {}, matchingColumns: [], schema: [], attemptToConvertTypes: false, convertFieldsToString: true },
      mode: 'once',
      options: { waitForSubWorkflow: true },
    },
    [12180, 300],
    'generate-visual-agent-000000000000000000000000',
  ),
  onError: 'continueErrorOutput',
  retryOnFail: true,
  maxTries: 2,
  waitBetweenTries: 5000,
});

nodes.push({
  ...node(
    'Validate Visual Design',
    'n8n-nodes-base.code',
    {
      mode: 'runOnceForAllItems',
      jsCode: `const request = $('Build Visual Agent Request').first().json;
const response = $input.first()?.json ?? {};
let parsed;
const rawOutput = String(response.output_text ?? '').trim();
if (!rawOutput && response.error) {
  const upstreamStatus = Number(response.error?.status ?? response.error?.statusCode ?? 0) || 'unknown';
  const upstreamMessage = String(response.error?.message ?? response.error).slice(0, 500);
  return [{ json: { ...request, visual_plan: [], visual_diagnostics: [{ kind: 'visual_model_unavailable', status: upstreamStatus, message: upstreamMessage }] } }];
}
const jsonCandidates = [rawOutput];
const fenceMarker = String.fromCharCode(96).repeat(3);
const fenced = rawOutput.match(new RegExp(fenceMarker + '(?:json)?\\s*([\\s\\S]*?)\\s*' + fenceMarker, 'i'));
if (fenced?.[1]) jsonCandidates.push(fenced[1].trim());
const objectStart = rawOutput.indexOf('{');
const objectEnd = rawOutput.lastIndexOf('}');
if (objectStart >= 0 && objectEnd > objectStart) jsonCandidates.push(rawOutput.slice(objectStart, objectEnd + 1));
for (const candidate of jsonCandidates) {
  try { parsed = JSON.parse(candidate); break; } catch {}
}
if (!parsed) return [{ json: { ...request, visual_plan: [], visual_diagnostics: [{ kind: 'visual_model_invalid_json', message: rawOutput.slice(0, 500) }] } }];
const visuals = Array.isArray(parsed.visuals) ? parsed.visuals.slice(0, 6) : [];
if (visuals.length < 3 || visuals.length > 5) throw new Error('visual plan requires three to five visuals');
const availableIds = new Set((request.available_datasets ?? []).map((item) => String(item.dataset_id ?? '')));
const titles = new Set();
const signatures = new Set();
let chartCount = 0;
let populationMapCount = 0;
let specializedContextCount = 0;
for (const visual of visuals) {
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
    const hasPopulation = layerIds.includes('population');
    if (hasPoi && !hasRoad) throw new Error('poi map requires road context');
    if (hasPoi && !String(visual.map_variant ?? '')) throw new Error('poi map requires a decision map variant');
    if (hasPopulation) populationMapCount += 1;
    if (['poi_access', 'context_full', 'regional_role'].includes(String(visual.map_variant ?? ''))) specializedContextCount += 1;
  }
}
if (populationMapCount > 1) throw new Error('visual plan contains duplicate population maps');
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
if (Array.isArray(request.visual_diagnostics) && request.visual_diagnostics.length > 0 && rendered.status !== 'ready') {
  return [{ json: { ...request, status: 'ready', assets: [], visual_diagnostics: request.visual_diagnostics } }];
}
if (rendered.status !== 'ready') throw new Error('project visual rendering failed');
return [{ json: { ...request, ...rendered, assets: Array.isArray(rendered.assets) ? rendered.assets : [] } }];`,
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
const request = $('Attach Project Context').first().json;
const steps = rendered.decision_state?.steps && typeof rendered.decision_state.steps === 'object' ? rendered.decision_state.steps : {};
const decisionChain = Object.entries(steps).map(([stepKey, value]) => ({ step_key: stepKey, step_order: Number(value?.step_order ?? 0), title: String(value?.title ?? ''), decision_brief: String(value?.decision_brief ?? '').trim() })).filter((item) => item.decision_brief).sort((left, right) => left.step_order - right.step_order);
if (decisionChain.length !== 12) throw new Error('report editorial requires twelve completed analyses');
const visualAssets = (Array.isArray(rendered.assets) ? rendered.assets : []).map((item) => ({ kind: String(item?.kind ?? ''), title: String(item?.title ?? ''), design: item?.design && typeof item.design === 'object' ? item.design : {} }));
const schema = { type: 'object', properties: { narrative: { type: 'string', minLength: 1 } }, required: ['narrative'], additionalProperties: false };
const instructions = [
  '你是空间策略报告的总编，只在十二项客观分析全部完成后工作。读者是项目甲方、政府决策者或投资人；用可信、有判断力且可执行的项目叙事，帮助他们理解并认可证据所支持的方案。',
  '输入的 decision_chain 是十二章自由表达的阶段判断，不是审计表。用它重建完整的决策逻辑：上游判断如何改变后续定位、产品、空间、运营和分期。找出真正推动最终选择的依赖关系、冲突与不可逆取舍，而不是复述每章结论。完整章节正文会由报告组装器原样保留，你只负责总判断和章节之间的衔接。',
  '不要按十二章顺序逐项摘要。先找出贯穿全稿的核心矛盾、竞争性解释和最终取舍，再说明选择如何形成、最脆弱的前提是什么、一期用什么记录确认或改判。',
  '重要结论、方案选择和不可行路径应紧邻已有数据、材料、同类案例或反例。证据不完整但足以比较路径时，可以作出尺度相称的明确判断，但必须保留原分析中的证据边界、反证、条件和不确定性。',
  '只能重组和表达输入中已经成立的判断，不得新增事实、数字、案例、承诺或因果关系，不得把条件性结论改写成确定事实，也不得掩盖不利证据。',
  '只输出可直接置于报告开头的决策叙事正文，不输出报告标题或十二章目录。不得输出任何内部步骤键、状态枚举、节点名、工作流名、引用 ID 或规则名。',
].join('\\n');
return [{ json: {
  ...rendered,
  instructions,
  input: JSON.stringify({ project_question: request.project_question, research_frame: String(rendered.decision_state?.research_frame ?? ''), project: request.project_context?.project ?? {}, decision_chain: decisionChain, visual_assets: visualAssets }),
  max_output_tokens: 3000,
  reasoning: { effort: 'high' },
  text: { format: { type: 'json_schema', name: 'spatial_report_editorial', strict: true, schema } },
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
    '生成决策叙事 Agent',
    'n8n-nodes-base.executeWorkflow',
    {
      source: 'database',
      workflowId: { __rl: true, value: 'codexRelayResponse1', mode: 'id' },
      workflowInputs: { mappingMode: 'defineBelow', value: {}, matchingColumns: [], schema: [], attemptToConvertTypes: false, convertFieldsToString: true },
      mode: 'once',
      options: { waitForSubWorkflow: true },
    },
    [13660, 300],
    'generate-report-editorial-agent-0000000000000000',
  ),
  onError: 'continueErrorOutput',
  retryOnFail: true,
  maxTries: 2,
  waitBetweenTries: 5000,
});

nodes.push({
  ...node(
    'Validate Report Editorial',
    'n8n-nodes-base.code',
    {
      mode: 'runOnceForAllItems',
      jsCode: `const request = $('Build Report Editorial Request').first().json;
const response = $input.first()?.json ?? {};
let parsed;
const rawOutput = String(response.output_text ?? '').trim();
const editorialDiagnostics = [];
if (!rawOutput && response.error) editorialDiagnostics.push({ kind: 'report_editorial_model_unavailable', status: Number(response.error?.status ?? 0) || 'unknown', message: String(response.error?.message ?? response.error).slice(0, 500) });
for (const candidate of [rawOutput, rawOutput.slice(rawOutput.indexOf('{'), rawOutput.lastIndexOf('}') + 1)]) {
  if (!candidate) continue;
  try { parsed = JSON.parse(candidate); break; } catch {}
}
if (!parsed) return [{ json: { ...request, editorial_narrative: '', editorial_diagnostics: editorialDiagnostics.length ? editorialDiagnostics : [{ kind: 'report_editorial_invalid_json', message: rawOutput.slice(0, 500) }] } }];
const editorialNarrative = String(parsed.narrative ?? '').trim();
if (!editorialNarrative) return [{ json: { ...request, editorial_narrative: '', editorial_diagnostics: [{ kind: 'report_editorial_empty' }] } }];
const leakagePatterns = [/step[_-]?\\d{1,2}/i, /decision_state/i, /quality_gate/i, /evidence_index/i, /\\bn8n\\b/i, /(?:node|节点)[ _-]?(?:id|编号)/i, /(?:run|workflow|response)[ _-]?id/i];
if (leakagePatterns.some((pattern) => pattern.test(editorialNarrative))) throw new Error('report editorial contains internal terms');
return [{ json: { ...request, editorial_narrative: editorialNarrative } }];`,
    },
    [13900, 300],
    'validate-report-editorial-00000000000000000000',
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
        decision_state: $json.decision_state,
        visual_assets: $json.assets ?? [],
        editorial_narrative: $json.editorial_narrative,
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
      jsonBody: '={{ JSON.stringify({ run_id: $json.run_id, title: $json.title, summary: $json.summary, markdown: $json.markdown, citations: $json.citations, decision_state: $json.decision_state, visual_assets: $json.visual_assets ?? [] }) }}',
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
connections['Claim Queued Analysis Run'] = {
  main: [[{ node: 'Build Visual Agent Request', type: 'main', index: 0 }]],
};
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
  main: [
    [{ node: '生成决策叙事 Agent', type: 'main', index: 0 }],
    [{ node: '记录任务失败', type: 'main', index: 0 }],
  ],
};
connections['生成决策叙事 Agent'] = {
  main: [
    [{ node: 'Validate Report Editorial', type: 'main', index: 0 }],
    [{ node: '记录任务失败', type: 'main', index: 0 }],
  ],
};
connections['Validate Report Editorial'] = {
  main: [
    [{ node: '编排空间策略报告', type: 'main', index: 0 }],
    [{ node: '记录任务失败', type: 'main', index: 0 }],
  ],
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
  ['Claim Queued Analysis Run', '认领待执行分析任务'],
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
  ['Build Report Editorial Request', '构建报告叙事请求'],
  ['生成决策叙事 Agent', '调用报告叙事模型'],
  ['Validate Report Editorial', '校验报告叙事'],
  ['编排空间策略报告', '生成最终报告'],
  ['发送报告到飞书？', '需要发送飞书？'],
  ['生成 Word 报告并发送到飞书', '生成 Word 报告并发送飞书'],
  ['Complete Analysis Run', '完成分析任务'],
], 'urban-agent-report', [0, 0], { 'Attach Project Context': '合并项目上下文' });
