import test from 'node:test'
import assert from 'node:assert/strict'

import { createAnalysisHistoryMethods } from '../src/features/history/restore.js'
import { createAnalysisHistoryOrchestratorMethods } from '../src/pages/analysis/orchestrators/history.js'
import {
  createAnalysisNightlightInitialState,
  createAnalysisNightlightMethods,
} from '../src/features/nightlight/panel.js'

const historyMethods = createAnalysisHistoryMethods()
const historyOrchestratorMethods = createAnalysisHistoryOrchestratorMethods()
const nightlightMethods = createAnalysisNightlightMethods()

function createHistoryRestoreContext(overrides = {}) {
  const nightlightState = createAnalysisNightlightInitialState()
  const ctx = {
    ...nightlightState,
    mapCore: {
      center: null,
      map: {
        setCenter(value) {
          ctx.mapSetCenterCalls.push(value)
        },
      },
      setRadius(value) {
        ctx.mapSetRadiusCalls.push(value)
      },
      clearGridPolygons() {
        ctx.clearedGridPolygons += 1
      },
      clearPopulationRasterOverlay() {
        ctx.clearedRasterOverlays += 1
      },
    },
    mapSetCenterCalls: [],
    mapSetRadiusCalls: [],
    clearedGridPolygons: 0,
    clearedRasterOverlays: 0,
    clearedH3Grid: 0,
    clearedPoiOverlayLayersArgs: [],
    clearScopeOutlineDisplayCalls: 0,
    resetRoadSyntaxStateCalls: 0,
    populationResetArgs: [],
    nightlightResetArgs: [],
    applySimplifyConfigCalls: 0,
    resetPanelCalls: [],
    step: 1,
    sidebarView: 'start',
    activeStep3Panel: 'nightlight',
    drawnScopePolygon: [[120, 30], [120.1, 30], [120, 30.1], [120, 30]],
    timeHorizon: 10,
    transportMode: 'walking',
    resultDataSource: '',
    scopeSource: '',
    lastIsochroneGeoJSON: null,
    isochroneScopeMode: 'point',
    allPoisDetails: [{ id: 'old-poi' }],
    poiGridResultsByYearType: {
      '2020:h3': { status: 'failed', error: 'old failed h3' },
    },
    activePoiGridResultKey: '2020:h3',
    clearH3Grid() {
      this.clearedH3Grid += 1
    },
    clearPoiOverlayLayers(args) {
      this.clearedPoiOverlayLayersArgs.push(args)
    },
    clearScopeOutlineDisplay() {
      this.clearScopeOutlineDisplayCalls += 1
    },
    resetRoadSyntaxState() {
      this.resetRoadSyntaxStateCalls += 1
    },
    resetPopulationAnalysisState(args) {
      this.populationResetArgs.push(args)
    },
    clearNightlightDisplayOnLeave: nightlightMethods.clearNightlightDisplayOnLeave,
    resetNightlightAnalysisState(args) {
      this.nightlightResetArgs.push(args)
      return nightlightMethods.resetNightlightAnalysisState.call(this, args)
    },
    normalizePoiSource(source, fallback) {
      return String(source || fallback || '')
    },
    normalizePath(path) {
      return Array.isArray(path) ? path : []
    },
    _closePolygonRing(path) {
      if (!Array.isArray(path) || !path.length) return []
      const out = path.map((point) => [point[0], point[1]])
      const first = out[0]
      const last = out[out.length - 1]
      if (!last || first[0] !== last[0] || first[1] !== last[1]) {
        out.push([first[0], first[1]])
      }
      return out
    },
    _normalizePolygonPayloadRings(polygon) {
      if (!Array.isArray(polygon) || !polygon.length) return []
      if (Array.isArray(polygon[0]) && Array.isArray(polygon[0][0])) {
        return polygon.map((ring) => this._closePolygonRing(ring))
      }
      return [this._closePolygonRing(polygon)]
    },
    applySimplifyConfig() {
      this.applySimplifyConfigCalls += 1
    },
    resetAnalysisDisplayTargetsForPanel(panelId, options) {
      this.resetPanelCalls.push({ panelId, options })
    },
  }
  return Object.assign(ctx, overrides)
}

