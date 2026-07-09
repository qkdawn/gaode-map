import fs from 'node:fs'
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  createAnalysisAgentInitialState,
  createAnalysisAgentSessionMethods,
  buildAnalysisTaskParamBundle,
  deriveAgentSessionPreview,
  getAnalysisTaskDefinition,
  resolveAnalysisTaskKeyFromTrace,
  normalizeAgentToolSummary,
  normalizeAgentTurnPayload,
  sortAgentSessions,
} from '../src/features/agent/sessions.js'
import {
  buildAgentAnalysisSnapshot,
  buildAgentPoiH3Evidence,
} from '../src/features/agent/analysis-snapshot-evidence.js'

const agentMethods = createAnalysisAgentSessionMethods()

test('agent tabs keep analysis workspace as canonical tab field', () => {
  const state = createAnalysisAgentInitialState()

  assert.equal(Object.keys(state.agentTabs).includes('analysisWorkspaceTabs'), true)
  assert.equal(Object.keys(state.agentTabs).includes('pptPlanningTabs'), false)

  state.agentTabs.analysisWorkspaceTabs = [{ id: 'analysis-1' }]
  assert.equal(state.agentTabs.analysisWorkspaceTabs[0].id, 'analysis-1')
  assert.equal(JSON.stringify(state.agentTabs).includes('pptPlanningTabs'), false)
})

function createSseResponse(events = []) {
  const encoder = new TextEncoder()
  const stream = new ReadableStream({
    start(controller) {
      events.forEach((event) => {
        controller.enqueue(
          encoder.encode(`event: ${event.type}\ndata: ${JSON.stringify(event.payload)}\n\n`),
        )
      })
      controller.close()
    },
  })
  return {
    ok: true,
    body: stream,
  }
}

function createAbortError() {
  const error = new Error('aborted')
  error.name = 'AbortError'
  return error
}

function createAbortablePendingResponse(signal) {
  return new Promise((_resolve, reject) => {
    const rejectAbort = () => reject(createAbortError())
    if (signal && signal.aborted) {
      rejectAbort()
      return
    }
    if (signal && typeof signal.addEventListener === 'function') {
      signal.addEventListener('abort', rejectAbort, { once: true })
    }
  })
}

function createDeferred() {
  let resolve
  let reject
  const promise = new Promise((promiseResolve, promiseReject) => {
    resolve = promiseResolve
    reject = promiseReject
  })
  return { promise, resolve, reject }
}

async function waitForDeferred(promise, label = 'expected async step did not start') {
  let timer = null
  try {
    await Promise.race([
      promise,
      new Promise((_resolve, reject) => {
        timer = setTimeout(() => reject(new Error(label)), 1000)
      }),
    ])
  } finally {
    if (timer) clearTimeout(timer)
  }
}

function getAgentSessionDetailId(url = '') {
  const match = String(url).match(/^\/api\/v1\/analysis\/agent\/sessions\/([^/?]+)/)
  return match ? decodeURIComponent(match[1]) : ''
}

function createAgentSessionDetailResponse(ctx, url = '') {
  const sessionId = getAgentSessionDetailId(url) || ctx.activeAgentSessionId
  const session = (typeof ctx.findAgentSession === 'function' ? ctx.findAgentSession(sessionId) : null) || {}
  const plan = session.plan || ctx.agentPlan || {}
  return {
    ok: true,
    async json() {
      return {
        id: sessionId,
        title: session.title || '社区商业概览',
        title_source: session.titleSource || 'ai',
        preview: session.preview || session.answer || ctx.agentAnswer || '',
        status: session.status || ctx.agentStatus || 'answered',
        stage: session.stage || ctx.agentStage || 'answered',
        panel_kind: session.panelKind || 'followup',
        history_id: session.historyId || (typeof ctx.getCurrentAgentHistoryId === 'function' ? ctx.getCurrentAgentHistoryId() : ''),
        is_pinned: !!session.isPinned,
        created_at: session.createdAt || '2026-04-05T00:00:00Z',
        updated_at: session.updatedAt || '2026-04-05T01:00:00Z',
        pinned_at: session.pinnedAt || null,
        input: session.input || '',
        messages: Array.isArray(session.messages) ? session.messages : ctx.agentMessages,
        output: {
          answer: session.answer || ctx.agentAnswer || '',
          clarification_question: session.clarificationQuestion || '',
          clarification_options: session.clarificationOptions || [],
          risk_prompt: session.riskPrompt || '',
          panel_payloads: session.panelPayloads || ctx.agentPanelPayloads || {},
        },
        diagnostics: {
          execution_trace: session.executionTrace || ctx.agentExecutionTrace || [],
          used_tools: session.usedTools || ctx.agentUsedTools || [],
          citations: session.citations || ctx.agentCitations || [],
          research_notes: session.researchNotes || ctx.agentResearchNotes || [],
          audit_issues: session.auditIssues || ctx.agentAuditIssues || [],
          thinking_timeline: session.thinkingTimeline || ctx.agentThinkingTimeline || [],
          error: session.error || ctx.agentError || '',
        },
        context_summary: session.contextSummary || ctx.agentContextSummary || {},
        plan: {
          steps: plan.steps || [],
          summary: plan.summary || '',
        },
        risk_confirmations: session.riskConfirmations || [],
      }
    },
  }
}

function createAgentContext(overrides = {}) {
  const state = createAnalysisAgentInitialState()
const defaultYearlyGridEvidence = {
  evidence_version: 'poi_iteration_yearly_grid_evidence_v1',
  years: [2023, 2024, 2025],
  grid_scope: 'poi_iteration_h3_per_year',
  grid_type: 'h3',
  latest_year: 2025,
  latest_h3_evidence: { evidence_version: 'poi_h3_evidence_v1' },
  items: [
      { year: 2023, status: 'ready', h3_evidence: {} },
      { year: 2024, status: 'ready', h3_evidence: {} },
      { year: 2025, status: 'ready', h3_evidence: {} },
  ],
  h3_items: [
      { year: 2023, status: 'ready', h3_evidence: {} },
      { year: 2024, status: 'ready', h3_evidence: {} },
      { year: 2025, status: 'ready', h3_evidence: {} },
  ],
  raster_items: [
      { year: 2023, status: 'ready', raster_evidence: {} },
      { year: 2024, status: 'ready', raster_evidence: {} },
      { year: 2025, status: 'ready', raster_evidence: {} },
  ],
}
  const basePayloads = {
    ...state.agentPanelPayloads,
    iteration_change: {
      ...(state.agentPanelPayloads.iteration_change || {}),
      poi: {
        ...((state.agentPanelPayloads.iteration_change || {}).poi || {}),
        yearly_grid_evidence: defaultYearlyGridEvidence,
      },
    },
  }
  const ctx = {
    ...state,
    ...agentMethods,
    agentPanelPayloads: basePayloads,
    sidebarView: 'wizard',
    step: 2,
    activeStep3Panel: 'agent',
    scopeSource: '',
    transportMode: 'walking',
    timeHorizon: 15,
    roadSyntaxSummary: null,
    populationOverview: null,
    nightlightOverview: null,
    allPoisDetails: [],
    h3AnalysisSummary: null,
    h3GridCount: 0,
    roadSyntaxDiagnostics: null,
    resultDataSource: 'local',
    poiDataSource: 'local',
    h3AnalysisCharts: {},
    h3GridResolution: 10,
    h3AnalysisGridFeatures: [],
    isComputingH3Analysis: false,
    isComputingPopulation: false,
    isComputingNightlight: false,
    isComputingRoadSyntax: false,
    h3NeighborRing: 1,
    h3GridMinOverlapRatio: 0.15,
    h3MetricView: 'density',
    h3StructureFillMode: 'gi_z',
    h3OnlySignificant: false,
    h3EntropyMinPoi: 3,
    h3LqSmoothingAlpha: 0.5,
    h3TargetCategory: '',
    h3CategoryMeta: [],
    h3DerivedStats: {},
    roadSyntaxMetric: 'connectivity',
    roadSyntaxMainTab: 'params',
    populationAnalysisView: 'analysis',
    nightlightAnalysisView: 'grid',
    lastNonAgentStep3Panel: 'poi',
    getIsochronePolygonRing() {
      return [[1, 1], [1, 2], [2, 2], [1, 1]]
    },
    getIsochronePolygonPayload() {
      return [[1, 1], [1, 2], [2, 2], [1, 1]]
    },
    getDrawnScopePolygonPoints() {
      return []
    },
    selectStep3Panel(panelId) {
      this.activeStep3Panel = panelId
    },
    $nextTick(callback) {
      if (typeof callback === 'function') callback()
      return Promise.resolve()
    },
  }
  return Object.assign(ctx, overrides)
}

function markSiteSelectionDataReady(ctx) {
  ctx.allPoisDetails = [{ id: 'poi-1', name: '咖啡样本' }]
  ctx.h3AnalysisSummary = { grid_count: 3, poi_count: 1 }
  ctx.h3GridCount = 3
  ctx.h3AnalysisGridFeatures = [{ properties: { h3_id: '8928308280fffff' } }]
  ctx.populationOverview = { summary: { total_population: 12000 } }
  ctx.nightlightOverview = { summary: { mean_radiance: 3.2 } }
  ctx.roadSyntaxSummary = { node_count: 10, edge_count: 12 }
  ctx.roadSyntaxStatus = '计算完成'
}

function buildSummaryPack(summary = '当前总结') {
  return {
    headline_judgment: { summary },
    secondary_conclusions: ['次级结论'],
    user_profile: { headline: '用户画像', traits: ['稳定客群'] },
    behavior_inference: { headline: '行为判断', traits: ['停留时长中等'] },
    evidence_refs: ['evidence-1'],
  }
}

test('sortAgentSessions keeps pinned sessions before newer unpinned sessions', () => {
  const sessions = sortAgentSessions([
    { id: 'b', isPinned: false, updatedAt: '2026-04-05T10:00:00Z', createdAt: '2026-04-05T10:00:00Z' },
    { id: 'a', isPinned: true, pinnedAt: '2026-04-05T09:00:00Z', updatedAt: '2026-04-05T08:00:00Z', createdAt: '2026-04-05T08:00:00Z' },
  ])

  assert.deepEqual(sessions.map((item) => item.id), ['a', 'b'])
})

test('normalizeAgentTurnPayload reads staged backend response shape', () => {
  const normalized = normalizeAgentTurnPayload({
    status: 'answered',
    stage: 'answered',
    output: {
      answer: '这里以社区商业为主，当前更适合继续做方向性预研。',
      panel_payloads: { h3_result: { summary: { grid_count: 8 } } },
    },
    diagnostics: {
      execution_trace: [{ tool_name: 'read_current_scope', status: 'success' }],
      used_tools: ['read_current_scope'],
      citations: ['analysis_snapshot.h3.summary'],
      research_notes: ['已复用现有结果'],
      audit_issues: ['不能直接推断经营收益'],
      planning_summary: '先读取范围，再分析业态结构',
      audit_summary: '证据完整，可直接回答',
      replan_count: 1,
      latency_ms: { gate: 120, tool_loop: 340, total: 980 },
      thinking_timeline: [{ id: 'thinking-1', phase: 'gating', title: '输入检查完成', detail: '已确认范围。', state: 'completed' }],
      error: '',
    },
    context_summary: {
      has_scope: true,
      available_results: ['pois', 'h3'],
      active_panel: 'agent',
      filters_digest: { poi_source: 'local' },
    },
    plan: {
      steps: [{ tool_name: 'read_current_scope', reason: '读取范围' }],
      summary: '先读取范围，再分析业态结构',
    },
  })

  assert.equal(normalized.output.answer, '这里以社区商业为主，当前更适合继续做方向性预研。')
  assert.equal(normalized.output.panelPayloads.h3_result.summary.grid_count, 8)
  assert.deepEqual(normalized.diagnostics.usedTools, ['read_current_scope'])
  assert.deepEqual(normalized.diagnostics.auditIssues, ['不能直接推断经营收益'])
  assert.equal(normalized.diagnostics.planningSummary, '先读取范围，再分析业态结构')
  assert.equal(normalized.diagnostics.auditSummary, '证据完整，可直接回答')
  assert.equal(normalized.diagnostics.replanCount, 1)
  assert.deepEqual(normalized.diagnostics.latencyMs, { gate: 120, tool_loop: 340, total: 980 })
  assert.equal(normalized.diagnostics.thinkingTimeline[0].id, 'thinking-1')
  assert.equal(normalized.contextSummary.active_panel, 'agent')
  assert.equal(normalized.plan.summary, '先读取范围，再分析业态结构')
})

test('context ask target normalization keeps a stable schema', () => {
  const ctx = createAgentContext()
  const target = ctx.normalizeContextAskTarget({
    type: 'site_candidate',
    id: 'h3-1',
    title: '候选点',
    source: 'site_selection',
    summary: '人口和活力较好',
    evidence: ['poi', { tool: 'population' }],
    artifact_refs: ['artifact-1'],
    payload: { rank: 1 },
  })

  assert.equal(target.type, 'site_candidate')
  assert.equal(target.source, 'site_selection')
  assert.equal(target.id, 'h3-1')
  assert.deepEqual(target.artifactRefs, ['artifact-1'])
  assert.equal(target.payload.rank, 1)
})

test('openContextAsk does not mutate legacy chat state', () => {
  const ctx = createAgentContext()
  ctx.agentInput = '旧输入'
  ctx.agentMessages = [{ role: 'user', content: '旧消息' }]

  ctx.openContextAsk(ctx.buildReportSectionContextAskTarget({
    sectionKey: 'headline',
    title: '核心判断',
    summary: '商业活力较强',
  }))

  assert.equal(ctx.contextAskVisible, true)
  assert.equal(ctx.contextAskTarget.type, 'report_section')
  assert.equal(ctx.agentInput, '旧输入')
  assert.deepEqual(ctx.agentMessages.map((item) => item.content), ['旧消息'])
})

test('context ask survives report detail tab switching', () => {
  const ctx = createAgentContext()
  ctx.openContextAsk({ type: 'report_section', title: '核心判断', source: 'report', summary: 'A' })
  ctx.contextAskMessages.push({ role: 'user', content: '为什么？' })

  const iterationId = ctx.openAgentIterationChangeFromReport({ autoload: false })
  ctx.openAgentSiteSelectionFromReport()
  ctx.switchAgentTopTab(iterationId)

  assert.equal(ctx.contextAskVisible, true)
  assert.equal(ctx.contextAskTarget.title, '核心判断')
  assert.deepEqual(ctx.contextAskMessages.map((item) => item.content), ['我会围绕“核心判断”解释，不会离开当前区域上下文。', '为什么？'])
})

test('analysis composer deep mode uses main agent loop and keeps user message raw', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.openAgentPptPlanningFromReport()
  ctx.agentInput = '识别断点街区'

  ctx.toggleAgentComposerMenu()
  assert.equal(ctx.agentComposerMenuOpen, true)
  ctx.selectAgentComposerMode('deep')
  assert.equal(ctx.agentComposerMode, 'deep')
  assert.equal(ctx.agentComposerMenuOpen, false)

  let requestBody = null
  const previousFetch = global.fetch
  global.fetch = async (url, options = {}) => {
    if (getAgentSessionDetailId(url)) return createAgentSessionDetailResponse(ctx, url)
    assert.equal(url, '/api/v1/analysis/agent/main-loop/stream')
    requestBody = JSON.parse(String(options.body || '{}'))
    return createSseResponse([
      {
        type: 'final',
        payload: {
          response: {
            status: 'answered',
            stage: 'answered',
            output: {
              answer: '断点集中在低连通高活力错配街区。',
              clarification_question: '',
              clarification_options: [],
              risk_prompt: '',
              panel_payloads: {},
            },
            diagnostics: { execution_trace: [], used_tools: [], citations: [], research_notes: [], audit_issues: [], thinking_timeline: [], error: '' },
            context_summary: { has_scope: true, available_results: [], active_panel: 'agent', filters_digest: {} },
            plan: { steps: [] },
            messages: [
              { role: 'assistant', content: '断点集中在低连通高活力错配街区。' },
            ],
            risk_confirmations: [],
          },
        },
      },
    ])
  }

  try {
    await ctx.submitAgentComposer()
  } finally {
    global.fetch = previousFetch
  }

  assert.equal(Object.prototype.hasOwnProperty.call(requestBody, 'thinking_mode'), false)
  assert.equal(requestBody.messages[0].content, '识别断点街区')
  assert.doesNotMatch(requestBody.messages[0].content, /深度分析工作方式/)
  assert.deepEqual(ctx.agentMessages.map((item) => item.content), ['识别断点街区', '断点集中在低连通高活力错配街区。'])
  assert.equal(ctx.agentMessages[1].role, 'assistant')
  assert.equal(ctx.agentComposerMode, '')
})

test('composer plus menu preserves new report action and clears deep mode', () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.openAgentFollowupFromSummary('', '追问解释')
  ctx.selectAgentComposerMode('deep')
  assert.equal(ctx.agentComposerMode, 'deep')

  ctx.startAgentComposerNewReportSession()

  assert.equal(ctx.agentComposerMode, '')
  assert.equal(ctx.agentWorkspaceView, 'report')
  assert.ok(ctx.activeAgentSessionId)
})

test('submitContextAskQuestion appends user and assistant messages', async () => {
  const ctx = createAgentContext()
  const calls = []
  const previousFetch = global.fetch
  global.fetch = async (url, options = {}) => {
    calls.push({ url, body: JSON.parse(options.body || '{}') })
    return {
      ok: true,
      async json() {
        return { status: 'success', answer: '依据 POI 和人口证据判断。', evidence: ['e1'], citations: ['c1'], warnings: [] }
      },
    }
  }
  ctx.activeAgentSessionId = 'agent-1'
  ctx.openContextAsk({ type: 'report_section', title: '核心判断', source: 'report', summary: 'A' }, { resetMessages: true })

  try {
    await ctx.submitContextAskQuestion('为什么？')
  } finally {
    global.fetch = previousFetch
  }

  assert.equal(calls[0].url, '/api/v1/analysis/agent/context-ask')
  assert.equal(calls[0].body.conversation_id, 'agent-1')
  assert.equal(calls[0].body.target.title, '核心判断')
  assert.deepEqual(ctx.contextAskMessages.slice(-2).map((item) => item.content), ['为什么？', '依据 POI 和人口证据判断。'])
})

test('normalizeAgentTurnPayload keeps backward compatibility when structured output is absent', () => {
  const normalized = normalizeAgentTurnPayload({
    status: 'answered',
    output: {
      answer: '这里只能先做方向性判断',
    },
  })

  assert.equal(normalized.output.answer, '这里只能先做方向性判断')
})

test('deriveAgentSessionPreview prefers answer text', () => {
  const preview = deriveAgentSessionPreview({
    messages: [{ role: 'user', content: '总结这个区域' }],
    answer: '这里以社区商业为主',
  })

  assert.equal(preview, '这里以社区商业为主')
})

test('openAgentToolsPanel switches to tools view and loads tools once', async () => {
  const ctx = createAgentContext()
  let fetchCount = 0
  global.fetch = async (url) => {
    fetchCount += 1
    assert.equal(url, '/api/v1/analysis/agent/tools')
    return {
      ok: true,
      async json() {
        return [
          {
            name: 'read_current_scope',
            description: '读取当前范围',
            category: 'information',
            layer: 'L1',
            ui_tier: 'foundation',
            data_domain: 'general',
            capability_type: 'fetch',
            scene_type: 'general',
            llm_exposure: 'primary',
            applicable_scenarios: ['所有地图分析任务起步'],
            cautions: [],
            requires: [],
            produces: ['scope_polygon'],
            input_schema: { type: 'object', properties: {} },
            output_schema: { type: 'object', properties: { has_scope: { type: 'boolean' } } },
            readonly: true,
            cost_level: 'safe',
            risk_level: 'safe',
            timeout_sec: 30,
            cacheable: false,
          },
        ]
      },
    }
  }

  ctx.openAgentToolsPanel()
  await Promise.resolve()
  await Promise.resolve()

  assert.equal(ctx.activeStep3Panel, 'agent')
  assert.equal(ctx.agentWorkspaceView, 'tools')
  assert.equal(ctx.agentToolsLoaded, true)
  assert.equal(ctx.agentTools.length, 1)
  assert.equal(ctx.agentTools[0].costLevel, 'safe')
  assert.equal(ctx.agentTools[0].uiTier, 'foundation')

  ctx.openAgentToolsPanel()
  await Promise.resolve()

  assert.equal(fetchCount, 1)
})

test('agent tools panel exposes categorized input packages', () => {
  const ctx = createAgentContext({
    poiGridType: 'raster',
    poiDataSource: 'local',
    resultDataSource: 'local',
    poiYearSource: '2024',
    h3GridResolution: 9,
    h3NeighborRing: 2,
    h3GridIncludeMode: 'intersects',
    h3GridMinOverlapRatio: 0.35,
    poiGridSummary: {
      grid_count: 2,
      active_cell_count: 1,
      assigned_poi_count: 5,
      max_poi_count: 5,
      avg_density_poi_per_km2: 12,
    },
    poiGridFeatures: [
      { type: 'Feature', properties: { cell_id: 'r0_c0', poi_count: 5, density_poi_per_km2: 12, dominant_category_name: '餐饮' } },
    ],
    h3AnalysisSummary: {
      grid_count: 8,
      poi_count: 5,
      avg_density_poi_per_km2: 8,
      avg_local_entropy: 0.42,
    },
    populationLayer: {
      cells: [{ cell_id: 'r0_c0', value: 100 }],
    },
    nightlightLayer: {
      cells: [{ cell_id: 'r0_c0', value: 20, class_label: '高亮' }],
    },
    populationOverview: { summary: { total_population: 100 } },
    nightlightOverview: { summary: { mean_radiance: 20 } },
  })

  assert.equal(ctx.agentToolsViewMode, 'tools')
  ctx.setAgentToolsViewMode('input_packages')
  assert.equal(ctx.agentToolsViewMode, 'input_packages')

  const groups = ctx.buildAgentInputPackageGroups()
  assert.deepEqual(groups.map((group) => group.key), ['param_bundles', 'shared_grid', 'poi_spatial', 'summary_evidence'])
  assert.equal(groups[0].items.length, 6)
  assert.equal(groups[1].items[0].rawInput.evidence_version, 'shared_grid_evidence_v1')
  assert.equal(groups[1].items[0].rawInput.top_coupled_cells[0].cell_id, 'r0_c0')
  assert.equal(groups[1].items[0].rawInput.poi_h3_evidence, undefined)

  const poiSpatial = groups[2].items
  assert.equal(poiSpatial.find((item) => item.key === 'poi_raster'), undefined)
  assert.equal(poiSpatial.find((item) => item.key === 'poi_h3').rawInput.evidence_version, 'poi_h3_evidence_v1')

  const h3Payload = ctx.buildAgentInputPackageBasisPayload(poiSpatial.find((item) => item.key === 'poi_h3'))
  assert.equal(h3Payload.rawInput.evidence_version, 'poi_h3_evidence_v1')
  assert.equal(h3Payload.rawInput.params.h3_resolution, 9)
  assert.equal(h3Payload.fields.some((field) => field.key === 'source_path' && field.value === 'h3.poi_h3_evidence'), true)
})

test('backToAgentReport keeps report state and cached tools', () => {
  const ctx = createAgentContext({
    agentWorkspaceView: 'tools',
    agentInput: '继续分析',
    agentMessages: [{ role: 'user', content: '总结这个区域' }],
    agentTools: [{ name: 'read_current_scope', requires: [], produces: [] }],
    agentToolsLoaded: true,
  })

  ctx.backToAgentReport()

  assert.equal(ctx.agentWorkspaceView, 'report')
  assert.equal(ctx.agentInput, '继续分析')
  assert.deepEqual(ctx.agentMessages.map((item) => item.content), ['总结这个区域'])
  assert.deepEqual(ctx.agentTools.map((item) => item.name), ['read_current_scope'])
  assert.equal(ctx.agentToolsLoaded, true)
})

test('agent tool detail dialog reads current tool without mutating sessions or tools', () => {
  const tool = normalizeAgentToolSummary({
    name: 'query_scope_dataset',
    description: 'Query scope dataset',
    ui_tier: 'dataset',
    data_domain: 'scope',
    capability_type: 'retrieve',
    risk_level: 'safe',
    readonly: true,
    produces: ['scope_dataset_rows'],
  })
  const ctx = createAgentContext({
    agentWorkspaceView: 'tools',
    agentTools: [tool],
    agentToolsLoaded: true,
  })
  const originalTools = ctx.agentTools
  const stopEvent = {
    stopped: false,
    stopPropagation() {
      this.stopped = true
    },
  }

  ctx.openAgentToolDetail(tool, stopEvent)

  assert.equal(stopEvent.stopped, true)
  assert.equal(ctx.agentToolDetailDialogOpen, true)
  assert.equal(ctx.agentActiveToolDetailName, 'query_scope_dataset')
  assert.equal(ctx.getAgentToolDetail().name, 'query_scope_dataset')
  assert.equal(ctx.agentTools, originalTools)
  assert.equal(ctx.agentSessions.length, 0)
  assert.equal(ctx.agentWorkspaceView, 'tools')

  ctx.closeAgentToolDetail()

  assert.equal(ctx.agentToolDetailDialogOpen, false)
  assert.equal(ctx.agentActiveToolDetailName, '')
  assert.equal(ctx.getAgentToolDetail(), null)
})

test('basis drawer state opens and closes with normalized payload', () => {
  const ctx = createAgentContext()
  ctx.openBasisDrawer({
    title: '经济活动强度依据',
    currentConclusion: '基于夜间灯光亮度，等时圈内经济活动强度呈现中等偏上。',
    fields: [{ key: 'mean_radiance', label: '平均辐亮', value: 12.3 }],
  })
  assert.equal(ctx.basisDrawerOpen, true)
  assert.equal(ctx.basisDrawerActiveTab, 'basic')
  assert.equal(ctx.getBasisDrawerPayload().title, '经济活动强度依据')
  assert.equal(ctx.getBasisDrawerPayload().aiPrompt, '该结论由规则模板生成，未调用 AI')
  ctx.setBasisDrawerTab('raw')
  assert.equal(ctx.basisDrawerActiveTab, 'raw')
  ctx.closeBasisDrawer()
  assert.equal(ctx.basisDrawerOpen, false)
  assert.equal(ctx.basisDrawerPayload, null)
})

test('nightlight basis payload includes economic activity evidence fields', () => {
  const ctx = createAgentContext({
    nightlightOverview: {
      summary: {
        total_radiance: 100,
        mean_radiance: 8.5,
        p90_radiance: 18,
        lit_pixel_ratio: 0.72,
        economic_activity_intensity_level: 'medium_high',
        sector_direction_analysis: { top_direction: '东' },
      },
    },
    nightlightLayer: {
      analysis: {
        economic_activity_summary_text: '基于夜间灯光亮度，等时圈内经济活动强度呈现中等偏上。',
        core_hotspot_count: 4,
        peak_to_edge_ratio: 2.1,
      },
    },
  })
  const payload = ctx.buildNightlightBasisPayload()
  assert.equal(payload.sourceType, 'rule')
  assert.match(payload.currentConclusion, /夜间灯光亮度/)
  assert.ok(payload.fields.some((field) => field.key === 'economic_activity_intensity_level'))
  assert.ok(payload.fields.some((field) => field.key === 'sector_direction_analysis'))
})

test('agent economic activity basis payload combines nightlight and road orientation evidence', () => {
  const ctx = createAgentContext({
    agentPanelPayloads: {
      summary_pack: {
        headline_judgment: { summary: '区域总结' },
        user_profile: { headline: '画像' },
        behavior_inference: { headline: '行为' },
        consumption_vitality: {
          title: '经济活动强度',
          reasoning: '高值主要集中在东侧，路网以东西向为主。',
          dimensions: [],
        },
        spatial_structure: { title: '空间结构', reasoning: '空间结构稳定。' },
        poi_structure: { title: 'POI结构', reasoning: 'POI结构稳定。' },
        business_support: { title: '业态承接', reasoning: '承接稳定。' },
      },
      current_nightlight_pattern_analysis: {
        economic_activity_intensity_level: 'medium_high',
        total_radiance: 100,
        sector_direction_analysis: { top_direction: '东' },
      },
      road_syntax_summary: {
        road_orientation_analysis: { dominant_orientation: '东西向' },
      },
    },
  })
  const item = ctx.getAgentSummaryAreaJudgments()[2]
  const payload = ctx.buildAgentSummaryBasisPayload(item)
  assert.equal(payload.sourceType, 'ai_checked')
  assert.match(payload.template, /夜间经济活动/)
  assert.ok(payload.fields.some((field) => field.key === 'sector_direction_analysis'))
  assert.ok(payload.fields.some((field) => field.key === 'road_orientation_analysis'))
})

test('agent summary section basis prompts are section-specific', () => {
  const ctx = createAgentContext()
  const prompts = [
    'spatial_structure',
    'poi_structure',
    'consumption_vitality',
    'business_support',
  ].map((sectionKey) => ctx.getAgentSummarySectionPrompt(sectionKey))

  assert.equal(new Set(prompts).size, 4)
  assert.match(prompts[0], /没有本次 AI 调用 prompt 快照/)
  assert.match(prompts[1], /没有本次 AI 调用 prompt 快照/)
  assert.match(prompts[2], /没有本次 AI 调用 prompt 快照/)
  assert.match(prompts[3], /没有本次 AI 调用 prompt 快照/)
  assert.doesNotMatch(prompts.join('\n'), /你是一名商业地理/)
})

test('agent summary basis formats road orientation as readable summary', () => {
  const ctx = createAgentContext({
    agentPanelPayloads: {
      summary_pack: {
        headline_judgment: { summary: 'Area summary' },
        user_profile: { headline: 'Users' },
        behavior_inference: { headline: 'Behavior' },
        consumption_vitality: {
          title: 'Economic activity',
          reasoning: 'Nightlight and roads align.',
          dimensions: [],
        },
        spatial_structure: { title: 'Spatial structure', reasoning: 'Stable.' },
        poi_structure: { title: 'POI structure', reasoning: 'Stable.' },
        business_support: { title: 'Business support', reasoning: 'Stable.' },
      },
      current_nightlight_pattern_analysis: {
        economic_activity_intensity_level: 'medium_high',
      },
      road_syntax_summary: {
        road_orientation_analysis: {
          dominant_orientation: 'north-south',
          secondary_orientation: 'east-west',
          dominant_share: 0.37229,
          secondary_share: 0.372109,
          orientation_rows: [
            { label: 'east-west', length_share: 0.372109 },
            { label: 'north-south', length_share: 0.37229 },
          ],
        },
      },
    },
  })
  const item = ctx.getAgentSummaryAreaJudgments()[2]
  const payload = ctx.buildAgentSummaryBasisPayload(item)
  const roadField = payload.fields.find((field) => field.key === 'road_orientation_analysis')

  assert.ok(roadField)
  assert.match(roadField.value, /主导/)
  assert.match(roadField.value, /37\.2%/)
  assert.doesNotMatch(roadField.value, /dominant_orientation/)
  assert.doesNotMatch(roadField.value, /orientation_rows/)
})

test('agent summary headline basis payload exposes structured evidence and real prompt contract', () => {
  const ctx = createAgentContext({
    agentPanelPayloads: {
      summary_pack: {
        headline_judgment: {
          summary: 'This is a food-led young consumer district.',
          supporting_clause: 'POI, population, nightlight, and hotspot evidence all support that reading.',
        },
        user_profile: { headline: 'Young nearby consumers', traits: ['young', 'daily consumption'] },
        behavior_inference: { headline: 'Frequent short-stay consumption', traits: ['dining', 'evening activity'] },
        prompt_snapshots: {
          headline: {
            prompt_key: 'headline',
            system_prompt: 'REAL headline system prompt',
            payload_note: 'REAL headline payload note',
            output_schema: { required: ['summary'] },
            evidence_version: 'summary_pack_v1',
          },
        },
        validation_results: {
          headline: {
            source: 'backend',
            prompt_key: 'headline',
            status: 'passed',
            output_schema: { required: ['summary'] },
            validated_output: { summary: 'This is a food-led young consumer district.' },
            checks: [{ key: 'required.summary', label: '必填字段 summary', passed: true }],
          },
        },
      },
      current_business_profile: {
        business_profile: 'food-led district',
        summary_text: 'Business profile is led by dining and daily services.',
        functional_mix_score: 0.72,
      },
      current_poi_structure_analysis: {
        summary_text: 'Dining is the dominant POI category.',
        dominant_categories: ['Dining', 'Shopping'],
        structure_tags: ['dining-led', 'daily-services'],
      },
      current_h3_structure_analysis: {
        summary_text: 'Commercial cells form a multi-core pattern.',
        distribution_pattern: 'multi-core',
        hotspot_count: 4,
        opportunity_count: 12,
      },
      current_commercial_hotspots: {
        hotspot_mode: 'multi-core',
        core_zone_count: 4,
        opportunity_zone_count: 12,
        summary_text: 'Four core commercial zones and twelve opportunity zones.',
      },
      current_population_profile_analysis: {
        summary_text: 'Population skews young.',
        top_age_band: '20-34',
      },
      current_nightlight_pattern_analysis: {
        economic_activity_intensity_level: 'medium_high',
        mean_radiance: 8.2,
      },
      current_road_pattern_analysis: {
        summary_text: 'Road network has east-west orientation.',
        road_orientation_analysis: { dominant_orientation: 'east-west' },
      },
      current_area_character_labels: {
        character_tags: ['young-consumption', 'multi-core'],
      },
    },
  })
  const payload = ctx.buildAgentSummaryBasisPayload({
    sectionKey: 'headline',
    title: 'Headline',
    reasoning: 'This is a food-led young consumer district.',
  })
  assert.ok(payload.fields.some((field) => field.key === 'headline_summary'))
  assert.ok(payload.fields.some((field) => field.key === 'supporting_clause'))
  assert.ok(payload.fields.some((field) => field.key === 'poi_structure_summary'))
  assert.ok(payload.fields.some((field) => field.key === 'spatial_structure_summary'))
  assert.ok(payload.fields.some((field) => field.key === 'population_profile'))
  assert.equal(payload.aiPrompt, 'REAL headline system prompt')
  assert.equal(payload.aiPromptPayloadNote, 'REAL headline payload note')
  assert.equal(payload.promptSourceLabel, '本次生成实际使用的提示词快照')
  assert.deepEqual(payload.outputSchema, { required: ['summary'] })
  assert.equal(payload.validationResults.headline.source, 'backend')
  assert.deepEqual(payload.validationResults.headline.validated_output, { summary: 'This is a food-led young consumer district.' })
  assert.equal(ctx.getBasisDrawerTabs().some((item) => item.key === 'validation'), true)
  assert.equal(payload.rawInput.evidence.task, 'summary_pack_generation')
})

test('agent summary basis payload includes baseline fields even with sparse section evidence', () => {
  const ctx = createAgentContext({
    agentPanelPayloads: {
      summary_pack: {
        headline_judgment: { summary: 'Conservative area judgment', supporting_clause: 'Evidence is limited.' },
        user_profile: { headline: 'Nearby users', traits: ['daily users'] },
        behavior_inference: { headline: 'Daily short visits', traits: ['short stay'] },
      },
    },
  })
  const payload = ctx.buildAgentSummaryBasisPayload({
    sectionKey: 'business_support',
    title: 'Business support',
    reasoning: 'Evidence is limited.',
  })
  assert.ok(payload.fields.some((field) => field.key === 'evidence_version'))
  assert.ok(payload.fields.some((field) => field.key === 'task'))
  assert.equal(payload.aiPromptPayloadNote, '')
  assert.match(payload.aiPrompt, /没有本次 AI 调用 prompt 快照/)
  assert.equal(payload.promptSourceLabel, '无本次调用快照')
  assert.equal(payload.fields.length >= 2, true)
})

test('agent nightlight iteration basis payload uses evidence pack prompt and non-empty fields', () => {
  const ctx = createAgentContext()
  ctx.createAgentIterationChangeTab({ autoload: false })
  ctx.commitAgentIterationNightlightPayload({
    status: 'ready',
    period: '2020-2024',
    years: [2020, 2022, 2024],
    series: [
      { year: 2020, total_radiance: 100, mean_radiance: 5, p90_radiance: 8, lit_pixel_ratio: 0.4 },
      { year: 2024, total_radiance: 160, mean_radiance: 7, p90_radiance: 12, lit_pixel_ratio: 0.5 },
    ],
    timeseries: {
      layer: {
        summary: {
          class_counts: { hotspot_emerging: 2, hotspot_stable: 3, hotspot_faded: 1, stable: 12 },
          migration_direction: 'east',
        },
      },
      insights: ['Nightlight hotspot increased.'],
    },
    snapshots: [
      { year: 2020, image_url: 'snapshot-a', grid_features: [{}], layer_cells: [{}] },
      { year: 2024, image_url: '', grid_features: [], layer_cells: [] },
    ],
    ai_analysis: {
      headline: 'Nightlight is increasing.',
      trend_summary: 'Total radiance increased.',
      hotspot_migration: 'Hotspots moved east.',
      risk_or_opportunity: 'More evening activity opportunity.',
    },
    prompt_snapshot: {
      prompt_key: 'nightlight_iteration',
      system_prompt: '真实夜光 system prompt with headline and hotspot_migration',
      payload_note: '真实夜光 payload note nightlight_iteration_v1',
      output_schema: { required: ['headline', 'hotspot_migration'] },
      evidence_version: 'nightlight_iteration_v1',
    },
    validation_results: {
      nightlight_iteration: {
        source: 'backend',
        prompt_key: 'nightlight_iteration',
        status: 'passed',
        output_schema: { required: ['headline', 'hotspot_migration'] },
        validated_output: { headline: 'Nightlight is increasing.', hotspot_migration: 'Hotspots moved east.' },
        checks: [{ key: 'required.headline', label: '必填字段 headline', passed: true }],
      },
    },
  })

  const payload = ctx.buildAgentIterationBasisPayload('nightlight')
  assert.ok(payload.fields.some((field) => field.key === 'evidence_version' && field.value === 'nightlight_iteration_v1'))
  assert.ok(payload.fields.some((field) => field.key === 'hotspot_shift'))
  assert.ok(payload.fields.some((field) => field.key === 'snapshot_refs'))
  assert.match(payload.aiPrompt, /headline/)
  assert.match(payload.aiPrompt, /hotspot_migration/)
  assert.match(payload.aiPromptPayloadNote, /nightlight_iteration_v1/)
  assert.equal(payload.validationResults.nightlight_iteration.source, 'backend')
  assert.equal(payload.validationResults.nightlight_iteration.validated_output.headline, 'Nightlight is increasing.')
  assert.equal(JSON.stringify(payload.rawInput).includes('data:image'), false)
})

test('rule basis payloads expose algorithm fields and clearly state no ai call', () => {
  const ctx = createAgentContext({
    nightlightOverview: {
      summary: {
        total_radiance: 100,
        mean_radiance: 8,
        economic_activity_intensity_level: 'medium',
      },
    },
    nightlightLayer: {
      analysis: {
        core_hotspot_count: 3,
        peak_to_edge_ratio: 1.8,
      },
    },
    roadSyntaxSummary: {
      node_count: 10,
      edge_count: 12,
      total_length_m: 1500,
      road_orientation_analysis: { dominant_orientation: 'east-west' },
    },
    roadSyntaxMetric: 'connectivity',
    roadSyntaxRadius: 800,
  })

  const nightlight = ctx.buildNightlightBasisPayload()
  const road = ctx.buildRoadSyntaxBasisPayload()
  assert.match(nightlight.aiPrompt, /未调用 AI/)
  assert.ok(nightlight.fields.some((field) => field.key === 'economic_activity_intensity_level'))
  assert.match(road.aiPrompt, /未调用 AI/)
  assert.ok(road.fields.some((field) => field.key === 'road_orientation_analysis'))
  assert.ok(road.rawInput.diagnostics)
})

