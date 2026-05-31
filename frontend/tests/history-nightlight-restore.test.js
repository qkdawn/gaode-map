import test from 'node:test'
import assert from 'node:assert/strict'

import { createAnalysisHistoryMethods } from '../src/features/history/restore.js'
import {
  createAnalysisNightlightInitialState,
  createAnalysisNightlightMethods,
} from '../src/features/nightlight/panel.js'

const historyMethods = createAnalysisHistoryMethods()
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
        { artifact_type: 'poi_raster_grid', updated_at: '2026-01-02', params: { year: 2020 }, payload: { year: 2020, features: [{ properties: { cell_id: 'wrong-year' } }], summary: { grid_count: 999 } } },
        { artifact_type: 'poi_raster_grid', updated_at: '2026-01-01', params: { year: 2024 }, payload: { year: 2024, features: [{ properties: { cell_id: 'cell-1' } }], summary: { grid_count: 1 } } },
        { artifact_type: 'poi_h3_grid', updated_at: '2026-01-01', params: { year: 2024 }, payload: { summary: { grid_count: 2 } } },
        { artifact_type: 'population', updated_at: '2026-01-01', payload: { year: '2026', overview: { summary: { total_population: 10 } }, layer_cells: [{ cell_id: 'p1' }] } },
        { artifact_type: 'nightlight', updated_at: '2026-01-01', payload: { year: 2025, overview: { summary: { mean_radiance: 3 } }, layer_cells: [{ cell_id: 'n1' }] } },
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
      { type: 'raster', year: 2020, status: 'ready' },
      { type: 'raster', year: 2024, status: 'ready' },
    ])
    assert.deepEqual(ctx.appliedPoiGrid, { type: 'raster', year: 2024 })
    assert.equal(ctx.populationOverview.summary.total_population, 10)
    assert.equal(ctx.nightlightOverview.summary.mean_radiance, 3)
    assert.equal(ctx.roadSyntaxSummary.node_count, 5)
    assert.deepEqual(ctx.summaryTaskBoardSyncs, [{ sync: false }])
  } finally {
    global.fetch = originalFetch
  }
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
      computeNightlightAnalysisCalls: 0,
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
      async computeNightlightAnalysis() {
        this.computeNightlightAnalysisCalls += 1
        this.nightlightOverview = { summary: { total_radiance: 15 } }
        this.nightlightLayer = { cells: [{ cell_id: 'new-cell' }] }
        this.nightlightRaster = { image_url: 'data:image/png;base64,new', bounds_gcj02: [] }
      },
      restoreNightlightDisplayOnEnter() {
        this.restoredNightlightDisplays += 1
      },
    },
  )

  await nightlightMethods.ensureNightlightPanelEntryState.call(ctx)

  assert.equal(ctx.loadNightlightMetaCalls, 1)
  assert.equal(ctx.ensureNightlightBaseGridCalls, 1)
  assert.equal(ctx.computeNightlightAnalysisCalls, 1)
  assert.equal(ctx.nightlightScopeId, 'new-scope')
  assert.deepEqual(ctx.nightlightOverview, { summary: { total_radiance: 15 } })
})
