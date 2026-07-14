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
            document_role: 'project_brief',
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
  assert.equal(target.evidence[0].text, '项目文档身份已传递（角色：project_brief），核心证据由后端档案模块读取。')
  assert.equal(target.evidence[0].document_role, 'project_brief')
  assert.equal(target.payload.sources[0].document_role, 'project_brief')
  assert.deepEqual(target.payload.sources[0].included, ['document_identity'])
  assert.equal(Object.prototype.hasOwnProperty.call(target.payload.sources[0], 'evidence_nodes'), false)
  assert.equal(Object.prototype.hasOwnProperty.call(target.payload.sources[0], 'metrics'), false)
  assert.equal(Object.prototype.hasOwnProperty.call(target.payload.sources[0], 'evidence'), false)
  assert.equal(Object.prototype.hasOwnProperty.call(target.payload.sources[0], 'sourceId'), false)
  assert.equal(Object.prototype.hasOwnProperty.call(target.payload.sources[0], 'sourceKind'), false)
  assert.equal(Object.prototype.hasOwnProperty.call(target.payload.sources[0], 'evidenceNodes'), false)
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
  assert.equal(Object.prototype.hasOwnProperty.call(target.payload.sources[0], 'evidence_nodes'), false)
  assert.equal(Object.prototype.hasOwnProperty.call(target.payload.sources[0], 'metric_gaps'), false)
  assert.equal(Object.prototype.hasOwnProperty.call(target.payload.sources[0], 'visual_specs'), false)
  assert.equal(target.evidence[0].text, '项目文档身份已传递（角色：未标注），核心证据由后端档案模块读取。')
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

  assert.equal(target.payload.sources[0].source_kind, 'document')
  assert.deepEqual(target.payload.sources[0].included, ['document_identity'])
})
