import fs from 'node:fs'
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  createAnalysisAgentInitialState,
  createAnalysisAgentSessionMethods,
  deriveAgentSessionPreview,
  getAnalysisTaskDefinition,
  resolveAnalysisTaskKeyFromTrace,
  normalizeAgentToolSummary,
  normalizeAgentTurnPayload,
  sortAgentSessions,
} from '../src/features/agent/sessions.js'

const agentMethods = createAnalysisAgentSessionMethods()

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

function createAgentContext(overrides = {}) {
  const state = createAnalysisAgentInitialState()
  const ctx = {
    ...state,
    ...agentMethods,
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
      cards: [{ type: 'summary', title: '概览', content: '这里以社区商业为主', items: [] }],
      next_suggestions: ['继续看路网'],
      panel_payloads: { h3_result: { summary: { grid_count: 8 } } },
      decision: { summary: '适合继续预研', mode: 'action', strength: 'moderate', can_act: true },
      support: [{ key: 'poi_count', metric: 'poi_count', headline: 'POI 样本量 12', interpretation: '供给样本够用', source: 'analysis_snapshot.poi_summary', confidence: 'moderate', limitation: '不能直接推断收益', supports: ['core_judgment'], is_key: true }],
      counterpoints: [{ kind: 'missing', title: '仍缺证据', detail: '当前仍缺少路网概览。' }],
      actions: [{ title: '补齐路网证据', detail: '先补跑路网分析', condition: '当要做更强判断时', target: 'evidence_gap', prompt: '补齐路网概览再判断' }],
      boundary: [{ title: '适用边界', detail: '不能直接推断经营收益。' }],
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
      followup_steps: [],
      followup_applied: false,
      summary: '先读取范围，再分析业态结构',
    },
  })

  assert.equal(normalized.output.cards[0].content, '这里以社区商业为主')
  assert.equal(normalized.output.panelPayloads.h3_result.summary.grid_count, 8)
  assert.equal(normalized.output.decision.mode, 'action')
  assert.equal(normalized.output.decision.canAct, true)
  assert.equal(normalized.output.support[0].headline, 'POI 样本量 12')
  assert.equal(normalized.output.counterpoints[0].kind, 'missing')
  assert.equal(normalized.output.actions[0].prompt, '补齐路网概览再判断')
  assert.equal(normalized.output.boundary[0].detail, '不能直接推断经营收益。')
  assert.deepEqual(normalized.diagnostics.usedTools, ['read_current_scope'])
  assert.deepEqual(normalized.diagnostics.auditIssues, ['不能直接推断经营收益'])
  assert.equal(normalized.diagnostics.planningSummary, '先读取范围，再分析业态结构')
  assert.equal(normalized.diagnostics.auditSummary, '证据完整，可直接回答')
  assert.equal(normalized.diagnostics.replanCount, 1)
  assert.equal(normalized.diagnostics.thinkingTimeline[0].id, 'thinking-1')
  assert.equal(normalized.contextSummary.active_panel, 'agent')
  assert.equal(normalized.plan.summary, '先读取范围，再分析业态结构')
})

test('normalizeAgentTurnPayload keeps backward compatibility when structured output is absent', () => {
  const normalized = normalizeAgentTurnPayload({
    status: 'answered',
    output: {
      cards: [{ type: 'summary', title: '概览', content: '这里只能先做方向性判断', items: [] }],
    },
  })

  assert.equal(normalized.output.decision.summary, '')
  assert.deepEqual(normalized.output.support, [])
  assert.deepEqual(normalized.output.actions, [])
  assert.deepEqual(normalized.output.boundary, [])
})

