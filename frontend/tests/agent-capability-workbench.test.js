import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

import { createAgentCapabilityWorkbenchMethods } from '../src/features/agent/capability-workbench.js'
import { createAnalysisLifecycleHooks } from '../src/pages/analysis/orchestrators/lifecycle.js'

const methods = createAgentCapabilityWorkbenchMethods()

function createContext(overrides = {}) {
  return {
    ...methods,
    analysisCapabilities: [],
    analysisCapabilitiesLoaded: false,
    analysisCapabilitiesLoading: false,
    analysisCapabilitiesError: '',
    analysisCapabilityIntentResolution: null,
    analysisCapabilityOverview: null,
    analysisCapabilityOverviewLoaded: false,
    analysisCapabilityOverviewLoading: false,
    analysisCapabilityOverviewError: '',
    analysisCapabilityOverviewHistoryId: '',
    analysisCapabilityOverviewRequestToken: 0,
    analysisCapabilitySearchQuery: '',
    analysisCapabilityStatusFilter: 'all',
    analysisCapabilityReadiness: {},
    analysisCapabilityReadinessErrors: {},
    analysisCapabilityReadinessLoading: false,
    analysisCapabilityInputSelections: {},
    activeAnalysisCapabilityId: '',
    analysisCapabilityRuns: [],
    analysisCapabilityRunsLoaded: false,
    analysisCapabilityRunsLoading: false,
    analysisCapabilityRunsError: '',
    analysisCapabilityRunsHistoryId: '',
    analysisCapabilityRunsCapabilityId: '',
    analysisCapabilityRunsRequestToken: 0,
    selectedAnalysisCapabilityRunId: '',
    selectedAnalysisCapabilityRunDetail: null,
    selectedAnalysisCapabilityRunLoading: false,
    selectedAnalysisCapabilityRunError: '',
    selectedAnalysisCapabilityRunRequestToken: 0,
    analysisCapabilityComparisonBaseRunId: '',
    analysisCapabilityRunComparison: null,
    analysisCapabilityRunComparisonLoading: false,
    analysisCapabilityRunComparisonError: '',
    analysisCapabilityRunComparisonRequestToken: 0,
    stage1EvidenceDrawerSpaceId: '',
    stage1EvidenceDrawerRunId: '',
    stage1ExpandedSpaceId: '',
    stage1ExpandedRunId: '',
    stage1MapFocusedSpaceId: '',
    stage1MapFocusedRunId: '',
    stage1MapFocusMessage: '',
    stage1SpatialMapMode: 'suggested_function',
    stage1SpatialHierarchyLevel: 'all',
    stage1SpatialPresentationMessage: '',
    stage1MovementType: 'all',
    stage1SelectedMovementRouteId: '',
    stage1MovementPresentationMessage: '',
    activeAgentSessionId: 'conversation-1',
    agentSkills: [],
    agentPanelPayloads: {},
    getCurrentAgentHistoryId: () => 'history-1',
    buildAgentAnalysisSnapshot: () => ({ scope: { scope_id: 'scope-1' } }),
    getAgentAnalysisSourceState: () => ({ sources: [] }),
    getAgentSelectedModelName: () => 'DeepSeek Chat',
    ...overrides,
  }
}

test('capability catalog is loaded once and grouped by category', async () => {
  const originalFetch = global.fetch
  let requests = 0
  global.fetch = async () => {
    requests += 1
    return {
      ok: true,
      json: async () => [
        { id: 'urban-strategy-stage1', category: 'planning' },
        { id: 'evidence-audit', category: 'governance' },
      ],
    }
  }
  try {
    const ctx = createContext()
    await ctx.loadAnalysisCapabilities()
    await ctx.loadAnalysisCapabilities()
    assert.equal(requests, 1)
    assert.deepEqual(ctx.getAnalysisCapabilityGroups().map(group => group.label), ['策划决策', '证据治理'])
  } finally {
    global.fetch = originalFetch
  }
})

test('run history request is scoped to current history and selected capability', async () => {
  const originalFetch = global.fetch
  const urls = []
  global.fetch = async url => {
    urls.push(String(url))
    return { ok: true, json: async () => [{ run_id: 'run-1', status: 'completed' }] }
  }
  try {
    const ctx = createContext()
    const first = await ctx.loadAnalysisCapabilityRuns({ capabilityId: 'urban-strategy-stage1' })
    const cached = await ctx.loadAnalysisCapabilityRuns({ capabilityId: 'urban-strategy-stage1' })
    assert.equal(urls.length, 1)
    assert.match(urls[0], /history_id=history-1/)
    assert.match(urls[0], /capability_id=urban-strategy-stage1/)
    assert.equal(first[0].run_id, 'run-1')
    cached[0].run_id = 'changed'
    assert.equal(ctx.getAnalysisCapabilityRuns()[0].run_id, 'run-1')
  } finally {
    global.fetch = originalFetch
  }
})

test('run history clears without a history and never leaks across histories', async () => {
  const originalFetch = global.fetch
  const urls = []
  global.fetch = async url => {
    urls.push(String(url))
    return { ok: true, json: async () => [{ run_id: `run-${urls.length}`, status: 'completed' }] }
  }
  try {
    let historyId = 'history-1'
    const ctx = createContext({ getCurrentAgentHistoryId: () => historyId })
    await ctx.loadAnalysisCapabilityRuns({ capabilityId: 'evidence-audit' })
    historyId = 'history-2'
    await ctx.loadAnalysisCapabilityRuns({ capabilityId: 'evidence-audit' })
    assert.equal(urls.length, 2)
    assert.match(urls[1], /history_id=history-2/)
    assert.equal(ctx.getAnalysisCapabilityRuns()[0].run_id, 'run-2')
    historyId = ''
    await ctx.loadAnalysisCapabilityRuns({ capabilityId: 'evidence-audit' })
    assert.deepEqual(ctx.getAnalysisCapabilityRuns(), [])
    assert.equal(urls.length, 2)
  } finally {
    global.fetch = originalFetch
  }
})

test('late run history responses cannot repopulate a cleared history', async () => {
  const originalFetch = global.fetch
  let resolvePayload
  global.fetch = async () => ({
    ok: true,
    json: () => new Promise(resolve => { resolvePayload = resolve }),
  })
  try {
    let historyId = 'history-1'
    const ctx = createContext({ getCurrentAgentHistoryId: () => historyId })
    const pending = ctx.loadAnalysisCapabilityRuns({ capabilityId: 'urban-strategy-stage1' })
    await Promise.resolve()
    historyId = ''
    await ctx.loadAnalysisCapabilityRuns({ capabilityId: 'urban-strategy-stage1' })
    resolvePayload([{ run_id: 'late-run', status: 'completed' }])
    await pending
    assert.deepEqual(ctx.getAnalysisCapabilityRuns(), [])
    assert.equal(ctx.analysisCapabilityRunsHistoryId, '')
  } finally {
    global.fetch = originalFetch
  }
})

test('selecting a run loads an immutable detail without replacing current panel payloads', async () => {
  const originalFetch = global.fetch
  global.fetch = async url => {
    assert.match(String(url), /analysis-capability-runs\/run-1$/)
    return {
      ok: true,
      json: async () => ({
        history_id: 'history-1',
        run: { run_id: 'run-1', status: 'stale', stale_input_artifact_ids: ['poi-result'], diagnostics: ['上游输入已更新'] },
        artifacts: [{ direction: 'output', artifact: { artifact_id: 'report-1', title: '阶段报告', version: 'run-1' }, payload: { markdown: 'historical' } }],
      }),
    }
  }
  try {
    const currentPanels = { stage1_deliverables: { report_markdown: 'current' } }
    const ctx = createContext({
      analysisCapabilityRuns: [{ run_id: 'run-1', status: 'stale' }],
      agentPanelPayloads: currentPanels,
    })
    const detail = await ctx.selectAnalysisCapabilityRun(ctx.analysisCapabilityRuns[0])
    detail.artifacts[0].payload.markdown = 'changed'
    assert.equal(ctx.getSelectedAnalysisCapabilityRunDetail().artifacts[0].payload.markdown, 'historical')
    assert.deepEqual(ctx.agentPanelPayloads, currentPanels)
    assert.equal(ctx.getSelectedAnalysisCapabilityRunArtifacts()[0].artifact.artifact_id, 'report-1')
    assert.equal(ctx.isAnalysisCapabilityRunSelected(ctx.analysisCapabilityRuns[0]), true)
    ctx.clearSelectedAnalysisCapabilityRun()
    assert.equal(ctx.getSelectedAnalysisCapabilityRunDetail(), null)
  } finally {
    global.fetch = originalFetch
  }
})

test('run detail failure exposes an explicit error and keeps current results intact', async () => {
  const originalFetch = global.fetch
  global.fetch = async () => ({ ok: false, status: 404 })
  try {
    const ctx = createContext({ agentPanelPayloads: { capability_run: { run_id: 'current-run' } } })
    await assert.rejects(ctx.selectAnalysisCapabilityRun({ run_id: 'missing-run' }), /404/)
    assert.match(ctx.selectedAnalysisCapabilityRunError, /404/)
    assert.equal(ctx.getCapabilityRun().run_id, 'current-run')
    assert.equal(ctx.selectedAnalysisCapabilityRunLoading, false)
  } finally {
    global.fetch = originalFetch
  }
})