function createArtifactBundleContext(overrides = {}) {
  const ctx = {
    cloneArtifactValue: historyOrchestratorMethods.cloneArtifactValue,
    normalizePoiSource(source, fallback) {
      return String(source || fallback || '')
    },
    getPopulationSelectedYear() {
      return String(this.populationSelectedYear || '2026')
    },
    buildAgentPopulationGridEvidence() {
      return { evidence_level: 'test_population_grid' }
    },
    populationSelectedYear: '2026',
    populationAnalysisView: 'density',
    populationScopeId: 'population-scope',
    populationOverview: { summary: { total_population: 100 } },
    populationGrid: {
      scope_id: 'population-grid-scope',
      features: [{ type: 'Feature', properties: { cell_id: 'p1' }, geometry: { type: 'Polygon', coordinates: [] } }],
    },
    populationLayer: {
      scope_id: 'population-layer-scope',
      cells: [{ cell_id: 'p1', value: 10 }],
    },
    nightlightSelectedYear: 2025,
    nightlightAnalysisView: 'radiance',
    nightlightScopeId: 'nightlight-scope',
    nightlightOverview: { summary: { mean_radiance: 3 } },
    nightlightGrid: {
      scope_id: 'nightlight-grid-scope',
      features: [{ type: 'Feature', properties: { cell_id: 'n1' }, geometry: { type: 'Polygon', coordinates: [] } }],
    },
    nightlightLayer: {
      scope_id: 'nightlight-layer-scope',
      cells: [{ cell_id: 'n1', value: 4 }],
    },
    nightlightRaster: { image_url: 'data:image/png;base64,test' },
    roadSyntaxGraphModel: 'segment',
    transportMode: 'walking',
    roadSyntaxMetric: 'choice',
    roadSyntaxSummary: { road_count: 1 },
    roadSyntaxDiagnostics: { status: 'ok' },
    roadSyntaxRoadFeatures: [{ type: 'Feature', properties: { road_id: 'r1' }, geometry: { type: 'LineString', coordinates: [] } }],
    roadSyntaxNodes: [{ type: 'Feature', properties: { node_id: 'node1' }, geometry: { type: 'Point', coordinates: [0, 0] } }],
    roadSyntaxWebglPayload: { layer: 'road' },
  }
  return Object.assign(ctx, overrides)
}

test('_applyHistoryDetailBaseResult resets nightlight analysis state while preserving meta and year', () => {
  const ctx = createHistoryRestoreContext({
    nightlightMetaLoaded: true,
    nightlightMeta: {
      available_years: [{ year: 2024, label: '2024 年' }, { year: 2025, label: '2025 年' }],
      default_year: 2025,
    },
    nightlightSelectedYear: 2024,
    nightlightStatus: '旧夜光结果',
    nightlightScopeId: 'old-scope',
    nightlightOverview: { summary: { total_radiance: 10 } },
    nightlightGrid: { features: [{ id: 'old-grid' }] },
    nightlightGridCount: 1,
    nightlightLayer: { cells: [{ cell_id: 'a' }] },
    nightlightRaster: { image_url: 'data:image/png;base64,old' },
  })

  historyMethods._applyHistoryDetailBaseResult.call(ctx, {
    params: {
      center: [121.48, 31.23],
      mode: 'driving',
      time_min: 15,
      source: 'local',
      drawn_polygon: [],
    },
    polygon: [[121.47, 31.22], [121.49, 31.22], [121.49, 31.24], [121.47, 31.22]],
  })

  assert.deepEqual(ctx.nightlightResetArgs, [{ keepMeta: true, keepYear: true }])
  assert.equal(ctx.nightlightStatus, '')
  assert.equal(ctx.nightlightScopeId, '')
  assert.equal(ctx.nightlightOverview, null)
  assert.equal(ctx.nightlightGrid, null)
  assert.equal(ctx.nightlightGridCount, 0)
  assert.equal(ctx.nightlightLayer, null)
  assert.equal(ctx.nightlightRaster, null)
  assert.equal(ctx.nightlightMetaLoaded, true)
  assert.equal(ctx.nightlightSelectedYear, 2024)
  assert.equal(ctx.clearedGridPolygons, 1)
  assert.equal(ctx.clearedRasterOverlays, 1)
  assert.equal(ctx.activeStep3Panel, 'poi')
  assert.equal(ctx.step, 2)
  assert.equal(ctx.sidebarView, 'wizard')
  assert.equal(ctx.scopeSource, 'history')
  assert.deepEqual(ctx.poiGridResultsByYearType, {})
  assert.equal(ctx.activePoiGridResultKey, '')
  assert.deepEqual(ctx.resetPanelCalls, [{ panelId: 'poi', options: { apply: false } }])
})

