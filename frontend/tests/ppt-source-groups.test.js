import test from 'node:test'
import assert from 'node:assert/strict'

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
  stableGroupId,
  syncSpecSourceIds,
} from '../src/features/ppt-planning/source-groups.js'

test('ppt source groups derive stable ids and normalize group payloads', () => {
  assert.equal(stableGroupId('城市活力证据'), PPT_UNCATEGORIZED_GROUP_ID)
  assert.equal(stableGroupId('Web Sources'), 'group:web-sources')
  assert.equal(stableGroupId('', 'group:fallback'), 'group:fallback')
  assert.equal(simpleHash('same-input'), simpleHash('same-input'))

  assert.deepEqual(normalizePptSourceGroup({
    title: 'Web Sources',
    source_ids: ['web:1', 'web:1', '', 'document:1'],
    collapsed: 1,
    meta: { source: 'ai' },
  }), {
    id: 'group:web-sources',
    title: 'Web Sources',
    emoji: '',
    sourceIds: ['web:1', 'document:1'],
    collapsed: true,
    meta: { source: 'ai' },
  })
})

test('ppt source groups create default groups from source semantics', () => {
  const sources = normalizeSources([
    { id: 'current:scope', title: '范围', status: 'ready', selected: true },
    { id: 'current:dataset:poi', title: 'POI', status: 'ready', selected: true },
    { id: 'current:analysis:road', title: '路网', status: 'pending', selected: true },
    { id: 'document:doc-1', title: '文档', source_kind: 'document', status: 'ready', selected: false },
    { id: 'web:news', title: '网页', source_kind: 'web', status: 'ready', selected: true },
  ])

  const groups = createDefaultPptSourceGroups(sources)
  assert.deepEqual(sourceIdsFromSources(sources), [
    'current:scope',
    'current:dataset:poi',
    'current:analysis:road',
    'document:doc-1',
    'web:news',
  ])
  assert.ok(groups.find((group) => group.id === 'group:spatial-scope').sourceIds.includes('current:scope'))
  assert.ok(groups.find((group) => group.id === 'group:urban-vitality').sourceIds.includes('current:dataset:poi'))
  assert.ok(groups.find((group) => group.id === 'group:accessibility').sourceIds.includes('current:analysis:road'))
  assert.ok(groups.find((group) => group.id === 'group:document-evidence').sourceIds.includes('document:doc-1'))
  assert.ok(groups.find((group) => group.id === 'group:web').sourceIds.includes('web:news'))
  assert.deepEqual(getReadySelectedSourceIds(sources), ['current:scope', 'current:dataset:poi', 'web:news'])
  assert.deepEqual(syncSpecSourceIds({ spec: { topic: '商业分析' } }, sources), {
    topic: '商业分析',
    sourceIds: ['current:scope', 'current:dataset:poi', 'web:news'],
  })
})

test('ppt source group reconciliation removes stale ids and respects ungrouped ids', () => {
  const sources = normalizeSources([
    { id: 'current:scope', status: 'ready', selected: true },
    { id: 'current:dataset:poi', status: 'ready', selected: true },
    { id: 'document:doc-1', source_kind: 'document', status: 'ready', selected: true },
  ])

  const reconciled = reconcilePptSourceGroups([
    { id: 'group:custom', title: '自定义', sourceIds: ['current:scope', 'missing:id', 'current:dataset:poi'] },
    { id: PPT_UNCATEGORIZED_GROUP_ID, title: '未分类', sourceIds: ['document:doc-1'] },
  ], sources, ['current:dataset:poi'])

  assert.deepEqual(reconciled.find((group) => group.id === 'group:custom').sourceIds, ['current:scope'])
  assert.equal(reconciled.some((group) => group.id === PPT_UNCATEGORIZED_GROUP_ID), false)
  assert.equal(reconciled.some((group) => group.sourceIds.includes('current:dataset:poi')), false)
  assert.ok(reconciled.find((group) => group.id === 'group:document-evidence').sourceIds.includes('document:doc-1'))
})

test('ppt source groups add moved ids to concrete groups only', () => {
  const groups = [{ id: 'group:web', title: '联网资料', sourceIds: ['web:1'], collapsed: true }]

  assert.deepEqual(ensureGroupForSourceIds(groups, PPT_UNCATEGORIZED_GROUP_ID, ['web:2']), groups)

  const appended = ensureGroupForSourceIds(groups, 'group:web', ['web:2', 'web:2'])
  assert.deepEqual(appended[0].sourceIds, ['web:1', 'web:2'])
  assert.equal(appended[0].collapsed, false)

  const created = ensureGroupForSourceIds(groups, 'group:manual', ['document:1'])
  assert.deepEqual(created.find((group) => group.id === 'group:manual'), {
    id: 'group:manual',
    title: '未分类来源',
    emoji: '',
    sourceIds: ['document:1'],
    collapsed: false,
    meta: { source: 'manual' },
  })
})
