<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { normalizePptPackageDetail } from './carrier-preview.js'
import { getBlockingPptInputSources } from './ui-state.js'

const props = defineProps({
  sources: {
    type: Array,
    default: () => [],
  },
  sourceGroups: {
    type: Array,
    default: () => [],
  },
  sourceSummary: {
    type: Object,
    default: () => ({ total: 0, selected: 0, ready: 0 }),
  },
  spec: {
    type: Object,
    default: () => ({
      topic: '',
      pageCount: 15,
      audience: '政府评审',
    }),
  },
  currentStep: {
    type: String,
    default: 'materials',
  },
  outline: {
    type: Array,
    default: () => [],
  },
  slides: {
    type: Array,
    default: () => [],
  },
  generationError: {
    type: String,
    default: '',
  },
  generationErrorSource: {
    type: String,
    default: '',
  },
  generationResponse: {
    type: Object,
    default: () => ({}),
  },
  generationJob: {
    type: Object,
    default: () => ({}),
  },
  dataPackageGenerating: {
    type: Boolean,
    default: false,
  },
  sourceGrouping: {
    type: Boolean,
    default: false,
  },
  activeRevisionTarget: {
    type: Object,
    default: () => ({}),
  },
  outlineRevisionDraft: {
    type: Object,
    default: () => ({}),
  },
  directiveRevisionDraft: {
    type: Object,
    default: () => ({}),
  },
  revisionSnapshots: {
    type: Object,
    default: () => ({}),
  },
  staleDirectivePageIds: {
    type: Array,
    default: () => [],
  },
  revisionGeneratingTarget: {
    type: Object,
    default: () => ({}),
  },
})

const emit = defineEmits([
  'classify-source-groups',
  'toggle-source',
  'toggle-all-sources',
  'toggle-source-group-collapsed',
  'set-source-group-selected',
  'move-source-to-group',
  'rename-source',
  'remove-source',
  'generate-package-source',
  'rename-source-group',
  'set-source-group-emoji',
  'remove-source-group',
  'upload-document-source',
  'update-spec-field',
  'create-data-package',
  'generate-outline',
  'generate-directive',
  'regenerate-outline',
  'regenerate-directive',
  'open-revision-target',
  'close-revision-target',
  'update-revision-draft',
  'save-revision',
  'regenerate-revision',
  'undo-revision',
])

const isSourcesCollapsed = ref(false)
const sourceMenu = ref({ kind: '', id: '', placement: 'below', x: 0, y: 0 })
const sourceDialog = ref({ mode: '', id: '', title: '', value: '', message: '' })
const documentSourceInput = ref(null)
const activeDocumentSourceId = ref('')
const activePackageSourceId = ref('')
const activeCurrentSourceId = ref('')
const activePackageCarrierId = ref('')
const activePackageCarrierPreviewMode = ref('local')
const flowViewMode = ref('')
const sourceMenuLockClass = 'agent-ppt-source-menu-open'

const sourcePanelLabel = computed(() => (isSourcesCollapsed.value ? '展开来源' : '折叠来源'))
const sourceCollapseIconPoints = computed(() => (
  isSourcesCollapsed.value ? '14.5,12 12,9.5 12,14.5 14.5,12' : '11.5,12 14,9.5 14,14.5 11.5,12'
))
const sourceById = computed(() => new Map(props.sources.map((source) => [String(source.id || ''), source])))
const sourceGroupsForTree = computed(() => props.sourceGroups.map((group) => ({
  ...group,
  items: (Array.isArray(group.sourceIds) ? group.sourceIds : [])
    .map((sourceId) => sourceById.value.get(String(sourceId || '')))
    .filter(Boolean),
})).filter((group) => group.items.length))
const groupedSourceIds = computed(() => new Set(sourceGroupsForTree.value.flatMap((group) => (
  Array.isArray(group.sourceIds) ? group.sourceIds.map((sourceId) => String(sourceId || '')) : []
))))
const ungroupedSources = computed(() => props.sources.filter((source) => (
  source && source.id && !groupedSourceIds.value.has(String(source.id || ''))
)))
const hasVisibleSources = computed(() => sourceGroupsForTree.value.length > 0 || ungroupedSources.value.length > 0)
const isOutlineGenerating = computed(() => props.currentStep === 'outline_generating')
const isDirectiveGenerating = computed(() => props.currentStep === 'directive_generating')
const hasOutline = computed(() => props.outline.length > 0)
const hasDirective = computed(() => props.currentStep === 'directive_draft')
const blockingInputSources = computed(() => getBlockingPptInputSources({ sources: props.sources }))
const outlineBlockReason = computed(() => {
  if (!(props.sourceSummary.selected || 0)) return '请先选择至少一个已生成来源'
  if (blockingInputSources.value.length) {
    const generating = blockingInputSources.value.some((source) => String(source.status || '') === 'generating')
    return generating ? '来源仍在构建中，完成后再生成目录' : '仍有来源未构建完成，完成后再生成目录'
  }
  return ''
})
const canGenerateOutline = computed(() => !outlineBlockReason.value && !isOutlineGenerating.value && !isDirectiveGenerating.value)
const canGenerateDirective = computed(() => hasOutline.value && !isOutlineGenerating.value && !isDirectiveGenerating.value)
const canCreateDataPackage = computed(() => (props.sourceSummary.selected || 0) > 0 && !props.dataPackageGenerating)
const activeGenerationJob = computed(() => (props.generationJob && typeof props.generationJob === 'object' ? props.generationJob : {}))
const generationJobPhase = computed(() => String(activeGenerationJob.value.phase || 'idle'))
const generationJobType = computed(() => String(activeGenerationJob.value.type || 'outline'))
const generationJobEvents = computed(() => (Array.isArray(activeGenerationJob.value.events) ? activeGenerationJob.value.events.slice(-20) : []))
const isGenerationJobActive = computed(() => ['requesting', 'response_received', 'applying', 'timed_out'].includes(generationJobPhase.value))
const generationJobTitle = computed(() => {
  const isDirective = generationJobType.value === 'directive'
  const labels = {
    requesting: isDirective ? '指令生成中' : '目录生成中',
    response_received: isDirective ? '后端已返回，正在应用指令' : '后端已返回，正在应用目录',
    applying: isDirective ? '正在写入指令' : '正在写入目录',
    ready: isDirective ? '指令已写入' : '目录已写入',
    failed: isDirective ? '指令生成失败' : '目录生成失败',
    timed_out: isDirective ? '指令请求已超时，仍等待可能晚到的返回' : '目录请求已超时，仍等待可能晚到的返回',
    superseded: '已有新请求接管',
  }
  return labels[generationJobPhase.value] || ''
})
const generationJobSummary = computed(() => {
  const summary = activeGenerationJob.value.responseSummary && typeof activeGenerationJob.value.responseSummary === 'object'
    ? activeGenerationJob.value.responseSummary
    : {}
  return [
    summary.outlineCount ? `outline ${summary.outlineCount} 页` : '',
    summary.slideCount ? `slides ${summary.slideCount} 页` : '',
    Array.isArray(summary.keys) && summary.keys.length ? `keys: ${summary.keys.slice(0, 8).join(', ')}` : '',
    activeGenerationJob.value.error ? `error: ${activeGenerationJob.value.error}` : '',
  ].filter(Boolean).join(' / ')
})
const shouldShowGenerationJobPanel = computed(() => (
  generationJobTitle.value
  && (isGenerationJobActive.value || ['failed', 'timed_out', 'superseded'].includes(generationJobPhase.value) || generationJobEvents.value.length)
))
const generationErrorText = computed(() => String(props.generationError || '').trim())
const generationResponsePayload = computed(() => {
  const response = props.generationResponse && typeof props.generationResponse === 'object'
    ? props.generationResponse
    : {}
  const payload = response.payload && typeof response.payload === 'object' ? response.payload : {}
  return Object.keys(payload).length ? payload : {}
})
const hasGenerationResponsePayload = computed(() => Object.keys(generationResponsePayload.value).length > 0)
const generationResponseTitle = computed(() => {
  const response = props.generationResponse && typeof props.generationResponse === 'object'
    ? props.generationResponse
    : {}
  const source = String(response.source || '').trim()
  const receivedAt = String(response.receivedAt || response.received_at || '').trim()
  const label = source === 'directive' ? '指令返回' : source === 'outline' ? '目录返回' : '生成返回'
  return receivedAt ? `${label} · ${receivedAt}` : label
})
const generationResponseSummary = computed(() => {
  const payload = generationResponsePayload.value
  const outline = Array.isArray(payload.outline) ? payload.outline : []
  const slides = Array.isArray(payload.slides) ? payload.slides : []
  const chartSpecs = slides.reduce((sum, slide) => {
    const specs = slide && (slide.chartSpecs || slide.chart_specs)
    return sum + (Array.isArray(specs) ? specs.length : 0)
  }, 0)
  const keys = Object.keys(payload)
  return [
    outline.length ? `outline ${outline.length} 页` : '',
    slides.length ? `slides ${slides.length} 页` : '',
    chartSpecs ? `chart_specs ${chartSpecs} 个` : '',
    keys.length ? `keys: ${keys.slice(0, 8).join(', ')}` : '',
  ].filter(Boolean).join(' / ')
})
const generationResponseJson = computed(() => {
  try {
    return JSON.stringify(generationResponsePayload.value, null, 2)
  } catch (_) {
    return '无法序列化生成返回。'
  }
})
const generationErrorTitle = computed(() => {
  if (!generationErrorText.value) return ''
  const labels = {
    source_refresh: '来源刷新失败，请检查历史数据或数据库连接后重试。',
    source_grouping: '来源分组失败，当前来源仍可继续用于生成目录。',
    data_package: '资料包生成失败，当前已选来源仍可继续用于生成目录。',
    outline: '目录生成失败，请检查模型配置后重试。',
    directive: '指令文件生成失败，请检查模型配置后重试。',
  }
  return labels[String(props.generationErrorSource || '')] || 'PPT 工作台请求失败，请稍后重试。'
})
const activePackageSource = computed(() => sourceById.value.get(String(activePackageSourceId.value || '')) || null)
const activeDocumentSource = computed(() => sourceById.value.get(String(activeDocumentSourceId.value || '')) || null)
const activeCurrentSource = computed(() => sourceById.value.get(String(activeCurrentSourceId.value || '')) || null)
const activeCurrentAiPayload = computed(() => {
  const meta = activeCurrentSource.value && activeCurrentSource.value.meta && typeof activeCurrentSource.value.meta === 'object'
    ? activeCurrentSource.value.meta
    : {}
  const payload = meta.aiPayload || meta.ai_payload
  return payload && typeof payload === 'object' ? payload : {}
})
const activeCurrentMetrics = computed(() => {
  const metrics = activeCurrentAiPayload.value.metrics
  return Array.isArray(metrics) ? metrics.slice(0, 80) : []
})
const activeCurrentReadyMetrics = computed(() => activeCurrentMetrics.value.filter((metric) => String(metric.status || '') === 'ready'))
const activeCurrentGapMetrics = computed(() => {
  const gaps = activeCurrentAiPayload.value.metric_gaps || activeCurrentAiPayload.value.metricGaps
  return Array.isArray(gaps) ? gaps.slice(0, 80) : []
})
const activeCurrentEvidenceItems = computed(() => {
  const evidence = activeCurrentAiPayload.value.evidence
  return Array.isArray(evidence) ? evidence.slice(0, 80) : []
})
const activeCurrentChartSpecs = computed(() => {
  const charts = activeCurrentAiPayload.value.chart_specs || activeCurrentAiPayload.value.chartSpecs
  return Array.isArray(charts) ? charts.slice(0, 40) : []
})
const activeCurrentScopePayload = computed(() => (
  activeCurrentAiPayload.value.scope && typeof activeCurrentAiPayload.value.scope === 'object'
    ? activeCurrentAiPayload.value.scope
    : null
))
const activeCurrentTransport = computed(() => sourceTransport(activeCurrentSource.value))
const activeDocumentIndexItems = computed(() => {
  const meta = activeDocumentSource.value && activeDocumentSource.value.meta && typeof activeDocumentSource.value.meta === 'object'
    ? activeDocumentSource.value.meta
    : {}
  const items = meta.document_index_preview || meta.documentIndexPreview
  return Array.isArray(items) ? items.slice(0, 40) : []
})
const activePackageDetail = computed(() => normalizePptPackageDetail(activePackageSource.value, {
  focusId: activePackageCarrierId.value,
  extentMode: activePackageCarrierPreviewMode.value,
}))
const activePackageSelectedCarrier = computed(() => {
  const activeId = String(activePackageCarrierId.value || '')
  return activePackageDetail.value.carriers.find((carrier) => String(carrier.carrier_id || '') === activeId)
    || activePackageDetail.value.carriers[0]
    || null
})
const activeFlowIndex = computed(() => {
  if (props.currentStep === 'outline_generating') return 1
  if (['outline_ready', 'directive_generating'].includes(props.currentStep)) return 2
  if (props.currentStep === 'directive_draft') return 3
  return 0
})
const canViewOutlineStep = computed(() => hasOutline.value)
const canViewDirectiveStep = computed(() => hasDirective.value)
const isViewingMaterials = computed(() => flowViewMode.value === 'materials' && (hasOutline.value || hasDirective.value))
const isViewingOutline = computed(() => flowViewMode.value === 'outline' && hasOutline.value)
const isViewingDirective = computed(() => flowViewMode.value === 'directive' && hasDirective.value)
const shouldShowConfigPanel = computed(() => !hasOutline.value || isViewingMaterials.value)
const shouldShowDirectiveRows = computed(() => hasDirective.value && !isViewingMaterials.value && !isViewingOutline.value)
const outlineRows = computed(() => {
  if (shouldShowDirectiveRows.value && props.slides.length) {
    return props.slides.map((item, index) => ({
      id: item.id || `slide-${index + 1}`,
      pageNo: item.index || index + 1,
      title: item.title || `页面 ${index + 1}`,
      detail: item.purpose || '逐页指令草稿',
      fields: [
        ['核心文案', item.keyMessage],
        ['页面提示', item.visualPlan],
        ['素材要求', Array.isArray(item.requiredSources) ? item.requiredSources.join(' / ') : item.requiredSources],
        ['讲稿提示', item.speakerNotes],
      ].filter((field) => String(field[1] || '').trim()),
      metricClaims: Array.isArray(item.metricClaims) ? item.metricClaims : [],
      metricGaps: Array.isArray(item.metricGaps) ? item.metricGaps : [],
      chartSpecs: Array.isArray(item.chartSpecs) ? item.chartSpecs : [],
      chartArtifacts: Array.isArray(item.chartArtifacts) ? item.chartArtifacts : [],
      mode: 'directive',
    }))
  }
  if (hasOutline.value) {
    return props.outline.map((item, index) => ({
      id: item.id || `outline-${index + 1}`,
      pageNo: item.pageNo || index + 1,
      title: item.theme || `页面 ${index + 1}`,
      detail: item.purpose || '目录草稿',
      fields: [],
      mode: 'outline',
    }))
  }
  return []
})

