function asArray(items) {
  return Array.isArray(items) ? items : []
}

function formatNumberWithUnit(value, unit = '', fallback = '') {
  if (value === undefined || value === null || value === '') return fallback
  const number = Number(value)
  const formatted = Number.isFinite(number)
    ? (Math.abs(number) >= 100
      ? number.toLocaleString('zh-CN', { maximumFractionDigits: 0 })
      : number.toLocaleString('zh-CN', { maximumFractionDigits: 3 }))
    : String(value)
  return `${formatted}${unit || ''}`
}

export function formatMetricClaimValue(claim = {}) {
  return formatNumberWithUnit(claim.value, claim.unit || '', claim.text || '')
}

export function visualData(visual = {}) {
  return visual.data && typeof visual.data === 'object' ? visual.data : {}
}

export function visualComposition(visual = {}) {
  return String(visualData(visual).composition || '')
}

export function visualMetricOverlays(visual = {}) {
  const overlays = visualData(visual).metric_overlays || visualData(visual).metricOverlays
  return asArray(overlays)
    .map((item) => (item && typeof item === 'object' ? item : {}))
    .filter((item) => item.label || item.metric_id || item.metricId)
}

export function formatVisualOverlayValue(item = {}) {
  return formatNumberWithUnit(item.value, item.unit || '', '—')
}

export function visualEvidenceSummary(visual = {}) {
  const metricIds = asArray(visual.source_metric_ids || visual.sourceMetricIds).filter(Boolean)
  const sourceIds = asArray(visual.source_ids || visual.sourceIds).filter(Boolean)
  if (metricIds.length) return `指标：${metricIds.slice(0, 3).join(' / ')}${metricIds.length > 3 ? ` 等 ${metricIds.length} 个` : ''}`
  if (sourceIds.length) return `来源：${sourceIds.slice(0, 3).join(' / ')}${sourceIds.length > 3 ? ` 等 ${sourceIds.length} 个` : ''}`
  return ''
}

export function visualReasonText(visual = {}) {
  const data = visualData(visual)
  return data.reason || visual.reason || ''
}

export function visualCaptureError(visual = {}) {
  const data = visualData(visual)
  const error = data.capture_error || data.captureError
  return error && typeof error === 'object' ? error : {}
}

export function visualExistingAssetMissingText(visual = {}) {
  const error = visualCaptureError(visual)
  if (error.message) {
    const code = error.code ? `（${error.code}）` : ''
    const detail = error.detail ? `：${error.detail}` : ''
    return `上次地图截图失败：${error.message}${code}${detail}`
  }
  return '需要复用现有空间图截图，当前未绑定资产。'
}

export function visualRowsPreview(visual = {}) {
  const data = visualData(visual)
  return Array.isArray(data.rows) ? data.rows.slice(0, 4) : []
}

export function visualColumnsPreview(visual = {}) {
  const data = visualData(visual)
  return Array.isArray(data.columns) ? data.columns.slice(0, 4) : []
}

export function visualColumnKey(column = {}) {
  if (column && typeof column === 'object') return column.key || column.field || column.label || ''
  return String(column || '')
}

export function visualColumnLabel(column = {}) {
  if (column && typeof column === 'object') return column.label || column.key || column.field || ''
  return String(column || '')
}

export function visualTypeLabel(visual = {}) {
  const labels = {
    figure: '数值图表',
    table: '指标表',
    metric_card: '指标卡',
    diagram: '语义图',
    matrix: '诊断矩阵',
    existing_asset: '已有空间图',
  }
  return labels[String(visual.visual_type || visual.visualType || '')] || '可视化'
}

export function visualNodeSummary(visual = {}) {
  return asArray(visual.nodes)
    .slice(0, 6)
    .map((node) => node && (node.title || node.label || node.name || node.id))
    .filter(Boolean)
}

export function visualGroupSummary(visual = {}) {
  return asArray(visual.groups)
    .slice(0, 4)
    .map((group) => group && (group.title || group.label || group.name || group.id))
    .filter(Boolean)
}

export function visualLinkSummary(visual = {}) {
  return asArray(visual.links).slice(0, 6).map((link) => {
    if (!link || typeof link !== 'object') return ''
    const source = link.source || link.from || ''
    const target = link.target || link.to || ''
    return source || target ? `${source} → ${target}`.trim() : ''
  }).filter(Boolean)
}
