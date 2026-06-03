import test from 'node:test'
import assert from 'node:assert/strict'

import { createAnalysisHistoryOrchestratorMethods } from '../src/pages/analysis/orchestrators/history.js'

function createContext(overrides = {}) {
  return {
    ...createAnalysisHistoryOrchestratorMethods(),
    selectedPoint: { lng: 112.9388, lat: 28.2282 },
    scopeSource: 'history',
    currentHistoryRecordId: 'history-1',
    currentHistoryPolygonWgs84: [[112.9, 28.2], [113.0, 28.3], [112.9, 28.2]],
    isochroneScopeMode: 'point',
    drawnScopePolygon: [],
    allPoisDetails: [],
    resultDataSource: 'local',
    poiDataSource: 'local',
    transportMode: 'walking',
    timeHorizon: 15,
    poiStatus: '',
    normalizePoiSource(source, fallback = 'local') {
      return source || fallback
    },
    getIsochronePolygonPayload() {
      return [[1, 1], [1, 2], [2, 2], [1, 1]]
    },
    loadHistoryList() {
      return Promise.resolve()
    },
    ...overrides,
  }
}

test('saveAnalysisHistoryAsync skips network save for restored history', async () => {
  const ctx = createContext()
  let fetchCalled = false
  const previousFetch = global.fetch
  global.fetch = async () => {
    fetchCalled = true
    throw new Error('should not save restored history')
  }

  try {
    ctx.saveAnalysisHistoryAsync()
    await new Promise((resolve) => setTimeout(resolve, 10))
    assert.equal(fetchCalled, false)
    assert.equal(ctx.poiStatus, '当前历史年份已保存，无需重复保存')
  } finally {
    global.fetch = previousFetch
  }
})

test('saveAnalysisHistoryAsync sends multi-year poi snapshots', async () => {
  const ctx = createContext({
    scopeSource: '',
    currentHistoryRecordId: '',
    currentHistoryAvailablePoiYears: [],
    resultPoiYear: 2024,
    poiYearSource: '2024',
  })
  const previousFetch = global.fetch
  let requestBody = null
  global.fetch = async (_url, options = {}) => {
    if (_url === '/api/v1/analysis/history/save') {
      requestBody = JSON.parse(options.body || '{}')
    }
    return {
      ok: true,
      json: async () => ({ history_id: 'history-multi' }),
    }
  }

  try {
    await ctx.saveAnalysisHistoryAsync([[1, 1], [1, 2], [2, 2], [1, 1]], [{ name: '餐饮' }], [{ id: 'display', name: 'D', location: [1, 2] }], {
      selectedYear: 2024,
      years: [2020, 2022, 2024],
      poiResultsByYear: [
        { source: 'local', year: 2020, pois: [{ id: 'a', name: 'A', location: [1, 1], type: '餐饮' }] },
        { source: 'local', year: 2022, pois: [{ id: 'b', name: 'B', location: [2, 2], type: '购物' }] },
        { source: 'local', year: 2024, pois: [{ id: 'c', name: 'C', location: [3, 3], type: '住宿' }] },
      ],
    })

    assert.deepEqual(requestBody.years, [2020, 2022, 2024])
    assert.equal(requestBody.year, 2024)
    assert.equal(requestBody.poi_results_by_year.length, 3)
    assert.deepEqual(requestBody.poi_results_by_year.map((item) => item.year), [2020, 2022, 2024])
    assert.deepEqual(ctx.currentHistoryAvailablePoiYears, [2020, 2022, 2024])
    assert.equal(ctx.currentHistorySelectedPoiYear, 2024)
  } finally {
    global.fetch = previousFetch
  }
})

test('persistAnalysisArtifact posts canonical artifact payload after ensuring history', async () => {
  const ctx = createContext({
    scopeSource: '',
    currentHistoryRecordId: '',
    resultPoiYear: 2024,
    poiYearSource: '2024',
    poiGridFeatures: [{ type: 'Feature', properties: { cell_id: 'cell-1', poi_count: 3 } }],
    poiGridSummary: { grid_count: 1, assigned_poi_count: 3 },
    getPoiRasterGridYear() {
      return 2024
    },
  })
  const previousFetch = global.fetch
  const requests = []
  global.fetch = async (url, options = {}) => {
    requests.push({ url, body: JSON.parse(options.body || '{}') })
    if (url === '/api/v1/analysis/history/save') {
      return { ok: true, json: async () => ({ history_id: 'history-artifact' }) }
    }
    return { ok: true, json: async () => ({ id: 1, artifact_type: 'poi_raster_grid' }) }
  }

  try {
    const result = await ctx.persistAnalysisArtifact('poi_raster_grid')

    assert.equal(result.artifact_type, 'poi_raster_grid')
    assert.equal(ctx.currentHistoryRecordId, 'history-artifact')
    const rasterRequest = requests.find((item) => item.url === '/api/v1/analysis/history/history-artifact/artifacts' && item.body.artifact_type === 'poi_raster_grid')
    assert.ok(rasterRequest)
    assert.equal(rasterRequest.body.params.year, 2024)
    assert.equal(rasterRequest.body.params.grid_type, 'shared_raster')
    assert.equal(rasterRequest.body.params.cell_id_source, 'population_nightlight_shared_cell_id')
    assert.equal(rasterRequest.body.payload.grid.grid_type, 'shared_raster')
    assert.equal(rasterRequest.body.payload.grid.features[0].properties.cell_id, 'cell-1')
    assert.deepEqual(rasterRequest.body.summary, { grid_count: 1, assigned_poi_count: 3 })
  } finally {
    global.fetch = previousFetch
  }
})
