import test from 'node:test'
import assert from 'node:assert/strict'

import { createAnalysisSharedGridMethods } from '../src/features/shared-grid/panel.js'
import { createAnalysisPoiStoreInitialState } from '../src/stores/analysis/poi.js'

const sharedGridMethods = createAnalysisSharedGridMethods()

function feature(cellId = 'r7_c9') {
  return {
    type: 'Feature',
    geometry: { type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]] },
    properties: {
      cell_id: cellId,
      density_poi_per_km2: 3.2,
      population_density: 23781,
      nightlight_radiance: 8.5,
      road_integration: 0.808,
      road_connectivity: 0.5,
      road_length_km_per_km2: 1.4,
    },
  }
}

function readiness(year, recordCount) {
  return { ready: true, year, record_count: recordCount, reason: '' }
}

function createContext(overrides = {}) {
  const calls = { setGridFeatures: 0, clearGridPolygons: 0 }
  const ctx = {
    step: 2,
    activeStep3Panel: 'shared_grid',
    h3SimplifyTargets: ['map', 'shared_grid'],
    historyDetailLoadToken: 7,
    allPoisDetails: [{ id: 'poi-1', location: [0.5, 0.5] }],
    resultPoiYear: 2026,
    populationGrid: { features: [feature()] },
    populationSelectedYear: '2026',
    nightlightGrid: { features: [feature()] },
    nightlightSelectedYear: 2025,
    roadSyntaxSummary: { road_count: 1 },
    roadSyntaxRoadFeatures: [{ type: 'Feature', geometry: { type: 'LineString', coordinates: [[0, 0], [1, 1]] }, properties: {} }],
    sharedGrid: { type: 'FeatureCollection', features: [feature()] },
    sharedGridSummary: { assigned_poi_count: 1 },
    sharedGridSourceVersions: {},
    sharedGridSourceReadiness: {},
    sharedGridLimitations: [],
    sharedGridMetric: 'density_poi_per_km2',
    sharedGridSelectedCellId: '',
    isGeneratingSharedGrid: false,
    getPopulationSelectedYear() { return this.populationSelectedYear },
    getIsochronePolygonPayload() { return [] },
    buildSelectedCategoryBuckets() { return [] },
    hasSimplifyDisplayTarget(target) { return this.h3SimplifyTargets.includes(target) },
    mapCore: {
      setAnalysisBackdropMode() {},
      setGridFeatures(features, style) {
        calls.setGridFeatures += 1
        calls.lastFeatures = features
        calls.lastStyle = style
      },
      clearGridPolygons() { calls.clearGridPolygons += 1 },
    },
    persistAnalysisArtifact: async () => ({ id: 1 }),
  }
  Object.assign(ctx, sharedGridMethods, overrides)
  return { ctx, calls }
}

test('Step 3 navigation places shared grid after road syntax and before AI', () => {
  const ids = createAnalysisPoiStoreInitialState().step3NavItems.map((item) => item.id)
  assert.ok(ids.includes('shared_grid'))
  assert.ok(ids.indexOf('syntax') < ids.indexOf('shared_grid'))
  assert.ok(ids.indexOf('shared_grid') < ids.indexOf('agent'))
})

test('shared grid requires all current source layers before generation', () => {
  const { ctx } = createContext({ nightlightGrid: null })

  assert.equal(ctx.isSharedGridReadyToGenerate(), false)
  assert.equal(ctx.getSharedGridBlockingText(), '请先准备：夜光')
})

test('a completed POI query with zero records remains a ready zero-valued source', () => {
  const { ctx } = createContext({ allPoisDetails: [], poiResultsByYear: [{ year: 2026, pois: [] }] })

  assert.equal(ctx.getCurrentSharedGridSourceRows().find((row) => row.key === 'poi').ready, true)
  assert.equal(ctx.isSharedGridReadyToGenerate(), true)
})

test('restored source metadata remains visible without enabling a refresh', () => {
  const { ctx } = createContext({
    allPoisDetails: [],
    populationGrid: null,
    nightlightGrid: null,
    roadSyntaxSummary: null,
    roadSyntaxRoadFeatures: [],
    sharedGridSourceReadiness: {
      poi: readiness(2026, 12),
      population: readiness('2026', 48),
      nightlight: readiness(2025, 48),
      road: readiness(null, 20),
    },
  })

  assert.equal(ctx.isSharedGridReadyToGenerate(), false)
  assert.ok(ctx.getSharedGridSourceRows().every((row) => row.ready))
  assert.match(ctx.getSharedGridSourceRows()[0].detail, /已参与已恢复网格/)
})

test('switching a shared-grid metric redraws the existing map layer without requesting data', () => {
  const { ctx, calls } = createContext()
  let fetchCalls = 0
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => { fetchCalls += 1; throw new Error('unexpected fetch') }
  try {
    ctx.setSharedGridMetric('road_integration')
  } finally {
    globalThis.fetch = originalFetch
  }

  assert.equal(ctx.sharedGridMetric, 'road_integration')
  assert.equal(calls.setGridFeatures, 1)
  assert.equal(calls.lastFeatures[0].properties.road_integration, 0.808)
  assert.equal(fetchCalls, 0)
})

test('history shared-grid artifact restores grid metadata and map overlay', () => {
  const { ctx, calls } = createContext({ sharedGrid: null })
  const restored = ctx.restoreHistorySharedGridArtifact({
    summary: { assigned_poi_count: 1 },
    payload: {
      grid: { type: 'FeatureCollection', features: [feature()] },
      summary: { assigned_poi_count: 1 },
      source_versions: { population: readiness('2026', 1) },
      source_readiness: { population: readiness('2026', 1) },
      limitations: ['仅作代理指标'],
    },
  }, 7)

  assert.equal(restored, true)
  assert.equal(ctx.sharedGrid.features[0].properties.cell_id, 'r7_c9')
  assert.equal(ctx.sharedGridSourceReadiness.population.ready, true)
  assert.equal(calls.setGridFeatures, 1)
})

test('leaving shared grid clears its independent grid overlay', () => {
  const { ctx, calls } = createContext()

  ctx.clearSharedGridDisplayOnLeave()

  assert.equal(calls.clearGridPolygons, 1)
})
