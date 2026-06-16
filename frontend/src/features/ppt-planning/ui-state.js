import {
  createDefaultPptSources,
  createDefaultPptSpec,
  createDefaultUserPptSources,
  createPptTransportFromAiPayload,
  normalizeDeckBrief,
  normalizeDeckSlideBrief,
  normalizeNarrativePlan,
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
  'narrative',
  'slides',
  'directive',
])

const PPT_GENERATION_JOB_EVENT_LIMIT = 60
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
const PPT_GENERATION_TERMINAL_PHASES = new Set(['ready', 'failed', 'superseded'])

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

function normalizeSlideQueueItem(value = {}, fallbackPageNo = 1) {
  const item = cloneObject(value)
  const pageNo = Number(item.pageNo || item.page_no || item.index || fallbackPageNo) || fallbackPageNo
  const status = asText(item.status)
  return {
    pageNo,
    status: ['pending', 'generating', 'ready', 'failed'].includes(status) ? status : 'pending',
    error: asText(item.error),
    updatedAt: asText(item.updatedAt || item.updated_at),
  }
}

function normalizeSlideGenerationQueue(value = [], outline = []) {
  const source = cloneArray(value)
  const byPage = new Map(source.map((item, index) => {
    const normalized = normalizeSlideQueueItem(item, index + 1)
    return [normalized.pageNo, normalized]
  }))
  const outlineItems = normalizePptOutline(outline)
  if (!outlineItems.length) return source.map((item, index) => normalizeSlideQueueItem(item, index + 1))
  return outlineItems.map((item) => byPage.get(item.pageNo) || normalizeSlideQueueItem({ pageNo: item.pageNo }, item.pageNo))
}

function normalizeSlideGenerationJob(value = {}) {
  const job = cloneObject(value)
  return {
    active: !!job.active,
    currentPageNo: Number(job.currentPageNo || job.current_page_no || 0) || 0,
    total: Number(job.total || 0) || 0,
    failedPageNo: Number(job.failedPageNo || job.failed_page_no || 0) || 0,
    error: asText(job.error),
    startedAt: asText(job.startedAt || job.started_at),
    completedAt: asText(job.completedAt || job.completed_at),
  }
}

function normalizeVisualGenerationStatus(value = {}) {
  const item = cloneObject(value)
  const status = asText(item.status)
  return {
    status: ['idle', 'generating', 'ready', 'failed'].includes(status) ? status : 'idle',
    error: asText(item.error),
    updatedAt: asText(item.updatedAt || item.updated_at),
  }
}

function normalizeVisualGenerationBySlide(value = {}) {
  const source = cloneObject(value)
  return Object.fromEntries(Object.entries(source)
    .map(([key, item]) => {
      const slideIndex = Number(key) || Number(item && (item.slideIndex || item.slide_index || item.index || 0)) || 0
      return slideIndex ? [String(slideIndex), normalizeVisualGenerationStatus(item)] : null
    })
    .filter(Boolean))
}

function cloneSerializable(value = {}) {
  try {
    return JSON.parse(JSON.stringify(value ?? {}))
  } catch (_) {
    return { unserializable: asText(value) || 'unserializable_response' }
  }
}