test('capability run context ask locks the selected immutable version and compacts artifacts', () => {
  let opened = null
  const detail = {
    history_id: 'history-1',
    run: {
      run_id: 'run-history-1',
      capability_id: 'urban-strategy-stage1',
      status: 'stale',
      current_stage: 'delivery',
      stale_input_artifact_ids: ['poi-grid-v2'],
      diagnostics: ['存在一项待复核代理指标'],
      stage_records: [{ stage_id: 'delivery', title: '交付编译', status: 'completed', summary: '生成第一阶段报告' }],
      input_artifact_refs: [{ artifact_id: 'poi-grid-v1', artifact_type: 'structured_data', title: 'POI 网格', version: 'v1' }],
      output_artifact_refs: [{
        artifact_id: 'stage1-report', artifact_type: 'report', title: '第一阶段报告', version: 'run-history-1',
        evidence_refs: ['evidence-poi-1'], source_artifact_refs: ['poi-grid-v1'], content_digest: 'digest-123',
      }],
    },
    artifacts: [{
      direction: 'output',
      artifact: {
        artifact_id: 'stage1-report', artifact_type: 'report', title: '第一阶段报告', version: 'run-history-1',
        evidence_refs: ['evidence-poi-1'], source_artifact_refs: ['poi-grid-v1'], content_digest: 'digest-123',
      },
      payload: { executive_summary: '这是历史版本的核心结论。'.repeat(40), decision: '优先补齐公共服务短板' },
    }],
  }
  const ctx = createContext({
    analysisCapabilities: [{ id: 'urban-strategy-stage1', display_name: '城市区域策划第一阶段' }],
    selectedAnalysisCapabilityRunId: 'run-history-1',
    selectedAnalysisCapabilityRunDetail: detail,
    normalizeContextAskTarget: target => target,
    openContextAsk: (target, options) => { opened = { target, options }; return target },
  })

  const target = ctx.buildCapabilityRunContextAskTarget(detail)
  assert.equal(target.type, 'capability_run')
  assert.equal(target.source, 'capability_run')
  assert.equal(target.payload.run_id, 'run-history-1')
  assert.equal(target.payload.version_kind, 'immutable_history')
  assert.deepEqual(target.payload.stale_input_artifact_ids, ['poi-grid-v2'])
  assert.equal(target.payload.artifacts[1].snapshot_state, 'immutable_payload')
  assert.ok(target.payload.artifacts[1].payload_highlights.every(item => item.length < 220))
  assert.equal(target.evidence[0].evidence_ref, 'evidence-poi-1')
  assert.match(target.summary, /不得将该版本表述为当前最新结论/)

  ctx.openCapabilityRunContextAsk(detail)
  assert.equal(opened.target.payload.run_id, 'run-history-1')
  assert.deepEqual(opened.options, { resetMessages: true })

  ctx.agentPanelPayloads = {
    capability_run: {
      run_id: 'run-current', capability_id: 'urban-strategy-stage1', status: 'completed', current_stage: 'delivery',
      input_artifact_refs: [], output_artifact_refs: [], stage_records: [], diagnostics: [],
    },
  }
  const currentTarget = ctx.buildCapabilityRunContextAskTarget()
  assert.equal(currentTarget.payload.run_id, 'run-current')
  assert.equal(currentTarget.payload.version_kind, 'current_result')
})

test('run history labels stale inputs, stages, versions and timestamps', () => {
  const run = {
    run_id: 'run-1', status: 'stale', current_stage: 'delivery', created_at: '2026-07-12T08:30:00Z',
    stale_input_artifact_ids: ['poi-result', 'population-grid'],
    stage_records: [{ stage_id: 'delivery', title: '交付编译' }],
  }
  const ctx = createContext({ analysisCapabilityRuns: [run, { run_id: 'run-0', status: 'completed' }] })
  assert.equal(ctx.getAnalysisCapabilityRunStatusLabel(run), '上游已更新')
  assert.equal(ctx.getAnalysisCapabilityRunVersionLabel(run, 0), '最新 v2')
  assert.equal(ctx.getAnalysisCapabilityRunVersionLabel(ctx.analysisCapabilityRuns[1], 1), '历史 v1')
  assert.equal(ctx.getAnalysisCapabilityRunCurrentStageLabel(run), '交付编译')
  assert.deepEqual(ctx.getAnalysisCapabilityRunChangedInputIds(run), ['poi-result', 'population-grid'])
  assert.match(ctx.getAnalysisCapabilityRunTimeLabel(run), /2026/)
})

test('selected capability run compares against another immutable version', async () => {
  const originalFetch = global.fetch
  const urls = []
  const comparison = {
    history_id: 'history-1',
    capability_id: 'urban-strategy-stage1',
    base_run: { run_id: 'run-1', status: 'completed' },
    target_run: { run_id: 'run-2', status: 'completed' },
    configuration_changes: [{ field: 'configuration_snapshot.question', label: '分析任务', change_type: 'changed', before: '初稿', after: '复算' }],
    stage_changes: [],
    artifact_changes: [{ direction: 'output', artifact_id: 'stage1-decision-matrix', title: '空间矩阵', change_type: 'changed' }],
    outcome_changes: [{ field: 'recommended', label: '推荐定位方案', change_type: 'changed', before: 'option-a', after: 'option-b' }],
    entity_changes: [{ category: 'space_decision', entity_id: 'unit-1', title: '原礼堂', change_type: 'changed', changed_fields: ['future_role'] }],
    summary: ['1 项核心结果发生变化。'],
    has_changes: true,
  }
  global.fetch = async url => {
    urls.push(String(url))
    return { ok: true, json: async () => comparison }
  }
  try {
    const ctx = createContext({
      analysisCapabilityRuns: [
        { run_id: 'run-2', status: 'completed', completed_at: '2026-07-12T02:00:00Z' },
        { run_id: 'run-1', status: 'completed', completed_at: '2026-07-12T01:00:00Z' },
      ],
      selectedAnalysisCapabilityRunId: 'run-2',
      selectedAnalysisCapabilityRunDetail: { run: { run_id: 'run-2' }, artifacts: [] },
    })
    assert.deepEqual(ctx.getAnalysisCapabilityComparisonCandidates().map(run => run.run_id), ['run-1'])
    assert.match(ctx.getAnalysisCapabilityRunComparisonOptionLabel(ctx.analysisCapabilityRuns[1]), /历史 v1/)
    ctx.setAnalysisCapabilityComparisonBaseRunId('run-1')
    const result = await ctx.compareSelectedAnalysisCapabilityRun()
    assert.match(urls[0], /base_run_id=run-1/)
    assert.match(urls[0], /target_run_id=run-2/)
    assert.equal(result.outcome_changes[0].label, '推荐定位方案')
    result.summary[0] = 'mutated'
    assert.equal(ctx.getAnalysisCapabilityRunComparison().summary[0], '1 项核心结果发生变化。')
    assert.equal(ctx.getAnalysisCapabilityComparisonChangeLabel('removed'), '移除')
    assert.equal(ctx.getAnalysisCapabilityComparisonEntityLabel('space_decision'), '空间决策')
    assert.equal(ctx.formatAnalysisCapabilityComparisonValue(['A', 'B']), 'A、B')
  } finally {
    global.fetch = originalFetch
  }
})

test('changing selected capability run clears comparison state and rejects late comparison response', async () => {
  const originalFetch = global.fetch
  let resolveComparison
  global.fetch = async url => {
    if (String(url).includes('run-comparisons')) {
      return { ok: true, json: () => new Promise(resolve => { resolveComparison = resolve }) }
    }
    return { ok: true, json: async () => ({ run: { run_id: 'run-3' }, artifacts: [] }) }
  }
  try {
    const ctx = createContext({
      selectedAnalysisCapabilityRunId: 'run-2',
      selectedAnalysisCapabilityRunDetail: { run: { run_id: 'run-2' }, artifacts: [] },
      analysisCapabilityComparisonBaseRunId: 'run-1',
    })
    const pending = ctx.compareSelectedAnalysisCapabilityRun()
    await Promise.resolve()
    await ctx.selectAnalysisCapabilityRun({ run_id: 'run-3' })
    assert.equal(ctx.analysisCapabilityComparisonBaseRunId, '')
    assert.equal(ctx.getAnalysisCapabilityRunComparison(), null)
    resolveComparison({ base_run: { run_id: 'run-1' }, target_run: { run_id: 'run-2' }, summary: ['late'] })
    assert.equal(await pending, null)
    assert.equal(ctx.getAnalysisCapabilityRunComparison(), null)
  } finally {
    global.fetch = originalFetch
  }
})

test('readiness request carries analysis snapshot and selected source identities', async () => {
  const originalFetch = global.fetch
  let requestBody = null
  global.fetch = async (_url, options) => {
    requestBody = JSON.parse(options.body)
    return { ok: true, json: async () => ({ status: 'ready', ready: true }) }
  }
  try {
    const ctx = createContext({
      getAgentAnalysisSourceState: () => ({
        sources: [{
          id: 'document:brief', type: 'document', title: '项目摘要', status: 'ready', selected: true,
          meta: { aiPayload: { source_id: 'document:brief', source_kind: 'document', document_role: 'project_brief', included: ['evidence'] } },
        }],
      }),
    })
    const capability = { id: 'urban-strategy-stage1', display_name: '城市区域策划第一阶段' }
    await ctx.inspectAnalysisCapability(capability)
    assert.deepEqual(requestBody.analysis_snapshot, { scope: { scope_id: 'scope-1' } })
    assert.equal(requestBody.selected_sources_context.sources[0].source_id, 'document:brief')
    assert.equal(ctx.getAnalysisCapabilityReadiness(capability.id).ready, true)
  } finally {
    global.fetch = originalFetch
  }
})

test('readiness failure is exposed without discarding the active capability', async () => {
  const originalFetch = global.fetch
  global.fetch = async () => ({ ok: false, status: 503 })
  try {
    const ctx = createContext()
    await ctx.inspectAnalysisCapability({ id: 'evidence-audit', display_name: '证据审计' })
    assert.equal(ctx.activeAnalysisCapabilityId, 'evidence-audit')
    assert.equal(ctx.analysisCapabilitiesError, '')
    assert.match(ctx.getAnalysisCapabilityReadinessError('evidence-audit'), /503/)
    assert.equal(ctx.analysisCapabilityReadinessLoading, false)
  } finally {
    global.fetch = originalFetch
  }
})

test('capability execution is blocked until readiness locks its inputs', async () => {
  let submitted = false
  const ctx = createContext({ submitAgentComposer: async () => { submitted = true } })

  await ctx.runAnalysisCapability({
    id: 'urban-strategy-stage1',
    status: 'available',
    executor_type: 'skill',
    executor_id: 'urban-strategy-stage1',
  })

  assert.equal(submitted, false)
  assert.match(ctx.getAnalysisCapabilityReadinessError('urban-strategy-stage1'), /锁定能力输入/)
})

test('running a Skill capability selects its executor for the current turn', async () => {
  const selected = []
  const submitted = []
  const skill = { id: 'urban-strategy-stage1', display_name: '城市区域策划第一阶段' }
  const ctx = createContext({
    agentSkills: [skill],
    analysisCapabilityReadiness: { 'urban-strategy-stage1': { status: 'ready', input_resolutions: [] } },
    loadAgentCapabilities: async () => {},
    chooseAgentSkill: value => selected.push(value),
    submitAgentComposer: async value => submitted.push(value),
  })
  await ctx.runAnalysisCapability({ id: 'urban-strategy-stage1', status: 'available', executor_type: 'skill', executor_id: 'urban-strategy-stage1' })
  assert.deepEqual(selected, [skill])
  assert.equal(ctx.agentWorkspaceView, 'report')
  assert.match(submitted[0].prompt, /第一阶段策划/)
})

