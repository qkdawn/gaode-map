import { asText, cloneArray, cloneObject } from './normalizers.js'

export const CONTEXT_ASK_URL = '/api/v1/analysis/agent/context-ask'

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
