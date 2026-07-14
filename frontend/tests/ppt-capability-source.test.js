import test from 'node:test'
import assert from 'node:assert/strict'

import {
  applyCapabilitySourceSelectionPolicy,
  capabilityInputSelectionFingerprint,
  capabilitySourceRunId,
  createStage1CapabilityFailedSource,
  createStage1CapabilityPlaceholderSource,
  createStage1CapabilityPptSource,
  normalizeCapabilityInputSelections,
} from '../src/features/ppt-planning/capability-source.js'
import {
  createAgentPptPlanningTabMethods,
  normalizeAgentPptPlanningTab,
  serializeAgentPptPlanningTab,
} from '../src/features/agent/ppt-planning-tabs.js'
import {
  buildPptSpecPayload,
  createPptPlanningState,
  getPptSourceDeliveryManifest,
  mergePptPlanningSources,
} from '../src/features/ppt-planning/ui-state.js'

const lockedSelection = runId => [{ requirement_id: 'approved_report', mode: 'specific_run', run_id: runId }]

function stage1RunDetail(runId = 'run-stage1') {
  const artifact = (artifactId, payload, title) => ({
    direction: 'output',
    artifact: {
      artifact_id: artifactId,
      artifact_type: artifactId === 'stage1-design-handoff' ? 'design_handoff' : 'report',
      title,
      version: 'v1',
      source_run_id: runId,
      source_artifact_refs: [],
      evidence_refs: [],
      content_digest: `sha256:${artifactId}`,
      created_at: '2026-07-12T00:00:00Z',
    },
    payload,
  })
  return {
    history_id: 'history-1',
    run: {
      run_id: runId,
      capability_id: 'urban-strategy-stage1',
      status: 'completed',
      completed_at: '2026-07-12T00:00:00Z',
    },
    artifacts: [
      artifact('stage1-report', '# 总体判断\n更新应以公共空间为先导。\n\n## 实施路径\n先治理慢行断点，再导入复合服务。', '第一阶段报告'),
      artifact('stage1-evidence-appendix', '## 道路证据\n路网分析支持慢行连接改善。\n\n## 人口证据\n人口数据仅作为需求代理指标。', '证据附录'),
      artifact('stage1-design-handoff', {
        space_requirements: [{ name: '社区客厅', rationale: '补足公共服务' }],
        unresolved_constraints: ['消防条件仍需现场核验'],
      }, '设计交接'),
    ],
  }
}

test('capability input lock normalization is deterministic and resolves the approved report run', () => {
  const normalized = normalizeCapabilityInputSelections([
    { requirementId: 'optional_input', mode: 'ignore_optional' },
    { requirementId: 'approved_report', mode: 'specific_run', runId: 'run-2' },
  ])
  assert.deepEqual(normalized, [
    { requirement_id: 'approved_report', mode: 'specific_run', run_id: 'run-2' },
    { requirement_id: 'optional_input', mode: 'ignore_optional' },
  ])
  assert.equal(capabilitySourceRunId(normalized), 'run-2')
  assert.equal(capabilityInputSelectionFingerprint([]), '')
  assert.equal(capabilityInputSelectionFingerprint(normalized), capabilityInputSelectionFingerprint([...normalized].reverse()))
})

test('immutable Stage 1 run becomes a selected deliverable PPT source with bounded semantic evidence', () => {
  const source = createStage1CapabilityPptSource(stage1RunDetail(), 'run-stage1')
  const payload = source.meta.aiPayload

  assert.equal(source.id, 'package:stage1-run:run-stage1')
  assert.equal(source.status, 'ready')
  assert.equal(source.selected, true)
  assert.equal(payload.version, 'ppt_ai_input_block_v1')
  assert.match(payload.policy, /不回退到当前运行时文件/)
  assert.ok(payload.evidence_nodes.length >= 5)
  assert.ok(payload.evidence_nodes.every(node => node.content.length <= 680))
  assert.deepEqual(
    new Set(payload.evidence_nodes.map(node => node.data.artifact_id)),
    new Set(['stage1-report', 'stage1-evidence-appendix', 'stage1-design-handoff']),
  )
  assert.ok(payload.evidence_nodes.every(node => node.run_id === 'run-stage1'))
  assert.ok(payload.evidence_nodes.some(node => node.content.includes('社区客厅')))
  assert.ok(payload.evidence_nodes.some(node => node.content.includes('慢行断点')))
})

