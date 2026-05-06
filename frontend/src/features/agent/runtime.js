import {
  asText,
  clampText,
  cloneArray,
  cloneObject,
  cloneRecordMap,
  completeActiveThinkingItemsInList,
  consumeSseStream,
  createAgentRunState,
  deriveAgentSessionPreview,
  deriveAgentSessionTitle,
  mergeAgentThinkingTimeline,
  normalizeAgentAction,
  normalizeAgentBoundaryItem,
  normalizeAgentCounterpoint,
  normalizeAgentDecision,
  normalizeAgentDecisionEvidence,
  normalizeAgentPanelPreloadNotes,
  normalizeAgentPlanEnvelope,
  normalizeAgentPlanThinkingItem,
  normalizeAgentProducedArtifacts,
  normalizeAgentReasoningDelta,
  normalizeAgentStatusThinkingItem,
  normalizeAgentSubmitThinkingItem,
  normalizeAgentThinkingItem,
  normalizeAgentToolSummary,
  normalizeAgentTraceThinkingItem,
  normalizeAgentTurnPayload,
  normalizeAgentWaitingThinkingItem,
  upsertReasoningDeltaInList,
  upsertThinkingItemInList,
} from './normalizers.js'
import {
  buildAgentPlanChecklist,
  buildAgentToolCallItems,
  hasAgentExecutionTraceContent,
  hasAgentPlanContent,
  shouldExpandAgentProcessSection,
} from './derived.js'
import {
  buildAnalysisTaskConfirmationFromTurn,
  cloneAnalysisTaskConfirmation,
} from './analysis-task-registry.js'

