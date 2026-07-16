import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

import { createAnalysisH3InitialState, createAnalysisH3Methods } from '../src/features/h3/panel.js'
import { createAnalysisNightlightInitialState, createAnalysisNightlightMethods } from '../src/features/nightlight/panel.js'
import { createAnalysisPoiInitialState, createAnalysisPoiPanelMethods } from '../src/features/poi/panel.js'
import { createAnalysisPopulationInitialState, createAnalysisPopulationMethods } from '../src/features/population/panel.js'


const poiMethods = createAnalysisPoiPanelMethods()
const h3Methods = createAnalysisH3Methods()
const populationMethods = createAnalysisPopulationMethods()
const nightlightMethods = createAnalysisNightlightMethods()


test('current grid regeneration always forces the selected grid result', async () => {
  const calls = []
  const ctx = {
    async ensureActivePoiGridResult(force) {
      calls.push(force)
      return { status: 'ready' }
    },
  }

  const result = await poiMethods.startPoiGridAnalysis.call(ctx)

  assert.deepEqual(calls, [true])
  assert.equal(result.status, 'ready')
})


test('population regeneration refetches the base grid and waits for artifact persistence', async () => {
  const originalFetch = globalThis.fetch
  const events = []
  globalThis.fetch = async (url) => {
    events.push(String(url))
    return {
      ok: true,
      async json() {
        return { scope_id: 'scope-new', summary: { total_population: 1200 } }
      },
    }
  }
  const ctx = Object.assign(createAnalysisPopulationInitialState(), populationMethods, {
    populationOverview: { summary: { total_population: 900 } },
    populationGrid: { features: [{ id: 'old-grid' }] },
    populationLayer: { view: 'density' },
    baseGridForces: [],
    getIsochronePolygonRing() { return [[112, 28], [112.1, 28], [112, 28.1]] },
    getIsochronePolygonPayload() { return [[112, 28], [112.1, 28], [112, 28.1]] },
    getPopulationSelectedYear() { return '2026' },
    getPopulationSelectedYearLabel() { return '2026 年' },
    async loadPopulationMeta() {},
    async ensurePopulationBaseGrid(force) {
      this.baseGridForces.push(force)
      this.populationGrid = { features: [{ id: 'new-grid' }] }
      this.populationGridCount = 1
    },
    async fetchPopulationLayer(view) {
      events.push(`layer:${view}`)
      this.populationLayer = { view }
    },
    async persistAnalysisArtifact(type) {
      events.push(`persist:${type}`)
      return { id: 90 }
    },
    $nextTick(callback) { if (callback) callback() },
    updatePopulationCharts() {},
  })

  try {
    const result = await populationMethods.regeneratePopulationAnalysis.call(ctx)
    assert.equal(result, true)
    assert.deepEqual(ctx.baseGridForces, [true])
    assert.deepEqual(events, [
      '/api/v1/analysis/population/overview',
      'layer:density',
      'persist:population',
    ])
    assert.match(ctx.populationStatus, /人口分析完成/)
  } finally {
    globalThis.fetch = originalFetch
  }
})


test('population regeneration reports persistence failure after calculation', async () => {
  const originalFetch = globalThis.fetch
  const originalConsoleError = console.error
  console.error = () => {}
  globalThis.fetch = async () => ({
    ok: true,
    async json() { return { scope_id: 'scope-new', summary: { total_population: 1200 } } },
  })
  const ctx = Object.assign(createAnalysisPopulationInitialState(), populationMethods, {
    getIsochronePolygonRing() { return [[112, 28], [112.1, 28], [112, 28.1]] },
    getIsochronePolygonPayload() { return [[112, 28], [112.1, 28], [112, 28.1]] },
    getPopulationSelectedYear() { return '2026' },
    getPopulationSelectedYearLabel() { return '2026 年' },
    async loadPopulationMeta() {},
    async ensurePopulationBaseGrid() { this.populationGrid = { features: [{ id: 'new-grid' }] } },
    async fetchPopulationLayer() { this.populationLayer = { view: 'density' } },
    async persistAnalysisArtifact() { throw new Error('mysql unavailable') },
    $nextTick(callback) { if (callback) callback() },
    updatePopulationCharts() {},
  })

  try {
    const result = await populationMethods.regeneratePopulationAnalysis.call(ctx)
    assert.equal(result, false)
    assert.match(ctx.populationStatus, /计算完成，但保存失败/)
  } finally {
    globalThis.fetch = originalFetch
    console.error = originalConsoleError
  }
})