test('deriveAgentSessionPreview prefers summary card over mirrored message fallback', () => {
  const preview = deriveAgentSessionPreview({
    messages: [{ role: 'user', content: '总结这个区域' }],
    cards: [{ type: 'summary', title: '核心判断', content: '这里以社区商业为主', items: [] }],
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

test('backToAgentChat keeps conversation state and cached tools', () => {
  const ctx = createAgentContext({
    agentWorkspaceView: 'tools',
    agentInput: '继续分析',
    agentMessages: [{ role: 'user', content: '总结这个区域' }],
    agentTools: [{ name: 'read_current_scope', requires: [], produces: [] }],
    agentToolsLoaded: true,
  })

  ctx.backToAgentChat()

  assert.equal(ctx.agentWorkspaceView, 'chat')
  assert.equal(ctx.agentInput, '继续分析')
  assert.deepEqual(ctx.agentMessages.map((item) => item.content), ['总结这个区域'])
  assert.deepEqual(ctx.agentTools.map((item) => item.name), ['read_current_scope'])
  assert.equal(ctx.agentToolsLoaded, true)
})

test('agent tool detail dialog reads current tool without mutating sessions or tools', () => {
  const tool = normalizeAgentToolSummary({
    name: 'compute_population_overview_from_scope',
    description: 'Build population overview',
    ui_tier: 'foundation',
    data_domain: 'population',
    capability_type: 'analyze',
    risk_level: 'safe',
    readonly: true,
    produces: ['current_population_summary'],
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
  assert.equal(ctx.agentActiveToolDetailName, 'compute_population_overview_from_scope')
  assert.equal(ctx.getAgentToolDetail().name, 'compute_population_overview_from_scope')
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

test('analysis task registry maps backend tool traces to left panel tasks', () => {
  assert.equal(getAnalysisTaskDefinition('poi_grid').panelId, 'poi')
  assert.equal(resolveAnalysisTaskKeyFromTrace({
    tool_name: 'compute_h3_metrics_from_scope_and_pois',
    status: 'success',
  }), 'poi_grid')
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
      taskKey: 'poi_grid',
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
  ctx.submitAgentTurn = async ({ prompt }) => {
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
    agentInput: '底部聊天框内容',
    agentClarificationDraft: '门卫卡片内容',
  })

  assert.equal(ctx.agentInput, '底部聊天框内容')
  assert.equal(ctx.agentClarificationDraft, '门卫卡片内容')
  assert.equal(ctx.canSubmitAgentClarificationDraft(), true)
})

test('clarification option click submits immediately without mutating composer input', () => {
  const ctx = createAgentContext({
    agentInput: '底部聊天框内容',
  })
  let submittedPrompt = ''
  ctx.submitAgentTurn = ({ prompt }) => {
    submittedPrompt = prompt
  }

  ctx.onAgentClarificationOptionClick('总结这个区域的商业特征')

  assert.equal(submittedPrompt, '总结这个区域的商业特征')
  assert.equal(ctx.agentInput, '底部聊天框内容')
  assert.equal(ctx.agentClarificationSubmitting, true)
})

test('clarification draft submit uses inline input and keeps composer untouched', () => {
  const ctx = createAgentContext({
    agentInput: '底部聊天框内容',
    agentClarificationDraft: '比较人口和夜间活力哪个更弱',
  })
  let submittedPrompt = ''
  ctx.submitAgentTurn = ({ prompt }) => {
    submittedPrompt = prompt
  }

  ctx.onAgentClarificationDraftSubmit()

  assert.equal(submittedPrompt, '比较人口和夜间活力哪个更弱')
  assert.equal(ctx.agentInput, '底部聊天框内容')
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
    name: 'run_area_character_pack',
    ui_tier: 'scenario',
    data_domain: 'general',
    capability_type: 'decide',
    scene_type: 'area_character',
    llm_exposure: 'primary',
    applicable_scenarios: ['区域总体调性'],
    cautions: ['不能替代控规'],
    input_schema: { type: 'object', properties: { policy_key: { type: 'string' } } },
    output_schema: { type: 'object', properties: { character_tags: { type: 'array' } } },
    requires: ['scope_polygon'],
    produces: ['area_character_pack'],
  })
  const toolB = normalizeAgentToolSummary({
    name: 'compute_population_overview_from_scope',
    ui_tier: 'foundation',
    data_domain: 'population',
    capability_type: 'analyze',
    scene_type: 'general',
    llm_exposure: 'primary',
    requires: ['scope_polygon'],
    produces: ['current_population_summary'],
  })
  const ctx = createAgentContext({
    agentTools: [toolA, toolB],
  })

  const groups = ctx.getGroupedAgentTools()

  assert.equal(toolA.uiTier, 'scenario')
  assert.equal(toolA.sceneType, 'area_character')
  assert.equal(toolA.capabilityType, 'decide')
  assert.deepEqual(toolA.applicableScenarios, ['区域总体调性'])
  assert.equal(groups[0].key, 'foundation')
  assert.equal(groups[1].key, 'scenario')
  assert.equal(groups[1].subgroups[0].key, 'area_character')
})

test('loadAgentSessionSummaries preserves local draft while adding persisted summaries', async () => {
  const ctx = createAgentContext()
  const draft = ctx.createAgentSession('本地草稿')
  ctx.agentSessions = [draft]
  ctx.activeAgentSessionId = draft.id
  ctx.agentConversationId = draft.id

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
  assert.deepEqual(ctx.getAgentRangeSessionGroups().map((item) => item.title), ['当前范围', '其他范围'])
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
    plan: { steps: [], followup_steps: [], followup_applied: false },
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
  ctx.agentConversationId = draft.id
  ctx.agentRenameDialogOpen = true
  ctx.agentRenameSessionId = draft.id
  ctx.agentRenameInput = '新名称'

  await ctx.submitAgentRename()

  assert.equal(ctx.findAgentSession(draft.id).persisted, false)
  assert.equal(ctx.findAgentSession(draft.id).title, '新名称')
  assert.equal(ctx.findAgentSession(draft.id).titleSource, 'user')
  assert.equal(ctx.getAgentHistorySessions().length, 0)
  assert.equal(ctx.agentRenameDialogOpen, false)
  assert.equal(ctx.agentConversationId, draft.id)
})

test('startNewAgentChat keeps new draft out of visible history until first turn succeeds', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentChat()

  assert.equal(ctx.agentSessions.length, 1)
  assert.equal(ctx.getAgentHistorySessions().length, 0)
  assert.equal(ctx.findAgentSession(ctx.activeAgentSessionId).persisted, false)

  global.fetch = async (url, options = {}) => {
    if (url === '/api/v1/analysis/agent/turn/stream') {
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
                cards: [{ type: 'summary', title: '概览', content: '这里以社区商业为主', items: [] }],
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
                followup_steps: [],
                followup_applied: false,
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
            cards: [{ type: 'summary', title: '概览', content: '这里以社区商业为主', items: [] }],
            clarification_question: '',
            risk_prompt: '',
            next_suggestions: [],
          },
          diagnostics: { execution_trace: [], used_tools: [], citations: [], research_notes: [], audit_issues: [], thinking_timeline: [{ id: 'thinking-1', phase: 'planned', title: '规划工具调用', detail: '正在决定下一步工具。', state: 'completed' }], error: '' },
          context_summary: { has_scope: true, available_results: [], active_panel: 'agent', filters_digest: {} },
          plan: { steps: [], followup_steps: [], followup_applied: false },
          risk_confirmations: [],
        }
      },
    }
  }

  ctx.agentInput = '总结这个区域'
  await ctx.submitAgentTurn()

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
  ctx.startNewAgentChat()
  ctx.agentInput = '总结这个区域'

  let capturedSignal = null
  global.fetch = async (url, options = {}) => {
    assert.equal(url, '/api/v1/analysis/agent/turn/stream')
    capturedSignal = options.signal
    return new Promise((_resolve, reject) => {
      options.signal.addEventListener('abort', () => {
        const error = new Error('aborted')
        error.name = 'AbortError'
        reject(error)
      }, { once: true })
    })
  }

  const pending = ctx.submitAgentTurn()
  await Promise.resolve()

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

test('running session survives switching to a new chat and can be revisited', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentChat()
  ctx.agentInput = '总结这个区域'

  const pendingBySessionId = new Map()
  global.fetch = async (url, options = {}) => {
    assert.equal(url, '/api/v1/analysis/agent/turn/stream')
    const payload = JSON.parse(String(options.body || '{}'))
    const sessionId = String(payload.conversation_id || '')
    return new Promise((_resolve, reject) => {
      pendingBySessionId.set(sessionId, { signal: options.signal, reject })
      options.signal.addEventListener('abort', () => {
        const error = new Error('aborted')
        error.name = 'AbortError'
        reject(error)
      }, { once: true })
    })
  }

  const sessionAId = ctx.activeAgentSessionId
  const pendingA = ctx.submitAgentTurn()
  await Promise.resolve()

  assert.equal(ctx.isAgentSessionRunning(sessionAId), true)
  assert.equal(ctx.agentLoading, true)

  ctx.startNewAgentChat()
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

test('parallel agent turns can run concurrently and cancel only the active session', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentChat()
  ctx.agentInput = '总结这个区域'

  const pendingBySessionId = new Map()
  global.fetch = async (url, options = {}) => {
    assert.equal(url, '/api/v1/analysis/agent/turn/stream')
    const payload = JSON.parse(String(options.body || '{}'))
    const sessionId = String(payload.conversation_id || '')
    return new Promise((_resolve, reject) => {
      pendingBySessionId.set(sessionId, { signal: options.signal, reject })
      options.signal.addEventListener('abort', () => {
        const error = new Error('aborted')
        error.name = 'AbortError'
        reject(error)
      }, { once: true })
    })
  }

  const sessionAId = ctx.activeAgentSessionId
  const pendingA = ctx.submitAgentTurn()
  await Promise.resolve()

  ctx.startNewAgentChat()
  ctx.agentInput = '下一步做什么分析'
  const sessionBId = ctx.activeAgentSessionId
  const pendingB = ctx.submitAgentTurn()
  await Promise.resolve()

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

test('submitAgentTurn shows submit process before first stream event', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentChat()
  ctx.agentInput = '总结这个区域'

  let capturedSignal = null
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
    return new Promise((_resolve, reject) => {
      options.signal.addEventListener('abort', () => {
        const error = new Error('aborted')
        error.name = 'AbortError'
        reject(error)
      }, { once: true })
    })
  }

  const pending = ctx.submitAgentTurn()
  await Promise.resolve()

  const steps = ctx.getAgentVisibleProcessSteps()
  assert.equal(steps.length, 1)
  assert.equal(steps[0].id, 'frontend-submit-request')
  assert.equal(steps[0].title, '提交请求')
  assert.equal(steps[0].detail.includes('正在建立 Agent 流式响应'), false)
  assert.equal(ctx.agentThinkingTimeline.some((item) => item.id === 'stream-connect'), false)
  assert.equal(ctx.agentThinkingExpanded, true)
  ctx.toggleAgentThinkingExpanded()
  assert.equal(ctx.agentThinkingExpanded, false)
  assert.equal(ctx.getAgentVisibleProcessSteps().length, 1)
  assert.equal(typeof capturedSignal?.aborted, 'boolean')

  ctx.cancelAgentTurn()
  await pending
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
  assert.equal(groups[1].title, 'Planner')
  assert.equal(groups[1].state, 'active')
})

test('getAgentProcessRoleGroups embeds planner checklist and tool calls', () => {
  const ctx = createAgentContext({
    agentPlan: {
      steps: [
        { tool_name: 'read_current_results', reason: '读取当前结果', evidence_goal: '确认已有摘要' },
        { tool_name: 'analyze_poi_mix_from_scope', reason: '分析业态结构', evidence_goal: '形成商业画像' },
      ],
      followupSteps: [],
      followupApplied: false,
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

  assert.equal(plannerGroup.title, 'Planner')
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
      followupSteps: [],
      followupApplied: false,
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
  ctx.startNewAgentChat()
  ctx.agentInput = '总结这个区域'

  global.fetch = async (url) => {
    if (url === '/api/v1/analysis/agent/turn/stream') {
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
                cards: [{ type: 'summary', title: '概览', content: '这里以社区商业为主', items: [] }],
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
              plan: { steps: [], followup_steps: [], followup_applied: false },
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
            cards: [{ type: 'summary', title: '概览', content: '这里以社区商业为主', items: [] }],
            clarification_question: '',
            risk_prompt: '',
            next_suggestions: [],
          },
          diagnostics: { execution_trace: [], used_tools: [], citations: [], research_notes: [], audit_issues: [], thinking_timeline: [], error: '' },
          context_summary: { has_scope: true, available_results: [], active_panel: 'agent', filters_digest: {} },
          plan: { steps: [], followup_steps: [], followup_applied: false },
          risk_confirmations: [],
        }
      },
    }
  }

  await ctx.submitAgentTurn()

  assert.deepEqual(
    ctx.getAgentVisibleProcessSteps().map((item) => item.id),
    ['frontend-submit-request', 'status-gating', 'status-planning', 'status-answered'],
  )
  assert.equal(ctx.getAgentVisibleProcessSteps()[0].state, 'completed')
  assert.equal(ctx.getAgentVisibleProcessSteps()[1].state, 'completed')
  assert.equal(ctx.getAgentVisibleProcessSteps()[2].state, 'completed')
  assert.equal(ctx.getAgentVisibleProcessSteps()[2].title, '规划分析步骤')
  assert.equal(ctx.getAgentVisibleProcessSteps()[3].state, 'completed')
})

test('applyAgentSessionSnapshot expands failed and risk confirmation thinking timeline', () => {
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
    plan: { steps: [], followupSteps: [], followupApplied: false },
    riskConfirmations: [],
    messages: [],
    thinkingTimeline: [
      { id: 'thinking-failed', phase: 'answering', title: '生成回答失败', detail: '需要查看原因。', state: 'failed' },
    ],
  }

  ctx.applyAgentSessionSnapshot({ ...baseSnapshot, status: 'failed' })
  assert.equal(ctx.agentThinkingExpanded, true)

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
      followupSteps: [],
      followupApplied: false,
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
        { tool_name: 'read_h3_structure_analysis', reason: '读取空间结构', evidence_goal: '判断集中或分散' },
      ],
      followupSteps: [
        { tool_name: 'detect_commercial_hotspots', reason: '识别商业热点', evidence_goal: '补空间热点结论', optional: true },
      ],
      followupApplied: true,
      summary: '先读取已有分析，再补充热点识别。',
    },
    agentExecutionTrace: [
      { tool_name: 'read_current_results', status: 'success' },
      { tool_name: 'read_h3_structure_analysis', status: 'start' },
    ],
    agentLoading: true,
    agentStage: 'executing',
  })

  const checklist = ctx.getAgentPlanChecklist()

  assert.equal(checklist.visible, true)
  assert.equal(checklist.summary.includes('已根据审计补充步骤'), true)
  assert.equal(checklist.progressLabel, '1/3 已完成')
  assert.equal(checklist.groups.length, 2)
  assert.equal(checklist.groups[0].items[0].status, 'completed')
  assert.equal(checklist.groups[0].items[1].status, 'active')
  assert.equal(checklist.groups[1].items[0].status, 'pending')
  assert.equal(checklist.groups[1].items[0].optional, true)

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
        tool_name: 'run_area_character_pack',
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
    tool_name: 'compute_population_overview_from_scope',
    status: 'success',
  })
  const second = await ctx.maybePreloadPanelForAgentTool({
    tool_name: 'compute_population_overview_from_scope',
    status: 'success',
  })

  assert.equal(first, true)
  assert.equal(second, false)
  assert.equal(populationPreloadCount, 1)
  assert.equal(ctx.activeStep3Panel, 'agent')
  assert.deepEqual(ctx.getAgentPanelPreloadNotes().map((item) => item.label), ['已预加载人口面板数据'])
})

