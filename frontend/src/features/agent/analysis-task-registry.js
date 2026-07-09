import { asText, cloneArray, cloneObject } from './normalizers.js'

import { buildAnalysisTaskParamBundle } from './analysis-task-params.js'

const ANALYSIS_TASKS = Object.freeze({
  poi_fetch: {
    key: 'poi_fetch',
    label: 'POI 抓取',
    panelId: 'poi',
    subPanelLabel: 'POI 分类抓取',
    estimate: '约 1-3 分钟',
    description: '使用当前分析范围抓取 POI 基础数据。',
    resultUsage: '完成后将作为网格与总结分析的基础输入。',
    toolNames: ['fetch_pois_in_scope'],
    producedArtifacts: ['current_pois', 'current_poi_summary'],
    runningFlag: 'isFetchingPois',
    hasResult(ctx) {
      return hasPoiFetchResult(ctx)
    },
    focus(ctx) {
      focusStep2Panel(ctx, 'poi')
      if (typeof ctx.setPoiSubTab === 'function') {
        ctx.setPoiSubTab('load')
      } else {
        ctx.poiSubTab = 'load'
      }
    },
    async run(ctx, options = {}) {
      if (typeof ctx.fetchPois !== 'function') {
        throw new Error('POI 抓取入口不可用')
      }
      const year = Number(ctx && (ctx.poiYearSource || ctx.resultPoiYear))
      if (Number.isFinite(year) && year > 0) {
        ctx.poiYearSelections = [year]
      }
      await ctx.fetchPois({
        preserveCurrentPanel: options.focus === false,
      })
    },
  },
  poi_raster_grid: {
    key: 'poi_raster_grid',
    label: 'POI 共享栅格计算',
    panelId: 'poi',
    subPanelLabel: 'POI 共享栅格',
    estimate: '约 1-3 分钟',
    description: '使用当前分析范围和 POI 数据生成同源 cell_id 共享栅格，补齐 POI 与人口/夜光耦合证据。',
    resultUsage: '完成后会用于人口、POI、夜光共享栅格交叉诊断。',
    toolNames: ['aggregate_pois_to_shared_grid'],
    producedArtifacts: ['current_poi_grid'],
    runningFlag: 'isLoadingPoiGrid',
    hasResult(ctx) {
      return !!(
        ctx
        && (
          ctx.poiGridSummary
          || (Array.isArray(ctx.poiGridFeatures) && ctx.poiGridFeatures.length)
        )
      )
    },
    focus(ctx) {
      focusStep2Panel(ctx, 'poi')
      if (typeof ctx.setPoiSubTab === 'function') {
        ctx.setPoiSubTab('grid')
      } else {
        ctx.poiSubTab = 'grid'
      }
      if (typeof ctx.setPoiGridType === 'function') {
        ctx.setPoiGridType('shared')
      } else {
        ctx.poiGridType = 'shared'
      }
    },
    async run(ctx) {
      if (typeof ctx.ensurePoiSharedGridAnalysis !== 'function') {
        throw new Error('POI 共享栅格计算入口不可用')
      }
      await ctx.ensurePoiSharedGridAnalysis(true)
    },
  },
  poi_h3_grid: {
    key: 'poi_h3_grid',
    label: 'POI H3 六边形网格计算',
    panelId: 'poi',
    subPanelLabel: 'POI H3 六边形网格',
    estimate: '约 1-3 分钟',
    description: '使用当前分析范围和 POI 数据生成 H3 六边形指标，补齐空间结构、热点和缺口证据。',
    resultUsage: '完成后会用于 POI 空间结构、热点、LISA、Gi*、LQ 和缺口分析。',
    toolNames: ['compute_h3_metrics_from_scope_and_pois', 'build_h3_grid_from_scope'],
    producedArtifacts: ['current_poi_h3', 'current_poi_h3_grid', 'current_poi_h3_summary', 'current_poi_h3_charts'],
    runningFlag: 'isComputingH3Analysis',
    hasResult(ctx) {
      return !!(
        ctx
        && (
          ctx.h3AnalysisSummary
          || (Array.isArray(ctx.h3AnalysisGridFeatures) && ctx.h3AnalysisGridFeatures.length)
          || Number(ctx.h3GridCount || 0) > 0
        )
      )
    },
    focus(ctx) {
      focusStep2Panel(ctx, 'poi')
      if (typeof ctx.setPoiSubTab === 'function') {
        ctx.setPoiSubTab('grid')
      } else {
        ctx.poiSubTab = 'grid'
      }
      if (typeof ctx.setPoiGridType === 'function') {
        ctx.setPoiGridType('hex')
      } else {
        ctx.poiGridType = 'hex'
      }
      if (typeof ctx.ensureH3PanelEntryState === 'function') {
        ctx.ensureH3PanelEntryState()
      }
    },
    async run(ctx) {
      if (typeof ctx.computeH3Analysis !== 'function') {
        throw new Error('POI H3 六边形网格计算入口不可用')
      }
      await ctx.computeH3Analysis()
    },
  },
  population: {
    key: 'population',
    label: '人口计算',
    panelId: 'population',
    subPanelLabel: '人口分析',
    estimate: '约 1-3 分钟',
    description: '使用当前分析范围计算人口总量、密度与结构信息。',
    resultUsage: '完成后会作为客群与生活圈判断的底层证据。',
    toolNames: ['compute_population_overview_from_scope'],
    producedArtifacts: ['current_population', 'current_population_summary', 'population_overview'],
    runningFlag: 'isComputingPopulation',
    hasResult(ctx) {
      return !!(ctx && ctx.populationOverview)
    },
    focus(ctx) {
      focusStep2Panel(ctx, 'population')
    },
    async run(ctx) {
      if (typeof ctx.computePopulationAnalysis !== 'function') {
        throw new Error('人口计算入口不可用')
      }
      await ctx.computePopulationAnalysis()
    },
  },
  nightlight: {
    key: 'nightlight',
    label: '夜光计算',
    panelId: 'nightlight',
    subPanelLabel: '夜光分析',
    estimate: '约 1-3 分钟',
    description: '使用当前分析范围计算夜光强度、热点与经济活动强度 proxy。',
    resultUsage: '完成后会用于补充夜间经济活动强度证据。',
    toolNames: ['compute_nightlight_overview_from_scope'],
    producedArtifacts: ['current_nightlight', 'current_nightlight_summary', 'nightlight_overview'],
    runningFlag: 'isComputingNightlight',
    hasResult(ctx) {
      return !!(ctx && (ctx.nightlightOverview || ctx.nightlightLayer))
    },
    focus(ctx) {
      focusStep2Panel(ctx, 'nightlight')
    },
    async run(ctx) {
      if (typeof ctx.computeNightlightAnalysis !== 'function') {
        throw new Error('夜光计算入口不可用')
      }
      await ctx.computeNightlightAnalysis()
    },
  },
  road_syntax: {
    key: 'road_syntax',
    label: '路网计算',
    panelId: 'syntax',
    subPanelLabel: '路网参数',
    estimate: '约 2-5 分钟',
    description: '使用当前分析范围计算路网句法指标和可达性证据。',
    resultUsage: '完成后会用于解释通达性、街道结构和商业可达性。',
    toolNames: ['compute_road_syntax_from_scope'],
    producedArtifacts: ['current_road', 'current_road_summary', 'road_syntax_summary'],
    runningFlag: 'isComputingRoadSyntax',
    hasResult(ctx) {
      if (!ctx || !ctx.roadSyntaxSummary) return false
      const statusText = asText(ctx.roadSyntaxStatus || '')
      if (/(^失败[:：]?|计算失败|渲染失败|未就绪|error|failed)/i.test(statusText)) {
        return false
      }
      return true
    },
    focus(ctx) {
      focusStep2Panel(ctx, 'syntax')
      if (typeof ctx.setRoadSyntaxMainTab === 'function') {
        ctx.setRoadSyntaxMainTab('params', { refresh: false, syncMetric: false })
      } else {
        ctx.roadSyntaxMainTab = 'params'
      }
    },
    async run(ctx) {
      if (typeof ctx.computeRoadSyntax !== 'function') {
        throw new Error('路网计算入口不可用')
      }
      await ctx.computeRoadSyntax()
    },
  },
})

