function asText(value, fallback = '') {
  const text = String(value ?? fallback ?? '').trim()
  return text
}

function clampText(value, maxLength, fallback = '') {
  const text = asText(value, fallback)
  if (!maxLength || maxLength <= 0) return text
  return text.slice(0, maxLength)
}

function cloneArray(items) {
  return Array.isArray(items) ? items.map((item) => (item && typeof item === 'object' ? { ...item } : item)) : []
}

function cloneObject(value, fallback = {}) {
  return value && typeof value === 'object' && !Array.isArray(value) ? { ...value } : { ...fallback }
}

function cloneRecordMap(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  return Object.keys(value).reduce((result, key) => {
    const nextKey = asText(key)
    if (!nextKey) return result
    result[nextKey] = value[key]
    return result
  }, {})
}

function normalizeAgentPanelKind(value) {
  return asText(value).toLowerCase()
}

function stableAgentHash(value) {
  const text = typeof value === 'string' ? value : JSON.stringify(value ?? '')
  let hash = 2166136261
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0).toString(36)
}

function normalizeAgentThinkingItem(seed = {}) {
  return {
    id: asText(seed.id) || `thinking-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
    phase: asText(seed.phase),
    title: asText(seed.title) || '处理中',
    detail: asText(seed.detail),
    items: cloneArray(seed.items).map((item) => asText(item)).filter(Boolean),
    meta: cloneObject(seed.meta),
    state: asText(seed.state || 'pending') || 'pending',
  }
}

function upsertThinkingItemInList(items = [], seed = {}) {
  const item = normalizeAgentThinkingItem(seed)
  const nextTimeline = cloneArray(items)
  const existingIndex = nextTimeline.findIndex((entry) => asText(entry && entry.id) === item.id)
  if (existingIndex >= 0) {
    nextTimeline.splice(existingIndex, 1, { ...nextTimeline[existingIndex], ...item })
  } else {
    nextTimeline.push(item)
  }
  return nextTimeline
}

function completeActiveThinkingItemsInList(items = [], excludeId = '') {
  const skipId = asText(excludeId)
  return cloneArray(items).map((item) => {
    const normalized = normalizeAgentThinkingItem(item)
    if (normalized.id === skipId || normalized.state !== 'active') return normalized
    return { ...normalized, state: 'completed' }
  })
}

function normalizeAgentTraceThinkingItem(seed = {}) {
  const toolName = asText(seed.tool_name || seed.toolName || 'unknown_tool')
  const status = asText(seed.status)
  const state = status === 'success' ? 'completed' : (['failed', 'blocked', 'skipped'].includes(status) ? 'failed' : 'active')
  const titleStatus = {
    start: '开始调用',
    success: '执行成功',
    failed: '执行失败',
    blocked: '等待确认',
    skipped: '已跳过',
  }[status] || status || '执行中'
  const items = []
  const argumentsSummary = asText(seed.arguments_summary || seed.argumentsSummary)
  const resultSummary = asText(seed.result_summary || seed.resultSummary)
  const evidenceCount = seed.evidence_count ?? seed.evidenceCount
  const warningCount = seed.warning_count ?? seed.warningCount
  const producedArtifacts = cloneArray(seed.produced_artifacts || seed.producedArtifacts).map((item) => asText(item)).filter(Boolean)
  if (argumentsSummary) items.push(`参数：${argumentsSummary}`)
  if (resultSummary) items.push(`结果：${resultSummary}`)
  if (evidenceCount !== undefined && evidenceCount !== null && String(evidenceCount) !== '') items.push(`证据：${evidenceCount} 条`)
  if (warningCount !== undefined && warningCount !== null && Number(warningCount) > 0) items.push(`警告：${warningCount} 条`)
  if (producedArtifacts.length) items.push(`产物：${producedArtifacts.slice(0, 6).join('、')}`)
  return normalizeAgentThinkingItem({
    id: asText(seed.id || seed.call_id || seed.callId) || `trace:${toolName}`,
    phase: 'executing',
    title: `${titleStatus} ${toolName}`,
    detail: asText(seed.message || seed.reason),
    items,
    meta: {
      toolName,
      status,
      callId: asText(seed.call_id || seed.callId),
    },
    state,
  })
}

function normalizeAgentReasoningDelta(seed = {}) {
  return {
    id: asText(seed.id) || 'agent-reasoning',
    phase: asText(seed.phase),
    title: asText(seed.title) || '模型思考',
    delta: String(seed.delta || ''),
    state: asText(seed.state || 'active') || 'active',
  }
}

function upsertReasoningDeltaInList(items = [], seed = {}) {
  const item = normalizeAgentReasoningDelta(seed)
  const nextBlocks = cloneArray(items)
  const existingIndex = nextBlocks.findIndex((entry) => asText(entry && entry.id) === item.id)
  if (existingIndex >= 0) {
    const current = nextBlocks[existingIndex] || {}
    nextBlocks.splice(existingIndex, 1, {
      ...current,
      id: item.id,
      phase: item.phase || current.phase || '',
      title: item.title || current.title || '模型思考',
      content: String(current.content || '') + item.delta,
      state: item.state || current.state || 'active',
    })
  } else if (item.delta || item.state !== 'completed') {
    nextBlocks.push({
      id: item.id,
      phase: item.phase,
      title: item.title,
      content: item.delta,
      state: item.state,
    })
  }
  return nextBlocks
}

function normalizeAgentPlanStep(seed = {}) {
  return {
    tool_name: asText(seed.tool_name || seed.toolName),
    arguments: cloneObject(seed.arguments),
    reason: asText(seed.reason),
    evidence_goal: asText(seed.evidence_goal || seed.evidenceGoal),
    expected_artifacts: cloneArray(seed.expected_artifacts || seed.expectedArtifacts).map((item) => asText(item)).filter(Boolean),
    optional: !!seed.optional,
  }
}

function normalizeAgentPlanEnvelope(seed = {}) {
  return {
    steps: cloneArray(seed.steps).map((item) => normalizeAgentPlanStep(item)).filter((item) => item.tool_name),
    followupSteps: cloneArray(seed.followupSteps || seed.followup_steps).map((item) => normalizeAgentPlanStep(item)).filter((item) => item.tool_name),
    followupApplied: !!(seed.followupApplied || seed.followup_applied),
    summary: asText(seed.summary),
  }
}

function normalizeAgentDecision(seed = {}) {
  return {
    summary: asText(seed.summary),
    mode: asText(seed.mode || 'judgment') || 'judgment',
    strength: asText(seed.strength || 'weak') || 'weak',
    canAct: !!(seed.canAct || seed.can_act),
  }
}

function normalizeAgentDecisionEvidence(seed = {}) {
  return {
    key: asText(seed.key || seed.metric),
    metric: asText(seed.metric),
    headline: asText(seed.headline),
    value: seed && Object.prototype.hasOwnProperty.call(seed, 'value') ? seed.value : null,
    interpretation: asText(seed.interpretation),
    source: asText(seed.source),
    confidence: asText(seed.confidence || 'weak') || 'weak',
    limitation: asText(seed.limitation),
    supports: cloneArray(seed.supports).map((item) => asText(item)).filter(Boolean),
    isKey: !!(seed.isKey || seed.is_key),
  }
}

function normalizeAgentCounterpoint(seed = {}) {
  return {
    kind: asText(seed.kind || 'boundary') || 'boundary',
    title: asText(seed.title),
    detail: asText(seed.detail),
  }
}

function normalizeAgentAction(seed = {}) {
  return {
    title: asText(seed.title),
    detail: asText(seed.detail),
    condition: asText(seed.condition),
    target: asText(seed.target),
    prompt: asText(seed.prompt),
  }
}

function normalizeAgentBoundaryItem(seed = {}) {
  return {
    title: asText(seed.title),
    detail: asText(seed.detail),
  }
}

function normalizeAgentPanelPreloadNote(seed = {}) {
  return {
    key: asText(seed.key),
    label: asText(seed.label),
  }
}

function normalizeAgentPanelPreloadNotes(items = []) {
  return cloneArray(items)
    .map((item) => normalizeAgentPanelPreloadNote(item))
    .filter((item) => item.key && item.label)
}

function normalizeAgentProducedArtifacts(seed = {}) {
  return cloneArray(seed.produced_artifacts || seed.producedArtifacts)
    .map((item) => asText(item))
    .filter(Boolean)
}

function normalizeAgentStatusThinkingItem(seed = {}) {
  const stage = asText(seed.stage)
  const mapping = {
    gating: ['门卫判断', '正在判断你的问题是否清晰、当前范围是否能直接开始分析。'],
    clarifying: ['生成追问', '还缺少关键信息，正在整理最关键的补充问题。'],
    context_ready: ['整理上下文', '正在汇总当前分析快照与可复用结果。'],
    planning: ['规划分析步骤', '正在决定这轮要调用哪些工具、补哪些证据。'],
    executing: ['执行工具', '正在执行工具调用并收集证据。'],
    auditing: ['审计结果', '正在检查这些证据够不够真正回答你的问题。'],
    replanning: ['重新规划', '审计发现证据还不够，正在调整下一轮分析步骤。'],
    synthesizing: ['综合分析', '正在把结果整理成更完整的判断、依据和建议。'],
    answered: ['回答生成完成', '已生成最终回答。'],
    requires_clarification: ['需要补充信息', '还差关键信息，补充后才能继续分析。'],
    requires_risk_confirmation: ['等待风险确认', '需要确认后继续执行。'],
    failed: ['处理失败', asText(seed.message) || 'Agent 执行失败。'],
  }
  const [title, detail] = mapping[stage] || ['更新状态', asText(seed.label || stage) || 'Agent 状态已更新。']
  return normalizeAgentThinkingItem({
    id: `status-${stage || 'unknown'}`,
    phase: stage || 'status',
    title,
    detail,
    state: ['answered'].includes(stage)
      ? 'completed'
      : (['failed', 'requires_clarification'].includes(stage) ? 'failed' : 'active'),
  })
}

function normalizeAgentSubmitThinkingItem(state = 'active') {
  return normalizeAgentThinkingItem({
    id: 'frontend-submit-request',
    phase: 'connecting',
    title: '提交请求',
    detail: state === 'completed' ? '问题已经发给 AI 了，正在等它开始处理。' : '正在提交问题，并等待 AI 接收请求。',
    state,
  })
}

function normalizeAgentWaitingThinkingItem(elapsedSeconds = 0) {
  const seconds = Number(elapsedSeconds || 0)
  if (seconds >= 30) {
    return normalizeAgentThinkingItem({
      id: 'frontend-wait-backend',
      phase: 'connecting',
      title: '等待后端首个进度事件',
      detail: '请求已经发出，但后端还没推来第一条真实进度。这里一旦收到门卫判断、规划、工具执行或审计事件，就会立刻切换成真实步骤。',
      state: 'active',
    })
  }
  if (seconds >= 12) {
    return normalizeAgentThinkingItem({
      id: 'frontend-wait-backend',
      phase: 'connecting',
      title: '等待后端首个进度事件',
      detail: '后端已收到请求，正在准备返回第一条真实步骤。',
      state: 'active',
    })
  }
  return normalizeAgentThinkingItem({
    id: 'frontend-wait-backend',
    phase: 'connecting',
    title: '等待后端首个进度事件',
    detail: '正在等待后端返回第一条真实进度。',
    state: 'active',
  })
}

function normalizeAgentPlanThinkingItem(seed = {}) {
  const normalizedPlan = normalizeAgentPlanEnvelope(seed)
  const previewItems = normalizedPlan.steps
    .slice(0, 4)
    .map((step) => asText(step.reason || step.tool_name))
    .filter(Boolean)
  return normalizeAgentThinkingItem({
    id: `plan-envelope-${stableAgentHash({
      steps: normalizedPlan.steps.map((step) => step.tool_name),
      followup: normalizedPlan.followupSteps.map((step) => step.tool_name),
      summary: normalizedPlan.summary,
    })}`,
    phase: normalizedPlan.followupApplied ? 'replanning' : 'planning',
    title: normalizedPlan.followupApplied ? '已补充后续步骤' : '已列出本轮步骤',
    detail: normalizedPlan.summary || '已生成待执行的分析步骤。',
    items: previewItems,
    state: 'completed',
  })
}

function mergeAgentThinkingTimeline(liveItems = [], finalItems = []) {
  let merged = cloneArray(liveItems)
  cloneArray(finalItems).forEach((item) => {
    merged = upsertThinkingItemInList(merged, item)
  })
  return cloneArray(merged)
}

function parseSseChunk(rawChunk = '') {
  const lines = String(rawChunk || '').split(/\r?\n/)
  let type = 'message'
  const dataLines = []
  lines.forEach((line) => {
    if (!line) return
    if (line.startsWith('event:')) {
      type = asText(line.slice(6))
      return
    }
    if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trimStart())
    }
  })
  const rawData = dataLines.join('\n').trim()
  if (!rawData) {
    return { type, payload: {} }
  }
  return {
    type,
    payload: JSON.parse(rawData),
  }
}

async function consumeSseStream(response, onEvent) {
  if (!response || !response.body || typeof response.body.getReader !== 'function') {
    throw new Error('Agent 流式响应缺少可读数据流')
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
    let splitIndex = buffer.indexOf('\n\n')
    while (splitIndex >= 0) {
      const rawChunk = buffer.slice(0, splitIndex)
      buffer = buffer.slice(splitIndex + 2)
      if (rawChunk.trim()) {
        onEvent(parseSseChunk(rawChunk))
      }
      splitIndex = buffer.indexOf('\n\n')
    }
    if (done) break
  }

  if (buffer.trim()) {
    onEvent(parseSseChunk(buffer))
  }
}

function normalizeAgentTurnPayload(seed = {}) {
  const rawOutput = seed.output && typeof seed.output === 'object' ? seed.output : {}
  const rawDiagnostics = seed.diagnostics && typeof seed.diagnostics === 'object' ? seed.diagnostics : {}
  const rawContextSummary = (seed.contextSummary && typeof seed.contextSummary === 'object')
    ? seed.contextSummary
    : ((seed.context_summary && typeof seed.context_summary === 'object') ? seed.context_summary : {})
  const rawPlan = seed.plan && typeof seed.plan === 'object' ? seed.plan : {}
  const output = {
    cards: cloneArray(
      Object.prototype.hasOwnProperty.call(seed, 'cards')
        ? seed.cards
        : (Object.prototype.hasOwnProperty.call(seed, 'assistant_cards') ? seed.assistant_cards : rawOutput.cards),
    ),
    clarificationQuestion: asText(
      Object.prototype.hasOwnProperty.call(seed, 'clarificationQuestion')
        ? seed.clarificationQuestion
        : (Object.prototype.hasOwnProperty.call(seed, 'clarification_question')
          ? seed.clarification_question
          : rawOutput.clarification_question),
    ),
    clarificationOptions: cloneArray(
      Object.prototype.hasOwnProperty.call(seed, 'clarificationOptions')
        ? seed.clarificationOptions
        : (Object.prototype.hasOwnProperty.call(seed, 'clarification_options')
          ? seed.clarification_options
          : rawOutput.clarification_options),
    ).map((item) => asText(item)).filter(Boolean),
    riskPrompt: asText(
      Object.prototype.hasOwnProperty.call(seed, 'riskPrompt')
        ? seed.riskPrompt
        : (Object.prototype.hasOwnProperty.call(seed, 'risk_prompt')
          ? seed.risk_prompt
          : rawOutput.risk_prompt),
    ),
    nextSuggestions: cloneArray(
      Object.prototype.hasOwnProperty.call(seed, 'nextSuggestions')
        ? seed.nextSuggestions
        : (Object.prototype.hasOwnProperty.call(seed, 'next_suggestions')
          ? seed.next_suggestions
          : rawOutput.next_suggestions),
    ),
    panelPayloads: cloneObject(
      Object.prototype.hasOwnProperty.call(seed, 'panelPayloads')
        ? seed.panelPayloads
        : (rawOutput.panel_payloads || rawOutput.panelPayloads),
    ),
    decision: normalizeAgentDecision(
      Object.prototype.hasOwnProperty.call(seed, 'decision')
        ? seed.decision
        : rawOutput.decision,
    ),
    support: cloneArray(
      Object.prototype.hasOwnProperty.call(seed, 'support')
        ? seed.support
        : rawOutput.support,
    ).map((item) => normalizeAgentDecisionEvidence(item)),
    counterpoints: cloneArray(
      Object.prototype.hasOwnProperty.call(seed, 'counterpoints')
        ? seed.counterpoints
        : rawOutput.counterpoints,
    ).map((item) => normalizeAgentCounterpoint(item)),
    actions: cloneArray(
      Object.prototype.hasOwnProperty.call(seed, 'actions')
        ? seed.actions
        : rawOutput.actions,
    ).map((item) => normalizeAgentAction(item)),
    boundary: cloneArray(
      Object.prototype.hasOwnProperty.call(seed, 'boundary')
        ? seed.boundary
        : rawOutput.boundary,
    ).map((item) => normalizeAgentBoundaryItem(item)),
  }
  const diagnostics = {
    executionTrace: cloneArray(
      Object.prototype.hasOwnProperty.call(seed, 'executionTrace')
        ? seed.executionTrace
        : (rawDiagnostics.execution_trace || rawDiagnostics.executionTrace),
    ),
    usedTools: cloneArray(
      Object.prototype.hasOwnProperty.call(seed, 'usedTools')
        ? seed.usedTools
        : (rawDiagnostics.used_tools || rawDiagnostics.usedTools),
    ),
    citations: cloneArray(
      Object.prototype.hasOwnProperty.call(seed, 'citations')
        ? seed.citations
        : rawDiagnostics.citations,
    ),
    researchNotes: cloneArray(
      Object.prototype.hasOwnProperty.call(seed, 'researchNotes')
        ? seed.researchNotes
        : (rawDiagnostics.research_notes || rawDiagnostics.researchNotes),
    ),
    auditIssues: cloneArray(
      Object.prototype.hasOwnProperty.call(seed, 'auditIssues')
        ? seed.auditIssues
        : (rawDiagnostics.audit_issues || rawDiagnostics.auditIssues),
    ),
    planningSummary: asText(
      Object.prototype.hasOwnProperty.call(seed, 'planningSummary')
        ? seed.planningSummary
        : (rawDiagnostics.planning_summary || rawDiagnostics.planningSummary),
    ),
    auditSummary: asText(
      Object.prototype.hasOwnProperty.call(seed, 'auditSummary')
        ? seed.auditSummary
        : (rawDiagnostics.audit_summary || rawDiagnostics.auditSummary),
    ),
    replanCount: Number(
      Object.prototype.hasOwnProperty.call(seed, 'replanCount')
        ? seed.replanCount
        : (rawDiagnostics.replan_count ?? rawDiagnostics.replanCount ?? 0),
    ) || 0,
    thinkingTimeline: cloneArray(
      Object.prototype.hasOwnProperty.call(seed, 'thinkingTimeline')
        ? seed.thinkingTimeline
        : (rawDiagnostics.thinking_timeline || rawDiagnostics.thinkingTimeline),
    )
      .map((item) => normalizeAgentThinkingItem(item)),
    error: asText(
      Object.prototype.hasOwnProperty.call(seed, 'error')
        ? seed.error
        : rawDiagnostics.error,
    ),
  }
  return {
    status: asText(seed.status),
    stage: asText(seed.stage || rawOutput.stage || seed.status),
    output,
    diagnostics,
    contextSummary: cloneObject(rawContextSummary),
    plan: normalizeAgentPlanEnvelope(rawPlan),
  }
}

function getAgentSummaryCardContent(cards = []) {
  const summaryCard = cloneArray(cards).find((card) => card && asText(card.type) === 'summary')
  return summaryCard ? asText(summaryCard.content) : ''
}

function stripMirroredSummaryAssistantMessage(messages = [], cards = []) {
  const rows = cloneArray(messages)
  const summary = getAgentSummaryCardContent(cards)
  if (!summary || !rows.length) return rows
  const last = rows[rows.length - 1]
  if (!last || asText(last.role) !== 'assistant') return rows
  if (asText(last.content) !== summary) return rows
  return rows.slice(0, -1)
}

function toTimestamp(value) {
  const ts = Date.parse(String(value || ''))
  return Number.isFinite(ts) ? ts : 0
}

function buildAgentPreviewCandidate(session = null) {
  if (!session || typeof session !== 'object') return ''
  return [
    asText(session.preview),
    asText(session.error),
    asText(session.riskPrompt),
    asText(session.clarificationQuestion),
    getAgentSummaryCardContent(session.cards || (session.output && session.output.cards) || []),
  ].find(Boolean) || ''
}

function sortAgentSessions(sessions = []) {
  return cloneArray(sessions).sort((left, right) => {
    const leftPinned = !!(left && left.isPinned)
    const rightPinned = !!(right && right.isPinned)
    if (leftPinned !== rightPinned) return leftPinned ? -1 : 1
    const leftPinnedAt = toTimestamp(left && left.pinnedAt)
    const rightPinnedAt = toTimestamp(right && right.pinnedAt)
    if (leftPinnedAt !== rightPinnedAt) return rightPinnedAt - leftPinnedAt
    const leftUpdatedAt = toTimestamp(left && left.updatedAt)
    const rightUpdatedAt = toTimestamp(right && right.updatedAt)
    if (leftUpdatedAt !== rightUpdatedAt) return rightUpdatedAt - leftUpdatedAt
    const leftCreatedAt = toTimestamp(left && left.createdAt)
    const rightCreatedAt = toTimestamp(right && right.createdAt)
    return rightCreatedAt - leftCreatedAt
  })
}

function deriveAgentSessionTitle(messages = []) {
  const rows = cloneArray(messages)
  const firstUserMessage = rows.find((item) => item && item.role === 'user' && asText(item.content))
  const raw = firstUserMessage ? asText(firstUserMessage.content) : ''
  return raw ? raw.slice(0, 24) : '新聊天'
}

function deriveAgentSessionPreview(session = null) {
  const text = buildAgentPreviewCandidate(session)
  return text ? text.slice(0, 120) : '开始一段新的分析对话'
}

function createAgentSessionRecord(seed = {}) {
  const nowIso = new Date().toISOString()
  const turn = normalizeAgentTurnPayload(seed)
  const messages = stripMirroredSummaryAssistantMessage(seed.messages, turn.output.cards)
  const titleSource = asText(seed.titleSource || seed.title_source || 'fallback') || 'fallback'
  const panelKind = normalizeAgentPanelKind(seed.panelKind || seed.panel_kind)
  const session = {
    id: asText(seed.id),
    title: clampText(seed.title, 60) || deriveAgentSessionTitle(messages),
    preview: clampText(seed.preview, 120),
    historyId: asText(seed.historyId || seed.history_id),
    updatedAt: asText(seed.updatedAt || nowIso),
    createdAt: asText(seed.createdAt || nowIso),
    pinnedAt: asText(seed.pinnedAt),
    status: asText(seed.status || 'idle'),
    stage: asText(seed.stage || turn.stage || 'gating'),
    input: String(seed.input || ''),
    output: cloneObject(turn.output),
    diagnostics: cloneObject(turn.diagnostics),
    contextSummary: cloneObject(turn.contextSummary),
    plan: cloneObject(turn.plan),
    cards: cloneArray(turn.output.cards),
    decision: normalizeAgentDecision(turn.output.decision),
    support: cloneArray(turn.output.support).map((item) => normalizeAgentDecisionEvidence(item)),
    counterpoints: cloneArray(turn.output.counterpoints).map((item) => normalizeAgentCounterpoint(item)),
    actions: cloneArray(turn.output.actions).map((item) => normalizeAgentAction(item)),
    boundary: cloneArray(turn.output.boundary).map((item) => normalizeAgentBoundaryItem(item)),
    executionTrace: cloneArray(turn.diagnostics.executionTrace),
    usedTools: cloneArray(turn.diagnostics.usedTools),
    citations: cloneArray(turn.diagnostics.citations),
    researchNotes: cloneArray(turn.diagnostics.researchNotes),
    auditIssues: cloneArray(turn.diagnostics.auditIssues),
    thinkingTimeline: cloneArray(turn.diagnostics.thinkingTimeline),
    nextSuggestions: cloneArray(turn.output.nextSuggestions),
    clarificationQuestion: String(turn.output.clarificationQuestion || ''),
    clarificationOptions: cloneArray(turn.output.clarificationOptions),
    riskPrompt: String(turn.output.riskPrompt || ''),
    error: String(turn.diagnostics.error || ''),
    riskConfirmations: cloneArray(seed.riskConfirmations || seed.risk_confirmations),
    panelPreloadNotes: normalizeAgentPanelPreloadNotes(seed.panelPreloadNotes),
    preloadedPanelKeys: cloneArray(seed.preloadedPanelKeys).map((item) => asText(item)).filter(Boolean),
    pendingTaskConfirmation: cloneObject(seed.pendingTaskConfirmation || seed.pending_task_confirmation),
    messages,
    panelPayloads: cloneObject(turn.output.panelPayloads),
    isPinned: !!seed.isPinned,
    persisted: !!seed.persisted,
    snapshotLoaded: !!seed.snapshotLoaded,
    titleSource,
    panelKind,
  }
  if (!session.preview) {
    session.preview = deriveAgentSessionPreview(session)
  }
  if (!session.id) {
    session.id = `agent-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
  }
  return session
}

