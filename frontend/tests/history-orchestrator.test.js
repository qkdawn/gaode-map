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

test('buildAnalysisArtifactBundle uses normalized dataset payloads', () => {
  const ctx = createContext({
    resultPoiYear: 2024,
    poiYearSource: '2024',
    h3NeighborRing: 2,
    poiGridFeatures: [{ type: 'Feature', properties: { cell_id: 'r1_c1', poi_count: 5 } }],
    poiGridSummary: { scope_id: 'shared-scope', grid_count: 1 },
    h3AnalysisGridFeatures: [{ type: 'Feature', properties: { h3_id: 'h3-1', poi_count: 9 } }],
    h3GridCount: 1,
    h3GridResolution: 9,
    h3GridIncludeMode: 'intersects',
    h3GridMinOverlapRatio: 0.25,
    h3AnalysisSummary: { grid_count: 1 },
    getPopulationSelectedYear() {
      return '2026'
    },
    populationAnalysisView: 'density',
    populationScopeId: 'population-scope',
    populationOverview: { summary: { total_population: 100 } },
    populationGrid: {
      scope_id: 'population-grid-scope',
      features: [{ type: 'Feature', properties: { cell_id: 'p1' } }],
    },
    populationLayer: { cells: [{ cell_id: 'p1', value: 10 }] },
    buildAgentPopulationGridEvidence() {
      return { evidence_level: 'population-test' }
    },
    nightlightSelectedYear: 2025,
    nightlightAnalysisView: 'radiance',
    nightlightScopeId: 'nightlight-scope',
    nightlightOverview: { summary: { mean_radiance: 3 } },
    nightlightGrid: {
      scope_id: 'nightlight-grid-scope',
      features: [{ type: 'Feature', properties: { cell_id: 'n1' } }],
    },
    nightlightLayer: { cells: [{ cell_id: 'n1', value: 4 }] },
    nightlightRaster: { image_url: 'data:image/png;base64,test' },
    roadSyntaxGraphModel: 'segment',
    roadSyntaxMetric: 'choice',
    roadSyntaxSummary: { road_count: 1 },
    roadSyntaxRoadFeatures: [{ type: 'Feature', properties: { road_id: 'road-1' } }],
    roadSyntaxNodes: [{ type: 'Feature', properties: { node_id: 'node-1' } }],
  })

  const raster = ctx.buildAnalysisArtifactBundle('poi_raster_grid')
  const h3 = ctx.buildAnalysisArtifactBundle('poi_h3_grid')
  const population = ctx.buildAnalysisArtifactBundle('population')
  const nightlight = ctx.buildAnalysisArtifactBundle('nightlight')
  const road = ctx.buildAnalysisArtifactBundle('road_syntax')

  for (const bundle of [raster, h3, population, nightlight, road]) {
    assert.equal(bundle.payload.geometry_coord_type, 'gcj02')
  }

  assert.equal(raster.payload.grid.type, 'FeatureCollection')
  assert.equal(raster.payload.grid.scope_id, 'shared-scope')
  assert.equal(raster.payload.grid.cell_count, 1)
  assert.equal(raster.payload.year, 2024)
  assert.equal(h3.payload.grid.type, 'FeatureCollection')
  assert.equal(h3.payload.grid.count, 1)
  assert.equal(h3.payload.grid.resolution, 9)
  assert.equal(h3.payload.year, 2024)
  assert.equal(population.payload.grid.scope_id, 'population-grid-scope')
  assert.equal(population.payload.grid.cell_count, 1)
  assert.equal(population.payload.layer.view, 'density')
  assert.equal(population.payload.layer.year, '2026')
  assert.equal(population.payload.year, '2026')
  assert.equal(nightlight.payload.grid.scope_id, 'nightlight-grid-scope')
  assert.equal(nightlight.payload.grid.cell_count, 1)
  assert.equal(nightlight.payload.layer.view, 'radiance')
  assert.equal(nightlight.payload.layer.year, 2025)
  assert.equal(nightlight.payload.year, 2025)
  assert.equal(road.payload.roads.type, 'FeatureCollection')
  assert.equal(road.payload.roads.count, 1)
  assert.equal(road.payload.nodes.type, 'FeatureCollection')
  assert.equal(road.payload.nodes.count, 1)
  assert.equal(road.payload.metric, 'choice')
})
