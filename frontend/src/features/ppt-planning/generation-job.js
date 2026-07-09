import { asText, cloneArray, cloneObject } from './base.js'
import {
  normalizeDeckBrief,
  normalizeNarrativePlan,
  normalizePptOutline,
  PPT_PLANNING_STEPS,
} from './model.js'

export const PPT_GENERATION_JOB_EVENT_LIMIT = 60
export const PPT_GENERATION_TERMINAL_PHASES = new Set(['ready', 'failed', 'superseded'])

const PPT_GENERATION_JOB_TYPES = new Set(['outline', 'narrative', 'slides', 'directive'])
const PPT_GENERATION_JOB_PHASES = new Set([
  'idle',
  'requesting',
  'response_received',
  'applying',
  'ready',
  'failed',
  'superseded',
])

function cloneSerializable(value = {}) {
  try {
    return JSON.parse(JSON.stringify(value ?? {}))
  } catch (_) {
    return { unserializable: asText(value) || 'unserializable_response' }
  }
}

export function normalizeGenerationResponse(value = {}) {
  const response = cloneObject(value)
  const payload = response.payload && typeof response.payload === 'object'
    ? cloneSerializable(response.payload)
    : cloneSerializable(value)
  return {
    source: asText(response.source || response.responseSource || response.response_source),
    receivedAt: asText(response.receivedAt || response.received_at),
    payload,
  }
}

export function createGenerationResponseSnapshot(source = '', payload = {}) {
  return normalizeGenerationResponse({
    source,
    receivedAt: new Date().toISOString(),
    payload,
  })
}

export function normalizeGenerationJobType(value = '') {
  const type = asText(value)
  return PPT_GENERATION_JOB_TYPES.has(type) ? type : ''
}

export function normalizeGenerationJobPhase(value = '') {
  const phase = asText(value)
  return PPT_GENERATION_JOB_PHASES.has(phase) ? phase : 'idle'
}

export function summarizeGenerationResponse(type = '', response = {}) {
  const payload = response && typeof response === 'object' ? response : {}
  const outline = normalizeGenerationJobType(type) === 'outline' || Array.isArray(payload.outline)
    ? normalizePptOutline(payload.outline)
    : []
  const narrative = normalizeGenerationJobType(type) === 'narrative' || Array.isArray(payload.slide_roles) || Array.isArray(payload.slideRoles)
    ? normalizeNarrativePlan(payload)
    : { slideRoles: [] }
  const deckBrief = normalizeGenerationJobType(type) === 'directive' || Array.isArray(payload.slides)
    ? normalizeDeckBrief(payload)
    : { slides: [] }
  const keys = Object.keys(payload).slice(0, 12)
  return {
    type: normalizeGenerationJobType(type),
    title: asText(payload.title),
    outlineCount: outline.length,
    narrativeRoleCount: cloneArray(narrative.slideRoles).length,
    slideCount: cloneArray(deckBrief.slides).length,
    keys,
  }
}

export function createGenerationEvent(name = '', details = {}) {
  return {
    name: asText(name) || 'event',
    at: new Date().toISOString(),
    details: cloneSerializable(details),
  }
}

export function normalizeGenerationEvents(events = []) {
  return cloneArray(events)
    .map((event) => {
      const item = cloneObject(event)
      const name = asText(item.name)
      if (!name) return null
      return {
        name,
        at: asText(item.at),
        details: cloneObject(item.details),
      }
    })
    .filter(Boolean)
    .slice(-PPT_GENERATION_JOB_EVENT_LIMIT)
}

export function normalizeGenerationJob(value = {}) {
  const job = cloneObject(value)
  const type = normalizeGenerationJobType(job.type)
  const phase = normalizeGenerationJobPhase(job.phase)
  if (!asText(job.id) && phase === 'idle') {
    return {
      id: '',
      type: '',
      phase: 'idle',
      tabId: '',
      startedAt: '',
      completedAt: '',
      error: '',
      responseSummary: {},
      events: [],
    }
  }
  return {
    id: asText(job.id),
    type,
    phase,
    tabId: asText(job.tabId || job.tab_id),
    startedAt: asText(job.startedAt || job.started_at),
    completedAt: asText(job.completedAt || job.completed_at),
    error: asText(job.error),
    responseSummary: cloneObject(job.responseSummary || job.response_summary),
    events: normalizeGenerationEvents(job.events),
  }
}

export function appendGenerationEvent(job = {}, name = '', details = {}) {
  const normalized = normalizeGenerationJob(job)
  return {
    ...normalized,
    events: [
      ...normalizeGenerationEvents(normalized.events),
      createGenerationEvent(name, details),
    ].slice(-PPT_GENERATION_JOB_EVENT_LIMIT),
  }
}

export function isCurrentGenerationJob(state = {}, requestId = '') {
  const job = normalizeGenerationJob(state.generationJob || state.generation_job)
  return !!asText(requestId) && asText(job.id) === asText(requestId)
}

export function generationStepForType(type = '') {
  const normalizedType = normalizeGenerationJobType(type)
  if (normalizedType === 'narrative') return PPT_PLANNING_STEPS.NARRATIVE_GENERATING
  if (normalizedType === 'slides' || normalizedType === 'directive') return PPT_PLANNING_STEPS.SLIDES_GENERATING
  return PPT_PLANNING_STEPS.OUTLINE_GENERATING
}

export function generationReadyStepForState(state = {}, type = '') {
  const normalizedType = normalizeGenerationJobType(type)
  if (normalizedType === 'slides' || normalizedType === 'directive') return cloneArray((state.deckBrief || {}).slides).length ? PPT_PLANNING_STEPS.DIRECTIVE_DRAFT : PPT_PLANNING_STEPS.NARRATIVE_READY
  if (normalizedType === 'narrative') return normalizeNarrativePlan(state.narrativePlan || state.narrative_plan).slideRoles.length ? PPT_PLANNING_STEPS.NARRATIVE_READY : PPT_PLANNING_STEPS.OUTLINE_READY
  return cloneArray(state.outline).length ? PPT_PLANNING_STEPS.OUTLINE_READY : PPT_PLANNING_STEPS.MATERIALS
}