test('nightlight regeneration refetches every bundle component despite restored results', async () => {
  const events = []
  const ctx = Object.assign(createAnalysisNightlightInitialState(), nightlightMethods, {
    nightlightOverview: { summary: { mean_radiance: 1 } },
    nightlightGrid: { features: [{ id: 'old-grid' }] },
    nightlightLayer: { view: 'radiance' },
    nightlightRaster: { image_url: 'old' },
    getIsochronePolygonRing() { return [[112, 28], [112.1, 28], [112, 28.1]] },
    getNightlightSelectedYearLabel() { return '2025 年' },
    async loadNightlightMeta() { events.push('meta') },
    async ensureNightlightBaseGrid(force) { events.push(`grid:${force}`) },
    async fetchNightlightOverview() { events.push('overview') },
    async fetchNightlightLayer(view) { events.push(`layer:${view}`); this.nightlightLayer = { view } },
    async fetchNightlightRaster() { events.push('raster') },
    isNightlightDisplayActive() { return false },
    async persistAnalysisArtifact(type) { events.push(`persist:${type}`); return { id: 91 } },
  })

  const result = await nightlightMethods.regenerateNightlightAnalysis.call(ctx)

  assert.equal(result, true)
  assert.deepEqual(events, [
    'meta',
    'grid:true',
    'overview',
    'layer:radiance',
    'raster',
    'persist:nightlight',
  ])
  assert.match(ctx.nightlightStatus, /夜光分析完成/)
})


test('nightlight regeneration reports persistence failure after calculation', async () => {
  const originalConsoleError = console.error
  console.error = () => {}
  const ctx = Object.assign(createAnalysisNightlightInitialState(), nightlightMethods, {
    getIsochronePolygonRing() { return [[112, 28], [112.1, 28], [112, 28.1]] },
    getNightlightSelectedYearLabel() { return '2025 年' },
    async loadNightlightMeta() {},
    async ensureNightlightBaseGrid() { this.nightlightGrid = { features: [{ id: 'new-grid' }] } },
    async fetchNightlightOverview() { this.nightlightOverview = { summary: { mean_radiance: 2 } } },
    async fetchNightlightLayer() { this.nightlightLayer = { view: 'radiance' } },
    async fetchNightlightRaster() { this.nightlightRaster = { image_url: 'new' } },
    isNightlightDisplayActive() { return false },
    async persistAnalysisArtifact() { throw new Error('mysql unavailable') },
  })

  try {
    const result = await nightlightMethods.regenerateNightlightAnalysis.call(ctx)
    assert.equal(result, false)
    assert.match(ctx.nightlightStatus, /计算完成，但保存失败/)
  } finally {
    console.error = originalConsoleError
  }
})


test('current grid entry preserves the artifact persistence failure status', async () => {
  const failure = new Error('mysql unavailable')
  failure.analysisArtifactSaveFailed = true
  const ctx = Object.assign(createAnalysisPoiInitialState(), poiMethods, {
    poiGridType: 'hex',
    poiYearSource: '2024',
    h3GridStatus: 'POI H3 计算完成，但保存失败：mysql unavailable',
    syncH3PoiFilterSelection() {},
    async computeH3Analysis() { throw failure },
  })

  await assert.rejects(() => poiMethods.startPoiGridAnalysis.call(ctx), /mysql unavailable/)

  assert.match(ctx.h3GridStatus, /计算完成，但保存失败/)
  assert.equal(ctx.getPoiGridResult(2024, 'h3').status, 'failed')
})


test('H3 regeneration does not report success when artifact persistence fails', async () => {
  const originalFetch = globalThis.fetch
  const originalWindow = globalThis.window
  const originalConsoleError = console.error
  globalThis.window = { setInterval: () => 1, clearInterval: () => {} }
  console.error = () => {}
  globalThis.fetch = async (url) => {
    if (String(url).includes('/progress')) {
      return { ok: true, async json() { return { step: 7, total: 7, stage: 'completed' } } }
    }
    return {
      ok: true,
      async json() {
        return {
          grid: { count: 1, features: [{ type: 'Feature', properties: { h3_id: 'h3-1' }, geometry: null }] },
          summary: { grid_count: 1, poi_count: 1 },
          charts: {},
        }
      },
    }
  }
  const ctx = Object.assign(createAnalysisH3InitialState(), h3Methods, {
    poiYearSource: '2024',
    resultPoiYear: 2024,
    allPoisDetails: [],
    getIsochronePolygonRing() { return [[112, 28], [112.1, 28], [112, 28.1]] },
    getIsochronePolygonPayload() { return [[112, 28], [112.1, 28], [112, 28.1]] },
    _buildH3AnalysisPois() { return [{ id: 'poi-1', location: [112.01, 28.01] }] },
    _toNumber(value, fallback) { return Number(value) || fallback },
    getH3DefaultSubTabByStage() { return 'metric_map' },
    computeH3DerivedStats() {},
    isH3DisplayActive() { return false },
    clearH3GridDisplayOnLeave() {},
    commitCurrentPoiGridResult() {},
    async persistAnalysisArtifact() { throw new Error('mysql unavailable') },
  })

  try {
    await assert.rejects(() => h3Methods.computeH3Analysis.call(ctx), /mysql unavailable/)
    assert.match(ctx.h3GridStatus, /计算完成，但保存失败/)
  } finally {
    globalThis.fetch = originalFetch
    globalThis.window = originalWindow
    console.error = originalConsoleError
  }
})


test('analysis sidebar exposes explicit regeneration controls', () => {
  const sidebar = fs.readFileSync(new URL('../src/pages/analysis/components/sidebar.html', import.meta.url), 'utf8')

  assert.match(sidebar, /重新生成当前格子/)
  assert.match(sidebar, /@click="regeneratePopulationAnalysis"/)
  assert.match(sidebar, /@click="regenerateNightlightAnalysis"/)
})
