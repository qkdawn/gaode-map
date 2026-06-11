<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { buildPptCarrierPreviewModel } from './carrier-preview.js'
import { getPendingPptPackageSources } from './ui-state.js'

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
  'rename-source-group',
  'set-source-group-emoji',
  'remove-source-group',
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
const activePackageSourceId = ref('')
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
const isOutlineGenerating = computed(() => props.currentStep === 'outline_generating')
const isDirectiveGenerating = computed(() => props.currentStep === 'directive_generating')
const hasOutline = computed(() => props.outline.length > 0)
const hasDirective = computed(() => props.currentStep === 'directive_draft')
const pendingPackageSources = computed(() => getPendingPptPackageSources({ sources: props.sources }))
const hasPendingPackageSources = computed(() => pendingPackageSources.value.length > 0)
const outlineBlockReason = computed(() => {
  if (!(props.sourceSummary.selected || 0)) return '请先选择至少一个已生成来源'
  if (hasPendingPackageSources.value) {
    const generating = pendingPackageSources.value.some((source) => String(source.status || '') === 'generating')
    return generating ? '资料包仍在整理中，完成后再生成目录' : '资料包尚未生成完成，完成后再生成目录'
  }
  return ''
})
const canGenerateOutline = computed(() => !outlineBlockReason.value && !isOutlineGenerating.value && !isDirectiveGenerating.value)
const canGenerateDirective = computed(() => hasOutline.value && !isOutlineGenerating.value && !isDirectiveGenerating.value)
const canCreateDataPackage = computed(() => (props.sourceSummary.selected || 0) > 0 && !props.dataPackageGenerating)
const generationErrorText = computed(() => String(props.generationError || '').trim())
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
const activePackagePayload = computed(() => {
  const payload = ((activePackageSource.value || {}).meta || {}).package
  return payload && typeof payload === 'object' ? payload : {}
})
const activePackageItems = computed(() => {
  const items = activePackagePayload.value.items
  return Array.isArray(items) ? items.slice(0, 100) : []
})
const activePackageCarriers = computed(() => {
  const carriers = activePackagePayload.value.carriers
  return Array.isArray(carriers) ? carriers.slice(0, 30) : []
})
const activePackageRoadContext = computed(() => {
  const context = activePackagePayload.value.road_context || activePackagePayload.value.roadContext
  return context && typeof context === 'object' ? context : {}
})
const activePackageCarrierPreview = computed(() => buildPptCarrierPreviewModel(activePackageCarriers.value, {
  roadContext: activePackageRoadContext.value,
  focusId: activePackageCarrierId.value || String((activePackageCarriers.value[0] || {}).carrier_id || ''),
  extentMode: activePackageCarrierPreviewMode.value,
}))
const activePackagePreviewCarriers = computed(() => activePackageCarrierPreview.value.items || [])
const activePackagePreviewRoads = computed(() => activePackageCarrierPreview.value.roadItems || [])
const activePackageSelectedCarrier = computed(() => {
  const activeId = String(activePackageCarrierId.value || '')
  return activePackageCarriers.value.find((carrier) => String(carrier.carrier_id || '') === activeId) || activePackageCarriers.value[0] || null
})
const activePackageCarrierSummary = computed(() => {
  const summary = activePackagePayload.value.carrier_summary || activePackagePayload.value.carrierSummary
  return summary && typeof summary === 'object' ? summary : {}
})
const activePackageEvidenceRefs = computed(() => {
  const refs = activePackagePayload.value.evidence_refs || activePackagePayload.value.evidenceRefs
  return Array.isArray(refs) ? refs.slice(0, 80) : []
})
const activePackageWarnings = computed(() => {
  const warnings = activePackagePayload.value.warnings
  return Array.isArray(warnings) ? warnings.filter(Boolean) : []
})
const activePackageAlignment = computed(() => {
  const alignment = activePackagePayload.value.alignment
  return alignment && typeof alignment === 'object' ? alignment : {}
})
const activePackageStats = computed(() => {
  const payload = activePackagePayload.value
  const alignment = activePackageAlignment.value
  const carrierSummary = activePackageCarrierSummary.value
  const carrierRows = activePackageCarriers.value.length ? [
    ['空间载体', carrierSummary.carrier_count ?? activePackageCarriers.value.length],
    ['路段', carrierSummary.segment_count],
    ['廊道', carrierSummary.corridor_count],
    ['街区 / loop', carrierSummary.block_loop_count],
  ] : []
  return [
    ...carrierRows,
    ['总候选', payload.total],
    ['入包点位', activePackageItems.value.length],
    ['已对齐', alignment.matched_item_count],
    ['共享格子', alignment.grid_cell_count],
    ['夜光格子', alignment.nightlight_cell_count],
  ].filter((row) => row[1] !== undefined && row[1] !== null && row[1] !== '')
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
  return (props.sourceGroups.find((group) => String(group.id || '') === String(groupId || '')) || {}).title || '未分类来源'
}

function isPackageSource(source = {}) {
  const meta = source.meta && typeof source.meta === 'object' ? source.meta : {}
  return meta.sourceKind === 'package' || String(source.id || '').startsWith('package:')
}

function isGeneratingSource(source = {}) {
  return String(source.status || '') === 'generating'
}

function openPackageDetail(source = {}) {
  if (!source.id || !isPackageSource(source)) return
  activePackageSourceId.value = source.id
  closeSourceMenu()
}

function closePackageDetail() {
  activePackageSourceId.value = ''
  activePackageCarrierId.value = ''
  activePackageCarrierPreviewMode.value = 'local'
}

function handleSourceRowClick(source = {}) {
  if (isPackageSource(source)) {
    openPackageDetail(source)
    return
  }
  if (source.status === 'ready') emit('toggle-source', source.id)
}

function formatPackageMetric(value) {
  if (value === undefined || value === null || value === '') return '-'
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(3).replace(/\.?0+$/, '')
  return String(value)
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
  activePackageCarriers,
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
    title: '移除来源',
    value: '',
    message: `确认从本次 PPT 来源池移除“${source.title || '未命名来源'}”？底层分析数据不会被删除。`,
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
    message: `确认移除“${group.title || '未分类来源'}”分类？组内来源会保留并移动到未分类来源。`,
  }
  closeSourceMenu()
}

