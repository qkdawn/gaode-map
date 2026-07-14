import { asText, cloneArray, cloneObject } from '../shared/normalizers.js'

const SOURCE_KIND_VALUES = new Set(['system', 'document', 'image', 'web', 'database', 'package'])
const EVIDENCE_KIND_BY_SOURCE = {
  system: 'dataset_record',
  document: 'document_excerpt',
  image: 'image_observation',
  web: 'web_excerpt',
  database: 'database_record',
  package: 'package_item',
}
const EVIDENCE_KIND_BY_METHOD = {
  package_summary: 'package_summary',
  package_carrier: 'spatial_carrier',
  package_poi_sample: 'package_item',
  pageindex_node: 'document_excerpt',
  derived_metric: 'spatial_metric',
  spatial_metric: 'spatial_metric',
  dataset_record: 'dataset_record',
  analysis_summary: 'analysis_summary',
  document_excerpt: 'document_excerpt',
  image_observation: 'image_observation',
  web_excerpt: 'web_excerpt',
  database_record: 'database_record',
  package_item: 'package_item',
  spatial_carrier: 'spatial_carrier',
}

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
  return cloneArray(payload.evidence_nodes)
    .map((item) => {
      const node = cloneObject(item)
      const nodeSourceIds = cloneArray(node.source_ids).map(asText).filter(Boolean)
      const content = asText(node.content)
      const data = cloneObject(node.data)
      if (!asText(node.id) || !asText(node.kind) || !nodeSourceIds.length || (!content && !Object.keys(data).length)) return null
      return {
        id: asText(node.id),
        kind: asText(node.kind),
        run_id: asText(node.run_id),
        source_ids: nodeSourceIds,
        metric_ids: cloneArray(node.metric_ids).map(asText).filter(Boolean),
        title: asText(node.title),
        content,
        summary: asText(node.summary).slice(0, 260),
        data,
        time_scope: cloneObject(node.time_scope),
        spatial_scope: cloneObject(node.spatial_scope),
        method: asText(node.method),
        quality_flags: cloneArray(node.quality_flags).map(cloneObject),
        locator: typeof node.locator === 'object' ? cloneObject(node.locator) : asText(node.locator),
        citation: asText(node.citation),
      }
    })
    .filter(Boolean)
}

export function evidenceNodesFromEvidenceItems(aiPayload = {}, items = []) {
  const payload = cloneObject(aiPayload)
  const sourceId = asText(payload.source_id)
  const sourceKind = canonicalAnalysisSourceKind(payload.source_kind, sourceId, 'unknown')
  return cloneArray(items)
    .map((item, index) => {
      const evidence = item && typeof item === 'object' ? cloneObject(item) : { text: asText(item) }
      const metadata = cloneObject(evidence.payload)
      const nodeId = asText(metadata.evidence_node_id || metadata.node_id || evidence.evidence_node_id)
        || `${sourceId}:evidence:${index + 1}`
      const nodeSourceId = asText(evidence.source_id || sourceId)
      const content = asText(evidence.text || evidence.content || evidence.summary)
      const title = asText(evidence.title) || asText(payload.title) || '证据'
      if (!nodeSourceId || (!content && !title)) return null
      return {
        id: nodeId,
        kind: asText(metadata.kind) || EVIDENCE_KIND_BY_METHOD[asText(evidence.type)] || EVIDENCE_KIND_BY_SOURCE[sourceKind] || 'dataset_record',
        run_id: asText(metadata.run_id),
        source_ids: [nodeSourceId],
        metric_ids: cloneArray(metadata.metric_ids).map(asText).filter(Boolean),
        title,
        content,
        summary: asText(evidence.summary || content).slice(0, 260),
        data: metadata,
        time_scope: cloneObject(metadata.time_scope),
        spatial_scope: cloneObject(metadata.spatial_scope),
        method: asText(metadata.method || evidence.type),
        quality_flags: cloneArray(metadata.quality_flags).map(cloneObject),
        locator: asText(metadata.locator || evidence.locator),
        citation: asText(evidence.citation),
      }
    })
    .filter(Boolean)
}
