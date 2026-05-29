import { asText, cloneArray, cloneObject } from './normalizers.js'

const PARAM_BUNDLE_VERSION = 1

function toNumber(value, fallback = 0) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function stableNormalize(value) {
  if (Array.isArray(value)) return value.map((item) => stableNormalize(item))
  if (!value || typeof value !== 'object') return value
  return Object.keys(value)
    .sort()
    .reduce((acc, key) => {
      acc[key] = stableNormalize(value[key])
      return acc
    }, {})
}

function stableStringify(value) {
  return JSON.stringify(stableNormalize(value || {}))
}

function buildCacheKey(taskKey = '', params = {}) {
  return `${asText(taskKey)}:v${PARAM_BUNDLE_VERSION}:${stableStringify(params)}`
}

function createBundle({ taskKey, domain, params = {}, evidenceParams = {}, resultRefs = {}, displayLabel = '' }) {
  const safeTaskKey = asText(taskKey)
  const safeParams = cloneObject(params)
  return {
    task_key: safeTaskKey,
    domain: asText(domain),
    version: PARAM_BUNDLE_VERSION,
    params: safeParams,
    evidence_params: cloneObject(evidenceParams),
    result_refs: cloneObject(resultRefs),
    cache_key: buildCacheKey(safeTaskKey, safeParams),
    display_label: asText(displayLabel),
  }
}

function buildPoiFetchParamBundle(ctx = {}) {
  const year = Number(ctx.poiYearSource || ctx.resultPoiYear || 0) || null
  const source = asText(ctx.poiDataSource || ctx.resultDataSource || '')
  const params = {
    source,
    year,
    years: year ? [year] : [],
  }
  return createBundle({
    taskKey: 'poi_fetch',
    domain: 'poi',
    params,
    evidenceParams: {
      poi_source: source,
      poi_year: year,
      poi_years: params.years,
    },
    resultRefs: {
      poi_count: Array.isArray(ctx.allPoisDetails) ? ctx.allPoisDetails.length : 0,
      category_summary_count: Array.isArray(ctx.poiCategorySummary) ? ctx.poiCategorySummary.length : 0,
    },
    displayLabel: `${year || '当前年份'}，${source || '当前 POI 数据源'}`,
  })
}

function buildPoiGridParamBundle(ctx = {}) {
  const year = Number(ctx.poiYearSource || ctx.resultPoiYear || 0) || null
  const source = asText(ctx.poiDataSource || ctx.resultDataSource || '')
  const isRasterMode = typeof ctx.isPoiRasterGridMode === 'function'
    ? ctx.isPoiRasterGridMode()
    : asText(ctx.poiGridType || 'raster') !== 'hex'
  const includeMode = asText(ctx.h3GridIncludeMode || '')
  const params = {
    current_display_grid_type: isRasterMode ? 'raster' : 'hex',
    computed_grid_types: ['raster', 'hex'],
    poi_source: source,
    poi_year: year,
    poi_years: year ? [year] : [],
    poi_coord_type: 'gcj02',
    raster: {
      grid_type: 'raster',
      cell_id_source: 'population_nightlight_shared_cell_id',
      coord_type: 'gcj02',
      poi_coord_type: 'gcj02',
      year,
    },
    hex: {
      grid_type: 'hex',
      h3_resolution: toNumber(ctx.h3GridResolution, 10),
      neighbor_ring: toNumber(ctx.h3NeighborRing, 1),
      include_mode: includeMode,
      min_overlap_ratio: includeMode === 'intersects' ? toNumber(ctx.h3GridMinOverlapRatio, 0) : 0,
    },
  }
  return createBundle({
    taskKey: 'poi_grid',
    domain: 'poi',
    params,
    evidenceParams: {
      description: 'POI 同时按共享 cell_id 栅格和 POI H3 六边形网格计算。',
      raster_usage: 'POI 共享栅格用于和人口/夜光按同一 cell_id 对齐。',
      hex_usage: 'POI H3 六边形网格用于 POI 供给、密度结构、热点和聚集分析。',
      current_display_grid_type: params.current_display_grid_type,
      computed_grid_types: cloneArray(params.computed_grid_types),
      raster: cloneObject(params.raster),
      hex: cloneObject(params.hex),
    },
    resultRefs: {
      raster_summary: cloneObject(ctx.poiGridSummary || {}),
      raster_counts: {
        grid_count: toNumber(ctx.poiGridSummary && ctx.poiGridSummary.grid_count, cloneArray(ctx.poiGridFeatures).length),
        active_cell_count: toNumber(ctx.poiGridSummary && ctx.poiGridSummary.active_cell_count, 0),
        assigned_poi_count: toNumber(ctx.poiGridSummary && ctx.poiGridSummary.assigned_poi_count, 0),
        max_poi_count: toNumber(ctx.poiGridSummary && ctx.poiGridSummary.max_poi_count, 0),
        avg_density_poi_per_km2: toNumber(ctx.poiGridSummary && ctx.poiGridSummary.avg_density_poi_per_km2, 0),
      },
      h3_summary: cloneObject(ctx.h3AnalysisSummary || {}),
      h3_counts: {
        grid_count: toNumber((ctx.h3AnalysisSummary && ctx.h3AnalysisSummary.grid_count) || ctx.h3GridCount, 0),
        poi_count: toNumber(ctx.h3AnalysisSummary && ctx.h3AnalysisSummary.poi_count, 0),
        avg_density_poi_per_km2: toNumber(ctx.h3AnalysisSummary && ctx.h3AnalysisSummary.avg_density_poi_per_km2, 0),
        avg_local_entropy: toNumber(ctx.h3AnalysisSummary && ctx.h3AnalysisSummary.avg_local_entropy, 0),
      },
    },
    displayLabel: `${year || '当前 POI 年份'}，${source || '当前 POI 数据'}，共享栅格 + POI H3，H3 res=${params.hex.h3_resolution}`,
  })
}

