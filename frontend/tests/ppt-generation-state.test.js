import test from 'node:test'
import assert from 'node:assert/strict'

import {
  applyPptGenerationSuccess,
  appendPptGenerationDebugEvent,
  completePptGenerationJob,
  createPptPlanningState,
  failPptGenerationJob,
  markPptGenerationApplying,
  markPptGenerationResponseReceived,
  startPptGenerationJob,
} from '../src/features/ppt-planning/ui-state.js'
import { createAgentPptPlanningTabMethods } from '../src/features/agent/ppt-planning-tabs.js'

const outlineResponse = {
  title: '演示 PPT',
  outline: [
    { id: 'p1', page_no: 1, theme: '首页', purpose: '开场' },
    { id: 'p2', page_no: 2, theme: '诊断', purpose: '问题' },
  ],
}

test('ppt generation job moves outline request through ready with response summary', () => {
  let state = createPptPlanningState()
  state = startPptGenerationJob(state, { requestId: 'outline-1', type: 'outline', tabId: 'tab-a' })

  assert.equal(state.currentStep, 'outline_generating')
  assert.equal(state.generationJob.phase, 'requesting')
  assert.equal(state.generationJob.id, 'outline-1')

  state = markPptGenerationResponseReceived(state, 'outline-1', outlineResponse)
  assert.equal(state.generationJob.phase, 'response_received')
  assert.equal(state.generationJob.responseSummary.outlineCount, 2)

  state = markPptGenerationApplying(state, 'outline-1')
  assert.equal(state.generationJob.phase, 'applying')

  state = applyPptGenerationSuccess(state, 'outline-1', outlineResponse)
  assert.equal(state.currentStep, 'outline_ready')
  assert.equal(state.outline.length, 2)
  assert.equal(state.spec.outline.length, 2)
  assert.equal(state.generationJob.phase, 'ready')
  assert.deepEqual(state.generationJob.events.map((event) => event.name), [
    'requesting',
    'response_received',
    'applying',
    'ready',
  ])
})

test('ppt generation completion applies response in one transaction', () => {
  let state = startPptGenerationJob(createPptPlanningState(), { requestId: 'outline-complete', type: 'outline', tabId: 'tab-a' })

  state = completePptGenerationJob(state, 'outline-complete', outlineResponse)

  assert.equal(state.currentStep, 'outline_ready')
  assert.equal(state.outline.length, 2)
  assert.equal(state.spec.outline.length, 2)
  assert.equal(state.generationJob.phase, 'ready')
  assert.deepEqual(state.generationJob.events.map((event) => event.name), [
    'requesting',
    'response_received',
    'applying',
    'ready',
  ])
})

test('ppt generation remains requestable until late success for same request id', () => {
  let state = startPptGenerationJob(createPptPlanningState(), { requestId: 'outline-late', type: 'outline', tabId: 'tab-a' })

  state = markPptGenerationResponseReceived(state, 'outline-late', outlineResponse)
  state = markPptGenerationApplying(state, 'outline-late')
  state = applyPptGenerationSuccess(state, 'outline-late', outlineResponse)

  assert.equal(state.generationJob.phase, 'ready')
  assert.equal(state.outline.length, 2)
  assert.ok(!state.generationJob.events.some((event) => event.name === 'timed_out'))
})

test('ppt generation ignores stale response after a newer request supersedes it', () => {
  let state = startPptGenerationJob(createPptPlanningState(), { requestId: 'outline-old', type: 'outline', tabId: 'tab-a' })
  state = startPptGenerationJob(state, { requestId: 'outline-new', type: 'outline', tabId: 'tab-a' })

  assert.equal(state.generationJob.id, 'outline-new')
  assert.equal(state.generationJob.phase, 'requesting')
  assert.ok(state.generationJob.events.some((event) => event.name === 'superseded'))

  const staleState = applyPptGenerationSuccess(state, 'outline-old', outlineResponse)
  assert.equal(staleState.generationJob.id, 'outline-new')
  assert.equal(staleState.outline.length, 0)

  const readyState = applyPptGenerationSuccess(state, 'outline-new', outlineResponse)
  assert.equal(readyState.generationJob.phase, 'ready')
  assert.equal(readyState.outline.length, 2)
})

test('ppt generation failure keeps response summary and returns to usable step', () => {
  let state = startPptGenerationJob(createPptPlanningState(), { requestId: 'outline-fail', type: 'outline', tabId: 'tab-a' })
  state = markPptGenerationResponseReceived(state, 'outline-fail', outlineResponse)
  state = markPptGenerationApplying(state, 'outline-fail')
  state = failPptGenerationJob(state, 'outline-fail', '目录返回已收到，但前端应用失败：bad svg', {
    source: 'outline',
    generationResponse: outlineResponse,
  })

  assert.equal(state.currentStep, 'materials')
  assert.equal(state.generationJob.phase, 'failed')
  assert.match(state.generationJob.error, /bad svg/)
  assert.equal(state.generationJob.responseSummary.outlineCount, 2)
  assert.deepEqual(state.generationJob.events.map((event) => event.name), [
    'requesting',
    'response_received',
    'applying',
    'failed',
  ])
})

