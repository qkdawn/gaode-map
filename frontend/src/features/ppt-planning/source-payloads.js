import { asText, cloneArray, cloneObject } from '../shared/normalizers.js'
import { evidenceNodesFromEvidenceItems } from '../analysis-sources/evidence-nodes.js'
import { createPptTransportFromAiPayload } from './model.js'

export function normalizePptLngLat(value = null) {
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

export function hasRing(value) {
  return Array.isArray(value) && value.length >= 3
}

export function resolvePptPlanningRadiusMeters(ctx = {}, featureProps = {}) {
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
  const metric = {
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
  }
  const details = cloneObject(options.details)
  if (Object.keys(details).length) metric.details = details
  const evidencePayload = cloneObject(options.evidencePayload || options.evidence_payload)
  if (Object.keys(evidencePayload).length) metric.evidence_payload = evidencePayload
  metrics.push(metric)
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
  const total = finiteMetricValue(totalPopulation)
  const rows = cloneArray(ageRows)
    .map((item) => ({
      age_band: asText(item && (item.age_band || item.ageBand)),
      age_band_label: asText(item && (item.age_band_label || item.ageBandLabel)),
      total: finiteMetricValue(item && item.total),
    }))
    .filter((item) => item.total !== null && item.total > 0)
    .map((item) => ({
      ...item,
      ratio: total && total > 0 ? Number((item.total / total).toFixed(6)) : null,
    }))
    .sort((left, right) => right.total - left.total)
  if (!rows.length) return null
  const top = rows[0]
  const ratio = top.ratio
  const topLabel = top.age_band_label || top.age_band
  const details = {
    dominant_age_band: top.age_band,
    dominant_age_band_label: top.age_band_label,
    dominant_age_band_population: top.total,
    dominant_age_band_ratio: ratio,
    age_distribution_ratios: rows,
  }
  return {
    value: ratio !== null ? Number((ratio * 100).toFixed(2)) : top.total,
    unit: ratio !== null ? '%' : '人',
    ...details,
    details,
    description: ratio !== null
      ? `已计算各年龄段占比；当前占比最高年龄段为${topLabel}，占总人口 ${Number((ratio * 100).toFixed(1))}%。`
      : `当前已读取年龄段人口数，但缺少总人口，无法计算占比；人口数最高年龄段为${topLabel}。`,
  }
}

export function buildCurrentNightlightAnalysis(ctx = {}) {
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

export function buildPptAnalysisMetrics(ctx = {}, scope = {}, taskResults = {}) {
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
      calculationMethod: '基于 populationOverview.age_distribution 计算各年龄段占总人口比例，并以占比最高年龄段作为卡片主值。',
      description: ageStructure.description,
      details: ageStructure.details,
      evidencePayload: ageStructure.details,
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

export function buildPptDataPackageSpatialPayload(current = {}) {
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

export function isReadySource(source = {}) {
  return asText(source && source.status) === 'ready'
}

export function isPptDocumentSource(source = {}) {
  const meta = cloneObject(source && source.meta)
  return asText(meta.sourceKind) === 'document' || asText(source && source.id).startsWith('document:')
}

export function isPptImageSource(source = {}) {
  const meta = cloneObject(source && source.meta)
  return asText(meta.sourceKind) === 'image' || asText(source && source.id).startsWith('image:')
}

export function isPptPersistedArtifactSource(source = {}) {
  const meta = cloneObject(source && source.meta)
  const sourceKind = asText(meta.sourceKind)
  const sourceId = asText(source && source.id)
  return sourceKind === 'package'
    || sourceKind === 'web'
    || sourceKind === 'database'
    || sourceId.startsWith('package:')
    || sourceId.startsWith('database:')
}

export function imageAttachmentIdFromPptSource(source = {}) {
  const meta = cloneObject(source && source.meta)
  const image = cloneObject(meta.image)
  const explicit = asText(meta.attachmentId || meta.attachment_id || image.attachment_id || image.attachmentId)
  if (explicit) return explicit
  const sourceId = asText(source && source.id)
  return sourceId.startsWith('image:') ? sourceId.slice('image:'.length) : ''
}

export function imageConversationIdFromPptSource(source = {}) {
  const meta = cloneObject(source && source.meta)
  const image = cloneObject(meta.image)
  return asText(meta.conversationId || meta.conversation_id || image.conversation_id || image.conversationId)
}

export function webSourceRetryPayloadFromPptSource(source = {}, areaId = '') {
  const meta = cloneObject(source && source.meta)
  const webSource = cloneObject(meta.web_source)
  const urls = cloneArray(webSource.urls).map((item) => asText(item)).filter(Boolean)
  return {
    area_id: asText(areaId || meta.areaId || meta.area_id),
    region_name: asText(webSource.region_name) || '当前分析区域',
    administrative_area: asText(webSource.administrative_area),
    topic: asText(webSource.topic || webSource.intent || source.title),
    intent: asText(webSource.intent),
    categories: cloneArray(webSource.categories).map((item) => asText(item)).filter(Boolean),
    source_modes: cloneArray(webSource.source_modes || webSource.sourceModes).map((item) => asText(item)).filter(Boolean),
    urls,
  }
}

export function documentIdFromPptSource(source = {}) {
  const meta = cloneObject(source && source.meta)
  const document = cloneObject(meta.document)
  const explicit = asText(meta.documentId || meta.document_id || document.id || document.document_id)
  if (explicit) return explicit
  const sourceId = asText(source && source.id)
  return sourceId.startsWith('document:') ? sourceId.slice('document:'.length) : ''
}

export function createPptSourceTransportPreview({
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

export function createPptAiInputBlock({
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
  const payload = {
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
  const evidenceNodes = evidenceNodesFromEvidenceItems(payload, evidenceItems)
  return {
    ...payload,
    evidence_nodes: evidenceNodes,
  }
}

export function createDocumentAiPayload(sourceId = '', title = '', meta = {}, status = 'pending', count = 0) {
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

export function createPackageAiPayload(sourceId = '', title = '', pack = {}) {
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

export function normalizeBackendPptDataSource(source = {}, areaId = '') {
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
    ? (persistedAiPayload.version === 'ppt_ai_input_block_v1'
      ? persistedAiPayload
      : createDocumentAiPayload(sourceId, title, meta, status, Number(source.count || meta.count || evidenceCount || 0) || 0))
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

export function hasPptEvidencePackage(state = {}, areaId = '', options = {}) {
  const normalizedAreaId = asText(areaId)
  const expectedMode = asText(options.packageMode) || 'evidence'
  const expectedIntent = asText(options.intent)
  const expectedVersion = asText(options.packageVersion)
  const expectedSourceIds = cloneArray(options.sourceIds).map((item) => asText(item)).filter(Boolean)
  return cloneArray(state.sources).some((source) => {
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

export function getPptEvidencePackageKey(areaId = '', options = {}) {
  const normalizedAreaId = asText(areaId)
  const sourceKey = cloneArray(options.sourceIds).map((item) => asText(item)).filter(Boolean).sort().join('+')
  const mode = asText(options.packageMode) || 'evidence'
  const intent = asText(options.intent)
  const version = asText(options.packageVersion)
  return normalizedAreaId ? `${normalizedAreaId}::${sourceKey}::${mode}::${intent}::${version}` : ''
}