test('analysis task registry maps backend tool traces to left panel tasks', () => {
  const rasterTask = getAnalysisTaskDefinition('poi_raster_grid')
  const poiH3Task = getAnalysisTaskDefinition('poi_h3_grid')
  assert.equal(rasterTask.panelId, 'poi')
  assert.equal(rasterTask.label, 'POI 共享栅格计算')
  assert.equal(rasterTask.subPanelLabel, 'POI 共享栅格')
  assert.deepEqual(rasterTask.producedArtifacts, ['current_poi_grid'])
  assert.equal(poiH3Task.panelId, 'poi')
  assert.equal(poiH3Task.label, 'POI H3 六边形网格计算')
  assert.equal(poiH3Task.subPanelLabel, 'POI H3 六边形网格')
  assert.deepEqual(poiH3Task.producedArtifacts, [
    'current_poi_h3',
    'current_poi_h3_grid',
    'current_poi_h3_summary',
    'current_poi_h3_charts',
  ])
  assert.equal(resolveAnalysisTaskKeyFromTrace({
    tool_name: 'aggregate_pois_to_shared_grid',
    status: 'success',
  }), 'poi_raster_grid')
  assert.equal(resolveAnalysisTaskKeyFromTrace({
    tool_name: 'compute_h3_metrics_from_scope_and_pois',
    status: 'success',
  }), 'poi_h3_grid')
  assert.equal(resolveAnalysisTaskKeyFromTrace({
    tool_name: 'compute_population_overview_from_scope',
    status: 'success',
  }), 'population')
  assert.equal(resolveAnalysisTaskKeyFromTrace({
    tool_name: 'compute_nightlight_overview_from_scope',
    status: 'success',
  }), 'nightlight')
  assert.equal(resolveAnalysisTaskKeyFromTrace({
    tool_name: 'compute_road_syntax_from_scope',
    status: 'success',
  }), 'road_syntax')
})

test('agent task adjustment focuses the correct first and second level panels', () => {
  const ctx = createAgentContext({
    agentPendingTaskConfirmation: {
      taskKey: 'poi_h3_grid',
      status: 'ready',
    },
  })

  ctx.onAgentTaskAdjustClick()

  assert.equal(ctx.sidebarView, 'wizard')
  assert.equal(ctx.step, 2)
  assert.equal(ctx.activeStep3Panel, 'poi')
  assert.equal(ctx.poiSubTab, 'grid')

  ctx.agentPendingTaskConfirmation = {
    taskKey: 'road_syntax',
    status: 'ready',
  }
  ctx.onAgentTaskAdjustClick()

  assert.equal(ctx.activeStep3Panel, 'syntax')
  assert.equal(ctx.roadSyntaxMainTab, 'params')
})

test('agent task start reuses current session and submits continuation after calculation', async () => {
  const ctx = createAgentContext()
  const session = ctx.createAgentSession('task bridge')
  ctx.updateAgentSessions([session], { loaded: true })
  ctx.applyAgentSessionSnapshot(session)
  let computeCount = 0
  let submittedPrompt = ''
  ctx.computePopulationAnalysis = async () => {
    computeCount += 1
    ctx.populationOverview = { summary: { total_population: 100 } }
  }
  ctx.submitMainAgentTurn = async ({ prompt }) => {
    submittedPrompt = prompt
  }
  ctx.setAgentTaskConfirmation({
    taskKey: 'population',
    status: 'ready',
    canStart: true,
  })

  await ctx.onAgentTaskStartClick()

  assert.equal(computeCount, 1)
  assert.equal(ctx.activeAgentSessionId, session.id)
  assert.equal(ctx.agentPendingTaskConfirmation.status, 'completed')
  assert.match(submittedPrompt, /人口计算/)
})

test('clarification draft state is isolated from the main composer', () => {
  const ctx = createAgentContext({
    agentInput: '底部追问框内容',
    agentClarificationDraft: '门卫卡片内容',
  })

  assert.equal(ctx.agentInput, '底部追问框内容')
  assert.equal(ctx.agentClarificationDraft, '门卫卡片内容')
  assert.equal(ctx.canSubmitAgentClarificationDraft(), true)
})

test('clarification option click submits immediately without mutating composer input', () => {
  const ctx = createAgentContext({
    agentInput: '底部追问框内容',
  })
  let submittedPrompt = ''
  ctx.submitMainAgentTurn = ({ prompt }) => {
    submittedPrompt = prompt
  }

  ctx.onAgentClarificationOptionClick('总结这个区域的商业特征')

  assert.equal(submittedPrompt, '总结这个区域的商业特征')
  assert.equal(ctx.agentInput, '底部追问框内容')
  assert.equal(ctx.agentClarificationSubmitting, true)
})

test('clarification draft submit uses inline input and keeps composer untouched', () => {
  const ctx = createAgentContext({
    agentInput: '底部追问框内容',
    agentClarificationDraft: '比较人口和夜间活力哪个更弱',
  })
  let submittedPrompt = ''
  ctx.submitMainAgentTurn = ({ prompt }) => {
    submittedPrompt = prompt
  }

  ctx.onAgentClarificationDraftSubmit()

  assert.equal(submittedPrompt, '比较人口和夜间活力哪个更弱')
  assert.equal(ctx.agentInput, '底部追问框内容')
  assert.equal(ctx.agentClarificationSubmitting, true)
})

test('clarification helpers keep options capped and hide inline index without suggestions', () => {
  const ctx = createAgentContext({
    agentClarificationOptions: ['A', 'B', 'C', 'D'],
  })

  assert.deepEqual(ctx.getAgentClarificationOptions(), ['A', 'B', 'C'])
  assert.equal(ctx.hasAgentClarificationOptions(), true)
  assert.equal(ctx.getAgentClarificationInputIndexLabel(), '4.')

  ctx.agentClarificationOptions = []

  assert.deepEqual(ctx.getAgentClarificationOptions(), [])
  assert.equal(ctx.hasAgentClarificationOptions(), false)
  assert.equal(ctx.getAgentClarificationInputIndexLabel(), '')
})

test('applyAgentSessionSnapshot clears transient clarification draft state', () => {
  const ctx = createAgentContext({
    agentClarificationDraft: '旧草稿',
    agentClarificationSubmitting: true,
  })

  ctx.applyAgentSessionSnapshot({
    ...ctxSessionBase('agent-a', 'A'),
    persisted: true,
    snapshotLoaded: true,
    clarificationQuestion: '你想重点看哪个方向？',
    clarificationOptions: ['总结这个区域的商业特征'],
  })

  assert.equal(ctx.agentClarificationDraft, '')
  assert.equal(ctx.agentClarificationSubmitting, false)
  assert.equal(ctx.agentClarificationQuestion, '你想重点看哪个方向？')
  assert.deepEqual(ctx.agentClarificationOptions, ['总结这个区域的商业特征'])
})

test('normalizeAgentToolSummary keeps new classification fields and grouping works', () => {
  const toolA = normalizeAgentToolSummary({
    name: 'search_analysis_context',
    ui_tier: 'retrieval',
    data_domain: 'analysis',
    capability_type: 'retrieve',
    scene_type: 'general',
    llm_exposure: 'primary',
    applicable_scenarios: ['证据检索'],
    cautions: ['不能替代原始数据'],
    input_schema: { type: 'object', properties: { query: { type: 'string' } } },
    output_schema: { type: 'object', properties: { matches: { type: 'array' } } },
    requires: ['analysis_snapshot'],
    produces: ['analysis_context_matches'],
  })
  const toolB = normalizeAgentToolSummary({
    name: 'query_scope_dataset',
    ui_tier: 'dataset',
    data_domain: 'scope',
    capability_type: 'retrieve',
    scene_type: 'general',
    llm_exposure: 'primary',
    requires: ['history_id'],
    produces: ['scope_dataset_rows'],
  })
  const ctx = createAgentContext({
    agentTools: [toolA, toolB],
  })

  const groups = ctx.getGroupedAgentTools()

  assert.equal(toolA.uiTier, 'retrieval')
  assert.equal(toolA.sceneType, 'general')
  assert.equal(toolA.capabilityType, 'retrieve')
  assert.deepEqual(toolA.applicableScenarios, ['证据检索'])
  assert.equal(groups[0].key, 'retrieval')
  assert.equal(groups[1].key, 'dataset')
  assert.equal(groups[0].subgroups[0].key, 'analysis')
})

test('loadAgentSessionSummaries preserves local draft while adding persisted summaries', async () => {
  const ctx = createAgentContext()
  const draft = ctx.createAgentSession('本地草稿')
  ctx.agentSessions = [draft]
  ctx.activeAgentSessionId = draft.id

  global.fetch = async () => ({
    ok: true,
    async json() {
      return [
        {
          id: 'agent-persisted',
          title: '已保存会话',
          preview: '服务器摘要',
          status: 'answered',
          history_id: 'history-persisted',
          is_pinned: false,
          created_at: '2026-04-05T00:00:00Z',
          updated_at: '2026-04-05T01:00:00Z',
          pinned_at: null,
        },
      ]
    },
  })

  await ctx.loadAgentSessionSummaries()

  assert.equal(ctx.agentSessionsLoaded, true)
  assert.equal(ctx.agentSessions.length, 2)
  assert.equal(ctx.getAgentHistorySessions().length, 1)
  assert.equal(ctx.findAgentSession('agent-persisted').historyId, 'history-persisted')
  assert.equal(ctx.agentSessions.some((item) => item.id === draft.id && item.persisted === false), true)
  assert.equal(ctx.agentSessions.some((item) => item.id === 'agent-persisted' && item.persisted === true), true)
})

test('agent history sessions are grouped by current history id', () => {
  const ctx = createAgentContext({
    scopeSource: 'history',
    currentHistoryRecordId: 'history-current',
  })
  ctx.agentSessions = [
    { ...ctxSessionBase('agent-current', '当前范围'), historyId: 'history-current', persisted: true, snapshotLoaded: true },
    { ...ctxSessionBase('agent-other', '其他范围'), historyId: 'history-other', persisted: true, snapshotLoaded: true },
    { ...ctxSessionBase('agent-legacy', '旧历史'), historyId: '', persisted: true, snapshotLoaded: true },
    { ...ctxSessionBase('agent-draft', '草稿'), historyId: 'history-current', persisted: false, snapshotLoaded: true },
  ]

  assert.deepEqual(ctx.getAgentCurrentRangeSessions().map((item) => item.id), ['agent-current'])
  assert.deepEqual(ctx.getAgentOtherRangeSessions().map((item) => item.id), ['agent-other', 'agent-legacy'])
  assert.deepEqual(ctx.getAgentRangeSessionGroups().map((item) => item.title), ['当前范围', '追问', '其他范围'])
})

test('summary history titles use generic summary label', () => {
  const ctx = createAgentContext()
  const session = {
    ...ctxSessionBase('summary-a', '该区域是一个以年轻人群日常消费和科教文化配套为主的多核商业区。'),
    panelKind: 'commercial_summary',
    panelPayloads: {
      summary_pack: buildSummaryPack('该区域是一个以年轻人群日常消费和科教文化配套为主的多核商业区。'),
    },
  }

  assert.equal(ctx.getAgentSessionTitle(session), '总结')
  assert.equal(ctx.getAgentSummaryViewTitle(session.panelPayloads, session.title), '总结')
  ctx.toggleAgentHistoryGroup('current-summary')
  assert.equal(ctx.isAgentHistoryGroupCollapsed('current-summary'), true)
})

test('agent history puts all sessions into other range when current history id is missing', () => {
  const ctx = createAgentContext({
    getIsochronePolygonPayload() {
      return []
    },
    getDrawnScopePolygonPoints() {
      return []
    },
  })
  ctx.agentSessions = [
    { ...ctxSessionBase('agent-a', 'A'), historyId: 'history-a', persisted: true, snapshotLoaded: true },
    { ...ctxSessionBase('agent-b', 'B'), historyId: '', persisted: true, snapshotLoaded: true },
  ]

  assert.equal(ctx.getCurrentAgentHistoryId(), '')
  assert.deepEqual(ctx.getAgentCurrentRangeSessions(), [])
  assert.deepEqual(ctx.getAgentOtherRangeSessions().map((item) => item.id), ['agent-a', 'agent-b'])
})

test('activateAgentSession switches immediately and hydrates persisted summary later', async () => {
  const ctx = createAgentContext({
    agentSessions: [
      {
        id: 'agent-persisted',
        title: '已保存会话',
        preview: '服务器摘要',
        status: 'answered',
        createdAt: '2026-04-05T00:00:00Z',
        updatedAt: '2026-04-05T01:00:00Z',
        pinnedAt: '',
        input: '',
        cards: [],
        executionTrace: [],
        usedTools: [],
        citations: [],
        researchNotes: [],
        nextSuggestions: [],
        clarificationQuestion: '',
        riskPrompt: '',
        error: '',
        riskConfirmations: [],
        messages: [],
        isPinned: false,
        persisted: true,
        snapshotLoaded: false,
      },
    ],
  })

  let resolveDetail
  global.fetch = async () => ({
    ok: true,
    async json() {
      return new Promise((resolve) => {
        resolveDetail = resolve
      })
    },
  })

  const activating = ctx.activateAgentSession('agent-persisted')

  assert.equal(ctx.activeAgentSessionId, 'agent-persisted')
  assert.equal(ctx.agentSessionHydrating, true)
  assert.equal(ctx.agentSessionDetailLoadingId, 'agent-persisted')
  assert.equal(ctx.agentMessages.length, 0)
  await Promise.resolve()

  resolveDetail({
    id: 'agent-persisted',
    title: '已保存会话',
    preview: '助手回复',
    status: 'answered',
    is_pinned: false,
    created_at: '2026-04-05T00:00:00Z',
    updated_at: '2026-04-05T01:00:00Z',
    pinned_at: null,
    input: '',
    messages: [
      { role: 'user', content: '总结这个区域' },
      { role: 'assistant', content: '这里以社区商业为主' },
    ],
    cards: [],
    output: { cards: [], clarification_question: '', risk_prompt: '', next_suggestions: [] },
    diagnostics: {
      execution_trace: [],
      used_tools: [],
      citations: [],
      research_notes: [],
      audit_issues: [],
      thinking_timeline: [{ id: 'thinking-restored', phase: 'answering', title: '回答生成完成', detail: '已恢复。', state: 'completed' }],
      error: '',
    },
    context_summary: {},
    plan: { steps: [] },
    risk_confirmations: [],
  })

  await activating

  assert.equal(ctx.activeAgentSessionId, 'agent-persisted')
  assert.equal(ctx.agentSessionHydrating, false)
  assert.equal(ctx.agentSessionDetailLoadingId, '')
  assert.equal(ctx.agentMessages.length, 2)
  assert.equal(ctx.agentThinkingTimeline[0].id, 'thinking-restored')
  assert.equal(ctx.agentThinkingExpanded, false)
  assert.equal(ctx.findAgentSession('agent-persisted').snapshotLoaded, true)
})

test('activateAgentSession ignores stale detail response when user switches again', async () => {
  const ctx = createAgentContext({
    agentSessions: [
      { ...ctxSessionBase('agent-a', 'A'), persisted: true, snapshotLoaded: false, preview: 'A 摘要' },
      { ...ctxSessionBase('agent-b', 'B'), persisted: true, snapshotLoaded: false, preview: 'B 摘要' },
    ],
  })

  const resolvers = new Map()
  global.fetch = async (url) => ({
    ok: true,
    async json() {
      const sessionId = String(url).split('/').pop()
      return new Promise((resolve) => {
        resolvers.set(sessionId, resolve)
      })
    },
  })

  const firstActivation = ctx.activateAgentSession('agent-a')
  assert.equal(ctx.activeAgentSessionId, 'agent-a')
  assert.equal(ctx.agentSessionHydrating, true)
  await Promise.resolve()

  const secondActivation = ctx.activateAgentSession('agent-b')
  assert.equal(ctx.activeAgentSessionId, 'agent-b')
  assert.equal(ctx.agentSessionDetailLoadingId, 'agent-b')
  await Promise.resolve()

  resolvers.get('agent-a')({
    id: 'agent-a',
    title: 'A',
    preview: 'A 完整内容',
    status: 'answered',
    is_pinned: false,
    created_at: '2026-04-05T00:00:00Z',
    updated_at: '2026-04-05T01:00:00Z',
    pinned_at: null,
    input: '',
    messages: [{ role: 'assistant', content: 'A 详情' }],
    cards: [],
    execution_trace: [],
    used_tools: [],
    citations: [],
    research_notes: [],
    next_suggestions: [],
    clarification_question: '',
    risk_prompt: '',
    error: '',
    risk_confirmations: [],
  })
  await firstActivation

  assert.equal(ctx.activeAgentSessionId, 'agent-b')
  assert.equal(ctx.agentSessionHydrating, true)
  assert.equal(ctx.agentMessages.length, 0)

  resolvers.get('agent-b')({
    id: 'agent-b',
    title: 'B',
    preview: 'B 完整内容',
    status: 'answered',
    is_pinned: false,
    created_at: '2026-04-05T00:00:00Z',
    updated_at: '2026-04-05T01:00:00Z',
    pinned_at: null,
    input: '',
    messages: [{ role: 'assistant', content: 'B 详情' }],
    cards: [],
    execution_trace: [],
    used_tools: [],
    citations: [],
    research_notes: [],
    next_suggestions: [],
    clarification_question: '',
    risk_prompt: '',
    error: '',
    risk_confirmations: [],
  })
  await secondActivation

  assert.equal(ctx.activeAgentSessionId, 'agent-b')
  assert.equal(ctx.agentSessionHydrating, false)
  assert.deepEqual(ctx.agentMessages.map((item) => item.content), ['B 详情'])
})

test('submitAgentRename updates local draft title without persisting history entry', async () => {
  const ctx = createAgentContext()
  const draft = ctx.createAgentSession('旧名称')
  ctx.agentSessions = [draft]
  ctx.activeAgentSessionId = draft.id
  ctx.agentRenameDialogOpen = true
  ctx.agentRenameSessionId = draft.id
  ctx.agentRenameInput = '新名称'

  await ctx.submitAgentRename()

  assert.equal(ctx.findAgentSession(draft.id).persisted, false)
  assert.equal(ctx.findAgentSession(draft.id).title, '新名称')
  assert.equal(ctx.findAgentSession(draft.id).titleSource, 'user')
  assert.equal(ctx.getAgentHistorySessions().length, 0)
  assert.equal(ctx.agentRenameDialogOpen, false)
})

test('getActiveAgentSessionId returns the active session id', () => {
  const ctx = createAgentContext()
  const draft = ctx.createAgentSession('兼容会话')
  ctx.agentSessions = [draft]
  ctx.activeAgentSessionId = draft.id

  assert.equal(ctx.getActiveAgentSessionId(), draft.id)
  assert.equal(ctx.readSessionState().id, draft.id)
})

test('startNewAgentReportSession keeps new draft out of visible history until first turn succeeds', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()

  assert.equal(ctx.agentSessions.length, 1)
  assert.equal(ctx.getAgentHistorySessions().length, 0)
  assert.equal(ctx.findAgentSession(ctx.activeAgentSessionId).persisted, false)

  global.fetch = async (url, options = {}) => {
    if (url === '/api/v1/analysis/agent/main-loop/stream') {
      const payload = JSON.parse(String(options.body || '{}'))
      assert.equal(payload.conversation_id, ctx.activeAgentSessionId)
      assert.equal(payload.governance_mode, 'auto')
      return createSseResponse([
        {
          type: 'status',
          payload: { stage: 'planned', label: '制定工具计划' },
        },
        {
          type: 'thinking',
          payload: { id: 'thinking-1', phase: 'planned', title: '规划工具调用', detail: '正在决定下一步工具。', state: 'active' },
        },
        {
          type: 'final',
          payload: {
            response: {
              status: 'answered',
              stage: 'answered',
              output: {
                answer: '这里以社区商业为主',
                clarification_question: '',
                risk_prompt: '',
              },
              diagnostics: {
                execution_trace: [],
                used_tools: [],
                citations: [],
                research_notes: [],
                audit_issues: [],
                thinking_timeline: [{ id: 'thinking-1', phase: 'planned', title: '规划工具调用', detail: '正在决定下一步工具。', state: 'completed' }],
                error: '',
              },
              context_summary: {
                has_scope: true,
                available_results: [],
                active_panel: 'agent',
                filters_digest: {},
              },
              plan: {
                steps: [],
              },
            },
          },
        },
      ])
    }

    return {
      ok: true,
      async json() {
        return {
          id: ctx.activeAgentSessionId,
          title: '社区商业概览',
          title_source: 'ai',
          preview: '这里以社区商业为主',
          status: 'answered',
          stage: 'answered',
          is_pinned: false,
          created_at: '2026-04-05T00:00:00Z',
          updated_at: '2026-04-05T01:00:00Z',
          pinned_at: null,
          input: '',
          messages: [
            { role: 'user', content: '总结这个区域' },
            {
              role: 'assistant',
              content: '这里以社区商业为主',
              process: {
                thinking_timeline: [
                  { id: 'thinking-gating', phase: 'gating', title: '检查输入', detail: '正在检查问题与范围。', state: 'completed' },
                  {
                    id: 'tool-call-read-current-scope',
                    phase: 'executing',
                    title: '执行成功 read_current_scope',
                    detail: '执行成功',
                    items: ['参数：无参数', '结果：scope_polygon 已读取', '证据：1 条', '产物：scope_polygon'],
                    state: 'completed',
                  },
                  { id: 'status-answered', phase: 'answered', title: '回答生成完成', detail: '', state: 'completed' },
                ],
                execution_trace: [{ tool_name: 'read_current_scope', status: 'success' }],
              },
            },
          ],
          output: {
            answer: '这里以社区商业为主',
            clarification_question: '',
            risk_prompt: '',
            next_suggestions: [],
          },
          diagnostics: { execution_trace: [], used_tools: [], citations: [], research_notes: [], audit_issues: [], thinking_timeline: [{ id: 'thinking-1', phase: 'planned', title: '规划工具调用', detail: '正在决定下一步工具。', state: 'completed' }], error: '' },
          context_summary: { has_scope: true, available_results: [], active_panel: 'agent', filters_digest: {} },
          plan: { steps: [] },
          risk_confirmations: [],
        }
      },
    }
  }

  ctx.agentInput = '总结这个区域'
  await ctx.submitMainAgentTurn()

  assert.equal(ctx.agentThinkingTimeline.length >= 1, true)
  assert.equal(ctx.getAgentHistorySessions().length, 1)
  assert.equal(ctx.findAgentSession(ctx.activeAgentSessionId).persisted, true)
  assert.equal(ctx.findAgentSession(ctx.activeAgentSessionId).title, '社区商业概览')
  assert.equal(ctx.findAgentSession(ctx.activeAgentSessionId).titleSource, 'ai')
  assert.equal(
    ctx.findAgentSession(ctx.activeAgentSessionId).thinkingTimeline.some((item) => item.id === 'thinking-1'),
    true,
  )
})

test('cancelAgentTurn aborts in-flight agent request and restores idle state', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.agentInput = '总结这个区域'

  let capturedSignal = null
  const streamStarted = createDeferred()
  global.fetch = async (url, options = {}) => {
    assert.equal(url, '/api/v1/analysis/agent/main-loop/stream')
    capturedSignal = options.signal
    streamStarted.resolve()
    return createAbortablePendingResponse(options.signal)
  }

  const pending = ctx.submitMainAgentTurn()
  await waitForDeferred(streamStarted.promise, 'agent stream fetch did not start before cancel test')

  assert.equal(ctx.agentLoading, true)
  assert.equal(typeof capturedSignal?.aborted, 'boolean')
  assert.equal(capturedSignal.aborted, false)

  ctx.cancelAgentTurn()
  await pending

  assert.equal(capturedSignal.aborted, true)
  assert.equal(ctx.agentLoading, false)
  assert.equal(ctx.agentStatus, 'idle')
  assert.equal(ctx.agentError, '')
  assert.equal(ctx.agentThinkingTimeline.length, 0)
  assert.equal(ctx.agentStreamElapsedTimer, null)
  assert.equal(ctx.agentStreamStartedAt, 0)
  assert.equal(ctx.agentInput, '总结这个区域')
})

test('submitMainAgentTurn does not send standalone attachment ids', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.agentInput = '结合附件看这个区域'

  let requestBody = null
  global.fetch = async (url, options = {}) => {
    if (getAgentSessionDetailId(url)) return createAgentSessionDetailResponse(ctx, url)
    assert.equal(url, '/api/v1/analysis/agent/main-loop/stream')
    requestBody = JSON.parse(String(options.body || '{}'))
    return createSseResponse([
      {
        type: 'final',
        payload: {
          response: {
            status: 'answered',
            stage: 'answered',
            output: { cards: [], next_suggestions: [], panel_payloads: {} },
            diagnostics: { execution_trace: [], used_tools: [], citations: [], research_notes: [], audit_issues: [], thinking_timeline: [], error: '' },
            context_summary: {},
            plan: {},
          },
        },
      },
    ])
  }

  await ctx.submitMainAgentTurn()

  assert.equal(Object.prototype.hasOwnProperty.call(requestBody, 'attachment_ids'), false)
})

test('submitMainAgentTurn caches automatic visual snapshots after first capture', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.agentInput = '总结这个区域的商业特征'
  let captureCount = 0
  ctx.captureAgentVisualSnapshots = async () => {
    captureCount += 1
    return [
      {
        snapshot_id: 'visual-road',
        kind: 'road_map',
        title: '路网分析全范围图层',
        data_url: 'data:image/jpeg;base64,abc',
        source: 'frontend_map',
        bounds: { west: 1, south: 2, east: 3, north: 4 },
        warnings: [],
      },
    ]
  }

  const requestBodies = []
  global.fetch = async (url, options = {}) => {
    if (getAgentSessionDetailId(url)) return createAgentSessionDetailResponse(ctx, url)
    assert.equal(url, '/api/v1/analysis/agent/main-loop/stream')
    requestBodies.push(JSON.parse(String(options.body || '{}')))
    return createSseResponse([
      {
        type: 'final',
        payload: {
          response: {
            status: 'answered',
            stage: 'answered',
            output: { cards: [], next_suggestions: [], panel_payloads: {} },
            diagnostics: { execution_trace: [], used_tools: [], citations: [], research_notes: [], audit_issues: [], thinking_timeline: [], error: '' },
            context_summary: {},
            plan: {},
          },
        },
      },
    ])
  }

  await ctx.submitMainAgentTurn()
  ctx.agentInput = '继续解释'
  await ctx.submitMainAgentTurn()

  assert.equal(captureCount, 1)
  assert.equal(requestBodies.length, 2)
  assert.equal(requestBodies[0].visual_snapshots[0].kind, 'road_map')
  assert.equal(requestBodies[1].visual_snapshots[0].data_url, 'data:image/jpeg;base64,abc')
  assert.equal(ctx.agentVisualSnapshotCache.status, 'ready')
  assert.equal(ctx.agentVisualSnapshotCache.visual_snapshots[0].snapshot_id, 'visual-road')
})

test('submitMainAgentTurn drops invalid visual snapshots from cache and request body', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.agentInput = '总结这个区域的商业特征'
  ctx.captureAgentVisualSnapshots = async () => [
    {
      snapshot_id: 'visual-empty',
      kind: 'overview_map',
      title: '当前地图总览',
      data_url: '',
      warnings: ['地图截图方法未返回有效图片，已跳过该快照。'],
    },
    {
      snapshot_id: 'visual-road',
      kind: 'road_map',
      title: '路网分析全范围图层',
      data_url: 'data:image/jpeg;base64,abc',
      warnings: [],
    },
  ]

  let requestBody = null
  global.fetch = async (url, options = {}) => {
    if (getAgentSessionDetailId(url)) return createAgentSessionDetailResponse(ctx, url)
    assert.equal(url, '/api/v1/analysis/agent/main-loop/stream')
    requestBody = JSON.parse(String(options.body || '{}'))
    return createSseResponse([
      {
        type: 'final',
        payload: {
          response: {
            status: 'answered',
            stage: 'answered',
            output: { answer: '已完成', panel_payloads: {} },
            diagnostics: { execution_trace: [], used_tools: [], citations: [], research_notes: [], audit_issues: [], thinking_timeline: [], error: '' },
            context_summary: {},
            plan: {},
          },
        },
      },
    ])
  }

  await ctx.submitMainAgentTurn()

  assert.equal(requestBody.visual_snapshots.length, 1)
  assert.equal(requestBody.visual_snapshots[0].snapshot_id, 'visual-road')
  assert.equal(ctx.agentVisualSnapshotCache.visual_snapshots.length, 1)
  assert.equal(ctx.agentVisualSnapshotCache.visual_snapshots[0].snapshot_id, 'visual-road')
  assert.equal(ctx.agentVisualSnapshotCache.warnings.some((item) => item.includes('当前地图总览 未传入有效图片')), true)
})

test('getCachedAgentVisualSnapshots self-heals old cache entries without image data', () => {
  const ctx = createAgentContext()
  const fingerprint = ctx.buildAgentVisualSnapshotFingerprint()
  ctx.agentVisualSnapshotCache = {
    status: 'ready',
    fingerprint,
    generated_at: '2026-06-01T00:00:00.000Z',
    visual_snapshots: [
      { snapshot_id: 'visual-empty', kind: 'overview_map', title: '当前地图总览', data_url: '' },
      { snapshot_id: 'visual-road', kind: 'road_map', title: '路网分析全范围图层', data_url: 'data:image/jpeg;base64,abc' },
    ],
    warnings: [],
  }

  const cached = ctx.getCachedAgentVisualSnapshots(fingerprint)

  assert.equal(cached.length, 1)
  assert.equal(cached[0].snapshot_id, 'visual-road')
  assert.equal(ctx.agentVisualSnapshotCache.visual_snapshots.length, 1)
  assert.equal(ctx.agentVisualSnapshotCache.warnings.some((item) => item.includes('当前地图总览 未传入有效图片')), true)
})

test('submitMainAgentTurn refreshes visual snapshot cache when fingerprint changes', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.agentInput = '总结这个区域'
  let captureCount = 0
  ctx.captureAgentVisualSnapshots = async () => {
    captureCount += 1
    return [
      { snapshot_id: `visual-${captureCount}`, kind: 'overview_map', title: '当前地图总览', data_url: `data:image/jpeg;base64,${captureCount}` },
    ]
  }

  const requestBodies = []
  global.fetch = async (url, options = {}) => {
    if (getAgentSessionDetailId(url)) return createAgentSessionDetailResponse(ctx, url)
    assert.equal(url, '/api/v1/analysis/agent/main-loop/stream')
    requestBodies.push(JSON.parse(String(options.body || '{}')))
    return createSseResponse([
      {
        type: 'final',
        payload: {
          response: {
            status: 'answered',
            stage: 'answered',
            output: { answer: '已完成', panel_payloads: {} },
            diagnostics: { execution_trace: [], used_tools: [], citations: [], research_notes: [], audit_issues: [], thinking_timeline: [], error: '' },
            context_summary: {},
            plan: {},
          },
        },
      },
    ])
  }

  await ctx.submitMainAgentTurn()
  ctx.agentInput = '换了结果后再总结'
  ctx.allPoisDetails = [{ id: 'poi-1' }]
  await ctx.submitMainAgentTurn()

  assert.equal(captureCount, 2)
  assert.equal(requestBodies[0].visual_snapshots[0].snapshot_id, 'visual-1')
  assert.equal(requestBodies[1].visual_snapshots[0].snapshot_id, 'visual-2')
})

test('submitMainAgentTurn continues when visual snapshot cache generation fails', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.agentInput = '总结这个区域'
  ctx.captureAgentVisualSnapshots = async () => {
    throw new Error('capture_failed')
  }

  let requestBody = null
  global.fetch = async (url, options = {}) => {
    if (getAgentSessionDetailId(url)) return createAgentSessionDetailResponse(ctx, url)
    assert.equal(url, '/api/v1/analysis/agent/main-loop/stream')
    requestBody = JSON.parse(String(options.body || '{}'))
    return createSseResponse([
      {
        type: 'final',
        payload: {
          response: {
            status: 'answered',
            stage: 'answered',
            output: { answer: '已完成', panel_payloads: {} },
            diagnostics: { execution_trace: [], used_tools: [], citations: [], research_notes: [], audit_issues: [], thinking_timeline: [], error: '' },
            context_summary: {},
            plan: {},
          },
        },
      },
    ])
  }

  await ctx.submitMainAgentTurn()

  assert.deepEqual(requestBody.visual_snapshots, [])
  assert.equal(ctx.agentVisualSnapshotCache.status, 'failed')
  assert.equal(ctx.agentVisualSnapshotCache.warnings[0].includes('capture_failed'), true)
})

test('ensureAgentVisualSnapshotCache does not retry failed cache for same fingerprint', async () => {
  const ctx = createAgentContext()
  let captureCount = 0
  ctx.captureAgentVisualSnapshots = async () => {
    captureCount += 1
    throw new Error('capture_failed')
  }

  const first = await ctx.ensureAgentVisualSnapshotCache()
  const second = await ctx.ensureAgentVisualSnapshotCache()

  assert.deepEqual(first, [])
  assert.deepEqual(second, [])
  assert.equal(captureCount, 1)
})

test('submitMainAgentTurn sends map search context separately from analysis snapshot', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.agentInput = '总结这个区域的商业特征'
  ctx.allPoisDetails = [
    { name: '湖南师范大学', type: '科教文化', lng: 112.95, lat: 28.18 },
    { name: '后湖小吃街', type: '餐饮', lng: 112.96, lat: 28.19 },
  ]
  ctx.h3AnalysisGridFeatures = [{ properties: { h3_id: 'h3-a', poi_count: 12 } }]
  ctx.roadSyntaxRoadFeatures = [{ properties: { id: 'r1', choice_score: 0.8 } }]
  ctx.populationLayer = { cells: [{ cell_id: 'p1', total_population: 900 }] }
  ctx.nightlightLayer = { cells: [{ cell_id: 'n1', radiance: 42 }] }
  ctx.captureAgentVisualSnapshots = async () => [
    { snapshot_id: 'visual-1', kind: 'overview_map', title: '当前地图总览', data_url: 'data:image/jpeg;base64,abc' },
  ]

  let requestBody = null
  global.fetch = async (url, options = {}) => {
    if (getAgentSessionDetailId(url)) return createAgentSessionDetailResponse(ctx, url)
    assert.equal(url, '/api/v1/analysis/agent/main-loop/stream')
    requestBody = JSON.parse(String(options.body || '{}'))
    return createSseResponse([
      {
        type: 'final',
        payload: {
          response: {
            status: 'answered',
            stage: 'answered',
            output: { answer: '已完成', panel_payloads: {} },
            diagnostics: { execution_trace: [], used_tools: [], citations: [], research_notes: [], audit_issues: [], thinking_timeline: [], error: '' },
            context_summary: {},
            plan: {},
          },
        },
      },
    ])
  }

  await ctx.submitMainAgentTurn()

  assert.equal(requestBody.analysis_snapshot.context.place_anchors, undefined)
  assert.equal(requestBody.analysis_snapshot.context.spatial_anchors, undefined)
  assert.deepEqual(requestBody.map_search_context.place_anchors.names, ['湖南师范大学', '后湖小吃街'])
  assert.equal(requestBody.map_search_context.spatial_anchors.h3.top_cells[0].h3_id, 'h3-a')
  assert.equal(requestBody.map_search_context.spatial_anchors.road.sample_segments[0].id, 'r1')
  assert.equal(requestBody.map_search_context.spatial_anchors.population.top_cells[0].cell_id, 'p1')
  assert.equal(requestBody.map_search_context.spatial_anchors.nightlight.top_cells[0].cell_id, 'n1')
  assert.equal(requestBody.visual_snapshots[0].kind, 'overview_map')
})

test('agent visual road snapshot bounds use road features', () => {
  const ctx = createAgentContext()
  ctx.roadSyntaxRoadFeatures = [
    { geometry: { coordinates: [[112.98, 28.19], [113.02, 28.23]] } },
    { geometry: { coordinates: [[112.97, 28.18], [113.01, 28.21]] } },
  ]

  assert.deepEqual(ctx.getAgentRoadFeatureBounds(), {
    west: 112.97,
    south: 28.18,
    east: 113.02,
    north: 28.23,
  })
})

test('agent visual snapshot targets include population and each road metric', () => {
  const ctx = createAgentContext()
  ctx.populationOverview = { summary: { total_population: 1200 } }
  ctx.roadSyntaxSummary = { node_count: 10 }
  ctx.roadSyntaxMetricTabs = () => [
    { value: 'connectivity', label: '连接度' },
    { value: 'control', label: '控制值' },
    { value: 'depth', label: '深度值' },
    { value: 'choice', label: '选择度' },
    { value: 'integration', label: '整合度' },
    { value: 'intelligibility', label: '可理解度' },
  ]

  const targets = ctx.buildAgentVisualSnapshotTargets()
  const roadTargets = targets.filter((item) => item.kind === 'road_map')

  assert.equal(targets.some((item) => item.kind === 'population_map'), true)
  assert.deepEqual(roadTargets.map((item) => item.metric), [
    'connectivity',
    'control',
    'depth',
    'choice',
    'integration',
    'intelligibility',
  ])
  assert.equal(roadTargets[0].title.includes('连接度'), true)
})

test('agent map search context includes concrete place anchors outside analysis snapshot', () => {
  const ctx = createAgentContext()
  ctx.allPoisDetails = [
    { name: '湖南师范大学', type: '科教文化', lng: 112.95, lat: 28.18 },
    { name: '后湖国际艺术区', type: '文化', lng: 112.96, lat: 28.19 },
    { name: '桃子湖公园', type: '公园', lng: 112.97, lat: 28.2 },
    { name: '麓山南路', type: '道路', lng: 112.98, lat: 28.21 },
  ]

  const snapshot = ctx.buildAgentAnalysisSnapshot()
  const mapSearchContext = ctx.buildAgentMapSearchContext()

  assert.equal(snapshot.context.place_anchors, undefined)
  assert.deepEqual(mapSearchContext.place_anchors.names, [
    '湖南师范大学',
    '后湖国际艺术区',
    '桃子湖公园',
    '麓山南路',
  ])
  assert.equal(mapSearchContext.place_anchors.groups.some((group) => group.key === 'campus_culture'), true)
})

test('agent map search context includes lightweight spatial anchors outside analysis snapshot', () => {
  const ctx = createAgentContext()
  ctx.selectedPoint = { name: '后湖', lng: 112.96, lat: 28.19 }
  ctx.h3AnalysisGridFeatures = [
    { properties: { h3_id: 'h3-a', poi_count: 12, density: 9.5, gi_z_score: 2.1 } },
    { properties: { h3_id: 'h3-b', poi_count: 3, density: 1.5 } },
  ]
  ctx.roadSyntaxRoadFeatures = [
    { properties: { id: 'r1', integration_score: 0.8, choice_score: 0.2 } },
  ]
  ctx.populationLayer = {
    summary: { total_population: 1200 },
    cells: [{ cell_id: 'p1', total_population: 900, density: 100 }],
  }
  ctx.nightlightLayer = {
    summary: { mean_radiance: 30 },
    cells: [{ cell_id: 'n1', radiance: 42 }],
  }

  const snapshot = ctx.buildAgentAnalysisSnapshot()
  const anchors = ctx.buildAgentMapSearchContext().spatial_anchors

  assert.equal(snapshot.context.spatial_anchors, undefined)
  assert.equal(anchors.selected_point.name, '后湖')
  assert.equal(anchors.h3.feature_count, 2)
  assert.equal(anchors.h3.top_cells[0].h3_id, 'h3-a')
  assert.equal(anchors.road.feature_count, 1)
  assert.equal(anchors.population.top_cells[0].cell_id, 'p1')
  assert.equal(anchors.nightlight.top_cells[0].cell_id, 'n1')
})

