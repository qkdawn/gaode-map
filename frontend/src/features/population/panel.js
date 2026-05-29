function createPopulationFallbackMeta() {
  return {
    sex_options: [
      { value: 'total', label: '总人口' },
      { value: 'male', label: '男性' },
      { value: 'female', label: '女性' },
    ],
    age_band_options: [
      { value: 'all', label: '全年龄' },
      { value: '00', label: '0岁' },
      { value: '01', label: '1-4岁' },
      { value: '05', label: '5-9岁' },
      { value: '10', label: '10-14岁' },
      { value: '15', label: '15-19岁' },
      { value: '20', label: '20-24岁' },
      { value: '25', label: '25-29岁' },
      { value: '30', label: '30-34岁' },
      { value: '35', label: '35-39岁' },
      { value: '40', label: '40-44岁' },
      { value: '45', label: '45-49岁' },
      { value: '50', label: '50-54岁' },
      { value: '55', label: '55-59岁' },
      { value: '60', label: '60-64岁' },
      { value: '65', label: '65-69岁' },
      { value: '70', label: '70-74岁' },
      { value: '75', label: '75-79岁' },
      { value: '80', label: '80-84岁' },
      { value: '85', label: '85-89岁' },
      { value: '90', label: '90岁及以上' },
    ],
    default_sex: 'total',
    default_age_band: 'all',
    default_year: '2026',
    year_options: ['2024', '2025', '2026'],
  }
}

function toNumber(value, fallback = 0) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

const SEX_STRUCTURE_METRIC_MODES = ['ratio', 'diff']
const SEX_DENSITY_TO_POPULATION_SCALE = 0.01
const SEX_COLOR_NEUTRAL = '#f3f4f6'
const SEX_COLOR_MALE = '#1d4ed8'
const SEX_COLOR_FEMALE = '#ec4899'

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value))
}

function quantile(values, p) {
  const list = (Array.isArray(values) ? values : [])
    .map((item) => Number(item))
    .filter((item) => Number.isFinite(item))
    .sort((left, right) => left - right)
  if (!list.length) return 0
  const index = clamp((list.length - 1) * clamp(p, 0, 1), 0, list.length - 1)
  const lower = Math.floor(index)
  const upper = Math.ceil(index)
  if (lower === upper) return list[lower]
  const weight = index - lower
  return list[lower] + (list[upper] - list[lower]) * weight
}

function parseHexColor(hex) {
  const safe = String(hex || '').replace('#', '').trim()
  if (safe.length !== 6) return { r: 0, g: 0, b: 0 }
  const r = Number.parseInt(safe.slice(0, 2), 16)
  const g = Number.parseInt(safe.slice(2, 4), 16)
  const b = Number.parseInt(safe.slice(4, 6), 16)
  return {
    r: Number.isFinite(r) ? r : 0,
    g: Number.isFinite(g) ? g : 0,
    b: Number.isFinite(b) ? b : 0,
  }
}

