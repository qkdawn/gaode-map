import {
  asText,
  cloneArray,
  cloneObject,
} from '../shared/normalizers.js'

const PPT_SOURCE_KIND_VALUES = new Set(['system', 'document', 'image', 'web', 'database', 'package'])

function canonicalPptSourceKind(rawKind = '', sourceId = '', fallback = '') {
  const kind = asText(rawKind)
  const id = asText(sourceId)
  if (PPT_SOURCE_KIND_VALUES.has(kind)) return kind
  if (id.startsWith('current:')) return 'system'
  if (id.includes(':')) {
    const prefix = id.split(':')[0]
    return PPT_SOURCE_KIND_VALUES.has(prefix) ? prefix : 'unknown'
  }
  const fallbackKind = asText(fallback)
  return PPT_SOURCE_KIND_VALUES.has(fallbackKind) ? fallbackKind : 'unknown'
}

export {
  asText,
  canonicalPptSourceKind,
  cloneArray,
  cloneObject,
}
