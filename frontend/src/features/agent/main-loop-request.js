import { ANALYSIS_WORKSPACE_TAB_KIND } from './workspace-kinds.js'
import { buildAnalysisQuickAskSelectedSourcesContext } from './analysis-quick-request.js'

export const MAIN_AGENT_LOOP_STREAM_URL = '/api/v1/analysis/agent/main-loop/stream'

export function shouldCaptureMainLoopVisualSnapshots(panelKind = '', options = {}) {
  return !(
    panelKind === ANALYSIS_WORKSPACE_TAB_KIND
    || options.visualSnapshots === false
    || options.includeVisualSnapshots === false
  )
}

export function buildMainLoopSelectedSourcesContext(ctx = {}, panelKind = '') {
  if (panelKind !== ANALYSIS_WORKSPACE_TAB_KIND) {
    return {}
  }
  return buildAnalysisQuickAskSelectedSourcesContext(ctx)
}

export async function buildMainLoopRequestBody(ctx = {}, turnContext = {}, options = {}) {
  const panelKind = turnContext.panelKind
  const executionMode = turnContext.mode === 'deep' || options.mode === 'deep' ? 'deep' : 'auto'
  const visualSnapshots = shouldCaptureMainLoopVisualSnapshots(panelKind, options)
    ? await ctx.ensureAgentVisualSnapshotCache()
    : []
  return {
    conversation_id: turnContext.targetSessionId,
    history_id: turnContext.historyId,
    target_capability_id: String(options.targetCapabilityId || '').trim(),
    capability_input_selections: Array.isArray(options.capabilityInputSelections)
      ? options.capabilityInputSelections.map(item => ({ ...item }))
      : [],
    governance_mode: 'auto',
    execution_mode: executionMode,
    messages: turnContext.requestMessages,
    analysis_snapshot: ctx.buildAgentAnalysisSnapshot(),
    map_search_context: typeof ctx.buildAgentMapSearchContext === 'function' ? ctx.buildAgentMapSearchContext() : {},
    selected_sources_context: buildMainLoopSelectedSourcesContext(ctx, panelKind),
    risk_confirmations: turnContext.requestRiskConfirmations,
    visual_snapshots: visualSnapshots,
    execution_profile: turnContext.executionProfile || { model_profile_id: '', skill_id: '', skill_scope: 'turn' },
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
    const error = await res.json().catch(() => ({}))
    const detail = typeof error.detail === 'string' ? error.detail : ''
    throw new Error(detail || `${MAIN_AGENT_LOOP_STREAM_URL} 请求失败(${res.status})`)
  }
  return res
}
