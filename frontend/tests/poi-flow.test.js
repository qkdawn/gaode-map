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

test('fetchPois sends one multi-year request and applies backend aggregation payload', async () => {
  const ctx = createContext()
  const previousFetch = global.fetch
  const requests = []
  global.fetch = async (url, options = {}) => {
    const body = JSON.parse(options.body || '{}')
    requests.push({ url, body })
    return {
      ok: true,
      json: async () => ({
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
      }),
    }
  }

  try {
    await ctx.fetchPois({ preserveCurrentPanel: true })

    assert.equal(requests.length, 1)
    assert.equal(requests[0].url, '/api/v1/analysis/pois/multi-year')
    assert.deepEqual(requests[0].body.years, [2020, 2022, 2024])
    assert.deepEqual(requests[0].body.categories, [{ id: 'food', name: 'Food', types: '050000' }])
    assert.equal(requests[0].body.save_history, true)
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