test('running a capability never falls back to plain Agent when its Skill is missing', async () => {
  let submitted = false
  const ctx = createContext({
    analysisCapabilityReadiness: { 'urban-strategy-stage1': { status: 'ready', input_resolutions: [] } },
    loadAgentCapabilities: async () => {},
    submitAgentComposer: async () => { submitted = true },
  })
  await ctx.runAnalysisCapability({ id: 'urban-strategy-stage1', status: 'available', executor_type: 'skill', executor_id: 'urban-strategy-stage1' })
  assert.equal(submitted, false)
  assert.match(ctx.analysisCapabilitiesError, /Skill 当前不可用/)
})

test('PPT capability reuses the existing planning workbench', async () => {
  let opened = 0
  const ctx = createContext({
    analysisCapabilityReadiness: { 'ppt-planning': { status: 'ready', input_resolutions: [] } },
    openAgentPptPlanningFromReport: () => { opened += 1 },
  })
  await ctx.runAnalysisCapability({ id: 'ppt-planning', status: 'available', executor_type: 'service', executor_id: 'ppt-planning' })
  assert.equal(opened, 1)
})

test('Stage 1 quality accessors expose verification gaps without mutating payloads', () => {
  const task = { evidence_id: 'e2', status: 'fieldwork_required', executor: 'fieldwork', missing_input: '消防核验', blocking_reason: '缺少现场资料', next_action: '现场踏勘', responsible_party: '消防顾问', verification_method: '完成消防疏散踏勘并签字', decision_impact: '完成前不得锁定礼堂使用强度' }
  const ctx = createContext({
    agentPanelPayloads: {
      capability_run: {
        run_id: 'caprun-1', capability_id: 'urban-strategy-stage1', status: 'completed_with_warnings', current_stage: 'formal-deliverables',
        execution_profile: { model_profile_id: 'model-1', model_display_name: '规划模型', skill_id: 'urban-strategy-stage1', skill_display_name: '城市区域策划第一阶段' },
        input_artifact_refs: [{ artifact_id: 'document:brief' }, { artifact_id: 'analysis:road' }],
        output_artifact_refs: [
          { artifact_id: 'stage1-report', artifact_type: 'report', title: 'Stage 1 report', filename: 'stage1_report.md', source_artifact_refs: ['stage1-evidence-ledger'], evidence_refs: ['e1', 'e2'], content_digest: 'sha256:1234567890abcdef1234' },
          { artifact_id: 'stage1-run-manifest', artifact_type: 'structured_data', title: 'Run manifest', filename: 'run_manifest.json', source_artifact_refs: [], evidence_refs: [], content_digest: '' },
        ],
        stage_records: [
          { stage_id: 'readiness', title: '资料完整性检查', status: 'completed', summary: '输入满足' },
          { stage_id: 'formal-deliverables', title: '编译正式交付物', status: 'completed', summary: '共享同一运行版本' },
        ],
      },
      stage1_quality_audit: { status: 'failed', score: 63, issues: [{ code: 'broken-ref', severity: 'error', message: '证据引用失效' }] },
      stage1_evidence_verification: {
        status: 'passed_with_gaps', as_of_date: '2026-07-12',
        status_counts: { verified: 2, inferred: 1, fieldwork_required: 1 },
        automated_checks: [
          { evidence_id: 'e2', tool_id: 'verify_road_analysis_claim', outcome: 'passed', claim_types: ['network_intelligibility'], diagnostics: ['r²一致'], derived_values: { r2: 0.05 }, summary: '已自动复算' },
          { evidence_id: 'e3', tool_id: 'verify_proxy_indicator_claim', outcome: 'passed_with_gaps', claim_types: ['poi_proxy'], diagnostics: ['POI不能等同真实需求'], derived_values: { poi: { record_count: 18 } }, summary: '代理边界已检查' },
        ],
        tasks: [task],
      },
      stage1_evidence_ledger: [
        { id: 'e1', evidence_type: 'F', status: 'verified', claim: '礼堂具备社区公共记忆价值', source_ref: '项目基础资料', source_artifact_id: 'document:brief:node-1', source_locator: 'p.12', source_date: '2025', scope: '原县政府礼堂', method: '读取项目资料', metric: '历史价值', value: '社区公共记忆节点', confidence: 'high', limitation: '当前使用状态需现场复核', next_action: '核对现状使用记录' },
        { id: 'e2', evidence_type: 'V', status: 'fieldwork_required', claim: '消防条件决定空间开放强度', source_ref: '消防专项资料', source_artifact_id: 'manual:fire-review', source_locator: '待补充', source_date: 'unknown', scope: '原县政府礼堂', method: '现场踏勘与专项检测', confidence: 'low', limitation: '尚未完成现场核验', next_action: '完成消防专项检测' },
      ],
      stage1_provenance_binding: {
        status: 'passed_with_gaps', assessed_count: 2, critical_evidence_ids: ['e1'],
        status_counts: { verified: 1, corrected: 1 },
        bindings: [
          { evidence_id: 'e1', status: 'verified', artifact_id: 'document:brief:node-1', locator: 'pageindex:node-1:p.12', corrected_fields: [], unverified_fields: [], discrepancies: [], message: '来源声明已绑定到真实数据资产。' },
          { evidence_id: 'e2', status: 'corrected', artifact_id: 'analysis_snapshot.road', locator: 'analysis_snapshot.road', corrected_fields: ['sample_size'], unverified_fields: ['coordinate_transform'], discrepancies: [{ field: 'sample_size', declared: 99, authoritative: 48, resolution: 'corrected' }], message: '已按真实数据资产修正来源声明。' },
        ],
        issues: [{ code: 'artifact_declaration_corrected', severity: 'warning', evidence_id: 'e2', message: '来源声明已修正', repair_hint: '检查提示词' }],
      },
      stage1_data_quality: {
        status: 'passed_with_gaps', assessed_count: 2, analytic_count: 1,
        critical_evidence_ids: ['e1'],
        coverage: { source_date: 2, source_locator: 1, analysis_date: 1, sample_diagnostics: 0, coordinate_system: 1 },
        coordinate_systems: ['EPSG:4490'], stale_evidence_ids: [],
        issues: [{ code: 'sample_diagnostics_missing', dimension: 'sample', severity: 'warning', evidence_id: 'e2', message: '缺少样本诊断', repair_hint: '补充分析产物元数据' }],
      },
      stage1_hard_constraint_screening: {
        status: 'conditional',
        status_counts: { verified: 1, unknown: 1 },
        required_constraint_ids: ['ownership', 'fire_safety'],
        assessments: [
          { constraint_id: 'ownership', label: '产权与使用权', state: 'verified', decision_effect: 'allow', scope: '项目范围', finding: '统一运营授权已核验', evidence_refs: ['e1'], verification_action: '' },
          { constraint_id: 'fire_safety', label: '消防与疏散', state: 'unknown', decision_effect: 'condition', scope: '礼堂', finding: '尚缺消防检测', evidence_refs: [], verification_action: '完成消防专项检测', executor: 'manual_authority' },
        ],
        pending_actions: [{ constraint_id: 'fire_safety', label: '消防与疏散', action: '完成消防专项检测', executor: 'manual_authority' }],
      },
      stage1_conflict_register: [
        { metric_key: 'households', label: '居民户数', values: ['102户', '120户'], evidence_ids: ['e2', 'node-2'], unresolved: true, explanation: '同级项目摘要口径冲突' },
        { metric_key: 'area', label: '项目面积', values: ['2.4公顷', '2.5公顷'], evidence_ids: ['node-3'], unresolved: false, explanation: '采用项目摘要口径' },
      ],
      stage1_spatial_matrix: {
        matrix_version: '2.0',
        positioning_option_id: 'option-a',
        spatial_hierarchy: [
          { id: 'system-1', title: '一院', level: 'system', parent_id: '', role: '公共文化系统', member_space_ids: [] },
          { id: 'cluster-1', title: '公共文化组团', level: 'cluster', parent_id: 'system-1', role: '公共文化体验组团', member_space_ids: [] },
          { id: 'unit-1', title: '礼堂单元', level: 'unit', parent_id: 'cluster-1', role: '社区文化单元', member_space_ids: ['unit-1'] },
        ],
        space_decisions: [{
          space_id: 'unit-1', hierarchy_id: 'unit-1', space_name: '原县政府礼堂',
          future_role: '社区文化锚点', core_audiences: ['社区家庭', '青年社群'],
          movement_role: '主游线目的地', value_role: '公共服务与活动引流',
          current_state_category: 'vacant', current_state: { summary: '闲置礼堂' },
          change_logic: { reason: '补足社区文化活动空间' },
          candidate_functions: [{ id: 'culture', name: '文化活动' }, { id: 'retail', name: '社区零售' }],
          preferred_function: { id: 'culture', name: '文化活动' },
          compatible_functions: [{ id: 'exhibition', name: '社区展览' }],
          excluded_functions: [{ id: 'heavy-food', name: '重餐饮', reason: '排烟受限' }],
          audience_scenarios: ['社区周末活动'], access_and_movement: { visitor_entry: '南侧主入口' },
          operation_strategy: { operator: '社区文化运营主体' }, renovation_and_delivery: { scope: '一期轻量改造' },
          implementation_phase: 'phase_1', risk_level: 'high', risk_summary: '消防与结构条件尚待核验',
          preconditions: ['完成消防评估'], assumptions: [], validation_actions: ['开展消防与结构核验'],
          evidence_refs: ['e1', 'e2', 'missing-evidence'], hard_constraint_refs: ['fire_safety'],
          recommendation_status: 'conditional', confidence: 'medium',
          map_binding: {
            status: 'bound', spatial_object_id: 'building:auditorium', object_type: 'building', title: '礼堂建筑轮廓',
            source_ref: 'project_gis.buildings', source_locator: 'project_gis.buildings/auditorium',
            feature: { type: 'Feature', properties: { building_id: 'auditorium' }, geometry: { type: 'Polygon', coordinates: [[[112, 28], [112.01, 28], [112.01, 28.01], [112, 28]]] } },
          },
        }],
        map_presentation: {
          modes: [
            { id: 'current_state', label: '现状', legend: [{ key: 'vacant', label: '闲置', color: '#dc2626' }] },
            { id: 'suggested_function', label: '建议功能', legend: [{ key: 'culture', label: '文化活动', color: '#2563eb' }] },
            { id: 'recommendation_strength', label: '推荐强度', legend: [{ key: 'conditional', label: '有条件推荐', color: '#d97706' }] },
            { id: 'risk', label: '风险', legend: [{ key: 'high', label: '高风险', color: '#ea580c' }] },
            { id: 'implementation_phase', label: '实施阶段', legend: [{ key: 'phase_1', label: '一期', color: '#0f766e' }] },
          ],
          hierarchy_levels: [
            { id: 'system', label: '系统层', decision_count: 0 },
            { id: 'cluster', label: '组团层', decision_count: 0 },
            { id: 'unit', label: '单元层', decision_count: 1 },
          ],
          items: [{
            space_id: 'unit-1', space_name: '原县政府礼堂', hierarchy_id: 'unit-1', hierarchy_level: 'unit', hierarchy_title: '礼堂单元',
            map_binding: { status: 'bound', feature: { type: 'Feature', geometry: { type: 'Polygon', coordinates: [[[112, 28], [112.01, 28], [112.01, 28.01], [112, 28]]] } } },
            values: {
              current_state: { key: 'vacant', label: '闲置', color: '#dc2626' },
              suggested_function: { key: 'culture', label: '文化活动', color: '#2563eb' },
              recommendation_strength: { key: 'conditional', label: '有条件推荐', color: '#d97706' },
              risk: { key: 'high', label: '高风险', color: '#ea580c', detail: '消防与结构条件尚待核验' },
              implementation_phase: { key: 'phase_1', label: '一期', color: '#0f766e' },
            },
          }],
          bound_item_count: 1,
        },
        movement_presentation: {
          types: [
            { id: 'visitor', label: '游客', color: '#2563eb', route_count: 1 },
            { id: 'resident', label: '居民', color: '#16a34a', route_count: 1 },
            { id: 'service', label: '后勤', color: '#d97706', route_count: 1 },
            { id: 'fire', label: '消防应急', color: '#dc2626', route_count: 1 },
          ],
          items: [
            {
              route_id: 'route-visitor', movement_type: 'visitor', movement_label: '游客', color: '#2563eb', title: '游客主游线', role: '连接入口与礼堂', status: 'proposed', status_label: '策划建议', entry_or_origin: '南侧入口', destinations: ['礼堂'], affected_space_ids: ['unit-1'], operating_windows: ['日间'], constraints: ['无障碍待核'], conflicts: [], evidence_refs: ['e1'], assumptions: [], validation_actions: ['现场踏勘'],
              map_binding: { status: 'bound', title: '入口路径', feature: { type: 'Feature', geometry: { type: 'LineString', coordinates: [[112, 28], [112.01, 28.01]] } } },
            },
            ...['resident', 'service', 'fire'].map((movementType, index) => ({
              route_id: `route-${movementType}`, movement_type: movementType, movement_label: ['居民', '后勤', '消防应急'][index], color: ['#16a34a', '#d97706', '#dc2626'][index], title: `${['居民', '后勤', '消防应急'][index]}流线`, role: '待核验流线', status: 'unavailable', status_label: '路径待补', entry_or_origin: '待核入口', destinations: ['礼堂'], affected_space_ids: ['unit-1'], operating_windows: ['待核'], constraints: [], conflicts: movementType === 'service' ? ['与游客流线交叉'] : [], evidence_refs: ['e1'], assumptions: [], validation_actions: ['补充路径测绘'], map_binding: { status: 'unavailable', reason: '尚无权威路径几何' },
            })),
          ],
          bound_item_count: 1,
        },
      },
      stage1_deliverables: {
        status: 'ready',
        source_contract: 'audited_stage1_package',
        artifacts: [
          { artifact_id: 'stage1-report', filename: 'stage1_report.md', title: 'Stage 1 主报告', format: 'markdown', status: 'ready', summary: '引用同一审计包中的 2 条证据。' },
          { artifact_id: 'stage1-evidence-appendix', filename: 'evidence_appendix.md', title: '证据附录', format: 'markdown', status: 'ready', summary: '保留证据定位与冲突。' },
          { artifact_id: 'stage1-design-handoff', filename: 'design_handoff.json', title: '设计任务书', format: 'json', status: 'ready', summary: '传递空间单元要求。' },
          { artifact_id: 'stage1-run-manifest', filename: 'run_manifest.json', title: '运行清单', format: 'json', status: 'ready', summary: '锁定运行快照。' },
        ],
        design_handoff: {
          positioning_option_id: 'option-a',
          space_requirements: [{ space_id: 'unit-1' }],
          unresolved_constraints: [{ type: 'fieldwork_required', id: 'e2' }],
        },
      },
    },
  })
  assert.equal(ctx.hasStage1Outcome(), true)
  const run = ctx.getCapabilityRun()
  run.stage_records[0].title = 'changed'
  assert.equal(ctx.getCapabilityRun().stage_records[0].title, '资料完整性检查')
  assert.equal(ctx.getCapabilityRunStatusLabel(), '完成但有提示')
  assert.equal(ctx.getCapabilityRunCurrentStageLabel(), '编译正式交付物')
  assert.equal(ctx.getCapabilityRunModelLabel(), '规划模型')
  assert.equal(ctx.getCapabilityRunSkillLabel(), '城市区域策划第一阶段')
  assert.equal(ctx.getCapabilityRunSourceCount(), 2)
  const outputArtifacts = ctx.getCapabilityRunOutputArtifacts()
  assert.equal(outputArtifacts.length, 2)
  assert.equal(ctx.getCapabilityRunArtifactTypeLabel(outputArtifacts[0]), '报告')
  assert.equal(ctx.getCapabilityRunArtifactTypeLabel(outputArtifacts[1]), '结构化数据')
  assert.equal(ctx.getCapabilityRunArtifactLineageText(outputArtifacts[0]), '1 个上游 · 2 条证据 · sha256:1234567890a')
  outputArtifacts[0].source_artifact_refs.push('changed')
  assert.equal(ctx.getCapabilityRunOutputArtifacts()[0].source_artifact_refs.length, 1)
  assert.equal(ctx.getStage1VerificationStatusLabel(), '证据门控通过，仍有缺口')
  assert.deepEqual(ctx.getStage1VerificationStatusItems(), [
    { key: 'verified', label: '已验证', count: 2 },
    { key: 'inferred', label: '推断', count: 1 },
    { key: 'fieldwork_required', label: '需现场核验', count: 1 },
  ])
  const checks = ctx.getStage1AutomatedVerificationChecks()
  checks[0].diagnostics[0] = 'changed'
  checks[0].derived_values.r2 = 1
  checks[1].derived_values.poi.record_count = 99
  assert.deepEqual(ctx.getStage1AutomatedVerificationChecks()[0].diagnostics, ['r²一致'])
  assert.equal(ctx.getStage1AutomatedVerificationChecks()[0].derived_values.r2, 0.05)
  assert.equal(ctx.getStage1AutomatedVerificationChecks()[1].derived_values.poi.record_count, 18)
  assert.equal(ctx.getStage1VerificationToolLabel(checks[0]), '路网指标一致性核验')
  assert.equal(ctx.getStage1VerificationToolLabel(checks[1]), '代理指标边界核验')
  assert.equal(ctx.getStage1VerificationDerivedText(checks[0]), 'r2=1')
  const tasks = ctx.getStage1VerificationTasks()
  tasks[0].missing_input = 'changed'
  assert.equal(task.missing_input, '消防核验')
  assert.equal(ctx.getStage1VerificationTaskExecutorLabel(ctx.getStage1VerificationTasks()[0]), '消防顾问')
  const qualityGate = ctx.getStage1QualityGate()
  assert.equal(qualityGate.status, 'blocked')
  assert.equal(qualityGate.label, '质量门已阻断')
  assert.equal(qualityGate.checks.length, 7)
  assert.equal(qualityGate.blocking_items.length, 2)
  assert.deepEqual(qualityGate.task_counts, { agent: 0, manual_authority: 1, fieldwork: 1 })
  assert.equal(qualityGate.task_total, 2)
  qualityGate.blocking_items[0].message = 'changed'
  assert.equal(ctx.getStage1QualityGate().blocking_items[0].message, '证据引用失效')
  assert.equal(ctx.getStage1QualityBlockingIssues()[0].code, 'broken-ref')
  const conflicts = ctx.getStage1ConflictRegister()
  conflicts[0].values[0] = 'changed'
  assert.equal(ctx.getStage1ConflictRegister()[0].values[0], '102户')
  assert.equal(ctx.getStage1UnresolvedConflictCount(), 1)
  assert.equal(ctx.getStage1ConflictStatusLabel(conflicts[0]), '待裁决')
  assert.equal(ctx.getStage1ConflictStatusLabel(conflicts[1]), '已确定口径')
  assert.equal(ctx.getStage1ConflictValuesText(ctx.getStage1ConflictRegister()[0]), '102户 / 120户')
  assert.equal(ctx.getStage1ProvenanceStatusLabel(), '真实资产绑定存在缺口')
  assert.deepEqual(ctx.getStage1ProvenanceStatusItems(), [
    { key: 'verified', label: '已验证', count: 1 },
    { key: 'corrected', label: '已修正', count: 1 },
  ])
  const provenanceBindings = ctx.getStage1ProvenanceBindings()
  provenanceBindings[1].discrepancies[0].authoritative = 100
  provenanceBindings[1].corrected_fields[0] = 'changed'
  assert.equal(ctx.getStage1ProvenanceBindings()[1].discrepancies[0].authoritative, 48)
  assert.deepEqual(ctx.getStage1ProvenanceBindings()[1].corrected_fields, ['sample_size'])
  assert.equal(ctx.getStage1ProvenanceCorrectionText(ctx.getStage1ProvenanceBindings()[1]), '修正字段：sample_size')
  assert.equal(ctx.getStage1ProvenanceUnverifiedText(ctx.getStage1ProvenanceBindings()[1]), '资产未登记：coordinate_transform')
  assert.equal(ctx.getStage1ProvenanceDiscrepancyText(ctx.getStage1ProvenanceBindings()[1]), 'sample_size：99 → 48')
  assert.equal(ctx.getStage1ProvenanceIssues()[0].message, '来源声明已修正')
  assert.equal(ctx.getStage1DataQualityStatusLabel(), '数据质量存在缺口')
  assert.deepEqual(ctx.getStage1DataQualityCoverageItems(), [
    { key: 'source_date', label: '来源日期', count: 2, total: 2, display: '2/2', gap: false },
    { key: 'source_locator', label: '精确定位', count: 1, total: 2, display: '1/2', gap: true },
    { key: 'analysis_date', label: '计算日期', count: 1, total: 1, display: '1/1', gap: false },
    { key: 'sample_diagnostics', label: '样本诊断', count: 0, total: 1, display: '0/1', gap: true },
    { key: 'coordinate_system', label: '坐标口径', count: 1, total: 1, display: '1/1', gap: false },
  ])
  const qualityIssues = ctx.getStage1DataQualityIssues()
  qualityIssues[0].message = 'changed'
  assert.equal(ctx.getStage1DataQualityIssues()[0].message, '缺少样本诊断')
  assert.equal(ctx.getStage1DataQualityCoordinateText(), 'EPSG:4490')
  assert.equal(ctx.getStage1HardConstraintStatusLabel(), '硬约束待核验')
  const hardConstraints = ctx.getStage1HardConstraintAssessments()
  hardConstraints[0].finding = 'changed'
  assert.equal(ctx.getStage1HardConstraintAssessments()[0].finding, '统一运营授权已核验')
  assert.equal(ctx.getStage1HardConstraintStateLabel(hardConstraints[1]), '待核验')
  assert.equal(ctx.getStage1HardConstraintEffectLabel(hardConstraints[1]), '作为前置条件')
  assert.equal(ctx.getStage1HardConstraintPendingActions()[0].executor, 'manual_authority')
  assert.equal(ctx.getStage1EvidenceCount(), 2)
  assert.equal(ctx.getStage1SpaceDecisionCount(), 1)
  const decision = ctx.getStage1SpaceDecisions()[0]
  const mapBinding = ctx.getStage1MapBinding(decision)
  mapBinding.feature.geometry.coordinates[0][0][0] = 0
  assert.equal(ctx.getStage1MapBinding(ctx.getStage1SpaceDecisions()[0]).feature.geometry.coordinates[0][0][0], 112)
  assert.deepEqual(ctx.getStage1SpaceManagementRows(), [{
    space_id: 'unit-1', space_name: '原县政府礼堂', hierarchy_id: 'unit-1', hierarchy_level: 'unit', hierarchy_label: '单元层',
    future_role: '社区文化锚点', preferred_function: '文化活动',
    core_audiences: '社区家庭；青年社群', movement_role: '主游线目的地', value_role: '公共服务与活动引流',
    recommendation_status: 'conditional', recommendation_label: '条件推荐', preconditions: '完成消防评估', evidence_count: 3,
    map_bound: true, map_label: '礼堂建筑轮廓',
  }])
  ctx.openStage1EvidenceDrawer(ctx.getStage1SpaceDecisions()[0])
  assert.equal(ctx.getStage1EvidenceDrawerDecision().space_id, 'unit-1')
  const evidenceEntries = ctx.getStage1DecisionEvidenceEntries(ctx.getStage1EvidenceDrawerDecision())
  assert.equal(evidenceEntries.length, 3)
  assert.equal(evidenceEntries[0].claim, '礼堂具备社区公共记忆价值')
  assert.equal(evidenceEntries[1].verification_task.next_action, '现场踏勘')
  assert.equal(evidenceEntries[1].quality_issues[0].message, '缺少样本诊断')
  assert.equal(evidenceEntries[1].conflicts[0].label, '居民户数')
  assert.equal(evidenceEntries[2].missing, true)
  evidenceEntries[0].claim = 'changed'
  assert.equal(ctx.getStage1DecisionEvidenceEntries(ctx.getStage1EvidenceDrawerDecision())[0].claim, '礼堂具备社区公共记忆价值')
  assert.equal(ctx.getStage1EvidenceTypeLabel(evidenceEntries[0]), '项目事实')
  assert.equal(ctx.getStage1EvidenceStatusLabel(evidenceEntries[1]), '需现场核验')
  assert.equal(ctx.getStage1EvidenceSourceText(evidenceEntries[0]), '项目基础资料 · document:brief:node-1 · p.12')
  assert.equal(ctx.getStage1EvidenceDateText(evidenceEntries[0]), '来源 2025')
  assert.equal(ctx.getStage1EvidenceMetricText(evidenceEntries[0]), '历史价值：社区公共记忆节点')
  assert.match(ctx.getStage1EvidenceQualityText(evidenceEntries[0]), /高置信证据/)
  assert.match(ctx.getStage1EvidenceGapText(evidenceEntries[1]), /尚未完成现场核验/)
  assert.equal(ctx.getStage1EvidenceNextActionText(evidenceEntries[1]), '现场踏勘')
  ctx.agentPanelPayloads.capability_run.run_id = 'caprun-2'
  assert.equal(ctx.getStage1EvidenceDrawerDecision(), null)
  ctx.agentPanelPayloads.capability_run.run_id = 'caprun-1'
  ctx.closeStage1EvidenceDrawer()
  assert.equal(ctx.getStage1EvidenceDrawerDecision(), null)
  const matrix = ctx.getStage1SpatialMatrix()
  matrix.space_decisions[0].preferred_function.name = 'changed'
  assert.equal(ctx.getStage1SpaceDecisions()[0].preferred_function.name, '文化活动')
  assert.equal(ctx.getStage1FunctionLabel(ctx.getStage1SpaceDecisions()[0].preferred_function), '文化活动')
  assert.equal(ctx.getStage1FunctionListText(ctx.getStage1SpaceDecisions()[0].candidate_functions), '文化活动、社区零售')
  assert.equal(ctx.getStage1DecisionDetailText(ctx.getStage1SpaceDecisions()[0].change_logic), '补足社区文化活动空间')
  assert.equal(ctx.getStage1DecisionStatusLabel(ctx.getStage1SpaceDecisions()[0]), '条件推荐')
  assert.equal(ctx.getStage1DecisionConfidenceLabel(ctx.getStage1SpaceDecisions()[0]), '中置信')
  const deliverables = ctx.getStage1Deliverables()
  deliverables.artifacts[0].filename = 'changed.md'
  deliverables.design_handoff.space_requirements[0].space_id = 'changed'
  assert.equal(ctx.getStage1DeliverableArtifacts()[0].filename, 'stage1_report.md')
  assert.equal(ctx.getStage1DesignHandoff().space_requirements[0].space_id, 'unit-1')
  assert.equal(ctx.getStage1DesignHandoff().positioning_option_id, 'option-a')
  assert.equal(ctx.getStage1DesignHandoffSpaceCount(), 1)
  assert.equal(ctx.getStage1DesignHandoffConstraintCount(), 1)
  assert.deepEqual(ctx.getStage1SpatialMapModes().map(item => item.id), [
    'current_state', 'suggested_function', 'recommendation_strength', 'risk', 'implementation_phase',
  ])
  const legend = ctx.getStage1SpatialPresentationLegend()
  legend[0].label = 'changed'
  assert.equal(ctx.getStage1SpatialPresentationLegend()[0].label, '文化活动')
  assert.deepEqual(ctx.getStage1SpatialHierarchyLevels().map(item => item.id), ['all', 'system', 'cluster', 'unit'])
  assert.equal(ctx.getStage1SpaceManagementRows()[0].hierarchy_label, '单元层')
  assert.deepEqual(ctx.getStage1MovementTypes().map(item => item.label), ['全部流线', '游客', '居民', '后勤', '消防应急'])
  assert.equal(ctx.getStage1MovementRouteCount(), 4)
  assert.equal(ctx.getStage1MovementBoundCount(), 1)
})