function focusStep2Panel(ctx, panelId = '') {
  if (!ctx) return
  ctx.sidebarView = 'wizard'
  ctx.step = 2
  if (typeof ctx.selectStep3Panel === 'function') {
    ctx.selectStep3Panel(panelId)
  } else {
    ctx.activeStep3Panel = panelId
  }
}

function hasPoiFetchResult(ctx) {
  if (!ctx) return false
  if (Array.isArray(ctx.allPoisDetails) && ctx.allPoisDetails.length > 0) return true
  const markerManager = ctx.markerManager
  if (markerManager && typeof markerManager.getVisiblePoints === 'function') {
    const points = markerManager.getVisiblePoints()
    if (Array.isArray(points) && points.length > 0) return true
  }
  return false
}

function getAnalysisTaskDefinition(taskKey = '') {
  return ANALYSIS_TASKS[asText(taskKey)] || null
}

function getAnalysisTaskDefinitions() {
  return Object.values(ANALYSIS_TASKS).map((item) => ({ ...item }))
}

function hasAnalysisTaskScope(ctx) {
  if (!ctx) return false
  if (typeof ctx.getIsochronePolygonRing === 'function' && ctx.getIsochronePolygonRing()) return true
  if (typeof ctx.getIsochronePolygonPayload === 'function') {
    const polygon = ctx.getIsochronePolygonPayload()
    if (Array.isArray(polygon) && polygon.length >= 3) return true
  }
  return !!ctx.lastIsochroneGeoJSON
}

function getAnalysisTaskParameterSummary(ctx, taskKey = '') {
  const task = getAnalysisTaskDefinition(taskKey)
  if (!task) return ''
  const bundle = buildAnalysisTaskParamBundle(ctx || {}, task.key)
  return bundle.display_label || '当前面板参数'
}

