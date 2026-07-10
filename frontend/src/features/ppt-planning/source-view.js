import { evidenceNodesFromAiPayload } from '../analysis-sources/evidence-nodes.js'
import { getPptSourceHealth } from './source-health.js'

function sourceMeta(source = {}) {
  if (!source || typeof source !== 'object') return {}
  return source.meta && typeof source.meta === 'object' ? source.meta : {}
}

function sourceAiPayload(source = {}) {
  const meta = sourceMeta(source)
  const payload = meta.aiPayload && typeof meta.aiPayload === 'object'
    ? meta.aiPayload
    : meta.ai_payload && typeof meta.ai_payload === 'object'
      ? meta.ai_payload
      : null
  return payload && typeof payload === 'object' ? payload : {}
}

function sourceKind(source = {}) {
  const kind = String((source && source.source_kind) || '').trim()
  if (kind) return kind
  const sourceId = String((source && source.id) || '')
  if (sourceId.startsWith('package-placeholder:')) return 'package-placeholder'
  if (sourceId.startsWith('package:')) return 'package'
  if (sourceId.startsWith('document:')) return 'document'
  if (sourceId.startsWith('image:')) return 'image'
  if (sourceId.startsWith('web:')) return 'web'
  if (sourceId.startsWith('database:')) return 'database'
  if (sourceId.startsWith('current:')) return 'system'
  return 'unknown'
}


export function documentRole(source = {}) {
  const meta = sourceMeta(source)
  const payload = sourceAiPayload(source)
  return String(
    payload.document_role
      || payload.documentRole
      || (meta.document && meta.document.document_role)
      || meta.document_role
      || '',
  ).trim()
}

export function documentRoleLabel(source = {}) {
  return {
    project_brief: '项目摘要',
    design_vision: '设计愿景',
    reference_document: '参考资料',
  }[documentRole(source)] || ''
}

export function isPackageSource(source = {}) {
  return sourceKind(source) === 'package'
}

export function isPackagePlaceholderSource(source = {}) {
  return sourceKind(source) === 'package-placeholder'
}

export function isDocumentSource(source = {}) {
  return sourceKind(source) === 'document'
}

export function isImageSource(source = {}) {
  return sourceKind(source) === 'image'
}

export function isWebSource(source = {}) {
  return sourceKind(source) === 'web'
}

export function isCurrentSource(source = {}) {
  return sourceKind(source) === 'system' && String(source.id || '').startsWith('current:')
}

export function isDatabaseSource(source = {}) {
  return sourceKind(source) === 'database'
}

export function isDeletableSource(source = {}) {
  return isDocumentSource(source) || isImageSource(source) || isPackageSource(source) || isWebSource(source) || isDatabaseSource(source)
}

export function sourceTransport(source = {}) {
  const meta = sourceMeta(source)
  const aiPayload = sourceAiPayload(source)
  if (aiPayload && aiPayload.version === 'ppt_ai_input_block_v1') {
    const evidenceNodes = evidenceNodesFromAiPayload(aiPayload)
    const evidenceCount = Number(aiPayload.evidence_count ?? aiPayload.evidenceCount ?? evidenceNodes.length ?? (aiPayload.counts || {}).evidence ?? 0) || 0
    return {
      source_id: aiPayload.source_id || source.id,
      sourceId: aiPayload.sourceId || source.id,
      title: aiPayload.title || source.title,
      source_kind: aiPayload.source_kind || sourceKind(source),
      sourceKind: aiPayload.source_kind || sourceKind(source),
      transport_status: (Array.isArray(aiPayload.included) && aiPayload.included.length) ? 'ready_to_send' : 'selected_no_payload',
      transportStatus: (Array.isArray(aiPayload.included) && aiPayload.included.length) ? 'ready_to_send' : 'selected_no_payload',
      included: Array.isArray(aiPayload.included) ? aiPayload.included : [],
      metric_count: Number((aiPayload.counts || {}).metrics || 0) || 0,
      metricCount: Number((aiPayload.counts || {}).metrics || 0) || 0,
      metric_gap_count: Number((aiPayload.counts || {}).metric_gaps || 0) || 0,
      metricGapCount: Number((aiPayload.counts || {}).metric_gaps || 0) || 0,
      evidence_count: evidenceCount,
      evidenceCount,
      scope_count: Number((aiPayload.counts || {}).scope || 0) || 0,
      scopeCount: Number((aiPayload.counts || {}).scope || 0) || 0,
      visual_spec_count: Number((aiPayload.counts || {}).visual_specs || 0) || 0,
      visualSpecCount: Number((aiPayload.counts || {}).visual_specs || 0) || 0,
      excluded: Array.isArray(aiPayload.excluded) ? aiPayload.excluded : [],
      policy: aiPayload.policy || '',
      preview: true,
    }
  }
  return meta.transport && typeof meta.transport === 'object' ? meta.transport : null
}