test('buildAnalysisArtifactBundle stores full population nightlight and road datasets', () => {
  const ctx = createArtifactBundleContext()

  const populationBundle = historyOrchestratorMethods.buildAnalysisArtifactBundle.call(ctx, 'population')
  const nightlightBundle = historyOrchestratorMethods.buildAnalysisArtifactBundle.call(ctx, 'nightlight')
  const roadBundle = historyOrchestratorMethods.buildAnalysisArtifactBundle.call(ctx, 'road_syntax')

  assert.equal(populationBundle.payload.grid.type, 'FeatureCollection')
  assert.equal(populationBundle.payload.grid.scope_id, 'population-grid-scope')
  assert.equal(populationBundle.payload.grid.count, 1)
  assert.equal(populationBundle.payload.grid.cell_count, 1)
  assert.equal(populationBundle.payload.grid.features[0].properties.cell_id, 'p1')
  assert.equal(populationBundle.payload.layer.cells[0].cell_id, 'p1')
  assert.equal(populationBundle.payload.grid_evidence.evidence_level, 'test_population_grid')

  assert.equal(nightlightBundle.payload.grid.type, 'FeatureCollection')
  assert.equal(nightlightBundle.payload.grid.scope_id, 'nightlight-grid-scope')
  assert.equal(nightlightBundle.payload.grid.count, 1)
  assert.equal(nightlightBundle.payload.grid.cell_count, 1)
  assert.equal(nightlightBundle.payload.grid.features[0].properties.cell_id, 'n1')
  assert.equal(nightlightBundle.payload.layer.cells[0].cell_id, 'n1')
  assert.equal(nightlightBundle.payload.raster.image_url, 'data:image/png;base64,test')

  assert.equal(roadBundle.payload.roads.type, 'FeatureCollection')
  assert.equal(roadBundle.payload.roads.features[0].properties.road_id, 'r1')
  assert.equal(roadBundle.payload.nodes.type, 'FeatureCollection')
  assert.equal(roadBundle.payload.nodes.features[0].properties.node_id, 'node1')
})

