async function postJson(url, payload = {}) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    const text = await response.text().catch(() => '')
    let detail = text
    try {
      detail = JSON.parse(text).detail || text
    } catch (_) {
      detail = text
    }
    throw new Error(detail || `ppt_planning_request_failed:${response.status}`)
  }
  return response.json()
}

async function getJson(url, params = {}) {
  const query = new URLSearchParams()
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim()) {
      query.set(key, String(value))
    }
  })
  const response = await fetch(`${url}${query.toString() ? `?${query.toString()}` : ''}`)
  if (!response.ok) {
    const text = await response.text().catch(() => '')
    let detail = text
    try {
      detail = JSON.parse(text).detail || text
    } catch (_) {
      detail = text
    }
    throw new Error(detail || `ppt_planning_request_failed:${response.status}`)
  }
  return response.json()
}

export function generatePptSpec(payload = {}) {
  return postJson('/api/v1/analysis/ppt/spec', payload)
}

export function regeneratePptSpecSection(payload = {}) {
  return postJson('/api/v1/analysis/ppt/spec/section', payload)
}

export function generateDeckBrief(payload = {}) {
  return postJson('/api/v1/analysis/ppt/deck-brief', payload)
}

export function regenerateDeckBriefSlide(payload = {}) {
  return postJson('/api/v1/analysis/ppt/deck-brief/slide', payload)
}

export function listPptDataSources(areaId = '') {
  return getJson('/api/v1/analysis/ppt/data/sources', { area_id: areaId })
}

export function readPptDataSourceSummary(areaId = '', sourceId = '') {
  return getJson('/api/v1/analysis/ppt/data/source-summary', { area_id: areaId, source_id: sourceId })
}

export function queryPptPoiPoints(payload = {}) {
  return postJson('/api/v1/analysis/ppt/data/query-poi-points', payload)
}

export function queryNearbyPptPoiPoints(payload = {}) {
  return postJson('/api/v1/analysis/ppt/data/nearby-pois', payload)
}

export function createPptDataPackage(payload = {}) {
  return postJson('/api/v1/analysis/ppt/data/packages', payload)
}

export function classifyPptSourceGroups(payload = {}) {
  return postJson('/api/v1/analysis/ppt/source-groups/classify', payload)
}