test('agent visual snapshot capture restores panel and map state', async () => {
  const mapState = { center: [113, 28], zoom: 12 }
  const ctx = createAgentContext({
    activeStep3Panel: 'agent',
    poiSubTab: 'category',
    allPoisDetails: [{ id: 'poi-1' }],
    buildAgentAnalysisSnapshot: () => ({
      scope: { polygon: [[112.9, 28.1], [113.1, 28.1], [113.1, 28.3], [112.9, 28.1]] },
    }),
    map: {
      getCenter: () => ({ lng: mapState.center[0], lat: mapState.center[1] }),
      getZoom: () => mapState.zoom,
      setZoomAndCenter: (zoom, center) => {
        mapState.zoom = zoom
        mapState.center = center
      },
    },
    _captureMapSnapshotBase64: async () => 'data:image/png;base64,abc',
    _sleepForExport: async () => {},
  })

  const snapshots = await ctx.captureAgentVisualSnapshots()

  assert.equal(snapshots.length, 2)
  assert.deepEqual(mapState, { center: [113, 28], zoom: 12 })
  assert.equal(ctx.activeStep3Panel, 'agent')
  assert.equal(ctx.poiSubTab, 'category')
})

test('agent visual snapshots use offscreen maps without changing visible panel state', async () => {
  const originalDocument = global.document
  const originalAMap = global.window.AMap
  const originalHtml2canvas = global.html2canvas
  const maps = []
  const appended = []
  const ctx = createAgentContext({
    activeStep3Panel: 'agent',
    poiSubTab: 'category',
    allPoisDetails: [{ id: 'p1', type: '餐饮', lng: 112.94, lat: 28.16 }],
    h3AnalysisSummary: { grid_count: 1 },
    h3AnalysisGridFeatures: [{
      type: 'Feature',
      geometry: { type: 'Polygon', coordinates: [[[112.93, 28.15], [112.95, 28.15], [112.95, 28.17], [112.93, 28.15]]] },
      properties: { h3_id: 'h3-a', poi_count: 8 },
    }],
    buildAgentAnalysisSnapshot: () => ({
      scope: { polygon: [[112.92, 28.14], [112.96, 28.14], [112.96, 28.18], [112.92, 28.14]] },
    }),
    applyPoiVisualState() {
      throw new Error('main_poi_visibility_should_not_change')
    },
    _captureMapSnapshotBase64() {
      throw new Error('main_map_capture_should_not_run')
    },
    _sleepForExport: async () => {},
  })

  const createNode = (tag) => ({
    tag,
    id: '',
    type: '',
    textContent: '',
    style: { cssText: '', display: '', backgroundColor: '', backgroundImage: '' },
    children: [],
    parentNode: null,
    setAttribute(name, value) { this[name] = value },
    appendChild(node) {
      node.parentNode = this
      this.children.push(node)
    },
    removeChild(node) {
      this.children = this.children.filter((item) => item !== node)
      node.parentNode = null
    },
    querySelectorAll() { return [] },
  })
  global.document = {
    getElementById() { return null },
    createElement: createNode,
    body: {
      appendChild(node) {
        node.parentNode = this
        appended.push(node)
      },
      removeChild(node) {
        node.parentNode = null
      },
    },
  }

  class FakeOverlay {
    constructor(options = {}) {
      this.options = options
      this.kind = this.constructor.name
    }
    setMap(map) {
      this.map = map
      if (map && map.overlays) map.overlays.push(this)
    }
  }
  class FakeMap {
    constructor(el, options = {}) {
      this.el = el
      this.options = options
      this.overlays = []
      this.destroyed = false
      maps.push(this)
    }
    setFitView(overlays, immediate, padding) {
      this.fit = { overlays, immediate, padding }
    }
    setCenter(center) { this.center = center }
    setZoom(zoom) { this.zoom = zoom }
    getContainer() { return this.el }
    destroy() { this.destroyed = true }
  }
  global.window.AMap = global.AMap = {
    Map: FakeMap,
    Polygon: class Polygon extends FakeOverlay {},
    CircleMarker: class CircleMarker extends FakeOverlay {},
    Polyline: class Polyline extends FakeOverlay {},
  }
  global.html2canvas = async (node) => ({
    toDataURL: () => `data:image/png;base64,${Buffer.from(node.style.cssText || 'snapshot').toString('base64')}`,
  })

  try {
    const snapshots = await ctx.captureAgentVisualSnapshots()

    assert.deepEqual(snapshots.map((item) => item.kind), ['overview_map', 'poi_map', 'h3_map'])
    assert.equal(snapshots.every((item) => item.data_url.startsWith('data:image/png;base64,')), true)
    assert.equal(ctx.activeStep3Panel, 'agent')
    assert.equal(ctx.poiSubTab, 'category')
    assert.equal(maps.length, 3)
    assert.equal(maps.every((map) => map.destroyed), true)
    assert.equal(appended.length, 3)
    assert.equal(maps[1].overlays.some((overlay) => overlay.kind === 'CircleMarker'), true)
    assert.equal(maps[2].overlays.some((overlay) => overlay.kind === 'CircleMarker'), false)
  } finally {
    global.document = originalDocument
    global.window.AMap = originalAMap
    global.AMap = originalAMap
    global.html2canvas = originalHtml2canvas
  }
})

test('agent visual snapshot cache mirror is dev gated', () => {
  const originalDocument = global.document
  const created = []
  const body = {
    appendChild(node) {
      created.push(node)
      node.parentNode = this
    },
  }
  global.document = {
    getElementById() { return created.find((node) => node.id === '__agent_visual_snapshot_cache__') || null },
    createElement(tag) {
      return {
        tag,
        id: '',
        type: '',
        textContent: '',
        style: { display: '' },
      }
    },
    body,
  }
  try {
    const ctx = createAgentContext()
    ctx.shouldMirrorAgentVisualSnapshotCacheForDev = () => false
    ctx.commitAgentVisualSnapshotCache({
      status: 'ready',
      fingerprint: 'a',
      visual_snapshots: [{ snapshot_id: 's1', kind: 'overview_map', data_url: 'data:image/jpeg;base64,abc' }],
    })
    assert.equal(created.length, 0)

    ctx.shouldMirrorAgentVisualSnapshotCacheForDev = () => true
    ctx.commitAgentVisualSnapshotCache({
      status: 'ready',
      fingerprint: 'b',
      visual_snapshots: [{ snapshot_id: 's2', kind: 'poi_map', data_url: 'data:image/jpeg;base64,def' }],
    })
    assert.equal(created.length, 1)
    assert.equal(created[0].type, 'application/json')
    assert.equal(JSON.parse(created[0].textContent).visual_snapshots[0].snapshot_id, 's2')
  } finally {
    global.document = originalDocument
  }
})

test('submitMainAgentTurn ignores duplicate submit while active session is running', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.agentInput = '哪里适合补充餐饮'

  let runRequestCount = 0
  const streamStarted = createDeferred()
  global.fetch = async (url, options = {}) => {
    assert.equal(url, '/api/v1/analysis/agent/main-loop/stream')
    runRequestCount += 1
    streamStarted.resolve()
    return createAbortablePendingResponse(options.signal)
  }

  const pending = ctx.submitMainAgentTurn()
  await waitForDeferred(streamStarted.promise, 'agent stream fetch did not start before duplicate-submit test')

  assert.equal(ctx.agentLoading, true)
  assert.deepEqual(ctx.agentMessages.map((item) => item.content), ['哪里适合补充餐饮'])

  ctx.agentInput = '哪里适合补充餐饮'
  await ctx.submitMainAgentTurn()

  assert.equal(runRequestCount, 1)
  assert.deepEqual(ctx.agentMessages.map((item) => item.content), ['哪里适合补充餐饮'])

  ctx.cancelAgentTurn()
  await pending
})

test('running session survives switching to a new report and can be revisited', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.agentInput = '总结这个区域'

  const pendingBySessionId = new Map()
  const streamStarted = createDeferred()
  global.fetch = async (url, options = {}) => {
    assert.equal(url, '/api/v1/analysis/agent/main-loop/stream')
    const payload = JSON.parse(String(options.body || '{}'))
    const sessionId = String(payload.conversation_id || '')
    const pending = createAbortablePendingResponse(options.signal)
    pendingBySessionId.set(sessionId, { signal: options.signal })
    streamStarted.resolve(sessionId)
    return pending
  }

  const sessionAId = ctx.activeAgentSessionId
  const pendingA = ctx.submitMainAgentTurn()
  await waitForDeferred(streamStarted.promise, 'agent stream fetch did not start before session-switch test')

  assert.equal(ctx.isAgentSessionRunning(sessionAId), true)
  assert.equal(ctx.agentLoading, true)

  ctx.startNewAgentReportSession()
  const sessionBId = ctx.activeAgentSessionId

  assert.notEqual(sessionBId, sessionAId)
  assert.equal(ctx.isAgentSessionRunning(sessionAId), true)
  assert.equal(ctx.agentLoading, false)
  assert.equal(ctx.getRunningAgentSessionCount(), 1)

  await ctx.activateAgentSession(sessionAId)
  assert.equal(ctx.activeAgentSessionId, sessionAId)
  assert.equal(ctx.agentLoading, true)

  ctx.cancelAgentTurn(sessionAId)
  await pendingA

  assert.equal(pendingBySessionId.get(sessionAId).signal.aborted, true)
  assert.equal(ctx.isAgentSessionRunning(sessionAId), false)
})

test('parallel main agent loop requests can run concurrently and cancel only the active session', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.agentInput = '总结这个区域'

  const pendingBySessionId = new Map()
  const streamStartedA = createDeferred()
  const streamStartedB = createDeferred()
  let sessionAId = ''
  let sessionBId = ''
  global.fetch = async (url, options = {}) => {
    assert.equal(url, '/api/v1/analysis/agent/main-loop/stream')
    const payload = JSON.parse(String(options.body || '{}'))
    const sessionId = String(payload.conversation_id || '')
    const pending = createAbortablePendingResponse(options.signal)
    pendingBySessionId.set(sessionId, { signal: options.signal })
    if (sessionId === sessionAId) streamStartedA.resolve(sessionId)
    if (sessionId === sessionBId) streamStartedB.resolve(sessionId)
    return pending
  }

  sessionAId = ctx.activeAgentSessionId
  const pendingA = ctx.submitMainAgentTurn()
  await waitForDeferred(streamStartedA.promise, 'first agent stream fetch did not start before parallel-turn test')

  ctx.startNewAgentReportSession()
  ctx.agentInput = '下一步做什么分析'
  sessionBId = ctx.activeAgentSessionId
  const pendingB = ctx.submitMainAgentTurn()
  await waitForDeferred(streamStartedB.promise, 'second agent stream fetch did not start before parallel-turn test')

  assert.equal(ctx.getRunningAgentSessionCount(), 2)
  assert.equal(ctx.isAgentSessionRunning(sessionAId), true)
  assert.equal(ctx.isAgentSessionRunning(sessionBId), true)
  assert.equal(ctx.agentLoading, true)

  ctx.cancelAgentTurn()
  await pendingB

  assert.equal(pendingBySessionId.get(sessionBId).signal.aborted, true)
  assert.equal(ctx.isAgentSessionRunning(sessionBId), false)
  assert.equal(ctx.isAgentSessionRunning(sessionAId), true)
  assert.equal(ctx.getRunningAgentSessionCount(), 1)

  ctx.cancelAgentTurn(sessionAId)
  await pendingA

  assert.equal(pendingBySessionId.get(sessionAId).signal.aborted, true)
  assert.equal(ctx.getRunningAgentSessionCount(), 0)
})

test('thinking elapsed timer updates reactive tick and freezes after stop', () => {
  const ctx = createAgentContext()
  const originalDateNow = Date.now
  const originalSetInterval = global.window.setInterval
  const originalClearInterval = global.window.clearInterval
  let now = 1000
  let timerCallback = null
  let clearedTimer = ''

  Date.now = () => now
  global.window.setInterval = (callback, intervalMs) => {
    assert.equal(intervalMs, 1000)
    timerCallback = callback
    return 'timer-1'
  }
  global.window.clearInterval = (timerId) => {
    clearedTimer = timerId
  }

  try {
    ctx.startAgentThinkingTimer()
    assert.equal(ctx.agentStreamStartedAt, 1000)
    assert.equal(ctx.agentStreamElapsedTimer, 'timer-1')
    assert.equal(ctx.getAgentThinkingElapsedLabel(), '1s')

    now = 3200
    timerCallback()
    assert.equal(ctx.agentStreamElapsedTick, 3200)
    assert.equal(ctx.getAgentThinkingElapsedLabel(), '2s')

    ctx.stopAgentThinkingTimer()
    assert.equal(clearedTimer, 'timer-1')
    assert.equal(ctx.agentStreamElapsedTimer, null)
    assert.equal(ctx.getAgentThinkingElapsedLabel(), '2s')

    now = 5200
    assert.equal(ctx.getAgentThinkingElapsedLabel(), '2s')
  } finally {
    Date.now = originalDateNow
    global.window.setInterval = originalSetInterval
    global.window.clearInterval = originalClearInterval
  }
})

test('thinking elapsed label does not keep growing after elapsed tick is missing', () => {
  const ctx = createAgentContext()
  const originalDateNow = Date.now
  let now = 1000
  Date.now = () => now

  try {
    ctx.agentStreamStartedAt = 1000
    ctx.agentStreamElapsedTick = 0
    assert.equal(ctx.getAgentThinkingElapsedLabel(), '1s')

    now = 61000
    assert.equal(ctx.getAgentThinkingElapsedLabel(), '1s')
  } finally {
    Date.now = originalDateNow
  }
})

test('waiting process fallback advances while first backend event is delayed', () => {
  const ctx = createAgentContext()
  const originalDateNow = Date.now
  const originalSetInterval = global.window.setInterval
  const originalClearInterval = global.window.clearInterval
  let now = 1000
  let timerCallback = null

  Date.now = () => now
  global.window.setInterval = (callback) => {
    timerCallback = callback
    return 'timer-waiting'
  }
  global.window.clearInterval = () => {}

  try {
    ctx.agentLoading = true
    ctx.agentStreamState = 'connecting'
    ctx.agentThinkingTimeline = []
    ctx.upsertAgentThinkingItem({
      id: 'frontend-submit-request',
      phase: 'connecting',
      title: '提交请求',
      detail: '正在提交请求并等待 Agent 响应。',
      state: 'active',
    })
    ctx.startAgentThinkingTimer()

    now = 5000
    timerCallback()
    assert.deepEqual(ctx.getAgentVisibleProcessSteps().map((item) => item.id), ['frontend-submit-request', 'frontend-wait-backend'])
    assert.equal(ctx.getAgentVisibleProcessSteps()[0].state, 'completed')
    assert.equal(ctx.getAgentVisibleProcessSteps()[1].title, '等待后端首个进度事件')

    now = 14000
    timerCallback()
    assert.equal(ctx.getAgentVisibleProcessSteps().at(-1).id, 'frontend-wait-backend')
    assert.equal(ctx.getAgentVisibleProcessSteps().at(-1).title, '等待后端首个进度事件')

    ctx.upsertAgentThinkingItem({
      id: 'thinking-gating',
      phase: 'gating',
      title: '检查输入',
      detail: '正在检查问题与范围。',
      state: 'active',
    })
    assert.deepEqual(ctx.getAgentVisibleProcessSteps().map((item) => item.id), ['frontend-submit-request', 'thinking-gating'])
  } finally {
    Date.now = originalDateNow
    global.window.setInterval = originalSetInterval
    global.window.clearInterval = originalClearInterval
  }
})

test('reasoning deltas are merged in-memory and can be cleared before persistence', () => {
  const ctx = createAgentContext()

  ctx.upsertAgentReasoningDelta({ id: 'reasoning-1', phase: 'planned', title: '模型思考', delta: '先检查', state: 'active' })
  ctx.upsertAgentReasoningDelta({ id: 'reasoning-1', phase: 'planned', title: '模型思考', delta: '范围。', state: 'completed' })

  assert.equal(ctx.agentReasoningBlocks.length, 1)
  assert.equal(ctx.agentReasoningBlocks[0].content, '先检查范围。')
  assert.equal(ctx.agentShouldRenderThinkingBlock(), true)
  assert.equal(ctx.getAgentVisibleReasoningBlocks().length, 1)
  assert.equal(ctx.getAgentVisibleReasoningBlocks()[0].title, '模型思考')

  ctx.clearAgentReasoningBlocks()
  assert.equal(ctx.agentReasoningBlocks.length, 0)
})

test('submitMainAgentTurn shows submit process before first stream event', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.agentInput = '总结这个区域'

  let capturedSignal = null
  const streamStarted = createDeferred()
  global.fetch = async (url, options = {}) => {
    if (url === '/api/v1/analysis/agent/summary/readiness') {
      return {
        ok: true,
        async json() {
          return {
            checked: false,
            ready: false,
            missing_tasks: [],
            reused: [],
            fetched: [],
          }
        },
      }
    }
    capturedSignal = options.signal
    streamStarted.resolve()
    return createAbortablePendingResponse(options.signal)
  }

  const pending = ctx.submitMainAgentTurn()
  try {
    await waitForDeferred(streamStarted.promise, 'agent stream fetch did not start before process-steps test')

    const steps = ctx.getAgentVisibleProcessSteps()
    assert.equal(steps.length, 2)
    assert.equal(steps[0].id, 'frontend-submit-request')
    assert.equal(steps[0].title, '提交请求')
    assert.equal(steps[0].detail.includes('正在建立 Agent 流式响应'), false)
    assert.equal(steps[1].id, 'frontend-visual-snapshot-cache')
    assert.equal(steps[1].title, '准备地图视觉证据')
    assert.equal(ctx.agentThinkingTimeline.some((item) => item.id === 'stream-connect'), false)
    assert.equal(ctx.agentThinkingExpanded, true)
    assert.equal(ctx.shouldShowAgentThinkingLiveStatus(), true)
    assert.equal(ctx.shouldShowAgentThinkingToggle(), false)
    ctx.toggleAgentThinkingExpanded()
    assert.equal(ctx.agentThinkingExpanded, false)
    assert.equal(ctx.getAgentVisibleProcessSteps().length, 2)
    assert.equal(typeof capturedSignal?.aborted, 'boolean')
  } finally {
    ctx.cancelAgentTurn()
    await pending.catch(() => {})
  }
})

test('submitMainAgentTurn collapses process when stream errors before final response', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.agentInput = '总结这个区域'

  global.fetch = async (url) => {
    if (url === '/api/v1/analysis/agent/summary/readiness') {
      return {
        ok: true,
        async json() {
          return { checked: false, ready: false, missing_tasks: [], reused: [], fetched: [] }
        },
      }
    }
    return createSseResponse([
      {
        type: 'error',
        payload: { message: '综合回答失败' },
      },
    ])
  }

  await ctx.submitMainAgentTurn()

  assert.equal(ctx.agentStatus, 'failed')
  assert.equal(ctx.agentThinkingExpanded, false)
  assert.equal(ctx.agentPlanExpanded, false)
  assert.equal(ctx.agentTraceExpanded, false)
  assert.equal(ctx.shouldShowAgentThinkingLiveStatus(), false)
  assert.equal(ctx.shouldShowAgentThinkingToggle(), true)
})

test('getAgentVisibleProcessSteps keeps cumulative visible timeline items', () => {
  const ctx = createAgentContext()

  ctx.upsertAgentThinkingItem({
    id: 'stream-connect',
    phase: 'connecting',
    title: '连接实时过程',
    detail: '正在建立 Agent 流式响应。',
    state: 'active',
  })
  ctx.upsertAgentThinkingItem({
    id: 'thinking-gating',
    phase: 'gating',
    title: '检查输入',
    detail: '正在检查问题与范围。',
    state: 'active',
  })
  ctx.upsertAgentTraceThinkingItem({
    id: 'tool-call-read-current-scope',
    tool_name: 'read_current_scope',
    status: 'success',
    message: '执行成功',
    result_summary: 'scope_polygon 已读取',
  })

  assert.equal(ctx.agentThinkingTimeline.length, 3)
  assert.deepEqual(ctx.getAgentVisibleProcessSteps().map((item) => item.id), ['thinking-gating', 'tool-call-read-current-scope'])
  assert.equal(ctx.getAgentVisibleProcessSteps()[1].items.includes('结果：scope_polygon 已读取'), true)
})

test('getAgentNaturalProcessItems renders process as prose with tool lines', () => {
  const ctx = createAgentContext()

  ctx.upsertAgentThinkingItem({
    id: 'thinking-gating',
    phase: 'gating',
    title: '思考',
    detail: '我先判断这个问题是不是“下一步分析建议”，避免重新跑区域画像。',
    display_text: '我先判断这个问题是不是“下一步分析建议”，避免重新跑区域画像。',
    state: 'completed',
  })
  ctx.upsertAgentTraceThinkingItem({
    id: 'tool-call-read-current-results-start',
    tool_name: 'read_current_results',
    status: 'start',
    arguments_summary: '无参数',
    message: '正在调用工具。',
  })
  ctx.upsertAgentTraceThinkingItem({
    id: 'tool-call-read-current-results-success',
    tool_name: 'read_current_results',
    status: 'success',
    result_summary: '已发现 POI、H3、road、population、nightlight 结果。',
    display_text: '已发现 POI、H3、road、population、nightlight 结果。',
    evidence_count: 5,
  })

  const items = ctx.getAgentNaturalProcessItems()

  assert.deepEqual(items.map((item) => item.text), [
    '我先判断这个问题是不是“下一步分析建议”，避免重新跑区域画像。',
    '调用工具：读取已有分析结果',
    '已发现 POI、H3、road、population、nightlight 结果。',
  ])
  assert.equal(items.some((item) => ['思考', '行动', '观察'].includes(item.text)), false)
  assert.equal(items[2].metaText, '证据：5 条')
})

test('getAgentNaturalProcessItems only renders explicit display text and tool usage', () => {
  const ctx = createAgentContext()

  ctx.upsertAgentThinkingItem({
    id: 'frontend-submit-request',
    phase: 'connecting',
    title: '提交请求',
    detail: '问题已经发给 AI 了，正在等它开始处理。',
    state: 'completed',
  })
  ctx.upsertAgentThinkingItem({
    id: 'status-gating',
    phase: 'gating',
    title: '门卫判断',
    detail: '正在判断你的问题是否清晰、当前范围是否能直接开始分析。',
    state: 'completed',
  })
  ctx.upsertAgentThinkingItem({
    id: 'thinking-gating-result',
    phase: 'gating',
    title: '门卫通过',
    detail: '这个 detail 不能作为自然过程文案。',
    display_text: '用户要解释路网较差原因，当前范围有效，可以开始分析。',
    state: 'completed',
  })
  ctx.upsertAgentThinkingItem({
    id: 'status-planning',
    phase: 'planning',
    title: '规划分析步骤',
    detail: '正在决定这轮要调用哪些工具、补哪些证据。',
    state: 'active',
  })
  ctx.upsertAgentThinkingItem({
    id: 'thinking-planning',
    phase: 'planning',
    title: '规划分析步骤',
    detail: '正在决定本轮应调用哪些工具、补哪些证据。',
    display_text: '先复用已有路网结果，再补充空间分布证据。',
    state: 'active',
  })
  ctx.upsertAgentTraceThinkingItem({
    id: 'tool-call-analysis-preflight-start',
    tool_name: 'read_current_results',
    status: 'start',
    message: '执行工具',
    display_text: '确认当前已有 POI、人口、夜光和路网证据状态。',
    arguments_summary: '无参数',
  })
  ctx.upsertAgentTraceThinkingItem({
    id: 'tool-call-analysis-preflight-success',
    tool_name: 'read_current_results',
    status: 'success',
    message: '执行成功',
    result_summary: '执行成功',
    evidence_count: 2,
  })

  const items = ctx.getAgentNaturalProcessItems()

  assert.deepEqual(items.map((item) => item.text), [
    '用户要解释路网较差原因，当前范围有效，可以开始分析。',
    '先复用已有路网结果，再补充空间分布证据。',
    '调用工具：读取已有分析结果',
  ])
  assert.equal(items.some((item) => item.text.includes('问题已经发给 AI')), false)
  assert.equal(items.some((item) => item.text.includes('正在决定这轮')), false)
  assert.equal(items.some((item) => item.text.includes('这个 detail 不能作为自然过程文案')), false)
  assert.equal(items[2].metaText, '确认当前已有 POI、人口、夜光和路网证据状态。')
})

test('getAgentNaturalProcessItems renders tool finish result summary without display text', () => {
  const ctx = createAgentContext()

  ctx.upsertAgentTraceThinkingItem({
    id: 'tool-call-query-scope-dataset-success',
    tool_name: 'query_scope_dataset',
    status: 'success',
    message: '执行成功',
    result_summary: '返回 8 条当前范围 POI 记录。',
    evidence_count: 8,
    warning_count: 1,
  })

  const items = ctx.getAgentNaturalProcessItems()

  assert.equal(items.length, 1)
  assert.equal(items[0].text, '返回 8 条当前范围 POI 记录。')
  assert.equal(items[0].metaText, '证据：8 条；警告：1 条')
  assert.equal(items[0].kind, 'result')
})

test('getAgentProcessRoleGroups groups role steps into first-level panels', () => {
  const ctx = createAgentContext()

  ctx.upsertAgentThinkingItem({
    id: 'status-gating',
    phase: 'gating',
    title: '门卫判断',
    detail: '正在判断问题是否清晰。',
    state: 'completed',
  })
  ctx.upsertAgentThinkingItem({
    id: 'thinking-gate-pass',
    phase: 'gating',
    title: '门卫通过',
    detail: '问题已明确，可以进入规划。',
    state: 'completed',
  })
  ctx.upsertAgentThinkingItem({
    id: 'thinking-planning',
    phase: 'planning',
    title: '规划分析步骤',
    detail: '正在决定要调用哪些工具。',
    state: 'active',
  })

  const groups = ctx.getAgentProcessRoleGroups()

  assert.deepEqual(groups.map((item) => item.key), ['gating', 'planning'])
  assert.equal(groups[0].title, '门卫判断')
  assert.deepEqual(groups[0].steps.map((item) => item.title), ['门卫判断', '门卫通过'])
  assert.equal(groups[0].summary, '问题已明确，可以进入规划。')
  assert.equal(groups[1].title, '工具判断')
  assert.equal(groups[1].state, 'active')
})

test('getAgentProcessRoleGroups embeds planner checklist and tool calls', () => {
  const ctx = createAgentContext({
    agentPlan: {
      steps: [
        { tool_name: 'read_current_results', reason: '读取当前结果', evidence_goal: '确认已有摘要' },
        { tool_name: 'search_analysis_context', reason: '检索业态结构证据', evidence_goal: '形成商业画像' },
      ],
      summary: '先读取已有分析，再生成商业画像。',
    },
    agentExecutionTrace: [
      {
        tool_name: 'read_current_results',
        status: 'success',
        result_summary: '已有结果可复用',
        produced_artifacts: ['current_analysis_summary'],
      },
    ],
  })

  ctx.upsertAgentThinkingItem({
    id: 'thinking-planning',
    phase: 'planning',
    title: '规划分析步骤',
    detail: '正在决定要调用哪些工具。',
    state: 'completed',
  })
  ctx.upsertAgentThinkingItem({
    id: 'trace-read-current-results',
    phase: 'executing',
    title: '执行成功 read_current_results',
    detail: '已有结果可复用。',
    state: 'completed',
  })

  const groups = ctx.getAgentProcessRoleGroups()
  const plannerGroup = groups.find((item) => item.key === 'planning')
  const executingGroup = groups.find((item) => item.key === 'executing')

  assert.equal(plannerGroup.title, '工具判断')
  assert.equal(plannerGroup.planChecklist.visible, true)
  assert.equal(plannerGroup.planChecklist.groups[0].items.length, 2)
  assert.equal(plannerGroup.countLabel.includes('1/2 已完成'), true)
  assert.equal(executingGroup.title, '工具执行')
  assert.equal(executingGroup.toolCallItems.length, 1)
  assert.equal(executingGroup.toolCallItems[0].toolName, 'read_current_results')
})

test('getAgentProcessRoleGroups creates planner and tool panels without timeline steps', () => {
  const ctx = createAgentContext({
    agentPlan: {
      steps: [{ tool_name: 'read_current_results', reason: '读取当前结果', evidence_goal: '确认已有摘要' }],
      summary: '先读取已有分析。',
    },
    agentExecutionTrace: [{ tool_name: 'read_current_results', status: 'success' }],
  })

  const groups = ctx.getAgentProcessRoleGroups()

  assert.deepEqual(groups.map((item) => item.key), ['planning', 'executing'])
  assert.equal(groups[0].steps.length, 0)
  assert.equal(groups[0].planChecklist.visible, true)
  assert.equal(groups[0].countLabel, '1/1 已完成')
  assert.equal(groups[1].steps.length, 0)
  assert.equal(groups[1].toolCallItems.length, 1)
  assert.equal(groups[1].countLabel, '1 次')
})

test('status events create visible process fallback steps', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.agentInput = '总结这个区域'

  global.fetch = async (url) => {
    if (url === '/api/v1/analysis/agent/main-loop/stream') {
      return createSseResponse([
        {
          type: 'status',
          payload: { stage: 'gating', label: '检查输入' },
        },
        {
          type: 'status',
          payload: { stage: 'planning', label: '规划工具调用' },
        },
        {
          type: 'final',
          payload: {
            response: {
              status: 'answered',
              stage: 'answered',
              output: {
                answer: '这里以社区商业为主',
                clarification_question: '',
                risk_prompt: '',
                next_suggestions: [],
              },
              diagnostics: {
                execution_trace: [],
                used_tools: [],
                citations: [],
                research_notes: [],
                audit_issues: [],
                thinking_timeline: [],
                error: '',
              },
              context_summary: { has_scope: true, available_results: [], active_panel: 'agent', filters_digest: {} },
              plan: { steps: [] },
            },
          },
        },
      ])
    }
    return {
      ok: true,
      async json() {
        return {
          id: ctx.activeAgentSessionId,
          title: '社区商业概览',
          title_source: 'ai',
          preview: '这里以社区商业为主',
          status: 'answered',
          stage: 'answered',
          is_pinned: false,
          created_at: '2026-04-05T00:00:00Z',
          updated_at: '2026-04-05T01:00:00Z',
          pinned_at: null,
          input: '',
          messages: [
            { role: 'user', content: '总结这个区域' },
            { role: 'assistant', content: '这里以社区商业为主' },
          ],
          output: {
            answer: '这里以社区商业为主',
            clarification_question: '',
            risk_prompt: '',
          },
          diagnostics: { execution_trace: [], used_tools: [], citations: [], research_notes: [], audit_issues: [], thinking_timeline: [], error: '' },
          context_summary: { has_scope: true, available_results: [], active_panel: 'agent', filters_digest: {} },
          plan: { steps: [] },
          risk_confirmations: [],
        }
      },
    }
  }

  await ctx.submitMainAgentTurn()

  assert.deepEqual(
    ctx.getAgentVisibleProcessSteps().map((item) => item.id),
    ['frontend-submit-request', 'frontend-visual-snapshot-cache', 'status-gating', 'status-planning', 'status-answered'],
  )
  assert.equal(ctx.getAgentVisibleProcessSteps()[0].state, 'completed')
  assert.equal(ctx.getAgentVisibleProcessSteps()[1].state, 'completed')
  assert.equal(ctx.getAgentVisibleProcessSteps()[2].state, 'completed')
  assert.equal(ctx.getAgentVisibleProcessSteps()[3].title, '工具判断')
  assert.equal(ctx.getAgentVisibleProcessSteps()[4].state, 'completed')
})

test('applyAgentSessionSnapshot collapses failed timeline but expands risk confirmation', () => {
  const ctx = createAgentContext()
  const baseSnapshot = {
    id: 'agent-restored',
    input: '',
    stage: 'failed',
    cards: [],
    executionTrace: [],
    usedTools: [],
    citations: [],
    researchNotes: [],
    auditIssues: [],
    nextSuggestions: [],
    contextSummary: {},
    plan: { steps: [] },
    riskConfirmations: [],
    messages: [],
    thinkingTimeline: [
      { id: 'thinking-failed', phase: 'answering', title: '生成回答失败', detail: '需要查看原因。', state: 'failed' },
    ],
  }

  ctx.applyAgentSessionSnapshot({ ...baseSnapshot, status: 'failed' })
  assert.equal(ctx.agentThinkingExpanded, false)

  ctx.applyAgentSessionSnapshot({
    ...baseSnapshot,
    status: 'requires_risk_confirmation',
    stage: 'requires_risk_confirmation',
    thinkingTimeline: [
      { id: 'thinking-risk', phase: 'governance', title: '等待风险确认', detail: '需要确认工具调用。', state: 'active' },
    ],
  })
  assert.equal(ctx.agentThinkingExpanded, true)

  ctx.applyAgentSessionSnapshot({
    ...baseSnapshot,
    status: 'answered',
    stage: 'answered',
    thinkingTimeline: [
      { id: 'thinking-answered', phase: 'answering', title: '回答生成完成', detail: '已完成。', state: 'completed' },
    ],
  })
  assert.equal(ctx.agentThinkingExpanded, false)
})

test('applyAgentSessionSnapshot keeps planner and tool calls collapsed for answered history', () => {
  const ctx = createAgentContext({
    agentPlanExpanded: false,
    agentTraceExpanded: true,
  })

  ctx.applyAgentSessionSnapshot({
    id: 'agent-restored-plan',
    status: 'answered',
    stage: 'answered',
    cards: [],
    executionTrace: [{ tool_name: 'read_current_results', status: 'success' }],
    usedTools: ['read_current_results'],
    citations: [],
    researchNotes: [],
    auditIssues: [],
    nextSuggestions: [],
    contextSummary: {},
    plan: {
      steps: [{ tool_name: 'read_current_results', reason: '读取当前结果' }],
      summary: '先读取结果。',
    },
    riskConfirmations: [],
    messages: [],
    thinkingTimeline: [],
  })

  assert.equal(ctx.agentThinkingExpanded, false)
  assert.equal(ctx.agentPlanExpanded, false)
  assert.equal(ctx.agentTraceExpanded, false)
  assert.equal(ctx.agentPlan.summary, '先读取结果。')
})

test('getAgentPlanChecklist derives grouped checklist states from plan and trace', () => {
  const ctx = createAgentContext({
    agentPlan: {
      steps: [
        { tool_name: 'read_current_results', reason: '读取当前结果', evidence_goal: '确认已有证据' },
        { tool_name: 'search_analysis_context', reason: '检索空间结构证据', evidence_goal: '判断集中或分散' },
      ],
      followupSteps: [
        { tool_name: 'read_analysis_evidence_node', reason: '读取热点证据节点', evidence_goal: '补空间热点结论', optional: true },
      ],
      followupApplied: true,
      summary: '先读取已有分析，再补充热点识别。',
    },
    agentExecutionTrace: [
      { tool_name: 'read_current_results', status: 'success' },
      { tool_name: 'search_analysis_context', status: 'start' },
    ],
    agentLoading: true,
    agentStage: 'executing',
  })

  const checklist = ctx.getAgentPlanChecklist()

  assert.equal(checklist.visible, true)
  assert.equal(checklist.summary, '先读取已有分析，再补充热点识别。')
  assert.equal(checklist.progressLabel, '1/3 已完成')
  assert.equal(checklist.groups.length, 1)
  assert.equal(checklist.groups[0].items[0].status, 'completed')
  assert.equal(checklist.groups[0].items[1].status, 'active')
  assert.equal(checklist.groups[0].items[2].status, 'pending')
  assert.equal(checklist.groups[0].items[2].optional, true)

  ctx.agentPlanExpanded = true
  ctx.toggleAgentPlanExpanded()
  assert.equal(ctx.agentPlanExpanded, false)
})

test('getAgentToolCallItems normalizes trace cards and supports independent toggle state', () => {
  const ctx = createAgentContext({
    agentExecutionTrace: [
      {
        id: 'trace-1',
        tool_name: 'read_current_results',
        status: 'success',
        message: '读取成功',
        arguments_summary: 'scope=current',
        result_summary: '返回摘要',
        evidence_count: 2,
        warning_count: 1,
        produced_artifacts: ['current_results_summary'],
      },
      {
        id: 'trace-2',
        tool_name: 'query_scope_dataset',
        status: 'blocked',
        reason: '等待风险确认',
      },
    ],
    agentTraceExpanded: true,
  })

  const items = ctx.getAgentToolCallItems()

  assert.equal(items.length, 2)
  assert.equal(items[0].toolName, 'read_current_results')
  assert.equal(items[0].statusTone, 'success')
  assert.deepEqual(items[0].producedArtifacts, ['current_results_summary'])
  assert.equal(items[1].statusTone, 'blocked')
  assert.equal(ctx.getAgentToolCallStatusLabel('blocked'), '等待确认')

  ctx.toggleAgentTraceExpanded()
  assert.equal(ctx.agentTraceExpanded, false)
})

test('maybePreloadPanelForAgentTool preloads matching panel once without switching active panel', async () => {
  let populationPreloadCount = 0
  const ctx = createAgentContext({
    activeStep3Panel: 'agent',
    async ensurePopulationPanelEntryState() {
      populationPreloadCount += 1
    },
  })

  const first = await ctx.maybePreloadPanelForAgentTool({
    tool_name: 'query_scope_dataset',
    status: 'success',
    produced_artifacts: ['current_population_profile_analysis'],
  })
  const second = await ctx.maybePreloadPanelForAgentTool({
    tool_name: 'query_scope_dataset',
    status: 'success',
    produced_artifacts: ['current_population_profile_analysis'],
  })

  assert.equal(first, true)
  assert.equal(second, false)
  assert.equal(populationPreloadCount, 1)
  assert.equal(ctx.activeStep3Panel, 'agent')
  assert.deepEqual(ctx.getAgentPanelPreloadNotes().map((item) => item.label), ['已预加载人口面板数据'])
})