test('loadHistoryDetail keeps restored history id and history scope source', async () => {
  const originalFetch = global.fetch
  const originalWindow = global.window
  const ctx = Object.assign(
    createHistoryRestoreContext(),
    historyMethods,
    {
      historyDetailLoadToken: 0,
      historyDetailAbortController: null,
      historyFetchAbortController: null,
      cancelHistoryLoading() {},
      cancelHistoryDetailLoading() {
        this.historyDetailLoadToken += 1
        this.historyDetailAbortController = null
      },
      stopScopeDrawing() {},
      clearIsochroneDebugState() {},
      $nextTick() {
        return Promise.resolve()
      },
      async _restoreHistoryPoisAsync(id) {
        this.restoredPoiHistoryId = id
        this.allPoisDetails = [{ id: 'history-poi' }]
      },
      syncSummaryTaskBoardFromLocalResults(options) {
        this.summaryTaskBoardSyncs = Array.isArray(this.summaryTaskBoardSyncs) ? this.summaryTaskBoardSyncs.slice() : []
        this.summaryTaskBoardSyncs.push(options)
      },
    },
  )
  global.window = {
    requestAnimationFrame(callback) {
      callback()
    },
  }
  global.fetch = async (url) => {
    if (url === '/api/v1/analysis/history/123/artifacts') {
      return {
        ok: true,
        async json() {
          return []
        },
      }
    }
    assert.equal(url, '/api/v1/analysis/history/123?include_pois=false')
    return {
      ok: true,
      async json() {
        return {
          params: {
            center: [121.48, 31.23],
            mode: 'walking',
            time_min: 15,
            source: 'local',
            drawn_polygon: [],
          },
          polygon: [[121.47, 31.22], [121.49, 31.22], [121.49, 31.24], [121.47, 31.22]],
          poi_count: 1,
        }
      },
    }
  }

  try {
    await ctx.loadHistoryDetail(123)
  } finally {
    global.fetch = originalFetch
    global.window = originalWindow
  }

  assert.equal(ctx.currentHistoryRecordId, '123')
  assert.equal(ctx.scopeSource, 'history')
  assert.equal(ctx.restoredPoiHistoryId, '123')
  assert.deepEqual(ctx.allPoisDetails, [{ id: 'history-poi' }])
  assert.deepEqual(ctx.summaryTaskBoardSyncs, [{ sync: false }])
})