function normalizeGenerationResponse(value = {}) {
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

function createGenerationResponseSnapshot(source = '', payload = {}) {
  return normalizeGenerationResponse({
    source,
    receivedAt: new Date().toISOString(),
    payload,
  })
}

function normalizeGenerationJobType(value = '') {
  const type = asText(value)
  return PPT_GENERATION_JOB_TYPES.has(type) ? type : ''
}

function normalizeGenerationJobPhase(value = '') {
  const phase = asText(value)
  return PPT_GENERATION_JOB_PHASES.has(phase) ? phase : 'idle'
}

function summarizeGenerationResponse(type = '', response = {}) {
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

function createGenerationEvent(name = '', details = {}) {
  return {
    name: asText(name) || 'event',
    at: new Date().toISOString(),
    details: cloneSerializable(details),
  }
}

function normalizeGenerationEvents(events = []) {
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

function normalizeGenerationJob(value = {}) {
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

function appendGenerationEvent(job = {}, name = '', details = {}) {
  const normalized = normalizeGenerationJob(job)
  return {
    ...normalized,
    events: [
      ...normalizeGenerationEvents(normalized.events),
      createGenerationEvent(name, details),
    ].slice(-PPT_GENERATION_JOB_EVENT_LIMIT),
  }
}

function isCurrentGenerationJob(state = {}, requestId = '') {
  const job = normalizeGenerationJob(state.generationJob || state.generation_job)
  return !!asText(requestId) && asText(job.id) === asText(requestId)
}

function generationStepForType(type = '') {
  const normalizedType = normalizeGenerationJobType(type)
  if (normalizedType === 'narrative') return PPT_PLANNING_STEPS.NARRATIVE_GENERATING
  if (normalizedType === 'slides' || normalizedType === 'directive') return PPT_PLANNING_STEPS.SLIDES_GENERATING
  return PPT_PLANNING_STEPS.OUTLINE_GENERATING
}

function generationReadyStepForState(state = {}, type = '') {
  const normalizedType = normalizeGenerationJobType(type)
  if (normalizedType === 'slides' || normalizedType === 'directive') return cloneArray((state.deckBrief || {}).slides).length ? PPT_PLANNING_STEPS.DIRECTIVE_DRAFT : PPT_PLANNING_STEPS.NARRATIVE_READY
  if (normalizedType === 'narrative') return normalizeNarrativePlan(state.narrativePlan || state.narrative_plan).slideRoles.length ? PPT_PLANNING_STEPS.NARRATIVE_READY : PPT_PLANNING_STEPS.OUTLINE_READY
  return cloneArray(state.outline).length ? PPT_PLANNING_STEPS.OUTLINE_READY : PPT_PLANNING_STEPS.MATERIALS
}

function normalizeContextManifest(value = {}) {
  const manifest = cloneObject(value)
  const sourceManifest = cloneArray(manifest.source_manifest || manifest.sourceManifest)
    .map((item) => {
      const entry = cloneObject(item)
      const sourceId = asText(entry.source_id || entry.sourceId)
      if (!sourceId) return null
      return {
        ...entry,
        source_id: sourceId,
        sourceId,
        title: asText(entry.title),
        source_kind: asText(entry.source_kind || entry.sourceKind),
        sourceKind: asText(entry.source_kind || entry.sourceKind),
        transport_status: asText(entry.transport_status || entry.transportStatus),
        transportStatus: asText(entry.transport_status || entry.transportStatus),
        included: uniqueText(entry.included),
        excluded: cloneArray(entry.excluded),
        metric_count: Number(entry.metric_count ?? entry.metricCount ?? 0) || 0,
        metricCount: Number(entry.metric_count ?? entry.metricCount ?? 0) || 0,
        evidence_count: Number(entry.evidence_count ?? entry.evidenceCount ?? 0) || 0,
        evidenceCount: Number(entry.evidence_count ?? entry.evidenceCount ?? 0) || 0,
        policy: asText(entry.policy),
      }
    })
    .filter(Boolean)
  return {
    ...manifest,
    version: asText(manifest.version),
    source_manifest: sourceManifest,
    sourceManifest,
    omitted_payloads: cloneArray(manifest.omitted_payloads || manifest.omittedPayloads),
    omittedPayloads: cloneArray(manifest.omitted_payloads || manifest.omittedPayloads),
  }
}

function mergeSourceTransportManifest(sources = [], contextManifest = {}) {
  const manifest = normalizeContextManifest(contextManifest)
  const bySourceId = new Map(cloneArray(manifest.source_manifest).map((item) => [asText(item.source_id || item.sourceId), item]))
  if (!bySourceId.size) return cloneArray(sources)
  return cloneArray(sources).map((source) => {
    const sourceId = asText(source.id)
    const transport = bySourceId.get(sourceId)
    if (!transport) return source
    return {
      ...source,
      meta: {
        ...(source.meta || {}),
        transport,
      },
    }
  })
}

function aiPayloadFromSource(source = {}) {
  const meta = cloneObject(source.meta)
  const payload = cloneObject(meta.aiPayload || meta.ai_payload)
  return payload.version === 'ppt_ai_input_block_v1' ? payload : {}
}

function sourceForPptRequest(source = {}) {
  const meta = cloneObject(source.meta)
  const aiPayload = aiPayloadFromSource(source)
  return normalizePptSource({
    id: source.id,
    type: source.type,
    title: source.title,
    status: source.status,
    selected: source.selected,
    meta: {
      label: asText(meta.label),
      sourceKind: asText(meta.sourceKind),
      areaId: asText(meta.areaId),
      aiPayload,
      ai_payload: aiPayload,
      transport: aiPayload.version ? createPptTransportFromAiPayload(aiPayload) : cloneObject(meta.transport),
    },
  })
}

function sourceHasDeliverableAiPayload(source = {}) {
  const aiPayload = aiPayloadFromSource(source)
  return cloneArray(aiPayload.included).map((item) => asText(item)).filter(Boolean).length > 0
}

export function getPptSourceDeliveryManifest(state = {}) {
  const sources = cloneArray(createPptPlanningState(state).sources)
  const selectedSources = sources.filter((item) => item && item.selected && asText(item.status) === 'ready')
  const deliverableSources = selectedSources.filter(sourceHasDeliverableAiPayload)
  const emptyPayloadSources = selectedSources.filter((item) => !sourceHasDeliverableAiPayload(item))
  return {
    selectedSources,
    deliverableSources,
    emptyPayloadSources,
    sourceIds: selectedSources.map((item) => asText(item.id)).filter(Boolean),
    deliverableSourceIds: deliverableSources.map((item) => asText(item.id)).filter(Boolean),
    emptyPayloadSourceIds: emptyPayloadSources.map((item) => asText(item.id)).filter(Boolean),
  }
}

function packageAiPayloadFromSource(source = {}) {
  const meta = cloneObject(source.meta)
  const pack = cloneObject(meta.package)
  const sourceId = asText(source.id)
  const title = asText(source.title)
  const evidence = []
  if (pack.summary) {
    evidence.push({
      source_id: sourceId,
      sourceId,
      source_title: title,
      sourceTitle: title,
      type: 'package_summary',
      title: asText(pack.title) || title,
      text: asText(pack.summary),
      payload: {
        package_mode: asText(pack.package_mode),
        intent: asText(pack.intent),
        total: pack.total,
      },
    })
  }
  cloneArray(pack.items).slice(0, 6).forEach((item) => {
    evidence.push({
      source_id: sourceId,
      sourceId,
      source_title: title,
      sourceTitle: title,
      type: 'package_poi_sample',
      title: asText(item.name) || '代表性 POI',
      text: [item.category, item.subcategory, item.address].map((value) => asText(value)).filter(Boolean).join(' / '),
      payload: {
        id: item.id,
        name: item.name,
        category: item.category,
        subcategory: item.subcategory,
        address: item.address,
      },
    })
  })
  cloneArray(pack.carriers).slice(0, 8).forEach((item) => {
    evidence.push({
      source_id: sourceId,
      sourceId,
      source_title: title,
      sourceTitle: title,
      type: 'package_carrier',
      title: asText(item.carrier_label || item.carrierLabel || item.carrier_id || item.carrierId) || '空间载体',
      text: asText(item.summary),
      payload: {
        carrier_id: item.carrier_id || item.carrierId,
        carrier_type: item.carrier_type || item.carrierType,
        road_metrics: item.road_metrics || item.roadMetrics,
        poi_metrics: item.poi_metrics || item.poiMetrics,
        population_metrics: item.population_metrics || item.populationMetrics,
        nightlight_metrics: item.nightlight_metrics || item.nightlightMetrics,
      },
    })
  })
  const included = evidence.length ? ['evidence'] : []
  return {
    version: 'ppt_ai_input_block_v1',
    source_id: sourceId,
    sourceId,
    title,
    source_kind: 'package',
    sourceKind: 'package',
    included,
    scope: null,
    metrics: [],
    metric_gaps: [],
    metricGaps: [],
    evidence,
    visual_specs: [],
    visualSpecs: [],
    excluded: [
      { type: 'package_full_items', reason: '不传资料包完整 POI 明细，只传摘要和代表样本。', count: cloneArray(pack.items).length },
      { type: 'package_carrier_geometries', reason: '不传载体完整 geometry，只传载体摘要和指标摘要。', count: cloneArray(pack.carriers).length },
    ],
    counts: { scope: 0, metrics: 0, metric_gaps: 0, evidence: evidence.length, visual_specs: 0 },
    policy: '资料包只通过摘要、代表样本、载体摘要进入 evidence；不传完整明细。',
  }
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
  if (sourceKind === 'document' || sourceId.startsWith('document:')) {
    return { id: 'group:document-evidence', title: '文档库', emoji: '' }
  }
  if (['current:scope', 'current:dataset:h3'].includes(sourceId)) {
    return { id: 'group:spatial-scope', title: '空间范围与网格', emoji: '' }
  }
  if (['current:dataset:poi', 'current:analysis:poi_h3', 'current:analysis:nightlight'].includes(sourceId)) {
    return { id: 'group:urban-vitality', title: '城市活力证据', emoji: '' }
  }
  if (sourceId === 'current:analysis:population') {
    return { id: 'group:population-demand', title: '人群与需求', emoji: '' }
  }
  if (sourceId === 'current:analysis:road') {
    return { id: 'group:accessibility', title: '交通与可达性', emoji: '' }
  }
  return { id: '', title: '', emoji: '' }
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
    if (!spec.id) return
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

function reconcilePptSourceGroups(seedGroups = [], sources = [], ungroupedSourceIds = []) {
  const sourceIds = cloneArray(sources).map((item) => asText(item.id)).filter(Boolean)
  const allowed = new Set(sourceIds)
  const ungrouped = new Set(uniqueText(ungroupedSourceIds))
  const seen = new Set()
  const normalizedGroups = cloneArray(seedGroups)
    .map(normalizePptSourceGroup)
    .filter((group) => group.id !== PPT_UNCATEGORIZED_GROUP_ID)
    .map((group) => {
      const groupSourceIds = group.sourceIds.filter((sourceId) => {
        if (!allowed.has(sourceId) || seen.has(sourceId) || ungrouped.has(sourceId)) return false
        seen.add(sourceId)
        return true
      })
      return { ...group, sourceIds: groupSourceIds }
    })
    .filter((group) => group.sourceIds.length)

  const groupById = new Map(normalizedGroups.map((group) => [group.id, group]))
  sourceIds.forEach((sourceId) => {
    if (seen.has(sourceId) || ungrouped.has(sourceId)) return
    const source = cloneArray(sources).find((item) => asText(item.id) === sourceId)
    const spec = getDefaultGroupSpecForSource(source)
    if (!spec.id) return
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

function ensureGroupForSourceIds(groups = [], groupId = '', sourceIds = []) {
  const ids = uniqueText(sourceIds)
  const id = asText(groupId)
  if (!ids.length) return cloneArray(groups)
  if (!id || id === PPT_UNCATEGORIZED_GROUP_ID) return cloneArray(groups)
  const nextGroups = cloneArray(groups).map(normalizePptSourceGroup)
  const existing = nextGroups.find((group) => group.id === id)
  if (existing) {
    existing.sourceIds = uniqueText([...existing.sourceIds, ...ids])
    existing.collapsed = false
    return nextGroups
  }
  return [
    ...nextGroups,
    {
      id,
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

function isRetainedUserSource(source = {}) {
  const sourceKind = asText(source.meta && source.meta.sourceKind)
  const sourceId = asText(source.id)
  return ['user', 'package', 'document'].includes(sourceKind)
    || sourceId.startsWith('document:')
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
  const seedSourceGroups = seed.sourceGroups || seed.source_groups || []
  const legacyUngroupedSourceIds = cloneArray(seedSourceGroups)
    .map(normalizePptSourceGroup)
    .filter((group) => group.id === PPT_UNCATEGORIZED_GROUP_ID)
    .flatMap((group) => group.sourceIds)
  const ungroupedSourceIds = uniqueText([
    ...(seed.ungroupedSourceIds || seed.ungrouped_source_ids || []),
    ...legacyUngroupedSourceIds,
  ])
  const contextManifest = normalizeContextManifest(seed.contextManifest || seed.context_manifest)
  const removedSet = new Set(removedSourceIds)
  const sources = mergeSourceTransportManifest(
    normalizeSources(seed.sources).filter((item) => !removedSet.has(asText(item.id))),
    contextManifest,
  )
  const allowedSourceIds = new Set(sourceIdsFromSources(sources))
  const normalizedUngroupedSourceIds = ungroupedSourceIds.filter((sourceId) => allowedSourceIds.has(sourceId))
  const selectedSourceIds = getReadySelectedSourceIds(sources)
  const spec = createDefaultPptSpec({
    ...seed.spec,
    sourceIds: cloneArray((seed.spec || {}).sourceIds || (seed.spec || {}).source_ids).length
      ? cloneArray((seed.spec || {}).sourceIds || (seed.spec || {}).source_ids)
      : selectedSourceIds,
  })
  const outline = normalizePptOutline(seed.outline || seed.deckOutline || seed.deck_outline || spec.outline)
  const deckBrief = normalizeDeckBrief(seed.deckBrief || seed.deck_brief || {})
  const narrativePlan = normalizeNarrativePlan(seed.narrativePlan || seed.narrative_plan || {})
  const slideGenerationQueue = normalizeSlideGenerationQueue(seed.slideGenerationQueue || seed.slide_generation_queue || [], outline)
  const sourceGroups = reconcilePptSourceGroups(seedSourceGroups.length ? seedSourceGroups : createDefaultPptSourceGroups(sources), sources, normalizedUngroupedSourceIds)
  return {
    currentStep: asText(seed.currentStep || seed.current_step) || PPT_PLANNING_STEPS.MATERIALS,
    sources,
    sourceGroups,
    contextManifest,
    removedSourceIds,
    ungroupedSourceIds: normalizedUngroupedSourceIds,
    spec,
    outline,
    narrativePlan,
    narrativeRevisionDraft: normalizeRevisionDraft(seed.narrativeRevisionDraft || seed.narrative_revision_draft),
    slideGenerationQueue,
    slideGenerationJob: normalizeSlideGenerationJob(seed.slideGenerationJob || seed.slide_generation_job),
    visualGenerationBySlide: normalizeVisualGenerationBySlide(seed.visualGenerationBySlide || seed.visual_generation_by_slide),
    deckBrief,
    selectedSlideId: normalizeSelectedSlideId(seed, deckBrief),
    generationError: asText(seed.generationError || seed.generation_error),
    generationErrorSource: normalizePptErrorSource(seed.generationErrorSource || seed.generation_error_source),
    generationResponse: normalizeGenerationResponse(seed.generationResponse || seed.generation_response),
    generationJob: normalizeGenerationJob(seed.generationJob || seed.generation_job),
    dataPackageGenerating: !!(seed.dataPackageGenerating || seed.data_package_generating),
    sourceRefreshing: !!(seed.sourceRefreshing || seed.source_refreshing),
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
  const manifest = getPptSourceDeliveryManifest({ sources })
  return {
    total: sources.length,
    selected: manifest.selectedSources.length,
    ready: ready.length,
    deliverable: manifest.deliverableSources.length,
    selectedDeliverable: manifest.deliverableSources.length,
    emptyPayload: manifest.emptyPayloadSources.length,
    sourceIds: manifest.sourceIds,
    deliverableSourceIds: manifest.deliverableSourceIds,
    emptyPayloadSourceIds: manifest.emptyPayloadSourceIds,
  }
}

export function isPptSourceRefreshing(state = {}) {
  return !!createPptPlanningState(state).sourceRefreshing
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

export function getBlockingPptInputSources(state = {}) {
  const sources = cloneArray(createPptPlanningState(state).sources)
  const pendingPackageIds = new Set(getPendingPptPackageSources({ sources }).map((item) => asText(item.id)))
  return sources.filter((item) => {
    if (!item) return false
    const sourceId = asText(item.id)
    const status = asText(item.status)
    if (status === 'ready') return false
    if (status === 'generating') return true
    if (item.selected) return true
    return pendingPackageIds.has(sourceId)
  })
}

export function hasPptBlockingInputs(state = {}) {
  const normalized = createPptPlanningState(state)
  return !!(
    normalized.sourceRefreshing
    || normalized.dataPackageGenerating
    || normalized.sourceGrouping
    || getBlockingPptInputSources(normalized).length
  )
}

export function getActiveDeckSlideBrief(state = {}) {
  const selectedId = asText(state.selectedSlideId)
  const slides = cloneArray((state.deckBrief || {}).slides)
  return slides.find((item) => asText(item && item.id) === selectedId) || slides[0] || null
}

function filenameFromVisualArtifact(artifact = {}) {
  const explicit = asText(artifact.filename)
  if (explicit) return explicit.split(/[\\/]/).pop()
  const url = asText(artifact.url)
  if (!url) return ''
  const path = url.split('?')[0].split('#')[0]
  try {
    return decodeURIComponent(path.split('/').pop() || '')
  } catch (_) {
    return path.split('/').pop() || ''
  }
}

export function collectPptVisualArtifactFilenames(value = {}) {
  const filenames = []
  const visitSlide = (slide = {}) => {
    cloneArray(slide.visualArtifacts || slide.visual_artifacts).forEach((artifact) => {
      const filename = filenameFromVisualArtifact(cloneObject(artifact))
      if (filename) filenames.push(filename)
    })
  }
  if (Array.isArray(value)) {
    value.forEach((item) => visitSlide(item))
  } else if (value && typeof value === 'object') {
    if (Array.isArray(value.slides)) {
      value.slides.forEach((item) => visitSlide(item))
    } else if (value.deckBrief || value.deck_brief) {
      collectPptVisualArtifactFilenames(value.deckBrief || value.deck_brief).forEach((filename) => filenames.push(filename))
    } else {
      visitSlide(value)
    }
  }
  return uniqueText(filenames)
}

function visualKey(visual = {}) {
  return asText(visual.visual_id || visual.visualId || visual.title)
}

function artifactKey(artifact = {}) {
  return asText(artifact.visual_id || artifact.visualId || artifact.source_visual_id || artifact.sourceVisualId)
}

function hasVisualArtifactForSpec(slide = {}, visual = {}) {
  const key = visualKey(visual)
  if (!key) return false
  return cloneArray(slide.visualArtifacts || slide.visual_artifacts).some((artifact) => artifactKey(artifact) === key)
}

function slideHasVisualSpecs(slide = {}) {
  return cloneArray(slide.visualSpecs || slide.visual_specs).length > 0
}

function slideHasPendingVisualSpecs(slide = {}) {
  return cloneArray(slide.visualSpecs || slide.visual_specs).some((visual) => !hasVisualArtifactForSpec(slide, visual))
}

function slideVisualStatusKey(slideIndex = 0) {
  return String(Number(slideIndex || 0) || 0)
}

function metricContextForVisualPayload(sources = []) {
  const metrics = []
  const metricGaps = []
  cloneArray(sources).forEach((source) => {
    const payload = aiPayloadFromSource(source)
    cloneArray(payload.metrics).forEach((metric) => metrics.push(cloneObject(metric)))
    cloneArray(payload.metric_gaps || payload.metricGaps).forEach((gap) => metricGaps.push(cloneObject(gap)))
  })
  return {
    metrics,
    metric_gaps: metricGaps,
  }
}

function sourceIdsForSlide(slide = {}) {
  const ids = []
  cloneArray(slide.requiredSources || slide.required_sources).forEach((item) => ids.push(asText(item)))
  cloneArray(slide.metricClaims || slide.metric_claims).forEach((claim) => {
    ids.push(asText(claim && (claim.source_id || claim.sourceId)))
  })
  cloneArray(slide.visualSpecs || slide.visual_specs).forEach((visual) => {
    cloneArray(visual && (visual.source_ids || visual.sourceIds)).forEach((sourceId) => ids.push(asText(sourceId)))
  })
  return uniqueText(ids).filter(Boolean)
}

export function markPptDirectiveStaleForSources(state = {}, sourceIds = []) {
  const normalized = createPptPlanningState(state)
  const changed = new Set(uniqueText(sourceIds))
  if (!changed.size) return normalized
  const stalePageIds = cloneArray(normalized.staleDirectivePageIds)
  cloneArray((normalized.deckBrief || {}).slides).forEach((slide) => {
    if (!sourceIdsForSlide(slide).some((sourceId) => changed.has(sourceId))) return
    stalePageIds.push(String(Number(slide.index || 0) || slide.index || ''))
  })
  return createPptPlanningState({
    ...normalized,
    staleDirectivePageIds: normalizeStaleDirectivePageIds([...normalized.staleDirectivePageIds, ...stalePageIds]),
  })
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
  const contextManifest = normalizeContextManifest(response.contextManifest || response.context_manifest)
  const sources = mergeSourceTransportManifest(normalized.sources, contextManifest)
  return createPptPlanningState({
    ...normalized,
    sources,
    contextManifest,
    currentStep: PPT_PLANNING_STEPS.OUTLINE_READY,
    outline,
    narrativePlan: normalizeNarrativePlan({}),
    narrativeRevisionDraft: {},
    slideGenerationQueue: normalizeSlideGenerationQueue([], outline),
    slideGenerationJob: {},
    deckBrief: normalizeDeckBrief({}),
    selectedSlideId: '',
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
    generationResponse: createGenerationResponseSnapshot('outline', response),
    revisionSnapshots: {},
    staleDirectivePageIds: [],
    activeRevisionTarget: {},
    outlineRevisionDraft: {},
    directiveRevisionDraft: {},
  })
}

export function startPptGenerationJob(state = {}, options = {}) {
  const normalized = createPptPlanningState(state)
  const requestId = asText(options.requestId || options.request_id)
  const type = normalizeGenerationJobType(options.type)
  const tabId = asText(options.tabId || options.tab_id)
  if (!requestId || !type || !tabId) return normalized
  const previousJob = normalizeGenerationJob(normalized.generationJob)
  const previousEvents = previousJob.id && !PPT_GENERATION_TERMINAL_PHASES.has(previousJob.phase)
    ? appendGenerationEvent({ ...previousJob, phase: 'superseded', completedAt: new Date().toISOString() }, 'superseded', { byRequestId: requestId }).events
    : []
  const job = appendGenerationEvent({
    id: requestId,
    type,
    phase: 'requesting',
    tabId,
    startedAt: new Date().toISOString(),
    completedAt: '',
    error: '',
    responseSummary: {},
    events: previousEvents,
  }, 'requesting', { tabId, type })
  return createPptPlanningState({
    ...normalized,
    currentStep: generationStepForType(type),
    generationError: '',
    generationErrorSource: '',
    generationResponse: {},
    generationJob: job,
  })
}

export function appendPptGenerationDebugEvent(state = {}, name = '', details = {}) {
  const normalized = createPptPlanningState(state)
  const job = normalizeGenerationJob(normalized.generationJob)
  if (!job.id) return normalized
  return createPptPlanningState({
    ...normalized,
    generationJob: appendGenerationEvent(job, name, details),
  })
}

export function markPptGenerationResponseReceived(state = {}, requestId = '', response = {}) {
  const normalized = createPptPlanningState(state)
  if (!isCurrentGenerationJob(normalized, requestId)) return normalized
  const job = normalizeGenerationJob(normalized.generationJob)
  const summary = summarizeGenerationResponse(job.type, response)
  return createPptPlanningState({
    ...normalized,
    generationJob: appendGenerationEvent({
      ...job,
      phase: 'response_received',
      responseSummary: summary,
    }, 'response_received', summary),
    generationResponse: createGenerationResponseSnapshot(job.type, response),
  })
}

export function markPptGenerationApplying(state = {}, requestId = '') {
  const normalized = createPptPlanningState(state)
  if (!isCurrentGenerationJob(normalized, requestId)) return normalized
  const job = normalizeGenerationJob(normalized.generationJob)
  return createPptPlanningState({
    ...normalized,
    generationJob: appendGenerationEvent({
      ...job,
      phase: 'applying',
    }, 'applying', { type: job.type }),
  })
}

export function applyPptGenerationSuccess(state = {}, requestId = '', response = {}) {
  const normalized = createPptPlanningState(state)
  if (!isCurrentGenerationJob(normalized, requestId)) return normalized
  const job = normalizeGenerationJob(normalized.generationJob)
  const applied = job.type === 'narrative'
    ? applyNarrativePlanResponse(normalized, response)
    : job.type === 'directive'
      ? applyDeckBriefResponse(normalized, response)
      : applyPptSpecResponse(normalized, response)
  const summary = summarizeGenerationResponse(job.type, response)
  return createPptPlanningState({
    ...applied,
    generationJob: appendGenerationEvent({
      ...job,
      phase: 'ready',
      completedAt: new Date().toISOString(),
      error: '',
      responseSummary: summary,
    }, 'ready', summary),
  })
}

export function completePptGenerationJob(state = {}, requestId = '', response = {}) {
  const normalized = createPptPlanningState(state)
  const job = normalizeGenerationJob(normalized.generationJob)
  if (!isCurrentGenerationJob(normalized, requestId)) {
    return createPptPlanningState({
      ...normalized,
      generationJob: appendGenerationEvent(job, 'stale_response_ignored', {
        requestId: asText(requestId),
        currentRequestId: job.id,
      }),
    })
  }
  const summary = summarizeGenerationResponse(job.type, response)
  const responseReceivedJob = appendGenerationEvent({
    ...job,
    phase: 'response_received',
    responseSummary: summary,
  }, 'response_received', summary)
  const applyingJob = appendGenerationEvent({
    ...responseReceivedJob,
    phase: 'applying',
  }, 'applying', { type: job.type })
  try {
    const baseState = createPptPlanningState({
      ...normalized,
      generationJob: applyingJob,
      generationResponse: createGenerationResponseSnapshot(job.type, response),
    })
    const applied = job.type === 'narrative'
      ? applyNarrativePlanResponse(baseState, response)
      : job.type === 'directive'
        ? applyDeckBriefResponse(baseState, response)
        : applyPptSpecResponse(baseState, response)
    return createPptPlanningState({
      ...applied,
      generationJob: appendGenerationEvent({
        ...applyingJob,
        phase: 'ready',
        completedAt: new Date().toISOString(),
        error: '',
        responseSummary: summary,
      }, 'ready', summary),
    })
  } catch (error) {
    const label = job.type === 'narrative' ? '叙事方案' : job.type === 'directive' ? '指令' : '目录'
    const message = `${label}返回已收到，但前端应用失败：${error && error.message ? error.message : String(error)}`
    return createPptPlanningState({
      ...normalized,
      currentStep: generationReadyStepForState(normalized, job.type),
      generationError: message,
      generationErrorSource: normalizePptErrorSource(job.type),
      generationResponse: createGenerationResponseSnapshot(job.type, response),
      generationJob: appendGenerationEvent({
        ...applyingJob,
        phase: 'failed',
        completedAt: new Date().toISOString(),
        error: message,
        responseSummary: summary,
      }, 'failed', { error: message, source: job.type }),
      dataPackageGenerating: false,
      sourceRefreshing: false,
      sourceGrouping: false,
    })
  }
}

export function failPptGenerationJob(state = {}, requestId = '', error = '', options = {}) {
  const normalized = createPptPlanningState(state)
  if (!isCurrentGenerationJob(normalized, requestId)) return normalized
  const job = normalizeGenerationJob(normalized.generationJob)
  const source = normalizePptErrorSource(options.source || job.type)
  const message = asText(error && error.message ? error.message : error) || 'ppt_generation_failed'
  const response = options && (options.generationResponse || options.generation_response)
  const responseSummary = response && typeof response === 'object'
    ? summarizeGenerationResponse(job.type, response)
    : job.responseSummary
  return createPptPlanningState({
    ...normalized,
    currentStep: generationReadyStepForState(normalized, job.type),
    generationError: message,
    generationErrorSource: source,
    generationResponse: response && typeof response === 'object' ? createGenerationResponseSnapshot(job.type, response) : normalized.generationResponse,
    generationJob: appendGenerationEvent({
      ...job,
      phase: 'failed',
      completedAt: new Date().toISOString(),
      error: message,
      responseSummary,
    }, 'failed', { error: message, source }),
    dataPackageGenerating: false,
    sourceRefreshing: false,
    sourceGrouping: false,
  })
}

export function supersedePptGenerationJob(state = {}, requestId = '') {
  const normalized = createPptPlanningState(state)
  if (!isCurrentGenerationJob(normalized, requestId)) return normalized
  const job = normalizeGenerationJob(normalized.generationJob)
  return createPptPlanningState({
    ...normalized,
    currentStep: generationReadyStepForState(normalized, job.type),
    generationJob: appendGenerationEvent({
      ...job,
      phase: 'superseded',
      completedAt: new Date().toISOString(),
      error: 'ppt_generation_superseded',
    }, 'superseded', { requestId }),
  })
}

export function setPptOutlineGenerating(state = {}) {
  return createPptPlanningState({
    ...createPptPlanningState(state),
    currentStep: PPT_PLANNING_STEPS.OUTLINE_GENERATING,
    generationError: '',
    generationErrorSource: '',
    generationResponse: {},
  })
}

export function setPptDirectiveGenerating(state = {}) {
  return createPptPlanningState({
    ...createPptPlanningState(state),
    currentStep: PPT_PLANNING_STEPS.SLIDES_GENERATING,
    generationError: '',
    generationErrorSource: '',
    generationResponse: {},
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
    narrativePlan: normalizeNarrativePlan({}),
    narrativeRevisionDraft: {},
    slideGenerationQueue: [],
    slideGenerationJob: {},
    visualGenerationBySlide: {},
    deckBrief: normalizeDeckBrief({}),
    contextManifest: {},
    selectedSlideId: '',
    generationError: '',
    generationErrorSource: '',
    generationResponse: {},
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
    narrativePlan: normalizeNarrativePlan({}),
    narrativeRevisionDraft: {},
    slideGenerationQueue: normalizeSlideGenerationQueue([], outline),
    slideGenerationJob: {},
    visualGenerationBySlide: {},
    deckBrief: normalizeDeckBrief({}),
    contextManifest: {},
    selectedSlideId: '',
    generationError: '',
    generationErrorSource: '',
    generationResponse: normalized.generationResponse,
    activeRevisionTarget: {},
    directiveRevisionDraft: {},
    revisionGeneratingTarget: {},
    staleDirectivePageIds: [],
  })
}

export function resetPptPlanningToNarrativeReady(state = {}) {
  const normalized = createPptPlanningState(state)
  const outline = normalizePptOutline(normalized.outline)
  const narrativePlan = normalizeNarrativePlan(normalized.narrativePlan)
  if (!outline.length) return resetPptPlanningToMaterials(normalized)
  if (!narrativePlan.slideRoles.length) return resetPptPlanningToOutlineReady(normalized)
  return createPptPlanningState({
    ...normalized,
    currentStep: PPT_PLANNING_STEPS.NARRATIVE_READY,
    outline,
    spec: {
      ...normalized.spec,
      outline,
    },
    narrativePlan,
    slideGenerationQueue: normalizeSlideGenerationQueue([], outline),
    slideGenerationJob: {},
    visualGenerationBySlide: {},
    deckBrief: normalizeDeckBrief({}),
    selectedSlideId: '',
    generationError: '',
    generationErrorSource: '',
    activeRevisionTarget: {},
    directiveRevisionDraft: {},
    revisionGeneratingTarget: {},
    staleDirectivePageIds: [],
  })
}

export function getPptPromptActions(state = {}) {
  const normalized = createPptPlanningState(state)
  const hasOutline = normalizePptOutline(normalized.outline).length > 0
  const hasNarrativePlan = normalizeNarrativePlan(normalized.narrativePlan).slideRoles.length > 0
  const slides = cloneArray((normalized.deckBrief || {}).slides)
  const hasSlides = slides.length > 0
  const hasVisualSpecs = slides.some(slideHasVisualSpecs)
  const hasPendingVisuals = slides.some(slideHasPendingVisualSpecs)
  const failedPageNo = Number(normalized.slideGenerationJob.failedPageNo || 0)
    || Number((normalizeSlideGenerationQueue(normalized.slideGenerationQueue, normalized.outline).find((item) => item.status === 'failed') || {}).pageNo || 0)
    || 0

  if (!hasOutline) {
    return [{ id: 'generate-outline', label: '生成目录', event: 'generate-outline', primary: true }]
  }
  if (!hasNarrativePlan) {
    return [
      { id: 'generate-narrative-plan', label: '生成叙事方案', event: 'generate-narrative-plan', primary: true },
      { id: 'regenerate-outline', label: '重新生成目录', event: 'regenerate-outline', primary: false },
    ]
  }
  if (!hasSlides || failedPageNo) {
    return [
      {
        id: 'generate-slides',
        label: failedPageNo ? '继续逐页生成 brief' : '逐页生成 brief',
        event: 'generate-slides',
        primary: true,
      },
      { id: 'regenerate-narrative-plan', label: '重新生成叙事方案', event: 'regenerate-narrative-plan', primary: false },
    ]
  }
  if (hasVisualSpecs) {
    return [{
      id: hasPendingVisuals ? 'generate-visuals' : 'regenerate-visuals',
      label: hasPendingVisuals ? '批量生成可视化' : '重新生成可视化',
      event: 'generate-all-visuals',
      primary: true,
    }]
  }
  return [{ id: 'regenerate-slides', label: '重新逐页生成 brief', event: 'regenerate-slides', primary: true }]
}

export function applyNarrativePlanResponse(state = {}, response = {}) {
  const normalized = createPptPlanningState(state)
  const narrativePlan = normalizeNarrativePlan(response)
  const contextManifest = normalizeContextManifest(response.contextManifest || response.context_manifest)
  const sources = mergeSourceTransportManifest(normalized.sources, contextManifest)
  return createPptPlanningState({
    ...normalized,
    sources,
    contextManifest,
    currentStep: PPT_PLANNING_STEPS.NARRATIVE_READY,
    narrativePlan,
    narrativeRevisionDraft: {},
    slideGenerationQueue: normalizeSlideGenerationQueue([], normalized.outline),
    slideGenerationJob: {},
    visualGenerationBySlide: {},
    deckBrief: normalizeDeckBrief({}),
    selectedSlideId: '',
    generationError: '',
    generationErrorSource: '',
    generationResponse: createGenerationResponseSnapshot('narrative', response),
    staleDirectivePageIds: [],
    activeRevisionTarget: {},
    directiveRevisionDraft: {},
  })
}

export function applyDeckBriefResponse(state = {}, response = {}) {
  const normalized = createPptPlanningState(state)
  const deckBrief = normalizeDeckBrief(response)
  const contextManifest = normalizeContextManifest(response.contextManifest || response.context_manifest)
  const sources = mergeSourceTransportManifest(normalized.sources, contextManifest)
  return createPptPlanningState({
    ...normalized,
    sources,
    contextManifest,
    currentStep: PPT_PLANNING_STEPS.DIRECTIVE_DRAFT,
    deckBrief,
    visualGenerationBySlide: {},
    generationError: '',
    generationErrorSource: '',
    generationResponse: createGenerationResponseSnapshot('directive', response),
    staleDirectivePageIds: [],
    activeRevisionTarget: {},
    outlineRevisionDraft: {},
    directiveRevisionDraft: {},
  })
}

export function startSlideGenerationQueue(state = {}, options = {}) {
  const normalized = createPptPlanningState(state)
  const outline = normalizePptOutline(normalized.outline)
  const slidesByIndex = new Set(cloneArray((normalized.deckBrief || {}).slides).map((slide) => Number(slide.index || 0)).filter(Boolean))
  const existingQueue = normalizeSlideGenerationQueue(normalized.slideGenerationQueue, outline)
  const queue = outline.map((item) => {
    const existing = existingQueue.find((entry) => entry.pageNo === item.pageNo)
    if (slidesByIndex.has(item.pageNo)) {
      return normalizeSlideQueueItem({ ...existing, pageNo: item.pageNo, status: 'ready', error: '' }, item.pageNo)
    }
    return normalizeSlideQueueItem({
      ...existing,
      pageNo: item.pageNo,
      status: existing && existing.status === 'ready' ? 'ready' : 'pending',
      error: existing && existing.status === 'failed' ? existing.error : '',
    }, item.pageNo)
  })
  const firstPending = queue.find((item) => item.status !== 'ready')
  if (firstPending) {
    firstPending.status = 'generating'
    firstPending.error = ''
    firstPending.updatedAt = new Date().toISOString()
  }
  return createPptPlanningState({
    ...normalized,
    currentStep: firstPending ? PPT_PLANNING_STEPS.SLIDES_GENERATING : PPT_PLANNING_STEPS.DIRECTIVE_DRAFT,
    slideGenerationQueue: queue,
    slideGenerationJob: {
      active: !!firstPending,
      currentPageNo: firstPending ? firstPending.pageNo : 0,
      total: outline.length,
      failedPageNo: 0,
      error: '',
      startedAt: asText(options.startedAt || options.started_at) || new Date().toISOString(),
      completedAt: '',
    },
    generationError: '',
    generationErrorSource: '',
  })
}

export function applyGeneratedSlideBrief(state = {}, slide = {}) {
  const normalized = createPptPlanningState(state)
  const nextSlide = normalizeDeckSlideBrief(slide, Number(slide.index || 1) || 1)
  const slides = cloneArray((normalized.deckBrief || {}).slides)
  const index = findSlideIndex(slides, nextSlide)
  const nextSlides = index >= 0
    ? slides.map((item, itemIndex) => (itemIndex === index ? nextSlide : item))
    : [...slides, nextSlide].sort((a, b) => (Number(a.index || 0) || 0) - (Number(b.index || 0) || 0))
  const outline = normalizePptOutline(normalized.outline)
  const queue = normalizeSlideGenerationQueue(normalized.slideGenerationQueue, outline).map((item) => (
    item.pageNo === nextSlide.index
      ? { ...item, status: 'ready', error: '', updatedAt: new Date().toISOString() }
      : item
  ))
  const nextPending = queue.find((item) => item.status !== 'ready')
  if (nextPending) {
    nextPending.status = 'generating'
    nextPending.error = ''
    nextPending.updatedAt = new Date().toISOString()
  }
  return createPptPlanningState({
    ...normalized,
    currentStep: nextPending ? PPT_PLANNING_STEPS.SLIDES_GENERATING : PPT_PLANNING_STEPS.DIRECTIVE_DRAFT,
    deckBrief: {
      ...normalizeDeckBrief(normalized.deckBrief),
      slides: nextSlides,
    },
    selectedSlideId: normalized.selectedSlideId || asText(nextSlide.id),
    slideGenerationQueue: queue,
    slideGenerationJob: {
      ...normalizeSlideGenerationJob(normalized.slideGenerationJob),
      active: !!nextPending,
      currentPageNo: nextPending ? nextPending.pageNo : 0,
      total: outline.length,
      completedAt: nextPending ? '' : new Date().toISOString(),
    },
    visualGenerationBySlide: {
      ...normalized.visualGenerationBySlide,
      [slideVisualStatusKey(nextSlide.index)]: normalizeVisualGenerationStatus({ status: 'idle' }),
    },
    generationError: '',
    generationErrorSource: '',
    generationResponse: createGenerationResponseSnapshot('slides', { slides: nextSlides }),
    staleDirectivePageIds: normalized.staleDirectivePageIds.filter((item) => item !== String(nextSlide.index)),
  })
}

export function buildPptVisualArtifactsPayload(state = {}, slide = {}, context = {}) {
  const normalized = createPptPlanningState(state)
  const target = normalizeDeckSlideBrief(slide, Number(slide.index || slide.pageNo || slide.page_no || 1) || 1)
  const manifest = getPptSourceDeliveryManifest(normalized)
  const sources = cloneArray(manifest.deliverableSources).map(sourceForPptRequest)
  const current = cloneObject(context.current)
  return {
    slide_index: Number(target.index || 1) || 1,
    visual_specs: cloneArray(target.visualSpecs).map((item) => cloneObject(item)),
    source_ids: uniqueText([
      ...manifest.deliverableSourceIds,
      ...sourceIdsForSlide(target),
    ]),
    existing_assets: cloneArray(
      current.visual_snapshots
      || current.visualSnapshots
      || current.visual_assets
      || current.visualAssets,
    ).map((item) => cloneObject(item)),
    metric_context: metricContextForVisualPayload(sources),
  }
}

export function startPptVisualArtifactsGeneration(state = {}, slideIndex = 0) {
  const normalized = createPptPlanningState(state)
  const key = slideVisualStatusKey(slideIndex)
  if (!key || key === '0') return normalized
  return createPptPlanningState({
    ...normalized,
    visualGenerationBySlide: {
      ...normalized.visualGenerationBySlide,
      [key]: normalizeVisualGenerationStatus({ status: 'generating', updatedAt: new Date().toISOString() }),
    },
  })
}

export function applyPptVisualArtifactsResponse(state = {}, response = {}) {
  const normalized = createPptPlanningState(state)
  const slideIndex = Number(response.slideIndex || response.slide_index || 0) || 0
  if (!slideIndex) return normalized
  const incomingArtifacts = cloneArray(response.visualArtifacts || response.visual_artifacts).map((item) => cloneObject(item))
  const nextSlides = cloneArray((normalized.deckBrief || {}).slides).map((slide) => {
    if (Number(slide.index || 0) !== slideIndex) return slide
    const incomingKeys = new Set(incomingArtifacts.map(artifactKey).filter(Boolean))
    const retained = cloneArray(slide.visualArtifacts).filter((artifact) => {
      const key = artifactKey(artifact)
      return key && !incomingKeys.has(key)
    })
    return {
      ...slide,
      visualArtifacts: [...retained, ...incomingArtifacts],
    }
  })
  const allVisualsReady = nextSlides.some(slideHasVisualSpecs) && !nextSlides.some(slideHasPendingVisualSpecs)
  return createPptPlanningState({
    ...normalized,
    currentStep: allVisualsReady ? PPT_PLANNING_STEPS.VISUALS_READY : normalized.currentStep,
    deckBrief: {
      ...normalizeDeckBrief(normalized.deckBrief),
      slides: nextSlides,
    },
    visualGenerationBySlide: {
      ...normalized.visualGenerationBySlide,
      [slideVisualStatusKey(slideIndex)]: normalizeVisualGenerationStatus({ status: 'ready', updatedAt: new Date().toISOString() }),
    },
  })
}

export function failPptVisualArtifacts(state = {}, slideIndex = 0, error = '') {
  const normalized = createPptPlanningState(state)
  const key = slideVisualStatusKey(slideIndex)
  if (!key || key === '0') return normalized
  return createPptPlanningState({
    ...normalized,
    visualGenerationBySlide: {
      ...normalized.visualGenerationBySlide,
      [key]: normalizeVisualGenerationStatus({
        status: 'failed',
        error: asText(error && error.message ? error.message : error) || 'ppt_visual_artifact_failed',
        updatedAt: new Date().toISOString(),
      }),
    },
  })
}

export function failSlideGenerationQueue(state = {}, pageNo = 0, error = '') {
  const normalized = createPptPlanningState(state)
  const failedPageNo = Number(pageNo || 0) || Number(normalized.slideGenerationJob.currentPageNo || 0) || 0
  const message = asText(error && error.message ? error.message : error) || 'ppt_slide_generation_failed'
  const queue = normalizeSlideGenerationQueue(normalized.slideGenerationQueue, normalized.outline).map((item) => (
    item.pageNo === failedPageNo
      ? { ...item, status: 'failed', error: message, updatedAt: new Date().toISOString() }
      : item.status === 'generating'
        ? { ...item, status: 'pending' }
        : item
  ))
  return createPptPlanningState({
    ...normalized,
    currentStep: cloneArray((normalized.deckBrief || {}).slides).length ? PPT_PLANNING_STEPS.DIRECTIVE_DRAFT : PPT_PLANNING_STEPS.NARRATIVE_READY,
    slideGenerationQueue: queue,
    slideGenerationJob: {
      ...normalizeSlideGenerationJob(normalized.slideGenerationJob),
      active: false,
      currentPageNo: 0,
      failedPageNo,
      error: message,
      completedAt: new Date().toISOString(),
    },
    generationError: message,
    generationErrorSource: 'slides',
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

export function setPptGenerationError(state = {}, error = '', source = '', options = {}) {
  const normalized = createPptPlanningState(state)
  const hasOutline = cloneArray(normalized.outline).length > 0
  const generationResponse = options && (options.generationResponse || options.generation_response)
    ? normalizeGenerationResponse(options.generationResponse || options.generation_response)
    : normalized.generationResponse
  return createPptPlanningState({
    ...normalized,
    currentStep: hasOutline ? PPT_PLANNING_STEPS.OUTLINE_READY : PPT_PLANNING_STEPS.MATERIALS,
    generationError: asText(error) || 'ppt_generation_failed',
    generationErrorSource: normalizePptErrorSource(source),
    generationResponse,
    dataPackageGenerating: false,
    sourceRefreshing: false,
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

export function setPptSourceRefreshing(state = {}, refreshing = true) {
  return createPptPlanningState({
    ...createPptPlanningState(state),
    sourceRefreshing: !!refreshing,
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
      status: ['generating', 'failed'].includes(asText(item.status)) ? asText(item.status) : 'pending',
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
    sourceGroups: reconcilePptSourceGroups(normalized.sourceGroups, sources, normalized.ungroupedSourceIds),
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
  const ungroupedSourceIds = uniqueText([...normalized.ungroupedSourceIds, ...missingSourceIds])
  const sourceGroups = reconcilePptSourceGroups(groups, normalized.sources, ungroupedSourceIds)
  return createPptPlanningState({
    ...normalized,
    sourceGroups,
    ungroupedSourceIds,
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
  const targetGroupId = asText(groupId)
  if (!normalized.sources.some((source) => source.id === id)) return normalized
  const sourceGroups = normalized.sourceGroups.map((group) => ({
    ...group,
    sourceIds: group.sourceIds.filter((item) => item !== id),
  })).filter((group) => group.sourceIds.length || group.id === targetGroupId)
  const ungroupedSourceIds = normalized.ungroupedSourceIds.filter((item) => item !== id)
  if (!targetGroupId || targetGroupId === PPT_UNCATEGORIZED_GROUP_ID) {
    return createPptPlanningState({
      ...normalized,
      sourceGroups,
      ungroupedSourceIds: uniqueText([...ungroupedSourceIds, id]),
    })
  }
  let foundTarget = false
  const movedGroups = sourceGroups.map((group) => {
    if (group.id !== targetGroupId) return group
    foundTarget = true
    return { ...group, sourceIds: uniqueText([...group.sourceIds, id]), collapsed: false }
  })
  const nextGroups = foundTarget
    ? movedGroups
    : ensureGroupForSourceIds(movedGroups, targetGroupId, [id])
  return createPptPlanningState({
    ...normalized,
    sourceGroups: nextGroups,
    ungroupedSourceIds,
  })
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
    ungroupedSourceIds: normalized.ungroupedSourceIds.filter((item) => item !== id),
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
  return createPptPlanningState({
    ...normalized,
    sourceGroups: remainingGroups,
    ungroupedSourceIds: uniqueText([...normalized.ungroupedSourceIds, ...targetGroup.sourceIds]),
  })
}

export function mergePptPlanningSources(state = {}, nextSources = []) {
  const normalized = createPptPlanningState(state)
  const previousById = new Map(normalized.sources.map((item) => [asText(item.id), item]))
  const removedSet = new Set(normalized.removedSourceIds)
  const normalizedNext = normalizeSources(nextSources).filter((item) => !removedSet.has(asText(item.id)))
  const mergedIds = new Set(normalizedNext.map((item) => item.id))
  const retainedSources = cloneArray(normalized.sources)
    .filter((item) => isRetainedUserSource(item) && !mergedIds.has(asText(item.id)))
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
    sourceGroups: reconcilePptSourceGroups(normalized.sourceGroups, sources, normalized.ungroupedSourceIds),
    removedSourceIds: normalized.removedSourceIds,
    outline: normalized.outline,
    spec: {
      ...normalized.spec,
      sourceIds: getReadySelectedSourceIds(sources),
    },
  })
}

export function upsertPptDocumentSource(state = {}, document = {}, options = {}) {
  const normalized = createPptPlanningState(state)
  const documentId = asText(document.id || document.document_id || document.documentId)
  const sourceId = asText(options.sourceId) || (documentId ? `document:${documentId}` : '')
  if (!sourceId) return normalized
  const status = asText(options.status || document.status) || 'pending'
  const ready = status === 'ready'
  const title = asText(document.title || document.file_name || document.fileName || options.title) || '文档资料'
  const label = asText(options.label)
    || (ready
      ? asText(options.count) ? `PageIndex 章节 ${Number(options.count) || 0} 个` : 'PageIndex 已生成'
      : status === 'generating' ? '整理中' : '待生成')
  const previousById = new Map(normalized.sources.map((item) => [asText(item.id), item]))
  const previous = previousById.get(sourceId)
  const indexPreview = cloneArray(options.documentIndexPreview || options.document_index_preview || (previous && previous.meta && previous.meta.document_index_preview))
  const evidence = ready ? indexPreview.slice(0, 40).map((node, index) => {
    const item = cloneObject(node)
    return {
      source_id: sourceId,
      sourceId,
      source_title: title,
      sourceTitle: title,
      type: 'pageindex_node',
      title: asText(item.title) || `文档章节 ${index + 1}`,
      text: asText(item.summary || item.text),
      citation: item.page_start || item.pageStart ? `PageIndex p.${item.page_start || item.pageStart}` : '',
      payload: {
        node_id: asText(item.node_id || item.nodeId),
        parent_node_id: asText(item.parent_node_id || item.parentNodeId),
        level: item.level,
        page_start: item.page_start || item.pageStart,
        page_end: item.page_end || item.pageEnd,
      },
    }
  }).filter((item) => asText(item.text)) : []
  const aiPayload = {
    version: 'ppt_ai_input_block_v1',
    source_id: sourceId,
    sourceId,
    title,
    source_kind: 'document',
    sourceKind: 'document',
    included: evidence.length ? ['evidence'] : [],
    scope: null,
    metrics: [],
    metric_gaps: [],
    metricGaps: [],
    evidence,
    visual_specs: [],
    visualSpecs: [],
    excluded: [{ type: 'document_full_text', reason: '不传文档全文，只传 PageIndex 节点/章节摘要。', count: Number(options.count || indexPreview.length || 0) || 0 }],
    counts: { scope: 0, metrics: 0, metric_gaps: 0, evidence: evidence.length, visual_specs: 0 },
    policy: '文档来源只通过 PageIndex 节点/章节摘要进入 evidence；不从全文临时抽取。',
  }
  const transport = ready ? createPptTransportFromAiPayload(aiPayload) : cloneObject(previous && previous.meta && previous.meta.transport)
  const nextSource = normalizePptSource({
    ...(previous || {}),
    id: sourceId,
    type: 'document',
    title,
    status,
    selected: ready ? (previous ? !!previous.selected : true) : false,
    meta: {
      ...cloneObject(previous && previous.meta),
      label,
      sourceKind: 'document',
      documentId,
      fileName: asText(document.file_name || document.fileName),
      count: Number(options.count ?? (previous && previous.meta && previous.meta.count) ?? 0) || 0,
      document_index_preview: indexPreview,
      aiPayload: ready ? aiPayload : cloneObject(previous && previous.meta && previous.meta.aiPayload),
      ai_payload: ready ? aiPayload : cloneObject(previous && previous.meta && previous.meta.ai_payload),
      transport,
    },
  })
  const sources = normalized.sources.some((source) => asText(source.id) === sourceId)
    ? normalized.sources.map((source) => (asText(source.id) === sourceId ? nextSource : source))
    : [...normalized.sources, nextSource]
  return createPptPlanningState({
    ...normalized,
    sources,
    sourceGroups: reconcilePptSourceGroups(normalized.sourceGroups, sources, normalized.ungroupedSourceIds),
    spec: syncSpecSourceIds(normalized, sources),
    generationError: '',
    generationErrorSource: '',
  })
}

export function addPptDataPackageSource(state = {}, response = {}) {
  const normalized = createPptPlanningState(state)
  let packageSource = normalizePptSource(response.source || response)
  if (!packageSource.id) return createPptPlanningState({ ...normalized, dataPackageGenerating: false })
  const packageMeta = cloneObject(packageSource.meta)
  const existingPayload = cloneObject(packageMeta.aiPayload || packageMeta.ai_payload)
  const aiPayload = existingPayload.version === 'ppt_ai_input_block_v1'
    ? existingPayload
    : packageAiPayloadFromSource(packageSource)
  packageSource = normalizePptSource({
    ...packageSource,
    meta: {
      ...packageMeta,
      aiPayload,
      ai_payload: aiPayload,
      transport: createPptTransportFromAiPayload(aiPayload),
    },
  })
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
    sourceGroups: reconcilePptSourceGroups(normalized.sourceGroups, sources, normalized.ungroupedSourceIds),
    removedSourceIds: normalized.removedSourceIds,
    spec: {
      ...normalized.spec,
      sourceIds: getReadySelectedSourceIds(sources),
    },
    dataPackageGenerating: false,
    sourceRefreshing: false,
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
  const manifest = getPptSourceDeliveryManifest(normalized)
  const sourceIds = manifest.deliverableSourceIds
  const sources = cloneArray(manifest.deliverableSources)
    .map(sourceForPptRequest)
  return {
    area_id: asText(context.areaId || context.area_id),
    source_ids: sourceIds,
    topic: asText(normalized.spec.topic),
    audience: asText(normalized.spec.audience),
    deck_type: asText(normalized.spec.deckType),
    page_count: Number(normalized.spec.pageCount || 15),
    research_enabled: !!normalized.spec.researchEnabled,
    sources,
  }
}

export function buildDeckBriefPayload(state = {}, context = {}) {
  const normalized = createPptPlanningState(state)
  const manifest = getPptSourceDeliveryManifest(normalized)
  const sourceIds = manifest.deliverableSourceIds
  const sources = cloneArray(manifest.deliverableSources)
    .map(sourceForPptRequest)
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
    sources,
    current: cloneObject(context.current),
    topic: asText(normalized.spec.topic),
    audience: asText(normalized.spec.audience),
    deck_type: asText(normalized.spec.deckType),
    page_count: Number(normalized.spec.pageCount || 15),
    research_enabled: !!normalized.spec.researchEnabled,
  }
}

function narrativePlanForRequest(plan = {}) {
  const normalized = normalizeNarrativePlan(plan)
  return {
    storyline: normalized.storyline,
    style_guide: normalized.styleGuide,
    evidence_strategy: normalized.evidenceStrategy,
    chart_strategy: normalized.chartStrategy,
    slide_roles: normalized.slideRoles.map((role) => ({
      page_no: role.pageNo,
      role: role.role,
      objective: role.objective,
      evidence_focus: cloneArray(role.evidenceFocus),
      visual_direction: role.visualDirection,
      chart_intent: role.chartIntent,
      transition_note: role.transitionNote,
    })),
    missing_inputs: cloneArray(normalized.missingInputs),
  }
}

export function buildNarrativePlanPayload(state = {}, context = {}) {
  const normalized = createPptPlanningState(state)
  return {
    ...buildDeckBriefPayload(normalized, context),
    outline: normalizePptOutline(normalized.outline).map((item) => ({
      id: item.id,
      page_no: item.pageNo,
      theme: item.theme,
      purpose: item.purpose,
    })),
  }
}

export function buildPptOutlineSectionPayload(state = {}, target = {}, revisionNote = '', context = {}) {
  const normalized = createPptPlanningState(state)
  const sourceIds = getPptSourceDeliveryManifest(normalized).deliverableSourceIds
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
  const sourceIds = getPptSourceDeliveryManifest(normalized).deliverableSourceIds
  const slides = cloneArray((normalized.deckBrief || {}).slides)
  const targetIndex = findSlideIndex(slides, target)
  const requestedIndex = Number(target.index || target.pageNo || target.page_no || 0) || 0
  const outlineItem = normalized.outline.find((item) => Number(item.pageNo || 0) === Number((targetIndex >= 0 ? slides[targetIndex].index : requestedIndex) || 0)) || null
  const targetItem = targetIndex >= 0
    ? slides[targetIndex]
    : {
        index: requestedIndex || Number(outlineItem && outlineItem.pageNo) || 1,
        title: asText(target.title) || asText(outlineItem && outlineItem.theme) || `页面 ${requestedIndex || 1}`,
        purpose: asText(target.purpose) || asText(outlineItem && outlineItem.purpose),
        keyMessage: '',
        visualPlan: '',
        requiredSources: [],
        metricClaims: [],
        metricGaps: [],
        visualSpecs: [],
        visualArtifacts: [],
      }
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
      metric_claims: cloneArray(item.metricClaims),
      metric_gaps: cloneArray(item.metricGaps),
      visual_specs: cloneArray(item.visualSpecs),
      visual_artifacts: cloneArray(item.visualArtifacts),
    })),
    target: {
      index: targetItem.index,
      title: targetItem.title,
      purpose: targetItem.purpose,
      key_message: targetItem.keyMessage,
      visual_plan: targetItem.visualPlan,
      required_sources: cloneArray(targetItem.requiredSources),
      metric_claims: cloneArray(targetItem.metricClaims),
      metric_gaps: cloneArray(targetItem.metricGaps),
      visual_specs: cloneArray(targetItem.visualSpecs),
      visual_artifacts: cloneArray(targetItem.visualArtifacts),
    },
    outline_item: outlineItem ? {
      id: outlineItem.id,
      page_no: outlineItem.pageNo,
      theme: outlineItem.theme,
      purpose: outlineItem.purpose,
    } : null,
    narrative_plan: narrativePlanForRequest(normalized.narrativePlan),
    revision_note: asText(revisionNote),
    source_ids: sourceIds,
  }
}
