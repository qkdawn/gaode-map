import { asText, cloneArray, cloneObject } from './normalizers.js'
import { buildAnalysisTaskParamBundle, buildAnalysisTaskParamBundles } from './analysis-task-params.js'

function toNumber(value, fallback = 0) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function buildAgentPoiGridEvidence(ctx = {}) {
  const bundle = buildAnalysisTaskParamBundle(ctx, 'poi_raster_grid')
  const params = cloneObject(bundle.params)
  const resultRefs = cloneObject(bundle.result_refs)
  return {
    evidence_version: 'poi_raster_grid_evidence_v1',
    current_display_grid_type: 'shared',
    computed_grid_types: ['shared'],
    params: {
      current_display_grid_type: 'shared',
      computed_grid_types: ['shared'],
      poi_source: asText(params.poi_source),
      poi_year: params.poi_year,
      poi_years: cloneArray(params.poi_years),
      poi_coord_type: asText(params.poi_coord_type),
      shared: cloneObject(params || {}),
    },
    raster_summary: cloneObject(resultRefs.raster_summary || ctx.poiGridSummary || {}),
    raster_counts: cloneObject(resultRefs.raster_counts || {}),
    notes: [
      'POI raster grid uses the same cell_id system as population and nightlight.',
      'H3 evidence is exposed separately as poi_h3_evidence_v1.',
    ],
  }
}

function buildAgentPoiH3Evidence(ctx = {}) {
  const pickMetricProps = (props = {}) => ({
    h3_id: asText(props.h3_id),
    poi_count: toNumber(props.poi_count, 0),
    density_poi_per_km2: toNumber(props.density_poi_per_km2, 0),
    local_entropy: toNumber(props.local_entropy, 0),
    neighbor_mean_density: toNumber(props.neighbor_mean_density, 0),
    neighbor_mean_entropy: toNumber(props.neighbor_mean_entropy, 0),
    neighbor_count: toNumber(props.neighbor_count, 0),
    category_counts: cloneObject(props.category_counts || {}),
    subcategory_counts: cloneObject(props.subcategory_counts || {}),
    lisa_i: Number.isFinite(Number(props.lisa_i)) ? Number(props.lisa_i) : null,
    lisa_z_score: Number.isFinite(Number(props.lisa_z_score)) ? Number(props.lisa_z_score) : null,
    gi_star_value: Number.isFinite(Number(props.gi_star_value)) ? Number(props.gi_star_value) : null,
    gi_star_z_score: Number.isFinite(Number(props.gi_star_z_score)) ? Number(props.gi_star_z_score) : null,
  })
  const scoreCell = (cell = {}) => (
    toNumber(cell.poi_count, 0) * 10
    + toNumber(cell.density_poi_per_km2, 0)
    + Math.abs(toNumber(cell.gi_star_z_score, 0)) * 120
    + Math.abs(toNumber(cell.lisa_z_score, 0)) * 80
    + toNumber(cell.local_entropy, 0) * 30
  )
  const compactRows = (section = {}, limit = 40) => cloneArray(section && section.rows).slice(0, limit)
  const compactSummary = (section = {}) => {
    const source = cloneObject(section)
    delete source.rows
    return source
  }
  const bundle = buildAnalysisTaskParamBundle(ctx, 'poi_h3_grid')
  const params = cloneObject(bundle.params)
  const summary = cloneObject(ctx.h3AnalysisSummary || {})
  const charts = cloneObject(ctx.h3AnalysisCharts || {})
  const features = cloneArray(ctx.h3AnalysisGridFeatures)
  const allCells = features
    .map((feature) => pickMetricProps((feature && feature.properties) || {}))
    .filter((cell) => asText(cell && cell.h3_id))
  const cells = allCells
    .slice()
    .sort((a, b) => scoreCell(b) - scoreCell(a))
    .slice(0, 40)
  const derivedStats = cloneObject(ctx.h3DerivedStats || {})
  return {
    evidence_version: 'poi_h3_evidence_v1',
    grid_type: 'h3',
    usage: 'POI-only spatial structure evidence; do not use it for population or nightlight coupling.',
    params,
    summary,
    charts,
    cells,
    derived_stats: {
      structure_rows: compactRows(derivedStats.structureSummary),
      typing_rows: compactRows(derivedStats.typingSummary),
      lq_rows: compactRows(derivedStats.lqSummary),
      gap_rows: compactRows(derivedStats.gapSummary),
      structure_summary: compactSummary(derivedStats.structureSummary),
      typing_summary: compactSummary(derivedStats.typingSummary),
      lq_summary: compactSummary(derivedStats.lqSummary),
      gap_summary: compactSummary(derivedStats.gapSummary),
    },
    ui: {
      target_category: asText(ctx.h3TargetCategory),
      target_category_label: typeof ctx._getH3CategoryLabel === 'function' ? asText(ctx._getH3CategoryLabel(ctx.h3TargetCategory)) : '',
      metric_view: asText(ctx.h3MetricView || 'density'),
      structure_fill_mode: asText(ctx.h3StructureFillMode || 'gi_z'),
      only_significant: !!ctx.h3OnlySignificant,
      entropy_min_poi: toNumber(ctx.h3EntropyMinPoi, 3),
      lq_smoothing_alpha: toNumber(ctx.h3LqSmoothingAlpha, 0.5),
    },
    category_meta: cloneArray(ctx.h3CategoryMeta),
    counts: {
      grid_count: toNumber(summary.grid_count || ctx.h3GridCount, 0),
      poi_count: toNumber(summary.poi_count, 0),
      gi_valid_count: toNumber(summary.gi_z_stats && summary.gi_z_stats.count, 0),
      lisa_valid_count: toNumber(summary.lisa_i_stats && summary.lisa_i_stats.count, 0),
      cell_count: allCells.length,
      included_cell_count: cells.length,
    },
    metrics: {
      avg_density_poi_per_km2: toNumber(summary.avg_density_poi_per_km2, 0),
      avg_local_entropy: toNumber(summary.avg_local_entropy, 0),
      global_moran_i_density: toNumber(summary.global_moran_i_density, 0),
      global_moran_z_score: toNumber(summary.global_moran_z_score, 0),
    },
    omitted: {
      cells_total: allCells.length,
      cells_included: cells.length,
      geometry_removed: true,
    },
    notes: [
      'H3 evidence is retained for POI density, clustering, entropy, Gi/LISA and hotspot analysis.',
      'H3 evidence must not be treated as shared-grid coupling evidence unless population and nightlight are also computed on H3.',
    ],
  }
}

