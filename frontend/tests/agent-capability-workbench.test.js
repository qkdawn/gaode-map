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

test('Stage 1 quality accessors summarize immutable panel payloads', () => {
  const ctx = createContext({
    agentPanelPayloads: {
      stage1_quality_audit: { passed: false, score: 63 },
      stage1_evidence_ledger: [{ id: 'e1' }, { id: 'e2' }],
      stage1_spatial_matrix: { space_decisions: [{ id: 's1' }] },
    },
  })
  assert.deepEqual(ctx.getStage1QualityAudit(), { passed: false, score: 63 })
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
  assert.match(sidebar, /openAnalysisCapabilitiesPanel/)
  assert.match(sidebar, />分析能力</)
})
