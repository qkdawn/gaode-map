function asText(value, fallback = '') {
  return String(value ?? fallback ?? '').trim()
}

function clampText(value, maxLength, fallback = '') {
  const text = asText(value, fallback)
  if (!maxLength || maxLength <= 0) return text
  return text.slice(0, maxLength)
}

function cloneArray(items) {
  return Array.isArray(items) ? items.map((item) => (item && typeof item === 'object' ? { ...item } : item)) : []
}

function cloneObject(value, fallback = {}) {
  return value && typeof value === 'object' && !Array.isArray(value) ? { ...value } : { ...fallback }
}

function cloneRecordMap(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  return Object.keys(value).reduce((result, key) => {
    const nextKey = asText(key)
    if (!nextKey) return result
    result[nextKey] = value[key]
    return result
  }, {})
}

export {
  asText,
  clampText,
  cloneArray,
  cloneObject,
  cloneRecordMap,
}
