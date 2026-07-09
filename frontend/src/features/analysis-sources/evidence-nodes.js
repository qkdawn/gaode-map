import { asText, cloneArray, cloneObject } from '../shared/normalizers.js'

const SOURCE_KIND_VALUES = new Set(['system', 'document', 'image', 'web', 'database', 'package'])

function canonicalAnalysisSourceKind(rawKind = '', sourceId = '', fallback = '') {
  const kind = asText(rawKind)
  const id = asText(sourceId)
  if (SOURCE_KIND_VALUES.has(kind)) return kind
  if (id.startsWith('current:')) return 'system'
  if (id.includes(':')) {
    const prefix = id.split(':')[0]
    return SOURCE_KIND_VALUES.has(prefix) ? prefix : 'unknown'
  }
  const fallbackKind = asText(fallback)
  return SOURCE_KIND_VALUES.has(fallbackKind) ? fallbackKind : 'unknown'
}

export function evidenceNodesFromAiPayload(aiPayload = {}) {
  const payload = cloneObject(aiPayload)
  const sourceId = asText(payload.source_id || payload.sourceId)
  const sourceKind = canonicalAnalysisSourceKind(payload.source_kind || payload.sourceKind, sourceId, 'unknown')
  return cloneArray(payload.evidence_nodes || payload.evidenceNodes)
    .map((item, index) => {
      const node = cloneObject(item)
      const nodeSourceId = asText(node.source_id || node.sourceId || sourceId)
      const nodeSourceType = canonicalAnalysisSourceKind(node.source_type || node.sourceType || sourceKind, nodeSourceId, sourceKind)
      const content = asText(node.content || node.text || node.summary)
      const title = asText(node.title) || asText(payload.title) || '证据'
      if (!nodeSourceId || (!content && !title)) return null
      const nodeId = asText(node.id || node.node_id || node.nodeId) || `${nodeSourceId}:evidence:${index + 1}`
      return {
        id: nodeId,
        source_id: nodeSourceId,
        source_type: nodeSourceType,
        title,
        content,
        summary: asText(node.summary || content).slice(0, 260),
        metadata: cloneObject(node.metadata || node.payload),
        locator: asText(node.locator),
        score: Number(node.score || 0) || 0,
        evidence_level: asText(node.evidence_level || node.evidenceLevel || 'source_evidence'),
        warnings: cloneArray(node.warnings).map((warning) => asText(warning)).filter(Boolean),
        citation: asText(node.citation),
      }
    })
    .filter(Boolean)
}

export function evidenceNodesFromEvidenceItems(aiPayload = {}, items = []) {
  const payload = cloneObject(aiPayload)
  const sourceId = asText(payload.source_id || payload.sourceId)
  const sourceKind = canonicalAnalysisSourceKind(payload.source_kind || payload.sourceKind, sourceId, 'unknown')
  return cloneArray(items)
    .map((item, index) => {
      const evidence = item && typeof item === 'object' ? cloneObject(item) : { text: asText(item) }
      const metadata = cloneObject(evidence.payload)
      const nodeId = asText(metadata.evidence_node_id || metadata.node_id || evidence.evidence_node_id)
        || `${sourceId}:evidence:${index + 1}`
      const nodeSourceId = asText(metadata.source_id || evidence.source_id || evidence.sourceId || sourceId)
      const nodeSourceType = canonicalAnalysisSourceKind(metadata.source_type || evidence.source_type || sourceKind, nodeSourceId, sourceKind)
      const content = asText(evidence.text || evidence.content || evidence.summary)
      const title = asText(evidence.title) || asText(payload.title) || '证据'
      if (!nodeSourceId || (!content && !title)) return null
      return {
        id: nodeId,
        source_id: nodeSourceId,
        source_type: nodeSourceType,
        title,
        content,
        summary: asText(evidence.summary || content).slice(0, 260),
        metadata,
        locator: asText(metadata.locator || evidence.locator),
        score: Number(evidence.score || 0) || 0,
        evidence_level: asText(metadata.evidence_level || evidence.type || evidence.evidence_level || 'source_evidence'),
        warnings: cloneArray(metadata.warnings || evidence.warnings).map((warning) => asText(warning)).filter(Boolean),
        citation: asText(evidence.citation),
      }
    })
    .filter(Boolean)
}
