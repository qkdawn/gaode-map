import {
  createDefaultDeckBriefPreview,
  createDefaultPptSources,
  createDefaultPptSpec,
  createDefaultUserPptSources,
  normalizeDeckBrief,
  normalizePptOutline,
  normalizePptSource,
  PPT_PLANNING_STEPS,
} from './model.js'

function asText(value, fallback = '') {
  return String(value ?? fallback ?? '').trim()
}

function cloneArray(items) {
  return Array.isArray(items) ? items.map((item) => (item && typeof item === 'object' ? { ...item } : item)) : []
}

function cloneObject(value, fallback = {}) {
  return value && typeof value === 'object' && !Array.isArray(value) ? { ...value } : { ...fallback }
}

export const PPT_UNCATEGORIZED_GROUP_ID = 'group:uncategorized'

const PPT_ERROR_SOURCE_LABELS = new Set([
  'source_refresh',
  'source_grouping',
  'data_package',
  'outline',
  'directive',
])

function uniqueText(items = []) {
  const seen = new Set()
  const values = []
  cloneArray(items).forEach((item) => {
    const value = asText(item)
    if (value && !seen.has(value)) {
      seen.add(value)
      values.push(value)
    }
  })
  return values
}

function normalizePptErrorSource(value = '') {
  const source = asText(value)
  return PPT_ERROR_SOURCE_LABELS.has(source) ? source : ''
}

function normalizeRevisionTarget(value = {}) {
  const type = asText(value.type)
  if (!['outline', 'directive'].includes(type)) return { type: '', id: '', pageNo: 0, index: 0 }
  const pageNo = Number(value.pageNo || value.page_no || 0) || 0
  const index = Number(value.index || pageNo || 0) || 0
  return {
    type,
    id: asText(value.id),
    pageNo,
    index,
  }
}

function normalizeRevisionSnapshots(value = {}) {
  const source = cloneObject(value)
  return Object.fromEntries(Object.entries(source)
    .map(([key, item]) => [asText(key), cloneObject(item)])
    .filter(([key]) => key))
}

function normalizeRevisionDraft(value = {}) {
  return cloneObject(value)
}

function normalizeStaleDirectivePageIds(value = []) {
  return uniqueText(value).map((item) => String(Number(item) || item)).filter(Boolean)
}

function stableGroupId(title = '', fallback = '') {
  const slug = asText(title)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return slug ? `group:${slug}` : asText(fallback) || PPT_UNCATEGORIZED_GROUP_ID
}

function normalizeSources(seedSources = []) {
  const rawSources = cloneArray(seedSources).length ? cloneArray(seedSources) : createDefaultPptSources()
  return rawSources.map(normalizePptSource).filter((item) => item.id)
}

function getDefaultGroupSpecForSource(source = {}) {
  const sourceId = asText(source.id)
  const sourceKind = asText((source.meta || {}).sourceKind)
  if (sourceKind === 'package' || sourceKind === 'package-placeholder' || sourceId.startsWith('package:') || sourceId.startsWith('package-placeholder:')) {
    return { id: 'group:packages', title: '资料包', emoji: '' }
  }
  if (['system:scope', 'system:h3'].includes(sourceId)) {
    return { id: 'group:spatial-scope', title: '空间范围与网格', emoji: '' }
  }
  if (['system:poi', 'system:nightlight'].includes(sourceId)) {
    return { id: 'group:urban-vitality', title: '城市活力证据', emoji: '' }
  }
  if (sourceId === 'system:population') {
    return { id: 'group:population-demand', title: '人群与需求', emoji: '' }
  }
  if (sourceId === 'system:road-syntax') {
    return { id: 'group:accessibility', title: '交通与可达性', emoji: '' }
  }
  return { id: PPT_UNCATEGORIZED_GROUP_ID, title: '未分类来源', emoji: '' }
}

function normalizePptSourceGroup(seed = {}) {
  const sourceIds = uniqueText(seed.sourceIds || seed.source_ids)
  const title = asText(seed.title) || '未分类来源'
  return {
    id: asText(seed.id) || stableGroupId(title),
    title,
    emoji: asText(seed.emoji),
    sourceIds,
    collapsed: !!seed.collapsed,
    meta: cloneObject(seed.meta),
  }
}

function createDefaultPptSourceGroups(sources = []) {
  const groupMap = new Map()
  cloneArray(sources).forEach((source) => {
    const spec = getDefaultGroupSpecForSource(source)
    if (!groupMap.has(spec.id)) {
      groupMap.set(spec.id, {
        id: spec.id,
        title: spec.title,
        emoji: spec.emoji,
        sourceIds: [],
        collapsed: false,
        meta: { source: 'default' },
      })
    }
    groupMap.get(spec.id).sourceIds.push(asText(source.id))
  })
  return Array.from(groupMap.values()).filter((group) => group.sourceIds.length)
}

