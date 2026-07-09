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
  assert.deepEqual(target.artifact_refs, ['document:ready'])
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
  assert.equal(Object.prototype.hasOwnProperty.call(target, 'artifactRefs'), false)
})

test('analysis source target ignores legacy ai payload aliases', () => {
  const target = buildAnalysisSourceTarget({
    sources: [{
      id: 'document:legacy-aliases',
      type: 'document',
      title: '旧字段文档',
      status: 'ready',
      selected: true,
      meta: {
        sourceKind: 'document',
        aiPayload: {
          source_id: 'document:legacy-aliases',
          sourceId: 'document:wrong-id',
          title: '旧字段文档',
          source_kind: 'document',
          sourceKind: 'web',
          included: ['evidence', 'metric_gaps', 'visual_specs'],
          evidenceNodes: [{
            id: 'legacy-node',
            sourceId: 'document:legacy-aliases',
            sourceType: 'document',
            title: '旧节点',
            content: '旧 camel EvidenceNode 不应进入 target。',
          }],
          metricGaps: [{ text: '旧指标缺口' }],
          visualSpecs: [{ visual_id: 'legacy-visual' }],
          counts: { evidence: 1, metric_gaps: 1, visual_specs: 1 },
        },
      },
    }],
  })

  assert.deepEqual(target.artifact_refs, ['document:legacy-aliases'])
  assert.equal(target.payload.sources[0].source_kind, 'document')
  assert.deepEqual(target.payload.sources[0].evidence_nodes, [])
  assert.deepEqual(target.payload.sources[0].metric_gaps, [])
  assert.deepEqual(target.payload.sources[0].visual_specs, [])
  assert.equal(target.evidence[0].text, '该来源包含可用于 AI 的分析输入块。')
})

test('analysis source target does not infer source kind from meta alias', () => {
  const target = buildAnalysisSourceTarget({
    sources: [{
      id: 'document:meta-kind',
      title: '旧 meta 类型',
      status: 'ready',
      selected: true,
      meta: {
        sourceKind: 'document',
        aiPayload: {
          source_id: 'document:meta-kind',
          included: ['evidence'],
          evidence_nodes: [{
            id: 'document:meta-kind:node:1',
            source_id: 'document:meta-kind',
            source_type: 'document',
            title: '证据',
            content: '当前 payload 没有声明 source_kind。',
          }],
        },
      },
    }],
  })

  assert.equal(target.payload.sources[0].source_kind, '')
})
