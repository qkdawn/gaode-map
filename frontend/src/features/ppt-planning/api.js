async function postJson(url, payload = {}) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(detail || `ppt_planning_request_failed:${response.status}`)
  }
  return response.json()
}

export function generatePptSpec(payload = {}) {
  return postJson('/api/v1/analysis/ppt/spec', payload)
}

export function generateDeckBrief(payload = {}) {
  return postJson('/api/v1/analysis/ppt/deck-brief', payload)
}
