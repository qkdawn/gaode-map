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
  if (sourceKind === 'package' || sourceId.startsWith('package:')) {
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
    dataPackageGenerating: !!(seed.dataPackageGenerating || seed.data_package_generating),
    sourceGrouping: !!(seed.sourceGrouping || seed.source_grouping),
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
  })
}

export function setPptOutlineGenerating(state = {}) {
  return createPptPlanningState({
    ...createPptPlanningState(state),
    currentStep: PPT_PLANNING_STEPS.OUTLINE_GENERATING,
    generationError: '',
  })
}

export function setPptDirectiveGenerating(state = {}) {
  return createPptPlanningState({
    ...createPptPlanningState(state),
    currentStep: PPT_PLANNING_STEPS.DIRECTIVE_GENERATING,
    generationError: '',
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
  })
}

export function setPptGenerationError(state = {}, error = '') {
  const normalized = createPptPlanningState(state)
  const hasOutline = cloneArray(normalized.outline).length > 0
  return createPptPlanningState({
    ...normalized,
    currentStep: hasOutline ? PPT_PLANNING_STEPS.OUTLINE_READY : PPT_PLANNING_STEPS.MATERIALS,
    generationError: asText(error) || 'ppt_generation_failed',
    dataPackageGenerating: false,
    sourceGrouping: false,
  })
}

export function setPptDataPackageGenerating(state = {}, generating = true) {
  return createPptPlanningState({
    ...createPptPlanningState(state),
    dataPackageGenerating: !!generating,
    generationError: '',
  })
}

export function setPptSourceGrouping(state = {}, grouping = true) {
  return createPptPlanningState({
    ...createPptPlanningState(state),
    sourceGrouping: !!grouping,
    generationError: '',
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
    if (asText(meta.sourceKind) !== 'package' && !asText(source.id).startsWith('package:')) return false
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
