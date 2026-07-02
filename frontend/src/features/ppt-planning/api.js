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
  const timeoutMs = Number(options.timeoutMs || options.timeout_ms || 0) || 0
  const emitDebug = (name = '', details = {}) => {
    if (!onDebugEvent) return
    try {
      onDebugEvent(name, { url, ...details })
    } catch (_) {
      // Debug hooks must never affect product behavior.
    }
  }
  let response
  const controller = timeoutMs > 0 && typeof AbortController !== 'undefined' ? new AbortController() : null
  let timeoutId = null
  if (controller) {
    timeoutId = globalThis.setTimeout(() => {
      try {
        controller.abort()
      } catch (_) {
        // Abort errors are normalized below.
      }
    }, timeoutMs)
  }
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: controller ? controller.signal : undefined,
    })
    emitDebug('fetch_response_headers_received', {
      ok: !!(response && response.ok),
      status: response && response.status,
    })
  } catch (error) {
    if (timeoutId) globalThis.clearTimeout(timeoutId)
    emitDebug('fetch_rejected_before_response', {
      name: error && error.name,
      message: error && error.message,
      timeoutMs,
    })
    const timedOut = controller && error && error.name === 'AbortError'
    const networkError = new Error(timedOut ? 'ppt_slide_request_timeout' : (error && error.message ? error.message : 'ppt_planning_network_error'))
    networkError.kind = timedOut ? 'timeout' : 'network_error'
    networkError.code = timedOut ? 'ppt_slide_request_timeout' : 'ppt_planning_network_error'
    networkError.url = url
    networkError.timeoutMs = timeoutMs
    networkError.cause = error
    throw networkError
  } finally {
    if (timeoutId) globalThis.clearTimeout(timeoutId)
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
    const message = typeof detail === 'string'
      ? detail
      : (detail && typeof detail === 'object'
          ? (detail.code || detail.reason || `ppt_planning_request_failed:${response.status}`)
          : `ppt_planning_request_failed:${response.status}`)
    const httpError = new Error(message || `ppt_planning_request_failed:${response.status}`)
    httpError.kind = 'http_error'
    httpError.code = 'ppt_planning_request_failed'
    httpError.status = response.status
    httpError.url = url
    httpError.responseText = text
    httpError.detail = detail
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
    emitDebug('fetch_json_parsed', { status: response.status })
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

export function createDeckBriefJob(payload = {}) {
  return postJsonWithTimeout('/api/v1/analysis/ppt/deck-brief/jobs', payload)
}

export function getDeckBriefJob(jobId = '') {
  return getJson(`/api/v1/analysis/ppt/deck-brief/jobs/${encodeURIComponent(jobId)}`)
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

export function regenerateDeckBriefSlide(payload = {}, options = {}) {
  return postJsonWithTimeout('/api/v1/analysis/ppt/deck-brief/slide', payload, options)
}

export function generatePptVisualArtifacts(payload = {}) {
  return postJson('/api/v1/analysis/ppt/visual-artifacts', payload)
}

export function cleanupPptVisualArtifacts(filenames = []) {
  return postJson('/api/v1/analysis/ppt/visual-artifacts/cleanup', { filenames })
}

export function listPptDataSources(areaId = '', options = {}) {
  return getJson('/api/v1/analysis/ppt/data/sources', {
    area_id: areaId,
    conversation_id: options.conversationId || options.conversation_id || '',
  })
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

export function createPptDatabasePackage(payload = {}) {
  return postJson('/api/v1/analysis/ppt/data/database-package', payload)
}

export function deletePptDataSource(areaId = '', sourceId = '') {
  const query = new URLSearchParams()
  query.set('area_id', String(areaId || ''))
  query.set('source_id', String(sourceId || ''))
  return deleteJson(`/api/v1/analysis/ppt/data/sources?${query.toString()}`)
}

export function getPptWebSourceLocationDefault(payload = {}) {
  return postJson('/api/v1/analysis/ppt/web-sources/location-default', payload)
}

export function previewPptWebSource(payload = {}) {
  return postJson('/api/v1/analysis/ppt/web-sources/preview', payload)
}

export function commitPptWebSource(payload = {}) {
  return postJson('/api/v1/analysis/ppt/web-sources/commit', payload)
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

export async function uploadImageSource(file, conversationId = '', historyId = '') {
  const form = new FormData()
  form.append('conversation_id', String(conversationId || ''))
  form.append('history_id', String(historyId || ''))
  form.append('file', file)
  const response = await fetch('/api/v1/analysis/ppt/image-sources', {
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
    throw new Error(detail || `image_upload_failed:${response.status}`)
  }
  return response.json()
}

export function scheduleDocumentParse(documentId = '') {
  return postJson(`/documents/${encodeURIComponent(String(documentId || ''))}/parse`, {})
}

export function deleteDocumentSource(documentId = '') {
  return deleteJson(`/documents/${encodeURIComponent(String(documentId || ''))}`)
}

export function deleteImageSource(attachmentId = '', conversationId = '') {
  const query = new URLSearchParams()
  query.set('conversation_id', String(conversationId || ''))
  return deleteJson(`/api/v1/analysis/ppt/image-sources/${encodeURIComponent(String(attachmentId || ''))}?${query.toString()}`)
}

export function retryImageSourceIngest(attachmentId = '', conversationId = '') {
  const query = new URLSearchParams()
  query.set('conversation_id', String(conversationId || ''))
  return postJson(`/api/v1/analysis/ppt/image-sources/${encodeURIComponent(String(attachmentId || ''))}/ingest?${query.toString()}`, {})
}

export function getJobStatus(jobId = '') {
  return getJson(`/jobs/${encodeURIComponent(String(jobId || ''))}`)
}