test('submitAgentTurn appends user message immediately and updates thinking timeline from stream', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentChat()
  ctx.agentInput = '总结这个区域'

  global.fetch = async (url) => {
    if (url === '/api/v1/analysis/agent/turn/stream') {
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
                cards: [{ type: 'summary', title: '概览', content: '这里以社区商业为主', items: [] }],
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
                followup_steps: [],
                followup_applied: false,
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
            cards: [{ type: 'summary', title: '概览', content: '这里以社区商业为主', items: [] }],
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
          plan: { steps: [], followup_steps: [], followup_applied: false },
          risk_confirmations: [],
        }
      },
    }
  }

  const pending = ctx.submitAgentTurn()
  await Promise.resolve()

  assert.deepEqual(ctx.agentMessages.map((item) => item.content), ['总结这个区域'])
  assert.equal(ctx.agentInput, '')
  assert.equal(ctx.agentThinkingExpanded, true)
  assert.equal(ctx.getAgentVisibleProcessSteps()[0].title, '提交请求')
  assert.equal(ctx.getAgentVisibleProcessSteps()[0].title === '连接实时过程', false)

  await pending

  assert.equal(ctx.agentThinkingTimeline.length, 5)
  assert.equal(ctx.agentThinkingExpanded, false)
  assert.equal(ctx.agentPlanExpanded, false)
  assert.equal(ctx.agentTraceExpanded, false)
  assert.deepEqual(ctx.getAgentMessagesBeforeThinking().map((item) => item.content), ['总结这个区域'])
  assert.deepEqual(ctx.getAgentMessagesAfterThinking().map((item) => item.content), [])
  assert.deepEqual(
    ctx.getAgentVisibleProcessSteps().map((item) => item.id),
    ['frontend-submit-request', 'status-gating', 'thinking-gating', 'tool-call-read-current-scope', 'status-answered'],
  )
  assert.equal(ctx.getAgentVisibleProcessSteps()[3].state, 'completed')
  const toolThinking = ctx.agentThinkingTimeline.find((item) => item.id === 'tool-call-read-current-scope')
  assert.equal(toolThinking.items.includes('参数：无参数'), true)
  assert.equal(toolThinking.items.includes('结果：scope_polygon 已读取'), true)
  assert.equal(ctx.agentStreamElapsedTimer, null)
  assert.equal(ctx.getAgentThinkingElapsedLabel().endsWith('s'), true)
  assert.equal(ctx.agentExecutionTrace.length, 1)
  assert.equal(ctx.agentCards.length, 1)
  assert.equal(ctx.agentReasoningBlocks.length, 1)
  assert.equal(ctx.getAgentVisibleReasoningBlocks()[0].content, '先读取当前范围。')
  assert.deepEqual(ctx.agentMessages.map((item) => item.content), ['总结这个区域'])
  assert.equal(
    ctx.findAgentSession(ctx.activeAgentSessionId).thinkingTimeline.some((item) => item.id === 'thinking-gating'),
    true,
  )
  assert.equal(ctx.findAgentSession(ctx.activeAgentSessionId).preview, '这里以社区商业为主')
  assert.equal(Object.prototype.hasOwnProperty.call(ctx.findAgentSession(ctx.activeAgentSessionId), 'reasoningBlocks'), false)
})