function showFlowView(mode = '') {
  if (mode === 'materials' && (hasOutline.value || hasDirective.value)) flowViewMode.value = 'materials'
  if (mode === 'outline' && hasOutline.value) flowViewMode.value = 'outline'
  if (mode === 'directive' && hasDirective.value) flowViewMode.value = 'directive'
}
const activeRevisionTarget = computed(() => props.activeRevisionTarget && typeof props.activeRevisionTarget === 'object' ? props.activeRevisionTarget : {})
const activeRevisionType = computed(() => String(activeRevisionTarget.value.type || ''))
const revisionDrawerOpen = computed(() => activeRevisionType.value === 'outline' || activeRevisionType.value === 'directive')
const activeRevisionTitle = computed(() => activeRevisionType.value === 'directive' ? '修改逐页指令' : '修改目录小节')
const activeRevisionDraft = computed(() => activeRevisionType.value === 'directive' ? props.directiveRevisionDraft : props.outlineRevisionDraft)
const activeRevisionNote = computed(() => String((activeRevisionDraft.value || {}).revisionNote || '').trim())
const canAiRegenerateRevision = computed(() => !!activeRevisionNote.value && !isCurrentRevisionGenerating.value)
const staleDirectivePageIdSet = computed(() => new Set((props.staleDirectivePageIds || []).map((item) => String(Number(item) || item))))
const revisionGeneratingKey = computed(() => revisionTargetKey(props.revisionGeneratingTarget || {}))
const activeRevisionKey = computed(() => revisionTargetKey(activeRevisionTarget.value))
const isCurrentRevisionGenerating = computed(() => !!activeRevisionKey.value && activeRevisionKey.value === revisionGeneratingKey.value)

function revisionTargetKey(target = {}) {
  const type = String(target.type || '')
  if (type === 'directive') return `slide:${Number(target.index || target.pageNo || 0) || 0}`
  if (type === 'outline') return `outline:${String(target.id || '') || (Number(target.pageNo || 0) || 0)}`
  return ''
}

function rowRevisionKey(row = {}) {
  if (row.mode === 'directive') return `slide:${Number(row.pageNo || 0) || 0}`
  return `outline:${String(row.id || '') || (Number(row.pageNo || 0) || 0)}`
}

function canUndoRow(row = {}) {
  return !!(props.revisionSnapshots || {})[rowRevisionKey(row)]
}

function isRowGenerating(row = {}) {
  return rowRevisionKey(row) === revisionGeneratingKey.value
}

function isDirectiveRowStale(row = {}) {
  return row.mode === 'directive' && staleDirectivePageIdSet.value.has(String(Number(row.pageNo || 0) || 0))
}

function formatMetricClaimValue(claim = {}) {
  const value = claim.value
  const unit = claim.unit || ''
  if (value === undefined || value === null || value === '') return claim.text || ''
  const number = Number(value)
  const formatted = Number.isFinite(number)
    ? (Math.abs(number) >= 100 ? number.toLocaleString('zh-CN', { maximumFractionDigits: 0 }) : number.toLocaleString('zh-CN', { maximumFractionDigits: 3 }))
    : String(value)
  return `${formatted}${unit || ''}`
}

function chartArtifactFor(row = {}, chart = {}) {
  const chartId = String(chart.chart_id || chart.chartId || '')
  return (row.chartArtifacts || []).find((item) => String(item.chart_id || item.chartId || '') === chartId) || {}
}

function chartPreviewUrl(row = {}, chart = {}) {
  const artifact = chartArtifactFor(row, chart)
  return artifact.url || ''
}

function chartRowsPreview(chart = {}) {
  return Array.isArray(chart.rows) ? chart.rows.slice(0, 4) : []
}

function chartColumnsPreview(chart = {}) {
  return Array.isArray(chart.columns) ? chart.columns.slice(0, 4) : []
}

function chartColumnKey(column = {}) {
  if (column && typeof column === 'object') return column.key || column.field || column.label || ''
  return String(column || '')
}

function chartColumnLabel(column = {}) {
  if (column && typeof column === 'object') return column.label || column.key || column.field || ''
  return String(column || '')
}

function openRevisionForRow(row = {}) {
  emit('open-revision-target', row.mode === 'directive' ? 'directive' : 'outline', {
    id: row.id,
    pageNo: row.pageNo,
    index: row.pageNo,
  })
}

function updateRevisionDraft(field = '', value = '') {
  if (!activeRevisionType.value) return
  emit('update-revision-draft', activeRevisionType.value, field, value)
}

function saveCurrentRevision() {
  if (!activeRevisionType.value || isCurrentRevisionGenerating.value) return
  emit('save-revision', activeRevisionType.value)
}

function regenerateCurrentRevision() {
  if (!canAiRegenerateRevision.value) return
  emit('regenerate-revision', activeRevisionType.value)
}

function undoRowRevision(row = {}) {
  if (!canUndoRow(row)) return
  emit('undo-revision', row.mode === 'directive' ? 'directive' : 'outline', {
    id: row.id,
    pageNo: row.pageNo,
    index: row.pageNo,
  })
}

function isGroupSelected(group = {}) {
  const readyItems = (group.items || []).filter((source) => source.status === 'ready')
  return readyItems.length > 0 && readyItems.every((source) => !!source.selected)
}

function toggleGroupSelected(group = {}) {
  emit('set-source-group-selected', group.id, !isGroupSelected(group))
}

function getSourceMenuPosition(event, kind = '') {
  const target = event?.currentTarget
  if (!target || typeof target.getBoundingClientRect !== 'function') {
    return { placement: 'below', x: 0, y: 0 }
  }
  const buttonRect = target.getBoundingClientRect()
  const panelRect = target.closest('.agent-ppt-sources-panel')?.getBoundingClientRect()
  const viewportHeight = typeof window === 'undefined' ? 0 : window.innerHeight
  const boundaryBottom = panelRect?.bottom || viewportHeight
  const boundaryTop = panelRect?.top || 0
  const spaceBelow = boundaryBottom - buttonRect.bottom
  const spaceAbove = buttonRect.top - boundaryTop
  const estimatedMenuHeight = kind === 'source' ? 240 : 128
  const placement = spaceBelow < estimatedMenuHeight && spaceAbove > spaceBelow ? 'above' : 'below'
  return {
    placement,
    x: Math.round(buttonRect.left),
    y: Math.round(placement === 'above' ? buttonRect.top - 4 : buttonRect.bottom + 4),
  }
}

