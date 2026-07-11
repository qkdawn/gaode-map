import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

import { createAgentCapabilityWorkbenchMethods } from '../src/features/agent/capability-workbench.js'

const methods = createAgentCapabilityWorkbenchMethods()

function createContext(overrides = {}) {
  return {
    ...methods,
    analysisCapabilities: [],
    analysisCapabilitiesLoaded: false,
    analysisCapabilitiesLoading: false,
    analysisCapabilitiesError: '',
    analysisCapabilityReadiness: {},
    analysisCapabilityReadinessLoading: false,
    activeAnalysisCapabilityId: '',
    activeAgentSessionId: 'conversation-1',
    agentSkills: [],
    agentPanelPayloads: {},
    getCurrentAgentHistoryId: () => 'history-1',
    buildAgentAnalysisSnapshot: () => ({ scope: { scope_id: 'scope-1' } }),
    getAgentAnalysisSourceState: () => ({ sources: [] }),
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

test('running a Skill capability selects its executor for the current turn', async () => {
  const selected = []
  const submitted = []
  const skill = { id: 'urban-strategy-stage1', display_name: '城市区域策划第一阶段' }
  const ctx = createContext({
    agentSkills: [skill],
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
    loadAgentCapabilities: async () => {},
    submitAgentComposer: async () => { submitted = true },
  })
  await ctx.runAnalysisCapability({ id: 'urban-strategy-stage1', status: 'available', executor_type: 'skill', executor_id: 'urban-strategy-stage1' })
  assert.equal(submitted, false)
  assert.match(ctx.analysisCapabilitiesError, /Skill 当前不可用/)
})

test('PPT capability reuses the existing planning workbench', async () => {
  let opened = 0
  const ctx = createContext({ openAgentPptPlanningFromReport: () => { opened += 1 } })
  await ctx.runAnalysisCapability({ id: 'ppt-planning', status: 'available', executor_type: 'service', executor_id: 'ppt-planning' })
  assert.equal(opened, 1)
})

test('Stage 1 quality accessors expose verification gaps without mutating payloads', () => {
  const task = { evidence_id: 'e2', executor: 'fieldwork', missing_input: '消防核验', blocking_reason: '缺少现场资料', next_action: '现场踏勘' }
  const ctx = createContext({
    agentPanelPayloads: {
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
      stage1_evidence_ledger: [{ id: 'e1' }, { id: 'e2' }],
      stage1_conflict_register: [
        { metric_key: 'households', label: '居民户数', values: ['102户', '120户'], evidence_ids: ['node-1', 'node-2'], unresolved: true, explanation: '同级项目摘要口径冲突' },
        { metric_key: 'area', label: '项目面积', values: ['2.4公顷', '2.5公顷'], evidence_ids: ['node-3'], unresolved: false, explanation: '采用项目摘要口径' },
      ],
      stage1_spatial_matrix: { space_decisions: [{ id: 's1' }] },
    },
  })
  assert.equal(ctx.hasStage1Outcome(), true)
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
  assert.equal(ctx.getStage1QualityBlockingIssues()[0].code, 'broken-ref')
  const conflicts = ctx.getStage1ConflictRegister()
  conflicts[0].values[0] = 'changed'
  assert.equal(ctx.getStage1ConflictRegister()[0].values[0], '102户')
  assert.equal(ctx.getStage1UnresolvedConflictCount(), 1)
  assert.equal(ctx.getStage1ConflictStatusLabel(conflicts[0]), '待裁决')
  assert.equal(ctx.getStage1ConflictStatusLabel(conflicts[1]), '已确定口径')
  assert.equal(ctx.getStage1ConflictValuesText(ctx.getStage1ConflictRegister()[0]), '102户 / 120户')
  assert.equal(ctx.getStage1EvidenceCount(), 2)
  assert.equal(ctx.getStage1SpaceDecisionCount(), 1)
})

test('analysis workspace templates expose capability navigation and detail view', async () => {
  const [main, sidebar] = await Promise.all([
    fs.promises.readFile(new URL('../src/pages/analysis/components/main.html', import.meta.url), 'utf8'),
    fs.promises.readFile(new URL('../src/pages/analysis/components/sidebar.html', import.meta.url), 'utf8'),
  ])
  assert.match(main, /agentWorkspaceView === 'capabilities'/)
  assert.match(main, /getAnalysisCapabilityGroups\(\)/)
  assert.match(main, /inspectAnalysisCapability\(capability\)/)
  assert.match(main, /runAnalysisCapability\(getActiveAnalysisCapability\(\)\)/)
  assert.match(main, /getStage1EvidenceVerification\(\)/)
  assert.match(main, /Agent 自动核验记录/)
  assert.match(main, /getStage1AutomatedVerificationChecks\(\)/)
  assert.match(main, /尚待完成的核验任务/)
  assert.match(main, /来源冲突与裁决状态/)
  assert.match(main, /getStage1ConflictRegister\(\)/)
  assert.match(main, /交付前必须修复/)
  assert.match(sidebar, /openAnalysisCapabilitiesPanel/)
  assert.match(sidebar, />分析能力</)
})