function reconcilePptSourceGroups(seedGroups = [], sources = []) {
  const sourceIds = cloneArray(sources).map((item) => asText(item.id)).filter(Boolean)
  const allowed = new Set(sourceIds)
  const seen = new Set()
  const normalizedGroups = cloneArray(seedGroups)
    .map(normalizePptSourceGroup)
    .map((group) => {
      const groupSourceIds = group.sourceIds.filter((sourceId) => {
        if (!allowed.has(sourceId) || seen.has(sourceId)) return false
        seen.add(sourceId)
        return true
      })
      return { ...group, sourceIds: groupSourceIds }
    })
    .filter((group) => group.sourceIds.length)

  const groupById = new Map(normalizedGroups.map((group) => [group.id, group]))
  sourceIds.forEach((sourceId) => {
    if (seen.has(sourceId)) return
    const source = cloneArray(sources).find((item) => asText(item.id) === sourceId)
    const spec = getDefaultGroupSpecForSource(source)
    const group = groupById.get(spec.id) || {
      id: spec.id,
      title: spec.title,
      emoji: spec.emoji,
      sourceIds: [],
      collapsed: false,
      meta: { source: 'default' },
    }
    group.sourceIds = [...group.sourceIds, sourceId]
    if (!groupById.has(spec.id)) {
      groupById.set(spec.id, group)
      normalizedGroups.push(group)
    }
    seen.add(sourceId)
  })

  return normalizedGroups
}

function sourceIdsFromSources(sources = []) {
  return cloneArray(sources).map((item) => asText(item.id)).filter(Boolean)
}

function syncSpecSourceIds(normalized = {}, sources = []) {
  return {
    ...normalized.spec,
    sourceIds: getReadySelectedSourceIds(sources),
  }
}

function ensureUncategorizedGroup(groups = [], sourceIds = []) {
  const ids = uniqueText(sourceIds)
  if (!ids.length) return cloneArray(groups)
  const nextGroups = cloneArray(groups).map(normalizePptSourceGroup)
  const existing = nextGroups.find((group) => group.id === PPT_UNCATEGORIZED_GROUP_ID)
  if (existing) {
    existing.sourceIds = uniqueText([...existing.sourceIds, ...ids])
    existing.collapsed = false
    return nextGroups
  }
  return [
    ...nextGroups,
    {
      id: PPT_UNCATEGORIZED_GROUP_ID,
      title: '未分类来源',
      emoji: '',
      sourceIds: ids,
      collapsed: false,
      meta: { source: 'manual' },
    },
  ]
}

function getReadySelectedSourceIds(sources = []) {
  return cloneArray(sources)
    .filter((item) => item && item.selected && asText(item.status) === 'ready')
    .map((item) => asText(item.id))
    .filter(Boolean)
}

function isPptPackageSource(source = {}) {
  const sourceKind = asText(source.meta && source.meta.sourceKind)
  const sourceId = asText(source.id)
  return sourceKind === 'package'
    || sourceKind === 'package-placeholder'
    || sourceId.startsWith('package:')
    || sourceId.startsWith('package-placeholder:')
}

function outlineRevisionKey(item = {}) {
  const id = asText(item.id)
  const pageNo = Number(item.pageNo || item.page_no || 0) || 0
  return `outline:${id || pageNo}`
}

function slideRevisionKey(item = {}) {
  const index = Number(item.index || item.pageNo || item.page_no || 0) || 0
  return `slide:${index}`
}

function findOutlineIndex(outline = [], target = {}) {
  const targetId = asText(target.id)
  const targetPageNo = Number(target.pageNo || target.page_no || 0) || 0
  return cloneArray(outline).findIndex((item) => {
    const itemId = asText(item.id)
    const itemPageNo = Number(item.pageNo || item.page_no || 0) || 0
    return (targetId && itemId === targetId) || (!!targetPageNo && itemPageNo === targetPageNo)
  })
}

function findSlideIndex(slides = [], target = {}) {
  const targetIndex = Number(target.index || target.pageNo || target.page_no || 0) || 0
  return cloneArray(slides).findIndex((item) => Number(item.index || 0) === targetIndex)
}

function normalizeSelectedSlideId(seed = {}, deckBrief = null) {
  const slides = cloneArray(deckBrief && deckBrief.slides)
  const fallback = asText(slides[0] && slides[0].id)
  const selected = asText(seed.selectedSlideId || seed.selected_slide_id)
  return slides.some((item) => asText(item && item.id) === selected) ? selected : fallback
}

export function createPptPlanningState(seed = {}) {
  const removedSourceIds = uniqueText(seed.removedSourceIds || seed.removed_source_ids)
  const removedSet = new Set(removedSourceIds)
  const sources = normalizeSources(seed.sources).filter((item) => !removedSet.has(asText(item.id)))
  const selectedSourceIds = getReadySelectedSourceIds(sources)
  const spec = createDefaultPptSpec({
    ...seed.spec,
    sourceIds: cloneArray((seed.spec || {}).sourceIds || (seed.spec || {}).source_ids).length
      ? cloneArray((seed.spec || {}).sourceIds || (seed.spec || {}).source_ids)
      : selectedSourceIds,
  })
  const outline = normalizePptOutline(seed.outline || seed.deckOutline || seed.deck_outline || spec.outline)
  const deckBrief = normalizeDeckBrief(seed.deckBrief || seed.deck_brief || createDefaultDeckBriefPreview())
  const sourceGroups = reconcilePptSourceGroups(seed.sourceGroups || seed.source_groups || createDefaultPptSourceGroups(sources), sources)
  return {
    currentStep: asText(seed.currentStep || seed.current_step) || PPT_PLANNING_STEPS.MATERIALS,
    sources,
    sourceGroups,
    removedSourceIds,
    spec,
    outline,
    deckBrief,
    selectedSlideId: normalizeSelectedSlideId(seed, deckBrief),
    generationError: asText(seed.generationError || seed.generation_error),
    generationErrorSource: normalizePptErrorSource(seed.generationErrorSource || seed.generation_error_source),
    dataPackageGenerating: !!(seed.dataPackageGenerating || seed.data_package_generating),
    sourceGrouping: !!(seed.sourceGrouping || seed.source_grouping),
    activeRevisionTarget: normalizeRevisionTarget(seed.activeRevisionTarget || seed.active_revision_target),
    outlineRevisionDraft: normalizeRevisionDraft(seed.outlineRevisionDraft || seed.outline_revision_draft),
    directiveRevisionDraft: normalizeRevisionDraft(seed.directiveRevisionDraft || seed.directive_revision_draft),
    revisionSnapshots: normalizeRevisionSnapshots(seed.revisionSnapshots || seed.revision_snapshots),
    staleDirectivePageIds: normalizeStaleDirectivePageIds(seed.staleDirectivePageIds || seed.stale_directive_page_ids),
    revisionGeneratingTarget: normalizeRevisionTarget(seed.revisionGeneratingTarget || seed.revision_generating_target),
  }
}