function toggleSourceMenu(kind = '', id = '', event = null) {
  const position = getSourceMenuPosition(event, kind)
  sourceMenu.value = sourceMenu.value.kind === kind && sourceMenu.value.id === id
    ? { kind: '', id: '', placement: 'below', x: 0, y: 0 }
    : { kind, id, ...position }
}

function closeSourceMenu() {
  sourceMenu.value = { kind: '', id: '', placement: 'below', x: 0, y: 0 }
}

function setSourceMenuScrollLock(isLocked = false) {
  if (typeof document === 'undefined') return
  document.documentElement.classList.toggle(sourceMenuLockClass, isLocked)
  document.body?.classList.toggle(sourceMenuLockClass, isLocked)
}

function handleSourceMenuKeydown(event) {
  if (event.key === 'Escape' && activePackageSource.value) closePackageDetail()
  else if (event.key === 'Escape' && activeCurrentSource.value) closeCurrentSourceDetail()
  else if (event.key === 'Escape' && sourceMenu.value.kind) closeSourceMenu()
}

watch(
  () => sourceMenu.value.kind,
  (kind) => setSourceMenuScrollLock(!!kind),
)

onMounted(() => {
  window.addEventListener('keydown', handleSourceMenuKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleSourceMenuKeydown)
  setSourceMenuScrollLock(false)
})

function groupTitle(groupId = '') {
  return (props.sourceGroups.find((group) => String(group.id || '') === String(groupId || '')) || {}).title || '来源'
}

function isPackageSource(source = {}) {
  const meta = source.meta && typeof source.meta === 'object' ? source.meta : {}
  return meta.sourceKind === 'package' || String(source.id || '').startsWith('package:')
}

function isPackagePlaceholderSource(source = {}) {
  const meta = source.meta && typeof source.meta === 'object' ? source.meta : {}
  return meta.sourceKind === 'package-placeholder' || String(source.id || '').startsWith('package-placeholder:')
}

function isDocumentSource(source = {}) {
  const meta = source.meta && typeof source.meta === 'object' ? source.meta : {}
  return meta.sourceKind === 'document' || String(source.id || '').startsWith('document:')
}

function isCurrentSource(source = {}) {
  const meta = source.meta && typeof source.meta === 'object' ? source.meta : {}
  return meta.sourceKind === 'system' && String(source.id || '').startsWith('current:')
}

function sourceTransport(source = {}) {
  const meta = source && source.meta && typeof source.meta === 'object' ? source.meta : {}
  const aiPayload = meta.aiPayload && typeof meta.aiPayload === 'object'
    ? meta.aiPayload
    : meta.ai_payload && typeof meta.ai_payload === 'object'
      ? meta.ai_payload
      : null
  if (aiPayload && aiPayload.version === 'ppt_ai_input_block_v1') {
    return {
      source_id: aiPayload.source_id || source.id,
      sourceId: aiPayload.sourceId || source.id,
      title: aiPayload.title || source.title,
      source_kind: aiPayload.source_kind || aiPayload.sourceKind || meta.sourceKind,
      sourceKind: aiPayload.source_kind || aiPayload.sourceKind || meta.sourceKind,
      transport_status: (Array.isArray(aiPayload.included) && aiPayload.included.length) ? 'ready_to_send' : 'selected_no_payload',
      transportStatus: (Array.isArray(aiPayload.included) && aiPayload.included.length) ? 'ready_to_send' : 'selected_no_payload',
      included: Array.isArray(aiPayload.included) ? aiPayload.included : [],
      metric_count: Number((aiPayload.counts || {}).metrics || 0) || 0,
      metricCount: Number((aiPayload.counts || {}).metrics || 0) || 0,
      metric_gap_count: Number((aiPayload.counts || {}).metric_gaps || 0) || 0,
      metricGapCount: Number((aiPayload.counts || {}).metric_gaps || 0) || 0,
      evidence_count: Number((aiPayload.counts || {}).evidence || 0) || 0,
      evidenceCount: Number((aiPayload.counts || {}).evidence || 0) || 0,
      scope_count: Number((aiPayload.counts || {}).scope || 0) || 0,
      scopeCount: Number((aiPayload.counts || {}).scope || 0) || 0,
      chart_spec_count: Number((aiPayload.counts || {}).chart_specs || 0) || 0,
      chartSpecCount: Number((aiPayload.counts || {}).chart_specs || 0) || 0,
      excluded: Array.isArray(aiPayload.excluded) ? aiPayload.excluded : [],
      policy: aiPayload.policy || '',
      preview: true,
    }
  }
  return meta.transport && typeof meta.transport === 'object' ? meta.transport : null
}

function sourceTransportLabel(source = {}) {
  const transport = sourceTransport(source)
  if (!transport) return ''
  const metricCount = Number(transport.metric_count ?? transport.metricCount ?? 0) || 0
  const evidenceCount = Number(transport.evidence_count ?? transport.evidenceCount ?? 0) || 0
  const scopeCount = Number(transport.scope_count ?? transport.scopeCount ?? 0) || 0
  const chartSpecCount = Number(transport.chart_spec_count ?? transport.chartSpecCount ?? 0) || 0
  const included = Array.isArray(transport.included) ? transport.included : []
  const status = String(transport.transport_status || transport.transportStatus || '')
  if (status === 'ready_to_send') {
    const parts = []
    if (scopeCount || included.includes('scope')) parts.push(`范围 ${scopeCount || 1}`)
    if (metricCount) parts.push(`metrics ${metricCount}`)
    if (evidenceCount) parts.push(`evidence ${evidenceCount}`)
    if (chartSpecCount) parts.push(`charts ${chartSpecCount}`)
    return parts.length ? `已构建 ${parts.join(' / ')}` : '已构建可传内容'
  }
  if (status === 'included' || metricCount || evidenceCount || scopeCount || included.length) {
    const parts = []
    if (scopeCount || included.includes('scope')) parts.push(`范围 ${scopeCount || 1}`)
    if (metricCount) parts.push(`metrics ${metricCount}`)
    if (evidenceCount) parts.push(`evidence ${evidenceCount}`)
    if (chartSpecCount) parts.push(`charts ${chartSpecCount}`)
    return parts.length ? `已传 ${parts.join(' / ')}` : '已传可用内容'
  }
  return '未传：无可用指标/证据'
}

function sourceTransportExcludedItems(source = {}) {
  const transport = sourceTransport(source)
  return transport && Array.isArray(transport.excluded) ? transport.excluded : []
}

function removeSourceMessage(source = {}) {
  if (isDocumentSource(source)) {
    return '确认彻底删除该文档来源？文档库里的原文件、解析结果和 PageIndex 索引都会删除。'
  }
  if (isPackageSource(source)) {
    return '确认从当前 PPT 来源列表删除该资料包？这只影响当前 PPT 工作台。'
  }
  return '确认从当前 PPT 来源列表删除该来源？刷新来源后可重新加入。'
}

function isGeneratingSource(source = {}) {
  return String(source.status || '') === 'generating'
}

function openPackageDetail(source = {}) {
  if (!source.id || !isPackageSource(source)) return
  activePackageSourceId.value = source.id
  closeSourceMenu()
}

function openDocumentEvidence(source = {}) {
  if (!source.id || !isDocumentSource(source)) return
  activeDocumentSourceId.value = source.id
  closeSourceMenu()
}

function openCurrentSourceDetail(source = {}) {
  if (!source.id || !isCurrentSource(source)) return
  activeCurrentSourceId.value = source.id
  closeSourceMenu()
}

function closeCurrentSourceDetail() {
  activeCurrentSourceId.value = ''
}

function closeDocumentEvidence() {
  activeDocumentSourceId.value = ''
}

function closePackageDetail() {
  activePackageSourceId.value = ''
  activePackageCarrierId.value = ''
  activePackageCarrierPreviewMode.value = 'local'
}

function handleSourceRowClick(source = {}) {
  if (isPackagePlaceholderSource(source)) {
    emit('generate-package-source', source.id)
    return
  }
  if (isPackageSource(source)) {
    openPackageDetail(source)
    return
  }
  if (isCurrentSource(source)) {
    openCurrentSourceDetail(source)
    return
  }
  if (isDocumentSource(source) && (
    (Array.isArray((source.meta || {}).document_index_preview) && (source.meta || {}).document_index_preview.length)
  )) {
    openDocumentEvidence(source)
    return
  }
  if (source.status === 'ready') emit('toggle-source', source.id)
}

function formatPackageMetric(value) {
  if (value === undefined || value === null || value === '') return '-'
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(3).replace(/\.?0+$/, '')
  return String(value)
}

function formatCurrentMetricValue(metric = {}) {
  if (metric.value === undefined || metric.value === null || metric.value === '') return '-'
  return `${formatPackageMetric(metric.value)}${metric.unit || ''}`
}

function currentMetricSourceIds(metric = {}) {
  const sourceIds = metric.source_ids || metric.sourceIds
  return Array.isArray(sourceIds) ? sourceIds.filter(Boolean).join(' / ') : (metric.source_id || metric.sourceId || '')
}

function currentGapTitle(gap = {}, index = 0) {
  return gap.label || gap.needed_metric || gap.neededMetric || gap.metric_id || gap.metricId || `缺口指标 ${index + 1}`
}

function currentGapDescription(gap = {}) {
  return gap.description || gap.text || gap.reason || '当前没有可用计算结果。'
}

function currentGapMeta(gap = {}) {
  return [
    gap.source_path || gap.sourcePath,
    gap.source_id || gap.sourceId,
    gap.metric_id || gap.metricId,
  ].filter(Boolean).join(' / ')
}

function packageItemTitle(item = {}, index = 0) {
  return item.name || item.title || item.label || `点位 ${index + 1}`
}

function packageItemSubtitle(item = {}) {
  return [item.category, item.subcategory || item.type].filter(Boolean).join(' / ') || '未分类'
}

function packageItemRadiance(item = {}) {
  const nightlightCell = item.nightlight_cell && typeof item.nightlight_cell === 'object' ? item.nightlight_cell : {}
  return nightlightCell.class_label || nightlightCell.label || formatPackageMetric(nightlightCell.radiance)
}

function carrierMetric(carrier = {}, group = '', key = '') {
  const payload = carrier[group] && typeof carrier[group] === 'object' ? carrier[group] : {}
  return formatPackageMetric(payload[key])
}

function carrierPoiLabel(carrier = {}) {
  const metrics = carrier.poi_metrics && typeof carrier.poi_metrics === 'object' ? carrier.poi_metrics : {}
  const count = metrics.total_related_poi_count ?? 0
  const categories = Array.isArray(metrics.dominant_categories) ? metrics.dominant_categories.slice(0, 2) : []
  const label = categories.map((item) => item.category || item.name).filter(Boolean).join(' / ')
  return label ? `${count} 个 · ${label}` : `${count} 个`
}

