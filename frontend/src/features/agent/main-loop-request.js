import { cloneArray } from './normalizers.js'
import { ANALYSIS_WORKSPACE_TAB_KIND } from './workspace-kinds.js'

export const MAIN_AGENT_LOOP_STREAM_URL = '/api/v1/analysis/agent/main-loop/stream'

export function shouldCaptureMainLoopVisualSnapshots(panelKind = '', options = {}) {
  return !(
    panelKind === ANALYSIS_WORKSPACE_TAB_KIND
    || options.visualSnapshots === false
    || options.includeVisualSnapshots === false
  )
}

export function buildMainLoopSelectedSourcesContext(ctx = {}, panelKind = '') {
  if (panelKind !== ANALYSIS_WORKSPACE_TAB_KIND || typeof ctx.buildAgentAnalysisSourceTarget !== 'function') {
    return {}
  }
  const target = ctx.buildAgentAnalysisSourceTarget()
  return { sources: cloneArray((target.payload || {}).sources) }
}

export async function buildMainLoopRequestBody(ctx = {}, turnContext = {}, options = {}) {
  const panelKind = turnContext.panelKind
  const visualSnapshots = shouldCaptureMainLoopVisualSnapshots(panelKind, options)
    ? await ctx.ensureAgentVisualSnapshotCache()
    : []
  return {
    conversation_id: turnContext.targetSessionId,
    history_id: turnContext.historyId,
    governance_mode: 'auto',
    messages: turnContext.requestMessages,
    analysis_snapshot: ctx.buildAgentAnalysisSnapshot(),
    map_search_context: typeof ctx.buildAgentMapSearchContext === 'function' ? ctx.buildAgentMapSearchContext() : {},
    selected_sources_context: buildMainLoopSelectedSourcesContext(ctx, panelKind),
    risk_confirmations: turnContext.requestRiskConfirmations,
    visual_snapshots: visualSnapshots,
  }
}

export async function postMainLoopStream(ctx = {}, turnContext = {}, options = {}) {
  const requestBody = await buildMainLoopRequestBody(ctx, turnContext, options)
  const res = await fetch(MAIN_AGENT_LOOP_STREAM_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal: turnContext.requestAbortController ? turnContext.requestAbortController.signal : undefined,
    body: JSON.stringify(requestBody),
  })
  if (!res.ok) {
    throw new Error(`${MAIN_AGENT_LOOP_STREAM_URL} 请求失败(${res.status})`)
  }
  return res
}