export function normalizePptPlanningState(seed = {}) {
  return createPptPlanningState(seed)
}

export function getSelectedPptSourceIds(state = {}) {
  return cloneArray(createPptPlanningState(state).sources)
    .filter((item) => item && item.selected && asText(item.status) === 'ready')
    .map((item) => asText(item.id))
    .filter(Boolean)
}

export function getPptSourceSummary(state = {}) {
  const sources = cloneArray(createPptPlanningState(state).sources)
  const ready = sources.filter((item) => item && asText(item.status) === 'ready')
  const selected = ready.filter((item) => item && item.selected)
  return {
    total: sources.length,
    selected: selected.length,
    ready: ready.length,
  }
}

export function getPendingPptPackageSources(state = {}) {
  const sources = cloneArray(createPptPlanningState(state).sources)
  const readySourceIds = new Set(sources
    .filter((item) => item && asText(item.status) === 'ready')
    .map((item) => asText(item.id))
    .filter(Boolean))
  return sources.filter((item) => {
    if (!item || !isPptPackageSource(item)) return false
    const status = asText(item.status)
    if (status === 'ready') return false
    if (status === 'generating') return true
    const sourceKind = asText(item.meta && item.meta.sourceKind)
    if (sourceKind !== 'package-placeholder') return true
    const pack = cloneObject(item.meta && item.meta.package)
    const sourceIds = uniqueText(pack.source_ids || pack.sourceIds)
    return sourceIds.length > 0 && sourceIds.every((sourceId) => readySourceIds.has(sourceId))
  })
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

export function applyPptSpecResponse(state = {}, response = {}) {
  const normalized = createPptPlanningState(state)
  const outline = normalizePptOutline(response.outline)
  return createPptPlanningState({
    ...normalized,
    currentStep: PPT_PLANNING_STEPS.OUTLINE_READY,
    outline,
    spec: {
      ...normalized.spec,
      title: asText(response.title) || normalized.spec.title,
      goal: asText(response.goal) || normalized.spec.goal,
      audience: asText(response.audience) || normalized.spec.audience,
      deckType: asText(response.deckType || response.deck_type) || normalized.spec.deckType,
      pageCount: Number(response.pageCount || response.page_count || normalized.spec.pageCount) || normalized.spec.pageCount,
      outline,
      missingInputs: cloneArray(response.missingInputs || response.missing_inputs),
    },
    generationError: '',
    generationErrorSource: '',
    revisionSnapshots: {},
    staleDirectivePageIds: [],
    activeRevisionTarget: {},
    outlineRevisionDraft: {},
    directiveRevisionDraft: {},
  })
}

export function setPptOutlineGenerating(state = {}) {
  return createPptPlanningState({
    ...createPptPlanningState(state),
    currentStep: PPT_PLANNING_STEPS.OUTLINE_GENERATING,
    generationError: '',
    generationErrorSource: '',
  })
}

export function setPptDirectiveGenerating(state = {}) {
  return createPptPlanningState({
    ...createPptPlanningState(state),
    currentStep: PPT_PLANNING_STEPS.DIRECTIVE_GENERATING,
    generationError: '',
    generationErrorSource: '',
  })
}

export function resetPptPlanningToMaterials(state = {}) {
  const normalized = createPptPlanningState(state)
  return createPptPlanningState({
    ...normalized,
    currentStep: PPT_PLANNING_STEPS.MATERIALS,
    outline: [],
    spec: {
      ...normalized.spec,
      outline: [],
      missingInputs: [],
    },
    deckBrief: createDefaultDeckBriefPreview(),
    selectedSlideId: '',
    generationError: '',
    generationErrorSource: '',
    activeRevisionTarget: {},
    outlineRevisionDraft: {},
    directiveRevisionDraft: {},
    revisionSnapshots: {},
    staleDirectivePageIds: [],
    revisionGeneratingTarget: {},
  })
}

export function resetPptPlanningToOutlineReady(state = {}) {
  const normalized = createPptPlanningState(state)
  const outline = normalizePptOutline(normalized.outline)
  if (!outline.length) return resetPptPlanningToMaterials(normalized)
  return createPptPlanningState({
    ...normalized,
    currentStep: PPT_PLANNING_STEPS.OUTLINE_READY,
    outline,
    spec: {
      ...normalized.spec,
      outline,
    },
    deckBrief: createDefaultDeckBriefPreview(),
    selectedSlideId: '',
    generationError: '',
    generationErrorSource: '',
    activeRevisionTarget: {},
    directiveRevisionDraft: {},
    revisionGeneratingTarget: {},
    staleDirectivePageIds: [],
  })
}

export function applyDeckBriefResponse(state = {}, response = {}) {
  const normalized = createPptPlanningState(state)
  const deckBrief = normalizeDeckBrief(response)
  return createPptPlanningState({
    ...normalized,
    currentStep: PPT_PLANNING_STEPS.DIRECTIVE_DRAFT,
    deckBrief,
    generationError: '',
    generationErrorSource: '',
    staleDirectivePageIds: [],
    activeRevisionTarget: {},
    outlineRevisionDraft: {},
    directiveRevisionDraft: {},
  })
}

export function getPptRevisionKey(type = '', target = {}) {
  return asText(type) === 'directive' ? slideRevisionKey(target) : outlineRevisionKey(target)
}

export function isPptDirectivePageStale(state = {}, pageNo = 0) {
  const normalized = createPptPlanningState(state)
  const id = String(Number(pageNo) || pageNo || '')
  return !!id && normalized.staleDirectivePageIds.includes(id)
}

export function setPptActiveRevisionTarget(state = {}, target = {}) {
  const normalized = createPptPlanningState(state)
  const active = normalizeRevisionTarget(target)
  if (!active.type) {
    return createPptPlanningState({
      ...normalized,
      activeRevisionTarget: {},
      outlineRevisionDraft: {},
      directiveRevisionDraft: {},
    })
  }
  if (active.type === 'outline') {
    const index = findOutlineIndex(normalized.outline, active)
    const item = index >= 0 ? normalized.outline[index] : {}
    return createPptPlanningState({
      ...normalized,
      activeRevisionTarget: {
        type: 'outline',
        id: asText(item.id) || active.id,
        pageNo: Number(item.pageNo || active.pageNo || 0) || 0,
      },
      outlineRevisionDraft: {
        theme: asText(item.theme),
        purpose: asText(item.purpose),
        revisionNote: '',
      },
      directiveRevisionDraft: {},
    })
  }
  const index = findSlideIndex((normalized.deckBrief || {}).slides, active)
  const item = index >= 0 ? (normalized.deckBrief.slides || [])[index] : {}
  return createPptPlanningState({
    ...normalized,
    activeRevisionTarget: {
      type: 'directive',
      index: Number(item.index || active.index || 0) || 0,
      pageNo: Number(item.index || active.pageNo || 0) || 0,
    },
    outlineRevisionDraft: {},
    directiveRevisionDraft: {
      title: asText(item.title),
      purpose: asText(item.purpose),
      keyMessage: asText(item.keyMessage || item.key_message),
      visualPlan: asText(item.visualPlan || item.visual_plan),
      requiredSources: cloneArray(item.requiredSources || item.required_sources).map((source) => asText(source)).filter(Boolean).join(', '),
      speakerNotes: asText(item.speakerNotes || item.speaker_notes),
      revisionNote: '',
    },
  })
}

export function setPptRevisionDraftField(state = {}, type = '', field = '', value = '') {
  const normalized = createPptPlanningState(state)
  const key = asText(field)
  if (!key) return normalized
  if (asText(type) === 'directive') {
    return createPptPlanningState({
      ...normalized,
      directiveRevisionDraft: { ...normalized.directiveRevisionDraft, [key]: value },
    })
  }
  return createPptPlanningState({
    ...normalized,
    outlineRevisionDraft: { ...normalized.outlineRevisionDraft, [key]: value },
  })
}

export function setPptRevisionGeneratingTarget(state = {}, target = {}) {
  return createPptPlanningState({
    ...createPptPlanningState(state),
    revisionGeneratingTarget: normalizeRevisionTarget(target),
    generationError: '',
    generationErrorSource: '',
  })
}

export function applyPptOutlineSectionRevision(state = {}, section = {}) {
  const normalized = createPptPlanningState(state)
  const nextSection = normalizePptOutline([section])[0]
  if (!nextSection) return normalized
  const index = findOutlineIndex(normalized.outline, nextSection)
  if (index < 0) return normalized
  const previous = normalized.outline[index]
  const nextOutline = normalized.outline.map((item, itemIndex) => (itemIndex === index ? nextSection : item))
  const key = outlineRevisionKey(previous)
  const stalePageId = String(Number(nextSection.pageNo || previous.pageNo || 0) || '')
  return createPptPlanningState({
    ...normalized,
    outline: nextOutline,
    spec: {
      ...normalized.spec,
      outline: nextOutline,
    },
    revisionSnapshots: {
      ...normalized.revisionSnapshots,
      [key]: { type: 'outline', item: previous },
    },
    staleDirectivePageIds: normalizeStaleDirectivePageIds([...normalized.staleDirectivePageIds, stalePageId]),
    activeRevisionTarget: {},
    outlineRevisionDraft: {},
    revisionGeneratingTarget: {},
    generationError: '',
    generationErrorSource: '',
  })
}

export function applyDeckBriefSlideRevision(state = {}, slide = {}) {
  const normalized = createPptPlanningState(state)
  const nextSlide = normalizeDeckBrief({ slides: [slide] }).slides[0]
  if (!nextSlide) return normalized
  const slides = cloneArray((normalized.deckBrief || {}).slides)
  const index = findSlideIndex(slides, nextSlide)
  if (index < 0) return normalized
  const previous = slides[index]
  const nextSlides = slides.map((item, itemIndex) => (itemIndex === index ? nextSlide : item))
  const key = slideRevisionKey(previous)
  const pageId = String(Number(nextSlide.index || 0) || '')
  return createPptPlanningState({
    ...normalized,
    deckBrief: {
      ...normalized.deckBrief,
      slides: nextSlides,
    },
    revisionSnapshots: {
      ...normalized.revisionSnapshots,
      [key]: { type: 'directive', item: previous },
    },
    staleDirectivePageIds: normalized.staleDirectivePageIds.filter((item) => item !== pageId),
    activeRevisionTarget: {},
    directiveRevisionDraft: {},
    revisionGeneratingTarget: {},
    generationError: '',
    generationErrorSource: '',
  })
}

export function undoPptSectionRevision(state = {}, type = '', target = {}) {
  const normalized = createPptPlanningState(state)
  const key = getPptRevisionKey(type, target)
  const snapshot = cloneObject(normalized.revisionSnapshots[key])
  const item = cloneObject(snapshot.item)
  if (!key || !item || !snapshot.type) return normalized
  const nextSnapshots = { ...normalized.revisionSnapshots }
  delete nextSnapshots[key]
  if (snapshot.type === 'outline') {
    const index = findOutlineIndex(normalized.outline, target)
    if (index < 0) return normalized
    const nextOutline = normalized.outline.map((outlineItem, itemIndex) => (itemIndex === index ? item : outlineItem))
    const pageId = String(Number(item.pageNo || item.page_no || 0) || '')
    return createPptPlanningState({
      ...normalized,
      outline: nextOutline,
      spec: { ...normalized.spec, outline: nextOutline },
      revisionSnapshots: nextSnapshots,
      staleDirectivePageIds: normalized.staleDirectivePageIds.filter((staleId) => staleId !== pageId),
      activeRevisionTarget: {},
      outlineRevisionDraft: {},
    })
  }
  const slides = cloneArray((normalized.deckBrief || {}).slides)
  const index = findSlideIndex(slides, target)
  if (index < 0) return normalized
  const nextSlides = slides.map((slideItem, itemIndex) => (itemIndex === index ? item : slideItem))
  const pageId = String(Number(item.index || 0) || '')
  return createPptPlanningState({
    ...normalized,
    deckBrief: { ...normalized.deckBrief, slides: nextSlides },
    revisionSnapshots: nextSnapshots,
    staleDirectivePageIds: normalized.staleDirectivePageIds.filter((staleId) => staleId !== pageId),
    activeRevisionTarget: {},
    directiveRevisionDraft: {},
  })
}

export function setPptGenerationError(state = {}, error = '', source = '') {
  const normalized = createPptPlanningState(state)
  const hasOutline = cloneArray(normalized.outline).length > 0
  return createPptPlanningState({
    ...normalized,
    currentStep: hasOutline ? PPT_PLANNING_STEPS.OUTLINE_READY : PPT_PLANNING_STEPS.MATERIALS,
    generationError: asText(error) || 'ppt_generation_failed',
    generationErrorSource: normalizePptErrorSource(source),
    dataPackageGenerating: false,
    sourceGrouping: false,
  })
}

export function setPptDataPackageGenerating(state = {}, generating = true) {
  return createPptPlanningState({
    ...createPptPlanningState(state),
    dataPackageGenerating: !!generating,
    generationError: '',
    generationErrorSource: '',
  })
}

export function syncPptPackagePlaceholderSources(state = {}, placeholders = []) {
  const normalized = createPptPlanningState(state)
  const removedSet = new Set(normalized.removedSourceIds)
  const nextPlaceholders = normalizeSources(placeholders)
    .filter((item) => {
      const sourceKind = asText(item.meta && item.meta.sourceKind)
      const sourceId = asText(item.id)
      return !removedSet.has(sourceId)
        && (sourceKind === 'package-placeholder' || sourceId.startsWith('package-placeholder:'))
    })
    .map((item) => normalizePptSource({
      ...item,
      status: asText(item.status) === 'generating' ? 'generating' : 'pending',
      selected: false,
      meta: {
        ...(item.meta || {}),
        sourceKind: 'package-placeholder',
        packagePlaceholder: true,
      },
    }))
  const sources = [
    ...normalized.sources.filter((item) => {
      const sourceKind = asText(item.meta && item.meta.sourceKind)
      const sourceId = asText(item.id)
      return sourceKind !== 'package-placeholder' && !sourceId.startsWith('package-placeholder:')
    }),
    ...nextPlaceholders,
  ]
  return createPptPlanningState({
    ...normalized,
    sources,
    sourceGroups: reconcilePptSourceGroups(normalized.sourceGroups, sources),
    spec: syncSpecSourceIds(normalized, sources),
  })
}

export function setPptSourceGrouping(state = {}, grouping = true) {
  return createPptPlanningState({
    ...createPptPlanningState(state),
    sourceGrouping: !!grouping,
    generationError: '',
    generationErrorSource: '',
  })
}

export function togglePptSourceSelection(state = {}, sourceId = '', selected = null) {
  const normalized = createPptPlanningState(state)
  const id = asText(sourceId)
  const sources = normalized.sources.map((item) => {
    if (item.id !== id) return item
    if (asText(item.status) !== 'ready') return { ...item, selected: false }
    return { ...item, selected: selected === null ? !item.selected : !!selected }
  })
  return createPptPlanningState({
    ...normalized,
    sources,
    sourceGroups: normalized.sourceGroups,
    removedSourceIds: normalized.removedSourceIds,
    spec: {
      ...normalized.spec,
      sourceIds: sources.filter((item) => item.selected).map((item) => item.id),
    },
  })
}

export function setAllPptSourcesSelected(state = {}, selected = true) {
  const normalized = createPptPlanningState(state)
  const sources = normalized.sources.map((item) => ({
    ...item,
    selected: asText(item.status) === 'ready' ? !!selected : false,
  }))
  return createPptPlanningState({
    ...normalized,
    sources,
    sourceGroups: normalized.sourceGroups,
    removedSourceIds: normalized.removedSourceIds,
    spec: {
      ...normalized.spec,
      sourceIds: sources.filter((item) => item.selected).map((item) => item.id),
    },
  })
}

export function applyPptSourceGroupsResponse(state = {}, response = {}) {
  const normalized = createPptPlanningState(state)
  const sourceIds = sourceIdsFromSources(normalized.sources)
  const incomingGroups = cloneArray(response.groups).map(normalizePptSourceGroup)
  const allowed = new Set(sourceIds)
  const assigned = new Set()
  const groups = incomingGroups
    .map((group) => {
      const groupSourceIds = []
      group.sourceIds.forEach((sourceId) => {
        if (!allowed.has(sourceId) || assigned.has(sourceId)) return
        assigned.add(sourceId)
        groupSourceIds.push(sourceId)
      })
      return { ...group, sourceIds: groupSourceIds }
    })
    .filter((group) => group.sourceIds.length)
  const missingSourceIds = sourceIds.filter((sourceId) => !assigned.has(sourceId))
  const sourceGroups = groups.length
    ? ensureUncategorizedGroup(groups, missingSourceIds)
    : reconcilePptSourceGroups([], normalized.sources)
  return createPptPlanningState({
    ...normalized,
    sourceGroups,
    removedSourceIds: normalized.removedSourceIds,
    sourceGrouping: false,
    spec: syncSpecSourceIds(normalized, normalized.sources),
  })
}

export function togglePptSourceGroupCollapsed(state = {}, groupId = '') {
  const normalized = createPptPlanningState(state)
  const id = asText(groupId)
  const sourceGroups = normalized.sourceGroups.map((group) => (
    group.id === id ? { ...group, collapsed: !group.collapsed } : group
  ))
  return createPptPlanningState({ ...normalized, sourceGroups })
}

export function setPptSourceGroupSelected(state = {}, groupId = '', selected = true) {
  const normalized = createPptPlanningState(state)
  const group = normalized.sourceGroups.find((item) => item.id === asText(groupId))
  if (!group) return normalized
  const groupSourceIds = new Set(group.sourceIds)
  const sources = normalized.sources.map((source) => {
    if (!groupSourceIds.has(source.id)) return source
    return { ...source, selected: asText(source.status) === 'ready' ? !!selected : false }
  })
  return createPptPlanningState({
    ...normalized,
    sources,
    sourceGroups: normalized.sourceGroups,
    spec: syncSpecSourceIds(normalized, sources),
  })
}

export function movePptSourceToGroup(state = {}, sourceId = '', groupId = '') {
  const normalized = createPptPlanningState(state)
  const id = asText(sourceId)
  const targetGroupId = asText(groupId) || PPT_UNCATEGORIZED_GROUP_ID
  if (!normalized.sources.some((source) => source.id === id)) return normalized
  const sourceGroups = normalized.sourceGroups.map((group) => ({
    ...group,
    sourceIds: group.sourceIds.filter((item) => item !== id),
  })).filter((group) => group.sourceIds.length || group.id === targetGroupId)
  let foundTarget = false
  const movedGroups = sourceGroups.map((group) => {
    if (group.id !== targetGroupId) return group
    foundTarget = true
    return { ...group, sourceIds: uniqueText([...group.sourceIds, id]), collapsed: false }
  })
  const nextGroups = foundTarget
    ? movedGroups
    : ensureUncategorizedGroup(movedGroups, [id]).map((group) => (
      group.id === PPT_UNCATEGORIZED_GROUP_ID ? { ...group, id: targetGroupId } : group
    ))
  return createPptPlanningState({ ...normalized, sourceGroups: reconcilePptSourceGroups(nextGroups, normalized.sources) })
}

export function renamePptSource(state = {}, sourceId = '', title = '') {
  const normalized = createPptPlanningState(state)
  const id = asText(sourceId)
  const nextTitle = asText(title)
  if (!id || !nextTitle) return normalized
  const sources = normalized.sources.map((source) => (
    source.id === id ? { ...source, title: nextTitle } : source
  ))
  return createPptPlanningState({
    ...normalized,
    sources,
    sourceGroups: normalized.sourceGroups,
    spec: syncSpecSourceIds(normalized, sources),
  })
}

export function removePptSource(state = {}, sourceId = '') {
  const normalized = createPptPlanningState(state)
  const id = asText(sourceId)
  if (!id) return normalized
  const sources = normalized.sources.filter((source) => source.id !== id)
  const sourceGroups = normalized.sourceGroups
    .map((group) => ({ ...group, sourceIds: group.sourceIds.filter((item) => item !== id) }))
    .filter((group) => group.sourceIds.length)
  return createPptPlanningState({
    ...normalized,
    sources,
    sourceGroups,
    removedSourceIds: uniqueText([...normalized.removedSourceIds, id]),
    spec: syncSpecSourceIds(normalized, sources),
  })
}

export function renamePptSourceGroup(state = {}, groupId = '', title = '') {
  const normalized = createPptPlanningState(state)
  const id = asText(groupId)
  const nextTitle = asText(title)
  if (!id || !nextTitle) return normalized
  const sourceGroups = normalized.sourceGroups.map((group) => (
    group.id === id ? { ...group, title: nextTitle } : group
  ))
  return createPptPlanningState({ ...normalized, sourceGroups })
}

export function setPptSourceGroupEmoji(state = {}, groupId = '', emoji = '') {
  const normalized = createPptPlanningState(state)
  const id = asText(groupId)
  if (!id) return normalized
  const sourceGroups = normalized.sourceGroups.map((group) => (
    group.id === id ? { ...group, emoji: asText(emoji) } : group
  ))
  return createPptPlanningState({ ...normalized, sourceGroups })
}

export function removePptSourceGroup(state = {}, groupId = '') {
  const normalized = createPptPlanningState(state)
  const id = asText(groupId)
  const targetGroup = normalized.sourceGroups.find((group) => group.id === id)
  if (!targetGroup) return normalized
  const remainingGroups = normalized.sourceGroups.filter((group) => group.id !== id)
  const sourceGroups = ensureUncategorizedGroup(remainingGroups, targetGroup.sourceIds)
  return createPptPlanningState({ ...normalized, sourceGroups })
}

export function mergePptPlanningSources(state = {}, nextSources = []) {
  const normalized = createPptPlanningState(state)
  const previousById = new Map(normalized.sources.map((item) => [asText(item.id), item]))
  const removedSet = new Set(normalized.removedSourceIds)
  const normalizedNext = normalizeSources(nextSources).filter((item) => !removedSet.has(asText(item.id)))
  const mergedIds = new Set(normalizedNext.map((item) => item.id))
  const retainedSources = cloneArray(normalized.sources)
    .filter((item) => ['user', 'package'].includes(asText((item.meta || {}).sourceKind)) && !mergedIds.has(asText(item.id)))
  const fallbackUserSources = retainedSources.length ? retainedSources : createDefaultUserPptSources()
  const sources = [...normalizedNext, ...fallbackUserSources].map((item) => {
    const previous = previousById.get(item.id)
    const ready = asText(item.status) === 'ready'
    const previousReady = previous && asText(previous.status) === 'ready'
    return normalizePptSource({
      ...item,
      selected: ready ? (previousReady ? !!previous.selected : !!item.selected) : false,
    })
  })
  return createPptPlanningState({
    ...normalized,
    sources,
    sourceGroups: reconcilePptSourceGroups(normalized.sourceGroups, sources),
    removedSourceIds: normalized.removedSourceIds,
    outline: normalized.outline,
    spec: {
      ...normalized.spec,
      sourceIds: getReadySelectedSourceIds(sources),
    },
  })
}

export function addPptDataPackageSource(state = {}, response = {}) {
  const normalized = createPptPlanningState(state)
  const packageSource = normalizePptSource(response.source || response)
  if (!packageSource.id) return createPptPlanningState({ ...normalized, dataPackageGenerating: false })
  const nextMeta = cloneObject(packageSource.meta)
  const nextPack = cloneObject(nextMeta.package)
  const nextSourceIds = uniqueText(nextPack.source_ids || nextPack.sourceIds).sort()
  const isSamePackageIntent = (source = {}) => {
    const meta = cloneObject(source.meta)
    const pack = cloneObject(meta.package)
    const sourceKind = asText(meta.sourceKind)
    const sourceId = asText(source.id)
    const packageLike = sourceKind === 'package'
      || sourceKind === 'package-placeholder'
      || sourceId.startsWith('package:')
      || sourceId.startsWith('package-placeholder:')
    if (!packageLike) return false
    if (asText(source.id) === packageSource.id) return true
    if (!nextPack.intent || !nextPack.package_mode) return false
    const sourceIds = uniqueText(pack.source_ids || pack.sourceIds).sort()
    return asText(meta.areaId) === asText(nextMeta.areaId)
      && asText(pack.intent) === asText(nextPack.intent)
      && asText(pack.package_mode) === asText(nextPack.package_mode)
      && sourceIds.length === nextSourceIds.length
      && sourceIds.every((sourceId, index) => sourceId === nextSourceIds[index])
  }
  const sources = [
    ...normalized.sources.filter((item) => !isSamePackageIntent(item)),
    {
      ...packageSource,
      status: 'ready',
      selected: true,
      meta: {
        ...(packageSource.meta || {}),
        sourceKind: 'package',
      },
    },
  ]
  return createPptPlanningState({
    ...normalized,
    sources,
    sourceGroups: reconcilePptSourceGroups(normalized.sourceGroups, sources),
    removedSourceIds: normalized.removedSourceIds,
    spec: {
      ...normalized.spec,
      sourceIds: getReadySelectedSourceIds(sources),
    },
    dataPackageGenerating: false,
    generationError: '',
    generationErrorSource: '',
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
  const sourceIds = getSelectedPptSourceIds(normalized)
  return {
    area_id: asText(context.areaId || context.area_id),
    source_ids: sourceIds,
    topic: asText(normalized.spec.topic),
    audience: asText(normalized.spec.audience),
    deck_type: asText(normalized.spec.deckType),
    page_count: Number(normalized.spec.pageCount || 15),
    research_enabled: !!normalized.spec.researchEnabled,
    sources: cloneArray(normalized.sources).filter((item) => sourceIds.includes(asText(item.id))),
    analysis_context: cloneObject(context.analysisContext || context.analysis_context),
  }
}

export function buildDeckBriefPayload(state = {}, context = {}) {
  const normalized = createPptPlanningState(state)
  const sourceIds = getSelectedPptSourceIds(normalized)
  return {
    area_id: asText(context.areaId || context.area_id),
    spec: {
      title: normalized.spec.title,
      goal: normalized.spec.goal,
      audience: normalized.spec.audience,
      deck_type: normalized.spec.deckType,
      page_count: Number(normalized.spec.pageCount || 15),
      outline: normalizePptOutline(normalized.outline).map((item) => ({
        id: item.id,
        page_no: item.pageNo,
        theme: item.theme,
        purpose: item.purpose,
      })),
      source_summary: '',
      missing_inputs: cloneArray(normalized.spec.missingInputs),
    },
    source_ids: sourceIds,
    sources: cloneArray(normalized.sources).filter((item) => sourceIds.includes(asText(item.id))),
    analysis_context: cloneObject(context.analysisContext || context.analysis_context),
    topic: asText(normalized.spec.topic),
    audience: asText(normalized.spec.audience),
    deck_type: asText(normalized.spec.deckType),
    page_count: Number(normalized.spec.pageCount || 15),
    research_enabled: !!normalized.spec.researchEnabled,
  }
}

export function buildPptOutlineSectionPayload(state = {}, target = {}, revisionNote = '', context = {}) {
  const normalized = createPptPlanningState(state)
  const sourceIds = getSelectedPptSourceIds(normalized)
  const targetIndex = findOutlineIndex(normalized.outline, target)
  const targetItem = targetIndex >= 0 ? normalized.outline[targetIndex] : target
  return {
    ...buildPptSpecPayload(normalized, context),
    spec: {
      title: normalized.spec.title,
      goal: normalized.spec.goal,
      audience: normalized.spec.audience,
      deck_type: normalized.spec.deckType,
      page_count: Number(normalized.spec.pageCount || 15),
      outline: normalizePptOutline(normalized.outline).map((item) => ({
        id: item.id,
        page_no: item.pageNo,
        theme: item.theme,
        purpose: item.purpose,
      })),
      source_summary: '',
      missing_inputs: cloneArray(normalized.spec.missingInputs),
    },
    outline: normalizePptOutline(normalized.outline).map((item) => ({
      id: item.id,
      page_no: item.pageNo,
      theme: item.theme,
      purpose: item.purpose,
    })),
    target: {
      id: targetItem.id,
      page_no: targetItem.pageNo,
      theme: targetItem.theme,
      purpose: targetItem.purpose,
    },
    revision_note: asText(revisionNote),
    source_ids: sourceIds,
  }
}

export function buildDeckBriefSlidePayload(state = {}, target = {}, revisionNote = '', context = {}) {
  const normalized = createPptPlanningState(state)
  const sourceIds = getSelectedPptSourceIds(normalized)
  const slides = cloneArray((normalized.deckBrief || {}).slides)
  const targetIndex = findSlideIndex(slides, target)
  const targetItem = targetIndex >= 0 ? slides[targetIndex] : target
  const outlineItem = normalized.outline.find((item) => Number(item.pageNo || 0) === Number(targetItem.index || 0)) || null
  return {
    ...buildDeckBriefPayload(normalized, context),
    outline: normalizePptOutline(normalized.outline).map((item) => ({
      id: item.id,
      page_no: item.pageNo,
      theme: item.theme,
      purpose: item.purpose,
    })),
    slides: slides.map((item) => ({
      index: item.index,
      title: item.title,
      purpose: item.purpose,
      key_message: item.keyMessage,
      visual_plan: item.visualPlan,
      required_sources: cloneArray(item.requiredSources),
      speaker_notes: item.speakerNotes,
    })),
    target: {
      index: targetItem.index,
      title: targetItem.title,
      purpose: targetItem.purpose,
      key_message: targetItem.keyMessage,
      visual_plan: targetItem.visualPlan,
      required_sources: cloneArray(targetItem.requiredSources),
      speaker_notes: targetItem.speakerNotes,
    },
    outline_item: outlineItem ? {
      id: outlineItem.id,
      page_no: outlineItem.pageNo,
      theme: outlineItem.theme,
      purpose: outlineItem.purpose,
    } : null,
    revision_note: asText(revisionNote),
    source_ids: sourceIds,
  }
}
