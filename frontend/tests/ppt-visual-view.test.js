import test from 'node:test'
import assert from 'node:assert/strict'

import {
  formatMetricClaimValue,
  formatVisualOverlayValue,
  visualColumnKey,
  visualColumnLabel,
  visualColumnsPreview,
  visualComposition,
  visualEvidenceSummary,
  visualExistingAssetMissingText,
  visualGroupSummary,
  visualLinkSummary,
  visualMetricOverlays,
  visualNodeSummary,
  visualReasonText,
  visualRowsPreview,
  visualTypeLabel,
} from '../src/features/ppt-planning/visual-view.js'

test('ppt visual view formats metric and overlay values', () => {
  assert.equal(formatMetricClaimValue({ value: 1234.56, unit: '人' }), '1,235人')
  assert.equal(formatMetricClaimValue({ value: 0.12345, unit: '%' }), '0.123%')
  assert.equal(formatMetricClaimValue({ text: '缺少数据' }), '缺少数据')
  assert.equal(formatVisualOverlayValue({ value: 98.7654, unit: '分' }), '98.765分')
  assert.equal(formatVisualOverlayValue({}), '—')
})

test('ppt visual view extracts visual summaries from payload variants', () => {
  const visual = {
    visual_type: 'existing_asset',
    source_metric_ids: ['poi.total', 'road.integration', 'nightlight.mean', 'population.total'],
    data: {
      composition: 'map_with_metric_overlays',
      reason: '缺少截图资产',
      metric_overlays: [
        { label: 'POI', value: 1200, unit: '个' },
        { metric_id: 'nightlight.mean', value: 0.45 },
        {},
      ],
      capture_error: { message: '图层缺失', code: 'missing_layer', detail: 'population_grid' },
      rows: [{ a: 1 }, { a: 2 }, { a: 3 }, { a: 4 }, { a: 5 }],
      columns: [{ key: 'a', label: 'A' }, { field: 'b' }, 'c', 'd', 'e'],
    },
  }

  assert.equal(visualTypeLabel(visual), '已有空间图')
  assert.equal(visualComposition(visual), 'map_with_metric_overlays')
  assert.equal(visualReasonText(visual), '缺少截图资产')
  assert.equal(visualEvidenceSummary(visual), '指标：poi.total / road.integration / nightlight.mean 等 4 个')
  assert.equal(visualMetricOverlays(visual).length, 2)
  assert.match(visualExistingAssetMissingText(visual), /图层缺失/)
  assert.deepEqual(visualRowsPreview(visual), [{ a: 1 }, { a: 2 }, { a: 3 }, { a: 4 }])
  assert.deepEqual(visualColumnsPreview(visual), [{ key: 'a', label: 'A' }, { field: 'b' }, 'c', 'd'])
  assert.equal(visualColumnKey({ key: 'a', label: 'A' }), 'a')
  assert.equal(visualColumnLabel({ field: 'b' }), 'b')
  assert.equal(visualColumnKey('c'), 'c')
})

test('ppt visual view summarizes diagram nodes groups and links', () => {
  const visual = {
    visualType: 'diagram',
    sourceIds: ['source:a', 'source:b', 'source:c', 'source:d'],
    nodes: [{ title: '机会' }, { label: '客群' }, { name: '交通' }, { id: 'poi' }, { title: '夜光' }, { title: '竞品' }, { title: '额外' }],
    groups: [{ title: '需求' }, { label: '供给' }, { name: '可达' }, { id: '风险' }, { title: '额外' }],
    links: [{ source: '机会', target: '客群' }, { from: '交通', to: '供给' }, {}, { source: '风险' }],
  }

  assert.equal(visualTypeLabel(visual), '语义图')
  assert.equal(visualEvidenceSummary(visual), '来源：source:a / source:b / source:c 等 4 个')
  assert.deepEqual(visualNodeSummary(visual), ['机会', '客群', '交通', 'poi', '夜光', '竞品'])
  assert.deepEqual(visualGroupSummary(visual), ['需求', '供给', '可达', '风险'])
  assert.deepEqual(visualLinkSummary(visual), ['机会 → 客群', '交通 → 供给', '风险 →'])
})