function formatHexColor({ r, g, b }) {
  const toHex = (value) => clamp(Math.round(toNumber(value, 0)), 0, 255).toString(16).padStart(2, '0')
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`
}

function mixHexColor(fromHex, toHex, ratio) {
  const from = parseHexColor(fromHex)
  const to = parseHexColor(toHex)
  const t = clamp(toNumber(ratio, 0), 0, 1)
  return formatHexColor({
    r: from.r + ((to.r - from.r) * t),
    g: from.g + ((to.g - from.g) * t),
    b: from.b + ((to.b - from.b) * t),
  })
}

function createPopulationSexSourceLayers() {
  return {
    scope_id: '',
    male: null,
    female: null,
  }
}

function createAnalysisPopulationInitialState() {
  const meta = createPopulationFallbackMeta()
  return {
    isComputingPopulation: false,
    isLoadingPopulationMeta: false,
    isLoadingPopulationGrid: false,
    populationStatus: '',
    populationScopeId: '',
    populationOverview: null,
    populationGrid: null,
    populationGridCount: 0,
    populationLayer: null,
    populationSubTab: 'analysis',
    populationAnalysisView: 'density',
    populationSexMetricMode: 'ratio',
    populationSexSourceLayers: createPopulationSexSourceLayers(),
    populationAgeMode: 'dominant',
    populationAgeBand: 'all',
    populationMeta: meta,
    populationMetaLoaded: false,
    populationSelectedYear: String(meta.default_year || '2026'),
    populationPrimaryChart: null,
    populationSecondaryChart: null,
    populationChartsResizeHandler: null,
  }
}

function createAnalysisPopulationMethods() {
  return {
    createPopulationFallbackMeta,
    isPopulationPanelActive() {
      return this.step === 2 && this.activeStep3Panel === 'population'
    },
    isPopulationDisplayActive() {
      return this.step === 2
        && (typeof this.hasSimplifyDisplayTarget === 'function'
          ? this.hasSimplifyDisplayTarget('population')
          : this.isPopulationPanelActive())
    },
    setPopulationAnalysisView(view) {
      const nextView = ['density', 'sex', 'age'].includes(String(view || '').trim().toLowerCase())
        ? String(view || '').trim().toLowerCase()
        : 'density'
      if (nextView === 'age') {
        this.populationAgeMode = 'dominant'
        this.populationAgeBand = 'all'
      }
      if (this.populationAnalysisView === nextView && this.populationLayer) {
        this.$nextTick(() => {
          this.updatePopulationCharts()
        })
        return
      }
      this.populationAnalysisView = nextView
      if (!this.populationOverview) return
      this.fetchPopulationLayer(nextView).catch((err) => {
        console.error(err)
        this.populationStatus = '人口图层切换失败: ' + (err && err.message ? err.message : String(err))
      })
    },
    getPopulationYearOptions() {
      const options = Array.isArray(this.populationMeta && this.populationMeta.year_options)
        ? this.populationMeta.year_options
        : []
      return options
        .map((item) => String(item || '').trim())
        .filter((item) => item.length > 0)
        .map((year) => ({ value: year, label: `${year} 年` }))
    },
    getPopulationSelectedYear() {
      const selected = String(this.populationSelectedYear || '').trim()
      const options = this.getPopulationYearOptions()
      if (options.some((item) => item.value === selected)) return selected
      return String((this.populationMeta && this.populationMeta.default_year) || '2026')
    },
    getPopulationSelectedYearLabel() {
      const year = this.getPopulationSelectedYear()
      const option = this.getPopulationYearOptions().find((item) => item.value === year)
      return String((option && option.label) || (year ? `${year} 年` : '-'))
    },
    async loadPopulationMeta(force = false) {
      if ((this.populationMetaLoaded && !force) || this.isLoadingPopulationMeta) return this.populationMeta
      this.isLoadingPopulationMeta = true
      try {
        const res = await fetch('/api/v1/analysis/population/meta')
        if (!res.ok) {
          throw new Error(`/api/v1/analysis/population/meta 请求失败(${res.status})`)
        }
        const data = await res.json()
        const meta = {
          sex_options: Array.isArray(data.sex_options) ? data.sex_options : createPopulationFallbackMeta().sex_options,
          age_band_options: Array.isArray(data.age_band_options) ? data.age_band_options : createPopulationFallbackMeta().age_band_options,
          default_sex: String(data.default_sex || 'total'),
          default_age_band: String(data.default_age_band || 'all'),
          default_year: String(data.default_year || '2026'),
          year_options: Array.isArray(data.year_options)
            ? data.year_options.map((item) => String(item || '').trim()).filter((item) => item.length > 0)
            : createPopulationFallbackMeta().year_options,
        }
        this.populationMeta = meta
        this.populationAgeBand = 'all'
        this.populationMetaLoaded = true
        if (!this.getPopulationYearOptions().some((item) => item.value === String(this.populationSelectedYear || '').trim())) {
          this.populationSelectedYear = String(meta.default_year || '2026')
        }
        return meta
      } catch (e) {
        console.error(e)
        this.populationMeta = createPopulationFallbackMeta()
        this.populationAgeBand = 'all'
        this.populationMetaLoaded = false
        this.populationSelectedYear = String(this.populationMeta.default_year || '2026')
        throw e
      } finally {
        this.isLoadingPopulationMeta = false
      }
    },
    formatPopulationValue(value) {
      const num = toNumber(value, 0)
      if (num >= 100000000) return `${(num / 100000000).toFixed(2)}亿`
      if (num >= 10000) return `${(num / 10000).toFixed(1)}万`
      return `${Math.round(num)}`
    },
    formatPopulationPercent(value) {
      return `${(toNumber(value, 0) * 100).toFixed(1)}%`
    },
    formatPopulationLegendPercent(value) {
      const num = toNumber(value, 0)
      const legend = (this.populationLayer && this.populationLayer.legend) || {}
      const span = Math.abs(toNumber(legend.max_value, 0) - toNumber(legend.min_value, 0))
      const digits = span < 0.1 ? 3 : (span < 1 ? 2 : 1)
      return `${num.toFixed(digits)}%`
    },
    formatPopulationDensity(value) {
      const num = toNumber(value, 0)
      if (num >= 100000) return `${(num / 10000).toFixed(1)}万`
      return `${Math.round(num)}`
    },
    formatPopulationSignedValue(value) {
      const num = toNumber(value, 0)
      if (Math.abs(num) < 1e-9) return '0'
      const prefix = num > 0 ? '+' : '-'
      return `${prefix}${this.formatPopulationValue(Math.abs(num))}`
    },
    normalizePopulationSexMetricMode(mode) {
      const normalized = String(mode || '').trim().toLowerCase()
      return SEX_STRUCTURE_METRIC_MODES.includes(normalized) ? normalized : 'ratio'
    },
    getPopulationSexMetricLabel(mode = this.populationSexMetricMode) {
      const safeMode = this.normalizePopulationSexMetricMode(mode)
      if (safeMode === 'diff') return '性别差异（男-女，人口）'
      return '男性占比（%）'
    },
    getPopulationSexMetricUnit(mode = this.populationSexMetricMode) {
      const safeMode = this.normalizePopulationSexMetricMode(mode)
      if (safeMode === 'diff') return '人'
      return '%'
    },
    isValidPopulationSexSourceCache(scopeId = this.populationScopeId) {
      const cache = this.populationSexSourceLayers || {}
      if (!cache || !cache.male || !cache.female) return false
      const cacheScopeId = String(cache.scope_id || '')
      const currentScopeId = String(scopeId || '')
      if (!cacheScopeId) return false
      if (!currentScopeId) return true
      return cacheScopeId === currentScopeId
    },
    getPopulationLayerCellValueMap(layer) {
      const cellMap = new Map()
      ;(((layer && layer.cells) || [])).forEach((cell) => {
        const cellId = String(cell && cell.cell_id ? cell.cell_id : '')
        if (!cellId) return
        const value = toNumber(cell && cell.value, 0)
        cellMap.set(cellId, value)
      })
      return cellMap
    },
    async requestPopulationLayer({ view, sexMode = 'male', ageMode = 'ratio', ageBand = 'all' }) {
      const rawRing = this.getIsochronePolygonRing()
      if (!rawRing) return null
      const polygon = this.getIsochronePolygonPayload()
      const year = this.getPopulationSelectedYear()
      const res = await fetch('/api/v1/analysis/population/layer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          polygon,
          coord_type: 'gcj02',
          year,
          scope_id: this.populationScopeId || null,
          view,
          sex_mode: sexMode,
          age_mode: ageMode,
          age_band: ageBand,
        }),
      })
      if (!res.ok) {
        let detail = ''
        try {
          detail = await res.text()
        } catch (_) {}
        throw new Error(detail || '人口图层生成失败')
      }
      return res.json()
    },
    async fetchPopulationSexSourceLayers(force = false) {
      if (!force && this.isValidPopulationSexSourceCache(this.populationScopeId)) {
        return this.populationSexSourceLayers
      }
      const [maleLayer, femaleLayer] = await Promise.all([
        this.requestPopulationLayer({ view: 'sex', sexMode: 'male', ageMode: 'ratio', ageBand: 'all' }),
        this.requestPopulationLayer({ view: 'sex', sexMode: 'female', ageMode: 'ratio', ageBand: 'all' }),
      ])
      const resolvedScopeId = String(
        (maleLayer && maleLayer.scope_id)
        || (femaleLayer && femaleLayer.scope_id)
        || this.populationScopeId
        || ''
      )
      this.populationScopeId = resolvedScopeId
      this.populationSexSourceLayers = {
        scope_id: resolvedScopeId,
        male: maleLayer || null,
        female: femaleLayer || null,
      }
      return this.populationSexSourceLayers
    },
    resolvePopulationSexMetricCell(mode, maleDensity, femaleDensity) {
      const safeMode = this.normalizePopulationSexMetricMode(mode)
      const male = Math.max(0, toNumber(maleDensity, 0))
      const female = Math.max(0, toNumber(femaleDensity, 0))
      if (safeMode === 'diff') {
        return { value: (male - female) * SEX_DENSITY_TO_POPULATION_SCALE, valid: true }
      }
      const total = male + female
      if (total <= 0) return { value: 0, valid: false }
      return { value: (male / total) * 100, valid: true }
    },
    resolvePopulationSexMetricScale(mode, values) {
      const safeMode = this.normalizePopulationSexMetricMode(mode)
      if (safeMode === 'ratio') {
        return { min: 0, max: 100, center: 50 }
      }
      if (!values.length) {
        return { min: -1, max: 1, center: 0 }
      }
      let minValue = quantile(values, 0.02)
      let maxValue = quantile(values, 0.98)
      minValue = Math.min(minValue, 0)
      maxValue = Math.max(maxValue, 0)
      if (!(maxValue > minValue)) {
        maxValue = minValue + 1
      }
      return {
        min: minValue,
        max: maxValue,
        center: 0,
      }
    },
    resolvePopulationSexMetricStyle(mode, value, valid, scale) {
      if (!valid || !Number.isFinite(value)) {
        return {
          color: '#f4f5f7',
          opacity: 0.12,
          stroke: '#d7dde7',
          displayValue: 0,
        }
      }
      const safeMode = this.normalizePopulationSexMetricMode(mode)
      const minValue = toNumber(scale && scale.min, 0)
      const maxValue = toNumber(scale && scale.max, 1)
      const centerValue = toNumber(scale && scale.center, safeMode === 'ratio' ? 50 : 0)
      const clamped = clamp(toNumber(value, 0), minValue, maxValue)
      let intensity = 0
      let color = SEX_COLOR_NEUTRAL
      if (safeMode === 'ratio') {
        if (clamped >= centerValue) {
          const span = Math.max(maxValue - centerValue, 1e-9)
          intensity = clamp((clamped - centerValue) / span, 0, 1)
          color = mixHexColor(SEX_COLOR_NEUTRAL, SEX_COLOR_MALE, intensity)
        } else {
          const span = Math.max(centerValue - minValue, 1e-9)
          intensity = clamp((centerValue - clamped) / span, 0, 1)
          color = mixHexColor(SEX_COLOR_NEUTRAL, SEX_COLOR_FEMALE, intensity)
        }
      } else {
        if (clamped >= centerValue) {
          const span = Math.max(maxValue - centerValue, 1e-9)
          intensity = clamp((clamped - centerValue) / span, 0, 1)
          color = mixHexColor(SEX_COLOR_NEUTRAL, SEX_COLOR_MALE, intensity)
        } else {
          const span = Math.max(centerValue - minValue, 1e-9)
          intensity = clamp((centerValue - clamped) / span, 0, 1)
          color = mixHexColor(SEX_COLOR_NEUTRAL, SEX_COLOR_FEMALE, intensity)
        }
      }
      return {
        color,
        opacity: 0.24 + (0.48 * intensity),
        stroke: '#ffffff',
        displayValue: clamped,
      }
    },
    buildPopulationSexLegend(mode, scale) {
      const safeMode = this.normalizePopulationSexMetricMode(mode)
      const title = this.getPopulationSexMetricLabel(safeMode)
      const unit = this.getPopulationSexMetricUnit(safeMode)
      const minValue = toNumber(scale && scale.min, 0)
      const maxValue = toNumber(scale && scale.max, 1)
      const center = toNumber(scale && scale.center, safeMode === 'ratio' ? 50 : 0)
      let stopValues = []
      if (safeMode === 'ratio') {
        stopValues = [0, 25, 50, 75, 100]
      } else {
        stopValues = [minValue, minValue / 2, 0, maxValue / 2, maxValue]
      }
      const uniqueValues = Array.from(new Set(stopValues.map((item) => Number(item).toFixed(6))))
        .map((item) => Number(item))
        .sort((left, right) => left - right)
      const span = Math.max(maxValue - minValue, 1e-9)
      const stops = uniqueValues.map((value) => {
        const style = this.resolvePopulationSexMetricStyle(safeMode, value, true, { min: minValue, max: maxValue, center })
        let label = ''
        if (safeMode === 'ratio') {
          label = `${value.toFixed(0)}%`
        } else if (safeMode === 'diff') {
          label = `${value >= 0 ? '+' : '-'}${this.formatPopulationValue(Math.abs(value))}人`
        }
        return {
          ratio: clamp((value - minValue) / span, 0, 1),
          color: style.color,
          value,
          label,
        }
      })
      return {
        title,
        kind: 'continuous',
        unit,
        min_value: minValue,
        max_value: maxValue,
        stops,
      }
    },
    buildPopulationSexStructureLayer(metricMode, maleLayer, femaleLayer) {
      const safeMode = this.normalizePopulationSexMetricMode(metricMode)
      const maleSummary = (maleLayer && maleLayer.summary) || {}
      const femaleSummary = (femaleLayer && femaleLayer.summary) || {}
      const gridFeatures = (((this.populationGrid && this.populationGrid.features) || []))
      const maleMap = this.getPopulationLayerCellValueMap(maleLayer)
      const femaleMap = this.getPopulationLayerCellValueMap(femaleLayer)
      const idSet = new Set()
      gridFeatures.forEach((feature) => {
        const props = (feature && feature.properties) || {}
        const cellId = String(props.cell_id || '')
        if (cellId) idSet.add(cellId)
      })
      maleMap.forEach((_, key) => idSet.add(String(key)))
      femaleMap.forEach((_, key) => idSet.add(String(key)))
      const rows = Array.from(idSet).map((cellId) => {
        const maleDensity = toNumber(maleMap.get(cellId), 0)
        const femaleDensity = toNumber(femaleMap.get(cellId), 0)
        const metric = this.resolvePopulationSexMetricCell(safeMode, maleDensity, femaleDensity)
        return {
          cell_id: cellId,
          male_density: maleDensity,
          female_density: femaleDensity,
          value: metric.value,
          valid: metric.valid,
        }
      })
      const validValues = rows
        .filter((row) => row.valid && Number.isFinite(row.value))
        .map((row) => toNumber(row.value, 0))
      const scale = this.resolvePopulationSexMetricScale(safeMode, validValues)
      const valueLabel = this.getPopulationSexMetricLabel(safeMode)
      const cells = rows.map((row) => {
        const style = this.resolvePopulationSexMetricStyle(safeMode, row.value, row.valid, scale)
        let textValue = '-'
        if (row.valid && Number.isFinite(row.value)) {
          if (safeMode === 'ratio') {
            textValue = `${toNumber(row.value, 0).toFixed(1)}%`
          } else if (safeMode === 'diff') {
            const num = toNumber(row.value, 0)
            textValue = `${num >= 0 ? '+' : ''}${this.formatPopulationValue(Math.abs(num))}人`
          } else {
            textValue = toNumber(row.value, 0).toFixed(1)
          }
        }
        return {
          cell_id: row.cell_id,
          value: row.valid && Number.isFinite(row.value) ? toNumber(row.value, 0) : 0,
          fill_color: style.color,
          stroke_color: style.stroke,
          fill_opacity: Number(style.opacity.toFixed(3)),
          label: `${valueLabel} ${textValue}`,
        }
      })
      const maleTotal = toNumber(maleSummary.selected_population, toNumber((this.populationOverview && this.populationOverview.summary && this.populationOverview.summary.male_total), 0))
      const femaleTotal = toNumber(femaleSummary.selected_population, toNumber((this.populationOverview && this.populationOverview.summary && this.populationOverview.summary.female_total), 0))
      const totalPopulation = maleTotal + femaleTotal
      const diffValue = maleTotal - femaleTotal
      return {
        scope_id: String(
          (maleLayer && maleLayer.scope_id)
          || (femaleLayer && femaleLayer.scope_id)
          || this.populationScopeId
          || ''
        ),
        selected: {
          view: 'sex',
          view_label: valueLabel,
          sex_mode: safeMode,
          sex_mode_label: this.getPopulationSexMetricLabel(safeMode),
          age_mode: null,
          age_mode_label: null,
          age_band: 'all',
          age_band_label: '全年龄',
          unit: this.getPopulationSexMetricUnit(safeMode),
        },
        summary: {
          male_total: Number(maleTotal.toFixed(3)),
          female_total: Number(femaleTotal.toFixed(3)),
          male_ratio: totalPopulation > 0 ? Number((maleTotal / totalPopulation).toFixed(6)) : 0,
          female_ratio: totalPopulation > 0 ? Number((femaleTotal / totalPopulation).toFixed(6)) : 0,
          sex_diff_total: Number(diffValue.toFixed(3)),
          nonzero_cell_count: rows.filter((row) => row.valid && Math.abs(toNumber(row.value, 0)) > 1e-9).length,
          sex_metric_mode: safeMode,
          sex_metric_label: this.getPopulationSexMetricLabel(safeMode),
        },
        legend: this.buildPopulationSexLegend(safeMode, scale),
        cells,
      }
    },
    async fetchPopulationSexStructureLayer(force = false) {
      const sources = await this.fetchPopulationSexSourceLayers(force)
      return this.buildPopulationSexStructureLayer(
        this.populationSexMetricMode,
        sources && sources.male,
        sources && sources.female,
      )
    },
    getPopulationGridFeatureMap() {
      const featureMap = new Map()
      ;(((this.populationGrid && this.populationGrid.features) || [])).forEach((feature) => {
        const props = (feature && feature.properties) || {}
        const cellId = String(props.cell_id || '')
        if (cellId) featureMap.set(cellId, props)
      })
      return featureMap
    },
    getPopulationTopCells(limit = 10) {
      const featureMap = this.getPopulationGridFeatureMap()
      return (((this.populationLayer && this.populationLayer.cells) || [])
        .slice()
        .sort((left, right) => toNumber(right && right.value, 0) - toNumber(left && left.value, 0))
        .slice(0, Math.max(1, Number(limit) || 10))
        .map((cell) => {
          const meta = featureMap.get(String(cell.cell_id || '')) || {}
          const row = Number.isFinite(Number(meta.row)) ? Number(meta.row) + 1 : '-'
          const col = Number.isFinite(Number(meta.col)) ? Number(meta.col) + 1 : '-'
          return {
            label: `R${row} C${col}`,
            value: toNumber(cell && cell.value, 0),
          }
        }))
    },
    disposePopulationCharts() {
      if (this.populationPrimaryChart) {
        this.populationPrimaryChart.dispose()
        this.populationPrimaryChart = null
      }
      if (this.populationSecondaryChart) {
        this.populationSecondaryChart.dispose()
        this.populationSecondaryChart = null
      }
      if (this.populationChartsResizeHandler) {
        window.removeEventListener('resize', this.populationChartsResizeHandler)
        this.populationChartsResizeHandler = null
      }
    },
    ensurePopulationChartResizeHandler() {
      if (this.populationChartsResizeHandler) return
      this.populationChartsResizeHandler = () => {
        if (this.populationPrimaryChart) this.populationPrimaryChart.resize()
        if (this.populationSecondaryChart) this.populationSecondaryChart.resize()
      }
      window.addEventListener('resize', this.populationChartsResizeHandler)
    },
    getPopulationChartInstances() {
      if (!window.echarts) return {}
      const primaryEl = document.getElementById('populationPrimaryChart')
      const secondaryEl = document.getElementById('populationSecondaryChart')
      if (!primaryEl) return {}
      if (primaryEl.clientWidth === 0) return {}
      this.ensurePopulationChartResizeHandler()
      let primaryChart = echarts.getInstanceByDom(primaryEl)
      if (!primaryChart) primaryChart = echarts.init(primaryEl)
      let secondaryChart = null
      if (secondaryEl && secondaryEl.clientWidth > 0) {
        secondaryChart = echarts.getInstanceByDom(secondaryEl)
        if (!secondaryChart) secondaryChart = echarts.init(secondaryEl)
      } else if (this.populationSecondaryChart) {
        this.populationSecondaryChart.dispose()
        this.populationSecondaryChart = null
      }
      this.populationPrimaryChart = primaryChart
      this.populationSecondaryChart = secondaryChart
      return { primaryChart, secondaryChart }
    },
    updatePopulationCharts() {
      if (!this.populationOverview || this.populationSubTab !== 'analysis') return
      const charts = this.getPopulationChartInstances()
      if (!charts.primaryChart) return
      const { primaryChart, secondaryChart } = charts
      const view = String(this.populationAnalysisView || 'density')
      if (view === 'sex') {
        if (!secondaryChart) return
        this.renderPopulationSexCharts(primaryChart, secondaryChart)
        return
      }
      if (view === 'age') {
        this.renderPopulationAgeCharts(primaryChart)
        return
      }
      if (!secondaryChart) return
      this.renderPopulationDensityCharts(primaryChart, secondaryChart)
    },
    renderPopulationDensityCharts(primaryChart, secondaryChart) {
      const values = (((this.populationLayer && this.populationLayer.cells) || [])
        .map((cell) => toNumber(cell && cell.value, 0))
        .filter((value) => value > 0))
      const histogramBins = 6
      const minValue = values.length ? Math.min(...values) : 0
      const maxValue = values.length ? Math.max(...values) : 0
      const span = Math.max(maxValue - minValue, 1)
      const bucketSize = span / histogramBins
      const histogram = Array.from({ length: histogramBins }, (_, index) => {
        const start = minValue + (bucketSize * index)
        const end = index === histogramBins - 1 ? maxValue : start + bucketSize
        const count = values.filter((value) => (
          index === histogramBins - 1
            ? value >= start && value <= end
            : value >= start && value < end
        )).length
        return {
          label: `${this.formatPopulationDensity(start)}-${this.formatPopulationDensity(end)}`,
          count,
        }
      })
      primaryChart.setOption({
        animationDuration: 240,
        title: { text: '密度分布', left: 0, top: 0, textStyle: { fontSize: 13, fontWeight: 600 } },
        tooltip: { trigger: 'axis' },
        grid: { left: 44, right: 12, top: 42, bottom: 36, containLabel: true },
        xAxis: {
          type: 'category',
          data: histogram.map((item) => item.label),
          axisLabel: { interval: 0, rotate: histogram.length > 4 ? 24 : 0, fontSize: 10, color: '#6b7280' },
          axisLine: { lineStyle: { color: '#d7dce3' } },
        },
        yAxis: {
          type: 'value',
          axisLine: { show: false },
          axisTick: { show: false },
          splitLine: { lineStyle: { color: '#eceff3' } },
          axisLabel: { color: '#6b7280' },
        },
        series: [{
          type: 'bar',
          data: histogram.map((item) => item.count),
          barMaxWidth: 24,
          itemStyle: { color: '#fb923c' },
        }],
      }, true)

      const topCells = this.getPopulationTopCells(10).reverse()
      secondaryChart.setOption({
        animationDuration: 240,
        title: { text: '高值格子排行', left: 0, top: 0, textStyle: { fontSize: 13, fontWeight: 600 } },
        tooltip: { trigger: 'axis' },
        grid: { left: 54, right: 12, top: 42, bottom: 18, containLabel: true },
        xAxis: {
          type: 'value',
          axisLine: { show: false },
          axisTick: { show: false },
          splitLine: { lineStyle: { color: '#eceff3' } },
          axisLabel: { color: '#6b7280', formatter: (value) => this.formatPopulationDensity(value) },
        },
        yAxis: {
          type: 'category',
          data: topCells.map((item) => item.label),
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: { color: '#6b7280' },
        },
        series: [{
          type: 'bar',
          data: topCells.map((item) => item.value),
          barMaxWidth: 18,
          itemStyle: { color: '#d946ef' },
        }],
      }, true)
    },
    renderPopulationSexCharts(primaryChart, secondaryChart) {
      const summary = (this.populationOverview && this.populationOverview.summary) || {}
      const maleValue = toNumber(summary.male_total, 0)
      const femaleValue = toNumber(summary.female_total, 0)
      const totalPopulation = maleValue + femaleValue
      const maleRatio = totalPopulation > 0 ? (maleValue / totalPopulation) * 100 : 0
      const femaleRatio = totalPopulation > 0 ? (femaleValue / totalPopulation) * 100 : 0
      const diffValue = maleValue - femaleValue
      const metricMode = this.normalizePopulationSexMetricMode(this.populationSexMetricMode)
      primaryChart.setOption({
        animationDuration: 240,
        title: { text: '性别占比（%）', left: 0, top: 0, textStyle: { fontSize: 13, fontWeight: 600 } },
        tooltip: { trigger: 'item' },
        legend: { bottom: 0, icon: 'circle' },
        series: [{
          type: 'pie',
          radius: ['46%', '72%'],
          center: ['50%', '44%'],
          label: {
            formatter: ({ name, value }) => `${name}\n${this.formatPopulationValue(value)}`,
            fontSize: 11,
          },
          data: [
            { name: '男性', value: maleValue, itemStyle: { color: '#2563eb' } },
            { name: '女性', value: femaleValue, itemStyle: { color: '#ec4899' } },
          ],
        }],
      }, true)
      if (metricMode === 'ratio') {
        secondaryChart.setOption({
          animationDuration: 240,
          title: { text: '性别占比对比（%）', left: 0, top: 0, textStyle: { fontSize: 13, fontWeight: 600 } },
          tooltip: { trigger: 'axis' },
          grid: { left: 44, right: 12, top: 42, bottom: 26, containLabel: true },
          xAxis: {
            type: 'category',
            data: ['男性', '女性'],
            axisLabel: { color: '#6b7280' },
            axisLine: { lineStyle: { color: '#d7dce3' } },
          },
          yAxis: {
            type: 'value',
            min: 0,
            max: 100,
            axisLine: { show: false },
            axisTick: { show: false },
            splitLine: { lineStyle: { color: '#eceff3' } },
            axisLabel: { color: '#6b7280', formatter: (value) => `${toNumber(value, 0).toFixed(0)}%` },
          },
          series: [{
            type: 'bar',
            data: [
              { value: Number(maleRatio.toFixed(2)), itemStyle: { color: '#2563eb' } },
              { value: Number(femaleRatio.toFixed(2)), itemStyle: { color: '#ec4899' } },
            ],
            barMaxWidth: 28,
          }],
        }, true)
        return
      }
      if (metricMode === 'diff') {
        secondaryChart.setOption({
          animationDuration: 240,
          title: { text: '性别差异（男-女，人口）', left: 0, top: 0, textStyle: { fontSize: 13, fontWeight: 600 } },
          tooltip: {
            trigger: 'axis',
            formatter: () => `差异值 ${this.formatPopulationSignedValue(diffValue)}人`,
          },
          grid: { left: 54, right: 12, top: 42, bottom: 26, containLabel: true },
          xAxis: {
            type: 'category',
            data: ['当前分析区'],
            axisLabel: { color: '#6b7280' },
            axisLine: { lineStyle: { color: '#d7dce3' } },
          },
          yAxis: {
            type: 'value',
            axisLine: { show: false },
            axisTick: { show: false },
            splitLine: { lineStyle: { color: '#eceff3' } },
            axisLabel: { color: '#6b7280', formatter: (value) => this.formatPopulationSignedValue(value) },
          },
          series: [{
            type: 'bar',
            data: [
              {
                value: Number(diffValue.toFixed(3)),
                itemStyle: { color: diffValue >= 0 ? '#2563eb' : '#ec4899' },
              },
            ],
            barMaxWidth: 36,
            markLine: {
              symbol: 'none',
              lineStyle: { color: '#9ca3af', type: 'dashed' },
              data: [{ yAxis: 0 }],
            },
          }],
        }, true)
      }
    },
    renderPopulationAgeCharts(primaryChart) {
      const ageRows = Array.isArray(this.populationOverview && this.populationOverview.age_distribution)
        ? this.populationOverview.age_distribution
        : []
      const labels = ageRows.map((row) => row.age_band_label || row.age_band || '')
      const totalPopulation = toNumber((this.populationOverview && this.populationOverview.summary && this.populationOverview.summary.total_population) || 0, 0)
      const ratios = ageRows.map((row) => {
        const value = toNumber(row && row.total, 0)
        return totalPopulation > 0 ? (value / totalPopulation) * 100 : 0
      })
      primaryChart.setOption({
        animationDuration: 240,
        title: { text: '区域年龄结构', left: 0, top: 0, textStyle: { fontSize: 13, fontWeight: 600 } },
        tooltip: {
          trigger: 'axis',
          formatter: (items) => {
            const first = Array.isArray(items) ? items[0] : null
            const index = Number(first && first.dataIndex)
            if (!Number.isFinite(index) || index < 0 || index >= ageRows.length) return ''
            const row = ageRows[index] || {}
            const ratio = ratios[index] || 0
            const label = labels[index] || ''
            return [
              `${label}`,
              `占比 ${ratio.toFixed(2)}%`,
              `总量 ${this.formatPopulationValue(row.total || 0)}`,
              `男性 ${this.formatPopulationValue(row.male || 0)}`,
              `女性 ${this.formatPopulationValue(row.female || 0)}`,
            ].join('<br/>')
          },
        },
        grid: { left: 44, right: 12, top: 42, bottom: 52, containLabel: true },
        xAxis: {
          type: 'category',
          data: labels,
          axisLabel: { interval: 0, rotate: labels.length > 8 ? 35 : 0, fontSize: 10, color: '#6b7280' },
          axisLine: { lineStyle: { color: '#d7dce3' } },
        },
        yAxis: {
          type: 'value',
          axisLine: { show: false },
          axisTick: { show: false },
          splitLine: { lineStyle: { color: '#eceff3' } },
          axisLabel: { color: '#6b7280', formatter: (value) => `${toNumber(value, 0).toFixed(1)}%` },
        },
        series: [{
          type: 'bar',
          data: ratios.map((value) => toNumber(value, 0)),
          barMaxWidth: 20,
          itemStyle: { color: '#f59e0b' },
        }],
      }, true)
    },
    resetPopulationAnalysisState(options = {}) {
      const keepMeta = !!(options && options.keepMeta)
      const keepYear = !!(options && options.keepYear)
      this.isComputingPopulation = false
      this.isLoadingPopulationGrid = false
      this.populationStatus = ''
      this.populationScopeId = ''
      this.populationOverview = null
      this.populationGrid = null
      this.populationGridCount = 0
      this.populationLayer = null
      this.populationSubTab = 'analysis'
      this.populationAnalysisView = 'density'
      this.populationSexMetricMode = 'ratio'
      this.populationSexSourceLayers = createPopulationSexSourceLayers()
      this.populationAgeMode = 'dominant'
      if (!keepMeta) {
        this.populationMeta = createPopulationFallbackMeta()
        this.populationMetaLoaded = false
      }
      if (!keepYear) {
        this.populationSelectedYear = String((this.populationMeta && this.populationMeta.default_year) || '2026')
      }
      this.populationAgeBand = 'all'
      this.clearPopulationRasterDisplayOnLeave()
      this.disposePopulationCharts()
    },
    clearPopulationRasterDisplayOnLeave() {
      if (this.mapCore && typeof this.mapCore.clearGridPolygons === 'function') {
        this.mapCore.clearGridPolygons()
      }
      if (this.mapCore && typeof this.mapCore.clearPopulationRasterOverlay === 'function') {
        this.mapCore.clearPopulationRasterOverlay()
      }
    },
    restorePopulationRasterDisplayOnEnter() {
      if (!this.isPopulationDisplayActive()) return
      this.applyPopulationGridToMap()
    },
    buildPopulationStyledFeatures() {
      const baseFeatures = ((this.populationGrid && this.populationGrid.features) || [])
      const usingAnalysisStyle = this.populationSubTab === 'analysis'
        && !!this.populationLayer
        && Array.isArray(this.populationLayer.cells)
        && this.populationLayer.cells.length > 0
      const cellMap = new Map(
        (((this.populationLayer && this.populationLayer.cells) || []).map((cell) => [String(cell.cell_id || ''), cell]))
      )
      return baseFeatures.map((feature) => {
        const props = Object.assign({}, (feature && feature.properties) || {})
        const cell = cellMap.get(String(props.cell_id || ''))
        return {
          type: 'Feature',
          geometry: feature.geometry,
          properties: Object.assign({}, props, usingAnalysisStyle && cell ? {
            fillColor: String(cell.fill_color || '#f3f4f6'),
            fillOpacity: toNumber(cell.fill_opacity, 0.18),
            strokeColor: String(cell.stroke_color || '#ffffff'),
            strokeWeight: 0.8,
          } : {
            fillColor: '#f4f6f8',
            fillOpacity: 0.16,
            strokeColor: '#d7dde7',
            strokeWeight: 0.8,
          }),
        }
      })
    },
    applyPopulationGridToMap() {
      if (!this.mapCore) return
      if (typeof this.mapCore.clearPopulationRasterOverlay === 'function') {
        this.mapCore.clearPopulationRasterOverlay()
      }
      const features = this.buildPopulationStyledFeatures()
      if (!features.length) {
        if (typeof this.mapCore.clearGridPolygons === 'function') this.mapCore.clearGridPolygons()
        return
      }
      if (typeof this.mapCore.setGridFeatures !== 'function') return
      this.mapCore.setGridFeatures(features, {
        strokeColor: '#d7dde7',
        strokeWeight: 0.8,
        fillColor: '#f4f6f8',
        fillOpacity: 0.16,
        clickable: false,
        webglBatch: true,
      })
    },
    async ensurePopulationBaseGrid(force = false) {
      const rawRing = this.getIsochronePolygonRing()
      if (!rawRing || this.isLoadingPopulationGrid) return this.populationGrid
      if (this.populationGrid && !force) return this.populationGrid
      this.isLoadingPopulationGrid = true
      try {
        const polygon = this.getIsochronePolygonPayload()
        const year = this.getPopulationSelectedYear()
        const res = await fetch('/api/v1/analysis/population/grid', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            polygon,
            coord_type: 'gcj02',
            year,
          }),
        })
        if (!res.ok) {
          let detail = ''
          try {
            detail = await res.text()
          } catch (_) {}
          throw new Error(detail || '人口格子生成失败')
        }
        const data = await res.json()
        const nextScopeId = String(data.scope_id || '')
        if (nextScopeId && nextScopeId !== String(this.populationScopeId || '')) {
          this.populationSexSourceLayers = createPopulationSexSourceLayers()
        }
        this.populationGrid = data
        this.populationGridCount = Number.isFinite(Number(data.cell_count)) ? Number(data.cell_count) : (((data && data.features) || []).length)
        this.populationScopeId = nextScopeId
        if (!this.populationOverview && this.populationGridCount <= 0) {
          this.populationStatus = '当前范围没有可用人口格子'
        }
        if (this.isPopulationDisplayActive()) {
          this.applyPopulationGridToMap()
        }
        return data
      } finally {
        this.isLoadingPopulationGrid = false
      }
    },
    async ensurePopulationPanelEntryState() {
      const rawRing = this.getIsochronePolygonRing()
      if (!rawRing) {
        this.populationStatus = ''
        this.restorePopulationRasterDisplayOnEnter()
        return
      }
      try {
        await this.loadPopulationMeta(false)
        await this.ensurePopulationBaseGrid(false)
      } catch (e) {
        this.populationStatus = '人口格子加载失败: ' + (e && e.message ? e.message : String(e))
        this.restorePopulationRasterDisplayOnEnter()
        return
      }
      if (!this.populationOverview && !this.isComputingPopulation && this.populationGridCount > 0) {
        this.populationStatus = '正在自动计算人口分析...'
        await this.computePopulationAnalysis()
        return
      }
      if (this.populationOverview && !this.populationLayer && !this.isComputingPopulation) {
        try {
          await this.fetchPopulationLayer(this.populationAnalysisView || 'density')
        } catch (e) {
          this.populationStatus = '人口图层加载失败: ' + (e && e.message ? e.message : String(e))
        }
      }
      if (this.populationOverview) {
        this.$nextTick(() => {
          this.updatePopulationCharts()
        })
      }
      this.restorePopulationRasterDisplayOnEnter()
    },
    async computePopulationAnalysis() {
      const rawRing = this.getIsochronePolygonRing()
      if (!rawRing || this.isComputingPopulation) return
      this.isComputingPopulation = true
      this.populationStatus = '正在加载人口格子...'
      try {
        await this.loadPopulationMeta(false)
        await this.ensurePopulationBaseGrid(false)
        const polygon = this.getIsochronePolygonPayload()
        this.populationStatus = '正在计算人口总览...'
        const overviewResp = await fetch('/api/v1/analysis/population/overview', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            polygon,
            coord_type: 'gcj02',
            year: this.getPopulationSelectedYear(),
          }),
        })
        if (!overviewResp.ok) {
          let detail = ''
          try {
            detail = await overviewResp.text()
          } catch (_) {}
          throw new Error(detail || '人口总览计算失败')
        }
        const overview = await overviewResp.json()
        const nextScopeId = String(overview.scope_id || this.populationScopeId || '')
        if (nextScopeId && nextScopeId !== String(this.populationScopeId || '')) {
          this.populationSexSourceLayers = createPopulationSexSourceLayers()
        }
        this.populationOverview = overview
        this.populationScopeId = nextScopeId
        this.populationSubTab = 'analysis'
        this.populationAnalysisView = 'density'
        this.populationStatus = '正在生成人口密度图层...'
        await this.fetchPopulationLayer('density')
        this.$nextTick(() => {
          this.updatePopulationCharts()
        })
        if (typeof this.persistAnalysisArtifactQuietly === 'function') {
          this.persistAnalysisArtifactQuietly('population')
        }
      } catch (e) {
        console.error(e)
        this.populationStatus = '人口分析失败: ' + (e && e.message ? e.message : String(e))
      } finally {
        this.isComputingPopulation = false
      }
    },
    async onPopulationYearChange() {
      const year = String(this.populationSelectedYear || '').trim()
      const options = this.getPopulationYearOptions()
      if (!options.some((item) => item.value === year)) {
        this.populationSelectedYear = String((this.populationMeta && this.populationMeta.default_year) || '2026')
      }
      this.populationStatus = `正在切换人口年份：${this.getPopulationSelectedYearLabel()}`
      this.populationScopeId = ''
      this.populationOverview = null
      this.populationGrid = null
      this.populationGridCount = 0
      this.populationLayer = null
      this.populationSubTab = 'analysis'
      this.populationAnalysisView = 'density'
      this.populationSexMetricMode = 'ratio'
      this.populationSexSourceLayers = createPopulationSexSourceLayers()
      this.populationAgeMode = 'dominant'
      this.populationAgeBand = 'all'
      this.clearPopulationRasterDisplayOnLeave()
      this.disposePopulationCharts()
      await this.ensurePopulationPanelEntryState()
    },
    async fetchPopulationLayer(view = this.populationAnalysisView) {
      const rawRing = this.getIsochronePolygonRing()
      if (!rawRing) return null
      const safeView = ['density', 'sex', 'age'].includes(String(view || '').trim().toLowerCase())
        ? String(view || '').trim().toLowerCase()
        : 'density'
      if (safeView === 'sex') {
        const sexLayer = await this.fetchPopulationSexStructureLayer(false)
        this.populationScopeId = String(sexLayer.scope_id || this.populationScopeId || '')
        this.populationLayer = sexLayer
        this.populationStatus = `人口分析完成：${this.getPopulationSexMetricLabel(this.populationSexMetricMode)}已更新`
        if (this.isPopulationDisplayActive()) {
          this.applyPopulationGridToMap()
        }
        this.$nextTick(() => {
          this.updatePopulationCharts()
        })
        return sexLayer
      }
      const requestAgeMode = safeView === 'age' ? 'dominant' : this.populationAgeMode
      const requestAgeBand = safeView === 'age' ? 'all' : this.populationAgeBand
      if (safeView === 'age') {
        this.populationAgeMode = 'dominant'
        this.populationAgeBand = 'all'
      }
      const layer = await this.requestPopulationLayer({
        view: safeView,
        sexMode: 'male',
        ageMode: requestAgeMode,
        ageBand: requestAgeBand,
      })
      this.populationScopeId = String(layer.scope_id || this.populationScopeId || '')
      this.populationLayer = layer
      const selected = layer.selected || {}
      this.populationStatus = `人口分析完成：${selected.view_label || '人口图层'}已更新`
      if (this.isPopulationDisplayActive()) {
        this.applyPopulationGridToMap()
      }
      this.$nextTick(() => {
        this.updatePopulationCharts()
      })
      return layer
    },
    async onPopulationSexMetricModeChange() {
      if (!this.populationOverview || this.isComputingPopulation || this.populationAnalysisView !== 'sex') return
      this.populationSexMetricMode = this.normalizePopulationSexMetricMode(this.populationSexMetricMode)
      this.isComputingPopulation = true
      this.populationStatus = '正在切换性别结构图层...'
      try {
        await this.fetchPopulationLayer('sex')
      } catch (e) {
        console.error(e)
        this.populationStatus = '性别结构图层切换失败: ' + (e && e.message ? e.message : String(e))
      } finally {
        this.isComputingPopulation = false
      }
    },
    getPopulationSummaryRows() {
      const layerSummary = (this.populationLayer && this.populationLayer.summary) || {}
      const overviewSummary = (this.populationOverview && this.populationOverview.summary) || {}
      const view = String(this.populationAnalysisView || 'density')
      if (view === 'sex') {
        const maleTotal = toNumber(layerSummary.male_total, toNumber(overviewSummary.male_total, 0))
        const femaleTotal = toNumber(layerSummary.female_total, toNumber(overviewSummary.female_total, 0))
        const total = maleTotal + femaleTotal
        const maleRatio = total > 0 ? maleTotal / total : 0
        const diffValue = maleTotal - femaleTotal
        return [
          { key: 'male_total', label: '男性人口', value: this.formatPopulationValue(maleTotal) },
          { key: 'female_total', label: '女性人口', value: this.formatPopulationValue(femaleTotal) },
          { key: 'male_ratio', label: '男性占比', value: this.formatPopulationPercent(maleRatio) },
          { key: 'sex_diff_total', label: '性别差异（男-女）', value: `${this.formatPopulationSignedValue(diffValue)}人` },
        ]
      }
      if (view === 'age') {
        const dominantCellCount = Math.max(0, Math.round(toNumber(layerSummary.dominant_cell_count, 0)))
        const cellCount = Math.max(0, Math.round(toNumber(this.populationGridCount, 0)))
        const backendRatio = toNumber(layerSummary.dominant_cell_ratio, -1)
        const dominantCellRatio = backendRatio >= 0
          ? backendRatio
          : (cellCount > 0 ? (dominantCellCount / cellCount) : 0)
        return [
          { key: 'top_dominant_age_band_label', label: '最常主导年龄', value: String(layerSummary.top_dominant_age_band_label || '-') },
          { key: 'dominant_cell_count', label: '主导格子数', value: `${dominantCellCount}` },
          { key: 'dominant_cell_ratio', label: '主导格子占比', value: `${(Math.max(0, dominantCellRatio) * 100).toFixed(1)}%` },
          { key: 'average_dominant_ratio_percent', label: '平均主导占比', value: `${toNumber(layerSummary.average_dominant_ratio_percent, 0).toFixed(1)}%` },
        ]
      }
      return [
        { key: 'total_population', label: '总人口', value: this.formatPopulationValue(layerSummary.total_population || overviewSummary.total_population || 0) },
        { key: 'average_density_per_km2', label: '平均密度', value: this.formatPopulationDensity(layerSummary.average_density_per_km2 || 0) },
        { key: 'peak_density_per_km2', label: '峰值密度', value: this.formatPopulationDensity(layerSummary.peak_density_per_km2 || 0) },
        { key: 'nonzero_cell_count', label: '非零格子数', value: `${Math.round(toNumber(layerSummary.nonzero_cell_count, 0))}` },
      ]
    },
    getPopulationLegendGradientStyle() {
      const stops = (((this.populationLayer && this.populationLayer.legend && this.populationLayer.legend.stops) || [])
        .filter((item) => item && item.color))
      if (!stops.length) return {}
      const gradient = stops
        .map((item) => `${item.color} ${Math.round(toNumber(item.ratio, 0) * 100)}%`)
        .join(', ')
      return {
        background: `linear-gradient(90deg, ${gradient})`,
      }
    },
  }
}

export { createAnalysisPopulationInitialState, createAnalysisPopulationMethods }
