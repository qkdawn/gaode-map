<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { normalizePptPackageDetail } from './carrier-preview.js'
import {
  formatMetricClaimValue,
  formatVisualOverlayValue,
  visualColumnKey,
  visualColumnLabel,
  visualColumnsPreview,
  visualComposition,
  visualData,
  visualEvidenceSummary,
  visualExistingAssetMissingText,
  visualGroupSummary,
  visualLinkSummary,
  visualMetricOverlays,
  visualNodeSummary,
  visualReasonText,
  visualRowsPreview,
  visualTypeLabel,
} from './visual-view.js'
import {
  carrierMetric,
  carrierPoiLabel,
  carrierPopulationLabel,
  carrierTypeLabel,
  currentGapDescription,
  currentGapMeta,
  currentGapTitle,
  currentMetricSourceIds,
  formatCurrentMetricValue,
  formatPackageMetric,
  packageItemRadiance,
  packageItemSubtitle,
  packageItemTitle,
} from './source-detail-view.js'
import {
  buildWebSourceCommitPreview,
  buildWebSourcePreviewPayload,
  closeWebSourceDialogForm,
  createWebSourceDialogState,
  openWebSourceDialogForm,
  parseWebSourceUrls,
  selectedWebSourceItems,
  toggleWebSourceCategorySelection,
  toggleWebSourceModeSelection,
  webSourceItemKey,
  webSourceItemUrlLabel,
  webSourceTierLabel,
} from './web-source-dialog.js'
import {
  isCurrentSource,
  isDeletableSource,
  isDocumentSource,
  isGeneratingSource,
  isPackagePlaceholderSource,
  isPackageSource,
  isRetryableSource,
  removeSourceMessage,
  sourceHealth,
  sourceHealthLabel,
  sourceHealthReason,
  sourceTransport,
  sourceTransportExcludedItems,
  sourceTransportLabel,
} from './source-view.js'
import { getBlockingPptInputSources, getPptPromptActions } from './ui-state.js'

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
  narrativePlan: {
    type: Object,
    default: () => ({}),
  },
  slideGenerationQueue: {
    type: Array,
    default: () => [],
  },
  slideGenerationJob: {
    type: Object,
    default: () => ({}),
  },
  visualGenerationBySlide: {
    type: Object,
    default: () => ({}),
  },
  slides: {
    type: Array,
    default: () => [],
  },
  selectedSlideId: {
    type: String,
    default: '',
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
  webSourceGenerating: {
    type: Boolean,
    default: false,
  },
  sourceDeleting: {
    type: Boolean,
    default: false,
  },
  sourceRefreshing: {
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
  'export-source',
  'export-all-sources',
  'remove-source',
  'remove-selected-sources',
  'retry-source',
  'generate-package-source',
  'rename-source-group',
  'set-source-group-emoji',
  'remove-source-group',
  'upload-document-source',
  'upload-image-source',
  'manage-web-source',
  'update-spec-field',
  'create-data-package',
  'generate-outline',
  'generate-narrative-plan',
  'generate-slides',
  'generate-slide-visuals',
  'generate-all-visuals',
  'select-slide',
  'regenerate-outline',
  'regenerate-narrative-plan',
  'regenerate-slides',
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
const webSourceDialog = ref(createWebSourceDialogState())
const documentSourceInput = ref(null)
const activeDocumentSourceId = ref('')
const activePackageSourceId = ref('')
const activeCurrentSourceId = ref('')
const activePackageCarrierId = ref('')
const activePackageCarrierPreviewMode = ref('local')
const flowViewMode = ref('')
const localActivePageNo = ref(0)
const bulkDeleteMode = ref(false)
const bulkDeleteSourceIds = ref(new Set())
const directiveRowRefs = {}
const failedVisualPreviewUrls = ref(new Set())
const visualPreviewDialog = ref({ url: '', title: '' })
const sourceMenuLockClass = 'agent-ppt-source-menu-open'
const nowTick = ref(Date.now())
let nowTickTimer = null

const sourcePanelLabel = computed(() => (isSourcesCollapsed.value ? '展开来源' : '折叠来源'))
const sourceCollapseIconPoints = computed(() => (
  isSourcesCollapsed.value ? '14.5,12 12,9.5 12,14.5 14.5,12' : '11.5,12 14,9.5 14,14.5 11.5,12'
))
const centerThreadBodyRef = ref(null)

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
const hasOutline = computed(() => props.outline.length > 0)
const hasNarrativePlan = computed(() => Array.isArray(props.narrativePlan && props.narrativePlan.slideRoles) && props.narrativePlan.slideRoles.length > 0)
const hasDirective = computed(() => props.slides.length > 0)
const hasVisualArtifacts = computed(() => props.slides.some((slide) => Array.isArray(slide.visualArtifacts) && slide.visualArtifacts.length))
const hasVisualSpecs = computed(() => props.slides.some((slide) => Array.isArray(slide.visualSpecs) && slide.visualSpecs.length))
const blockingInputSources = computed(() => getBlockingPptInputSources({ sources: props.sources }))
const outlineBlockReason = computed(() => {
  if (!(props.sourceSummary.selected || 0)) return '请先选择至少一个已生成来源'
  if (!(props.sourceSummary.deliverable || props.sourceSummary.selectedDeliverable || 0)) return '当前已选来源没有可发送给 AI 的指标或证据'
  if (props.sourceRefreshing || props.dataPackageGenerating || props.sourceGrouping) return '来源仍在构建中，完成后再生成目录'
  if (blockingInputSources.value.length) {
    const generating = blockingInputSources.value.some((source) => String(source.status || '') === 'generating')
    return generating ? '来源仍在构建中，完成后再生成目录' : '仍有来源未构建完成，完成后再生成目录'
  }
  return ''
})
const canGenerateOutline = computed(() => !outlineBlockReason.value && !isGenerationJobActive.value && !isSlideGenerationActive.value)
const canGenerateNarrativePlan = computed(() => hasOutline.value && !isGenerationJobActive.value && !isSlideGenerationActive.value)
const canGenerateSlides = computed(() => hasOutline.value && hasNarrativePlan.value && !isGenerationJobActive.value && !isSlideGenerationActive.value)
const canCreateDataPackage = computed(() => (props.sourceSummary.selected || 0) > 0 && !props.dataPackageGenerating)
const canSearchWebSource = computed(() => !props.webSourceGenerating && !webSourceDialog.value.loadingDefault && !webSourceDialog.value.searching && !webSourceDialog.value.adding)
const webSourcePreviewItems = computed(() => {
  const preview = webSourceDialog.value.preview && typeof webSourceDialog.value.preview === 'object' ? webSourceDialog.value.preview : {}
  return Array.isArray(preview.items) ? preview.items : []
})
const webSourcePreviewItemsByCategory = computed(() => {
  const grouped = new Map()
  webSourcePreviewItems.value.forEach((item, index) => {
    const category = String(item.category || '区域概况')
    if (!grouped.has(category)) grouped.set(category, [])
    grouped.get(category).push({ item, index })
  })
  return Array.from(grouped.entries()).map(([category, rows]) => ({ category, rows }))
})
const activeWebSourcePreviewItem = computed(() => webSourcePreviewItems.value[Math.max(0, Number(webSourceDialog.value.activeItemIndex || 0))] || null)
const selectedWebSourcePreviewItems = computed(() => {
  return selectedWebSourceItems(webSourcePreviewItems.value, webSourceDialog.value.selectedItemKeys)
})
const canCommitWebSource = computed(() => !!webSourceDialog.value.preview && selectedWebSourcePreviewItems.value.length > 0 && !props.webSourceGenerating && !webSourceDialog.value.adding)
const bulkDeleteSelectedSources = computed(() => props.sources.filter((source) => source && bulkDeleteSourceIds.value.has(String(source.id || '')) && isDeletableSource(source)))
const canStartBulkDelete = computed(() => props.sources.some((source) => source && isDeletableSource(source)) && !props.sourceDeleting)
const canConfirmBulkDelete = computed(() => bulkDeleteSelectedSources.value.length > 0 && !props.sourceDeleting)
const deliverableSourceCount = computed(() => props.sourceSummary.deliverable || props.sourceSummary.selectedDeliverable || 0)
const emptyPayloadSourceCount = computed(() => props.sourceSummary.emptyPayload || 0)
const activeGenerationJob = computed(() => (props.generationJob && typeof props.generationJob === 'object' ? props.generationJob : {}))
const generationJobPhase = computed(() => String(activeGenerationJob.value.phase || 'idle'))
const generationJobType = computed(() => String(activeGenerationJob.value.type || 'outline'))
const generationJobEvents = computed(() => (Array.isArray(activeGenerationJob.value.events) ? activeGenerationJob.value.events.slice(-60) : []))
const slideGenerationActiveJob = computed(() => (props.slideGenerationJob && typeof props.slideGenerationJob === 'object' ? props.slideGenerationJob : {}))
const hasPageQueue = computed(() => Array.isArray(props.slideGenerationQueue) && props.slideGenerationQueue.length > 0)
const hasActivePageQueueItem = computed(() => (
  hasPageQueue.value
  && props.slideGenerationQueue.some((item) => ['requesting', 'response_received', 'applying', 'generating', 'repairing', 'retrying'].includes(String(item && item.status || '')))
))
const isSlideGenerationActive = computed(() => !!slideGenerationActiveJob.value.active || hasActivePageQueueItem.value)
const isGenerationJobActive = computed(() => ['requesting', 'response_received', 'applying'].includes(generationJobPhase.value) && generationJobType.value !== 'slides')
const isBulkBriefGenerating = computed(() => (
  generationJobType.value === 'directive'
  && ['requesting', 'response_received', 'applying'].includes(generationJobPhase.value)
  && !hasDirective.value
  && !hasPageQueue.value
))
const isBriefGenerating = computed(() => isBulkBriefGenerating.value || isSlideGenerationActive.value)
const generationJobTitle = computed(() => {
  const isNarrative = generationJobType.value === 'narrative'
  const isDirective = generationJobType.value === 'directive' || generationJobType.value === 'slides'
  const labels = {
    requesting: isNarrative ? '叙事方案生成中' : isDirective ? 'brief 生成中' : '目录生成中',
    response_received: isNarrative ? '后端已返回，正在应用叙事方案' : isDirective ? '后端已返回，正在应用 brief' : '后端已返回，正在应用目录',
    applying: isNarrative ? '正在写入叙事方案' : isDirective ? '正在写入 brief' : '正在写入目录',
    ready: isNarrative ? '叙事方案已写入' : isDirective ? 'brief 已写入' : '目录已写入',
    failed: isNarrative ? '叙事方案生成失败' : isDirective ? 'brief 生成失败' : '目录生成失败',
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
  && (isGenerationJobActive.value || ['failed', 'superseded'].includes(generationJobPhase.value) || generationJobEvents.value.length)
))
const shouldOpenGenerationJobPanel = computed(() => ['failed', 'superseded'].includes(generationJobPhase.value))
const generationErrorText = computed(() => String(props.generationError || '').trim())
const generationResponsePayload = computed(() => {
  const response = props.generationResponse && typeof props.generationResponse === 'object'
    ? props.generationResponse
    : {}
  const source = String(response.source || '').trim()
  if (props.currentStep === 'slides_generating' && source === 'narrative') return {}
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
  const visualSpecs = slides.reduce((sum, slide) => {
    const specs = slide && (slide.visualSpecs || slide.visual_specs)
    return sum + (Array.isArray(specs) ? specs.length : 0)
  }, 0)
  const keys = Object.keys(payload)
  return [
    outline.length ? `outline ${outline.length} 页` : '',
    slides.length ? `slides ${slides.length} 页` : '',
    visualSpecs ? `visual_specs ${visualSpecs} 个` : '',
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
    narrative: '叙事方案生成失败，请检查模型配置后重试。',
    slides: 'brief 生成失败，可重新点击生成 brief 继续。',
    directive: '指令文件生成失败，请检查模型配置后重试。',
  }
  return labels[String(props.generationErrorSource || '')] || 'PPT 工作台请求失败，请稍后重试。'
})
const slideGenerationFailedPage = computed(() => {
  const failedFromJob = Number(slideGenerationActiveJob.value.failedPageNo || slideGenerationActiveJob.value.failed_page_no || 0) || 0
  if (failedFromJob) return failedFromJob
  const failedItem = Array.isArray(props.slideGenerationQueue)
    ? props.slideGenerationQueue.find((item) => String(item && item.status) === 'failed')
    : null
  return Number(failedItem && (failedItem.pageNo || failedItem.page_no || 0)) || 0
})
const activeSlideQueueItem = computed(() => {
  if (!Array.isArray(props.slideGenerationQueue)) return null
  const activeStatuses = new Set(['requesting', 'response_received', 'applying', 'repairing', 'retrying'])
  const activeItem = props.slideGenerationQueue.find((item) => activeStatuses.has(String(item && item.status || '')))
  if (activeItem) return activeItem
  const failedItem = props.slideGenerationQueue.find((item) => ['failed', 'timed_out'].includes(String(item && item.status || '')))
  if (failedItem) return failedItem
  const current = Number(slideGenerationActiveJob.value.currentPageNo || slideGenerationActiveJob.value.current_page_no || 0) || 0
  if (current) {
    return props.slideGenerationQueue.find((item) => Number(item && (item.pageNo || item.page_no || 0)) === current) || null
  }
  return props.slideGenerationQueue.find((item) => String(item && item.status || '') === 'pending') || null
})
const activeSlideWaitSeconds = computed(() => {
  if (!isSlideGenerationActive.value) return 0
  const startedAt = String(slideGenerationActiveJob.value.activePageStartedAt || slideGenerationActiveJob.value.active_page_started_at || '').trim()
  const startedMs = startedAt ? Date.parse(startedAt) : NaN
  if (!Number.isFinite(startedMs)) return 0
  return Math.max(0, Math.floor((nowTick.value - startedMs) / 1000))
})
const lastCompletedSlidePage = computed(() => {
  if (!Array.isArray(props.slideGenerationQueue)) return 0
  return props.slideGenerationQueue.reduce((max, item) => {
    const status = String(item && item.status || '')
    const pageNo = Number(item && (item.pageNo || item.page_no || 0)) || 0
    return status === 'ready' && pageNo > max ? pageNo : max
  }, 0)
})
const visibleGeneratedSlidePagesText = computed(() => {
  const pages = Array.isArray(props.slides)
    ? props.slides.map((slide) => Number(slide && slide.index || 0) || 0).filter(Boolean).sort((a, b) => a - b)
    : []
  if (!pages.length) return '暂无已生成页'
  const preview = pages.slice(0, 5).map((pageNo) => `第 ${pageNo} 页`).join('、')
  return pages.length > 5 ? `${preview} 等 ${pages.length} 页` : preview
})
const slideGenerationQueueChips = computed(() => {
  if (!Array.isArray(props.slideGenerationQueue)) return []
  return props.slideGenerationQueue.map((item) => {
    const pageNo = Number(item && (item.pageNo || item.page_no || 0)) || 0
    const status = String(item && item.status || 'pending')
    const labels = {
      ready: '完成',
      requesting: '请求中',
      response_received: '已返回',
      applying: '写入中',
      generating: '生成中',
      repairing: '修复中',
      retrying: '重试中',
      failed: '失败',
      timed_out: '超时',
      stale: '旧响应',
      pending: '待生成',
    }
    return {
      pageNo,
      status,
      label: labels[status] || '待生成',
      error: String(item && item.error || ''),
    }
  }).filter((item) => item.pageNo)
})
const slideGenerationQueueSummary = computed(() => {
  const total = slideGenerationQueueChips.value.length
  const ready = slideGenerationQueueChips.value.filter((item) => item.status === 'ready').length
  const failed = slideGenerationQueueChips.value.filter((item) => item.status === 'failed').length
  if (!total) return ''
  return failed ? `${ready}/${total} 页完成 · ${failed} 页失败` : `${ready}/${total} 页完成`
})
const slideGenerationProgressText = computed(() => {
  const queueItem = activeSlideQueueItem.value
  const current = Number(queueItem && (queueItem.pageNo || queueItem.page_no || 0)) || Number(slideGenerationActiveJob.value.currentPageNo || slideGenerationActiveJob.value.current_page_no || 0) || 0
  const total = Number(slideGenerationActiveJob.value.total || props.outline.length || 0) || 0
  if (isSlideGenerationActive.value && current && total) {
    const status = String(queueItem && queueItem.status || 'pending')
    const verb = status === 'response_received'
      ? '后端已返回，准备写入'
      : status === 'applying'
        ? '正在写入 brief'
        : status === 'repairing'
          ? '正在修复 AI JSON'
          : status === 'retrying'
            ? '正在重试'
            : status === 'requesting'
              ? '请求已发出，等待 AI 返回'
              : status === 'pending'
                ? '准备请求'
                : '等待 AI 返回'
    const waited = activeSlideWaitSeconds.value ? `，已等待 ${activeSlideWaitSeconds.value} 秒` : ''
    const completed = lastCompletedSlidePage.value ? `，已完成到第 ${lastCompletedSlidePage.value} 页` : ''
    return `后台正在生成第 ${current}/${total} 页 brief：${verb}${waited}${completed}。当前内容区显示 ${visibleGeneratedSlidePagesText.value}，AI 返回后会自动校验并尝试修复 JSON。`
  }
  if (slideGenerationFailedPage.value) return `第 ${slideGenerationFailedPage.value} 页生成失败，可重新点击生成 brief 继续。`
  return ''
})
const promptStageText = computed(() => {
  if (slideGenerationProgressText.value) return slideGenerationProgressText.value
  if (isBulkBriefGenerating.value) return '正在生成整套 brief，返回后会写入中心列表。'
  if (!hasOutline.value && outlineBlockReason.value) return outlineBlockReason.value
  if (!hasOutline.value) return '先生成目录，确定 15 页结构。'
  if (!hasNarrativePlan.value) return '目录已生成，下一步生成全局叙事方案。'
  if (!hasDirective.value) return '叙事方案已生成，下一步生成 brief。'
  if (hasVisualSpecs.value && !hasVisualArtifacts.value) return 'brief 已生成，下一步生成可视化图片。'
  if (isAnyVisualGenerating.value) return '正在生成可视化图片。'
  if (isViewingOutline.value) return '目录已生成；如需调整目录，可重新生成目录。'
  return 'brief 草稿已生成，可重新生成 brief。'
})
const configCheckStatus = computed(() => {
  if (!outlineBlockReason.value) return '资料已就绪，可以生成目录。'
  return outlineBlockReason.value
})
const configCheckItems = computed(() => [
  ['页数', `${props.spec.pageCount || 15} 页`],
  ['受众', props.spec.audience || '政府评审'],
  ['资料', `${props.sourceSummary.selected || 0} 个已选来源 · ${deliverableSourceCount.value} 个可用于 AI`],
])
const promptActions = computed(() => getPptPromptActions({
  outline: props.outline,
  narrativePlan: props.narrativePlan,
  deckBrief: { slides: props.slides },
  slideGenerationQueue: props.slideGenerationQueue,
  slideGenerationJob: props.slideGenerationJob,
  visualGenerationBySlide: props.visualGenerationBySlide,
}))
function isPromptActionDisabled(action = {}) {
  const event = String(action.event || '')
  if (isAnyVisualGenerating.value) return true
  if (['generate-slides', 'regenerate-slides'].includes(event)) return isGenerationJobActive.value || !hasNarrativePlan.value
  if (isGenerationJobActive.value || isSlideGenerationActive.value) return true
  if (event === 'generate-outline') return !canGenerateOutline.value
  if (event === 'generate-narrative-plan') return !canGenerateNarrativePlan.value
  if (event === 'generate-all-visuals') return !hasVisualSpecs.value
  if (event === 'regenerate-outline') return !hasOutline.value
  if (event === 'regenerate-narrative-plan') return !hasOutline.value
  if (event === 'regenerate-slides') return !hasNarrativePlan.value
  return false
}
function emitPromptAction(action = {}) {
  const event = String(action.event || '')
  if (!event || isPromptActionDisabled(action)) return
  emit(event)
}
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
const activeCurrentVisualSpecs = computed(() => {
  const visuals = activeCurrentAiPayload.value.visual_specs || activeCurrentAiPayload.value.visualSpecs
  return Array.isArray(visuals) ? visuals.slice(0, 40) : []
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
  if (hasDirective.value && hasVisualSpecs.value && !hasVisualArtifacts.value) return 4
  if (hasDirective.value) return 3
  if (props.currentStep === 'outline_generating') return 1
  if (['outline_ready', 'narrative_generating', 'narrative_ready'].includes(props.currentStep)) return 2
  if (props.currentStep === 'slides_generating' || props.currentStep === 'directive_draft') return 3
  if (props.currentStep === 'visuals_ready') return 4
  return 0
})
const canViewOutlineStep = computed(() => hasOutline.value)
const canViewDirectiveStep = computed(() => hasNarrativePlan.value || hasDirective.value || isBriefGenerating.value)
const isViewingMaterials = computed(() => flowViewMode.value === 'materials' && (hasOutline.value || hasDirective.value))
const isViewingOutline = computed(() => flowViewMode.value === 'outline' && hasOutline.value)
const isViewingDirective = computed(() => flowViewMode.value === 'directive' && (hasDirective.value || isBriefGenerating.value || hasNarrativePlan.value))
const isBriefPhase = computed(() => (
  hasDirective.value
  || isBriefGenerating.value
  || isViewingDirective.value
))
const shouldShowConfigPanel = computed(() => !hasOutline.value || isViewingMaterials.value)
const shouldShowNarrativePanel = computed(() => (
  hasNarrativePlan.value
  && !isBriefPhase.value
  && !isViewingMaterials.value
  && !isViewingOutline.value
))
const shouldShowDirectiveRows = computed(() => isBriefPhase.value && !isViewingMaterials.value && !isViewingOutline.value)
const narrativeStorylineText = computed(() => String(props.narrativePlan.storyline || '').trim())
const narrativeChapterRows = computed(() => {
  const chapters = Array.isArray(props.narrativePlan.chapters) ? props.narrativePlan.chapters : []
  return chapters.map((chapter, index) => ({
    id: `narrative-chapter-${index + 1}`,
    name: chapter.name || `章节 ${index + 1}`,
    pageRange: chapter.pageRange || '',
    job: chapter.job || '',
    output: chapter.output || '',
  }))
})
const narrativeEvidenceBuckets = computed(() => {
  const items = Array.isArray(props.narrativePlan.evidenceBuckets) ? props.narrativePlan.evidenceBuckets : []
  return items.map((item, index) => ({
    id: item.id || `narrative-bucket-${index + 1}`,
    label: item.label || item.id || `证据桶 ${index + 1}`,
    allowedSources: Array.isArray(item.allowedSources) ? item.allowedSources : [],
  })).filter((item) => item.id)
})
const narrativeVisualRules = computed(() => {
  const rules = props.narrativePlan.visualRules && typeof props.narrativePlan.visualRules === 'object'
    ? props.narrativePlan.visualRules
    : {}
  return [
    ['空间优先', rules.spatialFirst],
    ['数值图必须有数据', rules.numericChartsRequireData],
    ['策略页使用语义图', rules.diagramForStrategyPages],
    ['禁止降级柱状图', rules.noFallbackBar],
  ].map(([label, enabled]) => ({ label, enabled: !!enabled }))
})
const narrativeRoleRows = computed(() => {
  const roles = Array.isArray(props.narrativePlan && props.narrativePlan.slideRoles)
    ? props.narrativePlan.slideRoles
    : []
  return roles.map((role, index) => ({
    id: `narrative-role-${Number(role.pageNo || 0) || index + 1}`,
    pageNo: Number(role.pageNo || 0) || index + 1,
    title: role.role || `页面 ${index + 1}`,
    job: role.job || '',
    evidenceBucket: role.evidenceBucket || '',
    visualFamily: role.visualFamily || '',
    transitionNote: role.transitionNote || '',
  }))
})
const outlineRows = computed(() => {
  if (shouldShowDirectiveRows.value) {
    const slidesByPage = new Map((Array.isArray(props.slides) ? props.slides : [])
      .map((slide, index) => [Number(slide && slide.index || index + 1) || index + 1, slide]))
    const queueByPage = new Map((Array.isArray(props.slideGenerationQueue) ? props.slideGenerationQueue : [])
      .map((item) => [Number(item && (item.pageNo || item.page_no || 0)) || 0, item])
      .filter(([pageNo]) => pageNo))
    if (!slidesByPage.size && isBulkBriefGenerating.value) {
      const statusLabel = generationJobPhase.value === 'response_received'
        ? '已返回'
        : generationJobPhase.value === 'applying'
          ? '写入中'
          : '生成中'
      const detail = generationJobPhase.value === 'response_received'
        ? '后端已返回 brief，正在准备写入中心列表。'
        : generationJobPhase.value === 'applying'
          ? '正在写入 brief，完成后会替换为真实页面列表。'
          : '正在生成整套 brief，返回后会写入中心列表。'
      return [{
        id: 'brief-bulk-generating',
        pageNo: 0,
        title: '正在生成整套 brief',
        detail,
        fields: [
          ['生成状态', statusLabel],
          ['目录页数', props.outline.length ? `${props.outline.length} 页` : '按当前目录生成'],
          ['返回摘要', generationJobSummary.value],
        ].filter((field) => String(field[1] || '').trim()),
        metricClaims: [],
        metricGaps: [],
        visualSpecs: [],
        visualArtifacts: [],
        visualStatus: { status: 'idle', error: '' },
        mode: 'generating',
        statusLabel,
        statusClass: generationJobPhase.value || 'requesting',
      }]
    }
    const baseRows = slidesByPage.size
      ? Array.from(slidesByPage.values()).sort((left, right) => (Number(left && left.index || 0) || 0) - (Number(right && right.index || 0) || 0))
      : hasOutline.value
        ? props.outline
        : (Array.isArray(props.slides) ? props.slides : []).map((slide, index) => ({
          id: slide.id || `slide-${index + 1}`,
          pageNo: Number(slide.index || 0) || index + 1,
          theme: slide.title,
          purpose: slide.purpose,
        }))
    return baseRows.map((outlineItem, index) => {
      const pageNo = Number(outlineItem.pageNo || outlineItem.page_no || outlineItem.index || 0) || index + 1
      const item = slidesByPage.get(pageNo)
      const queueItem = queueByPage.get(pageNo) || {}
      const queueStatus = String(queueItem.status || '')
      if (!item) {
        if (!hasPageQueue.value) return null
        const isGenerating = ['requesting', 'response_received', 'applying', 'generating', 'repairing', 'retrying'].includes(queueStatus)
        const isFailed = ['failed', 'timed_out', 'stale'].includes(queueStatus)
        const statusLabel = isFailed
          ? (queueStatus === 'timed_out' ? '超时' : queueStatus === 'stale' ? '旧响应' : '失败')
          : isGenerating
            ? (queueStatus === 'response_received' ? '已返回' : queueStatus === 'applying' ? '写入中' : queueStatus === 'repairing' ? '修复中' : queueStatus === 'retrying' ? '重试中' : '请求中')
            : '待生成'
        const detail = isFailed
          ? (queueItem.error || (queueStatus === 'timed_out' ? '等待超时，可继续重试。' : queueStatus === 'stale' ? '旧响应已忽略，可继续重试。' : '本页 brief 生成失败，可点击生成 brief 继续。'))
          : isGenerating
            ? (queueStatus === 'response_received' ? '后端已返回，正在写入前端。' : queueStatus === 'applying' ? '正在写入 brief。' : '请求已发出，等待 AI 返回。')
            : '待生成 brief。'
        return {
          id: outlineItem.id || `brief-placeholder-${pageNo}`,
          pageNo,
          title: outlineItem.theme || outlineItem.title || `页面 ${pageNo}`,
          detail,
          fields: [
            ['目录目的', outlineItem.purpose],
            ['生成状态', isFailed ? '失败' : isGenerating ? '生成中' : '待生成'],
          ].filter((field) => String(field[1] || '').trim()),
          metricClaims: [],
          metricGaps: [],
          visualSpecs: [],
          visualArtifacts: [],
          visualStatus: visualGenerationStatus(pageNo),
          mode: isFailed ? 'failed' : isGenerating ? 'generating' : 'pending',
          statusLabel,
          statusClass: queueStatus || (isFailed ? 'failed' : isGenerating ? 'requesting' : 'pending'),
        }
      }
      return {
      id: item.id || `slide-${index + 1}`,
      pageNo,
      title: item.title || `页面 ${pageNo}`,
      detail: item.purpose || '页面 brief 草稿',
      fields: [
        ['核心表达', item.keyMessage],
        ['见地', item.insight || '暂未生成见地，可在重写抽屉补充。'],
        ['证据解释', (Array.isArray(item.evidenceExplanation) && item.evidenceExplanation.length) ? item.evidenceExplanation.join(' / ') : '暂无证据解释，可补充口径、阈值或来源说明。'],
        ['页面布局指令', item.visualPlan],
        ['素材与证据', Array.isArray(item.requiredSources) ? item.requiredSources.join(' / ') : item.requiredSources],
      ].filter((field) => String(field[1] || '').trim()),
      metricClaims: Array.isArray(item.metricClaims) ? item.metricClaims : [],
      metricGaps: Array.isArray(item.metricGaps) ? item.metricGaps : [],
      visualSpecs: Array.isArray(item.visualSpecs) ? item.visualSpecs : [],
      visualArtifacts: Array.isArray(item.visualArtifacts) ? item.visualArtifacts : [],
      visualStatus: visualGenerationStatus(pageNo),
      mode: 'directive',
      statusLabel: '已写入',
      statusClass: 'directive',
      }
    }).filter(Boolean)
  }
  if (hasOutline.value) {
    return props.outline.map((item, index) => ({
      id: item.id || `outline-${index + 1}`,
      pageNo: item.pageNo || index + 1,
      title: item.theme || `页面 ${index + 1}`,
      detail: item.purpose || '目录草稿',
      fields: [],
      metricClaims: [],
      metricGaps: [],
      visualSpecs: [],
      visualArtifacts: [],
      mode: 'outline',
      statusLabel: '目录草稿',
      statusClass: 'outline',
    }))
  }
  return []
})
const directiveRowList = computed(() => outlineRows.value.filter((row) => row && row.mode === 'directive'))
const flowNavigableRows = computed(() => outlineRows.value.filter((row) => row && ['outline', 'directive', 'pending', 'generating', 'failed'].includes(row.mode) && Number(row.pageNo || 0) > 0))
const externalSelectedFlowPageNo = computed(() => {
  const selectedId = String(props.selectedSlideId || '').trim()
  if (!selectedId) return 0
  const selectedRow = flowNavigableRows.value.find((row) => String(row.id || '') === selectedId)
  return Number(selectedRow && selectedRow.pageNo) || 0
})
const activeFlowPageNo = computed(() => (
  Number(localActivePageNo.value || externalSelectedFlowPageNo.value || 0) || 0
))
const selectedFlowRowId = computed(() => {
  const pageNo = activeFlowPageNo.value
  if (!pageNo) return ''
  const selectedRow = flowNavigableRows.value.find((row) => Number(row.pageNo || 0) === pageNo)
  return String(selectedRow && selectedRow.id || '')
})
const activeFlowRow = computed(() => {
  const pageNo = activeFlowPageNo.value
  if (pageNo) {
    const selectedRow = flowNavigableRows.value.find((row) => Number(row.pageNo || 0) === pageNo)
    if (selectedRow) return selectedRow
  }
  return directiveRowList.value[0] || flowNavigableRows.value[0] || null
})
const flowNavigationRows = computed(() => flowNavigableRows.value.map((row) => ({
  id: row.id,
  pageNo: row.pageNo,
  mode: row.mode,
  title: row.title,
  statusLabel: row.statusLabel || (row.mode === 'outline' ? '目录草稿' : ''),
  statusClass: row.statusClass || row.mode,
  active: Number(row.pageNo || 0) === activeFlowPageNo.value,
})))
const shouldShowFlowNavigation = computed(() => !isViewingMaterials.value && !shouldShowNarrativePanel.value && flowNavigationRows.value.length > 0)
watch(flowNavigableRows, (rows) => {
  if (!localActivePageNo.value) return
  if (!rows.some((row) => Number(row.pageNo || 0) === Number(localActivePageNo.value || 0))) {
    localActivePageNo.value = 0
  }
})

function showFlowView(mode = '') {
  if (mode === 'materials' && (hasOutline.value || hasDirective.value)) flowViewMode.value = 'materials'
  if (mode === 'outline' && hasOutline.value) flowViewMode.value = 'outline'
  if (mode === 'directive' && canViewDirectiveStep.value) flowViewMode.value = 'directive'
}
const activeRevisionTarget = computed(() => props.activeRevisionTarget && typeof props.activeRevisionTarget === 'object' ? props.activeRevisionTarget : {})
const activeRevisionType = computed(() => String(activeRevisionTarget.value.type || ''))
const revisionDrawerOpen = computed(() => activeRevisionType.value === 'outline' || activeRevisionType.value === 'directive')
const activeRevisionTitle = computed(() => activeRevisionType.value === 'directive' ? '修改页面 brief' : '修改目录小节')
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

function setFlowRowRef(pageNo = 0, element = null) {
  const key = String(Number(pageNo || 0) || pageNo)
  if (!key) return
  if (element) {
    directiveRowRefs[key] = element
  } else {
    delete directiveRowRefs[key]
  }
}

function scrollFlowRowIntoView(pageNo = 0, options = {}) {
  const key = String(Number(pageNo || 0) || pageNo)
  const element = directiveRowRefs[key]
  if (!element) return
  const behavior = options.behavior || 'auto'
  const container = element.closest('.agent-ppt-main-scroll')
  if (!container || typeof container.scrollTo !== 'function') {
    element.scrollIntoView({ block: 'nearest', behavior })
    return
  }
  const containerRect = container.getBoundingClientRect()
  const elementRect = element.getBoundingClientRect()
  const topGap = elementRect.top - containerRect.top
  const bottomGap = elementRect.bottom - containerRect.bottom
  if (topGap >= 12 && bottomGap <= -12) return
  const nextTop = container.scrollTop + topGap - 12
  container.scrollTo({ top: Math.max(0, nextTop), behavior })
}

function selectFlowRow(row = {}) {
  if (!row || !row.id) return
  localActivePageNo.value = Number(row.pageNo || 0) || 0
  if (row.mode === 'directive') emit('select-slide', row.id)
  scrollFlowRowIntoView(row.pageNo, { behavior: 'auto' })
}

function openActiveFlowRevision() {
  if (!activeFlowRow.value || isRowGenerating(activeFlowRow.value)) return
  openRevisionForRow(activeFlowRow.value)
}

function undoActiveFlowRevision() {
  if (!activeFlowRow.value || isRowGenerating(activeFlowRow.value)) return
  undoRowRevision(activeFlowRow.value)
}

function visualArtifactFor(row = {}, visual = {}) {
  const visualId = String(visual.visual_id || visual.visualId || '')
  return (row.visualArtifacts || []).find((item) => String(item.visual_id || item.visualId || '') === visualId) || {}
}

const isAnyVisualGenerating = computed(() => Object.values(props.visualGenerationBySlide || {}).some((item) => String(item && item.status) === 'generating'))

function visualGenerationStatus(slideIndex = 0) {
  const status = (props.visualGenerationBySlide || {})[String(Number(slideIndex || 0) || 0)]
  return status && typeof status === 'object' ? status : { status: 'idle', error: '' }
}

function isVisualGenerating(row = {}) {
  return String((row.visualStatus || {}).status || '') === 'generating'
}

function canGenerateRowVisuals(row = {}) {
  return row.mode === 'directive' && Array.isArray(row.visualSpecs) && row.visualSpecs.length > 0 && !isGenerationJobActive.value && !isSlideGenerationActive.value && !isVisualGenerating(row)
}

function visualPreviewUrl(row = {}, visual = {}) {
  const artifact = visualArtifactFor(row, visual)
  const asset = visual.asset && typeof visual.asset === 'object' ? visual.asset : {}
  return artifact.url || asset.url || asset.data_url || asset.dataUrl || ''
}

function isVisualPreviewFailed(row = {}, visual = {}) {
  const url = visualPreviewUrl(row, visual)
  return !!url && failedVisualPreviewUrls.value.has(url)
}

function markVisualPreviewFailed(row = {}, visual = {}) {
  const url = visualPreviewUrl(row, visual)
  if (!url) return
  failedVisualPreviewUrls.value = new Set([...failedVisualPreviewUrls.value, url])
}

function openVisualPreview(row = {}, visual = {}) {
  const url = visualPreviewUrl(row, visual)
  if (!url) return
  visualPreviewDialog.value = {
    url,
    title: visual.title || visual.caption || '可视化预览',
  }
}

function closeVisualPreview() {
  visualPreviewDialog.value = { url: '', title: '' }
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
  nowTickTimer = window.setInterval(() => {
    nowTick.value = Date.now()
  }, 1000)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleSourceMenuKeydown)
  if (nowTickTimer) {
    window.clearInterval(nowTickTimer)
    nowTickTimer = null
  }
  setSourceMenuScrollLock(false)
})

function groupTitle(groupId = '') {
  return (props.sourceGroups.find((group) => String(group.id || '') === String(groupId || '')) || {}).title || '来源'
}

function isBulkDeleteSelected(source = {}) {
  return bulkDeleteSourceIds.value.has(String(source.id || ''))
}

function enterBulkDeleteMode() {
  if (!canStartBulkDelete.value) return
  bulkDeleteMode.value = true
  bulkDeleteSourceIds.value = new Set()
  closeSourceMenu()
}

function exitBulkDeleteMode() {
  bulkDeleteMode.value = false
  bulkDeleteSourceIds.value = new Set()
}

function toggleBulkDeleteSource(source = {}) {
  if (!bulkDeleteMode.value || props.sourceDeleting || !isDeletableSource(source)) return
  const sourceId = String(source.id || '')
  if (!sourceId) return
  const next = new Set(bulkDeleteSourceIds.value)
  if (next.has(sourceId)) next.delete(sourceId)
  else next.add(sourceId)
  bulkDeleteSourceIds.value = next
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
  if (bulkDeleteMode.value) {
    toggleBulkDeleteSource(source)
    return
  }
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
    if (bulkDeleteSourceIds.value.size) {
      const allowed = new Set(props.sources.map((source) => String(source && source.id || '')).filter(Boolean))
      const next = new Set(Array.from(bulkDeleteSourceIds.value).filter((sourceId) => allowed.has(sourceId)))
      if (next.size !== bulkDeleteSourceIds.value.size) bulkDeleteSourceIds.value = next
    }
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

function openRemoveSelectedSources() {
  if (!bulkDeleteSelectedSources.value.length || props.sourceDeleting) return
  const deleteCount = bulkDeleteSelectedSources.value.length
  sourceDialog.value = {
    mode: 'remove-selected-sources',
    id: '',
    title: '批量删除来源',
    value: '',
    message: `确认彻底删除 ${deleteCount} 个来源？文档、资料包和 AI 搜索资料会从数据库删除。`,
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

async function openWebSourceDialog(mode = 'search') {
  const inputMode = String(mode || '') === 'url' ? 'url' : 'search'
  webSourceDialog.value = openWebSourceDialogForm(webSourceDialog.value, {
    inputMode,
    loadingDefault: true,
    topic: props.spec.topic || '',
  })
  try {
    const defaults = await new Promise((resolve) => {
      emit('manage-web-source', {
        mode: 'location-default',
        resolve,
      })
    })
    webSourceDialog.value = {
      ...webSourceDialog.value,
      loadingDefault: false,
      regionName: defaults && defaults.region_name ? defaults.region_name : '当前分析区域',
      administrativeArea: defaults && defaults.administrative_area ? defaults.administrative_area : '',
      warnings: Array.isArray(defaults && defaults.warnings) ? defaults.warnings : [],
    }
  } catch (_) {
    webSourceDialog.value = {
      ...webSourceDialog.value,
      loadingDefault: false,
      regionName: '当前分析区域',
      administrativeArea: '',
      warnings: ['默认地区名生成失败，请手动输入。'],
    }
  }
}

function closeWebSourceDialog() {
  webSourceDialog.value = closeWebSourceDialogForm(webSourceDialog.value)
}

function backToWebSourceForm() {
  webSourceDialog.value = {
    ...webSourceDialog.value,
    step: 'form',
    error: '',
  }
}

function isWebSourceModeSelected(mode = '') {
  const selected = Array.isArray(webSourceDialog.value.sourceModes) ? webSourceDialog.value.sourceModes : []
  return selected.includes(String(mode || '').trim())
}

function isWebSourceItemSelected(item = {}, index = 0) {
  const selected = Array.isArray(webSourceDialog.value.selectedItemKeys) ? webSourceDialog.value.selectedItemKeys : []
  return selected.includes(webSourceItemKey(item, index))
}

function isWebSourceItemActive(index = 0) {
  return Math.max(0, Number(webSourceDialog.value.activeItemIndex || 0)) === Math.max(0, Number(index || 0))
}

function selectWebSourcePreviewItem(index = 0) {
  webSourceDialog.value = {
    ...webSourceDialog.value,
    activeItemIndex: Math.max(0, Number(index || 0)),
  }
}

function toggleWebSourcePreviewItem(index = 0) {
  const item = webSourcePreviewItems.value[index]
  if (!item) return
  const key = webSourceItemKey(item, index)
  const selected = Array.isArray(webSourceDialog.value.selectedItemKeys) ? webSourceDialog.value.selectedItemKeys : []
  webSourceDialog.value = {
    ...webSourceDialog.value,
    selectedItemKeys: selected.includes(key)
      ? selected.filter((itemKey) => itemKey !== key)
      : [...selected, key],
  }
}

function selectAllWebSourcePreviewItems() {
  webSourceDialog.value = {
    ...webSourceDialog.value,
    selectedItemKeys: webSourcePreviewItems.value.map((item, index) => webSourceItemKey(item, index)),
  }
}

function clearWebSourcePreviewSelection() {
  webSourceDialog.value = {
    ...webSourceDialog.value,
    selectedItemKeys: [],
  }
}

function toggleWebSourceCategory(category = '') {
  webSourceDialog.value = {
    ...webSourceDialog.value,
    categories: toggleWebSourceCategorySelection(webSourceDialog.value.categories, category),
  }
}

function toggleWebSourceMode(mode = '') {
  webSourceDialog.value = {
    ...webSourceDialog.value,
    sourceModes: toggleWebSourceModeSelection(webSourceDialog.value.sourceModes, mode),
  }
}

function setWebSourceInputMode(mode = 'search') {
  const inputMode = String(mode || '') === 'url' ? 'url' : 'search'
  webSourceDialog.value = {
    ...webSourceDialog.value,
    inputMode,
    error: '',
    preview: null,
    selectedItemKeys: [],
    activeItemIndex: 0,
  }
}

async function submitWebSourceDialog() {
  if (!canSearchWebSource.value) return
  const urls = webSourceDialog.value.inputMode === 'url' ? parseWebSourceUrls(webSourceDialog.value.urlText) : []
  if (webSourceDialog.value.inputMode === 'url' && !urls.length) {
    webSourceDialog.value = {
      ...webSourceDialog.value,
      error: '请输入以 http:// 或 https:// 开头的网页 URL。',
    }
    return
  }
  const payload = buildWebSourcePreviewPayload(webSourceDialog.value, props.spec.topic)
  webSourceDialog.value = {
    ...webSourceDialog.value,
    searching: true,
    error: '',
    warnings: [],
  }
  try {
    const preview = await new Promise((resolve, reject) => {
      emit('manage-web-source', { ...payload, resolve, reject })
    })
    webSourceDialog.value = {
      ...webSourceDialog.value,
      step: 'preview',
      searching: false,
      preview,
      activeItemIndex: 0,
      selectedItemKeys: Array.isArray(preview && preview.items) ? preview.items.map((item, index) => webSourceItemKey(item, index)) : [],
      warnings: Array.isArray(preview && preview.warnings) ? preview.warnings : [],
    }
  } catch (error) {
    webSourceDialog.value = {
      ...webSourceDialog.value,
      searching: false,
      error: error && error.message ? error.message : '搜索失败',
    }
  }
}

async function commitWebSourceDialog() {
  if (!canCommitWebSource.value) return
  webSourceDialog.value = {
    ...webSourceDialog.value,
    adding: true,
    error: '',
  }
  try {
    const selectedItems = selectedWebSourcePreviewItems.value
    const commitPreview = buildWebSourceCommitPreview(webSourceDialog.value.preview, selectedItems)
    await new Promise((resolve, reject) => {
      emit('manage-web-source', {
        mode: 'commit',
        preview: commitPreview,
        resolve,
        reject,
      })
    })
    closeWebSourceDialog()
  } catch (error) {
    webSourceDialog.value = {
      ...webSourceDialog.value,
      adding: false,
      error: error && error.message ? error.message : '添加失败',
    }
  }
}

function openDocumentSourcePicker() {
  documentSourceInput.value?.click()
}

function handleDocumentSourceSelected(event) {
  const file = event?.target?.files?.[0]
  if (event?.target) event.target.value = ''
  if (!file) return
  const mimeType = String(file.type || '').toLowerCase()
  const fileName = String(file.name || '').toLowerCase()
  if (mimeType.startsWith('image/') || /\.(png|jpe?g|webp|bmp|tiff?)$/.test(fileName)) {
    emit('upload-image-source', file)
    return
  }
  if (mimeType === 'application/pdf' || /\.(pdf|docx)$/.test(fileName)) {
    emit('upload-document-source', file)
    return
  }
  sourceDialog.value = {
    mode: 'unsupported-source',
    id: '',
    title: '不支持的来源文件',
    value: '',
    message: '来源区目前支持 PDF、DOCX 和常见图片格式。',
  }
}

async function confirmSourceDialog() {
  const dialog = sourceDialog.value
  if (dialog.mode === 'rename-source') emit('rename-source', dialog.id, dialog.value)
  if (dialog.mode === 'remove-source') emit('remove-source', dialog.id)
  if (dialog.mode === 'remove-selected-sources') {
    const sourceIds = Array.from(bulkDeleteSourceIds.value)
    const done = new Promise((resolve) => {
      emit('remove-selected-sources', { source_ids: sourceIds, resolve })
    })
    closeSourceDialog()
    await done
    exitBulkDeleteMode()
    return
  }
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
            accept=".pdf,.docx,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,image/*"
            @change="handleDocumentSourceSelected">
          <button type="button" class="agent-ppt-add-source-btn" @click="openDocumentSourcePicker">+ 添加来源</button>
          <div class="agent-ppt-source-search">
            <div class="agent-ppt-source-search-main">
              <span class="agent-ppt-source-search-title">联网来源</span>
              <div class="agent-ppt-source-search-chips">
                <span>可信优先</span>
                <span>自动引用</span>
              </div>
            </div>
            <div class="agent-ppt-source-search-actions">
              <button
                type="button"
                class="agent-ppt-source-search-action is-primary"
                :disabled="webSourceGenerating"
                @click="openWebSourceDialog('search')">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <circle cx="11" cy="11" r="6"></circle>
                  <path d="M16 16l4 4"></path>
                </svg>
                <span>{{ webSourceGenerating ? '搜索中' : 'AI 搜索' }}</span>
              </button>
              <button
                type="button"
                class="agent-ppt-source-search-action"
                :disabled="webSourceGenerating"
                @click="openWebSourceDialog('url')">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M12 5v14"></path>
                  <path d="M5 12h14"></path>
                </svg>
                <span>添加 URL</span>
              </button>
            </div>
          </div>
          <button
            type="button"
            class="agent-ppt-data-package-btn"
            :disabled="!canCreateDataPackage"
            @click="$emit('create-data-package')">
            {{ dataPackageGenerating ? '整理中' : '生成资料包' }}
          </button>
          <div class="agent-ppt-source-tree-toolbar">
            <div class="agent-ppt-source-toolbar-status">
              <button
                type="button"
                class="agent-ppt-source-tag-btn"
                :disabled="sourceGrouping || !sources.length"
                title="重新为来源加标签"
                aria-label="重新为来源加标签"
                @click="$emit('classify-source-groups')">
                <span aria-hidden="true">✧</span>
              </button>
              <div class="agent-ppt-source-toolbar-copy">
                <strong>
                  {{ sourceSummary.selected || 0 }}/{{ sourceSummary.total || 0 }}
                  <span v-if="sourceRefreshing" class="agent-ppt-source-refresh-dot" aria-label="正在同步来源"></span>
                </strong>
                <small>{{ deliverableSourceCount }} 个可用于 AI</small>
              </div>
            </div>
            <button
              type="button"
              class="agent-ppt-source-select-row"
              v-if="!bulkDeleteMode"
              :class="{ 'is-selected': sourceSummary.ready > 0 && sourceSummary.selected === sourceSummary.ready }"
              @click="$emit('toggle-all-sources')">
              <span>全选</span>
              <span
                class="agent-ppt-source-checkbox"
                :class="{ 'is-checked': sourceSummary.ready > 0 && sourceSummary.selected === sourceSummary.ready }"
                aria-hidden="true">
                {{ sourceSummary.ready > 0 && sourceSummary.selected === sourceSummary.ready ? '✓' : '' }}
              </span>
            </button>
            <button
              v-if="!bulkDeleteMode"
              type="button"
              class="agent-ppt-source-select-row"
              :disabled="!sources.length"
              @click="$emit('export-all-sources')">
              <span>一键导出</span>
            </button>
            <button
              v-if="!bulkDeleteMode"
              type="button"
              class="agent-ppt-source-select-row agent-ppt-source-delete-selected"
              :disabled="!canStartBulkDelete"
              @click="enterBulkDeleteMode">
              <span>批量删除</span>
            </button>
            <button
              v-if="bulkDeleteMode"
              type="button"
              class="agent-ppt-source-select-row"
              :disabled="sourceDeleting"
              @click="exitBulkDeleteMode">
              <span>取消</span>
            </button>
            <button
              v-if="bulkDeleteMode"
              type="button"
              class="agent-ppt-source-select-row agent-ppt-source-delete-selected"
              :disabled="!canConfirmBulkDelete"
              @click="openRemoveSelectedSources">
              <span>{{ sourceDeleting ? '删除中' : `删除 ${bulkDeleteSelectedSources.length} 项` }}</span>
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
                  v-if="!bulkDeleteMode"
                  type="button"
                  class="agent-ppt-source-menu-btn"
                  aria-label="更多选项"
                  title="更多选项"
                  @click.stop="toggleSourceMenu('group', group.id, $event)">
                  ⋮
                </button>
                <button
                  v-if="!bulkDeleteMode"
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
                  :class="[{ 'is-ready': source.status === 'ready', 'is-generating': isGeneratingSource(source), 'is-pending': source.status !== 'ready', 'is-selected': bulkDeleteMode ? isBulkDeleteSelected(source) : source.selected }, `is-${source.type || 'file'}`, `is-health-${sourceHealth(source).healthStatus}`]">
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
                      <span class="agent-ppt-source-health" :class="`is-${sourceHealth(source).healthStatus}`" :title="sourceHealthReason(source)">
                        {{ sourceHealthLabel(source) }}
                      </span>
                      <em v-if="sourceTransportLabel(source)">{{ sourceTransportLabel(source) }}</em>
                    </span>
                  </button>
                  <button
                    v-if="!bulkDeleteMode"
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
                    :class="{ 'is-checked': bulkDeleteMode ? isBulkDeleteSelected(source) : source.selected }"
                    :disabled="bulkDeleteMode && !isDeletableSource(source)"
                    :aria-label="bulkDeleteMode ? '选择删除来源' : '切换来源选择'"
                    @click.stop="bulkDeleteMode ? toggleBulkDeleteSource(source) : $emit('toggle-source', source.id)">
                    {{ (bulkDeleteMode ? isBulkDeleteSelected(source) : source.selected) ? '✓' : '' }}
                  </button>
                  <span v-else class="agent-ppt-source-loading" :class="{ 'is-generating': isGeneratingSource(source) }" aria-label="未就绪"></span>
                  <div
                    v-if="sourceMenu.kind === 'source' && sourceMenu.id === source.id"
                    class="agent-ppt-source-menu"
                    :class="{ 'is-above': sourceMenu.placement === 'above' }"
                    :style="{ left: `${sourceMenu.x}px`, top: `${sourceMenu.y}px` }">
                    <button v-if="isPackagePlaceholderSource(source)" type="button" @click="$emit('generate-package-source', source.id)">生成资料包</button>
                    <button v-if="isRetryableSource(source)" type="button" @click="$emit('retry-source', source.id)">重试构建</button>
                    <button v-if="isPackageSource(source)" type="button" @click="openPackageDetail(source)">查看内容</button>
                    <button v-if="isCurrentSource(source)" type="button" @click="openCurrentSourceDetail(source)">查看分析</button>
                    <button
                      v-if="isDocumentSource(source)"
                      type="button"
                      :disabled="!(((source.meta && source.meta.document_index_preview) || []).length)"
                      @click="openDocumentEvidence(source)">
                      查看结构
                    </button>
                    <button type="button" @click="$emit('export-source', source.id)">完整导出</button>
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
              :class="[{ 'is-ready': source.status === 'ready', 'is-generating': isGeneratingSource(source), 'is-pending': source.status !== 'ready', 'is-selected': bulkDeleteMode ? isBulkDeleteSelected(source) : source.selected }, `is-${source.type || 'file'}`, `is-health-${sourceHealth(source).healthStatus}`]">
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
                  <span class="agent-ppt-source-health" :class="`is-${sourceHealth(source).healthStatus}`" :title="sourceHealthReason(source)">
                    {{ sourceHealthLabel(source) }}
                  </span>
                  <em v-if="sourceTransportLabel(source)">{{ sourceTransportLabel(source) }}</em>
                </span>
              </button>
              <button
                v-if="!bulkDeleteMode"
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
                :class="{ 'is-checked': bulkDeleteMode ? isBulkDeleteSelected(source) : source.selected }"
                :disabled="bulkDeleteMode && !isDeletableSource(source)"
                :aria-label="bulkDeleteMode ? '选择删除来源' : '切换来源选择'"
                @click.stop="bulkDeleteMode ? toggleBulkDeleteSource(source) : $emit('toggle-source', source.id)">
                {{ (bulkDeleteMode ? isBulkDeleteSelected(source) : source.selected) ? '✓' : '' }}
              </button>
              <span v-else class="agent-ppt-source-loading" :class="{ 'is-generating': isGeneratingSource(source) }" aria-label="未就绪"></span>
              <div
                v-if="sourceMenu.kind === 'source' && sourceMenu.id === source.id"
                class="agent-ppt-source-menu"
                :class="{ 'is-above': sourceMenu.placement === 'above' }"
                :style="{ left: `${sourceMenu.x}px`, top: `${sourceMenu.y}px` }">
                <button v-if="isPackagePlaceholderSource(source)" type="button" @click="$emit('generate-package-source', source.id)">生成资料包</button>
                <button v-if="isRetryableSource(source)" type="button" @click="$emit('retry-source', source.id)">重试构建</button>
                <button v-if="isPackageSource(source)" type="button" @click="openPackageDetail(source)">查看内容</button>
                <button v-if="isCurrentSource(source)" type="button" @click="openCurrentSourceDetail(source)">查看分析</button>
                <button
                  v-if="isDocumentSource(source)"
                  type="button"
                  :disabled="!(((source.meta && source.meta.document_index_preview) || []).length)"
                  @click="openDocumentEvidence(source)">
                  查看结构
                </button>
                <button type="button" @click="$emit('export-source', source.id)">完整导出</button>
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
          <small>{{ deliverableSourceCount }} AI</small>
        </button>
      </aside>

      <section class="agent-ppt-notebook-panel agent-ppt-center-panel" aria-label="聊天工作区">
        <slot name="center">
          <div class="agent-ppt-center-empty">
            <strong>聊天区</strong>
            <span>把完整对话放在这里，围绕来源继续发问。</span>
          </div>
        </slot>
      </section>

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
              'is-current': !isViewingMaterials && (activeFlowIndex === 1 || isViewingOutline),
              'is-complete': hasOutline && activeFlowIndex > 1 && !isViewingOutline
            }"
            :disabled="!canViewOutlineStep"
            @click="showFlowView('outline')">
            生成目录
          </button>
          <button
            type="button"
            :class="{ 'is-current': !isViewingMaterials && !isViewingOutline && activeFlowIndex === 2 && !hasNarrativePlan, 'is-complete': hasNarrativePlan }"
            :disabled="!hasNarrativePlan">
            生成叙事
          </button>
          <button
            type="button"
            :class="{ 'is-current': !isViewingMaterials && !isViewingOutline && ((hasNarrativePlan && !hasDirective) || activeFlowIndex === 3 || isViewingDirective), 'is-complete': hasDirective && activeFlowIndex > 3 && !isViewingDirective }"
            :disabled="!canViewDirectiveStep"
            @click="showFlowView('directive')">
            生成指令
          </button>
          <button
            type="button"
            :class="{ 'is-current': activeFlowIndex === 4 && !isViewingDirective, 'is-complete': hasVisualArtifacts }"
            :disabled="!hasDirective">
            生成图片
          </button>
          <button type="button" disabled>选择风格</button>
          <button type="button" :class="{ 'is-current': activeFlowIndex === 6 }" disabled>生成页面</button>
          <button type="button" :class="{ 'is-current': activeFlowIndex === 7 }" disabled>导出</button>
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
            <strong>{{ sourceSummary.selected || 0 }} 个已选来源 · {{ deliverableSourceCount }} 个可用于 AI</strong>
            <small v-if="emptyPayloadSourceCount">{{ emptyPayloadSourceCount }} 个未进入模型</small>
          </div>
        </div>
        <div class="agent-ppt-main-scroll">
          <div v-if="shouldShowConfigPanel" class="agent-ppt-target-config-panel">
            <div class="agent-ppt-target-config-head">
              <div>
                <span>生成前检查</span>
                <strong>配置目录生成目标</strong>
              </div>
              <small :class="{ 'is-blocked': !!outlineBlockReason }">
                {{ generationErrorText ? generationErrorTitle : configCheckStatus }}
              </small>
            </div>
            <div class="agent-ppt-target-config-body">
              <label class="agent-ppt-config-field is-topic">
                <span>主题</span>
                <input
                  type="text"
                  :value="spec.topic || ''"
                  placeholder="输入 PPT 主题"
                  @input="$emit('update-spec-field', 'topic', $event.target.value)">
              </label>
              <div class="agent-ppt-config-checks" aria-label="生成前检查项">
                <article
                  v-for="item in configCheckItems"
                  :key="`ppt-config-check-${item[0]}`">
                  <span>{{ item[0] }}</span>
                  <strong>{{ item[1] }}</strong>
                </article>
              </div>
            </div>
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
                <strong>{{ sourceSummary.selected || 0 }} 个已选来源 · {{ deliverableSourceCount }} 个可用于 AI</strong>
                <small v-if="emptyPayloadSourceCount">{{ emptyPayloadSourceCount }} 个未进入模型</small>
                <small v-if="blockingInputSources.length">{{ blockingInputSources.length }} 个来源仍未就绪</small>
              </div>
            </div>
          </div>
          <div v-else class="agent-ppt-directive-doc">
            <section v-if="shouldShowNarrativePanel" class="agent-ppt-narrative-panel" aria-label="叙事方案">
              <header class="agent-ppt-narrative-head">
                <div>
                  <span>叙事方案</span>
                  <strong>编剧分镜表</strong>
                </div>
                <small>{{ narrativeRoleRows.length }} 页角色</small>
              </header>
              <div v-if="narrativeStorylineText" class="agent-ppt-narrative-strategy">
                <article>
                  <span>一句话主线</span>
                  <p>{{ narrativeStorylineText }}</p>
                </article>
              </div>
              <div v-if="narrativeChapterRows.length" class="agent-ppt-narrative-strategy">
                <article
                  v-for="chapter in narrativeChapterRows"
                  :key="chapter.id">
                  <span>{{ chapter.name }}</span>
                  <p v-if="chapter.pageRange">页码：{{ chapter.pageRange }}</p>
                  <p>任务：{{ chapter.job || '待补充' }}</p>
                  <p>输出：{{ chapter.output || '待补充' }}</p>
                </article>
              </div>
              <div class="agent-ppt-narrative-roles">
                <article
                  v-for="role in narrativeRoleRows"
                  :key="role.id"
                  class="agent-ppt-narrative-role">
                  <span class="agent-ppt-directive-page">{{ String(role.pageNo).padStart(2, '0') }}</span>
                  <div class="agent-ppt-directive-content">
                    <strong>{{ role.title }}</strong>
                    <em>{{ role.job || '未提供页面任务' }}</em>
                    <dl class="agent-ppt-directive-fields">
                      <div v-if="role.evidenceBucket">
                        <dt>证据桶</dt>
                        <dd>{{ role.evidenceBucket }}</dd>
                      </div>
                      <div v-if="role.visualFamily">
                        <dt>视觉家族</dt>
                        <dd>{{ role.visualFamily }}</dd>
                      </div>
                      <div v-if="role.transitionNote">
                        <dt>承接关系</dt>
                        <dd>{{ role.transitionNote }}</dd>
                      </div>
                    </dl>
                  </div>
                </article>
              </div>
              <div v-if="narrativeEvidenceBuckets.length" class="agent-ppt-narrative-strategy">
                <article
                  v-for="item in narrativeEvidenceBuckets"
                  :key="item.id">
                  <span>{{ item.label }}</span>
                  <p>ID：{{ item.id }}</p>
                  <p v-if="item.allowedSources.length">可用来源：{{ item.allowedSources.join(' / ') }}</p>
                </article>
              </div>
              <div class="agent-ppt-narrative-strategy">
                <article>
                  <span>视觉规则</span>
                  <p
                    v-for="rule in narrativeVisualRules"
                    :key="`narrative-rule-${rule.label}`">
                    {{ rule.label }}：{{ rule.enabled ? '启用' : '关闭' }}
                  </p>
                </article>
              </div>
            </section>
            <template v-else>
              <div
                v-for="row in outlineRows"
                :key="`ppt-flow-row-${row.mode}-${row.pageNo}-${row.id}`"
                :ref="(element) => setFlowRowRef(row.pageNo, element)"
                class="agent-ppt-directive-row"
                :class="{ 'is-draft': row.mode === 'outline', 'is-directive': row.mode === 'directive', 'is-active': row.pageNo === activeFlowPageNo }">
                <span class="agent-ppt-directive-page">{{ String(row.pageNo).padStart(2, '0') }}</span>
                <div class="agent-ppt-directive-content">
                  <strong>
                    {{ row.title }}
                    <small
                      v-if="row.statusLabel"
                      class="agent-ppt-row-status"
                      :class="`is-${row.statusClass || row.mode}`">
                      {{ row.statusLabel }}
                    </small>
                  </strong>
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
                      <small class="agent-ppt-metric-source">
                        {{ claim.source_id || claim.sourceId || '来源' }}
                        <template v-if="claim.status || claim.scope || claim.spatial_scope || claim.spatialScope"> · {{ claim.status || 'ready' }} · {{ claim.scope || claim.spatial_scope || claim.spatialScope }}</template>
                      </small>
                      <small v-if="claim.source_path || claim.sourcePath || claim.calculation_method || claim.calculationMethod || claim.method" class="agent-ppt-metric-detail">
                        {{ claim.source_path || claim.sourcePath || claim.calculation_method || claim.calculationMethod || claim.method }}
                      </small>
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
                  <div v-if="row.visualSpecs.length" class="agent-ppt-chart-specs">
                    <span>
                      可视化方案
                      <small v-if="row.visualStatus && row.visualStatus.status === 'generating'">生成中</small>
                      <small v-else-if="row.visualStatus && row.visualStatus.status === 'failed'">{{ row.visualStatus.error || '生成失败' }}</small>
                      <small v-else-if="row.visualArtifacts.length">已生成 {{ row.visualArtifacts.length }} 个</small>
                    </span>
                    <article
                      v-for="visual in row.visualSpecs"
                      :key="`visual-spec-${row.id}-${visual.visual_id || visual.visualId || visual.title}`">
                      <header>
                        <strong>{{ visual.title || '可视化' }}</strong>
                        <small :class="`is-${visual.status || 'draft'}`">{{ visualTypeLabel(visual) }} · {{ visual.status || 'draft' }}</small>
                      </header>
                      <p v-if="visual.intent || visual.caption">
                        <b>证明：</b>{{ visual.intent || visual.caption }}
                      </p>
                      <p v-if="visualEvidenceSummary(visual)">
                        <b>证据：</b>{{ visualEvidenceSummary(visual) }}
                      </p>
                      <p v-if="visualReasonText(visual)" class="agent-ppt-visual-missing-reason">
                        <b>缺口：</b>{{ visualReasonText(visual) }}
                      </p>
                      <button
                        v-if="visualPreviewUrl(row, visual)"
                        type="button"
                        class="agent-ppt-visual-preview-link"
                        @click="openVisualPreview(row, visual)">
                        <img
                          :src="visualPreviewUrl(row, visual)"
                          :alt="visual.title || '可视化预览'"
                          @error="markVisualPreviewFailed(row, visual)">
                      </button>
                      <p v-if="isVisualPreviewFailed(row, visual)" class="agent-ppt-visual-preview-error">
                        图片已生成，但预览被浏览器拦截或加载失败。
                        <button type="button" @click="openVisualPreview(row, visual)">查看大图</button>
                      </p>
                      <div
                        v-if="visualComposition(visual) === 'map_with_metric_overlays' && visualMetricOverlays(visual).length"
                        class="agent-ppt-visual-metric-overlays">
                        <article
                          v-for="overlay in visualMetricOverlays(visual)"
                          :key="`visual-overlay-${row.id}-${visual.visual_id || visual.visualId}-${overlay.metric_id || overlay.metricId || overlay.label}`">
                          <span>{{ overlay.label || overlay.metric_id || overlay.metricId }}</span>
                          <strong>{{ formatVisualOverlayValue(overlay) }}</strong>
                        </article>
                      </div>
                      <p v-if="visual.visual_type === 'existing_asset'">
                        {{ visual.asset_kind || visual.assetKind || '空间图资产' }}
                        <template v-if="visual.source || (visual.asset && visual.asset.source)"> · {{ visual.source || (visual.asset && visual.asset.source) }}</template>
                        <template v-if="visual.caption"> · {{ visual.caption }}</template>
                      </p>
                      <p v-if="visual.status === 'needs_design_render'">语义结构已生成，等待设计渲染。</p>
                      <p v-if="visual.status === 'needs_existing_asset'">{{ visualExistingAssetMissingText(visual) }}</p>
                      <div
                        v-if="visualComposition(visual) === 'metric_dashboard' && visualMetricOverlays(visual).length"
                        class="agent-ppt-visual-metric-dashboard">
                        <article
                          v-for="overlay in visualMetricOverlays(visual)"
                          :key="`visual-dashboard-${row.id}-${visual.visual_id || visual.visualId}-${overlay.metric_id || overlay.metricId || overlay.label}`">
                          <span>{{ overlay.label || overlay.metric_id || overlay.metricId }}</span>
                          <strong>{{ formatVisualOverlayValue(overlay) }}</strong>
                        </article>
                      </div>
                      <table v-if="visualComposition(visual) !== 'metric_dashboard' && ['figure', 'table', 'metric_card'].includes(String(visual.visual_type || visual.visualType || '')) && visualRowsPreview(visual).length && visualColumnsPreview(visual).length">
                        <thead>
                          <tr>
                            <th
                              v-for="column in visualColumnsPreview(visual)"
                              :key="`visual-column-${row.id}-${visual.visual_id || visual.visualId}-${visualColumnKey(column)}`">
                              {{ visualColumnLabel(column) }}
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr
                            v-for="(visualRow, visualRowIndex) in visualRowsPreview(visual)"
                            :key="`visual-row-${row.id}-${visual.visual_id || visual.visualId}-${visualRowIndex}`">
                            <td
                              v-for="column in visualColumnsPreview(visual)"
                              :key="`visual-cell-${row.id}-${visual.visual_id || visual.visualId}-${visualRowIndex}-${visualColumnKey(column)}`">
                              {{ visualRow[visualColumnKey(column)] }}
                            </td>
                          </tr>
                        </tbody>
                      </table>
                      <ul v-if="['diagram', 'matrix'].includes(String(visual.visual_type || visual.visualType || ''))" class="agent-ppt-visual-outline">
                        <li v-if="visual.diagram_kind || visual.diagramKind">{{ visual.diagram_kind || visual.diagramKind }}</li>
                        <li v-for="item in visualNodeSummary(visual)" :key="`visual-node-${row.id}-${visual.visual_id || visual.visualId}-${item}`">{{ item }}</li>
                        <li v-for="item in visualGroupSummary(visual)" :key="`visual-group-${row.id}-${visual.visual_id || visual.visualId}-${item}`">{{ item }}</li>
                        <li v-for="item in visualLinkSummary(visual)" :key="`visual-link-${row.id}-${visual.visual_id || visual.visualId}-${item}`">{{ item }}</li>
                        <li v-if="visual.design_notes">{{ visual.design_notes }}</li>
                        <li v-if="visual.layout_hint">{{ visual.layout_hint }}</li>
                      </ul>
                    </article>
                    <button
                      type="button"
                      class="agent-ppt-visual-generate-btn"
                      :disabled="!canGenerateRowVisuals(row)"
                      @click="$emit('generate-slide-visuals', row.pageNo)">
                      {{ row.visualArtifacts.length ? '重新生成本页可视化' : '生成本页可视化' }}
                    </button>
                  </div>
                </div>
              </div>
            </template>
            <div v-if="shouldShowGenerationJobPanel || hasGenerationResponsePayload" class="agent-ppt-debug-section">
              <details v-if="shouldShowGenerationJobPanel" class="agent-ppt-generation-job" :open="shouldOpenGenerationJobPanel">
                <summary>
                  <span>{{ generationJobTitle }}</span>
                  <small>{{ generationJobSummary || activeGenerationJob.id || '等待状态更新' }}</small>
                </summary>
                <div v-if="slideGenerationQueueChips.length" class="agent-ppt-slide-queue-strip" :aria-label="slideGenerationQueueSummary">
                  <span
                    v-for="item in slideGenerationQueueChips"
                    :key="`ppt-slide-queue-chip-${item.pageNo}`"
                    class="agent-ppt-slide-queue-chip"
                    :class="`is-${item.status}`"
                    :title="item.error || item.label">
                    <strong>{{ String(item.pageNo).padStart(2, '0') }}</strong>
                    <small>{{ item.label }}</small>
                  </span>
                </div>
                <ol>
                  <li
                    v-for="(event, eventIndex) in generationJobEvents"
                    :key="`ppt-generation-event-${eventIndex}-${event.name}`">
                    <strong>{{ event.name }}</strong>
                    <span>{{ event.at }}</span>
                    <code v-if="event.details && Object.keys(event.details).length">{{ JSON.stringify(event.details) }}</code>
                  </li>
                </ol>
              </details>
              <details v-if="hasGenerationResponsePayload" class="agent-ppt-generation-response">
                <summary>
                  <span>{{ generationResponseTitle }}</span>
                  <small>{{ generationResponseSummary || '点击查看原始 JSON' }}</small>
                </summary>
                <pre>{{ generationResponseJson }}</pre>
              </details>
            </div>
          </div>
        </div>
        <div
          class="agent-ppt-brief-control-dock"
          :class="{ 'has-brief-navigation': shouldShowFlowNavigation }">
          <div
            v-if="shouldShowFlowNavigation"
            class="agent-ppt-brief-navigation"
            :aria-label="isViewingOutline ? '目录页码导航' : 'brief 页码导航'">
            <div class="agent-ppt-page-nav">
              <button
                v-for="item in flowNavigationRows"
                :key="`ppt-flow-nav-${item.mode}-${item.pageNo}-${item.id}`"
                type="button"
                :class="[{ 'is-active': item.active }, `is-${item.statusClass || 'pending'}`]"
                :title="`${item.pageNo}. ${item.title || '页面'} · ${item.statusLabel || '待生成'}`"
                @click="selectFlowRow(item)">
                {{ item.pageNo }}
              </button>
            </div>
            <div class="agent-ppt-brief-actions">
              <div class="agent-ppt-brief-active-page">
                <span v-if="activeFlowRow">{{ String(activeFlowRow.pageNo).padStart(2, '0') }}</span>
                <strong>{{ activeFlowRow ? activeFlowRow.title : '未选中页面' }}</strong>
                <small v-if="activeFlowRow">{{ activeFlowRow.statusLabel || (activeFlowRow.mode === 'outline' ? '目录草稿' : '待生成') }}</small>
              </div>
              <div class="agent-ppt-brief-action-buttons">
                <button
                  type="button"
                  :disabled="!activeFlowRow || isRowGenerating(activeFlowRow)"
                  @click="openActiveFlowRevision">
                  编辑
                </button>
                <button
                  type="button"
                  :disabled="!activeFlowRow || isRowGenerating(activeFlowRow)"
                  @click="openActiveFlowRevision">
                  AI 重生成
                </button>
                <button
                  type="button"
                  :disabled="!activeFlowRow || !canUndoRow(activeFlowRow) || isRowGenerating(activeFlowRow)"
                  @click="undoActiveFlowRevision">
                  撤回
                </button>
              </div>
            </div>
          </div>
          <div class="agent-ppt-prompt-box">
            <span v-if="generationErrorText">{{ generationErrorText }}</span>
            <span v-else-if="isGenerationJobActive">{{ generationJobTitle }}</span>
            <span v-else>{{ promptStageText }}</span>
            <div class="agent-ppt-prompt-actions">
              <button
                v-for="action in promptActions"
                :key="`ppt-prompt-action-${action.id}`"
                type="button"
                :class="{ 'is-primary': action.primary }"
                :disabled="isPromptActionDisabled(action)"
                @click="emitPromptAction(action)">
                {{ action.label }}
              </button>
            </div>
          </div>
        </div>
      </section>
    </div>

    <div v-if="visualPreviewDialog.url" class="agent-ppt-visual-preview-backdrop" @click.self="closeVisualPreview">
      <section class="agent-ppt-visual-preview-dialog" role="dialog" aria-modal="true" :aria-label="visualPreviewDialog.title || '可视化预览'">
        <header>
          <strong>{{ visualPreviewDialog.title || '可视化预览' }}</strong>
          <button type="button" aria-label="关闭预览" title="关闭" @click="closeVisualPreview">×</button>
        </header>
        <div class="agent-ppt-visual-preview-stage">
          <img :src="visualPreviewDialog.url" :alt="visualPreviewDialog.title || '可视化预览'">
        </div>
      </section>
    </div>

    <div v-if="revisionDrawerOpen" class="agent-ppt-revision-backdrop" @click.self="$emit('close-revision-target')">
      <section class="agent-ppt-revision-drawer" role="dialog" aria-modal="true" :aria-label="activeRevisionTitle">
        <header class="agent-ppt-revision-head">
          <div>
            <span>{{ activeRevisionType === 'directive' ? '页面 brief' : '目录小节' }}</span>
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
            <span>页面核心表达</span>
            <textarea
              rows="3"
              :value="directiveRevisionDraft.keyMessage || ''"
              :disabled="isCurrentRevisionGenerating"
              @input="updateRevisionDraft('keyMessage', $event.target.value)"></textarea>
          </label>
          <label class="agent-ppt-config-field">
            <span>见地</span>
            <textarea
              rows="3"
              :value="directiveRevisionDraft.insight || ''"
              :disabled="isCurrentRevisionGenerating"
              placeholder="补充该页判断、推断或分析结论"
              @input="updateRevisionDraft('insight', $event.target.value)"></textarea>
          </label>
          <label class="agent-ppt-config-field">
            <span>证据解释</span>
            <textarea
              rows="3"
              :value="directiveRevisionDraft.evidenceExplanation || ''"
              :disabled="isCurrentRevisionGenerating"
              placeholder="每行一条，说明口径、阈值、来源或可信度"
              @input="updateRevisionDraft('evidenceExplanation', $event.target.value)"></textarea>
          </label>
          <label class="agent-ppt-config-field">
            <span>页面布局指令</span>
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
              <span>可视化方案</span>
              <strong>{{ Number(activeCurrentTransport.visual_spec_count ?? activeCurrentTransport.visualSpecCount ?? 0) || 0 }}</strong>
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

        <div v-if="activeCurrentVisualSpecs.length" class="agent-ppt-package-section-head">
          <strong>可视化方案</strong>
          <span>{{ activeCurrentVisualSpecs.length }} 个</span>
        </div>
        <div v-if="activeCurrentVisualSpecs.length" class="agent-ppt-current-metric-list">
          <article
            v-for="(visual, index) in activeCurrentVisualSpecs"
            :key="`current-visual-${visual.visual_id || visual.visualId || index}`"
            class="agent-ppt-current-metric-card">
            <header>
              <div>
                <span>{{ visualTypeLabel(visual) }}</span>
                <strong>{{ visual.title || '可视化' }}</strong>
              </div>
            </header>
            <dl>
              <div>
                <dt>状态</dt>
                <dd>{{ visual.status || 'draft' }}</dd>
              </div>
              <div>
                <dt>来源</dt>
                <dd>{{ (visual.sourceIds || visual.source_ids || []).length }}</dd>
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
          <button
            type="button"
            class="is-primary"
            :disabled="sourceDialog.mode === 'remove-selected-sources' && sourceDeleting"
            @click="confirmSourceDialog">
            {{ sourceDialog.mode === 'remove-selected-sources' && sourceDeleting ? '删除中' : '确认' }}
          </button>
        </div>
      </div>
    </div>
    <div v-if="webSourceDialog.open" class="agent-ppt-source-dialog-backdrop" @click.self="closeWebSourceDialog">
      <div class="agent-ppt-source-dialog agent-ppt-research-dialog" role="dialog" aria-modal="true">
        <strong>{{ webSourceDialog.inputMode === 'url' ? '添加网页来源' : 'AI 搜索地区资料' }}</strong>
        <p v-if="webSourceDialog.error" class="agent-ppt-research-error">{{ webSourceDialog.error }}</p>
        <p v-else-if="webSourceDialog.loadingDefault">正在根据当前范围生成地区默认值...</p>
        <p v-else-if="webSourceDialog.warnings.length">{{ webSourceDialog.warnings.join('；') }}</p>

        <template v-if="webSourceDialog.step === 'form'">
          <div class="agent-ppt-research-source-list">
            <span>接入方式</span>
            <button
              type="button"
              :class="{ 'is-selected': webSourceDialog.inputMode === 'search' }"
              @click="setWebSourceInputMode('search')">
              AI 搜索
            </button>
            <button
              type="button"
              :class="{ 'is-selected': webSourceDialog.inputMode === 'url' }"
              @click="setWebSourceInputMode('url')">
              添加 URL
            </button>
          </div>
          <label>
            <span>地区名</span>
            <input v-model="webSourceDialog.regionName" type="text" autofocus>
          </label>
          <label>
            <span>城市/行政区</span>
            <input v-model="webSourceDialog.administrativeArea" type="text">
          </label>
          <label>
            <span>{{ webSourceDialog.inputMode === 'url' ? '资料主题' : '搜索目标' }}</span>
            <input v-model="webSourceDialog.topic" type="text">
          </label>
          <label v-if="webSourceDialog.inputMode === 'url'">
            <span>网页 URL</span>
            <textarea
              v-model="webSourceDialog.urlText"
              rows="4"
              placeholder="每行一个 URL，例如 https://www.gov.cn/..."></textarea>
          </label>
          <div v-if="webSourceDialog.inputMode === 'search'" class="agent-ppt-web-source-category-list">
            <button
              v-for="category in ['政策背景', '区域概况', '产业商业', '文旅案例', '竞品项目', '周边房租']"
              :key="`web-source-category-${category}`"
              type="button"
              :class="{ 'is-selected': webSourceDialog.categories.includes(category) }"
              @click="toggleWebSourceCategory(category)">
              {{ category }}
            </button>
          </div>
          <div v-if="webSourceDialog.inputMode === 'search'" class="agent-ppt-research-source-list">
            <span>来源范围</span>
            <button type="button" class="is-selected" disabled>官方/专业来源</button>
            <button
              type="button"
              :class="{ 'is-selected': isWebSourceModeSelected('market') }"
              @click="toggleWebSourceMode('market')">
              包含市场平台
            </button>
            <button
              type="button"
              :class="{ 'is-selected': isWebSourceModeSelected('community') }"
              @click="toggleWebSourceMode('community')">
              包含社媒/问答
            </button>
          </div>
          <div class="agent-ppt-source-dialog-actions">
            <button type="button" @click="closeWebSourceDialog">取消</button>
            <button type="button" :disabled="!canSearchWebSource" @click="submitWebSourceDialog">
              {{ webSourceDialog.loadingDefault ? '准备中' : webSourceDialog.searching ? '处理中' : webSourceDialog.inputMode === 'url' ? '抓取 URL' : '搜索' }}
            </button>
          </div>
        </template>

        <template v-else>
          <div class="agent-ppt-research-preview">
            <div class="agent-ppt-web-source-preview-toolbar">
              <strong>检索到 {{ webSourcePreviewItems.length }} 条资料</strong>
              <span>已选择 {{ selectedWebSourcePreviewItems.length }} 条</span>
              <button type="button" :disabled="!webSourcePreviewItems.length || webSourceDialog.adding" @click="selectAllWebSourcePreviewItems">全选</button>
              <button type="button" :disabled="!selectedWebSourcePreviewItems.length || webSourceDialog.adding" @click="clearWebSourcePreviewSelection">清空</button>
            </div>
            <section class="agent-ppt-research-result-list" aria-label="搜索资料列表">
              <div class="agent-ppt-web-source-preview-grid">
                <div class="agent-ppt-research-result-column">
                  <template v-for="group in webSourcePreviewItemsByCategory" :key="`web-source-group-${group.category}`">
                    <div class="agent-ppt-web-source-category-label">{{ group.category }}</div>
                    <article
                      v-for="row in group.rows"
                      :key="`web-source-preview-${row.item.url || row.item.title || row.index}`"
                      class="agent-ppt-research-result-card"
                      :class="{ 'is-selected': isWebSourceItemSelected(row.item, row.index), 'is-active': isWebSourceItemActive(row.index) }"
                      @click="selectWebSourcePreviewItem(row.index)">
                      <label @click.stop>
                        <input
                          type="checkbox"
                          :checked="isWebSourceItemSelected(row.item, row.index)"
                          :disabled="webSourceDialog.adding"
                          @click.stop
                          @change="toggleWebSourcePreviewItem(row.index)">
                        <span>{{ webSourceItemUrlLabel(row.item, row.index) }}</span>
                      </label>
                      <div class="agent-ppt-research-result-meta">
                        <span>{{ row.item.source_name || row.item.source_domain || '网页来源' }}</span>
                        <span>{{ webSourceTierLabel(row.item) }}</span>
                        <span>{{ row.item.confidence || 'unknown' }}</span>
                        <span :class="`is-${row.item.parse_status || 'unknown'}`">{{ row.item.parse_status === 'parsed' ? '已解析' : '待核验' }}</span>
                      </div>
                    </article>
                  </template>
                  <div v-if="!webSourcePreviewItems.length" class="agent-ppt-package-empty">没有检索到可添加资料。</div>
                </div>
                <aside class="agent-ppt-research-detail-panel" aria-label="搜索资料处理详情">
                  <template v-if="activeWebSourcePreviewItem">
                    <div class="agent-ppt-research-detail-head">
                      <strong>{{ activeWebSourcePreviewItem.title || '网页资料详情' }}</strong>
                      <a v-if="activeWebSourcePreviewItem.url" :href="activeWebSourcePreviewItem.url" target="_blank" rel="noreferrer">打开网页</a>
                    </div>
                    <dl>
                      <div>
                        <dt>来源</dt>
                        <dd>{{ activeWebSourcePreviewItem.source_name || activeWebSourcePreviewItem.source_domain || '网页来源' }}</dd>
                      </div>
                      <div>
                        <dt>来源等级</dt>
                        <dd>{{ webSourceTierLabel(activeWebSourcePreviewItem) }}</dd>
                      </div>
                      <div>
                        <dt>处理状态</dt>
                        <dd>{{ activeWebSourcePreviewItem.parse_status === 'parsed' ? 'Crawl4AI 已解析正文' : `待核验${activeWebSourcePreviewItem.parse_error ? `：${activeWebSourcePreviewItem.parse_error}` : ''}` }}</dd>
                      </div>
                      <div v-if="activeWebSourcePreviewItem.url">
                        <dt>原网页</dt>
                        <dd><a :href="activeWebSourcePreviewItem.url" target="_blank" rel="noreferrer">{{ activeWebSourcePreviewItem.url }}</a></dd>
                      </div>
                    </dl>
                    <div class="agent-ppt-research-detail-section">
                      <strong>摘要</strong>
                      <p>{{ activeWebSourcePreviewItem.summary || '暂无摘要，可打开网页人工核验。' }}</p>
                    </div>
                    <div v-if="Array.isArray(activeWebSourcePreviewItem.supported_claims) && activeWebSourcePreviewItem.supported_claims.length" class="agent-ppt-research-detail-section">
                      <strong>支持论点</strong>
                      <ul>
                        <li v-for="claim in activeWebSourcePreviewItem.supported_claims.slice(0, 3)" :key="`web-source-active-claim-${claim}`">{{ claim }}</li>
                      </ul>
                    </div>
                    <div v-if="Array.isArray(activeWebSourcePreviewItem.web_evidence_nodes) && activeWebSourcePreviewItem.web_evidence_nodes.length" class="agent-ppt-research-detail-section">
                      <strong>关键段落</strong>
                      <ul>
                        <li v-for="node in activeWebSourcePreviewItem.web_evidence_nodes.slice(0, 5)" :key="`web-source-active-node-${node.node_id || node.title || node.summary}`">
                          <span>{{ node.title || '网页证据' }}</span>
                          <p>{{ node.summary || node.text }}</p>
                        </li>
                      </ul>
                    </div>
                    <div v-if="activeWebSourcePreviewItem.parse_status !== 'parsed'" class="agent-ppt-research-detail-warning">
                      网页正文未成功解析，这条资料只作为待核验线索；加入后不会把它当成已确认事实。
                    </div>
                  </template>
                  <div v-else class="agent-ppt-package-empty">选择左侧资料查看处理详情。</div>
                </aside>
              </div>
            </section>
          </div>
          <div class="agent-ppt-source-dialog-actions">
            <button type="button" :disabled="webSourceDialog.adding" @click="backToWebSourceForm">返回修改</button>
            <button type="button" :disabled="webSourceDialog.adding" @click="closeWebSourceDialog">取消</button>
            <button type="button" :disabled="!canCommitWebSource" @click="commitWebSourceDialog">
              {{ webSourceDialog.adding ? '添加中' : `添加已选 ${selectedWebSourcePreviewItems.length} 项` }}
            </button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