test('Stage 1 spatial presentation renders authoritative geometry with server colors', () => {
  const calls = []
  let clickHandler = null
  const matrix = {
    space_decisions: [{ space_id: 'space-1', space_name: '礼堂' }],
    map_presentation: {
      modes: [{ id: 'risk', label: '风险', legend: [{ key: 'high', label: '高风险', color: '#ea580c' }] }],
      hierarchy_levels: [{ id: 'unit', label: '单元层', decision_count: 1 }],
      items: [{
        space_id: 'space-1', hierarchy_level: 'unit',
        map_binding: { status: 'bound', feature: { type: 'Feature', geometry: { type: 'Point', coordinates: [112, 28] } } },
        values: { risk: { key: 'high', label: '高风险', color: '#ea580c' } },
      }],
    },
  }
  const ctx = createContext({
    stage1SpatialMapMode: 'risk',
    agentPanelPayloads: { capability_run: { run_id: 'run-1' }, stage1_spatial_matrix: matrix },
    mapCore: {
      showSpatialPresentation(items, options) { calls.push({ items, options }); clickHandler = options.onClick; return items.length },
      clearSpatialPresentation() {},
    },
  })

  assert.equal(ctx.renderStage1SpatialPresentation(), 1)
  assert.equal(calls[0].items[0].color, '#ea580c')
  assert.deepEqual(calls[0].items[0].feature.geometry.coordinates, [112, 28])
  clickHandler(calls[0].items[0])
  assert.equal(ctx.stage1ExpandedSpaceId, 'space-1')
  assert.match(ctx.stage1SpatialPresentationMessage, /高风险|风险/)
})

