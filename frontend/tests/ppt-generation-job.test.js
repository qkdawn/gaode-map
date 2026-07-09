import test from 'node:test'
import assert from 'node:assert/strict'

import {
  appendGenerationEvent,
  generationReadyStepForState,
  generationStepForType,
  normalizeGenerationJob,
  normalizeGenerationResponse,
  PPT_GENERATION_JOB_EVENT_LIMIT,
  summarizeGenerationResponse,
} from '../src/features/ppt-planning/generation-job.js'
import { PPT_PLANNING_STEPS } from '../src/features/ppt-planning/model.js'

test('generation job helpers normalize job events and cap history', () => {
  let job = normalizeGenerationJob({
    id: 'job-1',
    type: 'outline',
    phase: 'requesting',
    tab_id: 'tab-1',
  })

  for (let index = 0; index < PPT_GENERATION_JOB_EVENT_LIMIT + 3; index += 1) {
    job = appendGenerationEvent(job, `event-${index}`, { index })
  }

  assert.equal(job.events.length, PPT_GENERATION_JOB_EVENT_LIMIT)
  assert.equal(job.events[0].name, 'event-3')
  assert.equal(job.events.at(-1).details.index, PPT_GENERATION_JOB_EVENT_LIMIT + 2)
  assert.equal(normalizeGenerationJob({ phase: 'unknown' }).phase, 'idle')
})

test('generation job helpers summarize responses and planning steps', () => {
  const outlineSummary = summarizeGenerationResponse('outline', {
    title: '分析汇报',
    outline: [
      { pageNo: 1, theme: '范围' },
      { page_no: 2, theme: '机会' },
    ],
  })
  const directiveSummary = summarizeGenerationResponse('directive', {
    slides: [
      { index: 1, title: '范围' },
    ],
  })

  assert.equal(outlineSummary.outlineCount, 2)
  assert.equal(directiveSummary.slideCount, 1)
  assert.equal(generationStepForType('narrative'), PPT_PLANNING_STEPS.NARRATIVE_GENERATING)
  assert.equal(generationReadyStepForState({ outline: [{ pageNo: 1 }] }, 'outline'), PPT_PLANNING_STEPS.OUTLINE_READY)
  assert.equal(generationReadyStepForState({ deckBrief: { slides: [{ index: 1 }] } }, 'directive'), PPT_PLANNING_STEPS.DIRECTIVE_DRAFT)
})

test('generation response normalization stores serializable payload snapshots', () => {
  const circular = { title: '循环对象' }
  circular.self = circular
  const response = normalizeGenerationResponse({
    source: 'outline',
    payload: circular,
  })

  assert.equal(response.source, 'outline')
  assert.equal(response.payload.unserializable, '[object Object]')
})