function buildPoiRasterGridParamBundle(ctx = {}) {
  const year = Number(ctx.poiYearSource || ctx.resultPoiYear || 0) || null
  const source = asText(ctx.poiDataSource || ctx.resultDataSource || '')
  const params = {
    grid_type: 'raster',
    poi_source: source,
    poi_year: year,
    poi_years: year ? [year] : [],
    poi_coord_type: 'gcj02',
    cell_id_source: 'population_nightlight_shared_cell_id',
    coord_type: 'gcj02',
  }
  return createBundle({
    taskKey: 'poi_raster_grid',
    domain: 'poi',
    params,
    evidenceParams: {
      description: 'POI 共享栅格和人口/夜光按同一 cell_id 对齐。',
      usage: '用于人口、POI、夜光共享栅格交叉诊断。',
      ...cloneObject(params),
    },
    resultRefs: {
      raster_summary: cloneObject(ctx.poiGridSummary || {}),
      raster_counts: {
        grid_count: toNumber(ctx.poiGridSummary && ctx.poiGridSummary.grid_count, cloneArray(ctx.poiGridFeatures).length),
        active_cell_count: toNumber(ctx.poiGridSummary && ctx.poiGridSummary.active_cell_count, 0),
        assigned_poi_count: toNumber(ctx.poiGridSummary && ctx.poiGridSummary.assigned_poi_count, 0),
        max_poi_count: toNumber(ctx.poiGridSummary && ctx.poiGridSummary.max_poi_count, 0),
        avg_density_poi_per_km2: toNumber(ctx.poiGridSummary && ctx.poiGridSummary.avg_density_poi_per_km2, 0),
      },
    },
    displayLabel: `${year || '当前 POI 年份'}，${source || '当前 POI 数据'}，POI 共享栅格`,
  })
}

function buildPoiH3GridParamBundle(ctx = {}) {
  const year = Number(ctx.poiYearSource || ctx.resultPoiYear || 0) || null
  const source = asText(ctx.poiDataSource || ctx.resultDataSource || '')
  const includeMode = asText(ctx.h3GridIncludeMode || '')
  const params = {
    grid_type: 'hex',
    poi_source: source,
    poi_year: year,
    poi_years: year ? [year] : [],
    poi_coord_type: 'gcj02',
    h3_resolution: toNumber(ctx.h3GridResolution, 10),
    neighbor_ring: toNumber(ctx.h3NeighborRing, 1),
    include_mode: includeMode,
    min_overlap_ratio: includeMode === 'intersects' ? toNumber(ctx.h3GridMinOverlapRatio, 0) : 0,
  }
  return createBundle({
    taskKey: 'poi_h3_grid',
    domain: 'poi',
    params,
    evidenceParams: {
      description: 'POI H3 六边形网格按 H3 聚合 POI 供给和密度结构。',
      usage: '用于 POI 空间结构、热点、LISA、Gi*、LQ 和缺口分析。',
      ...cloneObject(params),
    },
    resultRefs: {
      h3_summary: cloneObject(ctx.h3AnalysisSummary || {}),
      h3_counts: {
        grid_count: toNumber((ctx.h3AnalysisSummary && ctx.h3AnalysisSummary.grid_count) || ctx.h3GridCount, 0),
        poi_count: toNumber(ctx.h3AnalysisSummary && ctx.h3AnalysisSummary.poi_count, 0),
        avg_density_poi_per_km2: toNumber(ctx.h3AnalysisSummary && ctx.h3AnalysisSummary.avg_density_poi_per_km2, 0),
        avg_local_entropy: toNumber(ctx.h3AnalysisSummary && ctx.h3AnalysisSummary.avg_local_entropy, 0),
      },
    },
    displayLabel: `${year || '当前 POI 年份'}，${source || '当前 POI 数据'}，POI H3 res=${params.h3_resolution}`,
  })
}