function moveSourceToGroup(sourceId = '', groupId = '') {
  emit('move-source-to-group', sourceId, groupId)
  closeSourceMenu()
}

function closeSourceDialog() {
  sourceDialog.value = { mode: '', id: '', title: '', value: '', message: '' }
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
          <button type="button" class="agent-ppt-add-source-btn" disabled>+ 添加来源</button>
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
                    :class="{ 'is-inspectable': isPackageSource(source) }"
                    :aria-pressed="source.status === 'ready' && !isPackageSource(source) ? String(!!source.selected) : undefined"
                    :disabled="source.status !== 'ready' && !isPackageSource(source)"
                    @click="handleSourceRowClick(source)">
                    <span class="agent-ppt-source-icon" :class="`is-${source.type || 'file'}`"></span>
                    <span class="agent-ppt-source-name">
                      <strong>{{ source.title }}</strong>
                      <small>{{ (source.meta && source.meta.label) || (source.status === 'ready' ? '已生成' : '待生成') }}</small>
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
                    <button v-if="isPackageSource(source)" type="button" @click="openPackageDetail(source)">查看内容</button>
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
                    <button type="button" @click="openRemoveSource(source)">移除来源</button>
                    <button type="button" @click="openRenameSource(source)">重命名来源</button>
                  </div>
                </div>
              </div>
            </div>
            <div v-if="!sourceGroupsForTree.length" class="agent-ppt-source-empty">暂无可用来源。</div>
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
              {{ isOutlineGenerating ? '目录生成中' : '生成目录' }}
            </button>
            <template v-else-if="!hasDirective">
              <button
                type="button"
                class="is-primary"
                :disabled="!canGenerateDirective"
                @click="$emit('generate-directive')">
                {{ isDirectiveGenerating ? '指令生成中' : '生成指令文件' }}
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

    <div v-if="activePackageSource" class="agent-ppt-package-detail-backdrop" @click.self="closePackageDetail">
      <section
        class="agent-ppt-package-detail"
        :class="{ 'has-carrier-preview': activePackagePreviewCarriers.length }"
        role="dialog"
        aria-modal="true"
        aria-label="资料包内容">
        <header class="agent-ppt-package-detail-head">
          <div>
            <span>资料包</span>
            <strong>{{ activePackagePayload.title || activePackageSource.title }}</strong>
            <small>{{ (activePackageSource.meta && activePackageSource.meta.label) || activePackagePayload.summary || '已生成' }}</small>
          </div>
          <button type="button" aria-label="关闭" title="关闭" @click="closePackageDetail">×</button>
        </header>

        <p v-if="activePackagePayload.summary" class="agent-ppt-package-summary">{{ activePackagePayload.summary }}</p>

        <div v-if="activePackageStats.length" class="agent-ppt-package-stats">
          <div v-for="stat in activePackageStats" :key="`package-stat-${stat[0]}`">
            <span>{{ stat[0] }}</span>
            <strong>{{ formatPackageMetric(stat[1]) }}</strong>
          </div>
        </div>

        <dl class="agent-ppt-package-meta">
          <div v-if="activePackagePayload.intent">
            <dt>意图</dt>
            <dd>{{ activePackagePayload.intent }}</dd>
          </div>
          <div v-if="activePackageAlignment.alignment_level">
            <dt>对齐等级</dt>
            <dd>{{ activePackageAlignment.alignment_level }}</dd>
          </div>
          <div v-if="activePackageAlignment.join_key">
            <dt>连接键</dt>
            <dd>{{ activePackageAlignment.join_key }}</dd>
          </div>
          <div v-if="Array.isArray(activePackagePayload.source_ids) && activePackagePayload.source_ids.length">
            <dt>来源</dt>
            <dd>{{ activePackagePayload.source_ids.join(' / ') }}</dd>
          </div>
        </dl>

        <div v-if="activePackageWarnings.length" class="agent-ppt-package-warnings">
          <strong>提示</strong>
          <span v-for="warning in activePackageWarnings" :key="`package-warning-${warning}`">{{ warning }}</span>
        </div>

        <div v-if="activePackageCarriers.length" class="agent-ppt-package-section-head">
          <strong>空间载体</strong>
          <span>{{ activePackageCarriers.length }} 个</span>
        </div>
        <div v-if="activePackageCarriers.length" class="agent-ppt-carrier-workspace">
          <div v-if="activePackagePreviewCarriers.length" class="agent-ppt-carrier-preview">
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
              :viewBox="activePackageCarrierPreview.viewBox"
              role="img"
              aria-label="空间载体预览">
              <rect class="agent-ppt-carrier-preview-bg" x="0" y="0" width="1000" height="620" rx="18" />
              <g v-if="activePackagePreviewRoads.length" class="agent-ppt-carrier-preview-roads" aria-hidden="true">
                <path
                  v-for="road in activePackagePreviewRoads"
                  :key="`carrier-preview-road-${road.id}`"
                  class="agent-ppt-carrier-preview-road"
                  :class="road.className"
                  :d="road.path" />
              </g>
              <g
                v-for="item in activePackagePreviewCarriers"
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
                  v-if="item.isFocus || activePackagePreviewCarriers.length === 1"
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
              v-for="carrier in activePackageCarriers"
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
          <span>{{ activePackageItems.length }} 条</span>
        </div>
        <div v-if="activePackageItems.length" class="agent-ppt-package-table" role="table" aria-label="资料包点位明细">
          <div class="agent-ppt-package-table-head" role="row">
            <span role="columnheader">POI</span>
            <span role="columnheader">分类</span>
            <span role="columnheader">格子</span>
            <span role="columnheader">夜光</span>
          </div>
          <div
            v-for="(item, index) in activePackageItems"
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

        <div v-if="activePackageEvidenceRefs.length" class="agent-ppt-package-section-head">
          <strong>Evidence refs</strong>
          <span>{{ activePackageEvidenceRefs.length }} 条</span>
        </div>
        <div v-if="activePackageEvidenceRefs.length" class="agent-ppt-package-ref-list">
          <span v-for="refItem in activePackageEvidenceRefs" :key="`package-ref-${refItem}`">{{ refItem }}</span>
        </div>
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