test('clarification follow-up continues in the same session instead of opening a new chat', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentChat()
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
    assert.equal(url, '/api/v1/analysis/agent/turn/stream')
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
              cards: [{ type: 'summary', title: '概览', content: '已继续在原会话中回答。', items: [] }],
              clarification_question: '',
              clarification_options: [],
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
            context_summary: {},
            plan: { steps: [], followup_steps: [], followup_applied: false, summary: '' },
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
    ['总结这个区域', '哪里适合补充餐饮'],
  )
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
  ctx.startNewAgentChat()
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
    if (url === '/api/v1/analysis/agent/turn/stream') {
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
                cards: [{ type: 'summary', title: '概览', content: '第二轮结论', items: [] }],
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
              plan: { steps: [], followup_steps: [], followup_applied: false },
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
          ],
          output: {
            cards: [{ type: 'summary', title: '概览', content: '第二轮结论', items: [] }],
            clarification_question: '',
            risk_prompt: '',
            next_suggestions: [],
          },
          diagnostics: { execution_trace: [], used_tools: [], citations: [], research_notes: [], audit_issues: [], thinking_timeline: [{ id: 'thinking-gating', phase: 'gating', title: '门卫判断', detail: '已完成。', state: 'completed' }], error: '' },
          context_summary: { has_scope: true, available_results: [], active_panel: 'agent', filters_digest: {} },
          plan: { steps: [], followup_steps: [], followup_applied: false },
          risk_confirmations: [],
        }
      },
    }
  }

  const pending = ctx.submitAgentTurn()
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
  assert.deepEqual(ctx.getAgentMessagesAfterThinking().map((item) => item.content), [])
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

