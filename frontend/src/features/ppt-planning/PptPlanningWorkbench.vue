<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

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
  dataPackageGenerating: {
    type: Boolean,
    default: false,
  },
  sourceGrouping: {
    type: Boolean,
    default: false,
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
])

const isSourcesCollapsed = ref(false)
const sourceMenu = ref({ kind: '', id: '', placement: 'below', x: 0, y: 0 })
const sourceDialog = ref({ mode: '', id: '', title: '', value: '', message: '' })
const activePackageSourceId = ref('')
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
const canGenerateOutline = computed(() => (props.sourceSummary.selected || 0) > 0 && !isOutlineGenerating.value && !isDirectiveGenerating.value)
const canGenerateDirective = computed(() => hasOutline.value && !isOutlineGenerating.value && !isDirectiveGenerating.value)
const canCreateDataPackage = computed(() => (props.sourceSummary.selected || 0) > 0 && !props.dataPackageGenerating)
const activePackageSource = computed(() => sourceById.value.get(String(activePackageSourceId.value || '')) || null)
const activePackagePayload = computed(() => {
  const payload = ((activePackageSource.value || {}).meta || {}).package
  return payload && typeof payload === 'object' ? payload : {}
})
const activePackageItems = computed(() => {
  const items = activePackagePayload.value.items
  return Array.isArray(items) ? items.slice(0, 100) : []
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
  return [
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
const outlineRows = computed(() => {
  if (hasDirective.value && props.slides.length) {
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
  return source.type === 'package' || meta.sourceKind === 'package' || String(source.id || '').startsWith('package:')
}

function openPackageDetail(source = {}) {
  if (!source.id || !isPackageSource(source)) return
  activePackageSourceId.value = source.id
  closeSourceMenu()
}

function closePackageDetail() {
  activePackageSourceId.value = ''
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
                  :class="[{ 'is-ready': source.status === 'ready', 'is-pending': source.status !== 'ready', 'is-selected': source.selected }, `is-${source.type || 'file'}`]">
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
                  <span v-else class="agent-ppt-source-loading" aria-label="未就绪"></span>
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
          <span :class="{ 'is-current': activeFlowIndex === 0 }">配置</span>
          <span :class="{ 'is-current': activeFlowIndex === 1 }">生成目录</span>
          <span :class="{ 'is-current': activeFlowIndex === 2 }">生成指令</span>
          <span :class="{ 'is-current': activeFlowIndex === 3 }">选择风格</span>
          <span :class="{ 'is-current': activeFlowIndex === 4 }">生成页面</span>
          <span :class="{ 'is-current': activeFlowIndex === 5 }">导出</span>
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
        <div v-if="!outlineRows.length" class="agent-ppt-target-config-panel">
          <div class="agent-ppt-target-config-head">
            <strong>配置生成目标</strong>
            <span v-if="generationError">AI 生成暂不可用，请检查模型配置后重试。</span>
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
              <dl v-if="row.fields.length" class="agent-ppt-directive-fields">
                <div
                  v-for="field in row.fields"
                  :key="`ppt-directive-field-${row.id}-${field[0]}`">
                  <dt>{{ field[0] }}</dt>
                  <dd>{{ field[1] }}</dd>
                </div>
              </dl>
            </div>
          </div>
        </div>
        <div class="agent-ppt-prompt-box">
          <span v-if="generationError">{{ generationError }}</span>
          <span v-else-if="!hasOutline">先生成目录，再生成逐页指令文件</span>
          <span v-else-if="!hasDirective">目录已生成，下一步生成逐页指令</span>
          <span v-else>指令草稿已生成，可进入审核</span>
          <button
            v-if="!hasOutline"
            type="button"
            :disabled="!canGenerateOutline"
            @click="$emit('generate-outline')">
            {{ isOutlineGenerating ? '目录生成中' : '生成目录' }}
          </button>
          <button
            v-else
            type="button"
            :disabled="!canGenerateDirective || hasDirective"
            @click="$emit('generate-directive')">
            {{ isDirectiveGenerating ? '指令生成中' : hasDirective ? '指令草稿已生成' : '生成指令文件' }}
          </button>
        </div>
      </section>
    </div>

    <div v-if="activePackageSource" class="agent-ppt-package-detail-backdrop" @click.self="closePackageDetail">
      <section class="agent-ppt-package-detail" role="dialog" aria-modal="true" aria-label="资料包内容">
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