function createAgentSessionPlaceholderRecord(session = null) {
  const base = session && typeof session === 'object' ? session : {}
  return createAgentSessionRecord({
    ...base,
    input: '',
    cards: [],
    executionTrace: [],
    usedTools: [],
    citations: [],
    researchNotes: [],
    nextSuggestions: [],
    clarificationQuestion: '',
    clarificationOptions: [],
    riskPrompt: '',
    error: '',
    riskConfirmations: [],
    pendingTaskConfirmation: null,
    messages: [],
    output: {
      cards: [],
      clarificationQuestion: '',
      clarificationOptions: [],
      riskPrompt: '',
      nextSuggestions: [],
      panelPayloads: {},
      decision: { summary: '', mode: 'judgment', strength: 'weak', canAct: false },
      support: [],
      counterpoints: [],
      actions: [],
      boundary: [],
    },
    diagnostics: { executionTrace: [], usedTools: [], citations: [], researchNotes: [], auditIssues: [], thinkingTimeline: [], error: '' },
    contextSummary: {},
    plan: { steps: [], followupSteps: [], followupApplied: false, summary: '' },
    snapshotLoaded: false,
  })
}

function cloneAgentSessionRecord(session = null) {
  if (!session || typeof session !== 'object') return null
  return createAgentSessionRecord({
    ...session,
    cards: cloneArray(session.cards),
    executionTrace: cloneArray(session.executionTrace),
    usedTools: cloneArray(session.usedTools),
    citations: cloneArray(session.citations),
    researchNotes: cloneArray(session.researchNotes),
    thinkingTimeline: cloneArray(session.thinkingTimeline),
    nextSuggestions: cloneArray(session.nextSuggestions),
    riskConfirmations: cloneArray(session.riskConfirmations),
    panelPreloadNotes: normalizeAgentPanelPreloadNotes(session.panelPreloadNotes),
    preloadedPanelKeys: cloneArray(session.preloadedPanelKeys),
    pendingTaskConfirmation: cloneObject(session.pendingTaskConfirmation),
    messages: cloneArray(session.messages),
    panelPayloads: cloneObject(session.panelPayloads),
  })
}

