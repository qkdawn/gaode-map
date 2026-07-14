import test from 'node:test'
import assert from 'node:assert/strict'

import { createPackageAiPayload } from '../src/features/ppt-planning/source-payloads.js'

test('ppt package payload compacts package summary, samples, and carriers for AI', () => {
  const payload = createPackageAiPayload('package:poi:auto', 'POI 机会包', {
    title: '餐饮机会包',
    summary: '餐饮和购物密集，夜间活跃度中等。',
    package_mode: 'auto',
    intent: 'opportunity',
    total: 20,
    items: Array.from({ length: 8 }, (_, index) => ({
      id: `poi-${index + 1}`,
      name: `POI ${index + 1}`,
      category: '餐饮',
      subcategory: '咖啡',
      address: `地址 ${index + 1}`,
    })),
    carriers: Array.from({ length: 10 }, (_, index) => ({
      carrier_id: `carrier-${index + 1}`,
      carrier_label: `载体 ${index + 1}`,
      summary: `载体摘要 ${index + 1}`,
      road_metrics: { betweenness: index },
    })),
  })

  assert.equal(payload.version, 'ppt_ai_input_block_v1')
  assert.equal(payload.source_id, 'package:poi:auto')
  assert.equal(payload.source_kind, 'package')
  assert.deepEqual(payload.included, ['evidence'])
  assert.equal(payload.counts.evidence, 15)
  assert.equal(payload.evidence_nodes.length, 15)
  assert.equal(payload.excluded.find((item) => item.type === 'package_full_items').count, 8)
  assert.equal(payload.excluded.find((item) => item.type === 'package_carrier_geometries').count, 10)
  assert.equal(payload.evidence_nodes.some((node) => node.kind === 'package_summary'), true)
  assert.equal(payload.evidence_nodes.filter((node) => node.kind === 'package_item').length, 6)
  assert.equal(payload.evidence_nodes.filter((node) => node.kind === 'spatial_carrier').length, 8)
})

test('ppt package payload returns empty evidence contract when package has no summary or samples', () => {
  const payload = createPackageAiPayload('package:empty', '空资料包', {})

  assert.deepEqual(payload.included, [])
  assert.equal(payload.counts.evidence, 0)
  assert.deepEqual(payload.evidence_nodes, [])
  assert.equal(payload.excluded.find((item) => item.type === 'package_full_items').count, 0)
})
