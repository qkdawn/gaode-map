import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildPptSpecPayload,
  createPptPlanningState,
  getActiveDeckSlideBrief,
  getPptSourceSummary,
  setAllPptSourcesSelected,
  togglePptSourceSelection,
} from '../src/features/ppt-planning/ui-state.js'

test('ppt planning state creates NotebookLM-style selected sources and default spec', () => {
  const state = createPptPlanningState()

  assert.equal(state.spec.audience, '政府评审')
  assert.equal(state.spec.pageCount, 15)
  assert.equal(state.sources.length, 5)
  assert.deepEqual(getPptSourceSummary(state), { total: 5, selected: 3, ready: 3 })
})

test('ppt source selection updates the spec payload source ids', () => {
  const state = togglePptSourceSelection(createPptPlanningState(), 'attachment')
  const payload = buildPptSpecPayload(state, { areaId: 'area-1' })

  assert.equal(payload.area_id, 'area-1')
  assert.equal(payload.audience, '政府评审')
  assert.equal(payload.page_count, 15)
  assert.ok(payload.source_ids.includes('attachment'))
})

test('ppt state can select all sources and keep an active page brief', () => {
  const state = setAllPptSourcesSelected(createPptPlanningState(), true)
  const active = getActiveDeckSlideBrief(state)

  assert.equal(getPptSourceSummary(state).selected, 5)
  assert.equal(active.title, '封面')
  assert.equal(active.speakerNotes.includes('不直接生成 PPTX'), true)
})