test('submitMainAgentTurn appends user message immediately and updates thinking timeline from stream', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.agentInput = '总结这个区域'

  global.fetch = async (url) => {
    if (url === '/api/v1/analysis/agent/main-loop/stream') {
      assert.deepEqual(ctx.agentMessages.map((item) => item.content), ['总结这个区域'])
      return createSseResponse([
        {
          type: 'status',
          payload: { stage: 'gating', label: '检查输入' },
        },
        {
          type: 'thinking',
          payload: { id: 'thinking-gating', phase: 'gating', title: '检查输入', detail: '正在检查问题与范围。', state: 'active' },
        },
        {
          type: 'reasoning_delta',
          payload: { id: 'reasoning-1', phase: 'planned', title: '模型思考', delta: '先读取当前范围。', state: 'active' },
        },
        {
          type: 'trace',
          payload: {
            id: 'tool-call-read-current-scope',
            tool_name: 'read_current_scope',
            status: 'start',
            reason: 'LLM tool call',
            message: '开始执行工具',
            arguments_summary: '无参数',
            result_summary: '',
            evidence_count: 0,
            warning_count: 0,
            produced_artifacts: ['scope_polygon'],
          },
        },
        {
          type: 'final',
          payload: {
            response: {
              status: 'answered',
              stage: 'answered',
              output: {
                answer: '这里以社区商业为主',
                clarification_question: '',
                risk_prompt: '',
                next_suggestions: [],
              },
              diagnostics: {
                execution_trace: [{ tool_name: 'read_current_scope', status: 'success' }],
                used_tools: ['read_current_scope'],
                citations: [],
                research_notes: [],
                audit_issues: [],
                thinking_timeline: [
                  { id: 'thinking-gating', phase: 'gating', title: '检查输入', detail: '正在检查问题与范围。', state: 'completed' },
                  {
                    id: 'tool-call-read-current-scope',
                    phase: 'executing',
                    title: '执行成功 read_current_scope',
                    detail: '执行成功',
                    items: ['参数：无参数', '结果：scope_polygon 已读取', '证据：1 条', '产物：scope_polygon'],
                    state: 'completed',
                  },
                ],
                error: '',
              },
              context_summary: {
                has_scope: true,
                available_results: [],
                active_panel: 'agent',
                filters_digest: {},
              },
              plan: {
                steps: [{ tool_name: 'read_current_scope', reason: '读取范围' }],
              },
            },
          },
        },
      ])
    }
    return {
      ok: true,
      async json() {
        return {
          id: ctx.activeAgentSessionId,
          title: '社区商业概览',
          title_source: 'ai',
          preview: '这里以社区商业为主',
          status: 'answered',
          stage: 'answered',
          is_pinned: false,
          created_at: '2026-04-05T00:00:00Z',
          updated_at: '2026-04-05T01:00:00Z',
          pinned_at: null,
          input: '',
          messages: [
            { role: 'user', content: '总结这个区域' },
            { role: 'assistant', content: '这里以社区商业为主' },
          ],
          output: {
            answer: '这里以社区商业为主',
            clarification_question: '',
            risk_prompt: '',
            next_suggestions: [],
          },
          diagnostics: {
            execution_trace: [],
            used_tools: [],
            citations: [],
            research_notes: [],
            audit_issues: [],
            thinking_timeline: [
              { id: 'thinking-gating', phase: 'gating', title: '检查输入', detail: '正在检查问题与范围。', state: 'completed' },
              {
                id: 'tool-call-read-current-scope',
                phase: 'executing',
                title: '执行成功 read_current_scope',
                detail: '执行成功',
                items: ['参数：无参数', '结果：scope_polygon 已读取', '证据：1 条', '产物：scope_polygon'],
                state: 'completed',
              },
            ],
            error: '',
          },
          context_summary: { has_scope: true, available_results: [], active_panel: 'agent', filters_digest: {} },
          plan: { steps: [] },
          risk_confirmations: [],
        }
      },
    }
  }

  const pending = ctx.submitMainAgentTurn()
  await Promise.resolve()

  assert.deepEqual(ctx.agentMessages.map((item) => item.content), ['总结这个区域'])
  assert.equal(ctx.agentInput, '')
  assert.equal(ctx.agentThinkingExpanded, true)
  assert.equal(ctx.getAgentVisibleProcessSteps()[0].title, '提交请求')
  assert.equal(ctx.getAgentVisibleProcessSteps()[0].title === '连接实时过程', false)

  await pending

  assert.equal(ctx.agentThinkingTimeline.length, 6)
  assert.equal(ctx.agentThinkingExpanded, false)
  assert.equal(ctx.agentPlanExpanded, false)
  assert.equal(ctx.agentTraceExpanded, false)
  assert.equal(ctx.shouldShowAgentThinkingLiveStatus(), false)
  assert.equal(ctx.shouldShowAgentThinkingToggle(), true)
  assert.deepEqual(ctx.getAgentMessagesBeforeThinking().map((item) => item.content), ['总结这个区域'])
  assert.deepEqual(ctx.getAgentMessagesAfterThinking().map((item) => item.content), ['这里以社区商业为主'])
  assert.deepEqual(
    ctx.getAgentVisibleProcessSteps().map((item) => item.id),
    ['frontend-submit-request', 'frontend-visual-snapshot-cache', 'status-gating', 'thinking-gating', 'tool-call-read-current-scope', 'status-answered'],
  )
  assert.equal(ctx.getAgentVisibleProcessSteps()[4].state, 'completed')
  const toolThinking = ctx.agentThinkingTimeline.find((item) => item.id === 'tool-call-read-current-scope')
  assert.equal(toolThinking.items.includes('参数：无参数'), true)
  assert.equal(toolThinking.items.includes('结果：scope_polygon 已读取'), true)
  assert.equal(ctx.agentStreamElapsedTimer, null)
  assert.equal(ctx.getAgentThinkingElapsedLabel().endsWith('s'), true)
  assert.equal(ctx.agentExecutionTrace.length, 1)
  assert.equal(ctx.agentAnswer, '这里以社区商业为主')
  assert.equal(ctx.agentReasoningBlocks.length, 1)
  assert.equal(ctx.getAgentVisibleReasoningBlocks()[0].content, '先读取当前范围。')
  assert.deepEqual(ctx.agentMessages.map((item) => item.content), ['总结这个区域', '这里以社区商业为主'])
  assert.equal(ctx.shouldShowAgentThinkingProcessBlock(), false)
  assert.equal(ctx.shouldShowAgentMessageProcess(ctx.agentMessages[1]), true)
  assert.deepEqual(
    ctx.agentMessages[1].process.thinkingTimeline.map((item) => item.id),
    ['frontend-submit-request', 'frontend-visual-snapshot-cache', 'status-gating', 'thinking-gating', 'tool-call-read-current-scope', 'status-answered'],
  )
  assert.equal(
    ctx.findAgentSession(ctx.activeAgentSessionId).thinkingTimeline.some((item) => item.id === 'thinking-gating'),
    true,
  )
  assert.equal(ctx.findAgentSession(ctx.activeAgentSessionId).preview, '这里以社区商业为主')
  assert.equal(Object.prototype.hasOwnProperty.call(ctx.findAgentSession(ctx.activeAgentSessionId), 'reasoningBlocks'), false)
})

test('clarification follow-up continues in the same session instead of opening a new report', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.updateAgentSessionSnapshot(ctx.activeAgentSessionId, (session) => ({
    ...session,
    persisted: true,
    snapshotLoaded: true,
    status: 'requires_clarification',
    stage: 'requires_clarification',
    messages: [{ role: 'user', content: '总结这个区域' }],
    clarificationQuestion: '你想重点看哪个方向？',
    clarificationOptions: ['总结这个区域的商业特征', '哪里适合补充餐饮', '为什么这里路网较弱'],
  }))
  ctx.syncActiveAgentRuntimeView(ctx.activeAgentSessionId)

  const originalSessionId = ctx.activeAgentSessionId
  let capturedConversationId = ''
  global.fetch = async (url, options = {}) => {
    assert.equal(url, '/api/v1/analysis/agent/main-loop/stream')
    const payload = JSON.parse(String(options.body || '{}'))
    capturedConversationId = String(payload.conversation_id || '')
    return createSseResponse([
      {
        type: 'final',
        payload: {
          response: {
            status: 'answered',
            stage: 'answered',
            output: {
              answer: '已继续在原会话中回答。',
              clarification_question: '',
              clarification_options: [],
              risk_prompt: '',
            },
            diagnostics: {
              execution_trace: [],
              used_tools: [],
              citations: [],
              research_notes: [],
              audit_issues: [],
              thinking_timeline: [],
              error: '',
            },
            context_summary: {},
            plan: { steps: [], summary: '' },
          },
        },
      },
    ])
  }

  ctx.onAgentClarificationOptionClick('哪里适合补充餐饮')
  await new Promise((resolve) => setTimeout(resolve, 0))

  assert.equal(capturedConversationId, originalSessionId)
  assert.equal(ctx.activeAgentSessionId, originalSessionId)
  assert.equal(ctx.agentSessions.length, 1)
  assert.equal(ctx.findAgentSession(originalSessionId).status, 'answered')
  assert.deepEqual(
    ctx.findAgentSession(originalSessionId).messages.map((item) => item.content),
    ['总结这个区域', '哪里适合补充餐饮', '已继续在原会话中回答。'],
  )
  assert.equal(ctx.findAgentSession(originalSessionId).messages[2].role, 'assistant')
  assert.equal(ctx.shouldShowAgentThinkingProcessBlock(), false)
})

test('multi-turn thinking keeps previous assistant above the new user turn', async () => {
  const ctx = createAgentContext({
    agentMessages: [
      { role: 'user', content: '第一轮问题' },
      { role: 'assistant', content: '第一轮回答' },
    ],
    agentThinkingTimeline: [
      { id: 'thinking-prev', phase: 'answering', title: '回答生成完成', detail: '上一轮已结束。', state: 'completed' },
    ],
  })

  assert.deepEqual(ctx.getAgentMessagesBeforeThinking().map((item) => item.content), ['第一轮问题'])
  assert.deepEqual(ctx.getAgentMessagesAfterThinking().map((item) => item.content), ['第一轮回答'])

  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.updateAgentSessionSnapshot(ctx.activeAgentSessionId, (session) => ({
    ...session,
    messages: [
      { role: 'user', content: '第一轮问题' },
      { role: 'assistant', content: '第一轮回答' },
    ],
    thinkingTimeline: [],
  }))
  ctx.agentInput = '第二轮问题'

  global.fetch = async (url) => {
    if (url === '/api/v1/analysis/agent/main-loop/stream') {
      await Promise.resolve()
      return createSseResponse([
        { type: 'status', payload: { stage: 'gating', label: '门卫判断' } },
        { type: 'thinking', payload: { id: 'thinking-gating', phase: 'gating', title: '门卫判断', detail: '正在判断。', state: 'active' } },
        {
          type: 'final',
          payload: {
            response: {
              status: 'answered',
              stage: 'answered',
              output: {
                answer: '第二轮结论',
                clarification_question: '',
                risk_prompt: '',
                next_suggestions: [],
              },
              diagnostics: {
                execution_trace: [],
                used_tools: [],
                citations: [],
                research_notes: [],
                audit_issues: [],
                thinking_timeline: [{ id: 'thinking-gating', phase: 'gating', title: '门卫判断', detail: '已完成。', state: 'completed' }],
                error: '',
              },
              context_summary: { has_scope: true, available_results: [], active_panel: 'agent', filters_digest: {} },
              plan: { steps: [] },
            },
          },
        },
      ])
    }
    return {
      ok: true,
      async json() {
        return {
          id: ctx.activeAgentSessionId,
          title: '第二轮',
          title_source: 'ai',
          preview: '第二轮结论',
          status: 'answered',
          stage: 'answered',
          is_pinned: false,
          created_at: '2026-04-05T00:00:00Z',
          updated_at: '2026-04-05T01:00:00Z',
          pinned_at: null,
          input: '',
          messages: [
            { role: 'user', content: '第一轮问题' },
            { role: 'assistant', content: '第一轮回答' },
            { role: 'user', content: '第二轮问题' },
            {
              role: 'assistant',
              content: '第二轮结论',
              process: {
                thinking_timeline: [
                  { id: 'thinking-gating', phase: 'gating', title: '门卫判断', detail: '已完成。', state: 'completed' },
                  { id: 'status-answered', phase: 'answered', title: '回答生成完成', detail: '', state: 'completed' },
                ],
              },
            },
          ],
          output: {
            answer: '第二轮结论',
            clarification_question: '',
            risk_prompt: '',
          },
          diagnostics: { execution_trace: [], used_tools: [], citations: [], research_notes: [], audit_issues: [], thinking_timeline: [{ id: 'thinking-gating', phase: 'gating', title: '门卫判断', detail: '已完成。', state: 'completed' }], error: '' },
          context_summary: { has_scope: true, available_results: [], active_panel: 'agent', filters_digest: {} },
          plan: { steps: [] },
          risk_confirmations: [],
        }
      },
    }
  }

  const pending = ctx.submitMainAgentTurn()
  await Promise.resolve()

  assert.deepEqual(
    ctx.getAgentMessagesBeforeThinking().map((item) => item.content),
    ['第一轮问题', '第一轮回答', '第二轮问题'],
  )
  assert.deepEqual(ctx.getAgentMessagesAfterThinking().map((item) => item.content), [])

  await pending

  assert.deepEqual(
    ctx.getAgentMessagesBeforeThinking().map((item) => item.content),
    ['第一轮问题', '第一轮回答', '第二轮问题'],
  )
  assert.deepEqual(ctx.getAgentMessagesAfterThinking().map((item) => item.content), ['第二轮结论'])
  assert.deepEqual(
    ctx.getAgentThreadMessages().map((item) => item.content),
    ['第一轮问题', '第一轮回答', '第二轮问题', '第二轮结论'],
  )
})

test('getAgentMessagesAfterThinking only returns assistant messages from the current turn', () => {
  const ctx = createAgentContext({
    agentMessages: [
      { role: 'user', content: '第一轮问题' },
      { role: 'assistant', content: '第一轮回答' },
      { role: 'user', content: '第二轮问题' },
      { role: 'assistant', content: '第二轮回答' },
    ],
    agentThinkingTimeline: [
      { id: 'thinking-current', phase: 'answering', title: '回答生成完成', detail: '第二轮已结束。', state: 'completed' },
    ],
  })

  assert.deepEqual(
    ctx.getAgentMessagesBeforeThinking().map((item) => item.content),
    ['第一轮问题', '第一轮回答', '第二轮问题'],
  )
  assert.deepEqual(ctx.getAgentMessagesAfterThinking().map((item) => item.content), ['第二轮回答'])
})

test('submitMainAgentTurn keeps streamed timeline order when final diagnostics omit intermediate steps', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.agentInput = '总结这个区域'

  global.fetch = async (url) => {
    if (url === '/api/v1/analysis/agent/main-loop/stream') {
      return createSseResponse([
        {
          type: 'status',
          payload: { stage: 'gating', label: '门卫判断' },
        },
        {
          type: 'thinking',
          payload: { id: 'thinking-gate-pass', phase: 'gating', title: '门卫通过', detail: '问题已明确。', state: 'completed' },
        },
        {
          type: 'plan',
          payload: {
            steps: [{ tool_name: 'read_current_results', reason: '读取当前结果', evidence_goal: '确认已有证据' }],
            summary: '先读取当前结果。',
          },
        },
        {
          type: 'trace',
          payload: {
            id: 'tool-call-read-current-results',
            tool_name: 'read_current_results',
            status: 'success',
            message: '执行成功',
            result_summary: '已读取现有摘要',
          },
        },
        {
          type: 'final',
          payload: {
            response: {
              status: 'answered',
              stage: 'answered',
              output: {
                answer: '这里以社区商业为主',
                clarification_question: '',
                risk_prompt: '',
                next_suggestions: [],
              },
              diagnostics: {
                execution_trace: [{ tool_name: 'read_current_results', status: 'success' }],
                used_tools: ['read_current_results'],
                citations: [],
                research_notes: [],
                audit_issues: [],
                thinking_timeline: [
                  { id: 'status-gating', phase: 'gating', title: '门卫判断', detail: '已检查输入。', state: 'completed' },
                ],
                error: '',
              },
              context_summary: { has_scope: true, available_results: [], active_panel: 'agent', filters_digest: {} },
              plan: {
                steps: [{ tool_name: 'read_current_results', reason: '读取当前结果', evidence_goal: '确认已有证据' }],
                summary: '先读取当前结果。',
              },
            },
          },
        },
      ])
    }
    return {
      ok: true,
      async json() {
        return {
          id: ctx.activeAgentSessionId,
          title: '社区商业概览',
          title_source: 'ai',
          preview: '这里以社区商业为主',
          status: 'answered',
          stage: 'answered',
          is_pinned: false,
          created_at: '2026-04-05T00:00:00Z',
          updated_at: '2026-04-05T01:00:00Z',
          pinned_at: null,
          input: '',
          messages: [
            { role: 'user', content: '总结这个区域' },
            { role: 'assistant', content: '这里以社区商业为主' },
          ],
          output: {
            answer: '这里以社区商业为主',
            clarification_question: '',
            risk_prompt: '',
            next_suggestions: [],
          },
          diagnostics: {
            execution_trace: [{ tool_name: 'read_current_results', status: 'success' }],
            used_tools: ['read_current_results'],
            citations: [],
            research_notes: [],
            audit_issues: [],
            thinking_timeline: [
              { id: 'status-gating', phase: 'gating', title: '门卫判断', detail: '已检查输入。', state: 'completed' },
            ],
            error: '',
          },
          context_summary: { has_scope: true, available_results: [], active_panel: 'agent', filters_digest: {} },
          plan: { steps: [] },
          risk_confirmations: [],
        }
      },
    }
  }

  await ctx.submitMainAgentTurn()

  const steps = ctx.getAgentVisibleProcessSteps()
  assert.deepEqual(
    steps.map((item) => item.title),
    ['提交请求', '准备地图视觉证据', '门卫判断', '门卫通过', '已列出本轮步骤', '执行成功 read_current_results', '回答生成完成'],
  )
  assert.equal(steps[4].detail, '先读取当前结果。')
})

test('submitMainAgentTurn shows streamed plan above final response and keeps checklist expanded by default', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.agentInput = '总结这个区域'

  global.fetch = async (url) => {
    if (url === '/api/v1/analysis/agent/main-loop/stream') {
      return createSseResponse([
        {
          type: 'plan',
          payload: {
            steps: [
              { tool_name: 'read_current_results', reason: '读取当前结果', evidence_goal: '确认已有摘要' },
              { tool_name: 'search_analysis_context', reason: '检索业态结构证据', evidence_goal: '形成商业画像' },
            ],
            summary: '先读取已有分析，再生成商业画像。',
          },
        },
        {
          type: 'trace',
          payload: {
            tool_name: 'read_current_results',
            status: 'success',
            reason: '读取当前结果',
            message: '执行成功',
          },
        },
        {
          type: 'final',
          payload: {
            response: {
              status: 'answered',
              stage: 'answered',
              output: {
                answer: '这里以社区商业为主',
                clarification_question: '',
                risk_prompt: '',
                next_suggestions: [],
              },
              diagnostics: {
                execution_trace: [{ tool_name: 'read_current_results', status: 'success' }],
                used_tools: ['read_current_results'],
                citations: [],
                research_notes: [],
                audit_issues: [],
                thinking_timeline: [],
                error: '',
              },
              context_summary: { has_scope: true, available_results: [], active_panel: 'agent', filters_digest: {} },
              plan: {
                steps: [
                  { tool_name: 'read_current_results', reason: '读取当前结果', evidence_goal: '确认已有摘要' },
                  { tool_name: 'search_analysis_context', reason: '检索业态结构证据', evidence_goal: '形成商业画像' },
                ],
                summary: '先读取已有分析，再生成商业画像。',
              },
            },
          },
        },
      ])
    }
    return {
      ok: true,
      async json() {
        return {
          id: ctx.activeAgentSessionId,
          title: '社区商业概览',
          title_source: 'ai',
          preview: '这里以社区商业为主',
          status: 'answered',
          stage: 'answered',
          is_pinned: false,
          created_at: '2026-04-05T00:00:00Z',
          updated_at: '2026-04-05T01:00:00Z',
          pinned_at: null,
          input: '',
          messages: [{ role: 'user', content: '总结这个区域' }],
          output: {
            answer: '这里以社区商业为主',
            clarification_question: '',
            risk_prompt: '',
            next_suggestions: [],
          },
          diagnostics: { execution_trace: [{ tool_name: 'read_current_results', status: 'success' }], used_tools: ['read_current_results'], citations: [], research_notes: [], audit_issues: [], thinking_timeline: [], error: '' },
          context_summary: { has_scope: true, available_results: [], active_panel: 'agent', filters_digest: {} },
          plan: {
            steps: [
              { tool_name: 'read_current_results', reason: '读取当前结果', evidence_goal: '确认已有摘要' },
              { tool_name: 'search_analysis_context', reason: '检索业态结构证据', evidence_goal: '形成商业画像' },
            ],
            summary: '先读取已有分析，再生成商业画像。',
          },
          risk_confirmations: [],
        }
      },
    }
  }

  const pending = ctx.submitMainAgentTurn()
  await pending

  assert.equal(ctx.agentPlan.steps.length, 2)
  assert.equal(ctx.agentPlan.summary, '先读取已有分析，再生成商业画像。')
  assert.equal(ctx.agentPlanExpanded, false)
  assert.equal(ctx.agentTraceExpanded, false)
  assert.equal(ctx.getAgentPlanChecklist().visible, true)
  assert.equal(ctx.getAgentPlanChecklist().groups[0].items[0].status, 'completed')
  assert.equal(ctx.getAgentPlanChecklist().groups[0].items[1].status, 'pending')
})

test('submitMainAgentTurn preloads mapped panel after successful trace and records lightweight note', async () => {
  let h3EnsureCount = 0
  let h3ChartsCount = 0
  let decisionCardsCount = 0
  let h3RestoreCount = 0
  const ctx = createAgentContext({
    h3AnalysisSummary: { grid_count: 12 },
    ensureH3PanelEntryState() {
      h3EnsureCount += 1
    },
    updateH3Charts() {
      h3ChartsCount += 1
    },
    updateDecisionCards() {
      decisionCardsCount += 1
    },
    restoreH3GridDisplayOnEnter() {
      h3RestoreCount += 1
    },
  })
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.agentInput = '哪里是商业核心'

  global.fetch = async (url) => {
    if (url === '/api/v1/analysis/agent/main-loop/stream') {
      return createSseResponse([
        {
          type: 'trace',
          payload: {
            tool_name: 'query_scope_dataset',
            status: 'success',
            reason: '读取 H3 结构',
            message: '执行成功',
            produced_artifacts: ['current_h3_structure_analysis'],
          },
        },
        {
          type: 'final',
          payload: {
            response: {
              status: 'answered',
              stage: 'answered',
              output: {
                cards: [{ type: 'summary', title: '概览', content: '商业有明显集聚', items: [] }],
                clarification_question: '',
                risk_prompt: '',
                next_suggestions: [],
              },
              diagnostics: {
                execution_trace: [{ tool_name: 'query_scope_dataset', status: 'success', produced_artifacts: ['current_h3_structure_analysis'] }],
                used_tools: ['query_scope_dataset'],
                citations: [],
                research_notes: [],
                audit_issues: [],
                thinking_timeline: [],
                error: '',
              },
              context_summary: { has_scope: true, available_results: [], active_panel: 'agent', filters_digest: {} },
              plan: { steps: [], summary: '' },
            },
          },
        },
      ])
    }
    return {
      ok: true,
      async json() {
        return {
          id: ctx.activeAgentSessionId,
          title: '商业核心判断',
          title_source: 'ai',
          preview: '商业有明显集聚',
          status: 'answered',
          stage: 'answered',
          is_pinned: false,
          created_at: '2026-04-05T00:00:00Z',
          updated_at: '2026-04-05T01:00:00Z',
          pinned_at: null,
          input: '',
          messages: [{ role: 'user', content: '哪里是商业核心' }],
          output: {
            cards: [{ type: 'summary', title: '概览', content: '商业有明显集聚', items: [] }],
            clarification_question: '',
            risk_prompt: '',
            next_suggestions: [],
          },
          diagnostics: { execution_trace: [{ tool_name: 'query_scope_dataset', status: 'success', produced_artifacts: ['current_h3_structure_analysis'] }], used_tools: ['query_scope_dataset'], citations: [], research_notes: [], audit_issues: [], thinking_timeline: [], error: '' },
          context_summary: { has_scope: true, available_results: [], active_panel: 'agent', filters_digest: {} },
          plan: { steps: [], summary: '' },
          risk_confirmations: [],
        }
      },
    }
  }

  await ctx.submitMainAgentTurn()

  assert.equal(h3EnsureCount, 1)
  assert.equal(h3ChartsCount, 1)
  assert.equal(decisionCardsCount, 1)
  assert.equal(h3RestoreCount, 1)
  assert.deepEqual(ctx.getAgentPanelPreloadNotes().map((item) => item.label), ['已预加载 POI H3 面板内容'])
  assert.equal(ctx.activeStep3Panel, 'agent')
})

test('onAgentCardItemClick switches to result panel and focuses target h3 cell', async () => {
  let ensureCalls = 0
  let focusedH3Id = ''
  let receivedPayload = null
  const ctx = createAgentContext({
    async ensureH3ReadyForAgentTarget(payload, options = {}) {
      ensureCalls += 1
      receivedPayload = { payload, options }
      return true
    },
    focusGridByH3Id(h3Id) {
      focusedH3Id = h3Id
    },
  })
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.updateAgentSessionSnapshot(ctx.activeAgentSessionId, (session) => ({
    ...session,
    panelPayloads: {
      h3_result: {
        summary: { grid_count: 3 },
        ui: { target_category: 'group-05' },
      },
    },
  }))

  await ctx.onAgentCardItemClick({
    type: 'h3_candidate',
    h3_id: '8928308280fffff',
    text: '候选1：人民路附近',
  })

  assert.equal(ctx.sidebarView, 'wizard')
  assert.equal(ctx.step, 2)
  assert.equal(ctx.activeStep3Panel, 'poi')
  assert.equal(ctx.poiSubTab, 'grid')
  assert.equal(ensureCalls, 1)
  assert.equal(receivedPayload.payload.h3_result.summary.grid_count, 3)
  assert.equal(receivedPayload.options.targetCategory, 'group-05')
  assert.equal(focusedH3Id, '8928308280fffff')
})

test('site selection tab exposes target readiness and blocks missing target', () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  const tabId = ctx.createAgentSiteSelectionTab({ title: '区域内选址' })

  assert.equal(ctx.agentTabs.activeTabId, tabId)
  assert.equal(ctx.isAgentSiteSelectionTabActive(), true)
  assert.equal(ctx.getAgentTopTabs().find((item) => item.id === tabId).kind, 'site_selection')
  assert.equal(ctx.canRunAgentSiteSelection(), false)

  ctx.setAgentSiteSelectionTargetType('咖啡店')

  assert.equal(ctx.inferAgentSiteSelectionTargetType(), '咖啡店')
  assert.equal(ctx.getAgentSiteSelectionBlockingItems().length, 0)
  assert.equal(ctx.isAgentSiteSelectionDataReady(), false)
  assert.equal(ctx.getAgentSiteSelectionTaskBoardTasks().map((task) => task.key).includes('poi_raster_grid'), false)
  assert.equal(ctx.canRunAgentSiteSelection(), false)

  markSiteSelectionDataReady(ctx)

  assert.equal(ctx.isAgentSiteSelectionDataReady(), true)
  assert.equal(ctx.canRunAgentSiteSelection(), true)
})

test('site selection data fill reuses summary task runner', async () => {
  const ctx = createAgentContext()
  const ran = []
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.createAgentSiteSelectionTab({ title: '区域内选址' })
  ctx.runSummaryTask = async (key) => {
    ran.push(key)
    if (key === 'poi_fetch') ctx.allPoisDetails = [{ id: 'poi-1' }]
    if (key === 'poi_h3_grid') {
      ctx.h3AnalysisSummary = { grid_count: 1 }
      ctx.h3GridCount = 1
    }
    if (key === 'population') ctx.populationOverview = { summary: { total_population: 1 } }
    if (key === 'nightlight') ctx.nightlightOverview = { summary: { mean_radiance: 1 } }
    if (key === 'road_syntax') {
      ctx.roadSyntaxSummary = { node_count: 1 }
      ctx.roadSyntaxStatus = '计算完成'
    }
    ctx.finalizeSummaryTaskAsReused(key)
  }

  await ctx.runAgentSiteSelectionDataFill()

  assert.deepEqual(ran, ['poi_fetch', 'poi_h3_grid', 'population', 'nightlight', 'road_syntax'])
  assert.equal(ctx.isAgentSiteSelectionDataReady(), true)
})

test('site selection does not call analysis API before data is ready', async () => {
  const ctx = createAgentContext()
  const calls = []
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.createAgentSiteSelectionTab({ title: '区域内选址' })
  ctx.setAgentSiteSelectionTargetType('咖啡店')
  global.fetch = async (url) => {
    calls.push(url)
    return {
      ok: true,
      async json() {
        return {}
      },
    }
  }

  await ctx.generateAgentSiteSelection()

  assert.equal(calls.some((url) => String(url).includes('/api/v1/analysis/agent/site-selection')), false)
  assert.equal(ctx.getAgentSiteSelectionState().error, '请先补齐 POI、H3、人口、夜光和路网基础数据')
})

test('site selection analysis calls direct API instead of agent stream', async () => {
  const calls = []
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.currentHistoryRecordId = 'history-1'
  ctx.startNewAgentReportSession()
  const tabId = ctx.createAgentSiteSelectionTab({ title: '区域内选址' })
  ctx.setAgentSiteSelectionTargetType('咖啡店')
  ctx.setAgentSiteSelectionStrategy('supply_gap')
  ctx.setAgentSiteSelectionScenario('commuter')
  markSiteSelectionDataReady(ctx)

  global.fetch = async (url, options = {}) => {
    calls.push({ url, options })
    assert.equal(url, '/api/v1/analysis/agent/site-selection')
    const body = JSON.parse(options.body)
    assert.equal(body.place_type, '咖啡店')
    assert.equal(body.policy_key, 'business_catchment_1km')
    assert.equal(body.strategy, 'supply_gap')
    assert.equal(body.scenario, 'commuter')
    assert.equal(body.source, 'local')
    return {
      ok: true,
      async json() {
        return {
          status: 'success',
          site_selection_pack: {
            summary_text: '已形成候选格。',
            overall_verdict: 'suitable',
            verdict_text: '当前范围可优先验证咖啡店。',
            candidate_sites: [{
              rank: 1,
              h3_id: '8928308280fffff',
              display_title: '候选1',
              total_score: 80,
              positioning: '通勤快取型咖啡店',
              why_suitable: ['供给缺口明显'],
              next_validation_steps: ['观察早高峰人流'],
            }],
            ranking: [{ rank: 1, title: '候选1', total_score: 80 }],
            avoid_areas: [{ title: '低活力网格', reason: '夜间活力弱', score: 42 }],
          },
          current_target_supply_gap: { place_type: '咖啡店' },
          current_site_candidate_scores: { confidence: 'moderate' },
          warnings: ['人口数据缺失，已降级。'],
        }
      },
    }
  }

  await ctx.generateAgentSiteSelection()

  const siteSelectionCalls = calls.filter((call) => call.url === '/api/v1/analysis/agent/site-selection')
  assert.equal(siteSelectionCalls.length, 1)
  assert.equal(calls.some((call) => call.url.includes('/agent/main-loop/stream')), false)
  assert.equal(ctx.agentTabs.activeTabId, tabId)
  assert.equal(ctx.isAgentSiteSelectionTabActive(), true)
  assert.equal(ctx.getAgentSiteSelectionPack().summary_text, '已形成候选格。')
  assert.equal(ctx.getAgentSiteSelectionState().warnings[0], '人口数据缺失，已降级。')
  assert.equal(ctx.getAgentSiteSelectionCandidates()[0].title, '候选1')
  assert.equal(ctx.getAgentSiteSelectionState().selectedH3Id, '8928308280fffff')
  assert.equal(ctx.getAgentSiteSelectionCandidates()[0].positioning, '通勤快取型咖啡店')
  assert.equal(ctx.getAgentSiteSelectionSelectedWhySuitable()[0], '供给缺口明显')
  assert.equal(ctx.getAgentSiteSelectionSelectedValidationSteps()[0], '观察早高峰人流')
  assert.equal(ctx.getAgentSiteSelectionAvoidAreas()[0].title, '低活力网格')
  assert.equal(ctx.getAgentSiteSelectionVerdict().label, '适合优先验证')
})

test('site selection uses drawn polygon fallback when isochrone payload is empty', async () => {
  let requestBody = null
  const drawnPolygon = [[112.1, 28.1], [112.2, 28.1], [112.2, 28.2], [112.1, 28.1]]
  const ctx = createAgentContext({
    getIsochronePolygonRing() {
      return null
    },
    getIsochronePolygonPayload() {
      return []
    },
    getDrawnScopePolygonPoints() {
      return drawnPolygon
    },
  })
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.createAgentSiteSelectionTab({ title: '区域内选址' })
  ctx.setAgentSiteSelectionTargetType('咖啡店')
  markSiteSelectionDataReady(ctx)

  assert.equal(ctx.canRunAgentSiteSelection(), true)

  global.fetch = async (url, options = {}) => {
    assert.equal(url, '/api/v1/analysis/agent/site-selection')
    requestBody = JSON.parse(options.body)
    return {
      ok: true,
      async json() {
        return {
          status: 'success',
          site_selection_pack: {
            confidence: 'weak',
            candidate_sites: [],
            ranking: [],
            not_recommended_reason: '当前缺少足够候选区证据',
          },
        }
      },
    }
  }

  await ctx.generateAgentSiteSelection()

  assert.deepEqual(requestBody.analysis_snapshot.scope.drawn_polygon, drawnPolygon)
  assert.deepEqual(requestBody.analysis_snapshot.scope.polygon, drawnPolygon)
  assert.equal(ctx.getAgentSiteSelectionState().error, '')
  assert.equal(ctx.getAgentSiteSelectionVerdict().label, '谨慎预筛')
})

test('site selection maps backend scope errors to readable copy', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.createAgentSiteSelectionTab({ title: '区域内选址' })
  ctx.setAgentSiteSelectionTargetType('咖啡店')
  markSiteSelectionDataReady(ctx)

  global.fetch = async () => ({
    ok: true,
    async json() {
      return { status: 'failed', error: 'missing_scope_polygon' }
    },
  })

  await ctx.generateAgentSiteSelection()

  assert.equal(
    ctx.getAgentSiteSelectionState().error,
    '当前还没有可用分析范围。请先生成等时圈，或在地图上手绘一个范围后再分析。',
  )
})

test('site selection maps unresolved place type to readable copy', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.createAgentSiteSelectionTab({ title: '区域内选址' })
  ctx.setAgentSiteSelectionTargetType('不明确业态')
  markSiteSelectionDataReady(ctx)

  global.fetch = async () => ({
    ok: true,
    async json() {
      return { status: 'failed', error: 'unresolved_place_type' }
    },
  })

  await ctx.generateAgentSiteSelection()

  assert.equal(
    ctx.getAgentSiteSelectionState().error,
    '暂不支持这个业态名称。请换成咖啡店、便利店、餐饮、超市等更明确的类型。',
  )
})

test('site selection payload normalizes candidates, evidence, and h3 focus action', async () => {
  let focusedH3Id = ''
  const ctx = createAgentContext({
    async ensureH3ReadyForAgentTarget() {
      return true
    },
    focusGridByH3Id(h3Id) {
      focusedH3Id = h3Id
    },
  })
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.createAgentSiteSelectionTab({ title: '区域内选址' })
  ctx.commitAgentSiteSelectionPayload({
    panelPayloads: {
      site_selection_pack: {
        summary_text: '候选1综合支撑较好。',
        confidence: 'moderate',
        candidate_sites: [{
          rank: 1,
          h3_id: '8928308280fffff',
          display_title: '候选1：人民路附近',
          approx_address: '人民路附近',
          total_score: 86.4,
          gap_score: 0.62,
          scores: { population: 72, vitality: 66, road: 58 },
          reason_summary: '需求分位较高，供给分位较低',
        }],
        evidence_chain: [{
          tool_name: 'score_site_candidates',
          value: [{ rank: 1 }],
          rule_or_reason: '程序化评分排序',
          confidence: 'moderate',
        }],
      },
    },
    ui: { target_type: '咖啡店', status: 'ready' },
  })

  const candidates = ctx.getAgentSiteSelectionCandidates()
  assert.equal(candidates.length, 1)
  assert.equal(candidates[0].title, '候选1：人民路附近')
  assert.equal(ctx.formatAgentSiteSelectionScore(candidates[0].totalScore), '86')
  assert.equal(ctx.getAgentSiteSelectionEvidenceChain()[0].value, '1 项')
  assert.equal(candidates[0].positioning, '通勤快取型咖啡店 · 综合评估')
  assert.ok(ctx.getAgentSiteSelectionSelectedValidationSteps().length > 0)
  const askTarget = ctx.buildSiteCandidateContextAskTarget(candidates[0])
  assert.equal(askTarget.type, 'site_candidate')
  assert.equal(askTarget.id, '8928308280fffff')
  assert.equal(askTarget.payload.rank, 1)
  assert.equal(askTarget.payload.h3Id, '8928308280fffff')
  assert.equal(askTarget.evidence.length, 1)

  await ctx.onAgentSiteSelectionCandidateClick(candidates[0])

  assert.equal(ctx.activeStep3Panel, 'poi')
  assert.equal(ctx.poiSubTab, 'grid')
  assert.equal(focusedH3Id, '8928308280fffff')
})

test('site selection tabs persist and restore with panel payloads', () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  const tabId = ctx.createAgentSiteSelectionTab({ title: '区域内选址' })
  ctx.commitAgentSiteSelectionPayload({
    panelPayloads: {
      site_selection_pack: { summary_text: '已形成候选格。' },
    },
    ui: { target_type: '便利店', strategy: 'avoid_competition', scenario: 'community', status: 'ready' },
  })
  const uiState = ctx.buildAgentTabsUiState()

  assert.equal(uiState.site_selection_tabs.length, 1)
  assert.equal(uiState.site_selection_tabs[0].id, tabId)

  const restored = createAgentContext()
  restored.restoreAgentTabsFromSession({
    id: 'session-1',
    panelPayloads: {
      agent_tabs: {
        ...uiState,
        active_tab_id: tabId,
      },
    },
  })

  assert.equal(restored.isAgentSiteSelectionTabActive(), true)
  assert.equal(restored.inferAgentSiteSelectionTargetType(), '便利店')
  assert.equal(restored.getAgentSiteSelectionState().strategy, 'avoid_competition')
  assert.equal(restored.getAgentSiteSelectionState().scenario, 'community')
  assert.equal(restored.getAgentSiteSelectionPack().summary_text, '已形成候选格。')
})

test('submitMainAgentTurn collapses failed thinking timeline after final response', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.agentInput = '总结这个区域'

  global.fetch = async (url) => {
    if (url === '/api/v1/analysis/agent/main-loop/stream') {
      return createSseResponse([
        {
          type: 'thinking',
          payload: {
            id: 'thinking-answering',
            phase: 'answering',
            title: '生成回答',
            detail: '正在组织结果。',
            state: 'active',
          },
        },
        {
          type: 'final',
          payload: {
            response: {
              status: 'failed',
              stage: 'failed',
              output: {
                cards: [],
                clarification_question: '',
                risk_prompt: '',
                next_suggestions: [],
              },
              diagnostics: {
                execution_trace: [],
                used_tools: [],
                citations: [],
                research_notes: [],
                audit_issues: [],
                thinking_timeline: [
                  {
                    id: 'thinking-answering',
                    phase: 'answering',
                    title: '生成回答失败',
                    detail: 'LLM 卡片生成失败。',
                    state: 'failed',
                  },
                ],
                error: 'LLM 卡片生成失败',
              },
              context_summary: {
                has_scope: true,
                available_results: [],
                active_panel: 'agent',
                filters_digest: {},
              },
              plan: {
                steps: [],
              },
            },
          },
        },
      ])
    }
    throw new Error(`unexpected fetch ${url}`)
  }

  await ctx.submitMainAgentTurn()

  assert.equal(ctx.agentStatus, 'failed')
  assert.equal(ctx.agentThinkingExpanded, false)
  assert.equal(ctx.agentThinkingTimeline.some((item) => item.state === 'failed'), true)
  assert.equal(ctx.agentError, 'LLM 卡片生成失败')
})

