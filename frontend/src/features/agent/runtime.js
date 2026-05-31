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
  getAgentSummaryCardContent,
  hasAgentMessageProcessContent,
  mergeAgentThinkingTimeline,
  normalizeAgentAction,
  normalizeAgentBoundaryItem,
  normalizeAgentCounterpoint,
  normalizeAgentDecision,
  normalizeAgentDecisionEvidence,
  normalizeAgentAttachments,
  normalizeAgentMessageProcess,
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
import { buildAnalysisTaskParamBundle, buildAnalysisTaskParamBundles } from './analysis-task-params.js'

function createAgentRuntimeMethods() {
  return {
    buildAgentDeepThinkingWorkflowPrompt() {
      return [
        '深度思考审查视角：',
        '1. 空间自洽：检查人口、POI、夜光、路网、等时圈和边界之间是否互相支撑；明确耦合、错位和不能证明的关系。',
        '2. 证据可靠：区分“已有证据可支持”“只能趋势推断”“还需要补证据”；不要把人口、POI、夜光直接等同于消费额、客流或经营质量。',
        '3. 规划转译：把空间和数据判断转成可执行的定位、客群、业态组合、空间组织、运营动作，并标注约束和风险。',
        '4. 评审表达：最后输出可写回报告的结构化模块，包含核心判断、证据依据、风险边界和 3 个下一步追问。',
      ].join('\n')
    },
    buildAgentDeepAnalysisPrompt(question = '', targetSeed = null) {
      const target = typeof this.normalizeContextAskTarget === 'function'
        ? this.normalizeContextAskTarget(targetSeed)
        : cloneObject(targetSeed)
      const mode = asText(this.agentDeepAnalysisMode) === 'deep' ? 'deep' : 'quick'
      const title = asText(target && target.title) || '当前对象'
      const source = asText(target && target.source) || 'report'
      const summary = asText(target && target.summary)
      const evidence = cloneArray(target && target.evidence)
        .map((item) => (typeof item === 'string' ? item : JSON.stringify(item)))
        .filter(Boolean)
        .slice(0, 8)
      const parts = [
        mode === 'deep'
          ? '请把下面的问题作为“深度思考继续分析任务”处理：先重写问题，再盘点证据，规划工具，执行或复用分析结果，最后输出可写回报告的新模块。'
          : '请把下面的问题作为“快速继续分析任务”处理：优先复用已有证据，必要时少量调用工具，快速输出可写回报告的新模块。',
        `执行模式：${mode === 'deep' ? '深度思考' : '快速分析'}`,
        `当前对象：${title}`,
        `对象来源：${source}`,
      ]
      if (summary) parts.push(`对象摘要：${summary}`)
      if (evidence.length) parts.push(`已有证据：${evidence.join('；')}`)
      if (mode === 'deep') parts.push(this.buildAgentDeepThinkingWorkflowPrompt())
      parts.push(`用户问题：${asText(question)}`)
      return parts.join('\n')
    },
    normalizeAgentSiteSelectionScope() {
      const normalizeRing = (raw) => {
        if (!Array.isArray(raw) || !raw.length) return []
        if (typeof this._closePolygonRing === 'function' && typeof this.normalizePath === 'function') {
          const ring = this._closePolygonRing(this.normalizePath(raw, 3, 'agent.site_selection.scope'))
          return Array.isArray(ring) && ring.length >= 4 ? ring : []
        }
        const points = raw
          .filter((pt) => Array.isArray(pt) && pt.length >= 2)
          .map((pt) => [Number(pt[0]), Number(pt[1])])
          .filter((pt) => Number.isFinite(pt[0]) && Number.isFinite(pt[1]))
        if (points.length < 3) return []
        const first = points[0]
        const last = points[points.length - 1]
        if (Math.abs(first[0] - last[0]) > 1e-8 || Math.abs(first[1] - last[1]) > 1e-8) {
          points.push([first[0], first[1]])
        }
        return points.length >= 4 ? points : []
      }
      const normalizePayload = (raw) => {
        if (!Array.isArray(raw) || !raw.length) return []
        const direct = normalizeRing(raw)
        if (direct.length) return direct
        const rings = []
        raw.forEach((item) => {
          const ring = normalizeRing(item)
          if (ring.length) rings.push(ring)
          else if (Array.isArray(item) && Array.isArray(item[0])) {
            const outer = normalizeRing(item[0])
            if (outer.length) rings.push(outer)
          }
        })
        return rings.length === 1 ? rings[0] : rings
      }
      const polygon = typeof this.getIsochronePolygonPayload === 'function'
        ? normalizePayload(this.getIsochronePolygonPayload())
        : []
      const drawnPolygon = typeof this.getDrawnScopePolygonPoints === 'function'
        ? normalizeRing(this.getDrawnScopePolygonPoints())
        : []
      const isochroneFeature = typeof this._normalizeIsochroneFeatureForExport === 'function'
        ? this._normalizeIsochroneFeatureForExport()
        : null
      let featurePolygon = []
      const geometry = isochroneFeature && isochroneFeature.geometry ? isochroneFeature.geometry : null
      if (geometry && Array.isArray(geometry.coordinates)) {
        featurePolygon = normalizePayload(geometry.type === 'Polygon' ? geometry.coordinates[0] : geometry.coordinates)
      }
      const activePolygon = polygon.length ? polygon : (drawnPolygon.length ? drawnPolygon : featurePolygon)
      return {
        hasScope: Array.isArray(activePolygon) && activePolygon.length > 0,
        polygon: activePolygon,
        drawnPolygon,
        isochroneFeature,
      }
    },
    getAgentRunState(sessionId = '') {
      const nextId = this.getActiveAgentSessionId(sessionId)
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
      const nextId = this.getActiveAgentSessionId(sessionId)
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
      const targetSessionId = this.getActiveAgentSessionId(sessionId)
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
      const targetSessionId = this.getActiveAgentSessionId(sessionId)
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
      const targetSessionId = this.getActiveAgentSessionId(sessionId)
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
    getAgentReportThreadElement() {
      return (this.$refs && this.$refs.agentReportThreadBody) || null
    },
    getAgentReportThreadDistanceToBottom() {
      const body = this.getAgentReportThreadElement()
      if (!body) return 0
      return Math.max(0, body.scrollHeight - body.scrollTop - body.clientHeight)
    },
    isAgentReportThreadNearBottom(thresholdPx = 24) {
      return this.getAgentReportThreadDistanceToBottom() <= thresholdPx
    },
    setAgentAutoScrollLock(locked = false, options = {}) {
      const targetSessionId = this.getActiveAgentSessionId(options && options.sessionId)
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
      const targetSessionId = this.getActiveAgentSessionId()
      if (!targetSessionId || !this.isAgentSessionRunning(targetSessionId)) return
      this.setAgentAutoScrollLock(true, { sessionId: targetSessionId })
    },
    onAgentReportThreadWheel() {
      const targetSessionId = this.getActiveAgentSessionId()
      if (!targetSessionId || !this.isAgentSessionRunning(targetSessionId)) return
      const nearBottom = this.isAgentReportThreadNearBottom()
      this.setAgentAutoScrollLock(!nearBottom, { sessionId: targetSessionId, sticky: nearBottom })
    },
    onAgentReportThreadTouchMove() {
      this.onAgentReportThreadWheel()
    },
    onAgentReportThreadScroll() {
      if (Date.now() < Number(this.agentProgrammaticScrollUntil || 0)) return
      const targetSessionId = this.getActiveAgentSessionId()
      if (!targetSessionId || !this.isAgentSessionRunning(targetSessionId)) return
      const nearBottom = this.isAgentReportThreadNearBottom()
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
      const body = this.getAgentReportThreadElement()
      if (!body) return
      const behavior = options.behavior || 'smooth'
      this.agentProgrammaticScrollUntil = Date.now() + 120
      body.scrollTo({
        top: body.scrollHeight,
        behavior,
      })
    },
    maybeAutoScrollAgentThread(options = {}) {
      const targetSessionId = this.getActiveAgentSessionId(options && options.sessionId)
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
      const targetSessionId = this.getActiveAgentSessionId(sessionId)
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
      const tick = Number(this.agentStreamElapsedTick || startedAt)
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
        || hasArtifact('current_poi_h3_summary')
        || hasArtifact('current_poi_h3_grid')
        || hasArtifact('current_poi_h3_charts')
      ) {
        return { key: 'h3', label: '已预加载 POI H3 面板内容' }
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
      const targetSessionId = this.getActiveAgentSessionId(sessionId)
      if (!targetSessionId) return cloneArray(this.agentPreloadedPanelKeys).includes(targetKey)
      const runState = this.getAgentRunState(targetSessionId)
      if (!runState) return cloneArray(this.agentPreloadedPanelKeys).includes(targetKey)
      return cloneArray(runState.preloadedPanelKeys).includes(targetKey)
    },
    recordAgentPanelPreload(target = null, sessionId = '') {
      const key = asText(target && target.key)
      const label = asText(target && target.label)
      const targetSessionId = this.getActiveAgentSessionId(sessionId)
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
      const targetSessionId = this.getActiveAgentSessionId(sessionId)
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
    buildAgentPoiGridEvidence() {
      const toNumber = (value, fallback = 0) => {
        const parsed = Number(value)
        return Number.isFinite(parsed) ? parsed : fallback
      }
      const bundle = buildAnalysisTaskParamBundle(this, 'poi_raster_grid')
      const params = cloneObject(bundle.params)
      const resultRefs = cloneObject(bundle.result_refs)
      return {
        evidence_version: 'poi_raster_grid_evidence_v1',
        current_display_grid_type: 'raster',
        computed_grid_types: ['raster'],
        params: {
          current_display_grid_type: 'raster',
          computed_grid_types: ['raster'],
          poi_source: asText(params.poi_source),
          poi_year: params.poi_year,
          poi_years: cloneArray(params.poi_years),
          poi_coord_type: asText(params.poi_coord_type),
          raster: cloneObject(params || {}),
        },
        raster_summary: cloneObject(resultRefs.raster_summary || this.poiGridSummary || {}),
        raster_counts: cloneObject(resultRefs.raster_counts || {}),
        notes: [
          'POI raster grid uses the same cell_id system as population and nightlight.',
          'H3 evidence is exposed separately as poi_h3_evidence_v1.',
        ],
      }
    },
    buildAgentPoiH3Evidence() {
      const toNumber = (value, fallback = 0) => {
        const parsed = Number(value)
        return Number.isFinite(parsed) ? parsed : fallback
      }
      const pickMetricProps = (props = {}) => ({
        h3_id: asText(props.h3_id),
        poi_count: toNumber(props.poi_count, 0),
        density_poi_per_km2: toNumber(props.density_poi_per_km2, 0),
        local_entropy: toNumber(props.local_entropy, 0),
        neighbor_mean_density: toNumber(props.neighbor_mean_density, 0),
        neighbor_mean_entropy: toNumber(props.neighbor_mean_entropy, 0),
        neighbor_count: toNumber(props.neighbor_count, 0),
        category_counts: cloneObject(props.category_counts || {}),
        subcategory_counts: cloneObject(props.subcategory_counts || {}),
        lisa_i: Number.isFinite(Number(props.lisa_i)) ? Number(props.lisa_i) : null,
        lisa_z_score: Number.isFinite(Number(props.lisa_z_score)) ? Number(props.lisa_z_score) : null,
        gi_star_value: Number.isFinite(Number(props.gi_star_value)) ? Number(props.gi_star_value) : null,
        gi_star_z_score: Number.isFinite(Number(props.gi_star_z_score)) ? Number(props.gi_star_z_score) : null,
      })
      const scoreCell = (cell = {}) => (
        toNumber(cell.poi_count, 0) * 10
        + toNumber(cell.density_poi_per_km2, 0)
        + Math.abs(toNumber(cell.gi_star_z_score, 0)) * 120
        + Math.abs(toNumber(cell.lisa_z_score, 0)) * 80
        + toNumber(cell.local_entropy, 0) * 30
      )
      const compactRows = (section = {}, limit = 40) => cloneArray(section && section.rows).slice(0, limit)
      const compactSummary = (section = {}) => {
        const source = cloneObject(section)
        delete source.rows
        return source
      }
      const bundle = buildAnalysisTaskParamBundle(this, 'poi_h3_grid')
      const params = cloneObject(bundle.params)
      const summary = cloneObject(this.h3AnalysisSummary || {})
      const charts = cloneObject(this.h3AnalysisCharts || {})
      const features = cloneArray(this.h3AnalysisGridFeatures)
      const allCells = features
        .map((feature) => pickMetricProps((feature && feature.properties) || {}))
        .filter((cell) => asText(cell && cell.h3_id))
      const cells = allCells
        .slice()
        .sort((a, b) => scoreCell(b) - scoreCell(a))
        .slice(0, 40)
      const derivedStats = cloneObject(this.h3DerivedStats || {})
      return {
        evidence_version: 'poi_h3_evidence_v1',
        grid_type: 'h3',
        usage: 'POI-only spatial structure evidence; do not use it for population or nightlight coupling.',
        params,
        summary,
        charts,
        cells,
        derived_stats: {
          structure_rows: compactRows(derivedStats.structureSummary),
          typing_rows: compactRows(derivedStats.typingSummary),
          lq_rows: compactRows(derivedStats.lqSummary),
          gap_rows: compactRows(derivedStats.gapSummary),
          structure_summary: compactSummary(derivedStats.structureSummary),
          typing_summary: compactSummary(derivedStats.typingSummary),
          lq_summary: compactSummary(derivedStats.lqSummary),
          gap_summary: compactSummary(derivedStats.gapSummary),
        },
        ui: {
          target_category: asText(this.h3TargetCategory),
          target_category_label: typeof this._getH3CategoryLabel === 'function' ? asText(this._getH3CategoryLabel(this.h3TargetCategory)) : '',
          metric_view: asText(this.h3MetricView || 'density'),
          structure_fill_mode: asText(this.h3StructureFillMode || 'gi_z'),
          only_significant: !!this.h3OnlySignificant,
          entropy_min_poi: toNumber(this.h3EntropyMinPoi, 3),
          lq_smoothing_alpha: toNumber(this.h3LqSmoothingAlpha, 0.5),
        },
        category_meta: cloneArray(this.h3CategoryMeta),
        counts: {
          grid_count: toNumber(summary.grid_count || this.h3GridCount, 0),
          poi_count: toNumber(summary.poi_count, 0),
          gi_valid_count: toNumber(summary.gi_z_stats && summary.gi_z_stats.count, 0),
          lisa_valid_count: toNumber(summary.lisa_i_stats && summary.lisa_i_stats.count, 0),
          cell_count: allCells.length,
          included_cell_count: cells.length,
        },
        metrics: {
          avg_density_poi_per_km2: toNumber(summary.avg_density_poi_per_km2, 0),
          avg_local_entropy: toNumber(summary.avg_local_entropy, 0),
          global_moran_i_density: toNumber(summary.global_moran_i_density, 0),
          global_moran_z_score: toNumber(summary.global_moran_z_score, 0),
        },
        omitted: {
          cells_total: allCells.length,
          cells_included: cells.length,
          geometry_removed: true,
        },
        notes: [
          'H3 evidence is retained for POI density, clustering, entropy, Gi/LISA and hotspot analysis.',
          'H3 evidence must not be treated as shared-grid coupling evidence unless population and nightlight are also computed on H3.',
        ],
      }
    },
    buildAgentPopulationGridEvidence() {
      const toNumber = (value, fallback = 0) => {
        const parsed = Number(value)
        return Number.isFinite(parsed) ? parsed : fallback
      }
      const sortedTop = (rows, key, limit = 8, abs = false) => cloneArray(rows)
        .filter((row) => asText(row && row.cell_id))
        .sort((a, b) => {
          const left = toNumber(a && a[key], 0)
          const right = toNumber(b && b[key], 0)
          return (abs ? Math.abs(right) - Math.abs(left) : right - left)
        })
        .slice(0, limit)

      const baseCells = cloneArray((this.populationLayer && this.populationLayer.cells) || [])
        .map((cell) => ({
          cell_id: asText(cell && cell.cell_id),
          population_value: toNumber(cell && (cell.display_value ?? cell.value ?? cell.raw_value), 0),
          raw_value: toNumber(cell && cell.raw_value, 0),
        }))
        .filter((cell) => cell.cell_id)

      const sources = this.populationSexSourceLayers && typeof this.populationSexSourceLayers === 'object'
        ? this.populationSexSourceLayers
        : {}
      const maleCells = cloneArray((sources.male && sources.male.cells) || [])
      const femaleCells = cloneArray((sources.female && sources.female.cells) || [])
      const maleById = new Map(maleCells.map((cell) => [asText(cell && cell.cell_id), toNumber(cell && (cell.display_value ?? cell.value ?? cell.raw_value), 0)]))
      const femaleById = new Map(femaleCells.map((cell) => [asText(cell && cell.cell_id), toNumber(cell && (cell.display_value ?? cell.value ?? cell.raw_value), 0)]))
      const sexCellIds = Array.from(new Set([...maleById.keys(), ...femaleById.keys()])).filter(Boolean)
      const sexRows = sexCellIds.map((cellId) => {
        const maleValue = toNumber(maleById.get(cellId), 0)
        const femaleValue = toNumber(femaleById.get(cellId), 0)
        const total = maleValue + femaleValue
        return {
          cell_id: cellId,
          male_value: maleValue,
          female_value: femaleValue,
          sex_diff_value: Number((maleValue - femaleValue).toFixed(6)),
          male_ratio: total > 0 ? Number((maleValue / total).toFixed(6)) : 0,
          female_ratio: total > 0 ? Number((femaleValue / total).toFixed(6)) : 0,
        }
      })
      const sexById = new Map(sexRows.map((row) => [row.cell_id, row]))
      const cells = baseCells.map((cell) => ({
        ...cell,
        ...cloneObject(sexById.get(cell.cell_id) || {}),
      }))

      return {
        evidence_level: sexRows.length ? 'cell_id_population_and_sex' : (baseCells.length ? 'population_cells_only' : 'missing'),
        counts: {
          population_cells: baseCells.length,
          sex_cells: sexRows.length,
        },
        top_density_cells: sortedTop(baseCells, 'population_value'),
        low_density_cells: sortedTop(baseCells, 'population_value').reverse(),
        top_male_diff_cells: sortedTop(sexRows.filter((row) => row.sex_diff_value > 0), 'sex_diff_value'),
        top_female_diff_cells: sortedTop(sexRows.filter((row) => row.sex_diff_value < 0), 'sex_diff_value', 8, true),
        top_abs_sex_diff_cells: sortedTop(sexRows, 'sex_diff_value', 10, true),
        omitted: {
          cells_total: cells.length,
          cells_included: 0,
          raw_cells_removed: true,
        },
        notes: [
          'sex cell values are included only when male/female population source layers are already available in the frontend state',
          'cell-level sex differences are service-balance evidence, not evidence of gendered consumption preference',
        ],
      }
    },
    buildAgentSharedGridEvidence() {
      const toNumber = (value, fallback = 0) => {
        const parsed = Number(value)
        return Number.isFinite(parsed) ? parsed : fallback
      }
      const limit = 10
      const topRows = (rows, valueKey, rowLimit = limit) => cloneArray(rows)
        .map((row) => ({ ...row, value: toNumber(row && row[valueKey], 0) }))
        .filter((row) => asText(row && row.cell_id) && row.value > 0)
        .sort((a, b) => b.value - a.value)
        .slice(0, rowLimit)
      const scoreLevel = (score) => {
        if (score >= 0.67) return 'high'
        if (score <= 0.33) return 'low'
        return 'medium'
      }
      const typeFor = (row) => {
        const pop = row.population_level
        const poi = row.poi_level
        const light = row.nightlight_level
        if (pop === 'high' && poi === 'high' && light === 'high') return 'high_pop_high_poi_high_light'
        if (pop === 'high' && poi === 'low') return 'high_pop_low_poi'
        if (pop === 'high' && light === 'low') return 'high_pop_low_light'
        if (poi === 'high' && light === 'low') return 'high_poi_low_light'
        if (light === 'high' && poi === 'low') return 'high_light_low_poi'
        if (pop === 'low' && poi === 'high' && light === 'high') return 'low_pop_high_poi_high_light'
        if (pop === 'low' && poi === 'low' && light === 'low') return 'low_all'
        return 'balanced_medium'
      }
      const planningMeaning = (type) => {
        const meanings = {
          high_pop_high_poi_high_light: '人口、业态供给与夜间活力重合，适合作为优先策划节点。',
          high_pop_low_poi: '人口需求集中但 POI 供给偏弱，适合作为服务补位机会区。',
          high_pop_low_light: '人口基础较强但夜间活力偏弱，需关注夜间运营和活动转化。',
          high_poi_low_light: 'POI 供给较强但夜间亮度偏弱，需验证营业时间、夜间运营和灯光氛围。',
          high_light_low_poi: '夜光较强但 POI 供给偏弱，需验证是否来自道路照明、公共设施或非消费活动。',
          low_pop_high_poi_high_light: '人口基础偏弱但 POI 与夜光较强，需验证外来客流或目的性消费能力。',
          low_all: '人口、供给和夜间活力均偏弱，更适合低强度公共休闲或暂缓作为消费核心。',
          balanced_medium: '三类指标相对均衡，可作为复合型生活消费补充节点。',
        }
        return meanings[type] || meanings.balanced_medium
      }

      const populationGridEvidence = typeof this.buildAgentPopulationGridEvidence === 'function'
        ? this.buildAgentPopulationGridEvidence()
        : {}
      const populationCells = cloneArray((this.populationLayer && this.populationLayer.cells) || [])
        .map((cell) => ({
          cell_id: asText(cell && cell.cell_id),
          population_value: toNumber(cell && (cell.display_value ?? cell.value ?? cell.raw_value), 0),
        }))
        .filter((cell) => cell.cell_id)
      const populationSexRows = cloneArray(populationGridEvidence.top_abs_sex_diff_cells || [])
        .concat(cloneArray(populationGridEvidence.top_male_diff_cells || []))
        .concat(cloneArray(populationGridEvidence.top_female_diff_cells || []))
      const sexById = new Map(populationSexRows.map((row) => [asText(row && row.cell_id), row]))
      const poiCells = cloneArray((this.poiGridFeatures || []))
        .map((feature) => {
          const props = cloneObject(feature && feature.properties)
          return {
            cell_id: asText(props.cell_id),
            poi_count: toNumber(props.poi_count, 0),
            density_poi_per_km2: toNumber(props.density_poi_per_km2, 0),
            dominant_category: asText(props.dominant_category),
            dominant_category_name: asText(props.dominant_category_name),
          }
        })
      const nightlightCells = cloneArray((this.nightlightLayer && this.nightlightLayer.cells) || [])
        .map((cell) => ({
          cell_id: asText(cell && cell.cell_id),
          radiance: toNumber(cell && (cell.display_value ?? cell.value ?? cell.raw_value), 0),
          class_key: asText(cell && cell.class_key),
          class_label: asText(cell && cell.class_label),
        }))

      const populationById = new Map(populationCells.map((cell) => [cell.cell_id, {
        ...cell,
        ...cloneObject(sexById.get(cell.cell_id) || {}),
      }]))
      const poiById = new Map(poiCells.map((cell) => [cell.cell_id, cell]))
      const nightlightById = new Map(nightlightCells.map((cell) => [cell.cell_id, cell]))
      const sharedIds = Array.from(new Set([
        ...populationCells.map((cell) => cell.cell_id),
        ...poiCells.map((cell) => cell.cell_id),
        ...nightlightCells.map((cell) => cell.cell_id),
      ])).filter(Boolean)

      const maxPopulation = Math.max(1, ...populationCells.map((cell) => toNumber(cell.population_value, 0)))
      const maxPoi = Math.max(1, ...poiCells.map((cell) => toNumber(cell.poi_count, 0)))
      const maxNightlight = Math.max(1, ...nightlightCells.map((cell) => toNumber(cell.radiance, 0)))
      const overlapRows = sharedIds.map((cellId) => {
        const pop = populationById.get(cellId) || {}
        const poi = poiById.get(cellId) || {}
        const night = nightlightById.get(cellId) || {}
        const populationScore = toNumber(pop.population_value, 0) / maxPopulation
        const poiScore = toNumber(poi.poi_count, 0) / maxPoi
        const nightlightScore = toNumber(night.radiance, 0) / maxNightlight
        const row = {
          cell_id: cellId,
          population_value: toNumber(pop.population_value, 0),
          male_value: toNumber(pop.male_value, 0),
          female_value: toNumber(pop.female_value, 0),
          sex_diff_value: toNumber(pop.sex_diff_value, 0),
          male_ratio: toNumber(pop.male_ratio, 0),
          female_ratio: toNumber(pop.female_ratio, 0),
          poi_count: toNumber(poi.poi_count, 0),
          density_poi_per_km2: toNumber(poi.density_poi_per_km2, 0),
          nightlight_radiance: toNumber(night.radiance, 0),
          nightlight_class: asText(night.class_label || night.class_key),
          dominant_category_name: asText(poi.dominant_category_name),
          population_level: scoreLevel(populationScore),
          poi_level: scoreLevel(poiScore),
          nightlight_level: scoreLevel(nightlightScore),
          composite_score: Number(((populationScore + poiScore + nightlightScore) / 3).toFixed(6)),
          has_population: populationById.has(cellId),
          has_poi: poiById.has(cellId),
          has_nightlight: nightlightById.has(cellId),
        }
        const couplingType = typeFor(row)
        return {
          ...row,
          coupling_type: couplingType,
          planning_meaning: planningMeaning(couplingType),
        }
      })
      const completeRows = overlapRows.filter((row) => row.has_population && row.has_poi && row.has_nightlight)
      const byPopulation = (rows) => cloneArray(rows).sort((a, b) => b.population_value - a.population_value).slice(0, limit)
      const byPoi = (rows) => cloneArray(rows).sort((a, b) => b.poi_count - a.poi_count).slice(0, limit)
      const byNightlight = (rows) => cloneArray(rows).sort((a, b) => b.nightlight_radiance - a.nightlight_radiance).slice(0, limit)
      const bySexDiff = (rows) => cloneArray(rows)
        .filter((row) => Math.abs(toNumber(row.sex_diff_value, 0)) > 0)
        .sort((a, b) => Math.abs(b.sex_diff_value) - Math.abs(a.sex_diff_value))
        .slice(0, limit)

      const topCoupledCells = cloneArray(completeRows)
        .filter((row) => row.coupling_type === 'high_pop_high_poi_high_light')
        .sort((a, b) => b.composite_score - a.composite_score)
        .slice(0, limit)
      return {
        evidence_version: 'shared_grid_evidence_v1',
        grid_type: 'population_nightlight_shared_cell_id',
        join_key: 'cell_id',
        uses: ['population', 'poi_raster', 'nightlight'],
        evidence_level: completeRows.length ? 'cell_id_overlap' : 'partial_or_missing',
        counts: {
          population_cells: populationCells.length,
          poi_cells: poiCells.length,
          nightlight_cells: nightlightCells.length,
          complete_overlap_cells: completeRows.length,
        },
        top_population_cells: topRows(populationCells, 'population_value'),
        top_poi_cells: topRows(poiCells, 'poi_count'),
        top_nightlight_cells: topRows(nightlightCells, 'radiance'),
        top_coupled_cells: topCoupledCells,
        service_gap_cells: byPopulation(completeRows.filter((row) => row.coupling_type === 'high_pop_low_poi')),
        night_operation_gap_cells: byPopulation(completeRows.filter((row) => ['high_pop_low_light', 'high_poi_low_light'].includes(row.coupling_type))),
        external_flow_suspect_cells: byPoi(completeRows.filter((row) => row.coupling_type === 'low_pop_high_poi_high_light')),
        high_light_low_poi_cells: byNightlight(completeRows.filter((row) => row.coupling_type === 'high_light_low_poi')),
        sex_balance_attention_cells: bySexDiff(completeRows),
        notes: [
          'population, poi and nightlight cells use the same cell_id only when complete_overlap_cells > 0',
          'values are display-level evidence for spatial coupling, not proof of real traffic or consumption',
        ],
      }
    },
    buildAgentAnalysisSnapshot() {
      const poiTotal = Array.isArray(this.allPoisDetails) ? this.allPoisDetails.length : 0
      const populationSummary = (this.populationOverview && this.populationOverview.summary) || {}
      const nightlightSummary = (this.nightlightOverview && this.nightlightOverview.summary) || {}
      const h3Summary = this.h3AnalysisSummary || {}
      const roadSummary = this.roadSyntaxSummary || {}
      const siteSelectionScope = typeof this.normalizeAgentSiteSelectionScope === 'function'
        ? this.normalizeAgentSiteSelectionScope()
        : { polygon: [], drawnPolygon: [], isochroneFeature: null }
      const frontendAnalysis = typeof this._buildFrontendAnalysisForExport === 'function'
        ? this._buildFrontendAnalysisForExport()
        : {}
      const paramBundles = buildAnalysisTaskParamBundles(this, ['poi_fetch', 'poi_raster_grid', 'poi_h3_grid', 'population', 'nightlight', 'road_syntax'])
      const poiGridEvidence = typeof this.buildAgentPoiGridEvidence === 'function'
        ? this.buildAgentPoiGridEvidence()
        : {}
      const populationGridEvidence = typeof this.buildAgentPopulationGridEvidence === 'function'
        ? this.buildAgentPopulationGridEvidence()
        : {}
      const sharedGrid = typeof this.buildAgentSharedGridEvidence === 'function'
        ? this.buildAgentSharedGridEvidence()
        : {}
      const poiH3Evidence = typeof this.buildAgentPoiH3Evidence === 'function'
        ? this.buildAgentPoiH3Evidence()
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
          polygon: siteSelectionScope.polygon || [],
          drawn_polygon: siteSelectionScope.drawnPolygon || [],
          isochrone_feature: siteSelectionScope.isochroneFeature || null,
        },
        pois: [],
        poi_summary: {
          total: poiTotal,
          source: this.resultDataSource || this.poiDataSource || '',
        },
        h3: {
          summary: h3Summary,
          charts: this.h3AnalysisCharts || {},
          grid_count: Number(h3Summary.grid_count || this.h3GridCount || 0),
          grid_params: cloneObject(paramBundles.poi_h3_grid && paramBundles.poi_h3_grid.params),
          poi_h3_evidence: poiH3Evidence,
        },
        road: {
          summary: roadSummary,
          diagnostics: this.roadSyntaxDiagnostics || {},
        },
        population: {
          summary: populationSummary,
          grid_evidence: populationGridEvidence,
        },
        nightlight: {
          summary: nightlightSummary,
        },
        param_bundles: paramBundles,
        shared_grid: sharedGrid,
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
        messages: messages.map((item) => this.serializeAgentMessageForSession(item)),
        output: {
          cards: cloneArray(merged.cards),
          clarification_question: String(merged.clarificationQuestion || ''),
          clarification_options: cloneArray(merged.clarificationOptions).map((item) => asText(item)).filter(Boolean),
          risk_prompt: String(merged.riskPrompt || ''),
          next_suggestions: cloneArray(merged.nextSuggestions),
          panel_payloads: cloneObject(merged.panelPayloads),
          review_contract: cloneObject(merged.reviewContract),
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
          review_contract: cloneObject(merged.reviewContract || (merged.diagnostics && merged.diagnostics.reviewContract)),
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
        attachment_ids: cloneArray(merged.attachmentIds || merged.attachment_ids || this.agentAttachmentIds),
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
    getAgentReadyAttachmentIds() {
      return normalizeAgentAttachments(this.agentAttachments)
        .filter((item) => item.status === 'ready')
        .map((item) => item.attachmentId)
    },
    agentHasProcessingAttachments() {
      return normalizeAgentAttachments(this.agentAttachments)
        .some((item) => ['uploaded', 'processing'].includes(item.status))
    },
    syncAgentAttachmentState(sessionId = '') {
      const targetSessionId = this.getActiveAgentSessionId(sessionId)
      if (!targetSessionId) return
      this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
        ...session,
        attachments: normalizeAgentAttachments(this.agentAttachments),
        attachmentIds: this.getAgentReadyAttachmentIds(),
      }), { syncActive: false })
    },
    async refreshAgentAttachments(sessionId = '') {
      const targetSessionId = this.getActiveAgentSessionId(sessionId)
      if (!targetSessionId) return []
      const res = await fetch(`/api/v1/analysis/agent/attachments?conversation_id=${encodeURIComponent(targetSessionId)}`, {
        cache: 'no-store',
      })
      if (!res.ok) {
        throw new Error(`/api/v1/analysis/agent/attachments 请求失败(${res.status})`)
      }
      const rows = normalizeAgentAttachments(await res.json())
      if (targetSessionId === asText(this.activeAgentSessionId)) {
        this.agentAttachments = rows
        this.agentAttachmentIds = rows.filter((item) => item.status === 'ready').map((item) => item.attachmentId)
      }
      this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
        ...session,
        attachments: rows,
        attachmentIds: rows.filter((item) => item.status === 'ready').map((item) => item.attachmentId),
      }), { syncActive: targetSessionId === asText(this.activeAgentSessionId) })
      if (rows.some((item) => ['uploaded', 'processing'].includes(item.status))) {
        this.startAgentAttachmentPolling(targetSessionId)
      } else {
        this.stopAgentAttachmentPolling()
      }
      return rows
    },
    startAgentAttachmentPolling(sessionId = '') {
      const targetSessionId = this.getActiveAgentSessionId(sessionId)
      if (!targetSessionId || typeof window === 'undefined' || typeof window.setInterval !== 'function') return
      this.stopAgentAttachmentPolling()
      this.agentAttachmentPollTimer = window.setInterval(() => {
        this.refreshAgentAttachments(targetSessionId).catch((err) => {
          this.agentAttachmentError = err && err.message ? err.message : String(err)
          this.stopAgentAttachmentPolling()
        })
      }, 1600)
    },
    stopAgentAttachmentPolling() {
      if (this.agentAttachmentPollTimer && typeof window !== 'undefined' && typeof window.clearInterval === 'function') {
        window.clearInterval(this.agentAttachmentPollTimer)
      }
      this.agentAttachmentPollTimer = null
    },
    async uploadAgentAttachment(file = null) {
      if (!file || this.agentAttachmentUploading) return null
      this.ensureAgentPanelReady()
      const targetSessionId = this.getActiveAgentSessionId(this.activeAgentSessionId) || (this.createAgentSession().id)
      const form = new FormData()
      form.append('conversation_id', targetSessionId)
      form.append('history_id', this.getCurrentAgentHistoryId())
      form.append('file', file)
      this.agentAttachmentUploading = true
      this.agentAttachmentError = ''
      try {
        const res = await fetch('/api/v1/analysis/agent/attachments', {
          method: 'POST',
          body: form,
        })
        if (!res.ok) {
          throw new Error(`/api/v1/analysis/agent/attachments 上传失败(${res.status})`)
        }
        const record = normalizeAgentAttachments([await res.json()])[0]
        const current = normalizeAgentAttachments(this.agentAttachments)
        const next = [record, ...current.filter((item) => item.attachmentId !== record.attachmentId)]
        this.agentAttachments = next
        this.agentAttachmentIds = next.filter((item) => item.status === 'ready').map((item) => item.attachmentId)
        this.syncAgentAttachmentState(targetSessionId)
        this.startAgentAttachmentPolling(targetSessionId)
        return record
      } catch (err) {
        this.agentAttachmentError = err && err.message ? err.message : String(err)
        return null
      } finally {
        this.agentAttachmentUploading = false
      }
    },
    async removeAgentAttachment(attachmentId = '') {
      const targetSessionId = this.getActiveAgentSessionId(this.activeAgentSessionId)
      const nextId = asText(attachmentId)
      if (!targetSessionId || !nextId) return false
      const previous = normalizeAgentAttachments(this.agentAttachments)
      this.agentAttachments = previous.filter((item) => item.attachmentId !== nextId)
      this.agentAttachmentIds = this.getAgentReadyAttachmentIds()
      this.syncAgentAttachmentState(targetSessionId)
      try {
        const res = await fetch(`/api/v1/analysis/agent/attachments/${encodeURIComponent(nextId)}?conversation_id=${encodeURIComponent(targetSessionId)}`, {
          method: 'DELETE',
        })
        if (!res.ok && res.status !== 404) {
          throw new Error(`/api/v1/analysis/agent/attachments/${nextId} 删除失败(${res.status})`)
        }
        return true
      } catch (err) {
        this.agentAttachments = previous
        this.agentAttachmentIds = this.getAgentReadyAttachmentIds()
        this.agentAttachmentError = err && err.message ? err.message : String(err)
        this.syncAgentAttachmentState(targetSessionId)
        return false
      }
    },
    onAgentAttachmentInputChange(event = null) {
      const input = event && event.target
      const files = input && input.files ? Array.from(input.files) : []
      if (input) input.value = ''
      files.forEach((file) => {
        this.uploadAgentAttachment(file).catch((err) => {
          this.agentAttachmentError = err && err.message ? err.message : String(err)
        })
      })
      this.closeAgentComposerMenu()
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
    buildAgentAssistantMessageContent(turn = {}) {
      const output = turn && turn.output ? turn.output : {}
      const sections = []
      const summary = getAgentSummaryCardContent(output.cards)
      const decision = normalizeAgentDecision(output.decision)
      if (decision.summary) {
        sections.push(`## 核心判断\n${decision.summary}`)
      } else if (summary) {
        sections.push(summary)
      }
      const support = cloneArray(output.support).map((item) => normalizeAgentDecisionEvidence(item))
      if (support.length) {
        sections.push([
          '## 为什么这样判断',
          ...support.map((item) => {
            const headline = asText(item.headline || item.metric || item.key) || '证据'
            const detail = asText(item.interpretation)
            const source = asText(item.source)
            const confidence = asText(item.confidence)
            const meta = [source ? `来源：${source}` : '', confidence ? `置信度：${confidence}` : ''].filter(Boolean).join('；')
            return `- ${[headline, detail, meta].filter(Boolean).join('。')}`
          }),
        ].join('\n'))
      }
      const counterpoints = cloneArray(output.counterpoints).map((item) => normalizeAgentCounterpoint(item))
      if (counterpoints.length) {
        sections.push([
          '## 还不能判断什么',
          ...counterpoints.map((item) => `- ${[asText(item.title), asText(item.detail)].filter(Boolean).join('：')}`),
        ].join('\n'))
      }
      const actions = cloneArray(output.actions).map((item) => normalizeAgentAction(item))
      if (actions.length) {
        sections.push([
          '## 下一步怎么做',
          ...actions.map((item) => {
            const body = [
              asText(item.detail),
              asText(item.condition) ? `触发条件：${asText(item.condition)}` : '',
              asText(item.target) ? `目标：${asText(item.target)}` : '',
            ].filter(Boolean).join('；')
            return `- ${[asText(item.title), body].filter(Boolean).join('：')}`
          }),
        ].join('\n'))
      }
      const boundary = cloneArray(output.boundary).map((item) => normalizeAgentBoundaryItem(item))
      if (boundary.length) {
        sections.push([
          '## 适用边界',
          ...boundary.map((item) => `- ${[asText(item.title), asText(item.detail)].filter(Boolean).join('：')}`),
        ].join('\n'))
      }
      const clarification = asText(output.clarificationQuestion)
      if (clarification) {
        sections.push(`## 需要补充\n${clarification}`)
      }
      const riskPrompt = asText(output.riskPrompt)
      if (riskPrompt) {
        sections.push(`## 需要确认\n${riskPrompt}`)
      }
      return sections.filter(Boolean).join('\n\n') || summary || '已完成分析'
    },
    buildAgentTurnProcessSnapshot(seed = {}) {
      const runState = this.getAgentRunState(seed.sessionId) || createAgentRunState()
      const startedAtMs = Number(seed.startedAt || runState.startedAt || this.agentStreamStartedAt || 0) || 0
      const completedAtMs = Number(seed.completedAt || Date.now()) || Date.now()
      return normalizeAgentMessageProcess({
        turnId: asText(seed.turnId || runState.streamingMessageId) || `agent-turn-${completedAtMs.toString(36)}`,
        status: asText(seed.status || this.agentStatus),
        stage: asText(seed.stage || this.agentStage),
        startedAt: startedAtMs ? new Date(startedAtMs).toISOString() : '',
        completedAt: new Date(completedAtMs).toISOString(),
        elapsedMs: startedAtMs ? Math.max(0, completedAtMs - startedAtMs) : 0,
        thinkingTimeline: cloneArray(seed.thinkingTimeline),
        executionTrace: cloneArray(seed.executionTrace),
        plan: normalizeAgentPlanEnvelope(seed.plan),
        pendingTaskConfirmation: cloneObject(seed.pendingTaskConfirmation),
      })
    },
    buildAgentAssistantMessageFromTurn(turn = {}, process = {}) {
      const message = {
        role: 'assistant',
        content: this.buildAgentAssistantMessageContent(turn),
      }
      const normalizedProcess = normalizeAgentMessageProcess(process)
      if (hasAgentMessageProcessContent(normalizedProcess)) {
        message.process = normalizedProcess
      }
      return message
    },
    serializeAgentMessageForSession(message = {}) {
      const row = {
        role: asText(message && message.role) || 'user',
        content: String((message && message.content) || ''),
      }
      const process = normalizeAgentMessageProcess(message && message.process)
      if (hasAgentMessageProcessContent(process)) {
        row.process = process
      }
      return row
    },
    buildTurnContext(options = {}) {
      const panelKind = asText(options && options.panelKind)
        || (typeof this.getAgentActiveTopTab === 'function' ? asText(this.getAgentActiveTopTab().kind) : '')
        || 'followup'
      const mode = asText((options && options.mode) || this.agentComposerMode || this.agentDeepAnalysisMode) === 'deep' ? 'deep' : 'quick'
      this.agentDeepAnalysisMode = mode
      const target = (options && options.target) || (typeof this.getAgentActiveDeepAnalysisTab === 'function' ? ((this.getAgentActiveDeepAnalysisTab() || {}).target) : null)
      const rawQuestion = String((options && options.prompt) || this.agentInput || '').trim()
      const requestQuestion = panelKind === 'deep_analysis' && typeof this.buildAgentDeepAnalysisPrompt === 'function'
        ? this.buildAgentDeepAnalysisPrompt(rawQuestion, target)
        : rawQuestion
      if (!rawQuestion || !requestQuestion || this.agentSessionHydrating) return null
      const activeSessionId = this.getActiveAgentSessionId(this.activeAgentSessionId)
      if (this.agentLoading || (activeSessionId && this.isAgentSessionRunning(activeSessionId))) return null
      const composerAttachments = normalizeAgentAttachments(this.agentAttachments)
      this.ensureAgentPanelReady()
      if (composerAttachments.length && !normalizeAgentAttachments(this.agentAttachments).length) {
        this.agentAttachments = composerAttachments
        this.agentAttachmentIds = composerAttachments.filter((item) => item.status === 'ready').map((item) => item.attachmentId)
      }
      if (panelKind !== 'deep_analysis' && typeof this.ensureAgentFollowupTabForPrompt === 'function') {
        this.ensureAgentFollowupTabForPrompt(rawQuestion)
      }
      const currentSession = this.syncCurrentAgentSession() || this.readSessionState(this.activeAgentSessionId)
      const targetSessionId = this.getActiveAgentSessionId(currentSession && currentSession.id) || this.createAgentSession().id
      const wasPersisted = !!(currentSession && currentSession.persisted)
      const historyId = this.getCurrentAgentHistoryId()
      const requestAbortController = typeof AbortController !== 'undefined' ? new AbortController() : null
      const requestRiskConfirmations = Array.isArray(options && options.riskConfirmations)
        ? options.riskConfirmations
        : this.agentRiskConfirmations
      const requestAttachmentIds = typeof this.getAgentReadyAttachmentIds === 'function'
        ? this.getAgentReadyAttachmentIds()
        : cloneArray(this.agentAttachmentIds)
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
      const nextMessages = [...baseMessages, { role: 'user', content: rawQuestion }]
      const requestMessages = [
        ...baseMessages,
        { role: 'user', content: requestQuestion },
      ]
      return {
        question: requestQuestion,
        rawQuestion,
        requestMessages,
        mode,
        panelKind,
        target,
        currentSession,
        targetSessionId,
        wasPersisted,
        historyId,
        requestAbortController,
        requestRiskConfirmations,
        requestAttachmentIds,
        nextMessages,
      }
    },
    async consumeTurnStream(res, handler) {
      await consumeSseStream(res, handler)
    },
    normalizeReactLoopEvent(event = {}) {
      const type = asText(event.type)
      const payload = cloneObject(event.payload)
      const step = Number(event.step || 0) || 0
      const summary = asText(payload.summary || payload.conclusion || payload.message)
      const tool = asText(payload.meta && (payload.meta.tool_label || payload.meta.tool))
      const rawTool = asText(payload.meta && payload.meta.tool)
      const labels = {
        status: '状态',
        thought: '思考',
        action: '行动',
        observation: '观察',
        reflection: '反思',
        final: '结论',
        error: '异常',
      }
      return normalizeAgentThinkingItem({
        id: `react-${type || 'event'}-${step}-${tool || 'core'}`,
        phase: 'react_loop',
        title: labels[type] || 'ReAct',
        detail: summary,
        items: tool ? [`工具：${tool}`] : [],
        meta: {
          ...cloneObject(payload.meta),
          reactLoop: true,
          reactType: type,
          step,
          tool,
          rawTool,
          raw: payload.raw || null,
        },
        state: ['final'].includes(type)
          ? 'completed'
          : (['error'].includes(type) ? 'failed' : (['observation', 'reflection'].includes(type) ? 'completed' : 'active')),
      })
    },
    buildReactFinalTurnPayload({ finalEvent = {}, question = '', messages = [], executionTrace = [] } = {}) {
      const payload = cloneObject(finalEvent.payload)
      const conclusion = asText(payload.conclusion || payload.summary) || 'ReAct 循环已完成。'
      const evidenceStatus = asText(payload.evidence_status)
      const evidenceSteps = cloneArray(payload.evidence_steps || payload.evidenceSteps)
      const nextActions = cloneArray(payload.next_actions || payload.nextActions).map((item) => asText(item)).filter(Boolean)
      const uncertainties = cloneArray(payload.uncertainties).map((item) => asText(item)).filter(Boolean)
      const evidenceText = evidenceSteps.length ? `证据步骤：${evidenceSteps.join('、')}` : ''
      const evidenceStatusText = evidenceStatus ? `证据状态：${evidenceStatus}` : ''
      const detailItems = [evidenceStatusText, evidenceText, ...nextActions.slice(0, 3), ...uncertainties.slice(0, 2)]
        .filter(Boolean)
      const assistantParts = [conclusion]
      if (detailItems.length) {
        assistantParts.push(detailItems.map((item) => `- ${item}`).join('\n'))
      }
      const nextMessages = [
        ...cloneArray(messages),
        { role: 'assistant', content: assistantParts.filter(Boolean).join('\n\n') },
      ]
      return {
        status: 'answered',
        stage: 'answered',
        output: {
          cards: [],
          decision: {
            summary: '',
            mode: 'judgment',
            strength: evidenceStatus === '证据较完整' ? 'strong' : 'moderate',
            can_act: nextActions.length > 0,
          },
          support: [],
          actions: [],
          boundary: [],
          review_contract: cloneObject(payload.review_contract || payload.reviewContract),
          next_suggestions: nextActions,
          panel_payloads: {},
        },
        diagnostics: {
          execution_trace: cloneArray(executionTrace),
          used_tools: cloneArray(executionTrace).map((item) => asText(item.tool_name || item.toolName)).filter(Boolean),
          review_contract: cloneObject(payload.review_contract || payload.reviewContract),
          thinking_timeline: [],
          error: '',
        },
        context_summary: {
          question: asText(question),
          mode: 'react_loop',
        },
        plan: {
          steps: [],
          followup_steps: [],
          followup_applied: false,
          summary: 'ReAct 循环已完成',
        },
        messages: nextMessages,
      }
    },
    async submitReactAgentTurn(options = {}) {
      const turnContext = this.buildTurnContext(options)
      if (!turnContext) return
      const {
        question,
        rawQuestion,
        panelKind,
        targetSessionId,
        wasPersisted,
        historyId,
        requestAbortController,
        requestRiskConfirmations,
        requestAttachmentIds,
        nextMessages,
      } = turnContext
      this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
        ...session,
        panelKind,
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
        stage: 'executing',
        thinkingTimeline: [normalizeAgentSubmitThinkingItem('active')],
      }))
      this.setAgentRunState(targetSessionId, {
        abortController: requestAbortController,
        loading: true,
        streamState: 'connecting',
        streamingMessageId: `agent-react-${Date.now().toString(36)}`,
        reasoningBlocks: [],
        pendingQuestion: rawQuestion || question,
        autoScrollLocked: false,
        autoScrollSticky: true,
        autoScrollThresholdPx: 24,
      })
      this.agentTurnAbortController = targetSessionId === asText(this.activeAgentSessionId) ? requestAbortController : null
      this.agentInput = ''
      this.agentClarificationDraft = ''
      this.agentClarificationSubmitting = false
      this.agentThinkingExpanded = true
      this.agentPlanExpanded = false
      this.agentTraceExpanded = false
      this.startAgentThinkingTimer(targetSessionId)
      try {
        const runRes = await fetch('/api/v1/analysis/agent/react/run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          signal: requestAbortController ? requestAbortController.signal : undefined,
          body: JSON.stringify({
            question,
            analysis_snapshot: this.buildAgentAnalysisSnapshot(),
            options: {
              max_steps: 8,
              stagnation_limit: 2,
              tool_timeout_seconds: 20,
              max_tool_failures: 2,
            },
            attachment_ids: requestAttachmentIds,
          }),
        })
        if (!runRes.ok) {
          throw new Error(`/api/v1/analysis/agent/react/run 请求失败(${runRes.status})`)
        }
        const runPayload = await runRes.json()
        const runId = asText(runPayload && runPayload.run_id)
        if (!runId) throw new Error('ReAct run_id 缺失')
        const streamRes = await fetch(`/api/v1/analysis/agent/react/stream?run_id=${encodeURIComponent(runId)}`, {
          signal: requestAbortController ? requestAbortController.signal : undefined,
        })
        if (!streamRes.ok) {
          throw new Error(`/api/v1/analysis/agent/react/stream 请求失败(${streamRes.status})`)
        }
        let finalEvent = null
        const executionTrace = []
        await this.consumeTurnStream(streamRes, ({ type, payload }) => {
          const event = payload && typeof payload === 'object' && payload.type ? payload : { type, payload }
          const item = this.normalizeReactLoopEvent(event)
          if (type === 'action' || event.type === 'action') {
            executionTrace.push({
              tool_name: asText(event.payload && event.payload.meta && event.payload.meta.tool) || 'react_action',
              status: 'start',
              reason: asText(event.payload && event.payload.summary),
              message: asText(event.payload && event.payload.summary),
              evidence_count: 0,
              warning_count: 0,
            })
          }
          this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
            ...session,
            status: item.state === 'failed' ? 'failed' : 'running',
            stage: item.state === 'failed' ? 'failed' : 'executing',
            thinkingTimeline: upsertThinkingItemInList(
              completeActiveThinkingItemsInList(
                upsertThinkingItemInList(session.thinkingTimeline, normalizeAgentSubmitThinkingItem('completed')),
                item.id,
              ),
              item,
            ),
            executionTrace: cloneArray(executionTrace),
          }))
          this.setAgentRunState(targetSessionId, { streamState: 'streaming' })
          if (targetSessionId === asText(this.activeAgentSessionId)) {
            this.agentThinkingExpanded = true
            this.maybeAutoScrollAgentThread({ sessionId: targetSessionId })
          }
          if (event.type === 'final') {
            finalEvent = event
          }
        })
        if (!finalEvent) {
          throw new Error('ReAct 流式执行未返回最终结果')
        }
        const finalResponse = this.buildReactFinalTurnPayload({
          finalEvent,
          question: rawQuestion || question,
          messages: nextMessages,
          executionTrace,
        })
        const turn = normalizeAgentTurnPayload(finalResponse)
        const finalStatusItem = normalizeAgentStatusThinkingItem({ stage: 'answered' })
        const currentSessionSnapshot = this.findAgentSession(targetSessionId) || {}
        const nextThinkingTimeline = upsertThinkingItemInList(
          completeActiveThinkingItemsInList(currentSessionSnapshot.thinkingTimeline, finalStatusItem.id),
          finalStatusItem,
        )
        const assistantProcess = this.buildAgentTurnProcessSnapshot({
          sessionId: targetSessionId,
          status: 'answered',
          stage: 'answered',
          thinkingTimeline: nextThinkingTimeline,
          executionTrace,
          plan: turn.plan,
        })
        const finalMessages = cloneArray(finalResponse.messages)
        const lastMessage = finalMessages[finalMessages.length - 1]
        if (lastMessage && asText(lastMessage.role) === 'assistant' && hasAgentMessageProcessContent(assistantProcess)) {
          finalMessages.splice(finalMessages.length - 1, 1, {
            ...lastMessage,
            process: assistantProcess,
          })
        }
        this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
          ...session,
          panelKind,
          persisted: false,
          snapshotLoaded: true,
          status: 'answered',
          stage: 'answered',
          cards: cloneArray(turn.output.cards),
          decision: normalizeAgentDecision(turn.output.decision),
          support: cloneArray(turn.output.support).map((item) => normalizeAgentDecisionEvidence(item)),
          counterpoints: cloneArray(turn.output.counterpoints).map((item) => normalizeAgentCounterpoint(item)),
          actions: cloneArray(turn.output.actions).map((item) => normalizeAgentAction(item)),
          boundary: cloneArray(turn.output.boundary).map((item) => normalizeAgentBoundaryItem(item)),
          reviewContract: cloneObject(turn.output.reviewContract || turn.diagnostics.reviewContract),
          executionTrace: cloneArray(executionTrace),
          usedTools: cloneArray(finalResponse.diagnostics.used_tools),
          thinkingTimeline: nextThinkingTimeline,
          nextSuggestions: cloneArray(turn.output.nextSuggestions),
          messages: finalMessages.length ? finalMessages : nextMessages,
          error: '',
          contextSummary: cloneObject(turn.contextSummary),
          plan: normalizeAgentPlanEnvelope(turn.plan),
          riskConfirmations: [],
        }))
        this.setAgentRunState(targetSessionId, { streamState: 'completed' })
      } catch (err) {
        if (err && (err.name === 'AbortError' || String(err.message || '').includes('aborted'))) {
          this.stopAgentThinkingTimer(targetSessionId)
          this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
            ...session,
            input: rawQuestion || question,
            status: 'idle',
            stage: 'gating',
            thinkingTimeline: [],
            executionTrace: [],
          }))
          if (targetSessionId === asText(this.activeAgentSessionId)) {
            this.agentInput = rawQuestion || question
          }
          return
        }
        const message = 'ReAct 执行失败: ' + (err && err.message ? err.message : String(err))
        const item = normalizeAgentStatusThinkingItem({ stage: 'failed', message })
        this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
          ...session,
          status: 'failed',
          stage: 'failed',
          error: message,
          thinkingTimeline: upsertThinkingItemInList(
            completeActiveThinkingItemsInList(session.thinkingTimeline, item.id),
            item,
          ),
        }))
        this.setAgentRunState(targetSessionId, { streamState: 'failed' })
      } finally {
        this.syncUiAfterTurn(turnContext)
      }
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
      if (options && options.useReactLoop) {
        return this.submitReactAgentTurn(options)
      }
      const turnContext = this.buildTurnContext(options)
      if (!turnContext) return
      const {
        question,
        rawQuestion,
        requestMessages,
        mode,
        panelKind,
        targetSessionId,
        wasPersisted,
        historyId,
        requestAbortController,
        requestRiskConfirmations,
        requestAttachmentIds,
        nextMessages,
      } = turnContext
      this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
        ...session,
        panelKind,
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
      this.agentDeepAnalysisMode = mode
      this.setAgentRunState(targetSessionId, {
        abortController: requestAbortController,
        loading: true,
        streamState: 'connecting',
        streamingMessageId: `agent-stream-${Date.now().toString(36)}`,
        reasoningBlocks: [],
        panelPreloadNotes: [],
        preloadedPanelKeys: [],
        pendingQuestion: rawQuestion || question,
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
            messages: requestMessages,
            analysis_snapshot: this.buildAgentAnalysisSnapshot(),
            risk_confirmations: requestRiskConfirmations,
            attachment_ids: requestAttachmentIds,
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
              this.agentThinkingExpanded = false
              this.agentPlanExpanded = false
              this.agentTraceExpanded = false
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
          const assistantProcess = nextStatus === 'answered'
            ? this.buildAgentTurnProcessSnapshot({
              sessionId: targetSessionId,
              status: nextStatus,
              stage: nextStage,
              thinkingTimeline: nextThinkingTimeline,
              executionTrace: turn.diagnostics.executionTrace,
              plan: turn.plan,
              pendingTaskConfirmation,
            })
            : null
          const finalMessages = nextStatus === 'answered'
            ? [
              ...cloneArray(nextMessages),
              this.buildAgentAssistantMessageFromTurn(turn, assistantProcess),
            ]
            : cloneArray(nextMessages)
          this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
            ...session,
            panelKind,
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
            reviewContract: cloneObject(turn.output.reviewContract || turn.diagnostics.reviewContract),
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
            messages: nextStatus === 'answered' ? cloneArray(finalMessages) : cloneArray(session.messages),
            riskConfirmations: nextStatus === 'answered' ? [] : cloneArray(requestRiskConfirmations),
            attachmentIds: cloneArray(requestAttachmentIds),
            attachments: normalizeAgentAttachments(session.attachments),
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
            if (nextStatus === 'requires_risk_confirmation') {
              this.agentThinkingExpanded = Array.isArray(nextThinkingTimeline) && nextThinkingTimeline.length > 0
              this.agentPlanExpanded = hasAgentPlanContent(turn.plan)
              this.agentTraceExpanded = hasAgentExecutionTraceContent(turn.diagnostics.executionTrace)
            } else {
              this.agentThinkingExpanded = false
              this.agentPlanExpanded = false
              this.agentTraceExpanded = false
            }
            this.maybeAutoScrollAgentThread({ sessionId: targetSessionId })
          }
        })
        if (!finalResponse) {
          throw new Error('Agent 流式执行未返回最终结果')
        }
        await this.commitTurnResult(turnContext, finalResponse)
        if (mode === 'deep' && typeof this.clearAgentComposerMode === 'function') {
          this.agentComposerMode = ''
          this.closeAgentComposerMenu()
        }
      } catch (err) {
        if (err && (err.name === 'AbortError' || String(err.message || '').includes('aborted'))) {
          this.stopAgentThinkingTimer(targetSessionId)
          this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
            ...session,
            input: rawQuestion || question,
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
            this.agentInput = rawQuestion || question
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
          this.agentThinkingExpanded = false
          this.agentPlanExpanded = false
          this.agentTraceExpanded = false
        }
      } finally {
        this.syncUiAfterTurn(turnContext)
      }
    },
    cancelAgentTurn(sessionId = '') {
      const runState = this.getAgentRunState(this.getActiveAgentSessionId(sessionId))
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