function buildAgentPopulationGridEvidence(ctx = {}) {
  const sortedTop = (rows, key, limit = 8, abs = false) => cloneArray(rows)
    .filter((row) => asText(row && row.cell_id))
    .sort((a, b) => {
      const left = toNumber(a && a[key], 0)
      const right = toNumber(b && b[key], 0)
      return (abs ? Math.abs(right) - Math.abs(left) : right - left)
    })
    .slice(0, limit)

  const baseCells = cloneArray((ctx.populationLayer && ctx.populationLayer.cells) || [])
    .map((cell) => ({
      cell_id: asText(cell && cell.cell_id),
      population_value: toNumber(cell && (cell.display_value ?? cell.value ?? cell.raw_value), 0),
      raw_value: toNumber(cell && cell.raw_value, 0),
    }))
    .filter((cell) => cell.cell_id)

  const sources = ctx.populationSexSourceLayers && typeof ctx.populationSexSourceLayers === 'object'
    ? ctx.populationSexSourceLayers
    : {}
  const maleCells = cloneArray((sources.male && sources.male.cells) || [])
  const femaleCells = cloneArray((sources.female && sources.female.cells) || [])
  const maleById = new Map(maleCells.map((cell) => [asText(cell && cell.cell_id), toNumber(cell && (cell.display_value ?? cell.value ?? cell.raw_value), 0)]))
  const femaleById = new Map(femaleCells.map((cell) => [asText(cell && cell.cell_id), toNumber(cell && (cell.display_value ?? cell.value ?? cell.raw_value), 0)]))
  const sexCellIds = Array.from(new Set([...maleById.keys(), ...femaleById.keys()])).filter(Boolean)
  const sexRows = sexCellIds.map((cellId) => {
    const maleValue = toNumber(maleById.get(cellId), 0)
    const femaleValue = toNumber(femaleById.get(cellId), 0)
    const total = maleValue + femaleValue
    return {
      cell_id: cellId,
      male_value: maleValue,
      female_value: femaleValue,
      sex_diff_value: Number((maleValue - femaleValue).toFixed(6)),
      male_ratio: total > 0 ? Number((maleValue / total).toFixed(6)) : 0,
      female_ratio: total > 0 ? Number((femaleValue / total).toFixed(6)) : 0,
    }
  })
  const sexById = new Map(sexRows.map((row) => [row.cell_id, row]))
  const cells = baseCells.map((cell) => ({
    ...cell,
    ...cloneObject(sexById.get(cell.cell_id) || {}),
  }))

  return {
    evidence_level: sexRows.length ? 'cell_id_population_and_sex' : (baseCells.length ? 'population_cells_only' : 'missing'),
    counts: {
      population_cells: baseCells.length,
      sex_cells: sexRows.length,
    },
    top_density_cells: sortedTop(baseCells, 'population_value'),
    low_density_cells: sortedTop(baseCells, 'population_value').reverse(),
    top_male_diff_cells: sortedTop(sexRows.filter((row) => row.sex_diff_value > 0), 'sex_diff_value'),
    top_female_diff_cells: sortedTop(sexRows.filter((row) => row.sex_diff_value < 0), 'sex_diff_value', 8, true),
    top_abs_sex_diff_cells: sortedTop(sexRows, 'sex_diff_value', 10, true),
    omitted: {
      cells_total: cells.length,
      cells_included: 0,
      raw_cells_removed: true,
    },
    notes: [
      'sex cell values are included only when male/female population source layers are already available in the frontend state',
      'cell-level sex differences are service-balance evidence, not evidence of gendered consumption preference',
    ],
  }
}