test('Stage 1 spatial presentation filters hierarchy and reports missing geometry', () => {
  let rendered = null
  const ctx = createContext({
    stage1SpatialMapMode: 'current_state',
    stage1SpatialHierarchyLevel: 'cluster',
    agentPanelPayloads: {
      stage1_spatial_matrix: {
        space_decisions: [],
        map_presentation: {
          modes: [{ id: 'current_state', label: '现状', legend: [] }],
          hierarchy_levels: [{ id: 'unit', label: '单元层', decision_count: 1 }],
          items: [{ space_id: 'space-1', hierarchy_level: 'unit', map_binding: { status: 'unavailable' }, values: {} }],
        },
      },
    },
    mapCore: { showSpatialPresentation(items) { rendered = items; return 0 }, clearSpatialPresentation() {} },
  })

  assert.equal(ctx.renderStage1SpatialPresentation(), 0)
  assert.deepEqual(rendered, [])
  assert.equal(ctx.stage1SpatialPresentationMessage, '当前筛选下没有已绑定权威几何的空间决策。')
})

test('Stage 1 movement presentation uses server labels colors and authoritative paths', () => {
  let rendered = null
  let clickHandler = null
  const matrix = {
    space_decisions: [{ space_id: 'space-1', space_name: '礼堂' }],
    movement_presentation: {
      types: [
        { id: 'visitor', label: '游客', color: '#2563eb', route_count: 1 },
        { id: 'resident', label: '居民', color: '#16a34a', route_count: 0 },
        { id: 'service', label: '后勤', color: '#d97706', route_count: 0 },
        { id: 'fire', label: '消防应急', color: '#dc2626', route_count: 0 },
      ],
      items: [{
        route_id: 'route-visitor', movement_type: 'visitor', movement_label: '游客', color: '#2563eb', title: '游客主游线', affected_space_ids: ['space-1'],
        map_binding: { status: 'bound', feature: { type: 'Feature', geometry: { type: 'LineString', coordinates: [[112, 28], [112.01, 28.01]] } } },
      }],
      bound_item_count: 1,
    },
  }
  const ctx = createContext({
    agentPanelPayloads: { capability_run: { run_id: 'run-1' }, stage1_spatial_matrix: matrix },
    mapCore: {
      showSpatialPresentation(items, options) { rendered = items; clickHandler = options.onClick; return items.length },
    },
  })

  assert.equal(ctx.renderStage1MovementPresentation(), 1)
  assert.equal(rendered[0].color, '#2563eb')
  assert.equal(rendered[0].feature.geometry.type, 'LineString')
  clickHandler(rendered[0])
  assert.equal(ctx.stage1SelectedMovementRouteId, 'route-visitor')
  assert.equal(ctx.stage1ExpandedSpaceId, 'space-1')
  assert.match(ctx.stage1MovementPresentationMessage, /权威路径覆盖物/)
})