test('restoreHistoryArtifactsAsync hydrates reusable base artifacts', async () => {
  const originalFetch = global.fetch
  const ctx = Object.assign(createHistoryRestoreContext(), historyMethods, {
    historyDetailLoadToken: 1,
    currentHistorySelectedPoiYear: 2024,
    resultPoiYear: 2024,
    poiYearSource: '2024',
    commitPoiGridResult(year, type, patch) {
      this.committedPoiGrid = this.committedPoiGrid || []
      this.committedPoiGrid.push({ type, year, status: patch && patch.status })
    },
    commitCurrentPoiGridResult(type, year) {
      this.appliedPoiGrid = { type, year }
    },
    restorePoiRasterGridDisplayOnEnter() {
      this.restoredRasterDisplay = true
    },
    _restoreHistoryH3ResultAsync(payload) {
      this.h3AnalysisSummary = payload.summary
      return true
    },
    _restoreHistoryRoadResultAsync(payload) {
      this.roadSyntaxSummary = payload.summary
      return true
    },
    $nextTick(callback) {
      if (typeof callback === 'function') callback()
      return Promise.resolve()
    },
    updatePopulationCharts() {
      this.populationChartsUpdated = true
    },
    syncSummaryTaskBoardFromLocalResults(options) {
      this.summaryTaskBoardSyncs = Array.isArray(this.summaryTaskBoardSyncs) ? this.summaryTaskBoardSyncs.slice() : []
      this.summaryTaskBoardSyncs.push(options)
    },
  })
  global.fetch = async (url) => {
    assert.equal(url, '/api/v1/analysis/history/history-1/artifacts')
    return {
      ok: true,
      json: async () => [
        { artifact_type: 'poi_raster_grid', updated_at: '2026-01-02', params: { year: 2020, grid_type: 'shared_raster' }, payload: { year: 2020, grid: { type: 'FeatureCollection', grid_type: 'shared_raster', features: [{ properties: { cell_id: 'wrong-year' } }] }, summary: { grid_count: 999 } } },
        { artifact_type: 'poi_raster_grid', updated_at: '2026-01-01', params: { year: 2024, grid_type: 'shared_raster' }, payload: { year: 2024, grid: { type: 'FeatureCollection', grid_type: 'shared_raster', features: [{ properties: { cell_id: 'cell-1' } }] }, summary: { grid_count: 1 } } },
        { artifact_type: 'poi_h3_grid', updated_at: '2026-01-01', params: { year: 2024 }, payload: { summary: { grid_count: 2 } } },
        {
          artifact_type: 'population',
          updated_at: '2026-01-01',
          payload: {
            year: '2026',
            overview: { summary: { total_population: 10 } },
            grid: {
              type: 'FeatureCollection',
              scope_id: 'population-scope',
              features: [{ type: 'Feature', properties: { cell_id: 'p1' }, geometry: { type: 'Polygon', coordinates: [] } }],
              count: 1,
              cell_count: 1,
            },
            layer: {
              scope_id: 'population-scope',
              view: 'density',
              summary: { average_density_per_km2: 8000 },
              legend: { title: '人口密度' },
              cells: [{ cell_id: 'p1' }],
            },
          },
        },
        {
          artifact_type: 'nightlight',
          updated_at: '2026-01-01',
          payload: {
            year: 2025,
            overview: { summary: { mean_radiance: 3 } },
            grid: {
              type: 'FeatureCollection',
              scope_id: 'nightlight-scope',
              features: [{ type: 'Feature', properties: { cell_id: 'n1' }, geometry: { type: 'Polygon', coordinates: [] } }],
              count: 1,
              cell_count: 1,
            },
            layer: {
              scope_id: 'nightlight-scope',
              view: 'radiance',
              summary: { total_radiance: 30 },
              analysis: { core_hotspot_count: 2, hotspot_cell_ratio: 0.25, peak_to_edge_ratio: 3.2 },
              legend: { title: '夜光' },
              cells: [{ cell_id: 'n1' }],
            },
          },
        },
        { artifact_type: 'road_syntax', updated_at: '2026-01-01', payload: { summary: { node_count: 5 } } },
      ],
    }
  }

  try {
    const result = await ctx.restoreHistoryArtifactsAsync('history-1', 1)

    assert.equal(result.rasterRestored, true)
    assert.equal(result.h3Restored, true)
    assert.equal(result.populationRestored, true)
    assert.equal(result.nightlightRestored, true)
    assert.equal(result.roadRestored, true)
    assert.equal(ctx.poiGridSummary.grid_count, 1)
    assert.equal(ctx.h3AnalysisSummary.grid_count, 2)
    assert.deepEqual(ctx.committedPoiGrid, [
      { type: 'shared', year: 2020, status: 'ready' },
      { type: 'shared', year: 2024, status: 'ready' },
    ])
    assert.deepEqual(ctx.appliedPoiGrid, { type: 'shared', year: 2024 })
    assert.equal(ctx.populationOverview.summary.total_population, 10)
    assert.equal(ctx.populationGrid.scope_id, 'population-scope')
    assert.equal(ctx.populationGrid.features[0].properties.cell_id, 'p1')
    assert.equal(ctx.populationGridCount, 1)
    assert.equal(ctx.populationScopeId, 'population-scope')
    assert.equal(ctx.populationLayer.summary.average_density_per_km2, 8000)
    assert.equal(ctx.populationLayer.cells[0].cell_id, 'p1')
    assert.equal(ctx.nightlightOverview.summary.mean_radiance, 3)
    assert.equal(ctx.nightlightGrid.scope_id, 'nightlight-scope')
    assert.equal(ctx.nightlightGrid.features[0].properties.cell_id, 'n1')
    assert.equal(ctx.nightlightGridCount, 1)
    assert.equal(ctx.nightlightScopeId, 'nightlight-scope')
    assert.equal(ctx.nightlightLayer.analysis.core_hotspot_count, 2)
    assert.equal(ctx.nightlightLayer.analysis.hotspot_cell_ratio, 0.25)
    assert.equal(ctx.nightlightLayer.analysis.peak_to_edge_ratio, 3.2)
    assert.equal(ctx.nightlightLayer.cells[0].cell_id, 'n1')
    assert.equal(ctx.roadSyntaxSummary.node_count, 5)
    assert.deepEqual(ctx.summaryTaskBoardSyncs, [{ sync: false }])
  } finally {
    global.fetch = originalFetch
  }
})

