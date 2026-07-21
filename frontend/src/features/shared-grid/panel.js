function toNumber(value, fallback = null) {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

function clamp(value, min = 0, max = 1) {
  return Math.min(max, Math.max(min, value))
}

function interpolateColor(from, to, ratio) {
  const source = String(from || '#eff6ff').replace('#', '')
  const target = String(to || '#1d4ed8').replace('#', '')
  const t = clamp(toNumber(ratio, 0), 0, 1)
  const channel = (offset) => {
    const start = Number.parseInt(source.slice(offset, offset + 2), 16) || 0
    const end = Number.parseInt(target.slice(offset, offset + 2), 16) || 0
    return Math.round(start + ((end - start) * t)).toString(16).padStart(2, '0')
  }
  return `#${channel(0)}${channel(2)}${channel(4)}`
}

function cloneFeature(feature, properties) {
  return {
    ...feature,
    properties: {
      ...((feature && feature.properties) || {}),
      ...properties,
    },
  }
}

function formatYear(value) {
  const text = String(value ?? '').trim()
  return text ? `${text} 年` : '版本未标注'
}

export function createAnalysisSharedGridMethods() {
  return {
    isSharedGridPanelActive() {
      return this.step === 2 && this.activeStep3Panel === 'shared_grid'
    },
    isSharedGridDisplayActive() {
      return this.step === 2 && (typeof this.hasSimplifyDisplayTarget === 'function'
        ? this.hasSimplifyDisplayTarget('shared_grid')
        : this.isSharedGridPanelActive())
    },
    getSharedGridMetricOptions() {
      return [
        { value: 'density_poi_per_km2', label: 'POI 密度' },
        { value: 'population_density', label: '人口密度' },
        { value: 'nightlight_radiance', label: '夜光辐亮度' },
        { value: 'road_integration', label: '路网整合度' },
        { value: 'road_connectivity', label: '路网连通度' },
        { value: 'road_length_km_per_km2', label: '道路长度密度' },
      ]
    },
    getCurrentSharedGridSourceRows() {
      const poiCount = Array.isArray(this.allPoisDetails) ? this.allPoisDetails.length : 0
      const poiResults = Array.isArray(this.poiResultsByYear) ? this.poiResultsByYear : []
      const populationFeatures = Array.isArray(this.populationGrid && this.populationGrid.features)
        ? this.populationGrid.features
        : []
      const nightlightFeatures = Array.isArray(this.nightlightGrid && this.nightlightGrid.features)
        ? this.nightlightGrid.features
        : []
      const roadFeatures = Array.isArray(this.roadSyntaxRoadFeatures) ? this.roadSyntaxRoadFeatures : []
      return [
        {
          key: 'poi', label: 'POI', ready: poiCount > 0 || poiResults.length > 0,
          year: this.resultPoiYear || this.poiYearSource, recordCount: poiCount,
          missing: '未完成当前范围的 POI 查询（POI 为 0 条时也需完成一次查询）',
        },
        {
          key: 'population', label: '人口', ready: populationFeatures.length > 0,
          year: typeof this.getPopulationSelectedYear === 'function' ? this.getPopulationSelectedYear() : this.populationSelectedYear,
          recordCount: populationFeatures.length, missing: '未加载人口格网',
        },
        {
          key: 'nightlight', label: '夜光', ready: nightlightFeatures.length > 0,
          year: this.nightlightSelectedYear, recordCount: nightlightFeatures.length, missing: '未加载夜光格网',
        },
        {
          key: 'road', label: '路网', ready: !!this.roadSyntaxSummary || roadFeatures.length > 0,
          year: null, recordCount: roadFeatures.length, missing: '未完成路网分析',
        },
      ]
    },
    getSharedGridSourceRows() {
      const sourceReadiness = this.sharedGridSourceReadiness && typeof this.sharedGridSourceReadiness === 'object'
        ? this.sharedGridSourceReadiness
        : {}
      const sourceVersions = this.sharedGridSourceVersions && typeof this.sharedGridSourceVersions === 'object'
        ? this.sharedGridSourceVersions
        : {}
      return this.getCurrentSharedGridSourceRows().map((current) => {
        const stored = (sourceReadiness[current.key] && typeof sourceReadiness[current.key] === 'object')
          ? sourceReadiness[current.key]
          : ((sourceVersions[current.key] && typeof sourceVersions[current.key] === 'object') ? sourceVersions[current.key] : null)
        const hasStoredReadiness = !!stored && Object.prototype.hasOwnProperty.call(stored, 'ready')
        const ready = hasStoredReadiness ? !!stored.ready : current.ready
        const year = stored && stored.year !== undefined && stored.year !== null ? stored.year : current.year
        const count = stored && Number.isFinite(Number(stored.record_count)) ? Number(stored.record_count) : current.recordCount
        const reason = stored && String(stored.reason || '').trim() ? String(stored.reason).trim() : current.missing
        return {
          key: current.key,
          label: current.label,
          ready,
          detail: ready
            ? `${formatYear(year)} · ${count} ${current.key === 'road' ? '条线' : '格/条'}${hasStoredReadiness ? ' · 已参与已恢复网格' : ''}`
            : reason,
        }
      })
    },
    isSharedGridReadyToGenerate() {
      return this.getCurrentSharedGridSourceRows().every((row) => row.ready)
    },
    getSharedGridBlockingText() {
      const missing = this.getCurrentSharedGridSourceRows().filter((row) => !row.ready).map((row) => row.label)
      return missing.length ? `请先准备：${missing.join('、')}` : ''
    },
    formatSharedGridValue(value, digits = 2) {
      const number = toNumber(value, null)
      if (number === null) return '—'
      const precision = Math.max(0, Math.min(4, Number(digits) || 0))
      return number.toLocaleString('zh-CN', { maximumFractionDigits: precision })
    },
    getSharedGridFeatures() {
      return Array.isArray(this.sharedGrid && this.sharedGrid.features) ? this.sharedGrid.features : []
    },
    getSharedGridSelectedFeature() {
      const target = String(this.sharedGridSelectedCellId || '').trim()
      const features = this.getSharedGridFeatures()
      return features.find((feature) => String((feature && feature.properties && feature.properties.cell_id) || '') === target) || features[0] || null
    },
    setSharedGridMetric(metric) {
      const allowed = this.getSharedGridMetricOptions().map((item) => item.value)
      this.sharedGridMetric = allowed.includes(String(metric || '')) ? String(metric) : 'density_poi_per_km2'
      if (this.isSharedGridDisplayActive()) this.applySharedGridToMap()
    },
    buildSharedGridStyledFeatures() {
      const metric = String(this.sharedGridMetric || 'density_poi_per_km2')
      const features = this.getSharedGridFeatures()
      const values = features
        .map((feature) => toNumber(feature && feature.properties && feature.properties[metric], null))
        .filter((value) => value !== null)
      const min = values.length ? Math.min(...values) : 0
      const max = values.length ? Math.max(...values) : min
      const span = max - min
      return features.map((feature) => {
        const value = toNumber(feature && feature.properties && feature.properties[metric], null)
        const ratio = value === null ? 0 : (span > 0 ? clamp((value - min) / span) : 0.55)
        return cloneFeature(feature, {
          fillColor: value === null ? '#e5e7eb' : interpolateColor('#dbeafe', '#1d4ed8', ratio),
          fillOpacity: value === null ? 0.16 : 0.28 + (ratio * 0.46),
          strokeColor: value === null ? '#9ca3af' : '#2563eb',
          strokeWeight: 1.05,
        })
      })
    },
    applySharedGridToMap() {
      if (!this.isSharedGridDisplayActive()) return
      const features = this.buildSharedGridStyledFeatures()
      if (!features.length || !this.mapCore || typeof this.mapCore.setGridFeatures !== 'function') return
      if (typeof this.mapCore.setAnalysisBackdropMode === 'function') this.mapCore.setAnalysisBackdropMode('')
      this.mapCore.setGridFeatures(features, {
        strokeColor: '#2563eb', strokeWeight: 1.05, fillOpacity: 0.52, webglBatch: true,
      })
    },
    clearSharedGridDisplayOnLeave() {
      if (this.mapCore && typeof this.mapCore.clearGridPolygons === 'function') this.mapCore.clearGridPolygons()
    },
    ensureSharedGridPanelEntryState() {
      if (this.sharedGrid) this.applySharedGridToMap()
      if (!this.sharedGrid && !this.sharedGridStatus) this.sharedGridStatus = this.getSharedGridBlockingText() || '四类来源均已就绪，可手动生成共享网格'
    },
    buildSharedGridRequestPayload() {
      return {
        polygon: typeof this.getIsochronePolygonPayload === 'function' ? this.getIsochronePolygonPayload() : [],
        coord_type: 'gcj02',
        pois: Array.isArray(this.allPoisDetails) ? this.allPoisDetails : [],
        poi_coord_type: 'gcj02',
        poi_year: toNumber(this.resultPoiYear || this.poiYearSource, null),
        poi_ready: this.getCurrentSharedGridSourceRows().find((row) => row.key === 'poi').ready,
        population_year: String(typeof this.getPopulationSelectedYear === 'function' ? this.getPopulationSelectedYear() : this.populationSelectedYear || ''),
        nightlight_year: toNumber(this.nightlightSelectedYear, 0),
        road_features: Array.isArray(this.roadSyntaxRoadFeatures) ? this.roadSyntaxRoadFeatures : [],
        road_ready: !!this.getCurrentSharedGridSourceRows().find((row) => row.key === 'road').ready,
        categories: typeof this.buildSelectedCategoryBuckets === 'function' ? this.buildSelectedCategoryBuckets() : [],
      }
    },
    async generateSharedGrid() {
      const blocking = this.getSharedGridBlockingText()
      if (blocking || this.isGeneratingSharedGrid) {
        this.sharedGridStatus = blocking
        return false
      }
      this.isGeneratingSharedGrid = true
      this.sharedGridStatus = '正在按人口格网 cell_id 汇总 POI、人口、夜光与路网…'
      try {
        const response = await fetch('/api/v1/analysis/shared-grid', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(this.buildSharedGridRequestPayload()),
        })
        if (!response.ok) {
          let detail = ''
          try { detail = await response.text() } catch (_) {}
          throw new Error(detail || `共享网格请求失败 (${response.status})`)
        }
        const data = await response.json()
        this.sharedGrid = data.grid || null
        this.sharedGridSummary = data.summary || {}
        this.sharedGridSourceVersions = data.source_versions || {}
        this.sharedGridSourceReadiness = data.source_readiness || {}
        this.sharedGridLimitations = Array.isArray(data.limitations) ? data.limitations : []
        const first = this.getSharedGridFeatures()[0]
        this.sharedGridSelectedCellId = String((first && first.properties && first.properties.cell_id) || '')
        this.sharedGridStatus = `共享网格已生成：${this.getSharedGridFeatures().length} 个格网`
        this.applySharedGridToMap()
        if (typeof this.persistAnalysisArtifact === 'function') {
          try {
            const saved = await this.persistAnalysisArtifact('shared_grid')
            if (!saved) throw new Error('artifact 保存失败')
          } catch (error) {
            this.sharedGridStatus += '；计算完成但保存失败'
            console.warn('[shared-grid] artifact save failed', error)
          }
        }
        return true
      } catch (error) {
        this.sharedGridStatus = `共享网格生成失败：${error && error.message ? error.message : String(error)}`
        return false
      } finally {
        this.isGeneratingSharedGrid = false
      }
    },
    restoreHistorySharedGridArtifact(artifact, token) {
      if (!artifact || token !== this.historyDetailLoadToken) return false
      const payload = artifact.payload && typeof artifact.payload === 'object' ? artifact.payload : {}
      const grid = payload.grid && typeof payload.grid === 'object' ? payload.grid : null
      if (!grid || !Array.isArray(grid.features)) return false
      this.sharedGrid = grid
      this.sharedGridSummary = payload.summary && typeof payload.summary === 'object' ? payload.summary : (artifact.summary || {})
      this.sharedGridSourceVersions = payload.source_versions && typeof payload.source_versions === 'object' ? payload.source_versions : {}
      this.sharedGridSourceReadiness = payload.source_readiness && typeof payload.source_readiness === 'object' ? payload.source_readiness : this.sharedGridSourceVersions
      this.sharedGridLimitations = Array.isArray(payload.limitations) ? payload.limitations : []
      const first = grid.features[0]
      this.sharedGridSelectedCellId = String((first && first.properties && first.properties.cell_id) || '')
      this.sharedGridStatus = `已恢复共享网格：${grid.features.length} 个格网`
      if (this.isSharedGridDisplayActive()) this.applySharedGridToMap()
      return true
    },
  }
}