function normalizeAgentSessionSummary(item = {}, existing = null) {
  const base = existing && typeof existing === 'object' ? existing : {}
  const session = createAgentSessionRecord({
    ...base,
    id: item.id,
    title: item.title,
    preview: item.preview,
    status: item.status || base.status || 'idle',
    createdAt: item.created_at || base.createdAt,
    updatedAt: item.updated_at || base.updatedAt,
    pinnedAt: item.pinned_at || '',
    isPinned: !!item.is_pinned,
    persisted: true,
    snapshotLoaded: !!base.snapshotLoaded,
    titleSource: item.title_source || base.titleSource || 'fallback',
    historyId: item.history_id || base.historyId || '',
    panelKind: item.panel_kind || base.panelKind || '',
  })
  return session
}

function createAgentRunState(seed = {}) {
  return {
    abortController: seed.abortController || null,
    loading: !!seed.loading,
    streamState: asText(seed.streamState || seed.stream_state || 'idle') || 'idle',
    startedAt: Number(seed.startedAt ?? seed.started_at ?? 0) || 0,
    elapsedTick: Number(seed.elapsedTick ?? seed.elapsed_tick ?? 0) || 0,
    elapsedTimer: seed.elapsedTimer || null,
    streamingMessageId: asText(seed.streamingMessageId || seed.streaming_message_id),
    reasoningBlocks: cloneArray(seed.reasoningBlocks).map((item) => ({
      id: asText(item && item.id) || 'agent-reasoning',
      phase: asText(item && item.phase),
      title: asText(item && item.title) || '模型思考',
      content: String((item && item.content) || ''),
      state: asText(item && item.state) || 'active',
    })),
    panelPreloadNotes: normalizeAgentPanelPreloadNotes(seed.panelPreloadNotes),
    preloadedPanelKeys: cloneArray(seed.preloadedPanelKeys).map((item) => asText(item)).filter(Boolean),
    pendingQuestion: String(seed.pendingQuestion || ''),
    autoScrollLocked: !!seed.autoScrollLocked,
    autoScrollSticky: Object.prototype.hasOwnProperty.call(seed, 'autoScrollSticky')
      ? !!seed.autoScrollSticky
      : true,
    autoScrollThresholdPx: Number(seed.autoScrollThresholdPx ?? 24) || 24,
  }
}

