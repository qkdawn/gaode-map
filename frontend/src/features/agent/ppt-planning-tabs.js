import { asText, cloneArray, cloneObject } from './normalizers.js'
import { getAnalysisTaskDefinition } from './analysis-task-registry.js'
import { createPptSystemSources, createPptTransportFromAiPayload } from '../ppt-planning/model.js'
import {
  classifyPptSourceGroups,
  cleanupPptVisualArtifacts,
  createPptDataPackage,
  deleteDocumentSource,
  generateDeckBrief,
  generateDeckBriefWithDebug,
  generateNarrativePlan,
  generateNarrativePlanWithDebug,
  generatePptSpec,
  generatePptSpecWithDebug,
  generatePptVisualArtifacts,
  getJobStatus,
  listPptDataSources,
  regenerateDeckBriefSlide,
  regeneratePptSpecSection,
  scheduleDocumentParse,
  uploadDocumentSource,
} from '../ppt-planning/api.js'
import {
  addPptDataPackageSource,
  appendPptGenerationDebugEvent,
  applyDeckBriefSlideRevision,
  applyGeneratedSlideBrief,
  applyPptVisualArtifactsResponse,
  applyPptOutlineSectionRevision,
  applyPptSourceGroupsResponse,
  buildDeckBriefSlidePayload,
  buildDeckBriefPayload,
  buildPptVisualArtifactsPayload,
  buildPptOutlineSectionPayload,
  buildNarrativePlanPayload,
  buildPptSpecPayload,
  collectPptVisualArtifactFilenames,
  completePptGenerationJob,
  createPptPlanningState,
  getActiveDeckSlideBrief,
  getBlockingPptInputSources,
  hasPptBlockingInputs,
  getPptSourceDeliveryManifest,
  getPptRevisionKey,
  getPptSourceSummary,
  isPptDirectivePageStale,
  failPptGenerationJob,
  failPptVisualArtifacts,
  failSlideGenerationQueue,
  markPptDirectiveStaleForSources,
  mergePptPlanningSources,
  movePptSourceToGroup,
  removePptSource,
  removePptSourceGroup,
  renamePptSource,
  renamePptSourceGroup,
  resetPptPlanningToMaterials,
  resetPptPlanningToNarrativeReady,
  resetPptPlanningToOutlineReady,
  selectDeckSlideBrief,
  setAllPptSourcesSelected,
  setPptDataPackageGenerating,
  setPptGenerationError,
  setPptSourceRefreshing,
  startPptGenerationJob,
  startPptVisualArtifactsGeneration,
  startSlideGenerationQueue,
  setPptActiveRevisionTarget,
  setPptRevisionDraftField,
  setPptRevisionGeneratingTarget,
  setPptSourceGroupEmoji,
  setPptSourceGrouping,
  setPptSpecField,
  setPptSourceGroupSelected,
  syncPptPackagePlaceholderSources,
  togglePptSourceGroupCollapsed,
  togglePptSourceSelection,
  undoPptSectionRevision,
  upsertPptDocumentSource,
} from '../ppt-planning/ui-state.js'

const DEFAULT_PPT_POI_EVIDENCE_INTENT = '为 PPT 指令生成整理当前区域代表性 POI 资料'
const DEFAULT_PPT_NIGHTLIFE_POI_INTENT = '整理夜生活与夜间消费相关 POI，并与夜光格子对应'
const DEFAULT_PPT_CARRIER_EVIDENCE_INTENT = '识别当前区域 POI、路网、人口、夜光共同支撑的空间载体'
const PPT_NIGHTLIFE_PACKAGE_VERSION = 'nightlife-evidence-v2'
const PPT_CARRIER_PACKAGE_VERSION = 'road-carrier-evidence-v2'
const PPT_AUTO_PACKAGE_DEFINITIONS = Object.freeze([
  {
    key: 'poi-evidence',
    title: 'POI 资料包',
    sourceIds: ['current:dataset:poi'],
    packageMode: 'evidence',
    intent: DEFAULT_PPT_POI_EVIDENCE_INTENT,
    limit: 50,
  },
  {
    key: 'nightlife-poi',
    title: '夜生活 POI × 夜光格子资料包',
    sourceIds: ['current:dataset:poi', 'current:analysis:nightlight'],
    packageMode: 'evidence',
    intent: DEFAULT_PPT_NIGHTLIFE_POI_INTENT,
    packageVersion: PPT_NIGHTLIFE_PACKAGE_VERSION,
    limit: 50,
  },
  {
    key: 'road-carrier',
    title: 'POI × 路网空间载体资料包',
    sourceIds: ['current:dataset:poi', 'current:analysis:road', 'current:analysis:population', 'current:analysis:nightlight'],
    packageMode: 'evidence',
    intent: DEFAULT_PPT_CARRIER_EVIDENCE_INTENT,
    packageVersion: PPT_CARRIER_PACKAGE_VERSION,
    limit: 50,
  },
])

function normalizePptGenerationErrorMessage(error = null, source = '') {
  const raw = asText(error && error.message ? error.message : error)
  const type = asText(source)
  const messages = {
    ppt_outline_llm_timeout: '目录生成超时，请稍后重试或减少来源数量。',
    ppt_planning_llm_timeout: 'AI 接口响应超时，请稍后重试。',
    ppt_outline_invalid_response: 'AI 返回的目录格式不完整，请重试。',
    invalid_ppt_outline: 'AI 返回的目录为空或格式不正确，请重试。',
    ppt_planning_invalid_ai_response: 'AI 返回内容不符合要求，请重试。',
    ppt_planning_llm_invalid_response: 'AI 返回的单页 brief 不是合法 JSON，已停止在当前页，请点击继续重试。',
    ppt_planning_llm_http_error: 'AI 接口返回错误，请稍后重试。',
    ppt_planning_llm_request_failed: 'AI 接口请求失败，请检查网络或接口配置。',
    ppt_planning_llm_unavailable: 'AI 接口未启用或配置不可用。',
  }
  return messages[raw] || raw || 'PPT 生成失败，请稍后重试。'
}

function normalizePptLngLat(value = null) {
  if (!value) return []
  let lng = NaN
  let lat = NaN
  if (Array.isArray(value)) {
    lng = Number(value[0])
    lat = Number(value[1])
  } else if (typeof value === 'object') {
    if (typeof value.getLng === 'function' && typeof value.getLat === 'function') {
      lng = Number(value.getLng())
      lat = Number(value.getLat())
    } else {
      lng = Number(value.lng ?? value.longitude ?? value.lon ?? value.x)
      lat = Number(value.lat ?? value.latitude ?? value.y)
    }
  }
  if (!Number.isFinite(lng) || !Number.isFinite(lat)) return []
  if (lng < -180 || lng > 180 || lat < -90 || lat > 90) return []
  return [lng, lat]
}

function hasRing(value) {
  return Array.isArray(value) && value.length >= 3
}

function resolvePptPlanningRadiusMeters(ctx = {}, featureProps = {}) {
  const explicitRadius = Number(featureProps.radius_m ?? featureProps.radiusM ?? 0)
  if (Number.isFinite(explicitRadius) && explicitRadius > 0) {
    return Math.min(50000, Math.round(explicitRadius))
  }
  if (ctx && typeof ctx._resolveCircleRadiusMeters === 'function') {
    const runtimeRadius = Number(ctx._resolveCircleRadiusMeters())
    if (Number.isFinite(runtimeRadius) && runtimeRadius > 0) {
      return Math.min(50000, Math.round(runtimeRadius))
    }
  }
  const speedByMode = { walking: 5, bicycling: 15, driving: 30 }
  const mode = asText(ctx && ctx.transportMode).toLowerCase()
  const speedKmh = Number(speedByMode[mode]) || speedByMode.walking
  const timeMin = Number((ctx && ctx.timeHorizon) || featureProps.time_min || featureProps.timeMin || 0) || 0
  if (!Number.isFinite(timeMin) || timeMin <= 0) return null
  return Math.min(50000, Math.round((speedKmh * 1000 * timeMin) / 60))
}