test('immutable Stage 1 source is included in PPT generation requests', () => {
  const source = createStage1CapabilityPptSource(stage1RunDetail(), 'run-stage1')
  const state = mergePptPlanningSources(createPptPlanningState(), [source])
  const manifest = getPptSourceDeliveryManifest(state)
  const request = buildPptSpecPayload(state, { areaId: 'area-1' })

  assert.deepEqual(manifest.deliverableSourceIds, ['package:stage1-run:run-stage1'])
  assert.deepEqual(request.source_ids, ['package:stage1-run:run-stage1'])
  assert.equal(request.sources[0].meta.aiPayload.version, 'ppt_ai_input_block_v1')
  assert.equal(request.sources[0].meta.aiPayload.evidence_nodes[0].run_id, 'run-stage1')
})

test('missing immutable artifacts fail closed instead of falling back to current data', () => {
  const detail = stage1RunDetail()
  detail.artifacts = detail.artifacts.filter(item => item.artifact.artifact_id !== 'stage1-design-handoff')
  assert.throws(
    () => createStage1CapabilityPptSource(detail, 'run-stage1'),
    /analysis_run_artifacts_missing:stage1-design-handoff/,
  )
  const failed = createStage1CapabilityFailedSource('run-stage1', new Error('missing handoff'))
  assert.equal(failed.status, 'failed')
  assert.equal(failed.selected, false)
  assert.match(failed.summary, /missing handoff/)
})

test('PPT tabs serialize and restore their immutable capability lock', () => {
  const serialized = serializeAgentPptPlanningTab({
    id: 'ppt-1',
    title: '分析',
    source: 'current',
    capabilityInputSelections: lockedSelection('run-1'),
    pptPlanningState: createPptPlanningState(),
  })
  const restored = normalizeAgentPptPlanningTab(serialized, { restore: true })
  assert.deepEqual(serialized.capability_input_selections, lockedSelection('run-1'))
  assert.deepEqual(restored.capabilityInputSelections, lockedSelection('run-1'))
})

test('PPT opening reuses only a tab bound to the same immutable run', () => {
  const methods = createAgentPptPlanningTabMethods()
  const created = []
  const hydrated = []
  const ctx = {
    ...methods,
    agentWorkspaceView: '',
    agentTabs: {
      activeTabId: 'ppt-run-1',
      analysisWorkspaceTabs: [{
        id: 'ppt-run-1',
        kind: 'analysis',
        source: 'current',
        capabilityInputSelections: lockedSelection('run-1'),
        pptPlanningState: createPptPlanningState(),
      }],
    },
    ensureAgentTabs() { return this.agentTabs },
    switchAgentTopTab(id) { this.agentTabs.activeTabId = id },
    refreshAgentActivePptPlanningSources() {},
    refreshAgentActivePptPlanningDataSources() {},
    createAgentPptPlanningTab(options) { created.push(options); return `ppt-created-${created.length}` },
    hydrateAgentPptPlanningCapabilitySource(tabId, runId) { hydrated.push({ tabId, runId }); return Promise.resolve(true) },
  }

  assert.equal(ctx.openAgentPptPlanningFromReport({ capabilityInputSelections: lockedSelection('run-1') }), 'ppt-run-1')
  assert.equal(ctx.openAgentPptPlanningFromReport({ capabilityInputSelections: lockedSelection('run-2') }), 'ppt-created-1')
  assert.equal(created.length, 1)
  assert.deepEqual(created[0].capabilityInputSelections, lockedSelection('run-2'))
  assert.equal(created[0].pptPlanningState.sources.find(item => item.id === 'package:stage1-run:run-2').status, 'generating')
  assert.deepEqual(hydrated, [
    { tabId: 'ppt-run-1', runId: 'run-1' },
    { tabId: 'ppt-created-1', runId: 'run-2' },
  ])
})