function normalizeAgentToolSummary(item = {}) {
  return {
    name: asText(item.name),
    description: asText(item.description),
    category: asText(item.category),
    layer: asText(item.layer),
    uiTier: asText(item.uiTier || item.ui_tier || 'foundation') || 'foundation',
    dataDomain: asText(item.dataDomain || item.data_domain || 'general') || 'general',
    capabilityType: asText(item.capabilityType || item.capability_type || 'none') || 'none',
    sceneType: asText(item.sceneType || item.scene_type || 'general') || 'general',
    llmExposure: asText(item.llmExposure || item.llm_exposure || 'secondary') || 'secondary',
    toolkitId: asText(item.toolkitId || item.toolkit_id),
    defaultPolicyKey: asText(item.defaultPolicyKey || item.default_policy_key),
    evidenceContract: cloneArray(item.evidenceContract || item.evidence_contract).map((entry) => asText(entry)).filter(Boolean),
    applicableScenarios: cloneArray(item.applicableScenarios || item.applicable_scenarios).map((entry) => asText(entry)).filter(Boolean),
    cautions: cloneArray(item.cautions).map((entry) => asText(entry)).filter(Boolean),
    requires: cloneArray(item.requires).map((entry) => asText(entry)).filter(Boolean),
    produces: cloneArray(item.produces).map((entry) => asText(entry)).filter(Boolean),
    inputSchema: item && typeof item.inputSchema === 'object' ? item.inputSchema : (item.input_schema && typeof item.input_schema === 'object' ? item.input_schema : {}),
    outputSchema: item && typeof item.outputSchema === 'object' ? item.outputSchema : (item.output_schema && typeof item.output_schema === 'object' ? item.output_schema : {}),
    readonly: !!item.readonly,
    costLevel: asText(item.costLevel || item.cost_level || 'safe') || 'safe',
    riskLevel: asText(item.riskLevel || item.risk_level || 'safe') || 'safe',
    timeoutSec: Number(item.timeoutSec ?? item.timeout_sec ?? 0) || 0,
    cacheable: !!item.cacheable,
  }
}