function buildPopulationParamBundle(ctx = {}) {
  const year = asText(
    typeof ctx.getPopulationSelectedYear === 'function'
      ? ctx.getPopulationSelectedYear()
      : (ctx.populationSelectedYear || ''),
  )
  const view = asText(ctx.populationAnalysisView || '')
  const params = {
    year,
    view,
    grid_type: 'shared_cell_id',
    cell_id_source: 'population_nightlight_shared_cell_id',
  }
  return createBundle({
    taskKey: 'population',
    domain: 'population',
    params,
    evidenceParams: {
      year,
      view,
      grid_type: params.grid_type,
      cell_id_source: params.cell_id_source,
      sex_metric_mode: asText(ctx.populationSexMetricMode || ''),
    },
    resultRefs: {
      has_overview: !!ctx.populationOverview,
      grid_count: Number(ctx.populationGridCount || 0) || cloneArray(ctx.populationLayer && ctx.populationLayer.cells).length,
    },
    displayLabel: year ? `年份 ${year}` : '当前人口默认年份',
  })
}

function buildNightlightParamBundle(ctx = {}) {
  const year = asText(
    typeof ctx.getNightlightSelectedYear === 'function'
      ? ctx.getNightlightSelectedYear()
      : (ctx.nightlightSelectedYear || ''),
  )
  const params = {
    year,
    view: asText(ctx.nightlightAnalysisView || ''),
    grid_type: 'shared_cell_id',
    cell_id_source: 'population_nightlight_shared_cell_id',
  }
  return createBundle({
    taskKey: 'nightlight',
    domain: 'nightlight',
    params,
    evidenceParams: cloneObject(params),
    resultRefs: {
      has_overview: !!ctx.nightlightOverview,
      cell_count: cloneArray(ctx.nightlightLayer && ctx.nightlightLayer.cells).length,
    },
    displayLabel: year ? `年份 ${year}` : '当前夜光默认年份',
  })
}

function buildRoadSyntaxParamBundle(ctx = {}) {
  const params = {
    graph_model: asText(ctx.roadSyntaxGraphModel || ''),
    metric: asText(ctx.roadSyntaxLastMetricTab || ctx.roadSyntaxMetric || ''),
    blue: Number(ctx.roadSyntaxDisplayBlue || 0),
    red: Number(ctx.roadSyntaxDisplayRed || 0),
    transport_mode: asText(ctx.transportMode || ''),
    time_horizon: Number(ctx.timeHorizon || 0) || 0,
  }
  return createBundle({
    taskKey: 'road_syntax',
    domain: 'road',
    params,
    evidenceParams: cloneObject(params),
    resultRefs: {
      has_summary: !!ctx.roadSyntaxSummary,
      node_count: toNumber(ctx.roadSyntaxSummary && ctx.roadSyntaxSummary.node_count, 0),
      edge_count: toNumber(ctx.roadSyntaxSummary && ctx.roadSyntaxSummary.edge_count, 0),
    },
    displayLabel: `图模型 ${params.graph_model || 'segment'}，指标 ${params.metric || '当前指标'}`,
  })
}

function buildAnalysisTaskParamBundle(ctx = {}, taskKey = '') {
  const key = asText(taskKey)
  if (key === 'poi_fetch') return buildPoiFetchParamBundle(ctx)
  if (key === 'poi_raster_grid') return buildPoiRasterGridParamBundle(ctx)
  if (key === 'poi_h3_grid') return buildPoiH3GridParamBundle(ctx)
  if (key === 'poi_grid') return buildPoiGridParamBundle(ctx)
  if (key === 'population') return buildPopulationParamBundle(ctx)
  if (key === 'nightlight') return buildNightlightParamBundle(ctx)
  if (key === 'road_syntax') return buildRoadSyntaxParamBundle(ctx)
  return createBundle({
    taskKey: key,
    domain: '',
    params: {},
    evidenceParams: {},
    resultRefs: {},
    displayLabel: '当前面板参数',
  })
}

function buildAnalysisTaskParamBundles(ctx = {}, taskKeys = []) {
  return cloneArray(taskKeys)
    .map((key) => asText(key))
    .filter(Boolean)
    .reduce((acc, key) => {
      acc[key] = buildAnalysisTaskParamBundle(ctx, key)
      return acc
    }, {})
}

export {
  buildAnalysisTaskParamBundle,
  buildAnalysisTaskParamBundles,
}
