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

async function postJsonWithTimeout(url, payload = {}, options = {}) {
  const onDebugEvent = typeof options.onDebugEvent === 'function' ? options.onDebugEvent : null
  const emitDebug = (name = '', details = {}) => {
    if (!onDebugEvent) return
    try {
      onDebugEvent(name, { url, ...details })
    } catch (_) {
      // Debug hooks must never affect product behavior.
    }
  }
  let response
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    emitDebug('fetch_response_headers_received', {
      ok: !!(response && response.ok),
      status: response && response.status,
    })
  } catch (error) {
    emitDebug('fetch_rejected_before_response', {
      name: error && error.name,
      message: error && error.message,
    })
    const networkError = new Error(error && error.message ? error.message : 'ppt_planning_network_error')
    networkError.kind = 'network_error'
    networkError.code = 'ppt_planning_network_error'
    networkError.url = url
    networkError.cause = error
    throw networkError
  }
  if (!response.ok) {
    emitDebug('fetch_http_error_body_read_start', { status: response.status })
    const text = await response.text().catch(() => '')
    emitDebug('fetch_http_error_body_read_done', { status: response.status, textLength: text.length })
    let detail = text
    let data = null
    try {
      data = JSON.parse(text)
      detail = data.detail || text
    } catch (_) {
      detail = text
    }
    const httpError = new Error(detail || `ppt_planning_request_failed:${response.status}`)
    httpError.kind = 'http_error'
    httpError.code = 'ppt_planning_request_failed'
    httpError.status = response.status
    httpError.url = url
    httpError.responseText = text
    httpError.data = data
    throw httpError
  }
  try {
    emitDebug('fetch_json_read_start', { status: response.status })
    const data = await response.json()
    emitDebug('fetch_json_read_done', {
      status: response.status,
      keys: Object.keys(data || {}).slice(0, 8),
    })
    emitDebug('api_returning_data', { status: response.status })
    return data
  } catch (error) {
    emitDebug('fetch_json_read_failed', {
      name: error && error.name,
      message: error && error.message,
    })
    const jsonError = new Error('ppt_planning_invalid_json')
    jsonError.kind = 'invalid_json'
    jsonError.code = 'ppt_planning_invalid_json'
    jsonError.url = url
    jsonError.cause = error
    throw jsonError
  }
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

async function deleteJson(url) {
  const response = await fetch(url, { method: 'DELETE' })
  if (!response.ok) {
    const text = await response.text().catch(() => '')
    let detail = text
    try {
      detail = JSON.parse(text).detail || text
    } catch (_) {
      detail = text
    }
    throw new Error(detail || `ppt_planning_delete_failed:${response.status}`)
  }
  return response.json()
}

export function generatePptSpec(payload = {}) {
  return postJsonWithTimeout('/api/v1/analysis/ppt/spec', payload)
}

export function regeneratePptSpecSection(payload = {}) {
  return postJson('/api/v1/analysis/ppt/spec/section', payload)
}

export function generateDeckBrief(payload = {}) {
  return postJsonWithTimeout('/api/v1/analysis/ppt/deck-brief', payload)
}

export function generateNarrativePlan(payload = {}) {
  return postJsonWithTimeout('/api/v1/analysis/ppt/narrative-plan', payload)
}

export function generatePptSpecWithDebug(payload = {}, options = {}) {
  return postJsonWithTimeout('/api/v1/analysis/ppt/spec', payload, options)
}

export function generateNarrativePlanWithDebug(payload = {}, options = {}) {
  return postJsonWithTimeout('/api/v1/analysis/ppt/narrative-plan', payload, options)
}

export function generateDeckBriefWithDebug(payload = {}, options = {}) {
  return postJsonWithTimeout('/api/v1/analysis/ppt/deck-brief', payload, options)
}

export function regenerateDeckBriefSlide(payload = {}) {
  return postJson('/api/v1/analysis/ppt/deck-brief/slide', payload)
}

export function generatePptVisualArtifacts(payload = {}) {
  return postJson('/api/v1/analysis/ppt/visual-artifacts', payload)
}

export function cleanupPptVisualArtifacts(filenames = []) {
  return postJson('/api/v1/analysis/ppt/visual-artifacts/cleanup', { filenames })
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

export async function uploadDocumentSource(file, title = '') {
  const form = new FormData()
  form.append('file', file)
  if (String(title || '').trim()) form.append('title', String(title || '').trim())
  const response = await fetch('/documents/upload', {
    method: 'POST',
    body: form,
  })
  if (!response.ok) {
    const text = await response.text().catch(() => '')
    let detail = text
    try {
      detail = JSON.parse(text).detail || text
    } catch (_) {
      detail = text
    }
    throw new Error(detail || `document_upload_failed:${response.status}`)
  }
  return response.json()
}

export function scheduleDocumentParse(documentId = '') {
  return postJson(`/documents/${encodeURIComponent(String(documentId || ''))}/parse`, {})
}

export function deleteDocumentSource(documentId = '') {
  return deleteJson(`/documents/${encodeURIComponent(String(documentId || ''))}`)
}

export function getJobStatus(jobId = '') {
  return getJson(`/jobs/${encodeURIComponent(String(jobId || ''))}`)
}