function buildAgentSharedGridEvidence(ctx = {}) {
  const limit = 10
  const topRows = (rows, valueKey, rowLimit = limit) => cloneArray(rows)
    .map((row) => ({ ...row, value: toNumber(row && row[valueKey], 0) }))
    .filter((row) => asText(row && row.cell_id) && row.value > 0)
    .sort((a, b) => b.value - a.value)
    .slice(0, rowLimit)
  const scoreLevel = (score) => {
    if (score >= 0.67) return 'high'
    if (score <= 0.33) return 'low'
    return 'medium'
  }
  const typeFor = (row) => {
    const pop = row.population_level
    const poi = row.poi_level
    const light = row.nightlight_level
    if (pop === 'high' && poi === 'high' && light === 'high') return 'high_pop_high_poi_high_light'
    if (pop === 'high' && poi === 'low') return 'high_pop_low_poi'
    if (pop === 'high' && light === 'low') return 'high_pop_low_light'
    if (poi === 'high' && light === 'low') return 'high_poi_low_light'
    if (light === 'high' && poi === 'low') return 'high_light_low_poi'
    if (pop === 'low' && poi === 'high' && light === 'high') return 'low_pop_high_poi_high_light'
    if (pop === 'low' && poi === 'low' && light === 'low') return 'low_all'
    return 'balanced_medium'
  }
  const populationGridEvidence = buildAgentPopulationGridEvidence(ctx)
  const populationCells = cloneArray((ctx.populationLayer && ctx.populationLayer.cells) || [])
    .map((cell) => ({
      cell_id: asText(cell && cell.cell_id),
      population_value: toNumber(cell && (cell.display_value ?? cell.value ?? cell.raw_value), 0),
    }))
    .filter((cell) => cell.cell_id)
  const populationSexRows = cloneArray(populationGridEvidence.top_abs_sex_diff_cells || [])
    .concat(cloneArray(populationGridEvidence.top_male_diff_cells || []))
    .concat(cloneArray(populationGridEvidence.top_female_diff_cells || []))
  const sexById = new Map(populationSexRows.map((row) => [asText(row && row.cell_id), row]))
  const poiCells = cloneArray((ctx.poiGridFeatures || []))
    .map((feature) => {
      const props = cloneObject(feature && feature.properties)
      return {
        cell_id: asText(props.cell_id),
        poi_count: toNumber(props.poi_count, 0),
        density_poi_per_km2: toNumber(props.density_poi_per_km2, 0),
        dominant_category: asText(props.dominant_category),
        dominant_category_name: asText(props.dominant_category_name),
      }
    })
  const nightlightCells = cloneArray((ctx.nightlightLayer && ctx.nightlightLayer.cells) || [])
    .map((cell) => ({
      cell_id: asText(cell && cell.cell_id),
      radiance: toNumber(cell && (cell.display_value ?? cell.value ?? cell.raw_value), 0),
      class_key: asText(cell && cell.class_key),
      class_label: asText(cell && cell.class_label),
    }))

  const populationById = new Map(populationCells.map((cell) => [cell.cell_id, {
    ...cell,
    ...cloneObject(sexById.get(cell.cell_id) || {}),
  }]))
  const poiById = new Map(poiCells.map((cell) => [cell.cell_id, cell]))
  const nightlightById = new Map(nightlightCells.map((cell) => [cell.cell_id, cell]))
  const sharedIds = Array.from(new Set([
    ...populationCells.map((cell) => cell.cell_id),
    ...poiCells.map((cell) => cell.cell_id),
    ...nightlightCells.map((cell) => cell.cell_id),
  ])).filter(Boolean)

  const maxPopulation = Math.max(1, ...populationCells.map((cell) => toNumber(cell.population_value, 0)))
  const maxPoi = Math.max(1, ...poiCells.map((cell) => toNumber(cell.poi_count, 0)))
  const maxNightlight = Math.max(1, ...nightlightCells.map((cell) => toNumber(cell.radiance, 0)))
  const overlapRows = sharedIds.map((cellId) => {
    const pop = populationById.get(cellId) || {}
    const poi = poiById.get(cellId) || {}
    const night = nightlightById.get(cellId) || {}
    const populationScore = toNumber(pop.population_value, 0) / maxPopulation
    const poiScore = toNumber(poi.poi_count, 0) / maxPoi
    const nightlightScore = toNumber(night.radiance, 0) / maxNightlight
    const row = {
      cell_id: cellId,
      population_value: toNumber(pop.population_value, 0),
      male_value: toNumber(pop.male_value, 0),
      female_value: toNumber(pop.female_value, 0),
      sex_diff_value: toNumber(pop.sex_diff_value, 0),
      male_ratio: toNumber(pop.male_ratio, 0),
      female_ratio: toNumber(pop.female_ratio, 0),
      poi_count: toNumber(poi.poi_count, 0),
      density_poi_per_km2: toNumber(poi.density_poi_per_km2, 0),
      nightlight_radiance: toNumber(night.radiance, 0),
      nightlight_class: asText(night.class_label || night.class_key),
      dominant_category_name: asText(poi.dominant_category_name),
      population_level: scoreLevel(populationScore),
      poi_level: scoreLevel(poiScore),
      nightlight_level: scoreLevel(nightlightScore),
      composite_score: Number(((populationScore + poiScore + nightlightScore) / 3).toFixed(6)),
      has_population: populationById.has(cellId),
      has_poi: poiById.has(cellId),
      has_nightlight: nightlightById.has(cellId),
    }
    return {
      ...row,
      coupling_type: typeFor(row),
    }
  })
  const completeRows = overlapRows.filter((row) => row.has_population && row.has_poi && row.has_nightlight)
  const byPopulation = (rows) => cloneArray(rows).sort((a, b) => b.population_value - a.population_value).slice(0, limit)
  const byPoi = (rows) => cloneArray(rows).sort((a, b) => b.poi_count - a.poi_count).slice(0, limit)
  const byNightlight = (rows) => cloneArray(rows).sort((a, b) => b.nightlight_radiance - a.nightlight_radiance).slice(0, limit)
  const bySexDiff = (rows) => cloneArray(rows)
    .filter((row) => Math.abs(toNumber(row.sex_diff_value, 0)) > 0)
    .sort((a, b) => Math.abs(b.sex_diff_value) - Math.abs(a.sex_diff_value))
    .slice(0, limit)

  const topCoupledCells = cloneArray(completeRows)
    .filter((row) => row.coupling_type === 'high_pop_high_poi_high_light')
    .sort((a, b) => b.composite_score - a.composite_score)
    .slice(0, limit)
  return {
    evidence_version: 'shared_grid_evidence_v1',
    grid_type: 'population_nightlight_shared_cell_id',
    join_key: 'cell_id',
    uses: ['population', 'poi_raster', 'nightlight'],
    evidence_level: completeRows.length ? 'cell_id_overlap' : 'partial_or_missing',
    counts: {
      population_cells: populationCells.length,
      poi_cells: poiCells.length,
      nightlight_cells: nightlightCells.length,
      complete_overlap_cells: completeRows.length,
    },
    top_population_cells: topRows(populationCells, 'population_value'),
    top_poi_cells: topRows(poiCells, 'poi_count'),
    top_nightlight_cells: topRows(nightlightCells, 'radiance'),
    top_coupled_cells: topCoupledCells,
    high_pop_low_poi_cells: byPopulation(completeRows.filter((row) => row.coupling_type === 'high_pop_low_poi')),
    high_pop_or_poi_low_light_cells: byPopulation(completeRows.filter((row) => ['high_pop_low_light', 'high_poi_low_light'].includes(row.coupling_type))),
    low_pop_high_poi_high_light_cells: byPoi(completeRows.filter((row) => row.coupling_type === 'low_pop_high_poi_high_light')),
    high_light_low_poi_cells: byNightlight(completeRows.filter((row) => row.coupling_type === 'high_light_low_poi')),
    sex_balance_attention_cells: bySexDiff(completeRows),
    notes: [
      'population, poi and nightlight cells use the same cell_id only when complete_overlap_cells > 0',
      'values are display-level evidence for spatial coupling, not proof of real traffic or consumption',
    ],
  }
}

