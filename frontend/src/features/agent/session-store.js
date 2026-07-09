import {
  asText,
  cloneArray,
  cloneObject,
  cloneRecordMap,
  createAgentRunState,
  createAgentSessionPlaceholderRecord,
  createAgentSessionRecord,
  clampText,
  cloneAgentSessionRecord,
  deriveAgentSessionPreview,
  deriveAgentSessionTitle,
  normalizeAgentAction,
  normalizeAgentBoundaryItem,
  normalizeAgentCounterpoint,
  normalizeAgentDecision,
  normalizeAgentDecisionEvidence,
  normalizeAgentPanelPreloadNotes,
  normalizeAgentPlanEnvelope,
  normalizeAgentSessionSummary,
  sortAgentSessions,
} from './normalizers.js'
import {
  hasAgentExecutionTraceContent,
  hasAgentPlanContent,
  shouldExpandAgentProcessSection,
} from './derived.js'
import { cloneAnalysisTaskConfirmation } from './analysis-task-registry.js'
import { getAnalysisWorkspaceTabsFromState } from './analysis-workspace-tabs.js'

function createAgentSessionStoreMethods() {
  return {
    createAgentSession(seedTitle = '') {
      return createAgentSessionRecord({
        title: String(seedTitle || '').trim() || '新报告',
        preview: '开始一份新的区域分析',
        historyId: this.getCurrentAgentHistoryId(),
        status: 'idle',
        panelKind: 'followup',
        persisted: false,
        snapshotLoaded: true,
        titleSource: 'fallback',
      })
    },
    getAgentHistorySessions() {
      return this.agentSessions.filter((item) => !!(item && item.persisted))
    },
    getCurrentAgentHistoryId() {
      return asText(this.currentHistoryRecordId)
    },
    getAgentCurrentRangeSessions() {
      const currentHistoryId = this.getCurrentAgentHistoryId()
      if (!currentHistoryId) return []
      return this.getAgentHistorySessions().filter((item) => asText(item && item.historyId) === currentHistoryId)
    },
    getAgentOtherRangeSessions() {
      const currentHistoryId = this.getCurrentAgentHistoryId()
      return this.getAgentHistorySessions().filter((item) => {
        const sessionHistoryId = asText(item && item.historyId)
        return !currentHistoryId || !sessionHistoryId || sessionHistoryId !== currentHistoryId
      })
    },
    isAgentSummaryHistorySession(session = null) {
      if (!session || typeof session !== 'object') return false
      return asText(session.panelKind) === 'commercial_summary'
    },
    isAgentFollowupHistorySession(session = null) {
      if (!session || typeof session !== 'object') return false
      return asText(session.panelKind) === 'followup'
    },
    splitAgentHistorySessionsByPanel(sessions = []) {
      const summary = []
      const followup = []
      cloneArray(sessions).forEach((session) => {
        if (this.isAgentFollowupHistorySession(session)) {
          followup.push(session)
          return
        }
        if (this.isAgentSummaryHistorySession(session)) {
          summary.push(session)
          return
        }
        followup.push(session)
      })
      return { summary, followup }
    },
    getAgentRangeSessionGroups() {
      const currentSplit = this.splitAgentHistorySessionsByPanel(this.getAgentCurrentRangeSessions())
      const otherSplit = this.splitAgentHistorySessionsByPanel(this.getAgentOtherRangeSessions())
      return [
        {
          id: 'current',
          title: '当前范围',
          count: currentSplit.summary.length + currentSplit.followup.length,
          emptyText: '当前范围暂无历史',
          sessions: [],
          panels: [],
          headingOnly: true,
        },
        {
          id: 'current-summary',
          title: '总结',
          count: currentSplit.summary.length,
          emptyText: '当前范围暂无总结历史',
          sessions: currentSplit.summary,
          collapsible: true,
        },
        {
          id: 'current-followup',
          title: '追问',
          count: currentSplit.followup.length,
          emptyText: '当前范围暂无追问历史',
          sessions: currentSplit.followup,
          collapsible: true,
        },
        {
          id: 'other',
          title: '其他范围',
          count: otherSplit.summary.length + otherSplit.followup.length,
          emptyText: '其他范围暂无历史',
          sessions: [],
          panels: [
            {
              id: 'summary',
              title: '总结',
              count: otherSplit.summary.length,
              emptyText: '其他范围暂无总结历史',
              sessions: otherSplit.summary,
              collapsible: true,
            },
            {
              id: 'followup',
              title: '追问',
              count: otherSplit.followup.length,
              emptyText: '其他范围暂无追问历史',
              sessions: otherSplit.followup,
              collapsible: true,
            },
          ],
        },
      ].filter((group) => group.count > 0 || group.headingOnly)
    },
    isAgentHistorySessionInCurrentRange(session = null) {
      if (!session || typeof session !== 'object') return false
      const currentHistoryId = this.getCurrentAgentHistoryId()
      const sessionHistoryId = asText(session.historyId)
      return Boolean(currentHistoryId && sessionHistoryId && currentHistoryId === sessionHistoryId)
    },
    findAgentSession(sessionId = '') {
      const nextId = asText(sessionId)
      if (!nextId) return null
      return this.agentSessions.find((item) => asText(item && item.id) === nextId) || null
    },
    getActiveAgentSessionId(fallbackSessionId = '') {
      return asText(fallbackSessionId || this.activeAgentSessionId)
    },
    readSessionState(sessionId = '') {
      const nextId = this.getActiveAgentSessionId(sessionId)
      const session = nextId ? this.findAgentSession(nextId) : null
      return session ? cloneAgentSessionRecord(session) : null
    },
    patchSessionState(sessionId = '', patch = null, options = {}) {
      const nextId = this.getActiveAgentSessionId(sessionId)
      if (!nextId) return null
      const updater = typeof patch === 'function'
        ? patch
        : ((session) => ({
          ...session,
          ...(patch && typeof patch === 'object' ? patch : {}),
        }))
      return this.updateAgentSessionSnapshot(nextId, updater, options)
    },
    applyStreamEvent(sessionId = '', eventPatch = null, options = {}) {
      return this.patchSessionState(sessionId, eventPatch, options)
    },
    deriveActiveViewState(sessionId = '') {
      const session = this.readSessionState(sessionId)
      const activeTabId = asText(((this.agentTabs || {}).activeTabId) || '')
      const activeTopTab = typeof this.getAgentActiveTopTab === 'function'
        ? this.getAgentActiveTopTab()
        : null
      const isSummaryTab = asText(activeTopTab && activeTopTab.kind) === 'summary'
      return {
        session,
        activeTabId,
        isSummaryTab,
        followupThread: isSummaryTab
          ? null
          : cloneObject(this.getAgentActiveFollowupTab && this.getAgentActiveFollowupTab()),
      }
    },
    updateAgentSessionSnapshot(sessionId = '', updater = null, options = {}) {
      const nextId = asText(sessionId)
      if (!nextId) return null
      const existing = this.findAgentSession(nextId) || this.createAgentSession()
      const nextSeed = typeof updater === 'function'
        ? updater(cloneAgentSessionRecord(existing) || createAgentSessionRecord({ id: nextId }))
        : { ...existing, ...(updater && typeof updater === 'object' ? updater : {}) }
      const nextSession = createAgentSessionRecord({
        ...existing,
        ...nextSeed,
        id: nextId,
      })
      const filtered = this.agentSessions.filter((item) => asText(item && item.id) !== nextId)
      this.updateAgentSessions([nextSession, ...filtered], { loaded: this.agentSessionsLoaded })
      if (options.syncActive !== false && nextId === asText(this.activeAgentSessionId)) {
        this.applyAgentSessionSnapshot(nextSession)
      }
      return nextSession
    },
    updateAgentSessions(nextSessions = [], options = {}) {
      this.agentSessions = sortAgentSessions(nextSessions)
      if (Object.prototype.hasOwnProperty.call(options || {}, 'loaded')) {
        this.agentSessionsLoaded = !!options.loaded
      }
    },
    applyAgentSessionSnapshot(session, options = {}) {
      if (!session || typeof session !== 'object') return
      if (typeof this.stopAllSummaryTaskLogTracking === 'function') {
        this.stopAllSummaryTaskLogTracking()
      }
      const previousActiveSessionId = asText(this.activeAgentSessionId)
      this.activeAgentSessionId = String(session.id || '')
      this.agentInput = String(session.input || '')
      this.agentSessionHydrating = !!options.hydrating
      this.agentStatus = String(session.status || 'idle')
      this.agentStage = String(session.stage || 'gating')
      this.agentAnswer = String(session.answer || (session.output && session.output.answer) || '')
      this.agentExecutionTrace = cloneArray(session.executionTrace)
      this.agentUsedTools = cloneArray(session.usedTools)
      this.agentCitations = cloneArray(session.citations)
      this.agentResearchNotes = cloneArray(session.researchNotes)
      this.agentAuditIssues = cloneArray(session.auditIssues)
      this.agentPanelPayloads = cloneObject(session.panelPayloads)
      if (typeof this.syncAgentSummaryReadinessFromPanelPayload === 'function') {
        this.syncAgentSummaryReadinessFromPanelPayload(this.agentPanelPayloads)
      }
      if (typeof this.syncSummaryTaskBoardFromPanelPayload === 'function') {
        this.syncSummaryTaskBoardFromPanelPayload(this.agentPanelPayloads)
      }
      this.agentClarificationQuestion = String(session.clarificationQuestion || '')
      this.agentClarificationOptions = cloneArray(session.clarificationOptions)
      this.agentClarificationDraft = ''
      this.agentClarificationSubmitting = false
      this.agentRiskPrompt = String(session.riskPrompt || '')
      this.agentPendingTaskConfirmation = cloneAnalysisTaskConfirmation(session.pendingTaskConfirmation)
      this.agentError = String(session.error || '')
      this.agentContextSummary = cloneObject(session.contextSummary)
      this.agentPlan = normalizeAgentPlanEnvelope(session.plan)
      this.agentPlanExpanded = shouldExpandAgentProcessSection(this.agentStatus, {
        hasContent: hasAgentPlanContent(this.agentPlan),
      })
      this.agentTraceExpanded = shouldExpandAgentProcessSection(this.agentStatus, {
        hasContent: hasAgentExecutionTraceContent(this.agentExecutionTrace),
      })
      this.agentRiskConfirmations = cloneArray(session.riskConfirmations)
      this.agentMessages = cloneArray(session.messages)
      this.agentThinkingTimeline = cloneArray(session.thinkingTimeline)
      this.agentSummaryLoading = false
      this.agentSummaryGenerating = false
      this.agentSummaryProgressPhase = ''
      this.agentLoading = false
      this.agentReasoningBlocks = []
      this.agentStreamingMessageId = ''
      this.agentStreamState = 'idle'
      this.agentStreamStartedAt = 0
      this.agentStreamElapsedTick = 0
      this.agentStreamElapsedTimer = null
      this.agentPanelPreloadNotes = normalizeAgentPanelPreloadNotes(session.panelPreloadNotes)
      this.agentPreloadedPanelKeys = cloneArray(session.preloadedPanelKeys)
      this.agentThinkingExpanded = shouldExpandAgentProcessSection(this.agentStatus, {
        hasContent: !!(
          this.agentThinkingTimeline.length
          || hasAgentPlanContent(this.agentPlan)
          || hasAgentExecutionTraceContent(this.agentExecutionTrace)
        ),
      })
      if (!options.keepDetailLoadingId) {
        this.agentSessionDetailLoadingId = ''
      }
      const analysisWorkspaceTabs = typeof this.getAgentAnalysisWorkspaceTabs === 'function'
        ? this.getAgentAnalysisWorkspaceTabs(this.agentTabs)
        : getAnalysisWorkspaceTabsFromState(this.agentTabs)
      const hasAgentTopTabs = !!(
        this.agentTabs
        && (
          (Array.isArray(this.agentTabs.summaryTabs) && this.agentTabs.summaryTabs.length)
          || (Array.isArray(this.agentTabs.iterationChangeTabs) && this.agentTabs.iterationChangeTabs.length)
          || (Array.isArray(this.agentTabs.siteSelectionTabs) && this.agentTabs.siteSelectionTabs.length)
          || analysisWorkspaceTabs.length
          || (Array.isArray(this.agentTabs.followupTabs) && this.agentTabs.followupTabs.length)
        )
      )
      const shouldRestoreTabs = !!(
        options.hydrating
        || !this.agentTabs
        || !Array.isArray(this.agentTabs.followupTabs)
        || !hasAgentTopTabs
        || previousActiveSessionId !== asText(session.id)
      )
      if (typeof this.restoreAgentTabsFromSession === 'function') {
        if (shouldRestoreTabs) {
          this.restoreAgentTabsFromSession(session)
        } else if (typeof this.ensureAgentTabs === 'function') {
          this.ensureAgentTabs()
          if (typeof this.captureAgentActiveFollowupTabState === 'function') {
            this.captureAgentActiveFollowupTabState()
          }
        }
      }
      this.closeAgentSessionMenu()
      this.syncActiveAgentRuntimeView(session.id)
      if (typeof this.refreshAgentSummaryReadiness === 'function' && typeof this.isAgentSummaryTabActive === 'function') {
        if (this.isAgentSummaryTabActive()) {
          this.refreshAgentSummaryReadiness(false).catch((err) => {
            console.warn('Agent summary readiness refresh failed', err)
          })
        }
      }
    },
    mergeAgentSessionDetail(detail) {
      const existing = this.findAgentSession(detail && detail.id)
      const detailOutput = detail && detail.output && typeof detail.output === 'object' ? detail.output : {}
      const detailPanelPayloads = cloneObject(detailOutput.panel_payloads || detailOutput.panelPayloads || (existing && existing.panelPayloads))
      const session = createAgentSessionRecord({
        ...existing,
        id: detail && detail.id,
        title: detail && detail.title,
        preview: detail && detail.preview,
        historyId: (detail && (detail.history_id || detail.historyId)) || (existing && existing.historyId),
        status: detail && detail.status,
        stage: detail && detail.stage,
        input: detail && detail.input,
        output: detail && detail.output,
        panelPayloads: detailPanelPayloads,
        diagnostics: detail && detail.diagnostics,
        contextSummary: detail && detail.context_summary,
        plan: detail && detail.plan,
        riskConfirmations: detail && detail.risk_confirmations,
        messages: detail && detail.messages,
        isPinned: !!(detail && detail.is_pinned),
        persisted: true,
        snapshotLoaded: true,
        titleSource: detail && detail.title_source,
        panelKind: detail && detail.panel_kind,
        createdAt: detail && detail.created_at,
        updatedAt: detail && detail.updated_at,
        pinnedAt: detail && detail.pinned_at,
      })
      const filtered = this.agentSessions.filter((item) => asText(item && item.id) !== session.id)
      this.updateAgentSessions([session, ...filtered], { loaded: this.agentSessionsLoaded })
      return session
    },
    syncCurrentAgentSession(options = {}) {
      const activeId = this.getActiveAgentSessionId()
      if (!activeId) return null
      if (typeof this.captureAgentActiveFollowupTabState === 'function') {
        this.captureAgentActiveFollowupTabState()
      }
      const existing = this.readSessionState(activeId)
      let messages = cloneArray((existing && existing.messages) || [])
      if (!messages.length) {
        messages = cloneArray(this.agentMessages)
      }
      if (typeof this.getAgentActiveFollowupTab === 'function') {
        const activeFollowupTab = this.getAgentActiveFollowupTab()
        const threadMessages = cloneArray(activeFollowupTab && activeFollowupTab.thread && activeFollowupTab.thread.messages)
        if (threadMessages.length) {
          messages = threadMessages
        }
      }
      const panelPayloads = cloneObject(this.agentPanelPayloads)
      if (typeof this.buildAgentTabsUiState === 'function') {
        panelPayloads.agent_tabs = this.buildAgentTabsUiState()
      }
      if (typeof this.buildSummaryTaskBoardUiState === 'function') {
        panelPayloads.summary_task_board = this.buildSummaryTaskBoardUiState()
      }
      const existingTitleSource = asText(existing && existing.titleSource) || 'fallback'
      const shouldPreserveTitle = existing && ['user', 'ai'].includes(existingTitleSource)
      const fallbackTitle = deriveAgentSessionTitle(messages)
      const draft = createAgentSessionRecord({
        ...existing,
        id: activeId,
        title: shouldPreserveTitle
          ? existing.title
          : (messages.length ? fallbackTitle : clampText(existing && existing.title, 60) || '新报告'),
        preview: deriveAgentSessionPreview({
          error: this.agentError,
          riskPrompt: this.agentRiskPrompt,
          clarificationQuestion: this.agentClarificationQuestion,
          answer: this.agentAnswer,
          messages,
        }),
        updatedAt: new Date().toISOString(),
        createdAt: existing && existing.createdAt ? existing.createdAt : new Date().toISOString(),
        pinnedAt: existing && existing.pinnedAt ? existing.pinnedAt : '',
        historyId: Object.prototype.hasOwnProperty.call(options || {}, 'historyId')
          ? asText(options.historyId)
          : (asText(existing && existing.historyId) || this.getCurrentAgentHistoryId()),
        panelKind: Object.prototype.hasOwnProperty.call(options || {}, 'panelKind')
          ? asText(options.panelKind)
          : asText(existing && existing.panelKind),
        status: String(this.agentStatus || 'idle'),
        stage: String(this.agentStage || 'gating'),
        input: String(this.agentInput || ''),
        output: {
          answer: this.agentAnswer,
          clarificationQuestion: this.agentClarificationQuestion,
          clarificationOptions: this.agentClarificationOptions,
          riskPrompt: this.agentRiskPrompt,
          panelPayloads,
        },
        diagnostics: {
          executionTrace: this.agentExecutionTrace,
          usedTools: this.agentUsedTools,
          citations: this.agentCitations,
          researchNotes: this.agentResearchNotes,
          auditIssues: this.agentAuditIssues,
          planningSummary: asText(
            (existing && existing.diagnostics && (existing.diagnostics.planningSummary || existing.diagnostics.planning_summary))
            || (this.agentPlan && this.agentPlan.summary),
          ),
          auditSummary: asText(existing && existing.diagnostics && (existing.diagnostics.auditSummary || existing.diagnostics.audit_summary)),
          replanCount: Number(existing && existing.diagnostics && (existing.diagnostics.replanCount ?? existing.diagnostics.replan_count ?? 0)) || 0,
          latencyMs: cloneObject(existing && existing.diagnostics && (existing.diagnostics.latencyMs || existing.diagnostics.latency_ms)),
          thinkingTimeline: this.agentThinkingTimeline,
          error: this.agentError,
        },
        contextSummary: this.agentContextSummary,
        plan: this.agentPlan,
        riskConfirmations: this.agentRiskConfirmations,
        pendingTaskConfirmation: cloneAnalysisTaskConfirmation(this.agentPendingTaskConfirmation),
        panelPreloadNotes: this.agentPanelPreloadNotes,
        preloadedPanelKeys: this.agentPreloadedPanelKeys,
        panelPayloads,
        messages,
        isPinned: Object.prototype.hasOwnProperty.call(options || {}, 'isPinned')
          ? !!options.isPinned
          : !!(existing && existing.isPinned),
        persisted: Object.prototype.hasOwnProperty.call(options || {}, 'persisted')
          ? !!options.persisted
          : !!(existing && existing.persisted),
        snapshotLoaded: Object.prototype.hasOwnProperty.call(options || {}, 'snapshotLoaded')
          ? !!options.snapshotLoaded
          : true,
        titleSource: shouldPreserveTitle ? existingTitleSource : (existingTitleSource || 'fallback'),
      })
      const filtered = this.agentSessions.filter((item) => asText(item && item.id) !== activeId)
      this.updateAgentSessions([draft, ...filtered], { loaded: this.agentSessionsLoaded })
      return draft
    },
    async loadAgentSessionSummaries(force = false) {
      if (this.agentSessionsLoading) return this.agentSessions
      if (this.agentSessionsLoaded && !force) return this.agentSessions

      this.agentSessionsLoading = true
      try {
        const res = await fetch('/api/v1/analysis/agent/sessions', {
          cache: force ? 'no-store' : 'default',
        })
        if (!res.ok) {
          throw new Error(`/api/v1/analysis/agent/sessions 请求失败(${res.status})`)
        }
        const data = await res.json()
        const existingById = new Map(this.agentSessions.map((item) => [asText(item && item.id), item]))
        const persistedSessions = Array.isArray(data)
          ? data.map((item) => normalizeAgentSessionSummary(item, existingById.get(asText(item && item.id))))
          : []
        const persistedIds = new Set(persistedSessions.map((item) => item.id))
        const localPersisted = this.agentSessions.filter((item) => {
          const sessionId = asText(item && item.id)
          return !!(item && item.persisted && sessionId && !persistedIds.has(sessionId))
        })
        const localDrafts = this.agentSessions.filter((item) => !item.persisted && !persistedIds.has(asText(item && item.id)))
        this.updateAgentSessions([...persistedSessions, ...localPersisted, ...localDrafts], { loaded: true })
        if (typeof this.hydrateAgentSummaryHistoryDetails === 'function') {
          this.agentSummaryHistoryHydrationPromise = this.hydrateAgentSummaryHistoryDetails().catch((err) => {
            console.warn('Agent summary history detail hydration failed', err)
            return []
          })
        }
        return this.agentSessions
      } finally {
        this.agentSessionsLoading = false
      }
    },
    async hydrateAgentSummaryHistoryDetails(limit = 12) {
      const maxCount = Math.max(0, Number(limit || 0)) || 0
      const targets = this.agentSessions.filter((session) => {
        if (!session || !session.persisted || session.snapshotLoaded) return false
        if (!this.isAgentSummaryHistorySession(session)) return false
        const payloads = session.panelPayloads && typeof session.panelPayloads === 'object' ? session.panelPayloads : {}
        return !(payloads.summary_pack && typeof payloads.summary_pack === 'object')
      }).slice(0, maxCount)
      if (!targets.length) return []
      const details = await Promise.all(targets.map(async (session) => {
        try {
          return await this.loadAgentSessionDetail(session.id)
        } catch (err) {
          console.warn('Agent summary history detail load failed', session.id, err)
          return null
        }
      }))
      return details.filter(Boolean)
    },
    async loadAgentSessionDetail(sessionId = '') {
      const nextId = asText(sessionId)
      if (!nextId) return null
      const res = await fetch(`/api/v1/analysis/agent/sessions/${encodeURIComponent(nextId)}`, {
        cache: 'no-store',
      })
      if (!res.ok) {
        throw new Error(`/api/v1/analysis/agent/sessions/${nextId} 请求失败(${res.status})`)
      }
      const detail = await res.json()
      return this.mergeAgentSessionDetail(detail)
    },
    ensureAgentPanelReady() {
      const activeId = this.getActiveAgentSessionId()
      if (activeId) {
        const existing = this.findAgentSession(activeId)
        if (existing) {
          this.applyAgentSessionSnapshot(existing)
        }
      } else if (!this.agentSessions.length) {
        const session = this.createAgentSession()
        this.updateAgentSessions([session], { loaded: this.agentSessionsLoaded })
        this.applyAgentSessionSnapshot(session)
      } else {
        const localDraft = this.agentSessions.find((item) => !item.persisted) || this.agentSessions[0]
        if (localDraft) {
          this.applyAgentSessionSnapshot(localDraft)
        }
      }

      if (!this.agentSessionsLoaded && !this.agentSessionsLoading) {
        this.loadAgentSessionSummaries(false).catch((err) => {
          console.warn('Agent session summaries load failed', err)
        })
      }
    },
    startNewAgentReportSession() {
      this.agentWorkspaceView = 'report'
      if (typeof this.clearAgentComposerMode === 'function') {
        this.clearAgentComposerMode()
      }
      this.syncCurrentAgentSession()
      const session = this.createAgentSession()
      this.updateAgentSessions([session, ...this.agentSessions], { loaded: this.agentSessionsLoaded })
      this.applyAgentSessionSnapshot(session)
    },
    async activateAgentSession(sessionId = '') {
      const nextId = asText(sessionId)
      if (!nextId) return
      this.agentWorkspaceView = 'report'
      if (nextId === asText(this.activeAgentSessionId)) {
        const current = this.findAgentSession(nextId)
        if (current && current.snapshotLoaded) return
      }

      this.syncCurrentAgentSession()
      let session = this.findAgentSession(nextId)
      if (!session) return
      if (session.persisted && !session.snapshotLoaded) {
        const requestToken = Number(this.agentSessionDetailRequestToken || 0) + 1
        this.agentSessionDetailRequestToken = requestToken
        this.agentSessionDetailLoadingId = nextId
        this.applyAgentSessionSnapshot(createAgentSessionPlaceholderRecord(session), {
          hydrating: true,
          keepDetailLoadingId: true,
        })
        try {
          session = await this.loadAgentSessionDetail(nextId)
          if (
            Number(this.agentSessionDetailRequestToken || 0) !== requestToken
            || asText(this.activeAgentSessionId) !== nextId
          ) {
            return
          }
          this.applyAgentSessionSnapshot(session)
        } catch (err) {
          if (
            Number(this.agentSessionDetailRequestToken || 0) !== requestToken
            || asText(this.activeAgentSessionId) !== nextId
          ) {
            return
          }
          this.applyAgentSessionSnapshot(createAgentSessionRecord({
            ...session,
            error: `加载分析记录失败: ${err && err.message ? err.message : String(err)}`,
            snapshotLoaded: false,
          }))
        } finally {
          if (
            Number(this.agentSessionDetailRequestToken || 0) === requestToken
            && this.agentSessionDetailLoadingId === nextId
          ) {
            this.agentSessionDetailLoadingId = ''
          }
        }
        return
      }
      this.applyAgentSessionSnapshot(session)
    },
  }
}

export { createAgentSessionStoreMethods }