function finiteMetricValue(value) {
  if (value === null || value === undefined) return null
  if (typeof value === 'string' && value.trim() === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function metricScope(scope = {}) {
  const timeMin = finiteMetricValue(scope.time_min || scope.timeMin)
  const radiusM = finiteMetricValue(scope.radius_m || scope.radiusM)
  const parts = []
  if (timeMin !== null) parts.push(`${timeMin}分钟`)
  if (radiusM !== null) parts.push(`${Math.round(radiusM)}米`)
  return parts.join(' / ') || '当前分析范围'
}

function createAnalysisMetric(metrics, options = {}) {
  const domain = asText(options.domain)
  const key = asText(options.key)
  if (!domain || !key) return
  const sourceId = asText(options.sourceId) || `system:${domain}`
  const status = asText(options.status) || (finiteMetricValue(options.value) === null ? 'missing' : 'ready')
  const readyValue = status === 'ready' ? finiteMetricValue(options.value) : null
  metrics.push({
    metric_id: asText(options.metricId) || `analysis:${domain}:${key}`,
    domain,
    label: asText(options.label) || key,
    value: readyValue,
    unit: asText(options.unit),
    scope: asText(options.scope) || '当前分析范围',
    source_id: sourceId,
    source_ids: cloneArray(options.sourceIds).map((item) => asText(item)).filter(Boolean).length
      ? cloneArray(options.sourceIds).map((item) => asText(item)).filter(Boolean)
      : [sourceId],
    source_path: asText(options.sourcePath),
    calculation_method: asText(options.calculationMethod) || asText(options.method),
    status,
    description: asText(options.description),
  })
}

function addNumericAnalysisMetric(metrics, options = {}) {
  const value = finiteMetricValue(options.value)
  createAnalysisMetric(metrics, {
    ...options,
    value,
    status: value === null ? (asText(options.missingStatus) || 'missing') : 'ready',
  })
}

function addMissingAnalysisMetric(metrics, options = {}) {
  createAnalysisMetric(metrics, {
    ...options,
    status: asText(options.status) || 'missing',
    value: null,
  })
}

function buildPopulationAgeStructureMetric(ageRows = [], totalPopulation = null) {
  const rows = cloneArray(ageRows)
    .map((item) => ({
      age_band: asText(item && (item.age_band || item.ageBand)),
      age_band_label: asText(item && (item.age_band_label || item.ageBandLabel)),
      total: finiteMetricValue(item && item.total),
    }))
    .filter((item) => item.total !== null && item.total > 0)
    .sort((left, right) => right.total - left.total)
  if (!rows.length) return null
  const top = rows[0]
  const total = finiteMetricValue(totalPopulation)
  const ratio = total && total > 0 ? top.total / total : null
  return {
    value: ratio !== null ? Number((ratio * 100).toFixed(2)) : top.total,
    unit: ratio !== null ? '%' : '人',
    description: ratio !== null
      ? `主导年龄段为${top.age_band_label || top.age_band}，占总人口 ${Number((ratio * 100).toFixed(1))}%。`
      : `主导年龄段为${top.age_band_label || top.age_band}，人口约 ${Math.round(top.total)} 人。`,
  }
}

function buildCurrentNightlightAnalysis(ctx = {}) {
  const overview = cloneObject(ctx.nightlightOverview || {})
  const layer = cloneObject(ctx.nightlightLayer || {})
  return {
    ...overview,
    summary: {
      ...cloneObject(overview.summary || overview),
      ...cloneObject(layer.summary || {}),
    },
    analysis: cloneObject(layer.analysis || {}),
    view: asText(layer.view || ctx.nightlightAnalysisView || overview.view),
    scope_id: asText(layer.scope_id || overview.scope_id || ctx.nightlightScopeId),
    features: cloneArray(layer.cells),
  }
}

function averageFinite(values = []) {
  const finite = cloneArray(values).map((item) => Number(item)).filter((item) => Number.isFinite(item))
  if (!finite.length) return null
  return finite.reduce((sum, item) => sum + item, 0) / finite.length
}

function featurePropsList(features = []) {
  return cloneArray(features).map((feature) => cloneObject(feature && feature.properties)).filter((props) => Object.keys(props).length)
}

function buildPptAnalysisMetrics(ctx = {}, scope = {}, taskResults = {}) {
  const metrics = []
  const scopeText = metricScope(scope)
  const poiTotal = Array.isArray(ctx.allPoisDetails) ? ctx.allPoisDetails.length : null
  addNumericAnalysisMetric(metrics, {
    domain: 'poi',
    key: 'poi_count',
    label: 'POI 数量',
    value: poiTotal,
    unit: '个',
    scope: scopeText,
    sourceId: 'current:dataset:poi',
    sourceIds: ['current:dataset:poi'],
    sourcePath: 'allPoisDetails.length',
    calculationMethod: '当前范围内已抓取 POI 明细去重计数。',
    missingStatus: taskResults.poi_fetch ? 'missing' : 'not_ready',
    description: taskResults.poi_fetch ? 'POI 明细为空，无法形成数量指标。' : '请先完成 POI 抓取。',
  })

  const h3 = cloneObject(ctx.h3AnalysisSummary || {})
  const h3Features = featurePropsList(ctx.h3AnalysisGridFeatures)
  const h3DerivedStats = cloneObject(ctx.h3DerivedStats)
  const typingSummary = cloneObject(h3DerivedStats.typingSummary)
  const lqSummary = cloneObject(h3DerivedStats.lqSummary)
  const h3Ready = !!(ctx.h3AnalysisSummary || Number(ctx.h3GridCount || 0) > 0)
  const avgNeighborDensity = averageFinite(h3Features.map((props) => props.neighbor_mean_density))
  const avgNeighborEntropy = averageFinite(h3Features.map((props) => props.neighbor_mean_entropy))
  const maxLq = finiteMetricValue(lqSummary.maxLq ?? lqSummary.max_lq)
  const lqOpportunityCount = finiteMetricValue(lqSummary.opportunityCount ?? lqSummary.opportunity_count)
  const typingOpportunityCount = finiteMetricValue(typingSummary.opportunityCount ?? typingSummary.opportunity_count)
  const highMixCount = Object.entries(cloneObject(typingSummary.counts))
    .filter(([key]) => asText(key).includes('high_mix'))
    .reduce((sum, [, value]) => sum + (Number(value) || 0), 0)
  const typingRowCount = cloneArray(typingSummary.rows).length
  const functionalMixValue = finiteMetricValue(h3.functional_mix_score)
    ?? typingOpportunityCount
    ?? (typingRowCount ? highMixCount / typingRowCount : null)
  const hasSummaryFunctionalMix = finiteMetricValue(h3.functional_mix_score) !== null
  ;[
    ['grid_count', '网格数量', '个', h3.grid_count || ctx.h3GridCount, 'h3AnalysisSummary.grid_count'],
    ['poi_count', 'H3 POI 数量', '个', h3.poi_count, 'h3AnalysisSummary.poi_count'],
    ['avg_density_poi_per_km2', '平均 POI 密度', '个/km²', h3.avg_density_poi_per_km2, 'h3AnalysisSummary.avg_density_poi_per_km2'],
    ['avg_local_entropy', '平均局部熵', '', h3.avg_local_entropy, 'h3AnalysisSummary.avg_local_entropy'],
    ['global_moran_i_density', '密度 Moran I', '', h3.global_moran_i_density, 'h3AnalysisSummary.global_moran_i_density'],
    ['functional_mix_score', '功能混合度', hasSummaryFunctionalMix ? '分' : '', functionalMixValue, hasSummaryFunctionalMix ? 'h3AnalysisSummary.functional_mix_score' : 'h3DerivedStats.typingSummary'],
  ].forEach(([key, label, unit, value, sourcePath]) => addNumericAnalysisMetric(metrics, {
    domain: 'h3',
    key,
    label,
    value,
    unit,
    scope: scopeText,
    sourceId: 'current:analysis:poi_h3',
    sourceIds: ['current:dataset:h3', 'current:analysis:poi_h3'],
    sourcePath,
    calculationMethod: `${label}来自 POI H3 空间分析汇总。`,
    missingStatus: h3Ready ? 'missing' : 'not_ready',
    description: h3Ready ? `${label}当前结果未返回。` : '请先完成 POI H3 网格分析。',
  }))
  addNumericAnalysisMetric(metrics, {
    domain: 'h3',
    key: 'typing_opportunity_count',
    label: '高密高混合机会格数量',
    value: typingOpportunityCount,
    unit: '个',
    scope: scopeText,
    sourceId: 'current:analysis:poi_h3',
    sourceIds: ['current:analysis:poi_h3'],
    sourcePath: 'h3DerivedStats.typingSummary.opportunityCount',
    calculationMethod: '来自 H3 功能混合类型诊断，统计高密-高混合且邻域差值为正的机会格。',
    missingStatus: h3Ready ? 'missing' : 'not_ready',
    description: h3Ready ? '当前 H3 派生结果未提供功能混合机会格。' : '请先完成 POI H3 网格分析。',
  })
  ;[
    ['gi_z_stats.mean', 'Gi* Z 均值', h3.gi_z_stats && h3.gi_z_stats.mean],
    ['gi_z_stats.max', 'Gi* Z 峰值', h3.gi_z_stats && h3.gi_z_stats.max],
    ['lisa_i_stats.mean', 'LISA I 均值', h3.lisa_i_stats && h3.lisa_i_stats.mean],
    ['lisa_i_stats.max', 'LISA I 峰值', h3.lisa_i_stats && h3.lisa_i_stats.max],
  ].forEach(([key, label, value]) => addNumericAnalysisMetric(metrics, {
    domain: 'h3',
    key: key.replace(/\./g, '_'),
    label,
    value,
    scope: scopeText,
    sourceId: 'current:analysis:poi_h3',
    sourceIds: ['current:analysis:poi_h3'],
    sourcePath: `h3AnalysisSummary.${key}`,
    calculationMethod: `${label}来自 H3 空间自相关统计。`,
    missingStatus: h3Ready ? 'missing' : 'not_ready',
    description: h3Ready ? `${label}当前结果未返回。` : '请先完成 POI H3 网格分析。',
  }))
  addNumericAnalysisMetric(metrics, {
    domain: 'h3',
    key: 'neighbor_interpolation',
    label: '邻域均值/邻域插值',
    value: avgNeighborDensity,
    unit: '个/km²',
    scope: scopeText,
    sourceId: 'current:analysis:poi_h3',
    sourceIds: ['current:analysis:poi_h3'],
    sourcePath: 'h3AnalysisGridFeatures.properties.neighbor_mean_density',
    calculationMethod: '对 H3 网格属性 neighbor_mean_density 做均值汇总。',
    missingStatus: h3Ready ? 'missing' : 'not_ready',
    description: h3Ready ? '当前 H3 汇总未提供邻域插值结果。' : '请先完成 POI H3 网格分析。',
  })
  addNumericAnalysisMetric(metrics, {
    domain: 'h3',
    key: 'neighbor_mean_entropy',
    label: '邻域平均熵',
    value: avgNeighborEntropy,
    scope: scopeText,
    sourceId: 'current:analysis:poi_h3',
    sourceIds: ['current:analysis:poi_h3'],
    sourcePath: 'h3AnalysisGridFeatures.properties.neighbor_mean_entropy',
    calculationMethod: '对 H3 网格属性 neighbor_mean_entropy 做均值汇总。',
    missingStatus: h3Ready ? 'missing' : 'not_ready',
    description: h3Ready ? '当前 H3 汇总未提供邻域熵结果。' : '请先完成 POI H3 网格分析。',
  })
  addNumericAnalysisMetric(metrics, {
    domain: 'h3',
    key: 'lq',
    label: '区位商 LQ',
    value: maxLq,
    scope: scopeText,
    sourceId: 'current:analysis:poi_h3',
    sourceIds: ['current:analysis:poi_h3'],
    sourcePath: 'h3DerivedStats.lqSummary.maxLq',
    calculationMethod: '来自 H3 区位商诊断，取目标业态 LQ 最大值。',
    missingStatus: h3Ready ? 'missing' : 'not_ready',
    description: h3Ready ? '当前 H3 汇总未提供 LQ 结果。' : '请先完成 POI H3 网格分析。',
  })
  addNumericAnalysisMetric(metrics, {
    domain: 'h3',
    key: 'lq_opportunity_count',
    label: 'LQ 优势格数量',
    value: lqOpportunityCount,
    unit: '个',
    scope: scopeText,
    sourceId: 'current:analysis:poi_h3',
    sourceIds: ['current:analysis:poi_h3'],
    sourcePath: 'h3DerivedStats.lqSummary.opportunityCount',
    calculationMethod: '来自 H3 区位商诊断，统计目标业态 LQ >= 1.2 的优势格。',
    missingStatus: h3Ready ? 'missing' : 'not_ready',
    description: h3Ready ? '当前 H3 派生结果未提供 LQ 优势格数量。' : '请先完成 POI H3 网格分析。',
  })

  const populationOverview = cloneObject(ctx.populationOverview || {})
  const populationSummary = cloneObject(populationOverview.summary || populationOverview)
  const populationLayerSummary = cloneObject(ctx.populationLayer && ctx.populationLayer.summary)
  const populationReady = !!ctx.populationOverview
  const populationDensity = populationLayerSummary.average_density_per_km2
    ?? populationLayerSummary.population_density
    ?? populationLayerSummary.density
    ?? populationSummary.population_density
    ?? populationSummary.density
  ;[
    ['total_population', '总人口', '人', populationSummary.total_population || populationSummary.population_total || populationSummary.total],
    ['population_density', '人口密度', '人/km²', populationDensity, Object.prototype.hasOwnProperty.call(populationLayerSummary, 'average_density_per_km2') ? 'populationLayer.summary.average_density_per_km2' : 'populationOverview.summary.population_density'],
    ['male_ratio', '男性占比', '%', populationSummary.male_ratio],
    ['female_ratio', '女性占比', '%', populationSummary.female_ratio],
  ].forEach(([key, label, unit, value, sourcePath]) => addNumericAnalysisMetric(metrics, {
    domain: 'population',
    key,
    label,
    value,
    unit,
    scope: scopeText,
    sourceId: 'current:analysis:population',
    sourceIds: ['current:analysis:population'],
    sourcePath: sourcePath || `populationOverview.summary.${key}`,
    calculationMethod: `${label}来自当前范围人口分析汇总。`,
    missingStatus: populationReady ? 'missing' : 'not_ready',
    description: populationReady ? `${label}当前结果未返回。` : '请先完成人口计算。',
  }))
  const ageStructure = buildPopulationAgeStructureMetric(populationOverview.age_distribution, populationSummary.total_population)
  if (ageStructure) {
    addNumericAnalysisMetric(metrics, {
      domain: 'population',
      key: 'age_structure',
      label: '年龄结构',
      value: ageStructure.value,
      unit: ageStructure.unit,
      scope: scopeText,
      sourceId: 'current:analysis:population',
      sourceIds: ['current:analysis:population'],
      sourcePath: 'populationOverview.age_distribution',
      calculationMethod: '从人口年龄分布中选取人口数最高的主导年龄段，并计算其占比。',
      description: ageStructure.description,
    })
  } else {
    addMissingAnalysisMetric(metrics, {
      domain: 'population',
      key: 'age_structure',
      label: '年龄结构',
      scope: scopeText,
      sourceId: 'current:analysis:population',
      sourceIds: ['current:analysis:population'],
      sourcePath: 'populationOverview.age_distribution',
      status: populationReady ? 'missing' : 'not_ready',
      description: populationReady ? '当前人口分析未提供年龄结构。' : '请先完成人口计算。',
    })
  }

  const nightlightAnalysis = buildCurrentNightlightAnalysis(ctx)
  const nightlightLayerAnalysis = cloneObject(nightlightAnalysis.analysis || {})
  const nightlightSummary = {
    ...cloneObject(nightlightAnalysis.summary || {}),
    ...nightlightLayerAnalysis,
  }
  const nightlightReady = !!taskResults.nightlight
  ;[
    ['total_radiance', '夜光总辐亮', '', nightlightSummary.total_radiance],
    ['mean_radiance', '夜光均值', '', nightlightSummary.mean_radiance || nightlightSummary.mean],
    ['max_radiance', '夜光峰值', '', nightlightSummary.max_radiance || nightlightSummary.max],
    ['lit_pixel_ratio', '亮光像元占比', '%', nightlightSummary.lit_pixel_ratio],
    ['core_hotspot_count', '核心热点数', '个', nightlightSummary.core_hotspot_count],
    ['hotspot_cell_ratio', '热点格占比', '%', nightlightSummary.hotspot_cell_ratio],
    ['peak_to_edge_ratio', '峰边比', '', nightlightSummary.peak_to_edge_ratio],
  ].forEach(([key, label, unit, value]) => addNumericAnalysisMetric(metrics, {
    domain: 'nightlight',
    key,
    label,
    value,
    unit,
    scope: scopeText,
    sourceId: 'current:analysis:nightlight',
    sourceIds: ['current:analysis:nightlight'],
    sourcePath: Object.prototype.hasOwnProperty.call(nightlightLayerAnalysis, key)
      ? `nightlightLayer.analysis.${key}`
      : `nightlight.summary.${key}`,
    calculationMethod: `${label}来自当前范围夜光分析汇总。`,
    missingStatus: nightlightReady ? 'missing' : 'not_ready',
    description: finiteMetricValue(value) === null
      ? (nightlightReady ? `${label}当前结果未返回。` : '请先完成夜光计算。')
      : `${label}已从当前夜光分析结果读取。`,
  }))
  addNumericAnalysisMetric(metrics, {
    domain: 'nightlight',
    key: 'gradient_decay',
    label: '梯度/衰减类指标',
    value: nightlightSummary.peak_to_edge_ratio,
    scope: scopeText,
    sourceId: 'current:analysis:nightlight',
    sourceIds: ['current:analysis:nightlight'],
    sourcePath: 'nightlightLayer.analysis.peak_to_edge_ratio',
    calculationMethod: '以峰值格亮度与边缘/外圈平均亮度的比值表达夜光空间衰减强弱。',
    missingStatus: nightlightReady ? 'missing' : 'not_ready',
    description: finiteMetricValue(nightlightSummary.peak_to_edge_ratio) === null
      ? (nightlightReady ? '当前夜光分析未提供梯度/衰减结果。' : '请先完成夜光计算。')
      : '梯度/衰减类指标已从峰边比读取。',
  })

  const roadSummary = cloneObject(ctx.roadSyntaxSummary || {})
  const roadReady = !!ctx.roadSyntaxSummary
  ;[
    ['node_count', '路网节点数', '个', roadSummary.node_count],
    ['edge_count', '路网边数', '条', roadSummary.edge_count],
    ['avg_connectivity', '平均连接度', '', roadSummary.avg_connectivity ?? roadSummary.connectivity, 'roadSyntaxSummary.avg_connectivity'],
    ['avg_control', '平均控制度', '', roadSummary.avg_control ?? roadSummary.control, 'roadSyntaxSummary.avg_control'],
    ['avg_depth', '平均深度值', '', roadSummary.avg_depth ?? roadSummary.depth, 'roadSyntaxSummary.avg_depth'],
    ['avg_choice', '平均选择度', '', roadSummary.avg_choice ?? roadSummary.avg_choice_local ?? roadSummary.avg_choice_global ?? roadSummary.choice, 'roadSyntaxSummary.avg_choice|avg_choice_local|avg_choice_global'],
    ['avg_integration', '平均整合度', '', roadSummary.avg_integration ?? roadSummary.avg_integration_local ?? roadSummary.avg_integration_global ?? roadSummary.integration ?? roadSummary.avg_closeness ?? roadSummary.avg_accessibility_global, 'roadSyntaxSummary.avg_integration|avg_integration_local|avg_integration_global'],
    ['avg_intelligibility', '平均可理解度', '', roadSummary.avg_intelligibility ?? roadSummary.intelligibility, 'roadSyntaxSummary.avg_intelligibility'],
  ].forEach(([key, label, unit, value, sourcePath]) => addNumericAnalysisMetric(metrics, {
    domain: 'road',
    key,
    label,
    value,
    unit,
    scope: scopeText,
    sourceId: 'current:analysis:road',
    sourceIds: ['current:analysis:road'],
    sourcePath: sourcePath || `roadSyntaxSummary.${key}`,
    calculationMethod: `${label}来自当前范围路网句法分析汇总。`,
    missingStatus: roadReady ? 'missing' : 'not_ready',
    description: roadReady ? `${label}当前结果未返回。` : '请先完成路网计算。',
  }))

  return {
    version: 'current_metrics_v1',
    metrics,
  }
}

function buildPptDataPackageSpatialPayload(current = {}) {
  const scope = cloneObject(current.scope)
  const center = normalizePptLngLat(scope.center || scope.center_gcj02 || scope.centerGcj02)
  const payload = {}
  if (center.length) {
    payload.center = center
    payload.center_coord_type = asText(scope.center_coord_type || scope.centerCoordType) || 'gcj02'
  }
  const radiusM = Number(scope.radius_m ?? scope.radiusM ?? 0)
  if (Number.isFinite(radiusM) && radiusM > 0) {
    payload.radius_m = Math.min(50000, Math.round(radiusM))
  }
  return payload
}

function isReadySource(source = {}) {
  return asText(source && source.status) === 'ready'
}

function isPptDocumentSource(source = {}) {
  const meta = cloneObject(source && source.meta)
  return asText(meta.sourceKind) === 'document' || asText(source && source.id).startsWith('document:')
}

function documentIdFromPptSource(source = {}) {
  const meta = cloneObject(source && source.meta)
  const document = cloneObject(meta.document)
  const explicit = asText(meta.documentId || meta.document_id || document.id || document.document_id)
  if (explicit) return explicit
  const sourceId = asText(source && source.id)
  return sourceId.startsWith('document:') ? sourceId.slice('document:'.length) : ''
}

function createPptSourceTransportPreview({
  sourceId = '',
  title = '',
  sourceKind = '',
  metricCount = 0,
  evidenceCount = 0,
  visualSpecCount = 0,
  excludedType = '',
  excludedReason = '',
  policy = '',
} = {}) {
  const included = []
  if (Number(metricCount || 0) > 0) included.push('metrics')
  if (Number(evidenceCount || 0) > 0) included.push('evidence')
  return {
    source_id: asText(sourceId),
    sourceId: asText(sourceId),
    title: asText(title),
    source_kind: asText(sourceKind),
    sourceKind: asText(sourceKind),
    transport_status: included.length ? 'ready_to_send' : 'selected_no_payload',
    transportStatus: included.length ? 'ready_to_send' : 'selected_no_payload',
    included,
    metric_count: Number(metricCount || 0) || 0,
    metricCount: Number(metricCount || 0) || 0,
    evidence_count: Number(evidenceCount || 0) || 0,
    evidenceCount: Number(evidenceCount || 0) || 0,
    visual_spec_count: Number(visualSpecCount || 0) || 0,
    visualSpecCount: Number(visualSpecCount || 0) || 0,
    excluded: excludedType ? [{ type: excludedType, reason: excludedReason }] : [],
    policy: asText(policy) || '生成时发送这里显示的 metrics/evidence；完整原始数据不进入 LLM。',
    preview: true,
  }
}

function createPptAiInputBlock({
  sourceId = '',
  title = '',
  sourceKind = '',
  scope = null,
  metrics = [],
  metricGaps = [],
  evidence = [],
  visualSpecs = [],
  excluded = [],
  policy = '',
} = {}) {
  const normalizedScope = scope && typeof scope === 'object' ? cloneObject(scope) : null
  const readyMetrics = cloneArray(metrics).filter((metric) => asText(metric.status) === 'ready')
  const gaps = cloneArray(metricGaps)
  const evidenceItems = cloneArray(evidence).filter((item) => asText(item.title || item.text))
  const visuals = cloneArray(visualSpecs).filter((item) => asText(item.visual_id || item.visualId || item.title))
  const included = []
  if (normalizedScope) included.push('scope')
  if (readyMetrics.length) included.push('metrics')
  if (gaps.length) included.push('metric_gaps')
  if (evidenceItems.length) included.push('evidence')
  if (visuals.length) included.push('visual_specs')
  return {
    version: 'ppt_ai_input_block_v1',
    source_id: asText(sourceId),
    sourceId: asText(sourceId),
    title: asText(title),
    source_kind: asText(sourceKind),
    sourceKind: asText(sourceKind),
    included,
    scope: normalizedScope,
    metrics: readyMetrics,
    metric_gaps: gaps,
    metricGaps: gaps,
    evidence: evidenceItems,
    visual_specs: visuals,
    visualSpecs: visuals,
    excluded: cloneArray(excluded),
    counts: {
      scope: normalizedScope ? 1 : 0,
      metrics: readyMetrics.length,
      metric_gaps: gaps.length,
      evidence: evidenceItems.length,
      visual_specs: visuals.length,
    },
    policy: asText(policy) || '生成时只发送这个 AI 输入块；原始数据不进入 LLM。',
  }
}

function createDocumentAiPayload(sourceId = '', title = '', meta = {}, status = 'pending', count = 0) {
  const nodes = cloneArray(meta.document_index_preview || meta.documentIndexPreview)
  const evidence = status === 'ready'
    ? nodes.slice(0, 40).map((node, index) => {
      const item = cloneObject(node)
      return {
        source_id: sourceId,
        sourceId,
        source_title: title,
        sourceTitle: title,
        type: 'pageindex_node',
        title: asText(item.title) || `文档章节 ${index + 1}`,
        text: asText(item.summary || item.text),
        citation: item.page_start || item.pageStart ? `PageIndex p.${item.page_start || item.pageStart}` : '',
        payload: {
          node_id: asText(item.node_id || item.nodeId),
          parent_node_id: asText(item.parent_node_id || item.parentNodeId),
          level: item.level,
          page_start: item.page_start || item.pageStart,
          page_end: item.page_end || item.pageEnd,
        },
      }
    }).filter((item) => asText(item.text))
    : []
  return createPptAiInputBlock({
    sourceId,
    title,
    sourceKind: 'document',
    evidence,
    excluded: [{ type: 'document_full_text', reason: '不传文档全文，只传 PageIndex 节点/章节摘要。', count: Number(count || nodes.length || 0) || 0 }],
    policy: '文档来源只通过 PageIndex 节点/章节摘要进入 evidence；不从全文临时抽取。',
  })
}

function compactPackageEvidenceItem(sourceId = '', title = '', type = '', item = {}) {
  const payload = cloneObject(item)
  return {
    source_id: sourceId,
    sourceId,
    source_title: title,
    sourceTitle: title,
    type,
    title: asText(payload.title || payload.name || payload.carrier_label || payload.carrier_id) || title,
    text: asText(payload.summary || payload.address || payload.selection_reason || payload.category || payload.subcategory),
    payload,
  }
}

function createPackageAiPayload(sourceId = '', title = '', pack = {}) {
  const evidence = []
  const payload = cloneObject(pack)
  if (payload.summary) {
    evidence.push({
      source_id: sourceId,
      sourceId,
      source_title: title,
      sourceTitle: title,
      type: 'package_summary',
      title: asText(payload.title) || title,
      text: asText(payload.summary),
      payload: {
        package_mode: asText(payload.package_mode),
        intent: asText(payload.intent),
        total: payload.total,
        carrier_summary: cloneObject(payload.carrier_summary || payload.carrierSummary),
        alignment: cloneObject(payload.alignment),
      },
    })
  }
  cloneArray(payload.items).slice(0, 6).forEach((item) => {
    evidence.push(compactPackageEvidenceItem(sourceId, title, 'package_poi_sample', {
      id: item.id,
      name: item.name,
      category: item.category,
      subcategory: item.subcategory,
      address: item.address,
      distance_m: item.distance_m || item.distanceM,
      carrier_id: item.carrier_id || item.carrierId,
      carrier_label: item.carrier_label || item.carrierLabel,
      cell_id: item.cell_id || item.cellId,
    }))
  })
  cloneArray(payload.carriers).slice(0, 8).forEach((item) => {
    evidence.push(compactPackageEvidenceItem(sourceId, title, 'package_carrier', {
      carrier_id: item.carrier_id || item.carrierId,
      carrier_type: item.carrier_type || item.carrierType,
      carrier_label: item.carrier_label || item.carrierLabel,
      summary: item.summary,
      road_metrics: item.road_metrics || item.roadMetrics,
      poi_metrics: item.poi_metrics || item.poiMetrics,
      population_metrics: item.population_metrics || item.populationMetrics,
      nightlight_metrics: item.nightlight_metrics || item.nightlightMetrics,
    }))
  })
  return createPptAiInputBlock({
    sourceId,
    title,
    sourceKind: 'package',
    evidence,
    excluded: [
      { type: 'package_full_items', reason: '不传资料包完整 POI 明细，只传摘要和代表样本。', count: cloneArray(payload.items).length },
      { type: 'package_carrier_geometries', reason: '不传载体完整 geometry，只传载体摘要和指标摘要。', count: cloneArray(payload.carriers).length },
    ],
    policy: '资料包只通过摘要、代表样本、载体摘要进入 evidence；不传完整明细。',
  })
}

function normalizeBackendPptDataSource(source = {}, areaId = '') {
  const status = asText(source.status) || 'pending'
  const summary = asText(source.summary)
  const meta = cloneObject(source.meta)
  const pack = cloneObject(meta.package)
  const packageVersion = asText(meta.packageVersion || meta.package_version || pack.package_version)
  const sourceKind = asText(meta.sourceKind) || (asText(source.type) === 'document' || asText(source.id).startsWith('document:') ? 'document' : 'system')
  const sourceId = asText(source.id)
  const indexPreview = cloneArray(meta.document_index_preview || meta.documentIndexPreview)
  const evidenceCount = sourceKind === 'document' && status === 'ready'
    ? (indexPreview.length || Number(source.count || meta.count || 0) || 0)
    : 0
  const title = asText(source.title) || '未命名来源'
  const persistedAiPayload = cloneObject(meta.aiPayload || meta.ai_payload)
  const aiPayload = sourceKind === 'document'
    ? createDocumentAiPayload(sourceId, title, meta, status, Number(source.count || meta.count || evidenceCount || 0) || 0)
    : sourceKind === 'package' && persistedAiPayload.version !== 'ppt_ai_input_block_v1'
      ? createPackageAiPayload(sourceId, title, pack)
      : persistedAiPayload
  return {
    id: sourceId,
    type: asText(source.type) || 'data',
    title,
    status,
    selected: status === 'ready',
    meta: {
      ...meta,
      label: asText(meta.label) || summary || (status === 'ready' ? '已生成' : '待生成'),
      sourceKind,
      areaId: sourceKind === 'system' || sourceKind === 'package' ? (asText(meta.areaId) || asText(meta.area_id) || asText(areaId)) : asText(meta.areaId),
      packageVersion,
      package: sourceKind === 'package'
        ? { ...pack, package_version: packageVersion, area_id: asText(pack.area_id) || asText(meta.areaId) || asText(areaId) }
        : pack,
      count: Number(source.count || meta.count || 0) || 0,
      aiPayload,
      ai_payload: aiPayload,
      transport: aiPayload && aiPayload.version ? createPptTransportFromAiPayload(aiPayload) : (meta.transport || createPptSourceTransportPreview({
        sourceId,
        title,
        sourceKind,
        evidenceCount,
        excludedType: sourceKind === 'document' ? 'document_full_text' : '',
        excludedReason: sourceKind === 'document' ? '不传文档全文，只传 PageIndex 章节摘要。' : '',
        policy: sourceKind === 'document' ? '文档来源已通过 PageIndex 构建 evidence；生成时只发送章节摘要。' : '',
      })),
    },
  }
}

function hasPptEvidencePackage(state = {}, areaId = '', options = {}) {
  const normalizedAreaId = asText(areaId)
  const expectedMode = asText(options.packageMode) || 'evidence'
  const expectedIntent = asText(options.intent)
  const expectedVersion = asText(options.packageVersion)
  const expectedSourceIds = cloneArray(options.sourceIds).map((item) => asText(item)).filter(Boolean)
  return cloneArray(createPptPlanningState(state).sources).some((source) => {
    const meta = cloneObject(source.meta)
    const pack = cloneObject(meta.package)
    const sourceIds = cloneArray(pack.source_ids).map((item) => asText(item))
    if (asText(meta.sourceKind) !== 'package' && !asText(source.id).startsWith('package:')) return false
    if (normalizedAreaId && asText(meta.areaId) !== normalizedAreaId) return false
    if (expectedMode && asText(pack.package_mode) !== expectedMode) return false
    if (expectedIntent && asText(pack.intent) !== expectedIntent) return false
    if (expectedVersion && asText(meta.packageVersion) !== expectedVersion) return false
    return expectedSourceIds.every((sourceId) => sourceIds.includes(sourceId))
  })
}

function getPptEvidencePackageKey(areaId = '', options = {}) {
  const normalizedAreaId = asText(areaId)
  const sourceKey = cloneArray(options.sourceIds).map((item) => asText(item)).filter(Boolean).sort().join('+')
  const mode = asText(options.packageMode) || 'evidence'
  const intent = asText(options.intent)
  const version = asText(options.packageVersion)
  return normalizedAreaId ? `${normalizedAreaId}::${sourceKey}::${mode}::${intent}::${version}` : ''
}

function getPptAutoPackageDefinition(key = '') {
  return PPT_AUTO_PACKAGE_DEFINITIONS.find((item) => item.key === asText(key)) || null
}

function delay(ms = 0) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

async function waitForPptPlanningJob(jobId = '', { attempts = 20, intervalMs = 1500 } = {}) {
  const normalizedJobId = asText(jobId)
  if (!normalizedJobId) return null
  for (let index = 0; index < attempts; index += 1) {
    const job = await getJobStatus(normalizedJobId)
    const status = asText(job && job.status)
    if (status === 'succeeded') return job
    if (status === 'failed') throw new Error(asText(job && job.error) || 'document_job_failed')
    await delay(intervalMs)
  }
  return null
}

function attachPptDataPackageRuntimeMeta(response = {}, areaId = '', options = {}) {
  const source = cloneObject(response.source || response)
  if (!source.id) return response
  const meta = cloneObject(source.meta)
  const pack = cloneObject(meta.package)
  const title = asText(source.title)
  const aiPayload = createPackageAiPayload(asText(source.id), title, pack)
  return {
    ...response,
    source: {
      ...source,
      meta: {
        ...meta,
        areaId: asText(areaId),
        autoGenerated: !!options.autoGenerated,
        packageVersion: asText(options.packageVersion),
        aiPayload,
        ai_payload: aiPayload,
        transport: createPptTransportFromAiPayload(aiPayload),
      },
    },
  }
}

function selectedSourceIdsFromState(state = {}) {
  return cloneArray(createPptPlanningState(state).sources)
    .filter((source) => source && source.selected && asText(source.status) === 'ready')
    .map((source) => asText(source.id))
    .filter(Boolean)
}

function changedReadySourceIds(previous = {}, next = {}) {
  const previousIds = new Set(selectedSourceIdsFromState(previous))
  const nextIds = new Set(selectedSourceIdsFromState(next))
  return [...new Set([...previousIds, ...nextIds])].filter((sourceId) => previousIds.has(sourceId) !== nextIds.has(sourceId))
}

function uniquePptText(items = []) {
  return [...new Set(cloneArray(items).map((item) => asText(item)).filter(Boolean))]
}

function createPptGenerationRequestId(type = '') {
  const random = typeof globalThis.crypto !== 'undefined' && typeof globalThis.crypto.randomUUID === 'function'
    ? globalThis.crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
  return `ppt-${asText(type) || 'generation'}-${random}`
}

function pptGenerationJobDebug(job = {}) {
  const source = cloneObject(job)
  return {
    id: asText(source.id),
    phase: asText(source.phase),
    type: asText(source.type),
  }
}

function appendPptDebugEventToState(state = {}, eventName = '', details = {}) {
  return appendPptGenerationDebugEvent(createPptPlanningState(state), eventName, details)
}

export function normalizeAgentPptPlanningTab(item = {}, options = {}) {
  const source = asText(item && item.source) || 'draft'
  let pptPlanningState = createPptPlanningState(item && (item.ppt_planning_state || item.pptPlanningState))
  const generationJob = cloneObject(pptPlanningState.generationJob)
  if (options.restore && ['requesting', 'response_received', 'applying'].includes(asText(generationJob.phase))) {
    pptPlanningState = failPptGenerationJob(
      pptPlanningState,
      generationJob.id,
      '页面已重新加载，请重新发起生成请求。',
      { source: generationJob.type },
    )
    pptPlanningState = appendPptDebugEventToState(
      pptPlanningState,
      'tabs_restored_from_session',
      {
        sessionId: asText(options.sessionId || options.session_id),
        tabId: asText(item && item.id),
        restoredAsFailed: true,
        before: pptGenerationJobDebug(generationJob),
        after: pptGenerationJobDebug(pptPlanningState.generationJob),
      },
    )
  }
  return {
    id: asText(item && item.id),
    kind: 'ppt_planning',
    title: asText(item && item.title) || '策划 PPT',
    source,
    sessionId: asText((item && (item.session_id || item.sessionId)) || ''),
    readonly: options.restore ? !!(item && item.readonly && source !== 'history') : !!(item && item.readonly),
    createdAt: asText(item && (item.created_at || item.createdAt)) || new Date().toISOString(),
    panelPayloads: cloneObject(item && (item.panel_payloads || item.panelPayloads)),
    pptPlanningState,
  }
}

export function serializeAgentPptPlanningTab(item = {}, fallbackPanelPayloads = {}) {
  return {
    id: item.id,
    title: item.title || '策划 PPT',
    kind: 'ppt_planning',
    source: item.source || 'draft',
    session_id: item.sessionId || '',
    readonly: !!item.readonly,
    created_at: item.createdAt,
    panel_payloads: cloneObject(item.panelPayloads || fallbackPanelPayloads),
    ppt_planning_state: createPptPlanningState(item.pptPlanningState),
  }
}

export function createAgentPptPlanningTabMethods() {
  return {
    appendPptPlanningDebugEvent(state = {}, eventName = '', details = {}) {
      return appendPptDebugEventToState(state, eventName, details)
    },
    createAgentPptPlanningViewId() {
      return `ppt-planning-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
    },
    openAgentPptPlanningFromReport(options = {}) {
      this.agentWorkspaceView = 'report'
      const tabs = this.ensureAgentTabs(true)
      const existing = cloneArray(tabs.pptPlanningTabs).find((item) => asText(item && item.source) === 'current' || asText(item && item.source) === 'draft')
      if (existing && !options.forceNew) {
        const alreadyActive = asText(tabs.activeTabId) === asText(existing.id)
        this.switchAgentTopTab(existing.id)
        if (alreadyActive) {
          this.refreshAgentActivePptPlanningSources()
          this.refreshAgentActivePptPlanningDataSources()
        }
        return existing.id
      }
      return this.createAgentPptPlanningTab({ title: '策划 PPT', source: 'current' })
    },
    isAgentPptPlanningTabActive() {
      return asText(this.getAgentActiveTopTab().kind) === 'ppt_planning'
    },
    getAgentActivePptPlanningTab() {
      const tabs = this.ensureAgentTabs(false)
      const activeId = asText(tabs.activeTabId)
      return cloneArray(tabs.pptPlanningTabs).find((item) => asText(item && item.id) === activeId) || null
    },
    getAgentActivePptPlanningState() {
      const tab = this.getAgentActivePptPlanningTab()
      return createPptPlanningState(tab && tab.pptPlanningState)
    },
    getAgentPptPlanningTabState(tabId = '') {
      const targetId = asText(tabId)
      if (!targetId) return createPptPlanningState()
      const tabs = this.ensureAgentTabs(false)
      const tab = cloneArray(tabs.pptPlanningTabs).find((item) => asText(item && item.id) === targetId) || null
      return createPptPlanningState(tab && tab.pptPlanningState)
    },
    buildAgentPptPlanningCurrent() {
      const siteSelectionScope = typeof this.normalizeAgentSiteSelectionScope === 'function'
        ? this.normalizeAgentSiteSelectionScope()
        : {}
      const panelPayloads = cloneObject(this.agentPanelPayloads)
      const taskKeys = ['poi_fetch', 'poi_h3_grid', 'population', 'nightlight', 'road_syntax']
      const taskResults = {}
      taskKeys.forEach((taskKey) => {
        const def = getAnalysisTaskDefinition(taskKey)
        taskResults[taskKey] = !!(def && typeof def.hasResult === 'function' && def.hasResult(this))
      })
      const summaryReady = typeof this.hasAgentSummaryPack === 'function'
        ? this.hasAgentSummaryPack(panelPayloads.summary_pack || panelPayloads.summaryPack)
        : !!(panelPayloads.summary_pack || panelPayloads.summaryPack)
      const poiTotal = Array.isArray(this.allPoisDetails) ? this.allPoisDetails.length : 0
      const h3Summary = this.h3AnalysisSummary || {}
      const h3Count = Number(h3Summary.grid_count || this.h3GridCount || 0) || 0
      const nightlightAnalysis = buildCurrentNightlightAnalysis(this)
      const featureProps = cloneObject(siteSelectionScope.isochroneFeature && siteSelectionScope.isochroneFeature.properties)
      const selectedCenter = normalizePptLngLat(this.selectedPoint)
      const featureCenter = normalizePptLngLat(featureProps.center || featureProps.center_gcj02 || featureProps.centerGcj02)
      const scopeCenter = selectedCenter.length ? selectedCenter : featureCenter
      const timeMin = Number(this.timeHorizon || featureProps.time_min || featureProps.timeMin || 0) || 0
      const radiusM = resolvePptPlanningRadiusMeters(this, featureProps)
      const scope = {
        polygon: cloneArray(siteSelectionScope.polygon),
        drawn_polygon: cloneArray(siteSelectionScope.drawnPolygon),
        isochrone_feature: siteSelectionScope.isochroneFeature || null,
        center: scopeCenter,
        center_coord_type: scopeCenter.length ? 'gcj02' : '',
        radius_m: radiusM,
        time_min: timeMin,
        mode: asText(this.transportMode),
      }
      const metrics = buildPptAnalysisMetrics(this, scope, taskResults)
      const status = {
        scope: hasRing(scope.polygon) || hasRing(scope.drawn_polygon) || !!scope.isochrone_feature ? 'ready' : 'not_ready',
        poi: taskResults.poi_fetch ? 'ready' : 'not_ready',
        h3: taskResults.poi_h3_grid ? 'ready' : 'not_ready',
        poi_h3: taskResults.poi_h3_grid ? 'ready' : 'not_ready',
        population: taskResults.population ? 'ready' : 'not_ready',
        nightlight: taskResults.nightlight ? 'ready' : 'not_ready',
        road: taskResults.road_syntax ? 'ready' : 'not_ready',
      }
      const metricSummaryForSource = (sourceId) => {
        const bound = cloneArray(metrics.metrics).filter((metric) => cloneArray(metric.source_ids || metric.sourceIds).includes(sourceId))
        const readyCount = bound.filter((metric) => asText(metric.status) === 'ready').length
        const gapCount = bound.filter((metric) => asText(metric.status) !== 'ready').length
        if (readyCount || gapCount) return `ready ${readyCount} 项 / 缺口 ${gapCount} 项`
        return ''
      }
      return {
        scope,
        datasets: {
          poi: { items: cloneArray(this.allPoisDetails), count: poiTotal },
          h3: { features: cloneArray(this.h3AnalysisGridFeatures), count: h3Count },
          population: cloneObject(this.populationOverview || {}),
          nightlight: nightlightAnalysis,
          road: cloneObject(this.roadSyntaxSummary || {}),
        },
        analysis: {
          poi_h3: {
            summary: cloneObject(this.h3AnalysisSummary || {}),
            features: cloneArray(this.h3AnalysisGridFeatures),
          },
          population: cloneObject(this.populationOverview || {}),
          nightlight: nightlightAnalysis,
          road: cloneObject(this.roadSyntaxSummary || {}),
        },
        metrics,
        visual_assets: {},
        status,
        panelPayloads,
        summaryPack: cloneObject(panelPayloads.summary_pack || panelPayloads.summaryPack),
        summaryReady,
        taskResults,
        sourceDetails: {
          'current:scope': this.timeHorizon ? `${Number(this.timeHorizon)} 分钟范围` : '',
          center: scopeCenter.length ? `${scopeCenter[0].toFixed(4)}, ${scopeCenter[1].toFixed(4)}` : '',
          summary: summaryReady ? '已生成' : '',
          'current:dataset:poi': poiTotal ? `POI ${poiTotal} 条` : '',
          'current:dataset:h3': h3Count ? `H3 ${h3Count} 个网格` : '',
          'current:analysis:poi_h3': metricSummaryForSource('current:analysis:poi_h3'),
          'current:analysis:population': metricSummaryForSource('current:analysis:population'),
          'current:analysis:nightlight': metricSummaryForSource('current:analysis:nightlight'),
          'current:analysis:road': metricSummaryForSource('current:analysis:road'),
        },
      }
    },
    buildAgentPptPlanningSystemSourceContext() {
      return this.buildAgentPptPlanningCurrent()
    },
    mergeAgentPptPlanningSystemSources(state = {}) {
      const normalizedState = createPptPlanningState(state)
      const context = this.buildAgentPptPlanningApiContext()
      const areaId = asText(context.areaId || context.area_id)
      const previousById = new Map(cloneArray(normalizedState.sources).map((item) => [asText(item.id), item]))
      const systemSources = createPptSystemSources(this.buildAgentPptPlanningSystemSourceContext()).map((source) => {
        const previous = previousById.get(asText(source.id))
        if (
          previous
          && isReadySource(previous)
          && asText(previous.meta && previous.meta.sourceKind) === 'system'
          && areaId
          && asText(previous.meta && previous.meta.areaId) === areaId
        ) {
          const previousMeta = cloneObject(previous.meta)
          const sourceMeta = cloneObject(source.meta)
          const preservePreviousPayload = asText(source.status) !== 'ready'
          return {
            ...source,
            title: asText(previous.title) || source.title,
            status: asText(source.status) === 'ready' ? source.status : previous.status,
            selected: !!previous.selected,
            meta: {
              ...(preservePreviousPayload ? sourceMeta : previousMeta),
              ...(preservePreviousPayload ? previousMeta : sourceMeta),
              aiPayload: preservePreviousPayload ? previousMeta.aiPayload : sourceMeta.aiPayload,
              ai_payload: preservePreviousPayload ? previousMeta.ai_payload : sourceMeta.ai_payload,
              transport: preservePreviousPayload ? previousMeta.transport : sourceMeta.transport,
              areaId,
            },
          }
        }
        return source
      })
      return this.getAgentPptPlanningStateWithPackagePlaceholders(mergePptPlanningSources(normalizedState, systemSources), areaId)
    },
    getAgentPptPlanningStateWithSystemSources() {
      return this.mergeAgentPptPlanningSystemSources(this.getAgentActivePptPlanningState())
    },
    getAgentPptPlanningTabStateWithSystemSources(tabId = '') {
      return this.mergeAgentPptPlanningSystemSources(this.getAgentPptPlanningTabState(tabId))
    },
    getAgentPptPlanningStateWithPackagePlaceholders(state = {}, areaId = '') {
      const normalized = createPptPlanningState(state)
      const normalizedAreaId = asText(areaId || (this.buildAgentPptPlanningApiContext && this.buildAgentPptPlanningApiContext().areaId))
      const activeKeys = this.agentPptPlanningAutoPackageKeys || {}
      const packageErrors = this.agentPptPlanningPackageErrors || {}
      const readySourceIds = new Set(cloneArray(normalized.sources)
        .filter((source) => isReadySource(source))
        .map((source) => asText(source.id))
        .filter(Boolean))
      const placeholders = PPT_AUTO_PACKAGE_DEFINITIONS
        .filter((definition) => !hasPptEvidencePackage(normalized, normalizedAreaId, definition))
        .map((definition) => {
          const packageKey = getPptEvidencePackageKey(normalizedAreaId, definition)
          const generating = !!(packageKey && activeKeys[packageKey])
          const errorMessage = asText(packageKey && packageErrors[packageKey])
          const missingSourceIds = cloneArray(definition.sourceIds).filter((sourceId) => !readySourceIds.has(asText(sourceId)))
          return {
            id: `package-placeholder:${definition.key}`,
            type: 'package',
            title: definition.title,
            status: generating ? 'generating' : errorMessage ? 'failed' : 'pending',
            selected: false,
            meta: {
              label: generating ? '整理中' : errorMessage ? '生成失败' : missingSourceIds.length ? `缺少 ${missingSourceIds.length} 个依赖` : '点击生成',
              sourceKind: 'package-placeholder',
              packagePlaceholder: true,
              error: errorMessage,
              message: errorMessage,
              missingSourceIds,
              areaId: normalizedAreaId,
              packageVersion: asText(definition.packageVersion),
              package: {
                package_mode: definition.packageMode,
                intent: definition.intent,
                source_ids: cloneArray(definition.sourceIds),
              },
            },
          }
        })
      return syncPptPackagePlaceholderSources(normalized, placeholders)
    },
    refreshAgentActivePptPlanningSources() {
      const tabs = this.ensureAgentTabs(true)
      const activeTab = this.getAgentActiveTopTab()
      if (asText(activeTab.kind) !== 'ppt_planning') return
      const nextPptPlanningTabs = cloneArray(tabs.pptPlanningTabs).map((item) => {
        if (item.id !== activeTab.id || item.readonly) return item
        return {
          ...item,
          pptPlanningState: this.getAgentPptPlanningStateWithSystemSources(),
        }
      })
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), iterationChangeTabs: cloneArray(tabs.iterationChangeTabs), siteSelectionTabs: cloneArray(tabs.siteSelectionTabs), pptPlanningTabs: nextPptPlanningTabs, deepAnalysisTabs: cloneArray(tabs.deepAnalysisTabs), followupTabs: cloneArray(tabs.followupTabs) }
      this.syncCurrentAgentSession()
    },
    async refreshAgentActivePptPlanningDataSources(options = {}) {
      const context = this.buildAgentPptPlanningApiContext()
      const areaId = asText(context.areaId || context.area_id)
      const activeTab = this.getAgentActiveTopTab()
      const activeTabId = asText(activeTab && activeTab.id)
      if (!areaId || asText(activeTab && activeTab.kind) !== 'ppt_planning') return
      const initialState = this.getAgentPptPlanningStateWithPackagePlaceholders(
        this.getAgentPptPlanningStateWithSystemSources(),
        areaId,
      )
      this.updateAgentPptPlanningTabRuntimeState(activeTabId, setPptSourceRefreshing(initialState, true))
      try {
        const backendSources = await this.requestAgentPptPlanningDataSources(areaId)
        const tabs = this.ensureAgentTabs(true)
        if (asText(tabs.activeTabId) !== activeTabId) return
        const nextSources = cloneArray(backendSources).map((source) => normalizeBackendPptDataSource(source, areaId))
        const currentState = this.getAgentActivePptPlanningState()
        const refreshedState = this.getAgentPptPlanningStateWithPackagePlaceholders(
          mergePptPlanningSources(currentState, nextSources),
          areaId,
        )
        this.updateAgentActivePptPlanningStateWithSourceStale(setPptSourceRefreshing(refreshedState, false), currentState)
        if (options.autoPackage !== false) {
          await Promise.allSettled([
            this.autoCreateAgentPptPlanningPoiEvidencePackage({ areaId }),
            this.autoCreateAgentPptPlanningNightlifePoiPackage({ areaId }),
            this.autoCreateAgentPptPlanningRoadCarrierPackage({ areaId }),
          ])
        }
      } catch (error) {
        this.updateAgentActivePptPlanningState(setPptSourceRefreshing(
          setPptGenerationError(this.getAgentPptPlanningStateWithSystemSources(), error && error.message, 'source_refresh'),
          false,
        ))
      }
    },
    getAgentPptPlanningSources() {
      return cloneArray(this.getAgentPptPlanningStateWithSystemSources().sources)
    },
    getAgentPptPlanningSourceGroups() {
      return cloneArray(this.getAgentPptPlanningStateWithSystemSources().sourceGroups)
    },
    getAgentPptPlanningSpec() {
      return cloneObject(this.getAgentPptPlanningStateWithSystemSources().spec)
    },
    getAgentPptPlanningCurrentStep() {
      return asText(this.getAgentPptPlanningStateWithSystemSources().currentStep)
    },
    getAgentPptPlanningOutline() {
      return cloneArray(this.getAgentPptPlanningStateWithSystemSources().outline)
    },
    getAgentPptPlanningNarrativePlan() {
      return cloneObject(this.getAgentActivePptPlanningState().narrativePlan)
    },
    getAgentPptPlanningSlideGenerationQueue() {
      return cloneArray(this.getAgentActivePptPlanningState().slideGenerationQueue)
    },
    getAgentPptPlanningSlideGenerationJob() {
      return cloneObject(this.getAgentActivePptPlanningState().slideGenerationJob)
    },
    getAgentPptPlanningVisualGenerationBySlide() {
      return cloneObject(this.getAgentActivePptPlanningState().visualGenerationBySlide)
    },
    getAgentPptPlanningSlides() {
      return cloneArray((this.getAgentActivePptPlanningState().deckBrief || {}).slides)
    },
    getAgentPptPlanningGenerationError() {
      return asText(this.getAgentActivePptPlanningState().generationError)
    },
    getAgentPptPlanningGenerationErrorSource() {
      return asText(this.getAgentActivePptPlanningState().generationErrorSource)
    },
    getAgentPptPlanningGenerationResponse() {
      return cloneObject(this.getAgentActivePptPlanningState().generationResponse)
    },
    getAgentPptPlanningGenerationJob() {
      return cloneObject(this.getAgentActivePptPlanningState().generationJob)
    },
    isAgentPptPlanningSourceRefreshing() {
      return !!this.getAgentActivePptPlanningState().sourceRefreshing
    },
    getAgentPptPlanningActiveRevisionTarget() {
      return cloneObject(this.getAgentActivePptPlanningState().activeRevisionTarget)
    },
    getAgentPptPlanningOutlineRevisionDraft() {
      return cloneObject(this.getAgentActivePptPlanningState().outlineRevisionDraft)
    },
    getAgentPptPlanningDirectiveRevisionDraft() {
      return cloneObject(this.getAgentActivePptPlanningState().directiveRevisionDraft)
    },
    getAgentPptPlanningRevisionSnapshots() {
      return cloneObject(this.getAgentActivePptPlanningState().revisionSnapshots)
    },
    getAgentPptPlanningStaleDirectivePageIds() {
      return cloneArray(this.getAgentActivePptPlanningState().staleDirectivePageIds)
    },
    getAgentPptPlanningRevisionGeneratingTarget() {
      return cloneObject(this.getAgentActivePptPlanningState().revisionGeneratingTarget)
    },
    isAgentPptPlanningDataPackageGenerating() {
      return !!this.getAgentActivePptPlanningState().dataPackageGenerating
    },
    isAgentPptPlanningSourceGrouping() {
      return !!this.getAgentActivePptPlanningState().sourceGrouping
    },
    getAgentPptPlanningSourceSummary() {
      return getPptSourceSummary(this.getAgentPptPlanningStateWithSystemSources())
    },
    getAgentPptPlanningActiveSlide() {
      return getActiveDeckSlideBrief(this.getAgentActivePptPlanningState()) || {}
    },
    isAgentPptPlanningSlideActive(slideId = '') {
      return asText(this.getAgentActivePptPlanningState().selectedSlideId) === asText(slideId)
    },
    updateAgentActivePptPlanningState(nextState = {}) {
      const tabs = this.ensureAgentTabs(true)
      const activeTab = this.getAgentActiveTopTab()
      if (asText(activeTab.kind) !== 'ppt_planning') return
      this.updateAgentPptPlanningTabState(activeTab.id, nextState)
    },
    patchAgentPptPlanningTabState(tabId = '', nextState = {}, options = {}) {
      const targetId = asText(tabId)
      if (!targetId) return false
      const tabs = this.ensureAgentTabs(true)
      const tabIds = cloneArray(tabs.pptPlanningTabs).map((item) => asText(item && item.id)).filter(Boolean)
      const targetTab = cloneArray(tabs.pptPlanningTabs).find((item) => asText(item && item.id) === targetId) || null
      const normalizedNextState = createPptPlanningState(nextState)
      const shouldSync = options.sync !== false
      const includeUpdateDebug = options.debug !== false
      const updateDetails = {
        targetId,
        tabIds,
        matched: !!targetTab,
        readonly: !!(targetTab && targetTab.readonly),
        before: pptGenerationJobDebug(targetTab && targetTab.pptPlanningState && targetTab.pptPlanningState.generationJob),
        next: pptGenerationJobDebug(normalizedNextState.generationJob),
      }
      const fallbackActiveId = asText(tabs.activeTabId)
      const writeDebugToTab = (eventName = '', details = {}) => {
        const debugTargetId = targetTab ? targetId : fallbackActiveId
        if (!debugTargetId) return
        const debugTabs = this.ensureAgentTabs(true)
        let debugChanged = false
        const nextTabs = cloneArray(debugTabs.pptPlanningTabs).map((item) => {
          if (asText(item.id) !== debugTargetId) return item
          debugChanged = true
          return {
            ...item,
            pptPlanningState: appendPptDebugEventToState(item.pptPlanningState, eventName, details),
          }
        })
        if (debugChanged) {
          this.agentTabs = { ...debugTabs, summaryTabs: cloneArray(debugTabs.summaryTabs), iterationChangeTabs: cloneArray(debugTabs.iterationChangeTabs), siteSelectionTabs: cloneArray(debugTabs.siteSelectionTabs), pptPlanningTabs: nextTabs, deepAnalysisTabs: cloneArray(debugTabs.deepAnalysisTabs), followupTabs: cloneArray(debugTabs.followupTabs) }
        }
      }
      if (includeUpdateDebug) writeDebugToTab('tab_update_attempt', updateDetails)
      if (!targetTab) {
        if (includeUpdateDebug) writeDebugToTab('tab_update_noop_missing_tab', updateDetails)
        return false
      }
      if (targetTab.readonly) {
        if (includeUpdateDebug) writeDebugToTab('tab_update_noop_readonly', updateDetails)
        return false
      }
      let changed = false
      const refreshedTabs = this.ensureAgentTabs(true)
      const nextPptPlanningTabs = cloneArray(refreshedTabs.pptPlanningTabs).map((item) => {
        if (asText(item.id) !== targetId || item.readonly) return item
        changed = true
        const stateWithAttempt = includeUpdateDebug
          ? appendPptDebugEventToState(normalizedNextState, 'tab_update_attempt', updateDetails)
          : normalizedNextState
        return {
          ...item,
          pptPlanningState: includeUpdateDebug
            ? appendPptDebugEventToState(stateWithAttempt, 'tab_update_applied', updateDetails)
            : stateWithAttempt,
        }
      })
      if (!changed) return false
      this.agentTabs = { ...refreshedTabs, summaryTabs: cloneArray(refreshedTabs.summaryTabs), iterationChangeTabs: cloneArray(refreshedTabs.iterationChangeTabs), siteSelectionTabs: cloneArray(refreshedTabs.siteSelectionTabs), pptPlanningTabs: nextPptPlanningTabs, deepAnalysisTabs: cloneArray(refreshedTabs.deepAnalysisTabs), followupTabs: cloneArray(refreshedTabs.followupTabs) }
      if (shouldSync) {
        this.syncCurrentAgentSession()
        if (includeUpdateDebug) {
          const afterSync = this.getAgentPptPlanningTabState(targetId)
          writeDebugToTab('tab_update_after_sync', {
            ...updateDetails,
            afterSync: pptGenerationJobDebug(afterSync.generationJob),
          })
        }
      }
      return true
    },
    updateAgentPptPlanningTabRuntimeState(tabId = '', nextState = {}) {
      return this.patchAgentPptPlanningTabState(tabId, nextState, { sync: false, debug: false })
    },
    updateAgentPptPlanningTabState(tabId = '', nextState = {}) {
      return this.patchAgentPptPlanningTabState(tabId, nextState, { sync: true, debug: true })
    },
    cleanupAgentPptPlanningVisualArtifacts(filenames = []) {
      const uniqueFilenames = uniquePptText(filenames)
      if (!uniqueFilenames.length) return Promise.resolve(null)
      const request = typeof this.requestAgentPptPlanningVisualArtifactCleanup === 'function'
        ? this.requestAgentPptPlanningVisualArtifactCleanup(uniqueFilenames)
        : cleanupPptVisualArtifacts(uniqueFilenames)
      return Promise.resolve(request).catch((error) => {
        if (typeof console !== 'undefined' && console.warn) {
          console.warn('PPT visual artifact cleanup failed', error)
        }
        return null
      })
    },
    updateAgentActivePptPlanningStateWithSourceStale(nextState = {}, previousState = null, explicitSourceIds = []) {
      const previous = previousState ? createPptPlanningState(previousState) : this.getAgentActivePptPlanningState()
      const changedSourceIds = uniquePptText([...cloneArray(explicitSourceIds), ...changedReadySourceIds(previous, nextState)])
      const staleState = markPptDirectiveStaleForSources(nextState, changedSourceIds)
      this.updateAgentActivePptPlanningState(staleState)
    },
    toggleAgentPptPlanningSource(sourceId = '') {
      const state = this.getAgentPptPlanningStateWithSystemSources()
      this.updateAgentActivePptPlanningStateWithSourceStale(togglePptSourceSelection(state, sourceId), state, [sourceId])
    },
    toggleAgentPptPlanningSourceGroupCollapsed(groupId = '') {
      this.updateAgentActivePptPlanningState(togglePptSourceGroupCollapsed(this.getAgentPptPlanningStateWithSystemSources(), groupId))
    },
    setAgentPptPlanningSourceGroupSelected(groupId = '', selected = true) {
      const state = this.getAgentPptPlanningStateWithSystemSources()
      this.updateAgentActivePptPlanningStateWithSourceStale(setPptSourceGroupSelected(state, groupId, selected), state)
    },
    moveAgentPptPlanningSourceToGroup(sourceId = '', groupId = '') {
      this.updateAgentActivePptPlanningState(movePptSourceToGroup(this.getAgentPptPlanningStateWithSystemSources(), sourceId, groupId))
    },
    renameAgentPptPlanningSource(sourceId = '', title = '') {
      this.updateAgentActivePptPlanningState(renamePptSource(this.getAgentPptPlanningStateWithSystemSources(), sourceId, title))
    },
    async removeAgentPptPlanningSource(sourceId = '') {
      const state = this.getAgentPptPlanningStateWithSystemSources()
      const id = asText(sourceId)
      const source = cloneArray(state.sources).find((item) => asText(item && item.id) === id)
      try {
        if (isPptDocumentSource(source)) {
          const documentId = documentIdFromPptSource(source)
          if (documentId) await this.requestAgentPptPlanningDocumentDelete(documentId)
        }
        this.updateAgentActivePptPlanningStateWithSourceStale(removePptSource(state, id), state, [id])
      } catch (error) {
        this.updateAgentActivePptPlanningState(setPptGenerationError(state, error && error.message, 'source_refresh'))
      }
    },
    renameAgentPptPlanningSourceGroup(groupId = '', title = '') {
      this.updateAgentActivePptPlanningState(renamePptSourceGroup(this.getAgentPptPlanningStateWithSystemSources(), groupId, title))
    },
    setAgentPptPlanningSourceGroupEmoji(groupId = '', emoji = '') {
      this.updateAgentActivePptPlanningState(setPptSourceGroupEmoji(this.getAgentPptPlanningStateWithSystemSources(), groupId, emoji))
    },
    removeAgentPptPlanningSourceGroup(groupId = '') {
      this.updateAgentActivePptPlanningState(removePptSourceGroup(this.getAgentPptPlanningStateWithSystemSources(), groupId))
    },
    toggleAllAgentPptPlanningSources() {
      const summary = this.getAgentPptPlanningSourceSummary()
      const state = this.getAgentPptPlanningStateWithSystemSources()
      this.updateAgentActivePptPlanningStateWithSourceStale(setAllPptSourcesSelected(state, summary.selected < summary.ready), state)
    },
    updateAgentPptPlanningSpecField(field = '', value = '') {
      this.updateAgentActivePptPlanningState(setPptSpecField(this.getAgentPptPlanningStateWithSystemSources(), field, value))
    },
    openAgentPptPlanningRevisionTarget(type = '', target = {}) {
      this.updateAgentActivePptPlanningState(setPptActiveRevisionTarget(this.getAgentPptPlanningStateWithSystemSources(), { ...target, type }))
    },
    closeAgentPptPlanningRevisionTarget() {
      this.updateAgentActivePptPlanningState(setPptActiveRevisionTarget(this.getAgentActivePptPlanningState(), {}))
    },
    updateAgentPptPlanningRevisionDraft(type = '', field = '', value = '') {
      this.updateAgentActivePptPlanningState(setPptRevisionDraftField(this.getAgentActivePptPlanningState(), type, field, value))
    },
    saveAgentPptPlanningRevision(type = '') {
      const state = this.getAgentActivePptPlanningState()
      const target = cloneObject(state.activeRevisionTarget)
      if (asText(type) === 'directive') {
        const draft = cloneObject(state.directiveRevisionDraft)
        const requiredSources = asText(draft.requiredSources)
          .split(/[,，\n]/)
          .map((item) => asText(item))
          .filter(Boolean)
        this.updateAgentActivePptPlanningState(applyDeckBriefSlideRevision(state, {
          index: Number(target.index || target.pageNo || 0) || 0,
          title: asText(draft.title),
          purpose: asText(draft.purpose),
          keyMessage: asText(draft.keyMessage),
          visualPlan: asText(draft.visualPlan),
          requiredSources,
        }))
        return
      }
      const draft = cloneObject(state.outlineRevisionDraft)
      this.updateAgentActivePptPlanningState(applyPptOutlineSectionRevision(state, {
        id: asText(target.id),
        pageNo: Number(target.pageNo || 0) || 0,
        theme: asText(draft.theme),
        purpose: asText(draft.purpose),
      }))
    },
    async regenerateAgentPptPlanningRevision(type = '') {
      const state = this.getAgentPptPlanningStateWithSystemSources()
      const target = cloneObject(state.activeRevisionTarget)
      const normalizedType = asText(type)
      const draft = normalizedType === 'directive' ? cloneObject(state.directiveRevisionDraft) : cloneObject(state.outlineRevisionDraft)
      const revisionNote = asText(draft.revisionNote)
      if (!target.type || !revisionNote) return
      this.updateAgentActivePptPlanningState(setPptRevisionGeneratingTarget(state, target))
      try {
        if (normalizedType === 'directive') {
          const context = await this.buildAgentPptPlanningVisualApiContext()
          const staleFilenames = collectPptVisualArtifactFilenames(state.deckBrief.slides
            .filter((slide) => Number(slide.index || 0) === Number(target.index || target.pageNo || 0)))
          const response = await this.requestAgentPptPlanningDirectiveSlide(buildDeckBriefSlidePayload(state, target, revisionNote, context))
          this.updateAgentActivePptPlanningState(applyDeckBriefSlideRevision(this.getAgentActivePptPlanningState(), response))
          this.cleanupAgentPptPlanningVisualArtifacts(staleFilenames)
          return
        }
        const context = this.buildAgentPptPlanningApiContext()
        const response = await this.requestAgentPptPlanningOutlineSection(buildPptOutlineSectionPayload(state, target, revisionNote, context))
        this.updateAgentActivePptPlanningState(applyPptOutlineSectionRevision(this.getAgentActivePptPlanningState(), response))
      } catch (error) {
        const errorSource = normalizedType === 'directive' ? 'directive' : 'outline'
        this.updateAgentActivePptPlanningState(setPptGenerationError(
          this.getAgentActivePptPlanningState(),
          normalizePptGenerationErrorMessage(error, errorSource),
          errorSource,
        ))
      }
    },
    undoAgentPptPlanningRevision(type = '', target = {}) {
      this.updateAgentActivePptPlanningState(undoPptSectionRevision(this.getAgentActivePptPlanningState(), type, target))
    },
    hasAgentPptPlanningRevisionSnapshot(type = '', target = {}) {
      const state = this.getAgentActivePptPlanningState()
      const key = getPptRevisionKey(type, target)
      return !!(key && state.revisionSnapshots && state.revisionSnapshots[key])
    },
    isAgentPptPlanningDirectivePageStale(pageNo = 0) {
      return isPptDirectivePageStale(this.getAgentActivePptPlanningState(), pageNo)
    },
    buildAgentPptPlanningApiContext() {
      return {
        areaId: asText(
          (typeof this.getCurrentAgentHistoryId === 'function' && this.getCurrentAgentHistoryId())
          || this.currentHistoryRecordId
          || this.currentAnalysisId
          || this.analysisId
          || this.activeAgentSessionId,
        ),
        current: this.buildAgentPptPlanningCurrent(),
      }
    },
    async buildAgentPptPlanningVisualApiContext() {
      const context = this.buildAgentPptPlanningApiContext()
      let visualSnapshots = []
      if (typeof this.ensureAgentVisualSnapshotCache === 'function') {
        try {
          visualSnapshots = await this.ensureAgentVisualSnapshotCache()
        } catch (error) {
          if (typeof console !== 'undefined' && console.warn) {
            console.warn('PPT visual snapshots failed; continuing without existing assets', error)
          }
        }
      }
      return {
        ...context,
        current: {
          ...cloneObject(context.current),
          visual_snapshots: cloneArray(visualSnapshots),
        },
      }
    },
    requestAgentPptPlanningOutline(payload = {}) {
      return generatePptSpec(payload)
    },
    requestAgentPptPlanningOutlineWithDebug(payload = {}, options = {}) {
      return generatePptSpecWithDebug(payload, options)
    },
    requestAgentPptPlanningOutlineSection(payload = {}) {
      return regeneratePptSpecSection(payload)
    },
    requestAgentPptPlanningDirective(payload = {}) {
      return generateDeckBrief(payload)
    },
    requestAgentPptPlanningDirectiveWithDebug(payload = {}, options = {}) {
      return generateDeckBriefWithDebug(payload, options)
    },
    requestAgentPptPlanningNarrativePlan(payload = {}) {
      return generateNarrativePlan(payload)
    },
    requestAgentPptPlanningNarrativePlanWithDebug(payload = {}, options = {}) {
      return generateNarrativePlanWithDebug(payload, options)
    },
    requestAgentPptPlanningDirectiveSlide(payload = {}) {
      return regenerateDeckBriefSlide(payload)
    },
    requestAgentPptPlanningVisualArtifacts(payload = {}) {
      return generatePptVisualArtifacts(payload)
    },
    requestAgentPptPlanningDataSources(areaId = '') {
      return listPptDataSources(areaId)
    },
    requestAgentPptPlanningDataPackage(payload = {}) {
      return createPptDataPackage(payload)
    },
    requestAgentPptPlanningDocumentDelete(documentId = '') {
      return deleteDocumentSource(documentId)
    },
    requestAgentPptSourceGroupClassification(payload = {}) {
      return classifyPptSourceGroups(payload)
    },
    async uploadAgentPptPlanningDocumentSource(file) {
      if (!file) return
      let document = null
      try {
        document = await uploadDocumentSource(file, file.name || '')
        const documentId = asText(document && document.id)
        if (documentId) {
          this.updateAgentActivePptPlanningState(upsertPptDocumentSource(
            this.getAgentPptPlanningStateWithSystemSources(),
            document,
            { status: 'generating', label: '整理中' },
          ))
        }
        if (documentId) {
          const parseJob = await scheduleDocumentParse(documentId)
          await waitForPptPlanningJob(parseJob && parseJob.job_id)
          this.updateAgentActivePptPlanningState(upsertPptDocumentSource(
            this.getAgentPptPlanningStateWithSystemSources(),
            document,
            {
              status: 'ready',
              label: 'PageIndex 已生成',
            },
          ))
        }
        await this.refreshAgentActivePptPlanningDataSources({ autoPackage: false })
      } catch (error) {
        const documentId = asText(document && document.id)
        if (documentId) {
          this.updateAgentActivePptPlanningState(upsertPptDocumentSource(
            this.getAgentPptPlanningStateWithSystemSources(),
            document,
            { status: 'failed', label: '整理失败' },
          ))
        }
        this.updateAgentActivePptPlanningState(setPptGenerationError(this.getAgentPptPlanningStateWithSystemSources(), error && error.message, 'source_refresh'))
      }
    },
    async classifyAgentPptPlanningSourceGroups() {
      const state = this.getAgentPptPlanningStateWithSystemSources()
      if (!cloneArray(state.sources).length || state.sourceGrouping) return
      this.updateAgentActivePptPlanningState(setPptSourceGrouping(state, true))
      try {
        const context = this.buildAgentPptPlanningApiContext()
        const response = await this.requestAgentPptSourceGroupClassification({
          area_id: asText(context.areaId || context.area_id),
          sources: cloneArray(state.sources),
          current: cloneObject(context.current),
          previous_groups: cloneArray(state.sourceGroups).map((group) => ({
            id: group.id,
            title: group.title,
            emoji: group.emoji,
            source_ids: cloneArray(group.sourceIds),
            collapsed: !!group.collapsed,
            meta: cloneObject(group.meta),
          })),
        })
        this.updateAgentActivePptPlanningState(applyPptSourceGroupsResponse(this.getAgentPptPlanningStateWithSystemSources(), response))
      } catch (error) {
        this.updateAgentActivePptPlanningState(setPptGenerationError(this.getAgentPptPlanningStateWithSystemSources(), error && error.message, 'source_grouping'))
      }
    },
    async autoCreateAgentPptPlanningEvidencePackage(options = {}) {
      const context = this.buildAgentPptPlanningApiContext ? this.buildAgentPptPlanningApiContext() : {}
      const areaId = asText(options.areaId || context.areaId || context.area_id)
      const sourceIds = cloneArray(options.sourceIds).map((item) => asText(item)).filter(Boolean)
      const intent = asText(options.intent)
      const packageMode = asText(options.packageMode) || 'evidence'
      const packageVersion = asText(options.packageVersion)
      const state = this.getAgentPptPlanningStateWithSystemSources()
      const sourcesById = new Map(cloneArray(state.sources).map((item) => [asText(item.id), item]))
      const packageOptions = { sourceIds, packageMode, intent, packageVersion }
      const packageKey = getPptEvidencePackageKey(areaId, packageOptions)
      if (
        !areaId
        || !sourceIds.length
        || !intent
        || sourceIds.some((sourceId) => !isReadySource(sourcesById.get(sourceId)))
        || hasPptEvidencePackage(state, areaId, packageOptions)
      ) return
      const activePackageKeys = this.agentPptPlanningAutoPackageKeys || {}
      const packageErrors = this.agentPptPlanningPackageErrors || {}
      this.agentPptPlanningAutoPackageKeys = activePackageKeys
      this.agentPptPlanningPackageErrors = packageErrors
      if (packageKey && activePackageKeys[packageKey]) return
      if (packageKey) delete packageErrors[packageKey]
      if (packageKey) activePackageKeys[packageKey] = true
      this.updateAgentActivePptPlanningState(this.getAgentPptPlanningStateWithPackagePlaceholders(
        state,
        areaId,
      ))
      try {
        const spatialPayload = buildPptDataPackageSpatialPayload(context.current)
        const response = await this.requestAgentPptPlanningDataPackage({
          area_id: areaId,
          source_ids: sourceIds,
          package_mode: packageMode,
          package_version: packageVersion,
          intent,
          query: '',
          limit: Number(options.limit || 50) || 50,
          ...spatialPayload,
        })
        this.updateAgentActivePptPlanningState(addPptDataPackageSource(
          this.getAgentActivePptPlanningState(),
          attachPptDataPackageRuntimeMeta(response, areaId, { autoGenerated: true, packageVersion }),
        ))
        if (packageKey) delete packageErrors[packageKey]
        this.agentPptPlanningPackageErrors = packageErrors
      } catch (error) {
        const message = asText(error && error.message) || 'data_package_failed'
        if (packageKey) packageErrors[packageKey] = message
        this.agentPptPlanningPackageErrors = packageErrors
        this.updateAgentActivePptPlanningState(this.getAgentPptPlanningStateWithPackagePlaceholders(
          this.getAgentPptPlanningStateWithSystemSources(),
          areaId,
        ))
      } finally {
        if (packageKey) delete activePackageKeys[packageKey]
        this.updateAgentActivePptPlanningState(this.getAgentPptPlanningStateWithPackagePlaceholders(
          this.getAgentActivePptPlanningState(),
          areaId,
        ))
      }
    },
    async autoCreateAgentPptPlanningPoiEvidencePackage(options = {}) {
      const areaId = asText(options.areaId || (this.buildAgentPptPlanningApiContext && this.buildAgentPptPlanningApiContext().areaId))
      const definition = getPptAutoPackageDefinition('poi-evidence')
      return this.autoCreateAgentPptPlanningEvidencePackage({
        areaId,
        sourceIds: definition.sourceIds,
        packageMode: definition.packageMode,
        intent: definition.intent,
        packageVersion: definition.packageVersion,
        limit: definition.limit,
      })
    },
    async autoCreateAgentPptPlanningNightlifePoiPackage(options = {}) {
      const areaId = asText(options.areaId || (this.buildAgentPptPlanningApiContext && this.buildAgentPptPlanningApiContext().areaId))
      const definition = getPptAutoPackageDefinition('nightlife-poi')
      return this.autoCreateAgentPptPlanningEvidencePackage({
        areaId,
        sourceIds: definition.sourceIds,
        packageMode: definition.packageMode,
        intent: definition.intent,
        packageVersion: definition.packageVersion,
        limit: definition.limit,
      })
    },
    async autoCreateAgentPptPlanningRoadCarrierPackage(options = {}) {
      const areaId = asText(options.areaId || (this.buildAgentPptPlanningApiContext && this.buildAgentPptPlanningApiContext().areaId))
      const definition = getPptAutoPackageDefinition('road-carrier')
      return this.autoCreateAgentPptPlanningEvidencePackage({
        areaId,
        sourceIds: definition.sourceIds,
        packageMode: definition.packageMode,
        intent: definition.intent,
        packageVersion: definition.packageVersion,
        limit: definition.limit,
      })
    },
    async generateAgentPptPlanningPackageSource(sourceId = '') {
      const key = asText(sourceId).replace(/^package-placeholder:/, '')
      const definition = getPptAutoPackageDefinition(key)
      if (!definition) return
      const context = this.buildAgentPptPlanningApiContext ? this.buildAgentPptPlanningApiContext() : {}
      const areaId = asText(context.areaId || context.area_id)
      await this.autoCreateAgentPptPlanningEvidencePackage({
        areaId,
        sourceIds: definition.sourceIds,
        packageMode: definition.packageMode,
        intent: definition.intent,
        packageVersion: definition.packageVersion,
        limit: definition.limit,
      })
    },
    async createAgentPptPlanningDataPackage() {
      const state = this.getAgentPptPlanningStateWithSystemSources()
      const selectedSourceIds = cloneArray(state.sources)
        .filter((item) => item && item.selected && asText(item.status) === 'ready')
        .map((item) => asText(item.id))
        .filter(Boolean)
      if (!selectedSourceIds.length || state.dataPackageGenerating) return
      this.updateAgentActivePptPlanningState(setPptDataPackageGenerating(state, true))
      try {
        const context = this.buildAgentPptPlanningApiContext()
        const spatialPayload = buildPptDataPackageSpatialPayload(context.current)
        const response = await this.requestAgentPptPlanningDataPackage({
          area_id: asText(context.areaId || context.area_id),
          source_ids: selectedSourceIds,
          package_mode: 'evidence',
          intent: DEFAULT_PPT_POI_EVIDENCE_INTENT,
          query: '',
          limit: 50,
          ...spatialPayload,
        })
        this.updateAgentActivePptPlanningState(addPptDataPackageSource(
          this.getAgentPptPlanningStateWithSystemSources(),
          attachPptDataPackageRuntimeMeta(response, asText(context.areaId || context.area_id)),
        ))
      } catch (error) {
        this.updateAgentActivePptPlanningState(setPptGenerationError(this.getAgentPptPlanningStateWithSystemSources(), error && error.message, 'data_package'))
      }
    },
    async generateAgentPptPlanningOutline() {
      const activeTab = this.getAgentActivePptPlanningTab()
      const tabId = asText(activeTab && activeTab.id)
      if (!tabId) return
      const state = this.getAgentPptPlanningStateWithSystemSources()
      if (!getPptSourceSummary(state).selected) return
      if (hasPptBlockingInputs(state)) return
      const manifest = getPptSourceDeliveryManifest(state)
      if (!manifest.deliverableSources.length) {
        const requestId = createPptGenerationRequestId('outline-preflight')
        const failedState = failPptGenerationJob(
          startPptGenerationJob(state, { requestId, type: 'outline', tabId }),
          requestId,
          '当前已选来源没有可发送给 AI 的指标或证据，请刷新来源或重新选择来源。',
          { source: 'outline' },
        )
        this.updateAgentPptPlanningTabState(tabId, appendPptDebugEventToState(failedState, 'source_payload_preflight_failed', {
          selectedSourceIds: manifest.sourceIds,
          deliverableSourceIds: manifest.deliverableSourceIds,
          emptyPayloadSourceIds: manifest.emptyPayloadSourceIds,
        }))
        return
      }
      const requestId = createPptGenerationRequestId('outline')
      const writeRuntimeState = (nextState = {}) => this.updateAgentPptPlanningTabRuntimeState(tabId, nextState)
      const writeRuntimeEvent = (name = '', details = {}) => {
        try {
          return writeRuntimeState(appendPptDebugEventToState(
            this.getAgentPptPlanningTabState(tabId),
            name,
            { requestId, tabId, type: 'outline', ...cloneObject(details) },
          ))
        } catch (error) {
          if (typeof console !== 'undefined' && console.error) console.error('PPT outline runtime event failed', error)
          return false
        }
      }
      writeRuntimeState(startPptGenerationJob(state, { requestId, type: 'outline', tabId }))
      writeRuntimeEvent('outline_start_dispatched')
      const heartbeatId = globalThis.setInterval(() => {
        writeRuntimeEvent('generation_heartbeat')
      }, 10000)
      writeRuntimeEvent('heartbeat_scheduled', { intervalMs: 10000 })
      let response = null
      const emitRequestDebugEvent = (name = '', details = {}) => {
        writeRuntimeEvent(name, details)
      }
      try {
        const payload = buildPptSpecPayload(state, this.buildAgentPptPlanningApiContext())
        writeRuntimeEvent('source_payload_preflight', {
          selectedSourceIds: manifest.sourceIds,
          deliverableSourceIds: manifest.deliverableSourceIds,
          emptyPayloadSourceIds: manifest.emptyPayloadSourceIds,
          payloadSourceCount: cloneArray(payload.sources).length,
        })
        response = await this.requestAgentPptPlanningOutlineWithDebug(
          payload,
          { onDebugEvent: emitRequestDebugEvent },
        )
        writeRuntimeEvent('fetch_resolved')
        writeRuntimeEvent('json_or_api_returned', {
          outlineCount: cloneArray(response && response.outline).length,
          keys: Object.keys(response || {}).slice(0, 8),
        })
        const currentState = this.getAgentPptPlanningTabStateWithSystemSources(tabId)
        const completedState = completePptGenerationJob(currentState, requestId, response)
        this.updateAgentPptPlanningTabState(tabId, completedState)
      } catch (error) {
        writeRuntimeEvent('fetch_failed', {
          kind: asText(error && error.kind),
          code: asText(error && error.code),
          message: asText(error && error.message ? error.message : error),
        })
        this.updateAgentPptPlanningTabState(tabId, failPptGenerationJob(
          this.getAgentPptPlanningTabStateWithSystemSources(tabId),
          requestId,
          normalizePptGenerationErrorMessage(error, 'outline'),
          { source: 'outline', generationResponse: response || error?.response || error?.data || {} },
        ))
      } finally {
        globalThis.clearInterval(heartbeatId)
      }
    },
    async generateAgentPptPlanningDirective() {
      const activeTab = this.getAgentActivePptPlanningTab()
      const tabId = asText(activeTab && activeTab.id)
      if (!tabId) return
      const state = this.getAgentPptPlanningStateWithSystemSources()
      if (!cloneArray(state.outline).length) return
      const staleFilenames = collectPptVisualArtifactFilenames(state.deckBrief)
      const requestId = createPptGenerationRequestId('directive')
      const writeRuntimeState = (nextState = {}) => this.updateAgentPptPlanningTabRuntimeState(tabId, nextState)
      const writeRuntimeEvent = (name = '', details = {}) => {
        try {
          return writeRuntimeState(appendPptDebugEventToState(
            this.getAgentPptPlanningTabState(tabId),
            name,
            { requestId, tabId, type: 'directive', ...cloneObject(details) },
          ))
        } catch (error) {
          if (typeof console !== 'undefined' && console.error) console.error('PPT directive runtime event failed', error)
          return false
        }
      }
      writeRuntimeState(startPptGenerationJob(state, { requestId, type: 'directive', tabId }))
      writeRuntimeEvent('directive_start_dispatched')
      const heartbeatId = globalThis.setInterval(() => {
        writeRuntimeEvent('generation_heartbeat')
      }, 10000)
      writeRuntimeEvent('heartbeat_scheduled', { intervalMs: 10000 })
      let response = null
      const emitRequestDebugEvent = (name = '', details = {}) => {
        writeRuntimeEvent(name, details)
      }
      try {
        response = await this.requestAgentPptPlanningDirectiveWithDebug(
          buildDeckBriefPayload(state, await this.buildAgentPptPlanningVisualApiContext()),
          { onDebugEvent: emitRequestDebugEvent },
        )
        writeRuntimeEvent('fetch_resolved')
        writeRuntimeEvent('json_or_api_returned', {
          slideCount: cloneArray(response && response.slides).length,
          keys: Object.keys(response || {}).slice(0, 8),
        })
        const completedState = completePptGenerationJob(
          this.getAgentPptPlanningTabStateWithSystemSources(tabId),
          requestId,
          response,
        )
        this.updateAgentPptPlanningTabState(tabId, completedState)
        if (asText(completedState.generationJob && completedState.generationJob.phase) === 'ready') {
          this.cleanupAgentPptPlanningVisualArtifacts(staleFilenames)
        }
      } catch (error) {
        writeRuntimeEvent('fetch_failed', {
          kind: asText(error && error.kind),
          code: asText(error && error.code),
          message: asText(error && error.message ? error.message : error),
        })
        this.updateAgentPptPlanningTabState(tabId, failPptGenerationJob(
          this.getAgentPptPlanningTabStateWithSystemSources(tabId),
          requestId,
          normalizePptGenerationErrorMessage(error, 'directive'),
          { source: 'directive', generationResponse: response || error?.response || error?.data || {} },
        ))
      } finally {
        globalThis.clearInterval(heartbeatId)
      }
    },
    async generateAgentPptPlanningNarrativePlan() {
      const activeTab = this.getAgentActivePptPlanningTab()
      const tabId = asText(activeTab && activeTab.id)
      if (!tabId) return
      const state = this.getAgentPptPlanningStateWithSystemSources()
      if (!cloneArray(state.outline).length) return
      const requestId = createPptGenerationRequestId('narrative')
      const writeRuntimeState = (nextState = {}) => this.updateAgentPptPlanningTabRuntimeState(tabId, nextState)
      const writeRuntimeEvent = (name = '', details = {}) => {
        try {
          return writeRuntimeState(appendPptDebugEventToState(
            this.getAgentPptPlanningTabState(tabId),
            name,
            { requestId, tabId, type: 'narrative', ...cloneObject(details) },
          ))
        } catch (error) {
          if (typeof console !== 'undefined' && console.error) console.error('PPT narrative runtime event failed', error)
          return false
        }
      }
      writeRuntimeState(startPptGenerationJob(state, { requestId, type: 'narrative', tabId }))
      writeRuntimeEvent('narrative_start_dispatched')
      const heartbeatId = globalThis.setInterval(() => {
        writeRuntimeEvent('generation_heartbeat')
      }, 10000)
      let response = null
      try {
        response = await this.requestAgentPptPlanningNarrativePlanWithDebug(
          buildNarrativePlanPayload(state, this.buildAgentPptPlanningApiContext()),
          { onDebugEvent: (name = '', details = {}) => writeRuntimeEvent(name, details) },
        )
        writeRuntimeEvent('json_or_api_returned', {
          roleCount: cloneArray(response && (response.slide_roles || response.slideRoles)).length,
          keys: Object.keys(response || {}).slice(0, 8),
        })
        const completedState = completePptGenerationJob(
          this.getAgentPptPlanningTabStateWithSystemSources(tabId),
          requestId,
          response,
        )
        this.updateAgentPptPlanningTabState(tabId, completedState)
      } catch (error) {
        writeRuntimeEvent('fetch_failed', {
          kind: asText(error && error.kind),
          code: asText(error && error.code),
          message: asText(error && error.message ? error.message : error),
        })
        this.updateAgentPptPlanningTabState(tabId, failPptGenerationJob(
          this.getAgentPptPlanningTabStateWithSystemSources(tabId),
          requestId,
          normalizePptGenerationErrorMessage(error, 'narrative'),
          { source: 'narrative', generationResponse: response || error?.response || error?.data || {} },
        ))
      } finally {
        globalThis.clearInterval(heartbeatId)
      }
    },
    async generateAgentPptPlanningSlides() {
      const activeTab = this.getAgentActivePptPlanningTab()
      const tabId = asText(activeTab && activeTab.id)
      if (!tabId) return
      let state = this.getAgentPptPlanningStateWithSystemSources()
      const outline = cloneArray(state.outline).sort((a, b) => (Number(a.pageNo || 0) || 0) - (Number(b.pageNo || 0) || 0))
      if (!outline.length || !cloneArray(state.narrativePlan && state.narrativePlan.slideRoles).length) return
      this.updateAgentPptPlanningTabState(tabId, startSlideGenerationQueue(state))
      const visualContext = await this.buildAgentPptPlanningVisualApiContext()
      for (const outlineItem of outline) {
        state = this.getAgentPptPlanningTabStateWithSystemSources(tabId)
        const existing = cloneArray((state.deckBrief || {}).slides).find((slide) => Number(slide.index || 0) === Number(outlineItem.pageNo || 0))
        if (existing) continue
        try {
          const response = await this.requestAgentPptPlanningDirectiveSlide(buildDeckBriefSlidePayload(
            state,
            { index: Number(outlineItem.pageNo || 0), title: outlineItem.theme, purpose: outlineItem.purpose },
            '按已确认目录和叙事方案生成这一页 brief。',
            visualContext,
          ))
          this.updateAgentPptPlanningTabState(tabId, applyGeneratedSlideBrief(
            this.getAgentPptPlanningTabStateWithSystemSources(tabId),
            response,
          ))
        } catch (error) {
          this.updateAgentPptPlanningTabState(tabId, failSlideGenerationQueue(
            this.getAgentPptPlanningTabStateWithSystemSources(tabId),
            Number(outlineItem.pageNo || 0),
            normalizePptGenerationErrorMessage(error, 'slides'),
          ))
          break
        }
      }
    },
    async generateAgentPptPlanningSlideVisuals(slideIndex = 0) {
      const activeTab = this.getAgentActivePptPlanningTab()
      const tabId = asText(activeTab && activeTab.id)
      const index = Number(slideIndex || 0) || 0
      if (!tabId || !index) return
      let state = this.getAgentPptPlanningTabStateWithSystemSources(tabId)
      const slide = cloneArray((state.deckBrief || {}).slides).find((item) => Number(item.index || 0) === index)
      if (!slide || !cloneArray(slide.visualSpecs).length) return
      this.updateAgentPptPlanningTabState(tabId, startPptVisualArtifactsGeneration(state, index))
      try {
        const response = await this.requestAgentPptPlanningVisualArtifacts(buildPptVisualArtifactsPayload(
          this.getAgentPptPlanningTabStateWithSystemSources(tabId),
          slide,
          await this.buildAgentPptPlanningVisualApiContext(),
        ))
        this.updateAgentPptPlanningTabState(tabId, applyPptVisualArtifactsResponse(
          this.getAgentPptPlanningTabStateWithSystemSources(tabId),
          response,
        ))
      } catch (error) {
        this.updateAgentPptPlanningTabState(tabId, failPptVisualArtifacts(
          this.getAgentPptPlanningTabStateWithSystemSources(tabId),
          index,
          normalizePptGenerationErrorMessage(error, 'visuals'),
        ))
      }
    },
    async generateAgentPptPlanningAllVisuals() {
      const activeTab = this.getAgentActivePptPlanningTab()
      const tabId = asText(activeTab && activeTab.id)
      if (!tabId) return
      const initialState = this.getAgentPptPlanningTabStateWithSystemSources(tabId)
      const slides = cloneArray((initialState.deckBrief || {}).slides)
        .filter((slide) => cloneArray(slide.visualSpecs).length)
        .sort((left, right) => (Number(left.index || 0) || 0) - (Number(right.index || 0) || 0))
      if (!slides.length) return
      for (const slide of slides) {
        await this.generateAgentPptPlanningSlideVisuals(Number(slide.index || 0) || 0)
      }
    },
    confirmAgentPptPlanningStepReset(message = '') {
      if (typeof this.confirmPptPlanningStepReset === 'function') {
        return this.confirmPptPlanningStepReset(message)
      }
      if (typeof window === 'undefined' || typeof window.confirm !== 'function') return true
      return window.confirm(message)
    },
    async regenerateAgentPptPlanningOutlineWithConfirm() {
      const state = this.getAgentPptPlanningStateWithSystemSources()
      const hasOutline = cloneArray(state.outline).length > 0
      const hasDirective = asText(state.currentStep) === 'directive_draft' && cloneArray((state.deckBrief || {}).slides).length > 0
      if (!hasOutline && !hasDirective) return
      if (!getPptSourceSummary(state).selected || hasPptBlockingInputs(state)) return
      const confirmed = await this.confirmAgentPptPlanningStepReset('重新生成目录会清空旧目录和旧指令文件，确认继续？')
      if (!confirmed) return
      const staleFilenames = collectPptVisualArtifactFilenames(state.deckBrief)
      this.updateAgentActivePptPlanningState(resetPptPlanningToMaterials(this.getAgentPptPlanningStateWithSystemSources()))
      this.cleanupAgentPptPlanningVisualArtifacts(staleFilenames)
      await this.generateAgentPptPlanningOutline()
    },
    async regenerateAgentPptPlanningDirectiveWithConfirm() {
      const state = this.getAgentPptPlanningStateWithSystemSources()
      const hasOutline = cloneArray(state.outline).length > 0
      const hasDirective = asText(state.currentStep) === 'directive_draft' && cloneArray((state.deckBrief || {}).slides).length > 0
      if (!hasOutline || !hasDirective) return
      const confirmed = await this.confirmAgentPptPlanningStepReset('重新生成指令文件会清空旧指令文件，但保留当前目录，确认继续？')
      if (!confirmed) return
      const staleFilenames = collectPptVisualArtifactFilenames(state.deckBrief)
      this.updateAgentActivePptPlanningState(resetPptPlanningToOutlineReady(this.getAgentPptPlanningStateWithSystemSources()))
      this.cleanupAgentPptPlanningVisualArtifacts(staleFilenames)
      await this.generateAgentPptPlanningDirective()
    },
    async regenerateAgentPptPlanningNarrativePlanWithConfirm() {
      const state = this.getAgentPptPlanningStateWithSystemSources()
      const hasOutline = cloneArray(state.outline).length > 0
      if (!hasOutline) return
      const confirmed = await this.confirmAgentPptPlanningStepReset('重新生成叙事方案会清空旧叙事方案和逐页 brief，但保留当前目录，确认继续？')
      if (!confirmed) return
      const staleFilenames = collectPptVisualArtifactFilenames(state.deckBrief)
      this.updateAgentActivePptPlanningState(resetPptPlanningToOutlineReady(this.getAgentPptPlanningStateWithSystemSources()))
      this.cleanupAgentPptPlanningVisualArtifacts(staleFilenames)
      await this.generateAgentPptPlanningNarrativePlan()
    },
    async regenerateAgentPptPlanningSlidesWithConfirm() {
      const state = this.getAgentPptPlanningStateWithSystemSources()
      const hasNarrativePlan = cloneArray(state.narrativePlan && state.narrativePlan.slideRoles).length > 0
      if (!hasNarrativePlan) return
      const confirmed = await this.confirmAgentPptPlanningStepReset('重新逐页生成 brief 会清空旧 brief，但保留当前目录和叙事方案，确认继续？')
      if (!confirmed) return
      const staleFilenames = collectPptVisualArtifactFilenames(state.deckBrief)
      this.updateAgentActivePptPlanningState(resetPptPlanningToNarrativeReady(this.getAgentPptPlanningStateWithSystemSources()))
      this.cleanupAgentPptPlanningVisualArtifacts(staleFilenames)
      await this.generateAgentPptPlanningSlides()
    },
    selectAgentPptPlanningSlide(slideId = '') {
      this.updateAgentActivePptPlanningState(selectDeckSlideBrief(this.getAgentActivePptPlanningState(), slideId))
    },
    captureAgentActivePptPlanningTabState() {
      const tabs = this.ensureAgentTabs(true)
      const activeTab = this.getAgentActiveTopTab()
      if (asText(activeTab.kind) !== 'ppt_planning') return
      const nextPptPlanningTabs = cloneArray(tabs.pptPlanningTabs).map((item) => {
        if (item.id !== activeTab.id || item.readonly) return item
        return {
          ...item,
          panelPayloads: cloneObject(this.agentPanelPayloads),
          pptPlanningState: createPptPlanningState(item.pptPlanningState),
        }
      })
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), iterationChangeTabs: cloneArray(tabs.iterationChangeTabs), siteSelectionTabs: cloneArray(tabs.siteSelectionTabs), pptPlanningTabs: nextPptPlanningTabs, deepAnalysisTabs: cloneArray(tabs.deepAnalysisTabs), followupTabs: cloneArray(tabs.followupTabs) }
    },
    createAgentPptPlanningTab(options = {}) {
      const tabs = this.ensureAgentTabs(true)
      this.captureAgentActiveSummaryTabState()
      this.captureAgentActiveSiteSelectionTabState()
      this.captureAgentActivePptPlanningTabState()
      this.captureAgentActiveDeepAnalysisTabState()
      this.captureAgentActiveFollowupTabState()
      const tabId = this.createAgentPptPlanningViewId()
      const tab = {
        id: tabId,
        kind: 'ppt_planning',
        title: this.formatAgentTabTitle('ppt_planning', options.title),
        source: asText(options.source) || 'draft',
        sessionId: asText(options.sessionId),
        readonly: !!options.readonly,
        createdAt: new Date().toISOString(),
        panelPayloads: cloneObject(this.agentPanelPayloads),
        pptPlanningState: mergePptPlanningSources(createPptPlanningState(options.pptPlanningState), createPptSystemSources(this.buildAgentPptPlanningSystemSourceContext())),
      }
      tabs.pptPlanningTabs = [...cloneArray(tabs.pptPlanningTabs), tab]
      tabs.activeTabId = tabId
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), iterationChangeTabs: cloneArray(tabs.iterationChangeTabs), siteSelectionTabs: cloneArray(tabs.siteSelectionTabs), pptPlanningTabs: cloneArray(tabs.pptPlanningTabs), deepAnalysisTabs: cloneArray(tabs.deepAnalysisTabs), followupTabs: cloneArray(tabs.followupTabs) }
      this.syncActiveAgentRuntimeView(this.activeAgentSessionId)
      this.syncCurrentAgentSession()
      this.refreshAgentActivePptPlanningDataSources()
      return tabId
    },
  }
}
