import {
  asText,
  clampText,
  cloneArray,
  cloneObject,
  cloneRecordMap,
} from '../shared/normalizers.js'

function normalizeAgentPanelKind(value) {
  return asText(value).toLowerCase()
}

function normalizeAgentThinkingItem(seed = {}) {
  return {
    id: asText(seed.id) || `thinking-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
    phase: asText(seed.phase),
    title: asText(seed.title) || '处理中',
    detail: asText(seed.detail),
    displayText: asText(seed.displayText || seed.display_text),
    resultSummary: asText(seed.resultSummary || seed.result_summary),
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

function normalizeAgentMessage(seed = {}) {
  const raw = seed && typeof seed === 'object' ? seed : {}
  const message = {
    role: asText(raw.role) || 'user',
    content: String(raw.content || ''),
  }
  const id = asText(raw.id || raw.messageId || raw.message_id)
  if (id) message.id = id
  return message
}

function normalizeAgentMessages(items = []) {
  return cloneArray(items)
    .map((item) => normalizeAgentMessage(item))
    .filter((item) => item.content)
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

function toTimestamp(value) {
  const ts = Date.parse(String(value || ''))
  return Number.isFinite(ts) ? ts : 0
}

function buildAgentPreviewCandidate(session = null) {
  if (!session || typeof session !== 'object') return ''
  const messages = normalizeAgentMessages(session.messages)
  const lastMessage = messages.length ? messages[messages.length - 1] : null
  return [
    asText(session.preview),
    asText(session.error),
    asText(lastMessage && lastMessage.content),
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
  return raw ? raw.slice(0, 24) : '新报告'
}

function deriveAgentSessionPreview(session = null) {
  const text = buildAgentPreviewCandidate(session)
  return text ? text.slice(0, 120) : '开始一份新的区域分析'
}

function createAgentSessionRecord(seed = {}) {
  const nowIso = new Date().toISOString()
  const messages = normalizeAgentMessages(seed.messages)
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
    error: asText(seed.error),
    messages,
    activityItems: cloneArray(seed.activityItems || seed.activity_items)
      .map((item) => normalizeAgentThinkingItem(item)),
    panelPayloads: cloneObject(seed.panelPayloads),
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
    error: '',
    messages: [],
    activityItems: [],
    panelPayloads: {},
    snapshotLoaded: false,
  })
}

function cloneAgentSessionRecord(session = null) {
  if (!session || typeof session !== 'object') return null
  return createAgentSessionRecord({
    ...session,
    messages: cloneArray(session.messages),
    activityItems: cloneArray(session.activityItems),
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
  normalizeAgentThinkingItem,
  upsertThinkingItemInList,
  normalizeAgentMessage,
  normalizeAgentMessages,
  normalizeAgentPanelPreloadNote,
  normalizeAgentPanelPreloadNotes,
  parseSseChunk,
  consumeSseStream,
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