test('history restore ignores population and nightlight artifacts without full grid features', async () => {
  const ctx = createHistoryRestoreContext({
    historyDetailLoadToken: 1,
    populationGrid: { features: [{ id: 'existing-population-grid' }] },
    populationGridCount: 1,
    populationLayer: { cells: [{ cell_id: 'existing-p' }] },
    nightlightGrid: { features: [{ id: 'existing-nightlight-grid' }] },
    nightlightGridCount: 1,
    nightlightLayer: { cells: [{ cell_id: 'existing-n' }] },
  })

  const populationRestored = await historyMethods.restoreHistoryPopulationArtifact.call(ctx, {
    payload: {
      year: '2026',
      overview: { summary: { total_population: 10 } },
      layer: { cells: [{ cell_id: 'new-p1' }] },
    },
  }, 1)
  const nightlightRestored = await historyMethods.restoreHistoryNightlightArtifact.call(ctx, {
    payload: {
      year: 2025,
      overview: { summary: { mean_radiance: 3 } },
      layer: { cells: [{ cell_id: 'new-n1' }] },
    },
  }, 1)

  assert.equal(populationRestored, false)
  assert.equal(nightlightRestored, false)
  assert.deepEqual(ctx.populationGrid, { features: [{ id: 'existing-population-grid' }] })
  assert.equal(ctx.populationGridCount, 1)
  assert.deepEqual(ctx.populationLayer, { cells: [{ cell_id: 'existing-p' }] })
  assert.deepEqual(ctx.nightlightGrid, { features: [{ id: 'existing-nightlight-grid' }] })
  assert.equal(ctx.nightlightGridCount, 1)
  assert.deepEqual(ctx.nightlightLayer, { cells: [{ cell_id: 'existing-n' }] })
})

test('_restoreHistoryH3ResultAsync restores h3 data and recomputes derived stats', async () => {
  const ctx = createHistoryRestoreContext({
    historyDetailLoadToken: 1,
    activeStep3Panel: 'poi',
    poiSubTab: 'params',
    h3MainStage: 'params',
    h3SubTab: 'metric_map',
    h3MetricView: 'density',
    h3StructureFillMode: 'gi_z',
    computeH3DerivedStatsCalls: 0,
    ensureH3PanelEntryStateCalls: 0,
    computeH3DerivedStats() {
      this.computeH3DerivedStatsCalls += 1
      this.h3DerivedStats = { structureSummary: { rows: [{ h3_id: 'h3-1' }] } }
    },
    ensureH3PanelEntryState() {
      this.ensureH3PanelEntryStateCalls += 1
    },
    commitCurrentPoiGridResult(type, year) {
      this.committedH3GridResult = { type, year }
    },
  })

  const restored = await historyMethods._restoreHistoryH3ResultAsync.call(ctx, {
    grid: {
      type: 'FeatureCollection',
      features: [{ type: 'Feature', properties: { h3_id: 'h3-1', poi_count: 8 } }],
      count: 1,
      resolution: 9,
      include_mode: 'intersects',
      min_overlap_ratio: 0.35,
    },
    summary: { grid_count: 1, poi_count: 8 },
    charts: { density_histogram: { bins: [1, 2] } },
    year: 2024,
    ui: {
      main_stage: 'diagnosis',
      sub_tab: 'gap',
      metric_view: 'entropy',
      structure_fill_mode: 'lisa_z',
    },
  }, 1)

  assert.equal(restored, true)
  assert.equal(ctx.h3AnalysisGridFeatures.length, 1)
  assert.equal(ctx.h3GridResolution, 9)
  assert.equal(ctx.h3GridMinOverlapRatio, 0.35)
  assert.equal(ctx.h3AnalysisSummary.grid_count, 1)
  assert.equal(ctx.h3MainStage, 'diagnosis')
  assert.equal(ctx.h3SubTab, 'gap')
  assert.equal(ctx.h3MetricView, 'entropy')
  assert.equal(ctx.h3StructureFillMode, 'lisa_z')
  assert.equal(ctx.computeH3DerivedStatsCalls, 1)
  assert.equal(ctx.ensureH3PanelEntryStateCalls, 1)
  assert.deepEqual(ctx.committedH3GridResult, { type: 'h3', year: 2024 })
})