test('PPT capability hydration writes ready or failed source to the targeted tab', async () => {
  const methods = createAgentPptPlanningTabMethods()
  const originalFetch = global.fetch
  let state = mergePptPlanningSources(createPptPlanningState(), [createStage1CapabilityPlaceholderSource('run-stage1')])
  const ctx = {
    ...methods,
    getAgentPptPlanningTabState: () => state,
    updateAgentPptPlanningTabState: (_tabId, nextState) => { state = nextState; return true },
  }
  try {
    global.fetch = async () => ({ ok: true, json: async () => stage1RunDetail() })
    assert.equal(await ctx.hydrateAgentPptPlanningCapabilitySource('ppt-1', 'run-stage1'), true)
    assert.equal(state.sources.find(item => item.id === 'package:stage1-run:run-stage1').status, 'ready')

    global.fetch = async () => ({ ok: false, status: 503 })
    assert.equal(await ctx.hydrateAgentPptPlanningCapabilitySource('ppt-1', 'run-stage1'), false)
    const failed = state.sources.find(item => item.id === 'package:stage1-run:run-stage1')
    assert.equal(failed.status, 'failed')
    assert.match(failed.meta.error, /503/)
  } finally {
    global.fetch = originalFetch
  }
})


test('version-bound source policy selects only the immutable run until users explicitly add ready sources', () => {
  const placeholderState = createPptPlanningState({
    sources: [
      createStage1CapabilityPlaceholderSource('run-stage1'),
      { id: 'current:scope', title: '当前范围', status: 'ready', selected: true, meta: { sourceKind: 'system' } },
      { id: 'document:latest', title: '当前文档', status: 'ready', selected: true, meta: { sourceKind: 'document' } },
    ],
  })
  const pending = createPptPlanningState(applyCapabilitySourceSelectionPolicy(placeholderState, 'run-stage1'))
  assert.deepEqual(pending.sources.filter(item => item.selected).map(item => item.id), [])
  assert.deepEqual(pending.spec.sourceIds, [])

  const readyState = mergePptPlanningSources(pending, [createStage1CapabilityPptSource(stage1RunDetail(), 'run-stage1')])
  const isolated = createPptPlanningState(applyCapabilitySourceSelectionPolicy(readyState, 'run-stage1'))
  assert.deepEqual(isolated.sources.filter(item => item.selected).map(item => item.id), ['package:stage1-run:run-stage1'])

  const withExplicitDocument = createPptPlanningState(applyCapabilitySourceSelectionPolicy(readyState, 'run-stage1', {
    additionalSelectedSourceIds: ['document:latest'],
  }))
  assert.deepEqual(
    withExplicitDocument.sources.filter(item => item.selected).map(item => item.id).sort(),
    ['document:latest', 'package:stage1-run:run-stage1'],
  )
})

test('failed immutable run leaves no selected fallback even when additional sources were selected', () => {
  const state = createPptPlanningState({
    sources: [
      createStage1CapabilityFailedSource('run-stage1', 'unavailable'),
      { id: 'current:scope', title: '当前范围', status: 'ready', selected: true, meta: { sourceKind: 'system' } },
    ],
  })
  const isolated = createPptPlanningState(applyCapabilitySourceSelectionPolicy(state, 'run-stage1', {
    additionalSelectedSourceIds: ['current:scope'],
  }))
  assert.deepEqual(isolated.sources.filter(item => item.selected).map(item => item.id), [])
  assert.deepEqual(getPptSourceDeliveryManifest(isolated).deliverableSourceIds, [])
})

test('Stage 1 source rejects non-consumable runs while allowing an explicitly selected stale version', () => {
  const running = stage1RunDetail()
  running.run.status = 'running'
  assert.throws(
    () => createStage1CapabilityPptSource(running, 'run-stage1'),
    /analysis_run_not_consumable:running/,
  )

  const stale = stage1RunDetail()
  stale.run.status = 'stale'
  assert.equal(createStage1CapabilityPptSource(stale, 'run-stage1').status, 'ready')
})

test('creating a version-bound PPT tab deselects auto-ready current system sources', () => {
  const methods = createAgentPptPlanningTabMethods()
  const ctx = {
    ...methods,
    agentTabs: { activeTabId: '', analysisWorkspaceTabs: [] },
    agentPanelPayloads: {},
    ensureAgentTabs() { return this.agentTabs },
    captureAgentActiveSummaryTabState() {},
    captureAgentActiveSiteSelectionTabState() {},
    captureAgentActivePptPlanningTabState() {},
    captureAgentActiveFollowupTabState() {},
    createAgentPptPlanningViewId: () => 'ppt-locked',
    formatAgentTabTitle: (_kind, title) => title,
    buildAgentPptPlanningSystemSourceContext: () => ({ scopeReady: true }),
    syncActiveAgentRuntimeView() {},
    syncCurrentAgentSession() {},
    refreshAgentActivePptPlanningDataSources() {},
  }

  ctx.createAgentPptPlanningTab({
    capabilityInputSelections: lockedSelection('run-stage1'),
    pptPlanningState: mergePptPlanningSources(createPptPlanningState(), [createStage1CapabilityPlaceholderSource('run-stage1')]),
  })

  const tab = ctx.agentTabs.analysisWorkspaceTabs[0]
  const currentScope = tab.pptPlanningState.sources.find(item => item.id === 'current:scope')
  assert.equal(currentScope.status, 'ready')
  assert.equal(currentScope.selected, false)
  assert.deepEqual(tab.pptPlanningState.sources.filter(item => item.selected).map(item => item.id), [])
})

