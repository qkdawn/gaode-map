import test from 'node:test'
import assert from 'node:assert/strict'

import {
  ANALYSIS_SOURCES_TARGET_TYPE,
  buildAnalysisSourceTarget,
} from '../src/features/analysis-sources/target.js'

test('analysis source target keeps only selected ready deliverable sources', () => {
  const target = buildAnalysisSourceTarget({
    sources: [
      {
        id: 'document:ready',
        type: 'document',
        title: '规划文档',
        status: 'ready',
        selected: true,
        meta: {
          sourceKind: 'document',
          aiPayload: {
            source_id: 'document:ready',
            title: '规划文档',
            source_kind: 'document',
            included: ['metrics', 'evidence'],
            metrics: [{ metric_id: 'm1', label: '指标', value: 12 }],
            evidence_nodes: [{
              id: 'document:ready:e1',
              source_id: 'document:ready',
              source_type: 'document',
              title: '核心证据',
              content: '区域客流稳定。',
            }],
            counts: { metrics: 1 },
          },
        },
      },
      {
        id: 'document:unselected',
        status: 'ready',
        selected: false,
        meta: {
          aiPayload: {
            source_id: 'document:unselected',
            included: ['evidence'],
            evidence_nodes: [{ title: '不应发送', content: '未选中。' }],
          },
        },
      },
      {
        id: 'document:pending',
        status: 'pending',
        selected: true,
        meta: {
          aiPayload: {
            source_id: 'document:pending',
            included: ['evidence'],
            evidence_nodes: [{ title: '不应发送', content: '未完成。' }],
          },
        },
      },
      {
        id: 'document:empty',
        status: 'ready',
        selected: true,
        meta: {
          aiPayload: {
            source_id: 'document:empty',
            included: [],
          },
        },
      },
    ],
  })

  assert.equal(target.type, ANALYSIS_SOURCES_TARGET_TYPE)
  assert.deepEqual(target.payload.sources.map((source) => source.source_id), ['document:ready'])
  assert.equal(target.evidence[0].text, '1 个指标；1 条证据')
  assert.equal(target.payload.sources[0].evidence_nodes[0].id, 'document:ready:e1')
  assert.equal(target.payload.sources[0].evidence_nodes[0].source_type, 'document')
  assert.equal(target.payload.sources[0].evidence_nodes[0].evidence_level, 'source_evidence')
  assert.equal(Object.prototype.hasOwnProperty.call(target.payload.sources[0], 'evidence'), false)
  assert.equal(Object.prototype.hasOwnProperty.call(target.payload.sources[0], 'sourceId'), false)
  assert.equal(Object.prototype.hasOwnProperty.call(target.payload.sources[0], 'sourceKind'), false)
  assert.equal(Object.prototype.hasOwnProperty.call(target.payload.sources[0], 'evidenceNodes'), false)
  assert.equal(Object.prototype.hasOwnProperty.call(target.payload.sources[0].evidence_nodes[0], 'sourceId'), false)
  assert.equal(Object.prototype.hasOwnProperty.call(target.payload.sources[0].evidence_nodes[0], 'sourceType'), false)
  assert.equal(Object.prototype.hasOwnProperty.call(target.payload.sources[0].evidence_nodes[0], 'evidenceLevel'), false)
  assert.equal(Object.prototype.hasOwnProperty.call(target.evidence[0], 'sourceId'), false)
  assert.equal(Object.prototype.hasOwnProperty.call(target.evidence[0], 'sourceTitle'), false)
})