function carrierPopulationLabel(carrier = {}) {
  const metrics = carrier.population_metrics && typeof carrier.population_metrics === 'object' ? carrier.population_metrics : {}
  const strength = metrics.demand_strength || '-'
  if (metrics.total_population !== undefined && metrics.total_population !== null) {
    return `总人口 ${formatPackageMetric(metrics.total_population)} · ${strength}`
  }
  const label = metrics.view_label || '人口图层'
  const unit = metrics.unit ? ` ${metrics.unit}` : ''
  return `${label}均值 ${formatPackageMetric(metrics.mean_cell_value)}${unit} · ${strength}`
}

function carrierTypeLabel(carrier = {}) {
  const type = String(carrier.carrier_type || carrier.type || '')
  if (type === 'block_loop') return '街区 / loop'
  if (type === 'corridor') return '廊道'
  return '路段'
}

function selectPackageCarrier(carrierId = '') {
  const normalized = String(carrierId || '')
  if (normalized) activePackageCarrierId.value = normalized
}

function setPackageCarrierPreviewMode(mode = 'local') {
  activePackageCarrierPreviewMode.value = String(mode || '') === 'all' ? 'all' : 'local'
}

function isPackageCarrierActive(carrier = {}) {
  const carrierId = String(carrier.carrier_id || carrier.id || '')
  return !!carrierId && carrierId === String(activePackageCarrierId.value || '')
}

function carrierPreviewClass(item = {}) {
  const hasActive = String(activePackageCarrierId.value || '')
  return {
    'is-active': String(item.id || '') === hasActive,
    'is-muted': !!hasActive && String(item.id || '') !== hasActive,
    [`is-${String(item.type || 'segment')}`]: true,
  }
}

watch(
  () => activePackageDetail.value.carriers,
  (carriers) => {
    const firstCarrierId = String(((carriers || [])[0] || {}).carrier_id || '')
    const currentExists = (carriers || []).some((carrier) => String(carrier.carrier_id || '') === String(activePackageCarrierId.value || ''))
    activePackageCarrierId.value = currentExists ? activePackageCarrierId.value : firstCarrierId
  },
  { immediate: true },
)

watch(
  () => props.sources,
  () => {
    if (activePackageSourceId.value && !sourceById.value.has(String(activePackageSourceId.value))) closePackageDetail()
    if (activeCurrentSourceId.value && !sourceById.value.has(String(activeCurrentSourceId.value))) closeCurrentSourceDetail()
  },
  { deep: true },
)

function openRenameSource(source = {}) {
  sourceDialog.value = { mode: 'rename-source', id: source.id, title: '重命名来源', value: source.title || '', message: '' }
  closeSourceMenu()
}

function openRemoveSource(source = {}) {
  sourceDialog.value = {
    mode: 'remove-source',
    id: source.id,
    title: '删除来源',
    value: '',
    message: removeSourceMessage(source),
  }
  closeSourceMenu()
}

function openRenameGroup(group = {}) {
  sourceDialog.value = { mode: 'rename-group', id: group.id, title: '重命名分类', value: group.title || '', message: '' }
  closeSourceMenu()
}

function openGroupEmoji(group = {}) {
  sourceDialog.value = { mode: 'group-emoji', id: group.id, title: '添加表情符号', value: group.emoji || '', message: '输入一个短图标或表情，留空可清除。' }
  closeSourceMenu()
}

function openRemoveGroup(group = {}) {
  sourceDialog.value = {
    mode: 'remove-group',
    id: group.id,
    title: '移除分类',
    value: '',
    message: `确认移除“${group.title || '未命名分类'}”分类？组内来源会保留并显示为顶层独立来源。`,
  }
  closeSourceMenu()
}

function moveSourceToGroup(sourceId = '', groupId = '') {
  emit('move-source-to-group', sourceId, groupId)
  closeSourceMenu()
}

function moveSourceOutOfGroup(sourceId = '') {
  emit('move-source-to-group', sourceId, '')
  closeSourceMenu()
}

function closeSourceDialog() {
  sourceDialog.value = { mode: '', id: '', title: '', value: '', message: '' }
}

function openDocumentSourcePicker() {
  documentSourceInput.value?.click()
}

function handleDocumentSourceSelected(event) {
  const file = event?.target?.files?.[0]
  if (event?.target) event.target.value = ''
  if (!file) return
  emit('upload-document-source', file)
}

function confirmSourceDialog() {
  const dialog = sourceDialog.value
  if (dialog.mode === 'rename-source') emit('rename-source', dialog.id, dialog.value)
  if (dialog.mode === 'remove-source') emit('remove-source', dialog.id)
  if (dialog.mode === 'rename-group') emit('rename-source-group', dialog.id, dialog.value)
  if (dialog.mode === 'group-emoji') emit('set-source-group-emoji', dialog.id, dialog.value)
  if (dialog.mode === 'remove-group') emit('remove-source-group', dialog.id)
  closeSourceDialog()
}
</script>

