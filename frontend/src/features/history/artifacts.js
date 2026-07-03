function cloneArtifactValue(value) {
  if (value === undefined || value === null) return Array.isArray(value) ? [] : {}
  try {
    return JSON.parse(JSON.stringify(value))
  } catch (_) {
    return Array.isArray(value) ? value.slice() : Object.assign({}, value)
  }
}

function buildFeatureCollectionArtifact({ features = [], scopeId = '', extra = {} } = {}) {
  const safeFeatures = Array.isArray(features) ? features : []
  const payload = {
    type: 'FeatureCollection',
    features: safeFeatures,
    count: safeFeatures.length,
    cell_count: safeFeatures.length,
    scope_id: scopeId ? String(scopeId) : '',
    ...cloneArtifactValue(extra && typeof extra === 'object' ? extra : {}),
  }
  if (!payload.scope_id) delete payload.scope_id
  return payload
}

function buildMetricLayerArtifact({ layer = {}, view = '', year = null } = {}) {
  const payload = cloneArtifactValue(layer && typeof layer === 'object' ? layer : {})
  if (view !== undefined && view !== null && String(view).trim()) {
    payload.view = String(view)
  }
  if (year !== undefined && year !== null && String(year).trim()) {
    payload.year = year
  }
  return payload
}

function buildAnalysisArtifactEnvelope({ params = {}, payload = {}, summary = {} } = {}) {
  return {
    params: cloneArtifactValue(params && typeof params === 'object' ? params : {}),
    payload: cloneArtifactValue(payload && typeof payload === 'object' ? payload : {}),
    summary: cloneArtifactValue(summary && typeof summary === 'object' ? summary : {}),
  }
}

function restoreFeatureCollection(value, required = true) {
  const source = value && typeof value === 'object' ? value : {}
  const features = Array.isArray(source.features) ? source.features : []
  if (required && !features.length) return null
  const restored = {
    ...cloneArtifactValue(source),
    type: String(source.type || 'FeatureCollection'),
    features,
    count: Number.isFinite(Number(source.count)) ? Number(source.count) : features.length,
    cell_count: Number.isFinite(Number(source.cell_count)) ? Number(source.cell_count) : features.length,
  }
  return restored
}

function restoreLayer(value, required = true) {
  const layer = value && typeof value === 'object' ? cloneArtifactValue(value) : {}
  if (required && !Array.isArray(layer.cells)) return null
  if (!Array.isArray(layer.cells)) layer.cells = []
  return layer
}

export {
  buildAnalysisArtifactEnvelope,
  buildFeatureCollectionArtifact,
  buildMetricLayerArtifact,
  cloneArtifactValue,
  restoreFeatureCollection,
  restoreLayer,
}
