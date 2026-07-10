import {
  asText,
  canonicalPptSourceKind,
  cloneArray,
  cloneObject,
} from './base.js'
import {
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
import {
  createDefaultPptSourceGroups,
  ensureGroupForSourceIds,
  getReadySelectedSourceIds,
  normalizePptSourceGroup,
  normalizeSources,
  PPT_UNCATEGORIZED_GROUP_ID,
  reconcilePptSourceGroups,
  simpleHash,
  sourceIdsFromSources,
  syncSpecSourceIds,
} from './source-groups.js'
import {
  appendGenerationEvent,
  createGenerationResponseSnapshot,
  generationReadyStepForState,
  generationStepForType,
  isCurrentGenerationJob,
  normalizeGenerationEvents,
  normalizeGenerationJob,
  normalizeGenerationJobType,
  normalizeGenerationResponse,
  PPT_GENERATION_TERMINAL_PHASES,
  summarizeGenerationResponse,
} from './generation-job.js'
import {
  evidenceNodesFromAiPayload,
  evidenceNodesFromEvidenceItems,
} from '../analysis-sources/evidence-nodes.js'
import {
  aiPayloadFromSource,
  sourceHasDeliverableAiPayload,
} from './source-health.js'
import {
  createAggregateSourceRefreshPlaceholder,
  isPptSourceRefreshPlaceholder,
  isRefreshableBackendPptSource,
  sourceRefreshPlaceholderFromSource,
} from './source-refresh.js'
import { createPackageAiPayload } from './source-payloads.js'

export { getPptSourceHealth } from './source-health.js'

function cloneJsonValue(value) {
  if (value === undefined) return null
  try {
    return JSON.parse(JSON.stringify(value))
  } catch (_) {
    if (Array.isArray(value)) return value.map((item) => cloneJsonValue(item))
    if (value && typeof value === 'object') return { ...value }
    return value ?? null
  }
}

const PPT_ERROR_SOURCE_LABELS = new Set([
  'source_refresh',
  'source_grouping',
  'data_package',
  'outline',
  'narrative',
  'slides',
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

function normalizeSlideQueueItem(value = {}, fallbackPageNo = 1) {
  const item = cloneObject(value)
  const pageNo = Number(item.pageNo || item.page_no || item.index || fallbackPageNo) || fallbackPageNo
  const status = asText(item.status)
  const requestId = asText(item.requestId || item.request_id)
  const attempt = Number(item.attempt || 0) || 0
  return {
    pageNo,
    status: [
      'pending',
      'requesting',
      'response_received',
      'applying',
      'ready',
      'failed',
      'timed_out',
      'stale',
      'generating',
      'repairing',
      'retrying',
    ].includes(status) ? status : 'pending',
    requestId,
    attempt,
    startedAt: asText(item.startedAt || item.started_at),
    responseReceivedAt: asText(item.responseReceivedAt || item.response_received_at),
    appliedAt: asText(item.appliedAt || item.applied_at),
    completedAt: asText(item.completedAt || item.completed_at),
    error: asText(item.error),
    errorKind: asText(item.errorKind || item.error_kind),
    responseSummary: cloneObject(item.responseSummary || item.response_summary),
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
  const status = asText(job.status)
  return {
    id: asText(job.id),
    status: ['idle', 'running', 'paused', 'failed', 'completed'].includes(status) ? status : (job.active ? 'running' : 'idle'),
    active: !!job.active,
    currentPageNo: Number(job.currentPageNo || job.current_page_no || 0) || 0,
    total: Number(job.total || 0) || 0,
    lastCompletedPageNo: Number(job.lastCompletedPageNo || job.last_completed_page_no || 0) || 0,
    failedPageNo: Number(job.failedPageNo || job.failed_page_no || 0) || 0,
    error: asText(job.error),
    startedAt: asText(job.startedAt || job.started_at),
    updatedAt: asText(job.updatedAt || job.updated_at),
    activePageStartedAt: asText(job.activePageStartedAt || job.active_page_started_at),
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

function sourceForPptRequest(source = {}) {
  const meta = cloneObject(source.meta)
  const aiPayload = aiPayloadFromSource(source)
  const sourceKind = canonicalPptSourceKind(source.source_kind || source.sourceKind || meta.sourceKind, source.id, source.type)
  return normalizePptSource({
    id: source.id,
    type: source.type,
    title: source.title,
    status: source.status,
    selected: source.selected,
    source_kind: sourceKind,
    summary: asText(source.summary || meta.label),
    evidence_count: Number(source.evidence_count ?? source.evidenceCount ?? 0) || 0,
    locator_summary: asText(source.locator_summary || source.locatorSummary),
    availability: asText(source.availability),
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

export function buildPptSourceFullExportPayload(state = {}, sourceId = '', options = {}) {
  const normalized = createPptPlanningState(state)
  const id = asText(sourceId)
  const source = normalized.sources.find((item) => asText(item && item.id) === id)
  if (!source) return null
  const meta = cloneObject(source.meta)
  const aiPayload = aiPayloadFromSource(source)
  const transport = aiPayload.version ? createPptTransportFromAiPayload(aiPayload) : cloneObject(meta.transport)
  const group = normalized.sourceGroups.find((item) => cloneArray(item.sourceIds).map((sourceIdItem) => asText(sourceIdItem)).includes(id))
  const exportedAt = asText(options.exportedAt || options.exported_at) || new Date().toISOString()
  return {
    export_type: 'ppt_source_full_export',
    version: 'v1',
    exported_at: exportedAt,
    source: sourceForPptRequest(source),
    group: group ? {
      id: asText(group.id),
      title: asText(group.title),
      emoji: asText(group.emoji),
    } : null,
    ai_payload: cloneJsonValue(aiPayload),
    transport: cloneJsonValue(transport),
    evidence_nodes: cloneJsonValue(evidenceNodesFromAiPayload(aiPayload)),
    full_source: cloneJsonValue(source),
  }
}

export function buildPptAllSourcesFullExportPayload(state = {}, options = {}) {
  const normalized = createPptPlanningState(state)
  const exportedAt = asText(options.exportedAt || options.exported_at) || new Date().toISOString()
  const sources = normalized.sources
    .map((source) => buildPptSourceFullExportPayload(normalized, source && source.id, { exportedAt }))
    .filter(Boolean)
  return {
    export_type: 'ppt_all_sources_full_export',
    version: 'v1',
    exported_at: exportedAt,
    counts: {
      total: normalized.sources.length,
      ready: normalized.sources.filter((source) => asText(source.status) === 'ready').length,
      selected: normalized.sources.filter((source) => !!source.selected).length,
      exported: sources.length,
    },
    source_groups: cloneJsonValue(normalized.sourceGroups),
    sources,
  }
}

export function buildPptSourceFullExportFilename(source = {}) {
  const title = asText(source && source.title) || asText(source && source.id) || 'ppt-source'
  const safeTitle = title
    .replace(/[\\/:*?"<>|]+/g, '_')
    .replace(/\s+/g, '_')
    .slice(0, 80)
    || 'ppt-source'
  return `${safeTitle}_full_export.json`
}

export function buildPptAllSourcesFullExportFilename() {
  return 'ppt_sources_full_export.json'
}

function normalizeStaleDirectivePageIds(value = []) {
  return uniqueText(value).map((item) => String(Number(item) || item)).filter(Boolean)
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
  const sourceKind = canonicalPptSourceKind(source.source_kind || source.sourceKind || (source.meta && source.meta.sourceKind), source.id)
  const sourceId = asText(source.id)
  return ['package', 'document', 'image', 'web', 'database'].includes(sourceKind)
    || sourceId.startsWith('document:')
    || sourceId.startsWith('image:')
    || sourceId.startsWith('database:')
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
  const ungroupedSourceIds = uniqueText(seed.ungroupedSourceIds || seed.ungrouped_source_ids)
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
  const hasSlideGenerationQueue = Object.prototype.hasOwnProperty.call(seed, 'slideGenerationQueue')
    || Object.prototype.hasOwnProperty.call(seed, 'slide_generation_queue')
  const rawSlideGenerationQueue = seed.slideGenerationQueue || seed.slide_generation_queue || []
  const slideGenerationQueue = hasSlideGenerationQueue
    ? (cloneArray(rawSlideGenerationQueue).length ? normalizeSlideGenerationQueue(rawSlideGenerationQueue, outline) : [])
    : []
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
    briefJobId: asText(seed.briefJobId || seed.brief_job_id),
    briefJobStatus: asText(seed.briefJobStatus || seed.brief_job_status || 'idle'),
    briefJobProgress: cloneObject(seed.briefJobProgress || seed.brief_job_progress),
    briefJobError: cloneObject(seed.briefJobError || seed.brief_job_error),
    briefJobUpdatedAt: asText(seed.briefJobUpdatedAt || seed.brief_job_updated_at),
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

function pushUniqueMetricContextItem(items = [], item = {}, keyName = 'metric_id') {
  const next = cloneObject(item)
  const key = asText(next[keyName] || next.metricId || next.gap_id || next.gapId || next.text)
  if (!key) {
    items.push(next)
    return
  }
  const existingIndex = items.findIndex((current) => asText(current[keyName] || current.metricId || current.gap_id || current.gapId || current.text) === key)
  if (existingIndex < 0) {
    items.push(next)
    return
  }
  const current = cloneObject(items[existingIndex])
  if (asText(current.status) !== 'ready' && asText(next.status) === 'ready') {
    items[existingIndex] = next
  }
}

function mergeMetricContextPayload(metrics = [], metricGaps = [], payload = {}) {
  cloneArray(payload.metrics).forEach((metric) => pushUniqueMetricContextItem(metrics, metric, 'metric_id'))
  cloneArray(payload.metric_gaps || payload.metricGaps).forEach((gap) => pushUniqueMetricContextItem(metricGaps, gap, 'metric_id'))
}

function metricContextForVisualPayload(sources = [], current = {}) {
  const metrics = []
  const metricGaps = []
  cloneArray(sources).forEach((source) => {
    mergeMetricContextPayload(metrics, metricGaps, aiPayloadFromSource(source))
  })
  mergeMetricContextPayload(metrics, metricGaps, cloneObject(current.metrics))
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
    slideGenerationQueue: [],
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

export function startPptDeckBriefJob(state = {}, options = {}) {
  const normalized = createPptPlanningState(state)
  const jobId = asText(options.jobId || options.job_id)
  if (!jobId) return normalized
  const generationJob = appendGenerationEvent({
    id: jobId,
    type: 'directive',
    phase: 'requesting',
    tabId: asText(options.tabId || options.tab_id || ''),
    startedAt: new Date().toISOString(),
    completedAt: '',
    error: '',
    responseSummary: {},
    events: [],
  }, 'requesting', { jobId, type: 'directive' })
  return createPptPlanningState({
    ...normalized,
    briefJobId: jobId,
    briefJobStatus: 'queued',
    briefJobProgress: { stage: 'queued', message: 'brief 任务已创建' },
    briefJobError: {},
    briefJobUpdatedAt: asText(options.updatedAt || options.updated_at) || new Date().toISOString(),
    currentStep: PPT_PLANNING_STEPS.SLIDES_GENERATING,
    generationJob,
  })
}

export function updatePptDeckBriefJobState(state = {}, payload = {}) {
  const normalized = createPptPlanningState(state)
  const jobId = asText(payload.jobId || payload.job_id || normalized.briefJobId)
  if (!jobId) return normalized
  const status = asText(payload.status || 'queued') || 'queued'
  const progress = cloneObject(payload.progress || {})
  const error = cloneObject(payload.error || {})
  const job = normalizeGenerationJob(normalized.generationJob)
  const result = payload.result
  const completedBrief = status === 'completed' && result ? normalizeDeckBrief(result) : null
  const completedSlideCount = completedBrief ? cloneArray(completedBrief.slides).length : 0
  const completedJob = status === 'completed'
    ? appendGenerationEvent({
        ...job,
        id: job.id || jobId,
        type: 'directive',
        phase: 'ready',
        completedAt: new Date().toISOString(),
        error: '',
        responseSummary: { ...summarizeGenerationResponse('directive', result || {}), slideCount: completedSlideCount },
      }, 'ready', { jobId, slideCount: completedSlideCount })
    : status === 'failed'
      ? appendGenerationEvent({
          ...job,
          id: job.id || jobId,
          type: 'directive',
          phase: 'failed',
          completedAt: new Date().toISOString(),
          error: asText(error.message || error.code) || 'brief 生成失败',
          responseSummary: job.responseSummary,
        }, 'failed', { jobId, error: asText(error.code || error.message) || 'brief 生成失败' })
      : job
  return createPptPlanningState({
    ...normalized,
    briefJobId: jobId,
    briefJobStatus: status,
    briefJobProgress: progress,
    briefJobError: error,
    briefJobUpdatedAt: asText(payload.updatedAt || payload.updated_at) || new Date().toISOString(),
    ...(status === 'completed' && completedBrief
      ? {
          deckBrief: completedBrief,
          currentStep: PPT_PLANNING_STEPS.DIRECTIVE_DRAFT,
          generationError: '',
          generationErrorSource: '',
          generationJob: completedJob,
          slideGenerationQueue: [],
          slideGenerationJob: {},
        }
      : {}),
    ...(status === 'failed'
      ? {
          generationError: asText(error.message || error.code || 'brief 生成失败'),
          generationErrorSource: 'directive',
          generationJob: completedJob,
        }
      : {}),
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

export function applyDirectiveResponseAndMarkReady(state = {}, requestId = '', response = {}) {
  const normalized = createPptPlanningState(state)
  const job = normalizeGenerationJob(normalized.generationJob)
  const summary = summarizeGenerationResponse('directive', response)
  if (!isCurrentGenerationJob(normalized, requestId)) {
    const message = 'brief 已返回但请求已不是当前任务，请重新生成 brief。'
    return createPptPlanningState({
      ...normalized,
      generationError: message,
      generationErrorSource: 'directive',
      generationResponse: createGenerationResponseSnapshot('directive', response),
      generationJob: appendGenerationEvent({
        ...job,
        phase: 'failed',
        completedAt: new Date().toISOString(),
        error: message,
        responseSummary: summary,
      }, 'stale_response_ignored', {
        requestId: asText(requestId),
        currentRequestId: job.id,
        slideCount: summary.slideCount,
      }),
    })
  }
  const responseReceivedJob = appendGenerationEvent({
    ...job,
    phase: 'response_received',
    responseSummary: summary,
  }, 'response_received', summary)
  const applyingJob = appendGenerationEvent({
    ...responseReceivedJob,
    phase: 'applying',
  }, 'applying', { type: 'directive' })
  try {
    const baseState = createPptPlanningState({
      ...normalized,
      generationJob: applyingJob,
      generationResponse: createGenerationResponseSnapshot('directive', response),
    })
    const applied = applyDeckBriefResponse(baseState, response)
    const slideCount = cloneArray((applied.deckBrief || {}).slides).length
    if (!slideCount) {
      const message = 'brief 已返回但未写入前端状态，请重试。'
      return createPptPlanningState({
        ...baseState,
        currentStep: generationReadyStepForState(normalized, 'directive'),
        generationError: message,
        generationErrorSource: 'directive',
        generationJob: appendGenerationEvent({
          ...applyingJob,
          phase: 'failed',
          completedAt: new Date().toISOString(),
          error: message,
          responseSummary: summary,
        }, 'directive_writeback_missing', { requestId: asText(requestId), slideCount: summary.slideCount }),
      })
    }
    return createPptPlanningState({
      ...applied,
      slideGenerationQueue: [],
      slideGenerationJob: {},
      generationJob: appendGenerationEvent({
        ...applyingJob,
        phase: 'ready',
        completedAt: new Date().toISOString(),
        error: '',
        responseSummary: { ...summary, slideCount },
      }, 'ready', { ...summary, slideCount }),
    })
  } catch (error) {
    const message = `brief 已返回但前端应用失败：${error && error.message ? error.message : String(error)}`
    return createPptPlanningState({
      ...normalized,
      currentStep: generationReadyStepForState(normalized, 'directive'),
      generationError: message,
      generationErrorSource: 'directive',
      generationResponse: createGenerationResponseSnapshot('directive', response),
      generationJob: appendGenerationEvent({
        ...applyingJob,
        phase: 'failed',
        completedAt: new Date().toISOString(),
        error: message,
        responseSummary: summary,
      }, 'failed', { error: message, source: 'directive' }),
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
    slideGenerationQueue: [],
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
    slideGenerationQueue: [],
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

  if (!hasOutline) {
    return [{ id: 'generate-outline', label: '生成目录', event: 'generate-outline', primary: true }]
  }
  if (!hasNarrativePlan) {
    return [
      { id: 'generate-narrative-plan', label: '生成叙事方案', event: 'generate-narrative-plan', primary: true },
      { id: 'regenerate-outline', label: '重新生成目录', event: 'regenerate-outline', primary: false },
    ]
  }
  if (!hasSlides) {
    return [
      {
        id: 'generate-slides',
        label: '生成 brief',
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
  return [{ id: 'regenerate-slides', label: '重新生成 brief', event: 'regenerate-slides', primary: true }]
}

export function applyNarrativePlanResponse(state = {}, response = {}) {
  const normalized = createPptPlanningState(state)
  const narrativePlan = normalizeNarrativePlan(response)
  return createPptPlanningState({
    ...normalized,
    currentStep: PPT_PLANNING_STEPS.NARRATIVE_READY,
    narrativePlan,
    narrativeRevisionDraft: {},
    slideGenerationQueue: [],
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
    slideGenerationQueue: [],
    slideGenerationJob: {},
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
  return startSlideGenerationRun(state, options)
}

function activeSlideStatuses() {
  return new Set(['requesting', 'response_received', 'applying', 'generating', 'repairing', 'retrying'])
}

function resumableSlideStatuses() {
  return new Set(['pending', 'failed', 'timed_out', 'stale'])
}

function createSlideRunId() {
  return `ppt-slides-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function normalizeSlideRequestId(requestId = '') {
  return asText(requestId) || `ppt-slide-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function queueHasRequest(queue = [], pageNo = 0, requestId = '') {
  const id = asText(requestId)
  const page = Number(pageNo || 0) || 0
  const item = cloneArray(queue).find((entry) => Number(entry && entry.pageNo || 0) === page)
  return !!item && !!id && asText(item.requestId) === id
}

function slideQueueSummary(queue = []) {
  const normalized = cloneArray(queue).map((item) => normalizeSlideQueueItem(item))
  const ready = normalized.filter((item) => item.status === 'ready')
  const failed = normalized.find((item) => ['failed', 'timed_out', 'stale'].includes(item.status))
  const active = normalized.find((item) => activeSlideStatuses().has(item.status))
  return {
    readyCount: ready.length,
    lastCompletedPageNo: ready.reduce((max, item) => Math.max(max, Number(item.pageNo || 0) || 0), 0),
    failedPageNo: Number(failed && failed.pageNo || 0) || 0,
    currentPageNo: Number(active && active.pageNo || 0) || 0,
  }
}

function createSlidesGenerationJob(state = {}, queue = [], options = {}) {
  const normalized = createPptPlanningState(state)
  const previousJob = normalizeGenerationJob(normalized.generationJob)
  const now = asText(options.now) || new Date().toISOString()
  const jobId = asText(options.requestId || options.request_id) || createSlideRunId()
  const summary = slideQueueSummary(queue)
  const activePage = queue.find((item) => activeSlideStatuses().has(item.status))
  const failedPage = queue.find((item) => ['failed', 'timed_out', 'stale'].includes(item.status))
  const isCompleted = queue.length > 0 && queue.every((item) => item.status === 'ready')
  const previousEvents = previousJob.id && !PPT_GENERATION_TERMINAL_PHASES.has(previousJob.phase)
    ? appendGenerationEvent({ ...previousJob, phase: 'superseded', completedAt: now }, 'superseded', { byRequestId: jobId }).events
    : normalizeGenerationEvents(previousJob.events)
  const phase = failedPage ? 'failed' : isCompleted ? 'ready' : activePage ? 'requesting' : 'idle'
  return appendGenerationEvent({
    id: jobId,
    type: 'slides',
    phase,
    tabId: asText(options.tabId || options.tab_id),
    startedAt: asText(options.startedAt || options.started_at) || now,
    completedAt: failedPage || isCompleted ? now : '',
    error: asText(failedPage && failedPage.error),
    responseSummary: {
      slides: summary.readyCount,
      currentPageNo: Number(activePage && activePage.pageNo || 0) || 0,
      failedPageNo: Number(failedPage && failedPage.pageNo || 0) || 0,
    },
    events: previousEvents,
  }, 'started', { source: 'slides', total: queue.length, currentPageNo: Number(activePage && activePage.pageNo || 0) || 0 })
}

export function startSlideGenerationRun(state = {}, options = {}) {
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
  const now = new Date().toISOString()
  const firstRunnable = queue.find((item) => item.status !== 'ready')
  const generationJob = createSlidesGenerationJob(normalized, queue, { ...options, now })
  return createPptPlanningState({
    ...normalized,
    currentStep: firstRunnable ? PPT_PLANNING_STEPS.SLIDES_GENERATING : PPT_PLANNING_STEPS.DIRECTIVE_DRAFT,
    slideGenerationQueue: queue,
    slideGenerationJob: {
      id: generationJob.id,
      status: firstRunnable ? 'running' : 'completed',
      active: !!firstRunnable,
      currentPageNo: firstRunnable ? firstRunnable.pageNo : 0,
      total: outline.length,
      lastCompletedPageNo: slideQueueSummary(queue).lastCompletedPageNo,
      failedPageNo: 0,
      error: '',
      startedAt: asText(options.startedAt || options.started_at) || new Date().toISOString(),
      updatedAt: now,
      activePageStartedAt: '',
      completedAt: firstRunnable ? '' : now,
    },
    generationJob,
    generationError: '',
    generationErrorSource: '',
  })
}

export function markSlideGenerationPageActive(state = {}, pageNo = 0) {
  return markSlideRequestStarted(state, pageNo, normalizeSlideRequestId())
}

export function markSlideRequestStarted(state = {}, pageNo = 0, requestId = '') {
  const normalized = createPptPlanningState(state)
  const outline = normalizePptOutline(normalized.outline)
  const targetPageNo = Number(pageNo || 0) || 0
  if (!targetPageNo) return normalized
  const now = new Date().toISOString()
  const id = normalizeSlideRequestId(requestId)
  const previousQueue = normalizeSlideGenerationQueue(normalized.slideGenerationQueue, outline)
  const targetPrevious = previousQueue.find((item) => item.pageNo === targetPageNo)
  const queue = normalizeSlideGenerationQueue(normalized.slideGenerationQueue, outline).map((item) => {
    if (item.pageNo === targetPageNo) {
      return {
        ...item,
        status: 'requesting',
        requestId: id,
        attempt: (Number(targetPrevious && targetPrevious.attempt) || 0) + 1,
        startedAt: now,
        responseReceivedAt: '',
        appliedAt: '',
        completedAt: '',
        error: '',
        errorKind: '',
        responseSummary: {},
        updatedAt: now,
      }
    }
    if (activeSlideStatuses().has(item.status)) {
      return { ...item, status: item.status === 'ready' ? 'ready' : 'pending', requestId: '', updatedAt: now }
    }
    return item
  })
  const summary = slideQueueSummary(queue)
  const job = normalizeGenerationJob(normalized.generationJob)
  return createPptPlanningState({
    ...normalized,
    currentStep: PPT_PLANNING_STEPS.SLIDES_GENERATING,
    slideGenerationQueue: queue,
    slideGenerationJob: {
      ...normalizeSlideGenerationJob(normalized.slideGenerationJob),
      id: normalizeSlideGenerationJob(normalized.slideGenerationJob).id || job.id,
      status: 'running',
      active: true,
      currentPageNo: targetPageNo,
      total: outline.length,
      lastCompletedPageNo: summary.lastCompletedPageNo,
      failedPageNo: 0,
      error: '',
      startedAt: normalizeSlideGenerationJob(normalized.slideGenerationJob).startedAt || now,
      updatedAt: now,
      activePageStartedAt: now,
      completedAt: '',
    },
    generationJob: job.id && job.type === 'slides'
      ? {
          ...job,
          phase: 'requesting',
          error: '',
          responseSummary: {
            ...job.responseSummary,
            currentPageNo: targetPageNo,
            lastCompletedPageNo: summary.lastCompletedPageNo,
          },
        }
      : normalized.generationJob,
    generationError: '',
    generationErrorSource: '',
  })
}

export function markSlideResponseReceived(state = {}, pageNo = 0, requestId = '', summary = {}) {
  const normalized = createPptPlanningState(state)
  if (!queueHasRequest(normalized.slideGenerationQueue, pageNo, requestId)) {
    return markStaleSlideResponseIgnored(normalized, pageNo, requestId)
  }
  const now = new Date().toISOString()
  const queue = normalizeSlideGenerationQueue(normalized.slideGenerationQueue, normalized.outline).map((item) => (
    item.pageNo === Number(pageNo || 0)
      ? { ...item, status: 'response_received', responseReceivedAt: now, responseSummary: cloneObject(summary), updatedAt: now }
      : item
  ))
  const job = normalizeGenerationJob(normalized.generationJob)
  return createPptPlanningState({
    ...normalized,
    currentStep: PPT_PLANNING_STEPS.SLIDES_GENERATING,
    slideGenerationQueue: queue,
    slideGenerationJob: {
      ...normalizeSlideGenerationJob(normalized.slideGenerationJob),
      status: 'running',
      active: true,
      currentPageNo: Number(pageNo || 0) || 0,
      updatedAt: now,
    },
    generationJob: job.id && job.type === 'slides'
      ? {
          ...job,
          phase: 'response_received',
          responseSummary: { ...job.responseSummary, lastResponsePageNo: Number(pageNo || 0) || 0 },
        }
      : normalized.generationJob,
  })
}

export function markSlideApplying(state = {}, pageNo = 0, requestId = '') {
  const normalized = createPptPlanningState(state)
  if (!queueHasRequest(normalized.slideGenerationQueue, pageNo, requestId)) {
    return markStaleSlideResponseIgnored(normalized, pageNo, requestId)
  }
  const now = new Date().toISOString()
  const queue = normalizeSlideGenerationQueue(normalized.slideGenerationQueue, normalized.outline).map((item) => (
    item.pageNo === Number(pageNo || 0)
      ? { ...item, status: 'applying', updatedAt: now }
      : item
  ))
  const job = normalizeGenerationJob(normalized.generationJob)
  return createPptPlanningState({
    ...normalized,
    currentStep: PPT_PLANNING_STEPS.SLIDES_GENERATING,
    slideGenerationQueue: queue,
    slideGenerationJob: {
      ...normalizeSlideGenerationJob(normalized.slideGenerationJob),
      status: 'running',
      active: true,
      currentPageNo: Number(pageNo || 0) || 0,
      updatedAt: now,
    },
    generationJob: job.id && job.type === 'slides'
      ? { ...job, phase: 'applying' }
      : normalized.generationJob,
  })
}

function writeSlideBriefToDeck(state = {}, slide = {}) {
  const normalized = createPptPlanningState(state)
  const nextSlide = normalizeDeckSlideBrief(slide, Number(slide.index || 1) || 1)
  const slides = cloneArray((normalized.deckBrief || {}).slides)
  const index = findSlideIndex(slides, nextSlide)
  const nextSlides = index >= 0
    ? slides.map((item, itemIndex) => (itemIndex === index ? nextSlide : item))
    : [...slides, nextSlide].sort((a, b) => (Number(a.index || 0) || 0) - (Number(b.index || 0) || 0))
  return createPptPlanningState({
    ...normalized,
    deckBrief: {
      ...normalizeDeckBrief(normalized.deckBrief),
      slides: nextSlides,
    },
    selectedSlideId: normalized.selectedSlideId || asText(nextSlide.id),
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

export function applySlideResponseAndMarkReady(state = {}, pageNo = 0, requestId = '', response = {}) {
  const writeState = response && typeof response === 'object' && Object.keys(response).length
    ? writeSlideBriefToDeck(state, response)
    : createPptPlanningState(state)
  const normalized = createPptPlanningState(writeState)
  if (!queueHasRequest(normalized.slideGenerationQueue, pageNo, requestId)) {
    return markStaleSlideResponseIgnored(normalized, pageNo, requestId)
  }
  const now = new Date().toISOString()
  const targetPageNo = Number(pageNo || 0) || 0
  const outline = normalizePptOutline(normalized.outline)
  const queue = normalizeSlideGenerationQueue(normalized.slideGenerationQueue, outline).map((item) => (
    item.pageNo === targetPageNo
      ? { ...item, status: 'ready', error: '', errorKind: '', appliedAt: now, completedAt: now, updatedAt: now }
      : activeSlideStatuses().has(item.status)
        ? { ...item, status: 'pending', requestId: '', updatedAt: now }
        : item
  ))
  const nextRunnable = queue.find((item) => item.status !== 'ready')
  const summary = slideQueueSummary(queue)
  const job = normalizeGenerationJob(normalized.generationJob)
  const generationJob = job.id && job.type === 'slides'
    ? {
        ...job,
        phase: nextRunnable ? 'requesting' : 'ready',
        completedAt: nextRunnable ? '' : now,
        responseSummary: {
          ...job.responseSummary,
          slides: summary.readyCount,
          lastCompletedPageNo: summary.lastCompletedPageNo,
        },
      }
    : normalized.generationJob
  return createPptPlanningState({
    ...normalized,
    currentStep: nextRunnable ? PPT_PLANNING_STEPS.SLIDES_GENERATING : PPT_PLANNING_STEPS.DIRECTIVE_DRAFT,
    slideGenerationQueue: queue,
    slideGenerationJob: {
      ...normalizeSlideGenerationJob(normalized.slideGenerationJob),
      status: nextRunnable ? 'running' : 'completed',
      active: !!nextRunnable,
      currentPageNo: nextRunnable ? nextRunnable.pageNo : 0,
      total: outline.length,
      lastCompletedPageNo: summary.lastCompletedPageNo,
      failedPageNo: 0,
      error: '',
      updatedAt: now,
      activePageStartedAt: '',
      completedAt: nextRunnable ? '' : now,
    },
    generationJob,
    generationError: '',
    generationErrorSource: '',
  })
}

export function markSlideFailed(state = {}, pageNo = 0, requestId = '', error = '', errorKind = '') {
  const normalized = createPptPlanningState(state)
  const targetPageNo = Number(pageNo || 0) || Number(normalized.slideGenerationJob.currentPageNo || 0) || 0
  const message = asText(error && error.message ? error.message : error) || 'ppt_slide_generation_failed'
  const now = new Date().toISOString()
  const queue = normalizeSlideGenerationQueue(normalized.slideGenerationQueue, normalized.outline).map((item) => (
    item.pageNo === targetPageNo
      ? {
          ...item,
          status: 'failed',
          requestId: asText(requestId || item.requestId),
          error: message,
          errorKind: asText(errorKind) || 'http_error',
          completedAt: now,
          updatedAt: now,
        }
      : activeSlideStatuses().has(item.status)
        ? { ...item, status: 'pending', requestId: '', updatedAt: now }
        : item
  ))
  const summary = slideQueueSummary(queue)
  const job = normalizeGenerationJob(normalized.generationJob)
  return createPptPlanningState({
    ...normalized,
    currentStep: PPT_PLANNING_STEPS.SLIDES_GENERATING,
    slideGenerationQueue: queue,
    slideGenerationJob: {
      ...normalizeSlideGenerationJob(normalized.slideGenerationJob),
      status: 'failed',
      active: false,
      currentPageNo: 0,
      total: normalizePptOutline(normalized.outline).length,
      lastCompletedPageNo: summary.lastCompletedPageNo,
      failedPageNo: targetPageNo,
      error: message,
      updatedAt: now,
      activePageStartedAt: '',
      completedAt: now,
    },
    generationJob: job.id && job.type === 'slides'
      ? appendGenerationEvent({
          ...job,
          phase: 'failed',
          error: message,
          completedAt: now,
          responseSummary: {
            ...job.responseSummary,
            slides: summary.readyCount,
            failedPageNo: targetPageNo,
            errorKind: asText(errorKind) || 'http_error',
          },
        }, 'slide_failed', { error: message, pageNo: targetPageNo, requestId, errorKind: asText(errorKind) || 'http_error' })
      : normalized.generationJob,
    generationError: message,
    generationErrorSource: 'slides',
  })
}

export function markSlideTimedOut(state = {}, pageNo = 0, requestId = '', error = '') {
  const targetPageNo = Number(pageNo || 0) || 0
  const message = asText(error) || `第 ${targetPageNo || '当前'} 页请求超时，后端可能仍在处理，请点击继续重试。`
  const failed = markSlideFailed(state, targetPageNo, requestId, message, 'timeout')
  const normalized = createPptPlanningState(failed)
  const queue = normalizeSlideGenerationQueue(normalized.slideGenerationQueue, normalized.outline).map((item) => (
    item.pageNo === targetPageNo ? { ...item, status: 'timed_out' } : item
  ))
  return createPptPlanningState({ ...normalized, slideGenerationQueue: queue })
}

export function markStaleSlideResponseIgnored(state = {}, pageNo = 0, requestId = '') {
  const normalized = createPptPlanningState(state)
  const targetPageNo = Number(pageNo || 0) || 0
  const now = new Date().toISOString()
  const job = normalizeGenerationJob(normalized.generationJob)
  return createPptPlanningState({
    ...normalized,
    generationJob: job.id && job.type === 'slides'
      ? appendGenerationEvent(job, 'stale_slide_response_ignored', { pageNo: targetPageNo, requestId, at: now })
      : normalized.generationJob,
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
    visual_specs: cloneArray(target.visualSpecs).map((item) => clearPptMapSnapshotCaptureError(item)),
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
    metric_context: metricContextForVisualPayload(sources, current),
  }
}

export function clearPptMapSnapshotCaptureError(visual = {}) {
  const next = cloneObject(visual)
  const data = cloneObject(next.data)
  const composition = asText(data.composition || data.composition_type || data.compositionType)
  const isMapRequest = composition === 'map_snapshot_request' && (data.map_request || data.mapRequest)
  const isCarrierRequest = composition === 'carrier_snapshot_request' && (data.carrier_snapshot_request || data.carrierSnapshotRequest || data.package_source_id || data.packageSourceId)
  if (!isMapRequest && !isCarrierRequest) {
    return next
  }
  delete data.capture_error
  delete data.captureError
  next.data = data
  return next
}

export function clearPptSlideMapSnapshotCaptureErrors(state = {}, slideIndex = 0) {
  const normalized = createPptPlanningState(state)
  const targetIndex = Number(slideIndex || 0) || 0
  if (!targetIndex) return normalized
  const nextSlides = cloneArray((normalized.deckBrief || {}).slides).map((slide) => (
    Number(slide.index || 0) === targetIndex
      ? {
          ...slide,
          visualSpecs: cloneArray(slide.visualSpecs || slide.visual_specs).map((visual) => clearPptMapSnapshotCaptureError(visual)),
        }
      : slide
  ))
  return createPptPlanningState({
    ...normalized,
    deckBrief: {
      ...normalizeDeckBrief(normalized.deckBrief),
      slides: nextSlides,
    },
  })
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
  const incomingVisualSpecs = cloneArray(response.visualSpecs || response.visual_specs).map((item) => cloneObject(item))
  const nextSlides = cloneArray((normalized.deckBrief || {}).slides).map((slide) => {
    if (Number(slide.index || 0) !== slideIndex) return slide
    const incomingKeys = new Set(incomingArtifacts.map(artifactKey).filter(Boolean))
    const retained = cloneArray(slide.visualArtifacts).filter((artifact) => {
      const key = artifactKey(artifact)
      return key && !incomingKeys.has(key)
    })
    return {
      ...slide,
      visualSpecs: incomingVisualSpecs.length ? incomingVisualSpecs : slide.visualSpecs,
      visualArtifacts: [...retained, ...incomingArtifacts],
    }
  })
  const targetSlide = nextSlides.find((slide) => Number(slide.index || 0) === slideIndex) || {}
  const hasReadyVisualArtifacts = incomingArtifacts.length > 0 || cloneArray(targetSlide.visualArtifacts || targetSlide.visual_artifacts).length > 0
  const allVisualsReady = nextSlides.some(slideHasVisualSpecs) && !nextSlides.some(slideHasPendingVisualSpecs)
  return createPptPlanningState({
    ...normalized,
    currentStep: (hasReadyVisualArtifacts || allVisualsReady) ? PPT_PLANNING_STEPS.VISUALS_READY : normalized.currentStep,
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
      insight: asText(item.insight),
      evidenceExplanation: cloneArray(item.evidenceExplanation || item.evidence_explanation).map((source) => asText(source)).filter(Boolean).join('\n'),
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
  const hasIncomingVisualSpecs = cloneArray(slide.visualSpecs || slide.visual_specs).length > 0
  const hasIncomingVisualArtifacts = cloneArray(slide.visualArtifacts || slide.visual_artifacts).length > 0
  const mergedSlide = {
    ...nextSlide,
    visualSpecs: hasIncomingVisualSpecs ? nextSlide.visualSpecs : cloneArray(previous.visualSpecs).map((item) => cloneObject(item)),
    visualArtifacts: hasIncomingVisualArtifacts ? nextSlide.visualArtifacts : cloneArray(previous.visualArtifacts).map((item) => cloneObject(item)),
  }
  const nextSlides = slides.map((item, itemIndex) => (itemIndex === index ? mergedSlide : item))
  const key = slideRevisionKey(previous)
  const pageId = String(Number(mergedSlide.index || 0) || '')
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

export function syncPptSourceRefreshPlaceholderSources(state = {}, expectedSources = []) {
  const normalized = createPptPlanningState(state)
  const existingPlaceholders = normalized.sources.filter((item) => isPptSourceRefreshPlaceholder(item))
  const existingExpectedIds = new Set(existingPlaceholders
    .map((item) => asText(item.meta && item.meta.expectedSourceId))
    .filter(Boolean))
  const sourceIds = new Set(normalized.sources.map((item) => asText(item.id)).filter(Boolean))
  const manifestSources = cloneArray(expectedSources).length
    ? normalizeSources(expectedSources).filter((item) => isRefreshableBackendPptSource(item))
    : []
  const backendSources = manifestSources.length ? manifestSources : normalized.sources.filter((item) => isRefreshableBackendPptSource(item))
  const retainedPlaceholders = existingPlaceholders.filter((item) => {
    const expectedSourceId = asText(item.meta && item.meta.expectedSourceId)
    return expectedSourceId && !sourceIds.has(expectedSourceId)
  })
  const newPlaceholders = backendSources
    .filter((item) => !existingExpectedIds.has(asText(item.id)))
    .map((item, index) => sourceRefreshPlaceholderFromSource(item, index))
  const placeholders = [...retainedPlaceholders, ...newPlaceholders]
  if (!placeholders.length) placeholders.push(createAggregateSourceRefreshPlaceholder())
  const sources = [
    ...normalized.sources.filter((item) => !isPptSourceRefreshPlaceholder(item) && !isRefreshableBackendPptSource(item)),
    ...placeholders,
  ]
  return createPptPlanningState({
    ...normalized,
    sources,
    sourceGroups: reconcilePptSourceGroups(normalized.sourceGroups, sources, normalized.ungroupedSourceIds),
    spec: syncSpecSourceIds(normalized, sources),
  })
}

export function clearPptSourceRefreshPlaceholderSources(state = {}) {
  const normalized = createPptPlanningState(state)
  const sources = normalized.sources.filter((item) => !isPptSourceRefreshPlaceholder(item))
  return createPptPlanningState({
    ...normalized,
    sources,
    sourceGroups: reconcilePptSourceGroups(normalized.sourceGroups, sources, normalized.ungroupedSourceIds),
    spec: syncSpecSourceIds(normalized, sources),
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
  const previousSourceId = asText(options.previousSourceId || options.previous_source_id)
  const previous = previousById.get(sourceId) || (previousSourceId ? previousById.get(previousSourceId) : null)
  const documentRole = asText(
    options.documentRole
      || options.document_role
      || document.document_role
      || document.documentRole
      || (document.meta && document.meta.document && document.meta.document.document_role)
      || (previous && previous.meta && previous.meta.document && previous.meta.document.document_role)
      || (previous && previous.meta && (previous.meta.aiPayload || previous.meta.ai_payload) && (previous.meta.aiPayload || previous.meta.ai_payload).document_role),
  )
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
  const aiPayloadBase = {
    version: 'ppt_ai_input_block_v1',
    source_id: sourceId,
    sourceId,
    title,
    source_kind: 'document',
    sourceKind: 'document',
    document_role: documentRole,
    documentRole,
    included: ['document_identity'],
    scope: null,
    metrics: [],
    metric_gaps: [],
    metricGaps: [],
    visual_specs: [],
    visualSpecs: [],
    excluded: [{ type: 'document_full_text', reason: '不传文档全文，只传 PageIndex 节点/章节摘要。', count: Number(options.count || indexPreview.length || 0) || 0 }],
    counts: { scope: 0, metrics: 0, metric_gaps: 0, evidence: evidence.length, visual_specs: 0 },
    policy: '文档来源只通过 PageIndex 节点/章节摘要进入 evidence；不从全文临时抽取。',
  }
  const evidenceNodes = evidenceNodesFromEvidenceItems(aiPayloadBase, evidence)
  const aiPayload = {
    ...aiPayloadBase,
    evidence_nodes: evidenceNodes,
    evidenceNodes,
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
      uploadPlaceholder: !!options.uploadPlaceholder,
      documentId,
      document_role: documentRole,
      document: {
        ...cloneObject(previous && previous.meta && previous.meta.document),
        id: documentId,
        document_role: documentRole,
      },
      fileName: asText(document.file_name || document.fileName),
      count: Number(options.count ?? (previous && previous.meta && previous.meta.count) ?? 0) || 0,
      document_index_preview: indexPreview,
      aiPayload: ready ? aiPayload : cloneObject(previous && previous.meta && previous.meta.aiPayload),
      ai_payload: ready ? aiPayload : cloneObject(previous && previous.meta && previous.meta.ai_payload),
      transport,
    },
  })
  const replacementIds = new Set([sourceId, previousSourceId].filter(Boolean))
  const replacementIndex = normalized.sources.findIndex((source) => replacementIds.has(asText(source.id)))
  const sources = normalized.sources.filter((source) => !replacementIds.has(asText(source.id)))
  sources.splice(replacementIndex >= 0 ? replacementIndex : sources.length, 0, nextSource)
  const sourceGroups = normalized.sourceGroups.map((group) => ({
    ...group,
    sourceIds: uniqueText(cloneArray(group.sourceIds).map((id) => (asText(id) === previousSourceId ? sourceId : id))),
  }))
  const ungroupedSourceIds = uniqueText(normalized.ungroupedSourceIds.map((id) => (asText(id) === previousSourceId ? sourceId : id)))
  return createPptPlanningState({
    ...normalized,
    sources,
    sourceGroups: reconcilePptSourceGroups(sourceGroups, sources, ungroupedSourceIds),
    ungroupedSourceIds,
    spec: syncSpecSourceIds(normalized, sources),
    generationError: '',
    generationErrorSource: '',
  })
}

export function upsertPptImageSource(state = {}, attachment = {}, options = {}) {
  const normalized = createPptPlanningState(state)
  const attachmentId = asText(attachment.attachment_id || attachment.attachmentId || attachment.id)
  const sourceId = asText(options.sourceId) || (attachmentId ? `image:${attachmentId}` : '')
  if (!sourceId) return normalized
  const status = asText(options.status || attachment.status) || 'pending'
  const ready = status === 'ready'
  const title = asText(attachment.filename || attachment.fileName || options.title) || '图片来源'
  const mimeType = asText(attachment.mime_type || attachment.mimeType)
  const previousSourceId = asText(options.previousSourceId || options.previous_source_id)
  const previousById = new Map(normalized.sources.map((item) => [asText(item.id), item]))
  const previous = previousById.get(sourceId) || previousById.get(previousSourceId)
  const previousPayload = cloneObject(previous && previous.meta && (previous.meta.aiPayload || previous.meta.ai_payload))
  const aiPayload = previousPayload.version === 'ppt_ai_input_block_v1'
    ? previousPayload
    : {
        version: 'ppt_ai_input_block_v1',
        source_id: sourceId,
        sourceId,
        title,
        source_kind: 'image',
        sourceKind: 'image',
        included: [],
        scope: null,
        metrics: [],
        metric_gaps: [],
        metricGaps: [],
        evidence: [],
        visual_specs: [],
        visualSpecs: [],
        excluded: [{ type: 'image_binary', reason: '图片解析完成前不直接进入生成。' }],
        counts: { scope: 0, metrics: 0, metric_gaps: 0, evidence: 0, visual_specs: 0 },
        policy: '图片来源只通过 OCR、图像描述和视觉理解证据节点进入生成。',
      }
  const evidenceCount = Number((aiPayload.counts || {}).evidence || evidenceNodesFromAiPayload(aiPayload).length || 0) || 0
  const nextSource = normalizePptSource({
    ...(previous || {}),
    id: sourceId,
    type: 'image',
    title,
    status,
    selected: ready ? (previous ? !!previous.selected : true) : false,
    source_kind: 'image',
    summary: asText(attachment.summary || options.label) || (ready ? '图片解析完成' : status === 'generating' || status === 'processing' ? '图片解析中' : '待解析'),
    evidence_count: evidenceCount,
    locator_summary: `${title}${mimeType ? ` / ${mimeType}` : ''}`,
    availability: ready
      ? (evidenceCount > 0 ? 'available' : 'empty_evidence:image_parse_empty')
      : status === 'failed' ? 'failed:image_parse_failed' : 'building:image_parse_pending',
    meta: {
      ...cloneObject(previous && previous.meta),
      label: asText(attachment.summary || options.label) || (ready ? '图片解析完成' : '图片解析中'),
      sourceKind: 'image',
      uploadPlaceholder: !!options.uploadPlaceholder,
      attachmentId,
      conversationId: asText(attachment.conversation_id || attachment.conversationId || options.conversationId),
      fileName: title,
      mimeType,
      image: {
        attachment_id: attachmentId,
        conversation_id: asText(attachment.conversation_id || attachment.conversationId || options.conversationId),
        history_id: asText(attachment.history_id || attachment.historyId),
        filename: title,
        mime_type: mimeType,
        status,
      },
      aiPayload,
      ai_payload: aiPayload,
      transport: evidenceCount > 0 ? createPptTransportFromAiPayload(aiPayload) : cloneObject(previous && previous.meta && previous.meta.transport),
    },
  })
  const replacementIds = new Set([sourceId, previousSourceId].filter(Boolean))
  const replacementIndex = normalized.sources.findIndex((source) => replacementIds.has(asText(source.id)))
  const sources = normalized.sources.filter((source) => !replacementIds.has(asText(source.id)))
  sources.splice(replacementIndex >= 0 ? replacementIndex : sources.length, 0, nextSource)
  const sourceGroups = normalized.sourceGroups.map((group) => ({
    ...group,
    sourceIds: uniqueText(cloneArray(group.sourceIds).map((id) => (asText(id) === previousSourceId ? sourceId : id))),
  }))
  const ungroupedSourceIds = uniqueText(normalized.ungroupedSourceIds.map((id) => (asText(id) === previousSourceId ? sourceId : id)))
  return createPptPlanningState({
    ...normalized,
    sources,
    sourceGroups: reconcilePptSourceGroups(sourceGroups, sources, ungroupedSourceIds),
    ungroupedSourceIds,
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
  const sourceKind = canonicalPptSourceKind(packageMeta.sourceKind || packageSource.source_kind || packageSource.sourceKind, packageSource.id, 'package')
  const existingPayload = cloneObject(packageMeta.aiPayload || packageMeta.ai_payload)
  const aiPayload = existingPayload.version === 'ppt_ai_input_block_v1'
    ? existingPayload
    : createPackageAiPayload(packageSource.id, packageSource.title, packageMeta.package)
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
    const sourceKind = canonicalPptSourceKind(source.source_kind || source.sourceKind || meta.sourceKind, source.id)
    const sourceId = asText(source.id)
    const packageLike = sourceKind === 'package'
      || sourceKind === 'package-placeholder'
      || sourceId.startsWith('package:')
      || sourceId.startsWith('package-placeholder:')
      || (sourceKind === 'web' && asText(packageSource.id) === sourceId)
    if (!packageLike) return false
    if (asText(source.id) === packageSource.id) return true
    if (canonicalPptSourceKind(packageSource.source_kind || packageSource.sourceKind || nextMeta.sourceKind, packageSource.id) === 'web') return false
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
        sourceKind,
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
    web_sources_enabled: !!normalized.spec.webSourcesEnabled,
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
    web_sources_enabled: !!normalized.spec.webSourcesEnabled,
  }
}

function narrativePlanForRequest(plan = {}) {
  const normalized = normalizeNarrativePlan(plan)
  return {
    storyline: normalized.storyline,
    chapters: cloneArray(normalized.chapters).map((item) => ({
      name: item.name,
      page_range: item.pageRange,
      job: item.job,
      output: item.output,
    })),
    evidence_buckets: cloneArray(normalized.evidenceBuckets).map((item) => ({
      id: item.id,
      label: item.label,
      allowed_sources: cloneArray(item.allowedSources),
    })),
    slide_roles: normalized.slideRoles.map((role) => ({
      page_no: role.pageNo,
      role: role.role,
      job: role.job,
      evidence_bucket: role.evidenceBucket,
      visual_family: role.visualFamily,
      transition_note: role.transitionNote,
    })),
    visual_rules: {
      spatial_first: !!normalized.visualRules.spatialFirst,
      numeric_charts_require_data: !!normalized.visualRules.numericChartsRequireData,
      diagram_for_strategy_pages: !!normalized.visualRules.diagramForStrategyPages,
      no_fallback_bar: !!normalized.visualRules.noFallbackBar,
    },
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
        insight: '',
        visualPlan: '',
        requiredSources: [],
        metricClaims: [],
        metricGaps: [],
        visualSpecs: [],
        visualArtifacts: [],
      }
  const pageNo = Number(targetItem.index || requestedIndex || (outlineItem && outlineItem.pageNo) || 1) || 1
  const previousSlide = slides.find((item) => Number(item.index || 0) === pageNo - 1) || null
  const nextOutline = normalized.outline.find((item) => Number(item.pageNo || 0) === pageNo + 1) || null
  const generatedPages = slides.map((item) => Number(item.index || 0) || 0).filter(Boolean).sort((a, b) => a - b)
  const contextIdSeed = [
    asText(context.areaId || context.area_id || normalized.spec.areaId),
    asText(normalized.spec.topic),
    normalizePptOutline(normalized.outline).map((item) => `${item.pageNo}:${item.id}:${item.theme}`).join('|'),
    sourceIds.join('|'),
  ].join('::')
  const contextId = `ppt-brief-${simpleHash(contextIdSeed)}`
  return {
    ...buildDeckBriefPayload(normalized, context),
    context_id: contextId,
    page_no: pageNo,
    outline: normalizePptOutline(normalized.outline).map((item) => ({
      id: item.id,
      page_no: item.pageNo,
      theme: item.theme,
      purpose: item.purpose,
    })),
    slides: [],
    previous_slide_summary: previousSlide ? {
      index: previousSlide.index,
      title: previousSlide.title,
      purpose: previousSlide.purpose,
      key_message: previousSlide.keyMessage,
      insight: previousSlide.insight,
      evidence_explanation: cloneArray(previousSlide.evidenceExplanation),
      visual_plan: previousSlide.visualPlan,
      required_sources: cloneArray(previousSlide.requiredSources).slice(0, 8),
    } : {},
    next_outline_summary: nextOutline ? {
      id: nextOutline.id,
      page_no: nextOutline.pageNo,
      theme: nextOutline.theme,
      purpose: nextOutline.purpose,
    } : {},
    deck_progress_summary: {
      page_no: pageNo,
      page_count: normalizePptOutline(normalized.outline).length || Number(normalized.spec.pageCount || normalized.spec.page_count || 0) || 0,
      generated_pages: generatedPages,
      ready_count: generatedPages.length,
      pending_count: Math.max((normalizePptOutline(normalized.outline).length || 0) - generatedPages.length, 0),
    },
    target: {
      index: targetItem.index,
      title: targetItem.title,
      purpose: targetItem.purpose,
      key_message: targetItem.keyMessage,
      insight: targetItem.insight,
      evidence_explanation: cloneArray(targetItem.evidenceExplanation),
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