test('Stage 1 movement presentation filters types and exposes unavailable paths', () => {
  let rendered = null
  const ctx = createContext({
    stage1MovementType: 'service',
    agentPanelPayloads: {
      stage1_spatial_matrix: {
        movement_presentation: {
          types: [{ id: 'service', label: '后勤', color: '#d97706', route_count: 1 }],
          items: [{ route_id: 'route-service', movement_type: 'service', movement_label: '后勤', color: '#d97706', map_binding: { status: 'unavailable', reason: '待测绘' } }],
          bound_item_count: 0,
        },
      },
    },
    mapCore: { showSpatialPresentation(items) { rendered = items; return 0 } },
  })

  assert.equal(ctx.renderStage1MovementPresentation(), 0)
  assert.deepEqual(rendered, [])
  assert.equal(ctx.getStage1MovementItems()[0].map_binding.reason, '待测绘')
  assert.match(ctx.stage1MovementPresentationMessage, /缺口和核验动作/)
})

test('Stage 1 spatial reset clears focus and presentation overlays', () => {
  let focusClears = 0
  let presentationClears = 0
  const ctx = createContext({
    mapCore: {
      clearSpatialFeatureFocus: () => { focusClears += 1 },
      clearSpatialPresentation: () => { presentationClears += 1 },
    },
    stage1SpatialPresentationMessage: '已显示',
    stage1SelectedMovementRouteId: 'route-visitor',
    stage1MovementPresentationMessage: '已显示流线',
  })

  ctx.resetStage1SpatialInteraction()

  assert.equal(focusClears, 1)
  assert.equal(presentationClears, 1)
  assert.equal(ctx.stage1SpatialPresentationMessage, '')
  assert.equal(ctx.stage1SelectedMovementRouteId, '')
  assert.equal(ctx.stage1MovementPresentationMessage, '')
})

test('Stage 1 map focus is bound to the immutable capability Run', () => {
  let clickHandler = null
  const focusCalls = []
  const ctx = createContext({
    mapCore: {
      focusSpatialFeature(feature, options) {
        focusCalls.push({ feature, options })
        clickHandler = options.onClick
        return true
      },
    },
    agentPanelPayloads: {
      capability_run: { run_id: 'run-map-1' },
      stage1_spatial_matrix: {
        space_decisions: [{
          space_id: 'road-space',
          space_name: '南侧入口',
          map_binding: {
            status: 'bound',
            spatial_object_id: 'road:south-entry',
            object_type: 'road_segment',
            title: '南侧入口道路',
            source_ref: 'analysis_snapshot.road.features',
            source_locator: 'analysis_snapshot.road.features/south-entry',
            feature: {
              type: 'Feature',
              properties: { road_id: 'south-entry' },
              geometry: { type: 'LineString', coordinates: [[112, 28], [112.01, 28.01]] },
            },
          },
        }],
      },
    },
  })
  const decision = ctx.getStage1SpaceDecisions()[0]

  assert.equal(ctx.focusStage1SpaceOnMap(decision), true)
  assert.equal(focusCalls.length, 1)
  assert.equal(focusCalls[0].options.fitView, true)
  assert.equal(ctx.isStage1SpaceMapFocused(decision), true)
  assert.equal(ctx.isStage1SpaceDecisionExpanded(decision), true)
  assert.match(ctx.stage1MapFocusMessage, /南侧入口道路/)

  ctx.stage1ExpandedSpaceId = ''
  ctx.stage1ExpandedRunId = ''
  clickHandler()
  assert.equal(ctx.isStage1SpaceDecisionExpanded(decision), true)

  ctx.agentPanelPayloads.capability_run.run_id = 'run-map-2'
  assert.equal(ctx.isStage1SpaceMapFocused(decision), false)
  assert.equal(ctx.isStage1SpaceDecisionExpanded(decision), false)
})

test('Stage 1 map focus is cleared when the active capability Run changes', () => {
  let clears = 0
  const ctx = createContext({
    mapCore: { clearSpatialFeatureFocus: () => { clears += 1 } },
    stage1ExpandedSpaceId: 'space-1',
    stage1ExpandedRunId: 'run-1',
    stage1MapFocusedSpaceId: 'space-1',
    stage1MapFocusedRunId: 'run-1',
    stage1MapFocusMessage: '已定位',
  })
  const watcher = createAnalysisLifecycleHooks().watch['agentPanelPayloads.capability_run.run_id']

  watcher.call(ctx, 'run-2', 'run-1')

  assert.equal(clears, 1)
  assert.equal(ctx.stage1ExpandedSpaceId, '')
  assert.equal(ctx.stage1MapFocusedRunId, '')
  assert.equal(ctx.stage1MapFocusMessage, '')
})

test('Stage 1 map focus reports unavailable bindings without touching the map', () => {
  let focusCalls = 0
  const ctx = createContext({
    mapCore: { focusSpatialFeature: () => { focusCalls += 1; return true } },
    agentPanelPayloads: {
      capability_run: { run_id: 'run-map-1' },
      stage1_spatial_matrix: {
        space_decisions: [{
          space_id: 'courtyard-1',
          map_binding: { status: 'unavailable', reason: '尚未提供庭院权威轮廓。' },
        }],
      },
    },
  })
  const decision = ctx.getStage1SpaceDecisions()[0]

  assert.equal(ctx.focusStage1SpaceOnMap(decision), false)
  assert.equal(focusCalls, 0)
  assert.equal(ctx.stage1MapFocusMessage, '尚未提供庭院权威轮廓。')
})

test('Stage 1 quality gate distinguishes ready and conditional delivery', () => {
  const artifacts = [
    { artifact_id: 'stage1-report', status: 'ready' },
    { artifact_id: 'stage1-evidence-appendix', status: 'ready' },
    { artifact_id: 'stage1-design-handoff', status: 'ready' },
  ]
  const ready = createContext({
    agentPanelPayloads: {
      stage1_quality_audit: { status: 'passed', score: 100, checks_passed: 16, checks_total: 16, issues: [] },
      stage1_evidence_verification: { status: 'passed', report_allowed: true, status_counts: { verified: 3 }, blocking_reasons: [], tasks: [] },
      stage1_provenance_binding: { status: 'passed', assessed_count: 3, status_counts: { verified: 3 }, issues: [] },
      stage1_data_quality: { status: 'passed', assessed_count: 3, issues: [] },
      stage1_hard_constraint_screening: { status: 'clear', assessments: [{ constraint_id: 'ownership', state: 'verified' }], pending_actions: [] },
      stage1_deliverables: { status: 'ready', artifacts },
    },
  })
  assert.equal(ready.getStage1QualityGate().status, 'ready')
  assert.equal(ready.getStage1QualityGate().blocking_items.length, 0)

  const review = createContext({
    agentPanelPayloads: {
      ...ready.agentPanelPayloads,
      stage1_evidence_verification: {
        status: 'passed_with_gaps',
        report_allowed: true,
        status_counts: { verified: 2, fieldwork_required: 1 },
        blocking_reasons: [],
        tasks: [{ evidence_id: 'e3', status: 'fieldwork_required', executor: 'fieldwork' }],
      },
    },
  })
  assert.equal(review.getStage1QualityGate().status, 'review')
  assert.equal(review.getStage1QualityGate().task_total, 1)
})

