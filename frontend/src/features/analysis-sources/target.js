import { asText, cloneArray, cloneObject } from '../shared/normalizers.js'
import { evidenceNodesFromAiPayload } from './evidence-nodes.js'

export const ANALYSIS_SOURCES_TARGET_TYPE = 'analysis_sources'

function compactAnalysisSourceValue(value, depth = 2) {
  if (depth <= 0) {
    if (Array.isArray(value)) return value.length ? `array(${value.length})` : []
    if (value && typeof value === 'object') return `object(${Object.keys(value).length})`
    return typeof value === 'string' ? value.slice(0, 500) : value
  }
  if (Array.isArray(value)) {
    return value.slice(0, 8).map((item) => compactAnalysisSourceValue(item, depth - 1))
  }
  if (value && typeof value === 'object') {
    return Object.entries(value).slice(0, 16).reduce((result, [key, item]) => {
      if (item === undefined || item === null || item === '') return result
      result[key] = compactAnalysisSourceValue(item, depth - 1)
      return result
    }, {})
  }
  return typeof value === 'string' ? value.slice(0, 800) : value
}

function analysisAiPayloadFromSource(source = {}) {
  const meta = cloneObject(source && source.meta)
  const payload = cloneObject(meta.aiPayload || meta.ai_payload)
  const included = cloneArray(payload.included).map((item) => asText(item)).filter(Boolean)
  if (!included.length) return null
  const sourceKind = asText(payload.source_kind || payload.sourceKind)
  const documentRole = asText(
    payload.document_role
      || payload.documentRole
      || (meta.document && meta.document.document_role)
      || meta.document_role,
  )
  if (sourceKind === 'document' || asText(source.id).startsWith('document:')) {
    return {
      source_id: asText(payload.source_id || source.id),
      title: asText(payload.title || source.title),
      source_kind: 'document',
      document_role: documentRole,
      included: ['document_identity'],
      counts: {
        evidence: Number((payload.counts || {}).evidence || meta.count || 0) || 0,
      },
      policy: '前端只传文档身份与角色；后端按角色读取带页码定位的完整解析正文。',
    }
  }
  const evidenceNodes = evidenceNodesFromAiPayload(payload).slice(0, 8)
  const metrics = cloneArray(payload.metrics).slice(0, 12)
  const metricGaps = cloneArray(payload.metric_gaps).slice(0, 8)
  const visualSpecs = cloneArray(payload.visual_specs).slice(0, 8)
  const scope = compactAnalysisSourceValue(payload.scope, 2)
  return {
    source_id: asText(payload.source_id || source.id),
    title: asText(payload.title || source.title),
    source_kind: sourceKind,
    included,
    scope,
    metrics: compactAnalysisSourceValue(metrics, 2),
    metric_gaps: compactAnalysisSourceValue(metricGaps, 2),
    evidence_nodes: compactAnalysisSourceValue(evidenceNodes, 2),
    visual_specs: compactAnalysisSourceValue(visualSpecs, 2),
    counts: {
      scope: scope && typeof scope === 'object' && Object.keys(scope).length ? 1 : 0,
      metrics: metrics.length,
      metric_gaps: metricGaps.length,
      evidence: evidenceNodes.length,
      visual_specs: visualSpecs.length,
    },
    policy: asText(payload.policy),
  }
}

function buildAnalysisSourceEvidence(source = {}, payload = {}) {
  const evidenceNodes = cloneArray(payload.evidence_nodes)
    .map((item) => (item && typeof item === 'object' ? cloneObject(item) : null))
    .filter((item) => item && asText(item.title || item.content || item.summary))
  const metricCount = cloneArray(payload.metrics).length || Number((payload.counts || {}).metrics || 0) || 0
  const scopeCount = payload.scope && typeof payload.scope === 'object' && Object.keys(payload.scope).length ? 1 : 0
  const visualCount = cloneArray(payload.visual_specs).length || Number((payload.counts || {}).visual_specs || 0) || 0
  const parts = []
  if (scopeCount) parts.push('范围摘要')
  if (metricCount) parts.push(`${metricCount} 个指标`)
  if (evidenceNodes.length) parts.push(`${evidenceNodes.length} 条证据`)
  if (visualCount) parts.push(`${visualCount} 个图表规格`)
  return {
    source_id: asText(payload.source_id || source.id),
    title: asText(payload.title || source.title),
    source_title: asText(source.title),
    type: asText(source.type),
    document_role: asText(payload.document_role),
    text: asText(payload.source_kind) === 'document'
      ? `项目文档身份已传递（角色：${asText(payload.document_role) || '未标注'}），核心证据由后端档案模块读取。`
      : (parts.length ? parts.join('；') : '该来源包含可用于 AI 的分析输入块。'),
    payload: {
      included: cloneArray(payload.included),
      counts: cloneObject(payload.counts),
    },
  }
}

function getDeliverableAnalysisSources(state = {}) {
  return cloneArray(state && state.sources)
    .filter((source) => source && source.selected && asText(source.status) === 'ready')
    .map((source) => {
      const aiPayload = analysisAiPayloadFromSource(source)
      return aiPayload ? { source, aiPayload } : null
    })
    .filter(Boolean)
}

export function buildAnalysisSourceTarget(state = {}) {
  const deliverable = getDeliverableAnalysisSources(state)
  const sources = deliverable.map((item) => item.aiPayload)
  const evidence = deliverable.map((item) => buildAnalysisSourceEvidence(item.source, item.aiPayload))
  return {
    type: ANALYSIS_SOURCES_TARGET_TYPE,
    id: 'analysis-selected-sources',
    title: '已选分析来源',
    source: 'analysis',
    summary: sources.length ? `当前已选择 ${sources.length} 个可用于 AI 的分析来源。` : '',
    evidence,
    artifact_refs: sources.map((item) => asText(item.source_id)).filter(Boolean),
    payload: {
      sources,
    },
  }
}