test('submitAgentTurn keeps streamed timeline order when final diagnostics omit intermediate steps', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentChat()
  ctx.agentInput = '总结这个区域'

  global.fetch = async (url) => {
    if (url === '/api/v1/analysis/agent/turn/stream') {
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
            followup_steps: [],
            followup_applied: false,
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
                cards: [{ type: 'summary', title: '概览', content: '这里以社区商业为主', items: [] }],
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
                followup_steps: [],
                followup_applied: false,
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
            cards: [{ type: 'summary', title: '概览', content: '这里以社区商业为主', items: [] }],
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
          plan: { steps: [], followup_steps: [], followup_applied: false },
          risk_confirmations: [],
        }
      },
    }
  }

  await ctx.submitAgentTurn()

  const steps = ctx.getAgentVisibleProcessSteps()
  assert.deepEqual(
    steps.map((item) => item.title),
    ['提交请求', '门卫判断', '门卫通过', '已列出本轮步骤', '执行成功 read_current_results', '回答生成完成'],
  )
  assert.equal(steps[3].detail, '先读取当前结果。')
})

test('submitAgentTurn shows streamed plan above final response and keeps checklist expanded by default', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentChat()
  ctx.agentInput = '总结这个区域'

  global.fetch = async (url) => {
    if (url === '/api/v1/analysis/agent/turn/stream') {
      return createSseResponse([
        {
          type: 'plan',
          payload: {
            steps: [
              { tool_name: 'read_current_results', reason: '读取当前结果', evidence_goal: '确认已有摘要' },
              { tool_name: 'analyze_poi_mix_from_scope', reason: '分析业态结构', evidence_goal: '形成商业画像' },
            ],
            followup_steps: [],
            followup_applied: false,
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
                cards: [{ type: 'summary', title: '概览', content: '这里以社区商业为主', items: [] }],
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
                  { tool_name: 'analyze_poi_mix_from_scope', reason: '分析业态结构', evidence_goal: '形成商业画像' },
                ],
                followup_steps: [],
                followup_applied: false,
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
            cards: [{ type: 'summary', title: '概览', content: '这里以社区商业为主', items: [] }],
            clarification_question: '',
            risk_prompt: '',
            next_suggestions: [],
          },
          diagnostics: { execution_trace: [{ tool_name: 'read_current_results', status: 'success' }], used_tools: ['read_current_results'], citations: [], research_notes: [], audit_issues: [], thinking_timeline: [], error: '' },
          context_summary: { has_scope: true, available_results: [], active_panel: 'agent', filters_digest: {} },
          plan: {
            steps: [
              { tool_name: 'read_current_results', reason: '读取当前结果', evidence_goal: '确认已有摘要' },
              { tool_name: 'analyze_poi_mix_from_scope', reason: '分析业态结构', evidence_goal: '形成商业画像' },
            ],
            followup_steps: [],
            followup_applied: false,
            summary: '先读取已有分析，再生成商业画像。',
          },
          risk_confirmations: [],
        }
      },
    }
  }

  const pending = ctx.submitAgentTurn()
  await pending

  assert.equal(ctx.agentPlan.steps.length, 2)
  assert.equal(ctx.agentPlan.summary, '先读取已有分析，再生成商业画像。')
  assert.equal(ctx.agentPlanExpanded, false)
  assert.equal(ctx.agentTraceExpanded, false)
  assert.equal(ctx.getAgentPlanChecklist().visible, true)
  assert.equal(ctx.getAgentPlanChecklist().groups[0].items[0].status, 'completed')
  assert.equal(ctx.getAgentPlanChecklist().groups[0].items[1].status, 'pending')
})

