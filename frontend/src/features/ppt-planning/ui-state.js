import {
  createDefaultDeckBriefPreview,
  createDefaultPptSources,
  createDefaultPptSpec,
  normalizeDeckBrief,
  normalizePptSource,
} from './model.js'

function asText(value, fallback = '') {
  return String(value ?? fallback ?? '').trim()
}

function cloneArray(items) {
  return Array.isArray(items) ? items.map((item) => (item && typeof item === 'object' ? { ...item } : item)) : []
}

function normalizeSources(seedSources = []) {
  const rawSources = cloneArray(seedSources).length ? cloneArray(seedSources) : createDefaultPptSources()
  return rawSources.map(normalizePptSource).filter((item) => item.id)
}

function normalizeSelectedSlideId(seed = {}, deckBrief = null) {
  const slides = cloneArray(deckBrief && deckBrief.slides)
  const fallback = asText(slides[0] && slides[0].id)
  const selected = asText(seed.selectedSlideId || seed.selected_slide_id)
  return slides.some((item) => asText(item && item.id) === selected) ? selected : fallback
}

export function createPptPlanningState(seed = {}) {
  const sources = normalizeSources(seed.sources)
  const selectedSourceIds = sources.filter((item) => item.selected).map((item) => item.id)
  const spec = createDefaultPptSpec({
    ...seed.spec,
    sourceIds: cloneArray((seed.spec || {}).sourceIds || (seed.spec || {}).source_ids).length
      ? cloneArray((seed.spec || {}).sourceIds || (seed.spec || {}).source_ids)
      : selectedSourceIds,
  })
  const deckBrief = normalizeDeckBrief(seed.deckBrief || seed.deck_brief || createDefaultDeckBriefPreview())
  return {
    currentStep: asText(seed.currentStep || seed.current_step) || 'spec',
    sources,
    spec,
    deckBrief,
    selectedSlideId: normalizeSelectedSlideId(seed, deckBrief),
  }
}

export function normalizePptPlanningState(seed = {}) {
  return createPptPlanningState(seed)
}

export function getSelectedPptSourceIds(state = {}) {
  return cloneArray(state.sources)
    .filter((item) => item && item.selected)
    .map((item) => asText(item.id))
    .filter(Boolean)
}

export function getPptSourceSummary(state = {}) {
  const sources = cloneArray(state.sources)
  const selected = sources.filter((item) => item && item.selected)
  return {
    total: sources.length,
    selected: selected.length,
    ready: selected.filter((item) => asText(item.status) === 'ready').length,
  }
}

export function getActiveDeckSlideBrief(state = {}) {
  const selectedId = asText(state.selectedSlideId)
  const slides = cloneArray((state.deckBrief || {}).slides)
  return slides.find((item) => asText(item && item.id) === selectedId) || slides[0] || null
}

export function setPptSpecField(state = {}, field = '', value = '') {
  const normalized = createPptPlanningState(state)
  const key = asText(field)
  if (!key) return normalized
  const nextSpec = { ...normalized.spec, [key]: value }
  if (key === 'pageCount') nextSpec.pageCount = Number(value) || normalized.spec.pageCount
  return createPptPlanningState({ ...normalized, spec: nextSpec })
}

export function togglePptSourceSelection(state = {}, sourceId = '', selected = null) {
  const normalized = createPptPlanningState(state)
  const id = asText(sourceId)
  const sources = normalized.sources.map((item) => {
    if (item.id !== id) return item
    return { ...item, selected: selected === null ? !item.selected : !!selected }
  })
  return createPptPlanningState({
    ...normalized,
    sources,
    spec: {
      ...normalized.spec,
      sourceIds: sources.filter((item) => item.selected).map((item) => item.id),
    },
  })
}

export function setAllPptSourcesSelected(state = {}, selected = true) {
  const normalized = createPptPlanningState(state)
  const sources = normalized.sources.map((item) => ({ ...item, selected: !!selected }))
  return createPptPlanningState({
    ...normalized,
    sources,
    spec: {
      ...normalized.spec,
      sourceIds: sources.filter((item) => item.selected).map((item) => item.id),
    },
  })
}

export function selectDeckSlideBrief(state = {}, slideId = '') {
  const normalized = createPptPlanningState(state)
  const id = asText(slideId)
  const slides = cloneArray((normalized.deckBrief || {}).slides)
  if (!slides.some((item) => asText(item && item.id) === id)) return normalized
  return { ...normalized, selectedSlideId: id }
}

export function buildPptSpecPayload(state = {}, context = {}) {
  const normalized = createPptPlanningState(state)
  return {
    area_id: asText(context.areaId || context.area_id),
    source_ids: getSelectedPptSourceIds(normalized),
    topic: asText(normalized.spec.topic),
    audience: asText(normalized.spec.audience),
    deck_type: asText(normalized.spec.deckType),
    page_count: Number(normalized.spec.pageCount || 15),
    research_enabled: !!normalized.spec.researchEnabled,
  }
}
