import test from 'node:test'
import assert from 'node:assert/strict'

import { createAnalysisPoiFlowOrchestratorMethods } from '../src/pages/analysis/orchestrators/poi-flow.js'
import { createAnalysisPoiPanelMethods } from '../src/features/poi/panel.js'

function createContext(overrides = {}) {
  return {
    ...createAnalysisPoiFlowOrchestratorMethods(),
    ...createAnalysisPoiPanelMethods(),
    lastIsochroneGeoJSON: { type: 'Feature' },
    selectedPoint: { lng: 112.9, lat: 28.2, name: 'Test point' },
    transportMode: 'walking',
    timeHorizon: 15,
    poiYearSelections: [2020, 2022, 2024],
    poiYearSource: '2020',
    currentHistoryAvailablePoiYears: [],
    currentHistorySelectedPoiYear: null,
    currentHistoryRecordId: '',
    scopeSource: '',
    allPoisDetails: [],
    poiStatus: '',
    fetchProgress: 0,
    isFetchingPois: false,
    poiDataSource: 'local',
    resultDataSource: 'local',
    resultPoiYear: 2020,
    activeStep3Panel: 'poi',
    poiSubTab: 'category',
    fetchSubtypeProgress: {},
    poiCategories: [{ id: 'food', name: 'Food', color: '#f00' }],
    getIsochronePolygonPayload() {
      return [[1, 1], [1, 2], [2, 2], [1, 1]]
    },
    buildSelectedCategoryBuckets() {
      return [{ id: 'food', name: 'Food', types: '050000' }]
    },
    getPoiSourceLabel(source, year) {
      return `${year}-${source}`
    },
    resetRoadSyntaxState() {},
    resetFetchSubtypeProgress() {},
    updateFetchSubtypeProgressDisplay() {},
    accumulateFetchSubtypeHits() {},
    deduplicateFetchedPois(pois) {
      return pois
    },
    clearPoiOverlayLayers() {},
    rebuildPoiRuntimeSystem(pois) {
      this.rebuiltPois = pois
    },
    updatePoiCharts() {},
    resizePoiChart() {},
    applySimplifyConfig() {},
    resetAnalysisDisplayTargetsForPanel() {},
    ...overrides,
  }
}

function sseResponse(events) {
  const encoder = new TextEncoder()
  const chunks = events.map((event) => encoder.encode(`event: ${event.type}\ndata: ${JSON.stringify(event.payload)}\n\n`))
  return {
    ok: true,
    body: {
      getReader() {
        let index = 0
        return {
          async read() {
            if (index >= chunks.length) return { done: true, value: undefined }
            return { done: false, value: chunks[index++] }
          },
        }
      },
    },
  }
}

test('fetchPois streams multi-year progress and applies backend aggregation payload', async () => {
  const ctx = createContext()
  const previousFetch = global.fetch
  const requests = []
  global.fetch = async (url, options = {}) => {
    const body = JSON.parse(options.body || '{}')
    requests.push({ url, body })
    return sseResponse([
      { type: 'start', payload: { type: 'start', years: [2020, 2022, 2024], category_count: 1, total_units: 3 } },
      { type: 'category_start', payload: { type: 'category_start', year: 2020, source: 'local', category: 'Food', category_index: 1, category_count: 1, progress: 0 } },
      { type: 'category_complete', payload: { type: 'category_complete', year: 2020, source: 'local', category: 'Food', count: 1, completed_units: 1, total_units: 3, progress: 33 } },
      { type: 'year_complete', payload: { type: 'year_complete', year: 2024, source: 'local', count: 1, progress: 100 } },
      {
        type: 'final',
        payload: {
          type: 'final',
          result: {
        years: [2020, 2022, 2024],
        selected_year: 2024,
        display_pois: [
          { id: 'poi-2024', name: 'POI 2024', location: [112.9, 28.2], type: '050000' },
        ],
        results_by_year: [
          { source: 'local', year: 2020, pois: [{ id: 'poi-2020', location: [112.9, 28.2], type: '050000' }], count: 1 },
          { source: 'local', year: 2022, pois: [{ id: 'poi-2022', location: [112.9, 28.2], type: '050000' }], count: 1 },
          { source: 'local', year: 2024, pois: [{ id: 'poi-2024', location: [112.9, 28.2], type: '050000' }], count: 1 },
        ],
        category_summary: [{ id: 'food', name: 'Food', count: 1 }],
        errors: [],
        history_id: 'history-123',
          },
          progress: 100,
        },
      },
    ])
  }

  try {
    await ctx.fetchPois({ preserveCurrentPanel: true })

    assert.equal(requests.length, 1)
    assert.equal(requests[0].url, '/api/v1/analysis/pois/multi-year/stream')
    assert.deepEqual(requests[0].body.years, [2020, 2022, 2024])
    assert.deepEqual(requests[0].body.categories, [{ id: 'food', name: 'Food', types: '050000' }])
    assert.equal(requests[0].body.save_history, true)
    assert.equal(ctx.fetchProgress, 100)
    assert.deepEqual(ctx.currentHistoryAvailablePoiYears, [2020, 2022, 2024])
    assert.equal(ctx.currentHistorySelectedPoiYear, 2024)
    assert.equal(ctx.poiYearSource, '2024')
    assert.equal(ctx.allPoisDetails[0].id, 'poi-2024')
    assert.equal(ctx.currentHistoryRecordId, 'history-123')
    assert.equal(ctx.scopeSource, 'history')
    assert.deepEqual(ctx.poiCategorySummary, [{ id: 'food', name: 'Food', count: 1 }])
    assert.deepEqual(ctx.poiResultsByYear.map((item) => item.year), [2020, 2022, 2024])
  } finally {
    global.fetch = previousFetch
  }
})

