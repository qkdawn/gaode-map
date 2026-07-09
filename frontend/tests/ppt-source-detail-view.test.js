import test from 'node:test'
import assert from 'node:assert/strict'

import {
  carrierMetric,
  carrierPoiLabel,
  carrierPopulationLabel,
  carrierTypeLabel,
  currentGapDescription,
  currentGapMeta,
  currentGapTitle,
  currentMetricSourceIds,
  formatCurrentMetricValue,
  formatPackageMetric,
  packageItemRadiance,
  packageItemSubtitle,
  packageItemTitle,
} from '../src/features/ppt-planning/source-detail-view.js'

test('ppt source detail view formats current source metrics and gaps', () => {
  assert.equal(formatPackageMetric(null), '-')
  assert.equal(formatPackageMetric(12), '12')
  assert.equal(formatPackageMetric(12.3400), '12.34')
  assert.equal(formatCurrentMetricValue({ value: 0.4567, unit: '分' }), '0.457分')
  assert.equal(formatCurrentMetricValue({}), '-')
  assert.equal(currentMetricSourceIds({ sourceIds: ['current:scope', '', 'current:dataset:poi'] }), 'current:scope / current:dataset:poi')
  assert.equal(currentMetricSourceIds({ source_id: 'current:analysis:road' }), 'current:analysis:road')
  assert.equal(currentGapTitle({ needed_metric: '收入' }, 2), '收入')
  assert.equal(currentGapTitle({}, 2), '缺口指标 3')
  assert.equal(currentGapDescription({ reason: '缺少字段' }), '缺少字段')
  assert.equal(currentGapDescription({}), '当前没有可用计算结果。')
  assert.equal(currentGapMeta({ source_path: 'a.b', source_id: 'source:1', metric_id: 'metric:1' }), 'a.b / source:1 / metric:1')
})

test('ppt source detail view formats package items and carrier summaries', () => {
  assert.equal(packageItemTitle({}, 1), '点位 2')
  assert.equal(packageItemTitle({ label: '候选点' }, 0), '候选点')
  assert.equal(packageItemSubtitle({ category: '餐饮', subcategory: '咖啡' }), '餐饮 / 咖啡')
  assert.equal(packageItemSubtitle({}), '未分类')
  assert.equal(packageItemRadiance({ nightlight_cell: { radiance: 0.456 } }), '0.456')
  assert.equal(packageItemRadiance({ nightlight_cell: { class_label: '中亮度' } }), '中亮度')

  const carrier = {
    carrier_type: 'corridor',
    road_metrics: { choice_score: 12.5 },
    poi_metrics: {
      total_related_poi_count: 30,
      dominant_categories: [{ category: '餐饮' }, { name: '购物' }, { category: '娱乐' }],
    },
    population_metrics: {
      total_population: 1234.56,
      demand_strength: '中',
    },
  }
  assert.equal(carrierTypeLabel(carrier), '廊道')
  assert.equal(carrierMetric(carrier, 'road_metrics', 'choice_score'), '12.5')
  assert.equal(carrierPoiLabel(carrier), '30 个 · 餐饮 / 购物')
  assert.equal(carrierPopulationLabel(carrier), '总人口 1234.56 · 中')
  assert.equal(carrierTypeLabel({ carrier_type: 'block_loop' }), '街区 / loop')
  assert.equal(carrierTypeLabel({}), '路段')
  assert.equal(carrierPopulationLabel({ population_metrics: { view_label: '居住人口', mean_cell_value: 88.8, unit: '人', demand_strength: '弱' } }), '居住人口均值 88.8 人 · 弱')
})
