import {
  asText,
  canonicalPptSourceKind,
  cloneObject,
} from './base.js'
import { normalizePptSource } from './model.js'

export function isPptSourceRefreshPlaceholder(source = {}) {
  const sourceId = asText(source.id)
  const sourceKind = asText(source.meta && source.meta.sourceKind)
  return sourceKind === 'source-refresh-placeholder' || sourceId.startsWith('source-refresh-placeholder:')
}

export function isRefreshableBackendPptSource(source = {}) {
  if (!source || isPptSourceRefreshPlaceholder(source)) return false
  const sourceId = asText(source.id)
  const explicitKind = asText(source.meta && source.meta.sourceKind)
  const sourceKind = canonicalPptSourceKind(source.source_kind || source.sourceKind || explicitKind, sourceId, source.type)
  return sourceKind !== 'system' && sourceKind !== 'unknown' && explicitKind !== 'package-placeholder'
}

export function sourceRefreshPlaceholderFromSource(source = {}, index = 0) {
  const normalized = normalizePptSource(source)
  const sourceId = asText(normalized.id)
  const meta = cloneObject(normalized.meta)
  const sourceKind = canonicalPptSourceKind(normalized.source_kind || normalized.sourceKind || meta.sourceKind, sourceId, normalized.type)
  const title = asText(normalized.title) || `来源 ${index + 1}`
  return normalizePptSource({
    ...normalized,
    id: sourceId ? `source-refresh-placeholder:${sourceId}` : `source-refresh-placeholder:${index + 1}`,
    type: normalized.type || 'data',
    title,
    status: 'generating',
    selected: false,
    meta: {
      ...meta,
      label: '同步中',
      sourceKind: 'source-refresh-placeholder',
      sourceRefreshingPlaceholder: true,
      expectedSourceId: sourceId,
      expectedSourceKind: sourceKind,
    },
  })
}

export function createAggregateSourceRefreshPlaceholder() {
  return normalizePptSource({
    id: 'source-refresh-placeholder:backend-sources',
    type: 'data',
    title: '后端来源',
    status: 'generating',
    selected: false,
    meta: {
      label: '同步中',
      sourceKind: 'source-refresh-placeholder',
      sourceRefreshingPlaceholder: true,
      expectedSourceKind: 'backend',
    },
  })
}
