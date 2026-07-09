export function formatPackageMetric(value) {
  if (value === undefined || value === null || value === '') return '-'
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(3).replace(/\.?0+$/, '')
  return String(value)
}

export function formatCurrentMetricValue(metric = {}) {
  if (metric.value === undefined || metric.value === null || metric.value === '') return '-'
  return `${formatPackageMetric(metric.value)}${metric.unit || ''}`
}

export function currentMetricSourceIds(metric = {}) {
  const sourceIds = metric.source_ids || metric.sourceIds
  return Array.isArray(sourceIds) ? sourceIds.filter(Boolean).join(' / ') : (metric.source_id || metric.sourceId || '')
}

export function currentGapTitle(gap = {}, index = 0) {
  return gap.label || gap.needed_metric || gap.neededMetric || gap.metric_id || gap.metricId || `缺口指标 ${index + 1}`
}

export function currentGapDescription(gap = {}) {
  return gap.description || gap.text || gap.reason || '当前没有可用计算结果。'
}

export function currentGapMeta(gap = {}) {
  return [
    gap.source_path || gap.sourcePath,
    gap.source_id || gap.sourceId,
    gap.metric_id || gap.metricId,
  ].filter(Boolean).join(' / ')
}

export function packageItemTitle(item = {}, index = 0) {
  return item.name || item.title || item.label || `点位 ${index + 1}`
}

export function packageItemSubtitle(item = {}) {
  return [item.category, item.subcategory || item.type].filter(Boolean).join(' / ') || '未分类'
}

export function packageItemRadiance(item = {}) {
  const nightlightCell = item.nightlight_cell && typeof item.nightlight_cell === 'object' ? item.nightlight_cell : {}
  return nightlightCell.class_label || nightlightCell.label || formatPackageMetric(nightlightCell.radiance)
}

export function carrierMetric(carrier = {}, group = '', key = '') {
  const payload = carrier[group] && typeof carrier[group] === 'object' ? carrier[group] : {}
  return formatPackageMetric(payload[key])
}

export function carrierPoiLabel(carrier = {}) {
  const metrics = carrier.poi_metrics && typeof carrier.poi_metrics === 'object' ? carrier.poi_metrics : {}
  const count = metrics.total_related_poi_count ?? 0
  const categories = Array.isArray(metrics.dominant_categories) ? metrics.dominant_categories.slice(0, 2) : []
  const label = categories.map((item) => item.category || item.name).filter(Boolean).join(' / ')
  return label ? `${count} 个 · ${label}` : `${count} 个`
}

export function carrierPopulationLabel(carrier = {}) {
  const metrics = carrier.population_metrics && typeof carrier.population_metrics === 'object' ? carrier.population_metrics : {}
  const strength = metrics.demand_strength || '-'
  if (metrics.total_population !== undefined && metrics.total_population !== null) {
    return `总人口 ${formatPackageMetric(metrics.total_population)} · ${strength}`
  }
  const label = metrics.view_label || '人口图层'
  const unit = metrics.unit ? ` ${metrics.unit}` : ''
  return `${label}均值 ${formatPackageMetric(metrics.mean_cell_value)}${unit} · ${strength}`
}

export function carrierTypeLabel(carrier = {}) {
  const type = String(carrier.carrier_type || carrier.type || '')
  if (type === 'block_loop') return '街区 / loop'
  if (type === 'corridor') return '廊道'
  return '路段'
}