test('analysis workspace templates expose capability navigation and detail view', async () => {
  const [main, sidebar] = await Promise.all([
    fs.promises.readFile(new URL('../src/pages/analysis/components/main.html', import.meta.url), 'utf8'),
    fs.promises.readFile(new URL('../src/pages/analysis/components/sidebar.html', import.meta.url), 'utf8'),
  ])
  assert.match(main, /agentWorkspaceView === 'capabilities'/)
  assert.match(main, /getAnalysisCapabilityGroups\(\)/)
  assert.match(main, /上游版本选择/)
  assert.match(main, /不静默读取运行时文件/)
  assert.match(main, /运行前摘要/)
  assert.match(main, /运行中的任务不受后续配置修改影响/)
  assert.match(main, /getAnalysisCapabilityRunPreview/)
  assert.match(main, /锁定的上游输入/)
  assert.match(main, /将生成的产物/)
  assert.match(main, /确认并运行/)
  assert.match(main, /setAnalysisCapabilityInputMode/)
  assert.match(main, /setAnalysisCapabilityInputRun/)
  assert.match(main, /inspectAnalysisCapability\(capability\)/)
  assert.match(main, /runAnalysisCapability\(getActiveAnalysisCapability\(\)\)/)
  assert.match(main, /getCapabilityRun\(\)/)
  assert.match(main, /Capability Run/)
  assert.match(main, /查看不可变运行快照与阶段记录/)
  assert.match(main, /getCapabilityRunStages\(\)/)
  assert.match(main, /产物索引与血缘/)
  assert.match(main, /getCapabilityRunOutputArtifacts\(\)/)
  assert.match(main, /getCapabilityRunArtifactTypeLabel\(artifact\)/)
  assert.match(main, /getCapabilityRunArtifactLineageText\(artifact\)/)
  assert.match(main, /运行版本/)
  assert.match(main, /getAnalysisCapabilityRuns\(\)/)
  assert.match(main, /selectAnalysisCapabilityRun\(run\)/)
  assert.match(main, /不可变历史快照/)
  assert.match(main, /上游输入已更新/)
  assert.match(main, /getAnalysisCapabilityRunChangedInputIds\(run\)/)
  assert.match(main, /返回当前结果/)
  assert.match(main, /继续追问此版本/)
  assert.match(main, /openCapabilityRunContextAsk\(getSelectedAnalysisCapabilityRunDetail\(\)\)/)
  assert.match(main, /继续追问当前版本/)
  assert.match(main, /openCapabilityRunContextAsk\(\)/)
  assert.match(main, /getSelectedAnalysisCapabilityRunArtifacts\(\)/)
  assert.match(main, /版本比较/)
  assert.match(main, /compareSelectedAnalysisCapabilityRun\(\)/)
  assert.match(main, /核心结果变化/)
  assert.match(main, /仅保存元数据/)
  assert.match(main, /getStage1QualityGate\(\)/)
  assert.match(main, /Stage 1 Quality Gate/)
  assert.match(main, /硬约束筛选/)
  assert.match(main, /getStage1HardConstraintAssessments\(\)/)
  assert.match(main, /getStage1HardConstraintEffectLabel\(assessment\)/)
  assert.match(main, /交付前必须修复/)
  assert.match(main, /待核验责任/)
  assert.match(main, /getStage1EvidenceVerification\(\)/)
  assert.match(main, /Agent 自动核验记录/)
  assert.match(main, /getStage1AutomatedVerificationChecks\(\)/)
  assert.match(main, /尚待完成的核验任务/)
  assert.match(main, /getStage1VerificationTaskExecutorLabel\(task\)/)
  assert.match(main, /task\.verification_method/)
  assert.match(main, /task\.decision_impact/)
  assert.match(main, /证据与真实数据资产/)
  assert.match(main, /getStage1ProvenanceBindings\(\)/)
  assert.match(main, /getStage1ProvenanceDiscrepancyText\(binding\)/)
  assert.match(main, /数据质量与时空口径/)
  assert.match(main, /getStage1DataQualityCoverageItems\(\)/)
  assert.match(main, /空间功能策划决策矩阵/)
  assert.match(main, /getStage1SpaceDecisions\(\)/)
  assert.match(main, /getStage1DecisionStatusLabel\(decision\)/)
  assert.match(main, /管理层总览用于比较/)
  assert.match(main, /getStage1SpaceManagementRows\(\)/)
  assert.match(main, /focusStage1SpaceOnMap/)
  assert.match(main, /getStage1MapBindingLabel/)
  assert.match(main, /getStage1DecisionEvidenceEntries/)
  assert.match(main, /Decision Evidence/)
  assert.match(main, /来源冲突与裁决状态/)
  assert.match(main, /getStage1ConflictRegister\(\)/)
  assert.match(main, /正式交付物/)
  assert.match(main, /getStage1DeliverableArtifacts\(\)/)
  assert.match(main, /getStage1DesignHandoffConstraintCount\(\)/)
  assert.match(main, /交付前必须修复/)
  assert.match(sidebar, /openAnalysisCapabilitiesPanel/)
  assert.match(sidebar, />分析能力</)
})


test('upstream input selection serializes a locked historical run', async () => {
  let refreshed = 0
  const capability = {
    id: 'spatial-programming-matrix',
    status: 'available',
    input_requirements: [{
      id: 'stage1_basis',
      selection_modes: ['latest_successful', 'specific_run', 'recalculate'],
    }],
  }
  const ctx = createContext({
    analysisCapabilities: [capability],
    activeAnalysisCapabilityId: capability.id,
    analysisCapabilityReadiness: {
      [capability.id]: {
        status: 'ready',
        input_resolutions: [{
          requirement_id: 'stage1_basis',
          selection_mode: 'latest_successful',
          state: 'resolved',
          selected_run_id: 'run-current',
          available_versions: [{ run_id: 'run-history', stale: true }],
        }],
      },
    },
    refreshAnalysisCapabilityReadiness: async () => { refreshed += 1 },
  })

  await ctx.setAnalysisCapabilityInputMode(capability.id, 'stage1_basis', 'specific_run')
  assert.equal(refreshed, 0)
  await ctx.setAnalysisCapabilityInputRun(capability.id, 'stage1_basis', 'run-history')

  assert.equal(refreshed, 1)
  assert.deepEqual(ctx.buildAnalysisCapabilityInputSelections(capability.id), [{
    requirement_id: 'stage1_basis',
    mode: 'specific_run',
    run_id: 'run-history',
  }])
  assert.match(ctx.getAnalysisCapabilityVersionLabel({ run_id: 'run-history', stale: true }), /已过期/)
})

test('running a ready capability forwards target id and explicit upstream policy', async () => {
  let submitted = null
  const capability = {
    id: 'spatial-programming-matrix',
    status: 'available',
    executor_type: 'skill',
    executor_id: 'urban-strategy-stage1',
    description: '生成空间矩阵',
  }
  const skill = { id: 'urban-strategy-stage1' }
  const ctx = createContext({
    analysisCapabilities: [capability],
    activeAnalysisCapabilityId: capability.id,
    analysisCapabilityReadiness: {
      [capability.id]: {
        status: 'ready',
        input_resolutions: [{
          requirement_id: 'stage1_basis',
          selection_mode: 'specific_run',
          selected_run_id: 'run-1',
          state: 'resolved',
        }],
      },
    },
    analysisCapabilityInputSelections: {
      [capability.id]: { stage1_basis: { mode: 'specific_run', run_id: 'run-1' } },
    },
    agentSkills: [skill],
    loadAgentCapabilities: async () => {},
    chooseAgentSkill: () => {},
    submitAgentComposer: async options => { submitted = options },
    loadAnalysisCapabilityRuns: async () => [],
  })

  await ctx.runAnalysisCapability(capability)

  assert.equal(submitted.targetCapabilityId, capability.id)
  assert.deepEqual(submitted.capabilityInputSelections, [{
    requirement_id: 'stage1_basis',
    mode: 'specific_run',
    run_id: 'run-1',
  }])
})

test('run preview presents the exact readiness-locked execution contract', () => {
  const capability = {
    id: 'spatial-programming-matrix',
    display_name: '空间功能策划矩阵',
    executor_type: 'skill',
    executor_id: 'urban-strategy-stage1',
    estimated_stages: 4,
    output_contract: ['空间功能决策矩阵', '设计约束'],
  }
  const readiness = {
    status: 'ready',
    missing_required: [],
    missing_optional: [],
    conflicts: [],
    actions: [],
    input_resolutions: [{
      requirement_id: 'stage1_basis',
      label: 'Stage 1 结构化成果',
      selection_mode: 'latest_successful',
      selected_run_id: 'run-stage1-7',
      state: 'resolved',
      artifact_refs: [{ artifact_id: 'stage1-report' }, { artifact_id: 'stage1-design-handoff' }],
    }],
  }
  const originalReadiness = structuredClone(readiness)
  const ctx = createContext({
    analysisCapabilities: [capability],
    activeAnalysisCapabilityId: capability.id,
    analysisCapabilityReadiness: { [capability.id]: readiness },
    buildAgentAnalysisSnapshot: () => ({
      context: { mode: 'walking', time_min: 15, source: 'gaode', history_id: 'history-1' },
      scope: { drawn_polygon: [[116.1, 39.9], [116.2, 39.9], [116.2, 40], [116.1, 39.9]] },
      current_filters: { h3_resolution: 9, road_metric: 'integration' },
    }),
    getAgentAnalysisSourceState: () => ({
      sources: [{
        id: 'document:brief',
        title: '项目任务书',
        type: 'document',
        selected: true,
        status: 'ready',
        meta: { aiPayload: { source_id: 'document:brief', title: '项目任务书', source_kind: 'document', document_role: 'project_brief', included: ['document_identity'] } },
      }],
    }),
  })

  const preview = ctx.getAnalysisCapabilityRunPreview(capability)

  assert.equal(preview.status, 'ready')
  assert.equal(preview.scope, '当前地图多边形 · 4 个顶点')
  assert.equal(preview.model, 'DeepSeek Chat')
  assert.equal(preview.executor, 'Skill · urban-strategy-stage1')
  assert.equal(preview.estimated_stages, 4)
  assert.deepEqual(preview.sources.map(item => item.title), ['项目任务书'])
  assert.deepEqual(preview.selected_inputs[0], {
    requirement_id: 'stage1_basis',
    label: 'Stage 1 结构化成果',
    state: 'resolved',
    mode: 'specific_run',
    run_id: 'run-stage1-7',
    artifact_count: 2,
  })
  assert.deepEqual(preview.outputs, ['空间功能决策矩阵', '设计约束'])
  assert.ok(preview.parameters.some(item => item.label === '时间阈值' && item.value === '15 分钟'))
  assert.deepEqual(readiness, originalReadiness)
})

test('run preview makes blockers and optional gaps explicit before execution', () => {
  const capability = {
    id: 'evidence-audit',
    display_name: '证据与结论审计',
    executor_type: 'skill',
    executor_id: 'urban-strategy-stage1',
    output_contract: ['Claim-Evidence 台账'],
  }
  const ctx = createContext({
    analysisCapabilities: [capability],
    activeAnalysisCapabilityId: capability.id,
    analysisCapabilityReadiness: {
      [capability.id]: {
        status: 'blocked',
        missing_required: ['项目证据'],
        missing_optional: ['历史成果'],
        conflicts: ['来源时间口径不一致'],
        actions: [{ id: 'upload', label: '上传项目任务书', target: 'sources' }],
        input_resolutions: [],
      },
    },
  })

  const preview = ctx.getAnalysisCapabilityRunPreview(capability)

  assert.equal(preview.status, 'blocked')
  assert.deepEqual(preview.risks, [
    { level: 'blocked', label: '缺少必需输入：项目证据' },
    { level: 'blocked', label: '输入冲突：来源时间口径不一致' },
    { level: 'warning', label: '可选缺口：历史成果' },
    { level: 'warning', label: '建议处理：上传项目任务书' },
  ])
})

test('execution freezes readiness-resolved latest input to its immutable run', () => {
  const ctx = createContext({
    analysisCapabilityReadiness: {
      'ppt-planning': {
        status: 'ready',
        input_resolutions: [{
          requirement_id: 'approved_report',
          selection_mode: 'latest_successful',
          selected_run_id: 'run-selected-during-readiness',
          state: 'resolved',
        }],
      },
    },
    analysisCapabilityInputSelections: {
      'ppt-planning': { approved_report: { mode: 'latest_successful', run_id: 'run-selected-during-readiness' } },
    },
  })

  assert.deepEqual(ctx.buildAnalysisCapabilityInputSelections('ppt-planning'), [{
    requirement_id: 'approved_report',
    mode: 'latest_successful',
  }])
  assert.deepEqual(ctx.buildLockedAnalysisCapabilityInputSelections('ppt-planning'), [{
    requirement_id: 'approved_report',
    mode: 'specific_run',
    run_id: 'run-selected-during-readiness',
  }])
})