function buildAgentAnalysisSnapshot(ctx = {}) {
  const poiTotal = Array.isArray(ctx.allPoisDetails) ? ctx.allPoisDetails.length : 0
  const populationSummary = (ctx.populationOverview && ctx.populationOverview.summary) || {}
  const nightlightSummary = (ctx.nightlightOverview && ctx.nightlightOverview.summary) || {}
  const h3Summary = ctx.h3AnalysisSummary || {}
  const roadSummary = ctx.roadSyntaxSummary || {}
  const siteSelectionScope = typeof ctx.normalizeAgentSiteSelectionScope === 'function'
    ? ctx.normalizeAgentSiteSelectionScope()
    : { polygon: [], drawnPolygon: [], isochroneFeature: null }
  const frontendAnalysis = typeof ctx._buildFrontendAnalysisForExport === 'function'
    ? ctx._buildFrontendAnalysisForExport()
    : {}
  const paramBundles = buildAnalysisTaskParamBundles(ctx, ['poi_fetch', 'poi_raster_grid', 'poi_h3_grid', 'population', 'nightlight', 'road_syntax'])
  const poiH3Evidence = buildAgentPoiH3Evidence(ctx)
  return {
    context: {
      mode: ctx.transportMode || 'walking',
      time_min: Number(ctx.timeHorizon || 0) || 0,
      source: ctx.resultDataSource || ctx.poiDataSource || '',
      scope_source: ctx.scopeSource || '',
      history_id: asText(ctx.currentHistoryRecordId),
    },
    scope: {
      polygon: siteSelectionScope.polygon || [],
      drawn_polygon: siteSelectionScope.drawnPolygon || [],
      isochrone_feature: siteSelectionScope.isochroneFeature || null,
    },
    pois: [],
    poi_summary: {
      total: poiTotal,
      source: ctx.resultDataSource || ctx.poiDataSource || '',
    },
    h3: {
      summary: h3Summary,
      charts: ctx.h3AnalysisCharts || {},
      grid_count: Number(h3Summary.grid_count || ctx.h3GridCount || 0),
      grid_params: cloneObject(paramBundles.poi_h3_grid && paramBundles.poi_h3_grid.params),
      poi_h3_evidence: poiH3Evidence,
    },
    road: {
      summary: roadSummary,
      diagnostics: ctx.roadSyntaxDiagnostics || {},
    },
    population: {
      summary: populationSummary,
      grid_evidence: buildAgentPopulationGridEvidence(ctx),
    },
    nightlight: {
      summary: nightlightSummary,
    },
    param_bundles: paramBundles,
    shared_grid: buildAgentSharedGridEvidence(ctx),
    frontend_analysis: frontendAnalysis,
    active_panel: String(ctx.activeStep3Panel || ''),
    current_filters: {
      poi_source: ctx.poiDataSource || '',
      h3_resolution: Number(ctx.h3GridResolution || 0) || 0,
      h3_neighbor_ring: Number(ctx.h3NeighborRing || 0) || 0,
      road_metric: String(ctx.roadSyntaxMetric || ''),
      population_view: String(ctx.populationAnalysisView || ''),
      nightlight_view: String(ctx.nightlightAnalysisView || ''),
    },
  }
}

export {
  buildAgentAnalysisSnapshot,
  buildAgentPoiGridEvidence,
  buildAgentPoiH3Evidence,
  buildAgentPopulationGridEvidence,
  buildAgentSharedGridEvidence,
}
