import test from 'node:test'
import assert from 'node:assert/strict'

import {
  createAggregateSourceRefreshPlaceholder,
  isPptSourceRefreshPlaceholder,
  isRefreshableBackendPptSource,
  sourceRefreshPlaceholderFromSource,
} from '../src/features/ppt-planning/source-refresh.js'

test('ppt source refresh helpers classify refreshable backend sources', () => {
  assert.equal(isRefreshableBackendPptSource({ id: 'current:scope', meta: { sourceKind: 'system' } }), false)
  assert.equal(isRefreshableBackendPptSource({ id: 'package-placeholder:road', meta: { sourceKind: 'package-placeholder' } }), false)
  assert.equal(isRefreshableBackendPptSource({ id: 'source-refresh-placeholder:document:1', meta: { sourceKind: 'source-refresh-placeholder' } }), false)
  assert.equal(isRefreshableBackendPptSource({ id: 'document:1', meta: { sourceKind: 'document' } }), true)
  assert.equal(isRefreshableBackendPptSource({ id: 'web:1', source_kind: 'web' }), true)
  assert.equal(isRefreshableBackendPptSource({ id: 'database:pois', sourceKind: 'database' }), true)
})

test('ppt source refresh helpers create stable placeholder sources', () => {
  const placeholder = sourceRefreshPlaceholderFromSource({
    id: 'document:1',
    title: '招商文档',
    status: 'ready',
    selected: true,
    meta: { sourceKind: 'document', custom: 'kept' },
  })

  assert.equal(isPptSourceRefreshPlaceholder(placeholder), true)
  assert.equal(placeholder.id, 'source-refresh-placeholder:document:1')
  assert.equal(placeholder.title, '招商文档')
  assert.equal(placeholder.status, 'generating')
  assert.equal(placeholder.selected, false)
  assert.equal(placeholder.meta.sourceKind, 'source-refresh-placeholder')
  assert.equal(placeholder.meta.sourceRefreshingPlaceholder, true)
  assert.equal(placeholder.meta.expectedSourceId, 'document:1')
  assert.equal(placeholder.meta.expectedSourceKind, 'document')
  assert.equal(placeholder.meta.custom, 'kept')
})

test('ppt source refresh helpers create aggregate placeholder fallback', () => {
  const placeholder = createAggregateSourceRefreshPlaceholder()
  assert.equal(isPptSourceRefreshPlaceholder(placeholder), true)
  assert.equal(placeholder.id, 'source-refresh-placeholder:backend-sources')
  assert.equal(placeholder.title, '后端来源')
  assert.equal(placeholder.status, 'generating')
  assert.equal(placeholder.selected, false)
  assert.equal(placeholder.meta.expectedSourceKind, 'backend')
})