test('submitAgentTurn preloads mapped panel after successful trace and records lightweight note', async () => {
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
  ctx.startNewAgentChat()
  ctx.agentInput = '哪里是商业核心'

  global.fetch = async (url) => {
    if (url === '/api/v1/analysis/agent/turn/stream') {
      return createSseResponse([
        {
          type: 'trace',
          payload: {
            tool_name: 'read_h3_structure_analysis',
            status: 'success',
            reason: '读取 H3 结构',
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
                cards: [{ type: 'summary', title: '概览', content: '商业有明显集聚', items: [] }],
                clarification_question: '',
                risk_prompt: '',
                next_suggestions: [],
              },
              diagnostics: {
                execution_trace: [{ tool_name: 'read_h3_structure_analysis', status: 'success' }],
                used_tools: ['read_h3_structure_analysis'],
                citations: [],
                research_notes: [],
                audit_issues: [],
                thinking_timeline: [],
                error: '',
              },
              context_summary: { has_scope: true, available_results: [], active_panel: 'agent', filters_digest: {} },
              plan: { steps: [], followup_steps: [], followup_applied: false, summary: '' },
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
          diagnostics: { execution_trace: [{ tool_name: 'read_h3_structure_analysis', status: 'success' }], used_tools: ['read_h3_structure_analysis'], citations: [], research_notes: [], audit_issues: [], thinking_timeline: [], error: '' },
          context_summary: { has_scope: true, available_results: [], active_panel: 'agent', filters_digest: {} },
          plan: { steps: [], followup_steps: [], followup_applied: false, summary: '' },
          risk_confirmations: [],
        }
      },
    }
  }

  await ctx.submitAgentTurn()

  assert.equal(h3EnsureCount, 1)
  assert.equal(h3ChartsCount, 1)
  assert.equal(decisionCardsCount, 1)
  assert.equal(h3RestoreCount, 1)
  assert.deepEqual(ctx.getAgentPanelPreloadNotes().map((item) => item.label), ['已预加载 H3 面板内容'])
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
  ctx.startNewAgentChat()
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

test('submitAgentTurn keeps failed thinking timeline expanded after final response', async () => {
  const ctx = createAgentContext()
  ctx.agentSessionsLoaded = true
  ctx.startNewAgentChat()
  ctx.agentInput = '总结这个区域'

  global.fetch = async (url) => {
    if (url === '/api/v1/analysis/agent/turn/stream') {
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
                followup_steps: [],
                followup_applied: false,
              },
            },
          },
        },
      ])
    }
    throw new Error(`unexpected fetch ${url}`)
  }

  await ctx.submitAgentTurn()

  assert.equal(ctx.agentStatus, 'failed')
  assert.equal(ctx.agentThinkingExpanded, true)
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
        preview: '开始一段新的分析对话',
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
    agentConversationId: 'agent-a',
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
    agentConversationId: 'agent-a',
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
    agentConversationId: 'agent-a',
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
    agentConversationId: 'agent-a',
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
    agentConversationId: 'agent-a',
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