test('poi raster grid exposes public target label for templates', () => {
  const ctx = createContext({
    h3TargetCategory: 'food',
    h3CategoryMeta: [{ key: 'food', label: '餐饮' }],
  })

  assert.equal(ctx.getPoiRasterTargetCategoryLabel(), '餐饮')
})

test('ensurePoiRasterGrid force refreshes raster features from grid API', async () => {
  const ctx = createContext({
    poiSubTab: 'grid',
    poiGridType: 'raster',
    poiGridFeatures: [{
      type: 'Feature',
      geometry: { type: 'Polygon', coordinates: [] },
      properties: { cell_id: 'old-cell', h3_id: 'old-cell', poi_count: 9 },
    }],
    poiGridSummary: { grid_count: 1, max_poi_count: 9 },
    selectedH3Id: 'old-cell',
    getIsochronePolygonRing() {
      return [[1, 1], [1, 2], [2, 2], [1, 1]]
    },
    mapCore: {
      cleared: 0,
      rendered: null,
      clearGridPolygons() {
        this.cleared += 1
      },
      setGridFeatures(features, options) {
        this.rendered = { features, options }
      },
    },
  })
  const previousFetch = global.fetch
  const requests = []
  global.fetch = async (url, options = {}) => {
    requests.push({ url, body: JSON.parse(options.body || '{}') })
    return {
      ok: true,
      json: async () => ({
        features: [{
          type: 'Feature',
          geometry: { type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] },
          properties: { cell_id: 'new-cell', poi_count: 3 },
        }],
        summary: { grid_count: 1, active_cell_count: 1, assigned_poi_count: 3, max_poi_count: 3 },
      }),
    }
  }

  try {
    const data = await ctx.ensurePoiRasterGrid(true)

    assert.equal(requests.length, 1)
    assert.equal(requests[0].url, '/api/v1/analysis/pois/grid')
    assert.equal(requests[0].body.year, 2020)
    assert.equal(ctx.poiGridFeatures[0].properties.cell_id, 'new-cell')
    assert.equal(ctx.poiGridSummary.grid_count, 1)
    assert.equal(ctx.selectedH3Id, null)
    assert.equal(ctx.mapCore.cleared, 1)
    assert.equal(data.summary.assigned_poi_count, 3)
  } finally {
    global.fetch = previousFetch
  }
})

test('restorePoiRasterGridDisplayOnEnter renders clickable styled raster features', () => {
  const ctx = createContext({
    poiSubTab: 'grid',
    poiGridType: 'raster',
    poiGridSummary: { max_poi_count: 6 },
    poiGridFeatures: [
      {
        type: 'Feature',
        geometry: { type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] },
        properties: { cell_id: 'r0_c0', poi_count: 0 },
      },
      {
        type: 'Feature',
        geometry: { type: 'Polygon', coordinates: [[[1, 0], [2, 0], [2, 1], [1, 0]]] },
        properties: { cell_id: 'r0_c1', poi_count: 6 },
      },
    ],
    mapCore: {
      rendered: null,
      clearGridPolygons() {},
      setGridFeatures(features, options) {
        this.rendered = { features, options }
      },
    },
  })

  ctx.restorePoiRasterGridDisplayOnEnter()

  assert.equal(ctx.mapCore.rendered.options.clickable, true)
  assert.equal(ctx.mapCore.rendered.options.webglBatch, false)
  assert.equal(ctx.mapCore.rendered.features[0].properties.h3_id, 'r0_c0')
  assert.equal(ctx.mapCore.rendered.features[1].properties.h3_id, 'r0_c1')
  assert.equal(ctx.mapCore.rendered.features[0].properties.fillColor, '#f8fafc')
  assert.equal(ctx.mapCore.rendered.features[1].properties.fillColor, '#1d4ed8')
})