<template>
  <div class="agent-ppt-planning-workbench">
    <div
      v-if="sourceMenu.kind"
      class="agent-ppt-source-menu-backdrop"
      aria-hidden="true"
      @click="closeSourceMenu"
      @wheel.prevent
      @touchmove.prevent>
    </div>
    <div class="agent-ppt-notebook" :class="{ 'is-sources-collapsed': isSourcesCollapsed }">
      <aside class="agent-ppt-notebook-panel agent-ppt-sources-panel" :aria-label="sourcePanelLabel">
        <div class="agent-ppt-notebook-head">
          <h3>来源</h3>
          <button
            type="button"
            class="agent-ppt-source-collapse-btn"
            :aria-label="sourcePanelLabel"
            :title="sourcePanelLabel"
            @click="isSourcesCollapsed = !isSourcesCollapsed">
            <svg class="step3-sidebar-toggle-icon" viewBox="0 0 24 24" aria-hidden="true">
              <rect x="3.5" y="4" width="17" height="16" rx="3"></rect>
              <line x1="9" y1="4" x2="9" y2="20"></line>
              <polyline :points="sourceCollapseIconPoints"></polyline>
            </svg>
          </button>
        </div>
        <template v-if="!isSourcesCollapsed">
          <input
            ref="documentSourceInput"
            class="agent-ppt-source-file-input"
            type="file"
            accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            @change="handleDocumentSourceSelected">
          <button type="button" class="agent-ppt-add-source-btn" @click="openDocumentSourcePicker">+ 添加来源</button>
          <div class="agent-ppt-source-search">
            <div class="agent-ppt-source-search-main">
              <span>搜索联网来源</span>
              <div class="agent-ppt-source-search-chips">
                <button type="button" disabled>Web</button>
                <button type="button" disabled>深度研究</button>
              </div>
            </div>
            <button type="button" disabled>搜索</button>
          </div>
          <button
            type="button"
            class="agent-ppt-data-package-btn"
            :disabled="!canCreateDataPackage"
            @click="$emit('create-data-package')">
            {{ dataPackageGenerating ? '整理中' : '生成资料包' }}
          </button>
          <div class="agent-ppt-source-tree-toolbar">
            <button
              type="button"
              class="agent-ppt-source-tag-btn"
              :disabled="sourceGrouping || !sources.length"
              title="重新为来源加标签"
              aria-label="重新为来源加标签"
              @click="$emit('classify-source-groups')">
              <span aria-hidden="true">✧</span>
            </button>
            <button
              type="button"
              class="agent-ppt-source-select-row"
              :class="{ 'is-selected': sourceSummary.ready > 0 && sourceSummary.selected === sourceSummary.ready }"
              @click="$emit('toggle-all-sources')">
              <span>全选</span>
              <span
                class="agent-ppt-source-checkbox"
                :class="{ 'is-checked': sourceSummary.ready > 0 && sourceSummary.selected === sourceSummary.ready }"
                aria-hidden="true">
                {{ sourceSummary.ready > 0 && sourceSummary.selected === sourceSummary.ready ? '✓' : '' }}
              </span>
              <strong>{{ sourceSummary.selected || 0 }}/{{ sourceSummary.total || 0 }}</strong>
            </button>
          </div>
          <div class="agent-ppt-source-list agent-ppt-source-tree">
            <div
              v-for="group in sourceGroupsForTree"
              :key="`ppt-source-group-${group.id}`"
              class="agent-ppt-source-group">
              <div class="agent-ppt-source-group-row">
                <button
                  type="button"
                  class="agent-ppt-source-group-toggle"
                  :class="{ 'is-expanded': !group.collapsed }"
                  :aria-label="group.collapsed ? '展开分类' : '折叠分类'"
                  @click="$emit('toggle-source-group-collapsed', group.id)">
                  <span aria-hidden="true">›</span>
                </button>
                <button
                  type="button"
                  class="agent-ppt-source-group-main"
                  @click="$emit('toggle-source-group-collapsed', group.id)">
                  <span v-if="group.emoji" class="agent-ppt-source-group-emoji">{{ group.emoji }}</span>
                  <strong>{{ group.title }}</strong>
                </button>
                <button
                  type="button"
                  class="agent-ppt-source-menu-btn"
                  aria-label="更多选项"
                  title="更多选项"
                  @click.stop="toggleSourceMenu('group', group.id, $event)">
                  ⋮
                </button>
                <button
                  type="button"
                  class="agent-ppt-source-checkbox"
                  :class="{ 'is-checked': isGroupSelected(group) }"
                  aria-label="切换分类选择"
                  @click.stop="toggleGroupSelected(group)">
                  {{ isGroupSelected(group) ? '✓' : '' }}
                </button>
                <div
                  v-if="sourceMenu.kind === 'group' && sourceMenu.id === group.id"
                  class="agent-ppt-source-menu"
                  :class="{ 'is-above': sourceMenu.placement === 'above' }"
                  :style="{ left: `${sourceMenu.x}px`, top: `${sourceMenu.y}px` }">
                  <button type="button" @click="openRenameGroup(group)">重命名</button>
                  <button type="button" @click="openRemoveGroup(group)">移除</button>
                  <button type="button" @click="openGroupEmoji(group)">添加表情符号</button>
                </div>
              </div>
              <div v-if="!group.collapsed" class="agent-ppt-source-group-items">
                <div
                  v-for="source in group.items"
                  :key="`ppt-source-${source.id}`"
                  class="agent-ppt-source-row"
                  :class="[{ 'is-ready': source.status === 'ready', 'is-generating': isGeneratingSource(source), 'is-pending': source.status !== 'ready', 'is-selected': source.selected }, `is-${source.type || 'file'}`]">
                  <button
                    type="button"
                    class="agent-ppt-source-row-main"
                    :class="{ 'is-inspectable': isPackageSource(source) || isCurrentSource(source) || isDocumentSource(source) }"
                    :aria-pressed="source.status === 'ready' && !isPackageSource(source) && !isCurrentSource(source) && !isDocumentSource(source) ? String(!!source.selected) : undefined"
                    :disabled="source.status !== 'ready' && !isPackageSource(source) && !isCurrentSource(source) && !isDocumentSource(source)"
                    @click="handleSourceRowClick(source)">
                    <span class="agent-ppt-source-icon" :class="`is-${source.type || 'file'}`"></span>
                    <span class="agent-ppt-source-name">
                      <strong>{{ source.title }}</strong>
                      <small>{{ (source.meta && source.meta.label) || (source.status === 'ready' ? '已生成' : '待生成') }}</small>
                      <em v-if="sourceTransportLabel(source)">{{ sourceTransportLabel(source) }}</em>
                    </span>
                  </button>
                  <button
                    type="button"
                    class="agent-ppt-source-menu-btn"
                    aria-label="更多选项"
                    title="更多选项"
                    @click.stop="toggleSourceMenu('source', source.id, $event)">
                    ⋮
                  </button>
                  <button
                    v-if="source.status === 'ready'"
                    type="button"
                    class="agent-ppt-source-checkbox"
                    :class="{ 'is-checked': source.selected }"
                    aria-label="切换来源选择"
                    @click.stop="$emit('toggle-source', source.id)">
                    {{ source.selected ? '✓' : '' }}
                  </button>
                  <span v-else class="agent-ppt-source-loading" :class="{ 'is-generating': isGeneratingSource(source) }" aria-label="未就绪"></span>
                  <div
                    v-if="sourceMenu.kind === 'source' && sourceMenu.id === source.id"
                    class="agent-ppt-source-menu"
                    :class="{ 'is-above': sourceMenu.placement === 'above' }"
                    :style="{ left: `${sourceMenu.x}px`, top: `${sourceMenu.y}px` }">
                    <button v-if="isPackagePlaceholderSource(source)" type="button" @click="$emit('generate-package-source', source.id)">生成资料包</button>
                    <button v-else-if="isPackageSource(source)" type="button" @click="openPackageDetail(source)">查看内容</button>
                    <button v-if="isCurrentSource(source)" type="button" @click="openCurrentSourceDetail(source)">查看分析</button>
                    <button
                      v-if="isDocumentSource(source)"
                      type="button"
                      :disabled="!(((source.meta && source.meta.document_index_preview) || []).length)"
                      @click="openDocumentEvidence(source)">
                      查看结构
                    </button>
                    <div class="agent-ppt-source-move-menu">
                      <button type="button" class="agent-ppt-source-move-trigger" aria-haspopup="true">
                        <span aria-hidden="true"></span>
                        移至
                      </button>
                      <div class="agent-ppt-source-move-panel">
                        <button
                          v-for="targetGroup in sourceGroupsForTree"
                          :key="`move-${source.id}-${targetGroup.id}`"
                          type="button"
                          :disabled="targetGroup.sourceIds.includes(source.id)"
                          @click="moveSourceToGroup(source.id, targetGroup.id)">
                          {{ groupTitle(targetGroup.id) }}
                        </button>
                      </div>
                    </div>
                    <button
                      type="button"
                      @click="moveSourceOutOfGroup(source.id)">
                      移出分组
                    </button>
                    <button type="button" @click="openRenameSource(source)">重命名来源</button>
                  </div>
                </div>
              </div>
            </div>
            <div
              v-for="source in ungroupedSources"
              :key="`ppt-source-ungrouped-${source.id}`"
              class="agent-ppt-source-row"
              :class="[{ 'is-ready': source.status === 'ready', 'is-generating': isGeneratingSource(source), 'is-pending': source.status !== 'ready', 'is-selected': source.selected }, `is-${source.type || 'file'}`]">
              <button
                type="button"
                class="agent-ppt-source-row-main"
                :class="{ 'is-inspectable': isPackageSource(source) || isCurrentSource(source) || isDocumentSource(source) }"
                :aria-pressed="source.status === 'ready' && !isPackageSource(source) && !isCurrentSource(source) && !isDocumentSource(source) ? String(!!source.selected) : undefined"
                :disabled="source.status !== 'ready' && !isPackageSource(source) && !isCurrentSource(source) && !isDocumentSource(source)"
                @click="handleSourceRowClick(source)">
                <span class="agent-ppt-source-icon" :class="`is-${source.type || 'file'}`"></span>
                <span class="agent-ppt-source-name">
                  <strong>{{ source.title }}</strong>
                  <small>{{ (source.meta && source.meta.label) || (source.status === 'ready' ? '已生成' : '待生成') }}</small>
                  <em v-if="sourceTransportLabel(source)">{{ sourceTransportLabel(source) }}</em>
                </span>
              </button>
              <button
                type="button"
                class="agent-ppt-source-menu-btn"
                aria-label="更多选项"
                title="更多选项"
                @click.stop="toggleSourceMenu('source', source.id, $event)">
                ⋮
              </button>
              <button
                v-if="source.status === 'ready'"
                type="button"
                class="agent-ppt-source-checkbox"
                :class="{ 'is-checked': source.selected }"
                aria-label="切换来源选择"
                @click.stop="$emit('toggle-source', source.id)">
                {{ source.selected ? '✓' : '' }}
              </button>
              <span v-else class="agent-ppt-source-loading" :class="{ 'is-generating': isGeneratingSource(source) }" aria-label="未就绪"></span>
              <div
                v-if="sourceMenu.kind === 'source' && sourceMenu.id === source.id"
                class="agent-ppt-source-menu"
                :class="{ 'is-above': sourceMenu.placement === 'above' }"
                :style="{ left: `${sourceMenu.x}px`, top: `${sourceMenu.y}px` }">
                <button v-if="isPackagePlaceholderSource(source)" type="button" @click="$emit('generate-package-source', source.id)">生成资料包</button>
                <button v-else-if="isPackageSource(source)" type="button" @click="openPackageDetail(source)">查看内容</button>
                <button v-if="isCurrentSource(source)" type="button" @click="openCurrentSourceDetail(source)">查看分析</button>
                <button
                  v-if="isDocumentSource(source)"
                  type="button"
                  :disabled="!(((source.meta && source.meta.document_index_preview) || []).length)"
                  @click="openDocumentEvidence(source)">
                  查看结构
                </button>
                <div class="agent-ppt-source-move-menu">
                  <button type="button" class="agent-ppt-source-move-trigger" aria-haspopup="true">
                    <span aria-hidden="true"></span>
                    移至
                  </button>
                  <div class="agent-ppt-source-move-panel">
                    <button
                      v-for="targetGroup in sourceGroupsForTree"
                      :key="`move-ungrouped-${source.id}-${targetGroup.id}`"
                      type="button"
                      @click="moveSourceToGroup(source.id, targetGroup.id)">
                      {{ groupTitle(targetGroup.id) }}
                    </button>
                  </div>
                </div>
                <button type="button" @click="openRemoveSource(source)">删除来源</button>
                <button type="button" @click="openRenameSource(source)">重命名来源</button>
              </div>
            </div>
            <div v-if="!hasVisibleSources" class="agent-ppt-source-empty">暂无可用来源。</div>
          </div>
        </template>
        <button
          v-else
          type="button"
          class="agent-ppt-source-collapsed-summary"
          aria-label="展开来源"
          @click="isSourcesCollapsed = false">
          <span>来源</span>
          <strong>{{ sourceSummary.selected || 0 }}</strong>
        </button>
      </aside>

      <section class="agent-ppt-notebook-panel agent-ppt-document-panel" aria-label="指令文件">
        <div class="agent-ppt-notebook-head">
          <h3>指令文件</h3>
          <span>{{ spec.pageCount || 15 }} 页（可配置） · {{ spec.audience || '政府评审' }}</span>
        </div>
        <div class="agent-ppt-flow-strip" aria-label="PPT 生成流程">
          <button
            type="button"
            :class="{ 'is-current': activeFlowIndex === 0 || isViewingMaterials, 'is-complete': activeFlowIndex > 0 && !isViewingMaterials }"
            :disabled="activeFlowIndex === 0"
            @click="showFlowView('materials')">
            配置
          </button>
          <button
            type="button"
            :class="{
              'is-current': !isViewingMaterials && (activeFlowIndex === 1 || isViewingOutline || (activeFlowIndex === 2 && !isViewingDirective)),
              'is-complete': hasOutline && activeFlowIndex > 1 && !isViewingOutline
            }"
            :disabled="!canViewOutlineStep"
            @click="showFlowView('outline')">
            生成目录
          </button>
          <button
            type="button"
            :class="{ 'is-current': !isViewingMaterials && !isViewingOutline && (activeFlowIndex === 2 || activeFlowIndex === 3 || isViewingDirective), 'is-complete': hasDirective && !isViewingDirective }"
            :disabled="!canViewDirectiveStep"
            @click="showFlowView('directive')">
            生成指令
          </button>
          <button type="button" disabled>选择风格</button>
          <button type="button" :class="{ 'is-current': activeFlowIndex === 4 }" disabled>生成页面</button>
          <button type="button" :class="{ 'is-current': activeFlowIndex === 5 }" disabled>导出</button>
        </div>
        <div class="agent-ppt-directive-summary">
          <div>
            <span>主题</span>
            <strong>{{ spec.topic || '未配置' }}</strong>
          </div>
          <div>
            <span>页数</span>
            <strong>{{ spec.pageCount || 15 }}（可配置）</strong>
          </div>
          <div>
            <span>受众</span>
            <strong>{{ spec.audience || '政府评审' }}</strong>
          </div>
          <div>
            <span>资料</span>
            <strong>{{ sourceSummary.selected || 0 }} 个已选来源</strong>
          </div>
        </div>
        <div class="agent-ppt-main-scroll">
          <details v-if="shouldShowGenerationJobPanel" class="agent-ppt-generation-job" open>
            <summary>
              <span>{{ generationJobTitle }}</span>
              <small>{{ generationJobSummary || activeGenerationJob.id || '等待状态更新' }}</small>
            </summary>
            <ol>
              <li
                v-for="(event, eventIndex) in generationJobEvents"
                :key="`ppt-generation-event-${eventIndex}-${event.name}`">
                <strong>{{ event.name }}</strong>
                <span>{{ event.at }}</span>
              </li>
            </ol>
          </details>
          <div v-if="shouldShowConfigPanel" class="agent-ppt-target-config-panel">
            <div class="agent-ppt-target-config-head">
              <strong>配置生成目标</strong>
              <span v-if="generationErrorText">{{ generationErrorTitle }}</span>
              <span v-else>确认主题、页数、受众和来源后生成 PPT 目录。</span>
            </div>
            <label class="agent-ppt-config-field">
              <span>主题</span>
              <input
                type="text"
                :value="spec.topic || ''"
                placeholder="输入 PPT 主题"
                @input="$emit('update-spec-field', 'topic', $event.target.value)">
            </label>
            <div class="agent-ppt-target-config-grid">
              <label class="agent-ppt-config-field">
                <span>页数</span>
                <input
                  type="number"
                  min="1"
                  max="80"
                  :value="spec.pageCount || 15"
                  @input="$emit('update-spec-field', 'pageCount', $event.target.value)">
              </label>
              <label class="agent-ppt-config-field">
                <span>受众</span>
                <input
                  type="text"
                  :value="spec.audience || '政府评审'"
                  @input="$emit('update-spec-field', 'audience', $event.target.value)">
              </label>
              <div class="agent-ppt-config-field is-readonly">
                <span>资料</span>
                <strong>{{ sourceSummary.selected || 0 }} 个已选来源</strong>
              </div>
            </div>
          </div>
          <div v-else class="agent-ppt-directive-doc">
            <details v-if="hasGenerationResponsePayload" class="agent-ppt-generation-response">
              <summary>
                <span>{{ generationResponseTitle }}</span>
                <small>{{ generationResponseSummary || '点击查看原始 JSON' }}</small>
              </summary>
              <pre>{{ generationResponseJson }}</pre>
            </details>
            <div
              v-for="row in outlineRows"
              :key="`ppt-directive-row-${row.id}`"
              class="agent-ppt-directive-row"
              :class="{ 'is-draft': row.mode === 'outline', 'is-directive': row.mode === 'directive' }">
              <span class="agent-ppt-directive-page">{{ String(row.pageNo).padStart(2, '0') }}</span>
              <div class="agent-ppt-directive-content">
                <strong>{{ row.title }}</strong>
                <em>{{ row.detail }}</em>
                <span v-if="isDirectiveRowStale(row)" class="agent-ppt-revision-stale">目录已变更，建议重生成本页指令</span>
                <dl v-if="row.fields.length" class="agent-ppt-directive-fields">
                  <div
                    v-for="field in row.fields"
                    :key="`ppt-directive-field-${row.id}-${field[0]}`">
                    <dt>{{ field[0] }}</dt>
                    <dd>{{ field[1] }}</dd>
                  </div>
                </dl>
                <div v-if="row.metricClaims.length" class="agent-ppt-metric-claims">
                  <span>数值证据</span>
                  <article
                    v-for="claim in row.metricClaims"
                    :key="`metric-claim-${row.id}-${claim.claim_id || claim.claimId || claim.metric_id || claim.metricId}`">
                    <strong>{{ formatMetricClaimValue(claim) }}</strong>
                    <p>{{ claim.text || claim.usage || '已绑定数值证据' }}</p>
                    <small>
                      {{ claim.source_id || claim.sourceId || '来源' }}
                      <template v-if="claim.status || claim.scope || claim.spatial_scope || claim.spatialScope"> · {{ claim.status || 'ready' }} · {{ claim.scope || claim.spatial_scope || claim.spatialScope }}</template>
                      <template v-if="claim.source_path || claim.sourcePath"> · {{ claim.source_path || claim.sourcePath }}</template>
                    </small>
                    <small>{{ claim.calculation_method || claim.calculationMethod || claim.method || '已有分析指标' }}</small>
                  </article>
                </div>
                <div v-if="row.metricGaps.length" class="agent-ppt-metric-gaps">
                  <span>数值缺口</span>
                  <p
                    v-for="gap in row.metricGaps"
                    :key="`metric-gap-${row.id}-${gap.gap_id || gap.gapId || gap.text}`">
                    {{ gap.text || gap.reason || gap.needed_metric || gap.neededMetric }}
                  </p>
                </div>
                <div v-if="row.chartSpecs.length" class="agent-ppt-chart-specs">
                  <span>图表规格</span>
                  <article
                    v-for="chart in row.chartSpecs"
                    :key="`chart-spec-${row.id}-${chart.chart_id || chart.chartId || chart.title}`">
                    <header>
                      <strong>{{ chart.title || '图表' }}</strong>
                      <small>{{ chart.chart_type || chart.chartType || 'chart' }} · {{ (chart.rows || []).length }} 行</small>
                    </header>
                    <img
                      v-if="chartPreviewUrl(row, chart)"
                      :src="chartPreviewUrl(row, chart)"
                      :alt="chart.title || '图表预览'">
                    <table>
                      <thead>
                        <tr>
                          <th
                            v-for="column in chartColumnsPreview(chart)"
                            :key="`chart-column-${row.id}-${chart.chart_id || chart.chartId}-${chartColumnKey(column)}`">
                            {{ chartColumnLabel(column) }}
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr
                          v-for="(chartRow, chartRowIndex) in chartRowsPreview(chart)"
                          :key="`chart-row-${row.id}-${chart.chart_id || chart.chartId}-${chartRowIndex}`">
                          <td
                            v-for="column in chartColumnsPreview(chart)"
                            :key="`chart-cell-${row.id}-${chart.chart_id || chart.chartId}-${chartRowIndex}-${chartColumnKey(column)}`">
                            {{ chartRow[chartColumnKey(column)] }}
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </article>
                </div>
              </div>
              <div class="agent-ppt-row-actions">
                <button
                  type="button"
                  :disabled="isRowGenerating(row)"
                  @click="openRevisionForRow(row)">
                  编辑
                </button>
                <button
                  type="button"
                  :disabled="isRowGenerating(row)"
                  @click="openRevisionForRow(row)">
                  AI 重生成
                </button>
                <button
                  type="button"
                  :disabled="!canUndoRow(row) || isRowGenerating(row)"
                  @click="undoRowRevision(row)">
                  撤回
                </button>
              </div>
            </div>
          </div>
        </div>
        <div class="agent-ppt-prompt-box">
          <span v-if="generationErrorText">{{ generationErrorText }}</span>
          <span v-else-if="isGenerationJobActive">{{ generationJobTitle }}</span>
          <span v-else-if="!hasOutline && outlineBlockReason">{{ outlineBlockReason }}</span>
          <span v-else-if="!hasOutline">先生成目录，再生成逐页指令文件</span>
          <span v-else-if="!hasDirective">目录已生成，下一步生成逐页指令</span>
          <span v-else-if="isViewingOutline">正在查看目录；如需调整目录，可重新生成目录。</span>
          <span v-else>指令草稿已生成；下一阶段暂未开放，可按需重新生成指令文件。</span>
          <div class="agent-ppt-prompt-actions">
            <button
              v-if="!hasOutline"
              type="button"
              class="is-primary"
              :disabled="!canGenerateOutline"
              @click="$emit('generate-outline')">
              {{ isOutlineGenerating || (isGenerationJobActive && generationJobType === 'outline') ? (generationJobTitle || '目录生成中') : '生成目录' }}
            </button>
            <template v-else-if="!hasDirective">
              <button
                type="button"
                class="is-primary"
                :disabled="!canGenerateDirective"
                @click="$emit('generate-directive')">
                {{ isDirectiveGenerating || (isGenerationJobActive && generationJobType === 'directive') ? (generationJobTitle || '指令生成中') : '生成指令文件' }}
              </button>
              <button
                type="button"
                :disabled="isOutlineGenerating || isDirectiveGenerating"
                @click="$emit('regenerate-outline')">
                重新生成目录
              </button>
            </template>
            <template v-else-if="isViewingOutline">
              <button
                type="button"
                :disabled="isOutlineGenerating || isDirectiveGenerating"
                @click="$emit('regenerate-outline')">
                重新生成目录
              </button>
            </template>
            <template v-else>
              <button type="button" class="is-primary" disabled>下一阶段暂未开放</button>
              <button
                type="button"
                :disabled="isOutlineGenerating || isDirectiveGenerating"
                @click="$emit('regenerate-directive')">
                重新生成指令文件
              </button>
            </template>
          </div>
        </div>
      </section>
    </div>

    <div v-if="revisionDrawerOpen" class="agent-ppt-revision-backdrop" @click.self="$emit('close-revision-target')">
      <section class="agent-ppt-revision-drawer" role="dialog" aria-modal="true" :aria-label="activeRevisionTitle">
        <header class="agent-ppt-revision-head">
          <div>
            <span>{{ activeRevisionType === 'directive' ? '逐页指令' : '目录小节' }}</span>
            <strong>{{ activeRevisionTitle }}</strong>
          </div>
          <button type="button" aria-label="关闭" title="关闭" @click="$emit('close-revision-target')">×</button>
        </header>

        <div v-if="activeRevisionType === 'outline'" class="agent-ppt-revision-fields">
          <label class="agent-ppt-config-field">
            <span>小节标题</span>
            <input
              type="text"
              :value="outlineRevisionDraft.theme || ''"
              :disabled="isCurrentRevisionGenerating"
              @input="updateRevisionDraft('theme', $event.target.value)">
          </label>
          <label class="agent-ppt-config-field">
            <span>小节目的</span>
            <textarea
              rows="4"
              :value="outlineRevisionDraft.purpose || ''"
              :disabled="isCurrentRevisionGenerating"
              @input="updateRevisionDraft('purpose', $event.target.value)"></textarea>
          </label>
        </div>

        <div v-else class="agent-ppt-revision-fields">
          <label class="agent-ppt-config-field">
            <span>页面标题</span>
            <input
              type="text"
              :value="directiveRevisionDraft.title || ''"
              :disabled="isCurrentRevisionGenerating"
              @input="updateRevisionDraft('title', $event.target.value)">
          </label>
          <label class="agent-ppt-config-field">
            <span>页面目的</span>
            <textarea
              rows="3"
              :value="directiveRevisionDraft.purpose || ''"
              :disabled="isCurrentRevisionGenerating"
              @input="updateRevisionDraft('purpose', $event.target.value)"></textarea>
          </label>
          <label class="agent-ppt-config-field">
            <span>核心文案</span>
            <textarea
              rows="3"
              :value="directiveRevisionDraft.keyMessage || ''"
              :disabled="isCurrentRevisionGenerating"
              @input="updateRevisionDraft('keyMessage', $event.target.value)"></textarea>
          </label>
          <label class="agent-ppt-config-field">
            <span>页面提示</span>
            <textarea
              rows="3"
              :value="directiveRevisionDraft.visualPlan || ''"
              :disabled="isCurrentRevisionGenerating"
              @input="updateRevisionDraft('visualPlan', $event.target.value)"></textarea>
          </label>
          <label class="agent-ppt-config-field">
            <span>素材要求</span>
            <input
              type="text"
              :value="directiveRevisionDraft.requiredSources || ''"
              :disabled="isCurrentRevisionGenerating"
              placeholder="用逗号分隔来源 id"
              @input="updateRevisionDraft('requiredSources', $event.target.value)">
          </label>
          <label class="agent-ppt-config-field">
            <span>讲稿提示</span>
            <textarea
              rows="4"
              :value="directiveRevisionDraft.speakerNotes || ''"
              :disabled="isCurrentRevisionGenerating"
              @input="updateRevisionDraft('speakerNotes', $event.target.value)"></textarea>
          </label>
        </div>

        <label class="agent-ppt-config-field">
          <span>AI 修改建议</span>
          <textarea
            rows="4"
            :value="activeRevisionDraft.revisionNote || ''"
            :disabled="isCurrentRevisionGenerating"
            placeholder="写清楚希望这一小节如何调整"
            @input="updateRevisionDraft('revisionNote', $event.target.value)"></textarea>
        </label>

        <div class="agent-ppt-revision-actions">
          <button type="button" :disabled="isCurrentRevisionGenerating" @click="saveCurrentRevision">保存人工修改</button>
          <button type="button" :disabled="!canAiRegenerateRevision" @click="regenerateCurrentRevision">
            {{ isCurrentRevisionGenerating ? 'AI 重生成中' : 'AI 重生成此小节' }}
          </button>
        </div>
      </section>
    </div>

    <div v-if="activeCurrentSource" class="agent-ppt-package-detail-backdrop" @click.self="closeCurrentSourceDetail">
      <section
        class="agent-ppt-package-detail agent-ppt-current-source-detail"
        role="dialog"
        aria-modal="true"
        aria-label="当前分析来源">
        <header class="agent-ppt-package-detail-head">
          <div>
            <span>当前分析来源</span>
            <strong>{{ activeCurrentSource.title }}</strong>
            <small>{{ (activeCurrentSource.meta && activeCurrentSource.meta.label) || (activeCurrentSource.status === 'ready' ? '已生成' : '待生成') }}</small>
            <em v-if="sourceTransportLabel(activeCurrentSource)">{{ sourceTransportLabel(activeCurrentSource) }}</em>
          </div>
          <button type="button" aria-label="关闭" title="关闭" @click="closeCurrentSourceDetail">×</button>
        </header>

        <div class="agent-ppt-package-stats">
          <div>
            <span>Ready 指标</span>
            <strong>{{ activeCurrentReadyMetrics.length }}</strong>
          </div>
          <div>
            <span>缺口</span>
            <strong>{{ activeCurrentGapMetrics.length }}</strong>
          </div>
          <div>
            <span>状态</span>
            <strong>{{ activeCurrentSource.status === 'ready' ? '已生成' : '待生成' }}</strong>
          </div>
          <div>
            <span>本次传入</span>
            <strong>{{ sourceTransportLabel(activeCurrentSource) || '尚未生成' }}</strong>
          </div>
        </div>

        <div v-if="activeCurrentTransport" class="agent-ppt-current-transport">
          <div class="agent-ppt-package-section-head">
            <strong>传给 AI 的内容</strong>
            <span>{{ activeCurrentTransport.policy || '数字只来自 current.metrics；原始大数据不直传。' }}</span>
          </div>
          <div class="agent-ppt-current-transport-grid">
            <article>
              <span>已包含</span>
              <strong>{{ (activeCurrentTransport.included || []).join(' / ') || '无' }}</strong>
            </article>
            <article>
              <span>范围</span>
              <strong>{{ Number(activeCurrentTransport.scope_count ?? activeCurrentTransport.scopeCount ?? 0) || 0 }}</strong>
            </article>
            <article>
              <span>指标</span>
              <strong>{{ Number(activeCurrentTransport.metric_count ?? activeCurrentTransport.metricCount ?? 0) || 0 }}</strong>
            </article>
            <article>
              <span>证据</span>
              <strong>{{ Number(activeCurrentTransport.evidence_count ?? activeCurrentTransport.evidenceCount ?? 0) || 0 }}</strong>
            </article>
            <article>
              <span>图表规格</span>
              <strong>{{ Number(activeCurrentTransport.chart_spec_count ?? activeCurrentTransport.chartSpecCount ?? 0) || 0 }}</strong>
            </article>
          </div>
          <div v-if="sourceTransportExcludedItems(activeCurrentSource).length" class="agent-ppt-current-transport-excluded">
            <strong>未传内容</strong>
            <p
              v-for="(item, index) in sourceTransportExcludedItems(activeCurrentSource)"
              :key="`current-excluded-${index}`">
              {{ item.type || 'payload' }}：{{ item.reason || '为避免上下文超限，未直接传入。' }}
            </p>
          </div>
        </div>

        <div v-if="activeCurrentScopePayload" class="agent-ppt-package-section-head">
          <strong>范围输入</strong>
          <span>scope</span>
        </div>
        <div v-if="activeCurrentScopePayload" class="agent-ppt-current-metric-list">
          <article class="agent-ppt-current-metric-card">
            <dl>
              <div v-for="(value, key) in activeCurrentScopePayload" :key="`scope-${key}`">
                <dt>{{ key }}</dt>
                <dd>{{ Array.isArray(value) ? value.join(', ') : value }}</dd>
              </div>
            </dl>
          </article>
        </div>

        <div v-if="activeCurrentReadyMetrics.length" class="agent-ppt-package-section-head">
          <strong>可用于 PPT 的数值指标</strong>
          <span>{{ activeCurrentReadyMetrics.length }} 项</span>
        </div>
        <div v-if="activeCurrentReadyMetrics.length" class="agent-ppt-current-metric-list">
          <article
            v-for="metric in activeCurrentReadyMetrics"
            :key="`current-ready-${metric.metric_id}`"
            class="agent-ppt-current-metric-card">
            <header>
              <div>
                <span>{{ metric.domain || 'analysis' }}</span>
                <strong>{{ metric.label }}</strong>
              </div>
              <b>{{ formatCurrentMetricValue(metric) }}</b>
            </header>
            <dl>
              <div v-if="metric.calculation_method || metric.calculationMethod || metric.method">
                <dt>口径</dt>
                <dd>{{ metric.calculation_method || metric.calculationMethod || metric.method }}</dd>
              </div>
              <div v-if="metric.scope">
                <dt>范围</dt>
                <dd>{{ metric.scope }}</dd>
              </div>
              <div v-if="metric.source_path || metric.sourcePath">
                <dt>路径</dt>
                <dd>{{ metric.source_path || metric.sourcePath }}</dd>
              </div>
              <div v-if="currentMetricSourceIds(metric)">
                <dt>绑定来源</dt>
                <dd>{{ currentMetricSourceIds(metric) }}</dd>
              </div>
            </dl>
          </article>
        </div>

        <div v-if="activeCurrentEvidenceItems.length" class="agent-ppt-package-section-head">
          <strong>会传给 AI 的 evidence</strong>
          <span>{{ activeCurrentEvidenceItems.length }} 条</span>
        </div>
        <div v-if="activeCurrentEvidenceItems.length" class="agent-ppt-current-metric-list">
          <article
            v-for="(item, index) in activeCurrentEvidenceItems"
            :key="`current-evidence-${index}`"
            class="agent-ppt-current-metric-card">
            <header>
              <div>
                <span>{{ item.type || 'evidence' }}</span>
                <strong>{{ item.title || '证据' }}</strong>
              </div>
            </header>
            <p>{{ item.text || item.summary || '无摘要' }}</p>
            <dl v-if="item.payload">
              <div v-for="(value, key) in item.payload" :key="`evidence-${index}-${key}`">
                <dt>{{ key }}</dt>
                <dd>{{ typeof value === 'object' ? JSON.stringify(value) : value }}</dd>
              </div>
            </dl>
          </article>
        </div>

        <div v-if="activeCurrentChartSpecs.length" class="agent-ppt-package-section-head">
          <strong>图表规格</strong>
          <span>{{ activeCurrentChartSpecs.length }} 个</span>
        </div>
        <div v-if="activeCurrentChartSpecs.length" class="agent-ppt-current-metric-list">
          <article
            v-for="(chart, index) in activeCurrentChartSpecs"
            :key="`current-chart-${chart.chart_id || chart.chartId || index}`"
            class="agent-ppt-current-metric-card">
            <header>
              <div>
                <span>{{ chart.chart_type || chart.chartType || 'chart' }}</span>
                <strong>{{ chart.title || '图表' }}</strong>
              </div>
            </header>
            <dl>
              <div>
                <dt>columns</dt>
                <dd>{{ (chart.columns || []).length }}</dd>
              </div>
              <div>
                <dt>rows</dt>
                <dd>{{ (chart.rows || []).length }}</dd>
              </div>
            </dl>
          </article>
        </div>

        <div v-if="activeCurrentGapMetrics.length" class="agent-ppt-package-section-head">
          <strong>缺口指标</strong>
          <span>{{ activeCurrentGapMetrics.length }} 项</span>
        </div>
        <div v-if="activeCurrentGapMetrics.length" class="agent-ppt-current-gap-list">
          <article
            v-for="(gap, index) in activeCurrentGapMetrics"
            :key="`current-gap-${gap.metric_id || gap.metricId || gap.gap_id || gap.gapId || index}`"
            class="agent-ppt-current-gap-card">
            <strong>{{ currentGapTitle(gap, index) }}</strong>
            <span>{{ gap.status || 'missing' }}</span>
            <p>{{ currentGapDescription(gap) }}</p>
            <small v-if="currentGapMeta(gap)">{{ currentGapMeta(gap) }}</small>
          </article>
        </div>

        <div v-if="!activeCurrentMetrics.length" class="agent-ppt-package-empty">
          这个来源目前没有可展示的标准指标。完成对应分析后会在这里显示。
        </div>
      </section>
    </div>

    <div v-if="activePackageSource" class="agent-ppt-package-detail-backdrop" @click.self="closePackageDetail">
      <section
        class="agent-ppt-package-detail"
        :class="{ 'has-carrier-preview': activePackageDetail.previewCarriers.length }"
        role="dialog"
        aria-modal="true"
        aria-label="资料包内容">
        <header class="agent-ppt-package-detail-head">
          <div>
            <span>资料包</span>
            <strong>{{ activePackageDetail.title || activePackageSource.title }}</strong>
            <small>{{ activePackageDetail.summary || '已生成' }}</small>
          </div>
          <button type="button" aria-label="关闭" title="关闭" @click="closePackageDetail">×</button>
        </header>

        <p v-if="activePackageDetail.payload.summary" class="agent-ppt-package-summary">{{ activePackageDetail.payload.summary }}</p>

        <div v-if="activePackageDetail.stats.length" class="agent-ppt-package-stats">
          <div v-for="stat in activePackageDetail.stats" :key="`package-stat-${stat[0]}`">
            <span>{{ stat[0] }}</span>
            <strong>{{ formatPackageMetric(stat[1]) }}</strong>
          </div>
        </div>

        <dl class="agent-ppt-package-meta">
          <div v-if="activePackageDetail.payload.intent">
            <dt>意图</dt>
            <dd>{{ activePackageDetail.payload.intent }}</dd>
          </div>
          <div v-if="activePackageDetail.alignment.alignment_level">
            <dt>对齐等级</dt>
            <dd>{{ activePackageDetail.alignment.alignment_level }}</dd>
          </div>
          <div v-if="activePackageDetail.alignment.join_key">
            <dt>连接键</dt>
            <dd>{{ activePackageDetail.alignment.join_key }}</dd>
          </div>
          <div v-if="activePackageDetail.sourceIds.length">
            <dt>来源</dt>
            <dd>{{ activePackageDetail.sourceIds.join(' / ') }}</dd>
          </div>
        </dl>

        <div v-if="activePackageDetail.warnings.length" class="agent-ppt-package-warnings">
          <strong>提示</strong>
          <span v-for="warning in activePackageDetail.warnings" :key="`package-warning-${warning}`">{{ warning }}</span>
        </div>

        <div v-if="activePackageDetail.carriers.length" class="agent-ppt-package-section-head">
          <strong>空间载体</strong>
          <span>{{ activePackageDetail.carriers.length }} 个</span>
        </div>
        <div v-if="activePackageDetail.carriers.length" class="agent-ppt-carrier-workspace">
          <div v-if="activePackageDetail.previewCarriers.length" class="agent-ppt-carrier-preview">
            <div class="agent-ppt-carrier-preview-head">
              <div class="agent-ppt-carrier-preview-title">
                <strong>空间预览</strong>
                <span>{{ activePackageSelectedCarrier?.carrier_id || '-' }} · {{ activePackageSelectedCarrier?.carrier_label || '空间载体' }}</span>
              </div>
              <div class="agent-ppt-carrier-preview-mode" aria-label="空间预览范围">
                <button
                  type="button"
                  :class="{ 'is-active': activePackageCarrierPreviewMode === 'local' }"
                  :aria-pressed="String(activePackageCarrierPreviewMode === 'local')"
                  title="聚焦当前载体"
                  @click="setPackageCarrierPreviewMode('local')">
                  局部
                </button>
                <button
                  type="button"
                  :class="{ 'is-active': activePackageCarrierPreviewMode === 'all' }"
                  :aria-pressed="String(activePackageCarrierPreviewMode === 'all')"
                  title="显示全部载体"
                  @click="setPackageCarrierPreviewMode('all')">
                  全部
                </button>
              </div>
            </div>
            <svg
              class="agent-ppt-carrier-preview-svg"
              :viewBox="activePackageDetail.preview.viewBox"
              role="img"
              aria-label="空间载体预览">
              <rect class="agent-ppt-carrier-preview-bg" x="0" y="0" width="1000" height="620" rx="18" />
              <g v-if="activePackageDetail.previewRoads.length" class="agent-ppt-carrier-preview-roads" aria-hidden="true">
                <path
                  v-for="road in activePackageDetail.previewRoads"
                  :key="`carrier-preview-road-${road.id}`"
                  class="agent-ppt-carrier-preview-road"
                  :class="road.className"
                  :d="road.path" />
              </g>
              <g
                v-for="item in activePackageDetail.previewCarriers"
                :key="`carrier-preview-${item.id}`"
                class="agent-ppt-carrier-preview-shape"
                :class="carrierPreviewClass(item)"
                tabindex="0"
                role="button"
                :aria-label="`${item.id} ${item.label}`"
                @click="selectPackageCarrier(item.id)"
                @keydown.enter.prevent="selectPackageCarrier(item.id)"
                @keydown.space.prevent="selectPackageCarrier(item.id)">
                <path v-if="item.type === 'block_loop' && item.polygonPath" class="agent-ppt-carrier-preview-fill" :d="item.polygonPath" />
                <path
                  v-if="item.outlinePath || item.boundaryPath || item.polygonPath"
                  class="agent-ppt-carrier-preview-line"
                  :d="item.outlinePath || item.boundaryPath || item.polygonPath" />
                <text
                  v-if="item.isFocus || activePackageDetail.previewCarriers.length === 1"
                  class="agent-ppt-carrier-preview-label"
                  :x="item.labelX"
                  :y="item.labelY">
                  {{ item.id.replace('block_loop_', 'L').replace('corridor_', 'C').replace('segment_', 'S') }}
                </text>
              </g>
            </svg>
          </div>
          <div class="agent-ppt-carrier-list">
            <article
              v-for="carrier in activePackageDetail.carriers"
              :key="`package-carrier-${carrier.carrier_id}`"
              class="agent-ppt-carrier-row"
              :class="[`is-${carrier.carrier_type || 'segment'}`, { 'is-active': isPackageCarrierActive(carrier) }]"
              tabindex="0"
              role="button"
              @click="selectPackageCarrier(carrier.carrier_id)"
              @keydown.enter.prevent="selectPackageCarrier(carrier.carrier_id)"
              @keydown.space.prevent="selectPackageCarrier(carrier.carrier_id)">
              <div class="agent-ppt-carrier-row-head">
                <div>
                  <span>{{ carrierTypeLabel(carrier) }}</span>
                  <strong>{{ carrier.carrier_label || '空间载体' }}</strong>
                </div>
                <small>{{ carrier.carrier_id }}</small>
              </div>
              <p v-if="carrier.summary">{{ carrier.summary }}</p>
              <dl class="agent-ppt-carrier-metrics">
                <div>
                  <dt>Choice / Integration</dt>
                  <dd>{{ carrierMetric(carrier, 'road_metrics', 'choice_score') }} / {{ carrierMetric(carrier, 'road_metrics', 'integration_score') }}</dd>
                </div>
                <div>
                  <dt>POI</dt>
                  <dd>{{ carrierPoiLabel(carrier) }}</dd>
                </div>
                <div>
                  <dt>人口</dt>
                  <dd>{{ carrierPopulationLabel(carrier) }}</dd>
                </div>
                <div>
                  <dt>夜光</dt>
                  <dd>{{ carrierMetric(carrier, 'nightlight_metrics', 'mean_radiance') }} · {{ carrier.nightlight_metrics?.night_activity_level || '-' }}</dd>
                </div>
              </dl>
            </article>
          </div>
        </div>

        <div class="agent-ppt-package-section-head">
          <strong>点位明细</strong>
          <span>{{ activePackageDetail.items.length }} 条</span>
        </div>
        <div v-if="activePackageDetail.items.length" class="agent-ppt-package-table" role="table" aria-label="资料包点位明细">
          <div class="agent-ppt-package-table-head" role="row">
            <span role="columnheader">POI</span>
            <span role="columnheader">分类</span>
            <span role="columnheader">格子</span>
            <span role="columnheader">夜光</span>
          </div>
          <div
            v-for="(item, index) in activePackageDetail.items"
            :key="`package-item-${item.id || item.name || index}`"
            class="agent-ppt-package-table-row"
            role="row">
            <strong role="cell">{{ packageItemTitle(item, index) }}</strong>
            <span role="cell">{{ packageItemSubtitle(item) }}</span>
            <span role="cell">{{ item.cell_id || item.alignment_status || '-' }}</span>
            <span role="cell">{{ packageItemRadiance(item) }}</span>
          </div>
        </div>
        <div v-else class="agent-ppt-package-empty">这个资料包没有返回点位明细。</div>

        <div v-if="activePackageDetail.evidenceRefs.length" class="agent-ppt-package-section-head">
          <strong>Evidence refs</strong>
          <span>{{ activePackageDetail.evidenceRefs.length }} 条</span>
        </div>
        <div v-if="activePackageDetail.evidenceRefs.length" class="agent-ppt-package-ref-list">
          <span v-for="refItem in activePackageDetail.evidenceRefs" :key="`package-ref-${refItem}`">{{ refItem }}</span>
        </div>
      </section>
    </div>

    <div v-if="activeDocumentSource" class="agent-ppt-package-detail-backdrop" @click.self="closeDocumentEvidence">
      <section
        class="agent-ppt-package-detail agent-ppt-document-evidence-detail"
        role="dialog"
        aria-modal="true"
        aria-label="PageIndex 文档结构">
        <header class="agent-ppt-package-detail-head">
          <div>
            <span>PageIndex 文档结构</span>
            <strong>{{ activeDocumentSource.title }}</strong>
            <small>{{ (activeDocumentSource.meta && activeDocumentSource.meta.label) || '已生成' }}</small>
          </div>
          <button type="button" aria-label="关闭" title="关闭" @click="closeDocumentEvidence">×</button>
        </header>

        <div v-if="activeDocumentIndexItems.length" class="agent-ppt-document-index-list">
          <article
            v-for="(item, index) in activeDocumentIndexItems"
            :key="`document-index-${item.node_id || item.nodeId || index}`"
            class="agent-ppt-document-index-card"
            :style="{ '--node-depth': Math.max(0, Number(item.level || 0) - 1) }">
            <header>
              <strong>{{ item.title || `章节 ${index + 1}` }}</strong>
              <span>p.{{ item.page_start || item.pageStart || 1 }}{{ (item.page_end || item.pageEnd) && (item.page_end || item.pageEnd) !== (item.page_start || item.pageStart) ? `-${item.page_end || item.pageEnd}` : '' }}</span>
            </header>
            <p v-if="item.summary">{{ item.summary }}</p>
          </article>
        </div>
        <div v-else class="agent-ppt-package-empty">这个文档暂时没有生成 PageIndex 章节结构。</div>

      </section>
    </div>

    <div v-if="sourceDialog.mode" class="agent-ppt-source-dialog-backdrop" @click.self="closeSourceDialog">
      <div class="agent-ppt-source-dialog" role="dialog" aria-modal="true">
        <strong>{{ sourceDialog.title }}</strong>
        <p v-if="sourceDialog.message">{{ sourceDialog.message }}</p>
        <label v-if="['rename-source', 'rename-group', 'group-emoji'].includes(sourceDialog.mode)">
          <span>{{ sourceDialog.mode === 'group-emoji' ? '图标' : '名称' }}</span>
          <input v-model="sourceDialog.value" type="text" autofocus>
        </label>
        <div class="agent-ppt-source-dialog-actions">
          <button type="button" @click="closeSourceDialog">取消</button>
          <button type="button" class="is-primary" @click="confirmSourceDialog">确认</button>
        </div>
      </div>
    </div>
  </div>
</template>