test('refreshing a version-bound PPT tab does not auto-select new backend sources and preserves explicit additions', async () => {
  const methods = createAgentPptPlanningTabMethods()
  let autoPackageCalls = 0
  let state = createPptPlanningState({
    sources: [
      createStage1CapabilityPptSource(stage1RunDetail(), 'run-stage1'),
      { id: 'document:explicit', title: '显式文档', status: 'ready', selected: true, meta: { sourceKind: 'document' } },
    ],
  })
  const activeTab = {
    id: 'ppt-locked',
    kind: 'analysis',
    capabilityInputSelections: lockedSelection('run-stage1'),
    pptPlanningState: state,
  }
  const ctx = {
    ...methods,
    buildAgentPptPlanningApiContext: () => ({ areaId: 'area-1' }),
    getAgentActiveTopTab: () => activeTab,
    getAgentActivePptPlanningTab: () => activeTab,
    getAgentActivePptPlanningState: () => state,
    mergeAgentPptPlanningSystemSources: value => createPptPlanningState(value),
    getAgentPptPlanningStateWithPackagePlaceholders: value => createPptPlanningState(value),
    updateAgentPptPlanningTabRuntimeState: (_tabId, nextState) => { state = createPptPlanningState(nextState) },
    requestAgentPptPlanningSourceManifest: async () => [],
    requestAgentPptPlanningDataSources: async () => [
      { id: 'document:explicit', title: '显式文档', status: 'ready', meta: { sourceKind: 'document' } },
      { id: 'document:new', title: '新发现文档', status: 'ready', meta: { sourceKind: 'document' } },
    ],
    ensureAgentTabs: () => ({ activeTabId: 'ppt-locked', analysisWorkspaceTabs: [activeTab] }),
    updateAgentActivePptPlanningStateWithSourceStale: nextState => { state = createPptPlanningState(nextState) },
    updateAgentActivePptPlanningState: nextState => { state = createPptPlanningState(nextState) },
    autoCreateAgentPptPlanningPoiEvidencePackage: async () => { autoPackageCalls += 1 },
    autoCreateAgentPptPlanningNightlifePoiPackage: async () => { autoPackageCalls += 1 },
    autoCreateAgentPptPlanningRoadCarrierPackage: async () => { autoPackageCalls += 1 },
  }

  await ctx.refreshAgentActivePptPlanningDataSources()

  assert.deepEqual(
    state.sources.filter(item => item.selected).map(item => item.id).sort(),
    ['document:explicit', 'package:stage1-run:run-stage1'],
  )
  assert.equal(state.sources.find(item => item.id === 'document:new').selected, false)
  assert.equal(autoPackageCalls, 0)
})

test('reopening an already hydrated immutable PPT tab does not fetch the run again', () => {
  const methods = createAgentPptPlanningTabMethods()
  let hydrationCalls = 0
  const ctx = {
    ...methods,
    agentWorkspaceView: '',
    agentTabs: {
      activeTabId: 'ppt-run-1',
      analysisWorkspaceTabs: [{
        id: 'ppt-run-1',
        kind: 'analysis',
        source: 'current',
        capabilityInputSelections: lockedSelection('run-1'),
        pptPlanningState: mergePptPlanningSources(
          createPptPlanningState(),
          [createStage1CapabilityPptSource(stage1RunDetail('run-1'), 'run-1')],
        ),
      }],
    },
    ensureAgentTabs() { return this.agentTabs },
    switchAgentTopTab() {},
    refreshAgentActivePptPlanningSources() {},
    refreshAgentActivePptPlanningDataSources() {},
    hydrateAgentPptPlanningCapabilitySource() { hydrationCalls += 1 },
  }

  assert.equal(ctx.openAgentPptPlanningFromReport({ capabilityInputSelections: lockedSelection('run-1') }), 'ppt-run-1')
  assert.equal(hydrationCalls, 0)
})