export {
  asText,
  clampText,
  cloneArray,
  cloneObject,
  cloneRecordMap,
  stableAgentHash,
  normalizeAgentThinkingItem,
  upsertThinkingItemInList,
  completeActiveThinkingItemsInList,
  normalizeAgentTraceThinkingItem,
  normalizeAgentReasoningDelta,
  upsertReasoningDeltaInList,
  normalizeAgentPlanStep,
  normalizeAgentPlanEnvelope,
  normalizeAgentDecision,
  normalizeAgentDecisionEvidence,
  normalizeAgentCounterpoint,
  normalizeAgentAction,
  normalizeAgentBoundaryItem,
  normalizeAgentPanelPreloadNote,
  normalizeAgentPanelPreloadNotes,
  normalizeAgentProducedArtifacts,
  normalizeAgentStatusThinkingItem,
  normalizeAgentSubmitThinkingItem,
  normalizeAgentWaitingThinkingItem,
  normalizeAgentPlanThinkingItem,
  mergeAgentThinkingTimeline,
  parseSseChunk,
  consumeSseStream,
  normalizeAgentTurnPayload,
  getAgentSummaryCardContent,
  stripMirroredSummaryAssistantMessage,
  toTimestamp,
  buildAgentPreviewCandidate,
  sortAgentSessions,
  deriveAgentSessionTitle,
  deriveAgentSessionPreview,
  createAgentSessionRecord,
  createAgentSessionPlaceholderRecord,
  cloneAgentSessionRecord,
  normalizeAgentSessionSummary,
  createAgentRunState,
  normalizeAgentToolSummary,
}