test('_restoreHistoryPoisAsync includes backend detail in failure message', async () => {
  const originalFetch = global.fetch
  const ctx = Object.assign(createHistoryRestoreContext(), historyMethods, {
    historyDetailLoadToken: 1,
  })
  global.fetch = async () => ({
    ok: false,
    status: 500,
    clone() {
      return this
    },
    async json() {
      return { detail: '数据库排序内存不足，POI 明细未恢复' }
    },
    async text() {
      return ''
    },
  })

  try {
    await assert.rejects(
      () => ctx._restoreHistoryPoisAsync('history-1', 1, new AbortController().signal),
      /数据库排序内存不足/,
    )
  } finally {
    global.fetch = originalFetch
  }
})

test('ensureNightlightPanelEntryState recomputes after history reset cleared previous results', async () => {
  const ctx = Object.assign(
    createAnalysisNightlightInitialState(),
    nightlightMethods,
    {
      step: 2,
      activeStep3Panel: 'nightlight',
      simplifyTargets: ['map', 'nightlight'],
      loadNightlightMetaCalls: 0,
      ensureNightlightBaseGridCalls: 0,
      fetchNightlightOverviewCalls: 0,
      fetchNightlightLayerCalls: [],
      fetchNightlightRasterCalls: 0,
      restoredNightlightDisplays: 0,
      getIsochronePolygonRing() {
        return [[121.47, 31.22], [121.49, 31.22], [121.49, 31.24], [121.47, 31.22]]
      },
      hasSimplifyDisplayTarget(target) {
        return this.simplifyTargets.includes(target)
      },
      applyNightlightGridToMap() {},
      clearNightlightDisplayOnLeave() {},
      async loadNightlightMeta() {
        this.loadNightlightMetaCalls += 1
        this.nightlightMetaLoaded = true
        return this.nightlightMeta
      },
      async ensureNightlightBaseGrid() {
        this.ensureNightlightBaseGridCalls += 1
        this.nightlightGrid = { features: [{ id: 'new-grid' }] }
        this.nightlightGridCount = 1
        this.nightlightScopeId = 'new-scope'
        return this.nightlightGrid
      },
      async fetchNightlightOverview() {
        this.fetchNightlightOverviewCalls += 1
        this.nightlightOverview = { summary: { total_radiance: 15 } }
        return this.nightlightOverview
      },
      async fetchNightlightLayer(view) {
        this.fetchNightlightLayerCalls.push(view)
        this.nightlightAnalysisView = view
        this.nightlightLayer = {
          view,
          analysis: {
            core_hotspot_count: 2,
            hotspot_cell_ratio: 0.25,
            peak_to_edge_ratio: 3.5,
          },
          cells: [{ cell_id: 'new-cell' }],
        }
        return this.nightlightLayer
      },
      async fetchNightlightRaster() {
        this.fetchNightlightRasterCalls += 1
        this.nightlightRaster = { image_url: 'data:image/png;base64,new', bounds_gcj02: [] }
        return this.nightlightRaster
      },
      restoreNightlightDisplayOnEnter() {
        this.restoredNightlightDisplays += 1
      },
    },
  )

  await nightlightMethods.ensureNightlightPanelEntryState.call(ctx)

  assert.equal(ctx.loadNightlightMetaCalls, 1)
  assert.equal(ctx.ensureNightlightBaseGridCalls, 1)
  assert.equal(ctx.fetchNightlightOverviewCalls, 1)
  assert.deepEqual(ctx.fetchNightlightLayerCalls, ['radiance'])
  assert.equal(ctx.fetchNightlightRasterCalls, 1)
  assert.equal(ctx.nightlightScopeId, 'new-scope')
  assert.deepEqual(ctx.nightlightOverview, { summary: { total_radiance: 15 } })
  assert.equal(ctx.nightlightLayer.analysis.core_hotspot_count, 2)
  assert.equal(ctx.nightlightLayer.analysis.hotspot_cell_ratio, 0.25)
  assert.equal(ctx.nightlightLayer.analysis.peak_to_edge_ratio, 3.5)
})