function createAgentRuntimeMethods() {
  return {
    getAgentRunState(sessionId = '') {
      const nextId = asText(sessionId || this.activeAgentSessionId || this.agentConversationId)
      if (!nextId) return null
      const registry = cloneRecordMap(this.agentRunRegistry)
      const current = registry[nextId]
      return current ? createAgentRunState(current) : null
    },
    setAgentRunState(sessionId = '', patch = {}) {
      const nextId = asText(sessionId)
      if (!nextId) return null
      const registry = cloneRecordMap(this.agentRunRegistry)
      const current = registry[nextId] ? createAgentRunState(registry[nextId]) : createAgentRunState()
      const nextState = createAgentRunState({ ...current, ...patch })
      this.agentRunRegistry = {
        ...registry,
        [nextId]: nextState,
      }
      if (nextId === asText(this.activeAgentSessionId)) {
        this.syncActiveAgentRuntimeView(nextId)
      }
      return nextState
    },
    clearAgentRunState(sessionId = '', options = {}) {
      const nextId = asText(sessionId)
      if (!nextId) return
      const registry = cloneRecordMap(this.agentRunRegistry)
      const current = registry[nextId] ? createAgentRunState(registry[nextId]) : null
      if (current && current.elapsedTimer && typeof window !== 'undefined' && typeof window.clearInterval === 'function') {
        window.clearInterval(current.elapsedTimer)
      }
      if (current && options.abort && current.abortController) {
        try {
          current.abortController.abort()
        } catch (_) {
          // Ignore abort errors from already-settled controllers.
        }
      }
      delete registry[nextId]
      this.agentRunRegistry = registry
      if (nextId === asText(this.activeAgentSessionId)) {
        this.syncActiveAgentRuntimeView(nextId)
      }
    },
    destroyAllAgentRuns() {
      Object.keys(cloneRecordMap(this.agentRunRegistry)).forEach((sessionId) => {
        this.clearAgentRunState(sessionId, { abort: true })
      })
      this.agentRunRegistry = {}
      this.agentTurnAbortController = null
    },
    isAgentSessionRunning(sessionId = '') {
      const runState = this.getAgentRunState(sessionId)
      return !!(runState && runState.loading)
    },
    getRunningAgentSessionCount() {
      return Object.values(cloneRecordMap(this.agentRunRegistry))
        .map((entry) => createAgentRunState(entry))
        .filter((entry) => entry.loading)
        .length
    },
    getAgentRunningBadgeText() {
      const count = this.getRunningAgentSessionCount()
      if (count <= 0) return ''
      return count > 1 ? String(count) : '运行中'
    },
    syncActiveAgentRuntimeView(sessionId = '') {
      const nextId = asText(sessionId || this.activeAgentSessionId || this.agentConversationId)
      if (!nextId) {
        this.agentLoading = false
        this.agentStreamState = 'idle'
        this.agentStreamStartedAt = 0
        this.agentStreamElapsedTick = 0
        this.agentStreamElapsedTimer = null
        this.agentStreamingMessageId = ''
        this.agentReasoningBlocks = []
        this.agentPanelPreloadNotes = []
        this.agentPreloadedPanelKeys = []
        this.agentPanelPayloads = {}
        this.agentPendingTaskConfirmation = null
        this.agentTurnAbortController = null
        return
      }
      const runState = this.getAgentRunState(nextId)
      if (!runState) {
        const session = this.findAgentSession(nextId) || {
          status: this.agentStatus,
          thinkingTimeline: this.agentThinkingTimeline,
          plan: this.agentPlan,
          executionTrace: this.agentExecutionTrace,
          panelPreloadNotes: this.agentPanelPreloadNotes,
          preloadedPanelKeys: this.agentPreloadedPanelKeys,
          panelPayloads: this.agentPanelPayloads,
        }
        const hasPlan = hasAgentPlanContent(session && session.plan)
        const hasTrace = hasAgentExecutionTraceContent(session && session.executionTrace)
        const hasProcessContent = !!(
          (Array.isArray(session && session.thinkingTimeline) && session.thinkingTimeline.length)
          || hasPlan
          || hasTrace
          || (Array.isArray(this.agentReasoningBlocks) && this.agentReasoningBlocks.length)
        )
        const shouldPreserveElapsed = !!(
          session
          && ['answered', 'failed', 'requires_risk_confirmation'].includes(asText(session.status))
          && Number(this.agentStreamStartedAt || 0) > 0
        )
        const shouldPreserveReasoning = !!(
          session
          && ['answered', 'failed', 'requires_risk_confirmation'].includes(asText(session.status))
          && Array.isArray(this.agentReasoningBlocks)
          && this.agentReasoningBlocks.length > 0
        )
        this.agentLoading = false
        this.agentStreamState = 'idle'
        if (!shouldPreserveElapsed) {
          this.agentStreamStartedAt = 0
          this.agentStreamElapsedTick = 0
        }
        this.agentStreamElapsedTimer = null
        this.agentStreamingMessageId = ''
        if (!shouldPreserveReasoning) {
          this.agentReasoningBlocks = []
        }
        this.agentPanelPreloadNotes = normalizeAgentPanelPreloadNotes(session && session.panelPreloadNotes)
        this.agentPreloadedPanelKeys = cloneArray(session && session.preloadedPanelKeys)
        this.agentPanelPayloads = cloneObject(session && session.panelPayloads)
        this.agentPendingTaskConfirmation = cloneAnalysisTaskConfirmation(session && session.pendingTaskConfirmation)
        this.agentThinkingExpanded = shouldExpandAgentProcessSection(session && session.status, {
          hasContent: hasProcessContent,
        })
        this.agentPlanExpanded = shouldExpandAgentProcessSection(session && session.status, {
          hasContent: hasPlan,
        })
        this.agentTraceExpanded = shouldExpandAgentProcessSection(session && session.status, {
          hasContent: hasTrace,
        })
        this.agentTurnAbortController = null
        return
      }
      this.agentLoading = !!runState.loading
      this.agentStreamState = asText(runState.streamState || 'idle') || 'idle'
      this.agentStreamStartedAt = Number(runState.startedAt || 0) || 0
      this.agentStreamElapsedTick = Number(runState.elapsedTick || runState.startedAt || 0) || 0
      this.agentStreamElapsedTimer = runState.elapsedTimer || null
      this.agentStreamingMessageId = asText(runState.streamingMessageId)
      this.agentReasoningBlocks = cloneArray(runState.reasoningBlocks)
      this.agentPanelPreloadNotes = normalizeAgentPanelPreloadNotes(runState.panelPreloadNotes)
      this.agentPreloadedPanelKeys = cloneArray(runState.preloadedPanelKeys)
      this.agentTurnAbortController = runState.abortController || null
      if (runState.loading && (this.agentThinkingTimeline.length || this.agentReasoningBlocks.length || this.agentExecutionTrace.length || hasAgentPlanContent(this.agentPlan))) {
        this.agentThinkingExpanded = true
      }
      if (runState.loading && hasAgentPlanContent(this.agentPlan)) {
        this.agentPlanExpanded = true
      }
      if (runState.loading && hasAgentExecutionTraceContent(this.agentExecutionTrace)) {
        this.agentTraceExpanded = true
      }
    },
    resetAgentStreamingState(sessionId = '') {
      const targetSessionId = asText(sessionId || this.activeAgentSessionId || this.agentConversationId)
      if (!targetSessionId) {
        this.agentTurnAbortController = null
        this.agentStreamingMessageId = ''
        this.agentStreamState = 'idle'
        this.agentStreamStartedAt = 0
        this.agentStreamElapsedTick = 0
        this.agentThinkingExpanded = false
        this.agentPlanExpanded = false
        this.agentTraceExpanded = false
        this.agentPanelPreloadNotes = []
        this.agentPreloadedPanelKeys = []
        return
      }
      this.setAgentRunState(targetSessionId, {
        loading: false,
        streamState: 'idle',
        startedAt: 0,
        elapsedTick: 0,
        streamingMessageId: '',
        reasoningBlocks: [],
        panelPreloadNotes: [],
        preloadedPanelKeys: [],
        pendingQuestion: '',
      })
    },
    startAgentThinkingTimer(sessionId = '') {
      const targetSessionId = asText(sessionId || this.activeAgentSessionId || this.agentConversationId)
      if (!targetSessionId) {
        this.agentStreamStartedAt = Date.now()
        this.agentStreamElapsedTick = this.agentStreamStartedAt
        if (typeof window === 'undefined' || typeof window.setInterval !== 'function') {
          return
        }
        this.agentStreamElapsedTimer = window.setInterval(() => {
          this.agentStreamElapsedTick = Date.now()
          this.updateAgentWaitingProcessFallback()
        }, 1000)
        return
      }
      const runState = this.getAgentRunState(targetSessionId) || createAgentRunState()
      if (runState.elapsedTimer && typeof window !== 'undefined' && typeof window.clearInterval === 'function') {
        window.clearInterval(runState.elapsedTimer)
      }
      const startedAt = Date.now()
      const nextState = {
        startedAt,
        elapsedTick: startedAt,
      }
      if (typeof window !== 'undefined' && typeof window.setInterval === 'function') {
        nextState.elapsedTimer = window.setInterval(() => {
          const activeRunState = this.getAgentRunState(targetSessionId)
          if (!activeRunState || !activeRunState.loading) {
            if (typeof window.clearInterval === 'function' && activeRunState && activeRunState.elapsedTimer) {
              window.clearInterval(activeRunState.elapsedTimer)
            }
            return
          }
          this.setAgentRunState(targetSessionId, { elapsedTick: Date.now() })
          if (targetSessionId === asText(this.activeAgentSessionId)) {
            this.updateAgentWaitingProcessFallback(targetSessionId)
          }
        }, 1000)
      }
      this.setAgentRunState(targetSessionId, nextState)
    },
    stopAgentThinkingTimer(sessionId = '') {
      const targetSessionId = asText(sessionId || this.activeAgentSessionId || this.agentConversationId)
      if (!targetSessionId) {
        if (this.agentStreamElapsedTimer && typeof window !== 'undefined' && typeof window.clearInterval === 'function') {
          window.clearInterval(this.agentStreamElapsedTimer)
        }
        this.agentStreamElapsedTimer = null
        return
      }
      const runState = this.getAgentRunState(targetSessionId)
      if (runState && runState.elapsedTimer && typeof window !== 'undefined' && typeof window.clearInterval === 'function') {
        window.clearInterval(runState.elapsedTimer)
      }
      if (runState) {
        this.setAgentRunState(targetSessionId, { elapsedTimer: null })
      }
    },
    getAgentChatBodyElement() {
      return (this.$refs && this.$refs.agentChatBody) || null
    },
    getAgentChatDistanceToBottom() {
      const body = this.getAgentChatBodyElement()
      if (!body) return 0
      return Math.max(0, body.scrollHeight - body.scrollTop - body.clientHeight)
    },
    isAgentChatNearBottom(thresholdPx = 24) {
      return this.getAgentChatDistanceToBottom() <= thresholdPx
    },
    setAgentAutoScrollLock(locked = false, options = {}) {
      const targetSessionId = asText((options && options.sessionId) || this.activeAgentSessionId || this.agentConversationId)
      if (!targetSessionId) return
      const patch = {
        autoScrollLocked: !!locked,
      }
      if (Object.prototype.hasOwnProperty.call(options || {}, 'sticky')) {
        patch.autoScrollSticky = !!options.sticky
      }
      if (Object.prototype.hasOwnProperty.call(options || {}, 'thresholdPx')) {
        patch.autoScrollThresholdPx = Number(options.thresholdPx || 0) || 24
      }
      this.setAgentRunState(targetSessionId, patch)
    },
    onAgentInnerScrollIntent() {
      const targetSessionId = asText(this.activeAgentSessionId || this.agentConversationId)
      if (!targetSessionId || !this.isAgentSessionRunning(targetSessionId)) return
      this.setAgentAutoScrollLock(true, { sessionId: targetSessionId })
    },
    onAgentChatBodyWheel() {
      const targetSessionId = asText(this.activeAgentSessionId || this.agentConversationId)
      if (!targetSessionId || !this.isAgentSessionRunning(targetSessionId)) return
      const nearBottom = this.isAgentChatNearBottom()
      this.setAgentAutoScrollLock(!nearBottom, { sessionId: targetSessionId, sticky: nearBottom })
    },
    onAgentChatBodyTouchMove() {
      this.onAgentChatBodyWheel()
    },
    onAgentChatBodyScroll() {
      if (Date.now() < Number(this.agentProgrammaticScrollUntil || 0)) return
      const targetSessionId = asText(this.activeAgentSessionId || this.agentConversationId)
      if (!targetSessionId || !this.isAgentSessionRunning(targetSessionId)) return
      const nearBottom = this.isAgentChatNearBottom()
      this.setAgentAutoScrollLock(!nearBottom, { sessionId: targetSessionId, sticky: nearBottom })
    },
    upsertAgentThinkingItem(seed = {}) {
      this.agentThinkingTimeline = upsertThinkingItemInList(this.agentThinkingTimeline, seed)
      return this.agentThinkingTimeline
    },
    upsertAgentTraceThinkingItem(seed = {}) {
      return this.upsertAgentThinkingItem(normalizeAgentTraceThinkingItem(seed))
    },
    upsertAgentReasoningDelta(seed = {}) {
      this.agentReasoningBlocks = upsertReasoningDeltaInList(this.agentReasoningBlocks, seed)
      return this.agentReasoningBlocks
    },
    clearAgentReasoningBlocks() {
      this.agentReasoningBlocks = []
    },
    scrollAgentThreadToLatest(options = {}) {
      const body = this.getAgentChatBodyElement()
      if (!body) return
      const behavior = options.behavior || 'smooth'
      this.agentProgrammaticScrollUntil = Date.now() + 120
      body.scrollTo({
        top: body.scrollHeight,
        behavior,
      })
    },
    maybeAutoScrollAgentThread(options = {}) {
      const targetSessionId = asText((options && options.sessionId) || this.activeAgentSessionId || this.agentConversationId)
      const force = !!(options && options.force)
      if (!targetSessionId) return
      const runState = this.getAgentRunState(targetSessionId)
      if (!runState) {
        if (force) {
          this.scrollAgentThreadToLatest({ behavior: 'auto' })
        }
        return
      }
      if (!force && runState.autoScrollLocked && !runState.autoScrollSticky) return
      this.scrollAgentThreadToLatest({ behavior: force ? 'auto' : 'smooth' })
    },
    markAgentSubmitProcessReady() {
      this.agentThinkingTimeline = upsertThinkingItemInList(
        completeActiveThinkingItemsInList(this.agentThinkingTimeline, 'frontend-submit-request'),
        normalizeAgentSubmitThinkingItem('completed'),
      )
    },
    completeAgentActiveProcessSteps(excludeId = '') {
      this.agentThinkingTimeline = completeActiveThinkingItemsInList(this.agentThinkingTimeline, excludeId)
    },
    updateAgentWaitingProcessFallback(sessionId = '') {
      const targetSessionId = asText(sessionId || this.activeAgentSessionId || this.agentConversationId)
      if (!targetSessionId) {
        if (!this.agentLoading || this.agentStreamState !== 'connecting') return
        const startedAt = Number(this.agentStreamStartedAt || 0)
        if (!startedAt) return
        const hasBackendStep = cloneArray(this.agentThinkingTimeline)
          .some((item) => {
            const id = asText(item && item.id)
            return id && id !== 'stream-connect' && !id.startsWith('frontend-')
          })
        if (hasBackendStep) return
        const elapsedSeconds = Math.floor((Number(this.agentStreamElapsedTick || Date.now()) - startedAt) / 1000)
        if (elapsedSeconds < 3) return
        this.markAgentSubmitProcessReady()
        const item = normalizeAgentWaitingThinkingItem(elapsedSeconds)
        this.completeAgentActiveProcessSteps(item.id)
        this.upsertAgentThinkingItem(item)
        return
      }
      const runState = this.getAgentRunState(targetSessionId)
      if (!runState || !runState.loading) return
      const elapsedMs = Number(runState.elapsedTick || Date.now()) - Number(runState.startedAt || Date.now())
      if (elapsedMs <= 0) return
      const elapsedSeconds = Math.max(1, Math.floor(elapsedMs / 1000))
      const steps = cloneArray(this.agentThinkingTimeline)
      const hasBackendStep = steps.some((item) => !String((item && item.id) || '').startsWith('frontend-'))
      if (hasBackendStep) return
      const fallbackItem = normalizeAgentWaitingThinkingItem(elapsedSeconds)
      this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
        ...session,
        status: 'running',
        thinkingTimeline: upsertThinkingItemInList(session.thinkingTimeline, fallbackItem),
      }))
    },
    getAgentThinkingElapsedLabel() {
      const startedAt = Number(this.agentStreamStartedAt || 0)
      if (!startedAt) return ''
      const tick = Number(this.agentStreamElapsedTick || Date.now())
      const seconds = Math.max(1, Math.floor((tick - startedAt) / 1000))
      return `${seconds}s`
    },
    resolvePanelPreloadTarget(trace = {}) {
      const toolName = asText(trace.tool_name || trace.toolName)
      const artifacts = normalizeAgentProducedArtifacts(trace)
      const hasArtifact = (expected) => artifacts.includes(expected)
      if (
        toolName === 'fetch_pois_in_scope'
        || hasArtifact('current_pois')
        || hasArtifact('current_poi_summary')
      ) {
        return { key: 'poi', label: '已预加载 POI 面板内容' }
      }
      if (
        toolName === 'compute_h3_metrics_from_scope_and_pois'
        || toolName === 'read_h3_structure_analysis'
        || hasArtifact('current_h3_structure_analysis')
        || hasArtifact('current_h3_metrics')
      ) {
        return { key: 'h3', label: '已预加载 H3 面板内容' }
      }
      if (
        toolName === 'compute_population_overview_from_scope'
        || toolName === 'read_population_profile_analysis'
        || hasArtifact('current_population_profile_analysis')
        || hasArtifact('population_overview')
      ) {
        return { key: 'population', label: '已预加载人口面板数据' }
      }
      if (
        toolName === 'compute_nightlight_overview_from_scope'
        || toolName === 'read_nightlight_pattern_analysis'
        || hasArtifact('current_nightlight_pattern_analysis')
        || hasArtifact('nightlight_overview')
      ) {
        return { key: 'nightlight', label: '已预加载夜光面板数据' }
      }
      if (
        toolName === 'compute_road_syntax_from_scope'
        || toolName === 'read_road_pattern_analysis'
        || hasArtifact('current_road_pattern_analysis')
        || hasArtifact('road_syntax_summary')
      ) {
        return { key: 'syntax', label: '已预加载路网面板展示' }
      }
      return null
    },
    hasAgentPreloadedPanel(key = '', sessionId = '') {
      const targetKey = asText(key)
      if (!targetKey) return false
      const targetSessionId = asText(sessionId || this.activeAgentSessionId || this.agentConversationId)
      if (!targetSessionId) return cloneArray(this.agentPreloadedPanelKeys).includes(targetKey)
      const runState = this.getAgentRunState(targetSessionId)
      if (!runState) return cloneArray(this.agentPreloadedPanelKeys).includes(targetKey)
      return cloneArray(runState.preloadedPanelKeys).includes(targetKey)
    },
    recordAgentPanelPreload(target = null, sessionId = '') {
      const key = asText(target && target.key)
      const label = asText(target && target.label)
      const targetSessionId = asText(sessionId || this.activeAgentSessionId || this.agentConversationId)
      if (!key || !label) return
      if (!targetSessionId) {
        if (this.hasAgentPreloadedPanel(key)) return
        this.agentPreloadedPanelKeys = [...cloneArray(this.agentPreloadedPanelKeys), key]
        this.agentPanelPreloadNotes = [
          ...normalizeAgentPanelPreloadNotes(this.agentPanelPreloadNotes),
          { key, label },
        ]
        return
      }
      if (this.hasAgentPreloadedPanel(key, targetSessionId)) return
      const runState = this.getAgentRunState(targetSessionId) || createAgentRunState()
      const nextPanelPreloadNotes = [
        ...normalizeAgentPanelPreloadNotes(runState.panelPreloadNotes),
        { key, label },
      ]
      const nextPreloadedPanelKeys = [...cloneArray(runState.preloadedPanelKeys), key]
      this.setAgentRunState(targetSessionId, {
        panelPreloadNotes: nextPanelPreloadNotes,
        preloadedPanelKeys: nextPreloadedPanelKeys,
      })
      this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
        ...session,
        panelPreloadNotes: nextPanelPreloadNotes,
        preloadedPanelKeys: nextPreloadedPanelKeys,
      }))
    },
    async preloadAgentPanelContent(target = null) {
      const key = asText(target && target.key)
      if (!key) return false
      if (key === 'poi') {
        if (typeof this.updatePoiCharts === 'function') {
          this.updatePoiCharts()
        }
        if (typeof this.resizePoiChart === 'function') {
          if (typeof this.$nextTick === 'function') {
            this.$nextTick(() => {
              this.resizePoiChart()
            })
          } else {
            this.resizePoiChart()
          }
        }
        return true
      }
      if (key === 'h3') {
        if (typeof this.ensureH3ReadyForAgentTarget === 'function') {
          const restored = await this.ensureH3ReadyForAgentTarget(this.getAgentActivePanelPayloads(), { allowCompute: false })
          if (!restored && typeof this.ensureH3PanelEntryState === 'function') {
            this.ensureH3PanelEntryState()
          }
        } else if (typeof this.ensureH3PanelEntryState === 'function') {
          this.ensureH3PanelEntryState()
        }
        if (typeof this.restoreH3GridDisplayOnEnter === 'function') {
          this.restoreH3GridDisplayOnEnter()
        }
        if (typeof this.updateH3Charts === 'function') {
          this.updateH3Charts()
        }
        if (typeof this.updateDecisionCards === 'function') {
          this.updateDecisionCards()
        }
        return true
      }
      if (key === 'population') {
        if (typeof this.ensurePopulationPanelEntryState === 'function') {
          await this.ensurePopulationPanelEntryState()
          return true
        }
        return false
      }
      if (key === 'nightlight') {
        if (typeof this.ensureNightlightPanelEntryState === 'function') {
          await this.ensureNightlightPanelEntryState()
          return true
        }
        return false
      }
      if (key === 'syntax') {
        if (!this.roadSyntaxSummary) return false
        const metricTabs = (typeof this.roadSyntaxMetricTabs === 'function')
          ? this.roadSyntaxMetricTabs().map((tab) => asText(tab && tab.value)).filter(Boolean)
          : ['connectivity', 'control', 'depth', 'choice', 'integration', 'intelligibility']
        const defaultMetric = typeof this.roadSyntaxDefaultMetric === 'function'
          ? asText(this.roadSyntaxDefaultMetric())
          : 'connectivity'
        const preferredMetric = asText(this.roadSyntaxLastMetricTab || this.roadSyntaxMetric || defaultMetric)
        const targetMetric = metricTabs.includes(preferredMetric) ? preferredMetric : defaultMetric
        if (typeof this.setRoadSyntaxMainTab === 'function') {
          this.setRoadSyntaxMainTab(targetMetric, { refresh: false, syncMetric: true })
        }
        if (typeof this.renderRoadSyntaxByMetric === 'function') {
          await this.renderRoadSyntaxByMetric(targetMetric)
        }
        return true
      }
      return false
    },
    async maybePreloadPanelForAgentTool(trace = {}, sessionId = '') {
      const targetSessionId = asText(sessionId || this.activeAgentSessionId || this.agentConversationId)
      const normalizedTrace = cloneObject(trace)
      const status = asText(normalizedTrace.status)
      if (status !== 'success') return false
      const target = this.resolvePanelPreloadTarget(normalizedTrace)
      if (!target) return false
      if (targetSessionId && this.hasAgentPreloadedPanel(target.key, targetSessionId)) return false
      if (!targetSessionId && this.hasAgentPreloadedPanel(target.key)) return false
      try {
        const didPreload = await this.preloadAgentPanelContent(target)
        if (!didPreload) return false
        this.recordAgentPanelPreload(target, targetSessionId)
        return true
      } catch (err) {
        console.warn(`Agent panel preload failed for ${target.key}`, err)
        return false
      }
    },
    getCurrentAgentHistoryId() {
      return asText(this.currentHistoryRecordId)
    },
    buildAgentAnalysisSnapshot() {
      const pois = Array.isArray(this.allPoisDetails) ? this.allPoisDetails.slice(0, 500) : []
      const poiTotal = Array.isArray(this.allPoisDetails) ? this.allPoisDetails.length : 0
      const populationSummary = (this.populationOverview && this.populationOverview.summary) || {}
      const nightlightSummary = (this.nightlightOverview && this.nightlightOverview.summary) || {}
      const h3Summary = this.h3AnalysisSummary || {}
      const roadSummary = this.roadSyntaxSummary || {}
      const isochroneFeature = typeof this._normalizeIsochroneFeatureForExport === 'function'
        ? this._normalizeIsochroneFeatureForExport()
        : null
      const frontendAnalysis = typeof this._buildFrontendAnalysisForExport === 'function'
        ? this._buildFrontendAnalysisForExport()
        : {}
      return {
        context: {
          mode: this.transportMode || 'walking',
          time_min: Number(this.timeHorizon || 0) || 0,
          source: this.resultDataSource || this.poiDataSource || '',
          scope_source: this.scopeSource || '',
          history_id: asText(this.currentHistoryRecordId),
        },
        scope: {
          polygon: this.getIsochronePolygonPayload(),
          drawn_polygon: (typeof this.getDrawnScopePolygonPoints === 'function') ? this.getDrawnScopePolygonPoints() : [],
          isochrone_feature: isochroneFeature,
        },
        pois,
        poi_summary: {
          total: poiTotal,
          source: this.resultDataSource || this.poiDataSource || '',
        },
        h3: {
          summary: h3Summary,
          charts: this.h3AnalysisCharts || {},
          grid_count: Number(h3Summary.grid_count || this.h3GridCount || 0),
        },
        road: {
          summary: roadSummary,
          diagnostics: this.roadSyntaxDiagnostics || {},
        },
        population: {
          summary: populationSummary,
        },
        nightlight: {
          summary: nightlightSummary,
        },
        frontend_analysis: frontendAnalysis,
        active_panel: String(this.activeStep3Panel || ''),
        current_filters: {
          poi_source: this.poiDataSource || '',
          h3_resolution: Number(this.h3GridResolution || 0) || 0,
          h3_neighbor_ring: Number(this.h3NeighborRing || 0) || 0,
          road_metric: String(this.roadSyntaxMetric || ''),
          population_view: String(this.populationAnalysisView || ''),
          nightlight_view: String(this.nightlightAnalysisView || ''),
        },
      }
    },
    extractAgentRiskToolName(prompt = '') {
      const match = String(prompt || '').match(/`([^`]+)`/)
      return match ? String(match[1] || '').trim() : ''
    },
    buildAgentSessionRequestPayload(session = null, overrides = {}) {
      const current = session || this.syncCurrentAgentSession() || this.findAgentSession(this.activeAgentSessionId)
      const merged = {
        ...(current || {}),
        ...overrides,
      }
      const messages = cloneArray(merged.messages)
      const titleSource = asText(merged.titleSource) || 'fallback'
      const title = ['user', 'ai'].includes(titleSource)
        ? (clampText(merged.title, 60) || deriveAgentSessionTitle(messages))
        : (clampText(merged.title, 60) || deriveAgentSessionTitle(messages))
      return {
        title,
        history_id: asText(merged.historyId) || this.getCurrentAgentHistoryId(),
        panel_kind: asText(merged.panelKind),
        preview: clampText(merged.preview, 120) || deriveAgentSessionPreview(merged),
        status: asText(merged.status || 'idle') || 'idle',
        stage: asText(merged.stage || 'gating') || 'gating',
        is_pinned: Object.prototype.hasOwnProperty.call(overrides || {}, 'isPinned')
          ? !!overrides.isPinned
          : !!merged.isPinned,
        input: String(merged.input || ''),
        messages: messages.map((item) => ({
          role: asText(item && item.role) || 'user',
          content: String((item && item.content) || ''),
        })),
        output: {
          cards: cloneArray(merged.cards),
          clarification_question: String(merged.clarificationQuestion || ''),
          clarification_options: cloneArray(merged.clarificationOptions).map((item) => asText(item)).filter(Boolean),
          risk_prompt: String(merged.riskPrompt || ''),
          next_suggestions: cloneArray(merged.nextSuggestions),
          panel_payloads: cloneObject(merged.panelPayloads),
          decision: {
            summary: asText(merged.decision && merged.decision.summary),
            mode: asText(merged.decision && merged.decision.mode) || 'judgment',
            strength: asText(merged.decision && merged.decision.strength) || 'weak',
            can_act: !!(merged.decision && merged.decision.canAct),
          },
          support: cloneArray(merged.support).map((item) => ({
            key: asText(item && item.key),
            metric: asText(item && item.metric),
            headline: asText(item && item.headline),
            value: item && Object.prototype.hasOwnProperty.call(item, 'value') ? item.value : null,
            interpretation: asText(item && item.interpretation),
            source: asText(item && item.source),
            confidence: asText(item && item.confidence) || 'weak',
            limitation: asText(item && item.limitation),
            supports: cloneArray(item && item.supports).map((entry) => asText(entry)).filter(Boolean),
            is_key: !!(item && item.isKey),
          })),
          counterpoints: cloneArray(merged.counterpoints).map((item) => ({
            kind: asText(item && item.kind) || 'boundary',
            title: asText(item && item.title),
            detail: asText(item && item.detail),
          })),
          actions: cloneArray(merged.actions).map((item) => ({
            title: asText(item && item.title),
            detail: asText(item && item.detail),
            condition: asText(item && item.condition),
            target: asText(item && item.target),
            prompt: asText(item && item.prompt),
          })),
          boundary: cloneArray(merged.boundary).map((item) => ({
            title: asText(item && item.title),
            detail: asText(item && item.detail),
          })),
        },
        diagnostics: {
          execution_trace: cloneArray(merged.executionTrace),
          used_tools: cloneArray(merged.usedTools),
          citations: cloneArray(merged.citations),
          research_notes: cloneArray(merged.researchNotes),
          audit_issues: cloneArray(merged.auditIssues),
          planning_summary: String((merged.diagnostics && merged.diagnostics.planningSummary) || (merged.plan && merged.plan.summary) || ''),
          audit_summary: String((merged.diagnostics && merged.diagnostics.auditSummary) || ''),
          replan_count: Number((merged.diagnostics && merged.diagnostics.replanCount) || 0) || 0,
          thinking_timeline: cloneArray(merged.thinkingTimeline),
          error: String(merged.error || ''),
        },
        context_summary: cloneObject(merged.contextSummary),
        plan: {
          steps: cloneArray(merged.plan && merged.plan.steps),
          followup_steps: cloneArray(merged.plan && merged.plan.followupSteps),
          followup_applied: !!(merged.plan && merged.plan.followupApplied),
          summary: String((merged.plan && merged.plan.summary) || ''),
        },
        risk_confirmations: cloneArray(merged.riskConfirmations),
      }
    },
    async putAgentSession(sessionId = '', overrides = {}) {
      const nextId = asText(sessionId)
      if (!nextId) {
        throw new Error('missing agent session id')
      }
      const session = this.findAgentSession(nextId)
      const body = this.buildAgentSessionRequestPayload(session, overrides)
      const res = await fetch(`/api/v1/analysis/agent/sessions/${encodeURIComponent(nextId)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        throw new Error(`/api/v1/analysis/agent/sessions/${nextId} PUT 失败(${res.status})`)
      }
      const detail = await res.json()
      return this.mergeAgentSessionDetail(detail)
    },
    async patchAgentSessionMetadata(sessionId = '', payload = {}) {
      const nextId = asText(sessionId)
      if (!nextId) {
        throw new Error('missing agent session id')
      }
      const res = await fetch(`/api/v1/analysis/agent/sessions/${encodeURIComponent(nextId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        throw new Error(`/api/v1/analysis/agent/sessions/${nextId} PATCH 失败(${res.status})`)
      }
      const detail = await res.json()
      return this.mergeAgentSessionDetail(detail)
    },
    buildTurnContext(options = {}) {
      const question = String((options && options.prompt) || this.agentInput || '').trim()
      if (!question || this.agentSessionHydrating) return null
      this.ensureAgentPanelReady()
      if (typeof this.ensureAgentFollowupTabForPrompt === 'function') {
        this.ensureAgentFollowupTabForPrompt(question)
      }
      const currentSession = this.syncCurrentAgentSession() || this.readSessionState(this.activeAgentSessionId)
      const targetSessionId = asText((currentSession && currentSession.id) || this.activeAgentSessionId || this.agentConversationId) || this.createAgentSession().id
      const wasPersisted = !!(currentSession && currentSession.persisted)
      const historyId = this.getCurrentAgentHistoryId()
      const requestAbortController = typeof AbortController !== 'undefined' ? new AbortController() : null
      const requestRiskConfirmations = Array.isArray(options && options.riskConfirmations)
        ? options.riskConfirmations
        : this.agentRiskConfirmations
      let baseMessages = cloneArray((currentSession && currentSession.messages) || [])
      if (!baseMessages.length && typeof this.getAgentActiveFollowupTab === 'function') {
        const activeFollowupTab = this.getAgentActiveFollowupTab()
        const threadMessages = cloneArray(activeFollowupTab && activeFollowupTab.thread && activeFollowupTab.thread.messages)
        if (threadMessages.length) {
          baseMessages = threadMessages
        }
      }
      if (!baseMessages.length) {
        baseMessages = cloneArray(this.agentMessages)
      }
      const nextMessages = [...baseMessages, { role: 'user', content: question }]
      return {
        question,
        currentSession,
        targetSessionId,
        wasPersisted,
        historyId,
        requestAbortController,
        requestRiskConfirmations,
        nextMessages,
      }
    },
    async consumeTurnStream(res, handler) {
      await consumeSseStream(res, handler)
    },
    async commitTurnResult(turnContext = {}, finalResponse = null) {
      const targetSessionId = asText(turnContext.targetSessionId)
      this.stopAgentThinkingTimer(targetSessionId)
      if (!turnContext.wasPersisted && String((finalResponse || {}).status || '') === 'answered') {
        try {
          await this.loadAgentSessionDetail(targetSessionId)
        } catch (detailErr) {
          console.warn('Agent session detail load failed after first streamed turn', detailErr)
        }
      }
    },
    syncUiAfterTurn(turnContext = {}) {
      const targetSessionId = asText(turnContext.targetSessionId)
      this.stopAgentThinkingTimer(targetSessionId)
      const runState = this.getAgentRunState(targetSessionId)
      if (runState && runState.abortController === turnContext.requestAbortController) {
        this.clearAgentRunState(targetSessionId)
      }
      if (targetSessionId === asText(this.activeAgentSessionId)) {
        this.agentClarificationSubmitting = false
        this.syncActiveAgentRuntimeView(targetSessionId)
      }
    },
    async submitAgentTurn(options = {}) {
      const turnContext = this.buildTurnContext(options)
      if (!turnContext) return
      const {
        question,
        targetSessionId,
        wasPersisted,
        historyId,
        requestAbortController,
        requestRiskConfirmations,
        nextMessages,
      } = turnContext
      this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
        ...session,
        panelKind: 'followup',
        persisted: wasPersisted,
        snapshotLoaded: true,
        historyId,
        input: '',
        messages: nextMessages,
        cards: [],
        executionTrace: [],
        usedTools: [],
        citations: [],
        researchNotes: [],
        auditIssues: [],
        nextSuggestions: [],
        clarificationQuestion: '',
        clarificationOptions: [],
        pendingTaskConfirmation: null,
        riskPrompt: '',
        error: '',
        contextSummary: {},
        plan: normalizeAgentPlanEnvelope(),
        riskConfirmations: cloneArray(requestRiskConfirmations),
        panelPreloadNotes: [],
        preloadedPanelKeys: [],
        status: 'running',
        stage: 'gating',
        thinkingTimeline: [normalizeAgentSubmitThinkingItem('active')],
      }))
      this.setAgentRunState(targetSessionId, {
        abortController: requestAbortController,
        loading: true,
        streamState: 'connecting',
        streamingMessageId: `agent-stream-${Date.now().toString(36)}`,
        reasoningBlocks: [],
        panelPreloadNotes: [],
        preloadedPanelKeys: [],
        pendingQuestion: question,
        autoScrollLocked: false,
        autoScrollSticky: true,
        autoScrollThresholdPx: 24,
      })
      this.agentTurnAbortController = targetSessionId === asText(this.activeAgentSessionId) ? requestAbortController : null
      this.agentInput = ''
      this.agentClarificationDraft = ''
      this.agentClarificationSubmitting = false
      this.agentThinkingExpanded = true
      this.agentPlanExpanded = true
      this.agentTraceExpanded = true
      this.startAgentThinkingTimer(targetSessionId)
      try {
        if (targetSessionId === asText(this.activeAgentSessionId)) {
          this.maybeAutoScrollAgentThread({ sessionId: targetSessionId, force: true })
        }

        const res = await fetch('/api/v1/analysis/agent/turn/stream', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          signal: requestAbortController ? requestAbortController.signal : undefined,
          body: JSON.stringify({
            conversation_id: targetSessionId,
            history_id: historyId,
            governance_mode: 'auto',
            messages: nextMessages,
            analysis_snapshot: this.buildAgentAnalysisSnapshot(),
            risk_confirmations: requestRiskConfirmations,
          }),
        })
        if (!res.ok) {
          throw new Error(`/api/v1/analysis/agent/turn/stream 请求失败(${res.status})`)
        }
        let finalResponse = null
        await this.consumeTurnStream(res, ({ type, payload }) => {
          const markStreamActive = () => {
            this.setAgentRunState(targetSessionId, { streamState: 'streaming' })
            if (targetSessionId === asText(this.activeAgentSessionId)) {
              this.maybeAutoScrollAgentThread({ sessionId: targetSessionId })
            }
          }
          if (type === 'meta') {
            return
          }
          if (type === 'status') {
            const item = normalizeAgentStatusThinkingItem(payload)
            this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
              ...session,
              stage: asText(payload && payload.stage) || session.stage || 'gating',
              status: 'running',
              thinkingTimeline: upsertThinkingItemInList(
                completeActiveThinkingItemsInList(
                  upsertThinkingItemInList(session.thinkingTimeline, normalizeAgentSubmitThinkingItem('completed')),
                  item.id,
                ),
                item,
              ),
            }))
            markStreamActive()
            if (targetSessionId === asText(this.activeAgentSessionId)) {
              this.agentThinkingExpanded = true
            }
            return
          }
          if (type === 'thinking') {
            const item = normalizeAgentThinkingItem(payload)
            this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
              ...session,
              status: 'running',
              thinkingTimeline: upsertThinkingItemInList(
                completeActiveThinkingItemsInList(
                  upsertThinkingItemInList(session.thinkingTimeline, normalizeAgentSubmitThinkingItem('completed')),
                  item.id,
                ),
                item,
              ),
            }))
            markStreamActive()
            if (targetSessionId === asText(this.activeAgentSessionId)) {
              this.agentThinkingExpanded = true
            }
            return
          }
          if (type === 'plan') {
            const nextPlan = normalizeAgentPlanEnvelope(payload)
            const planItem = normalizeAgentPlanThinkingItem(payload)
            const currentSessionSnapshot = this.findAgentSession(targetSessionId)
            const hadPlan = !!(
              currentSessionSnapshot
              && currentSessionSnapshot.plan
              && (cloneArray(currentSessionSnapshot.plan.steps).length || cloneArray(currentSessionSnapshot.plan.followupSteps).length)
            )
            this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
              ...session,
              status: 'running',
              plan: nextPlan,
              thinkingTimeline: upsertThinkingItemInList(
                completeActiveThinkingItemsInList(session.thinkingTimeline, planItem.id),
                planItem,
              ),
            }))
            if (!hadPlan && (nextPlan.steps.length || nextPlan.followupSteps.length) && targetSessionId === asText(this.activeAgentSessionId)) {
              this.agentPlanExpanded = true
            }
            markStreamActive()
            if (targetSessionId === asText(this.activeAgentSessionId)) {
              this.agentThinkingExpanded = true
              this.agentTraceExpanded = true
            }
            return
          }
          if (type === 'reasoning_delta') {
            const runState = this.getAgentRunState(targetSessionId) || createAgentRunState()
            this.setAgentRunState(targetSessionId, {
              reasoningBlocks: upsertReasoningDeltaInList(runState.reasoningBlocks, payload),
              streamState: 'streaming',
            })
            if (targetSessionId === asText(this.activeAgentSessionId)) {
              this.maybeAutoScrollAgentThread({ sessionId: targetSessionId })
            }
            return
          }
          if (type === 'trace') {
            const item = normalizeAgentTraceThinkingItem(payload)
            this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
              ...session,
              status: 'running',
              thinkingTimeline: upsertThinkingItemInList(
                completeActiveThinkingItemsInList(
                  upsertThinkingItemInList(session.thinkingTimeline, normalizeAgentSubmitThinkingItem('completed')),
                  item.id,
                ),
                item,
              ),
              executionTrace: [...cloneArray(session.executionTrace), cloneObject(payload)],
            }))
            this.maybePreloadPanelForAgentTool(payload, targetSessionId).then((didPreload) => {
              if (didPreload) {
                if (targetSessionId === asText(this.activeAgentSessionId)) {
                  this.maybeAutoScrollAgentThread({ sessionId: targetSessionId })
                }
              }
            })
            markStreamActive()
            if (targetSessionId === asText(this.activeAgentSessionId)) {
              this.agentThinkingExpanded = true
            }
            return
          }
          if (type === 'error') {
            const errorMessage = asText(payload && payload.message)
            const item = normalizeAgentStatusThinkingItem({
              stage: 'failed',
              message: errorMessage,
            })
            this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
              ...session,
              status: 'failed',
              stage: 'failed',
              error: errorMessage,
              thinkingTimeline: upsertThinkingItemInList(
                completeActiveThinkingItemsInList(session.thinkingTimeline, item.id),
                item,
              ),
            }))
            this.setAgentRunState(targetSessionId, { streamState: 'failed' })
            if (targetSessionId === asText(this.activeAgentSessionId)) {
              this.agentThinkingExpanded = true
            }
            return
          }
          if (type !== 'final') return

          const responsePayload = payload && typeof payload === 'object' ? payload.response || {} : {}
          finalResponse = responsePayload
          const turn = normalizeAgentTurnPayload(responsePayload)
          const nextStatus = asText(responsePayload.status || 'answered') || 'answered'
          const nextStage = asText(responsePayload.stage || turn.stage || 'answered') || 'answered'
          const pendingTaskConfirmation = nextStatus === 'answered'
            ? buildAnalysisTaskConfirmationFromTurn(this, turn)
            : null
          const currentSessionSnapshot = this.findAgentSession(targetSessionId) || {}
          let nextThinkingTimeline = mergeAgentThinkingTimeline(
            cloneArray(currentSessionSnapshot.thinkingTimeline),
            cloneArray(turn.diagnostics.thinkingTimeline),
          )
          if (['answered', 'failed'].includes(nextStatus)) {
            const finalStatusItem = normalizeAgentStatusThinkingItem({
              stage: nextStatus === 'answered' ? 'answered' : 'failed',
              message: turn.diagnostics.error,
            })
            nextThinkingTimeline = upsertThinkingItemInList(
              completeActiveThinkingItemsInList(nextThinkingTimeline, finalStatusItem.id),
              finalStatusItem,
            )
          }
          this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
            ...session,
            panelKind: 'followup',
            persisted: true,
            snapshotLoaded: true,
            status: nextStatus,
            stage: nextStage,
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
            thinkingTimeline: nextThinkingTimeline,
            nextSuggestions: cloneArray(turn.output.nextSuggestions),
            clarificationQuestion: String(turn.output.clarificationQuestion || ''),
            clarificationOptions: cloneArray(turn.output.clarificationOptions),
            pendingTaskConfirmation,
            riskPrompt: String(turn.output.riskPrompt || ''),
            error: String(turn.diagnostics.error || ''),
            contextSummary: cloneObject(turn.contextSummary),
            plan: normalizeAgentPlanEnvelope(turn.plan),
            panelPayloads: (() => {
              const mergedPayloads = {
                ...cloneObject(session.panelPayloads),
                ...cloneObject(turn.output.panelPayloads),
              }
              if (session.panelPayloads && session.panelPayloads.summary_pack) {
                mergedPayloads.summary_pack = cloneObject(session.panelPayloads.summary_pack)
              }
              if (typeof this.buildAgentTabsUiState === 'function') {
                mergedPayloads.agent_tabs = this.buildAgentTabsUiState()
              }
              return mergedPayloads
            })(),
            messages: nextStatus === 'answered' ? cloneArray(nextMessages) : cloneArray(session.messages),
            riskConfirmations: nextStatus === 'answered' ? [] : cloneArray(requestRiskConfirmations),
          }))
          if (targetSessionId === asText(this.activeAgentSessionId) && turn.output.panelPayloads && turn.output.panelPayloads.h3_result) {
            this.preloadAgentPanelContent({ key: 'h3', label: '已预加载 H3 面板内容' }).catch((err) => {
              console.warn('Agent H3 hydrate after final failed', err)
            })
          }
          this.setAgentRunState(targetSessionId, {
            streamState: nextStatus === 'failed' ? 'failed' : 'completed',
          })
          if (targetSessionId === asText(this.activeAgentSessionId)) {
            this.agentClarificationDraft = ''
            this.agentClarificationSubmitting = false
            if (['failed', 'requires_risk_confirmation'].includes(nextStatus)) {
              this.agentThinkingExpanded = Array.isArray(nextThinkingTimeline) && nextThinkingTimeline.length > 0
              this.agentPlanExpanded = hasAgentPlanContent(turn.plan)
              this.agentTraceExpanded = hasAgentExecutionTraceContent(turn.diagnostics.executionTrace)
            }
            this.maybeAutoScrollAgentThread({ sessionId: targetSessionId })
          }
        })
        if (!finalResponse) {
          throw new Error('Agent 流式执行未返回最终结果')
        }
        await this.commitTurnResult(turnContext, finalResponse)
      } catch (err) {
        if (err && (err.name === 'AbortError' || String(err.message || '').includes('aborted'))) {
          this.stopAgentThinkingTimer(targetSessionId)
          this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
            ...session,
            input: question,
            status: 'idle',
            stage: 'gating',
            cards: [],
            executionTrace: [],
            usedTools: [],
            citations: [],
            researchNotes: [],
            auditIssues: [],
            nextSuggestions: [],
            clarificationQuestion: '',
            clarificationOptions: [],
            pendingTaskConfirmation: null,
            riskPrompt: '',
            error: '',
            contextSummary: cloneObject(session.contextSummary),
            plan: normalizeAgentPlanEnvelope(),
            thinkingTimeline: [],
          }))
          if (targetSessionId === asText(this.activeAgentSessionId)) {
            this.agentInput = question
            this.agentClarificationDraft = ''
            this.agentClarificationSubmitting = false
          }
          return
        }
        console.error(err)
        const item = normalizeAgentStatusThinkingItem({
          stage: 'failed',
          message: 'Agent 执行失败: ' + (err && err.message ? err.message : String(err)),
        })
        this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
          ...session,
          status: 'failed',
          stage: 'failed',
          error: 'Agent 执行失败: ' + (err && err.message ? err.message : String(err)),
          thinkingTimeline: upsertThinkingItemInList(
            completeActiveThinkingItemsInList(session.thinkingTimeline, item.id),
            item,
          ),
        }))
        this.setAgentRunState(targetSessionId, { streamState: 'failed' })
        if (targetSessionId === asText(this.activeAgentSessionId)) {
          this.agentClarificationSubmitting = false
          this.agentThinkingExpanded = true
        }
      } finally {
        this.syncUiAfterTurn(turnContext)
      }
    },
    cancelAgentTurn(sessionId = '') {
      const runState = this.getAgentRunState(sessionId || this.activeAgentSessionId || this.agentConversationId)
      const controller = runState && runState.abortController
      if (!controller) return
      try {
        controller.abort()
      } catch (_) {
        // Ignore abort errors from already-settled controllers.
      }
    },
    async confirmAgentRiskAndRetry() {
      const toolName = this.extractAgentRiskToolName(this.agentRiskPrompt)
      if (!toolName) return
      this.agentRiskConfirmations = [toolName]
      await this.submitAgentTurn({
        prompt: this.agentInput || (this.agentMessages.length ? this.agentMessages[this.agentMessages.length - 1].content : ''),
        riskConfirmations: [toolName],
      })
    },
  }
}

export { createAgentRuntimeMethods }
