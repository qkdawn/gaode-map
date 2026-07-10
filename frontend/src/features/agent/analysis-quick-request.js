import { asText, cloneArray, cloneObject } from './normalizers.js'
import { buildAnalysisSourceTarget } from '../analysis-sources/target.js'

export function buildAnalysisQuickAskTarget(ctx = {}) {
  const state = typeof ctx.getAgentAnalysisSourceState === 'function'
    ? ctx.getAgentAnalysisSourceState()
    : {}
  return buildAnalysisSourceTarget(state)
}

function buildAnalysisQuickAskSnapshot(ctx = {}) {
  const snapshot = ctx.buildAgentAnalysisSnapshot ? cloneObject(ctx.buildAgentAnalysisSnapshot()) : {}
  return {
    context: cloneObject(snapshot.context),
    scope: cloneObject(snapshot.scope),
    poi_summary: cloneObject(snapshot.poi_summary),
    h3: { summary: cloneObject(snapshot.h3 && snapshot.h3.summary) },
    road: { summary: cloneObject(snapshot.road && snapshot.road.summary) },
    population: { summary: cloneObject(snapshot.population && snapshot.population.summary) },
    nightlight: { summary: cloneObject(snapshot.nightlight && snapshot.nightlight.summary) },
    active_panel: asText(snapshot.active_panel),
    current_filters: cloneObject(snapshot.current_filters),
  }
}

export function buildAnalysisQuickAskRequest(ctx = {}, question = '') {
  const target = buildAnalysisQuickAskTarget(ctx)
  if (!cloneArray(target.payload && target.payload.sources).length) return null
  return {
    conversation_id: ctx.getActiveAgentSessionId ? ctx.getActiveAgentSessionId() : asText(ctx.activeAgentSessionId),
    history_id: asText(ctx.getCurrentAgentHistoryId && ctx.getCurrentAgentHistoryId()),
    question: asText(question),
    analysis_snapshot: buildAnalysisQuickAskSnapshot(ctx),
    target,
    require_ai: true,
  }
}

export function buildAnalysisQuickAskSelectedSourcesContext(ctx = {}) {
  const target = buildAnalysisQuickAskTarget(ctx)
  return { sources: cloneArray((target.payload || {}).sources) }
}