function createPptTabUpdateContext(tab = {}) {
  const methods = createAgentPptPlanningTabMethods()
  return {
    ...methods,
    agentPanelPayloads: {},
    syncCount: 0,
    agentPptPlanningAutoPackageKeys: {},
    agentPptPlanningPackageErrors: {},
    agentTabs: {
      summaryTabs: [],
      iterationChangeTabs: [],
      siteSelectionTabs: [],
      deepAnalysisTabs: [],
      followupTabs: [],
      pptPlanningTabs: tab.id ? [tab] : [],
      activeTabId: tab.id || '',
    },
    ensureAgentTabs() {
      return this.agentTabs
    },
    getAgentActiveTopTab() {
      return this.agentTabs.pptPlanningTabs.find((item) => item.id === this.agentTabs.activeTabId) || {}
    },
    buildAgentPptPlanningApiContext() {
      return { areaId: 'area-a' }
    },
    buildAgentPptPlanningSystemSourceContext() {
      return {}
    },
    syncCurrentAgentSession() {
      this.syncCount += 1
      return null
    },
  }
}

test('ppt tab update debug event records successful writes', () => {
  const state = startPptGenerationJob(createPptPlanningState(), { requestId: 'debug-1', type: 'outline', tabId: 'tab-a' })
  const ctx = createPptTabUpdateContext({
    id: 'tab-a',
    kind: 'ppt_planning',
    source: 'current',
    readonly: false,
    pptPlanningState: state,
  })
  const nextState = appendPptGenerationDebugEvent(state, 'manual_next_event', { requestId: 'debug-1' })

  ctx.updateAgentPptPlanningTabState('tab-a', nextState)

  const events = ctx.getAgentPptPlanningTabState('tab-a').generationJob.events.map((event) => event.name)
  assert.ok(events.includes('tab_update_attempt'))
  assert.ok(events.includes('tab_update_applied'))
  assert.ok(events.includes('tab_update_after_sync'))
})

test('ppt runtime patch skips session sync while commit syncs once', () => {
  const state = startPptGenerationJob(createPptPlanningState(), { requestId: 'runtime-1', type: 'outline', tabId: 'tab-a' })
  const ctx = createPptTabUpdateContext({
    id: 'tab-a',
    kind: 'ppt_planning',
    source: 'current',
    readonly: false,
    pptPlanningState: createPptPlanningState(),
  })

  ctx.updateAgentPptPlanningTabRuntimeState('tab-a', state)

  assert.equal(ctx.syncCount, 0)
  assert.equal(ctx.getAgentPptPlanningTabState('tab-a').generationJob.id, 'runtime-1')

  const readyState = completePptGenerationJob(ctx.getAgentPptPlanningTabState('tab-a'), 'runtime-1', outlineResponse)
  ctx.updateAgentPptPlanningTabState('tab-a', readyState)

  assert.equal(ctx.syncCount, 1)
  assert.equal(ctx.getAgentPptPlanningTabState('tab-a').generationJob.phase, 'ready')
})

test('ppt tab update debug event records missing target tab', () => {
  const state = startPptGenerationJob(createPptPlanningState(), { requestId: 'debug-2', type: 'outline', tabId: 'tab-active' })
  const ctx = createPptTabUpdateContext({
    id: 'tab-active',
    kind: 'ppt_planning',
    source: 'current',
    readonly: false,
    pptPlanningState: state,
  })

  ctx.updateAgentPptPlanningTabState('tab-missing', state)

  const events = ctx.getAgentPptPlanningTabState('tab-active').generationJob.events
  assert.ok(events.some((event) => event.name === 'tab_update_noop_missing_tab'))
  assert.equal(ctx.syncCount, 0)
})

test('ppt tab update debug event records readonly target tab', () => {
  const state = startPptGenerationJob(createPptPlanningState(), { requestId: 'debug-3', type: 'outline', tabId: 'tab-readonly' })
  const ctx = createPptTabUpdateContext({
    id: 'tab-readonly',
    kind: 'ppt_planning',
    source: 'history',
    readonly: true,
    pptPlanningState: state,
  })

  ctx.updateAgentPptPlanningTabState('tab-readonly', state)

  const unchanged = ctx.getAgentPptPlanningTabState('tab-readonly')
  assert.ok(unchanged.generationJob.events.some((event) => event.name === 'tab_update_noop_readonly'))
  assert.equal(ctx.syncCount, 0)
})