test('toggleAgentSessionPinned patches persisted session and reorders list', async () => {
  const ctx = createAgentContext({
    agentSessions: [
      {
        ...ctxSessionBase('agent-a', 'A'),
        persisted: true,
        snapshotLoaded: true,
        updatedAt: '2026-04-05T00:00:00Z',
      },
      {
        ...ctxSessionBase('agent-b', 'B'),
        persisted: true,
        snapshotLoaded: true,
        updatedAt: '2026-04-05T01:00:00Z',
      },
    ],
  })

  global.fetch = async (_url, options = {}) => ({
    ok: true,
    async json() {
      const body = JSON.parse(String(options.body || '{}'))
      return {
        id: 'agent-a',
        title: 'A',
        preview: '开始一份新的区域分析',
        status: 'idle',
        is_pinned: !!body.is_pinned,
        created_at: '2026-04-05T00:00:00Z',
        updated_at: '2026-04-05T02:00:00Z',
        pinned_at: body.is_pinned ? '2026-04-05T02:00:00Z' : null,
        input: '',
        messages: [],
        cards: [],
        execution_trace: [],
        used_tools: [],
        citations: [],
        research_notes: [],
        next_suggestions: [],
        clarification_question: '',
        risk_prompt: '',
        error: '',
        risk_confirmations: [],
      }
    },
  })

  await ctx.toggleAgentSessionPinned('agent-a')

  assert.deepEqual(ctx.agentSessions.map((item) => item.id), ['agent-a', 'agent-b'])
  assert.equal(ctx.findAgentSession('agent-a').isPinned, true)
})

test('deleteAgentSession removes non-active persisted session optimistically and restores on failure', async () => {
  const ctx = createAgentContext({
    agentSessions: [
      { ...ctxSessionBase('agent-a', 'A'), persisted: true, snapshotLoaded: true, updatedAt: '2026-04-05T01:00:00Z' },
      { ...ctxSessionBase('agent-b', 'B'), persisted: true, snapshotLoaded: true, updatedAt: '2026-04-05T00:00:00Z' },
    ],
    activeAgentSessionId: 'agent-a',
  })

  let fetchCalled = false
  global.fetch = async () => {
    fetchCalled = true
    throw new Error('network down')
  }

  await ctx.deleteAgentSession('agent-b')

  assert.equal(fetchCalled, true)
  assert.deepEqual(ctx.agentSessions.map((item) => item.id), ['agent-a', 'agent-b'])
  assert.equal(ctx.activeAgentSessionId, 'agent-a')
})

test('deleteAgentSession removes active persisted session and falls back immediately to next session', async () => {
  const first = ctxSessionBase('agent-a', 'A')
  const second = ctxSessionBase('agent-b', 'B')
  const ctx = createAgentContext({
    agentSessions: [
      { ...first, persisted: true, snapshotLoaded: true, updatedAt: '2026-04-05T01:00:00Z' },
      { ...second, persisted: true, snapshotLoaded: true, updatedAt: '2026-04-05T00:00:00Z' },
    ],
    activeAgentSessionId: 'agent-a',
  })

  global.fetch = async () => ({
    ok: true,
    async json() {
      return { status: 'success', id: 'agent-a' }
    },
    get body() {
      return undefined
    },
  })

  const deleting = ctx.deleteAgentSession('agent-a')

  assert.deepEqual(ctx.agentSessions.map((item) => item.id), ['agent-b'])
  assert.equal(ctx.activeAgentSessionId, 'agent-b')

  await deleting

  assert.deepEqual(ctx.agentSessions.map((item) => item.id), ['agent-b'])
  assert.equal(ctx.activeAgentSessionId, 'agent-b')
})

test('deleteAgentSession falls back to hydrating persisted session when next session is summary only', async () => {
  const ctx = createAgentContext({
    agentSessions: [
      { ...ctxSessionBase('agent-a', 'A'), persisted: true, snapshotLoaded: true, updatedAt: '2026-04-05T01:00:00Z' },
      { ...ctxSessionBase('agent-b', 'B'), persisted: true, snapshotLoaded: false, updatedAt: '2026-04-05T00:00:00Z', preview: 'B 摘要' },
    ],
    activeAgentSessionId: 'agent-a',
  })

  let resolveDetail
  global.fetch = async (url) => {
    if (String(url).endsWith('/agent-a')) {
      return {
        ok: true,
        async json() {
          return { status: 'success', id: 'agent-a' }
        },
      }
    }
    return {
      ok: true,
      async json() {
        return new Promise((resolve) => {
          resolveDetail = resolve
        })
      },
    }
  }

  const deleting = ctx.deleteAgentSession('agent-a')

  assert.equal(ctx.activeAgentSessionId, 'agent-b')
  assert.equal(ctx.agentSessionHydrating, true)
  assert.equal(ctx.agentSessionDetailLoadingId, 'agent-b')
  await Promise.resolve()

  resolveDetail({
    id: 'agent-b',
    title: 'B',
    preview: 'B 详情',
    status: 'answered',
    is_pinned: false,
    created_at: '2026-04-05T00:00:00Z',
    updated_at: '2026-04-05T02:00:00Z',
    pinned_at: null,
    input: '',
    messages: [{ role: 'assistant', content: 'B 完整内容' }],
    cards: [],
    execution_trace: [],
    used_tools: [],
    citations: [],
    research_notes: [],
    next_suggestions: [],
    clarification_question: '',
    risk_prompt: '',
    error: '',
    risk_confirmations: [],
  })

  await deleting

  assert.equal(ctx.agentSessionHydrating, false)
  assert.deepEqual(ctx.agentMessages.map((item) => item.content), ['B 完整内容'])
})

test('deleteAgentSession restores previous active session when delete request fails', async () => {
  const ctx = createAgentContext({
    agentSessions: [
      { ...ctxSessionBase('agent-a', 'A'), persisted: true, snapshotLoaded: true, updatedAt: '2026-04-05T01:00:00Z', messages: [{ role: 'assistant', content: 'A 内容' }] },
      { ...ctxSessionBase('agent-b', 'B'), persisted: true, snapshotLoaded: true, updatedAt: '2026-04-05T00:00:00Z' },
    ],
    activeAgentSessionId: 'agent-a',
    agentMessages: [{ role: 'assistant', content: 'A 内容' }],
  })

  global.fetch = async () => {
    throw new Error('delete failed')
  }

  await ctx.deleteAgentSession('agent-a')

  assert.deepEqual(ctx.agentSessions.map((item) => item.id), ['agent-a', 'agent-b'])
  assert.equal(ctx.activeAgentSessionId, 'agent-a')
  assert.deepEqual(ctx.agentMessages.map((item) => item.content), ['A 内容'])
})

test('deleteAgentSession falls back to hidden draft when no persisted history remains', async () => {
  const ctx = createAgentContext({
    agentSessions: [
      { ...ctxSessionBase('agent-a', 'A'), persisted: true, snapshotLoaded: true },
    ],
    activeAgentSessionId: 'agent-a',
  })

  global.fetch = async () => ({
    ok: true,
    async json() {
      return { status: 'success', id: 'agent-a' }
    },
  })

  await ctx.deleteAgentSession('agent-a')

  assert.equal(ctx.getAgentHistorySessions().length, 0)
  assert.equal(ctx.agentSessions.length, 1)
  assert.equal(ctx.findAgentSession(ctx.activeAgentSessionId).persisted, false)
})

test('createAgentSummaryTab opens a new summary view instead of reusing the default summary tab', () => {
  const ctx = createAgentContext({
    agentPanelPayloads: {
      summary_pack: buildSummaryPack('这是一个以日常生活消费为主的社区级商业区，适合继续补齐业态结构证据'),
      summary_status: { status: 'ready', generated: true },
    },
    agentSummaryReadiness: {
      checked: true,
      ready: true,
      missingTasks: [],
      reused: [],
      fetched: [],
    },
  })

  const tabs = ctx.ensureAgentTabs(true)
  assert.equal(tabs.summaryTabs.length, 1)
  assert.equal(tabs.summaryTabs[0].id, 'summary-current')

  const firstId = ctx.createAgentSummaryTab()
  const secondId = ctx.createAgentSummaryTab()

  assert.notEqual(firstId, 'summary-current')
  assert.notEqual(secondId, 'summary-current')
  assert.notEqual(firstId, secondId)
  assert.equal(ctx.agentTabs.summaryTabs.length, 3)
  assert.equal(ctx.agentTabs.summaryTabs[0].id, 'summary-current')
  assert.equal(ctx.agentTabs.summaryTabs.find((item) => item.id === firstId).title, '总结')
  assert.equal(ctx.agentTabs.summaryTabs.find((item) => item.id === secondId).title, '总结')
  assert.equal(ctx.agentTabs.activeTabId, secondId)
})

test('agent report navigation opens drill-down views and returns to report home', () => {
  const ctx = createAgentContext({
    agentPanelPayloads: {
      summary_pack: buildSummaryPack('这是一个以日常生活消费为主的社区级商业区'),
      summary_status: { status: 'ready', generated: true },
    },
  })

  const homeId = ctx.getAgentReportHomeTabId()
  assert.equal(homeId, 'summary-current')
  assert.equal(ctx.isAgentSummaryTabActive(), true)
  assert.equal(ctx.getAgentWorkspaceNavTitle(), '区域报告')
  assert.equal(ctx.shouldShowAgentComposer(), false)

  const siteId = ctx.openAgentSiteSelectionFromReport()
  assert.equal(ctx.getAgentActiveTopTab().kind, 'site_selection')
  assert.equal(ctx.agentTabs.activeTabId, siteId)
  assert.equal(ctx.isAgentReportDetailView(), true)
  assert.equal(ctx.getAgentWorkspaceNavTitle(), '区域内选址')
  assert.equal(ctx.shouldShowAgentComposer(), false)

  const pptId = ctx.openAgentPptPlanningFromReport()
  assert.equal(ctx.getAgentActiveTopTab().kind, 'analysis')
  assert.equal(ctx.agentTabs.activeTabId, pptId)
  assert.equal(ctx.isAgentPptPlanningTabActive(), true)
  assert.equal(ctx.isAgentReportDetailView(), true)
  assert.equal(ctx.getAgentWorkspaceNavTitle(), '分析')
  assert.equal(ctx.getAgentWorkspaceNavSubtitle(), '围绕已选来源做快速或深度分析，也可继续生成展示材料')
  assert.equal(ctx.shouldShowAgentComposer(), true)
  assert.equal(ctx.shouldShowAgentGlobalComposer(), false)
  assert.equal(ctx.openAgentPptPlanningFromReport(), pptId)

  ctx.returnToAgentReportHome()
  assert.equal(ctx.isAgentSummaryTabActive(), true)
  assert.equal(ctx.agentTabs.activeTabId, homeId)

  const iterationId = ctx.openAgentIterationChangeFromReport({ autoload: false })
  assert.equal(ctx.getAgentActiveTopTab().kind, 'iteration_change')
  assert.equal(ctx.agentTabs.activeTabId, iterationId)
  assert.equal(ctx.getAgentWorkspaceNavTitle(), '多年变化')
  assert.equal(ctx.shouldShowAgentComposer(), false)

  ctx.openAgentFollowupFromSummary('为什么这样判断？')
  assert.equal(ctx.getAgentActiveTopTab().kind, 'followup')
  assert.equal(ctx.getAgentWorkspaceNavTitle(), '追问解释')
  assert.equal(ctx.shouldShowAgentComposer(), false)

  assert.equal(ctx.getAgentWorkspaceNavTitle(), '追问解释')
  assert.equal(ctx.shouldShowAgentComposer(), false)
})

test('ppt planning keeps center composer turns in the ppt tab', () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()

  const pptId = ctx.openAgentPptPlanningFromReport()
  ctx.agentInput = '继续分析当前资料'

  const turnContext = ctx.buildTurnContext()

  assert.equal(turnContext.panelKind, 'analysis')
  assert.equal(ctx.agentTabs.activeTabId, pptId)
  assert.equal(ctx.getAgentActiveTopTab().kind, 'analysis')
  assert.deepEqual(
    ctx.agentTabs.followupTabs.map((item) => item.title),
    [],
  )
  assert.deepEqual(
    turnContext.nextMessages.map((item) => item.content),
    ['继续分析当前资料'],
  )
})

test('composer outside analysis tab opens analysis quick answer instead of main loop', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  assert.notEqual(ctx.getAgentActiveTopTab().kind, 'analysis')
  ctx.getAgentPptPlanningStateWithSystemSources = () => ctx.getAgentActivePptPlanningState()
  ctx.refreshAgentActivePptPlanningSources = () => {}
  ctx.refreshAgentActivePptPlanningDataSources = () => {}
  const originalOpenPpt = ctx.openAgentPptPlanningFromReport.bind(ctx)
  ctx.openAgentPptPlanningFromReport = (options = {}) => {
    const tabId = originalOpenPpt(options)
    ctx.updateAgentActivePptPlanningState({
      ...ctx.getAgentActivePptPlanningState(),
      sources: [{
        id: 'current:scope',
        type: 'data',
        title: '当前等时圈范围',
        status: 'ready',
        selected: true,
        meta: {
          sourceKind: 'system',
          aiPayload: {
            version: 'ppt_ai_input_block_v1',
            source_id: 'current:scope',
            title: '当前等时圈范围',
            included: ['scope', 'evidence'],
            scope: { has_polygon: true },
            evidence: [{ title: '范围', text: '当前区域' }],
            counts: { scope: 1, evidence: 1 },
          },
        },
      }],
    })
    return tabId
  }

  let submitMainAgentTurnCalled = false
  ctx.submitMainAgentTurn = async () => {
    submitMainAgentTurnCalled = true
  }
  const originalFetch = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, body: JSON.parse(options.body || '{}') })
    return {
      ok: true,
      async json() {
        return { status: 'success', answer: '范围证据可用于 PPT。', evidence: [], citations: [], warnings: [] }
      },
    }
  }

  try {
    ctx.agentInput = '这些资料能说明什么？'
    await ctx.submitAgentComposer()
  } finally {
    globalThis.fetch = originalFetch
  }

  assert.equal(submitMainAgentTurnCalled, false)
  assert.equal(ctx.getAgentActiveTopTab().kind, 'analysis')
  assert.deepEqual(ctx.agentTabs.followupTabs, [])
  assert.equal(calls.some((item) => String(item.url).includes('/api/v1/analysis/agent/context-ask')), true)
  assert.deepEqual(ctx.agentMessages.map((item) => item.content), ['这些资料能说明什么？', '范围证据可用于 PPT。'])
})

test('ppt planning quick composer uses lightweight ask without agent tool turn', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  const pptId = ctx.openAgentPptPlanningFromReport()
  ctx.updateAgentActivePptPlanningState({
    ...ctx.getAgentActivePptPlanningState(),
    sources: [{
      id: 'current:scope',
      type: 'data',
      title: '当前等时圈范围',
      status: 'ready',
      selected: true,
      meta: {
        sourceKind: 'system',
        aiPayload: {
          version: 'ppt_ai_input_block_v1',
          source_id: 'current:scope',
          title: '当前等时圈范围',
          included: ['scope', 'evidence'],
          scope: { has_polygon: true },
          evidence: [{ title: '范围', text: '当前区域' }],
          counts: { scope: 1, evidence: 1 },
        },
      },
    }],
  })
  let submitMainAgentTurnCalled = false
  ctx.submitMainAgentTurn = async () => {
    submitMainAgentTurnCalled = true
  }
  const calls = []
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, body: JSON.parse(options.body || '{}') })
    return {
      ok: true,
      async json() {
        return { status: 'success', answer: '范围证据可用于 PPT。', evidence: [], citations: [], warnings: [] }
      },
    }
  }

  try {
    ctx.agentInput = '这些资料能说明什么？'
    await ctx.submitAgentComposer()
  } finally {
    globalThis.fetch = originalFetch
  }

  assert.equal(submitMainAgentTurnCalled, false)
  assert.equal(ctx.agentTabs.activeTabId, pptId)
  assert.equal(ctx.getAgentActiveTopTab().kind, 'analysis')
  assert.deepEqual(ctx.agentTabs.followupTabs, [])
  assert.equal(calls[0].url, '/api/v1/analysis/agent/context-ask')
  assert.equal(calls[0].body.require_ai, true)
  assert.equal(calls[0].body.target.type, 'analysis_sources')
  assert.equal(calls[0].body.target.source, 'analysis')
  assert.deepEqual(ctx.agentMessages.map((item) => item.content), ['这些资料能说明什么？', '范围证据可用于 PPT。'])
  assert.equal(ctx.agentMessages.some((item) => item.process), false)
  assert.deepEqual(ctx.agentThinkingTimeline, [])
  assert.deepEqual(ctx.agentExecutionTrace, [])
  assert.deepEqual(ctx.agentPlan.steps, [])
})

test('analysis deep composer calls main agent loop', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.openAgentPptPlanningFromReport()
  let seenOptions = null
  ctx.submitMainAgentTurn = async (options = {}) => {
    seenOptions = options
  }

  ctx.agentInput = '深度检查这些资料'
  ctx.selectAgentComposerMode('deep')
  await ctx.submitAgentComposer()

  assert.equal(seenOptions.panelKind, 'analysis')
  assert.equal(seenOptions.mode, 'deep')
})

test('analysis deep main-loop skips visual snapshot capture', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.openAgentPptPlanningFromReport()
  ctx.updateAgentActivePptPlanningState({
    ...ctx.getAgentActivePptPlanningState(),
    sources: [{
      id: 'document:doc-1',
      type: 'document',
      title: '项目文档',
      status: 'ready',
      selected: true,
      meta: {
        sourceKind: 'document',
        aiPayload: {
          version: 'ppt_ai_input_block_v1',
          source_id: 'document:doc-1',
          title: '项目文档',
          source_kind: 'document',
          included: ['evidence'],
          evidence_nodes: [{
            id: 'document:doc-1:evidence:1',
            source_id: 'document:doc-1',
            title: '更新目标',
            content: '围绕城市更新目标组织空间证据。',
          }],
          counts: { evidence: 1 },
        },
      },
    }],
  })
  ctx.agentInput = '深度检查这些资料'
  ctx.selectAgentComposerMode('deep')
  let captureCount = 0
  ctx.captureAgentVisualSnapshots = async () => {
    captureCount += 1
    return [{
      snapshot_id: 'visual-should-not-send',
      kind: 'overview_map',
      data_url: 'data:image/jpeg;base64,abc',
    }]
  }
  let requestBody = null
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (url, options = {}) => {
    if (getAgentSessionDetailId(url)) return createAgentSessionDetailResponse(ctx, url)
    assert.equal(url, '/api/v1/analysis/agent/main-loop/stream')
    requestBody = JSON.parse(String(options.body || '{}'))
    return createSseResponse([{
      type: 'final',
      payload: {
        response: {
          status: 'answered',
          stage: 'answered',
          output: { answer: '已完成', cards: [], next_suggestions: [], panel_payloads: {} },
          diagnostics: { execution_trace: [], used_tools: [], citations: [], research_notes: [], audit_issues: [], thinking_timeline: [], error: '' },
          context_summary: {},
          plan: {},
        },
      },
    }])
  }

  try {
    await ctx.submitAgentComposer()
  } finally {
    globalThis.fetch = originalFetch
  }

  assert.equal(captureCount, 0)
  assert.deepEqual(requestBody.visual_snapshots, [])
  assert.equal(Object.prototype.hasOwnProperty.call(requestBody, 'thinking_mode'), false)
  assert.equal(requestBody.selected_sources_context.sources.some((item) => item.source_id === 'document:doc-1'), true)
})

test('ppt planning quick composer blocks when no selected deliverable source exists', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.openAgentPptPlanningFromReport()
  ctx.getAgentPptPlanningStateWithSystemSources = () => ctx.getAgentActivePptPlanningState()
  ctx.updateAgentActivePptPlanningState({
    ...ctx.getAgentActivePptPlanningState(),
    selectedSlideId: '',
    sources: [{
      id: 'empty-source',
      type: 'data',
      title: '空来源',
      status: 'ready',
      selected: true,
      meta: {
        aiPayload: {
          version: 'ppt_ai_input_block_v1',
          source_id: 'empty-source',
          included: [],
        },
      },
    }],
  })
  const originalFetch = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url) => {
    calls.push(url)
    throw new Error('should_not_fetch')
  }

  try {
    ctx.agentInput = '能回答吗？'
    await ctx.submitAgentComposer()
  } finally {
    globalThis.fetch = originalFetch
  }

  assert.equal(calls.some((url) => String(url).includes('/api/v1/analysis/agent/context-ask')), false)
  assert.deepEqual(ctx.agentMessages.map((item) => item.content), ['能回答吗？', '请先勾选可用于 AI 的来源'])
  assert.deepEqual(ctx.agentExecutionTrace, [])
  assert.deepEqual(ctx.agentPlan.steps, [])
})

test('summary session history persists tourism cross analysis in summary pack and tabs', () => {
  const tourismCrossAnalysis = {
    title: '文旅交叉策划分析',
    content: '该地块适合以年轻客群为核心，以餐饮业态为底盘，打造青年社交型城市文旅消费场景。',
  }
  const summaryPack = buildSummaryPack('当前范围总结')
  summaryPack.tourism_cross_analysis = tourismCrossAnalysis
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.agentPanelPayloads = {
    summary_pack: summaryPack,
    summary_status: { status: 'ready', generated: true, title: '区域总结' },
  }

  ctx.commitAgentSummaryPayloadsToActiveTab()
  const activeSummaryPayloads = ctx.getAgentActiveSummaryPanelPayloads()
  const uiState = ctx.buildAgentTabsUiState()
  const requestPayload = ctx.buildAgentSessionRequestPayload()

  assert.equal(ctx.getAgentSummaryTourismCrossAnalysis().content, tourismCrossAnalysis.content)
  assert.equal(ctx.getAgentActiveTopTab().content.tourism_cross_analysis.content, tourismCrossAnalysis.content)
  assert.equal(activeSummaryPayloads.summary_pack.tourism_cross_analysis.content, tourismCrossAnalysis.content)
  assert.equal(uiState.summary_tabs[0].content.tourism_cross_analysis.content, tourismCrossAnalysis.content)
  assert.equal(uiState.summary_tabs[0].panel_payloads.summary_pack.tourism_cross_analysis.content, tourismCrossAnalysis.content)
  assert.equal(requestPayload.output.panel_payloads.summary_pack.tourism_cross_analysis.content, tourismCrossAnalysis.content)
  assert.equal(requestPayload.output.panel_payloads.agent_tabs.summary_tabs[0].content.tourism_cross_analysis.content, tourismCrossAnalysis.content)
})

test('summary stream completion fills tourism content from payload', async () => {
  const tourismCrossAnalysis = {
    title: '文旅交叉策划分析',
    content: '一、综合判断\n适合做复合文旅消费场景。\n五、人口 x POI x 夜光交叉诊断\n三类信号基本匹配。\n九、策划结论\n该地块适合以年轻客群为核心客群。',
  }
  const summaryPack = buildSummaryPack('当前范围总结')
  summaryPack.tourism_cross_analysis = tourismCrossAnalysis
  const ctx = createAgentContext({
    agentSummaryReadiness: {
      checked: true,
      ready: true,
      missingTasks: [],
      reused: [],
      fetched: [],
    },
  })
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentReportSession()
  ctx.refreshAgentSummaryReadiness = async () => {}
  ctx.canGenerateSummaryAfterTasks = () => true

  global.fetch = async (url) => {
    assert.equal(url, '/api/v1/analysis/agent/summary/generate')
    return createSseResponse([
      { type: 'section_start', payload: { key: 'tourism_cross_analysis', title: tourismCrossAnalysis.title } },
      { type: 'section_complete', payload: { key: 'tourism_cross_analysis', status: 'ready', payload: tourismCrossAnalysis } },
      {
        type: 'final',
        payload: {
          data_readiness: { checked: true, ready: true, missing_tasks: [], reused: [], fetched: [] },
          panel_payloads: { summary_status: { status: 'ready', generated: true } },
          summary_pack: summaryPack,
          warnings: [],
          error: '',
          phases: ['completed'],
        },
      },
    ])
  }

  await ctx.generateAgentSummaryPanel()

  assert.equal(ctx.agentSummaryStreamSections.tourism_cross_analysis.content, tourismCrossAnalysis.content)
  assert.equal(ctx.getAgentSummaryTourismCrossAnalysis().content, tourismCrossAnalysis.content)
})

test('getAgentSummaryGateProgressText only shows readiness checking while loading', () => {
  const ctx = createAgentContext()
  ctx.agentSummaryLoading = false
  ctx.agentSummaryGenerating = false
  ctx.agentSummaryProgressPhase = ''
  ctx.agentSummaryReadiness = {
    checked: true,
    ready: false,
    missingTasks: ['poi_fetch', 'population'],
    reused: [],
    fetched: [],
  }

  assert.equal(ctx.getAgentSummaryGateProgressText(), '已完成数据检查，还缺 2 项')

  ctx.agentSummaryLoading = true
  assert.equal(ctx.getAgentSummaryGateProgressText(), '正在检查数据就绪度…')
})

test('getSummaryTaskKeysToFill skips tasks that are already reusable', () => {
  const ctx = createAgentContext({
    agentSummaryReadiness: {
      checked: true,
      ready: false,
      missingTasks: ['h3', 'nightlight', 'road_syntax'],
      reused: ['nightlight'],
      fetched: [],
    },
  })
  ctx.summaryTaskHasReusableResult = (taskKey) => taskKey === 'nightlight'

  assert.deepEqual(ctx.getSummaryTaskKeysToFill(), ['poi_h3_grid', 'road_syntax'])
})

test('summary poi fetch task uses one analysis year and marks fetched years', () => {
  const ctx = createAgentContext({
    poiYearSelections: [2020, 2022, 2024],
    poiYearSource: '2024',
    resultPoiYear: 2024,
    poiResultsByYear: [{ year: 2020, count: 1 }, { year: 2024, count: 3 }],
    resultDataSource: 'history',
    poiDataSource: 'history',
  })
  const task = ctx.createSummaryTaskBoardTask({ key: 'poi_fetch', label: 'POI 抓取' })

  assert.equal(ctx.getSummaryTaskPoiYearLabel(), '2024')
  assert.equal(ctx.getSummaryTaskPoiSourceLabel(), 'history')
  assert.deepEqual(ctx.captureSummaryTaskParams('poi_fetch'), {
    source: 'history',
    year: 2024,
    years: [2024],
  })
  assert.match(ctx.getSummaryTaskPoiYearOptions().find((item) => Number(item.value) === 2024).label, /已抓取/)
  assert.doesNotMatch(ctx.getSummaryTaskPoiYearOptions().find((item) => Number(item.value) === 2022).label, /已抓取/)
  assert.equal(task.label, 'POI 抓取')
})

test('summary poi grid year switches active poi details for h3 input', async () => {
  const ctx = createAgentContext({
    poiYearSelections: [2020, 2022, 2024],
    poiYearSource: '2020',
    resultPoiYear: 2020,
    poiResultsByYear: [
      { year: 2020, source: 'local', pois: [{ id: 'poi-2020' }] },
      { year: 2024, source: 'local', pois: [{ id: 'poi-2024' }] },
    ],
  })
  let rebuilt = []
  ctx.deduplicateFetchedPois = (pois) => pois
  ctx.rebuildPoiRuntimeSystem = (pois) => { rebuilt = pois }
  ctx.updatePoiCharts = () => {}
  ctx.poiYearSource = '2024'

  await ctx.onSummaryTaskPoiGridYearChange()

  assert.equal(ctx.resultPoiYear, 2024)
  assert.equal(ctx.allPoisDetails[0].id, 'poi-2024')
  assert.equal(rebuilt[0].id, 'poi-2024')
  assert.deepEqual(ctx.captureSummaryTaskParams('poi_raster_grid').poi_years, [2024])
  assert.equal(ctx.captureSummaryTaskParams('poi_h3_grid').poi_year, 2024)
})

test('analysis task param bundles drive summary task params and cache keys', () => {
  const ctx = createAgentContext({
    poiGridType: 'raster',
    poiDataSource: 'local',
    resultDataSource: 'local',
    poiYearSource: '2024',
    h3GridResolution: 9,
    h3NeighborRing: 2,
    h3GridIncludeMode: 'intersects',
    h3GridMinOverlapRatio: 0.35,
  })
  const rasterBundle = buildAnalysisTaskParamBundle(ctx, 'poi_raster_grid')
  const h3Bundle = buildAnalysisTaskParamBundle(ctx, 'poi_h3_grid')
  assert.equal(rasterBundle.task_key, 'poi_raster_grid')
  assert.equal(rasterBundle.params.grid_type, 'shared_raster')
  assert.equal(rasterBundle.params.cell_id_source, 'population_nightlight_shared_cell_id')
  assert.match(rasterBundle.evidence_params.description, /POI 共享栅格/)
  assert.match(rasterBundle.evidence_params.description, /同一 cell_id/)
  assert.match(rasterBundle.display_label, /POI 共享栅格/)
  assert.equal(h3Bundle.task_key, 'poi_h3_grid')
  assert.equal(h3Bundle.params.grid_type, 'hex')
  assert.equal(h3Bundle.params.h3_resolution, 9)
  assert.equal(h3Bundle.params.min_overlap_ratio, 0.35)
  assert.match(h3Bundle.evidence_params.description, /POI H3 六边形网格/)
  assert.match(h3Bundle.evidence_params.description, /POI 供给和密度结构/)
  assert.match(h3Bundle.display_label, /POI H3 res=9/)
  assert.deepEqual(ctx.captureSummaryTaskParams('poi_raster_grid'), rasterBundle.params)
  assert.deepEqual(ctx.captureSummaryTaskParams('poi_h3_grid'), h3Bundle.params)

  const firstSnapshot = ctx.stringifySummaryTaskParams(h3Bundle.params)
  ctx.h3GridResolution = 10
  const secondSnapshot = ctx.stringifySummaryTaskParams(ctx.captureSummaryTaskParams('poi_h3_grid'))
  assert.notEqual(firstSnapshot, secondSnapshot)
})

test('summary poi grid fill computes raster grid and h3 separately', async () => {
  const calls = []
  const ctx = createAgentContext({
    poiGridType: 'raster',
    h3AnalysisSummary: { grid_count: 8 },
    h3AnalysisGridFeatures: [{ type: 'Feature', properties: { h3_id: '8928308280fffff' } }],
    h3GridCount: 8,
    agentSummaryReadiness: {
      checked: true,
      ready: false,
      missingTasks: ['poi_grid'],
      reused: [],
      fetched: [],
    },
  })
  ctx.ensurePoiSharedGridAnalysis = async (force = false) => {
    calls.push({ task: 'raster', force })
    ctx.poiGridSummary = { grid_count: 2, active_cell_count: 1 }
    ctx.poiGridFeatures = [{ type: 'Feature', properties: { cell_id: 'cell-1', poi_count: 3 } }]
  }
  ctx.computeH3Analysis = async () => {
    calls.push({ task: 'h3' })
    ctx.h3AnalysisSummary = { grid_count: 8 }
    ctx.h3AnalysisGridFeatures = [{ type: 'Feature', properties: { h3_id: '8928308280fffff' } }]
    ctx.h3GridCount = 8
  }

  assert.equal(getAnalysisTaskDefinition('poi_raster_grid').hasResult(ctx), false)
  assert.equal(getAnalysisTaskDefinition('poi_h3_grid').hasResult(ctx), true)
  assert.deepEqual(ctx.getSummaryTaskKeysToFill(), ['poi_raster_grid'])

  await ctx.runSummaryTask('poi_raster_grid')

  assert.deepEqual(calls, [{ task: 'raster', force: true }])
  assert.equal(ctx.getSummaryTaskByKey('poi_raster_grid').status, 'completed')
  assert.equal(getAnalysisTaskDefinition('poi_raster_grid').hasResult(ctx), true)
})

test('summary poi grid split reuses raster and h3 independently', () => {
  const rasterOnly = createAgentContext({
    poiGridSummary: { grid_count: 2, active_cell_count: 1 },
    poiGridFeatures: [{ type: 'Feature', properties: { cell_id: 'r0_c0' } }],
    agentSummaryReadiness: {
      checked: true,
      ready: false,
      missingTasks: ['poi_grid'],
      reused: [],
      fetched: [],
    },
  })
  assert.equal(getAnalysisTaskDefinition('poi_raster_grid').hasResult(rasterOnly), true)
  assert.equal(getAnalysisTaskDefinition('poi_h3_grid').hasResult(rasterOnly), false)
  assert.deepEqual(rasterOnly.getSummaryTaskKeysToFill(), ['poi_h3_grid'])

  const h3Only = createAgentContext({
    h3AnalysisSummary: { grid_count: 8, poi_count: 10 },
    h3AnalysisGridFeatures: [{ type: 'Feature', properties: { h3_id: '8928308280fffff' } }],
    h3GridCount: 8,
    agentSummaryReadiness: {
      checked: true,
      ready: false,
      missingTasks: ['poi_grid'],
      reused: [],
      fetched: [],
    },
  })
  assert.equal(getAnalysisTaskDefinition('poi_raster_grid').hasResult(h3Only), false)
  assert.equal(getAnalysisTaskDefinition('poi_h3_grid').hasResult(h3Only), true)
  assert.deepEqual(h3Only.getSummaryTaskKeysToFill(), ['poi_raster_grid'])
})

test('poi iteration secondary nav starts at data and gates analysis until ready', () => {
  const ctx = createAgentContext({
    currentHistoryRecordId: '',
    currentHistoryAvailablePoiYears: [],
    agentPanelPayloads: {
      iteration_change: {
        poi: { status: 'needs_data', yearly_grid_evidence: { items: [] } },
      },
    },
  })

  assert.equal(ctx.getAgentIterationSecondaryView('poi'), 'data')
  assert.deepEqual(ctx.getAgentIterationSecondaryNavItems('poi').map((item) => item.key), ['data'])
  ctx.setAgentIterationSecondaryView('ai', 'poi')
  assert.equal(ctx.getAgentIterationSecondaryView('poi'), 'data')

  ctx.currentHistoryRecordId = 'history-1'
  ctx.currentHistoryAvailablePoiYears = [2023, 2024, 2025]
  ctx.commitAgentIterationPoiPayload({
    status: 'ready',
    yearly_grid_evidence: {
      evidence_version: 'poi_iteration_yearly_grid_evidence_v1',
      years: [2023, 2024, 2025],
      grid_scope: 'poi_iteration_h3_per_year',
      grid_type: 'h3',
      latest_year: 2025,
      latest_h3_evidence: { evidence_version: 'poi_h3_evidence_v1' },
      items: [
        { year: 2023, status: 'ready', h3_evidence: {} },
        { year: 2024, status: 'ready', h3_evidence: {} },
        { year: 2025, status: 'ready', h3_evidence: {} },
      ],
      h3_items: [
        { year: 2023, status: 'ready', h3_evidence: {} },
        { year: 2024, status: 'ready', h3_evidence: {} },
        { year: 2025, status: 'ready', h3_evidence: {} },
      ],
      raster_items: [
        { year: 2023, status: 'ready', raster_evidence: {} },
        { year: 2024, status: 'ready', raster_evidence: {} },
        { year: 2025, status: 'ready', raster_evidence: {} },
      ],
    },
  })
  const readyItems = ctx.getAgentIterationSecondaryNavItems('poi')
  assert.deepEqual(readyItems.map((item) => item.key), ['data', 'ai', 'metrics', 'trend', 'space', 'detail'])
  assert.equal(readyItems.find((item) => item.key === 'ai').label, '业态基础分析')
})

test('poi iteration yearly grid evidence stores h3 per year without raster', async () => {
  const calls = []
  const ctx = createAgentContext({
    currentHistoryRecordId: 'history-1',
    currentHistoryAvailablePoiYears: [2023, 2024],
    h3GridResolution: 9,
    agentPanelPayloads: {
      iteration_change: {
        poi: { yearly_grid_evidence: { evidence_version: 'poi_iteration_yearly_grid_evidence_v1', items: [] } },
      },
    },
  })
  ctx.selectAgentPoiYearForGrid = async (year) => { calls.push({ task: 'select', year }) }
  ctx.selectAllH3PoiFilters = () => { calls.push({ task: 'h3_filters' }) }
  ctx.computeH3Analysis = async () => {
    calls.push({ task: 'h3' })
    const selectedYear = calls.filter((call) => call.task === 'select').slice(-1)[0]?.year
    ctx.h3AnalysisProgress = { run_id: `run-${selectedYear}`, stage: 'completed', step: 7, total: 7, elapsed_sec: 5, extra: { grid_count: 1, poi_count: 1 } }
    return { progress: ctx.h3AnalysisProgress }
  }
  ctx.buildAgentPoiH3Evidence = () => ({
    evidence_version: 'poi_h3_evidence_v1',
    params: { h3_resolution: ctx.h3GridResolution },
    cells: [{ h3_id: 'h3-1' }],
  })

  const evidence = await ctx.buildAgentPoiYearlyGridEvidence([2023, 2024])

  assert.equal(evidence.grid_scope, 'poi_iteration_h3_per_year')
  assert.equal(evidence.grid_type, 'h3')
  assert.deepEqual(calls.map((call) => call.task), ['select', 'h3_filters', 'h3', 'select', 'h3_filters', 'h3'])
  assert.equal(evidence.items.length, 2)
  assert.equal(evidence.h3_items.length, 2)
  assert.equal(evidence.items.every((item) => item.status === 'ready'), true)
  assert.equal(evidence.items[0].run_id, 'run-2023')
  assert.equal(evidence.items[0].progress.stage, 'completed')
  assert.equal('raster_items' in evidence, false)
})

test('poi iteration h3 year rows expose progress stage and detail labels', async () => {
  const ctx = createAgentContext({
    h3GridResolution: 10,
    currentHistoryAvailablePoiYears: [2020, 2022, 2024],
    agentPanelPayloads: {
      iteration_change: {
        poi: {
          yearly_grid_evidence: {
            evidence_version: 'poi_iteration_yearly_grid_evidence_v1',
            years: [2020, 2022, 2024],
            grid_scope: 'poi_iteration_h3_per_year',
            items: [
              { year: 2020, status: 'running', run_id: 'run-2020', progress: { stage: 'aggregate_poi', step: 2, total: 7, elapsed_sec: 6, extra: { grid_count: 500, poi_count: 3179 } }, h3_evidence: {} },
              { year: 2022, status: 'queued', h3_evidence: {} },
              { year: 2024, status: 'ready', h3_evidence: { summary: { grid_count: 420, poi_count: 2500 }, params: { h3_resolution: 10 } } },
            ],
          },
        },
      },
    },
  })

  const rows = ctx.getAgentIterationPoiGridYearRows()
  assert.equal(rows[0].stageLabel, '聚合 POI 中')
  assert.match(rows[0].detailLabel, /2\/7/)
  assert.match(rows[0].detailLabel, /500格/)
  assert.match(rows[0].detailLabel, /3179POI/)
  assert.equal(rows[2].stageLabel, '已完成')
  assert.match(rows[2].detailLabel, /420格/)
})

test('poi iteration grid completion clears stale missing notice', async () => {
  const ctx = createAgentContext({
    currentHistoryRecordId: 'history-1',
    currentHistoryAvailablePoiYears: [2023, 2024],
    agentPanelPayloads: {
      iteration_change: {
        poi: {
          status: 'needs_data',
          notice: '多年 POI 分析还缺 POI / 网格分析，请先补齐。',
          error: '旧错误',
          yearly_grid_evidence: { evidence_version: 'poi_iteration_yearly_grid_evidence_v1', items: [] },
        },
      },
    },
  })
  ctx.selectAgentPoiYearForGrid = async () => {}
  ctx.selectAllH3PoiFilters = () => {}
  ctx.computeH3Analysis = async () => {}
  ctx.buildAgentPoiH3Evidence = () => ({
    evidence_version: 'poi_h3_evidence_v1',
    params: { h3_resolution: 10 },
    summary: { grid_count: 1 },
    cells: [{ h3_id: 'h3-1', poi_count: 3 }],
  })

  await ctx.runAgentIterationPoiTask('poi_h3_grid')

  assert.equal(ctx.getAgentIterationPoiReadiness().ready, true)
  assert.equal(ctx.getAgentIterationPoiTaskKeysToFill().length, 0)
  assert.equal(ctx.getAgentIterationPoiPayload().notice, '')
  assert.equal(ctx.getAgentIterationPoiPayload().error, '')
  assert.equal(ctx.getAgentIterationPoiPrimaryActionLabel(), '重新抓取/重算')
})

