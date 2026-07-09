import { asText, cloneArray } from './normalizers.js'
import { serializeContextAskTarget } from './context-ask-request.js'
import { buildAnalysisSourceTarget } from '../analysis-sources/target.js'

export function buildAnalysisQuickAskTarget(ctx = {}) {
  const state = typeof ctx.getAgentAnalysisSourceState === 'function'
    ? ctx.getAgentAnalysisSourceState()
    : {}
  return buildAnalysisSourceTarget(state)
}

export function buildAnalysisQuickAskRequest(ctx = {}, question = '') {
  const target = buildAnalysisQuickAskTarget(ctx)
  if (!cloneArray(target.payload && target.payload.sources).length) return null
  return {
    conversation_id: ctx.getActiveAgentSessionId ? ctx.getActiveAgentSessionId() : asText(ctx.activeAgentSessionId),
    history_id: asText(ctx.getCurrentAgentHistoryId && ctx.getCurrentAgentHistoryId()),
    question: asText(question),
    analysis_snapshot: ctx.buildAgentAnalysisSnapshot ? ctx.buildAgentAnalysisSnapshot() : {},
    target: serializeContextAskTarget(target),
    require_ai: true,
  }
}

export function buildAnalysisQuickAskSelectedSourcesContext(ctx = {}) {
  const target = buildAnalysisQuickAskTarget(ctx)
  return { sources: cloneArray((target.payload || {}).sources) }
}
