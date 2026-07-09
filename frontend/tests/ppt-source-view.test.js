import test from 'node:test'
import assert from 'node:assert/strict'

import {
  isCurrentSource,
  isDeletableSource,
  isDocumentSource,
  isPackagePlaceholderSource,
  isPackageSource,
  removeSourceMessage,
  sourceTransport,
  sourceTransportExcludedItems,
  sourceTransportLabel,
} from '../src/features/ppt-planning/source-view.js'

test('ppt source view helpers classify source ownership and actions', () => {
  assert.equal(isCurrentSource({ id: 'current:scope', meta: { sourceKind: 'system' } }), true)
  assert.equal(isDocumentSource({ id: 'document:doc-1', meta: { sourceKind: 'document' } }), true)
  assert.equal(isPackageSource({ id: 'package:poi:auto', meta: { sourceKind: 'package' } }), true)
  assert.equal(isPackagePlaceholderSource({ id: 'package-placeholder:road', meta: { sourceKind: 'package-placeholder' } }), true)
  assert.equal(isDeletableSource({ id: 'current:scope', meta: { sourceKind: 'system' } }), false)
  assert.equal(isDeletableSource({ id: 'database:parcel', meta: { sourceKind: 'database' } }), true)
  assert.match(removeSourceMessage({ id: 'document:doc-1', meta: { sourceKind: 'document' } }), /文档库/)
})


test('ppt source view helpers prefer canonical source_kind over meta alias', () => {
  assert.equal(isPackageSource({ id: 'external:package-1', source_kind: 'package', meta: { sourceKind: 'system' } }), true)
  assert.equal(isDocumentSource({ id: 'external:doc-1', source_kind: 'document', meta: { sourceKind: 'system' } }), true)
  assert.equal(isCurrentSource({ id: 'current:scope', source_kind: 'system', meta: { sourceKind: 'package' } }), true)
  assert.equal(isDeletableSource({ id: 'external:package-1', source_kind: 'package', meta: { sourceKind: 'system' } }), true)
})
test('ppt source view helpers derive transport from ai payload', () => {
  const source = {
    id: 'current:analysis',
    title: '当前分析',
    meta: {
      sourceKind: 'system',
      aiPayload: {
        version: 'ppt_ai_input_block_v1',
        source_id: 'current:analysis',
        title: '当前分析',
        source_kind: 'system',
        included: ['scope', 'metrics', 'evidence', 'visual_specs'],
        counts: { scope: 1, metrics: 2, visual_specs: 1 },
        excluded: ['raw_rows'],
        evidence_nodes: [{
          id: 'current:analysis:e1',
          source_id: 'current:analysis',
          source_type: 'system',
          title: '证据',
          content: '范围内 POI 完整。',
        }],
      },
    },
  }

  const transport = sourceTransport(source)
  assert.equal(transport.transport_status, 'ready_to_send')
  assert.equal(transport.evidence_count, 1)
  assert.equal(sourceTransportLabel(source), '已构建 范围 1 / metrics 2 / evidence 1 / visuals 1')
  assert.deepEqual(sourceTransportExcludedItems(source), ['raw_rows'])
})

test('ppt source transport fallback uses canonical source kind', () => {
  const transport = sourceTransport({
    id: 'external:web-source',
    title: '联网资料',
    source_kind: 'web',
    meta: {
      sourceKind: 'database',
      aiPayload: {
        version: 'ppt_ai_input_block_v1',
        source_id: 'external:web-source',
        title: '联网资料',
        included: ['evidence'],
        counts: { evidence: 0 },
      },
    },
  })

  assert.equal(transport.source_kind, 'web')
  assert.equal(transport.sourceKind, 'web')
})
