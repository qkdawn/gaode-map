function createNightlightFallbackMeta() {
  return {
    available_years: [
      { year: 2025, label: '2025 年' },
    ],
    default_year: 2025,
  }
}

function toNumber(value, fallback = 0) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function createAnalysisNightlightInitialState() {
  const meta = createNightlightFallbackMeta()
  return {
    isComputingNightlight: false,
    isLoadingNightlightMeta: false,
    isLoadingNightlightGrid: false,
    nightlightLayerAbortController: null,
    nightlightLayerRequestSeq: 0,
    nightlightStatus: '',
    nightlightScopeId: '',
    nightlightMeta: meta,
    nightlightMetaLoaded: false,
    nightlightSelectedYear: Number(meta.default_year || 2025),
    nightlightAnalysisView: 'radiance',
    nightlightOverview: null,
    nightlightGrid: null,
    nightlightGridCount: 0,
    nightlightLayer: null,
    nightlightRaster: null,
  }
}

function createAnalysisNightlightMethods() {
  return {
    createNightlightFallbackMeta,
    isNightlightPanelActive() {
      return this.step === 2 && this.activeStep3Panel === 'nightlight'
    },
    isNightlightDisplayActive() {
      return this.step === 2
        && (typeof this.hasSimplifyDisplayTarget === 'function'
          ? this.hasSimplifyDisplayTarget('nightlight')
          : this.isNightlightPanelActive())
    },
    formatNightlightValue(value, digits = 2) {
      const num = toNumber(value, 0)
      if (num >= 1000000) return `${(num / 1000000).toFixed(2)}M`
      if (num >= 1000) return `${(num / 1000).toFixed(1)}k`
      return num.toFixed(digits)
    },
    formatNightlightPercent(value) {
      return `${(toNumber(value, 0) * 100).toFixed(1)}%`
    },
    getNightlightViewOptions() {
      return [
        { value: 'radiance', label: '辐亮' },
        { value: 'hotspot', label: '热点分级' },
        { value: 'gradient', label: '梯度衰减' },
      ]
    },
    setNightlightAnalysisView(view) {
      const nextView = ['radiance', 'hotspot', 'gradient'].includes(String(view || '').trim().toLowerCase())
        ? String(view || '').trim().toLowerCase()
        : 'radiance'
      const currentLayerView = String((this.nightlightLayer && this.nightlightLayer.view) || '').trim().toLowerCase()
      if (this.nightlightAnalysisView === nextView && this.nightlightLayer && currentLayerView === nextView) return
      this.nightlightAnalysisView = nextView
      if (!this.nightlightOverview) return
      this.fetchNightlightLayer(nextView).catch((err) => {
        if (err && err.name === 'AbortError') return
        console.error(err)
        this.nightlightStatus = '夜光图层切换失败: ' + (err && err.message ? err.message : String(err))
      })
    },
    cancelNightlightLayerRequest() {
      if (this.nightlightLayerAbortController) {
        try {
          this.nightlightLayerAbortController.abort()
        } catch (_) {}
        this.nightlightLayerAbortController = null
      }
      this.nightlightLayerRequestSeq = Number(this.nightlightLayerRequestSeq || 0) + 1
    },
    getNightlightYearOptions() {
      return Array.isArray(this.nightlightMeta && this.nightlightMeta.available_years)
        ? this.nightlightMeta.available_years
        : []
    },
    getNightlightSelectedYearLabel() {
      const year = Number(this.nightlightSelectedYear || 0)
      const option = this.getNightlightYearOptions().find((item) => Number(item && item.year) === year)
      return String((option && option.label) || (year > 0 ? `${year} 年` : '-'))
    },
    async loadNightlightMeta(force = false) {
      if ((this.nightlightMetaLoaded && !force) || this.isLoadingNightlightMeta) return this.nightlightMeta
      this.isLoadingNightlightMeta = true
      try {
        const res = await fetch('/api/v1/analysis/nightlight/meta')
        if (!res.ok) {
          throw new Error(`/api/v1/analysis/nightlight/meta 请求失败(${res.status})`)
        }
        const data = await res.json()
        const years = Array.isArray(data.available_years)
          ? data.available_years
            .map((item) => ({
              year: Number(item && item.year),
              label: String((item && item.label) || `${item && item.year} 年`),
            }))
            .filter((item) => Number.isFinite(item.year) && item.year > 0)
          : []
        const defaultYear = Number(data.default_year || (years[years.length - 1] && years[years.length - 1].year) || 2025)
        this.nightlightMeta = {
          available_years: years.length ? years : createNightlightFallbackMeta().available_years,
          default_year: defaultYear,
        }
        this.nightlightMetaLoaded = true
        if (!Number.isFinite(Number(this.nightlightSelectedYear)) || !years.some((item) => item.year === Number(this.nightlightSelectedYear))) {
          this.nightlightSelectedYear = defaultYear
        }
        return this.nightlightMeta
      } catch (e) {
        console.error(e)
        this.nightlightMeta = createNightlightFallbackMeta()
        this.nightlightMetaLoaded = false
        this.nightlightSelectedYear = Number(this.nightlightMeta.default_year || 2025)
        throw e
      } finally {
        this.isLoadingNightlightMeta = false
      }
    },
    resetNightlightAnalysisState(options = {}) {
      const keepMeta = !!(options && options.keepMeta)
      const keepYear = !!(options && options.keepYear)
      if (typeof this.cancelNightlightLayerRequest === 'function') {
        this.cancelNightlightLayerRequest()
      }
      this.isComputingNightlight = false
      this.isLoadingNightlightGrid = false
      this.nightlightStatus = ''
      this.nightlightScopeId = ''
      this.nightlightOverview = null
      this.nightlightGrid = null
      this.nightlightGridCount = 0
      this.nightlightLayer = null
      this.nightlightRaster = null
      if (!keepMeta) {
        this.nightlightMeta = createNightlightFallbackMeta()
        this.nightlightMetaLoaded = false
      }
      if (!keepYear) {
        this.nightlightSelectedYear = Number((this.nightlightMeta && this.nightlightMeta.default_year) || 2025)
      }
      this.nightlightAnalysisView = 'radiance'
      this.clearNightlightDisplayOnLeave()
    },
    clearNightlightDisplayOnLeave() {
      if (this.mapCore && typeof this.mapCore.setAnalysisBackdropMode === 'function') {
        this.mapCore.setAnalysisBackdropMode('')
      }
      if (this.mapCore && typeof this.mapCore.clearGridPolygons === 'function') {
        this.mapCore.clearGridPolygons()
      }
      if (this.mapCore && typeof this.mapCore.clearPopulationRasterOverlay === 'function') {
        this.mapCore.clearPopulationRasterOverlay()
      }
    },
    buildNightlightStyledFeatures() {
      const baseFeatures = ((this.nightlightGrid && this.nightlightGrid.features) || [])
      const safeView = String(this.nightlightAnalysisView || 'radiance').trim().toLowerCase()
      const cellMap = new Map(
        (((this.nightlightLayer && this.nightlightLayer.cells) || []).map((cell) => [String((cell && cell.cell_id) || ''), cell]))
      )
      return baseFeatures.map((feature) => {
        const props = Object.assign({}, (feature && feature.properties) || {})
        const cell = cellMap.get(String(props.cell_id || ''))
        const baseOpacity = toNumber(cell && cell.fill_opacity, 0.28)
        const hasData = !!(cell && cell.has_data)
        const effectiveOpacity = safeView === 'radiance' && hasData
          ? Math.min(0.82, Math.max(0.44, baseOpacity + 0.16))
          : baseOpacity
        return {
          type: 'Feature',
          geometry: feature.geometry,
          properties: Object.assign({}, props, cell ? {
            nightlightClassKey: cell.class_key ? String(cell.class_key) : '',
            nightlightClassLabel: cell.class_label ? String(cell.class_label) : '',
            fillColor: String(cell.fill_color || '#0f172a'),
            fillOpacity: effectiveOpacity,
            strokeColor: String(cell.stroke_color || '#94a3b8'),
            strokeWeight: 0.8,
          } : {
            nightlightClassKey: '',
            nightlightClassLabel: '',
            fillColor: '#090b1f',
            fillOpacity: 0.28,
            strokeColor: '#94a3b8',
            strokeWeight: 0.8,
          }),
        }
      })
    },
    buildNightlightBoundaryConfig() {
      const safeView = String(this.nightlightAnalysisView || 'radiance').trim().toLowerCase()
      if (safeView === 'hotspot') {
        return {
          nightlightBoundaryField: 'nightlightClassKey',
          nightlightBoundaryOrder: ['core_hotspot', 'secondary_hotspot', 'emerging_hotspot'],
          nightlightBoundaryStyleMap: {
            core_hotspot: {
              strokeStyle: 'solid',
              strokeWeight: 6,
              strokeOpacity: 0.96,
              strokeColor: '#fff7bc',
              haloWeight: 9,
              haloColor: '#ffffff',
              haloOpacity: 0.96,
              zIndex: 270,
            },
            secondary_hotspot: {
              strokeStyle: 'solid',
              strokeWeight: 4.5,
              strokeOpacity: 0.94,
              strokeColor: '#fde047',
              haloWeight: 6,
              haloColor: '#fffbeb',
              haloOpacity: 0.9,
              zIndex: 269,
            },
            emerging_hotspot: {
              strokeStyle: 'solid',
              strokeWeight: 3.2,
              strokeOpacity: 0.94,
              strokeColor: '#f59e0b',
              haloWeight: 4,
              haloColor: '#fff7ed',
              haloOpacity: 0.82,
              zIndex: 268,
            },
          },
        }
      }
      if (safeView === 'gradient') {
        return {
          nightlightBoundaryField: 'nightlightClassKey',
          nightlightBoundaryOrder: ['core_peak', 'inner_spread', 'middle_decay', 'outer_decay', 'fringe_dark'],
          nightlightBoundaryStyleMap: {
            core_peak: {
              strokeStyle: 'solid',
              strokeWeight: 5.2,
              strokeOpacity: 0.96,
              strokeColor: '#fff7bc',
              haloWeight: 7,
              haloColor: '#ffffff',
              haloOpacity: 0.92,
              zIndex: 272,
            },
            inner_spread: {
              strokeStyle: 'solid',
              strokeWeight: 4.3,
              strokeOpacity: 0.94,
              strokeColor: '#fde047',
              haloWeight: 5,
              haloColor: '#fef9c3',
              haloOpacity: 0.86,
              zIndex: 271,
            },
            middle_decay: {
              strokeStyle: 'solid',
              strokeWeight: 3.5,
              strokeOpacity: 0.92,
              strokeColor: '#f59e0b',
              haloWeight: 4,
              haloColor: '#fffbeb',
              haloOpacity: 0.72,
              zIndex: 270,
            },
            outer_decay: {
              strokeStyle: 'solid',
              strokeWeight: 2.8,
              strokeOpacity: 0.9,
              strokeColor: '#c2410c',
              haloWeight: 3,
              haloColor: '#ffedd5',
              haloOpacity: 0.62,
              zIndex: 269,
            },
            fringe_dark: {
              strokeStyle: 'solid',
              strokeWeight: 2.1,
              strokeOpacity: 0.82,
              strokeColor: '#475569',
              haloWeight: 2,
              haloColor: '#cbd5e1',
              haloOpacity: 0.46,
              zIndex: 268,
            },
          },
        }
      }
      return {}
    },
    applyNightlightGridToMap() {
      if (!this.mapCore) return
      if (typeof this.mapCore.clearPopulationRasterOverlay === 'function') {
        this.mapCore.clearPopulationRasterOverlay()
      }
      const features = this.buildNightlightStyledFeatures()
      if (!features.length) {
        if (typeof this.mapCore.clearGridPolygons === 'function') {
          this.mapCore.clearGridPolygons()
        }
        return
      }
      if (typeof this.mapCore.setGridFeatures === 'function') {
        this.mapCore.setGridFeatures(features, Object.assign({
          strokeColor: '#94a3b8',
          strokeWeight: 0.8,
          fillColor: '#090b1f',
          fillOpacity: 0.28,
          clickable: false,
          webglBatch: true,
        }, this.buildNightlightBoundaryConfig()))
      }
    },
    restoreNightlightDisplayOnEnter() {
      if (!this.isNightlightDisplayActive()) return
      if (this.mapCore && typeof this.mapCore.setAnalysisBackdropMode === 'function') {
        this.mapCore.setAnalysisBackdropMode('nightlight')
      }
      this.applyNightlightGridToMap()
    },
    async ensureNightlightBaseGrid(force = false) {
      const rawRing = this.getIsochronePolygonRing()
      if (!rawRing || this.isLoadingNightlightGrid) return this.nightlightGrid
      if (this.nightlightGrid && !force) return this.nightlightGrid
      this.isLoadingNightlightGrid = true
      try {
        const polygon = this.getIsochronePolygonPayload()
        const res = await fetch('/api/v1/analysis/nightlight/grid', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            polygon,
            coord_type: 'gcj02',
            year: Number(this.nightlightSelectedYear || 0) || null,
          }),
        })
        if (!res.ok) {
          let detail = ''
          try {
            detail = await res.text()
          } catch (_) {}
          throw new Error(detail || '夜光格子生成失败')
        }
        const data = await res.json()
        this.nightlightGrid = data
        this.nightlightGridCount = Number.isFinite(Number(data.cell_count))
          ? Number(data.cell_count)
          : ((((data && data.features) || []).length))
        this.nightlightScopeId = String(data.scope_id || '')
        if (this.isNightlightDisplayActive()) {
          this.applyNightlightGridToMap()
        }
        return data
      } finally {
        this.isLoadingNightlightGrid = false
      }
    },
    async fetchNightlightOverview() {
      const polygon = this.getIsochronePolygonPayload()
      const res = await fetch('/api/v1/analysis/nightlight/overview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          polygon,
          coord_type: 'gcj02',
          year: Number(this.nightlightSelectedYear || 0) || null,
        }),
      })
      if (!res.ok) {
        let detail = ''
        try {
          detail = await res.text()
        } catch (_) {}
        throw new Error(detail || '夜光总览生成失败')
      }
      const data = await res.json()
      this.nightlightOverview = data
      this.nightlightScopeId = String(data.scope_id || this.nightlightScopeId || '')
      return data
    },
    async fetchNightlightLayer(view = this.nightlightAnalysisView) {
      const polygon = this.getIsochronePolygonPayload()
      const safeView = ['radiance', 'hotspot', 'gradient'].includes(String(view || '').trim().toLowerCase())
        ? String(view || '').trim().toLowerCase()
        : 'radiance'
      this.cancelNightlightLayerRequest()
      const requestSeq = Number(this.nightlightLayerRequestSeq || 0) + 1
      this.nightlightLayerRequestSeq = requestSeq
      const controller = typeof AbortController !== 'undefined' ? new AbortController() : null
      if (controller) {
        this.nightlightLayerAbortController = controller
      }
      try {
        const res = await fetch('/api/v1/analysis/nightlight/layer', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            polygon,
            coord_type: 'gcj02',
            year: Number(this.nightlightSelectedYear || 0) || null,
            scope_id: this.nightlightScopeId || null,
            view: safeView,
          }),
          signal: controller ? controller.signal : undefined,
        })
        if (!res.ok) {
          let detail = ''
          try {
            detail = await res.text()
          } catch (_) {}
          throw new Error(detail || '夜光图层生成失败')
        }
        const data = await res.json()
        if (requestSeq !== Number(this.nightlightLayerRequestSeq || 0)) {
          return this.nightlightLayer
        }
        this.nightlightAnalysisView = safeView
        this.nightlightLayer = data
        this.nightlightScopeId = String(data.scope_id || this.nightlightScopeId || '')
        if (this.isNightlightDisplayActive()) {
          this.applyNightlightGridToMap()
        }
        return data
      } finally {
        if (this.nightlightLayerAbortController === controller) {
          this.nightlightLayerAbortController = null
        }
      }
    },
    async fetchNightlightRaster() {
      const polygon = this.getIsochronePolygonPayload()
      const res = await fetch('/api/v1/analysis/nightlight/raster', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          polygon,
          coord_type: 'gcj02',
          year: Number(this.nightlightSelectedYear || 0) || null,
          scope_id: this.nightlightScopeId || null,
        }),
      })
      if (!res.ok) {
        let detail = ''
        try {
          detail = await res.text()
        } catch (_) {}
        throw new Error(detail || '夜光栅格预览生成失败')
      }
      const data = await res.json()
      this.nightlightRaster = data
      this.nightlightScopeId = String(data.scope_id || this.nightlightScopeId || '')
      return data
    },
    async computeNightlightAnalysis() {
      const rawRing = this.getIsochronePolygonRing()
      if (!rawRing || this.isComputingNightlight) return
      this.isComputingNightlight = true
      this.nightlightStatus = '正在计算夜光分析...'
      try {
        await this.ensureNightlightBaseGrid(false)
        await this.fetchNightlightOverview()
        this.nightlightAnalysisView = 'radiance'
        await this.fetchNightlightLayer('radiance')
        await this.fetchNightlightRaster()
        this.nightlightStatus = `夜光分析完成：${this.getNightlightSelectedYearLabel()}`
        if (this.isNightlightDisplayActive()) {
          this.applyNightlightGridToMap()
        }
        if (typeof this.persistAnalysisArtifactQuietly === 'function') {
          this.persistAnalysisArtifactQuietly('nightlight')
        }
      } catch (e) {
        console.error(e)
        this.nightlightStatus = '夜光分析失败: ' + (e && e.message ? e.message : String(e))
      } finally {
        this.isComputingNightlight = false
      }
    },
    async ensureNightlightPanelEntryState() {
      const rawRing = this.getIsochronePolygonRing()
      if (!rawRing) {
        this.nightlightStatus = ''
        this.restoreNightlightDisplayOnEnter()
        return
      }
      try {
        await this.loadNightlightMeta(false)
        await this.ensureNightlightBaseGrid(false)
      } catch (e) {
        this.nightlightStatus = '夜光格子加载失败: ' + (e && e.message ? e.message : String(e))
        this.restoreNightlightDisplayOnEnter()
        return
      }
      if (!this.nightlightOverview || !this.nightlightLayer || !this.nightlightRaster) {
        await this.computeNightlightAnalysis()
        return
      }
      this.nightlightStatus = this.nightlightStatus || `夜光分析完成：${this.getNightlightSelectedYearLabel()}`
      this.restoreNightlightDisplayOnEnter()
    },
    async onNightlightYearChange() {
      const year = Number(this.nightlightSelectedYear || 0)
      const options = this.getNightlightYearOptions()
      if (!options.some((item) => Number(item.year) === year)) {
        this.nightlightSelectedYear = Number((this.nightlightMeta && this.nightlightMeta.default_year) || 2025)
      }
      this.cancelNightlightLayerRequest()
      this.nightlightOverview = null
      this.nightlightGrid = null
      this.nightlightGridCount = 0
      this.nightlightAnalysisView = 'radiance'
      this.nightlightLayer = null
      this.nightlightRaster = null
      this.nightlightScopeId = ''
      await this.ensureNightlightPanelEntryState()
    },
    getNightlightSummaryRows() {
      const summary = (this.nightlightOverview && this.nightlightOverview.summary)
        || (this.nightlightLayer && this.nightlightLayer.summary)
        || {}
      const analysis = (this.nightlightLayer && this.nightlightLayer.analysis) || {}
      const safeView = String(this.nightlightAnalysisView || 'radiance')
      if (safeView === 'hotspot') {
        return [
          { key: 'core_hotspot_count', label: '核心热点格数', value: `${Math.round(toNumber(analysis.core_hotspot_count, 0))}` },
          { key: 'secondary_hotspot_count', label: '高亮热点格数', value: `${Math.round(toNumber(analysis.secondary_hotspot_count, 0))}` },
          { key: 'hotspot_cell_ratio', label: '热点格子占比', value: this.formatNightlightPercent(analysis.hotspot_cell_ratio) },
          { key: 'peak_radiance', label: '峰值辐亮', value: this.formatNightlightValue(analysis.peak_radiance, 2) },
        ]
      }
      if (safeView === 'gradient') {
        return [
          { key: 'peak_radiance', label: '峰值辐亮', value: this.formatNightlightValue(analysis.peak_radiance, 2) },
          { key: 'max_distance_km', label: '最大衰减半径', value: `${toNumber(analysis.max_distance_km, 0).toFixed(2)} km` },
          { key: 'core_band_count', label: '核心带格数', value: `${Math.round(toNumber(analysis.core_band_count, 0))}` },
          { key: 'peak_to_edge_ratio', label: '峰边比', value: `${toNumber(analysis.peak_to_edge_ratio, 0).toFixed(2)}x` },
        ]
      }
      return [
        { key: 'total_radiance', label: '总辐亮', value: this.formatNightlightValue(summary.total_radiance, 1) },
        { key: 'mean_radiance', label: '平均辐亮', value: this.formatNightlightValue(summary.mean_radiance, 2) },
        { key: 'p90_radiance', label: 'P90 辐亮', value: this.formatNightlightValue(summary.p90_radiance, 2) },
        { key: 'lit_pixel_ratio', label: '点亮占比', value: this.formatNightlightPercent(summary.lit_pixel_ratio) },
      ]
    },
    getNightlightLegendGradientStyle() {
      const stops = (((this.nightlightLayer && this.nightlightLayer.legend && this.nightlightLayer.legend.stops) || [])
        .map((item) => {
          const ratio = Math.max(0, Math.min(1, toNumber(item && item.ratio, 0)))
          return `${String(item && item.color || '#0f172a')} ${Math.round(ratio * 100)}%`
        }))
      return {
        background: `linear-gradient(90deg, ${stops.length ? stops.join(', ') : '#0f172a 0%, #fde047 100%'})`,
      }
    },
    getNightlightLegendNote() {
      const safeView = String(this.nightlightAnalysisView || 'radiance').trim().toLowerCase()
      if (safeView === 'hotspot') return '地图轮廓仅表示核心/高亮/次级热点带边界。'
      if (safeView === 'gradient') return '地图线表示 5 档梯度衰减分带边界。'
      return ''
    },
  }
}

export {
  createAnalysisNightlightInitialState,
  createAnalysisNightlightMethods,
}
