import { cloneArray, cloneObject, consumeSseStream } from './normalizers.js'
import { buildAnalysisQuickAskSelectedSourcesContext } from './analysis-quick-request.js'

export const CONVERSATION_TURN_STREAM_URL = '/api/v1/analysis/agent/conversations/turns/stream'

export function buildConversationMapContext(ctx = {}) {
  const snapshot = typeof ctx.buildAgentAnalysisSnapshot === 'function'
    ? ctx.buildAgentAnalysisSnapshot()
    : {}
  return {
    active_panel: String(snapshot.active_panel || ''),
    scope: cloneObject(snapshot.scope),
    current_filters: cloneObject(snapshot.current_filters),
    map_view: typeof ctx.getAgentMapViewState === 'function'
      ? cloneObject(ctx.getAgentMapViewState())
      : {},
    selected_sources: cloneArray(buildAnalysisQuickAskSelectedSourcesContext(ctx).sources),
  }
}

export function buildConversationTurnRequest(ctx = {}, turnContext = {}, options = {}) {
  return {
    conversation_id: String(turnContext.targetSessionId || '').trim(),
    history_id: String(turnContext.historyId || '').trim(),
    message: String(turnContext.rawQuestion || turnContext.question || '').trim(),
    panel_kind: String(turnContext.panelKind || 'analysis').trim(),
    map_context: {
      ...buildConversationMapContext(ctx),
      target_capability_id: String(options.targetCapabilityId || '').trim(),
      capability_input_selections: cloneArray(options.capabilityInputSelections),
      ...cloneObject(options.mapContext),
    },
  }
}

export async function postConversationTurnStream(ctx = {}, turnContext = {}, options = {}) {
  const response = await fetch(CONVERSATION_TURN_STREAM_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    signal: turnContext.requestAbortController ? turnContext.requestAbortController.signal : options.signal,
    body: JSON.stringify(buildConversationTurnRequest(ctx, turnContext, options)),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(String(error.detail || `${CONVERSATION_TURN_STREAM_URL} 请求失败(${response.status})`))
  }
  return response
}

export async function collectConversationTurn(request = {}, options = {}) {
  const response = await fetch(CONVERSATION_TURN_STREAM_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    signal: options.signal,
    body: JSON.stringify(request),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(String(error.detail || `conversation_turn_failed_${response.status}`))
  }
  let answer = ''
  let error = ''
  await consumeSseStream(response, ({ type, payload }) => {
    if (type === 'message_delta') {
      const delta = String((payload && payload.delta) || '')
      answer += delta
      if (delta && typeof options.onDelta === 'function') options.onDelta(delta)
    } else if (type === 'item_completed' && payload && payload.type === 'agentMessage') {
      answer = String(payload.text || answer)
    } else if (type === 'error') {
      error = String((payload && payload.message) || 'conversation_turn_failed')
    } else if (type === 'turn_completed' && payload && payload.status !== 'completed') {
      error = String(payload.error || `conversation_turn_${payload.status || 'failed'}`)
    }
  })
  if (error) throw new Error(error)
  if (!answer.trim()) throw new Error('conversation_empty_response')
  return { answer }
}