test('createAgentSummaryTab opens a new summary window instead of reusing the default summary tab', () => {
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
  assert.equal(ctx.agentTabs.summaryTabs.find((item) => item.id === firstId).title, '区域总结')
  assert.equal(ctx.agentTabs.summaryTabs.find((item) => item.id === secondId).title, '区域总结')
  assert.equal(ctx.agentTabs.activeTabId, secondId)
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
      missingTasks: ['poi_grid', 'nightlight', 'road_syntax'],
      reused: ['nightlight'],
      fetched: [],
    },
  })
  ctx.summaryTaskHasReusableResult = (taskKey) => taskKey === 'nightlight'

  assert.deepEqual(ctx.getSummaryTaskKeysToFill(), ['poi_grid', 'road_syntax'])
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
        { key: 'poi_grid', label: 'POI / 网格分析', status: 'running' },
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
          assert.equal(selector, 'polygon')
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
            { year: 2024, total_population: 1000, population_density: 50 },
            { year: 2026, total_population: 1200, population_density: 58 },
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
  assert.equal(ctx.getAgentIterationKinds().find((item) => item.key === 'population').disabled, false)
})

test('ensureAgentIterationPoi summarizes multi-year history pois', async () => {
  const ctx = createAgentContext({
    currentHistoryRecordId: 'history-1',
    currentHistoryAvailablePoiYears: [2023, 2024, 2025],
    selectedPoint: { lng: 112.93, lat: 28.13 },
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
  ctx.createAgentIterationChangeTab({ autoload: false })
  global.fetch = async (url, options = {}) => {
    if (String(url).includes('/api/v1/analysis/agent/iteration/poi/build')) {
      const body = JSON.parse(options.body || '{}')
      assert.equal(body.history_id, 'history-1')
      assert.deepEqual(body.years, [2023, 2024, 2025])
      assert.deepEqual(body.center, [112.93, 28.13])
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
            emerging_area: '二区',
            structure_judgement: '一级结构偏向餐饮主导。',
          },
          ai_summary: ['当前POI规模处于中等水平，餐饮为主导业态。', '一区为核心聚集区。'],
          ai_insights: {
            fastest_growth: '咖啡 +120%',
            declining_category: '传统零售 -35%',
            emerging_area: '二区',
            structure_judgement: '业态结构偏消费型。',
          },
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
  assert.equal(payload.ai_summary[0], '当前POI规模处于中等水平，餐饮为主导业态。')
  assert.equal(payload.ai_insights.emerging_area, '二区')
  assert.equal(ctx.getAgentIterationPoiAiSummaryRows().length, 2)
  assert.equal(ctx.getAgentIterationPoiAiInsightRows().find((item) => item.key === 'fastest_growth').value, '咖啡 +120%')
  assert.equal(ctx.getAgentIterationPoiTotalLineChart().length, 3)
  assert.equal(ctx.getAgentIterationPoiCategoryStackChart().length, 3)
  assert.equal(ctx.getAgentIterationPoiSubcategoryStackChart().length, 3)
  assert.equal(payload.spatial_factors.direction_factor.dominant_direction, '东北')
  assert.equal(payload.subcategory_spatial_trend_rows[0].name, '咖啡厅')
  assert.match(ctx.formatAgentIterationPoiSpatialTrend(ctx.getAgentIterationPoiSpatialTrendRows()[0]), /主导方位 东北/)
  assert.equal(ctx.getAgentIterationPoiAreaHeatmaps().length, 3)
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
      url: 'https://restapi.amap.com/v3/staticmap?location=112.9,28.1&zoom=13&size=640*420&key=test',
      bounds: { min_lng: 112.8, min_lat: 28.0, max_lng: 113.0, max_lat: 28.2 },
      center: [112.9, 28.1],
      zoom: 13,
      size: { width: 640, height: 420 },
      source: 'amap_static_url',
      view: { width: 100, height: 65.625 },
      view_box: '0 0 100 65.625',
      aspect_ratio: '100 / 65.625',
      viewport: { left_px: 10, top_px: 20, width: 640, height: 420, zoom: 13 },
    },
    area_heatmap_boundary: [{ x: 10, y: 90 }, { x: 90, y: 90 }, { x: 90, y: 10 }],
    area_heatmap_polygon: [[112.8, 28.0], [113.0, 28.0], [113.0, 28.2]],
    area_heatmap_snapshots: [{ year: 2025, image_url: 'data:image/png;base64,test', point_count: 1, top_area: '一区', status: 'ready' }],
  })

  assert.equal(ctx.getAgentIterationPoiAreaHeatmapBasemap().source, 'amap_static_url')
  assert.match(ctx.getAgentIterationPoiAreaHeatmapBasemap().url, /staticmap/)
  assert.equal(ctx.getAgentIterationPoiAreaHeatmapViewBox(), '0 0 100 65.625')
  assert.deepEqual(ctx.getAgentIterationPoiAreaHeatmapViewSize(), { width: 100, height: 65.625 })
  assert.deepEqual(ctx.getAgentIterationPoiAreaHeatmapAspectStyle(), { aspectRatio: '100 / 65.625' })
  assert.equal(ctx.getAgentIterationPoiAreaHeatmapBoundaryPoints(), '10.00,90.00 90.00,90.00 90.00,10.00')
  assert.equal(ctx.getAgentIterationPoiAreaHeatmapPolygon().length, 3)
  assert.equal(ctx.getAgentIterationPoiAreaHeatmapSnapshot(2025).image_url, 'data:image/png;base64,test')
  const evidence = ctx.buildAgentPoiIterationEvidence(ctx.getAgentIterationPoiPayload())
  assert.equal(evidence.area_heatmap_basemap.source, 'amap_static_url')
  assert.equal(evidence.area_heatmap_boundary.length, 3)
  assert.equal(evidence.area_heatmap_polygon.length, 3)

  ctx.commitAgentIterationPoiPayload({ area_heatmap_basemap: { source: 'none', url: '' }, area_heatmap_boundary: [] })
  assert.equal(ctx.getAgentIterationPoiAreaHeatmapBasemap().url, '')
  assert.equal(ctx.getAgentIterationPoiAreaHeatmapViewBox(), '0 0 100 100')
  assert.equal(ctx.getAgentIterationPoiAreaHeatmapBoundaryPoints(), '')
})