test('poi iteration primary action recomputes all poi data when already ready', async () => {
  const calls = []
  const ctx = createAgentContext()
  ctx.getAgentIterationPoiTaskBoardTasks = () => []
  ctx.getAgentIterationPoiTaskKeysToFill = () => []
  ctx.runAgentIterationPoiTask = async (key) => {
    calls.push(key)
  }
  ctx.ensureAgentIterationPoi = async (force) => {
    calls.push(`ensure:${force}`)
    return { status: 'ready' }
  }
  ctx.setAgentIterationSecondaryView = (view, kind) => {
    calls.push(`nav:${kind}:${view}`)
  }

  assert.equal(ctx.getAgentIterationPoiPrimaryActionLabel(), '重新抓取/重算')
  await ctx.runAgentIterationPoiPrimaryAction()

  assert.deepEqual(calls, [
    'poi_fetch',
    'poi_h3_grid',
    'ensure:true',
    'nav:poi:ai',
  ])
})

test('summary primary action reuses available results instead of full recompute', async () => {
  const calls = []
  const ctx = createAgentContext({
    agentSummaryReadiness: {
      checked: true,
      ready: false,
      missingTasks: ['poi_fetch'],
      reused: [],
      fetched: [],
    },
  })
  ctx.canGenerateSummaryAfterTasks = () => false
  ctx.getSummaryTaskKeysToFill = () => []
  ctx.startSummaryParallelFill = async () => {
    calls.push('parallel_fill')
  }
  ctx.generateAgentSummaryPanel = async () => {
    calls.push('generate')
  }

  assert.equal(ctx.getAgentSummaryPrimaryActionLabel(), '复用已有结果')
  await ctx.runAgentSummaryPrimaryAction()

  assert.deepEqual(calls, ['parallel_fill'])
})

test('getAgentSummaryGeneratingSections maps task progress into staged skeleton cards', () => {
  const ctx = createAgentContext({
    agentSummaryGenerating: true,
    agentSummaryProgressPhase: 'fetch_missing',
    summaryTaskBoard: {
      runState: 'running',
      tasks: [
        { key: 'poi_fetch', label: 'POI 抓取', status: 'completed' },
        { key: 'population', label: '人口结构分析', status: 'completed' },
        { key: 'nightlight', label: '夜光分析', status: 'running' },
        { key: 'poi_h3_grid', label: 'POI H3 六边形网格计算', status: 'running' },
        { key: 'road_syntax', label: '路网与可达性分析', status: 'pending' },
      ],
    },
  })

  const sections = ctx.getAgentSummaryGeneratingSections()

  assert.equal(sections.find((item) => item.key === 'tags').status, 'active')
  assert.equal(sections.find((item) => item.key === 'user_profile').status, 'ready')
  assert.equal(sections.find((item) => item.key === 'behavior').status, 'active')
  assert.match(sections.find((item) => item.key === 'spatial_structure').detail, /等待|正在/)
  assert.equal(sections.find((item) => item.key === 'poi_structure').status, 'active')
  assert.equal(sections.find((item) => item.key === 'consumption_vitality').status, 'active')
  assert.match(sections.find((item) => item.key === 'business_support').detail, /等待|正在/)

  ctx.agentSummaryProgressPhase = 'analysis_started'
  assert.equal(ctx.getAgentSummaryGeneratingSections().find((item) => item.key === 'headline').status, 'active')
  assert.equal(ctx.getAgentSummaryGeneratingSections().find((item) => item.key === 'spatial_structure').status, 'active')
})

test('createAgentIterationChangeTab opens independent iteration tab', () => {
  const ctx = createAgentContext()

  const tabId = ctx.createAgentIterationChangeTab({ autoload: false })

  assert.ok(tabId.startsWith('iteration-change-'))
  assert.equal(ctx.getAgentActiveTopTab().kind, 'iteration_change')
  assert.equal(ctx.isAgentIterationChangeTabActive(), true)
  assert.equal(ctx.agentIterationActiveKind, 'poi')
  assert.equal(ctx.getAgentTopTabs().find((item) => item.id === tabId).title, '多年迭代变化')
})

test('ensureAgentIterationNightlight loads three snapshots without mutating nightlight panel state', async () => {
  const ctx = createAgentContext({
    nightlightSelectedYear: 2025,
    nightlightOverview: { summary: { total_radiance: 99 } },
    nightlightLayer: { view: 'radiance' },
    nightlightRaster: { image_url: 'old' },
  })
  ctx.ensureAgentIterationPoiAreaHeatmapSnapshots = async (payload) => payload
  ctx.createAgentIterationChangeTab({ autoload: false })
  const calls = []
  global.fetch = async (url, options = {}) => {
    calls.push({ url, body: options.body ? JSON.parse(options.body) : null })
    if (url === '/api/v1/analysis/timeseries/meta') {
      return { ok: true, json: async () => ({ nightlight_years: [2022, 2023, 2024, 2025] }) }
    }
    if (url === '/api/v1/analysis/timeseries/nightlight') {
      return {
        ok: true,
        json: async () => ({
          series: [
            { year: 2023, total_radiance: 10, mean_radiance: 1, p90_radiance: 2, lit_pixel_ratio: 0.2 },
            { year: 2024, total_radiance: 20, mean_radiance: 2, p90_radiance: 3, lit_pixel_ratio: 0.3 },
            { year: 2025, total_radiance: 30, mean_radiance: 3, p90_radiance: 4, lit_pixel_ratio: 0.4 },
          ],
          layer: { summary: { class_counts: { hotspot_emerging: 2, hotspot_stable: 1, hotspot_faded: 0, stable: 5 } } },
          insights: [],
        }),
      }
    }
    if (url === '/api/v1/analysis/nightlight/overview') {
      const year = JSON.parse(options.body).year
      return {
        ok: true,
        json: async () => ({
          scope_id: `scope-${year}`,
          summary: { total_radiance: year, mean_radiance: 1, p90_radiance: 2, lit_pixel_ratio: 0.25 },
        }),
      }
    }
    if (url === '/api/v1/analysis/nightlight/grid') {
      const year = JSON.parse(options.body).year
      return {
        ok: true,
        json: async () => ({
          scope_id: `scope-${year}`,
          features: [{
            type: 'Feature',
            properties: { cell_id: `cell-${year}` },
            geometry: { type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]] },
          }],
        }),
      }
    }
    if (url === '/api/v1/analysis/nightlight/layer') {
      const year = JSON.parse(options.body).year
      return {
        ok: true,
        json: async () => ({
          scope_id: `scope-${year}`,
          cells: [{ cell_id: `cell-${year}`, fill_color: '#facc15', fill_opacity: 0.7, stroke_color: '#ffffff' }],
          legend: {},
        }),
      }
    }
    if (url === '/api/v1/analysis/nightlight/raster') {
      const year = JSON.parse(options.body).year
      return {
        ok: true,
        json: async () => ({
          scope_id: `scope-${year}`,
          image_url: `data:image/png;base64,${year}`,
          bounds_gcj02: [[0, 0], [1, 1]],
          legend: {},
          summary: { total_radiance: year, mean_radiance: 1, p90_radiance: 2, lit_pixel_ratio: 0.25 },
        }),
      }
    }
    if (url === '/api/v1/analysis/agent/iteration/nightlight/interpret') {
      const body = JSON.parse(options.body)
      assert.deepEqual(body.evidence.years, [2023, 2024, 2025])
      assert.equal(body.evidence.snapshot_refs.some((item) => item.image_url), false)
      return {
        ok: true,
        json: async () => ({
          status: 'ready',
          ai_analysis: {
            headline: '热点增强',
            trend_summary: '总辐亮连续增强',
            hotspot_migration: '新增热点增加',
            risk_or_opportunity: '夜间商业机会增强',
          },
        }),
      }
    }
    throw new Error(`unexpected fetch ${url}`)
  }

  const payload = await ctx.ensureAgentIterationNightlight(true)

  assert.equal(payload.status, 'ready')
  assert.deepEqual(payload.years, [2023, 2024, 2025])
  assert.equal(payload.snapshots.length, 3)
  assert.equal(payload.snapshots[0].grid_features.length, 1)
  assert.equal(ctx.getAgentIterationSnapshotCells(payload.snapshots[0]).length, 1)
  assert.equal(payload.ai_analysis.headline, '热点增强')
  assert.equal(ctx.nightlightSelectedYear, 2025)
  assert.deepEqual(ctx.nightlightOverview, { summary: { total_radiance: 99 } })
  assert.deepEqual(ctx.nightlightLayer, { view: 'radiance' })
  assert.deepEqual(ctx.nightlightRaster, { image_url: 'old' })
  assert.equal(calls.filter((item) => item.url === '/api/v1/analysis/nightlight/raster').length, 3)
  assert.equal(calls.filter((item) => item.url === '/api/v1/analysis/nightlight/grid').length, 3)
  assert.equal(calls.filter((item) => item.url === '/api/v1/analysis/nightlight/layer').length, 3)
})

test('copyAgentIterationSnapshotImage writes png snapshot to clipboard', async () => {
  const ctx = createAgentContext()
  const writes = []
  const originalNavigator = global.navigator
  const originalClipboardItem = global.ClipboardItem
  Object.defineProperty(global, 'navigator', {
    configurable: true,
    value: {
      clipboard: {
        write: async (items) => writes.push(items),
      },
    },
  })
  global.ClipboardItem = class ClipboardItem {
    constructor(items) {
      this.items = items
    }
  }
  try {
    await ctx.copyAgentIterationSnapshotImage({
      year: 2025,
      image_url: 'data:image/png;base64,iVBORw0KGgo=',
      summary: { total_radiance: 1 },
    })

    assert.equal(writes.length, 1)
    assert.equal(writes[0][0].items['image/png'].type, 'image/png')
    assert.equal(ctx.agentIterationSnapshotCopyStatus, '图片已复制')
    assert.equal(ctx.agentIterationSnapshotDetailOpen, false)
  } finally {
    Object.defineProperty(global, 'navigator', {
      configurable: true,
      value: originalNavigator,
    })
    global.ClipboardItem = originalClipboardItem
  }
})

test('buildAgentIterationSnapshotSvgMarkupFromNode serializes displayed svg', () => {
  const ctx = createAgentContext()
  const svgNode = {
    cloneNode() {
      return {
        attrs: {},
        setAttribute(name, value) {
          this.attrs[name] = value
        },
        querySelectorAll(selector) {
          if (selector !== 'polygon') return []
          return [{
            attrs: {},
            getAttribute(name) {
              return this.attrs[name] || ''
            },
            setAttribute(name, value) {
              this.attrs[name] = value
            },
          }]
        },
      }
    },
  }
  const originalSerializer = global.XMLSerializer
  global.XMLSerializer = class XMLSerializer {
    serializeToString(node) {
      assert.equal(node.attrs.xmlns, 'http://www.w3.org/2000/svg')
      assert.equal(node.attrs.width, '360')
      assert.equal(node.attrs.height, '260')
      return '<svg data-source="dom"></svg>'
    }
  }
  try {
    assert.equal(ctx.buildAgentIterationSnapshotSvgMarkupFromNode(svgNode), '<svg data-source="dom"></svg>')
  } finally {
    global.XMLSerializer = originalSerializer
  }
})

test('buildAgentIterationSnapshotSvgMarkupFromNode uses viewport export size when provided', () => {
  const ctx = createAgentContext()
  const svgNode = {
    cloneNode() {
      return {
        attrs: {},
        setAttribute(name, value) {
          this.attrs[name] = value
        },
        querySelectorAll() {
          return []
        },
      }
    },
  }
  const originalSerializer = global.XMLSerializer
  global.XMLSerializer = class XMLSerializer {
    serializeToString(node) {
      return JSON.stringify(node.attrs)
    }
  }
  try {
    const markup = ctx.buildAgentIterationSnapshotSvgMarkupFromNode(svgNode, { width: 940, height: 520 })
    assert.match(markup, /"width":"940"/)
    assert.match(markup, /"height":"520"/)
  } finally {
    global.XMLSerializer = originalSerializer
  }
})

test('ensureAgentIterationPopulation stores summary features', async () => {
  const ctx = createAgentContext()
  ctx.createAgentIterationChangeTab({ autoload: false })
  global.fetch = async (url, options = {}) => {
    if (url === '/api/v1/analysis/timeseries/meta') {
      return {
        ok: true,
        json: async () => ({
          default_population_period: '2024-2026',
          population_periods: [{ value: '2024-2026', label: '2024 -> 2026' }],
        }),
      }
    }
    if (url === '/api/v1/analysis/timeseries/population') {
      const body = JSON.parse(options.body)
      assert.equal(body.period, '2024-2026')
      assert.equal(body.layer_view, 'population_delta')
      return {
        ok: true,
        json: async () => ({
          series: [
            {
              year: 2024,
              total_population: 1000,
              male_total: 480,
              female_total: 520,
              male_ratio: 0.48,
              female_ratio: 0.52,
              population_density: 50,
              top_age_band_label: '25-29岁',
              top_age_band_ratio: 0.18,
              age_group_ratios: { child_0_14: 0.12, working_15_64: 0.72, senior_65_plus: 0.16 },
            },
            {
              year: 2026,
              total_population: 1200,
              male_total: 590,
              female_total: 610,
              male_ratio: 0.491667,
              female_ratio: 0.508333,
              population_density: 58,
              top_age_band_label: '30-34岁',
              top_age_band_ratio: 0.2,
              age_group_ratios: { child_0_14: 0.1, working_15_64: 0.7, senior_65_plus: 0.2 },
            },
          ],
          layer: { summary: { cell_count: 10, increase_count: 7, decrease_count: 2, average_rate: 0.12 } },
          insights: ['人口增长网格占主导'],
        }),
      }
    }
    throw new Error(`unexpected fetch ${url}`)
  }

  const payload = await ctx.ensureAgentIterationPopulation(true)
  const rows = ctx.getAgentIterationPopulationFeatureRows()

  assert.equal(payload.status, 'ready')
  assert.equal(payload.period, '2024-2026')
  assert.equal(rows.find((item) => item.key === 'increase').value, 7)
  assert.equal(rows.find((item) => item.key === 'population_delta').value, '200')
  assert.equal(rows.find((item) => item.key === 'male_total').value, '590')
  assert.equal(rows.find((item) => item.key === 'female_total').value, '610')
  assert.equal(rows.find((item) => item.key === 'male_ratio').value, '49.2%')
  assert.equal(rows.find((item) => item.key === 'sex_delta').value, '-20')
  assert.equal(rows.find((item) => item.key === 'dominant_age_band').value, '30-34岁')
  assert.equal(rows.find((item) => item.key === 'dominant_age_shift').value, '25-29岁 -> 30-34岁')
  assert.equal(rows.find((item) => item.key === 'working_age_ratio').value, '70.0%')
  assert.equal(rows.find((item) => item.key === 'senior_ratio').value, '20.0%')
  assert.equal(ctx.getAgentIterationKinds().find((item) => item.key === 'population').disabled, false)
})

test('ensureAgentIterationPoi summarizes multi-year history pois', async () => {
  const ctx = createAgentContext({
    currentHistoryRecordId: 'history-1',
    currentHistoryAvailablePoiYears: [2023, 2024, 2025],
    selectedPoint: { lng: 112.93, lat: 28.13 },
    h3GridResolution: 9,
    h3NeighborRing: 2,
    h3TargetCategory: 'food',
    h3CategoryMeta: [{ key: 'food', label: '餐饮' }],
    h3AnalysisSummary: {
      grid_count: 1,
      poi_count: 4,
      avg_density_poi_per_km2: 18.2,
      avg_local_entropy: 0.62,
      gi_z_stats: { count: 1 },
      lisa_i_stats: { count: 1 },
    },
    h3AnalysisCharts: { density_histogram: { bins: ['0-10'], counts: [1] } },
    h3AnalysisGridFeatures: [{
      type: 'Feature',
      geometry: { type: 'Polygon', coordinates: [] },
      properties: {
        h3_id: 'h3-1',
        poi_count: 4,
        density_poi_per_km2: 18.2,
        local_entropy: 0.62,
        neighbor_mean_density: 10,
        neighbor_mean_entropy: 0.4,
        neighbor_count: 6,
        category_counts: { food: 4 },
        gi_star_z_score: 2.4,
        gi_star_value: 1.1,
        lisa_i: 0.32,
        lisa_z_score: 1.8,
      },
    }],
    h3DerivedStats: {
      structureSummary: { rows: [{ h3_id: 'h3-1', gi_star_z_score: 2.4, lisa_i: 0.32, structure_signal: 2.4 }] },
      typingSummary: { rows: [{ h3_id: 'h3-1', type_key: 'high_density_high_mix', entropy_norm: 0.62 }] },
      lqSummary: { rows: [{ h3_id: 'h3-1', lq_target: 1.5, lq_map: { food: 1.5 } }] },
      gapSummary: { rows: [{ h3_id: 'h3-1', gap_score: 0.3, demand_pct: 0.8, supply_pct: 0.5 }] },
    },
    agentPanelPayloads: {
      iteration_change: {
        poi: {
          yearly_grid_evidence: {
            evidence_version: 'poi_iteration_yearly_grid_evidence_v1',
            years: [2023, 2024, 2025],
            grid_scope: 'poi_iteration_h3_per_year',
            grid_type: 'h3',
            latest_year: 2025,
            latest_h3_evidence: { evidence_version: 'poi_h3_evidence_v1' },
            items: [
              { year: 2023, status: 'ready', h3_evidence: {} },
              { year: 2024, status: 'ready', h3_evidence: {} },
              { year: 2025, status: 'ready', h3_evidence: {} },
            ],
          },
        },
      },
    },
    typeIdToGroupId: {
      'type-050100': 'group-7',
      'type-050500': 'group-7',
      'type-060100': 'group-6',
    },
    typeIdToLabel: {
      'type-050100': '中餐厅',
      'type-050500': '咖啡厅',
      'type-060100': '商场',
    },
    categoryById: {
      'group-7': { id: 'group-7', name: '餐饮' },
      'group-6': { id: 'group-6', name: '购物' },
    },
    resolvePoiTypeId(typeText) {
      const raw = String(typeText || '')
      if (this.typeIdToGroupId[raw]) return raw
      if (raw.includes('咖啡厅')) return 'type-050500'
      if (raw.includes('中餐厅')) return 'type-050100'
      if (raw.includes('商场') || raw.includes('专卖店')) return 'type-060100'
      return ''
    },
    resolvePoiCategory(typeText) {
      const typeId = this.resolvePoiTypeId(typeText)
      const groupId = this.typeIdToGroupId[typeId]
      return groupId ? this.categoryById[groupId] : null
    },
    getPoiTypeLabel(typeId) {
      return this.typeIdToLabel[String(typeId || '')] || String(typeId || '')
    },
  })
  let snapshotCalls = 0
  ctx.ensureAgentIterationPoiAreaHeatmapSnapshots = async (payload) => {
    snapshotCalls += 1
    return payload
  }
  ctx.createAgentIterationChangeTab({ autoload: false })
  global.fetch = async (url, options = {}) => {
    if (String(url).includes('/api/v1/analysis/agent/iteration/poi/build')) {
      const body = JSON.parse(options.body || '{}')
      assert.equal(body.history_id, 'history-1')
      assert.deepEqual(body.years, [2023, 2024, 2025])
      assert.deepEqual(body.center, [112.93, 28.13])
      assert.equal(body.h3_evidence.evidence_version, 'poi_h3_evidence_v1')
      assert.equal(body.h3_evidence.cells[0].gi_star_z_score, 2.4)
      assert.equal(body.h3_evidence.cells[0].geometry, undefined)
      assert.equal(body.h3_evidence.derived_stats.lq_rows[0].lq_target, 1.5)
      assert.equal(body.h3_evidence.omitted.geometry_removed, true)
      return {
        ok: true,
        json: async () => ({
          status: 'ready',
          source: 'history',
          years: [2023, 2024, 2025],
          summaries: [
            { year: 2023, count: 2, category_count: 2, subcategory_count: 2, category_counts: { 餐饮: 1, 购物: 1 }, subcategory_counts: { 咖啡厅: 1, 商场: 1 }, top_categories: [{ name: '餐饮', count: 1 }], top_subcategories: [{ name: '咖啡厅', parent: '餐饮', count: 1 }], top_areas: [{ name: '一区', count: 2 }] },
            { year: 2024, count: 3, category_count: 2, subcategory_count: 3, category_counts: { 餐饮: 2, 购物: 1 }, subcategory_counts: { 咖啡厅: 1, 中餐厅: 1, 商场: 1 }, top_categories: [{ name: '餐饮', count: 2 }], top_subcategories: [{ name: '咖啡厅', parent: '餐饮', count: 1 }], top_areas: [{ name: '一区', count: 2 }] },
            { year: 2025, count: 4, category_count: 3, subcategory_count: 4, category_counts: { 餐饮: 3, 购物: 0, 住宿服务: 1 }, subcategory_counts: { 咖啡厅: 2, 中餐厅: 1, 酒店: 1 }, top_categories: [{ name: '餐饮', count: 3 }], top_subcategories: [{ name: '咖啡厅', parent: '餐饮', count: 2 }], top_areas: [{ name: '一区', count: 2 }] },
          ],
          trend_rows: [
            { key: 'total_delta', label: 'POI 首尾变化', value: '+2' },
            { key: 'top_increase', label: '增长最明显业态', value: '餐饮 +2' },
          ],
          total_series: [{ year: 2023, value: 2 }, { year: 2024, value: 3 }, { year: 2025, value: 4 }],
          category_stack: [{ year: 2023, total: 2, segments: [{ name: '餐饮', count: 1 }] }, { year: 2024, total: 3, segments: [{ name: '餐饮', count: 2 }] }, { year: 2025, total: 4, segments: [{ name: '餐饮', count: 3 }] }],
          subcategory_stack: [{ year: 2023, total: 2, segments: [{ name: '咖啡厅', parent: '餐饮', count: 1 }] }, { year: 2024, total: 3, segments: [{ name: '咖啡厅', parent: '餐饮', count: 1 }] }, { year: 2025, total: 4, segments: [{ name: '咖啡厅', parent: '餐饮', count: 2 }] }],
          subcategory_trend_rows: [
            { key: 'subcategory_delta', label: '小类类型变化', value: '+2' },
            { key: 'top_subcategory_increase', label: '增长最明显小类', value: '咖啡厅（餐饮） +1' },
            { key: 'top_subcategory_decrease', label: '减少最明显小类', value: '商场（购物） -1' },
            { key: 'latest_top_subcategory', label: '末年第一小类', value: '咖啡厅（餐饮）' },
          ],
          area_heatmaps: [{ year: 2023, points: [{ x: 5, y: 5 }], point_count: 2, top_area: '一区' }, { year: 2024, points: [{ x: 10, y: 10 }], point_count: 3, top_area: '一区' }, { year: 2025, points: [{ x: 20, y: 20 }], point_count: 4, top_area: '一区' }],
          area_heatmap_polygon: [[112.8, 28.0], [113.0, 28.0], [113.0, 28.2], [112.8, 28.2], [112.8, 28.0]],
          rule_summary: ['当前POI规模为 4，一级主导业态为餐饮。'],
          rule_insights: {
            fastest_growth: '餐饮大类增长较快；小类增长最快为咖啡厅',
            declining_category: '未发现明显衰退行业。',
            emerging_area: '咖啡厅新增偏东北、中圈层补点',
            structure_judgement: '一级结构偏向餐饮主导。',
          },
          report_title: '业态基础分析总结报告',
          report_sections: [
            {
              heading: '一、总体判断：区域业态处于温和扩张阶段',
              paragraphs: ['从 POI 变化看，区域总量持续增长，餐饮为主导业态。'],
            },
            {
              heading: '二、空间特征：中圈层补点明显',
              paragraphs: ['咖啡厅新增主要集中在东北方向，说明增长更偏内部加密。'],
            },
          ],
          report_content: '业态基础分析总结报告\n\n一、总体判断：区域业态处于温和扩张阶段\n\n从 POI 变化看，区域总量持续增长，餐饮为主导业态。',
          spatial_factors: {
            geometry_mode: 'point',
            direction_factor: { dominant_direction: '东北' },
          },
          subcategory_spatial_trend_rows: [{
            name: '咖啡厅',
            parent: '餐饮',
            delta: 1,
            dominant_direction: '东北',
            secondary_direction: '东',
            dominant_ring: '中圈层',
            centroid_shift_direction: '东北',
            centroid_shift_m: 420,
            hotspot_grid_count: 1,
            hotspot_grid_count_delta: 1,
            top_area: '一区',
          }],
          subcategory_spatial_summary: ['咖啡厅新增主要集中在东北方向。'],
          h3_evidence: body.h3_evidence,
          error: '',
        }),
      }
    }
    throw new Error(`unexpected fetch ${url}`)
  }

  const payload = await ctx.ensureAgentIterationPoi(true)
  const featureRows = ctx.getAgentIterationPoiFeatureRows()
  const trendRows = ctx.getAgentIterationPoiTrendRows()

  assert.equal(payload.status, 'ready')
  assert.deepEqual(payload.years, [2023, 2024, 2025])
  assert.equal(payload.summaries.length, 3)
  assert.equal(payload.summaries[2].category_counts['餐饮'], 3)
  assert.equal(payload.summaries[2].subcategory_counts['咖啡厅'], 2)
  assert.equal(payload.summaries[2].top_subcategories[0].parent, '餐饮')
  assert.equal(payload.ai_summary.length, 0)
  assert.equal(Object.keys(payload.ai_insights).length, 0)
  assert.equal(payload.report_title, '业态基础分析总结报告')
  assert.equal(payload.report_sections[0].heading, '一、总体判断：区域业态处于温和扩张阶段')
  assert.match(payload.report_content, /区域总量持续增长/)
  assert.equal(ctx.hasAgentIterationPoiReport(), true)
  assert.equal(ctx.getAgentIterationPoiReportSections().length, 2)
  assert.equal(ctx.getAgentIterationPoiTotalLineChart().length, 3)
  assert.equal(ctx.getAgentIterationPoiCategoryStackChart().length, 3)
  assert.equal(ctx.getAgentIterationPoiSubcategoryStackChart().length, 3)
  assert.equal(payload.spatial_factors.direction_factor.dominant_direction, '东北')
  assert.equal(payload.subcategory_spatial_trend_rows[0].name, '咖啡厅')
  assert.equal(payload.h3_evidence.cells[0].lisa_i, 0.32)
  assert.equal(payload.h3_evidence.derived_stats.gap_rows[0].gap_score, 0.3)
  assert.match(ctx.formatAgentIterationPoiSpatialTrend(ctx.getAgentIterationPoiSpatialTrendRows()[0]), /主导方位 东北/)
  assert.equal(ctx.getAgentIterationPoiAreaHeatmaps().length, 3)
  assert.equal(snapshotCalls, 1)
  assert.equal(ctx.getAgentIterationPoiAreaHeatmapPolygon().length, 5)
  assert.equal(ctx.getAgentIterationPoiAreaHeatmapSnapshots().length, 3)
  assert.match(ctx.getAgentIterationPoiLineChartPolyline(), /,/)
  assert.equal(featureRows.find((item) => item.key === 'total').value, '4')
  assert.equal(featureRows.find((item) => item.key === 'top_subcategory').value, '咖啡厅')
  assert.equal(trendRows.find((item) => item.key === 'total_delta').value, '+2')
  assert.match(trendRows.find((item) => item.key === 'top_increase').value, /餐饮/)
  assert.notEqual(trendRows.find((item) => item.key === 'top_subcategory_increase').value, '-')
  assert.equal(payload.subcategory_trend_rows.length, 4)
  assert.equal(ctx.getAgentIterationKinds().find((item) => item.key === 'poi').disabled, false)
})

test('agent iteration poi exposes all subcategory groups and spatial rows', () => {
  const ctx = createAgentContext()
  const topSubcategories = Array.from({ length: 10 }, (_, index) => ({
    name: `小类${index}`,
    parent: index < 7 ? '餐饮' : '购物',
    count: 10 - index,
    ratio: (10 - index) / 55,
  }))
  const spatialRows = Array.from({ length: 8 }, (_, index) => ({
    name: `小类${index}`,
    parent: '餐饮',
    delta: index + 1,
    dominant_direction: '东北',
    hotspot_grid_count: index + 1,
  }))
  ctx.commitAgentIterationPoiPayload({
    status: 'ready',
    summaries: [{
      year: 2025,
      count: 55,
      subcategory_count: 10,
      category_counts: { 餐饮: 49, 购物: 6 },
      top_subcategories: topSubcategories,
      category_to_subcategory_mix: {
        餐饮: topSubcategories.slice(0, 7),
        购物: topSubcategories.slice(7),
      },
    }],
    subcategory_spatial_trend_rows: spatialRows,
  })

  const groups = ctx.getAgentIterationPoiSubcategoryGroups()

  assert.equal(ctx.getAgentIterationPoiSubcategoryTotal(), 10)
  assert.equal(groups.length, 2)
  assert.equal(groups[0].category, '餐饮')
  assert.equal(groups[0].items.length, 7)
  assert.equal(groups[1].items.length, 3)
  assert.equal(ctx.getAgentIterationPoiSpatialTrendRows().length, 8)
  assert.equal(ctx.getAgentIterationPoiSpatialTrendRows(6).length, 6)
  const evidenceSummary = ctx.buildAgentPoiIterationEvidence(ctx.getAgentIterationPoiPayload()).summaries[0]
  assert.equal(evidenceSummary.top_subcategories.length, 10)
  assert.equal(evidenceSummary.category_to_subcategory_mix['餐饮'].length, 7)
})

test('agent iteration poi exposes area heatmap basemap and boundary metadata', () => {
  const ctx = createAgentContext()
  ctx.commitAgentIterationPoiPayload({
    status: 'ready',
    summaries: [{ year: 2025, count: 2 }],
    area_heatmaps: [{ year: 2025, points: [{ x: 12, y: 24 }], point_count: 1, top_area: '一区' }],
    area_heatmap_basemap: {
      url: '',
      bounds: { min_lng: 112.8, min_lat: 28.0, max_lng: 113.0, max_lat: 28.2 },
      center: [112.9, 28.1],
      zoom: null,
      size: { width: 100, height: 65.625 },
      source: 'none',
      view: { width: 100, height: 65.625 },
      view_box: '0 0 100 65.625',
      aspect_ratio: '100 / 65.625',
    },
    area_heatmap_boundary: [{ x: 10, y: 90 }, { x: 90, y: 90 }, { x: 90, y: 10 }],
    area_heatmap_polygon: [[112.8, 28.0], [113.0, 28.0], [113.0, 28.2]],
    area_heatmap_snapshots: [{ year: 2025, image_url: 'data:image/png;base64,test', point_count: 1, top_area: '一区', status: 'ready' }],
    prompt_snapshot: {
      prompt_key: 'poi_iteration',
      system_prompt: '真实 POI system prompt poi_iteration_v1 growth_area_signal',
      payload_note: '真实 POI payload note User payload',
      output_schema: { required: ['report_title', 'report_sections', 'report_content'] },
      evidence_version: 'poi_iteration_v1',
    },
  })

  assert.equal(ctx.getAgentIterationPoiAreaHeatmapBasemap().source, 'none')
  assert.equal(ctx.getAgentIterationPoiAreaHeatmapBasemap().url, '')
  assert.equal(ctx.hasAgentIterationPoiAreaHeatmapBasemapImage(), false)
  assert.equal(ctx.getAgentIterationPoiAreaHeatmapViewBox(), '0 0 100 65.625')
  assert.deepEqual(ctx.getAgentIterationPoiAreaHeatmapViewSize(), { width: 100, height: 65.625 })
  assert.deepEqual(ctx.getAgentIterationPoiAreaHeatmapAspectStyle(), { aspectRatio: '100 / 65.625' })
  assert.equal(ctx.getAgentIterationPoiAreaHeatmapBoundaryPoints(), '10.00,90.00 90.00,90.00 90.00,10.00')
  assert.equal(ctx.getAgentIterationPoiAreaHeatmapDisplayBoundaryPoints(), '21.13,61.69 78.88,61.69 78.88,3.94')
  assert.equal(ctx.getAgentIterationPoiAreaHeatmapChangeSummary(), '展示当前区域全部 POI 的年度空间分布。')
  assert.equal(ctx.formatAgentIterationPoiAreaHeatmapDelta(-12), '-12')
  assert.deepEqual(ctx.getAgentIterationPoiAreaHeatmapDeltaStateClass(-12), { 'is-positive': false, 'is-negative': true, 'is-flat': false })
  assert.equal(ctx.getAgentIterationPoiAreaHeatmapPolygon().length, 3)
  assert.equal(ctx.getAgentIterationPoiAreaHeatmapSnapshot(2025).image_url, 'data:image/png;base64,test')
  const evidence = ctx.buildAgentPoiIterationEvidence(ctx.getAgentIterationPoiPayload())
  assert.equal(evidence.area_heatmap_basemap.source, 'none')
  assert.equal(evidence.area_heatmap_boundary.length, 3)
  assert.equal(evidence.area_heatmap_polygon.length, 3)
  const preview = ctx.buildAgentPoiIterationAiEvidencePreview(ctx.getAgentIterationPoiPayload())
  assert.equal(preview.task, 'poi_iteration_change')
  assert.equal(preview.evidence_version, 'poi_iteration_v1')
  assert.equal(preview.year_summaries[0].poi_count, 2)
  assert.equal(preview.area_distribution[0].hotspot_cell_count, 0)
  assert.equal(preview.scope.polygon_point_count, 3)
  assert.equal(preview.material_change_highlights.ranking_policy.includes('absolute_delta'), true)
  assert.equal(preview.growth_area_signal.label, 'growth_area_direction')
  assert.equal(preview.constraints.no_coordinate_reasoning, true)
  assert.equal(preview.constraints.no_low_base_rate_as_primary, true)
  assert.equal(JSON.stringify(preview).includes('data:image/png'), false)

  const basis = ctx.buildAgentIterationBasisPayload('poi')
  assert.equal(JSON.stringify(basis.rawInput).includes('data:image/png'), false)
  assert.equal(basis.rawInput.evidence_version, 'poi_iteration_v1')
  assert.equal(basis.rawInput.scope.polygon_point_count, 3)
  assert.equal(basis.fields[0].key, 'evidence_version')
  assert.equal(basis.fields.some((field) => field.key === 'feature_rows'), false)
  assert.equal(basis.fields.some((field) => field.key === 'spatial_factors'), false)
  assert.match(basis.aiPrompt, /poi_iteration_v1/)
  assert.match(basis.aiPrompt, /growth_area_signal/)
  assert.match(basis.aiPromptPayloadNote, /User payload/)
  assert.equal(ctx.formatBasisFieldValue([{ key: 'total_delta', label: 'POI 首尾变化', value: '-795' }]), 'POI 首尾变化：-795')
  assert.equal(ctx.formatBasisFieldValue(basis.fields).includes('{"key"'), false)

  ctx.commitAgentIterationPoiPayload({ area_heatmap_basemap: { source: 'none', url: '' }, area_heatmap_boundary: [] })
  assert.equal(ctx.getAgentIterationPoiAreaHeatmapBasemap().url, '')
  assert.equal(ctx.getAgentIterationPoiAreaHeatmapViewBox(), '0 0 100 100')
  assert.deepEqual(ctx.getAgentIterationPoiAreaHeatmapAspectStyle(), { aspectRatio: '100 / 100' })
  assert.equal(ctx.getAgentIterationPoiAreaHeatmapBoundaryPoints(), '')
})

test('agent iteration poi evidence compacts canonical h3 feature payloads for basis', () => {
  const ctx = createAgentContext()
  ctx.commitAgentIterationPoiPayload({
    status: 'ready',
    years: [2020, 2024],
    summaries: [
      { year: 2020, count: 1, category_counts: { 餐饮: 1 }, subcategory_counts: { 中餐厅: 1 }, top_areas: [{ name: 'A' }] },
      { year: 2024, count: 2, category_counts: { 餐饮: 2 }, subcategory_counts: { 中餐厅: 2 }, top_areas: [{ name: 'A' }] },
    ],
    h3_evidence: {
      evidence_version: 'poi_h3_evidence_v1',
      cells: [{
        type: 'Feature',
        geometry: { type: 'Polygon', coordinates: [[[112.1, 28.1], [112.2, 28.1], [112.1, 28.1]]] },
        properties: {
          h3_id: 'h3-canonical',
          poi_count: 2,
          density_poi_per_km2: 18.2,
          gi_star_z_score: 2.4,
          lisa_i: 0.3,
        },
      }],
      derived_stats: {
        lq_rows: [{ h3_id: 'h3-1', lq_target: 1.2 }],
      },
    },
    yearly_grid_evidence: {
      evidence_version: 'poi_iteration_yearly_grid_evidence_v1',
      items: [{
        year: 2024,
        status: 'ready',
        h3_evidence: {
          cells: [{
            type: 'Feature',
            geometry: { type: 'Polygon', coordinates: [[[112.1, 28.1], [112.2, 28.1], [112.1, 28.1]]] },
            properties: { h3_id: 'h3-year', poi_count: 2 },
          }],
        },
      }],
    },
  })

  const preview = ctx.buildAgentPoiIterationAiEvidencePreview(ctx.getAgentIterationPoiPayload())
  const basis = ctx.buildAgentIterationBasisPayload('poi', 'analysis')
  const serialized = JSON.stringify(basis.rawInput)

  assert.equal(preview.h3_evidence.cells[0].h3_id, 'h3-canonical')
  assert.equal(preview.h3_evidence.cells[0].geometry, undefined)
  assert.equal(preview.h3_evidence.cells[0].properties, undefined)
  assert.equal(preview.h3_evidence.derived_stats.lq_rows[0].lq_target, 1.2)
  assert.equal(preview.yearly_grid_evidence.items[0].h3_evidence.cells[0].h3_id, 'h3-year')
  assert.equal(serialized.includes('"geometry"'), false)
  assert.equal(serialized.includes('"coordinates"'), false)
  assert.equal(serialized.includes('"properties"'), false)
})

