import test from 'node:test'
import assert from 'node:assert/strict'

import { buildPoiRuntimePoints } from '../src/features/poi/records.js'

test('buildPoiRuntimePoints classifies canonical POI records by typecode', () => {
  const typeIds = {
    '050100': 'type-food',
    '060100': 'type-shopping',
    '170200': 'type-company',
  }
  const result = buildPoiRuntimePoints([
    {
      poi_id: 'poi-food',
      name: '社区食堂',
      typecode: '050100',
      address: '测试路 1 号',
      location: [112.90, 28.10],
    },
    {
      poi_id: 'poi-shopping',
      name: '社区商店',
      typecode: '060100',
      address: '测试路 2 号',
      location: [112.91, 28.11],
    },
    {
      poi_id: 'poi-company',
      name: '测试公司',
      typecode: '170200',
      address: '测试路 3 号',
      location: [112.92, 28.12],
    },
  ], {
    defaultTypeId: 'type-company-enterprise',
    normalizeLngLat(value) {
      return Array.isArray(value) && value.length >= 2 ? value : null
    },
    resolveTypeId(value) {
      return typeIds[String(value || '')] || ''
    },
    summarizeCoordInput(value) {
      return value
    },
  })

  assert.deepEqual(result.points.map((point) => point.type), [
    'type-food',
    'type-shopping',
    'type-company',
  ])
  assert.deepEqual(result.points.map((point) => point._pid), [
    'poi-food',
    'poi-shopping',
    'poi-company',
  ])
  assert.equal(result.invalidPointCount, 0)
})
