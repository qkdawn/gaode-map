import test from 'node:test'
import assert from 'node:assert/strict'

import {
  applyPptGenerationSuccess,
  createPptPlanningState,
  failPptGenerationJob,
  markPptGenerationApplying,
  markPptGenerationResponseReceived,
  startPptGenerationJob,
  timeoutPptGenerationJob,
} from '../src/features/ppt-planning/ui-state.js'

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

test('ppt generation timeout does not block late success for same request id', () => {
  let state = startPptGenerationJob(createPptPlanningState(), { requestId: 'outline-late', type: 'outline', tabId: 'tab-a' })
  state = timeoutPptGenerationJob(state, 'outline-late')

  assert.equal(state.generationJob.phase, 'timed_out')

  state = markPptGenerationResponseReceived(state, 'outline-late', outlineResponse)
  state = markPptGenerationApplying(state, 'outline-late')
  state = applyPptGenerationSuccess(state, 'outline-late', outlineResponse)

  assert.equal(state.generationJob.phase, 'ready')
  assert.equal(state.outline.length, 2)
  assert.ok(state.generationJob.events.some((event) => event.name === 'timed_out'))
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
