import { cloneArray } from './normalizers.js'
import { buildAnalysisSourceTarget } from '../analysis-sources/target.js'

export function buildAnalysisQuickAskTarget(ctx = {}) {
  const state = typeof ctx.getAgentAnalysisSourceState === 'function'
    ? ctx.getAgentAnalysisSourceState()
    : {}
  return buildAnalysisSourceTarget(state)
}

export function buildAnalysisQuickAskSelectedSourcesContext(ctx = {}) {
  const target = buildAnalysisQuickAskTarget(ctx)
  return { sources: cloneArray((target.payload || {}).sources) }
}
