import {
  asText,
  clampText,
  cloneArray,
  cloneAgentSessionRecord,
  cloneObject,
  consumeSseStream,
  createAgentSessionRecord,
  hasAgentMessageProcessContent,
  normalizeAgentMessageProcess,
  normalizeAgentPanelPreloadNotes,
  normalizeAgentToolSummary,
  sortAgentSessions,
} from './normalizers.js'
import {
  buildAgentPlanChecklist,
  buildAgentToolCallItems,
  hasAgentExecutionTraceContent,
  hasAgentPlanContent,
  shouldShowAgentProcessLiveStatus,
  shouldShowAgentProcessToggle,
} from './derived.js'
import {
  buildAnalysisTaskConfirmation,
  cloneAnalysisTaskConfirmation,
  focusAnalysisTaskPanel,
  getAnalysisTaskDefinition,
  getAnalysisTaskDefinitions,
  runAnalysisTask,
} from './analysis-task-registry.js'
import { buildAnalysisTaskParamBundle } from './analysis-task-params.js'
import { createAgentPptPlanningTabMethods } from './ppt-planning-tabs.js'
import {
  normalizeAgentPptPlanningTab,
  serializeAgentPptPlanningTab,
} from './ppt-planning-tabs.js'

export function createAgentIterationChangeUiMethods() {
  return {
    getAgentIterationKinds() {
      return [
        { key: 'poi', label: 'POI', disabled: false },
        { key: 'population', label: '人口', disabled: false },
        { key: 'nightlight', label: '夜光', disabled: false },
      ]
    },
    getAgentIterationSecondaryView(kind = '') {
      const currentKind = asText(kind || this.agentIterationActiveKind) || 'poi'
      const view = cloneObject(this.agentIterationSecondaryView)
      const items = this.getAgentIterationSecondaryNavItems(currentKind)
      const saved = asText(view[currentKind])
      if (saved && items.some((item) => item.key === saved)) return saved
      const defaultItem = items[0] || {}
      return asText(defaultItem.key)
    },
    isAgentIterationSecondaryView(key = '', kind = '') {
      return this.getAgentIterationSecondaryView(kind) === asText(key)
    },
    setAgentIterationSecondaryView(key = '', kind = '') {
      const currentKind = asText(kind || this.agentIterationActiveKind) || 'poi'
      const target = asText(key)
      const items = this.getAgentIterationSecondaryNavItems(currentKind)
      if (!items.some((item) => item.key === target)) return
      this.agentIterationSecondaryView = {
        ...cloneObject(this.agentIterationSecondaryView),
        [currentKind]: target,
      }
    },
    getAgentIterationSelectedSecondaryItem(kind = '') {
      const currentKind = asText(kind || this.agentIterationActiveKind) || 'poi'
      const key = this.getAgentIterationSecondaryView(currentKind)
      return this.getAgentIterationSecondaryNavItems(currentKind).find((item) => item.key === key) || {}
    },
    getAgentIterationSecondaryPlaceholderTitle(kind = '') {
      const item = this.getAgentIterationSelectedSecondaryItem(kind)
      return `${asText(item.label) || '模块'}生成中`
    },
    shouldShowAgentIterationSecondaryPlaceholder(kind = '') {
      const currentKind = asText(kind || this.agentIterationActiveKind) || 'poi'
      const item = this.getAgentIterationSelectedSecondaryItem(currentKind)
      if (!asText(item.key)) return false
      if (currentKind === 'poi') {
        if (this.agentIterationPoiError || this.getAgentIterationPoiPayload().error) return false
        if (item.key === 'ai' && asText(this.getAgentIterationPoiPayload().status) === 'ready') return false
        return !item.available
      }
      if (currentKind === 'population') {
        if (this.agentIterationPopulationError || this.getAgentIterationPopulationPayload().error) return false
        return !item.available
      }
      if (this.agentIterationNightlightError || this.getAgentIterationNightlightPayload().error) return false
      return !item.available
    },
    getAgentIterationSecondaryNavItems() {
      const activeKind = asText(arguments[0] || this.agentIterationActiveKind) || 'poi'
      if (activeKind === 'poi') {
        const readiness = this.getAgentIterationPoiReadiness()
        const poiReady = asText(this.getAgentIterationPoiPayload().status) === 'ready' && readiness.ready
        const dataItem = { key: 'data', label: '数据补齐', available: true }
        if (!poiReady) return [dataItem]
        return [
          dataItem,
          { key: 'ai', label: '业态基础分析', available: poiReady },
          { key: 'metrics', label: '核心指标', available: poiReady },
          { key: 'trend', label: '趋势结构', available: this.getAgentIterationPoiTotalLineChart().length >= 2 },
          { key: 'space', label: '空间分布', available: this.getAgentIterationPoiAreaHeatmaps().length > 0 },
          { key: 'detail', label: '年度明细', available: this.getAgentIterationPoiSnapshotRows().length > 0 },
        ]
      }
      if (activeKind === 'population') {
        return [
          { key: 'metrics', label: '核心指标', available: asText(this.getAgentIterationPopulationPayload().status) === 'ready' },
        ]
      }
      return [
        { key: 'snapshots', label: '年度快照', available: cloneArray(this.getAgentIterationNightlightPayload().snapshots).length > 0 },
        { key: 'ai', label: 'AI解读', available: !!asText(this.getAgentIterationNightlightPayload().status) },
        { key: 'trend', label: '趋势指标', available: !!asText(this.getAgentIterationNightlightPayload().status) },
      ]
    },
    getAgentIterationPayload(kind = 'nightlight') {
      const payloads = cloneObject(this.agentPanelPayloads)
      const root = payloads.iteration_change && typeof payloads.iteration_change === 'object'
        ? payloads.iteration_change
        : {}
      return cloneObject(root[asText(kind) || 'nightlight'])
    },
    getAgentIterationNightlightPayload() {
      return this.getAgentIterationPayload('nightlight')
    },
    getAgentIterationPoiPayload() {
      return this.getAgentIterationPayload('poi')
    },
    getAgentIterationPopulationPayload() {
      return this.getAgentIterationPayload('population')
    },
    getAgentIterationActiveLoading() {
      if (this.agentIterationActiveKind === 'poi') return !!this.agentIterationPoiLoading
      if (this.agentIterationActiveKind === 'population') return !!this.agentIterationPopulationLoading
      return !!this.agentIterationNightlightLoading
    },
    getAgentIterationActiveLoadingText() {
      return this.getAgentIterationActiveLoading() ? '生成中' : '重新生成'
    },
    getAgentIterationActiveDescription() {
      if (this.agentIterationActiveKind === 'poi') return '历史 POI 特征与多年结构变化趋势'
      if (this.agentIterationActiveKind === 'population') return '人口变化的总结特征'
      return '近三年夜光快照与热点迁移趋势解析'
    },
    isAgentIterationPayloadEmpty(payload = null) {
      const status = asText(payload && payload.status)
      return !status || status === 'idle'
    },
    getAgentIterationEmptyNotice(kind = '') {
      const payload = this.getAgentIterationPayload(kind || this.agentIterationActiveKind)
      return asText(payload.notice) || '已切换历史记录，请重新生成多年迭代变化。'
    },
    getAgentIterationNightlightAnalysisRows() {
      const payload = this.getAgentIterationNightlightPayload()
      const analysis = cloneObject(payload.ai_analysis)
      return [
        { key: 'headline', label: '趋势判断', value: analysis.headline },
        { key: 'trend_summary', label: '总体变化', value: analysis.trend_summary },
        { key: 'hotspot_migration', label: '热点迁移', value: analysis.hotspot_migration },
        { key: 'risk_or_opportunity', label: '机会风险', value: analysis.risk_or_opportunity },
      ].filter((item) => asText(item.value))
    },
    formatAgentIterationMetric(value, digits = 2) {
      const number = Number(value)
      if (!Number.isFinite(number)) return '-'
      return number.toLocaleString('zh-CN', {
        maximumFractionDigits: digits,
        minimumFractionDigits: Math.min(1, digits),
      })
    },
    formatAgentIterationPercent(value) {
      const number = Number(value)
      if (!Number.isFinite(number)) return '-'
      return `${(number * 100).toFixed(1)}%`
    },
    formatAgentIterationSignedPercent(value) {
      const number = Number(value)
      if (!Number.isFinite(number)) return '-'
      return `${number >= 0 ? '+' : ''}${(number * 100).toFixed(1)}%`
    },
    getAgentIterationPopulationAgeGroupRatios(row = {}) {
      const groups = row && typeof row.age_group_ratios === 'object' ? row.age_group_ratios : {}
      const distribution = cloneArray(row && row.age_distribution)
      const total = Number(row && (row.total_population ?? row.population ?? 0)) || distribution.reduce((sum, item) => sum + (Number(item && item.total) || 0), 0)
      if (groups && Object.keys(groups).length) {
        return {
          child: Number(groups.child_0_14),
          working: Number(groups.working_15_64),
          senior: Number(groups.senior_65_plus),
        }
      }
      const sums = { child: 0, working: 0, senior: 0 }
      distribution.forEach((item) => {
        const key = asText(item && item.age_band)
        const start = key === '00' ? 0 : Number(key)
        const value = Number(item && item.total) || 0
        if (!Number.isFinite(start)) return
        if (start < 15) sums.child += value
        else if (start < 65) sums.working += value
        else sums.senior += value
      })
      if (!total) return { child: NaN, working: NaN, senior: NaN }
      return {
        child: sums.child / total,
        working: sums.working / total,
        senior: sums.senior / total,
      }
    },
    getAgentIterationPopulationFeatureRows() {
      const payload = this.getAgentIterationPopulationPayload()
      const series = cloneArray(payload.series || (payload.timeseries && payload.timeseries.series))
      const layerSummary = (((payload.timeseries || {}).layer || {}).summary) || {}
      const first = series[0] || {}
      const last = series[series.length - 1] || first
      const countDelta = Number(last.total_population ?? last.population ?? 0) - Number(first.total_population ?? first.population ?? 0)
      const densityDelta = Number(last.population_density ?? last.density ?? 0) - Number(first.population_density ?? first.density ?? 0)
      const maleTotal = Number(last.male_total)
      const femaleTotal = Number(last.female_total)
      const totalPopulation = Number(last.total_population ?? last.population ?? 0)
      const maleRatio = Number.isFinite(Number(last.male_ratio))
        ? Number(last.male_ratio)
        : (Number.isFinite(maleTotal) && Number.isFinite(femaleTotal) && (maleTotal + femaleTotal) > 0 ? maleTotal / (maleTotal + femaleTotal) : NaN)
      const femaleRatio = Number.isFinite(Number(last.female_ratio))
        ? Number(last.female_ratio)
        : (Number.isFinite(maleRatio) ? 1 - maleRatio : NaN)
      const sexDelta = Number.isFinite(maleTotal) && Number.isFinite(femaleTotal) ? maleTotal - femaleTotal : NaN
      const ageGroups = this.getAgentIterationPopulationAgeGroupRatios(last)
      const dominantAge = asText(last.top_age_band_label || last.dominant_age_band || last.top_age_band)
      const firstDominantAge = asText(first.top_age_band_label || first.dominant_age_band || first.top_age_band)
      const topAgeRatio = Number(last.top_age_band_ratio)
      const rows = [
        { key: 'period', label: '分析周期', value: asText(payload.period) || '-' },
        { key: 'cell_count', label: '格网数', value: Number.isFinite(Number(layerSummary.cell_count)) ? Math.round(Number(layerSummary.cell_count)) : '-' },
        { key: 'increase', label: '增长格网', value: Math.round(Number(layerSummary.increase_count || 0)) },
        { key: 'decrease', label: '下降格网', value: Math.round(Number(layerSummary.decrease_count || 0)) },
        { key: 'average_rate', label: '平均变化率', value: this.formatAgentIterationSignedPercent(layerSummary.average_rate) },
      ]
      if (series.length >= 2) {
        rows.push(
          { key: 'population_delta', label: '总人口首尾变化', value: this.formatAgentIterationMetric(countDelta, 0) },
          { key: 'density_delta', label: '平均密度首尾变化', value: this.formatAgentIterationMetric(densityDelta, 2) },
        )
      }
      rows.push(
        { key: 'male_total', label: '末年男性人口', value: Number.isFinite(maleTotal) ? this.formatAgentIterationMetric(maleTotal, 0) : '' },
        { key: 'female_total', label: '末年女性人口', value: Number.isFinite(femaleTotal) ? this.formatAgentIterationMetric(femaleTotal, 0) : '' },
        { key: 'male_ratio', label: '末年男性占比', value: Number.isFinite(maleRatio) ? this.formatAgentIterationPercent(maleRatio) : '' },
        { key: 'female_ratio', label: '末年女性占比', value: Number.isFinite(femaleRatio) ? this.formatAgentIterationPercent(femaleRatio) : '' },
        { key: 'sex_delta', label: '末年性别差（男-女）', value: Number.isFinite(sexDelta) ? this.formatAgentIterationMetric(sexDelta, 0) : '' },
        { key: 'dominant_age_band', label: '末年主年龄段', value: dominantAge },
        {
          key: 'dominant_age_shift',
          label: '主年龄段首尾变化',
          value: firstDominantAge && dominantAge ? `${firstDominantAge} -> ${dominantAge}` : '',
        },
        { key: 'top_age_band_ratio', label: '主年龄段占比', value: Number.isFinite(topAgeRatio) ? this.formatAgentIterationPercent(topAgeRatio) : '' },
        { key: 'child_ratio', label: '少儿人口占比(0-14)', value: Number.isFinite(ageGroups.child) ? this.formatAgentIterationPercent(ageGroups.child) : '' },
        { key: 'working_age_ratio', label: '劳动年龄占比(15-64)', value: Number.isFinite(ageGroups.working) ? this.formatAgentIterationPercent(ageGroups.working) : '' },
        { key: 'senior_ratio', label: '老年人口占比(65+)', value: Number.isFinite(ageGroups.senior) ? this.formatAgentIterationPercent(ageGroups.senior) : '' },
      )
      return rows.filter((item) => item.value !== undefined && item.value !== null && item.value !== '')
    },
    getAgentIterationNightlightTrendRows() {
      const payload = this.getAgentIterationNightlightPayload()
      const series = cloneArray(payload.series || (payload.timeseries && payload.timeseries.series))
      if (series.length < 2) return []
      const first = series[0] || {}
      const last = series[series.length - 1] || {}
      const delta = (key) => Number(last[key] || 0) - Number(first[key] || 0)
      return [
        { key: 'total_radiance', label: '总辐亮首尾变化', value: this.formatAgentIterationMetric(delta('total_radiance'), 1) },
        { key: 'mean_radiance', label: '平均辐亮首尾变化', value: this.formatAgentIterationMetric(delta('mean_radiance'), 2) },
        { key: 'p90_radiance', label: 'P90首尾变化', value: this.formatAgentIterationMetric(delta('p90_radiance'), 2) },
        { key: 'lit_pixel_ratio', label: '点亮占比首尾变化', value: this.formatAgentIterationPercent(delta('lit_pixel_ratio')) },
      ]
    },
    getAgentIterationNightlightHotspotRows() {
      const payload = this.getAgentIterationNightlightPayload()
      const counts = (((payload.timeseries || {}).layer || {}).summary || {}).class_counts || {}
      return [
        { key: 'hotspot_emerging', label: '新增热点', value: counts.hotspot_emerging },
        { key: 'hotspot_stable', label: '持续热点', value: counts.hotspot_stable },
        { key: 'hotspot_faded', label: '衰退热点', value: counts.hotspot_faded },
        { key: 'stable', label: '稳定格网', value: counts.stable },
      ].filter((item) => item.value !== undefined && item.value !== null)
    },
    getAgentIterationPoiFeatureRows() {
      const payload = this.getAgentIterationPoiPayload()
      const summaries = cloneArray(payload.summaries)
      const latest = summaries[summaries.length - 1] || {}
      const topSubcategory = (cloneArray(latest.top_subcategories)[0] || {})
      return [
        { key: 'year', label: '特征年份', value: latest.year || asText(payload.year) || '-' },
        { key: 'total', label: 'POI 数量', value: this.formatAgentIterationMetric(latest.count, 0) },
        { key: 'category_count', label: '业态类型数', value: this.formatAgentIterationMetric(latest.category_count, 0) },
        { key: 'top_category', label: '第一业态', value: ((latest.top_categories || [])[0] || {}).name || '-' },
        { key: 'top_category_count', label: '第一业态数量', value: this.formatAgentIterationMetric((((latest.top_categories || [])[0] || {}).count), 0) },
        { key: 'subcategory_count', label: '小类类型数', value: this.formatAgentIterationMetric(latest.subcategory_count, 0) },
        { key: 'top_subcategory', label: '第一小类', value: topSubcategory.name || '-' },
        { key: 'top_subcategory_parent', label: '第一小类所属大类', value: topSubcategory.parent || '-' },
        { key: 'top_area', label: '主要行政区', value: ((latest.top_areas || [])[0] || {}).name || '-' },
      ].filter((item) => item.value !== undefined && item.value !== null && item.value !== '')
    },
    getAgentIterationPoiTrendRows() {
      const payload = this.getAgentIterationPoiPayload()
      return cloneArray(payload.trend_rows)
        .concat(cloneArray(payload.subcategory_trend_rows))
        .filter((item) => asText(item.label) && item.value !== undefined && item.value !== null)
    },
    getAgentIterationPoiTargetYears() {
      const historyYears = cloneArray(this.currentHistoryAvailablePoiYears)
        .map((item) => Number(item))
        .filter((item) => Number.isFinite(item))
      const selected = cloneArray(this.poiYearSelections)
        .map((item) => Number(item))
        .filter((item) => Number.isFinite(item))
      if (this.agentIterationPoiYearSelectionTouched && selected.length >= 2) {
        return Array.from(new Set(selected)).sort((a, b) => a - b)
      }
      if (historyYears.length >= 2) return Array.from(new Set(historyYears)).sort((a, b) => a - b)
      if (selected.length >= 2) return Array.from(new Set(selected)).sort((a, b) => a - b)
      return [2020, 2022, 2024]
    },
    getAgentIterationPoiYearlyGridEvidence() {
      const payload = this.getAgentIterationPoiPayload()
      const evidence = payload.yearly_grid_evidence && typeof payload.yearly_grid_evidence === 'object'
        ? payload.yearly_grid_evidence
        : {}
      return cloneObject(evidence)
    },
    getAgentIterationPoiReadiness() {
      const years = this.getAgentIterationPoiTargetYears()
      const historyYears = cloneArray(this.currentHistoryAvailablePoiYears)
        .map((item) => Number(item))
        .filter((item) => Number.isFinite(item))
      const hasReadableHistory = !!asText(this.currentHistoryRecordId)
      const hasMultiYearPoi = hasReadableHistory && historyYears.length >= 2
      const yearly = this.getAgentIterationPoiYearlyGridEvidence()
      const readyH3Years = new Set(cloneArray(yearly.h3_items || yearly.items)
        .filter((item) => asText(item && item.status || 'ready') === 'ready')
        .map((item) => Number(item && item.year))
        .filter((item) => Number.isFinite(item)))
      const hasYearlyH3Grid = years.length >= 2 && years.every((year) => readyH3Years.has(Number(year)))
      const missingTasks = []
      if (!hasMultiYearPoi) missingTasks.push('poi_fetch')
      if (!hasYearlyH3Grid) missingTasks.push('poi_h3_grid')
      return {
        checked: true,
        ready: missingTasks.length === 0,
        missingTasks,
        reused: [
          hasMultiYearPoi ? 'poi_fetch' : '',
          hasYearlyH3Grid ? 'poi_h3_grid' : '',
        ].filter(Boolean),
        fetched: [],
        years,
      }
    },
    getAgentIterationPoiTaskBoardTasks() {
      const readiness = this.getAgentIterationPoiReadiness()
      const board = this.getAgentIterationPoiPayload().task_board || {}
      const taskMap = new Map(cloneArray(board.tasks).map((item) => [asText(item && item.key), item]))
      return ['poi_fetch', 'poi_h3_grid'].map((key) => {
        const existing = cloneObject(taskMap.get(key))
        const isMissing = readiness.missingTasks.includes(key)
        const isReused = readiness.reused.includes(key)
        const status = asText(existing.status) === 'running' || asText(existing.status) === 'failed'
          ? asText(existing.status)
          : (isMissing ? 'pending' : (isReused ? 'reused' : 'completed'))
        return {
          key,
          label: this.getAgentSummaryTaskLabel(key),
          status,
          error: asText(existing.error),
          startedAt: asText(existing.startedAt),
          endedAt: asText(existing.endedAt),
        }
      })
    },
    getAgentIterationPoiTaskKeysToFill() {
      return this.getAgentIterationPoiReadiness().missingTasks
    },
    isAgentIterationPoiTaskBoardRunning() {
      return this.getAgentIterationPoiTaskBoardTasks().some((task) => task.status === 'running')
    },
    getAgentIterationPoiPrimaryActionLabel() {
      if (this.isAgentIterationPoiTaskBoardRunning()) return '补齐中'
      return this.getAgentIterationPoiTaskKeysToFill().length ? '补齐缺失' : '重新抓取/重算'
    },
    getAgentIterationPoiDataCompletionYears() {
      return this.getAgentIterationPoiTargetYears()
    },
    getAgentIterationPoiYearOptionRows() {
      const optionMap = new Map()
      cloneArray(typeof this.getPoiMultiYearOptions === 'function' ? this.getPoiMultiYearOptions() : [])
        .forEach((item) => {
          const year = Number(item && item.value)
          if (Number.isFinite(year)) optionMap.set(year, { year, label: asText(item.label) || `${year}` })
        })
      cloneArray(this.currentHistoryAvailablePoiYears)
        .map((item) => Number(item))
        .filter((item) => Number.isFinite(item))
        .forEach((year) => {
          if (!optionMap.has(year)) optionMap.set(year, { year, label: `${year} 本地` })
        })
      this.getAgentIterationPoiTargetYears().forEach((year) => {
        if (!optionMap.has(year)) optionMap.set(year, { year, label: `${year}` })
      })
      const selectedYears = new Set(this.getAgentIterationPoiTargetYears().map((year) => Number(year)))
      const availableYears = new Set(cloneArray(this.currentHistoryAvailablePoiYears)
        .map((item) => Number(item))
        .filter((item) => Number.isFinite(item)))
      return Array.from(optionMap.values())
        .sort((a, b) => Number(a.year) - Number(b.year))
        .map((item) => ({
          ...item,
          selected: selectedYears.has(Number(item.year)),
          fetched: availableYears.has(Number(item.year)),
        }))
    },
    toggleAgentIterationPoiYearSelection(year, checked) {
      this.agentIterationPoiYearSelectionTouched = true
      if (typeof this.togglePoiYearSelection === 'function') {
        this.togglePoiYearSelection(year, checked)
      } else {
        const value = Number(year)
        if (!Number.isFinite(value)) return
        const next = new Set(this.getAgentIterationPoiTargetYears())
        if (checked) next.add(value)
        else if (next.size > 1) next.delete(value)
        this.poiYearSelections = Array.from(next).sort((a, b) => a - b)
      }
      this.commitAgentIterationPoiPayload({
        status: 'needs_data',
        yearly_grid_evidence: {},
        h3_evidence: {},
      })
    },
    getAgentIterationPoiYearStatusLabel(status = '') {
      const value = asText(status)
      if (value === 'ready' || value === 'completed' || value === 'reused') return '已完成'
      if (value === 'running') return '运行中'
      if (value === 'queued') return '排队中'
      if (value === 'failed') return '失败'
      return '缺失'
    },
    getAgentIterationPoiFetchYearRows() {
      const years = this.getAgentIterationPoiDataCompletionYears()
      const availableYears = new Set(cloneArray(this.currentHistoryAvailablePoiYears)
        .map((item) => Number(item))
        .filter((item) => Number.isFinite(item)))
      const task = this.getAgentIterationPoiTaskBoardTasks().find((item) => item.key === 'poi_fetch') || {}
      const taskStatus = asText(task.status)
      return years.map((year) => {
        const hasYear = availableYears.has(Number(year))
        const status = taskStatus === 'running'
          ? 'running'
          : (taskStatus === 'failed' && !hasYear ? 'failed' : (hasYear ? 'ready' : 'missing'))
        return {
          year,
          status,
          label: this.getAgentIterationPoiYearStatusLabel(status),
          source: hasYear ? '历史 POI 快照' : '待抓取',
          reuse: hasYear ? '可复用' : '未复用',
          error: status === 'failed' ? asText(task.error) : '',
        }
      })
    },
    getAgentIterationPoiGridYearRows() {
      const years = this.getAgentIterationPoiDataCompletionYears()
      const yearly = this.getAgentIterationPoiYearlyGridEvidence()
      const itemMap = new Map(cloneArray(yearly.items).map((item) => [Number(item && item.year), cloneObject(item)]))
      const task = this.getAgentIterationPoiTaskBoardTasks().find((item) => item.key === 'poi_h3_grid') || {}
      const taskStatus = asText(task.status)
      const stageLabelMap = {
        queued: '排队中',
        build_grid: '生成网格中',
        aggregate_poi: '聚合 POI 中',
        compute_metrics: '计算指标中',
        arcgis_prepare: '准备 ArcGIS 中',
        arcgis_running: 'ArcGIS 热点分析中',
        finalize: '整理结果中',
        completed: '已完成',
        failed: '失败',
      }
      return years.map((year) => {
        const item = itemMap.get(Number(year)) || {}
        const itemStatus = asText(item.status)
        const progress = cloneObject(item.progress || {})
        const stage = asText(progress.stage || '')
        const hasH3 = !!Object.keys(cloneObject(item.h3_evidence)).length
        const status = itemStatus === 'running'
          ? 'running'
          : (itemStatus === 'failed'
            ? 'failed'
            : (itemStatus === 'ready' || hasH3
              ? 'ready'
              : (taskStatus === 'running' ? 'queued' : 'missing')))
        const total = Number(progress.total || 0) || 7
        const step = Math.max(0, Math.min(total, Number(progress.step || 0) || 0))
        const elapsedSec = Math.max(0, Math.floor(Number(progress.elapsed_sec || 0) || 0))
        const extra = cloneObject(progress.extra || {})
        const gridCount = Number(extra.grid_count || (((item.h3_evidence || {}).summary || {}).grid_count) || 0) || 0
        const poiCount = Number(extra.poi_count || (((item.h3_evidence || {}).summary || {}).poi_count) || 0) || 0
        return {
          year,
          status,
          label: this.getAgentIterationPoiYearStatusLabel(status),
          stageLabel: stageLabelMap[stage] || (status === 'ready' ? '已完成' : (status === 'failed' ? '失败' : (status === 'running' ? '运行中' : '缺失'))),
          detailLabel: status === 'running'
            ? `${step}/${total} · ${elapsedSec}s${gridCount ? ` · ${gridCount}格` : ''}${poiCount ? ` · ${poiCount}POI` : ''}`
            : (status === 'ready'
              ? `${gridCount || Number((((item.h3_evidence || {}).summary || {}).grid_count) || 0) || 0}格 · ${poiCount || Number((((item.h3_evidence || {}).summary || {}).poi_count) || 0) || 0}POI`
              : ''),
          resolution: (((item.h3_evidence || {}).params || {}).h3_resolution) || this.h3GridResolution || '-',
          scope: asText(item.grid_scope || yearly.grid_scope) || 'poi_iteration_h3_per_year',
          error: asText(item.error) || (status === 'failed' ? asText(task.error) : ''),
          runId: asText(item.run_id),
          progress,
        }
      })
    },
    getAgentIterationPoiGridReadyCount() {
      return this.getAgentIterationPoiGridYearRows()
        .filter((row) => asText(row && row.status) === 'ready')
        .length
    },
    getAgentIterationPoiGridErrorRows() {
      return this.getAgentIterationPoiGridYearRows()
        .filter((row) => !!asText(row && row.error))
    },
    getAgentIterationPoiRasterGridYearRows() {
      const years = this.getAgentIterationPoiDataCompletionYears()
      const yearly = this.getAgentIterationPoiYearlyGridEvidence()
      const itemMap = new Map(cloneArray(yearly.raster_items).map((item) => [Number(item && item.year), cloneObject(item)]))
      const task = this.getAgentIterationPoiTaskBoardTasks().find((item) => item.key === 'poi_raster_grid') || {}
      const taskStatus = asText(task.status)
      return years.map((year) => {
        const item = itemMap.get(Number(year)) || {}
        const itemStatus = asText(item.status)
        const hasRaster = !!Object.keys(cloneObject(item.raster_evidence)).length
        const status = itemStatus === 'running'
          ? 'running'
          : (itemStatus === 'failed'
            ? 'failed'
            : (itemStatus === 'ready' || hasRaster
              ? 'ready'
              : (taskStatus === 'running' ? 'queued' : 'missing')))
        return {
          year,
          status,
          label: this.getAgentIterationPoiYearStatusLabel(status),
          resolution: 'cell_id',
          scope: asText(item.grid_scope || yearly.raster_grid_scope) || 'poi_iteration_raster_per_year',
          error: asText(item.error) || (status === 'failed' ? asText(task.error) : ''),
        }
      })
    },
    getAgentIterationPoiRasterGridReadyCount() {
      return this.getAgentIterationPoiRasterGridYearRows()
        .filter((row) => asText(row && row.status) === 'ready')
        .length
    },
    getAgentIterationPoiRasterGridErrorRows() {
      return this.getAgentIterationPoiRasterGridYearRows()
        .filter((row) => !!asText(row && row.error))
    },
    getAgentIterationPoiLatestH3YearLabel() {
      const yearly = this.getAgentIterationPoiYearlyGridEvidence()
      return yearly.latest_year ? `${yearly.latest_year}` : '-'
    },
    getAgentIterationPoiAiSummaryRows() {
      const payload = this.getAgentIterationPoiPayload()
      const rows = cloneArray(payload.ai_summary).map((item) => asText(item)).filter(Boolean)
      if (rows.length) return rows
      return []
    },
    getAgentIterationPoiReportSections() {
      const payload = this.getAgentIterationPoiPayload()
      const sections = cloneArray(payload.report_sections).map((item, idx) => {
        const heading = asText(item && item.heading) || `章节${idx + 1}`
        const paragraphs = cloneArray(item && item.paragraphs).map((paragraph) => asText(paragraph)).filter(Boolean)
        return { key: `report-section-${idx}`, heading, paragraphs }
      }).filter((item) => item.paragraphs.length)
      if (sections.length) return sections
      const content = asText(payload.report_content)
      if (!content) return []
      return [{
        key: 'report-content',
        heading: asText(payload.report_title) || '业态基础分析总结报告',
        paragraphs: content.split(/\n{2,}/).map((item) => asText(item)).filter(Boolean),
      }]
    },
    hasAgentIterationPoiReport() {
      return !!(this.getAgentIterationPoiReportSections().length || asText(this.getAgentIterationPoiPayload().report_content))
    },
    isAgentIterationAiTimeout(error = '') {
      return /ai_timeout/i.test(asText(error))
    },
    getAgentIterationPoiAiStatusText() {
      const payload = this.getAgentIterationPoiPayload()
      if (this.hasAgentIterationPoiReport()) return ''
      if (asText(payload.ai_status) === 'loading') return '基础统计已完成，AI 深度解读正在生成。'
      if (this.isAgentIterationAiTimeout(payload.ai_error)) return '基础统计和快照已完成，AI 深度解读仍在补充。'
      if (payload.ai_error) return this.getAgentIterationAiErrorLabel(payload.ai_error)
      return '基础统计已完成，等待 AI 深度解读。'
    },
    shouldShowAgentIterationPoiAiPlaceholder() {
      const payload = this.getAgentIterationPoiPayload()
      return asText(payload.status) === 'ready'
        && !cloneArray(payload.ai_summary).length
        && !this.hasAgentIterationPoiReport()
        && !asText(payload.ai_error)
    },
    getAgentIterationPoiAiInsightRows() {
      const payload = this.getAgentIterationPoiPayload()
      const insights = cloneObject(payload.ai_insights)
      const pickInsightValue = (key) => insights[key] || ''
      const normalizeGrowthAreaValue = (value) => {
        const text = formatInsightValue(value)
        if (!text) return ''
        const hasOldAreaTerm = text.includes('新兴区域') || text.includes('新兴片区')
        if (!hasOldAreaTerm) return text
        return text.replaceAll('新兴区域', '增长片区').replaceAll('新兴片区', '增长片区')
      }
      const formatInsightValue = (value) => {
        if (value && typeof value === 'object' && !Array.isArray(value)) {
          const name = asText(value.name || value.area_signal || value.current_structure)
          const category = asText(value.category)
          const subcategory = asText(value.subcategory)
          const area = asText(value.area || value.region || value.direction || value.ring)
          const delta = value.delta ?? value.change ?? ''
          const count = value.count ?? ''
          const evidence = asText(value.evidence || value.reason)
          const interpretation = asText(value.interpretation || value.trend)
          const parts = []
          if (name) parts.push(`判断：${name}`)
          if (category) parts.push(`大类：${category}`)
          if (subcategory) parts.push(`小类：${subcategory}${category && !subcategory.includes(category) ? `（${category}）` : ''}`)
          if (area) parts.push(`区域：${area}`)
          if (delta !== '') parts.push(`变化：${delta}`)
          if (count !== '') parts.push(`数量：${count}`)
          if (evidence) parts.push(`证据：${evidence}`)
          if (interpretation) parts.push(`解读：${interpretation}`)
          return parts.join('；') || JSON.stringify(value)
        }
        if (Array.isArray(value)) return value.map((item) => formatInsightValue(item)).filter(Boolean).join('；')
        return asText(value)
      }
      return [
        { key: 'fastest_growth', label: '增长最快行业', value: formatInsightValue(pickInsightValue('fastest_growth')) },
        { key: 'declining_category', label: '衰退行业', value: formatInsightValue(pickInsightValue('declining_category')) },
        { key: 'emerging_area', label: '增长片区', value: normalizeGrowthAreaValue(pickInsightValue('emerging_area')) },
        { key: 'structure_judgement', label: '结构判断', value: formatInsightValue(pickInsightValue('structure_judgement')) },
      ].filter((item) => item.value)
    },
    getAgentIterationPoiDriverRows() {
      const payload = this.getAgentIterationPoiPayload()
      const rows = cloneArray(payload.driver_analysis).length
        ? cloneArray(payload.driver_analysis)
        : cloneArray(cloneObject(payload.ai_insights).driver_analysis)
      return rows.map((row, idx) => ({
        key: `driver-${idx}`,
        label: asText(row.driver) || `原因${idx + 1}`,
        value: [
          asText(row.evidence) ? `证据：${asText(row.evidence)}` : '',
          asText(row.confidence) ? `置信度：${asText(row.confidence)}` : '',
          asText(row.explanation),
        ].filter(Boolean).join('；'),
      })).filter((row) => row.value)
    },
    getAgentIterationPoiPlanningRows() {
      const payload = this.getAgentIterationPoiPayload()
      const rows = cloneArray(payload.planning_implications).length
        ? cloneArray(payload.planning_implications)
        : cloneArray(cloneObject(payload.ai_insights).planning_implications)
      return rows.map((row, idx) => ({
        key: `planning-${idx}`,
        label: asText(row.implication) || `启示${idx + 1}`,
        value: [
          asText(row.evidence) ? `依据：${asText(row.evidence)}` : '',
          asText(row.suggested_direction) ? `方向：${asText(row.suggested_direction)}` : '',
        ].filter(Boolean).join('；'),
      })).filter((row) => row.value)
    },
    shouldShowAgentIterationPoiInsightPlaceholder() {
      const payload = this.getAgentIterationPoiPayload()
      return asText(payload.status) === 'ready'
        && ['pending', 'loading'].includes(asText(payload.ai_status))
        && !this.getAgentIterationPoiAiInsightRows().length
        && !asText(payload.ai_error)
    },
    isAgentIterationPoiSpatialSignalLoading() {
      const payload = this.getAgentIterationPoiPayload()
      const aiStatus = asText(payload.ai_status)
      return asText(payload.status) === 'ready'
        && ['pending', 'loading'].includes(aiStatus)
        && !cloneArray(payload.subcategory_spatial_trend_rows).length
        && !asText(payload.ai_error)
    },
    getAgentIterationPoiSpatialTrendRows(limit = undefined) {
      const rows = cloneArray(this.getAgentIterationPoiPayload().subcategory_spatial_trend_rows)
        .map((row) => ({
          name: asText(row.name),
          parent: asText(row.parent),
          delta: Number(row.delta || 0),
          dominantDirection: asText(row.dominant_direction),
          secondaryDirection: asText(row.secondary_direction),
          dominantRing: asText(row.dominant_ring),
          centroidShiftDirection: asText(row.centroid_shift_direction),
          centroidShiftM: Number(row.centroid_shift_m || 0),
          hotspotGridCount: Number(row.hotspot_grid_count || 0),
          hotspotGridCountDelta: Number(row.hotspot_grid_count_delta || 0),
          hotspotPattern: asText(row.hotspot_pattern),
          topArea: asText(row.top_area),
        }))
        .filter((row) => row.name)
      const safeLimit = Number(limit)
      return Number.isFinite(safeLimit) && safeLimit > 0 ? rows.slice(0, safeLimit) : rows
    },
    formatAgentIterationPoiSpatialTrend(row = {}) {
      const delta = Number(row.delta || 0)
      const pieces = []
      if (row.dominantDirection) {
        pieces.push(`主导方位 ${row.dominantDirection}${row.secondaryDirection ? `/${row.secondaryDirection}` : ''}`)
      }
      if (row.dominantRing) pieces.push(`圈层 ${row.dominantRing}`)
      if (row.centroidShiftDirection && Number(row.centroidShiftM || 0) > 0) {
        pieces.push(`重心向${row.centroidShiftDirection}移动 ${this.formatAgentIterationMetric(row.centroidShiftM, 0)}米`)
      }
      if (Number.isFinite(Number(row.hotspotGridCount))) {
        const hotspotDelta = Number(row.hotspotGridCountDelta || 0)
        pieces.push(`热点格 ${this.formatAgentIterationMetric(row.hotspotGridCount, 0)}个${hotspotDelta ? `（${hotspotDelta > 0 ? '+' : ''}${hotspotDelta}）` : ''}`)
      }
      if (row.topArea) pieces.push(`主要区域 ${row.topArea}`)
      return `${delta >= 0 ? '+' : ''}${delta}；${pieces.join('；') || '空间变化信号有限'}`
    },
    getAgentIterationPoiSnapshotRows() {
      return cloneArray(this.getAgentIterationPoiPayload().summaries)
    },
    getAgentIterationPoiTotalLineChart() {
      const payload = this.getAgentIterationPoiPayload()
      const series = cloneArray(payload.total_series)
      if (series.length >= 2) return series
      return cloneArray(payload.summaries)
        .filter((item) => item && item.year !== undefined && item.count !== undefined)
        .map((item) => ({ year: item.year, value: Number(item.count || 0) }))
    },
    getAgentIterationPoiCategoryStackChart() {
      return cloneArray(this.getAgentIterationPoiPayload().category_stack)
    },
    getAgentIterationPoiSubcategoryStackChart() {
      return cloneArray(this.getAgentIterationPoiPayload().subcategory_stack)
    },
    getAgentIterationPoiSubcategoryGroups() {
      const payload = this.getAgentIterationPoiPayload()
      const summaries = cloneArray(payload.summaries)
      const latest = summaries[summaries.length - 1] || {}
      const latestTotal = Math.max(1, Number(latest.count || 0))
      const categoryCounts = cloneObject(latest.category_counts)
      const mix = cloneObject(latest.category_to_subcategory_mix)
      const groupMap = new Map()
      Object.entries(mix).forEach(([category, rows]) => {
        const items = cloneArray(rows)
          .map((item) => ({
            name: asText(item.name),
            parent: asText(item.parent || category),
            count: Number(item.count || 0),
            ratio: Number(item.count || 0) / latestTotal,
          }))
          .filter((item) => item.name)
          .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, 'zh-CN'))
        if (items.length) {
          const total = Number(categoryCounts[category] || 0) || items.reduce((sum, item) => sum + Number(item.count || 0), 0)
          groupMap.set(category, { category, total, subcategoryCount: items.length, items })
        }
      })
      if (!groupMap.size) {
        cloneArray(latest.top_subcategories).forEach((item) => {
          const category = asText(item.parent) || '未分类'
          if (!groupMap.has(category)) groupMap.set(category, { category, total: 0, subcategoryCount: 0, items: [] })
          const group = groupMap.get(category)
          const count = Number(item.count || 0)
          group.total += count
          group.items.push({
            name: asText(item.name),
            parent: category,
            count,
            ratio: Number(item.ratio || 0) || count / latestTotal,
          })
          group.subcategoryCount = group.items.length
        })
      }
      return Array.from(groupMap.values())
        .map((group) => ({
          ...group,
          items: cloneArray(group.items).sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, 'zh-CN')),
        }))
        .sort((a, b) => Number(b.total || 0) - Number(a.total || 0) || a.category.localeCompare(b.category, 'zh-CN'))
    },
    getAgentIterationPoiSubcategoryTotal() {
      const payload = this.getAgentIterationPoiPayload()
      const summaries = cloneArray(payload.summaries)
      const latest = summaries[summaries.length - 1] || {}
      const count = Number(latest.subcategory_count)
      if (Number.isFinite(count) && count >= 0) return count
      return this.getAgentIterationPoiSubcategoryGroups().reduce((sum, group) => sum + cloneArray(group.items).length, 0)
    },
    getAgentIterationPoiTopSubcategoryRows(limit = undefined) {
      const payload = this.getAgentIterationPoiPayload()
      const summaries = cloneArray(payload.summaries)
      const latest = summaries[summaries.length - 1] || {}
      const rows = cloneArray(latest.top_subcategories)
      const safeLimit = Number(limit)
      return Number.isFinite(safeLimit) && safeLimit > 0 ? rows.slice(0, safeLimit) : rows
    },
    getAgentIterationPoiStructureSpatialCategories() {
      return this.getAgentIterationPoiSubcategoryGroups()
        .map((group) => ({ category: asText(group.category), total: Number(group.total || 0), subcategoryCount: Number(group.subcategoryCount || 0) }))
        .filter((item) => item.category)
    },
    getAgentIterationPoiStructureSpatialRows() {
      const trendMap = new Map(this.getAgentIterationPoiSpatialTrendRows().map((row) => [row.name, row]))
      const rowMap = new Map()
      this.getAgentIterationPoiSubcategoryGroups().forEach((group) => {
        cloneArray(group.items).forEach((item) => {
          const name = asText(item.name)
          if (!name) return
          const trend = trendMap.get(name) || {}
          const hasSpatialSignal = Boolean(trendMap.has(name))
          rowMap.set(name, {
            name,
            parent: asText(item.parent || group.category || trend.parent) || '未分类',
            count: Number(item.count || 0),
            ratio: Number(item.ratio || 0),
            delta: Number(trend.delta || 0),
            dominantDirection: asText(trend.dominantDirection),
            secondaryDirection: asText(trend.secondaryDirection),
            dominantRing: asText(trend.dominantRing),
            centroidShiftDirection: asText(trend.centroidShiftDirection),
            centroidShiftM: Number(trend.centroidShiftM || 0),
            hotspotGridCount: Number(trend.hotspotGridCount || 0),
            hotspotGridCountDelta: Number(trend.hotspotGridCountDelta || 0),
            hotspotPattern: asText(trend.hotspotPattern),
            topArea: asText(trend.topArea),
            hasSpatialSignal,
          })
        })
      })
      this.getAgentIterationPoiSpatialTrendRows().forEach((trend) => {
        if (rowMap.has(trend.name)) return
        rowMap.set(trend.name, {
          name: trend.name,
          parent: asText(trend.parent) || '未分类',
          count: 0,
          ratio: 0,
          delta: Number(trend.delta || 0),
          dominantDirection: asText(trend.dominantDirection),
          secondaryDirection: asText(trend.secondaryDirection),
          dominantRing: asText(trend.dominantRing),
          centroidShiftDirection: asText(trend.centroidShiftDirection),
          centroidShiftM: Number(trend.centroidShiftM || 0),
          hotspotGridCount: Number(trend.hotspotGridCount || 0),
          hotspotGridCountDelta: Number(trend.hotspotGridCountDelta || 0),
          hotspotPattern: asText(trend.hotspotPattern),
          topArea: asText(trend.topArea),
          hasSpatialSignal: true,
        })
      })
      return Array.from(rowMap.values())
    },
    getAgentIterationPoiStructureSpatialGroups() {
      const state = cloneObject(this.agentIterationPoiStructureSpatialView)
      const category = asText(state.category)
      const sortBy = asText(state.sortBy) || 'count'
      const spatialOnly = Boolean(state.spatialOnly)
      const compare = (a, b) => {
        if (sortBy === 'ratio') return Number(b.ratio || 0) - Number(a.ratio || 0) || Number(b.count || 0) - Number(a.count || 0)
        if (sortBy === 'abs_delta') return Math.abs(Number(b.delta || 0)) - Math.abs(Number(a.delta || 0)) || Number(b.count || 0) - Number(a.count || 0)
        if (sortBy === 'growth') return Number(b.delta || 0) - Number(a.delta || 0) || Number(b.count || 0) - Number(a.count || 0)
        if (sortBy === 'decrease') return Number(a.delta || 0) - Number(b.delta || 0) || Number(b.count || 0) - Number(a.count || 0)
        return Number(b.count || 0) - Number(a.count || 0) || Number(b.ratio || 0) - Number(a.ratio || 0)
      }
      const groups = new Map()
      this.getAgentIterationPoiStructureSpatialRows()
        .filter((row) => (!category || row.parent === category) && (!spatialOnly || row.hasSpatialSignal))
        .sort((a, b) => compare(a, b) || a.name.localeCompare(b.name, 'zh-CN'))
        .forEach((row) => {
          const parent = asText(row.parent) || '未分类'
          if (!groups.has(parent)) groups.set(parent, { category: parent, total: 0, subcategoryCount: 0, rows: [] })
          const group = groups.get(parent)
          group.total += Number(row.count || 0)
          group.rows.push(row)
          group.subcategoryCount = group.rows.length
        })
      return Array.from(groups.values())
        .sort((a, b) => Number(b.total || 0) - Number(a.total || 0) || a.category.localeCompare(b.category, 'zh-CN'))
    },
    getAgentIterationPoiAreaHeatmapCalibratedPayload() {
      return this.getAgentIterationPoiPayload()
    },
    setAgentIterationPoiStructureSpatialViewPatch(patch = {}) {
      const current = cloneObject(this.agentIterationPoiStructureSpatialView)
      const next = { ...current, ...cloneObject(patch) }
      const validSorts = new Set(['count', 'ratio', 'abs_delta', 'growth', 'decrease'])
      const categories = this.getAgentIterationPoiStructureSpatialCategories().map((item) => item.category)
      this.agentIterationPoiStructureSpatialView = {
        category: categories.includes(asText(next.category)) ? asText(next.category) : '',
        sortBy: validSorts.has(asText(next.sortBy)) ? asText(next.sortBy) : 'count',
        spatialOnly: Boolean(next.spatialOnly),
      }
      return this.agentIterationPoiStructureSpatialView
    },
    getAgentIterationPoiAreaHeatmaps() {
      const rows = cloneArray(this.getAgentIterationPoiAreaHeatmapCalibratedPayload().area_heatmaps)
        .filter((row) => row && asText(row.year))
        .sort((a, b) => Number(a.year || 0) - Number(b.year || 0))
      if (!rows.length) return []
      const counts = rows.map((row) => Number(row.point_count || cloneArray(row.points).length || 0))
      const minCount = Math.min(...counts)
      const maxCount = Math.max(...counts)
      const span = Math.max(1, maxCount - minCount)
      let previous = null
      const firstCount = counts[0] || 0
      return rows.map((row, index) => {
        const count = Number(row.point_count || cloneArray(row.points).length || 0)
        const delta = previous ? count - Number(previous.point_count || cloneArray(previous.points).length || 0) : 0
        const ratio = previous && Number(previous.point_count || 0)
          ? delta / Math.max(1, Number(previous.point_count || 0))
          : 0
        previous = row
        return {
          ...row,
          cells: cloneArray(row.cells),
          points: cloneArray(row.points),
          point_count: count,
          delta_from_previous: delta,
          delta_from_first: count - firstCount,
          delta_ratio_from_previous: ratio,
          is_first_year: index === 0,
          count_level: (count - minCount) / span,
        }
      })
    },
    getAgentIterationPoiAreaHeatmapChangeSummary() {
      const rows = this.getAgentIterationPoiAreaHeatmaps()
      if (rows.length < 2) return '展示当前区域全部 POI 的年度空间分布。'
      const first = rows[0]
      const last = rows[rows.length - 1]
      const deltas = rows.slice(1).map((row) => Number(row.delta_from_previous || 0))
      const totalDelta = Number(last.point_count || 0) - Number(first.point_count || 0)
      const trend = deltas.every((delta) => delta > 0)
        ? '持续增长'
        : deltas.every((delta) => delta < 0)
          ? '持续下降'
          : (deltas[0] < 0 && deltas[deltas.length - 1] > 0 ? '先降后回升' : '波动变化')
      return `${first.year}-${last.year} 全部 POI ${trend}，净变化 ${this.formatAgentIterationPoiAreaHeatmapDelta(totalDelta)}。`
    },
    formatAgentIterationPoiAreaHeatmapDelta(value = 0) {
      const number = Number(value || 0)
      if (!Number.isFinite(number) || number === 0) return '持平'
      return `${number > 0 ? '+' : ''}${this.formatAgentIterationMetric(number, 0)}`
    },
    getAgentIterationPoiAreaHeatmapDeltaStateClass(value = 0) {
      const number = Number(value || 0)
      return {
        'is-positive': number > 0,
        'is-negative': number < 0,
        'is-flat': !number,
      }
    },
    getAgentIterationPoiAreaHeatmapHotspotCount(heatmap = {}) {
      return cloneArray(heatmap.cells).length
    },
    isAgentIterationPoiAreaHeatmapCopying(heatmap = {}) {
      return asText(this.agentIterationSnapshotCopyKey) === `poi-area-${asText(heatmap.year)}`
        && /正在复制/.test(asText(this.agentIterationSnapshotCopyStatus))
    },
    isAgentIterationPoiAreaHeatmapCopied(heatmap = {}) {
      return asText(this.agentIterationSnapshotCopyKey) === `poi-area-${asText(heatmap.year)}`
        && /已复制/.test(asText(this.agentIterationSnapshotCopyStatus))
    },
    isAgentIterationPoiAreaHeatmapCopyFailed(heatmap = {}) {
      return asText(this.agentIterationSnapshotCopyKey) === `poi-area-${asText(heatmap.year)}`
        && /失败/.test(asText(this.agentIterationSnapshotCopyStatus))
    },
    getAgentIterationPoiAreaHeatmapCopyLabel(heatmap = {}) {
      if (this.isAgentIterationPoiAreaHeatmapCopying(heatmap)) return '复制中'
      if (this.isAgentIterationPoiAreaHeatmapCopied(heatmap)) return '已复制'
      if (this.isAgentIterationPoiAreaHeatmapCopyFailed(heatmap)) return '复制失败'
      return '点击复制'
    },
    getAgentIterationPoiAreaHeatmapLayerState() {
      const layers = cloneObject(this.agentIterationPoiAreaHeatmapLayers)
      const mode = asText(layers.mode)
      if (mode === 'cells' || mode === 'points') {
        return {
          cells: mode === 'cells',
          points: mode === 'points',
        }
      }
      if (Boolean(layers.cells) && !Boolean(layers.points)) {
        return { cells: true, points: false }
      }
      return {
        cells: false,
        points: true,
      }
    },
    isAgentIterationPoiAreaHeatmapLayerVisible(layer = '') {
      const key = asText(layer)
      const layers = this.getAgentIterationPoiAreaHeatmapLayerState()
      if (!Object.prototype.hasOwnProperty.call(layers, key)) return true
      return Boolean(layers[key])
    },
    getAgentIterationPoiAreaHeatmapLayerLabel(layer = '') {
      const key = asText(layer)
      if (key === 'cells') return '格网'
      if (key === 'points') return '点位'
      return key || '图层'
    },
    toggleAgentIterationPoiAreaHeatmapLayer(layer = '', event = null) {
      if (event && typeof event.preventDefault === 'function') event.preventDefault()
      if (event && typeof event.stopPropagation === 'function') event.stopPropagation()
      const key = asText(layer)
      if (!['cells', 'points'].includes(key)) return this.getAgentIterationPoiAreaHeatmapLayerState()
      this.agentIterationPoiAreaHeatmapLayers = {
        mode: key,
        cells: key === 'cells',
        points: key === 'points',
      }
      return this.agentIterationPoiAreaHeatmapLayers
    },
    getAgentIterationPoiAreaHeatmapBasemap() {
      return cloneObject(this.getAgentIterationPoiAreaHeatmapCalibratedPayload().area_heatmap_basemap)
    },
    hasAgentIterationPoiAreaHeatmapBasemapImage() {
      const basemap = this.getAgentIterationPoiAreaHeatmapBasemap()
      return !!asText(basemap.url)
    },
    getAgentIterationPoiAreaHeatmapViewSize() {
      const basemap = this.getAgentIterationPoiAreaHeatmapBasemap()
      const view = cloneObject(basemap.view)
      const width = Number(view.width || 0)
      const height = Number(view.height || 0)
      if (Number.isFinite(width) && width > 0 && Number.isFinite(height) && height > 0) {
        return { width, height }
      }
      const parts = asText(basemap.view_box).split(/\s+/).map((part) => Number(part)).filter((part) => Number.isFinite(part))
      if (parts.length >= 4 && parts[2] > 0 && parts[3] > 0) {
        return { width: parts[2], height: parts[3] }
      }
      return { width: 100, height: 100 }
    },
    getAgentIterationPoiAreaHeatmapViewBox() {
      const basemap = this.getAgentIterationPoiAreaHeatmapBasemap()
      const viewBox = asText(basemap.view_box)
      if (viewBox) return viewBox
      const size = this.getAgentIterationPoiAreaHeatmapViewSize()
      return `0 0 ${size.width} ${size.height}`
    },
    getAgentIterationPoiAreaHeatmapSvgAttrs() {
      return {
        viewBox: this.getAgentIterationPoiAreaHeatmapViewBox(),
      }
    },
    getAgentIterationPoiAreaHeatmapAspectStyle() {
      const basemap = this.getAgentIterationPoiAreaHeatmapBasemap()
      const aspectRatio = asText(basemap.aspect_ratio)
      if (aspectRatio) return { aspectRatio }
      const size = this.getAgentIterationPoiAreaHeatmapViewSize()
      return { aspectRatio: `${size.width} / ${size.height}` }
    },
    getAgentIterationPoiAreaHeatmapBoundary() {
      return cloneArray(this.getAgentIterationPoiAreaHeatmapCalibratedPayload().area_heatmap_boundary)
    },
    getAgentIterationPoiAreaHeatmapFittedViewBox() {
      const boundary = this.getAgentIterationPoiAreaHeatmapBoundary()
        .map((point) => ({ x: Number(point && point.x), y: Number(point && point.y) }))
        .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y))
      if (boundary.length < 2) {
        const basemap = this.getAgentIterationPoiAreaHeatmapBasemap()
        return asText(basemap.view_box)
      }
      const xs = boundary.map((point) => point.x)
      const ys = boundary.map((point) => point.y)
      const minX = Math.min(...xs)
      const maxX = Math.max(...xs)
      const minY = Math.min(...ys)
      const maxY = Math.max(...ys)
      const width = Math.max(maxX - minX, 1e-6)
      const height = Math.max(maxY - minY, 1e-6)
      const pad = Math.max(width, height) * 0.08
      return [
        Number((minX - pad).toFixed(3)),
        Number((minY - pad).toFixed(3)),
        Number((width + pad * 2).toFixed(3)),
        Number((height + pad * 2).toFixed(3)),
      ].join(' ')
    },
    getAgentIterationPoiAreaHeatmapBoundaryBox() {
      const boundary = this.getAgentIterationPoiAreaHeatmapBoundary()
        .map((point) => ({ x: Number(point && point.x), y: Number(point && point.y) }))
        .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y))
      if (boundary.length < 2) return null
      const xs = boundary.map((point) => point.x)
      const ys = boundary.map((point) => point.y)
      const minX = Math.min(...xs)
      const maxX = Math.max(...xs)
      const minY = Math.min(...ys)
      const maxY = Math.max(...ys)
      return {
        minX,
        maxX,
        minY,
        maxY,
        width: Math.max(maxX - minX, 1e-6),
        height: Math.max(maxY - minY, 1e-6),
      }
    },
    getAgentIterationPoiAreaHeatmapDisplayFrame() {
      return this.getAgentIterationPoiAreaHeatmapViewSize()
    },
    getAgentIterationPoiAreaHeatmapDisplayTransform() {
      if (this.hasAgentIterationPoiAreaHeatmapBasemapImage()) return null
      const box = this.getAgentIterationPoiAreaHeatmapBoundaryBox()
      if (!box) return null
      const frame = this.getAgentIterationPoiAreaHeatmapDisplayFrame()
      const frameWidth = Math.max(1, Number(frame.width || 100))
      const frameHeight = Math.max(1, Number(frame.height || 100))
      const fillRatio = 0.88
      const scale = Math.min(
        Math.max(1e-6, frameWidth * fillRatio) / box.width,
        Math.max(1e-6, frameHeight * fillRatio) / box.height,
      )
      const fittedWidth = box.width * scale
      const fittedHeight = box.height * scale
      return {
        minX: box.minX,
        minY: box.minY,
        scale,
        offsetX: (frameWidth - fittedWidth) / 2,
        offsetY: (frameHeight - fittedHeight) / 2,
      }
    },
    projectAgentIterationPoiAreaHeatmapDisplayPoint(point = {}, transform = null) {
      const x = Number(point && point.x)
      const y = Number(point && point.y)
      if (!Number.isFinite(x) || !Number.isFinite(y)) return { x: 0, y: 0 }
      if (!transform) return { x, y }
      return {
        x: Number((Number(transform.offsetX || 0) + (x - Number(transform.minX || 0)) * Number(transform.scale || 1)).toFixed(3)),
        y: Number((Number(transform.offsetY || 0) + (y - Number(transform.minY || 0)) * Number(transform.scale || 1)).toFixed(3)),
      }
    },
    getAgentIterationPoiAreaHeatmapDisplayBoundary() {
      const transform = this.getAgentIterationPoiAreaHeatmapDisplayTransform()
      return this.getAgentIterationPoiAreaHeatmapBoundary()
        .map((point) => this.projectAgentIterationPoiAreaHeatmapDisplayPoint(point, transform))
    },
    getAgentIterationPoiAreaHeatmapDisplayBoundaryPoints() {
      return this.getAgentIterationPoiAreaHeatmapDisplayBoundary()
        .map((point) => `${Number(point.x || 0).toFixed(2)},${Number(point.y || 0).toFixed(2)}`)
        .join(' ')
    },
    getAgentIterationPoiAreaHeatmapDisplayPoints(heatmap = {}) {
      const transform = this.getAgentIterationPoiAreaHeatmapDisplayTransform()
      const points = cloneArray(heatmap.points)
        .map((point) => ({
          ...point,
          ...this.projectAgentIterationPoiAreaHeatmapDisplayPoint(point, transform),
        }))
      return this.clusterAgentIterationPoiAreaHeatmapDisplayPoints(points)
    },
    clusterAgentIterationPoiAreaHeatmapDisplayPoints(points = []) {
      const rows = cloneArray(points).filter((point) => Number.isFinite(Number(point.x)) && Number.isFinite(Number(point.y)))
      if (rows.length <= 60) {
        return rows.map((point) => ({ ...point, count: 1, radius: 2, opacity: 0.68 }))
      }
      const cellSize = rows.length > 420 ? 8 : rows.length > 180 ? 7 : 6
      const clusters = new Map()
      rows.forEach((point) => {
        const key = `${Math.floor(Number(point.x) / cellSize)}:${Math.floor(Number(point.y) / cellSize)}`
        const cluster = clusters.get(key) || { xSum: 0, ySum: 0, count: 0, points: [] }
        cluster.xSum += Number(point.x)
        cluster.ySum += Number(point.y)
        cluster.count += 1
        cluster.points.push(point)
        clusters.set(key, cluster)
      })
      return [...clusters.values()].map((cluster) => {
        const count = Math.max(1, Number(cluster.count || 0))
        return {
          ...(cluster.points[0] || {}),
          x: Number((cluster.xSum / count).toFixed(3)),
          y: Number((cluster.ySum / count).toFixed(3)),
          count,
          radius: Number(Math.min(5.4, 1.8 + Math.sqrt(count) * 0.72).toFixed(2)),
          opacity: Number(Math.min(0.74, 0.42 + Math.sqrt(count) * 0.045).toFixed(2)),
        }
      })
    },
    getAgentIterationPoiAreaHeatmapDisplayCells(heatmap = {}) {
      const transform = this.getAgentIterationPoiAreaHeatmapDisplayTransform()
      if (!transform) return cloneArray(heatmap.cells)
      return cloneArray(heatmap.cells).map((cell) => {
        const topLeft = this.projectAgentIterationPoiAreaHeatmapDisplayPoint({ x: cell.x, y: cell.y }, transform)
        return {
          ...cell,
          x: topLeft.x,
          y: topLeft.y,
          width: Number((Number(cell.width || 0) * Number(transform.scale || 1)).toFixed(3)),
          height: Number((Number(cell.height || 0) * Number(transform.scale || 1)).toFixed(3)),
        }
      })
    },
    getAgentIterationPoiAreaHeatmapBoundaryPoints() {
      return this.getAgentIterationPoiAreaHeatmapBoundary()
        .map((point) => `${Number(point.x || 0).toFixed(2)},${Number(point.y || 0).toFixed(2)}`)
        .join(' ')
    },
    getAgentIterationPoiAreaHeatmapPolygon() {
      return cloneArray(this.getAgentIterationPoiAreaHeatmapCalibratedPayload().area_heatmap_polygon)
    },
    normalizeAgentPoiAreaHeatmapPolygon(polygon = []) {
      return this.normalizeAgentIterationSnapshotPolygon(polygon)
    },
    getAgentPoiAreaHeatmapSourcePairs(summaries = [], polygon = []) {
      const polygonPairs = this.normalizeAgentPoiAreaHeatmapPolygon(polygon)
      if (polygonPairs.length >= 3) return polygonPairs
      return cloneArray(summaries)
        .flatMap((summary) => cloneArray(summary.points))
        .map((point) => [Number(point && point.lng), Number(point && point.lat)])
        .filter((point) => Number.isFinite(point[0]) && Number.isFinite(point[1]))
    },
    buildAgentPoiAreaHeatmapViewport(summaries = [], polygon = []) {
      const pairs = this.getAgentPoiAreaHeatmapSourcePairs(summaries, polygon)
      if (!pairs.length) return null
      const lngs = pairs.map((point) => Number(point[0])).filter(Number.isFinite)
      const lats = pairs.map((point) => Number(point[1])).filter(Number.isFinite)
      if (!lngs.length || !lats.length) return null
      const minLng = Math.min(...lngs)
      const maxLng = Math.max(...lngs)
      const minLat = Math.min(...lats)
      const maxLat = Math.max(...lats)
      const refLat = (minLat + maxLat) / 2
      const metersPerLon = Math.max(1000, 111320 * Math.abs(Math.cos((refLat * Math.PI) / 180)))
      const projectRaw = (lng, lat) => ({
        x: Number(lng) * metersPerLon,
        y: Number(lat) * 111320,
      })
      const minProjected = projectRaw(minLng, minLat)
      const maxProjected = projectRaw(maxLng, maxLat)
      const rawSpanX = Math.max(maxProjected.x - minProjected.x, 1e-9)
      const rawSpanY = Math.max(maxProjected.y - minProjected.y, 1e-9)
      const viewWidth = 100
      const viewHeight = Math.max(50, Math.min(100, Number((viewWidth * rawSpanY / rawSpanX).toFixed(3))))
      const padding = 6
      const usableWidth = Math.max(1, viewWidth - padding * 2)
      const usableHeight = Math.max(1, viewHeight - padding * 2)
      const scale = Math.min(usableWidth / rawSpanX, usableHeight / rawSpanY)
      const contentWidth = rawSpanX * scale
      const contentHeight = rawSpanY * scale
      return {
        minLng,
        minLat,
        maxLng,
        maxLat,
        refLat,
        metersPerLon,
        minProjected,
        maxProjected,
        rawSpanX,
        rawSpanY,
        view: { width: viewWidth, height: viewHeight },
        padding,
        scale,
        offsetX: (viewWidth - contentWidth) / 2,
        offsetY: (viewHeight - contentHeight) / 2,
      }
    },
    projectAgentPoiAreaHeatmapPoint(lng, lat, viewport = null) {
      if (!viewport) return { x: 0, y: 0 }
      const projected = {
        x: Number(lng) * Number(viewport.metersPerLon || 1),
        y: Number(lat) * 111320,
      }
      const x = Number(viewport.offsetX || 0) + ((projected.x - Number((viewport.minProjected || {}).x || 0)) * Number(viewport.scale || 1))
      const y = Number((viewport.view || {}).height || 100)
        - Number(viewport.offsetY || 0)
        - ((projected.y - Number((viewport.minProjected || {}).y || 0)) * Number(viewport.scale || 1))
      const viewWidth = Math.max(1, Number((viewport.view || {}).width || 100))
      const viewHeight = Math.max(1, Number((viewport.view || {}).height || 100))
      return {
        x: Number(Math.max(0, Math.min(viewWidth, x)).toFixed(3)),
        y: Number(Math.max(0, Math.min(viewHeight, y)).toFixed(3)),
      }
    },
    isAgentPoiAreaHeatmapPointInPolygon(lng, lat, polygon = []) {
      const ring = this.normalizeAgentPoiAreaHeatmapPolygon(polygon)
      if (ring.length < 3) return true
      const x = Number(lng)
      const y = Number(lat)
      if (!Number.isFinite(x) || !Number.isFinite(y)) return false
      let inside = false
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
        const xi = Number(ring[i][0])
        const yi = Number(ring[i][1])
        const xj = Number(ring[j][0])
        const yj = Number(ring[j][1])
        const intersects = ((yi > y) !== (yj > y))
          && (x < ((xj - xi) * (y - yi)) / ((yj - yi) || 1e-12) + xi)
        if (intersects) inside = !inside
      }
      return inside
    },
    buildAgentPoiAreaHeatmapBoundary(polygon = [], viewport = null) {
      return this.normalizeAgentPoiAreaHeatmapPolygon(polygon)
        .map((point) => this.projectAgentPoiAreaHeatmapPoint(point[0], point[1], viewport))
        .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y))
    },
    buildAgentPoiAreaHeatmapBasemap(viewport = null) {
      const view = cloneObject(viewport && viewport.view, { width: 100, height: 100 })
      const width = Math.max(1, Number(view.width || 100))
      const height = Math.max(1, Number(view.height || 100))
      const bounds = viewport
        ? {
            min_lng: Number(Number(viewport.minLng).toFixed(6)),
            min_lat: Number(Number(viewport.minLat).toFixed(6)),
            max_lng: Number(Number(viewport.maxLng).toFixed(6)),
            max_lat: Number(Number(viewport.maxLat).toFixed(6)),
            ref_lat: Number(Number(viewport.refLat).toFixed(6)),
          }
        : {}
      return {
        url: '',
        bounds,
        center: viewport ? [Number(((Number(viewport.minLng) + Number(viewport.maxLng)) / 2).toFixed(6)), Number(((Number(viewport.minLat) + Number(viewport.maxLat)) / 2).toFixed(6))] : [],
        zoom: null,
        size: { width: 640, height: Math.max(320, Math.round(640 * height / width)) },
        source: 'none',
        view: { width, height },
        view_box: `0 0 ${width} ${height}`,
        aspect_ratio: `${width} / ${height}`,
        viewport: {},
      }
    },
    getAgentIterationPoiAreaHeatmapSnapshots() {
      const payload = this.getAgentIterationPoiPayload()
      const byYear = new Map(cloneArray(payload.area_heatmaps).map((row) => [String(row.year), row]))
      return cloneArray(payload.area_heatmap_snapshots).map((snapshot) => {
        const fallback = byYear.get(String(snapshot.year)) || {}
        return {
          year: snapshot.year,
          image_url: asText(snapshot.image_url),
          point_count: Number(snapshot.point_count ?? fallback.point_count ?? 0),
          top_area: asText(snapshot.top_area || fallback.top_area),
          status: asText(snapshot.status) || 'pending',
          error: asText(snapshot.error),
        }
      })
    },
    getAgentIterationPoiAreaHeatmapSnapshot(year) {
      const key = String(year || '')
      return this.getAgentIterationPoiAreaHeatmapSnapshots().find((item) => String(item.year || '') === key) || {}
    },
    getAgentIterationPoiAreaHeatmapSnapshotStatusText(snapshot = {}) {
      const status = asText(snapshot.status)
      if (status === 'ready') return '快照已生成'
      if (status === 'loading') return `${asText(snapshot.year) || '该年份'} 快照生成中`
      if (status === 'failed') return '快照生成失败，已显示矢量兜底'
      return `${asText(snapshot.year) || '该年份'} 等待生成快照`
    },
    getAgentIterationPoiAreaHeatmapCellOpacity(cell = {}) {
      const intensity = Math.max(0, Math.min(1, Number(cell.intensity || 0)))
      return (0.12 + intensity * 0.52).toFixed(3)
    },
    getAgentIterationPoiAreaHeatmapDeltaText(heatmap = {}) {
      const delta = Number(heatmap.delta_from_previous || 0)
      if (!Number.isFinite(delta) || delta === 0) return '首期/持平'
      const ratio = Number(heatmap.delta_ratio_from_previous || 0)
      const ratioText = Number.isFinite(ratio) && ratio
        ? `，${ratio > 0 ? '+' : ''}${Math.round(ratio * 100)}%`
        : ''
      return `${delta > 0 ? '+' : ''}${this.formatAgentIterationMetric(delta, 0)}点${ratioText}`
    },
    getAgentIterationPoiAreaHeatmapDeltaClass(heatmap = {}) {
      const delta = Number(heatmap.delta_from_previous || 0)
      if (delta > 0) return 'positive'
      if (delta < 0) return 'negative'
      return ''
    },
    getAgentIterationPoiAreaHeatmapTrendStyle(heatmap = {}) {
      const level = Math.max(0, Math.min(1, Number(heatmap.count_level || 0)))
      return { width: `${Math.max(8, Math.round(level * 100))}%` }
    },
    buildAgentPoiAreaHeatmapSnapshotPlaceholders(payload = {}) {
      const heatmapByYear = new Map(cloneArray(payload.area_heatmaps).map((row) => [String(row.year), row]))
      return cloneArray(payload.summaries).map((summary) => {
        const fallback = heatmapByYear.get(String(summary.year)) || {}
        return {
          year: summary.year,
          image_url: '',
          point_count: Number(cloneArray(summary.points).length || fallback.point_count || 0),
          top_area: asText((((cloneArray(summary.top_areas)[0] || {})).name) || fallback.top_area),
          status: 'pending',
          error: '',
        }
      })
    },
    getAgentPoiAreaSnapshotCacheKey(payload = {}) {
      const years = cloneArray(payload.years).join(',')
      const polygon = JSON.stringify(cloneArray(payload.area_heatmap_polygon).slice(0, 160))
      const counts = cloneArray(payload.summaries).map((summary) => `${summary.year}:${cloneArray(summary.points).length}`).join(',')
      const size = this.getAgentPoiSnapshotRenderSize(payload)
      return `basemap-points-v4|${size.width}x${size.height}|${asText(payload.historyId || payload.history_id)}|${years}|${counts}|${polygon.length}:${polygon.slice(0, 80)}`
    },
    getAgentPoiAreaHeatmapCalibrationCacheKey(payload = {}) {
      const years = cloneArray(payload.years).join(',')
      const polygon = JSON.stringify(cloneArray(payload.area_heatmap_polygon).slice(0, 220))
      const counts = cloneArray(payload.summaries).map((summary) => `${summary.year}:${cloneArray(summary.points).length}`).join(',')
      return `${asText(payload.historyId || payload.history_id || payload.source)}|${years}|${counts}|${polygon.length}:${polygon.slice(0, 120)}`
    },
    buildAgentPoiAreaHeatmapBasemapFromImage(imageUrl = '', size = {}) {
      const width = Math.max(1, Number(size.width || 760))
      const height = Math.max(1, Number(size.height || 760))
      return {
        url: asText(imageUrl),
        bounds: {},
        center: [],
        zoom: null,
        size: { width, height },
        source: asText(imageUrl) ? 'amap_js_snapshot' : 'none',
        view: { width, height },
        view_box: `0 0 ${width} ${height}`,
        aspect_ratio: `${width} / ${height}`,
        viewport: {},
      }
    },
    getAgentPoiSnapshotRenderSize(payload = {}) {
      const basemap = cloneObject(payload.area_heatmap_basemap)
      const size = cloneObject(basemap.size || basemap.view)
      const width = Math.max(1, Math.round(Number(size.width || 760)))
      const height = Math.max(1, Math.round(Number(size.height || width || 760)))
      return { width, height }
    },
    projectAgentPoiAreaHeatmapLngLatWithMap(map = null, lng, lat) {
      if (!map || typeof map.lngLatToContainer !== 'function' || !window.AMap || typeof AMap.LngLat !== 'function') return null
      const point = map.lngLatToContainer(new AMap.LngLat(Number(lng), Number(lat)))
      const x = Number(point && (point.x ?? point.getX?.()))
      const y = Number(point && (point.y ?? point.getY?.()))
      if (!Number.isFinite(x) || !Number.isFinite(y)) return null
      return { x: Number(x.toFixed(3)), y: Number(y.toFixed(3)) }
    },
    buildAgentPoiAreaHeatmapRowsFromProjectedSummaries(summaries = [], polygon = [], map = null, size = {}) {
      const width = Math.max(1, Number(size.width || 760))
      const height = Math.max(1, Number(size.height || 760))
      const gridSize = 12
      const cellWidth = width / gridSize
      const cellHeight = height / gridSize
      return cloneArray(summaries)
        .filter((summary) => cloneArray(summary.points).length)
        .sort((a, b) => Number(a.year || 0) - Number(b.year || 0))
        .map((summary) => {
          const points = cloneArray(summary.points)
            .filter((point) => this.isAgentPoiAreaHeatmapPointInPolygon(point && point.lng, point && point.lat, polygon))
            .map((point) => {
              const projected = this.projectAgentPoiAreaHeatmapLngLatWithMap(map, point && point.lng, point && point.lat)
              if (!projected) return null
              return {
                x: Math.max(0, Math.min(width, projected.x)),
                y: Math.max(0, Math.min(height, projected.y)),
                area: asText(point.area),
                category: asText(point.category),
                subcategory: asText(point.subcategory),
              }
            })
            .filter(Boolean)
          const cellCounts = new Map()
          points.forEach((point) => {
            const col = Math.max(0, Math.min(gridSize - 1, Math.floor(Number(point.x || 0) / cellWidth)))
            const row = Math.max(0, Math.min(gridSize - 1, Math.floor(Number(point.y || 0) / cellHeight)))
            const key = `${col}:${row}`
            cellCounts.set(key, (cellCounts.get(key) || 0) + 1)
          })
          const maxCellCount = Math.max(1, ...Array.from(cellCounts.values()))
          const cells = Array.from(cellCounts.entries())
            .sort(([a], [b]) => {
              const [aCol, aRow] = a.split(':').map((item) => Number(item))
              const [bCol, bRow] = b.split(':').map((item) => Number(item))
              return aRow - bRow || aCol - bCol
            })
            .map(([key, count]) => {
              const [col, row] = key.split(':').map((item) => Number(item))
              return {
                x: Number((col * cellWidth).toFixed(3)),
                y: Number((row * cellHeight).toFixed(3)),
                width: Number(cellWidth.toFixed(3)),
                height: Number(cellHeight.toFixed(3)),
                count,
                intensity: Number((count / maxCellCount).toFixed(4)),
              }
            })
          return {
            year: summary.year,
            points: points.slice(0, 260),
            cells,
            point_count: points.length,
            top_area: asText(((cloneArray(summary.top_areas)[0] || {}).name)),
          }
        })
    },
    buildAgentPoiAreaHeatmapBoundaryFromMap(polygon = [], map = null, size = {}) {
      const width = Math.max(1, Number(size.width || 760))
      const height = Math.max(1, Number(size.height || 760))
      return this.normalizeAgentPoiAreaHeatmapPolygon(polygon)
        .map((point) => this.projectAgentPoiAreaHeatmapLngLatWithMap(map, point[0], point[1]))
        .filter(Boolean)
        .map((point) => ({
          x: Math.max(0, Math.min(width, point.x)),
          y: Math.max(0, Math.min(height, point.y)),
        }))
    },
    async renderAgentIterationPoiAreaHeatmapCalibration(payload = {}) {
      if (!window.AMap || typeof AMap.Map !== 'function') throw new Error('amap_unavailable')
      if (typeof html2canvas !== 'function') throw new Error('html2canvas_unavailable')
      const summaries = cloneArray(payload.summaries)
      if (!summaries.length) throw new Error('no_summaries')
      const polygonPath = this.normalizeAgentIterationSnapshotPolygon(payload.area_heatmap_polygon)
      const allPoints = summaries.flatMap((summary) => cloneArray(summary.points))
        .filter((point) => Number.isFinite(Number(point && point.lng)) && Number.isFinite(Number(point && point.lat)))
      if (polygonPath.length < 3 && !allPoints.length) throw new Error('no_geometry')
      const size = { width: 760, height: 760 }
      const host = this.getOrCreateAgentIterationPoiSnapshotHost()
      host.innerHTML = ''
      const mapEl = document.createElement('div')
      mapEl.style.cssText = `width:${size.width}px;height:${size.height}px;position:relative;background:#fff;overflow:hidden;`
      host.appendChild(mapEl)

      const overlays = []
      let map = null
      try {
        map = new AMap.Map(mapEl, {
          zoom: 13,
          viewMode: '2D',
          resizeEnable: false,
          features: ['bg', 'point', 'road', 'building'],
        })
        let polygonOverlay = null
        if (polygonPath.length >= 3 && typeof AMap.Polygon === 'function') {
          polygonOverlay = new AMap.Polygon({
            path: polygonPath,
            strokeOpacity: 0,
            fillOpacity: 0,
            zIndex: 1,
          })
          polygonOverlay.setMap(map)
          overlays.push(polygonOverlay)
        }
        const fitMarkers = []
        if (!polygonOverlay && typeof AMap.Marker === 'function') {
          allPoints.slice(0, 1200).forEach((point) => {
            const marker = new AMap.Marker({
              position: [Number(point.lng), Number(point.lat)],
              opacity: 0,
              zIndex: 1,
            })
            marker.setMap(map)
            overlays.push(marker)
            fitMarkers.push(marker)
          })
        }
        if (polygonOverlay && typeof map.setFitView === 'function') {
          map.setFitView([polygonOverlay], false, [32, 32, 32, 32])
        } else if (fitMarkers.length && typeof map.setFitView === 'function') {
          map.setFitView(fitMarkers, false, [32, 32, 32, 32])
        }
        await this.waitForAgentPoiSnapshotPaint(900)
        const boundary = this.buildAgentPoiAreaHeatmapBoundaryFromMap(polygonPath, map, size)
        const rows = this.buildAgentPoiAreaHeatmapRowsFromProjectedSummaries(summaries, polygonPath, map, size)
        overlays.forEach((overlay) => {
          try { if (overlay && typeof overlay.setMap === 'function') overlay.setMap(null) } catch (_) {}
        })
        this.cleanAgentPoiSnapshotMapChrome(mapEl)
        const basemapReady = await this.waitForAgentPoiSnapshotImages(mapEl, 3000)
        if (!basemapReady) throw new Error('basemap_image_load_failed')
        const canvas = await html2canvas(mapEl, {
          useCORS: true,
          backgroundColor: '#ffffff',
          scale: 1,
          logging: false,
          ignoreElements: (element) => this.isAgentPoiSnapshotIgnoredElement(element),
        })
        const imageUrl = canvas && typeof canvas.toDataURL === 'function' ? canvas.toDataURL('image/png') : ''
        if (!asText(imageUrl).startsWith('data:image/png')) throw new Error('snapshot_unavailable')
        if (polygonPath.length >= 3 && boundary.length < 3) throw new Error('boundary_projection_unavailable')
        if (asText(imageUrl).length < 50000) throw new Error('basemap_snapshot_too_small')
        return {
          status: 'ready',
          area_heatmaps: rows,
          area_heatmap_basemap: this.buildAgentPoiAreaHeatmapBasemapFromImage(imageUrl, size),
          area_heatmap_boundary: boundary,
          area_heatmap_polygon: polygonPath,
        }
      } finally {
        overlays.forEach((overlay) => {
          try { if (overlay && typeof overlay.setMap === 'function') overlay.setMap(null) } catch (_) {}
        })
        try { if (map && typeof map.destroy === 'function') map.destroy() } catch (_) {}
        host.innerHTML = ''
      }
    },
    async ensureAgentIterationPoiAreaHeatmapCalibration(payloadArg = null) {
      const payload = payloadArg || this.getAgentIterationPoiPayload()
      if (asText(payload.status) !== 'ready') return payload
      const cacheKey = this.getAgentPoiAreaHeatmapCalibrationCacheKey(payload)
      if (!cacheKey || asText(this.agentIterationPoiAreaHeatmapCalibrationGeneratingKey) === cacheKey) return payload
      const cached = cloneObject((this.agentIterationPoiAreaHeatmapCalibrationCache || {})[cacheKey])
      if (asText(cached.status) === 'ready') return payload
      this.agentIterationPoiAreaHeatmapCalibrationGeneratingKey = cacheKey
      try {
        const calibrated = await this.renderAgentIterationPoiAreaHeatmapCalibration(payload)
        this.agentIterationPoiAreaHeatmapCalibrationCache = {
          ...cloneObject(this.agentIterationPoiAreaHeatmapCalibrationCache),
          [cacheKey]: calibrated,
        }
      } catch (err) {
        const nextCache = cloneObject(this.agentIterationPoiAreaHeatmapCalibrationCache)
        delete nextCache[cacheKey]
        this.agentIterationPoiAreaHeatmapCalibrationCache = nextCache
      } finally {
        if (asText(this.agentIterationPoiAreaHeatmapCalibrationGeneratingKey) === cacheKey) {
          this.agentIterationPoiAreaHeatmapCalibrationGeneratingKey = ''
        }
      }
      return payload
    },
    async ensureAgentIterationPoiAreaHeatmapSnapshots(payloadArg = null) {
      const payload = payloadArg || this.getAgentIterationPoiPayload()
      if (asText(payload.status) !== 'ready') return payload
      const years = cloneArray(payload.summaries).map((summary) => summary.year).filter((year) => asText(year))
      if (!years.length) return payload
      const cacheKey = this.getAgentPoiAreaSnapshotCacheKey(payload)
      if (asText(this.agentIterationPoiSnapshotGeneratingKey) === cacheKey) return payload
      const cached = cloneArray((this.agentIterationPoiSnapshotCache || {})[cacheKey])
      if (cached.length && cached.every((item) => asText(item.status) === 'ready' || asText(item.status) === 'failed')) {
        return this.commitAgentIterationPoiPayload({ area_heatmap_snapshots: cached })
      }

      const placeholders = (cloneArray(payload.area_heatmap_snapshots).length
        ? cloneArray(payload.area_heatmap_snapshots)
        : this.buildAgentPoiAreaHeatmapSnapshotPlaceholders(payload))
        .map((item) => ({
          ...item,
          status: asText(item.image_url) ? 'ready' : 'pending',
          error: '',
        }))
      this.commitAgentIterationPoiPayload({
        area_heatmap_snapshots: placeholders,
      })

      this.agentIterationPoiSnapshotGeneratingKey = cacheKey
      try {
        const snapshots = []
        for (const summary of cloneArray(payload.summaries)) {
          const year = summary.year
          const base = placeholders.find((item) => String(item.year) === String(year)) || {}
          const currentSnapshots = this.getAgentIterationPoiAreaHeatmapSnapshots().length
            ? this.getAgentIterationPoiAreaHeatmapSnapshots()
            : placeholders
          this.commitAgentIterationPoiPayload({ area_heatmap_snapshots: currentSnapshots.map((item) => (
            String(item.year) === String(year) && !asText(item.image_url)
              ? { ...item, status: 'loading', error: '' }
              : item
          )) })
          try {
            const imageUrl = await this.renderAgentIterationPoiAreaSnapshot(summary, payload)
            snapshots.push({
              ...base,
              year,
              image_url: imageUrl,
              point_count: cloneArray(summary.points).length,
              top_area: asText((((cloneArray(summary.top_areas)[0] || {})).name) || base.top_area),
              status: imageUrl ? 'ready' : 'failed',
              error: imageUrl ? '' : 'snapshot_unavailable',
            })
          } catch (err) {
            snapshots.push({
              ...base,
              year,
              image_url: '',
              point_count: cloneArray(summary.points).length,
              top_area: asText((((cloneArray(summary.top_areas)[0] || {})).name) || base.top_area),
              status: 'failed',
              error: asText(err && err.message) || 'snapshot_failed',
            })
          }
          this.commitAgentIterationPoiPayload({ area_heatmap_snapshots: cloneArray(snapshots).concat(
            placeholders.filter((item) => !snapshots.some((snapshot) => String(snapshot.year) === String(item.year)))
          ) })
        }
        this.agentIterationPoiSnapshotCache = {
          ...cloneObject(this.agentIterationPoiSnapshotCache),
          [cacheKey]: snapshots,
        }
        return this.commitAgentIterationPoiPayload({ area_heatmap_snapshots: snapshots })
      } finally {
        if (asText(this.agentIterationPoiSnapshotGeneratingKey) === cacheKey) {
          this.agentIterationPoiSnapshotGeneratingKey = ''
        }
      }
    },
    normalizeAgentIterationSnapshotPolygon(polygon = []) {
      const source = cloneArray(polygon)
      const ring = Array.isArray(source[0]) && Array.isArray(source[0][0]) ? source[0] : source
      return cloneArray(ring)
        .map((point) => [Number(point && point[0]), Number(point && point[1])])
        .filter((point) => Number.isFinite(point[0]) && Number.isFinite(point[1]))
    },
    getOrCreateAgentIterationPoiSnapshotHost() {
      let host = document.getElementById('agentIterationPoiSnapshotHost')
      if (host) return host
      host = document.createElement('div')
      host.id = 'agentIterationPoiSnapshotHost'
      host.style.cssText = 'position:fixed;left:0;top:0;width:760px;height:760px;background:#fff;z-index:-1;pointer-events:none;overflow:hidden;'
      document.body.appendChild(host)
      return host
    },
    waitForAgentPoiSnapshotPaint(ms = 650) {
      return new Promise((resolve) => window.setTimeout(resolve, Math.max(0, Number(ms) || 0)))
    },
    extractAgentPoiSnapshotCssUrls(value = '') {
      const raw = asText(value)
      if (!raw || raw === 'none') return []
      const urls = []
      raw.replace(/url\((['"]?)(.*?)\1\)/g, (_match, _quote, url) => {
        const normalized = asText(url).trim()
        if (normalized) urls.push(normalized)
        return _match
      })
      return urls
    },
    async waitForAgentPoiSnapshotImageUrl(src = '', timeoutMs = 3000) {
      const url = asText(src)
      if (!url || typeof Image === 'undefined') return true
      return await new Promise((resolve) => {
        let settled = false
        const timerApi = typeof window !== 'undefined' ? window : globalThis
        const finish = (ok) => {
          if (settled) return
          settled = true
          if (timer) timerApi.clearTimeout(timer)
          resolve(!!ok)
        }
        const timer = timerApi.setTimeout(() => finish(false), Math.max(250, Number(timeoutMs) || 3000))
        const image = new Image()
        image.crossOrigin = 'anonymous'
        image.onload = async () => {
          try {
            if (typeof image.decode === 'function') await image.decode()
          } catch (_) {}
          finish(true)
        }
        image.onerror = () => finish(false)
        image.src = url
      })
    },
    async waitForAgentPoiSnapshotImages(root = null, timeoutMs = 3000) {
      if (!root || typeof root.querySelectorAll !== 'function') return true
      const urls = new Set()
      const nodes = [root, ...Array.from(root.querySelectorAll('*') || [])]
      nodes.forEach((node) => {
        if (!node) return
        if (node.tagName && String(node.tagName).toLowerCase() === 'img') {
          const src = asText(node.currentSrc || node.src || (node.getAttribute && node.getAttribute('src')))
          if (src) urls.add(src)
        }
        if (node.style && node.style.backgroundImage) {
          this.extractAgentPoiSnapshotCssUrls(node.style.backgroundImage).forEach((url) => urls.add(url))
        }
      })
      const results = await Promise.all(Array.from(urls).map((url) => this.waitForAgentPoiSnapshotImageUrl(url, timeoutMs)))
      return results.every(Boolean)
    },
    isAgentPoiSnapshotIgnoredElement(element = null) {
      if (!element || typeof element.matches !== 'function') return false
      return element.matches('.amap-logo, .amap-copyright, .amap-control, [class^="amap-control"], [class*=" amap-control"]')
    },
    cleanAgentPoiSnapshotMapChrome(root = null) {
      if (!root || typeof root.querySelectorAll !== 'function') return
      root.querySelectorAll('.amap-logo, .amap-copyright, .amap-control, [class^="amap-control"], [class*=" amap-control"]').forEach((node) => {
        if (node && node.style) {
          node.style.display = 'none'
          node.style.visibility = 'hidden'
          node.style.opacity = '0'
        }
      })
    },
    applyAgentPoiSnapshotBasemap(mapEl = null, payload = {}) {
      if (!mapEl || !mapEl.style) return false
      const url = asText((payload.area_heatmap_basemap || {}).url)
      if (!url) return false
      mapEl.style.backgroundImage = `url("${url}")`
      mapEl.style.backgroundSize = '100% 100%'
      mapEl.style.backgroundPosition = 'center'
      mapEl.style.backgroundRepeat = 'no-repeat'
      return true
    },
    buildAgentPoiSnapshotOverlaySvg(map = null, summary = {}, payload = {}) {
      if (!map || typeof map.lngLatToContainer !== 'function') return ''
      const size = this.getAgentPoiSnapshotRenderSize(payload)
      const polygonPath = this.normalizeAgentIterationSnapshotPolygon(payload.area_heatmap_polygon)
      const boundary = this.buildAgentPoiAreaHeatmapBoundaryFromMap(polygonPath, map, size)
      const row = this.buildAgentPoiAreaHeatmapRowsFromProjectedSummaries([summary], polygonPath, map, size)[0] || {}
      const boundaryPoints = boundary.map((point) => `${Number(point.x || 0).toFixed(1)},${Number(point.y || 0).toFixed(1)}`).join(' ')
      const clipId = `poi-snapshot-clip-${asText(summary.year) || 'year'}`
      const points = cloneArray(row.points).slice(0, 900).map((point) => (
        `<circle cx="${Number(point.x || 0).toFixed(1)}" cy="${Number(point.y || 0).toFixed(1)}" r="1.35" fill="#17324d" fill-opacity="0.7" stroke="rgba(255,255,255,0.72)" stroke-width="0.42"></circle>`
      )).join('')
      const clipOpen = boundaryPoints ? `<g clip-path="url(#${clipId})">` : '<g>'
      const defs = boundaryPoints ? `<defs><clipPath id="${clipId}"><polygon points="${boundaryPoints}"></polygon></clipPath></defs>` : ''
      return `
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${size.width} ${size.height}" style="position:absolute;inset:0;width:100%;height:100%;pointer-events:none;">
          ${defs}
          ${clipOpen}${points}</g>
        </svg>
      `
    },
    async renderAgentIterationPoiAreaSnapshot(summary = {}, payload = {}) {
      if (!window.AMap || typeof AMap.Map !== 'function') throw new Error('amap_unavailable')
      if (typeof html2canvas !== 'function') throw new Error('html2canvas_unavailable')
      const points = cloneArray(summary.points).filter((point) => Number.isFinite(Number(point.lng)) && Number.isFinite(Number(point.lat)))
      if (!points.length) throw new Error('no_points')
      const polygonPath = this.normalizeAgentIterationSnapshotPolygon(payload.area_heatmap_polygon)
      const size = this.getAgentPoiSnapshotRenderSize(payload)
      const host = this.getOrCreateAgentIterationPoiSnapshotHost()
      host.innerHTML = ''
      const mapEl = document.createElement('div')
      mapEl.style.cssText = `width:${size.width}px;height:${size.height}px;position:relative;background:#fff;overflow:hidden;`
      const hasFallbackBasemap = this.applyAgentPoiSnapshotBasemap(mapEl, payload)
      host.appendChild(mapEl)

      const overlays = []
      let map = null
      try {
        map = new AMap.Map(mapEl, {
          zoom: 13,
          viewMode: '2D',
          resizeEnable: false,
          features: ['bg', 'point', 'road', 'building'],
        })
        let polygonOverlay = null
        if (polygonPath.length >= 3 && typeof AMap.Polygon === 'function') {
          polygonOverlay = new AMap.Polygon({
            path: polygonPath,
            strokeColor: '#2563eb',
            strokeWeight: 1.5,
            strokeOpacity: 0.95,
            fillColor: '#2563eb',
            fillOpacity: 0.05,
            zIndex: 20,
          })
          polygonOverlay.setMap(map)
          overlays.push(polygonOverlay)
        }
        if (polygonOverlay && typeof map.setFitView === 'function') {
          map.setFitView([polygonOverlay], false, [28, 28, 28, 28])
        } else if (typeof map.setFitView === 'function') {
          map.setFitView(overlays, false, [28, 28, 28, 28])
        }
        if (polygonOverlay && typeof polygonOverlay.setMap === 'function') {
          polygonOverlay.setMap(null)
        }
        await this.waitForAgentPoiSnapshotPaint()
        if (hasFallbackBasemap) {
          const basemapReady = await this.waitForAgentPoiSnapshotImageUrl((payload.area_heatmap_basemap || {}).url, 3000)
          if (!basemapReady) throw new Error('basemap_image_load_failed')
        }
        const overlayHost = document.createElement('div')
        overlayHost.style.cssText = 'position:absolute;inset:0;pointer-events:none;z-index:50;'
        overlayHost.innerHTML = this.buildAgentPoiSnapshotOverlaySvg(map, summary, payload)
        mapEl.appendChild(overlayHost)
        this.cleanAgentPoiSnapshotMapChrome(mapEl)
        const basemapReady = await this.waitForAgentPoiSnapshotImages(mapEl, 3000)
        if (!basemapReady) throw new Error('basemap_image_load_failed')
        const canvas = await html2canvas(mapEl, {
          useCORS: true,
          backgroundColor: '#ffffff',
          scale: 1,
          logging: false,
          ignoreElements: (element) => this.isAgentPoiSnapshotIgnoredElement(element),
        })
        const dataUrl = canvas && typeof canvas.toDataURL === 'function' ? canvas.toDataURL('image/png') : ''
        return asText(dataUrl).startsWith('data:image/png') ? dataUrl : ''
      } finally {
        overlays.forEach((overlay) => {
          try { if (overlay && typeof overlay.setMap === 'function') overlay.setMap(null) } catch (_) {}
        })
        try { if (map && typeof map.destroy === 'function') map.destroy() } catch (_) {}
        host.innerHTML = ''
      }
    },
    getAgentIterationPoiLineChartPoints() {
      const series = this.getAgentIterationPoiTotalLineChart()
      if (!series.length) return []
      const values = series.map((item) => Number(item.value || 0))
      const minValue = Math.min(...values)
      const maxValue = Math.max(...values)
      const span = Math.max(maxValue - minValue, 1)
      const width = 320
      const height = 140
      const padX = 18
      const padY = 18
      const step = series.length > 1 ? (width - padX * 2) / (series.length - 1) : 0
      return series.map((item, index) => ({
        year: item.year,
        value: Number(item.value || 0),
        x: padX + step * index,
        y: height - padY - ((Number(item.value || 0) - minValue) / span) * (height - padY * 2),
      }))
    },
    getAgentIterationPoiLineChartPolyline() {
      return this.getAgentIterationPoiLineChartPoints()
        .map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`)
        .join(' ')
    },
    getAgentIterationPoiCategoryLegend() {
      const names = []
      this.getAgentIterationPoiCategoryStackChart().forEach((row) => {
        cloneArray(row.segments).forEach((segment) => {
          const name = asText(segment.name)
          if (name && !names.includes(name)) names.push(name)
        })
      })
      return names
    },
    getAgentIterationCategoryColor(name = '') {
      const palette = ['#2563eb', '#f97316', '#16a34a', '#9333ea', '#dc2626', '#94a3b8']
      const legend = this.getAgentIterationPoiCategoryLegend()
      const index = Math.max(0, legend.indexOf(asText(name)))
      return palette[index % palette.length]
    },
    setAgentIterationKind(kind = '') {
      const next = asText(kind) || 'nightlight'
      if (!this.getAgentIterationKinds().some((item) => item.key === next && !item.disabled)) return
      this.agentIterationActiveKind = next
      const nextSecondary = this.getAgentIterationSecondaryView(next)
      if (!nextSecondary) this.setAgentIterationSecondaryView((this.getAgentIterationSecondaryNavItems(next)[0] || {}).key, next)
      const tabs = this.ensureAgentTabs(true)
      const activeId = asText(tabs.activeTabId)
      tabs.iterationChangeTabs = cloneArray(tabs.iterationChangeTabs).map((item) => (
        item.id === activeId ? { ...item, activeKind: next } : item
      ))
      this.agentTabs = { ...tabs, iterationChangeTabs: cloneArray(tabs.iterationChangeTabs) }
      this.ensureAgentIterationKind(next).catch((err) => {
        console.warn('[Agent] iteration kind load failed:', err)
      })
    },
    ensureAgentIterationKind(kind = '', force = false) {
      const next = asText(kind || this.agentIterationActiveKind) || 'poi'
      if (next === 'poi') return this.ensureAgentIterationPoi(force)
      if (next === 'population') return this.ensureAgentIterationPopulation(force)
      return this.ensureAgentIterationNightlight(force)
    },
    resetAgentIterationChangeForHistorySwitch(historyId = '', options = {}) {
      const nextHistoryId = asText(historyId)
      if (!nextHistoryId) return false
      const previousHistoryId = asText(options.previousHistoryId || options.previous_history_id)
      if (previousHistoryId && previousHistoryId === nextHistoryId) return false

      const notice = '已切换历史记录，请重新生成多年迭代变化。'
      const now = new Date().toISOString()
      const buildIdlePayload = (kind) => ({
        status: 'idle',
        historyId: nextHistoryId,
        history_id: nextHistoryId,
        notice,
        error: '',
        reset_reason: 'history_switch',
        kind,
        updated_at: now,
      })
      const resetRoot = {
        poi: buildIdlePayload('poi'),
        population: buildIdlePayload('population'),
        nightlight: buildIdlePayload('nightlight'),
      }
      const resetPanelPayloads = (panelPayloads = {}) => ({
        ...cloneObject(panelPayloads),
        iteration_change: cloneObject(resetRoot),
      })

      const tabs = this.ensureAgentTabs(true)
      const iterationTabs = cloneArray(tabs.iterationChangeTabs)
      tabs.iterationChangeTabs = iterationTabs.map((item) => ({
        ...item,
        panelPayloads: resetPanelPayloads(item && item.panelPayloads),
      }))
      this.agentTabs = { ...tabs, iterationChangeTabs: cloneArray(tabs.iterationChangeTabs) }

      this.agentPanelPayloads = resetPanelPayloads(this.agentPanelPayloads)
      if (asText(this.getAgentActiveTopTab().kind) === 'iteration_change') {
        const activeId = asText(this.getAgentActiveTopTab().id)
        const activeTab = cloneArray(this.agentTabs.iterationChangeTabs).find((item) => item.id === activeId)
        if (activeTab && activeTab.panelPayloads && typeof activeTab.panelPayloads === 'object') {
          this.agentPanelPayloads = cloneObject(activeTab.panelPayloads)
        }
      }

      this.agentIterationPoiLoading = false
      this.agentIterationPoiError = ''
      this.agentIterationPopulationLoading = false
      this.agentIterationPopulationError = ''
      this.agentIterationNightlightLoading = false
      this.agentIterationNightlightError = ''
      if (typeof this.syncCurrentAgentSession === 'function') {
        this.syncCurrentAgentSession()
      }
      return true
    },
    async requestAgentPopulationTimeseries(period) {
      const polygon = this.getIsochronePolygonPayload()
      const res = await fetch('/api/v1/analysis/timeseries/population', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          polygon,
          coord_type: 'gcj02',
          period,
          layer_view: 'population_delta',
        }),
      })
      if (!res.ok) {
        let detail = ''
        try { detail = await res.text() } catch (_) {}
        throw new Error(detail || '人口时序变化请求失败')
      }
      return res.json()
    },
    commitAgentIterationPayload(kind = 'nightlight', patch = {}, options = {}) {
      const normalizedKind = asText(kind) || 'nightlight'
      const tabs = this.ensureAgentTabs(true)
      const activeId = asText(options.tabId) || asText(tabs.activeTabId)
      const targetTab = cloneArray(tabs.iterationChangeTabs).find((item) => item.id === activeId)
      const currentPayloads = targetTab && targetTab.panelPayloads && typeof targetTab.panelPayloads === 'object'
        ? cloneObject(targetTab.panelPayloads)
        : cloneObject(this.agentPanelPayloads)
      const currentRoot = cloneObject(currentPayloads.iteration_change)
      const nextPayload = {
        ...cloneObject(currentRoot[normalizedKind]),
        ...cloneObject(patch),
        updated_at: new Date().toISOString(),
      }
      const nextPayloads = {
        ...currentPayloads,
        iteration_change: {
          ...currentRoot,
          [normalizedKind]: nextPayload,
        },
      }
      tabs.iterationChangeTabs = cloneArray(tabs.iterationChangeTabs).map((item) => (
        item.id === activeId ? { ...item, panelPayloads: cloneObject(nextPayloads), activeKind: normalizedKind } : item
      ))
      this.agentTabs = { ...tabs, iterationChangeTabs: cloneArray(tabs.iterationChangeTabs) }
      if (asText(tabs.activeTabId) === activeId) {
        this.agentPanelPayloads = nextPayloads
      }
      this.syncCurrentAgentSession()
      return nextPayload
    },
    commitAgentIterationPopulationPayload(patch = {}, options = {}) {
      return this.commitAgentIterationPayload('population', patch, options)
    },
    commitAgentIterationPoiPayload(patch = {}, options = {}) {
      return this.commitAgentIterationPayload('poi', patch, options)
    },
    clearAgentIterationPoiNoticeIfReady(options = {}) {
      const readiness = this.getAgentIterationPoiReadiness()
      if (!readiness.ready) return this.getAgentIterationPoiPayload()
      return this.commitAgentIterationPoiPayload({ notice: '', error: '' }, options)
    },
    async ensureAgentIterationPopulation(force = false) {
      if (!this.getIsochronePolygonRing || !this.getIsochronePolygonRing()) {
        this.agentIterationPopulationError = '请先生成或选择分析范围'
        return null
      }
      const existing = this.getAgentIterationPopulationPayload()
      if (!force && asText(existing.status) === 'ready') return existing
      if (this.agentIterationPopulationLoading) return existing
      const targetTabId = asText(this.getAgentActiveTopTab().kind) === 'iteration_change'
        ? asText(this.getAgentActiveTopTab().id)
        : ''
      this.agentIterationPopulationLoading = true
      this.agentIterationPopulationError = ''
      this.commitAgentIterationPopulationPayload({ status: 'loading', error: '' }, { tabId: targetTabId })
      try {
        const metaRes = await fetch('/api/v1/analysis/timeseries/meta')
        if (!metaRes.ok) throw new Error(`/api/v1/analysis/timeseries/meta 请求失败(${metaRes.status})`)
        const meta = await metaRes.json()
        const period = asText(meta.default_population_period)
          || asText((cloneArray(meta.population_periods).slice(-1)[0] || {}).value)
          || '2024-2026'
        const timeseries = await this.requestAgentPopulationTimeseries(period)
        return this.commitAgentIterationPopulationPayload({
          status: 'ready',
          period,
          timeseries,
          series: cloneArray(timeseries.series),
          insights: cloneArray(timeseries.insights),
          error: '',
        }, { tabId: targetTabId })
      } catch (err) {
        const message = asText(err && err.message) || String(err)
        this.agentIterationPopulationError = message
        return this.commitAgentIterationPopulationPayload({ status: 'failed', error: message }, { tabId: targetTabId })
      } finally {
        this.agentIterationPopulationLoading = false
      }
    },
    getAgentPoiCategoryName(poi = {}) {
      return this.getAgentPoiTypeBreakdown(poi).category
    },
    getAgentPoiTypeBreakdown(poi = {}) {
      const rawType = asText(poi.type || poi.typecode || poi.type_code)
      let subcategoryId = ''
      if (rawType && typeof this.resolvePoiTypeId === 'function') {
        subcategoryId = asText(this.resolvePoiTypeId(rawType))
      }
      if (subcategoryId) {
        const subcategory = typeof this.getPoiTypeLabel === 'function'
          ? asText(this.getPoiTypeLabel(subcategoryId))
          : subcategoryId
        const parentId = this.typeIdToGroupId && this.typeIdToGroupId[subcategoryId]
          ? asText(this.typeIdToGroupId[subcategoryId])
          : ''
        const category = parentId && this.categoryById && this.categoryById[parentId]
          ? asText(this.categoryById[parentId].name)
          : (rawType && typeof this.resolvePoiCategory === 'function'
              ? asText((this.resolvePoiCategory(rawType) || {}).name)
              : '')
        return {
          category: category || '未分类',
          subcategory: subcategory || '未分类小类',
          subcategory_id: subcategoryId,
          raw_type: rawType,
        }
      }
      if (rawType && typeof this.resolvePoiCategory === 'function') {
        const category = this.resolvePoiCategory(rawType)
        if (category && category.name) {
          return {
            category: asText(category.name),
            subcategory: '未分类小类',
            subcategory_id: '',
            raw_type: rawType,
          }
        }
      }
      const labels = rawType.split(/[;|,，/]/).map((item) => asText(item)).filter(Boolean)
      return {
        category: labels[0] || '未分类',
        subcategory: labels[1] || labels[0] || '未分类小类',
        subcategory_id: '',
        raw_type: rawType,
      }
    },
    summarizeAgentIterationPois(pois = [], year = null) {
      const categoryCounts = new Map()
      const subcategoryCounts = new Map()
      const subcategoryParentMap = new Map()
      const categoryToSubcategoryCounts = new Map()
      const areaCounts = new Map()
      const points = []
      cloneArray(pois).forEach((poi) => {
        const typeInfo = this.getAgentPoiTypeBreakdown(poi)
        const category = asText(typeInfo.category) || '未分类'
        const subcategory = asText(typeInfo.subcategory) || '未分类小类'
        categoryCounts.set(category, (categoryCounts.get(category) || 0) + 1)
        subcategoryCounts.set(subcategory, (subcategoryCounts.get(subcategory) || 0) + 1)
        if (!subcategoryParentMap.has(subcategory)) subcategoryParentMap.set(subcategory, category)
        if (!categoryToSubcategoryCounts.has(category)) categoryToSubcategoryCounts.set(category, new Map())
        const childCounts = categoryToSubcategoryCounts.get(category)
        childCounts.set(subcategory, (childCounts.get(subcategory) || 0) + 1)
        const area = asText(poi.adname || poi.cityname || poi.pname) || '未知区域'
        areaCounts.set(area, (areaCounts.get(area) || 0) + 1)
        const location = Array.isArray(poi && poi.location) ? poi.location : []
        const lng = Number(location[0])
        const lat = Number(location[1])
        if (Number.isFinite(lng) && Number.isFinite(lat)) {
          points.push({ lng, lat, category, subcategory, area })
        }
      })
      const total = Math.max(1, cloneArray(pois).length)
      const sortCounts = (map, extra = () => ({})) => Array.from(map.entries())
        .map(([name, count]) => ({ name, count, ratio: Number(count || 0) / total, ...extra(name, count) }))
        .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, 'zh-CN'))
      const categoryToSubcategoryMix = {}
      categoryToSubcategoryCounts.forEach((childMap, category) => {
        const categoryTotal = Math.max(1, Number(categoryCounts.get(category) || 0))
        categoryToSubcategoryMix[category] = Array.from(childMap.entries())
          .map(([name, count]) => ({
            name,
            parent: category,
            count,
            ratio: Number(count || 0) / categoryTotal,
          }))
          .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, 'zh-CN'))
      })
      return {
        year: Number.isFinite(Number(year)) ? Number(year) : null,
        count: cloneArray(pois).length,
        category_count: categoryCounts.size,
        subcategory_count: subcategoryCounts.size,
        top_categories: sortCounts(categoryCounts).slice(0, 5),
        top_subcategories: sortCounts(subcategoryCounts, (name) => ({ parent: subcategoryParentMap.get(name) || '未分类' })),
        top_areas: sortCounts(areaCounts).slice(0, 5),
        category_counts: Object.fromEntries(categoryCounts.entries()),
        subcategory_counts: Object.fromEntries(subcategoryCounts.entries()),
        category_to_subcategory_mix: categoryToSubcategoryMix,
        area_counts: Object.fromEntries(areaCounts.entries()),
        points,
      }
    },
    buildAgentPoiCategoryStack(summaries = []) {
      const sorted = cloneArray(summaries).filter((item) => item && item.category_counts).sort((a, b) => Number(a.year || 0) - Number(b.year || 0))
      if (sorted.length < 2) return []
      const totals = new Map()
      sorted.forEach((summary) => {
        Object.entries(cloneObject(summary.category_counts)).forEach(([name, count]) => {
          totals.set(name, (totals.get(name) || 0) + Number(count || 0))
        })
      })
      const topNames = Array.from(totals.entries())
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'zh-CN'))
        .slice(0, 5)
        .map(([name]) => name)
      return sorted.map((summary) => {
        const counts = cloneObject(summary.category_counts)
        const total = Math.max(1, Number(summary.count || 0))
        const segments = topNames.map((name) => ({
          name,
          count: Number(counts[name] || 0),
          ratio: Number(counts[name] || 0) / total,
        }))
        const known = segments.reduce((sum, item) => sum + item.count, 0)
        if (Math.max(0, Number(summary.count || 0) - known) > 0) {
          segments.push({
            name: '其他',
            count: Math.max(0, Number(summary.count || 0) - known),
            ratio: Math.max(0, Number(summary.count || 0) - known) / total,
          })
        }
        return { year: summary.year, total: Number(summary.count || 0), segments }
      })
    },
    buildAgentPoiSubcategoryStack(summaries = []) {
      const sorted = cloneArray(summaries).filter((item) => item && item.subcategory_counts).sort((a, b) => Number(a.year || 0) - Number(b.year || 0))
      if (sorted.length < 2) return []
      const totals = new Map()
      const parentByName = new Map()
      sorted.forEach((summary) => {
        cloneArray(summary.top_subcategories).forEach((item) => {
          if (item && item.name && !parentByName.has(item.name)) parentByName.set(item.name, item.parent || '')
        })
        Object.entries(cloneObject(summary.subcategory_counts)).forEach(([name, count]) => {
          totals.set(name, (totals.get(name) || 0) + Number(count || 0))
        })
      })
      const topNames = Array.from(totals.entries())
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'zh-CN'))
        .slice(0, 6)
        .map(([name]) => name)
      return sorted.map((summary) => {
        const counts = cloneObject(summary.subcategory_counts)
        const total = Math.max(1, Number(summary.count || 0))
        const segments = topNames.map((name) => ({
          name,
          parent: parentByName.get(name) || '',
          count: Number(counts[name] || 0),
          ratio: Number(counts[name] || 0) / total,
        }))
        const known = segments.reduce((sum, item) => sum + item.count, 0)
        if (Math.max(0, Number(summary.count || 0) - known) > 0) {
          segments.push({
            name: '其他小类',
            parent: '',
            count: Math.max(0, Number(summary.count || 0) - known),
            ratio: Math.max(0, Number(summary.count || 0) - known) / total,
          })
        }
        return { year: summary.year, total: Number(summary.count || 0), segments }
      })
    },
    buildAgentPoiAreaHeatmaps(summaries = [], polygon = []) {
      const sorted = cloneArray(summaries).filter((item) => cloneArray(item.points).length).sort((a, b) => Number(a.year || 0) - Number(b.year || 0))
      if (!sorted.length) return []
      const viewport = this.buildAgentPoiAreaHeatmapViewport(sorted, polygon)
      if (!viewport) return []
      const view = cloneObject(viewport.view, { width: 100, height: 100 })
      const viewWidth = Math.max(1, Number(view.width || 100))
      const viewHeight = Math.max(1, Number(view.height || 100))
      return sorted.map((summary) => {
        const points = cloneArray(summary.points)
          .filter((point) => this.isAgentPoiAreaHeatmapPointInPolygon(point && point.lng, point && point.lat, polygon))
          .map((point) => ({
            ...this.projectAgentPoiAreaHeatmapPoint(point.lng, point.lat, viewport),
            area: asText(point.area),
            category: asText(point.category),
            subcategory: asText(point.subcategory),
          }))
        const gridSize = 12
        const cellCounts = new Map()
        const cellWidth = viewWidth / gridSize
        const cellHeight = viewHeight / gridSize
        points.forEach((point) => {
          const col = Math.max(0, Math.min(gridSize - 1, Math.floor(Number(point.x || 0) / cellWidth)))
          const row = Math.max(0, Math.min(gridSize - 1, Math.floor(Number(point.y || 0) / cellHeight)))
          const key = `${col}:${row}`
          cellCounts.set(key, (cellCounts.get(key) || 0) + 1)
        })
        const maxCellCount = Math.max(1, ...Array.from(cellCounts.values()))
        const cells = Array.from(cellCounts.entries())
          .map(([key, count]) => {
            const [col, row] = key.split(':').map((item) => Number(item))
            return {
              x: Number((col * cellWidth).toFixed(3)),
              y: Number((row * cellHeight).toFixed(3)),
              width: Number(cellWidth.toFixed(3)),
              height: Number(cellHeight.toFixed(3)),
              count,
              intensity: Number((count / maxCellCount).toFixed(4)),
            }
          })
          .sort((a, b) => Number(a.y || 0) - Number(b.y || 0) || Number(a.x || 0) - Number(b.x || 0))
        return {
          year: summary.year,
          points: points.slice(0, 260),
          cells,
          point_count: points.length,
          top_area: ((cloneArray(summary.top_areas)[0] || {}).name) || '',
        }
      })
    },
    buildAgentPoiAreaHeatmapBundle(summaries = [], polygon = []) {
      const normalizedPolygon = this.normalizeAgentPoiAreaHeatmapPolygon(polygon)
      const viewport = this.buildAgentPoiAreaHeatmapViewport(summaries, normalizedPolygon)
      return {
        area_heatmaps: this.buildAgentPoiAreaHeatmaps(summaries, normalizedPolygon),
        area_heatmap_basemap: this.buildAgentPoiAreaHeatmapBasemap(viewport),
        area_heatmap_boundary: normalizedPolygon.length >= 3 ? this.buildAgentPoiAreaHeatmapBoundary(normalizedPolygon, viewport) : [],
        area_heatmap_polygon: normalizedPolygon,
      }
    },
    buildAgentPoiRuleInsights(summaries = []) {
      const sorted = cloneArray(summaries).filter((item) => item && item.count !== undefined).sort((a, b) => Number(a.year || 0) - Number(b.year || 0))
      const latest = sorted[sorted.length - 1] || {}
      const formatTopSubcategories = (summary = {}, limit = 3) => cloneArray(summary.top_subcategories)
        .slice(0, limit)
        .map((item) => `${item.name}${item.parent ? `（${item.parent}）` : ''}`)
        .join('、')
      if (sorted.length < 2) {
        const topCategory = (cloneArray(latest.top_categories)[0] || {})
        const topSubcategory = (cloneArray(latest.top_subcategories)[0] || {})
        const subcategoryText = formatTopSubcategories(latest)
        const topArea = (cloneArray(latest.top_areas)[0] || {})
        return {
          summary: [
            `当前POI规模为 ${this.formatAgentIterationMetric(latest.count, 0)}，一级主导业态为${topCategory.name || '未分类'}。`,
            subcategoryText ? `关键小类集中在${subcategoryText}。` : '当前小类结构信号有限。',
            `${topArea.name || '主要区域'}为核心聚集区，呈现当前POI的主要空间承载。`,
          ],
          insights: {
            fastest_growth: '当前只有一个年份，暂无法判断增长最快行业。',
            declining_category: '当前只有一个年份，暂无法判断衰退行业。',
            emerging_area: topArea.name ? `当前核心承载片区：${topArea.name}` : '当前缺少可识别的增长片区信号。',
            structure_judgement: topCategory.name ? `一级业态以${topCategory.name}为主${topSubcategory.name ? `，内部小类以${topSubcategory.name}较突出` : ''}。` : '业态结构信号有限。',
          },
        }
      }
      const first = sorted[0]
      const last = sorted[sorted.length - 1]
      const firstCounts = cloneObject(first.category_counts)
      const lastCounts = cloneObject(last.category_counts)
      const firstSubCounts = cloneObject(first.subcategory_counts)
      const lastSubCounts = cloneObject(last.subcategory_counts)
      const names = Array.from(new Set([...Object.keys(firstCounts), ...Object.keys(lastCounts)]))
      const changes = names.map((name) => {
        const before = Number(firstCounts[name] || 0)
        const after = Number(lastCounts[name] || 0)
        return {
          name,
          before,
          after,
          delta: after - before,
          rate: before > 0 ? ((after - before) / before) : (after > 0 ? 1 : 0),
        }
      })
      const fastest = changes.filter((item) => item.delta > 0).sort((a, b) => b.rate - a.rate || b.delta - a.delta)[0]
      const declining = changes.filter((item) => item.delta < 0).sort((a, b) => a.rate - b.rate || a.delta - b.delta)[0]
      const subNames = Array.from(new Set([...Object.keys(firstSubCounts), ...Object.keys(lastSubCounts)]))
      const subChanges = subNames.map((name) => {
        const before = Number(firstSubCounts[name] || 0)
        const after = Number(lastSubCounts[name] || 0)
        const parent = ((cloneArray(last.top_subcategories).find((item) => item.name === name) || cloneArray(first.top_subcategories).find((item) => item.name === name) || {}).parent) || ''
        return {
          name,
          parent,
          before,
          after,
          delta: after - before,
          rate: before > 0 ? ((after - before) / before) : (after > 0 ? 1 : 0),
        }
      })
      const fastestSubcategory = subChanges.filter((item) => item.delta > 0).sort((a, b) => b.rate - a.rate || b.delta - a.delta)[0]
      const decliningSubcategory = subChanges.filter((item) => item.delta < 0).sort((a, b) => a.rate - b.rate || a.delta - b.delta)[0]
      const firstAreas = cloneObject(first.area_counts)
      const lastAreas = cloneObject(last.area_counts)
      const areaNames = Array.from(new Set([...Object.keys(firstAreas), ...Object.keys(lastAreas)]))
      const growthArea = areaNames.map((name) => ({
        name,
        before: Number(firstAreas[name] || 0),
        after: Number(lastAreas[name] || 0),
        delta: Number(lastAreas[name] || 0) - Number(firstAreas[name] || 0),
      })).filter((item) => item.delta > 0).sort((a, b) => b.delta - a.delta)[0]
      const growthAreaText = growthArea
        ? `growth_area=${growthArea.name}; delta=${growthArea.delta}.`
        : 'growth_area=-; named_growth_area=false.'
      const topCategory = (cloneArray(last.top_categories)[0] || {})
      const topSubcategory = (cloneArray(last.top_subcategories)[0] || {})
      const topArea = (cloneArray(last.top_areas)[0] || {})
      const topRatio = Number(last.count || 0) > 0 ? Number(topCategory.count || 0) / Number(last.count || 0) : 0
      const totalDelta = Number(last.count || 0) - Number(first.count || 0)
      const subcategoryText = formatTopSubcategories(last)
      return {
        summary: [
          `当前POI规模为 ${this.formatAgentIterationMetric(last.count, 0)}，较${first.year || '首年'}${totalDelta >= 0 ? '增加' : '减少'} ${this.formatAgentIterationMetric(Math.abs(totalDelta), 0)}。`,
          `top_category=${topCategory.name || '-'}; top_category_ratio=${(topRatio * 100).toFixed(1)}%.`,
          subcategoryText ? `top_subcategories=${subcategoryText}.` : 'top_subcategories=-.',
          `top_area=${topArea.name || '-'}.`,
          `top_category_ratio_signal=${topRatio >= 0.25 ? 'ge_0_25' : 'lt_0_25'}.`,
        ],
        insights: {
          fastest_growth: fastest ? `category=${fastest.name}; delta=${fastest.delta}; rate=${(fastest.rate * 100).toFixed(1)}%; subcategory=${fastestSubcategory ? fastestSubcategory.name : '-'}.` : 'fastest_growth=-.',
          declining_category: declining ? `category=${declining.name}; delta=${declining.delta}; rate=${(declining.rate * 100).toFixed(1)}%; subcategory=${decliningSubcategory ? decliningSubcategory.name : '-'}.` : 'declining_category=-.',
          emerging_area: growthAreaText,
          structure_judgement: topCategory.name ? `top_category=${topCategory.name}; top_subcategory=${topSubcategory.name || '-'}.` : 'top_category=-.',
        },
      }
    },
    compactAgentPoiIterationH3Evidence(value = {}, cellLimit = 40, rowLimit = 20) {
      const source = cloneObject(value || {})
      const pickNumber = (item) => {
        const parsed = Number(item)
        return Number.isFinite(parsed) ? parsed : null
      }
      const pickCell = (cell = {}) => {
        const props = cell && typeof cell.properties === 'object' ? cell.properties : cell
        const h3Id = asText(props && props.h3_id)
        if (!h3Id) return null
        return {
          h3_id: h3Id,
          poi_count: pickNumber(props.poi_count),
          density_poi_per_km2: pickNumber(props.density_poi_per_km2),
          local_entropy: pickNumber(props.local_entropy),
          neighbor_mean_density: pickNumber(props.neighbor_mean_density),
          neighbor_mean_entropy: pickNumber(props.neighbor_mean_entropy),
          neighbor_count: pickNumber(props.neighbor_count),
          category_counts: cloneObject(props.category_counts || {}),
          gi_star_z_score: pickNumber(props.gi_star_z_score),
          gi_star_value: pickNumber(props.gi_star_value),
          lisa_i: pickNumber(props.lisa_i),
          lisa_z_score: pickNumber(props.lisa_z_score),
        }
      }
      const derived = cloneObject(source.derived_stats)
      const rowsFrom = (compactKey, legacyKey) => {
        const compact = cloneArray(derived[compactKey])
        if (compact.length) return compact.slice(0, rowLimit)
        return cloneArray(derived[legacyKey] && derived[legacyKey].rows).slice(0, rowLimit)
      }
      const summaryFrom = (compactKey, legacyKey) => {
        const compact = cloneObject(derived[compactKey])
        if (Object.keys(compact).length) return compact
        const legacy = cloneObject(derived[legacyKey])
        delete legacy.rows
        return legacy
      }
      const allCells = cloneArray(source.cells).map(pickCell).filter(Boolean)
      const cells = allCells.slice(0, cellLimit)
      return {
        evidence_version: asText(source.evidence_version) || 'poi_h3_evidence_v1',
        grid_type: asText(source.grid_type) || 'h3',
        usage: asText(source.usage) || 'POI-only spatial structure evidence; do not use it for population or nightlight coupling.',
        params: cloneObject(source.params),
        counts: {
          ...cloneObject(source.counts),
          cell_count: Number((source.counts && source.counts.cell_count) || allCells.length || 0) || 0,
          included_cell_count: cells.length,
        },
        metrics: cloneObject(source.metrics),
        summary: cloneObject(source.summary),
        charts: cloneObject(source.charts),
        cells,
        derived_stats: {
          structure_rows: rowsFrom('structure_rows', 'structureSummary'),
          typing_rows: rowsFrom('typing_rows', 'typingSummary'),
          lq_rows: rowsFrom('lq_rows', 'lqSummary'),
          gap_rows: rowsFrom('gap_rows', 'gapSummary'),
          structure_summary: summaryFrom('structure_summary', 'structureSummary'),
          typing_summary: summaryFrom('typing_summary', 'typingSummary'),
          lq_summary: summaryFrom('lq_summary', 'lqSummary'),
          gap_summary: summaryFrom('gap_summary', 'gapSummary'),
        },
        omitted: {
          cells_total: Number((source.omitted && source.omitted.cells_total) || allCells.length || 0) || 0,
          cells_included: cells.length,
          geometry_removed: true,
        },
        constraints: {
          poi_only: true,
          do_not_use_for_population_nightlight_coupling: true,
        },
      }
    },
    compactAgentPoiIterationYearlyGridEvidence(value = {}) {
      const source = cloneObject(value || {})
      const compactRaster = (item = {}) => ({
        year: item && item.year,
        status: asText(item && item.status) || 'ready',
        error: asText(item && item.error),
        grid_scope: asText((item && item.grid_scope) || source.raster_grid_scope) || 'poi_iteration_raster_per_year',
        raster_evidence: this.compactAgentPoiIterationRasterEvidence((item && item.raster_evidence) || {}, 20),
      })
      const compactH3 = (item = {}) => ({
        year: item && item.year,
        status: asText(item && item.status) || 'ready',
        error: asText(item && item.error),
        grid_scope: asText((item && item.grid_scope) || source.grid_scope) || 'poi_iteration_h3_per_year',
        h3_evidence: this.compactAgentPoiIterationH3Evidence((item && item.h3_evidence) || {}, 20, 12),
      })
      const h3Items = cloneArray(source.h3_items || source.items).map(compactH3)
      return {
        evidence_version: asText(source.evidence_version) || 'poi_iteration_yearly_grid_evidence_v1',
        years: cloneArray(source.years),
        grid_scope: asText(source.grid_scope) || 'poi_iteration_h3_per_year',
        grid_type: asText(source.grid_type) || 'h3',
        raster_grid_scope: asText(source.raster_grid_scope) || 'poi_iteration_raster_per_year',
        latest_year: source.latest_year || null,
        latest_h3_evidence: this.compactAgentPoiIterationH3Evidence(source.latest_h3_evidence || {}, 20, 12),
        items: h3Items,
        h3_items: h3Items,
        raster_items: cloneArray(source.raster_items).map(compactRaster),
      }
    },
    compactAgentPoiIterationRasterEvidence(value = {}, cellLimit = 40) {
      const source = cloneObject(value || {})
      return {
        evidence_version: asText(source.evidence_version) || 'poi_raster_grid_evidence_v1',
        grid_type: asText(source.grid_type) || 'shared_raster',
        params: cloneObject(source.params),
        summary: cloneObject(source.summary),
        counts: cloneObject(source.counts),
        cells: cloneArray(source.cells).slice(0, cellLimit),
        constraints: {
          shared_cell_id: true,
          use_for_population_nightlight_coupling: true,
        },
      }
    },
    buildAgentPoiIterationEvidence(payload = {}) {
      const centerLng = Number(this.selectedPoint && this.selectedPoint.lng)
      const centerLat = Number(this.selectedPoint && this.selectedPoint.lat)
      const center = Number.isFinite(centerLng) && Number.isFinite(centerLat)
        ? [centerLng, centerLat]
        : undefined
      return {
        years: cloneArray(payload.years),
        center,
        summaries: cloneArray(payload.summaries).map((summary) => ({
          year: summary.year,
          count: summary.count,
          category_count: summary.category_count,
          top_categories: cloneArray(summary.top_categories),
          category_counts: cloneObject(summary.category_counts),
          subcategory_count: summary.subcategory_count,
          top_subcategories: cloneArray(summary.top_subcategories),
          subcategory_counts: cloneObject(summary.subcategory_counts),
          top_areas: cloneArray(summary.top_areas),
          category_to_subcategory_mix: cloneObject(summary.category_to_subcategory_mix),
          points: cloneArray(summary.points).map((point) => ({
            lng: Number(point.lng),
            lat: Number(point.lat),
            category: asText(point.category),
            subcategory: asText(point.subcategory),
            area: asText(point.area),
          })).filter((point) => Number.isFinite(point.lng) && Number.isFinite(point.lat)),
        })),
        trend_rows: cloneArray(payload.trend_rows),
        total_series: cloneArray(payload.total_series),
        category_stack: cloneArray(payload.category_stack).map((row) => ({
          year: row.year,
          segments: cloneArray(row.segments).map((segment) => ({
            name: segment.name,
            count: segment.count,
            ratio: segment.ratio,
          })),
        })),
        subcategory_stack: cloneArray(payload.subcategory_stack).map((row) => ({
          year: row.year,
          segments: cloneArray(row.segments).map((segment) => ({
            name: segment.name,
            parent: segment.parent,
            count: segment.count,
            ratio: segment.ratio,
          })),
        })),
        subcategory_trend_rows: cloneArray(payload.subcategory_trend_rows),
        area_heatmaps: cloneArray(payload.area_heatmaps).map((row) => ({
          year: row.year,
          point_count: row.point_count,
          top_area: row.top_area,
          points: cloneArray(row.points),
          cells: cloneArray(row.cells),
        })),
        area_heatmap_basemap: cloneObject(payload.area_heatmap_basemap),
        area_heatmap_boundary: cloneArray(payload.area_heatmap_boundary),
        area_heatmap_polygon: cloneArray(payload.area_heatmap_polygon),
        area_heatmap_snapshots: cloneArray(payload.area_heatmap_snapshots),
        h3_evidence: this.compactAgentPoiIterationH3Evidence(payload.h3_evidence || {}),
        yearly_grid_evidence: this.compactAgentPoiIterationYearlyGridEvidence(payload.yearly_grid_evidence || {}),
        rule_insights: cloneObject(payload.rule_insights),
      }
    },
    buildAgentPoiIterationAiEvidencePreview(payload = {}) {
      const evidence = this.buildAgentPoiIterationEvidence(payload)
      const summaries = cloneArray(evidence.summaries)
      const first = summaries[0] || {}
      const last = summaries[summaries.length - 1] || {}
      const getCounts = (summary, key) => cloneObject(summary && summary[key])
      const ratio = (count, total) => {
        const safeTotal = Math.max(0, Number(total || 0))
        return safeTotal > 0 ? Number((Number(count || 0) / safeTotal).toFixed(6)) : 0
      }
      const spatialRows = cloneArray(payload.subcategory_spatial_trend_rows)
      const spatialNames = new Set(spatialRows.map((row) => asText(row && row.name)).filter(Boolean))
      const parentLookup = new Map()
      summaries.forEach((summary) => {
        cloneArray(summary.top_subcategories).forEach((item) => {
          const name = asText(item && item.name)
          const parent = asText(item && item.parent)
          if (name && parent && !parentLookup.has(name)) parentLookup.set(name, parent)
        })
        Object.entries(cloneObject(summary.category_to_subcategory_mix)).forEach(([category, rows]) => {
          cloneArray(rows).forEach((item) => {
            const name = asText(item && item.name)
            const parent = asText((item && item.parent) || category)
            if (name && parent && !parentLookup.has(name)) parentLookup.set(name, parent)
          })
        })
      })
      const buildChanges = (key, limit, includeParent = false) => {
        const firstCounts = getCounts(first, key)
        const lastCounts = getCounts(last, key)
        const names = Array.from(new Set(Object.keys(firstCounts).concat(Object.keys(lastCounts)))).filter(Boolean)
        return names.map((name) => {
          const firstCount = Number(firstCounts[name] || 0)
          const lastCount = Number(lastCounts[name] || 0)
          const row = {
            name,
            first_count: firstCount,
            last_count: lastCount,
            delta: lastCount - firstCount,
            rate: firstCount > 0 ? Number(((lastCount - firstCount) / firstCount).toFixed(6)) : null,
            first_ratio: ratio(firstCount, first.count),
            last_ratio: ratio(lastCount, last.count),
            is_low_base: Math.max(firstCount, lastCount) < 10,
          }
          if (includeParent && parentLookup.get(name)) row.parent = parentLookup.get(name)
          if (includeParent && spatialNames.has(name)) row.has_spatial_signal = true
          return row
        }).sort((a, b) => {
          if (includeParent) {
            const spatialDelta = Number(!!b.has_spatial_signal) - Number(!!a.has_spatial_signal)
            if (spatialDelta) return spatialDelta
          }
          return Math.abs(Number(b.delta || 0)) - Math.abs(Number(a.delta || 0))
            || Number(b.last_ratio || 0) - Number(a.last_ratio || 0)
            || Number(b.last_count || 0) - Number(a.last_count || 0)
        }).slice(0, limit)
      }
      const materialChangeRows = (rows, direction, limit = 5) => {
        const sign = direction === 'growth' ? 1 : -1
        return cloneArray(rows)
          .filter((row) => Number(row && row.delta) * sign > 0)
          .sort((a, b) => Math.abs(Number(b.delta || 0)) - Math.abs(Number(a.delta || 0))
            || Number(!!a.is_low_base) - Number(!!b.is_low_base)
            || Number(b.last_ratio || 0) - Number(a.last_ratio || 0)
            || Number(b.last_count || 0) - Number(a.last_count || 0))
          .slice(0, limit)
      }
      const lowBaseGrowthRows = (rows, limit = 8) => cloneArray(rows)
        .filter((row) => row && row.is_low_base && Number(row.delta) > 0)
        .sort((a, b) => Number(b.rate || 0) - Number(a.rate || 0)
          || Math.abs(Number(b.delta || 0)) - Math.abs(Number(a.delta || 0)))
        .slice(0, limit)
      const growthAreaSignalRows = cloneArray(spatialRows)
        .filter((row) => Number(row && row.delta) > 0)
        .sort((a, b) => Number(b.delta || 0) - Number(a.delta || 0)
          || Number(b.centroid_shift_m || 0) - Number(a.centroid_shift_m || 0)
          || Number(b.hotspot_grid_count || 0) - Number(a.hotspot_grid_count || 0))
        .slice(0, 5)
        .map((row) => ({
          name: row.name,
          parent: row.parent,
          delta: row.delta,
          dominant_direction: row.dominant_direction,
          secondary_direction: row.secondary_direction,
          dominant_ring: row.dominant_ring,
          centroid_shift_direction: row.centroid_shift_direction,
          centroid_shift_m: row.centroid_shift_m,
          hotspot_grid_count: row.hotspot_grid_count,
          hotspot_grid_count_delta: row.hotspot_grid_count_delta,
          top_area: row.top_area,
        }))
      const areaName = cloneArray(last.top_areas)[0] && asText(cloneArray(last.top_areas)[0].name)
      const categoryChanges = buildChanges('category_counts', 12, false)
      const subcategoryChanges = buildChanges('subcategory_counts', 24, true)
      return {
        task: 'poi_iteration_change',
        evidence_version: 'poi_iteration_v1',
        years: cloneArray(evidence.years),
        scope: {
          center: evidence.center,
          area_name: areaName || '',
          scope_type: cloneArray(evidence.area_heatmap_polygon).length ? 'history_polygon' : 'point_bounds',
          polygon_point_count: cloneArray(evidence.area_heatmap_polygon).length,
        },
        year_summaries: summaries.map((summary) => ({
          year: summary.year,
          poi_count: summary.count,
          category_count: summary.category_count,
          top_categories: cloneArray(summary.top_categories).slice(0, 8),
          subcategory_count: summary.subcategory_count,
          top_subcategories: cloneArray(summary.top_subcategories).slice(0, 12),
          top_areas: cloneArray(summary.top_areas).slice(0, 8),
        })),
        trend_metrics: cloneArray(evidence.trend_rows),
        category_changes: categoryChanges,
        subcategory_changes: subcategoryChanges,
        material_change_highlights: {
          ranking_policy: 'primary_rank_by_absolute_delta_then_last_ratio_and_last_count; percentage_rate_is_secondary',
          category_growth: materialChangeRows(categoryChanges, 'growth', 5),
          category_decline: materialChangeRows(categoryChanges, 'decline', 5),
          subcategory_growth: materialChangeRows(subcategoryChanges, 'growth', 8),
          subcategory_decline: materialChangeRows(subcategoryChanges, 'decline', 8),
          low_base_growth_watchlist: lowBaseGrowthRows(categoryChanges.concat(subcategoryChanges), 8),
        },
        spatial_factors: cloneObject(payload.spatial_factors),
        subcategory_spatial_trends: spatialRows.slice(0, 30).map((row) => ({
          name: row.name,
          parent: row.parent,
          delta: row.delta,
          dominant_direction: row.dominant_direction,
          secondary_direction: row.secondary_direction,
          dominant_ring: row.dominant_ring,
          centroid_shift_direction: row.centroid_shift_direction,
          centroid_shift_m: row.centroid_shift_m,
          hotspot_grid_count: row.hotspot_grid_count,
          hotspot_grid_count_delta: row.hotspot_grid_count_delta,
          top_area: row.top_area,
        })),
        growth_area_signal: {
          label: 'growth_area_direction',
          interpretation_policy: 'describe internal growth direction/ring/hotspots inside the isochrone; do not require an administrative new area name',
          has_named_area: false,
          growth_rows: growthAreaSignalRows,
        },
        h3_evidence: cloneObject(evidence.h3_evidence),
        yearly_grid_evidence: cloneObject(evidence.yearly_grid_evidence),
        area_distribution: cloneArray(evidence.area_heatmaps).map((row) => ({
          year: row.year,
          point_count: row.point_count,
          top_area: row.top_area,
          hotspot_cell_count: cloneArray(row.cells).length,
          top_cells: cloneArray(row.cells)
            .slice()
            .sort((a, b) => Number(b.intensity || 0) - Number(a.intensity || 0))
            .slice(0, 12)
            .map((cell, index) => ({
              rank: index + 1,
              intensity: cell.intensity,
              poi_count: cell.count || cell.poi_count || cell.point_count,
            })),
        })),
        rule_insights: cloneObject(evidence.rule_insights),
        constraints: {
          no_invented_places: true,
          no_coordinate_reasoning: true,
          no_low_base_rate_as_primary: true,
          growth_ranking_policy: 'use material_change_highlights; rank by absolute delta before percentage rate',
          output_language: 'zh-CN',
        },
      }
    },
    async requestAgentPoiIterationAnalysis(payload = {}) {
      const res = await fetch('/api/v1/analysis/agent/iteration/poi/interpret', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ evidence: this.buildAgentPoiIterationEvidence(payload) }),
      })
      if (!res.ok) {
        let detail = ''
        try { detail = await res.text() } catch (_) {}
        throw new Error(detail || 'AI POI 趋势解析失败')
      }
      return res.json()
    },
    async requestAgentPoiIterationBuild({ historyId = '', years = [], center = undefined, h3Evidence = undefined, yearlyGridEvidence = undefined } = {}) {
      const res = await fetch('/api/v1/analysis/agent/iteration/poi/build', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          history_id: asText(historyId),
          years: cloneArray(years).map((item) => Number(item)).filter((item) => Number.isFinite(item)),
          center,
          h3_evidence: h3Evidence || (typeof this.buildAgentPoiH3Evidence === 'function' ? this.buildAgentPoiH3Evidence() : {}),
          yearly_grid_evidence: yearlyGridEvidence || this.getAgentIterationPoiPayload().yearly_grid_evidence || {},
        }),
      })
      if (!res.ok) {
        let detail = ''
        try { detail = await res.text() } catch (_) {}
        throw new Error(detail || 'POI 多年迭代聚合失败')
      }
      return res.json()
    },
    async ensureAgentIterationPoiAiAnalysis(payloadArg = null, options = {}) {
      const payload = payloadArg || this.getAgentIterationPoiPayload()
      if (asText(payload.status) !== 'ready') return payload
      if (this.hasAgentIterationPoiReport() || asText(payload.ai_status) === 'loading') return payload
      const tabId = asText(options.tabId)
      this.commitAgentIterationPoiPayload({ ai_status: 'loading', ai_error: '' }, tabId ? { tabId } : {})
      try {
        const aiResult = await this.requestAgentPoiIterationAnalysis(payload)
        return this.commitAgentIterationPoiPayload({
          ai_status: aiResult.status === 'ready' ? 'ready' : 'failed',
          ai_summary: [],
          ai_insights: {},
          driver_analysis: [],
          planning_implications: [],
          report_title: asText(aiResult.report_title),
          report_sections: cloneArray(aiResult.report_sections),
          report_content: asText(aiResult.report_content),
          spatial_factors: cloneObject(aiResult.spatial_factors),
          subcategory_spatial_trend_rows: cloneArray(aiResult.subcategory_spatial_trend_rows),
          subcategory_spatial_summary: cloneArray(aiResult.subcategory_spatial_summary),
          ai_prompt: asText(aiResult.ai_prompt),
          ai_prompt_payload_note: asText(aiResult.ai_prompt_payload_note),
          prompt_snapshot: cloneObject(aiResult.prompt_snapshot),
          prompt_snapshots: cloneObject(aiResult.prompt_snapshots),
          ai_error: aiResult.status === 'ready' ? '' : asText(aiResult.error),
        }, tabId ? { tabId } : {})
      } catch (err) {
        const message = asText(err && err.message) || String(err)
        return this.commitAgentIterationPoiPayload({
          ai_status: 'failed',
          ai_error: message,
        }, tabId ? { tabId } : {})
      }
    },
    buildAgentPoiTrendRows(summaries = []) {
      const sorted = cloneArray(summaries).filter((item) => item && item.count !== undefined)
      if (sorted.length < 2) return []
      const first = sorted[0]
      const last = sorted[sorted.length - 1]
      const firstCounts = cloneObject(first.category_counts)
      const lastCounts = cloneObject(last.category_counts)
      const categoryNames = Array.from(new Set([...Object.keys(firstCounts), ...Object.keys(lastCounts)]))
      const deltas = categoryNames.map((name) => ({
        name,
        delta: Number(lastCounts[name] || 0) - Number(firstCounts[name] || 0),
      })).sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta) || a.name.localeCompare(b.name, 'zh-CN'))
      const topIncrease = deltas.find((item) => item.delta > 0)
      const topDecrease = deltas.find((item) => item.delta < 0)
      const totalDelta = Number(last.count || 0) - Number(first.count || 0)
      return [
        { key: 'years', label: '覆盖年份', value: `${first.year || '-'}-${last.year || '-'}` },
        { key: 'total_delta', label: 'POI 首尾变化', value: `${totalDelta >= 0 ? '+' : ''}${this.formatAgentIterationMetric(totalDelta, 0)}` },
        { key: 'category_delta', label: '业态类型变化', value: `${Number(last.category_count || 0) - Number(first.category_count || 0) >= 0 ? '+' : ''}${Number(last.category_count || 0) - Number(first.category_count || 0)}` },
        { key: 'top_increase', label: '增长最明显业态', value: topIncrease ? `${topIncrease.name} +${topIncrease.delta}` : '-' },
        { key: 'top_decrease', label: '减少最明显业态', value: topDecrease ? `${topDecrease.name} ${topDecrease.delta}` : '-' },
        { key: 'latest_top', label: '末年第一业态', value: ((last.top_categories || [])[0] || {}).name || '-' },
      ]
    },
    buildAgentPoiSubcategoryTrendRows(summaries = []) {
      const sorted = cloneArray(summaries).filter((item) => item && item.count !== undefined)
      if (sorted.length < 2) return []
      const first = sorted[0]
      const last = sorted[sorted.length - 1]
      const firstCounts = cloneObject(first.subcategory_counts)
      const lastCounts = cloneObject(last.subcategory_counts)
      const names = Array.from(new Set([...Object.keys(firstCounts), ...Object.keys(lastCounts)]))
      const parentByName = {}
      cloneArray(first.top_subcategories).concat(cloneArray(last.top_subcategories)).forEach((item) => {
        if (item && item.name && !parentByName[item.name]) parentByName[item.name] = item.parent || ''
      })
      const deltas = names.map((name) => ({
        name,
        parent: parentByName[name] || '',
        delta: Number(lastCounts[name] || 0) - Number(firstCounts[name] || 0),
      })).sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta) || a.name.localeCompare(b.name, 'zh-CN'))
      const topIncrease = deltas.find((item) => item.delta > 0)
      const topDecrease = deltas.find((item) => item.delta < 0)
      const latestTop = (cloneArray(last.top_subcategories)[0] || {})
      return [
        { key: 'subcategory_delta', label: '小类类型变化', value: `${Number(last.subcategory_count || 0) - Number(first.subcategory_count || 0) >= 0 ? '+' : ''}${Number(last.subcategory_count || 0) - Number(first.subcategory_count || 0)}` },
        { key: 'top_subcategory_increase', label: '增长最明显小类', value: topIncrease ? `${topIncrease.name}${topIncrease.parent ? `（${topIncrease.parent}）` : ''} +${topIncrease.delta}` : '-' },
        { key: 'top_subcategory_decrease', label: '减少最明显小类', value: topDecrease ? `${topDecrease.name}${topDecrease.parent ? `（${topDecrease.parent}）` : ''} ${topDecrease.delta}` : '-' },
        { key: 'latest_top_subcategory', label: '末年第一小类', value: latestTop.name ? `${latestTop.name}${latestTop.parent ? `（${latestTop.parent}）` : ''}` : '-' },
      ]
    },
    async requestAgentPoiYearSnapshot(year) {
      const historyId = asText(this.currentHistoryRecordId)
      if (!historyId) throw new Error('当前没有可读取的历史记录')
      const res = await fetch(`/api/v1/analysis/history/${historyId}/pois?year=${Number(year)}`)
      if (!res.ok) {
        let detail = ''
        try { detail = await res.text() } catch (_) {}
        throw new Error(detail || `历史 POI ${year} 请求失败(${res.status})`)
      }
      return res.json()
    },
    commitAgentIterationPoiTaskBoardPatch(taskKey = '', patch = {}) {
      const key = asText(taskKey)
      if (!key) return this.getAgentIterationPoiPayload()
      const payload = this.getAgentIterationPoiPayload()
      const current = payload.task_board && typeof payload.task_board === 'object' ? payload.task_board : {}
      const tasks = this.getAgentIterationPoiTaskBoardTasks().map((task) => (
        task.key === key ? { ...task, ...cloneObject(patch) } : task
      ))
      return this.commitAgentIterationPoiPayload({
        task_board: {
          ...cloneObject(current),
          runState: tasks.some((task) => task.status === 'running') ? 'running' : asText(current.runState || 'idle'),
          tasks,
          lastRunAt: asText(current.lastRunAt) || new Date().toISOString(),
        },
      })
    },
    buildAgentPoiRasterGridEvidence() {
      const bundle = buildAnalysisTaskParamBundle(this, 'poi_raster_grid')
      const params = cloneObject(bundle.params || {})
      return {
        evidence_version: 'poi_raster_grid_evidence_v1',
        grid_type: 'shared_raster',
        params: {
          poi_year: Number(this.poiYearSource || this.resultPoiYear || 0) || null,
          shared: cloneObject(params || {}),
        },
        summary: cloneObject(this.poiGridSummary || {}),
        counts: {
          grid_count: Number((this.poiGridSummary && this.poiGridSummary.grid_count) || cloneArray(this.poiGridFeatures).length || 0) || 0,
          active_cell_count: Number(this.poiGridSummary && this.poiGridSummary.active_cell_count || 0) || 0,
          assigned_poi_count: Number(this.poiGridSummary && this.poiGridSummary.assigned_poi_count || 0) || 0,
        },
        cells: cloneArray(this.poiGridFeatures).map((feature) => {
          const props = cloneObject(feature && feature.properties)
          return {
            cell_id: asText(props.cell_id || props.h3_id),
            poi_count: Number(props.poi_count || 0) || 0,
            density_poi_per_km2: Number(props.density_poi_per_km2 || 0) || 0,
            dominant_category: asText(props.dominant_category),
            dominant_category_name: asText(props.dominant_category_name),
            category_counts: cloneObject(props.category_counts),
          }
        }).filter((cell) => cell.cell_id).slice(0, 80),
      }
    },
    async buildAgentPoiYearlyGridEvidence(years = []) {
      const targetYears = cloneArray(years).map((item) => Number(item)).filter((item) => Number.isFinite(item)).sort((a, b) => a - b)
      const h3Items = []
      const publishProgress = () => {
        const readyItems = h3Items.filter((item) => asText(item.status) === 'ready')
        const latest = readyItems.slice().sort((a, b) => Number(a.year || 0) - Number(b.year || 0)).slice(-1)[0] || {}
        this.commitAgentIterationPoiPayload({
          yearly_grid_evidence: {
            evidence_version: 'poi_iteration_yearly_grid_evidence_v1',
            years: targetYears,
            grid_scope: 'poi_iteration_h3_per_year',
            grid_type: 'h3',
            items: cloneArray(h3Items),
            h3_items: cloneArray(h3Items),
            latest_year: latest.year || null,
            latest_h3_evidence: cloneObject(latest.h3_evidence || {}),
          },
          h3_evidence: cloneObject(latest.h3_evidence || {}),
        })
      }
      for (const year of targetYears) {
        h3Items.push({
          year,
          status: 'running',
          error: '',
          grid_scope: 'poi_iteration_h3_per_year',
          h3_evidence: {},
          run_id: '',
          progress: { status: 'running', stage: 'queued', message: '已接收请求，等待开始计算', step: 0, total: 7, elapsed_sec: 0, extra: { year } },
        })
        publishProgress()
        try {
          let h3 = null
          if (typeof this.ensurePoiGridResult === 'function') {
            h3 = await this.ensurePoiGridResult({ year, gridType: 'h3', force: false })
          } else {
            await this.selectAgentPoiYearForGrid(year)
            if (typeof this.selectAllH3PoiFilters === 'function') this.selectAllH3PoiFilters()
            const h3Run = typeof this.computeH3Analysis === 'function' ? await this.computeH3Analysis() : null
            h3 = {
              evidence: typeof this.buildAgentPoiH3Evidence === 'function' ? this.buildAgentPoiH3Evidence() : {},
              progress: cloneObject((h3Run && h3Run.progress) || this.h3AnalysisProgress || {}),
            }
          }
          h3Items[h3Items.length - 1] = {
            year,
            status: 'ready',
            error: '',
            grid_scope: 'poi_iteration_h3_per_year',
            h3_evidence: cloneObject(h3.evidence || {}),
            run_id: asText(((h3.progress || {}).run_id)),
            progress: cloneObject(h3.progress || {}),
          }
        } catch (err) {
          h3Items[h3Items.length - 1] = {
            year,
            status: 'failed',
            error: asText(err && err.message) || String(err),
            grid_scope: 'poi_iteration_h3_per_year',
            h3_evidence: {},
            run_id: '',
            progress: { status: 'failed', stage: 'failed', message: asText(err && err.message) || String(err), step: 7, total: 7, elapsed_sec: 0, extra: { year } },
          }
        }
        publishProgress()
      }
      const readyItems = h3Items.filter((item) => asText(item.status) === 'ready')
      const latest = readyItems.slice().sort((a, b) => Number(a.year || 0) - Number(b.year || 0)).slice(-1)[0] || {}
      return {
        evidence_version: 'poi_iteration_yearly_grid_evidence_v1',
        years: targetYears,
        grid_scope: 'poi_iteration_h3_per_year',
        grid_type: 'h3',
        items: h3Items,
        h3_items: h3Items,
        latest_year: latest.year || null,
        latest_h3_evidence: cloneObject(latest.h3_evidence || {}),
      }
    },
    async runAgentIterationPoiTask(taskKey = '') {
      const key = asText(taskKey)
      if (!['poi_fetch', 'poi_h3_grid'].includes(key)) return
      const startedAt = new Date().toISOString()
      this.commitAgentIterationPoiTaskBoardPatch(key, { status: 'running', startedAt, endedAt: '', error: '' })
      try {
        if (key === 'poi_fetch') {
          const years = this.getAgentIterationPoiTargetYears()
          this.poiYearSelections = years
          if (typeof this.fetchPois !== 'function') throw new Error('POI 抓取入口不可用')
          await this.fetchPois({ preserveCurrentPanel: true })
        } else {
          const years = this.getAgentIterationPoiTargetYears()
          for (const year of years) {
            if (typeof this.ensurePoiGridResult === 'function') {
              await this.ensurePoiGridResult({ year, gridType: 'h3', force: false })
            } else {
              await this.selectAgentPoiYearForGrid(year)
              if (typeof this.selectAllH3PoiFilters === 'function') this.selectAllH3PoiFilters()
              if (typeof this.computeH3Analysis === 'function') await this.computeH3Analysis()
            }
          }
          const evidence = await this.buildAgentPoiYearlyGridEvidence(years)
          const failedRows = cloneArray(evidence.h3_items || evidence.items)
          const failed = failedRows.find((item) => asText(item.status) === 'failed')
          if (failed) throw new Error(`${failed.year || ''} 年H3计算失败：${asText(failed.error)}`)
          this.commitAgentIterationPoiPayload({
            yearly_grid_evidence: evidence,
            h3_evidence: cloneObject(evidence.latest_h3_evidence || {}),
          })
          this.clearAgentIterationPoiNoticeIfReady()
        }
        this.commitAgentIterationPoiTaskBoardPatch(key, { status: 'completed', endedAt: new Date().toISOString(), error: '' })
      } catch (err) {
        const message = asText(err && err.message) || String(err)
        this.commitAgentIterationPoiTaskBoardPatch(key, { status: 'failed', endedAt: new Date().toISOString(), error: message })
        throw err
      }
    },
    async runAgentIterationPoiPrimaryAction() {
      const missing = this.getAgentIterationPoiTaskKeysToFill()
      if (missing.length) {
        for (const key of missing) {
          await this.runAgentIterationPoiTask(key)
        }
      } else {
        await this.runAgentIterationPoiTask('poi_fetch')
        await this.runAgentIterationPoiTask('poi_h3_grid')
      }
      const payload = await this.ensureAgentIterationPoi(true)
      if (asText(payload.status) === 'ready') this.setAgentIterationSecondaryView('ai', 'poi')
      return payload
    },
    async ensureAgentIterationPoi(force = false) {
      const existing = this.getAgentIterationPoiPayload()
      if (!force && asText(existing.status) === 'ready') {
        this.ensureAgentIterationPoiAreaHeatmapSnapshots(existing).catch((err) => {
          console.warn('[agent-iteration-poi] area snapshot generation failed', err)
        })
        return existing
      }
      if (this.agentIterationPoiLoading) return existing
      const targetTabId = asText(this.getAgentActiveTopTab().kind) === 'iteration_change'
        ? asText(this.getAgentActiveTopTab().id)
        : ''
      this.agentIterationPoiLoading = true
      this.agentIterationPoiError = ''
      this.commitAgentIterationPoiPayload({ status: 'loading', error: '' }, { tabId: targetTabId })
      try {
        const readiness = this.getAgentIterationPoiReadiness()
        if (!readiness.ready) {
          return this.commitAgentIterationPoiPayload({
            status: 'needs_data',
            source: 'readiness',
            years: cloneArray(readiness.years),
            error: '',
            notice: `多年 POI 分析还缺 ${readiness.missingTasks.map((key) => this.getAgentSummaryTaskLabel(key)).join('、')}，请先补齐。`,
          }, { tabId: targetTabId })
        }
        const historyYears = cloneArray(this.currentHistoryAvailablePoiYears)
          .map((item) => Number(item))
          .filter((item) => Number.isFinite(item))
          .sort((a, b) => a - b)
        const historyId = asText(this.currentHistoryRecordId)
        if (historyId && historyYears.length >= 2) {
          const centerLng = Number(this.selectedPoint && this.selectedPoint.lng)
          const centerLat = Number(this.selectedPoint && this.selectedPoint.lat)
          const center = Number.isFinite(centerLng) && Number.isFinite(centerLat)
            ? [centerLng, centerLat]
            : undefined
          const yearlyGridEvidence = this.getAgentIterationPoiYearlyGridEvidence()
          const latestH3 = cloneObject(yearlyGridEvidence.latest_h3_evidence)
          const latestH3HasMetrics = cloneArray(latestH3.cells).length || Object.keys(cloneObject(latestH3.summary)).length || Object.keys(cloneObject(latestH3.metrics)).length
          const h3Evidence = latestH3HasMetrics ? latestH3 : (typeof this.buildAgentPoiH3Evidence === 'function' ? this.buildAgentPoiH3Evidence() : {})
          const builtPayload = await this.requestAgentPoiIterationBuild({ historyId, years: historyYears, center, h3Evidence, yearlyGridEvidence })
          const committed = this.commitAgentIterationPoiPayload({
            status: asText(builtPayload.status) || 'ready',
            source: asText(builtPayload.source) || 'history',
            historyId,
            years: cloneArray(builtPayload.years),
            summaries: cloneArray(builtPayload.summaries),
            trend_rows: cloneArray(builtPayload.trend_rows),
            total_series: cloneArray(builtPayload.total_series),
            category_stack: cloneArray(builtPayload.category_stack),
            subcategory_stack: cloneArray(builtPayload.subcategory_stack),
            subcategory_trend_rows: cloneArray(builtPayload.subcategory_trend_rows),
            area_heatmaps: cloneArray(builtPayload.area_heatmaps),
            area_heatmap_basemap: cloneObject(builtPayload.area_heatmap_basemap),
            area_heatmap_boundary: cloneArray(builtPayload.area_heatmap_boundary),
            area_heatmap_polygon: cloneArray(builtPayload.area_heatmap_polygon),
            area_heatmap_snapshots: this.buildAgentPoiAreaHeatmapSnapshotPlaceholders(builtPayload),
            spatial_factors: cloneObject(builtPayload.spatial_factors),
            subcategory_spatial_trend_rows: cloneArray(builtPayload.subcategory_spatial_trend_rows),
            subcategory_spatial_summary: cloneArray(builtPayload.subcategory_spatial_summary),
            h3_evidence: cloneObject(builtPayload.h3_evidence || h3Evidence),
            yearly_grid_evidence: cloneObject(builtPayload.yearly_grid_evidence || yearlyGridEvidence),
            rule_summary: cloneArray(builtPayload.rule_summary),
            rule_insights: cloneObject(builtPayload.rule_insights),
            ai_summary: [],
            ai_insights: {},
            driver_analysis: [],
            planning_implications: [],
            report_title: asText(builtPayload.report_title),
            report_sections: cloneArray(builtPayload.report_sections),
            report_content: asText(builtPayload.report_content),
            ai_status: asText(builtPayload.ai_status) || (cloneArray(builtPayload.report_sections).length || asText(builtPayload.report_content) ? 'ready' : 'pending'),
            ai_error: asText(builtPayload.ai_error),
            error: asText(builtPayload.error),
            notice: '',
          }, { tabId: targetTabId })
          this.ensureAgentIterationPoiAreaHeatmapSnapshots(committed).catch((err) => {
            console.warn('[agent-iteration-poi] area snapshot generation failed', err)
          })
          this.ensureAgentIterationPoiAiAnalysis(committed, { tabId: targetTabId }).catch((err) => {
            console.warn('[agent-iteration-poi] ai analysis failed', err)
          })
          if (this.getAgentIterationSecondaryView('poi') === 'data') this.setAgentIterationSecondaryView('ai', 'poi')
          return committed
        }
        return this.commitAgentIterationPoiPayload({
          status: 'needs_data',
          source: 'readiness',
          years: cloneArray(this.getAgentIterationPoiTargetYears()),
          error: '',
          notice: '多年 POI 分析需要可读取的多年 POI 历史记录和年度网格证据，请先补齐。',
        }, { tabId: targetTabId })
      } catch (err) {
        const message = asText(err && err.message) || String(err)
        this.agentIterationPoiError = message
        return this.commitAgentIterationPoiPayload({ status: 'failed', error: message }, { tabId: targetTabId })
      } finally {
        this.agentIterationPoiLoading = false
      }
    },
    async requestAgentNightlightYearSnapshot(year) {
      const polygon = this.getIsochronePolygonPayload()
      const requestBody = { polygon, coord_type: 'gcj02', year: Number(year) || null }
      const overviewRes = await fetch('/api/v1/analysis/nightlight/overview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody),
      })
      if (!overviewRes.ok) {
        let detail = ''
        try { detail = await overviewRes.text() } catch (_) {}
        throw new Error(detail || `夜光${year}概览请求失败`)
      }
      const overview = await overviewRes.json()
      const gridPromise = fetch('/api/v1/analysis/nightlight/grid', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody),
      }).then(async (res) => {
        if (!res.ok) throw new Error(`夜光${year}格网请求失败`)
        return res.json()
      })
      const layerPromise = fetch('/api/v1/analysis/nightlight/layer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...requestBody,
          scope_id: overview.scope_id || null,
          view: 'radiance',
        }),
      }).then(async (res) => {
        if (!res.ok) throw new Error(`夜光${year}图层请求失败`)
        return res.json()
      })
      const rasterRes = await fetch('/api/v1/analysis/nightlight/raster', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...requestBody, scope_id: overview.scope_id || null }),
      })
      if (!rasterRes.ok) {
        let detail = ''
        try { detail = await rasterRes.text() } catch (_) {}
        throw new Error(detail || `夜光${year}快照请求失败`)
      }
      const raster = await rasterRes.json()
      const [gridResult, layerResult] = await Promise.allSettled([gridPromise, layerPromise])
      const grid = gridResult.status === 'fulfilled' ? gridResult.value : {}
      const layer = layerResult.status === 'fulfilled' ? layerResult.value : {}
      return {
        year: Number(year),
        summary: cloneObject(overview.summary || raster.summary),
        image_url: asText(raster.image_url),
        bounds_gcj02: cloneArray(raster.bounds_gcj02),
        legend: cloneObject(raster.legend),
        grid_features: cloneArray(grid.features),
        layer_cells: cloneArray(layer.cells),
        vector_legend: cloneObject(layer.legend),
        scope_id: asText(raster.scope_id || overview.scope_id),
      }
    },
    async requestAgentNightlightTimeseries(period) {
      const polygon = this.getIsochronePolygonPayload()
      const res = await fetch('/api/v1/analysis/timeseries/nightlight', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          polygon,
          coord_type: 'gcj02',
          period,
          layer_view: 'hotspot_shift',
        }),
      })
      if (!res.ok) {
        let detail = ''
        try { detail = await res.text() } catch (_) {}
        throw new Error(detail || '夜光热点迁移请求失败')
      }
      return res.json()
    },
    buildAgentNightlightIterationEvidence(payload = {}) {
      const snapshots = cloneArray(payload.snapshots).map((item) => ({
        year: item.year,
        summary: cloneObject(item.summary),
        has_image: !!item.image_url,
        has_vector: cloneArray(item.grid_features).length > 0 && cloneArray(item.layer_cells).length > 0,
        bounds_gcj02: cloneArray(item.bounds_gcj02),
      }))
      const timeseries = cloneObject(payload.timeseries)
      return {
        task: 'nightlight_iteration_change',
        evidence_version: 'nightlight_iteration_v1',
        years: cloneArray(payload.years),
        period: asText(payload.period),
        series: cloneArray(payload.series || timeseries.series),
        hotspot_shift: cloneObject((timeseries.layer || {}).summary),
        insights: cloneArray(timeseries.insights),
        snapshot_refs: snapshots,
      }
    },
    async requestAgentNightlightIterationAnalysis(payload = {}) {
      const res = await fetch('/api/v1/analysis/agent/iteration/nightlight/interpret', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ evidence: this.buildAgentNightlightIterationEvidence(payload) }),
      })
      if (!res.ok) {
        let detail = ''
        try { detail = await res.text() } catch (_) {}
        throw new Error(detail || 'AI夜光趋势解析失败')
      }
      return res.json()
    },
    commitAgentIterationNightlightPayload(patch = {}, options = {}) {
      const tabs = this.ensureAgentTabs(true)
      const activeId = asText(options.tabId) || asText(tabs.activeTabId)
      const targetTab = cloneArray(tabs.iterationChangeTabs).find((item) => item.id === activeId)
      const currentPayloads = targetTab && targetTab.panelPayloads && typeof targetTab.panelPayloads === 'object'
        ? cloneObject(targetTab.panelPayloads)
        : cloneObject(this.agentPanelPayloads)
      const currentRoot = cloneObject(currentPayloads.iteration_change)
      const nextNightlight = {
        ...cloneObject(currentRoot.nightlight),
        ...cloneObject(patch),
        updated_at: new Date().toISOString(),
      }
      const nextPayloads = {
        ...currentPayloads,
        iteration_change: {
          ...currentRoot,
          nightlight: nextNightlight,
        },
      }
      tabs.iterationChangeTabs = cloneArray(tabs.iterationChangeTabs).map((item) => (
        item.id === activeId ? { ...item, panelPayloads: cloneObject(nextPayloads), activeKind: 'nightlight' } : item
      ))
      this.agentTabs = { ...tabs, iterationChangeTabs: cloneArray(tabs.iterationChangeTabs) }
      if (asText(tabs.activeTabId) === activeId) {
        this.agentPanelPayloads = nextPayloads
      }
      this.syncCurrentAgentSession()
      return nextNightlight
    },
    async ensureAgentIterationNightlight(force = false) {
      if (!this.getIsochronePolygonRing || !this.getIsochronePolygonRing()) {
        this.agentIterationNightlightError = '请先生成或选择分析范围'
        return null
      }
      const existing = this.getAgentIterationNightlightPayload()
      if (!force && asText(existing.status) === 'ready' && cloneArray(existing.snapshots).length) return existing
      if (this.agentIterationNightlightLoading) return existing
      const targetTabId = asText(this.getAgentActiveTopTab().kind) === 'iteration_change'
        ? asText(this.getAgentActiveTopTab().id)
        : ''
      this.agentIterationNightlightLoading = true
      this.agentIterationNightlightError = ''
      this.commitAgentIterationNightlightPayload({ status: 'loading', error: '' }, { tabId: targetTabId })
      try {
        const metaRes = await fetch('/api/v1/analysis/timeseries/meta')
        if (!metaRes.ok) throw new Error(`/api/v1/analysis/timeseries/meta 请求失败(${metaRes.status})`)
        const meta = await metaRes.json()
        const years = cloneArray(meta.nightlight_years)
          .map((item) => Number(item))
          .filter((item) => Number.isFinite(item))
          .sort((a, b) => a - b)
          .slice(-3)
        if (years.length < 2) throw new Error('夜光多年数据不足')
        const period = `${years[0]}-${years[years.length - 1]}`
        const [timeseriesResult, ...snapshotResults] = await Promise.allSettled([
          this.requestAgentNightlightTimeseries(period),
          ...years.map((year) => this.requestAgentNightlightYearSnapshot(year)),
        ])
        const timeseries = timeseriesResult.status === 'fulfilled' ? timeseriesResult.value : {}
        const snapshots = snapshotResults.map((result, index) => {
          if (result.status === 'fulfilled') return result.value
          return { year: years[index], error: asText(result.reason && result.reason.message) || '快照加载失败' }
        })
        const basePayload = {
          status: 'analysis_loading',
          years,
          period,
          snapshots,
          timeseries,
          series: cloneArray(timeseries.series),
          error: '',
        }
        this.commitAgentIterationNightlightPayload(basePayload, { tabId: targetTabId })
        let aiResult = { status: 'failed', ai_analysis: {}, error: '' }
        try {
          aiResult = await this.requestAgentNightlightIterationAnalysis(basePayload)
        } catch (err) {
          aiResult = { status: 'failed', ai_analysis: {}, error: asText(err && err.message) || 'AI解析失败' }
        }
        return this.commitAgentIterationNightlightPayload({
          ...basePayload,
          status: aiResult.status === 'ready' ? 'ready' : 'ready_with_ai_error',
          ai_analysis: cloneObject(aiResult.ai_analysis),
          ai_prompt: asText(aiResult.ai_prompt),
          ai_prompt_payload_note: asText(aiResult.ai_prompt_payload_note),
          prompt_snapshot: cloneObject(aiResult.prompt_snapshot),
          ai_error: asText(aiResult.error),
        }, { tabId: targetTabId })
      } catch (err) {
        const message = asText(err && err.message) || String(err)
        this.agentIterationNightlightError = message
        return this.commitAgentIterationNightlightPayload({ status: 'failed', error: message }, { tabId: targetTabId })
      } finally {
        this.agentIterationNightlightLoading = false
      }
    },
    getAgentIterationSnapshotCells(snapshot = {}) {
      const features = cloneArray(snapshot.grid_features)
      const cells = cloneArray(snapshot.layer_cells)
      if (!features.length || !cells.length) return []
      const styleById = new Map(cells.map((cell) => [asText(cell && cell.cell_id), cloneObject(cell)]))
      const points = []
      features.forEach((feature) => {
        const rings = (((feature || {}).geometry || {}).coordinates || [])
        const outerRing = Array.isArray(rings[0]) ? rings[0] : []
        outerRing.forEach((point) => {
          if (Array.isArray(point) && Number.isFinite(Number(point[0])) && Number.isFinite(Number(point[1]))) {
            points.push([Number(point[0]), Number(point[1])])
          }
        })
      })
      if (!points.length) return []
      const xs = points.map((point) => point[0])
      const ys = points.map((point) => point[1])
      const minX = Math.min(...xs)
      const maxX = Math.max(...xs)
      const minY = Math.min(...ys)
      const maxY = Math.max(...ys)
      const spanX = Math.max(maxX - minX, 1e-9)
      const spanY = Math.max(maxY - minY, 1e-9)
      const width = 360
      const height = 260
      const pad = 14
      const scale = Math.min((width - pad * 2) / spanX, (height - pad * 2) / spanY)
      const offsetX = (width - spanX * scale) / 2
      const offsetY = (height - spanY * scale) / 2
      const project = (point) => {
        const x = offsetX + ((Number(point[0]) - minX) * scale)
        const y = height - offsetY - ((Number(point[1]) - minY) * scale)
        return `${x.toFixed(1)},${y.toFixed(1)}`
      }
      return features.map((feature, index) => {
        const props = cloneObject(feature && feature.properties)
        const cellId = asText(props.cell_id)
        const style = styleById.get(cellId) || {}
        const rawRings = (((feature || {}).geometry || {}).coordinates || [])
        const ring = Array.isArray(rawRings[0]) ? rawRings[0] : []
        const rawOpacity = Number(style.fill_opacity)
        const brightOpacity = Number.isFinite(rawOpacity)
          ? Math.min(0.92, Math.max(0.34, rawOpacity + 0.18))
          : 0.68
        return {
          key: cellId || `cell-${index}`,
          points: ring.map(project).join(' '),
          fill: asText(style.fill_color) || '#334155',
          opacity: brightOpacity,
          stroke: 'rgba(148, 163, 184, 0.28)',
        }
      }).filter((item) => item.points)
    },
    getAgentIterationSnapshotCellCount(snapshot = {}) {
      const cells = cloneArray(snapshot.layer_cells)
      if (cells.length) return cells.length
      return this.getAgentIterationSnapshotCells(snapshot).length
    },
    buildAgentIterationSnapshotCopyText(snapshot = {}) {
      const summary = cloneObject(snapshot.summary)
      return [
        `年份：${asText(snapshot.year) || '-'}`,
        `总辐亮：${this.formatAgentIterationMetric(summary.total_radiance, 1)}`,
        `均值：${this.formatAgentIterationMetric(summary.mean_radiance, 2)}`,
        `P90：${this.formatAgentIterationMetric(summary.p90_radiance, 2)}`,
        `点亮率：${this.formatAgentIterationPercent(summary.lit_pixel_ratio)}`,
        `快照格网数：${this.getAgentIterationSnapshotCellCount(snapshot)}`,
      ].join('\n')
    },
    buildAgentIterationSnapshotSvgMarkup(snapshot = {}) {
      const cells = this.getAgentIterationSnapshotCells(snapshot)
      if (!cells.length) return ''
      const year = asText(snapshot.year) || 'snapshot'
      const polygons = cells.map((cell) => (
        `<polygon points="${asText(cell.points)}" fill="${asText(cell.fill) || '#334155'}" fill-opacity="${Number(cell.opacity) || 0.68}" stroke="${asText(cell.stroke) || 'rgba(148, 163, 184, 0.28)'}" stroke-width="0.55"></polygon>`
      )).join('')
      return [
        '<svg xmlns="http://www.w3.org/2000/svg" width="720" height="520" viewBox="0 0 360 260" role="img">',
        '<defs><linearGradient id="agent-nightlight-copy-bg" x1="0" y1="0" x2="1" y2="1">',
        '<stop offset="0%" stop-color="#0f2347"></stop>',
        '<stop offset="58%" stop-color="#07152f"></stop>',
        '<stop offset="100%" stop-color="#020617"></stop>',
        '</linearGradient></defs>',
        `<title>${year} 夜光格网快照</title>`,
        '<rect x="0" y="0" width="360" height="260" rx="10" fill="url(#agent-nightlight-copy-bg)"></rect>',
        polygons,
        '</svg>',
      ].join('')
    },
    findAgentIterationSnapshotSvgFromEvent(event = null) {
      const target = event && event.currentTarget && typeof event.currentTarget.querySelector === 'function'
        ? event.currentTarget
        : null
      return target ? target.querySelector('.agent-iteration-snapshot-svg') : null
    },
    buildAgentIterationSnapshotSvgMarkupFromNode(svgNode = null, options = {}) {
      if (!svgNode || typeof XMLSerializer === 'undefined') return ''
      const cloned = svgNode.cloneNode(true)
      cloned.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
      const width = Number(options && options.width) || 360
      const height = Number(options && options.height) || 260
      cloned.setAttribute('width', String(Math.max(1, Math.round(width))))
      cloned.setAttribute('height', String(Math.max(1, Math.round(height))))
      cloned.querySelectorAll('.agent-iteration-heatmap-boundary').forEach((polygon) => {
        polygon.setAttribute('fill', '#2563eb')
        polygon.setAttribute('fill-opacity', polygon.getAttribute('fill-opacity') || '0.07')
        polygon.setAttribute('stroke', '#1d4ed8')
        polygon.setAttribute('stroke-width', polygon.getAttribute('stroke-width') || '0.72')
        polygon.setAttribute('stroke-linejoin', 'round')
        polygon.setAttribute('vector-effect', 'non-scaling-stroke')
      })
      cloned.querySelectorAll('.agent-iteration-heatmap-cell').forEach((rect) => {
        rect.setAttribute('fill', '#f97316')
        rect.setAttribute('stroke', '#7f1d1d')
        rect.setAttribute('stroke-opacity', rect.getAttribute('stroke-opacity') || '0.36')
        rect.setAttribute('stroke-width', rect.getAttribute('stroke-width') || '0.14')
      })
      cloned.querySelectorAll('.agent-iteration-heatmap-point').forEach((circle) => {
        circle.setAttribute('fill', '#0891b2')
        circle.setAttribute('stroke', '#f0fdfa')
        circle.setAttribute('stroke-opacity', circle.getAttribute('stroke-opacity') || '0.94')
        circle.setAttribute('stroke-width', circle.getAttribute('stroke-width') || '0.68')
        circle.setAttribute('paint-order', 'stroke fill')
        circle.setAttribute('vector-effect', 'non-scaling-stroke')
      })
      cloned.querySelectorAll('polygon').forEach((polygon) => {
        polygon.setAttribute('stroke-width', polygon.getAttribute('stroke-width') || '0.55')
      })
      return new XMLSerializer().serializeToString(cloned)
    },
    dataUrlToBlob(dataUrl = '') {
      const raw = asText(dataUrl)
      const match = raw.match(/^data:([^;,]+)(;base64)?,(.*)$/)
      if (!match) return null
      const mime = match[1] || 'image/png'
      const encoded = match[3] || ''
      if (match[2]) {
        const binary = atob(encoded)
        const bytes = new Uint8Array(binary.length)
        for (let index = 0; index < binary.length; index += 1) {
          bytes[index] = binary.charCodeAt(index)
        }
        return new Blob([bytes], { type: mime })
      }
      return new Blob([decodeURIComponent(encoded)], { type: mime })
    },
    async renderAgentIterationSnapshotPngBlob(snapshot = {}, svgNode = null) {
      const imageUrl = asText(snapshot.image_url)
      if (imageUrl.startsWith('data:image/png')) return this.dataUrlToBlob(imageUrl)
      const svgMarkup = this.buildAgentIterationSnapshotSvgMarkupFromNode(svgNode) || this.buildAgentIterationSnapshotSvgMarkup(snapshot)
      if (!svgMarkup || typeof document === 'undefined') return null
      const viewBox = svgNode && svgNode.viewBox && svgNode.viewBox.baseVal
        ? svgNode.viewBox.baseVal
        : null
      const baseWidth = Math.max(360, Math.round((viewBox && viewBox.width) || 360))
      const baseHeight = Math.max(260, Math.round((viewBox && viewBox.height) || 260))
      const scale = 4
      const svgBlob = new Blob([svgMarkup], { type: 'image/svg+xml;charset=utf-8' })
      const svgUrl = URL.createObjectURL(svgBlob)
      try {
        const image = await new Promise((resolve, reject) => {
          const img = new Image()
          img.onload = () => resolve(img)
          img.onerror = () => reject(new Error('snapshot_image_load_failed'))
          img.src = svgUrl
        })
        const canvas = document.createElement('canvas')
        canvas.width = baseWidth * scale
        canvas.height = baseHeight * scale
        const context = canvas.getContext('2d')
        if (!context) return null
        context.imageSmoothingEnabled = true
        context.imageSmoothingQuality = 'high'
        context.drawImage(image, 0, 0, canvas.width, canvas.height)
        return await new Promise((resolve) => {
          canvas.toBlob((blob) => resolve(blob), 'image/png')
        })
      } finally {
        URL.revokeObjectURL(svgUrl)
      }
    },
    getAgentIterationPoiAreaHeatmapViewportSize(viewport = null) {
      if (!viewport) return { width: 0, height: 0 }
      const rect = typeof viewport.getBoundingClientRect === 'function'
        ? viewport.getBoundingClientRect()
        : {}
      const width = Math.max(1, Math.round(Number(rect.width || viewport.clientWidth || viewport.offsetWidth || 0)))
      const height = Math.max(1, Math.round(Number(rect.height || viewport.clientHeight || viewport.offsetHeight || width || 0)))
      return { width, height }
    },
    async loadAgentIterationImageElement(src = '') {
      const url = asText(src)
      if (!url || typeof Image === 'undefined') return null
      return await new Promise((resolve, reject) => {
        const image = new Image()
        image.crossOrigin = 'anonymous'
        image.onload = () => resolve(image)
        image.onerror = () => reject(new Error('heatmap_image_load_failed'))
        image.src = url
      })
    },
    async renderAgentIterationPoiAreaHeatmapViewportBlob(cardNode = null) {
      if (!cardNode || typeof cardNode.querySelector !== 'function' || typeof document === 'undefined') return null
      const viewport = cardNode.querySelector('.agent-iteration-heatmap-viewport')
      if (!viewport) return null
      const size = this.getAgentIterationPoiAreaHeatmapViewportSize(viewport)
      if (!size.width || !size.height) return null
      const scale = 2
      const canvas = document.createElement('canvas')
      canvas.width = size.width * scale
      canvas.height = size.height * scale
      const context = canvas.getContext('2d')
      if (!context) return null
      context.fillStyle = '#ffffff'
      context.fillRect(0, 0, canvas.width, canvas.height)
      context.imageSmoothingEnabled = true
      context.imageSmoothingQuality = 'high'
      const imageNode = viewport.querySelector('img.agent-iteration-heatmap-img')
      const imageSrc = imageNode && imageNode.getAttribute ? asText(imageNode.getAttribute('src')) : ''
      if (imageSrc) {
        try {
          const image = await this.loadAgentIterationImageElement(imageSrc)
          if (image) context.drawImage(image, 0, 0, canvas.width, canvas.height)
        } catch (_) {}
      }
      const svgNode = viewport.querySelector('svg.agent-iteration-heatmap-svg')
      const svgMarkup = svgNode ? this.buildAgentIterationSnapshotSvgMarkupFromNode(svgNode, {
        width: canvas.width,
        height: canvas.height,
      }) : ''
      if (svgMarkup) {
        const svgUrl = URL.createObjectURL(new Blob([svgMarkup], { type: 'image/svg+xml;charset=utf-8' }))
        try {
          const overlay = await this.loadAgentIterationImageElement(svgUrl)
          if (overlay) context.drawImage(overlay, 0, 0, canvas.width, canvas.height)
        } finally {
          URL.revokeObjectURL(svgUrl)
        }
      }
      if (!imageSrc && !svgMarkup) return null
      return await new Promise((resolve) => {
        try {
          canvas.toBlob((blob) => resolve(blob), 'image/png')
        } catch (_) {
          resolve(null)
        }
      })
    },
    async copyAgentIterationSnapshotImage(snapshot = {}, svgNode = null) {
      const target = cloneObject(snapshot)
      const key = asText(target.year) || 'snapshot'
      this.agentIterationSnapshotCopyKey = key
      this.agentIterationSnapshotCopyStatus = '正在复制图片…'
      try {
        if (typeof navigator === 'undefined' || !navigator.clipboard || typeof navigator.clipboard.write !== 'function' || typeof ClipboardItem === 'undefined') {
          throw new Error('clipboard_image_unavailable')
        }
        const blob = await this.renderAgentIterationSnapshotPngBlob(target, svgNode)
        if (!blob) throw new Error('snapshot_image_unavailable')
        await navigator.clipboard.write([new ClipboardItem({ [blob.type || 'image/png']: blob })])
        this.agentIterationSnapshotCopyStatus = '图片已复制'
        this.agentIterationSnapshotDetailOpen = false
        this.agentIterationSnapshotDetail = null
      } catch (_) {
        this.agentIterationSnapshotDetail = target
        this.agentIterationSnapshotDetailOpen = true
        this.agentIterationSnapshotCopyStatus = '图片复制失败，可复制下方指标文本'
      }
    },
    async copyAgentIterationPoiAreaHeatmapImage(heatmap = {}, event = null) {
      const year = asText(heatmap && heatmap.year)
      if (!year) return
      const snapshot = {
        ...cloneObject(this.getAgentIterationPoiAreaHeatmapSnapshot(year)),
        year,
        image_url: asText((this.getAgentIterationPoiAreaHeatmapSnapshot(year) || {}).image_url),
        point_count: heatmap.point_count,
        top_area: heatmap.top_area,
      }
      this.agentIterationSnapshotCopyKey = `poi-area-${year}`
      this.agentIterationSnapshotCopyStatus = '正在复制图片…'
      try {
        if (typeof navigator === 'undefined' || !navigator.clipboard || typeof navigator.clipboard.write !== 'function' || typeof ClipboardItem === 'undefined') {
          throw new Error('clipboard_image_unavailable')
        }
        const cardNode = event && event.currentTarget ? event.currentTarget : null
        const blobPromise = (async () => {
          let blob = null
          if (cardNode) {
            blob = await this.renderAgentIterationPoiAreaHeatmapViewportBlob(cardNode)
          }
          if (!blob) {
            blob = asText(snapshot.image_url).startsWith('data:image/png')
              ? this.dataUrlToBlob(snapshot.image_url)
              : null
          }
          if (!blob) {
            blob = await this.renderAgentIterationSnapshotPngBlob(snapshot, cardNode && cardNode.querySelector ? cardNode.querySelector('svg') : null)
          }
          if (!blob) throw new Error('snapshot_image_unavailable')
          return blob.type === 'image/png' ? blob : new Blob([blob], { type: 'image/png' })
        })()
        await navigator.clipboard.write([new ClipboardItem({ 'image/png': blobPromise })])
        this.agentIterationSnapshotCopyKey = `poi-area-${year}`
        this.agentIterationSnapshotCopyStatus = '图片已复制'
      } catch (_) {
        this.agentIterationSnapshotCopyKey = `poi-area-${year}`
        this.agentIterationSnapshotCopyStatus = '图片复制失败，请重试'
      }
    },
    openAgentIterationSnapshotDetail(snapshot = {}, event = null) {
      if (!snapshot || typeof snapshot !== 'object' || asText(snapshot.error)) return
      const hasVector = this.getAgentIterationSnapshotCells(snapshot).length > 0
      const hasImage = !!asText(snapshot.image_url)
      if (!hasVector && !hasImage) return
      this.copyAgentIterationSnapshotImage(snapshot, this.findAgentIterationSnapshotSvgFromEvent(event))
    },
    closeAgentIterationSnapshotDetail() {
      this.agentIterationSnapshotDetailOpen = false
      this.agentIterationSnapshotDetail = null
      this.agentIterationSnapshotCopyStatus = ''
      this.agentIterationSnapshotCopyKey = ''
    },
    async copyAgentIterationSnapshotDetail() {
      const snapshot = cloneObject(this.agentIterationSnapshotDetail)
      const text = this.buildAgentIterationSnapshotCopyText(snapshot)
      if (!text.trim()) {
        this.agentIterationSnapshotCopyStatus = '无可复制内容'
        return
      }
      try {
        if (typeof navigator === 'undefined' || !navigator.clipboard || typeof navigator.clipboard.writeText !== 'function') {
          throw new Error('clipboard_unavailable')
        }
        await navigator.clipboard.writeText(text)
        this.agentIterationSnapshotCopyStatus = '已复制'
      } catch (_) {
        this.agentIterationSnapshotCopyStatus = '复制失败，请手动复制下方文本'
      }
    },
    getAgentIterationAiErrorLabel(error = '') {
      const raw = asText(error)
      if (!raw) return ''
      if (/ai_timeout/i.test(raw)) return '基础统计和快照已完成，AI 深度解读仍在补充。'
      if (/llm_unavailable/i.test(raw)) return 'AI 服务暂未启用，当前先展示结构化变化指标与年度快照。'
      if (/invalid_ai_analysis/i.test(raw)) return 'AI 解析结果格式异常，当前先展示结构化变化指标与年度快照。'
      return raw
    },
  }
}