function normalizeAnalysisTaskConfirmation(seed = {}) {
  const task = getAnalysisTaskDefinition(seed.taskKey || seed.task_key)
  if (!task) return null
  const status = asText(seed.status || 'ready') || 'ready'
  return {
    id: asText(seed.id) || `agent-task-${task.key}`,
    taskKey: task.key,
    label: asText(seed.label) || task.label,
    title: asText(seed.title) || `准备启动：${task.label}`,
    description: asText(seed.description) || task.description,
    estimate: asText(seed.estimate) || task.estimate,
    resultUsage: asText(seed.resultUsage || seed.result_usage) || task.resultUsage,
    panelId: task.panelId,
    subPanelLabel: task.subPanelLabel,
    parameterSummary: asText(seed.parameterSummary || seed.parameter_summary),
    status,
    statusLabel: asText(seed.statusLabel || seed.status_label),
    blockReason: asText(seed.blockReason || seed.block_reason),
    error: asText(seed.error),
    canStart: !!seed.canStart,
    canReuse: !!seed.canReuse,
    createdAt: asText(seed.createdAt || seed.created_at) || new Date().toISOString(),
    updatedAt: asText(seed.updatedAt || seed.updated_at) || new Date().toISOString(),
  }
}

function buildAnalysisTaskConfirmation(ctx, taskKey = '', seed = {}) {
  const task = getAnalysisTaskDefinition(taskKey)
  if (!task) return null
  let status = asText(seed.status || 'ready') || 'ready'
  let blockReason = asText(seed.blockReason || seed.block_reason)
  const running = !!(ctx && task.runningFlag && ctx[task.runningFlag])
  const hasScope = hasAnalysisTaskScope(ctx)
  const hasResult = !!task.hasResult(ctx)
  if (!hasScope) {
    status = 'blocked'
    blockReason = '缺少可计算的分析范围，请先完成范围生成或绘制区域。'
  } else if (running) {
    status = 'running'
    blockReason = `${task.label}正在运行，请等待当前任务完成。`
  } else if (hasResult && status === 'ready') {
    status = 'reuse_available'
  }
  return normalizeAnalysisTaskConfirmation({
    ...seed,
    taskKey: task.key,
    status,
    blockReason,
    parameterSummary: asText(seed.parameterSummary || seed.parameter_summary) || getAnalysisTaskParameterSummary(ctx, task.key),
    canStart: hasScope && !running,
    canReuse: hasResult,
  })
}

function resolveAnalysisTaskKeyFromTrace(trace = {}) {
  const toolName = asText(trace.tool_name || trace.toolName || trace.name)
  const artifacts = cloneArray(trace.produced_artifacts || trace.producedArtifacts || trace.produces)
    .map((item) => asText(item))
    .filter(Boolean)
  return Object.values(ANALYSIS_TASKS).find((task) => {
    if (task.toolNames.includes(toolName)) return true
    return artifacts.some((artifact) => task.producedArtifacts.includes(artifact))
  })?.key || ''
}

function buildAnalysisTaskConfirmationFromTurn(ctx, turn = {}) {
  const traceItems = cloneArray(turn && turn.diagnostics && turn.diagnostics.executionTrace)
  const matchedTrace = traceItems.find((item) => {
    const status = asText(item && item.status)
    return ['success', 'blocked', 'failed', 'start'].includes(status) && resolveAnalysisTaskKeyFromTrace(item)
  })
  const taskKey = resolveAnalysisTaskKeyFromTrace(matchedTrace)
  if (!taskKey) return null
  return buildAnalysisTaskConfirmation(ctx, taskKey, {
    id: `agent-task-${taskKey}-${Date.now().toString(36)}`,
  })
}

async function runAnalysisTask(ctx, taskKey = '', options = {}) {
  const task = getAnalysisTaskDefinition(taskKey)
  if (!ctx || !task) {
    throw new Error('未知分析任务')
  }
  if (options.focus !== false) {
    task.focus(ctx)
  }
  if (typeof ctx.$nextTick === 'function') {
    await ctx.$nextTick()
  }
  await task.run(ctx, options)
  return buildAnalysisTaskConfirmation(ctx, task.key, { status: 'completed' })
}

function focusAnalysisTaskPanel(ctx, taskKey = '') {
  const task = getAnalysisTaskDefinition(taskKey)
  if (!ctx || !task) return false
  task.focus(ctx)
  return true
}

function cloneAnalysisTaskConfirmation(item = null) {
  return item && typeof item === 'object'
    ? normalizeAnalysisTaskConfirmation(cloneObject(item))
    : null
}

export {
  buildAnalysisTaskConfirmation,
  buildAnalysisTaskConfirmationFromTurn,
  cloneAnalysisTaskConfirmation,
  focusAnalysisTaskPanel,
  getAnalysisTaskDefinition,
  getAnalysisTaskDefinitions,
  normalizeAnalysisTaskConfirmation,
  resolveAnalysisTaskKeyFromTrace,
  runAnalysisTask,
}