test('ensureNightlightPanelEntryState fills missing layer and raster when overview already exists', async () => {
  const ctx = Object.assign(
    createAnalysisNightlightInitialState(),
    nightlightMethods,
    {
      step: 2,
      activeStep3Panel: 'nightlight',
      nightlightOverview: { scope_id: 'old-scope', summary: { total_radiance: 20 } },
      loadNightlightMetaCalls: 0,
      ensureNightlightBaseGridCalls: 0,
      fetchNightlightOverviewCalls: 0,
      fetchNightlightLayerCalls: [],
      fetchNightlightRasterCalls: 0,
      persistedArtifacts: [],
      getIsochronePolygonRing() {
        return [[121.47, 31.22], [121.49, 31.22], [121.49, 31.24], [121.47, 31.22]]
      },
      hasSimplifyDisplayTarget(target) {
        return target === 'nightlight'
      },
      applyNightlightGridToMap() {},
      clearNightlightDisplayOnLeave() {},
      async loadNightlightMeta() {
        this.loadNightlightMetaCalls += 1
        return this.nightlightMeta
      },
      async ensureNightlightBaseGrid() {
        this.ensureNightlightBaseGridCalls += 1
        this.nightlightGrid = { features: [{ id: 'grid' }] }
        this.nightlightGridCount = 1
        this.nightlightScopeId = 'scope-2025'
        return this.nightlightGrid
      },
      async fetchNightlightOverview() {
        this.fetchNightlightOverviewCalls += 1
        throw new Error('overview should not refetch')
      },
      async fetchNightlightLayer(view) {
        this.fetchNightlightLayerCalls.push(view)
        this.nightlightAnalysisView = view
        this.nightlightLayer = {
          view,
          analysis: {
            core_hotspot_count: 4,
            hotspot_cell_ratio: 0.4,
            peak_to_edge_ratio: 2.8,
          },
          cells: [{ cell_id: 'n1' }],
        }
        return this.nightlightLayer
      },
      async fetchNightlightRaster() {
        this.fetchNightlightRasterCalls += 1
        this.nightlightRaster = { image_url: 'data:image/png;base64,new', bounds_gcj02: [] }
        return this.nightlightRaster
      },
      persistAnalysisArtifactQuietly(kind) {
        this.persistedArtifacts.push(kind)
      },
      restoreNightlightDisplayOnEnter() {
        this.restoredNightlightDisplays = Number(this.restoredNightlightDisplays || 0) + 1
      },
    },
  )

  await nightlightMethods.ensureNightlightPanelEntryState.call(ctx)

  assert.equal(ctx.fetchNightlightOverviewCalls, 0)
  assert.deepEqual(ctx.fetchNightlightLayerCalls, ['radiance'])
  assert.equal(ctx.fetchNightlightRasterCalls, 1)
  assert.equal(ctx.nightlightLayer.analysis.core_hotspot_count, 4)
  assert.equal(ctx.nightlightLayer.analysis.hotspot_cell_ratio, 0.4)
  assert.equal(ctx.nightlightLayer.analysis.peak_to_edge_ratio, 2.8)
  assert.deepEqual(ctx.persistedArtifacts, ['nightlight'])
  assert.match(ctx.nightlightStatus, /夜光分析完成/)
})