export function currentSourceEvidenceNodes(source = {}) {
  return evidenceNodesFromAiPayload(sourceAiPayload(source)).slice(0, 80)
}

export function currentSourceDetailTabs({
  readyMetrics = [],
  evidenceNodes = [],
  scopePayload = null,
  visualSpecs = [],
  gapMetrics = [],
} = {}) {
  return [
    { key: 'metrics', label: 'Metrics', count: Array.isArray(readyMetrics) ? readyMetrics.length : 0 },
    { key: 'evidence', label: 'EvidenceNode', count: Array.isArray(evidenceNodes) ? evidenceNodes.length : 0 },
    { key: 'scope', label: 'Scope', count: scopePayload && typeof scopePayload === 'object' ? 1 : 0 },
    { key: 'visuals', label: 'Visuals', count: Array.isArray(visualSpecs) ? visualSpecs.length : 0 },
    { key: 'gaps', label: 'Gaps', count: Array.isArray(gapMetrics) ? gapMetrics.length : 0 },
  ].map((item) => ({ ...item, available: item.count > 0 }))
}

export function sourceTransportLabel(source = {}) {
  const transport = sourceTransport(source)
  if (!transport) return ''
  const metricCount = Number(transport.metric_count ?? transport.metricCount ?? 0) || 0
  const evidenceCount = Number(transport.evidence_count ?? transport.evidenceCount ?? 0) || 0
  const scopeCount = Number(transport.scope_count ?? transport.scopeCount ?? 0) || 0
  const visualSpecCount = Number(transport.visual_spec_count ?? transport.visualSpecCount ?? 0) || 0
  const included = Array.isArray(transport.included) ? transport.included : []
  const status = String(transport.transport_status || transport.transportStatus || '')
  if (status === 'ready_to_send') {
    const parts = []
    if (scopeCount || included.includes('scope')) parts.push(`范围 ${scopeCount || 1}`)
    if (metricCount) parts.push(`metrics ${metricCount}`)
    if (evidenceCount) parts.push(`evidence ${evidenceCount}`)
    if (visualSpecCount) parts.push(`visuals ${visualSpecCount}`)
    return parts.length ? `已构建 ${parts.join(' / ')}` : '已构建可传内容'
  }
  if (status === 'included' || metricCount || evidenceCount || scopeCount || included.length) {
    const parts = []
    if (scopeCount || included.includes('scope')) parts.push(`范围 ${scopeCount || 1}`)
    if (metricCount) parts.push(`metrics ${metricCount}`)
    if (evidenceCount) parts.push(`evidence ${evidenceCount}`)
    if (visualSpecCount) parts.push(`visuals ${visualSpecCount}`)
    return parts.length ? `已传 ${parts.join(' / ')}` : '已传可用内容'
  }
  return '未传：无可用指标/证据'
}

export function sourceHealth(source = {}) {
  return getPptSourceHealth(source)
}

export function sourceHealthLabel(source = {}) {
  return sourceHealth(source).healthLabel || ''
}

export function sourceHealthReason(source = {}) {
  return sourceHealth(source).healthReason || ''
}

export function isRetryableSource(source = {}) {
  if (sourceMeta(source).uploadPlaceholder) return false
  return !!sourceHealth(source).retryable
    && (isDocumentSource(source) || isImageSource(source) || isWebSource(source))
}

export function sourceTransportExcludedItems(source = {}) {
  const transport = sourceTransport(source)
  return transport && Array.isArray(transport.excluded) ? transport.excluded : []
}

export function removeSourceMessage(source = {}) {
  if (isDocumentSource(source)) {
    return '确认彻底删除该文档来源？文档库里的原文件、解析结果和 PageIndex 索引都会删除。'
  }
  if (isImageSource(source)) {
    return '确认彻底删除该图片来源？图片文件、OCR 和视觉理解结果都会删除。'
  }
  if (isPackageSource(source)) {
    return '确认彻底删除该资料包？已持久化的资料包记录会从数据库删除，刷新后不会再出现。'
  }
  return '确认从当前 PPT 来源列表删除该来源？刷新来源后可重新加入。'
}

export function isGeneratingSource(source = {}) {
  return String(source.status || '') === 'generating'
}
