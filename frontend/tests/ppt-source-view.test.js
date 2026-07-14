import test from 'node:test'
import assert from 'node:assert/strict'

import {
  currentSourceDetailTabs,
  currentSourceEvidenceNodes,
  documentRole,
  documentRoleLabel,
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

test('ppt source view helpers expose document role badges', () => {
  const brief = {
    id: 'document:brief',
    meta: { document: { document_role: 'project_brief' } },
  }
  const vision = {
    id: 'document:vision',
    meta: { aiPayload: { document_role: 'design_vision' } },
  }
  assert.equal(documentRole(brief), 'project_brief')
  assert.equal(documentRoleLabel(brief), '项目摘要')
  assert.equal(documentRoleLabel(vision), '设计愿景')
  assert.equal(documentRoleLabel({ id: 'document:reference', meta: { document_role: 'reference_document' } }), '参考资料')
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
          kind: 'dataset_record',
          run_id: '',
          source_ids: ['current:analysis'],
          metric_ids: [],
          title: '证据',
          content: '范围内 POI 完整。',
          data: {},
          time_scope: {},
          spatial_scope: {},
          method: 'dataset_summary',
          quality_flags: [],
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

test('ppt current source detail reads canonical evidence nodes and tab counts', () => {
  const source = {
    id: 'current:analysis:population',
    title: '人口结构分析',
    meta: {
      sourceKind: 'system',
      aiPayload: {
        version: 'ppt_ai_input_block_v1',
        source_id: 'current:analysis:population',
        source_kind: 'system',
        evidence: [{ title: '旧 evidence', text: '不应作为详情 EvidenceNode 数据源' }],
        evidence_nodes: [{
          id: 'current:analysis:population:evidence:derived_metric:age',
          kind: 'spatial_metric',
          run_id: 'run:population',
          source_ids: ['current:analysis:population'],
          metric_ids: ['analysis:population:age_structure'],
          title: '年龄结构',
          content: '已计算各年龄段占比。',
          method: 'derived_metric',
          quality_flags: [],
          time_scope: {},
          spatial_scope: {},
          data: {
            metric_id: 'analysis:population:age_structure',
          },
        }],
      },
    },
  }

  const nodes = currentSourceEvidenceNodes(source)
  assert.equal(nodes.length, 1)
  assert.equal(nodes[0].title, '年龄结构')
  assert.equal(nodes[0].data.metric_id, 'analysis:population:age_structure')

  const tabs = currentSourceDetailTabs({
    readyMetrics: [{ metric_id: 'analysis:population:age_structure' }],
    evidenceNodes: nodes,
    scopePayload: { has_polygon: true },
    visualSpecs: [{ visual_id: 'v1' }, { visual_id: 'v2' }],
    gapMetrics: [],
  })
  assert.deepEqual(tabs.map((item) => [item.key, item.label, item.count, item.available]), [
    ['metrics', 'Metrics', 1, true],
    ['evidence', 'EvidenceNode', 1, true],
    ['scope', 'Scope', 1, true],
    ['visuals', 'Visuals', 2, true],
    ['gaps', 'Gaps', 0, false],
  ])
})

test('ppt current source detail helpers tolerate empty active source during setup', () => {
  assert.deepEqual(currentSourceEvidenceNodes(null), [])
  assert.equal(sourceTransport(null), null)
  assert.equal(sourceTransportLabel(null), '')
})
