import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildWebSourceCommitPreview,
  buildWebSourcePreviewPayload,
  closeWebSourceDialogForm,
  createWebSourceDialogState,
  DEFAULT_WEB_SOURCE_CATEGORIES,
  DEFAULT_WEB_SOURCE_MODES,
  openWebSourceDialogForm,
  parseWebSourceUrls,
  selectedWebSourceItems,
  toggleWebSourceCategorySelection,
  toggleWebSourceModeSelection,
  webSourceItemKey,
  webSourceItemUrlLabel,
  webSourceTierLabel,
} from '../src/features/ppt-planning/web-source-dialog.js'

test('web source dialog creates stable default state and parses urls', () => {
  const state = createWebSourceDialogState({ inputMode: 'url', topic: '商圈', selectedItemKeys: ['a'] })
  assert.equal(state.inputMode, 'url')
  assert.equal(state.topic, '商圈')
  assert.deepEqual(state.categories, DEFAULT_WEB_SOURCE_CATEGORIES)
  assert.deepEqual(state.sourceModes, DEFAULT_WEB_SOURCE_MODES)
  assert.deepEqual(state.selectedItemKeys, ['a'])

  assert.deepEqual(parseWebSourceUrls('https://a.com\nbad ftp://x https://a.com，http://b.cn/path?q=1'), [
    'https://a.com',
    'http://b.cn/path?q=1',
  ])
})

test('web source dialog owns open and close reset policy', () => {
  const current = createWebSourceDialogState({
    inputMode: 'url',
    topic: '旧主题',
    urlText: 'https://old.example',
    sourceModes: ['trusted'],
    selectedItemKeys: ['old'],
    preview: { items: [{ title: 'old' }] },
    error: 'old error',
    warnings: ['old warning'],
  })

  const opened = openWebSourceDialogForm(current, { inputMode: 'url', topic: '新主题' })
  assert.equal(opened.open, true)
  assert.equal(opened.inputMode, 'url')
  assert.equal(opened.loadingDefault, true)
  assert.equal(opened.topic, '新主题')
  assert.equal(opened.urlText, '')
  assert.deepEqual(opened.sourceModes, DEFAULT_WEB_SOURCE_MODES)
  assert.deepEqual(opened.selectedItemKeys, [])
  assert.equal(opened.preview, null)
  assert.equal(opened.error, '')
  assert.deepEqual(opened.warnings, [])

  const closed = closeWebSourceDialogForm(opened)
  assert.equal(closed.open, false)
  assert.equal(closed.inputMode, 'search')
  assert.equal(closed.loadingDefault, false)
  assert.equal(closed.urlText, '')
  assert.deepEqual(closed.sourceModes, DEFAULT_WEB_SOURCE_MODES)
  assert.deepEqual(closed.selectedItemKeys, [])
  assert.equal(closed.preview, null)
})

test('web source dialog derives item labels and selection', () => {
  const items = [
    { url: 'https://a.com', title: 'A', source_tier: 'market' },
    { title: 'B', sourceTier: 'community', source_domain: 'b.com' },
    { source_name: 'C' },
  ]

  assert.equal(webSourceItemKey(items[0], 0), 'https://a.com')
  assert.equal(webSourceItemKey(items[1], 1), 'B')
  assert.equal(webSourceItemUrlLabel(items[1], 1), 'b.com')
  assert.equal(webSourceItemUrlLabel(items[2], 2), 'C')
  assert.equal(webSourceTierLabel(items[0]), '市场线索')
  assert.equal(webSourceTierLabel(items[1]), '低可信线索')
  assert.equal(webSourceTierLabel({}), '可信来源')
  assert.deepEqual(selectedWebSourceItems(items, ['https://a.com', 'B']), [items[0], items[1]])
})

test('web source dialog toggles category and mode selections', () => {
  assert.deepEqual(toggleWebSourceCategorySelection(['政策背景'], '产业商业'), ['政策背景', '产业商业'])
  assert.deepEqual(toggleWebSourceCategorySelection(['政策背景', '产业商业'], '产业商业'), ['政策背景'])
  assert.deepEqual(toggleWebSourceCategorySelection(['政策背景'], ''), ['政策背景'])
  assert.deepEqual(toggleWebSourceModeSelection(['trusted', 'market'], 'trusted'), ['trusted', 'market'])
  assert.deepEqual(toggleWebSourceModeSelection(['trusted', 'market'], 'community'), ['trusted', 'market', 'community'])
})

test('web source dialog builds preview and commit payloads', () => {
  const previewPayload = buildWebSourcePreviewPayload({
    inputMode: 'url',
    regionName: '',
    administrativeArea: '杭州',
    topic: '',
    categories: ['产业商业'],
    sourceModes: [],
    urlText: 'https://a.com https://a.com https://b.com',
  }, '默认主题')

  assert.deepEqual(previewPayload, {
    mode: 'preview',
    region_name: '当前分析区域',
    administrative_area: '杭州',
    topic: '默认主题',
    categories: ['产业商业'],
    source_modes: DEFAULT_WEB_SOURCE_MODES,
    urls: ['https://a.com', 'https://b.com'],
  })

  const commitPreview = buildWebSourceCommitPreview({
    evidence_refs: ['https://a.com', 'https://c.com'],
    warnings: ['w1'],
    source: { id: 'web:area', meta: { web_source: { query: 'old' } } },
  }, [
    { url: 'https://a.com', title: 'A' },
    { url: '', title: 'B' },
  ])

  assert.deepEqual(commitPreview.evidence_refs, ['https://a.com'])
  assert.equal(commitPreview.summary, '已选择 2 条地区资料。')
  assert.equal(commitPreview.source.meta.web_source.selected_item_count, 2)
  assert.deepEqual(commitPreview.source.meta.web_source.selected_urls, ['https://a.com'])
  assert.deepEqual(commitPreview.source.meta.web_source.selected_titles, ['A', 'B'])
  assert.equal(commitPreview.source.meta.web_source.query, 'old')
})