test('PPT execution receives the readiness-locked Stage 1 run', async () => {
  let openedWith = null
  const capability = { id: 'ppt-planning', status: 'available', executor_type: 'service', executor_id: 'ppt-planning' }
  const ctx = createContext({
    analysisCapabilityReadiness: {
      [capability.id]: {
        status: 'ready',
        input_resolutions: [{
          requirement_id: 'approved_report',
          selection_mode: 'latest_successful',
          selected_run_id: 'run-locked',
          state: 'resolved',
        }],
      },
    },
    openAgentPptPlanningFromReport: options => { openedWith = options },
  })

  await ctx.runAnalysisCapability(capability)

  assert.deepEqual(openedWith.capabilityInputSelections, [{
    requirement_id: 'approved_report',
    mode: 'specific_run',
    run_id: 'run-locked',
  }])
})


test('workbench overview centralizes card readiness, recent runs and recommendation', async () => {
  const originalFetch = global.fetch
  let requestBody = null
  global.fetch = async (url, options) => {
    assert.match(String(url), /analysis-capabilities\/workbench$/)
    requestBody = JSON.parse(options.body)
    return {
      ok: true,
      json: async () => ({
        cards: [
          {
            capability_id: 'urban-strategy-stage1',
            state: 'ready',
            run_count: 0,
            latest_run: null,
            readiness: { capability_id: 'urban-strategy-stage1', status: 'ready', missing_required: [] },
          },
        ],
        recent_runs: [{ run_id: 'run-1', capability_id: 'urban-strategy-stage1', status: 'completed' }],
        recommendation: { capability_id: 'urban-strategy-stage1', action: 'run', reason: '输入已就绪' },
      }),
    }
  }
  try {
    const ctx = createContext()
    const overview = await ctx.loadAnalysisCapabilityOverview()
    assert.equal(requestBody.history_id, 'history-1')
    assert.equal(requestBody.conversation_id, 'conversation-1')
    assert.equal(overview.recommendation.action, 'run')
    assert.equal(ctx.getAnalysisCapabilityReadiness('urban-strategy-stage1').status, 'ready')
    overview.cards[0].state = 'changed'
    assert.equal(ctx.getAnalysisCapabilityOverviewCard('urban-strategy-stage1').state, 'ready')
  } finally {
    global.fetch = originalFetch
  }
})

test('capability discovery filters by status and searchable contract text', () => {
  const ctx = createContext({
    analysisCapabilities: [
      { id: 'urban-strategy-stage1', category: 'planning', display_name: '城市更新 Stage 1', description: '形成策划报告', output_contract: ['设计任务书'], input_requirements: [] },
      { id: 'ppt-planning', category: 'delivery', display_name: '成果 PPT', description: '演示文稿', output_contract: ['可编辑 PPT'], input_requirements: [] },
    ],
    analysisCapabilityOverview: {
      cards: [
        { capability_id: 'urban-strategy-stage1', state: 'completed', readiness: { status: 'ready' }, run_count: 2 },
        { capability_id: 'ppt-planning', state: 'blocked', readiness: { status: 'blocked', missing_required: ['已审定报告'] }, run_count: 0 },
      ],
      recent_runs: [],
      recommendation: null,
    },
  })

  ctx.analysisCapabilityStatusFilter = 'blocked'
  assert.deepEqual(ctx.getFilteredAnalysisCapabilities().map(item => item.id), ['ppt-planning'])
  ctx.analysisCapabilityStatusFilter = 'all'
  ctx.analysisCapabilitySearchQuery = '设计任务书'
  assert.deepEqual(ctx.getFilteredAnalysisCapabilities().map(item => item.id), ['urban-strategy-stage1'])
  ctx.analysisCapabilitySearchQuery = '不存在'
  assert.deepEqual(ctx.getAnalysisCapabilityGroups(), [])
})

test('recommended and recent capability actions open the exact capability run', async () => {
  const selected = []
  const ctx = createContext({
    analysisCapabilities: [{ id: 'urban-strategy-stage1', display_name: '城市更新 Stage 1' }],
    analysisCapabilityOverview: {
      cards: [],
      recent_runs: [],
      recommendation: { capability_id: 'urban-strategy-stage1', action: 'inspect_run', run_id: 'run-7', reason: '任务进行中' },
    },
    inspectAnalysisCapability: async capability => {
      ctx.activeAnalysisCapabilityId = capability.id
      ctx.analysisCapabilityRuns = [{ run_id: 'run-7', capability_id: capability.id, status: 'running' }]
    },
    selectAnalysisCapabilityRun: async run => { selected.push(run.run_id) },
  })

  await ctx.openAnalysisCapabilityRecommendation()
  assert.equal(ctx.activeAnalysisCapabilityId, 'urban-strategy-stage1')
  assert.deepEqual(selected, ['run-7'])
  assert.equal(ctx.getAnalysisCapabilityRecommendationLabel(ctx.getAnalysisCapabilityRecommendation()), '查看当前任务')
})


test('analysis workspace template exposes recommendation, recent runs and discovery controls', () => {
  const template = fs.readFileSync(new URL('../src/pages/analysis/components/main.html', import.meta.url), 'utf8')
  assert.match(template, /getAnalysisCapabilityRecommendation\(\)/)
  assert.match(template, /getAnalysisCapabilityRecentRuns\(\)/)
  assert.match(template, /analysisCapabilitySearchQuery/)
  assert.match(template, /analysisCapabilityStatusFilter/)
  assert.match(template, /getAnalysisCapabilityCardStateLabel/)
  assert.match(template, /getAnalysisCapabilityIntentResolution\(\)/)
  assert.match(template, /availability_note/)
  assert.match(template, /activation_requirements/)
})


test('late workbench overview cannot leak recommendations across histories', async () => {
  const originalFetch = global.fetch
  const pending = []
  global.fetch = async () => ({
    ok: true,
    json: () => new Promise(resolve => pending.push(resolve)),
  })
  try {
    let historyId = 'history-a'
    const ctx = createContext({ getCurrentAgentHistoryId: () => historyId })
    const first = ctx.loadAnalysisCapabilityOverview(true)
    await Promise.resolve()
    historyId = 'history-b'
    const second = ctx.loadAnalysisCapabilityOverview(true)
    await Promise.resolve()
    pending[1]({ cards: [], recent_runs: [], recommendation: { capability_id: 'new', action: 'run', reason: 'new' } })
    await second
    pending[0]({ cards: [], recent_runs: [], recommendation: { capability_id: 'old', action: 'run', reason: 'old' } })
    await first
    assert.equal(ctx.getAnalysisCapabilityRecommendation().capability_id, 'new')
    assert.equal(ctx.analysisCapabilityOverviewHistoryId, 'history-b')
  } finally {
    global.fetch = originalFetch
  }
})


test('explicit conversation capability intent opens the authoritative workbench target', async () => {
  const originalFetch = global.fetch
  const calls = []
  global.fetch = async (url, options) => {
    calls.push({ url: String(url), body: JSON.parse(options.body) })
    return {
      ok: true,
      json: async () => ({
        matched: true,
        capability_id: 'spatial-programming-matrix',
        action: 'open_configuration',
        matched_phrase: '生成空间功能策划矩阵',
        reason: '先检查输入并锁定运行版本。',
      }),
    }
  }
  try {
    let openedPanel = false
    let openedCapability = ''
    const ctx = createContext({
      agentInput: '生成空间功能策划矩阵',
      analysisCapabilitiesLoaded: true,
      analysisCapabilities: [{ id: 'spatial-programming-matrix', status: 'available' }],
      openAnalysisCapabilitiesPanel: () => { openedPanel = true },
      openAnalysisCapabilityOverviewTarget: async id => {
        openedCapability = id
        return ctx.analysisCapabilities[0]
      },
    })

    const routed = await ctx.routeAnalysisCapabilityIntent(ctx.agentInput)

    assert.match(calls[0].url, /analysis-capabilities\/resolve-intent$/)
    assert.deepEqual(calls[0].body, { message: '生成空间功能策划矩阵' })
    assert.equal(routed.type, 'capability_intent')
    assert.equal(openedPanel, true)
    assert.equal(openedCapability, 'spatial-programming-matrix')
    assert.equal(ctx.agentInput, '')
    const resolution = ctx.getAnalysisCapabilityIntentResolution()
    resolution.capability_id = 'mutated'
    assert.equal(ctx.getAnalysisCapabilityIntentResolution().capability_id, 'spatial-programming-matrix')
  } finally {
    global.fetch = originalFetch
  }
})

test('unmatched or failed intent resolution leaves ordinary conversation untouched', async () => {
  const originalFetch = global.fetch
  try {
    const ctx = createContext({ agentInput: '解释一下这个指标' })
    global.fetch = async () => ({ ok: true, json: async () => ({ matched: false, action: 'none' }) })
    assert.equal(await ctx.routeAnalysisCapabilityIntent(ctx.agentInput), null)
    assert.equal(ctx.agentInput, '解释一下这个指标')

    global.fetch = async () => { throw new Error('offline') }
    assert.equal(await ctx.routeAnalysisCapabilityIntent(ctx.agentInput), null)
    assert.equal(ctx.agentInput, '解释一下这个指标')
  } finally {
    global.fetch = originalFetch
  }
})

test('unavailable capability contract is searchable and explains activation prerequisites', () => {
  const capability = {
    id: 'rsir-business-analysis',
    category: 'analysis',
    status: 'unavailable',
    display_name: 'RSIR 商业分析',
    description: '商业判断',
    availability_note: '方法契约尚未确认',
    activation_requirements: ['注册可测试的领域执行器'],
    intent_phrases: ['生成 RSIR 商业分析'],
    output_contract: [],
    input_requirements: [],
  }
  const ctx = createContext({ analysisCapabilities: [capability] })

  assert.equal(ctx.getAnalysisCapabilityCardState(capability), 'unavailable')
  assert.equal(ctx.getAnalysisCapabilityCardMeta(capability), '需完成 1 项启用条件')
  ctx.analysisCapabilitySearchQuery = '领域执行器'
  assert.deepEqual(ctx.getFilteredAnalysisCapabilities().map(item => item.id), ['rsir-business-analysis'])
})

test('composer checks explicit capability intent before falling back to chat execution', () => {
  const runtime = fs.readFileSync(new URL('../src/features/agent/runtime.js', import.meta.url), 'utf8')
  assert.match(runtime, /await this\.routeAnalysisCapabilityIntent\(prompt\)/)
  assert.match(runtime, /if \(routed\) return routed/)
  assert.match(runtime, /!explicitTargetCapabilityId/)
})