test('agent iteration poi heatmap template keeps aspect ratio on viewport wrapper', async () => {
  const html = await fs.promises.readFile(new URL('../src/pages/analysis/components/main.html', import.meta.url), 'utf8')
  assert.match(html, /class="agent-iteration-heatmap-viewport"[^>]*:style="getAgentIterationPoiAreaHeatmapAspectStyle\(\)"/)
  assert.doesNotMatch(html, /class="agent-iteration-heatmap-svg"[^>]*:style="getAgentIterationPoiAreaHeatmapAspectStyle\(\)"/)
})

test('agent iteration poi area snapshots use tight map framing and hide map chrome', async () => {
  const ctx = createAgentContext()
  ctx.waitForAgentPoiSnapshotPaint = async () => {}
  const originalDocument = global.document
  const originalAMap = global.window.AMap
  const originalHtml2canvas = global.html2canvas
  const calls = { fitPadding: null, zoom: null, ignoredLogo: null, ignoredCopyright: null, capturedCss: '' }
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
        style: { cssText: '', width: '', height: '' },
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
      getZoom() { return 13 }
      setZoom(zoom) { calls.zoom = zoom }
      destroy() {}
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
      { area_heatmap_polygon: [[112.8, 28.0], [113.0, 28.0], [113.0, 28.2], [112.8, 28.2], [112.8, 28.0]] },
    )

    assert.equal(imageUrl, 'data:image/png;base64,snapshot')
    assert.deepEqual(calls.fitPadding, [28, 28, 28, 28])
    assert.equal(calls.zoom, null)
    assert.match(calls.capturedCss, /width:760px/)
    assert.match(calls.capturedCss, /height:420px/)
    assert.equal(calls.ignoredLogo, true)
    assert.equal(calls.ignoredCopyright, true)
  } finally {
    global.document = originalDocument
    global.window.AMap = originalAMap
    global.AMap = originalAMap
    global.html2canvas = originalHtml2canvas
  }
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

test('iteration change ready payloads are reused unless force refresh is requested', async () => {
  const ctx = createAgentContext({
    currentHistoryRecordId: 'history-1',
    currentHistoryAvailablePoiYears: [2023, 2024],
  })
  ctx.createAgentIterationChangeTab({ autoload: false })
  ctx.commitAgentIterationPoiPayload({ status: 'ready', years: [2023, 2024], summaries: [{ year: 2024, count: 2 }] })
  ctx.commitAgentIterationPopulationPayload({ status: 'ready', period: '2024-2026', series: [{ year: 2024 }] })
  ctx.commitAgentIterationNightlightPayload({ status: 'ready', years: [2023, 2024, 2025], snapshots: [{ year: 2025, image_url: 'data:image/png;base64,2025' }] })

  const calls = []
  global.fetch = async (url, options = {}) => {
    calls.push({ url, body: options.body ? JSON.parse(options.body) : null })
    if (String(url).includes('/api/v1/analysis/agent/iteration/poi/build')) {
      return { ok: true, json: async () => ({ status: 'ready', source: 'history', years: [2023, 2024], summaries: [{ year: 2024, count: 1 }], ai_summary: [], ai_insights: {}, error: '' }) }
    }
    throw new Error(`unexpected fetch ${url}`)
  }

  await ctx.ensureAgentIterationKind('poi')
  await ctx.ensureAgentIterationKind('population')
  await ctx.ensureAgentIterationKind('nightlight')
  assert.equal(calls.length, 0)

  await ctx.ensureAgentIterationKind('poi', true)
  assert.equal(calls.filter((item) => String(item.url).includes('/api/v1/analysis/agent/iteration/poi/build')).length, 1)
  assert.equal(calls.filter((item) => String(item.url).includes('/api/v1/analysis/history/history-1/pois')).length, 0)
  assert.equal(calls.filter((item) => String(item.url).includes('/api/v1/analysis/agent/iteration/poi/interpret')).length, 0)
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
      return { ok: true, json: async () => ({ status: 'ready', source: 'history', years: [2023, 2024], summaries: [{ year: 2024, count: 1 }], ai_summary: [], ai_insights: {}, error: '' }) }
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

function ctxSessionBase(id, title) {
  return {
    id,
    title,
    preview: '开始一段新的分析对话',
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

