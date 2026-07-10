import { asText, cloneArray, cloneObject, consumeSseStream } from './normalizers.js'

export const CONTEXT_ASK_URL = '/api/v1/analysis/agent/context-ask'
export const CONTEXT_ASK_STREAM_URL = `${CONTEXT_ASK_URL}/stream`

export function serializeContextAskTarget(target = {}) {
  const source = target && typeof target === 'object' ? target : {}
  return {
    type: asText(source.type) || 'report_section',
    id: asText(source.id),
    title: asText(source.title),
    source: asText(source.source) || 'report',
    summary: asText(source.summary),
    evidence: cloneArray(source.evidence),
    artifact_refs: cloneArray(source.artifact_refs).map((item) => asText(item)).filter(Boolean),
    payload: cloneObject(source.payload),
  }
}

export async function postContextAsk(request = {}, options = {}) {
  const response = await fetch(CONTEXT_ASK_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal: options.signal,
    body: JSON.stringify(request),
  })
  let data = {}
  try {
    data = await response.json()
  } catch (_) {
    data = {}
  }
  if (!response.ok || asText(data.status) === 'failed') {
    throw new Error(asText(data.error || data.detail) || `context_ask_failed_${response.status}`)
  }
  return {
    answer: asText(data.answer),
    evidence: cloneArray(data.evidence),
    citations: cloneArray(data.citations),
    warnings: cloneArray(data.warnings),
  }
}


export async function postContextAskStream(request = {}, options = {}) {
  const response = await fetch(CONTEXT_ASK_STREAM_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    signal: options.signal,
    body: JSON.stringify(request),
  })
  if (!response.ok) {
    let data = {}
    try { data = await response.json() } catch (_) {}
    throw new Error(asText(data.error || data.detail) || `context_ask_failed_${response.status}`)
  }
  let completed = null
  let streamError = ''
  await consumeSseStream(response, ({ type, payload }) => {
    if (type === 'answer_delta') {
      const delta = asText(payload && payload.delta)
      if (delta && typeof options.onDelta === 'function') options.onDelta(delta)
      return
    }
    if (type === 'complete') {
      completed = {
        answer: asText(payload && payload.answer),
        evidence: cloneArray(payload && payload.evidence),
        citations: cloneArray(payload && payload.citations),
        warnings: cloneArray(payload && payload.warnings),
      }
      return
    }
    if (type === 'error') {
      streamError = asText(payload && (payload.message || payload.error)) || 'ai_call_failed'
    }
  })
  if (streamError) throw new Error(streamError)
  if (!completed || !completed.answer) throw new Error('ai_invalid_response')
  return completed
}
