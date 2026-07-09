export const DEFAULT_WEB_SOURCE_CATEGORIES = ['政策背景', '区域概况', '产业商业', '文旅案例', '竞品项目', '周边房租']
export const DEFAULT_WEB_SOURCE_MODES = ['trusted', 'market']

export function createWebSourceDialogState(seed = {}) {
  return {
    open: !!seed.open,
    step: seed.step || 'form',
    inputMode: seed.inputMode === 'url' ? 'url' : 'search',
    loadingDefault: !!seed.loadingDefault,
    searching: !!seed.searching,
    adding: !!seed.adding,
    regionName: seed.regionName || '',
    administrativeArea: seed.administrativeArea || '',
    topic: seed.topic || '',
    urlText: seed.urlText || '',
    categories: Array.isArray(seed.categories) ? seed.categories : [...DEFAULT_WEB_SOURCE_CATEGORIES],
    sourceModes: Array.isArray(seed.sourceModes) ? seed.sourceModes : [...DEFAULT_WEB_SOURCE_MODES],
    preview: seed.preview || null,
    selectedItemKeys: Array.isArray(seed.selectedItemKeys) ? seed.selectedItemKeys : [],
    activeItemIndex: Number(seed.activeItemIndex || 0) || 0,
    error: seed.error || '',
    warnings: Array.isArray(seed.warnings) ? seed.warnings : [],
  }
}

export function openWebSourceDialogForm(current = {}, seed = {}) {
  return createWebSourceDialogState({
    ...current,
    ...seed,
    open: true,
    step: 'form',
    inputMode: seed.inputMode === 'url' ? 'url' : 'search',
    loadingDefault: seed.loadingDefault !== undefined ? !!seed.loadingDefault : true,
    searching: false,
    adding: false,
    urlText: '',
    sourceModes: [...DEFAULT_WEB_SOURCE_MODES],
    preview: null,
    selectedItemKeys: [],
    activeItemIndex: 0,
    error: '',
    warnings: [],
  })
}

export function closeWebSourceDialogForm(current = {}) {
  return createWebSourceDialogState({
    ...current,
    open: false,
    step: 'form',
    inputMode: 'search',
    loadingDefault: false,
    searching: false,
    adding: false,
    urlText: '',
    sourceModes: [...DEFAULT_WEB_SOURCE_MODES],
    preview: null,
    selectedItemKeys: [],
    activeItemIndex: 0,
    error: '',
    warnings: [],
  })
}

export function webSourceItemKey(item = {}, index = 0) {
  return String(item.url || item.title || `web-source-item-${index}`)
}

export function webSourceItemUrlLabel(item = {}, index = 0) {
  return String(item.url || item.source_domain || item.source_name || `网页 ${index + 1}`)
}

export function webSourceTierLabel(item = {}) {
  const tier = String(item.source_tier || item.sourceTier || '').trim()
  if (tier === 'community') return '低可信线索'
  if (tier === 'market') return '市场线索'
  return '可信来源'
}

function toggleTextItem(items = [], value = '', options = {}) {
  const normalized = String(value || '').trim()
  if (!normalized) return Array.isArray(items) ? items : []
  const current = Array.isArray(items) ? items : []
  if (Array.isArray(options.locked) && options.locked.includes(normalized)) return current
  return current.includes(normalized)
    ? current.filter((item) => item !== normalized)
    : [...current, normalized]
}

export function toggleWebSourceCategorySelection(categories = [], category = '') {
  return toggleTextItem(categories, category)
}

export function toggleWebSourceModeSelection(sourceModes = [], mode = '') {
  return toggleTextItem(sourceModes, mode, { locked: ['trusted'] })
}

export function parseWebSourceUrls(value = '') {
  const seen = new Set()
  return String(value || '')
    .split(/[\n,，\s]+/)
    .map((item) => item.trim())
    .filter((item) => /^https?:\/\/[^/\s]+\S*$/i.test(item))
    .filter((item) => {
      if (seen.has(item)) return false
      seen.add(item)
      return true
    })
}

export function selectedWebSourceItems(previewItems = [], selectedItemKeys = []) {
  const selected = new Set(Array.isArray(selectedItemKeys) ? selectedItemKeys : [])
  return (Array.isArray(previewItems) ? previewItems : []).filter((item, index) => selected.has(webSourceItemKey(item, index)))
}

export function buildWebSourcePreviewPayload(dialog = {}, topic = '') {
  const inputMode = dialog.inputMode === 'url' ? 'url' : 'search'
  const urls = inputMode === 'url' ? parseWebSourceUrls(dialog.urlText) : []
  return {
    mode: 'preview',
    region_name: dialog.regionName || '当前分析区域',
    administrative_area: dialog.administrativeArea || '',
    topic: dialog.topic || topic || '',
    categories: Array.isArray(dialog.categories) ? dialog.categories : DEFAULT_WEB_SOURCE_CATEGORIES,
    source_modes: Array.isArray(dialog.sourceModes) && dialog.sourceModes.length ? dialog.sourceModes : DEFAULT_WEB_SOURCE_MODES,
    urls,
  }
}

export function buildWebSourceCommitPreview(preview = {}, selectedItems = []) {
  const safePreview = preview && typeof preview === 'object' ? preview : {}
  const items = Array.isArray(selectedItems) ? selectedItems : []
  const selectedUrls = new Set(items.map((item) => String(item && item.url || '')))
  const selectedTitles = new Set(items.map((item) => String(item && item.title || '')))
  const nextEvidenceRefs = Array.isArray(safePreview.evidence_refs)
    ? safePreview.evidence_refs.filter((url) => selectedUrls.has(String(url || '')))
    : []
  return {
    ...safePreview,
    items,
    evidence_refs: nextEvidenceRefs,
    summary: `已选择 ${items.length} 条地区资料。`,
    warnings: Array.isArray(safePreview.warnings) ? safePreview.warnings : [],
    source: {
      ...(safePreview.source || {}),
      meta: {
        ...((safePreview.source && safePreview.source.meta) || {}),
        web_source: {
          ...(((safePreview.source && safePreview.source.meta && safePreview.source.meta.web_source) || {})),
          selected_item_count: items.length,
          selected_urls: Array.from(selectedUrls).filter(Boolean),
          selected_titles: Array.from(selectedTitles).filter(Boolean),
        },
      },
    },
  }
}