test('buildAgentIterationSnapshotSvgMarkupFromNode inlines poi heatmap overlay styles', () => {
  const ctx = createAgentContext()
  const nodes = []
  const makeNode = (className) => {
    const attrs = { class: className }
    const node = {
      attrs,
      setAttribute(key, value) {
        attrs[key] = value
      },
      getAttribute(key) {
        return attrs[key] || ''
      },
    }
    nodes.push(node)
    return node
  }
  const boundary = makeNode('agent-iteration-heatmap-boundary')
  const cell = makeNode('agent-iteration-heatmap-cell')
  const point = makeNode('agent-iteration-heatmap-point')
  const originalSerializer = global.XMLSerializer
  global.XMLSerializer = class XMLSerializer {
    serializeToString() {
      return JSON.stringify(nodes.map((node) => node.attrs))
    }
  }
  try {
    const markup = ctx.buildAgentIterationSnapshotSvgMarkupFromNode({
      cloneNode() {
        return {
          setAttribute() {},
          querySelectorAll(selector) {
            if (selector === '.agent-iteration-heatmap-boundary') return [boundary]
            if (selector === '.agent-iteration-heatmap-cell') return [cell]
            if (selector === '.agent-iteration-heatmap-point') return [point]
            if (selector === 'polygon') return [boundary]
            return []
          },
        }
      },
    })

    assert.match(markup, /#1d4ed8/)
    assert.match(markup, /#f97316/)
    assert.match(markup, /#0891b2/)
    assert.doesNotMatch(markup, /"fill":""/)
  } finally {
    global.XMLSerializer = originalSerializer
  }
})

test('agent iteration poi basis keeps real prompt while splitting analysis and insight fields', () => {
  const ctx = createAgentContext()
  ctx.commitAgentIterationPoiPayload({
    status: 'ready',
    years: [2020, 2024],
    summaries: [
      { year: 2020, count: 10, category_count: 2, subcategory_count: 3, top_areas: [{ name: 'A' }] },
      { year: 2024, count: 18, category_count: 3, subcategory_count: 4, top_areas: [{ name: 'A' }] },
    ],
    trend_rows: [{ key: 'total_delta', label: 'POI 首尾变化', value: '+8' }],
    category_trend_rows: [
      { name: '餐饮', delta: 6, first_count: 4, last_count: 10 },
      { name: '购物', delta: -2, first_count: 4, last_count: 2 },
    ],
    subcategory_trend_rows: [
      { name: '咖啡厅', parent: '餐饮', delta: 5, first_count: 1, last_count: 6 },
    ],
    subcategory_spatial_trend_rows: [
      { name: '咖啡厅', parent: '餐饮', delta: 5, dominant_direction: '东北', dominant_ring: '中圈层', hotspot_grid_count: 2 },
    ],
    area_distribution: [{ year: 2024, point_count: 18, hotspot_cell_count: 2 }],
    report_title: '业态基础分析总结报告',
    report_sections: [
      {
        heading: '一、总体判断：区域业态温和增长',
        paragraphs: ['从 POI 总量和餐饮增量看，区域生活消费基础增强。'],
      },
    ],
    report_content: '业态基础分析总结报告\n\n一、总体判断：区域业态温和增长\n\n从 POI 总量和餐饮增量看，区域生活消费基础增强。',
    h3_evidence: { evidence_version: 'poi_h3_evidence_v1', counts: { grid_count: 4 } },
    yearly_grid_evidence: { evidence_version: 'poi_iteration_yearly_grid_evidence_v1', items: [{ year: 2024, status: 'ready' }] },
    ai_prompt: '真实 POI 多年调用 system prompt',
    ai_prompt_payload_note: '真实 POI 多年调用 user payload note',
    prompt_snapshot: {
      prompt_key: 'poi_iteration',
      system_prompt: '真实 POI 多年调用 system prompt',
      payload_note: '真实 POI 多年调用 user payload note',
      output_schema: { required: ['report_title', 'report_sections', 'report_content'] },
      evidence_version: 'poi_iteration_v1',
    },
  })

  const analysisBasis = ctx.buildAgentIterationBasisPayload('poi', 'analysis')
  const insightBasis = ctx.buildAgentIterationBasisPayload('poi', 'insight')

  assert.equal(analysisBasis.aiPrompt, '真实 POI 多年调用 system prompt')
  assert.equal(insightBasis.aiPrompt, '真实 POI 多年调用 system prompt')
  assert.equal(analysisBasis.aiPromptPayloadNote, '真实 POI 多年调用 user payload note')
  assert.equal(insightBasis.aiPromptPayloadNote, '真实 POI 多年调用 user payload note')
  assert.equal(analysisBasis.promptSourceLabel, '本次生成实际使用的提示词快照')
  assert.notEqual(analysisBasis.title, insightBasis.title)
  assert.match(analysisBasis.currentConclusion, /区域生活消费基础增强/)
  assert.match(insightBasis.currentConclusion, /区域生活消费基础增强/)
  assert.equal(analysisBasis.fields.some((field) => field.key === 'output_fields' && String(field.value).includes('summary_points')), false)
  assert.equal(analysisBasis.fields.some((field) => field.key === 'output_fields' && String(field.value).includes('report_content')), true)
  assert.equal(analysisBasis.fields.some((field) => field.key === 'h3_evidence'), true)
  assert.equal(analysisBasis.fields.some((field) => field.key === 'yearly_grid_evidence'), true)
  assert.equal(insightBasis.fields.some((field) => field.key === 'output_fields' && String(field.value).includes('fastest_growth')), false)
  assert.equal(analysisBasis.fields.some((field) => field.key === 'prompt_structure' && String(field.value).includes('同一基础提示词')), true)
  assert.equal(insightBasis.fields.some((field) => field.key === 'prompt_structure' && String(field.value).includes('业态基础分析')), true)
  assert.equal(insightBasis.rules.some((rule) => String(rule).includes('不是重复调用')), true)
  assert.equal(JSON.stringify(analysisBasis.rawInput).includes('data:image/png'), false)
  assert.equal(analysisBasis.rawInput.evidence_version, 'poi_iteration_v1')
})

test('agent iteration poi analysis template renders report sections instead of insight cards', async () => {
  const html = await fs.promises.readFile(new URL('../src/pages/analysis/components/main.html', import.meta.url), 'utf8')
  const start = html.indexOf('<div class="agent-summary-card-title">业态基础分析</div>')
  const end = html.indexOf('<section v-if="getAgentIterationPoiPayload().status === \'ready\' && isAgentIterationSecondaryView(\'metrics\')"', start)
  const block = html.slice(start, end)

  assert.match(block, /getAgentIterationPoiReportSections\(\)/)
  assert.match(block, /agent-iteration-report-section/)
  assert.doesNotMatch(block, /getAgentIterationPoiAiInsightRows\(\)/)
  assert.doesNotMatch(block, /增长最快行业/)
  assert.doesNotMatch(block, /衰退行业/)
  assert.doesNotMatch(block, /增长片区/)
  assert.doesNotMatch(block, /结构判断/)
})

test('agent iteration poi insight keeps skeleton while ai is pending even with rule fallback', () => {
  const ctx = createAgentContext()
  ctx.commitAgentIterationPoiPayload({
    status: 'ready',
    ai_status: 'pending',
    ai_summary: [],
    ai_insights: {},
    ai_error: '',
    rule_insights: {
      fastest_growth: '规则增长行业',
      declining_category: '规则衰退行业',
      emerging_area: '规则增长片区',
      structure_judgement: '规则结构判断',
    },
  })

  assert.deepEqual(ctx.getAgentIterationPoiAiInsightRows(), [])
  assert.equal(ctx.shouldShowAgentIterationPoiInsightPlaceholder(), true)
})

test('agent iteration poi insight does not synthesize fallback after ai timeout', () => {
  const ctx = createAgentContext()
  ctx.commitAgentIterationPoiPayload({
    status: 'ready',
    ai_error: 'ai_timeout',
    ai_insights: {},
    rule_insights: {},
    subcategory_spatial_trend_rows: [
      {
        name: '快餐厅',
        parent: '餐饮',
        delta: 155,
        dominant_direction: '西南',
        dominant_ring: '中圈层',
        centroid_shift_direction: '西南',
        centroid_shift_m: 74,
        hotspot_grid_count: 5,
        top_area: '岳麓区',
      },
      {
        name: '购物相关场所',
        parent: '购物',
        delta: -179,
        dominant_direction: '北',
        hotspot_grid_count: 2,
      },
    ],
  })

  const rows = ctx.getAgentIterationPoiAiInsightRows()

  assert.deepEqual(rows, [])
})

test('agent iteration poi normalizes legacy emerging area wording without fallback synthesis', () => {
  const ctx = createAgentContext()
  ctx.commitAgentIterationPoiPayload({
    status: 'ready',
    ai_error: 'ai_timeout',
    ai_insights: { emerging_area: '未发现明显新兴区域' },
    rule_insights: {},
    subcategory_spatial_trend_rows: [{
      name: '快餐厅',
      parent: '餐饮',
      delta: 155,
      dominant_direction: '西南',
      dominant_ring: '中圈层',
      hotspot_grid_count: 5,
    }],
  })

  const growthArea = ctx.getAgentIterationPoiAiInsightRows().find((item) => item.key === 'emerging_area')

  assert.equal(growthArea.label, '增长片区')
  assert.equal(growthArea.value, '未发现明显增长片区')
  assert.equal(growthArea.value.includes('新兴区域'), false)
})

test('agent iteration poi ai timeout is treated as progressive status', () => {
  const ctx = createAgentContext()
  ctx.commitAgentIterationPoiPayload({
    status: 'ready',
    ai_error: 'ai_timeout',
    ai_summary: [],
    rule_summary: ['基础规则分析已完成。'],
  })

  assert.equal(ctx.isAgentIterationAiTimeout(ctx.getAgentIterationPoiPayload().ai_error), true)
  assert.equal(ctx.getAgentIterationPoiAiStatusText(), '基础统计和快照已完成，AI 深度解读仍在补充。')
  assert.deepEqual(ctx.getAgentIterationPoiAiSummaryRows(), [])
})

test('agent iteration poi area heatmap explains count changes', () => {
  const ctx = createAgentContext()
  ctx.commitAgentIterationPoiPayload({
    status: 'ready',
    area_heatmaps: [
      { year: 2020, point_count: 4791, cells: [{ intensity: 1 }], points: [] },
      { year: 2022, point_count: 3760, cells: [{ intensity: 1 }, { intensity: 0.5 }], points: [] },
      { year: 2024, point_count: 3996, cells: [], points: [] },
    ],
  })

  const rows = ctx.getAgentIterationPoiAreaHeatmaps()

  assert.equal(rows[1].delta_from_previous, -1031)
  assert.equal(rows[2].delta_from_previous, 236)
  assert.equal(rows[2].delta_from_first, -795)
  assert.equal(rows[0].is_first_year, true)
  assert.equal(rows[1].is_first_year, false)
  assert.equal(ctx.getAgentIterationPoiAreaHeatmapChangeSummary(), '2020-2024 全部 POI 先降后回升，净变化 -795。')
  assert.equal(ctx.getAgentIterationPoiAreaHeatmapHotspotCount(rows[1]), 2)
})

test('agent iteration poi heatmap layers switch between cells and points', () => {
  const ctx = createAgentContext()

  assert.deepEqual(ctx.getAgentIterationPoiAreaHeatmapLayerState(), { cells: false, points: true })
  assert.equal(ctx.isAgentIterationPoiAreaHeatmapLayerVisible('cells'), false)
  assert.equal(ctx.isAgentIterationPoiAreaHeatmapLayerVisible('points'), true)
  assert.equal(ctx.getAgentIterationPoiAreaHeatmapLayerLabel('cells'), '格网')
  assert.equal(ctx.getAgentIterationPoiAreaHeatmapLayerLabel('points'), '点位')

  const eventCalls = []
  ctx.toggleAgentIterationPoiAreaHeatmapLayer('cells', {
    preventDefault: () => eventCalls.push('prevent'),
    stopPropagation: () => eventCalls.push('stop'),
  })

  assert.deepEqual(eventCalls, ['prevent', 'stop'])
  assert.equal(ctx.isAgentIterationPoiAreaHeatmapLayerVisible('cells'), true)
  assert.equal(ctx.isAgentIterationPoiAreaHeatmapLayerVisible('points'), false)

  ctx.toggleAgentIterationPoiAreaHeatmapLayer('points')

  assert.equal(ctx.isAgentIterationPoiAreaHeatmapLayerVisible('cells'), false)
  assert.equal(ctx.isAgentIterationPoiAreaHeatmapLayerVisible('points'), true)
  assert.deepEqual(ctx.agentIterationPoiAreaHeatmapLayers, { mode: 'points', cells: false, points: true })
})

test('agent iteration poi shows placeholders until async ai interpretation lands', async () => {
  const ctx = createAgentContext({
    currentHistoryRecordId: 'history-async-ai',
    currentHistoryAvailablePoiYears: [2023, 2025],
  })
  ctx.ensureAgentIterationPoiAreaHeatmapSnapshots = async (payload) => payload
  ctx.createAgentIterationChangeTab({ autoload: false })
  let resolveInterpret = null
  const calls = []
  global.fetch = async (url, options = {}) => {
    calls.push({ url, body: options.body ? JSON.parse(options.body) : null })
    if (String(url).includes('/api/v1/analysis/agent/iteration/poi/build')) {
      return {
        ok: true,
        json: async () => ({
          status: 'ready',
          source: 'history',
          historyId: 'history-async-ai',
          years: [2023, 2025],
          summaries: [
            { year: 2023, count: 1, category_count: 1, subcategory_count: 1, points: [{ lng: 112.9, lat: 28.1 }], top_areas: [{ name: 'A' }] },
            { year: 2025, count: 3, category_count: 1, subcategory_count: 1, points: [{ lng: 112.91, lat: 28.11 }], top_areas: [{ name: 'A' }] },
          ],
          trend_rows: [{ key: 'total_delta', label: 'POI 首尾变化', value: '+2' }],
          total_series: [{ year: 2023, value: 1 }, { year: 2025, value: 3 }],
          category_stack: [],
          subcategory_stack: [],
          subcategory_trend_rows: [],
          area_heatmaps: [{ year: 2023, points: [], cells: [], point_count: 1 }, { year: 2025, points: [], cells: [], point_count: 3 }],
          area_heatmap_basemap: { source: 'none', url: '', view: { width: 100, height: 100 }, view_box: '0 0 100 100' },
          area_heatmap_boundary: [],
          area_heatmap_polygon: [],
          rule_summary: ['基础规则摘要'],
          rule_insights: {},
          ai_status: 'pending',
          ai_summary: [],
          ai_insights: {},
          ai_error: '',
          error: '',
        }),
      }
    }
    if (String(url).includes('/api/v1/analysis/agent/iteration/poi/interpret')) {
      await new Promise((resolve) => { resolveInterpret = resolve })
      return {
        ok: true,
        json: async () => ({
          status: 'ready',
          report_title: '业态基础分析总结报告',
          report_sections: [
            { heading: '一、总体判断：AI 解释完成', paragraphs: ['餐饮增长最快，区域业态基础增强。'] },
          ],
          report_content: '业态基础分析总结报告\n\n一、总体判断：AI 解释完成\n\n餐饮增长最快，区域业态基础增强。',
          spatial_factors: { geometry_mode: 'point' },
          subcategory_spatial_trend_rows: [{ name: '咖啡厅', parent: '餐饮', delta: 2, dominant_direction: '东北' }],
          subcategory_spatial_summary: ['咖啡厅向东北聚集'],
          ai_prompt: '真实 POI system prompt',
          ai_prompt_payload_note: '真实 user payload note',
          prompt_snapshot: {
            prompt_key: 'poi_iteration',
            system_prompt: '真实 POI system prompt',
            payload_note: '真实 user payload note',
            output_schema: { required: ['report_title', 'report_sections', 'report_content'] },
            evidence_version: 'poi_iteration_v1',
          },
          error: '',
        }),
      }
    }
    throw new Error(`unexpected fetch ${url}`)
  }

  const payload = await ctx.ensureAgentIterationPoi(true)
  assert.equal(payload.status, 'ready')
  assert.equal(ctx.getAgentIterationPoiPayload().ai_status, 'loading')
  assert.equal(ctx.shouldShowAgentIterationPoiAiPlaceholder(), true)
  assert.deepEqual(ctx.getAgentIterationPoiAiSummaryRows(), [])
  assert.equal(ctx.shouldShowAgentIterationPoiInsightPlaceholder(), true)

  resolveInterpret()
  await Promise.resolve()
  await Promise.resolve()
  await new Promise((resolve) => setTimeout(resolve, 0))

  assert.equal(ctx.getAgentIterationPoiPayload().ai_status, 'ready')
  assert.equal(ctx.getAgentIterationPoiPayload().report_title, '业态基础分析总结报告')
  assert.equal(ctx.getAgentIterationPoiReportSections()[0].heading, '一、总体判断：AI 解释完成')
  assert.equal(ctx.buildAgentIterationBasisPayload('poi').aiPrompt, '真实 POI system prompt')
  assert.equal(ctx.buildAgentIterationBasisPayload('poi').aiPromptPayloadNote, '真实 user payload note')
  assert.match(ctx.getAgentIterationPoiReportSections()[0].paragraphs[0], /餐饮增长最快/)
  assert.equal(ctx.shouldShowAgentIterationPoiAiPlaceholder(), false)
  assert.equal(calls.filter((item) => String(item.url).includes('/api/v1/analysis/agent/iteration/poi/build')).length, 1)
  assert.equal(calls.filter((item) => String(item.url).includes('/api/v1/analysis/agent/iteration/poi/interpret')).length, 1)
})

test('agent iteration poi heatmap keeps raw coordinates over basemap image', () => {
  const ctx = createAgentContext()
  ctx.commitAgentIterationPoiPayload({
    status: 'ready',
    area_heatmap_basemap: {
      url: 'https://restapi.amap.com/v3/staticmap?location=112.9,28.1&zoom=13&size=640*420&key=test',
      source: 'amap_static_url',
      view: { width: 100, height: 65.625 },
      view_box: '0 0 100 65.625',
      aspect_ratio: '100 / 65.625',
    },
    area_heatmap_boundary: [{ x: 10, y: 60 }, { x: 90, y: 60 }, { x: 90, y: 6 }, { x: 10, y: 6 }],
    area_heatmaps: [{
      year: 2025,
      cells: [{ x: 10, y: 20, width: 8, height: 6, intensity: 1 }],
      points: [{ x: 50, y: 40 }],
    }],
  })

  assert.equal(ctx.hasAgentIterationPoiAreaHeatmapBasemapImage(), true)
  assert.equal(ctx.getAgentIterationPoiAreaHeatmapDisplayBoundaryPoints(), '10.00,60.00 90.00,60.00 90.00,6.00 10.00,6.00')
  assert.deepEqual(ctx.getAgentIterationPoiAreaHeatmapDisplayPoints(ctx.getAgentIterationPoiAreaHeatmaps()[0])[0], { x: 50, y: 40, count: 1, radius: 2, opacity: 0.68 })
  assert.deepEqual(ctx.getAgentIterationPoiAreaHeatmapDisplayCells(ctx.getAgentIterationPoiAreaHeatmaps()[0])[0], { x: 10, y: 20, width: 8, height: 6, intensity: 1 })
})

test('agent iteration poi heatmap display transform fits boundary into basemap viewport', () => {
  const ctx = createAgentContext()
  ctx.commitAgentIterationPoiPayload({
    status: 'ready',
    area_heatmap_basemap: {
      view: { width: 100, height: 65.625 },
      view_box: '0 0 100 65.625',
      aspect_ratio: '100 / 65.625',
    },
    area_heatmap_boundary: [{ x: 10, y: 20 }, { x: 90, y: 20 }, { x: 90, y: 60 }, { x: 10, y: 60 }],
    area_heatmaps: [{
      year: 2025,
      cells: [{ x: 10, y: 20, width: 20, height: 10, intensity: 1 }],
      points: [{ x: 50, y: 40 }],
    }],
  })

  assert.equal(ctx.getAgentIterationPoiAreaHeatmapViewBox(), '0 0 100 65.625')
  assert.deepEqual(ctx.getAgentIterationPoiAreaHeatmapAspectStyle(), { aspectRatio: '100 / 65.625' })
  assert.equal(ctx.getAgentIterationPoiAreaHeatmapDisplayBoundaryPoints(), '6.00,10.81 94.00,10.81 94.00,54.81 6.00,54.81')
  assert.deepEqual(ctx.getAgentIterationPoiAreaHeatmapDisplayPoints(ctx.getAgentIterationPoiAreaHeatmaps()[0])[0], { x: 50, y: 32.813, count: 1, radius: 2, opacity: 0.68 })
  assert.deepEqual(ctx.getAgentIterationPoiAreaHeatmapDisplayCells(ctx.getAgentIterationPoiAreaHeatmaps()[0])[0], {
    x: 6,
    y: 10.813,
    width: 22,
    height: 11,
    intensity: 1,
  })
})

test('agent iteration poi frontend heatmap bundle uses polygon viewport and filters outside points', () => {
  const ctx = createAgentContext()
  const polygon = [[112.89, 28.09], [113.01, 28.09], [113.01, 28.13], [112.89, 28.13], [112.89, 28.09]]
  const bundle = ctx.buildAgentPoiAreaHeatmapBundle([{
    year: 2025,
    points: [
      { lng: 112.92, lat: 28.11, area: 'A', category: '餐饮', subcategory: '咖啡厅' },
      { lng: 113.5, lat: 29.0, area: 'B', category: '餐饮', subcategory: '火锅' },
    ],
    top_areas: [{ name: 'A' }],
  }], polygon)

  assert.equal(bundle.area_heatmap_polygon.length, 5)
  assert.equal(bundle.area_heatmap_boundary.length, 5)
  assert.equal(bundle.area_heatmap_basemap.view_box, `0 0 ${bundle.area_heatmap_basemap.view.width} ${bundle.area_heatmap_basemap.view.height}`)
  assert.notEqual(bundle.area_heatmap_basemap.view_box, '0 0 100 100')
  assert.equal(bundle.area_heatmaps[0].point_count, 1)
  const view = bundle.area_heatmap_basemap.view
  assert.ok(bundle.area_heatmaps[0].points.every((point) => point.x >= 0 && point.x <= view.width && point.y >= 0 && point.y <= view.height))
  assert.ok(bundle.area_heatmap_boundary.every((point) => point.x >= 0 && point.x <= view.width && point.y >= 0 && point.y <= view.height))
})

test('ensureAgentIterationPoi without multi-year data asks for poi/grid fill', async () => {
  const ctx = createAgentContext({
    allPoisDetails: [
      { id: 'inside', type: 'type-050500', typeLabel: '咖啡厅', adname: 'A', location: [112.92, 28.12] },
      { id: 'outside', type: 'type-050500', typeLabel: '咖啡厅', adname: 'B', location: [113.5, 29.0] },
    ],
    currentHistorySelectedPoiYear: 2025,
    currentHistoryRecordId: '',
    currentHistoryAvailablePoiYears: [],
    getIsochronePolygonPayload() {
      return [[112.89, 28.09], [113.01, 28.09], [113.01, 28.13], [112.89, 28.13], [112.89, 28.09]]
    },
    getIsochronePolygonRing() {
      return [[112.89, 28.09], [113.01, 28.09], [113.01, 28.13], [112.89, 28.13], [112.89, 28.09]]
    },
  })
  ctx.createAgentIterationChangeTab({ autoload: false })

  const payload = await ctx.ensureAgentIterationPoi(true)

  assert.equal(payload.status, 'needs_data')
  assert.deepEqual(ctx.getAgentIterationPoiTaskKeysToFill(), ['poi_fetch', 'poi_h3_grid'])
  assert.match(payload.notice, /POI/)
})

test('agent iteration poi heatmap template prefers snapshot image and falls back to svg', async () => {
  const html = await fs.promises.readFile(new URL('../src/pages/analysis/components/main.html', import.meta.url), 'utf8')
  const heatmapStart = html.indexOf('agent-iteration-heatmap-layer-controls')
  const heatmapEnd = html.indexOf('agent-iteration-heatmap-caption', heatmapStart)
  const heatmapBlock = html.slice(heatmapStart, heatmapEnd)
  assert.match(heatmapBlock, /getAgentIterationPoiAreaHeatmapSnapshot\(heatmap\.year\)\.image_url/)
  assert.match(heatmapBlock, /agent-iteration-heatmap-img/)
  assert.match(heatmapBlock, /agent-iteration-heatmap-overlay/)
  assert.match(heatmapBlock, /agent-iteration-heatmap-layer-controls/)
  assert.match(heatmapBlock, /getAgentIterationPoiAreaHeatmapCopyLabel\(heatmap\)/)
  assert.match(heatmapBlock, /toggleAgentIterationPoiAreaHeatmapLayer\(layer, \$event\)/)
  assert.match(heatmapBlock, /isAgentIterationPoiAreaHeatmapLayerVisible\('cells'\)/)
  assert.match(heatmapBlock, /isAgentIterationPoiAreaHeatmapLayerVisible\('points'\)/)
  assert.match(heatmapBlock, /@click="copyAgentIterationPoiAreaHeatmapImage\(heatmap, \$event\)"/)
  assert.match(heatmapBlock, /v-if="!heatmap\.is_first_year" class="agent-iteration-heatmap-change-strip"/)
  assert.match(heatmapBlock, /getAgentIterationPoiAreaHeatmapSnapshotStatusText/)
  assert.match(heatmapBlock, /:style="getAgentIterationPoiAreaHeatmapAspectStyle\(\)"/)
  assert.match(heatmapBlock, /agent-iteration-heatmap-viewport--snapshot"[\s\S]*:style="getAgentIterationPoiAreaHeatmapAspectStyle\(\)"/)
  assert.match(heatmapBlock, /<svg v-bind="getAgentIterationPoiAreaHeatmapSvgAttrs\(\)"/)
  assert.doesNotMatch(heatmapBlock, /:viewBox=/)
  assert.match(heatmapBlock, /<image/)
  assert.match(heatmapBlock, /agent-iteration-heatmap-basemap/)
  assert.match(heatmapBlock, /agent-iteration-heatmap-loading/)
  assert.match(heatmapBlock, /getAgentIterationPoiAreaHeatmapDisplayBoundaryPoints/)
  assert.match(heatmapBlock, /getAgentIterationPoiAreaHeatmapDisplayCells\(heatmap\)/)
  assert.match(heatmapBlock, /getAgentIterationPoiAreaHeatmapDisplayPoints\(heatmap\)/)
  assert.match(heatmapBlock, /agent-iteration-heatmap-boundary/)
  assert.match(heatmapBlock, /agent-iteration-heatmap-point/)
})

test('agent history template hides empty text while folders are collapsed', async () => {
  const html = await fs.promises.readFile(new URL('../src/pages/analysis/components/sidebar.html', import.meta.url), 'utf8')
  assert.match(html, /!isAgentHistoryGroupCollapsed\(group\.id\) && \(!group\.panels \|\| !group\.panels\.length\)/)
  assert.match(html, /v-else-if="!isAgentHistoryGroupCollapsed\(`\$\{group\.id\}-\$\{panel\.id\}`\)"/)
  assert.match(html, /!isAgentHistoryGroupCollapsed\(group\.id\) && !\(group\.sessions && group\.sessions\.length\) && !\(group\.headingOnly && group\.count > 0\)/)
})

test('agent iteration poi heatmap clusters dense display points', () => {
  const ctx = createAgentContext()
  const points = Array.from({ length: 90 }, (_, idx) => ({
    x: 20 + (idx % 10) * 0.35,
    y: 30 + Math.floor(idx / 10) * 0.35,
  })).concat(Array.from({ length: 20 }, (_, idx) => ({
    x: 70 + (idx % 5) * 0.3,
    y: 18 + Math.floor(idx / 5) * 0.3,
  })))
  ctx.commitAgentIterationPoiPayload({
    status: 'ready',
    area_heatmaps: [{ year: 2025, points }],
  })

  const clustered = ctx.getAgentIterationPoiAreaHeatmapDisplayPoints(ctx.getAgentIterationPoiAreaHeatmaps()[0])

  assert.equal(clustered.length < points.length, true)
  assert.equal(clustered.some((point) => point.count > 1), true)
  assert.equal(clustered.some((point) => point.radius > 2), true)
})

test('agent iteration poi snapshot image keeps small points without baking heatmap cells or boundary', () => {
  const ctx = createAgentContext()
  ctx.buildAgentPoiAreaHeatmapRowsFromProjectedSummaries = () => [{
    points: [{ x: 120, y: 140 }],
    cells: [{ x: 100, y: 120, width: 20, height: 20, intensity: 1 }],
  }]
  const svg = ctx.buildAgentPoiSnapshotOverlaySvg({
    lngLatToContainer(lngLat) {
      const lng = Number(lngLat.lng)
      const lat = Number(lngLat.lat)
      return { x: lng * 10, y: lat * 10 }
    },
  }, {
    year: 2025,
    points: [{ lng: 112.9, lat: 28.1 }],
  }, {
    area_heatmap_polygon: [[112.8, 28.0], [113.0, 28.0], [113.0, 28.2], [112.8, 28.2]],
  })

  assert.doesNotMatch(svg, /#f97316/)
  assert.doesNotMatch(svg, /<rect\b/)
  assert.match(svg, /<circle\b/)
  assert.doesNotMatch(svg, /stroke="#2563eb"/)
  assert.match(svg, /viewBox="0 0 760 760"/)
  assert.match(ctx.getAgentPoiAreaSnapshotCacheKey({ years: [2025], summaries: [], area_heatmap_polygon: [] }), /^basemap-points-v4\|760x760\|/)
})

test('basis drawer fetches current registry config only when history snapshot is missing', async () => {
  const ctx = createAgentContext()
  const calls = []
  global.fetch = async (url) => {
    calls.push(String(url))
    return {
      ok: true,
      json: async () => ({
        prompt_key: 'business_support',
        system_prompt: '当前 registry prompt',
        payload_note: '当前 registry note',
        output_schema: { required: ['reasoning'] },
        evidence_version: 'summary_pack_v1',
      }),
    }
  }

  ctx.openBasisDrawer({
    title: '业态承接依据',
    sourceType: 'ai_checked',
    promptKey: 'business_support',
    aiPrompt: '当前结果没有本次 AI 调用 prompt 快照',
  })
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()

  assert.equal(calls.length, 1)
  assert.equal(ctx.getBasisDrawerPayload().aiPrompt, '当前 registry prompt')
  assert.equal(ctx.getBasisDrawerPayload().aiPromptPayloadNote, '当前 registry note')
  assert.equal(ctx.getBasisDrawerPayload().promptSourceLabel, '当前配置，非历史快照')
})

test('basis drawer does not fetch registry when history prompt snapshot exists', async () => {
  const ctx = createAgentContext()
  let called = false
  global.fetch = async () => {
    called = true
    throw new Error('should not fetch')
  }

  ctx.openBasisDrawer({
    title: '空间结构依据',
    sourceType: 'ai_checked',
    promptKey: 'spatial_structure',
    promptSnapshot: {
      prompt_key: 'spatial_structure',
      system_prompt: '历史真实 prompt',
      payload_note: '历史真实 note',
      output_schema: { required: ['reasoning'] },
    },
    aiPrompt: '历史真实 prompt',
    aiPromptPayloadNote: '历史真实 note',
  })
  await Promise.resolve()

  assert.equal(called, false)
  assert.equal(ctx.getBasisDrawerPayload().aiPrompt, '历史真实 prompt')
  assert.equal(ctx.getBasisDrawerPayload().promptSourceLabel, '')
})

test('iteration basis no longer treats legacy ai_prompt as real prompt without snapshot', () => {
  const ctx = createAgentContext()
  ctx.commitAgentIterationPoiPayload({
    status: 'ready',
    report_title: '业态基础分析总结报告',
    report_sections: [{ heading: '一、总体判断：总量上升', paragraphs: ['总量上升。'] }],
    report_content: '业态基础分析总结报告\n\n一、总体判断：总量上升\n\n总量上升。',
    ai_prompt: '旧字段 system prompt 不应作为真实 prompt',
    ai_prompt_payload_note: '旧字段 note 不应作为真实 note',
  })

  const basis = ctx.buildAgentIterationBasisPayload('poi')

  assert.notEqual(basis.aiPrompt, '旧字段 system prompt 不应作为真实 prompt')
  assert.match(basis.aiPrompt, /没有本次 AI 调用 prompt 快照/)
  assert.equal(basis.aiPromptPayloadNote, '')
  assert.equal(basis.promptSourceLabel, '无本次调用快照')
})

test('copyAgentIterationPoiAreaHeatmapImage composites viewport before ready snapshot', async () => {
  const ctx = createAgentContext()
  ctx.commitAgentIterationPoiPayload({
    status: 'ready',
    area_heatmaps: [{ year: 2025, point_count: 8, top_area: '一区' }],
    area_heatmap_snapshots: [{ year: 2025, image_url: 'data:image/png;base64,ZGF0YQ==', status: 'ready' }],
  })
  const writes = []
  const drawCalls = []
  const originalNavigator = global.navigator
  const originalClipboardItem = global.ClipboardItem
  const originalDocument = global.document
  const originalImage = global.Image
  const originalURL = global.URL
  const originalSerializer = global.XMLSerializer
  Object.defineProperty(global, 'navigator', {
    configurable: true,
    value: {
      clipboard: {
        write: async (items) => writes.push(items),
      },
    },
  })
  global.ClipboardItem = class ClipboardItem {
    constructor(items) {
      this.items = items
    }
  }
  global.Image = class Image {
    set src(value) {
      this._src = value
      if (typeof this.onload === 'function') this.onload()
    }
    get src() {
      return this._src
    }
  }
  global.document = {
    createElement(tag) {
      if (tag === 'canvas') {
        return {
          width: 0,
          height: 0,
          getContext() {
            return {
              fillStyle: '',
              imageSmoothingEnabled: false,
              imageSmoothingQuality: '',
              fillRect() {},
              drawImage(image) {
                drawCalls.push(image && image.src)
              },
            }
          },
          toBlob(callback) {
            callback(new Blob(['composited-first'], { type: 'image/png' }))
          },
        }
      }
      return {}
    },
  }
  global.URL = {
    ...global.URL,
    createObjectURL() {
      return 'blob:overlay-first'
    },
    revokeObjectURL() {},
  }
  global.XMLSerializer = class XMLSerializer {
    serializeToString() {
      return '<svg xmlns="http://www.w3.org/2000/svg"><rect class="agent-iteration-heatmap-cell"></rect></svg>'
    }
  }
  const cardNode = {
    querySelector(selector) {
      if (selector === '.agent-iteration-heatmap-viewport') {
        return {
          className: 'agent-iteration-heatmap-viewport',
          clientWidth: 320,
          clientHeight: 180,
          getBoundingClientRect() {
            return { width: 320, height: 180 }
          },
          querySelector(innerSelector) {
            if (innerSelector === 'img.agent-iteration-heatmap-img') {
              return { getAttribute: () => 'data:image/png;base64,ZGF0YQ==' }
            }
            if (innerSelector === 'svg.agent-iteration-heatmap-svg') {
              return {
                cloneNode() {
                  return {
                    setAttribute() {},
                    querySelectorAll() { return [] },
                  }
                },
              }
            }
            return null
          },
        }
      }
      return null
    },
  }
  try {
    await ctx.copyAgentIterationPoiAreaHeatmapImage({ year: 2025, point_count: 8, top_area: '一区' }, { currentTarget: cardNode })

    assert.equal(writes.length, 1)
    assert.equal(await writes[0][0].items['image/png'].then((blob) => blob.type), 'image/png')
    assert.equal(drawCalls.length, 2)
    assert.equal(drawCalls[1], 'blob:overlay-first')
    assert.equal(ctx.agentIterationSnapshotCopyStatus, '图片已复制')
  } finally {
    Object.defineProperty(global, 'navigator', {
      configurable: true,
      value: originalNavigator,
    })
    global.ClipboardItem = originalClipboardItem
    global.document = originalDocument
    global.Image = originalImage
    global.URL = originalURL
    global.XMLSerializer = originalSerializer
  }
})

test('copyAgentIterationPoiAreaHeatmapImage uses ready snapshot when card node is unavailable', async () => {
  const ctx = createAgentContext()
  ctx.commitAgentIterationPoiPayload({
    status: 'ready',
    area_heatmaps: [{ year: 2025, point_count: 8, top_area: '一区' }],
    area_heatmap_snapshots: [{ year: 2025, image_url: 'data:image/png;base64,ZGF0YQ==', status: 'ready' }],
  })
  const writes = []
  const originalNavigator = global.navigator
  const originalClipboardItem = global.ClipboardItem
  Object.defineProperty(global, 'navigator', {
    configurable: true,
    value: {
      clipboard: {
        write: async (items) => writes.push(items),
      },
    },
  })
  global.ClipboardItem = class ClipboardItem {
    constructor(items) {
      this.items = items
    }
  }
  try {
    await ctx.copyAgentIterationPoiAreaHeatmapImage({ year: 2025, point_count: 8, top_area: '一区' }, { currentTarget: null })

    assert.equal(writes.length, 1)
    assert.equal(await writes[0][0].items['image/png'].then((blob) => blob.type), 'image/png')
    assert.equal(ctx.agentIterationSnapshotCopyStatus, '图片已复制')
  } finally {
    Object.defineProperty(global, 'navigator', {
      configurable: true,
      value: originalNavigator,
    })
    global.ClipboardItem = originalClipboardItem
  }
})

test('agent iteration poi heatmap copy label shows failure state', () => {
  const ctx = createAgentContext()
  ctx.agentIterationSnapshotCopyKey = 'poi-area-2025'
  ctx.agentIterationSnapshotCopyStatus = '图片复制失败，请重试'

  assert.equal(ctx.isAgentIterationPoiAreaHeatmapCopyFailed({ year: 2025 }), true)
  assert.equal(ctx.getAgentIterationPoiAreaHeatmapCopyLabel({ year: 2025 }), '复制失败')
})

test('copyAgentIterationPoiAreaHeatmapImage falls back when viewport composition is unavailable', async () => {
  const ctx = createAgentContext()
  const writes = []
  const originalNavigator = global.navigator
  const originalClipboardItem = global.ClipboardItem
  Object.defineProperty(global, 'navigator', {
    configurable: true,
    value: {
      clipboard: {
        write: async (items) => writes.push(items),
      },
    },
  })
  global.ClipboardItem = class ClipboardItem {
    constructor(items) {
      this.items = items
    }
  }
  let fallbackCalled = false
  ctx.renderAgentIterationSnapshotPngBlob = async () => {
    fallbackCalled = true
    return new Blob(['fallback-image'], { type: 'image/png' })
  }
  const cardNode = {
    querySelector(selector) {
      if (selector === '.agent-iteration-heatmap-viewport') {
        return {
          querySelector() {
            return null
          },
        }
      }
      return null
    },
  }
  try {
    await ctx.copyAgentIterationPoiAreaHeatmapImage({ year: 2025, point_count: 8, top_area: '一区' }, { currentTarget: cardNode })

    assert.equal(fallbackCalled, true)
    assert.equal(writes.length, 1)
    assert.equal(await writes[0][0].items['image/png'].then((blob) => blob.type), 'image/png')
    assert.equal(ctx.agentIterationSnapshotCopyStatus, '图片已复制')
  } finally {
    Object.defineProperty(global, 'navigator', {
      configurable: true,
      value: originalNavigator,
    })
    global.ClipboardItem = originalClipboardItem
  }
})

test('copyAgentIterationPoiAreaHeatmapImage composites visible img and svg', async () => {
  const ctx = createAgentContext()
  const writes = []
  const drawCalls = []
  const originalNavigator = global.navigator
  const originalClipboardItem = global.ClipboardItem
  const originalDocument = global.document
  const originalImage = global.Image
  const originalURL = global.URL
  Object.defineProperty(global, 'navigator', {
    configurable: true,
    value: {
      clipboard: {
        write: async (items) => writes.push(items),
      },
    },
  })
  global.ClipboardItem = class ClipboardItem {
    constructor(items) {
      this.items = items
    }
  }
  global.Image = class Image {
    set src(value) {
      this._src = value
      if (typeof this.onload === 'function') this.onload()
    }
    get src() {
      return this._src
    }
  }
  global.document = {
    createElement(tag) {
      if (tag === 'canvas') {
        return {
          width: 0,
          height: 0,
          getContext() {
            return {
              fillStyle: '',
              imageSmoothingEnabled: false,
              imageSmoothingQuality: '',
              fillRect() {},
              drawImage(image) {
                drawCalls.push(image && image.src)
              },
            }
          },
          toBlob(callback) {
            callback(new Blob(['composited'], { type: 'image/png' }))
          },
        }
      }
      return {}
    },
  }
  global.URL = {
    ...global.URL,
    createObjectURL() {
      return 'blob:overlay-svg'
    },
    revokeObjectURL() {},
  }
  let fallbackCalled = false
  ctx.renderAgentIterationSnapshotPngBlob = async () => {
    fallbackCalled = true
    return null
  }
  const cardNode = {
    querySelector(selector) {
      if (selector === '.agent-iteration-heatmap-viewport') {
        return {
          clientWidth: 320,
          clientHeight: 180,
          getBoundingClientRect() {
            return { width: 320, height: 180 }
          },
          querySelector(innerSelector) {
            if (innerSelector === 'img.agent-iteration-heatmap-img') {
              return { getAttribute: () => 'data:image/png;base64,ZGF0YQ==' }
            }
            if (innerSelector === 'svg.agent-iteration-heatmap-svg') {
              return {
                cloneNode() {
                  return {
                    setAttribute() {},
                    querySelectorAll() { return [] },
                  }
                },
              }
            }
            return null
          },
        }
      }
      return null
    },
  }
  const originalSerializer = global.XMLSerializer
  global.XMLSerializer = class XMLSerializer {
    serializeToString() {
      return '<svg xmlns="http://www.w3.org/2000/svg"><circle cx="10" cy="10" r="4"></circle></svg>'
    }
  }
  try {
    await ctx.copyAgentIterationPoiAreaHeatmapImage({ year: 2025, point_count: 8 }, { currentTarget: cardNode })

    assert.equal(writes.length, 1)
    assert.equal(await writes[0][0].items['image/png'].then((blob) => blob.type), 'image/png')
    assert.equal(drawCalls.length, 2)
    assert.equal(drawCalls[1], 'blob:overlay-svg')
    assert.equal(fallbackCalled, false)
  } finally {
    Object.defineProperty(global, 'navigator', {
      configurable: true,
      value: originalNavigator,
    })
    global.ClipboardItem = originalClipboardItem
    global.document = originalDocument
    global.Image = originalImage
    global.URL = originalURL
    global.XMLSerializer = originalSerializer
  }
})

test('agent iteration poi heatmap css lets svg viewport use dynamic aspect', async () => {
  const css = await fs.promises.readFile(new URL('../src/styles/base.css', import.meta.url), 'utf8')
  const cardBlock = css.slice(css.indexOf('.agent-iteration-heatmap-card'), css.indexOf('.agent-iteration-heatmap-head'))
  const viewportBlock = css.slice(css.indexOf('.agent-iteration-heatmap-viewport'), css.indexOf('.agent-iteration-heatmap-svg'))
  const svgBlock = css.slice(css.indexOf('.agent-iteration-heatmap-svg'), css.indexOf('.agent-iteration-heatmap-boundary'))
  const pointBlock = css.slice(css.indexOf('.agent-iteration-heatmap-point'), css.indexOf('.agent-iteration-heatmap-trend'))
  assert.match(cardBlock, /display:\s*flex/)
  assert.match(cardBlock, /flex-direction:\s*column/)
  assert.doesNotMatch(cardBlock, /grid-template-rows/)
  assert.match(viewportBlock, /flex:\s*0\s+0\s+auto/)
  assert.match(svgBlock, /width:\s*100%/)
  assert.match(svgBlock, /height:\s*100%/)
  assert.match(css, /\.agent-iteration-heatmap-img\s*{[\s\S]*object-fit:\s*fill/)
  assert.match(pointBlock, /#0891b2/)
  assert.doesNotMatch(pointBlock, /#ef4444/)
  assert.match(pointBlock, /stroke-width:\s*0\.68/)
})

test('agent iteration poi area snapshots use tight map framing and hide map chrome', async () => {
  const ctx = createAgentContext()
  ctx.waitForAgentPoiSnapshotPaint = async () => {}
  const originalDocument = global.document
  const originalAMap = global.window.AMap
  const originalHtml2canvas = global.html2canvas
  const calls = { fitPadding: null, zoom: null, ignoredLogo: null, ignoredCopyright: null, capturedCss: '', capturedBackgroundImage: '' }
  const fakeHost = {
    id: '',
    style: { cssText: '' },
    innerHTML: '',
    children: [],
    appendChild(node) { this.children.push(node) },
    querySelectorAll() { return [] },
  }
  global.document = {
    getElementById() { return null },
    createElement(tag) {
      return {
        tag,
        id: '',
        className: '',
        style: { cssText: '', width: '', height: '', backgroundImage: '', backgroundSize: '', backgroundPosition: '', backgroundRepeat: '' },
        children: [],
        appendChild(node) { this.children.push(node) },
        querySelectorAll() { return [] },
        matches(selector) {
          return String(selector).split(',').map((item) => item.trim()).some((selectorItem) => (
            selectorItem === `.${this.className}` || (selectorItem.includes('amap-control') && this.className.includes('amap-control'))
          ))
        },
      }
    },
    body: {
      appendChild(node) { fakeHost.node = node },
    },
  }

  class FakeOverlay {
    constructor(options = {}) { this.options = options }
    setMap(map) { this.map = map }
  }

  global.window.AMap = global.AMap = {
    Map: class {
      constructor(el, options = {}) {
        this.el = el
        this.options = options
      }
      setFitView(overlays, immediate, padding) {
        calls.fitPadding = padding
      }
      lngLatToContainer(lngLat) {
        const lng = Number(lngLat.lng)
        const lat = Number(lngLat.lat)
        return {
          x: 100 + ((lng - 112.8) / 0.2) * 560,
          y: 360 - ((lat - 28.0) / 0.2) * 300,
        }
      }
      getZoom() { return 13 }
      setZoom(zoom) { calls.zoom = zoom }
      destroy() {}
    },
    LngLat: class {
      constructor(lng, lat) {
        this.lng = lng
        this.lat = lat
      }
    },
    Polygon: FakeOverlay,
    Marker: FakeOverlay,
    Pixel: class {
      constructor(x, y) {
        this.x = x
        this.y = y
      }
    },
  }
  global.html2canvas = async (node, options = {}) => {
    calls.capturedCss = node.style.cssText
    calls.capturedBackgroundImage = node.style.backgroundImage
    const logo = document.createElement('div')
    logo.className = 'amap-logo'
    const copyright = document.createElement('div')
    copyright.className = 'amap-copyright'
    calls.ignoredLogo = options.ignoreElements(logo)
    calls.ignoredCopyright = options.ignoreElements(copyright)
    return { toDataURL: () => 'data:image/png;base64,snapshot' }
  }

  try {
    const imageUrl = await ctx.renderAgentIterationPoiAreaSnapshot(
      { year: 2025, points: [{ lng: 112.9, lat: 28.1, category: '餐饮', subcategory: '咖啡厅' }] },
      {
        area_heatmap_basemap: {
          url: 'https://restapi.amap.com/v3/staticmap?test=1',
          size: { width: 760, height: 760 },
        },
        area_heatmap_polygon: [[112.8, 28.0], [113.0, 28.0], [113.0, 28.2], [112.8, 28.2], [112.8, 28.0]],
      },
    )

    assert.equal(imageUrl, 'data:image/png;base64,snapshot')
    assert.deepEqual(calls.fitPadding, [28, 28, 28, 28])
    assert.equal(calls.zoom, null)
    assert.match(calls.capturedCss, /width:760px/)
    assert.match(calls.capturedCss, /height:760px/)
    assert.match(calls.capturedBackgroundImage, /staticmap/)
    assert.equal(calls.ignoredLogo, true)
    assert.equal(calls.ignoredCopyright, true)
  } finally {
    global.document = originalDocument
    global.window.AMap = originalAMap
    global.AMap = originalAMap
    global.html2canvas = originalHtml2canvas
  }
})

test('agent iteration poi snapshot waits for basemap images before capture', async () => {
  const ctx = createAgentContext()
  const originalImage = global.Image
  const loaded = []
  global.Image = class {
    set crossOrigin(value) {
      this._crossOrigin = value
    }
    set src(value) {
      this._src = value
      loaded.push(value)
      setTimeout(() => this.onload && this.onload(), 0)
    }
    decode() {
      return Promise.resolve()
    }
  }

  try {
    const root = {
      tagName: 'DIV',
      style: { backgroundImage: 'url("https://tiles.example/base.png")' },
      querySelectorAll() {
        return [{
          tagName: 'IMG',
          currentSrc: 'https://tiles.example/tile.png',
          style: { backgroundImage: '' },
        }]
      },
    }
    const ready = await ctx.waitForAgentPoiSnapshotImages(root, 1000)

    assert.equal(ready, true)
    assert.deepEqual(loaded, ['https://tiles.example/base.png', 'https://tiles.example/tile.png'])
  } finally {
    global.Image = originalImage
  }
})

test('agent iteration poi snapshot marks failed when fallback basemap image cannot load', async () => {
  const ctx = createAgentContext()
  ctx.renderAgentIterationPoiAreaSnapshot = async () => {
    throw new Error('basemap_image_load_failed')
  }

  const payload = await ctx.ensureAgentIterationPoiAreaHeatmapSnapshots({
    status: 'ready',
    historyId: 'history-basemap-failure',
    years: [2020],
    summaries: [
      { year: 2020, points: [{ lng: 112.9, lat: 28.1 }], top_areas: [{ name: 'A' }] },
    ],
    area_heatmaps: [
      { year: 2020, point_count: 1 },
    ],
    area_heatmap_basemap: {
      url: 'https://tiles.example/basemap.png',
      size: { width: 760, height: 760 },
    },
    area_heatmap_polygon: [[112.8, 28.0], [113.0, 28.0], [113.0, 28.2], [112.8, 28.2], [112.8, 28.0]],
  })

  const snapshot = payload.area_heatmap_snapshots[0]
  assert.equal(snapshot.status, 'failed')
  assert.equal(snapshot.image_url, '')
  assert.equal(snapshot.error, 'basemap_image_load_failed')
})

test('agent iteration poi area snapshots are committed progressively', async () => {
  const ctx = createAgentContext()
  const commits = []
  const originalCommit = ctx.commitAgentIterationPoiPayload.bind(ctx)
  ctx.commitAgentIterationPoiPayload = (patch = {}, options = {}) => {
    const result = originalCommit(patch, options)
    if (Array.isArray(patch.area_heatmap_snapshots)) {
      commits.push(patch.area_heatmap_snapshots.map((item) => ({
        year: item.year,
        status: item.status,
        hasImage: Boolean(item.image_url),
      })))
    }
    return result
  }
  ctx.renderAgentIterationPoiAreaSnapshot = async (summary) => `data:image/png;base64,${summary.year}`

  await ctx.ensureAgentIterationPoiAreaHeatmapSnapshots({
    status: 'ready',
    historyId: 'history-progressive',
    years: [2020, 2022, 2024],
    summaries: [
      { year: 2020, points: [{ lng: 112.9, lat: 28.1 }], top_areas: [{ name: 'A' }] },
      { year: 2022, points: [{ lng: 112.91, lat: 28.11 }], top_areas: [{ name: 'B' }] },
      { year: 2024, points: [{ lng: 112.92, lat: 28.12 }], top_areas: [{ name: 'C' }] },
    ],
    area_heatmaps: [
      { year: 2020, point_count: 1 },
      { year: 2022, point_count: 1 },
      { year: 2024, point_count: 1 },
    ],
    area_heatmap_polygon: [[112.8, 28.0], [113.0, 28.0], [113.0, 28.2], [112.8, 28.2], [112.8, 28.0]],
  })

  assert.deepEqual(commits[0].map((item) => item.status), ['pending', 'pending', 'pending'])
  assert.deepEqual(commits[1].map((item) => item.status), ['loading', 'pending', 'pending'])
  assert.equal(commits[2][0].hasImage, true)
  assert.deepEqual(commits[3].map((item) => item.status), ['ready', 'loading', 'pending'])
  assert.equal(commits[4][1].hasImage, true)
  assert.deepEqual(commits.at(-1).map((item) => item.status), ['ready', 'ready', 'ready'])
})

test('agent iteration poi merges structure and spatial rows with filters and sorting', () => {
  const ctx = createAgentContext()
  ctx.agentIterationPoiStructureSpatialView = { category: '', sortBy: 'count', spatialOnly: false }
  ctx.commitAgentIterationPoiPayload({
    status: 'ready',
    summaries: [{
      year: 2025,
      count: 18,
      subcategory_count: 4,
      category_counts: { 餐饮: 12, 购物: 6 },
      top_subcategories: [
        { name: '咖啡厅', parent: '餐饮', count: 7, ratio: 7 / 18 },
        { name: '火锅', parent: '餐饮', count: 5, ratio: 5 / 18 },
        { name: '商场', parent: '购物', count: 4, ratio: 4 / 18 },
        { name: '便利店', parent: '购物', count: 2, ratio: 2 / 18 },
      ],
      category_to_subcategory_mix: {
        餐饮: [
          { name: '咖啡厅', parent: '餐饮', count: 7 },
          { name: '火锅', parent: '餐饮', count: 5 },
        ],
        购物: [
          { name: '商场', parent: '购物', count: 4 },
          { name: '便利店', parent: '购物', count: 2 },
        ],
      },
    }],
    subcategory_spatial_trend_rows: [
      {
        name: '咖啡厅',
        parent: '餐饮',
        delta: 3,
        dominant_direction: '东北',
        dominant_ring: '中圈层',
        centroid_shift_direction: '东北',
        centroid_shift_m: 120,
        hotspot_grid_count: 2,
        hotspot_grid_count_delta: 1,
        top_area: '三区',
      },
      {
        name: '商场',
        parent: '购物',
        delta: -4,
        dominant_direction: '西南',
        hotspot_grid_count: 1,
        top_area: '二区',
      },
    ],
  })

  const rows = ctx.getAgentIterationPoiStructureSpatialRows()
  assert.equal(rows.length, 4)
  assert.equal(rows.find((row) => row.name === '咖啡厅').dominantDirection, '东北')
  assert.equal(rows.find((row) => row.name === '咖啡厅').hasSpatialSignal, true)
  assert.equal(rows.find((row) => row.name === '火锅').hasSpatialSignal, false)

  let groups = ctx.getAgentIterationPoiStructureSpatialGroups()
  assert.equal(groups.length, 2)
  assert.deepEqual(groups[0].rows.map((row) => row.name), ['咖啡厅', '火锅'])

  ctx.setAgentIterationPoiStructureSpatialViewPatch({ category: '购物' })
  groups = ctx.getAgentIterationPoiStructureSpatialGroups()
  assert.equal(groups.length, 1)
  assert.equal(groups[0].category, '购物')
  assert.deepEqual(groups[0].rows.map((row) => row.name), ['商场', '便利店'])

  ctx.setAgentIterationPoiStructureSpatialViewPatch({ category: '', sortBy: 'ratio' })
  assert.equal(ctx.getAgentIterationPoiStructureSpatialGroups()[0].rows[0].name, '咖啡厅')

  ctx.setAgentIterationPoiStructureSpatialViewPatch({ sortBy: 'abs_delta' })
  groups = ctx.getAgentIterationPoiStructureSpatialGroups()
  assert.equal(groups.find((group) => group.category === '购物').rows[0].name, '商场')

  ctx.setAgentIterationPoiStructureSpatialViewPatch({ sortBy: 'growth' })
  assert.equal(ctx.getAgentIterationPoiStructureSpatialGroups()[0].rows[0].name, '咖啡厅')

  ctx.setAgentIterationPoiStructureSpatialViewPatch({ sortBy: 'decrease' })
  groups = ctx.getAgentIterationPoiStructureSpatialGroups()
  assert.equal(groups.find((group) => group.category === '购物').rows[0].name, '商场')

  ctx.setAgentIterationPoiStructureSpatialViewPatch({ spatialOnly: true })
  const spatialOnlyRows = ctx.getAgentIterationPoiStructureSpatialGroups().flatMap((group) => group.rows)
  assert.deepEqual(spatialOnlyRows.map((row) => row.name).sort(), ['咖啡厅', '商场'])
})

test('agent iteration poi trend template does not duplicate structure spatial table', async () => {
  const html = await fs.promises.readFile(new URL('../src/pages/analysis/components/main.html', import.meta.url), 'utf8')
  const trendStart = html.indexOf("isAgentIterationSecondaryView('trend')")
  const spaceStart = html.indexOf("isAgentIterationSecondaryView('space')", trendStart)
  const block = html.slice(trendStart, spaceStart)
  assert.doesNotMatch(block, /agent-iteration-poi-structure-spatial-card/)
  assert.doesNotMatch(block, /小类空间变化/)
})

test('agent iteration poi space template shows all poi heatmap before subcategory spatial table', async () => {
  const html = await fs.promises.readFile(new URL('../src/pages/analysis/components/main.html', import.meta.url), 'utf8')
  const spaceStart = html.indexOf("isAgentIterationSecondaryView('space')")
  const detailStart = html.indexOf("isAgentIterationSecondaryView('detail')", spaceStart)
  const block = html.slice(spaceStart, detailStart)
  const heatmapIndex = block.indexOf('agent-iteration-heatmap-grid')
  const subcategoryIndex = block.indexOf('agent-iteration-poi-structure-spatial-card')
  assert.ok(heatmapIndex >= 0)
  assert.ok(subcategoryIndex > heatmapIndex)
  assert.match(block, /agent-iteration-poi-structure-spatial-card/)
  assert.match(block, /isAgentIterationPoiSpatialSignalLoading\(\)/)
})

test('agent process and context loading use frameless scan state classes', async () => {
  const html = await fs.promises.readFile(new URL('../src/pages/analysis/components/main.html', import.meta.url), 'utf8')
  const css = await fs.promises.readFile(new URL('../src/styles/analysis-page.css', import.meta.url), 'utf8')

  assert.match(html, /'is-agent-pending': String\(message\.id \|\| ''\)\.startsWith\('analysis-quick-ask-pending'\)/)
  assert.match(html, /'is-loading': agentLoading/)
  assert.match(html, /context-ask-message is-assistant is-loading/)
  assert.match(css, /@keyframes agent-soft-scan/)
  assert.match(css, /\.agent-thinking-bubble\.is-loading::after/)
  assert.match(css, /\.agent-process-flow-item\.is-active::after/)
  assert.match(css, /\.agent-message-bubble\.is-agent-pending::after/)
  assert.match(css, /\.agent-thinking-bubble\s*\{[^}]*background:\s*transparent/s)
  assert.match(css, /\.agent-thinking-bubble\s*\{[^}]*border-color:\s*transparent/s)
  assert.match(css, /\.agent-thinking-bubble\s*\{[^}]*box-shadow:\s*none/s)
  assert.match(css, /\.agent-process-flow-item\s*\{[^}]*background:\s*transparent/s)
  assert.doesNotMatch(css, /\.agent-process-flow-item\s*\{[^}]*box-shadow:/s)
  assert.doesNotMatch(css, /\.agent-process-flow-item\s*\{[^}]*border:/s)
  assert.doesNotMatch(css, /\.agent-message-bubble\.is-agent-pending\s*\{[^}]*background:\s*transparent/s)
  assert.match(css, /\.context-ask-message\.is-loading \.context-ask-bubble::after/)
  assert.match(css, /prefers-reduced-motion: reduce/)
  assert.doesNotMatch(css, /context-ask-message\.is-assistant:last-child \.context-ask-bubble::after/)
})

test('iteration change ready payloads are reused unless force refresh is requested', async () => {
  const ctx = createAgentContext({
    currentHistoryRecordId: 'history-1',
    currentHistoryAvailablePoiYears: [2023, 2024],
  })
  let snapshotCalls = 0
  ctx.ensureAgentIterationPoiAreaHeatmapSnapshots = async () => {
    snapshotCalls += 1
  }
  ctx.createAgentIterationChangeTab({ autoload: false })
  ctx.commitAgentIterationPoiPayload({ status: 'ready', years: [2023, 2024], summaries: [{ year: 2024, count: 2 }] })
  ctx.commitAgentIterationPopulationPayload({ status: 'ready', period: '2024-2026', series: [{ year: 2024 }] })
  ctx.commitAgentIterationNightlightPayload({ status: 'ready', years: [2023, 2024, 2025], snapshots: [{ year: 2025, image_url: 'data:image/png;base64,2025' }] })

  const calls = []
  global.fetch = async (url, options = {}) => {
    calls.push({ url, body: options.body ? JSON.parse(options.body) : null })
    if (String(url).includes('/api/v1/analysis/agent/iteration/poi/build')) {
      return { ok: true, json: async () => ({ status: 'ready', source: 'history', years: [2023, 2024], summaries: [{ year: 2024, count: 1 }], report_sections: [], report_content: '', error: '' }) }
    }
    if (String(url).includes('/api/v1/analysis/agent/iteration/poi/interpret')) {
      return { ok: true, json: async () => ({ status: 'ready', report_title: '业态基础分析总结报告', report_sections: [{ heading: '一、总体判断', paragraphs: ['报告完成。'] }], report_content: '报告完成。', error: '' }) }
    }
    throw new Error(`unexpected fetch ${url}`)
  }

  await ctx.ensureAgentIterationKind('poi')
  await ctx.ensureAgentIterationKind('population')
  await ctx.ensureAgentIterationKind('nightlight')
  assert.equal(calls.length, 0)
  assert.equal(snapshotCalls, 1)

  await ctx.ensureAgentIterationKind('poi', true)
  assert.equal(calls.filter((item) => String(item.url).includes('/api/v1/analysis/agent/iteration/poi/build')).length, 1)
  assert.equal(calls.filter((item) => String(item.url).includes('/api/v1/analysis/history/history-1/pois')).length, 0)
  assert.equal(calls.filter((item) => String(item.url).includes('/api/v1/analysis/agent/iteration/poi/interpret')).length, 1)
})

test('iteration async result is saved to its tab after switching away', async () => {
  const ctx = createAgentContext({
    currentHistoryRecordId: 'history-1',
    currentHistoryAvailablePoiYears: [2023, 2024],
  })
  const iterationTabId = ctx.createAgentIterationChangeTab({ autoload: false })
  const summaryTabId = ctx.createAgentSummaryTab()
  ctx.switchAgentTopTab(iterationTabId)

  let resolveFirstPoi = null
  const calls = []
  global.fetch = async (url, options = {}) => {
    calls.push({ url, body: options.body ? JSON.parse(options.body) : null })
    if (String(url).includes('/api/v1/analysis/agent/iteration/poi/build')) {
      await new Promise((resolve) => { resolveFirstPoi = resolve })
      return { ok: true, json: async () => ({ status: 'ready', source: 'history', years: [2023, 2024], summaries: [{ year: 2024, count: 1 }], report_sections: [], report_content: '', error: '' }) }
    }
    throw new Error(`unexpected fetch ${url}`)
  }

  const loading = ctx.ensureAgentIterationPoi(true)
  await Promise.resolve()
  ctx.switchAgentTopTab(summaryTabId)
  resolveFirstPoi()
  await loading
  ctx.switchAgentTopTab(iterationTabId)

  assert.equal(ctx.getAgentIterationPoiPayload().status, 'ready')
  assert.equal(ctx.agentIterationPoiLoading, false)
  const iterationTab = ctx.agentTabs.iterationChangeTabs.find((item) => item.id === iterationTabId)
  assert.equal(((iterationTab.panelPayloads.iteration_change || {}).poi || {}).status, 'ready')
  calls.length = 0
  await ctx.ensureAgentIterationPoi()
  assert.equal(calls.length, 0)
})

test('history switch resets iteration payloads without touching summary payloads or fetching', async () => {
  const ctx = createAgentContext({
    currentHistoryRecordId: 'history-a',
    agentPanelPayloads: {
      summary_pack: buildSummaryPack('历史 A 总结'),
      iteration_change: {
        poi: { status: 'ready', years: [2023, 2024], summaries: [{ year: 2024, count: 8 }] },
        population: { status: 'ready', period: '2024-2026', series: [{ year: 2026 }] },
        nightlight: { status: 'ready', years: [2023, 2024, 2025], snapshots: [{ year: 2025 }] },
      },
    },
  })
  ctx.createAgentIterationChangeTab({ autoload: false })
  ctx.agentIterationPoiLoading = true
  ctx.agentIterationPoiError = 'old poi error'
  ctx.agentIterationPopulationLoading = true
  ctx.agentIterationPopulationError = 'old population error'
  ctx.agentIterationNightlightLoading = true
  ctx.agentIterationNightlightError = 'old nightlight error'
  let fetchCalled = false
  global.fetch = async () => {
    fetchCalled = true
    throw new Error('reset should not fetch')
  }

  const changed = ctx.resetAgentIterationChangeForHistorySwitch('history-b', { previousHistoryId: 'history-a' })

  assert.equal(changed, true)
  assert.equal(fetchCalled, false)
  assert.equal(ctx.agentPanelPayloads.summary_pack.headline_judgment.summary, '历史 A 总结')
  assert.equal(ctx.getAgentIterationPoiPayload().status, 'idle')
  assert.equal(ctx.getAgentIterationPoiPayload().historyId, 'history-b')
  assert.equal(ctx.getAgentIterationPoiPayload().notice, '已切换历史记录，请重新生成多年迭代变化。')
  assert.equal(ctx.getAgentIterationPopulationPayload().status, 'idle')
  assert.equal(ctx.getAgentIterationNightlightPayload().status, 'idle')
  assert.equal(ctx.agentIterationPoiLoading, false)
  assert.equal(ctx.agentIterationPoiError, '')
  assert.equal(ctx.agentIterationPopulationLoading, false)
  assert.equal(ctx.agentIterationPopulationError, '')
  assert.equal(ctx.agentIterationNightlightLoading, false)
  assert.equal(ctx.agentIterationNightlightError, '')
  const iterationTab = ctx.agentTabs.iterationChangeTabs[0]
  assert.equal(iterationTab.panelPayloads.iteration_change.poi.status, 'idle')
  assert.equal(iterationTab.panelPayloads.iteration_change.nightlight.history_id, 'history-b')
})

test('history switch keeps iteration payload when history id is unchanged', () => {
  const ctx = createAgentContext({
    currentHistoryRecordId: 'history-a',
    agentPanelPayloads: {
      summary_pack: buildSummaryPack('历史 A 总结'),
      iteration_change: {
        poi: { status: 'ready', years: [2023, 2024], summaries: [{ year: 2024, count: 8 }] },
      },
    },
  })
  ctx.createAgentIterationChangeTab({ autoload: false })

  const changed = ctx.resetAgentIterationChangeForHistorySwitch('history-a', { previousHistoryId: 'history-a' })
  const iterationTab = ctx.agentTabs.iterationChangeTabs[0]

  assert.equal(changed, false)
  assert.equal(iterationTab.panelPayloads.iteration_change.poi.status, 'ready')
  assert.deepEqual(iterationTab.panelPayloads.iteration_change.poi.years, [2023, 2024])
})

test('iteration change payload survives agent tab ui state restore', () => {
  const ctx = createAgentContext()
  ctx.createAgentIterationChangeTab({ autoload: false })
  ctx.commitAgentIterationNightlightPayload({
    status: 'ready',
    years: [2023, 2024, 2025],
    period: '2023-2025',
    snapshots: [{ year: 2025, image_url: 'data:image/png;base64,2025' }],
  })
  const uiState = ctx.buildAgentTabsUiState()
  delete uiState.iteration_change_tabs[0].activeKind
  delete uiState.iteration_change_tabs[0].active_kind

  const restored = createAgentContext({
    agentPanelPayloads: {
      agent_tabs: uiState,
      iteration_change: ctx.agentPanelPayloads.iteration_change,
    },
  })
  restored.restoreAgentTabsFromSession({ panelPayloads: restored.agentPanelPayloads })
  restored.switchAgentTopTab(uiState.iteration_change_tabs[0].id)

  assert.equal(restored.isAgentIterationChangeTabActive(), true)
  assert.deepEqual(restored.getAgentIterationNightlightPayload().years, [2023, 2024, 2025])
  assert.equal(restored.getAgentIterationNightlightPayload().snapshots[0].year, 2025)
  assert.equal(restored.agentIterationActiveKind, 'poi')

  uiState.iteration_change_tabs[0].activeKind = 'nightlight'
  const restoredWithKind = createAgentContext({
    agentPanelPayloads: {
      agent_tabs: uiState,
      iteration_change: ctx.agentPanelPayloads.iteration_change,
    },
  })
  restoredWithKind.restoreAgentTabsFromSession({ panelPayloads: restoredWithKind.agentPanelPayloads })
  restoredWithKind.switchAgentTopTab(uiState.iteration_change_tabs[0].id)
  assert.equal(restoredWithKind.agentIterationActiveKind, 'nightlight')
})

test('summary history opens directly into that historical summary tab', async () => {
  const currentPack = buildSummaryPack('当前范围总结')
  const historyPack = buildSummaryPack('历史 A 总结')
  const ctx = createAgentContext({
    currentHistoryRecordId: 'history-current',
    agentPanelPayloads: { summary_pack: currentPack },
    agentSessions: [
      {
        ...ctxSessionBase('summary-history-a', '旧标题'),
        persisted: true,
        snapshotLoaded: false,
        historyId: 'history-current',
        panelKind: 'commercial_summary',
      },
    ],
    agentSessionsLoaded: true,
  })

  global.fetch = async (url) => {
    if (String(url).includes('/api/v1/analysis/agent/sessions/summary-history-a')) {
      return {
        ok: true,
        async json() {
          return {
            id: 'summary-history-a',
            title: '旧标题',
            preview: '旧预览',
            history_id: 'history-current',
            panel_kind: 'commercial_summary',
            status: 'answered',
            output: {
              panel_payloads: {
                summary_pack: historyPack,
                summary_status: { status: 'ready', generated: true, title: '区域总结' },
              },
            },
            diagnostics: {},
            messages: [],
            created_at: '2026-04-05T00:00:00Z',
            updated_at: '2026-04-05T01:00:00Z',
          }
        },
      }
    }
    return { ok: true, async json() { return { data_readiness: { checked: true, ready: true, missing_tasks: [] } } } }
  }

  const activeTabId = await ctx.openAgentHistorySessionTab('summary-history-a')

  assert.equal(activeTabId, 'summary-history-summary-history-a')
  assert.equal(ctx.isAgentSummaryTabActive(), true)
  assert.equal(ctx.agentPanelPayloads.summary_pack.headline_judgment.summary, '历史 A 总结')
  assert.equal(ctx.getAgentActiveSummaryPanelPayloads().summary_pack.headline_judgment.summary, '历史 A 总结')
  assert.equal(ctx.getAgentActiveTopTab().source, 'history')
  assert.equal(ctx.getAgentSessionTitle(ctx.findAgentSession('summary-history-a')), '总结')
})

test('summary history list hydrates detail payloads for compact titles and previews', async () => {
  const historyPack = buildSummaryPack('该区域是一个以年轻人群日常消费和科教文化配套为主的多核商业区。')
  historyPack.headline_judgment.supporting_clause = '餐饮、科教和日常消费共同支撑多核结构。'
  const ctx = createAgentContext()
  const calls = []
  global.fetch = async (url) => {
    calls.push(String(url))
    if (String(url) === '/api/v1/analysis/agent/sessions') {
      return {
        ok: true,
        async json() {
          return [
            {
              id: 'summary-history-a',
              title: '该区域是一个以年轻人群日常消费和科教文化配套为主的多核商业区。',
              preview: '开始一份新的区域分析',
              history_id: 'history-current',
              panel_kind: 'commercial_summary',
              status: 'answered',
              title_source: 'fallback',
              created_at: '2026-04-05T00:00:00Z',
              updated_at: '2026-04-05T01:00:00Z',
            },
          ]
        },
      }
    }
    if (String(url).includes('/api/v1/analysis/agent/sessions/summary-history-a')) {
      return {
        ok: true,
        async json() {
          return {
            id: 'summary-history-a',
            title: '该区域是一个以年轻人群日常消费和科教文化配套为主的多核商业区。',
            preview: '开始一份新的区域分析',
            history_id: 'history-current',
            panel_kind: 'commercial_summary',
            status: 'answered',
            output: {
              panel_payloads: {
                summary_pack: historyPack,
                summary_status: { status: 'ready', generated: true },
              },
            },
            diagnostics: {},
            messages: [],
            created_at: '2026-04-05T00:00:00Z',
            updated_at: '2026-04-05T01:00:00Z',
          }
        },
      }
    }
    throw new Error(`unexpected fetch ${url}`)
  }

  await ctx.loadAgentSessionSummaries(true)
  await ctx.agentSummaryHistoryHydrationPromise

  const session = ctx.findAgentSession('summary-history-a')
  assert.equal(ctx.getAgentSessionTitle(session), '总结')
  assert.equal(ctx.getAgentSessionPreview(session), '餐饮、科教和日常消费共同支撑多核结构。')
  assert.ok(calls.some((url) => url.includes('/summary-history-a')))
})

test('agent analysis snapshot includes population grid sex difference evidence', () => {
  const ctx = createAgentContext({
    populationOverview: {
      summary: {
        total_population: 300,
        male_total: 160,
        female_total: 140,
      },
    },
    populationLayer: {
      cells: [
        { cell_id: 'r0_c0', value: 180 },
        { cell_id: 'r0_c1', value: 120 },
      ],
    },
    populationSexSourceLayers: {
      scope_id: 'scope-1',
      male: { cells: [{ cell_id: 'r0_c0', value: 100 }, { cell_id: 'r0_c1', value: 60 }] },
      female: { cells: [{ cell_id: 'r0_c0', value: 80 }, { cell_id: 'r0_c1', value: 70 }] },
    },
    poiGridFeatures: [
      { type: 'Feature', properties: { cell_id: 'r0_c0', poi_count: 5, density_poi_per_km2: 20, dominant_category_name: '餐饮' } },
    ],
    nightlightLayer: {
      cells: [{ cell_id: 'r0_c0', value: 12, class_label: '高亮' }],
    },
  })

  const snapshot = ctx.buildAgentAnalysisSnapshot()
  const populationGrid = snapshot.population.grid_evidence
  const overlap = snapshot.shared_grid.top_coupled_cells[0]

  assert.equal(snapshot.shared_grid.evidence_version, 'shared_grid_evidence_v1')
  assert.equal(snapshot.shared_grid.join_key, 'cell_id')
  assert.deepEqual(snapshot.shared_grid.uses, ['population', 'poi_raster', 'nightlight'])
  assert.equal(populationGrid.evidence_level, 'cell_id_population_and_sex')
  assert.equal(populationGrid.top_abs_sex_diff_cells[0].cell_id, 'r0_c0')
  assert.equal(populationGrid.top_abs_sex_diff_cells[0].sex_diff_value, 20)
  assert.equal(overlap.cell_id, 'r0_c0')
  assert.equal(overlap.male_value, 100)
  assert.equal(overlap.female_value, 80)
  assert.equal(overlap.sex_diff_value, 20)
  assert.equal(overlap.coupling_type, 'high_pop_high_poi_high_light')
  assert.ok(!Object.prototype.hasOwnProperty.call(snapshot.shared_grid, 'top_overlap_cells'))
  assert.ok(!Object.prototype.hasOwnProperty.call(snapshot.shared_grid, 'mismatch_signals'))
})

test('agent analysis snapshot keeps poi raster out of summary evidence', () => {
  const ctx = createAgentContext({
    poiGridType: 'raster',
    poiDataSource: 'local',
    resultDataSource: 'local',
    poiYearSource: '2024',
    h3GridResolution: 9,
    h3NeighborRing: 2,
    h3GridIncludeMode: 'intersects',
    h3GridMinOverlapRatio: 0.35,
    poiGridSummary: {
      grid_count: 4,
      active_cell_count: 2,
      assigned_poi_count: 10,
      max_poi_count: 6,
      avg_density_poi_per_km2: 25.5,
    },
    poiGridFeatures: [
      { type: 'Feature', properties: { cell_id: 'r0_c0', poi_count: 6 } },
    ],
    h3AnalysisSummary: {
      grid_count: 8,
      poi_count: 10,
      avg_density_poi_per_km2: 18.2,
      avg_local_entropy: 0.4,
    },
  })

  const snapshot = ctx.buildAgentAnalysisSnapshot()

  assert.equal(snapshot.poi_summary.total, 0)
  assert.equal(snapshot.poi_summary.grid_evidence, undefined)
  assert.equal(snapshot.pois.length, 0)
  assert.equal(snapshot.h3.poi_h3_evidence.evidence_version, 'poi_h3_evidence_v1')
  assert.equal(snapshot.h3.poi_h3_evidence.grid_type, 'h3')
  assert.equal(snapshot.h3.poi_h3_evidence.params.h3_resolution, 9)
  assert.equal(snapshot.h3.poi_h3_evidence.params.neighbor_ring, 2)
  assert.equal(snapshot.h3.poi_h3_evidence.params.min_overlap_ratio, 0.35)
  assert.equal(snapshot.h3.poi_h3_evidence.counts.grid_count, 8)
  assert.equal(snapshot.param_bundles.poi_h3_grid.params.h3_resolution, 9)
  assert.equal(snapshot.param_bundles.poi_raster_grid.params.grid_type, 'shared_raster')
  assert.equal(snapshot.param_bundles.poi_fetch.params.year, 2024)
  assert.equal(snapshot.param_bundles.population.task_key, 'population')
  assert.equal(snapshot.h3.grid_params.h3_resolution, 9)
})

test('analysis snapshot evidence module owns h3 and shared-grid contracts', () => {
  const ctx = createAgentContext({
    h3GridResolution: 9,
    h3NeighborRing: 2,
    h3GridIncludeMode: 'intersects',
    h3GridMinOverlapRatio: 0.35,
    h3AnalysisSummary: {
      grid_count: 3,
      poi_count: 11,
      avg_density_poi_per_km2: 18,
      avg_local_entropy: 0.45,
    },
    h3AnalysisGridFeatures: [
      { type: 'Feature', properties: { h3_id: 'h3-a', poi_count: 4, density_poi_per_km2: 9, gi_star_z_score: 2.2 } },
    ],
    h3DerivedStats: {
      lqSummary: { rows: [{ h3_id: 'h3-a', lq_target: 1.4 }], total: 1 },
    },
    populationLayer: { cells: [{ cell_id: 'r0_c0', value: 100 }] },
    poiGridFeatures: [{ type: 'Feature', properties: { cell_id: 'r0_c0', poi_count: 7 } }],
    nightlightLayer: { cells: [{ cell_id: 'r0_c0', value: 12 }] },
  })

  const h3Evidence = buildAgentPoiH3Evidence(ctx)
  const snapshot = buildAgentAnalysisSnapshot(ctx)

  assert.equal(h3Evidence.evidence_version, 'poi_h3_evidence_v1')
  assert.equal(h3Evidence.cells[0].h3_id, 'h3-a')
  assert.equal(h3Evidence.derived_stats.lq_rows[0].lq_target, 1.4)
  assert.equal(snapshot.h3.poi_h3_evidence.evidence_version, 'poi_h3_evidence_v1')
  assert.equal(snapshot.shared_grid.evidence_version, 'shared_grid_evidence_v1')
  assert.equal(snapshot.shared_grid.top_coupled_cells[0].cell_id, 'r0_c0')
  assert.equal(snapshot.param_bundles.poi_h3_grid.params.min_overlap_ratio, 0.35)
})

function ctxSessionBase(id, title) {
  return {
    id,
    title,
    preview: '开始一份新的区域分析',
    status: 'idle',
    input: '',
    cards: [],
    executionTrace: [],
    usedTools: [],
    citations: [],
    researchNotes: [],
    nextSuggestions: [],
    clarificationQuestion: '',
    riskPrompt: '',
    error: '',
    riskConfirmations: [],
    messages: [],
    createdAt: '2026-04-05T00:00:00Z',
    updatedAt: '2026-04-05T00:00:00Z',
    pinnedAt: '',
    isPinned: false,
  }
}

test.after(() => {
  global.window = undefined
  global.fetch = undefined
  global.alert = undefined
  global.confirm = undefined
})

global.window = globalThis
global.alert = () => {}
global.confirm = () => true
