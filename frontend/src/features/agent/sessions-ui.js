import {
  asText,
  clampText,
  cloneArray,
  cloneAgentSessionRecord,
  cloneObject,
  consumeSseStream,
  createAgentSessionRecord,
  normalizeAgentPanelPreloadNotes,
  normalizeAgentToolSummary,
  sortAgentSessions,
} from './normalizers.js'
import {
  buildAgentPlanChecklist,
  buildAgentToolCallItems,
  hasAgentExecutionTraceContent,
  hasAgentPlanContent,
} from './derived.js'
import {
  buildAnalysisTaskConfirmation,
  cloneAnalysisTaskConfirmation,
  focusAnalysisTaskPanel,
  getAnalysisTaskDefinition,
  getAnalysisTaskDefinitions,
  runAnalysisTask,
} from './analysis-task-registry.js'
import { buildAnalysisTaskParamBundle } from './analysis-task-params.js'

function createAgentUiMethods() {
  return {
    escapeAgentMessageHtml(value = '') {
      return asText(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')
    },
    renderAgentInlineMarkdown(value = '') {
      return this.escapeAgentMessageHtml(value)
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/`([^`]+)`/g, '<code>$1</code>')
    },
    renderAgentMessageHtml(message = {}) {
      const role = asText(message && message.role)
      const content = asText(message && message.content)
      if (!content) return ''
      if (role === 'user') {
        return this.escapeAgentMessageHtml(content).replace(/\n/g, '<br>')
      }
      const lines = content.replace(/\r\n/g, '\n').split('\n')
      const html = []
      for (const rawLine of lines) {
        const line = asText(rawLine).trim()
        if (!line) {
          html.push('<div class="agent-message-gap"></div>')
          continue
        }
        const heading = line.match(/^(#{1,4})\s+(.+)$/)
        if (heading) {
          html.push(`<div class="agent-message-heading">${this.renderAgentInlineMarkdown(heading[2])}</div>`)
          continue
        }
        const quote = line.match(/^>\s*(.+)$/)
        if (quote) {
          html.push(`<div class="agent-message-quote">${this.renderAgentInlineMarkdown(quote[1])}</div>`)
          continue
        }
        const bullet = line.match(/^[-*]\s+(.+)$/)
        if (bullet) {
          html.push(`<div class="agent-message-list-item"><span>•</span><span>${this.renderAgentInlineMarkdown(bullet[1])}</span></div>`)
          continue
        }
        html.push(`<div class="agent-message-paragraph">${this.renderAgentInlineMarkdown(line)}</div>`)
      }
      return html.join('')
    },
    renderAgentReportMarkdownHtml(value = '') {
      const content = asText(value).replace(/\r\n/g, '\n')
      if (!content) return ''
      const lines = content
        .split('\n')
        .filter((line) => !/^```(?:markdown|md)?\s*$/i.test(asText(line).trim()))
      const html = []
      let seenContent = false
      const hasStructuredLines = lines.some((line) => /^(\d+)[.、]\s+/.test(asText(line).trim()) || /^#{1,4}\s+/.test(asText(line).trim()))
      for (const rawLine of lines) {
        const line = asText(rawLine).trim()
        if (!line) {
          if (html.length) html.push('<div class="agent-iteration-report-gap"></div>')
          continue
        }
        const heading = line.match(/^(#{1,4})\s+(.+)$/)
        if (heading) {
          html.push(`<div class="agent-iteration-report-md-heading">${this.renderAgentInlineMarkdown(heading[2])}</div>`)
          seenContent = true
          continue
        }
        if (!seenContent && hasStructuredLines && line.length <= 40 && !/^(\d+)[.、]\s+/.test(line)) {
          html.push(`<div class="agent-iteration-report-md-heading">${this.renderAgentInlineMarkdown(line)}</div>`)
          seenContent = true
          continue
        }
        const numbered = line.match(/^(\d+)[.、]\s+(.+)$/)
        if (numbered) {
          html.push(`<div class="agent-iteration-report-md-list-item"><span>${this.escapeAgentMessageHtml(numbered[1])}.</span><span>${this.renderAgentInlineMarkdown(numbered[2])}</span></div>`)
          seenContent = true
          continue
        }
        const bullet = line.match(/^[-*]\s+(.+)$/)
        if (bullet) {
          html.push(`<div class="agent-iteration-report-md-list-item"><span>•</span><span>${this.renderAgentInlineMarkdown(bullet[1])}</span></div>`)
          seenContent = true
          continue
        }
        html.push(`<div class="agent-iteration-report-md-paragraph">${this.renderAgentInlineMarkdown(line)}</div>`)
        seenContent = true
      }
      return html.join('')
    },
    getAgentSessionTitle(session = null) {
      if (!session || typeof session !== 'object') return '新报告'
      if (this.isAgentSummaryHistorySession && this.isAgentSummaryHistorySession(session)) {
        return this.getAgentSummaryCompactTitle(cloneObject(session.panelPayloads), session.title)
      }
      return clampText(session.title, 60) || '新报告'
    },
    getAgentSessionPreview(session = null) {
      if (!session || typeof session !== 'object') return '开始一份新的区域分析'
      if (this.isAgentSummaryHistorySession && this.isAgentSummaryHistorySession(session)) {
        const pack = this.getAgentSummaryPack(cloneObject(session.panelPayloads))
        const supporting = asText((pack.headline_judgment || {}).supporting_clause)
        const headline = asText((pack.headline_judgment || {}).summary)
        return clampText(supporting || headline || session.preview, 120) || '查看已生成的区域总结'
      }
      return clampText(session.preview, 120) || '开始一份新的区域分析'
    },
    isAgentHistoryGroupCollapsed(groupId = '') {
      const key = asText(groupId)
      if (!key) return false
      const state = this.agentHistoryCollapsedGroups && typeof this.agentHistoryCollapsedGroups === 'object'
        ? this.agentHistoryCollapsedGroups
        : {}
      return !!state[key]
    },
    toggleAgentHistoryGroup(groupId = '', event = null) {
      if (event && typeof event.stopPropagation === 'function') event.stopPropagation()
      const key = asText(groupId)
      if (!key) return
      const state = this.agentHistoryCollapsedGroups && typeof this.agentHistoryCollapsedGroups === 'object'
        ? this.agentHistoryCollapsedGroups
        : {}
      this.agentHistoryCollapsedGroups = {
        ...state,
        [key]: !state[key],
      }
    },
    agentHasConversationContent() {
      const activeTab = this.getAgentActiveTopTab()
      if (!asText(activeTab.id)) return false
      if (asText(activeTab.kind) === 'summary') {
        return this.hasAgentSummaryPack()
      }
      return Boolean(
        (Array.isArray(this.agentMessages) && this.agentMessages.length)
        || (Array.isArray(this.agentCards) && this.agentCards.length)
        || this.agentError
        || this.agentClarificationQuestion
        || this.agentRiskPrompt,
      )
    },
    createDefaultAgentSummaryTab() {
      return {
        id: 'summary',
        kind: 'summary',
        frozen: true,
        source: 'current',
        sessionId: '',
        title: '区域总结',
        createdAt: new Date().toISOString(),
        content: {},
        evidenceRefs: [],
        panelPayloads: {},
      }
    },
    createDefaultAgentTabs() {
      return {
        summaryTab: this.createDefaultAgentSummaryTab(),
        summaryTabs: [],
        iterationChangeTabs: [],
        siteSelectionTabs: [],
        deepAnalysisTabs: [],
        followupTabs: [],
        activeTabId: '',
        followupLimit: 6,
        nextFollowupNumber: 1,
      }
    },
    normalizeAgentFollowupTitle(title = '') {
      const raw = asText(title)
      if (!raw) return '追问解释'
      return /^追问(?:解释)?\d*$/u.test(raw) ? '追问解释' : raw
    },
    getAgentTabKindLabel(kind = '') {
      const normalized = asText(kind)
      if (normalized === 'summary') return '区域总结'
      if (normalized === 'iteration_change') return '多年迭代变化'
      if (normalized === 'site_selection') return '区域内选址'
      if (normalized === 'deep_analysis') return '继续分析'
      return '追问解释'
    },
    extractAgentTabShortTitle(kind = '', seed = '') {
      const label = this.getAgentTabKindLabel(kind)
      const raw = clampText(asText(seed).replace(/^(?:区域总结|多年迭代变化|区域内选址|继续分析|追问解释|总结|追问)\s*[·:：-]\s*/u, '').trim(), 24)
      if (raw) return raw
      return label
    },
    extractAgentSummaryCompactTitle(seed = '') {
      return '总结'
    },
    getAgentSummaryCompactTitle(panelPayloads = null, fallbackTitle = '') {
      const pack = this.getAgentSummaryPack(panelPayloads)
      const headline = asText(((pack.headline_judgment || {}).summary) || fallbackTitle)
      return this.extractAgentSummaryCompactTitle(headline)
    },
    formatAgentTabTitle(kind = '', seed = '') {
      const label = this.getAgentTabKindLabel(kind)
      const shortTitle = this.extractAgentTabShortTitle(kind, seed)
      return shortTitle && shortTitle !== label ? `${label} · ${shortTitle}` : label
    },
    getAgentSummaryViewTitle(panelPayloads = null, fallbackTitle = '') {
      return this.getAgentSummaryCompactTitle(panelPayloads, fallbackTitle)
    },
    getAgentFollowupViewTitle(seed = null, fallbackTitle = '') {
      const source = seed && typeof seed === 'object' ? seed : {}
      const firstUserMessage = cloneArray(source.messages)
        .find((item) => asText(item && item.role) === 'user' && asText(item && item.content))
      const titleSeed = asText(source.title || fallbackTitle || (firstUserMessage && firstUserMessage.content))
      return this.formatAgentTabTitle('followup', titleSeed)
    },
    createAgentFollowupThreadState(seed = {}) {
      const normalized = cloneObject(seed)
      return {
        input: String(normalized.input || ''),
        status: String(normalized.status || 'idle'),
        stage: String(normalized.stage || 'gating'),
        messages: cloneArray(normalized.messages),
        cards: cloneArray(normalized.cards),
        decision: cloneObject(normalized.decision || { summary: '', mode: 'judgment', strength: 'weak', canAct: false }),
        support: cloneArray(normalized.support),
        counterpoints: cloneArray(normalized.counterpoints),
        actions: cloneArray(normalized.actions),
        boundary: cloneArray(normalized.boundary),
        executionTrace: cloneArray(normalized.executionTrace),
        usedTools: cloneArray(normalized.usedTools),
        citations: cloneArray(normalized.citations),
        researchNotes: cloneArray(normalized.researchNotes),
        auditIssues: cloneArray(normalized.auditIssues),
        nextSuggestions: cloneArray(normalized.nextSuggestions),
        clarificationQuestion: String(normalized.clarificationQuestion || ''),
        clarificationOptions: cloneArray(normalized.clarificationOptions),
        riskPrompt: String(normalized.riskPrompt || ''),
        error: String(normalized.error || ''),
        contextSummary: cloneObject(normalized.contextSummary),
        plan: cloneObject(normalized.plan || { steps: [], followupSteps: [], followupApplied: false, summary: '' }),
        panelPayloads: cloneObject(normalized.panelPayloads),
        panelPreloadNotes: cloneArray(normalized.panelPreloadNotes),
        preloadedPanelKeys: cloneArray(normalized.preloadedPanelKeys),
        thinkingTimeline: cloneArray(normalized.thinkingTimeline),
        pendingTaskConfirmation: cloneObject(normalized.pendingTaskConfirmation),
        riskConfirmations: cloneArray(normalized.riskConfirmations),
        deepAnalysisMode: asText(normalized.deepAnalysisMode || normalized.deep_analysis_mode) || 'quick',
      }
    },
    buildAgentFollowupThreadFromCurrentState() {
      return this.createAgentFollowupThreadState({
        input: this.agentInput,
        status: this.agentStatus,
        stage: this.agentStage,
        messages: this.agentMessages,
        cards: this.agentCards,
        decision: this.agentDecision,
        support: this.agentSupport,
        counterpoints: this.agentCounterpoints,
        actions: this.agentActions,
        boundary: this.agentBoundary,
        reviewContract: this.agentReviewContract,
        executionTrace: this.agentExecutionTrace,
        usedTools: this.agentUsedTools,
        citations: this.agentCitations,
        researchNotes: this.agentResearchNotes,
        auditIssues: this.agentAuditIssues,
        nextSuggestions: this.agentNextSuggestions,
        clarificationQuestion: this.agentClarificationQuestion,
        clarificationOptions: this.agentClarificationOptions,
        riskPrompt: this.agentRiskPrompt,
        error: this.agentError,
        contextSummary: this.agentContextSummary,
        plan: this.agentPlan,
        panelPayloads: this.agentPanelPayloads,
        panelPreloadNotes: this.agentPanelPreloadNotes,
        preloadedPanelKeys: this.agentPreloadedPanelKeys,
        thinkingTimeline: this.agentThinkingTimeline,
        pendingTaskConfirmation: this.agentPendingTaskConfirmation,
        riskConfirmations: this.agentRiskConfirmations,
        deepAnalysisMode: this.agentDeepAnalysisMode,
      })
    },
    applyAgentFollowupThreadToCurrentState(thread = null) {
      const state = this.createAgentFollowupThreadState(thread || {})
      this.agentInput = String(state.input || '')
      this.agentStatus = String(state.status || 'idle')
      this.agentStage = String(state.stage || 'gating')
      this.agentMessages = cloneArray(state.messages)
      this.agentCards = cloneArray(state.cards)
      this.agentDecision = cloneObject(state.decision)
      this.agentSupport = cloneArray(state.support)
      this.agentCounterpoints = cloneArray(state.counterpoints)
      this.agentActions = cloneArray(state.actions)
      this.agentBoundary = cloneArray(state.boundary)
      this.agentReviewContract = cloneObject(state.reviewContract)
      this.agentExecutionTrace = cloneArray(state.executionTrace)
      this.agentUsedTools = cloneArray(state.usedTools)
      this.agentCitations = cloneArray(state.citations)
      this.agentResearchNotes = cloneArray(state.researchNotes)
      this.agentAuditIssues = cloneArray(state.auditIssues)
      this.agentNextSuggestions = cloneArray(state.nextSuggestions)
      this.agentClarificationQuestion = String(state.clarificationQuestion || '')
      this.agentClarificationOptions = cloneArray(state.clarificationOptions)
      this.agentRiskPrompt = String(state.riskPrompt || '')
      this.agentError = String(state.error || '')
      this.agentContextSummary = cloneObject(state.contextSummary)
      this.agentPlan = cloneObject(state.plan)
      this.agentPanelPayloads = cloneObject(state.panelPayloads)
      this.agentPanelPreloadNotes = normalizeAgentPanelPreloadNotes(state.panelPreloadNotes)
      this.agentPreloadedPanelKeys = cloneArray(state.preloadedPanelKeys)
      this.agentThinkingTimeline = cloneArray(state.thinkingTimeline)
      this.agentPendingTaskConfirmation = cloneAnalysisTaskConfirmation(state.pendingTaskConfirmation)
      this.agentRiskConfirmations = cloneArray(state.riskConfirmations)
      this.agentDeepAnalysisMode = asText(state.deepAnalysisMode) || 'quick'
    },
    getAgentActiveTopTab() {
      const tabs = this.ensureAgentTabs(false)
      const activeId = asText(tabs.activeTabId)
      const summaryTab = cloneArray(tabs.summaryTabs).find((item) => asText(item && item.id) === activeId)
      if (summaryTab) return { ...cloneObject(summaryTab), kind: 'summary', fixed: false }
      const iterationChangeTab = cloneArray(tabs.iterationChangeTabs).find((item) => asText(item && item.id) === activeId)
      if (iterationChangeTab) return { ...cloneObject(iterationChangeTab), kind: 'iteration_change', fixed: false }
      const siteSelectionTab = cloneArray(tabs.siteSelectionTabs).find((item) => asText(item && item.id) === activeId)
      if (siteSelectionTab) return { ...cloneObject(siteSelectionTab), kind: 'site_selection', fixed: false }
      const deepAnalysisTab = cloneArray(tabs.deepAnalysisTabs).find((item) => asText(item && item.id) === activeId)
      if (deepAnalysisTab) return { ...cloneObject(deepAnalysisTab), kind: 'deep_analysis', fixed: false }
      const followupTab = cloneArray(tabs.followupTabs).find((item) => asText(item && item.id) === activeId)
      if (followupTab) return { ...cloneObject(followupTab), kind: 'followup', fixed: false }
      return { id: '', kind: '', fixed: false, source: '', sessionId: '', title: '' }
    },
    isCurrentAgentSummaryTabActive() {
      const activeTab = this.getAgentActiveTopTab()
      return asText(activeTab.kind) === 'summary' && asText(activeTab.source) === 'current'
    },
    createAgentSummaryViewId() {
      return `summary-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
    },
    createAgentSiteSelectionViewId() {
      return `site-selection-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
    },
    createAgentIterationChangeViewId() {
      return `iteration-change-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
    },
    createAgentDeepAnalysisViewId() {
      return `deep-analysis-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
    },
    isAgentActiveTabReadonly() {
      const activeTab = this.getAgentActiveTopTab()
      return !!activeTab.readonly
    },
    isAgentHistorySessionTabActive(sessionId = '') {
      const nextSessionId = asText(sessionId)
      if (!nextSessionId) return false
      return asText(this.getAgentActiveTopTab().sessionId) === nextSessionId
    },
    isAgentHistorySessionInCurrentRange(session = null) {
      if (!session || typeof session !== 'object') return false
      const currentHistoryId = asText(this.getCurrentAgentHistoryId && this.getCurrentAgentHistoryId())
      const historyId = asText(session.historyId)
      return Boolean(historyId && currentHistoryId && historyId === currentHistoryId)
    },
    getAgentActiveSummaryPanelPayloads() {
      const tabs = this.ensureAgentTabs(false)
      const activeTab = this.getAgentActiveTopTab()
      if (asText(activeTab.kind) === 'summary' && activeTab.panelPayloads && typeof activeTab.panelPayloads === 'object') {
        return cloneObject(activeTab.panelPayloads)
      }
      const payloads = cloneObject(this.agentPanelPayloads)
      if (payloads.summary_pack && typeof payloads.summary_pack === 'object') {
        return payloads
      }
      const fallbackPack = cloneObject(((tabs.summaryTab || {}).content) || {})
      if (!Object.keys(fallbackPack).length) {
        return payloads
      }
      return {
        ...payloads,
        summary_pack: fallbackPack,
        summary_status: {
          status: this.hasAgentSummaryPack(fallbackPack) ? 'ready' : 'idle',
          generated: this.hasAgentSummaryPack(fallbackPack),
          ...cloneObject((payloads.summary_status && typeof payloads.summary_status === 'object') ? payloads.summary_status : {}),
        },
      }
    },
    getAgentSummaryPack(panelPayloads = null) {
      const payloads = panelPayloads && typeof panelPayloads === 'object'
        ? cloneObject(panelPayloads)
        : this.getAgentActiveSummaryPanelPayloads()
      const pack = payloads.summary_pack && typeof payloads.summary_pack === 'object'
        ? payloads.summary_pack
        : {}
      return cloneObject(pack)
    },
    getAgentSummaryTourismCrossAnalysis(panelPayloads = null) {
      const pack = this.getAgentSummaryPack(panelPayloads)
      const payload = pack.tourism_cross_analysis && typeof pack.tourism_cross_analysis === 'object'
        ? pack.tourism_cross_analysis
        : {}
      return {
        title: asText(payload.title) || '文旅交叉策划分析',
        content: asText(payload.content),
      }
    },
    commitAgentSummaryPayloadsToActiveTab() {
      const tabs = this.ensureAgentTabs(true)
      const activeTab = this.getAgentActiveTopTab()
      const activeId = asText(activeTab.id || tabs.activeTabId)
      const currentPayloads = {
        ...cloneObject(this.agentPanelPayloads),
        summary_task_board: this.buildSummaryTaskBoardUiState(),
      }
      const summaryPack = this.getAgentSummaryPack(currentPayloads)
      const nextTabs = cloneArray(tabs.summaryTabs).map((item) => {
        if (asText(item.id) !== activeId) return item
        return {
          ...item,
          title: this.getAgentSummaryViewTitle(currentPayloads, item.title || '区域总结'),
          panelPayloads: cloneObject(currentPayloads),
          content: cloneObject(summaryPack),
          evidenceRefs: cloneArray(summaryPack.evidence_refs || item.evidenceRefs || []),
        }
      })
      this.agentTabs = {
        ...tabs,
        summaryTabs: nextTabs,
      }
      this.agentPanelPayloads = currentPayloads
      return currentPayloads
    },
    getAgentSummaryAreaJudgments(panelPayloads = null) {
      const pack = this.getAgentSummaryPack(panelPayloads)
      const rows = Array.isArray(pack.secondary_conclusions) ? pack.secondary_conclusions : []
      const sectionOrder = [
        ['spatial_structure', '空间结构'],
        ['poi_structure', 'POI结构'],
        ['consumption_vitality', '经济活动强度'],
        ['business_support', '业态承接'],
      ]
      const mapped = sectionOrder.map(([sectionKey, fallbackTitle]) => {
        const direct = pack[sectionKey] && typeof pack[sectionKey] === 'object'
          ? pack[sectionKey]
          : null
        const matched = direct || rows.find((item) => {
          const key = asText(item && (item.section_key || item.sectionKey))
          const title = asText(item && item.title)
          return key === sectionKey || title === fallbackTitle
        })
        if (!matched || typeof matched !== 'object') return null
        const dimensions = Array.isArray(matched.dimensions) ? matched.dimensions : []
        return {
          sectionKey,
          title: asText(matched.title || fallbackTitle) || fallbackTitle,
          reasoning: asText(matched.reasoning),
          dimensions: dimensions
            .map((item) => ({
              key: asText(item && item.key),
              label: asText(item && item.label),
              conclusion: asText(item && item.conclusion),
            }))
            .filter((item) => item.conclusion),
        }
      }).filter((item) => item && item.reasoning)
      if (mapped.length === sectionOrder.length) return mapped
      return rows.map((item, index) => ({
        sectionKey: asText(item && (item.section_key || item.sectionKey)) || `legacy-${index}`,
        title: asText(item && item.title) || '-',
        reasoning: asText(item && item.reasoning) || '-',
        dimensions: Array.isArray(item && item.dimensions)
          ? item.dimensions.map((dim) => ({
            key: asText(dim && dim.key),
            label: asText(dim && dim.label),
            conclusion: asText(dim && dim.conclusion),
          })).filter((dim) => dim.conclusion)
          : [],
      }))
    },
    getAgentSummarySecondaryConclusions(panelPayloads = null) {
      return this.getAgentSummaryAreaJudgments(panelPayloads)
    },
    getAgentSummaryStatus(panelPayloads = null) {
      const payloads = panelPayloads && typeof panelPayloads === 'object'
        ? cloneObject(panelPayloads)
        : this.getAgentActiveSummaryPanelPayloads()
      const status = payloads.summary_status && typeof payloads.summary_status === 'object'
        ? payloads.summary_status
        : {}
      const summaryPack = this.getAgentSummaryPack(payloads)
      return {
        status: asText(status.status || (this.hasAgentSummaryPack(summaryPack) ? 'ready' : 'idle')) || 'idle',
        generated: !!status.generated || this.hasAgentSummaryPack(summaryPack),
        llmAvailable: Object.prototype.hasOwnProperty.call(status, 'llm_available') ? !!status.llm_available : true,
        title: asText(status.title || ''),
        description: asText(status.description || ''),
        message: asText(status.message || ''),
        errorCode: asText(status.error_code || ''),
        errorStage: asText(status.error_stage || ''),
        retryable: Object.prototype.hasOwnProperty.call(status, 'retryable') ? !!status.retryable : true,
      }
    },
    syncAgentSummaryStateFromPanelPayload(panelPayloads = null) {
      const payloads = cloneObject(panelPayloads || this.getAgentActiveSummaryPanelPayloads())
      this.syncAgentSummaryReadinessFromPanelPayload(payloads)
      this.syncSummaryTaskBoardFromPanelPayload(payloads)
      return payloads
    },
    hasAgentSummaryPack(summaryPackSeed = null) {
      const summaryPack = summaryPackSeed && typeof summaryPackSeed === 'object'
        ? cloneObject(summaryPackSeed)
        : this.getAgentSummaryPack()
      const areaJudgments = this.getAgentSummaryAreaJudgments({ summary_pack: summaryPack })
      return !!(
        ((summaryPack.headline_judgment || {}).summary)
        && areaJudgments.length === 4
        && (((summaryPack.user_profile || {}).headline) || Array.isArray((summaryPack.user_profile || {}).traits))
        && (((summaryPack.behavior_inference || {}).headline) || Array.isArray((summaryPack.behavior_inference || {}).traits))
      )
    },
    shouldShowAgentSummaryGeneratedState() {
      const status = this.getAgentSummaryStatus()
      const ready = this.isCurrentAgentSummaryTabActive() ? this.agentSummaryReadiness.ready : true
      return ready && status.generated && this.hasAgentSummaryPack()
    },
    shouldShowAgentSummaryGeneratingState() {
      return this.isCurrentAgentSummaryTabActive() && !!this.agentSummaryGenerating
    },
    openBasisDrawer(payload = null, event = null) {
      if (event && typeof event.stopPropagation === 'function') event.stopPropagation()
      this.basisDrawerPayload = this.normalizeBasisPayload(payload)
      this.basisDrawerActiveTab = 'basic'
      this.basisPromptEditMode = false
      this.basisPromptError = ''
      this.basisPromptNotice = ''
      this.basisDrawerOpen = true
      if (this.basisDrawerPayload.promptKey && !asText(this.basisDrawerPayload.promptSnapshot && this.basisDrawerPayload.promptSnapshot.prompt_key)) {
        this.ensureAgentPromptConfig(this.basisDrawerPayload.promptKey)
          .then((config) => {
            if (!config || !this.basisDrawerOpen) return
            const current = this.normalizeBasisPayload(this.basisDrawerPayload)
            if (asText(current.promptSnapshot && current.promptSnapshot.prompt_key)) return
            this.basisDrawerPayload = this.normalizeBasisPayload({
              ...current,
              promptSnapshot: config,
              promptSourceLabel: '当前配置，非历史快照',
              aiPrompt: config.system_prompt,
              aiPromptPayloadNote: config.payload_note,
              outputSchema: config.output_schema,
            })
          })
          .catch(() => {})
      }
    },
    closeBasisDrawer() {
      this.basisDrawerOpen = false
      this.basisDrawerPayload = null
      this.basisDrawerActiveTab = 'basic'
      this.basisPromptEditMode = false
      this.basisPromptError = ''
      this.basisPromptNotice = ''
    },
    normalizeContextAskTarget(target = null) {
      const source = target && typeof target === 'object' ? target : {}
      const allowedTypes = new Set(['report_section', 'trend_chart', 'trend_metric', 'site_candidate'])
      const allowedSources = new Set(['report', 'iteration', 'site_selection'])
      const type = allowedTypes.has(asText(source.type)) ? asText(source.type) : 'report_section'
      const targetSource = allowedSources.has(asText(source.source)) ? asText(source.source) : 'report'
      const title = clampText(asText(source.title), 80) || '当前上下文'
      const evidence = cloneArray(source.evidence || source.evidence_refs || source.evidenceRefs)
        .map((item) => (item && typeof item === 'object' ? cloneObject(item) : asText(item)))
        .filter((item) => (typeof item === 'object' ? Object.keys(item).length : !!item))
      const artifactRefs = cloneArray(source.artifactRefs || source.artifact_refs)
        .map((item) => asText(item))
        .filter(Boolean)
      return {
        type,
        id: asText(source.id || source.key) || `${type}-${Date.now().toString(36)}`,
        title,
        source: targetSource,
        summary: clampText(asText(source.summary || source.reasoning || source.content || source.value), 800),
        evidence,
        artifactRefs,
        payload: cloneObject(source.payload),
      }
    },
    getContextAskSourceLabel(source = '') {
      const labels = {
        report: '区域报告',
        iteration: '多年变化',
        site_selection: '区域内选址',
      }
      return labels[asText(source)] || '当前分析'
    },
    getContextAskQuickQuestions() {
      return ['为什么这么判断？', '用了哪些证据？', '这个结论可靠吗？']
    },
    openContextAsk(target = null, options = {}) {
      const normalized = this.normalizeContextAskTarget(target)
      this.contextAskTarget = normalized
      this.contextAskVisible = true
      this.contextAskMinimized = !!options.minimized
      this.contextAskError = ''
      this.contextAskDraft = asText(options.question)
      if (!Array.isArray(this.contextAskMessages) || options.resetMessages) {
        this.contextAskMessages = []
      }
      if (!this.contextAskMessages.length || options.resetMessages) {
        this.contextAskMessages = [{
          role: 'assistant',
          content: `我会围绕“${normalized.title}”解释，不会离开当前区域上下文。`,
          evidence: [],
          citations: [],
          warnings: [],
        }]
      }
      return normalized
    },
    closeContextAsk() {
      this.contextAskVisible = false
      this.contextAskMinimized = false
      this.contextAskLoading = false
      this.contextAskError = ''
      this.contextAskDraft = ''
    },
    minimizeContextAsk() {
      this.contextAskMinimized = !this.contextAskMinimized
      this.contextAskVisible = true
    },
    resizeContextAsk(size = {}) {
      const current = this.contextAskSize && typeof this.contextAskSize === 'object'
        ? this.contextAskSize
        : { width: 420, height: 560 }
      const width = Math.min(720, Math.max(320, Number(size.width || current.width || 420)))
      const height = Math.min(760, Math.max(220, Number(size.height || current.height || 560)))
      this.contextAskSize = { width, height }
      return this.contextAskSize
    },
    buildContextAskFallbackAnswer(question = '', targetSeed = null) {
      const target = this.normalizeContextAskTarget(targetSeed || this.contextAskTarget)
      const summary = asText(target.summary) || '当前对象没有完整自然语言摘要，需要结合右侧证据和图表继续核对。'
      const evidenceCount = cloneArray(target.evidence).length
      const refsCount = cloneArray(target.artifactRefs).length
      const basis = evidenceCount ? `已有 ${evidenceCount} 条证据可参考` : '当前上下文没有传入结构化证据'
      const refs = refsCount ? `，并关联 ${refsCount} 个产物引用` : ''
      return [
        `针对“${target.title}”：${summary}`,
        `你的问题是“${asText(question) || '请解释这个判断'}”。${basis}${refs}。`,
        '不确定性：这个回答只解释当前点击对象，不会重新跑工具；如果原始数据缺失或证据链较弱，需要回到报告证据抽屉复核。',
      ].join('\n')
    },
    async submitContextAskQuestion(question = '') {
      const text = asText(question || this.contextAskDraft).trim()
      if (!text || this.contextAskLoading) return null
      const target = this.normalizeContextAskTarget(this.contextAskTarget)
      this.contextAskVisible = true
      this.contextAskMinimized = false
      this.contextAskDraft = ''
      this.contextAskError = ''
      this.contextAskMessages = [
        ...cloneArray(this.contextAskMessages),
        { role: 'user', content: text },
      ]
      this.contextAskLoading = true
      try {
        const response = await fetch('/api/v1/analysis/agent/context-ask', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            conversation_id: this.getActiveAgentSessionId ? this.getActiveAgentSessionId() : asText(this.activeAgentSessionId),
            history_id: asText(this.getCurrentAgentHistoryId && this.getCurrentAgentHistoryId()),
            question: text,
            analysis_snapshot: this.buildAgentAnalysisSnapshot ? this.buildAgentAnalysisSnapshot() : {},
            target: {
              ...target,
              artifact_refs: cloneArray(target.artifactRefs),
            },
          }),
        })
        let data = {}
        try { data = await response.json() } catch (_) { data = {} }
        if (!response.ok || asText(data.status) === 'failed') {
          throw new Error(asText(data.error || data.detail) || `context_ask_failed_${response.status}`)
        }
        const assistant = {
          role: 'assistant',
          content: asText(data.answer) || this.buildContextAskFallbackAnswer(text, target),
          evidence: cloneArray(data.evidence),
          citations: cloneArray(data.citations),
          warnings: cloneArray(data.warnings),
        }
        this.contextAskMessages = [...cloneArray(this.contextAskMessages), assistant]
        return assistant
      } catch (error) {
        const assistant = {
          role: 'assistant',
          content: this.buildContextAskFallbackAnswer(text, target),
          evidence: cloneArray(target.evidence),
          citations: cloneArray(target.artifactRefs),
          warnings: ['AI 解释接口暂不可用，已返回本地规则解释。'],
        }
        this.contextAskMessages = [...cloneArray(this.contextAskMessages), assistant]
        this.contextAskError = asText(error && error.message)
        return assistant
      } finally {
        this.contextAskLoading = false
      }
    },
    buildReportSectionContextAskTarget(seed = {}) {
      const source = seed && typeof seed === 'object' ? seed : { summary: asText(seed) }
      const sectionKey = asText(source.sectionKey || source.section_key || source.id || source.key) || 'report-section'
      const basis = this.buildAgentSummaryBasisPayload
        ? this.buildAgentSummaryBasisPayload({
          sectionKey,
          title: asText(source.title) || '区域报告',
          reasoning: asText(source.reasoning || source.summary || source.content || source.value),
        })
        : {}
      return this.normalizeContextAskTarget({
        type: 'report_section',
        id: sectionKey,
        title: asText(source.title) || asText(basis.title) || '区域报告',
        source: 'report',
        summary: asText(source.summary || source.reasoning || source.content || source.value || basis.currentConclusion),
        evidence: cloneArray(source.evidence || basis.fields),
        artifactRefs: cloneArray(source.artifactRefs || source.artifact_refs || basis.evidenceRefs),
        payload: {
          section_key: sectionKey,
          dimensions: cloneArray(source.dimensions),
          basis,
        },
      })
    },
    buildIterationContextAskTarget(seed = {}) {
      const source = seed && typeof seed === 'object' ? seed : { summary: asText(seed) }
      const kind = asText(source.kind || this.agentIterationActiveKind) || 'poi'
      const section = asText(source.section || source.id || source.key) || kind
      const payload = source.payload && typeof source.payload === 'object'
        ? cloneObject(source.payload)
        : this.getAgentIterationPayload(kind)
      return this.normalizeContextAskTarget({
        type: asText(source.type) || 'trend_metric',
        id: `${kind}-${section}`,
        title: asText(source.title) || this.getAgentIterationActiveDescription(),
        source: 'iteration',
        summary: asText(source.summary || source.value || payload.notice || payload.report_title),
        evidence: cloneArray(source.evidence || source.rows || payload.report_sections || payload.ai_summary),
        artifactRefs: cloneArray(source.artifactRefs || source.artifact_refs),
        payload: {
          kind,
          section,
          row: cloneObject(source.row),
          payload,
        },
      })
    },
    buildSiteCandidateContextAskTarget(candidate = null) {
      const source = candidate && typeof candidate === 'object'
        ? candidate
        : (this.getAgentSiteSelectionSelectedCandidate ? this.getAgentSiteSelectionSelectedCandidate() : {})
      const evidenceChain = this.getAgentSiteSelectionEvidenceChain ? this.getAgentSiteSelectionEvidenceChain() : []
      return this.normalizeContextAskTarget({
        type: 'site_candidate',
        id: asText(source.h3Id || source.h3_id || source.title) || 'site-candidate',
        title: asText(source.title) || `候选 ${source.rank || ''}`.trim() || '候选点',
        source: 'site_selection',
        summary: asText(source.reason) || cloneArray(source.whySuitable).join('；') || cloneArray(source.strengths).join('；'),
        evidence: evidenceChain,
        artifactRefs: [asText(source.h3Id || source.h3_id)].filter(Boolean),
        payload: {
          rank: Number(source.rank || 0) || 0,
          h3Id: asText(source.h3Id || source.h3_id),
          score: Number(source.totalScore || source.total_score || 0) || 0,
          reason: asText(source.reason),
          strengths: cloneArray(source.strengths).map((item) => asText(item)).filter(Boolean),
          risks: cloneArray(source.risks).map((item) => asText(item)).filter(Boolean),
          whySuitable: cloneArray(source.whySuitable || source.why_suitable).map((item) => asText(item)).filter(Boolean),
          validationSteps: cloneArray(source.nextValidationSteps || source.next_validation_steps).map((item) => asText(item)).filter(Boolean),
          evidence_chain: evidenceChain,
        },
      })
    },
    setBasisDrawerTab(tab = 'basic') {
      const key = asText(tab) || 'basic'
      if (!this.getBasisDrawerTabs().some((item) => item.key === key)) return
      this.basisDrawerActiveTab = key
    },
    getBasisDrawerTabs() {
      return [
        { key: 'basic', label: '基础说明' },
        { key: 'validation', label: '输出验证' },
        { key: 'template', label: '规则模板' },
        { key: 'raw', label: '原始字段' },
      ]
    },
    getBasisDrawerPayload() {
      return this.normalizeBasisPayload(this.basisDrawerPayload || {})
    },
    normalizeBasisPayload(payload = null) {
      const source = payload && typeof payload === 'object' ? payload : {}
      const sourceType = asText(source.sourceType || source.source_type || 'rule')
      const defaultPrompt = sourceType === 'rule'
        ? '该结论由规则模板生成，未调用 AI'
        : '当前结果没有可追溯的 AI prompt。'
      return {
        title: asText(source.title) || '生成依据',
        currentConclusion: asText(source.currentConclusion || source.current_conclusion),
        fields: cloneArray(source.fields).filter((item) => item && (asText(item.label) || asText(item.key))),
        rules: cloneArray(source.rules).map((item) => asText(item)).filter(Boolean),
        template: asText(source.template),
        aiPrompt: asText(source.aiPrompt || source.ai_prompt) || defaultPrompt,
        aiPromptPayloadNote: asText(source.aiPromptPayloadNote || source.ai_prompt_payload_note),
        outputSchema: cloneObject(source.outputSchema || source.output_schema || {}),
        promptKey: asText(source.promptKey || source.prompt_key),
        promptSnapshot: cloneObject(source.promptSnapshot || source.prompt_snapshot || {}),
        promptSourceLabel: asText(source.promptSourceLabel || source.prompt_source_label),
        rawInput: cloneObject(source.rawInput || source.raw_input || {}),
        validationResults: cloneObject(source.validationResults || source.validation_results || {}),
        sourceType,
      }
    },
    normalizeAgentPromptConfig(seed = null) {
      const source = seed && typeof seed === 'object' ? seed : {}
      return {
        prompt_key: asText(source.prompt_key || source.promptKey),
        title: asText(source.title),
        system_prompt: asText(source.system_prompt || source.systemPrompt),
        payload_note: asText(source.payload_note || source.payloadNote),
        output_schema: cloneObject(source.output_schema || source.outputSchema || {}),
        evidence_version: asText(source.evidence_version || source.evidenceVersion),
        updated_at: asText(source.updated_at || source.updatedAt),
      }
    },
    async ensureAgentPromptConfig(promptKey = '', force = false) {
      const key = asText(promptKey)
      if (!key) return null
      if (!force && this.agentPromptConfigs && this.agentPromptConfigs[key]) {
        return this.normalizeAgentPromptConfig(this.agentPromptConfigs[key])
      }
      const res = await fetch(`/api/v1/analysis/agent/prompts/${encodeURIComponent(key)}`)
      if (!res.ok) throw new Error(`提示词配置读取失败(${res.status})`)
      const config = this.normalizeAgentPromptConfig(await res.json())
      this.agentPromptConfigs = { ...cloneObject(this.agentPromptConfigs), [key]: config }
      return config
    },
    getBasisPromptEffectiveConfig() {
      const payload = this.getBasisDrawerPayload()
      const snapshot = this.normalizeAgentPromptConfig(payload.promptSnapshot)
      if (snapshot.prompt_key) return snapshot
      const current = this.normalizeAgentPromptConfig((this.agentPromptConfigs || {})[payload.promptKey])
      return current.prompt_key ? current : { prompt_key: payload.promptKey }
    },
    getPromptMissingMessage(promptKey = '') {
      const key = asText(promptKey)
      if (!key) return '当前结果没有可追溯的 AI prompt。'
      return `当前结果没有本次 AI 调用 prompt 快照；可读取当前 Prompt Registry 配置，但这不是历史调用证据。prompt_key: ${key}`
    },
    resolveBasisPromptDisplay(promptKey = '', promptSnapshotSeed = null) {
      const key = asText(promptKey)
      const snapshot = this.normalizeAgentPromptConfig(promptSnapshotSeed)
      if (snapshot.prompt_key && snapshot.system_prompt) {
        return {
          aiPrompt: snapshot.system_prompt,
          aiPromptPayloadNote: snapshot.payload_note,
          outputSchema: cloneObject(snapshot.output_schema),
          promptSnapshot: snapshot,
          promptSourceLabel: '本次生成实际使用的提示词快照',
        }
      }
      const current = this.normalizeAgentPromptConfig((this.agentPromptConfigs || {})[key])
      if (current.prompt_key && current.system_prompt) {
        return {
          aiPrompt: current.system_prompt,
          aiPromptPayloadNote: current.payload_note,
          outputSchema: cloneObject(current.output_schema),
          promptSnapshot: current,
          promptSourceLabel: '当前配置，非历史快照',
        }
      }
      return {
        aiPrompt: this.getPromptMissingMessage(key),
        aiPromptPayloadNote: '',
        outputSchema: {},
        promptSnapshot: snapshot.prompt_key ? snapshot : {},
        promptSourceLabel: key ? '无本次调用快照' : '无可追溯提示词',
      }
    },
    startBasisPromptEdit() {
      const config = this.getBasisPromptEffectiveConfig()
      this.basisPromptDraft = {
        system_prompt: asText(config.system_prompt),
        payload_note: asText(config.payload_note),
        output_schema_text: this.formatBasisRawInput(config.output_schema),
      }
      this.basisPromptEditMode = true
      this.basisPromptError = ''
      this.basisPromptNotice = ''
    },
    cancelBasisPromptEdit() {
      this.basisPromptEditMode = false
      this.basisPromptError = ''
    },
    async saveBasisPromptConfig() {
      const payload = this.getBasisDrawerPayload()
      const key = asText(payload.promptKey)
      if (!key) return
      let outputSchema = {}
      try {
        outputSchema = JSON.parse(asText(this.basisPromptDraft.output_schema_text) || '{}')
      } catch (_) {
        this.basisPromptError = 'output_schema 必须是合法 JSON'
        return
      }
      this.basisPromptSaving = true
      this.basisPromptError = ''
      try {
        const res = await fetch(`/api/v1/analysis/agent/prompts/${encodeURIComponent(key)}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            system_prompt: asText(this.basisPromptDraft.system_prompt),
            payload_note: asText(this.basisPromptDraft.payload_note),
            output_schema: outputSchema,
          }),
        })
        if (!res.ok) {
          let detail = ''
          try { detail = await res.text() } catch (_) {}
          throw new Error(detail || `提示词保存失败(${res.status})`)
        }
        const config = this.normalizeAgentPromptConfig(await res.json())
        this.agentPromptConfigs = { ...cloneObject(this.agentPromptConfigs), [key]: config }
        this.basisPromptEditMode = false
        this.basisPromptNotice = '已保存。下一次生成生效，当前历史结果不重算。'
        if (!asText(payload.promptSnapshot && payload.promptSnapshot.prompt_key)) {
          this.basisDrawerPayload = this.normalizeBasisPayload({
            ...payload,
            promptSnapshot: config,
            promptSourceLabel: '当前配置，非历史快照',
            aiPrompt: config.system_prompt,
            aiPromptPayloadNote: config.payload_note,
            outputSchema: config.output_schema,
          })
        }
      } catch (err) {
        this.basisPromptError = asText(err && err.message) || String(err)
      } finally {
        this.basisPromptSaving = false
      }
    },
    formatBasisFieldValue(value) {
      if (value === undefined || value === null || value === '') return '-'
      if (Array.isArray(value)) {
        return value.map((item) => {
          if (item && typeof item === 'object') {
            const label = asText(item.label || item.name || item.key || item.title)
            const itemValue = item.value ?? item.count ?? item.delta ?? item.poi_count ?? ''
            if (label && itemValue !== '') return `${label}：${this.formatBasisFieldValue(itemValue)}`
            const compactParts = [
              asText(item.name),
              asText(item.parent),
              item.delta !== undefined && item.delta !== null ? `变化 ${item.delta}` : '',
              item.last_count !== undefined && item.last_count !== null ? `末年 ${item.last_count}` : '',
              item.poi_count !== undefined && item.poi_count !== null ? `${item.poi_count}点` : '',
            ].filter(Boolean)
            return compactParts.join('，') || JSON.stringify(item)
          }
          return asText(item)
        }).filter(Boolean).join('；') || '-'
      }
      if (typeof value === 'object') {
        const entries = Object.entries(value)
          .filter(([, itemValue]) => itemValue !== undefined && itemValue !== null && itemValue !== '')
          .slice(0, 8)
          .map(([key, itemValue]) => `${key}：${this.formatBasisFieldValue(itemValue)}`)
        return entries.join('；') || '-'
      }
      return asText(value)
    },
    formatBasisRawInput(value = null) {
      const raw = value && typeof value === 'object' ? value : {}
      try {
        return JSON.stringify(raw, null, 2)
      } catch (_) {
        return '{}'
      }
    },
    getAgentIterationPoiSystemPrompt() {
      return this.getPromptMissingMessage('poi_iteration')
    },
    getAgentIterationPoiPromptPayloadNote() {
      return ''
    },
    hasBasisFieldValue(value) {
      if (value === undefined || value === null || value === '') return false
      if (Array.isArray(value)) return value.length > 0
      if (typeof value === 'object') return Object.keys(value).length > 0
      return true
    },
    formatBasisRatio(value) {
      const number = Number(value)
      if (!Number.isFinite(number)) return ''
      return `${(number * 100).toFixed(1)}%`
    },
    summarizeRoadOrientationAnalysis(analysis = null) {
      const source = analysis && typeof analysis === 'object' ? analysis : {}
      const dominant = asText(source.dominant_orientation)
      const secondary = asText(source.secondary_orientation)
      const dominantShare = this.formatBasisRatio(source.dominant_share)
      const secondaryShare = this.formatBasisRatio(source.secondary_share)
      const parts = []
      if (dominant) parts.push(`主导：${dominant}${dominantShare ? `（${dominantShare}）` : ''}`)
      if (secondary) parts.push(`次主导：${secondary}${secondaryShare ? `（${secondaryShare}）` : ''}`)
      const rows = cloneArray(source.orientation_rows)
        .map((item) => {
          const label = asText(item && item.label)
          const share = this.formatBasisRatio(item && item.length_share)
          return label && share ? `${label} ${share}` : ''
        })
        .filter(Boolean)
        .slice(0, 4)
      if (rows.length) parts.push(`分布：${rows.join('、')}`)
      return parts.join('；') || ''
    },
    appendBasisField(fields, key, label, value) {
      if (!Array.isArray(fields) || !this.hasBasisFieldValue(value)) return
      fields.push({ key, label, value })
    },
    buildAgentSummaryEvidencePack(panelPayloads = null) {
      const payloads = panelPayloads && typeof panelPayloads === 'object'
        ? cloneObject(panelPayloads)
        : this.getAgentActiveSummaryPanelPayloads()
      const pack = this.getAgentSummaryPack(payloads)
      const businessProfile = cloneObject(payloads.current_business_profile || {})
      const poiStructure = cloneObject(payloads.current_poi_structure_analysis || {})
      const h3Structure = cloneObject(payloads.current_h3_structure_analysis || {})
      const commercialHotspots = cloneObject(payloads.current_commercial_hotspots || {})
      const populationProfile = cloneObject(payloads.current_population_profile_analysis || {})
      const nightlightPattern = cloneObject(
        payloads.current_nightlight_pattern_analysis
        || payloads.nightlight_pattern
        || payloads.nightlight
        || {},
      )
      const nightlightSummary = cloneObject(
        payloads.current_nightlight_summary
        || ((payloads.nightlight_overview || {}).summary)
        || ((this.nightlightOverview || {}).summary)
        || {},
      )
      const roadPattern = cloneObject(payloads.current_road_pattern_analysis || {})
      const roadSummary = cloneObject(
        payloads.road_syntax_summary
        || ((payloads.road || {}).summary)
        || this.roadSyntaxSummary
        || {},
      )
      const areaLabels = cloneObject(payloads.current_area_character_labels || {})
      return {
        task: 'summary_pack_generation',
        evidence_version: 'summary_pack_v1',
        generated_sections: {
          headline_judgment: cloneObject(pack.headline_judgment || {}),
          user_profile: cloneObject(pack.user_profile || {}),
          behavior_inference: cloneObject(pack.behavior_inference || {}),
          tourism_cross_analysis: cloneObject(pack.tourism_cross_analysis || {}),
        },
        business_profile: {
          label: businessProfile.business_profile,
          portrait: businessProfile.portrait,
          summary_text: businessProfile.summary_text,
          functional_mix_score: businessProfile.functional_mix_score,
        },
        poi_structure: {
          summary_text: poiStructure.summary_text,
          dominant_categories: cloneArray(poiStructure.dominant_categories),
          structure_tags: cloneArray(poiStructure.structure_tags),
          top_category_mix: cloneArray(poiStructure.top_category_mix || poiStructure.top_categories),
        },
        spatial_structure: {
          distribution_pattern: h3Structure.distribution_pattern,
          summary_text: h3Structure.summary_text,
          hotspot_mode: commercialHotspots.hotspot_mode || h3Structure.hotspot_mode,
          hotspot_summary: commercialHotspots.summary_text,
          core_zone_count: commercialHotspots.core_zone_count ?? h3Structure.core_zone_count,
          opportunity_zone_count: commercialHotspots.opportunity_zone_count ?? h3Structure.opportunity_count,
          hotspot_count: h3Structure.hotspot_count,
          structure_signal_count: h3Structure.structure_signal_count,
        },
        population_profile: {
          summary_text: populationProfile.summary_text,
          total_population: populationProfile.total_population,
          top_age_band: populationProfile.top_age_band,
          dominant_age_band: populationProfile.dominant_age_band,
        },
        nightlight_pattern: {
          summary_text: nightlightPattern.summary_text || nightlightSummary.summary_text,
          economic_activity_summary_text: nightlightPattern.economic_activity_summary_text || nightlightSummary.economic_activity_summary_text,
          economic_activity_intensity_level: nightlightPattern.economic_activity_intensity_level || nightlightSummary.economic_activity_intensity_level,
          total_radiance: nightlightPattern.total_radiance ?? nightlightSummary.total_radiance,
          mean_radiance: nightlightPattern.mean_radiance ?? nightlightSummary.mean_radiance,
          p90_radiance: nightlightPattern.p90_radiance ?? nightlightSummary.p90_radiance,
          lit_pixel_ratio: nightlightPattern.lit_pixel_ratio ?? nightlightSummary.lit_pixel_ratio,
          core_hotspot_count: nightlightPattern.core_hotspot_count ?? nightlightSummary.core_hotspot_count,
          sector_direction_analysis: cloneObject(nightlightPattern.sector_direction_analysis || nightlightSummary.sector_direction_analysis || {}),
        },
        road_pattern: {
          summary_text: roadPattern.summary_text || roadSummary.summary_text,
          connectivity_signal: roadPattern.connectivity_signal || roadSummary.connectivity_signal,
          access_signal: roadPattern.access_signal || roadSummary.access_signal,
          readability_signal: roadPattern.readability_signal || roadSummary.readability_signal,
          road_orientation_analysis: cloneObject(roadPattern.road_orientation_analysis || roadSummary.road_orientation_analysis || {}),
        },
        area_labels: cloneArray(areaLabels.character_tags || areaLabels.area_labels || []),
        guardrails: {
          write_business_judgment_not_data_description: true,
          no_raw_metric_recital_as_headline: true,
          user_profile_must_describe_people: true,
          behavior_inference_must_describe_usage: true,
          no_invented_facts: true,
        },
      }
    },
    getAgentSummarySectionPrompt(sectionKey = '') {
      return this.getPromptMissingMessage(sectionKey)
    },
    getAgentSummaryPromptPayloadNote(sectionKey = '') {
      return ''
    },
    buildAgentSummaryEvidenceFields(section = {}, evidence = {}) {
      const key = asText(section.sectionKey || section.section_key)
      const generated = evidence.generated_sections || {}
      const fields = cloneArray(section.dimensions).map((dimension) => ({
        key: asText(dimension.key),
        label: asText(dimension.label),
        value: asText(dimension.conclusion),
      }))
      this.appendBasisField(fields, 'evidence_version', '证据包版本', evidence.evidence_version)
      this.appendBasisField(fields, 'task', '生成任务', evidence.task)
      const headline = generated.headline_judgment || {}
      const userProfile = generated.user_profile || {}
      const behavior = generated.behavior_inference || {}
      const tourismCrossAnalysis = generated.tourism_cross_analysis || {}
      if (key === 'headline') {
      this.appendBasisField(fields, 'headline_summary', '核心判断', headline.summary)
        this.appendBasisField(fields, 'supporting_clause', '支撑解释', headline.supporting_clause)
      }
      if (key === 'user_profile') {
        this.appendBasisField(fields, 'user_profile_headline', '用户画像结论', userProfile.headline)
        this.appendBasisField(fields, 'user_profile_traits', '画像特征', userProfile.traits)
      }
      if (key === 'behavior_inference') {
        this.appendBasisField(fields, 'behavior_headline', '行为推断结论', behavior.headline)
        this.appendBasisField(fields, 'behavior_traits', '行为特征', behavior.traits)
      }
      if (key === 'tourism_cross_analysis') {
        this.appendBasisField(fields, 'tourism_cross_analysis_title', '分析标题', tourismCrossAnalysis.title)
        this.appendBasisField(fields, 'tourism_cross_analysis_content', '交叉分析文本', tourismCrossAnalysis.content)
      }
      if (key === 'headline' || key === 'poi_structure' || key === 'business_support' || key === 'tourism_cross_analysis') {
        this.appendBasisField(fields, 'business_profile', '商业画像', evidence.business_profile)
        this.appendBasisField(fields, 'poi_structure_summary', 'POI 结构摘要', (evidence.poi_structure || {}).summary_text)
        this.appendBasisField(fields, 'dominant_categories', '主导业态', (evidence.poi_structure || {}).dominant_categories)
        this.appendBasisField(fields, 'structure_tags', '结构标签', (evidence.poi_structure || {}).structure_tags)
      }
      if (key === 'headline' || key === 'spatial_structure' || key === 'tourism_cross_analysis') {
        this.appendBasisField(fields, 'spatial_structure_summary', '空间结构摘要', (evidence.spatial_structure || {}).summary_text)
        this.appendBasisField(fields, 'hotspot_mode', '热点模式', (evidence.spatial_structure || {}).hotspot_mode)
        this.appendBasisField(fields, 'core_zone_count', '核心区数量', (evidence.spatial_structure || {}).core_zone_count)
        this.appendBasisField(fields, 'opportunity_zone_count', '机会区数量', (evidence.spatial_structure || {}).opportunity_zone_count)
      }
      if (key === 'headline' || key === 'user_profile' || key === 'behavior_inference' || key === 'tourism_cross_analysis') {
        this.appendBasisField(fields, 'population_profile', '人口画像摘要', (evidence.population_profile || {}).summary_text)
        this.appendBasisField(fields, 'top_age_band', '主要年龄段', (evidence.population_profile || {}).top_age_band || (evidence.population_profile || {}).dominant_age_band)
      }
      if (key === 'headline' || key === 'consumption_vitality' || key === 'behavior_inference' || key === 'business_support' || key === 'tourism_cross_analysis') {
        const nightlight = evidence.nightlight_pattern || {}
        const road = evidence.road_pattern || {}
        this.appendBasisField(fields, 'economic_activity_intensity_level', '经济活动强度等级', nightlight.economic_activity_intensity_level)
        this.appendBasisField(fields, 'total_radiance', '总辐亮', nightlight.total_radiance)
        this.appendBasisField(fields, 'mean_radiance', '平均辐亮', nightlight.mean_radiance)
        this.appendBasisField(fields, 'p90_radiance', 'P90 辐亮', nightlight.p90_radiance)
        this.appendBasisField(fields, 'lit_pixel_ratio', '点亮占比', nightlight.lit_pixel_ratio)
        this.appendBasisField(fields, 'sector_direction_analysis', '夜光扇区方位', nightlight.sector_direction_analysis)
        this.appendBasisField(fields, 'road_orientation_analysis', '路网方位', this.summarizeRoadOrientationAnalysis(road.road_orientation_analysis))
        this.appendBasisField(fields, 'road_pattern_summary', '路网摘要', road.summary_text)
      }
      this.appendBasisField(fields, 'area_labels', '区域标签', evidence.area_labels)
      return fields.filter((field) => this.hasBasisFieldValue(field.value))
    },
    buildAgentSummaryBasisPayload(item = null) {
      const section = item && typeof item === 'object' ? item : {}
      const key = asText(section.sectionKey || section.section_key)
      const panelPayloads = this.getAgentActiveSummaryPanelPayloads()
      const pack = this.getAgentSummaryPack(panelPayloads)
      const evidence = this.buildAgentSummaryEvidencePack(panelPayloads)
      const fields = this.buildAgentSummaryEvidenceFields(section, evidence)
      const snapshots = cloneObject(panelPayloads.prompt_snapshots || pack.prompt_snapshots || {})
      const validationResults = cloneObject(panelPayloads.validation_results || pack.validation_results || {})
      const promptSnapshot = cloneObject(snapshots[key] || {})
      const promptDisplay = this.resolveBasisPromptDisplay(key, promptSnapshot)
      return {
        title: `${asText(section.title) || '区域总结'}依据`,
        currentConclusion: asText(section.reasoning),
        fields,
        rules: key === 'consumption_vitality'
          ? [
            '夜光作为等时圈内夜间经济活动和建成活动强度的代理变量。',
            '强弱主要参考 total_radiance、mean_radiance、p90_radiance、lit_pixel_ratio、热点核心数量与峰值边缘比。',
            '空间表述优先使用 8 扇区夜光统计；道路表述使用长度加权路网方位。',
            '比较夜光高值方位与路网主导/次主导方位，形成一致、部分一致或不一致判断。',
          ]
          : [
            '区域总结由后端汇总当前已完成的结构化分析结果生成。',
            '结论会经过后端字段校验与敏感推断改写，避免超出已有证据。',
          ],
        template: key === 'consumption_vitality'
          ? '从空间分布来看，等时圈内夜间经济活动整体处于{强度水平}，高值区域主要集中在{夜光高值方向/区域}。区域道路以{主导路网走向}为主，{次主导路网走向}为辅。两者在空间上呈现{一致性关系}，表明交通对经济活动分布具有{影响程度}。'
          : '根据{面板结构化字段}生成{结论标题}，并将主要证据压缩为一段可汇报文字。',
        aiPrompt: promptDisplay.aiPrompt,
        aiPromptPayloadNote: promptDisplay.aiPromptPayloadNote,
        outputSchema: promptDisplay.outputSchema,
        promptKey: key,
        promptSnapshot: promptDisplay.promptSnapshot,
        promptSourceLabel: promptDisplay.promptSourceLabel,
        validationResults: validationResults[key] ? { [key]: cloneObject(validationResults[key]) } : {},
        rawInput: {
          section,
          generated_section: key === 'headline'
            ? cloneObject((pack.headline_judgment || {}))
            : cloneObject((pack[key] || pack[`${key}`] || {})),
          evidence,
        },
        sourceType: 'ai_checked',
      }
    },
    buildNightlightBasisPayload() {
      const summary = cloneObject((this.nightlightOverview && this.nightlightOverview.summary) || (this.nightlightLayer && this.nightlightLayer.summary) || {})
      const analysis = cloneObject((this.nightlightLayer && this.nightlightLayer.analysis) || {})
      const summaryRows = typeof this.getNightlightSummaryRows === 'function' ? this.getNightlightSummaryRows() : []
      const conclusion = asText(
        analysis.economic_activity_summary_text
        || summary.economic_activity_summary_text
        || '基于夜间灯光亮度，展示等时圈内夜间经济活动强度、热点集中度与空间梯度。',
      )
      return {
        title: '夜光分析指标说明',
        currentConclusion: conclusion,
        fields: [
          ...summaryRows.map((row) => ({ key: row.key, label: row.label, value: row.value })),
          { key: 'economic_activity_intensity_level', label: '经济活动强度等级', value: analysis.economic_activity_intensity_level || summary.economic_activity_intensity_level },
          { key: 'sector_direction_analysis', label: '扇区方位统计', value: analysis.sector_direction_analysis || summary.sector_direction_analysis },
          { key: 'core_hotspot_count', label: '热点核心数量', value: analysis.core_hotspot_count },
          { key: 'peak_to_edge_ratio', label: '峰值边缘比', value: analysis.peak_to_edge_ratio },
        ],
        rules: [
          '夜光只作为夜间经济活动与建成活动强度代理，不推断白天消费、客流、营业额或消费能力。',
          '强度等级由总辐亮、均值、P90、点亮占比、热点数量和空间梯度共同判断。',
          '扇形方位按等时圈中心划分 8 个方向，统计各方向总辐亮、均值、热点数量和占比。',
        ],
        template: '基于夜间灯光亮度，等时圈内经济活动强度呈现{强度水平}，高值区域主要集中在{主要方位}，热点集中度为{集中度描述}。',
        aiPrompt: '未调用 AI。该抽屉展示夜光算法指标说明：总辐亮、均值、P90、点亮占比、热点核心、峰值边缘比与 8 扇区方位统计均来自前端/后端结构化计算结果。',
        rawInput: {
          summary,
          analysis,
          active_view: this.nightlightAnalysisView,
        },
        sourceType: 'rule',
      }
    },
    buildRoadSyntaxBasisPayload() {
      const summary = cloneObject(this.roadSyntaxSummary || {})
      const orientation = cloneObject(summary.road_orientation_analysis || {})
      return {
        title: '路网分析指标说明',
        currentConclusion: '按当前等时圈内路网结构展示道路规模、空间句法指标与长度加权道路方位。',
        fields: [
          { key: 'node_count', label: '节点数量', value: summary.node_count },
          { key: 'edge_count', label: '边数量', value: summary.edge_count },
          { key: 'total_length_m', label: '道路总长度', value: summary.total_length_m },
          { key: 'road_orientation_analysis', label: '路网方位分析', value: orientation },
          { key: 'metric', label: '当前指标', value: this.roadSyntaxMetric || this.roadSyntaxLastMetricTab },
          { key: 'radius', label: '分析半径', value: this.roadSyntaxRadius },
        ],
        rules: [
          '路网方位从 LineString 几何计算道路段方向，并按道路长度加权。',
          '轴向归类为东西向、南北向、东北-西南向、西北-东南向。',
          '长度占比最高的是主导方位，第二高的是次主导方位，用于和夜光高值方向做空间一致性对照。',
        ],
        template: '区域道路以{主导路网走向}为主，{次主导路网走向}为辅；与夜光高值方向呈现{一致性关系}。',
        aiPrompt: '未调用 AI。该抽屉展示路网算法指标说明：节点、边、道路长度、空间句法指标与长度加权道路方位均来自结构化计算结果。',
        rawInput: {
          summary,
          diagnostics: {
            status: (this.roadSyntaxDiagnostics || {}).status,
            warning: (this.roadSyntaxDiagnostics || {}).warning,
            error: (this.roadSyntaxDiagnostics || {}).error,
          },
          metric: this.roadSyntaxMetric,
          radius: this.roadSyntaxRadius,
        },
        sourceType: 'rule',
      }
    },
    getAgentIterationNightlightSystemPrompt() {
      return this.getPromptMissingMessage('nightlight_iteration')
    },
    getAgentIterationNightlightPromptPayloadNote() {
      return ''
    },
    buildAgentIterationBasisPayload(kind = 'poi', section = '') {
      const safeKind = asText(kind) || 'poi'
      const safeSection = asText(section)
      const payload = this.getAgentIterationPayload(safeKind)
      const isNightlight = safeKind === 'nightlight'
      const isPoi = safeKind === 'poi'
      const isPoiInsight = isPoi && safeSection === 'insight'
      const isPoiAnalysis = isPoi && safeSection === 'analysis'
      const rawInput = isPoi
        ? this.buildAgentPoiIterationAiEvidencePreview(payload)
        : this.buildAgentNightlightIterationEvidence(payload)
      const promptKey = isPoi ? 'poi_iteration' : 'nightlight_iteration'
      const promptSnapshots = cloneObject(payload.prompt_snapshots || payload.promptSnapshots || {})
      const promptSnapshot = cloneObject(payload.prompt_snapshot || payload.promptSnapshot || promptSnapshots[promptKey] || {})
      const allValidationResults = cloneObject(payload.validation_results || payload.validationResults || {})
      const validationResult = cloneObject(allValidationResults[promptKey] || {})
      const promptDisplay = this.resolveBasisPromptDisplay(promptKey, promptSnapshot)
      const evidenceYears = cloneArray(rawInput.years)
      const evidenceYearSummaries = cloneArray(rawInput.year_summaries)
      const latestEvidenceYear = evidenceYearSummaries[evidenceYearSummaries.length - 1] || {}
      const evidenceTrendMetrics = cloneArray(rawInput.trend_metrics)
      const evidenceCategoryChanges = cloneArray(rawInput.category_changes)
      const evidenceSubcategoryChanges = cloneArray(rawInput.subcategory_changes)
      const evidenceSpatialTrends = cloneArray(rawInput.subcategory_spatial_trends)
      const evidenceAreaDistribution = cloneArray(rawInput.area_distribution)
      const h3Evidence = cloneObject(rawInput.h3_evidence)
      const yearlyGridEvidence = cloneObject(rawInput.yearly_grid_evidence)
      const nightlightSeries = cloneArray(rawInput.series)
      const nightlightHotspot = cloneObject(rawInput.hotspot_shift)
      const nightlightSnapshotRefs = cloneArray(rawInput.snapshot_refs)
      const findMetricValue = (key, fallbackLabel = '') => {
        const row = evidenceTrendMetrics.find((item) => asText(item && item.key) === key)
          || evidenceTrendMetrics.find((item) => fallbackLabel && asText(item && item.label).includes(fallbackLabel))
        return row ? row.value : ''
      }
      const formatChangeName = (row = null) => {
        if (!row || typeof row !== 'object') return ''
        const name = asText(row.name)
        const parent = asText(row.parent)
        const delta = Number(row.delta || 0)
        return `${name}${parent ? `（${parent}）` : ''} ${delta >= 0 ? '+' : ''}${delta}`
      }
      const strongestGrowth = (rows) => cloneArray(rows)
        .filter((row) => Number(row && row.delta) > 0)
        .sort((a, b) => Number(b.delta || 0) - Number(a.delta || 0))[0]
      const strongestDecline = (rows) => cloneArray(rows)
        .filter((row) => Number(row && row.delta) < 0)
        .sort((a, b) => Number(a.delta || 0) - Number(b.delta || 0))[0]
      const poiEvidenceFields = [
        { key: 'evidence_version', label: '证据包版本', value: rawInput.evidence_version },
        { key: 'period', label: '分析周期', value: evidenceYears.length ? `${evidenceYears[0]}-${evidenceYears[evidenceYears.length - 1]}` : payload.period },
        { key: 'scope', label: '分析范围', value: `${asText((rawInput.scope || {}).area_name) || '未命名区域'} · ${asText((rawInput.scope || {}).scope_type) || '-'}` },
        { key: 'latest_total', label: '末年 POI 数量', value: latestEvidenceYear.poi_count },
        { key: 'total_delta', label: 'POI 首尾变化', value: findMetricValue('total_delta', 'POI 首尾变化') },
        { key: 'category_growth', label: '增长最明显业态', value: findMetricValue('top_increase') || formatChangeName(strongestGrowth(evidenceCategoryChanges)) },
        { key: 'category_decline', label: '减少最明显业态', value: findMetricValue('top_decrease') || formatChangeName(strongestDecline(evidenceCategoryChanges)) },
        { key: 'subcategory_growth', label: '增长最明显小类', value: findMetricValue('top_subcategory_increase') || formatChangeName(strongestGrowth(evidenceSubcategoryChanges)) },
        { key: 'subcategory_decline', label: '减少最明显小类', value: findMetricValue('top_subcategory_decrease') || formatChangeName(strongestDecline(evidenceSubcategoryChanges)) },
        { key: 'spatial_signal_count', label: '小类空间信号', value: evidenceSpatialTrends.length ? `${evidenceSpatialTrends.length} 条` : '暂无，可能仍在生成或后端未返回' },
        { key: 'area_distribution', label: '年度区域分布', value: evidenceAreaDistribution.map((row) => `${row.year || '-'}：${row.point_count ?? '-'}点，热点${row.hotspot_cell_count ?? 0}格`) },
        { key: 'h3_evidence', label: '末年 H3 网格证据', value: h3Evidence },
        { key: 'yearly_grid_evidence', label: '年度网格证据', value: yearlyGridEvidence },
      ].filter((item) => item.value !== undefined && item.value !== null && item.value !== '')
      const poiAnalysisFields = poiEvidenceFields
        .filter((field) => [
          'evidence_version',
          'period',
          'scope',
          'latest_total',
          'total_delta',
          'category_growth',
          'category_decline',
          'subcategory_growth',
          'subcategory_decline',
          'h3_evidence',
          'yearly_grid_evidence',
        ].includes(field.key))
        .concat([
          { key: 'prompt_structure', label: '提示词结构', value: '同一基础提示词；本块读取业态基础分析长文报告，并结合 H3 与年度网格证据。' },
          { key: 'output_fields', label: '本块使用输出字段', value: 'report_title, report_sections, report_content' },
        ])
      const poiInsightFields = [
        { key: 'evidence_version', label: '证据包版本', value: rawInput.evidence_version },
        { key: 'period', label: '分析周期', value: evidenceYears.length ? `${evidenceYears[0]}-${evidenceYears[evidenceYears.length - 1]}` : payload.period },
        { key: 'scope', label: '分析范围', value: `${asText((rawInput.scope || {}).area_name) || '未命名区域'} · ${asText((rawInput.scope || {}).scope_type) || '-'}` },
        { key: 'material_change_highlights', label: '增长/衰退排序依据', value: rawInput.material_change_highlights },
        { key: 'growth_area_signal', label: '增长片区信号', value: rawInput.growth_area_signal },
        { key: 'spatial_signal_count', label: '小类空间信号', value: evidenceSpatialTrends.length ? `${evidenceSpatialTrends.length} 条` : '暂无，可能仍在生成或后端未返回' },
        { key: 'area_distribution', label: '年度区域分布', value: evidenceAreaDistribution.map((row) => `${row.year || '-'}：${row.point_count ?? '-'}点，热点${row.hotspot_cell_count ?? 0}格`) },
        { key: 'h3_evidence', label: '末年 H3 网格证据', value: h3Evidence },
        { key: 'yearly_grid_evidence', label: '年度网格证据', value: yearlyGridEvidence },
        { key: 'prompt_structure', label: '提示词结构', value: '同一基础提示词；本块读取业态基础分析长文报告，并结合 H3 与年度网格证据。' },
        { key: 'output_fields', label: '本块使用输出字段', value: 'report_title, report_sections, report_content' },
      ].filter((item) => item.value !== undefined && item.value !== null && item.value !== '')
      const conclusionRows = isNightlight
        ? this.getAgentIterationNightlightAnalysisRows().map((row) => `${row.label}：${row.value}`)
        : isPoiInsight
          ? this.getAgentIterationPoiReportSections().flatMap((section) => [section.heading, ...section.paragraphs])
          : [
              ...this.getAgentIterationPoiReportSections().flatMap((section) => [section.heading, ...section.paragraphs]),
            ]
      return {
        title: isNightlight ? '夜光多年变化依据' : isPoiInsight ? 'POI 多年洞察依据' : isPoiAnalysis ? 'POI 多年分析依据' : 'POI 多年变化依据',
        currentConclusion: conclusionRows.join('\n') || '当前暂无可展示结论。',
        fields: isNightlight
          ? [
            { key: 'evidence_version', label: '证据包版本', value: rawInput.evidence_version },
            { key: 'period', label: '分析周期', value: payload.period },
            { key: 'years', label: '覆盖年份', value: cloneArray(rawInput.years).join('-') },
            { key: 'series_count', label: '年度统计条数', value: nightlightSeries.length },
            { key: 'trend_rows', label: '趋势指标', value: this.getAgentIterationNightlightTrendRows() },
            { key: 'hotspot_rows', label: '热点变化', value: this.getAgentIterationNightlightHotspotRows() },
            { key: 'hotspot_shift', label: '热点迁移摘要', value: nightlightHotspot },
            { key: 'snapshot_refs', label: '快照引用', value: nightlightSnapshotRefs.map((item) => `${item.year || '-'}：${item.has_image ? '有快照' : '无快照'}，${item.has_vector ? '有矢量' : '无矢量'}`) },
          ].filter((item) => item.value !== undefined && item.value !== null && item.value !== '')
          : isPoiInsight ? poiInsightFields : isPoiAnalysis ? poiAnalysisFields : poiEvidenceFields,
        rules: [
          '多年迭代先抽取年度快照和结构化指标，再生成趋势判断。',
          'AI 输出会被后端要求按固定 JSON 字段返回，前端只展示通过校验的字段。',
          isPoi
            ? isPoiInsight
              ? '这是同一轮 POI 多年解读中的报告字段，不是重复调用；本块展示业态基础分析总结报告。'
              : isPoiAnalysis
                ? '这是同一轮 POI 多年解读中的业态基础分析报告字段，不是重复调用；本块展示完整章节正文。'
                : 'POI 分析关注总量、业态结构、区域分布与增长/衰退方向。'
            : '夜光分析关注总辐亮、均值、P90、点亮占比和热点迁移。',
        ],
        template: isPoi
          ? isPoiInsight
            ? '从同一轮 POI 多年解读结果中读取{报告标题}、{章节正文}与{完整报告文本}。'
            : isPoiAnalysis
              ? '从同一轮 POI 多年解读结果中读取 report_sections，组织业态基础分析长文报告。'
              : '基于{年份序列}的 POI 总量、业态结构和区域分布变化，概括{趋势判断}、{结构变化}与{机会风险}。'
          : '基于近三年夜光快照，概括{趋势判断}、{总体变化}、{热点迁移}与{机会风险}。',
        aiPrompt: promptDisplay.aiPrompt,
        aiPromptPayloadNote: promptDisplay.aiPromptPayloadNote,
        outputSchema: promptDisplay.outputSchema,
        promptKey,
        promptSnapshot: promptDisplay.promptSnapshot,
        promptSourceLabel: promptDisplay.promptSourceLabel,
        validationResults: Object.keys(validationResult).length ? { [promptKey]: validationResult } : {},
        rawInput,
        sourceType: 'ai_checked',
      }
    },
    getAgentSummaryGateTitle() {
      const status = this.getAgentSummaryStatus()
      if (!this.agentSummaryReadiness.ready) {
        return '区域总结'
      }
      return status.title || '区域总结'
    },
    getAgentSummaryGateDescription() {
      const status = this.getAgentSummaryStatus()
      if (!this.agentSummaryReadiness.ready) {
        return ''
      }
      return status.description || '基础分析结果已就绪，但当前还没有可展示的区域总结。'
    },
    normalizeAgentSummaryReadiness(seed = null) {
      const value = seed && typeof seed === 'object' ? seed : {}
      return {
        checked: !!value.checked,
        ready: !!value.ready,
        missingTasks: cloneArray(value.missingTasks || value.missing_tasks).map((item) => asText(item)).filter(Boolean),
        reused: cloneArray(value.reused).map((item) => asText(item)).filter(Boolean),
        fetched: cloneArray(value.fetched).map((item) => asText(item)).filter(Boolean),
      }
    },
    syncAgentSummaryReadinessFromPanelPayload(panelPayloads = null) {
      const payloads = cloneObject(panelPayloads || this.agentPanelPayloads)
      const readiness = this.normalizeAgentSummaryReadiness(payloads.data_readiness || payloads.dataReadiness || {})
      this.agentSummaryReadiness = readiness
      if (!readiness.ready) return readiness
      this.agentSummaryError = ''
      return readiness
    },
    getAgentSummaryTaskLabel(taskKey = '') {
      const key = asText(taskKey)
      const mapping = {
        poi_fetch: 'POI 抓取',
        poi_raster_grid: 'POI 栅格计算',
        poi_h3_grid: 'POI H3 网格计算',
        poi_grid: 'POI / 网格分析',
        population: '人口结构分析',
        nightlight: '夜光分析',
        road_syntax: '路网与可达性分析',
        poi_structure: 'POI结构分析',
        spatial_structure: '空间结构分析',
        area_labels: '区域标签推断',
      }
      return mapping[key] || key || '-'
    },
    getAgentSummaryMissingTaskLabels() {
      const readiness = this.normalizeAgentSummaryReadiness(this.agentSummaryReadiness)
      return cloneArray(readiness.missingTasks).map((taskKey) => this.getAgentSummaryTaskLabel(taskKey))
    },
    getSummaryTaskKeys() {
      return ['poi_fetch', 'poi_raster_grid', 'poi_h3_grid', 'population', 'nightlight', 'road_syntax']
    },
    mapReadinessTaskToBoardTaskKeys(taskKey = '') {
      const key = asText(taskKey)
      if (!key) return []
      const mapping = {
        poi_fetch: ['poi_fetch'],
        poi_grid: ['poi_raster_grid', 'poi_h3_grid'],
        h3: ['poi_h3_grid'],
        poi_raster_grid: ['poi_raster_grid'],
        poi_h3_grid: ['poi_h3_grid'],
        population: ['population'],
        nightlight: ['nightlight'],
        road_syntax: ['road_syntax'],
        poi_structure: ['poi_h3_grid'],
        spatial_structure: ['poi_h3_grid', 'population', 'nightlight', 'road_syntax'],
        area_labels: ['poi_h3_grid', 'population', 'nightlight', 'road_syntax'],
      }
      return cloneArray(mapping[key] || [])
    },
    getSummaryTaskKeysFromReadiness() {
      const readiness = this.normalizeAgentSummaryReadiness(this.agentSummaryReadiness)
      const mapped = cloneArray(readiness.missingTasks)
        .flatMap((item) => this.mapReadinessTaskToBoardTaskKeys(item))
        .filter(Boolean)
      const deduped = Array.from(new Set(mapped))
      return deduped.filter((item) => this.getSummaryTaskKeys().includes(item))
    },
    getSummaryReusableTaskKeysFromReadiness() {
      const readiness = this.normalizeAgentSummaryReadiness(this.agentSummaryReadiness)
      const mapped = cloneArray(readiness.reused)
        .flatMap((item) => this.mapReadinessTaskToBoardTaskKeys(item))
        .filter(Boolean)
      const deduped = Array.from(new Set(mapped))
      return deduped.filter((item) => this.getSummaryTaskKeys().includes(item))
    },
    getSummaryTaskKeysToFill() {
      const reusableKeys = new Set(this.getSummaryReusableTaskKeysFromReadiness())
      const missing = this.getSummaryTaskKeysFromReadiness()
      if (missing.length) {
        return missing.filter((key) => !reusableKeys.has(key) && !this.summaryTaskHasReusableResult(key))
      }
      return this.getSummaryTaskKeys().filter((key) => {
        if (reusableKeys.has(key)) return false
        if (this.summaryTaskHasReusableResult(key)) return false
        return !this.isSummaryTaskTerminalStatus(this.getSummaryTaskByKey(key)?.status)
      })
    },
    filterSummaryTaskKeysForReuse(taskKeys = [], options = {}) {
      const forcePoiFetch = !!options.forcePoiFetch
      const forceKeys = new Set(cloneArray(options.forceKeys).map((item) => asText(item)).filter(Boolean))
      return cloneArray(taskKeys).filter((key) => {
        const normalized = asText(key)
        if (!normalized) return false
        if (forceKeys.has(normalized)) return true
        if (normalized === 'poi_fetch' && forcePoiFetch) return true
        if (this.hasSummaryTaskParamChanged(normalized)) return true
        const def = getAnalysisTaskDefinition(normalized)
        return !(def && typeof def.hasResult === 'function' && def.hasResult(this))
      })
    },
    getSummaryTaskCatalog() {
      const keys = new Set(this.getSummaryTaskKeys())
      return getAnalysisTaskDefinitions().filter((item) => keys.has(asText(item && item.key)))
    },
    createSummaryTaskBoardTask(taskDef = {}, seed = {}) {
      const key = asText(seed.key || taskDef.key)
      return {
        key,
        label: asText(seed.label || taskDef.label || key),
        status: asText(seed.status || 'pending') || 'pending',
        paramsSnapshot: cloneObject(seed.paramsSnapshot || seed.params_snapshot || {}),
        startedAt: asText(seed.startedAt || seed.started_at || ''),
        endedAt: asText(seed.endedAt || seed.ended_at || ''),
        durationMs: Number(seed.durationMs || seed.duration_ms || 0) || 0,
        logs: cloneArray(seed.logs).map((item) => cloneObject(item)),
        error: asText(seed.error || ''),
      }
    },
    createDefaultSummaryTaskBoard() {
      const tasks = this.getSummaryTaskCatalog().map((task) => this.createSummaryTaskBoardTask(task))
      return {
        runState: 'idle',
        tasks,
        lastRunAt: '',
      }
    },
    normalizeSummaryTaskBoard(seed = null) {
      const input = seed && typeof seed === 'object' ? seed : {}
      const base = this.createDefaultSummaryTaskBoard()
      const map = new Map(cloneArray(input.tasks).map((item) => [asText(item && item.key), item]))
      return {
        runState: asText(input.runState || input.run_state || base.runState) || 'idle',
        tasks: base.tasks.map((task) => this.createSummaryTaskBoardTask(task, map.get(task.key) || task)),
        lastRunAt: asText(input.lastRunAt || input.last_run_at || ''),
      }
    },
    ensureSummaryTaskBoard(commit = false) {
      const board = this.normalizeSummaryTaskBoard(this.summaryTaskBoard)
      if (commit) this.summaryTaskBoard = board
      return board
    },
    syncSummaryTaskBoardFromPanelPayload(panelPayloads = null) {
      const payloads = cloneObject(panelPayloads || this.agentPanelPayloads)
      const board = this.normalizeSummaryTaskBoard(payloads.summary_task_board || payloads.summaryTaskBoard || this.summaryTaskBoard)
      this.summaryTaskBoard = board
      return board
    },
    syncSummaryTaskBoardFromLocalResults(options = {}) {
      const board = this.ensureSummaryTaskBoard(false)
      const now = new Date().toISOString()
      const tasks = cloneArray(board.tasks).map((task) => {
        const key = asText(task && task.key)
        const def = getAnalysisTaskDefinition(key)
        const isRunning = !!(def && def.runningFlag && this[def.runningFlag])
        const hasResult = !!(def && typeof def.hasResult === 'function' && def.hasResult(this))
        const status = isRunning ? 'running' : (hasResult ? 'reused' : 'pending')
        return {
          ...task,
          status,
          startedAt: status === 'running' ? asText(task.startedAt || now) : asText(task.startedAt),
          endedAt: status === 'running' ? '' : asText(task.endedAt),
          durationMs: status === 'pending' ? 0 : Number(task.durationMs || 0) || 0,
          error: status === 'pending' || status === 'running' || status === 'reused' ? '' : asText(task.error),
        }
      })
      const hasRunning = tasks.some((item) => asText(item.status) === 'running')
      const pendingKeys = tasks
        .filter((item) => !this.isSummaryTaskTerminalStatus(item.status))
        .map((item) => asText(item.key))
        .filter(Boolean)
      const runState = hasRunning ? 'running' : (pendingKeys.length ? 'idle' : 'completed')
      const nextBoard = this.updateSummaryTaskBoard({ ...board, tasks, runState }, { sync: false })
      const readiness = this.normalizeAgentSummaryReadiness({
        checked: true,
        ready: !pendingKeys.length,
        missingTasks: pendingKeys,
        reused: tasks.filter((item) => this.isSummaryTaskTerminalStatus(item.status)).map((item) => asText(item.key)),
        fetched: [],
      })
      this.agentSummaryReadiness = readiness
      this.agentPanelPayloads = {
        ...cloneObject(this.agentPanelPayloads),
        data_readiness: {
          checked: readiness.checked,
          ready: readiness.ready,
          missing_tasks: cloneArray(readiness.missingTasks),
          reused: cloneArray(readiness.reused),
          fetched: cloneArray(readiness.fetched),
        },
        summary_task_board: this.buildSummaryTaskBoardUiState(),
      }
      if (options.sync !== false) this.syncCurrentAgentSession()
      return nextBoard
    },
    buildSummaryTaskBoardUiState() {
      const board = this.ensureSummaryTaskBoard(true)
      return {
        run_state: asText(board.runState || 'idle'),
        last_run_at: asText(board.lastRunAt || ''),
        tasks: cloneArray(board.tasks).map((task) => ({
          key: task.key,
          label: task.label,
          status: task.status,
          params_snapshot: cloneObject(task.paramsSnapshot),
          started_at: task.startedAt,
          ended_at: task.endedAt,
          duration_ms: task.durationMs,
          logs: cloneArray(task.logs).map((item) => cloneObject(item)),
          error: task.error,
        })),
      }
    },
    updateSummaryTaskBoard(nextBoard = null, options = {}) {
      const board = this.normalizeSummaryTaskBoard(nextBoard || this.summaryTaskBoard)
      this.summaryTaskBoard = board
      if (options.sync !== false) {
        this.agentPanelPayloads = {
          ...cloneObject(this.agentPanelPayloads),
          summary_task_board: this.buildSummaryTaskBoardUiState(),
        }
        this.syncCurrentAgentSession()
      }
      return board
    },
    getSummaryTaskBoardTasks() {
      return cloneArray(this.ensureSummaryTaskBoard(false).tasks)
    },
    getSummaryTaskByKey(taskKey = '') {
      const key = asText(taskKey)
      return this.getSummaryTaskBoardTasks().find((item) => asText(item && item.key) === key) || null
    },
    summaryTaskHasReusableResult(taskKey = '') {
      const key = asText(taskKey)
      const def = getAnalysisTaskDefinition(key)
      return !!(def && typeof def.hasResult === 'function' && def.hasResult(this))
    },
    getSummaryTaskStatusLabel(taskOrStatus = '') {
      const task = taskOrStatus && typeof taskOrStatus === 'object' ? taskOrStatus : null
      const status = asText(task ? task.status : taskOrStatus)
      if (task && status === 'pending' && this.summaryTaskHasReusableResult(task.key)) {
        return '已有结果'
      }
      const mapping = {
        pending: '待执行',
        running: '运行中',
        reused: '已复用',
        completed: '已完成',
        failed: '失败',
      }
      return mapping[status] || '待执行'
    },
    getSummaryTaskEmptyLogText(task = null) {
      const current = task && typeof task === 'object' ? task : {}
      const status = asText(current.status)
      if (status === 'pending' && this.summaryTaskHasReusableResult(current.key)) {
        return '已有结果，可直接复用'
      }
      if (status === 'reused') {
        return '已复用现有结果'
      }
      return '暂无日志'
    },
    isSummaryTaskTerminalStatus(status = '') {
      const key = asText(status)
      return key === 'completed' || key === 'reused'
    },
    finalizeSummaryTaskAsReused(taskKey = '', options = {}) {
      const key = asText(taskKey)
      const def = getAnalysisTaskDefinition(key)
      if (!key || !def) return null
      const now = new Date().toISOString()
      const board = this.ensureSummaryTaskBoard(false)
      const tasks = cloneArray(board.tasks).map((task) => {
        if (asText(task.key) !== key) return task
        const startedAt = asText(task.startedAt || now)
        const started = Date.parse(startedAt)
        const ended = Date.parse(now)
        return {
          ...task,
          status: 'reused',
          startedAt,
          endedAt: now,
          durationMs: Number.isFinite(started) && Number.isFinite(ended) ? Math.max(0, ended - started) : 0,
          error: '',
          paramsSnapshot: this.captureSummaryTaskParams(key),
          logs: [],
        }
      })
      const nextRunState = tasks.every((item) => this.isSummaryTaskTerminalStatus(item.status))
        ? 'completed'
        : (tasks.some((item) => item.status === 'running') ? 'running' : 'idle')
      this.updateSummaryTaskBoard({ ...board, tasks, runState: nextRunState })
      const message = asText(options.message || `检测到已有结果，本次复用：${def.label}`)
      this.appendSummaryTaskLog(key, message)
      return this.getSummaryTaskByKey(key)
    },
    appendSummaryTaskLog(taskKey = '', message = '', level = 'info') {
      const key = asText(taskKey)
      if (!key || !message) return
      const board = this.ensureSummaryTaskBoard(false)
      const tasks = cloneArray(board.tasks).map((task) => {
        if (asText(task.key) !== key) return task
        const logs = cloneArray(task.logs)
        logs.push({
          at: new Date().toISOString(),
          level: asText(level) || 'info',
          message: asText(message),
        })
        return { ...task, logs: logs.slice(-40) }
      })
      this.updateSummaryTaskBoard({ ...board, tasks })
    },
    _ensureSummaryTaskLogTrackers() {
      if (!this.summaryTaskLogTrackers || typeof this.summaryTaskLogTrackers !== 'object') {
        this.summaryTaskLogTrackers = {}
      }
      return this.summaryTaskLogTrackers
    },
    normalizeSummaryTaskLogMessage(message = '') {
      return asText(message).replace(/\s+/g, ' ').trim()
    },
    getSummaryTaskProgressMessage(taskKey = '') {
      const key = asText(taskKey)
      if (!key) return ''
      if (key === 'road_syntax') {
        const progressMsg = asText(this.roadSyntaxProgressMessage || '')
        const step = Number(this.roadSyntaxProgressStep || 0)
        const total = Number(this.roadSyntaxProgressTotal || 0)
        if (progressMsg) {
          if (step > 0 && total > 0) return `进度 ${Math.floor(step)}/${Math.floor(total)}：${progressMsg}`
          return progressMsg
        }
        return asText(this.roadSyntaxStatus || '')
      }
      if (key === 'poi_fetch') {
        const status = asText(this.poiStatus || '')
        const progress = Number(this.fetchProgress || 0)
        if (!status) return ''
        if (Number.isFinite(progress) && progress > 0 && progress < 100 && status.indexOf('%') < 0) {
          return `${status}（${Math.round(progress)}%）`
        }
        return status
      }
      if (key === 'poi_raster_grid') return asText(this.poiGridStatus || '')
      if (key === 'poi_h3_grid') return asText(this.h3GridStatus || '')
      if (key === 'population') return asText(this.populationStatus || '')
      if (key === 'nightlight') return asText(this.nightlightStatus || '')
      return ''
    },
    isSummaryTaskIntermediateStatus(taskKey = '', statusText = '') {
      const key = asText(taskKey)
      const message = this.normalizeSummaryTaskLogMessage(statusText || this.getSummaryTaskProgressMessage(key))
      if (!key || !message) return false
      if (key === 'road_syntax') {
        return /(局部任务已启动|正在准备路网|图层预处理中|图层预加载中|仍在预处理)/i.test(message)
      }
      return false
    },
    isSummaryTaskFailureStatus(taskKey = '', statusText = '') {
      const key = asText(taskKey)
      const message = this.normalizeSummaryTaskLogMessage(statusText || this.getSummaryTaskProgressMessage(key))
      if (!key || !message) return false
      if (this.isSummaryTaskIntermediateStatus(key, message)) return false
      return /(失败|异常|错误|failed|error)/i.test(message)
    },
    isSummaryTaskBackgroundRunning(taskKey = '', def = null, statusText = '') {
      const key = asText(taskKey)
      const message = this.normalizeSummaryTaskLogMessage(statusText || this.getSummaryTaskProgressMessage(key))
      if (!key) return false
      if (this.isSummaryTaskIntermediateStatus(key, message)) return true
      const hasBackendProgress = /(请求已发送|后端计算中|计算中|执行中|处理中|排队|进度|已发送)/i.test(message)
      if (hasBackendProgress) return true
      if (this.isSummaryTaskFailureStatus(key, message)) return false
      if (def && def.runningFlag && this[def.runningFlag]) return true
      return false
    },
    async waitForSummaryTaskBackgroundResult(taskKey = '', def = null, options = {}) {
      const key = asText(taskKey)
      if (!key || !def) return false
      const intervalMs = Math.max(1, Number(options.backgroundPollIntervalMs || 2000) || 2000)
      const timeoutMs = Math.max(intervalMs, Number(options.backgroundTimeoutMs || 5 * 60 * 1000) || 5 * 60 * 1000)
      const startedAtMs = Date.now()
      if (options.suppressPlaceholder) {
        const trackers = this._ensureSummaryTaskLogTrackers()
        const tracker = trackers[key] && typeof trackers[key] === 'object' ? trackers[key] : {}
        trackers[key] = { ...tracker, suppressPlaceholder: true }
        this.summaryTaskLogTrackers = trackers
      }
      while (Date.now() - startedAtMs <= timeoutMs) {
        this.pollSummaryTaskProgressLog(key)
        if (typeof def.hasResult === 'function' ? !!def.hasResult(this) : true) return true
        const statusText = this.getSummaryTaskProgressMessage(key)
        if (!this.isSummaryTaskBackgroundRunning(key, def, statusText)) return false
        await new Promise((resolve) => setTimeout(resolve, intervalMs))
      }
      throw new Error('后台计算等待超时，请切换到对应面板查看或重试')
    },
    _appendSummaryTaskProgressLogIfChanged(taskKey = '', message = '', level = 'info') {
      const key = asText(taskKey)
      const normalized = this.normalizeSummaryTaskLogMessage(message)
      if (!key || !normalized) return false
      const trackers = this._ensureSummaryTaskLogTrackers()
      const tracker = trackers[key] && typeof trackers[key] === 'object' ? trackers[key] : {}
      if (this.normalizeSummaryTaskLogMessage(tracker.lastMessage) === normalized) return false
      this.appendSummaryTaskLog(key, normalized, level)
      trackers[key] = {
        ...tracker,
        lastMessage: normalized,
        lastRealLogAtMs: Date.now(),
      }
      this.summaryTaskLogTrackers = trackers
      return true
    },
    pollSummaryTaskProgressLog(taskKey = '') {
      const key = asText(taskKey)
      if (!key) return
      const trackers = this._ensureSummaryTaskLogTrackers()
      const tracker = trackers[key] && typeof trackers[key] === 'object' ? trackers[key] : {}
      const message = this.getSummaryTaskProgressMessage(key)
      if (this._appendSummaryTaskProgressLogIfChanged(key, message, 'info')) return
      const now = Date.now()
      const startedAtMs = Number(tracker.startedAtMs || 0)
      const lastRealLogAtMs = Number(tracker.lastRealLogAtMs || 0)
      const lastPlaceholderAtMs = Number(tracker.lastPlaceholderAtMs || 0)
      const placeholderIntervalMs = 9000
      const inactiveSince = Math.max(startedAtMs, lastRealLogAtMs)
      if (tracker.suppressPlaceholder) return
      if (!inactiveSince || (now - inactiveSince) < placeholderIntervalMs) return
      if (lastPlaceholderAtMs && (now - lastPlaceholderAtMs) < placeholderIntervalMs) return
      const def = getAnalysisTaskDefinition(key)
      const elapsedSec = Math.max(0, Math.floor((now - startedAtMs) / 1000))
      const fallback = `${asText((def && def.label) || key)}执行中（${elapsedSec}s）...`
      this.appendSummaryTaskLog(key, fallback, 'info')
      trackers[key] = {
        ...tracker,
        lastMessage: this.normalizeSummaryTaskLogMessage(fallback),
        lastPlaceholderAtMs: now,
      }
      this.summaryTaskLogTrackers = trackers
    },
    startSummaryTaskLogTracking(taskKey = '', options = {}) {
      const key = asText(taskKey)
      if (!key) return
      this.stopSummaryTaskLogTracking(key)
      const trackers = this._ensureSummaryTaskLogTrackers()
      const now = Date.now()
      const intervalMs = Math.max(600, Math.min(1000, Number(options.intervalMs || 700) || 700))
      const startedAtMs = Number(options.startedAtMs || now) || now
      trackers[key] = {
        timerId: setInterval(() => this.pollSummaryTaskProgressLog(key), intervalMs),
        lastMessage: '',
        startedAtMs,
        lastRealLogAtMs: startedAtMs,
        lastPlaceholderAtMs: 0,
        suppressPlaceholder: !!options.suppressPlaceholder,
      }
      this.summaryTaskLogTrackers = trackers
    },
    stopSummaryTaskLogTracking(taskKey = '') {
      const key = asText(taskKey)
      if (!key || !this.summaryTaskLogTrackers || typeof this.summaryTaskLogTrackers !== 'object') return
      const trackers = this.summaryTaskLogTrackers
      const tracker = trackers[key]
      if (!tracker || typeof tracker !== 'object') return
      if (tracker.timerId) clearInterval(tracker.timerId)
      delete trackers[key]
      this.summaryTaskLogTrackers = { ...trackers }
    },
    stopAllSummaryTaskLogTracking() {
      if (!this.summaryTaskLogTrackers || typeof this.summaryTaskLogTrackers !== 'object') return
      Object.keys(this.summaryTaskLogTrackers).forEach((key) => this.stopSummaryTaskLogTracking(key))
    },
    captureSummaryTaskParams(taskKey = '') {
      const key = asText(taskKey)
      const bundle = buildAnalysisTaskParamBundle(this, key)
      if (bundle && bundle.params && Object.keys(bundle.params).length) {
        return cloneObject(bundle.params)
      }
      return {}
    },
    getSummaryTaskPoiYearLabel() {
      const year = Number(this.poiYearSource || this.resultPoiYear || 0)
      return Number.isFinite(year) && year > 0 ? String(year) : '-'
    },
    getSummaryTaskPoiSourceLabel() {
      return asText(this.resultDataSource || this.poiDataSource || '') || '当前数据源'
    },
    getSummaryTaskFetchedPoiYears() {
      const years = new Set()
      cloneArray(this.poiResultsByYear).forEach((item) => {
        const year = Number(item && item.year)
        if (Number.isFinite(year) && (cloneArray(item && item.pois).length || Number(item && item.count) > 0)) years.add(year)
      })
      cloneArray(this.currentHistoryAvailablePoiYears).forEach((item) => {
        const year = Number(item)
        if (Number.isFinite(year)) years.add(year)
      })
      const currentYear = Number(this.resultPoiYear || this.currentHistorySelectedPoiYear || 0)
      if (Number.isFinite(currentYear) && cloneArray(this.allPoisDetails).length) years.add(currentYear)
      return Array.from(years).sort((a, b) => a - b)
    },
    getSummaryTaskPoiYearOptions() {
      const fetched = new Set(this.getSummaryTaskFetchedPoiYears().map((item) => Number(item)))
      const baseOptions = typeof this.getPoiMultiYearOptions === 'function'
        ? this.getPoiMultiYearOptions()
        : [
          { value: 2020, label: '2020 本地' },
          { value: 2022, label: '2022 本地' },
          { value: 2024, label: '2024 本地' },
          { value: 2026, label: '2026 高德' },
        ]
      return cloneArray(baseOptions).map((item) => {
        const value = Number(item && item.value)
        const isFetched = fetched.has(value)
        const label = asText(item && item.label) || String(value || '')
        return {
          ...cloneObject(item),
          value: String(value),
          year: value,
          fetched: isFetched,
          label: isFetched ? `${label} · 已抓取` : label,
        }
      })
    },
    stringifySummaryTaskParams(params = {}) {
      const normalize = (value) => {
        if (Array.isArray(value)) return value.map((item) => normalize(item))
        if (!value || typeof value !== 'object') return value
        return Object.keys(value)
          .sort()
          .reduce((acc, key) => {
            acc[key] = normalize(value[key])
            return acc
          }, {})
      }
      return JSON.stringify(normalize(params || {}))
    },
    hasSummaryTaskParamChanged(taskKey = '', task = null) {
      const key = asText(taskKey)
      if (!key) return false
      const currentTask = task && typeof task === 'object' ? task : this.getSummaryTaskByKey(key)
      const snapshot = currentTask && typeof currentTask === 'object' ? currentTask.paramsSnapshot : {}
      if (!Object.keys(snapshot || {}).length) return asText(currentTask && currentTask.status) === 'pending'
      return this.stringifySummaryTaskParams(this.captureSummaryTaskParams(key)) !== this.stringifySummaryTaskParams(snapshot || {})
    },
    getSummaryTaskParameterDependents(taskKey = '') {
      const key = asText(taskKey)
      if (key === 'poi_fetch') return ['poi_fetch', 'poi_raster_grid', 'poi_h3_grid']
      if (key === 'poi_raster_grid') return ['poi_raster_grid']
      if (key === 'poi_h3_grid') return ['poi_h3_grid']
      if (key === 'population') return ['population']
      if (key === 'nightlight') return ['nightlight']
      return key ? [key] : []
    },
    onSummaryTaskParameterChange(taskKey = '') {
      const affected = this.getSummaryTaskParameterDependents(taskKey)
      if (!affected.length) return
      const affectedSet = new Set(affected)
      const board = this.ensureSummaryTaskBoard(false)
      const tasks = cloneArray(board.tasks).map((task) => {
        const key = asText(task && task.key)
        if (!affectedSet.has(key) || asText(task && task.status) === 'running') return task
        return {
          ...task,
          status: 'pending',
          paramsSnapshot: {},
          endedAt: '',
          durationMs: 0,
          error: '',
        }
      })
      this.updateSummaryTaskBoard({ ...board, tasks, runState: 'idle' })
      const readiness = this.normalizeAgentSummaryReadiness(this.agentSummaryReadiness)
      const missing = Array.from(new Set([...cloneArray(readiness.missingTasks), ...affected]))
      this.agentSummaryReadiness = this.normalizeAgentSummaryReadiness({
        ...readiness,
        checked: true,
        ready: false,
        missingTasks: missing,
      })
      this.agentPanelPayloads = {
        ...cloneObject(this.agentPanelPayloads),
        data_readiness: {
          checked: this.agentSummaryReadiness.checked,
          ready: this.agentSummaryReadiness.ready,
          missing_tasks: cloneArray(this.agentSummaryReadiness.missingTasks),
          reused: cloneArray(this.agentSummaryReadiness.reused).filter((key) => !affectedSet.has(asText(key))),
          fetched: cloneArray(this.agentSummaryReadiness.fetched),
        },
      }
      this.syncCurrentAgentSession()
    },
    async onSummaryTaskPoiAnalysisYearChange() {
      const targetYear = Number(this.poiYearSource || this.resultPoiYear || 0)
      if (Number.isFinite(targetYear) && targetYear > 0) {
        this.poiYearSelections = [targetYear]
        await this.selectAgentPoiYearForGrid(targetYear)
      }
      this.onSummaryTaskParameterChange('poi_fetch')
    },
    async onSummaryTaskPoiGridYearChange() {
      await this.onSummaryTaskPoiAnalysisYearChange()
      this.onSummaryTaskParameterChange('poi_h3_grid')
    },
    async selectAgentPoiYearForGrid(year = '') {
      const targetYear = Number(year)
      if (!Number.isFinite(targetYear)) return
      const existing = cloneArray(this.poiResultsByYear)
        .find((item) => Number(item && item.year) === targetYear && cloneArray(item && item.pois).length)
      if (existing) {
        this.allPoisDetails = this.deduplicateFetchedPois
          ? this.deduplicateFetchedPois(cloneArray(existing.pois))
          : cloneArray(existing.pois)
        this.resultPoiYear = targetYear
        this.currentHistorySelectedPoiYear = targetYear
        this.poiYearSource = String(targetYear)
        this.poiDataSource = asText(existing.source || this.poiDataSource || this.resultDataSource)
        this.resultDataSource = this.poiDataSource
        this.poiCategorySummary = cloneArray(existing.category_summary || this.poiCategorySummary)
        if (typeof this.rebuildPoiRuntimeSystem === 'function') this.rebuildPoiRuntimeSystem(this.allPoisDetails)
        if (typeof this.updatePoiCharts === 'function') this.updatePoiCharts()
        return
      }
      if (String(this.scopeSource || '').trim().toLowerCase() === 'history' && String(this.currentHistoryRecordId || '').trim() && typeof this.loadCurrentHistoryPoiYear === 'function') {
        await this.loadCurrentHistoryPoiYear(targetYear)
        return
      }
    },
    isSummaryTaskRunning(taskKey = '') {
      const task = this.getSummaryTaskByKey(taskKey)
      return !!(task && task.status === 'running')
    },
    canRunSummaryParallelFill() {
      return !this.isAgentSummaryTaskBoardRunning()
    },
    canRerunSummaryTask(task = null) {
      const current = task && typeof task === 'object' ? task : {}
      const key = asText(current.key)
      if (!key || this.isAgentSummaryBusy()) return false
      return asText(current.status) !== 'running'
    },
    canGenerateSummaryAfterTasks() {
      const readiness = this.normalizeAgentSummaryReadiness(this.agentSummaryReadiness)
      if (readiness.ready) return true
      const tasks = this.getSummaryTaskBoardTasks()
      return !!tasks.length && tasks.every((item) => this.isSummaryTaskTerminalStatus(item.status))
    },
    getSummaryTaskPendingLabels() {
      return this.getSummaryTaskBoardTasks()
        .filter((item) => item.status !== 'completed')
        .map((item) => asText(item.label || item.key))
    },
    async runSummaryTask(taskKey = '', options = {}) {
      const key = asText(taskKey)
      const def = getAnalysisTaskDefinition(key)
      if (!key || !def) throw new Error('未知任务')
      this.stopSummaryTaskLogTracking(key)
      const currentTask = this.getSummaryTaskByKey(key)
      const paramsChanged = this.hasSummaryTaskParamChanged(key, currentTask)
      if (!options.force && !paramsChanged && typeof def.hasResult === 'function' && def.hasResult(this)) {
        this.finalizeSummaryTaskAsReused(key)
        return
      }
      const board = this.ensureSummaryTaskBoard(false)
      const now = new Date().toISOString()
      const tasks = cloneArray(board.tasks).map((task) => {
        if (asText(task.key) !== key) return task
        return {
          ...task,
          status: 'running',
          startedAt: now,
          endedAt: '',
          error: '',
          paramsSnapshot: this.captureSummaryTaskParams(key),
          logs: [],
        }
      })
      this.updateSummaryTaskBoard({ ...board, tasks, runState: 'running' })
      this.appendSummaryTaskLog(key, `开始执行：${def.label}`)
      this.startSummaryTaskLogTracking(key, { startedAtMs: Date.now(), suppressPlaceholder: !!options.suppressPlaceholder })
      try {
        await runAnalysisTask(this, key, { focus: false })
        this.pollSummaryTaskProgressLog(key)
        let hasResult = typeof def.hasResult === 'function' ? !!def.hasResult(this) : true
        if (!hasResult) {
          const statusText = this.getSummaryTaskProgressMessage(key)
          if (this.isSummaryTaskBackgroundRunning(key, def, statusText)) {
            hasResult = await this.waitForSummaryTaskBackgroundResult(key, def, {
              ...options,
              suppressPlaceholder: true,
            })
          }
        }
        if (!hasResult) {
          const statusText = this.getSummaryTaskProgressMessage(key)
          throw new Error(statusText || `${def.label}未产出可用结果，请检查对应面板状态后重试`)
        }
        const endedAt = new Date().toISOString()
        const merged = this.ensureSummaryTaskBoard(false)
        const nextTasks = cloneArray(merged.tasks).map((task) => {
          if (asText(task.key) !== key) return task
          const started = Date.parse(asText(task.startedAt || endedAt))
          const ended = Date.parse(endedAt)
          return {
            ...task,
            status: 'completed',
            endedAt,
            durationMs: Number.isFinite(started) && Number.isFinite(ended) ? Math.max(0, ended - started) : 0,
            error: '',
          }
        })
        const nextRunState = nextTasks.every((item) => this.isSummaryTaskTerminalStatus(item.status))
          ? 'completed'
          : (nextTasks.some((item) => item.status === 'running') ? 'running' : 'idle')
        this.updateSummaryTaskBoard({ ...merged, tasks: nextTasks, runState: nextRunState })
        this.appendSummaryTaskLog(key, '执行完成', 'success')
      } catch (err) {
        this.pollSummaryTaskProgressLog(key)
        const endedAt = new Date().toISOString()
        const statusText = this.getSummaryTaskProgressMessage(key)
        const rawMessage = err && err.message ? err.message : String(err)
        const message = this.isSummaryTaskIntermediateStatus(key, statusText)
          ? (rawMessage || `${def.label}仍在处理中，请稍后查看`)
          : rawMessage
        const merged = this.ensureSummaryTaskBoard(false)
        const nextTasks = cloneArray(merged.tasks).map((task) => {
          if (asText(task.key) !== key) return task
          const started = Date.parse(asText(task.startedAt || endedAt))
          const ended = Date.parse(endedAt)
          return {
            ...task,
            status: 'failed',
            endedAt,
            durationMs: Number.isFinite(started) && Number.isFinite(ended) ? Math.max(0, ended - started) : 0,
            error: this.isSummaryTaskIntermediateStatus(key, statusText) ? '' : message,
          }
        })
        this.updateSummaryTaskBoard({ ...merged, tasks: nextTasks, runState: 'failed' })
        this.appendSummaryTaskLog(key, `执行失败：${message}`, 'error')
        throw err
      } finally {
        this.stopSummaryTaskLogTracking(key)
      }
    },
    async rerunSummaryTask(taskKey = '') {
      const key = asText(taskKey)
      const task = this.getSummaryTaskByKey(key)
      if (!this.canRerunSummaryTask(task)) return
      this.agentSummaryError = ''
      await this.runSummaryTask(key, { force: true, source: 'manual-rerun' })
      await this.refreshAgentSummaryReadiness(true)
    },
    async startSummaryParallelFill() {
      if (!this.canRunSummaryParallelFill()) return
      this.syncSummaryTaskBoardFromLocalResults()
      if (!this.canRunSummaryParallelFill()) return
      const requestedKeys = this.getSummaryTaskKeysToFill()
      const keysToRun = this.filterSummaryTaskKeysForReuse(requestedKeys, { forcePoiFetch: false })
      const reusedKeys = requestedKeys.filter((key) => !keysToRun.includes(key))
      reusedKeys.forEach((key) => this.finalizeSummaryTaskAsReused(key))
      if (!keysToRun.length) {
        this.updateSummaryTaskBoard({
          ...this.ensureSummaryTaskBoard(false),
          runState: 'completed',
          lastRunAt: new Date().toISOString(),
        })
        this.agentSummaryError = ''
        await this.refreshAgentSummaryReadiness(true)
        return
      }
      const board = this.ensureSummaryTaskBoard(false)
      const next = {
        ...board,
        runState: 'running',
        lastRunAt: new Date().toISOString(),
      }
      this.updateSummaryTaskBoard(next)
      const promises = keysToRun.map((key) => this.runSummaryTask(key, { source: 'parallel' }))
      const settled = await Promise.allSettled(promises)
      const hasFailed = settled.some((item) => item.status === 'rejected')
      if (hasFailed) {
        const messages = settled
          .filter((item) => item.status === 'rejected')
          .map((item) => {
            const reason = item.reason
            return reason && reason.message ? reason.message : String(reason || '')
          })
          .filter(Boolean)
        this.agentSummaryError = messages.length ? `补齐失败：${messages[0]}` : '补齐失败，请查看任务日志'
      } else {
        this.agentSummaryError = ''
      }
      const current = this.ensureSummaryTaskBoard(false)
      this.updateSummaryTaskBoard({
        ...current,
        runState: hasFailed ? 'failed' : 'completed',
      })
      if (!hasFailed) {
        await this.refreshAgentSummaryReadiness(true)
      }
    },
    resetAgentSummaryRecompute() {
      if (typeof this.stopAllSummaryTaskLogTracking === 'function') {
        this.stopAllSummaryTaskLogTracking()
      }
      const board = this.createDefaultSummaryTaskBoard()
      const readiness = {
        checked: true,
        ready: false,
        missingTasks: this.getSummaryTaskKeys(),
        reused: [],
        fetched: [],
      }
      const payloads = {
        ...cloneObject(this.agentPanelPayloads),
        data_readiness: {
          checked: readiness.checked,
          ready: readiness.ready,
          missing_tasks: cloneArray(readiness.missingTasks),
          reused: [],
          fetched: [],
        },
        summary_status: {
          status: 'idle',
          generated: false,
          title: '区域总结',
          description: '',
          message: '',
        },
        summary_pack: {},
        summary_task_board: {
          run_state: board.runState,
          last_run_at: board.lastRunAt,
          tasks: cloneArray(board.tasks).map((task) => ({
            key: task.key,
            label: task.label,
            status: task.status,
            params_snapshot: cloneObject(task.paramsSnapshot),
            started_at: task.startedAt,
            ended_at: task.endedAt,
            duration_ms: task.durationMs,
            logs: cloneArray(task.logs),
            error: task.error,
          })),
        },
      }
      const draft = createAgentSessionRecord({
        title: '区域总结补齐',
        preview: '复用已有结果并补齐缺失分析',
        historyId: this.getCurrentAgentHistoryId(),
        panelKind: 'commercial_summary',
        status: 'idle',
        stage: 'gating',
        output: {
          cards: [],
          panelPayloads: payloads,
          decision: { summary: '', mode: 'judgment', strength: 'weak', canAct: false },
          support: [],
          counterpoints: [],
          actions: [],
          boundary: [],
        },
        diagnostics: { executionTrace: [], usedTools: [], citations: [], researchNotes: [], auditIssues: [], thinkingTimeline: [], error: '' },
        contextSummary: {},
        plan: { steps: [], followupSteps: [], followupApplied: false, summary: '' },
        persisted: false,
        snapshotLoaded: true,
        titleSource: 'fallback',
      })
      this.updateAgentSessions([draft, ...this.agentSessions], { loaded: this.agentSessionsLoaded })
      this.activeAgentSessionId = draft.id
      this.agentWorkspaceView = 'report'
      this.agentInput = ''
      this.agentStatus = 'idle'
      this.agentStage = 'gating'
      this.agentCards = []
      this.agentDecision = { summary: '', mode: 'judgment', strength: 'weak', canAct: false }
      this.agentSupport = []
      this.agentCounterpoints = []
      this.agentActions = []
      this.agentBoundary = []
      this.agentReviewContract = {}
      this.agentExecutionTrace = []
      this.agentUsedTools = []
      this.agentCitations = []
      this.agentResearchNotes = []
      this.agentAuditIssues = []
      this.agentNextSuggestions = []
      this.agentMessages = []
      this.agentPanelPayloads = payloads
      this.agentSummaryReadiness = readiness
      this.agentSummaryError = ''
      this.agentSummaryWarnings = []
      this.agentSummaryLoading = false
      this.agentSummaryGenerating = false
      this.agentSummaryProgressPhase = ''
      this.resetAgentSummaryStreamSections()
      this.summaryTaskBoard = board
      this.agentTabs = this.createDefaultAgentTabs()
      this.createAgentSummaryTab({ title: '区域总结', reuseExisting: true })
      this.syncCurrentAgentSession({ persisted: false, snapshotLoaded: true, panelKind: 'commercial_summary' })
    },
    isAgentSummaryBusy() {
      return Boolean(this.agentSummaryGenerating || this.agentSummaryLoading)
    },
    isAgentSummaryTaskBoardRunning() {
      const board = this.ensureSummaryTaskBoard(false)
      return asText(board.runState) === 'running'
        || cloneArray(board.tasks).some((item) => asText(item && item.status) === 'running')
    },
    isAgentSummaryPrimaryActionDisabled() {
      return Boolean(this.agentSummaryGenerating || this.isAgentSummaryTaskBoardRunning())
    },
    getAgentSummaryPrimaryActionLabel() {
      if (this.agentSummaryGenerating) return '生成中...'
      if (this.canGenerateSummaryAfterTasks()) return '生成区域总结'
      return this.getSummaryTaskKeysToFill().length ? '补齐缺失' : '复用已有结果'
    },
    runAgentSummaryPrimaryAction() {
      if (this.canGenerateSummaryAfterTasks()) {
        return this.generateAgentSummaryPanel()
      }
      return this.startSummaryParallelFill()
    },
    createSummaryHistorySessionId() {
      return `summary-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
    },
    getAgentSummaryPhaseLabel() {
      const phase = asText(this.agentSummaryProgressPhase)
      const mapping = {
        precheck: '正在检查数据就绪度',
        fetch_missing: '正在补齐缺失分析',
        derive_analysis: '正在补齐结构化分析',
        analysis_started: '正在生成结构化区域总结',
        completed: '区域总结生成完成',
      }
      return mapping[phase] || ''
    },
    createEmptyAgentSummaryStreamSections() {
      return {
        headline: { key: 'headline', content: '', status: 'pending', error: '', payload: {} },
        tags: { key: 'tags', content: '', status: 'pending', error: '', payload: {} },
        spatial_structure: { key: 'spatial_structure', content: '', status: 'pending', error: '', payload: {} },
        poi_structure: { key: 'poi_structure', content: '', status: 'pending', error: '', payload: {} },
        consumption_vitality: { key: 'consumption_vitality', content: '', status: 'pending', error: '', payload: {} },
        business_support: { key: 'business_support', content: '', status: 'pending', error: '', payload: {} },
        user_profile: { key: 'user_profile', content: '', status: 'pending', error: '', payload: {} },
        behavior: { key: 'behavior', content: '', status: 'pending', error: '', payload: {} },
        tourism_cross_analysis: { key: 'tourism_cross_analysis', content: '', status: 'pending', error: '', payload: {} },
        followups: { key: 'followups', content: '', status: 'pending', error: '', payload: {} },
      }
    },
    resetAgentSummaryStreamSections() {
      this.agentSummaryStreamSections = this.createEmptyAgentSummaryStreamSections()
      return this.agentSummaryStreamSections
    },
    ensureAgentSummaryStreamSections() {
      const current = cloneObject(this.agentSummaryStreamSections)
      if (Object.keys(current).length) return current
      return this.resetAgentSummaryStreamSections()
    },
    patchAgentSummaryStreamSection(sectionKey = '', patch = {}) {
      const key = asText(sectionKey)
      if (!key) return null
      const current = this.ensureAgentSummaryStreamSections()
      this.agentSummaryStreamSections = {
        ...current,
        [key]: {
          ...(current[key] || { key, content: '', status: 'pending', error: '', payload: {} }),
          ...cloneObject(patch),
        },
      }
      return this.agentSummaryStreamSections[key]
    },
    getAgentSummaryFollowupQuestions(panelPayloads = null) {
      const payloads = panelPayloads && typeof panelPayloads === 'object'
        ? cloneObject(panelPayloads)
        : this.getAgentActiveSummaryPanelPayloads()
      const summaryPack = this.getAgentSummaryPack(payloads)
      const items = cloneArray(
        summaryPack.followup_questions
        || payloads.summary_followup_questions
        || (((this.agentSummaryStreamSections || {}).followups || {}).payload || {}).followup_questions,
      ).map((item) => asText(item)).filter(Boolean)
      if (items.length) return items
      return [
        '请解释这份区域总结背后的证据链与判断依据',
        '请展开这一范围的业态建议与主要风险',
        '请把这份区域总结转成可执行清单',
      ]
    },
    getAgentSummaryGeneratingSections() {
      const phase = asText(this.agentSummaryProgressPhase)
      const phaseStarted = phase === 'analysis_started'
      const liveSections = this.ensureAgentSummaryStreamSections()
      const buildTaskState = (taskKeys = []) => {
        const keys = cloneArray(taskKeys).map((item) => asText(item)).filter(Boolean)
        const tasks = keys.map((key) => this.getSummaryTaskByKey(key)).filter(Boolean)
        const pendingLabels = keys
          .filter((key) => {
            const task = this.getSummaryTaskByKey(key)
            return !(task && this.isSummaryTaskTerminalStatus(task.status))
          })
          .map((key) => this.getAgentSummaryTaskLabel(key))
        const hasRunning = tasks.some((task) => asText(task && task.status) === 'running')
        const allTerminal = keys.length > 0 && keys.every((key) => {
          const task = this.getSummaryTaskByKey(key)
          return !!(task && this.isSummaryTaskTerminalStatus(task.status))
        })
        return { hasRunning, allTerminal, pendingLabels }
      }
      const buildStatusLabel = (status = '') => {
        if (status === 'failed') return '失败'
        if (status === 'ready') return '已就绪'
        if (status === 'active') return '生成中'
        return '等待中'
      }
      const buildDetail = (state, fallback = '等待生成结构化内容') => {
        if (phaseStarted && state.allTerminal) return '结构化证据已齐，正在组织成文'
        if (state.hasRunning) return '相关分析正在生成'
        if (state.allTerminal) return '结构化证据已齐备'
        if (state.pendingLabels.length) return `等待${state.pendingLabels.slice(0, 2).join('、')}`
        return fallback
      }
      const sections = [
        { key: 'headline', title: '核心判断', layout: 'text', taskKeys: ['poi_h3_grid', 'population', 'nightlight', 'road_syntax'] },
        { key: 'tags', title: '商业类型标签（ICSC）', layout: 'tags', taskKeys: ['poi_h3_grid'] },
        { key: 'spatial_structure', title: '空间结构', layout: 'panel', taskKeys: ['poi_h3_grid', 'population', 'nightlight', 'road_syntax'] },
        { key: 'poi_structure', title: 'POI结构', layout: 'panel', taskKeys: ['poi_h3_grid'] },
        { key: 'consumption_vitality', title: '经济活动强度', layout: 'panel', taskKeys: ['nightlight'] },
        { key: 'business_support', title: '业态承接', layout: 'panel', taskKeys: ['poi_h3_grid', 'road_syntax'] },
        { key: 'user_profile', title: '用户画像', layout: 'list', taskKeys: ['population'] },
        { key: 'behavior', title: '商业行为推断', layout: 'list', taskKeys: ['nightlight', 'road_syntax'] },
        { key: 'tourism_cross_analysis', title: '文旅交叉策划分析', layout: 'longtext', taskKeys: ['poi_raster_grid', 'poi_h3_grid', 'population', 'nightlight'] },
        { key: 'followups', title: '快捷追问', layout: 'actions', taskKeys: ['poi_h3_grid', 'population', 'nightlight', 'road_syntax'] },
      ]
      return sections.map((section) => {
        const live = liveSections[section.key] || {}
        const state = buildTaskState(section.taskKeys)
        let status = 'pending'
        if (['ready', 'failed', 'active'].includes(asText(live.status))) {
          status = asText(live.status)
        } else if (phaseStarted && (section.key === 'headline' || section.key === 'tourism_cross_analysis' || section.key === 'followups')) {
          status = 'active'
        } else if (state.hasRunning) {
          status = 'active'
        } else if (state.allTerminal) {
          status = 'ready'
        } else if (phase === 'derive_analysis' && ['headline', 'spatial_structure', 'poi_structure', 'consumption_vitality', 'business_support'].includes(section.key)) {
          status = 'active'
        }
        return {
          ...section,
          status,
          statusLabel: buildStatusLabel(status),
          detail: asText(live.error) || (!asText(live.content) ? buildDetail(state) : ''),
          content: asText(live.content),
          payload: cloneObject(live.payload),
        }
      })
    },
    getAgentSummaryGateProgressText() {
      const phaseLabel = this.getAgentSummaryPhaseLabel()
      if (phaseLabel) return `${phaseLabel}…`
      if (this.agentSummaryLoading) return '正在检查数据就绪度…'
      const readiness = this.normalizeAgentSummaryReadiness(this.agentSummaryReadiness)
      if (readiness.checked) {
        if (readiness.ready || this.canGenerateSummaryAfterTasks()) return '数据已就绪，可直接生成区域总结'
        const pendingCount = this.getAgentSummaryMissingTaskLabels().length
        return pendingCount > 0 ? `已完成数据检查，还缺 ${pendingCount} 项` : '已完成数据检查'
      }
      return '等待开始'
    },
    async refreshAgentSummaryReadiness(force = false) {
      if (!this.isCurrentAgentSummaryTabActive()) return this.agentSummaryReadiness
      if (this.agentSummaryLoading) return this.agentSummaryReadiness
      if (!force && this.hasAgentSummaryPack() && this.agentSummaryReadiness.ready) return this.agentSummaryReadiness
      this.agentSummaryLoading = true
      this.agentSummaryError = ''
      this.agentSummaryWarnings = []
      try {
        await Promise.allSettled([
          typeof this.loadPopulationMeta === 'function' ? this.loadPopulationMeta(false) : null,
          typeof this.loadNightlightMeta === 'function' ? this.loadNightlightMeta(false) : null,
        ].filter(Boolean))
        const res = await fetch('/api/v1/analysis/agent/summary/readiness', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            conversation_id: this.getActiveAgentSessionId(),
            history_id: asText(this.getCurrentAgentHistoryId()),
            analysis_snapshot: this.buildAgentAnalysisSnapshot(),
          }),
        })
        if (!res.ok) {
          let detail = ''
          try {
            detail = await res.text()
          } catch (_) {}
          throw new Error(detail || `/api/v1/analysis/agent/summary/readiness 请求失败(${res.status})`)
        }
        const data = await res.json()
        this.agentSummaryReadiness = this.normalizeAgentSummaryReadiness(data && data.data_readiness)
        this.agentSummaryWarnings = cloneArray(data && data.warnings)
        this.agentSummaryError = asText(data && data.error)
        this.agentPanelPayloads = {
          ...cloneObject(this.agentPanelPayloads),
          data_readiness: {
            checked: this.agentSummaryReadiness.checked,
            ready: this.agentSummaryReadiness.ready,
            missing_tasks: cloneArray(this.agentSummaryReadiness.missingTasks),
            reused: cloneArray(this.agentSummaryReadiness.reused),
            fetched: cloneArray(this.agentSummaryReadiness.fetched),
          },
        }
        this.syncCurrentAgentSession()
        return this.agentSummaryReadiness
      } catch (err) {
        this.agentSummaryError = err && err.message ? err.message : String(err)
        return this.agentSummaryReadiness
      } finally {
        this.agentSummaryLoading = false
      }
    },
    async generateAgentSummaryPanel() {
      if (this.agentSummaryGenerating) return
      if (!this.isAgentSummaryTabActive()) {
        this.createAgentSummaryTab({ title: '区域总结' })
      } else {
        this.createAgentSummaryTab({ title: '区域总结', reuseExisting: true })
      }
      this.agentSummaryGenerating = true
      this.resetAgentSummaryStreamSections()
      this.agentSummaryProgressPhase = 'precheck'
      this.agentSummaryError = ''
      this.agentSummaryWarnings = []
      this.agentPanelPayloads = {
        ...cloneObject(this.agentPanelPayloads),
        summary_status: {
          status: 'generating',
          generated: false,
          title: '区域总结生成中',
          description: '正在基于结构化证据生成区域总结。',
          message: '',
        },
      }
      this.syncCurrentAgentSession()
      const readinessSnapshot = this.normalizeAgentSummaryReadiness(this.agentSummaryReadiness)
      const canUseCurrentReadiness = readinessSnapshot.checked
        && readinessSnapshot.ready
        && !cloneArray(readinessSnapshot.missingTasks).length
      if (canUseCurrentReadiness) {
        this.refreshAgentSummaryReadiness(true).catch((err) => {
          console.warn('Agent summary readiness refresh failed while generating', err)
        })
      } else {
        await this.refreshAgentSummaryReadiness(true)
      }
      if (!this.canGenerateSummaryAfterTasks()) {
        const pending = this.getSummaryTaskKeysFromReadiness().map((taskKey) => this.getAgentSummaryTaskLabel(taskKey))
        this.agentSummaryError = pending.length ? `请先补齐缺失项：${pending.join('、')}` : '请先完成补齐任务后再生成区域总结'
        this.agentSummaryGenerating = false
        return
      }
      try {
        const res = await fetch('/api/v1/analysis/agent/summary/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            conversation_id: this.getActiveAgentSessionId(),
            history_id: asText(this.getCurrentAgentHistoryId()),
            analysis_snapshot: this.buildAgentAnalysisSnapshot(),
          }),
        })
        if (!res.ok) {
          let detail = ''
          try {
            detail = await res.text()
          } catch (_) {}
          throw new Error(detail || `/api/v1/analysis/agent/summary/generate 请求失败(${res.status})`)
        }
        let finalPayload = null
        await consumeSseStream(res, (event) => {
          const type = asText(event && event.type)
          const payload = cloneObject(event && event.payload)
          const normalizeStreamKey = (key, extra = {}) => {
            const rawKey = asText(key)
            if (rawKey === 'secondary') {
              return asText(extra.section_key || extra.sectionKey)
            }
            return rawKey
          }
          if (type === 'status') {
            this.agentSummaryProgressPhase = asText(payload.phase) || this.agentSummaryProgressPhase
            return
          }
          if (type === 'section_start') {
            const streamKey = normalizeStreamKey(payload.key, payload)
            if (!streamKey) return
            this.patchAgentSummaryStreamSection(streamKey, {
              status: 'active',
              error: '',
              content: '',
              payload: cloneObject(payload.payload),
            })
            return
          }
          if (type === 'section_delta') {
            const streamKey = normalizeStreamKey(payload.key, payload)
            if (!streamKey) return
            const current = cloneObject((this.ensureAgentSummaryStreamSections() || {})[streamKey] || {})
            this.patchAgentSummaryStreamSection(streamKey, {
              status: 'active',
              content: `${asText(current.content)}${asText(payload.delta)}`,
            })
            return
          }
          if (type === 'section_complete') {
            const nextStatus = asText(payload.status || 'ready') || 'ready'
            const sectionPayload = cloneObject(payload.payload)
            let nextContent = ''
            const streamKey = normalizeStreamKey(payload.key, payload)
            if (payload.key === 'headline') {
              nextContent = [asText(sectionPayload.summary), asText(sectionPayload.supporting_clause)].filter(Boolean).join('\n')
            } else if (payload.key === 'user_profile' || payload.key === 'behavior') {
              nextContent = [asText(sectionPayload.headline), ...cloneArray(sectionPayload.traits).map((item) => asText(item)).filter(Boolean)].join('\n')
            } else if (payload.key === 'secondary') {
              cloneArray(sectionPayload.secondary_conclusions).forEach((item) => {
                const itemKey = asText(item && item.section_key)
                if (!itemKey) return
                this.patchAgentSummaryStreamSection(itemKey, {
                  status: nextStatus === 'failed' ? 'failed' : 'ready',
                  payload: cloneObject(item),
                  content: asText(item && item.reasoning),
                  error: nextStatus === 'failed' ? (asText(payload.message) || '当前面板生成失败') : '',
                })
              })
              return
            } else if (['spatial_structure', 'poi_structure', 'consumption_vitality', 'business_support'].includes(payload.key)) {
              nextContent = asText(sectionPayload.reasoning)
            } else if (payload.key === 'followups') {
              nextContent = cloneArray(sectionPayload.followup_questions).map((item) => asText(item)).filter(Boolean).join('\n')
            } else if (payload.key === 'tags') {
              nextContent = cloneArray(sectionPayload.icsc_tags).map((item) => asText(item)).filter(Boolean).join('、')
            } else if (payload.key === 'tourism_cross_analysis') {
              nextContent = asText(sectionPayload.content)
            }
            if (!streamKey) return
            this.patchAgentSummaryStreamSection(streamKey, {
              status: nextStatus === 'failed' ? 'failed' : 'ready',
              payload: sectionPayload,
              content: nextContent || asText(((this.ensureAgentSummaryStreamSections() || {})[streamKey] || {}).content),
              error: nextStatus === 'failed' ? (asText(payload.message) || '当前面板生成失败') : '',
            })
            return
          }
          if (type === 'panel_payload') {
            const nextPayloads = {
              ...cloneObject(this.agentPanelPayloads),
              ...cloneObject(payload.payload),
            }
            this.agentPanelPayloads = nextPayloads
            return
          }
          if (type === 'error') {
            const targetKey = normalizeStreamKey(payload.key, payload)
            if (targetKey && targetKey !== 'global') {
              const current = cloneObject((this.ensureAgentSummaryStreamSections() || {})[targetKey] || {})
              this.patchAgentSummaryStreamSection(targetKey, {
                status: 'failed',
                error: asText(payload.message) || '当前面板生成失败',
                content: asText(current.content),
              })
            } else {
              this.agentSummaryError = asText(payload.message) || this.agentSummaryError
            }
            return
          }
          if (type === 'final') {
            finalPayload = payload
          }
        })
        if (!finalPayload) {
          throw new Error('区域总结流式生成未返回最终结果')
        }
        const data = cloneObject(finalPayload)
        const phases = cloneArray(data.phases).map((item) => asText(item)).filter(Boolean)
        this.agentSummaryProgressPhase = phases.length ? phases[phases.length - 1] : 'completed'
        this.agentSummaryReadiness = this.normalizeAgentSummaryReadiness(data && data.data_readiness)
        this.agentSummaryWarnings = cloneArray(data && data.warnings)
        this.agentSummaryError = asText(data && data.error)
        this.agentPanelPayloads = {
          ...cloneObject(this.agentPanelPayloads),
          data_readiness: {
            checked: this.agentSummaryReadiness.checked,
            ready: this.agentSummaryReadiness.ready,
            missing_tasks: cloneArray(this.agentSummaryReadiness.missingTasks),
            reused: cloneArray(this.agentSummaryReadiness.reused),
            fetched: cloneArray(this.agentSummaryReadiness.fetched),
          },
        }
        const payloads = cloneObject(data && data.panel_payloads)
        if (payloads && typeof payloads === 'object') {
          this.agentPanelPayloads = {
            ...cloneObject(this.agentPanelPayloads),
            ...payloads,
          }
        }
        if (data && data.summary_pack && typeof data.summary_pack === 'object') {
          this.agentPanelPayloads = {
            ...cloneObject(this.agentPanelPayloads),
            summary_pack: cloneObject(data.summary_pack),
          }
        }
        if (this.isCurrentAgentSummaryTabActive()) {
          this.commitAgentSummaryPayloadsToActiveTab()
        }
        const summaryPack = cloneObject(this.getAgentSummaryPack())
        const summaryStatus = this.getAgentSummaryStatus(this.agentPanelPayloads)
        if (!summaryStatus.generated || !this.hasAgentSummaryPack(summaryPack)) {
          return
        }
        const headline = asText((summaryPack.headline_judgment || {}).summary)
        const supporting = asText((summaryPack.headline_judgment || {}).supporting_clause)
        const summarySession = createAgentSessionRecord({
          id: this.createSummaryHistorySessionId(),
          title: clampText(headline || '区域总结', 60) || '区域总结',
          preview: clampText(supporting || headline || '区域总结', 120) || '区域总结',
          historyId: this.getCurrentAgentHistoryId(),
          panelKind: 'commercial_summary',
          status: 'answered',
          stage: 'answered',
          input: '',
          messages: [],
          cards: [],
          decision: this.agentDecision,
          support: this.agentSupport,
          counterpoints: this.agentCounterpoints,
          actions: this.agentActions,
          boundary: this.agentBoundary,
          reviewContract: this.agentReviewContract,
          executionTrace: this.agentExecutionTrace,
          usedTools: this.agentUsedTools,
          citations: this.agentCitations,
          researchNotes: this.agentResearchNotes,
          auditIssues: this.agentAuditIssues,
          nextSuggestions: [],
          clarificationQuestion: '',
          clarificationOptions: [],
          riskPrompt: '',
          error: '',
          contextSummary: this.agentContextSummary,
          plan: this.agentPlan,
          panelPayloads: this.agentPanelPayloads,
          persisted: true,
          snapshotLoaded: true,
          titleSource: 'ai',
        })
        this.updateAgentSessions(
          [summarySession, ...this.agentSessions.filter((item) => asText(item && item.id) !== asText(summarySession.id))],
          { loaded: this.agentSessionsLoaded },
        )
        this.applyAgentSessionSnapshot(summarySession)
        const synced = this.syncCurrentAgentSession({
          persisted: true,
          status: 'answered',
          historyId: this.getCurrentAgentHistoryId(),
          panelKind: 'commercial_summary',
        })
        const sessionId = asText((synced && synced.id) || summarySession.id)
        if (sessionId) {
          await this.putAgentSession(sessionId, {
            status: 'answered',
            persisted: true,
            historyId: this.getCurrentAgentHistoryId(),
            panelKind: 'commercial_summary',
          })
        }
        await this.loadAgentSessionSummaries(true)
      } catch (err) {
        const message = err && err.message ? err.message : String(err)
        this.agentSummaryError = message
        this.agentPanelPayloads = {
          ...cloneObject(this.agentPanelPayloads),
          summary_status: {
            status: 'failed',
            generated: false,
            title: '区域总结生成失败',
            description: '生成区域总结时发生错误，请检查后重试。',
            message,
          },
        }
        this.agentSummaryProgressPhase = ''
      } finally {
        if (!this.agentSummaryReadiness.ready) {
          this.agentSummaryProgressPhase = ''
        }
        this.agentSummaryGenerating = false
      }
    },
    ensureAgentTabs(commit = false) {
      const base = this.agentTabs && typeof this.agentTabs === 'object'
        ? this.agentTabs
        : this.createDefaultAgentTabs()
      const currentSummaryPack = this.getAgentSummaryPack(this.agentPanelPayloads)
      const preservedSummaryPack = cloneObject((((base.summaryTab || {}).content) || {}))
      const defaultSummaryPack = this.hasAgentSummaryPack(currentSummaryPack) || Object.keys(currentSummaryPack).length
        ? currentSummaryPack
        : preservedSummaryPack
      const currentSummaryStatus = this.getAgentSummaryStatus(this.agentPanelPayloads)
      const nextTabs = {
        summaryTab: {
          ...this.createDefaultAgentSummaryTab(),
          ...cloneObject(base.summaryTab && typeof base.summaryTab === 'object' ? base.summaryTab : {}),
          id: 'summary',
          kind: 'summary',
          frozen: true,
          source: 'current',
        },
        summaryTabs: cloneArray(base.summaryTabs).map((item) => ({
          id: asText(item && item.id),
          kind: 'summary',
          title: asText(item && item.title) || '区域总结',
          source: asText(item && item.source) || 'history',
          sessionId: asText(item && item.sessionId),
          createdAt: asText(item && item.createdAt) || new Date().toISOString(),
          readonly: Object.prototype.hasOwnProperty.call(item || {}, 'readonly') ? !!item.readonly : false,
          panelPayloads: cloneObject(item && item.panelPayloads),
          content: cloneObject(item && item.content),
          evidenceRefs: cloneArray(item && item.evidenceRefs),
        })).filter((item) => item.id),
        iterationChangeTabs: cloneArray(base.iterationChangeTabs).map((item) => ({
          id: asText(item && item.id),
          kind: 'iteration_change',
          title: asText(item && item.title) || '多年迭代变化',
          source: asText(item && item.source) || 'draft',
          sessionId: asText(item && item.sessionId),
          readonly: !!(item && item.readonly),
          createdAt: asText(item && item.createdAt) || new Date().toISOString(),
          panelPayloads: cloneObject(item && item.panelPayloads),
          activeKind: asText(item && item.activeKind) || 'poi',
        })).filter((item) => item.id),
        siteSelectionTabs: cloneArray(base.siteSelectionTabs).map((item) => ({
          id: asText(item && item.id),
          kind: 'site_selection',
          title: asText(item && item.title) || '区域内选址',
          source: asText(item && item.source) || 'draft',
          sessionId: asText(item && item.sessionId),
          readonly: !!(item && item.readonly),
          createdAt: asText(item && item.createdAt) || new Date().toISOString(),
          panelPayloads: cloneObject(item && item.panelPayloads),
        })).filter((item) => item.id),
        deepAnalysisTabs: cloneArray(base.deepAnalysisTabs).map((item) => ({
          id: asText(item && item.id),
          kind: 'deep_analysis',
          title: asText(item && item.title) || '继续分析',
          source: asText(item && item.source) || 'draft',
          sessionId: asText(item && item.sessionId),
          readonly: !!(item && item.readonly),
          createdAt: asText(item && item.createdAt) || new Date().toISOString(),
          target: this.normalizeContextAskTarget(item && item.target),
          question: asText(item && item.question),
          mode: asText(item && item.mode) || 'quick',
          resultModuleId: asText(item && item.resultModuleId),
          thread: this.createAgentFollowupThreadState(item && item.thread),
          panelPayloads: cloneObject(item && item.panelPayloads),
        })).filter((item) => item.id),
        followupTabs: cloneArray(base.followupTabs).map((item) => ({
          id: asText(item && item.id),
          kind: 'followup',
          title: this.getAgentFollowupViewTitle(item, item && item.title),
          linkedSummaryId: asText(item && item.linkedSummaryId) || 'summary',
          source: asText(item && item.source) || 'draft',
          sessionId: asText(item && item.sessionId),
          readonly: !!(item && item.readonly && asText(item && item.source) !== 'history'),
          createdAt: asText(item && item.createdAt) || new Date().toISOString(),
          thread: this.createAgentFollowupThreadState(item && item.thread),
        })).filter((item) => item.id),
        activeTabId: asText(base.activeTabId),
        followupLimit: Number(base.followupLimit || 6) || 6,
        nextFollowupNumber: Number(base.nextFollowupNumber || 1) || 1,
      }
      if (!nextTabs.summaryTab.id) nextTabs.summaryTab.id = 'summary'
      const currentSummaryTabs = cloneArray(nextTabs.summaryTabs).filter((item) => asText(item.source) === 'current')
      const historySummaryTabs = cloneArray(nextTabs.summaryTabs).filter((item) => asText(item.source) !== 'current')
      const shouldAutoCreateCurrentSummary = true
      let syncedCurrentSummaryTabs = currentSummaryTabs.map((item) => {
        const preservedPayloads = cloneObject(item.panelPayloads)
        const payloadPack = this.getAgentSummaryPack(preservedPayloads)
        const content = Object.keys(payloadPack).length
          ? cloneObject(payloadPack)
          : (Object.keys(cloneObject(item.content)).length ? cloneObject(item.content) : cloneObject(defaultSummaryPack))
        const panelPayloads = {
          ...preservedPayloads,
          ...(Object.keys(content).length ? { summary_pack: cloneObject(content) } : {}),
        }
        if (!panelPayloads.summary_task_board && !panelPayloads.summaryTaskBoard) {
          panelPayloads.summary_task_board = this.normalizeSummaryTaskBoard(this.summaryTaskBoard)
        }
        return {
          ...item,
          title: this.getAgentSummaryViewTitle(panelPayloads, item.title || currentSummaryStatus.title),
          panelPayloads,
          content: cloneObject(content),
          evidenceRefs: cloneArray(content.evidence_refs || item.evidenceRefs || []),
        }
      })
      if (!syncedCurrentSummaryTabs.length && shouldAutoCreateCurrentSummary) {
        syncedCurrentSummaryTabs = [{
          id: 'summary-current',
          kind: 'summary',
          title: this.getAgentSummaryViewTitle(this.agentPanelPayloads, currentSummaryStatus.title),
          source: 'current',
          sessionId: '',
          readonly: false,
          createdAt: new Date().toISOString(),
          panelPayloads: cloneObject(this.agentPanelPayloads),
          content: cloneObject(defaultSummaryPack),
          evidenceRefs: cloneArray(defaultSummaryPack.evidence_refs || []),
        }]
      }
      nextTabs.summaryTabs = [...syncedCurrentSummaryTabs, ...historySummaryTabs]
      const validIds = new Set([...nextTabs.summaryTabs.map((item) => item.id), ...nextTabs.iterationChangeTabs.map((item) => item.id), ...nextTabs.siteSelectionTabs.map((item) => item.id), ...nextTabs.deepAnalysisTabs.map((item) => item.id), ...nextTabs.followupTabs.map((item) => item.id)])
      if (!validIds.has(nextTabs.activeTabId)) {
        nextTabs.activeTabId = nextTabs.summaryTabs[0] ? nextTabs.summaryTabs[0].id : (nextTabs.iterationChangeTabs[0] ? nextTabs.iterationChangeTabs[0].id : (nextTabs.siteSelectionTabs[0] ? nextTabs.siteSelectionTabs[0].id : (nextTabs.deepAnalysisTabs[0] ? nextTabs.deepAnalysisTabs[0].id : (nextTabs.followupTabs[0] ? nextTabs.followupTabs[0].id : ''))))
      }
      nextTabs.summaryTab.content = defaultSummaryPack
      nextTabs.summaryTab.evidenceRefs = cloneArray((defaultSummaryPack.evidence_refs || []))
      if (commit) {
        this.agentTabs = nextTabs
      }
      return nextTabs
    },
    getAgentTopTabs() {
      const tabs = this.ensureAgentTabs(false)
      return [
        ...tabs.summaryTabs.map((item) => ({
          id: item.id,
          title: item.title || '区域总结',
          kind: 'summary',
          closable: true,
          source: item.source || 'history',
          sessionId: item.sessionId || '',
        })),
        ...tabs.iterationChangeTabs.map((item) => ({
          id: item.id,
          title: item.title || '多年迭代变化',
          kind: 'iteration_change',
          closable: true,
          source: item.source || 'draft',
          sessionId: item.sessionId || '',
        })),
        ...tabs.siteSelectionTabs.map((item) => ({
          id: item.id,
          title: item.title || '区域内选址',
          kind: 'site_selection',
          closable: true,
          source: item.source || 'draft',
          sessionId: item.sessionId || '',
        })),
        ...tabs.deepAnalysisTabs.map((item) => ({
          id: item.id,
          title: item.title || '继续分析',
          kind: 'deep_analysis',
          closable: true,
          source: item.source || 'draft',
          sessionId: item.sessionId || '',
        })),
        ...tabs.followupTabs.map((item) => ({
          id: item.id,
          title: item.title || '追问解释',
          kind: 'followup',
          closable: true,
          source: item.source || 'draft',
          sessionId: item.sessionId || '',
        })),
      ]
    },
    getAgentReportHomeTabId() {
      const tabs = this.ensureAgentTabs(false)
      const current = cloneArray(tabs.summaryTabs).find((item) => asText(item && item.source) === 'current')
      const first = current || cloneArray(tabs.summaryTabs)[0]
      return asText(first && first.id)
    },
    getAgentWorkspaceNavKicker() {
      const kind = asText(this.getAgentActiveTopTab().kind)
      if (kind === 'site_selection') return '区域报告 / 选址'
      if (kind === 'iteration_change') return '区域报告 / 变化'
      if (kind === 'deep_analysis') return '区域报告 / 继续分析'
      if (kind === 'followup') return '区域报告 / 追问'
      return 'Agent 工作台'
    },
    getAgentWorkspaceNavTitle() {
      const activeTab = this.getAgentActiveTopTab()
      const kind = asText(activeTab.kind)
      if (kind === 'site_selection') return '区域内选址'
      if (kind === 'iteration_change') return '多年变化'
      if (kind === 'deep_analysis') return '继续分析'
      if (kind === 'followup') return '追问解释'
      return '区域报告'
    },
    getAgentWorkspaceNavSubtitle() {
      const kind = asText(this.getAgentActiveTopTab().kind)
      if (kind === 'site_selection') return '从区域报告进入的开店位置判断'
      if (kind === 'iteration_change') return '从区域报告进入的时间变化分析'
      if (kind === 'deep_analysis') return '基于当前报告对象继续跑工具、生成新证据'
      if (kind === 'followup') return '围绕当前区域报告继续追问'
      if (this.hasAgentSummaryPack()) return '先看判断，再追问、查证据或继续做任务'
      return '先补齐证据并生成当前区域的智能报告'
    },
    isAgentReportDetailView() {
      return ['site_selection', 'iteration_change', 'deep_analysis', 'followup'].includes(asText(this.getAgentActiveTopTab().kind))
    },
    returnToAgentReportHome() {
      const tabId = this.getAgentReportHomeTabId()
      if (tabId) {
        this.switchAgentTopTab(tabId)
        return tabId
      }
      return this.createAgentSummaryTab({ title: '区域总结', reuseExisting: true })
    },
    openAgentSiteSelectionFromReport(options = {}) {
      this.agentWorkspaceView = 'report'
      const tabs = this.ensureAgentTabs(true)
      const existing = cloneArray(tabs.siteSelectionTabs).find((item) => asText(item && item.source) === 'current' || asText(item && item.source) === 'draft')
      if (existing && !options.forceNew) {
        this.switchAgentTopTab(existing.id)
        return existing.id
      }
      return this.createAgentSiteSelectionTab({ title: '区域内选址', source: 'current' })
    },
    openAgentIterationChangeFromReport(options = {}) {
      this.agentWorkspaceView = 'report'
      return this.createAgentIterationChangeTab({ reuseExisting: true, source: 'current', autoload: options.autoload !== false })
    },
    isAgentSummaryTabActive() {
      return asText(this.getAgentActiveTopTab().kind) === 'summary'
    },
    isAgentIterationChangeTabActive() {
      return asText(this.getAgentActiveTopTab().kind) === 'iteration_change'
    },
    isAgentSiteSelectionTabActive() {
      return asText(this.getAgentActiveTopTab().kind) === 'site_selection'
    },
    isAgentDeepAnalysisTabActive() {
      return asText(this.getAgentActiveTopTab().kind) === 'deep_analysis'
    },
    getAgentActiveFollowupTab() {
      const tabs = this.ensureAgentTabs(false)
      const activeId = asText(tabs.activeTabId)
      return tabs.followupTabs.find((item) => item.id === activeId) || null
    },
    captureAgentActiveFollowupTabState() {
      const tabs = this.ensureAgentTabs(true)
      if (asText(this.getAgentActiveTopTab().kind) !== 'followup') return
      const target = this.getAgentActiveFollowupTab()
      if (!target) return
      if (target.readonly) return
      target.thread = this.buildAgentFollowupThreadFromCurrentState()
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), iterationChangeTabs: cloneArray(tabs.iterationChangeTabs), siteSelectionTabs: cloneArray(tabs.siteSelectionTabs), deepAnalysisTabs: cloneArray(tabs.deepAnalysisTabs), followupTabs: cloneArray(tabs.followupTabs) }
    },
    captureAgentActiveSummaryTabState() {
      const tabs = this.ensureAgentTabs(true)
      const activeTab = this.getAgentActiveTopTab()
      if (asText(activeTab.kind) !== 'summary' || asText(activeTab.source) !== 'current') return
      const target = cloneArray(tabs.summaryTabs).find((item) => item.id === activeTab.id)
      if (!target || target.readonly) return
      const panelPayloads = {
        ...cloneObject(this.agentPanelPayloads),
        summary_task_board: this.buildSummaryTaskBoardUiState(),
      }
      const summaryPack = this.getAgentSummaryPack(panelPayloads)
      target.title = this.getAgentSummaryViewTitle(panelPayloads, target.title || '区域总结')
      target.panelPayloads = panelPayloads
      target.content = cloneObject(summaryPack)
      target.evidenceRefs = cloneArray(summaryPack.evidence_refs || [])
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), iterationChangeTabs: cloneArray(tabs.iterationChangeTabs), siteSelectionTabs: cloneArray(tabs.siteSelectionTabs), deepAnalysisTabs: cloneArray(tabs.deepAnalysisTabs), followupTabs: cloneArray(tabs.followupTabs) }
    },
    captureAgentActiveSiteSelectionTabState() {
      const tabs = this.ensureAgentTabs(true)
      const activeTab = this.getAgentActiveTopTab()
      if (asText(activeTab.kind) !== 'site_selection') return
      const target = cloneArray(tabs.siteSelectionTabs).find((item) => item.id === activeTab.id)
      if (!target || target.readonly) return
      target.panelPayloads = cloneObject(this.agentPanelPayloads)
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), iterationChangeTabs: cloneArray(tabs.iterationChangeTabs), siteSelectionTabs: cloneArray(tabs.siteSelectionTabs), deepAnalysisTabs: cloneArray(tabs.deepAnalysisTabs), followupTabs: cloneArray(tabs.followupTabs) }
    },
    getAgentActiveDeepAnalysisTab() {
      const tabs = this.ensureAgentTabs(false)
      const activeId = asText(tabs.activeTabId)
      return cloneArray(tabs.deepAnalysisTabs).find((item) => asText(item && item.id) === activeId) || null
    },
    captureAgentActiveDeepAnalysisTabState() {
      const tabs = this.ensureAgentTabs(true)
      const activeTab = this.getAgentActiveTopTab()
      if (asText(activeTab.kind) !== 'deep_analysis') return
      const target = cloneArray(tabs.deepAnalysisTabs).find((item) => item.id === activeTab.id)
      if (!target || target.readonly) return
      target.thread = this.buildAgentFollowupThreadFromCurrentState()
      target.question = asText(this.agentInput || target.question)
      target.mode = asText(this.agentComposerMode || this.agentDeepAnalysisMode || target.mode) || 'quick'
      target.panelPayloads = cloneObject(this.agentPanelPayloads)
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), iterationChangeTabs: cloneArray(tabs.iterationChangeTabs), siteSelectionTabs: cloneArray(tabs.siteSelectionTabs), deepAnalysisTabs: cloneArray(tabs.deepAnalysisTabs), followupTabs: cloneArray(tabs.followupTabs) }
    },
    switchAgentTopTab(tabId = '') {
      const nextId = asText(tabId)
      if (!nextId) return
      this.captureAgentActiveSummaryTabState()
      this.captureAgentActiveSiteSelectionTabState()
      this.captureAgentActiveDeepAnalysisTabState()
      this.captureAgentActiveFollowupTabState()
      const tabs = this.ensureAgentTabs(true)
      if (tabs.activeTabId === nextId) return
      tabs.activeTabId = nextId
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), iterationChangeTabs: cloneArray(tabs.iterationChangeTabs), siteSelectionTabs: cloneArray(tabs.siteSelectionTabs), deepAnalysisTabs: cloneArray(tabs.deepAnalysisTabs), followupTabs: cloneArray(tabs.followupTabs) }
      const targetSummary = cloneArray(tabs.summaryTabs).find((item) => item.id === nextId)
      if (targetSummary) {
        this.syncActiveAgentRuntimeView(this.activeAgentSessionId)
        if (asText(targetSummary.source) === 'current') {
          this.agentPanelPayloads = cloneObject(targetSummary.panelPayloads)
        }
        this.syncAgentSummaryStateFromPanelPayload(targetSummary.panelPayloads)
      } else if (tabs.iterationChangeTabs.some((item) => item.id === nextId)) {
        const target = tabs.iterationChangeTabs.find((item) => item.id === nextId)
        this.agentIterationActiveKind = asText(target && target.activeKind) || 'poi'
        this.syncActiveAgentRuntimeView(this.activeAgentSessionId)
        if (target && target.panelPayloads && typeof target.panelPayloads === 'object') {
          this.agentPanelPayloads = cloneObject(target.panelPayloads)
        }
      } else if (tabs.siteSelectionTabs.some((item) => item.id === nextId)) {
        const target = tabs.siteSelectionTabs.find((item) => item.id === nextId)
        this.syncActiveAgentRuntimeView(this.activeAgentSessionId)
        if (target && target.panelPayloads && typeof target.panelPayloads === 'object') {
          this.agentPanelPayloads = cloneObject(target.panelPayloads)
        }
      } else if (tabs.deepAnalysisTabs.some((item) => item.id === nextId)) {
        const target = tabs.deepAnalysisTabs.find((item) => item.id === nextId)
        this.applyAgentFollowupThreadToCurrentState(target && target.thread)
        this.agentDeepAnalysisMode = asText(target && target.mode) || 'quick'
        if (target && target.panelPayloads && typeof target.panelPayloads === 'object') {
          this.agentPanelPayloads = cloneObject(target.panelPayloads)
        }
        this.syncActiveAgentRuntimeView(this.activeAgentSessionId)
      } else {
        const target = tabs.followupTabs.find((item) => item.id === nextId)
        if (target) {
          this.applyAgentFollowupThreadToCurrentState(target.thread)
          this.syncActiveAgentRuntimeView(this.activeAgentSessionId)
        }
      }
      this.syncCurrentAgentSession()
      if (targetSummary && asText(targetSummary.source) === 'current') {
        this.syncSummaryTaskBoardFromLocalResults()
        this.refreshAgentSummaryReadiness(false)
      }
    },
    canCreateAgentFollowupTab() {
      const tabs = this.ensureAgentTabs(false)
      return tabs.followupTabs.length < Number(tabs.followupLimit || 6)
    },
    createAgentSummaryTab(options = {}) {
      const tabs = this.ensureAgentTabs(true)
      const panelPayloads = {
        ...cloneObject(this.agentPanelPayloads),
        summary_task_board: this.buildSummaryTaskBoardUiState(),
      }
      const summaryPack = this.getAgentSummaryPack(panelPayloads)
      const reuseExisting = !!options.reuseExisting
      const existing = reuseExisting
        ? cloneArray(tabs.summaryTabs).find((item) => asText(item.source) === 'current')
        : null
      const summaryTab = existing || {
        id: reuseExisting ? 'summary-current' : this.createAgentSummaryViewId(),
        kind: 'summary',
        source: 'current',
        sessionId: '',
        readonly: false,
        createdAt: new Date().toISOString(),
        panelPayloads,
        content: cloneObject(summaryPack),
        evidenceRefs: cloneArray(summaryPack.evidence_refs || []),
      }
      summaryTab.title = this.getAgentSummaryViewTitle(panelPayloads, options.title)
      summaryTab.panelPayloads = panelPayloads
      summaryTab.content = cloneObject(summaryPack)
      summaryTab.evidenceRefs = cloneArray(summaryPack.evidence_refs || [])
      if (!existing) {
        tabs.summaryTabs = [...cloneArray(tabs.summaryTabs), summaryTab]
      } else {
        tabs.summaryTabs = cloneArray(tabs.summaryTabs).map((item) => (item.id === existing.id ? summaryTab : item))
      }
      tabs.activeTabId = summaryTab.id
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), iterationChangeTabs: cloneArray(tabs.iterationChangeTabs), siteSelectionTabs: cloneArray(tabs.siteSelectionTabs), deepAnalysisTabs: cloneArray(tabs.deepAnalysisTabs), followupTabs: cloneArray(tabs.followupTabs) }
      this.syncActiveAgentRuntimeView(this.activeAgentSessionId)
      this.syncSummaryTaskBoardFromLocalResults()
      this.syncCurrentAgentSession()
      this.refreshAgentSummaryReadiness(false)
      return summaryTab.id
    },
    createAgentSiteSelectionTab(options = {}) {
      const tabs = this.ensureAgentTabs(true)
      this.captureAgentActiveSummaryTabState()
      this.captureAgentActiveDeepAnalysisTabState()
      this.captureAgentActiveFollowupTabState()
      const tabId = this.createAgentSiteSelectionViewId()
      const tab = {
        id: tabId,
        kind: 'site_selection',
        title: this.formatAgentTabTitle('site_selection', options.title),
        source: asText(options.source) || 'draft',
        sessionId: '',
        readonly: false,
        createdAt: new Date().toISOString(),
        panelPayloads: cloneObject(this.agentPanelPayloads),
      }
      tabs.siteSelectionTabs = [...cloneArray(tabs.siteSelectionTabs), tab]
      tabs.activeTabId = tabId
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), iterationChangeTabs: cloneArray(tabs.iterationChangeTabs), siteSelectionTabs: cloneArray(tabs.siteSelectionTabs), deepAnalysisTabs: cloneArray(tabs.deepAnalysisTabs), followupTabs: cloneArray(tabs.followupTabs) }
      this.syncActiveAgentRuntimeView(this.activeAgentSessionId)
      this.syncCurrentAgentSession()
      return tabId
    },
    createAgentIterationChangeTab(options = {}) {
      const tabs = this.ensureAgentTabs(true)
      this.captureAgentActiveSummaryTabState()
      this.captureAgentActiveDeepAnalysisTabState()
      this.captureAgentActiveFollowupTabState()
      const reuseExisting = !!options.reuseExisting
      const existing = reuseExisting
        ? cloneArray(tabs.iterationChangeTabs).find((item) => asText(item.source) === 'current')
        : null
      const tabId = existing ? existing.id : this.createAgentIterationChangeViewId()
      const tab = {
        ...(existing || {}),
        id: tabId,
        kind: 'iteration_change',
        title: this.formatAgentTabTitle('iteration_change'),
        source: asText(options.source) || 'current',
        sessionId: asText(options.sessionId),
        readonly: !!options.readonly,
        createdAt: asText(existing && existing.createdAt) || new Date().toISOString(),
        activeKind: asText(existing && existing.activeKind) || 'poi',
        panelPayloads: cloneObject(this.agentPanelPayloads),
      }
      if (existing) {
        tabs.iterationChangeTabs = cloneArray(tabs.iterationChangeTabs).map((item) => (item.id === existing.id ? tab : item))
      } else {
        tabs.iterationChangeTabs = [...cloneArray(tabs.iterationChangeTabs), tab]
      }
      tabs.activeTabId = tabId
      this.agentIterationActiveKind = tab.activeKind
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), iterationChangeTabs: cloneArray(tabs.iterationChangeTabs), siteSelectionTabs: cloneArray(tabs.siteSelectionTabs), deepAnalysisTabs: cloneArray(tabs.deepAnalysisTabs), followupTabs: cloneArray(tabs.followupTabs) }
      this.syncActiveAgentRuntimeView(this.activeAgentSessionId)
      this.syncCurrentAgentSession()
      if (options.autoload !== false) {
        this.ensureAgentIterationKind(tab.activeKind).catch((err) => {
          console.warn('Agent iteration load failed', err)
        })
      }
      return tabId
    },
    createAgentDeepAnalysisTab(options = {}) {
      const tabs = this.ensureAgentTabs(true)
      this.captureAgentActiveSummaryTabState()
      this.captureAgentActiveSiteSelectionTabState()
      this.captureAgentActiveFollowupTabState()
      const target = this.normalizeContextAskTarget(options.target)
      const question = asText(options.question)
      const titleSeed = asText(options.title || question || target.title)
      const tabId = this.createAgentDeepAnalysisViewId()
      const thread = this.createAgentFollowupThreadState({
        input: question,
      })
      const tab = {
        id: tabId,
        kind: 'deep_analysis',
        title: this.formatAgentTabTitle('deep_analysis', titleSeed),
        source: asText(options.source) || 'current',
        sessionId: asText(options.sessionId),
        readonly: !!options.readonly,
        createdAt: new Date().toISOString(),
        target,
        question,
        mode: asText(options.mode) || 'quick',
        thread,
        panelPayloads: cloneObject(this.agentPanelPayloads),
      }
      tabs.deepAnalysisTabs = [...cloneArray(tabs.deepAnalysisTabs), tab]
      tabs.activeTabId = tabId
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), iterationChangeTabs: cloneArray(tabs.iterationChangeTabs), siteSelectionTabs: cloneArray(tabs.siteSelectionTabs), deepAnalysisTabs: cloneArray(tabs.deepAnalysisTabs), followupTabs: cloneArray(tabs.followupTabs) }
      this.agentDeepAnalysisMode = tab.mode
      this.applyAgentFollowupThreadToCurrentState(thread)
      this.syncActiveAgentRuntimeView(this.activeAgentSessionId)
      this.syncCurrentAgentSession()
      return tabId
    },
    openAgentDeepAnalysisFromTarget(target = null, options = {}) {
      this.agentWorkspaceView = 'report'
      const normalizedTarget = this.normalizeContextAskTarget(target)
      if (!asText(this.activeAgentSessionId) && typeof this.createAgentSession === 'function') {
        const draft = this.createAgentSession('继续分析')
        this.updateAgentSessions([draft, ...cloneArray(this.agentSessions)], { loaded: this.agentSessionsLoaded })
        this.activeAgentSessionId = draft.id
      }
      return this.createAgentDeepAnalysisTab({
        target: normalizedTarget,
        title: options.title || normalizedTarget.title || '继续分析',
        question: options.question,
        mode: options.mode || 'quick',
        source: options.source || normalizedTarget.source || 'current',
      })
    },
    setAgentDeepAnalysisMode(mode = '') {
      const normalized = asText(mode) === 'deep' ? 'deep' : 'quick'
      this.agentDeepAnalysisMode = normalized
      const tabs = this.ensureAgentTabs(true)
      const activeTab = this.getAgentActiveTopTab()
      if (asText(activeTab.kind) === 'deep_analysis') {
        tabs.deepAnalysisTabs = cloneArray(tabs.deepAnalysisTabs).map((item) => (
          item.id === activeTab.id ? { ...item, mode: normalized } : item
        ))
        this.agentTabs = { ...tabs, deepAnalysisTabs: cloneArray(tabs.deepAnalysisTabs) }
        this.syncCurrentAgentSession()
      }
      return normalized
    },
    toggleAgentComposerMenu() {
      this.agentComposerMenuOpen = !this.agentComposerMenuOpen
    },
    closeAgentComposerMenu() {
      this.agentComposerMenuOpen = false
    },
    selectAgentComposerMode(mode = '') {
      const normalized = asText(mode) === 'deep' ? 'deep' : ''
      this.agentComposerMode = normalized
      this.agentDeepAnalysisMode = normalized === 'deep' ? 'deep' : 'quick'
      this.closeAgentComposerMenu()
      return normalized
    },
    clearAgentComposerMode() {
      this.agentComposerMode = ''
      this.agentDeepAnalysisMode = 'quick'
      this.closeAgentComposerMenu()
    },
    startAgentComposerNewReportSession() {
      this.clearAgentComposerMode()
      this.startNewAgentReportSession()
    },
    getAgentDeepAnalysisModeLabel(mode = '') {
      return asText(mode || this.agentDeepAnalysisMode) === 'deep' ? '深度思考' : '快速分析'
    },
    getAgentDeepAnalysisEvidencePreview(limit = 3) {
      const activeTab = this.getAgentActiveDeepAnalysisTab()
      const target = activeTab && activeTab.target && typeof activeTab.target === 'object'
        ? activeTab.target
        : {}
      return cloneArray(target.evidence)
        .slice(0, Math.max(1, Number(limit || 3)))
        .map((item) => {
          if (typeof item === 'string') return item
          try {
            return JSON.stringify(item)
          } catch (_) {
            return asText(item)
          }
        })
        .map((item) => clampText(item, 120))
        .filter(Boolean)
        .join('；')
    },
    buildAgentDeepAnalysisResultModule(seed = {}) {
      const activeTab = this.getAgentActiveDeepAnalysisTab()
      const target = this.normalizeContextAskTarget((seed && seed.target) || (activeTab && activeTab.target))
      const decision = cloneObject(seed.decision || this.agentDecision)
      const support = cloneArray(seed.support || this.agentSupport)
      const actions = cloneArray(seed.actions || this.agentActions)
      const counterpoints = cloneArray(seed.counterpoints || this.agentCounterpoints)
      const boundary = cloneArray(seed.boundary || this.agentBoundary)
      const question = asText(seed.question || (activeTab && activeTab.question) || this.agentInput || (this.agentMessages[0] && this.agentMessages[0].content))
      const titleSeed = asText(seed.title || decision.summary || question || target.title)
      return {
        id: asText(seed.id) || `deep-module-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`,
        type: 'deep_analysis',
        title: asText(seed.title) || this.formatAgentTabTitle('deep_analysis', titleSeed),
        mode: asText(seed.mode || this.agentDeepAnalysisMode) === 'deep' ? 'deep' : 'quick',
        source: target.source,
        target,
        question,
        conclusion: asText(seed.conclusion || decision.summary),
        strength: asText(decision.strength || 'weak') || 'weak',
        support,
        actions,
        counterpoints,
        boundary,
        evidence: cloneArray(seed.evidence || this.agentCitations || target.evidence),
        trace: cloneArray(seed.trace || this.agentExecutionTrace),
        createdAt: asText(seed.createdAt) || new Date().toISOString(),
      }
    },
    getAgentDeepAnalysisPreviewModule() {
      if (!this.hasAgentStructuredOutput()) return null
      return this.buildAgentDeepAnalysisResultModule()
    },
    getAgentSummaryDeepAnalysisModules(panelPayloads = null) {
      const pack = this.getAgentSummaryPack(panelPayloads)
      return cloneArray(pack.deep_analysis_modules || pack.deepAnalysisModules)
        .map((item) => this.buildAgentDeepAnalysisResultModule(item))
        .filter((item) => item.id && item.conclusion)
    },
    writeAgentDeepAnalysisModuleToReport(moduleSeed = null) {
      const module = this.buildAgentDeepAnalysisResultModule(moduleSeed || {})
      if (!module.conclusion) return null
      const tabs = this.ensureAgentTabs(true)
      const summaryTab = cloneArray(tabs.summaryTabs).find((item) => asText(item.source) === 'current') || tabs.summaryTabs[0]
      if (!summaryTab) return null
      const panelPayloads = cloneObject(summaryTab.panelPayloads || this.agentPanelPayloads)
      const summaryPack = this.getAgentSummaryPack(panelPayloads)
      const modules = cloneArray(summaryPack.deep_analysis_modules || summaryPack.deepAnalysisModules)
      const exists = modules.some((item) => asText(item && item.id) === module.id)
      const nextModules = exists
        ? modules.map((item) => (asText(item && item.id) === module.id ? module : item))
        : [...modules, module]
      const nextPack = {
        ...summaryPack,
        deep_analysis_modules: nextModules,
      }
      const nextPayloads = {
        ...panelPayloads,
        summary_pack: nextPack,
      }
      tabs.summaryTabs = cloneArray(tabs.summaryTabs).map((item) => (
        item.id === summaryTab.id
          ? { ...item, panelPayloads: nextPayloads, content: nextPack, evidenceRefs: cloneArray(nextPack.evidence_refs || item.evidenceRefs) }
          : item
      ))
      const activeDeepTab = this.getAgentActiveDeepAnalysisTab()
      if (activeDeepTab) {
        tabs.deepAnalysisTabs = cloneArray(tabs.deepAnalysisTabs).map((item) => (
          item.id === activeDeepTab.id ? { ...item, resultModuleId: module.id } : item
        ))
      }
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), deepAnalysisTabs: cloneArray(tabs.deepAnalysisTabs) }
      if (asText(this.getAgentActiveTopTab().kind) === 'summary' || asText(summaryTab.source) === 'current') {
        this.agentPanelPayloads = nextPayloads
        this.syncAgentSummaryStateFromPanelPayload(nextPayloads)
      }
      this.syncCurrentAgentSession()
      return module
    },
    startEditAgentDeepAnalysisModule(moduleSeed = null) {
      const module = this.buildAgentDeepAnalysisResultModule(moduleSeed || {})
      if (!module.id) return null
      this.agentEditingDeepModuleId = module.id
      this.agentEditingDeepModuleDraft = {
        title: asText(module.title),
        conclusion: asText(module.conclusion),
      }
      return module.id
    },
    cancelEditAgentDeepAnalysisModule() {
      this.agentEditingDeepModuleId = ''
      this.agentEditingDeepModuleDraft = { title: '', conclusion: '' }
    },
    saveAgentDeepAnalysisModuleEdit(moduleSeed = null) {
      const module = this.buildAgentDeepAnalysisResultModule(moduleSeed || {})
      const moduleId = asText(module.id || this.agentEditingDeepModuleId)
      if (!moduleId) return null
      const title = asText(this.agentEditingDeepModuleDraft && this.agentEditingDeepModuleDraft.title) || module.title
      const conclusion = asText(this.agentEditingDeepModuleDraft && this.agentEditingDeepModuleDraft.conclusion) || module.conclusion
      const tabs = this.ensureAgentTabs(true)
      const summaryTab = cloneArray(tabs.summaryTabs).find((item) => asText(item.source) === 'current') || tabs.summaryTabs[0]
      if (!summaryTab) return null
      const panelPayloads = cloneObject(summaryTab.panelPayloads || this.agentPanelPayloads)
      const summaryPack = this.getAgentSummaryPack(panelPayloads)
      const modules = cloneArray(summaryPack.deep_analysis_modules || summaryPack.deepAnalysisModules)
      const nextModules = modules.map((item) => (
        asText(item && item.id) === moduleId
          ? { ...cloneObject(item), title, conclusion }
          : item
      ))
      const nextPack = {
        ...summaryPack,
        deep_analysis_modules: nextModules,
      }
      const nextPayloads = {
        ...panelPayloads,
        summary_pack: nextPack,
      }
      tabs.summaryTabs = cloneArray(tabs.summaryTabs).map((item) => (
        item.id === summaryTab.id
          ? { ...item, panelPayloads: nextPayloads, content: nextPack, evidenceRefs: cloneArray(nextPack.evidence_refs || item.evidenceRefs) }
          : item
      ))
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs) }
      this.agentPanelPayloads = nextPayloads
      this.syncAgentSummaryStateFromPanelPayload(nextPayloads)
      this.cancelEditAgentDeepAnalysisModule()
      this.syncCurrentAgentSession()
      return this.buildAgentDeepAnalysisResultModule({ ...module, title, conclusion })
    },
    createAgentFollowupTab(options = {}) {
      const tabs = this.ensureAgentTabs(true)
      if (!this.canCreateAgentFollowupTab()) {
        window.alert(`最多可保留 ${tabs.followupLimit} 条追问解释，请先关闭旧追问。`)
        return null
      }
      this.captureAgentActiveFollowupTabState()
      const number = Number(tabs.nextFollowupNumber || (tabs.followupTabs.length + 1))
      const tabId = `followup-${number}`
      const seedPrompt = asText(options.seedPrompt)
      const thread = this.createAgentFollowupThreadState({
        input: seedPrompt,
      })
      const title = this.getAgentFollowupViewTitle({
        title: options.title,
        messages: seedPrompt ? [{ role: 'user', content: seedPrompt }] : [],
      }, options.title)
      tabs.followupTabs = [
        ...cloneArray(tabs.followupTabs),
        {
          id: tabId,
          kind: 'followup',
          title,
          linkedSummaryId: 'summary',
          source: asText(options.source) || 'draft',
          sessionId: asText(options.sessionId),
          readonly: !!options.readonly,
          createdAt: new Date().toISOString(),
          thread,
        },
      ]
      tabs.nextFollowupNumber = number + 1
      tabs.activeTabId = tabId
      this.agentTabs = tabs
      this.applyAgentFollowupThreadToCurrentState(thread)
      this.syncActiveAgentRuntimeView(this.activeAgentSessionId)
      this.syncCurrentAgentSession()
      return tabId
    },
    buildAgentHistorySummaryTab(session = null) {
      const sessionId = asText(session && session.id)
      const panelPayloads = cloneObject(session && session.panelPayloads)
      const pack = this.getAgentSummaryPack(panelPayloads)
      return {
        id: `summary-history-${sessionId}`,
        kind: 'summary',
        title: this.getAgentSummaryViewTitle(panelPayloads, session && session.title),
        source: 'history',
        sessionId,
        readonly: false,
        createdAt: new Date().toISOString(),
        panelPayloads,
        content: pack,
        evidenceRefs: cloneArray(pack.evidence_refs || []),
      }
    },
    buildAgentHistoryFollowupTab(session = null) {
      const sessionId = asText(session && session.id)
      return {
        id: `followup-history-${sessionId}`,
        kind: 'followup',
        title: this.getAgentFollowupViewTitle(session, session && session.title),
        linkedSummaryId: 'summary',
        source: 'history',
        sessionId,
        readonly: false,
        createdAt: new Date().toISOString(),
        thread: this.createAgentFollowupThreadState(session || {}),
      }
    },
    buildAgentHistoryDeepAnalysisTab(session = null) {
      const sessionId = asText(session && session.id)
      const panelPayloads = cloneObject(session && session.panelPayloads)
      const uiState = cloneObject(panelPayloads.agent_tabs)
      const savedTabs = cloneArray(uiState.deep_analysis_tabs || uiState.deepAnalysisTabs)
      const savedTab = savedTabs.find((item) => asText(item && (item.session_id || item.sessionId)) === sessionId) || savedTabs[0] || {}
      return {
        id: `deep-analysis-history-${sessionId}`,
        kind: 'deep_analysis',
        title: asText(savedTab.title) || this.formatAgentTabTitle('deep_analysis', session && session.title),
        source: 'history',
        sessionId,
        readonly: false,
        createdAt: new Date().toISOString(),
        target: this.normalizeContextAskTarget(savedTab.target),
        question: asText(savedTab.question || session && session.input),
        mode: asText(savedTab.mode) || 'quick',
        resultModuleId: asText(savedTab.result_module_id || savedTab.resultModuleId),
        thread: this.createAgentFollowupThreadState(session || savedTab.thread || {}),
        panelPayloads,
      }
    },
    openAgentSummaryHistoryTab(session = null) {
      if (!session || !asText(session.id)) return null
      const panelPayloads = cloneObject(session.panelPayloads)
      if (Object.keys(panelPayloads).length) {
        this.agentPanelPayloads = panelPayloads
        this.syncAgentSummaryStateFromPanelPayload(panelPayloads)
      }
      const tabs = this.ensureAgentTabs(true)
      const tab = this.buildAgentHistorySummaryTab(session)
      const existing = cloneArray(tabs.summaryTabs).find((item) => item.sessionId === tab.sessionId || item.id === tab.id)
      if (existing) {
        tabs.activeTabId = existing.id
      } else {
        tabs.summaryTabs = [...cloneArray(tabs.summaryTabs), tab]
        tabs.activeTabId = tab.id
      }
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), iterationChangeTabs: cloneArray(tabs.iterationChangeTabs), siteSelectionTabs: cloneArray(tabs.siteSelectionTabs), deepAnalysisTabs: cloneArray(tabs.deepAnalysisTabs), followupTabs: cloneArray(tabs.followupTabs) }
      this.syncActiveAgentRuntimeView(this.activeAgentSessionId)
      this.syncCurrentAgentSession()
      return tabs.activeTabId
    },
    openAgentFollowupHistoryTab(session = null) {
      if (!session || !asText(session.id)) return null
      const tabs = this.ensureAgentTabs(true)
      const tab = this.buildAgentHistoryFollowupTab(session)
      const existing = cloneArray(tabs.followupTabs).find((item) => item.sessionId === tab.sessionId || item.id === tab.id)
      if (existing) {
        tabs.activeTabId = existing.id
        this.applyAgentFollowupThreadToCurrentState(existing.thread)
      } else {
        tabs.followupTabs = [...cloneArray(tabs.followupTabs), tab]
        tabs.activeTabId = tab.id
        this.applyAgentFollowupThreadToCurrentState(tab.thread)
      }
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), iterationChangeTabs: cloneArray(tabs.iterationChangeTabs), siteSelectionTabs: cloneArray(tabs.siteSelectionTabs), deepAnalysisTabs: cloneArray(tabs.deepAnalysisTabs), followupTabs: cloneArray(tabs.followupTabs) }
      this.syncActiveAgentRuntimeView(this.activeAgentSessionId)
      this.syncCurrentAgentSession()
      return tabs.activeTabId
    },
    openAgentDeepAnalysisHistoryTab(session = null) {
      if (!session || !asText(session.id)) return null
      const tabs = this.ensureAgentTabs(true)
      const tab = this.buildAgentHistoryDeepAnalysisTab(session)
      const existing = cloneArray(tabs.deepAnalysisTabs).find((item) => item.sessionId === tab.sessionId || item.id === tab.id)
      if (existing) {
        tabs.activeTabId = existing.id
        this.applyAgentFollowupThreadToCurrentState(existing.thread)
      } else {
        tabs.deepAnalysisTabs = [...cloneArray(tabs.deepAnalysisTabs), tab]
        tabs.activeTabId = tab.id
        this.applyAgentFollowupThreadToCurrentState(tab.thread)
      }
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), iterationChangeTabs: cloneArray(tabs.iterationChangeTabs), siteSelectionTabs: cloneArray(tabs.siteSelectionTabs), deepAnalysisTabs: cloneArray(tabs.deepAnalysisTabs), followupTabs: cloneArray(tabs.followupTabs) }
      this.syncActiveAgentRuntimeView(this.activeAgentSessionId)
      this.syncCurrentAgentSession()
      return tabs.activeTabId
    },
    async openAgentHistorySessionTab(sessionId = '') {
      const nextId = asText(sessionId)
      if (!nextId) return null
      let session = this.findAgentSession(nextId)
      if (!session) return null
      if (session.persisted && !session.snapshotLoaded) {
        this.agentSessionDetailLoadingId = nextId
        try {
          session = await this.loadAgentSessionDetail(nextId)
        } finally {
          if (this.agentSessionDetailLoadingId === nextId) {
            this.agentSessionDetailLoadingId = ''
          }
        }
      }
      if (!session) return null
      if (!this.isAgentHistorySessionInCurrentRange(session)) return null
      this.agentWorkspaceView = 'report'
      if (this.isAgentSummaryHistorySession(session)) {
        this.applyAgentSessionSnapshot(session)
        return this.openAgentSummaryHistoryTab(session)
      }
      if (this.isAgentDeepAnalysisHistorySession(session)) {
        this.applyAgentSessionSnapshot(session)
        return this.openAgentDeepAnalysisHistoryTab(session)
      }
      return this.openAgentFollowupHistoryTab(session)
    },
    openAgentFollowupFromSummary(prompt = '', title = '追问解释') {
      const nextPrompt = asText(prompt)
      const tabId = this.createAgentFollowupTab({
        title,
        seedPrompt: nextPrompt,
      })
      if (!tabId) return
      if (nextPrompt) this.agentInput = nextPrompt
    },
    ensureAgentFollowupTabForPrompt(prompt = '') {
      if (asText(this.getAgentActiveTopTab().kind) === 'followup') return
      this.openAgentFollowupFromSummary(prompt || this.agentInput || '', '追问解释')
    },
    getAgentActiveSiteSelectionTab() {
      const tabs = this.ensureAgentTabs(false)
      const activeId = asText(tabs.activeTabId)
      return cloneArray(tabs.siteSelectionTabs).find((item) => asText(item && item.id) === activeId) || null
    },
    getAgentActiveSiteSelectionPayloads() {
      const activeTab = this.getAgentActiveSiteSelectionTab()
      if (activeTab && activeTab.panelPayloads && typeof activeTab.panelPayloads === 'object') {
        return cloneObject(activeTab.panelPayloads)
      }
      return cloneObject(this.agentPanelPayloads)
    },
    getAgentSiteSelectionState() {
      const payloads = this.getAgentActiveSiteSelectionPayloads()
      const state = payloads.site_selection_ui && typeof payloads.site_selection_ui === 'object'
        ? payloads.site_selection_ui
        : {}
      return {
        targetType: asText(state.target_type || state.targetType),
        status: asText(state.status || 'idle') || 'idle',
        error: asText(state.error),
        strategy: asText(state.strategy) || 'balanced',
        scenario: asText(state.scenario) || 'commuter',
        warnings: cloneArray(state.warnings).map((item) => asText(item)).filter(Boolean),
        selectedH3Id: asText(state.selected_h3_id || state.selectedH3Id),
        updatedAt: asText(state.updated_at || state.updatedAt),
      }
    },
    commitAgentSiteSelectionPayload(patch = {}) {
      const tabs = this.ensureAgentTabs(true)
      const activeId = asText(this.getAgentActiveTopTab().kind) === 'site_selection'
        ? asText(this.getAgentActiveTopTab().id)
        : asText(tabs.activeTabId)
      const targetTab = cloneArray(tabs.siteSelectionTabs).find((item) => item.id === activeId)
      const currentPayloads = targetTab && targetTab.panelPayloads && typeof targetTab.panelPayloads === 'object'
        ? cloneObject(targetTab.panelPayloads)
        : cloneObject(this.agentPanelPayloads)
      const currentUi = cloneObject(currentPayloads.site_selection_ui)
      const nextPayloads = {
        ...currentPayloads,
        ...cloneObject(patch.panelPayloads),
        site_selection_ui: {
          ...currentUi,
          ...cloneObject(patch.ui),
          updated_at: new Date().toISOString(),
        },
      }
      tabs.siteSelectionTabs = cloneArray(tabs.siteSelectionTabs).map((item) => (
        item.id === activeId ? { ...item, panelPayloads: cloneObject(nextPayloads) } : item
      ))
      this.agentTabs = { ...tabs, siteSelectionTabs: cloneArray(tabs.siteSelectionTabs) }
      if (asText(tabs.activeTabId) === activeId) {
        this.agentPanelPayloads = nextPayloads
      }
      this.syncCurrentAgentSession()
      return nextPayloads
    },
    inferAgentSiteSelectionTargetType() {
      const state = this.getAgentSiteSelectionState()
      if (state.targetType) return state.targetType
      const payloads = this.getAgentActiveSiteSelectionPayloads()
      const candidates = [
        payloads.site_selection_pack && payloads.site_selection_pack.place_type,
        payloads.current_target_supply_gap && payloads.current_target_supply_gap.place_type,
        payloads.current_poi_summary && payloads.current_poi_summary.keywords,
        payloads.current_poi_summary && payloads.current_poi_summary.types,
        this.agentInput,
      ]
      return asText(candidates.find((item) => asText(item))) || ''
    },
    setAgentSiteSelectionTargetType(value = '') {
      this.commitAgentSiteSelectionPayload({
        ui: {
          target_type: asText(value),
          error: '',
        },
      })
    },
    getAgentSiteSelectionStrategyOptions() {
      return [
        { value: 'balanced', label: '综合评估' },
        { value: 'supply_gap', label: '补供给缺口' },
        { value: 'traffic_vitality', label: '蹭流量活力' },
        { value: 'avoid_competition', label: '避开竞争' },
      ]
    },
    getAgentSiteSelectionScenarioOptions() {
      return [
        { value: 'commuter', label: '通勤快取' },
        { value: 'community', label: '社区日常' },
        { value: 'night_social', label: '夜间轻社交' },
        { value: 'student', label: '学生消费' },
        { value: 'family', label: '家庭亲子' },
      ]
    },
    setAgentSiteSelectionStrategy(value = '') {
      const options = this.getAgentSiteSelectionStrategyOptions()
      const next = options.some((item) => item.value === value) ? value : 'balanced'
      this.commitAgentSiteSelectionPayload({
        ui: {
          strategy: next,
          error: '',
        },
      })
    },
    setAgentSiteSelectionScenario(value = '') {
      const options = this.getAgentSiteSelectionScenarioOptions()
      const next = options.some((item) => item.value === value) ? value : 'commuter'
      this.commitAgentSiteSelectionPayload({
        ui: {
          scenario: next,
          error: '',
        },
      })
    },
    getAgentSiteSelectionPack() {
      const payloads = this.getAgentActiveSiteSelectionPayloads()
      const pack = payloads.site_selection_pack && typeof payloads.site_selection_pack === 'object'
        ? payloads.site_selection_pack
        : {}
      return cloneObject(pack)
    },
    hasAgentSiteSelectionPack() {
      const pack = this.getAgentSiteSelectionPack()
      return !!(
        cloneArray(pack.candidate_sites).length
        || cloneArray(pack.ranking).length
        || asText(pack.summary_text)
        || asText(pack.not_recommended_reason)
      )
    },
    isAgentSiteSelectionRunning() {
      const state = this.getAgentSiteSelectionState()
      return state.status === 'running'
    },
    getAgentSiteSelectionScopeInfo() {
      if (typeof this.normalizeAgentSiteSelectionScope === 'function') {
        return this.normalizeAgentSiteSelectionScope()
      }
      const polygon = (typeof this.getIsochronePolygonPayload === 'function') ? this.getIsochronePolygonPayload() : []
      const drawnPolygon = (typeof this.getDrawnScopePolygonPoints === 'function') ? this.getDrawnScopePolygonPoints() : []
      return {
        hasScope: (Array.isArray(polygon) && polygon.length > 0) || (Array.isArray(drawnPolygon) && drawnPolygon.length >= 4),
        polygon: Array.isArray(polygon) && polygon.length ? polygon : drawnPolygon,
        drawnPolygon,
        isochroneFeature: null,
      }
    },
    formatAgentSiteSelectionError(error = '') {
      const message = asText(error)
      const mapping = {
        missing_scope_polygon: '当前还没有可用分析范围。请先生成等时圈，或在地图上手绘一个范围后再分析。',
        missing_place_type: '请先输入目标业态，例如咖啡店、便利店或餐饮。',
        unresolved_place_type: '暂不支持这个业态名称。请换成咖啡店、便利店、餐饮、超市等更明确的类型。',
        site_selection_base_failed: '选址基础分析没有跑通，请确认范围、POI 数据源和年份后重试。',
      }
      return mapping[message] || message || '选址分析失败，请稍后重试。'
    },
    getAgentSiteSelectionReadinessItems() {
      const scopeInfo = this.getAgentSiteSelectionScopeInfo()
      const hasScope = !!(scopeInfo && scopeInfo.hasScope)
      return [
        { key: 'scope', label: '当前范围', ready: hasScope, detail: hasScope ? '已读取等时圈或手绘范围' : '请先生成等时圈或选择分析范围', required: true },
        { key: 'target', label: '目标业态', ready: !!this.inferAgentSiteSelectionTargetType(), detail: this.inferAgentSiteSelectionTargetType() || '请输入咖啡店、餐饮、便利店等目标', required: true },
      ]
    },
    getAgentSiteSelectionBlockingItems() {
      return this.getAgentSiteSelectionReadinessItems().filter((item) => item.required && !item.ready)
    },
    getAgentSiteSelectionTaskKeys() {
      return ['poi_fetch', 'poi_h3_grid', 'population', 'nightlight', 'road_syntax']
    },
    getAgentSiteSelectionTaskBoardTasks() {
      const keys = new Set(this.getAgentSiteSelectionTaskKeys())
      return this.getSummaryTaskBoardTasks().filter((task) => keys.has(asText(task && task.key)))
    },
    isAgentSiteSelectionDataReady() {
      const tasks = this.getAgentSiteSelectionTaskBoardTasks()
      if (!tasks.length) return false
      return tasks.every((task) => {
        const status = asText(task && task.status)
        return this.isSummaryTaskTerminalStatus(status) || this.summaryTaskHasReusableResult(task.key)
      })
    },
    isAgentSiteSelectionDataFillRunning() {
      return this.getAgentSiteSelectionTaskBoardTasks().some((task) => asText(task && task.status) === 'running')
    },
    getAgentSiteSelectionDataGateTitle() {
      if (this.isAgentSiteSelectionDataFillRunning()) return '正在补齐选址基础数据'
      return '先补齐选址基础数据'
    },
    getAgentSiteSelectionDataGateDescription() {
      return '完成 POI、H3、人口、夜光和路网抓取后，再进入正式选址分析。'
    },
    getAgentSiteSelectionDataGateProgressText() {
      const tasks = this.getAgentSiteSelectionTaskBoardTasks()
      const done = tasks.filter((task) => this.isSummaryTaskTerminalStatus(task.status) || this.summaryTaskHasReusableResult(task.key)).length
      return `${done}/${tasks.length || this.getAgentSiteSelectionTaskKeys().length} 项已就绪`
    },
    canRunAgentSiteSelectionDataFill() {
      return !this.isAgentSiteSelectionDataFillRunning() && !this.agentSummaryGenerating
    },
    async runAgentSiteSelectionDataFill() {
      if (!this.canRunAgentSiteSelectionDataFill()) return
      this.syncSummaryTaskBoardFromLocalResults()
      const requestedKeys = this.getAgentSiteSelectionTaskKeys()
      const keysToRun = this.filterSummaryTaskKeysForReuse(requestedKeys, { forcePoiFetch: false })
      const reusedKeys = requestedKeys.filter((key) => !keysToRun.includes(key))
      reusedKeys.forEach((key) => this.finalizeSummaryTaskAsReused(key))
      if (!keysToRun.length) {
        this.updateSummaryTaskBoard({
          ...this.ensureSummaryTaskBoard(false),
          runState: this.isAgentSiteSelectionDataReady() ? 'completed' : 'idle',
          lastRunAt: new Date().toISOString(),
        })
        this.agentSummaryError = ''
        return
      }
      this.updateSummaryTaskBoard({
        ...this.ensureSummaryTaskBoard(false),
        runState: 'running',
        lastRunAt: new Date().toISOString(),
      })
      const settled = await Promise.allSettled(keysToRun.map((key) => this.runSummaryTask(key, { source: 'site-selection' })))
      const hasFailed = settled.some((item) => item.status === 'rejected')
      if (hasFailed) {
        const first = settled.find((item) => item.status === 'rejected')
        const reason = first && first.reason
        this.agentSummaryError = reason && reason.message ? `补齐失败：${reason.message}` : '补齐失败，请查看任务日志'
      } else {
        this.agentSummaryError = ''
      }
      this.updateSummaryTaskBoard({
        ...this.ensureSummaryTaskBoard(false),
        runState: hasFailed ? 'failed' : 'completed',
      })
    },
    canRunAgentSiteSelection() {
      return !this.isAgentSiteSelectionRunning()
        && this.getAgentSiteSelectionBlockingItems().length === 0
        && this.isAgentSiteSelectionDataReady()
    },
    getAgentSiteSelectionSourceLabel() {
      const source = asText(this.resultDataSource || this.poiDataSource || 'local') || 'local'
      const year = Number(this.resultPoiYear || this.poiYearSource || 0) || null
      return year ? `${source} · ${year}` : source
    },
    getAgentSiteSelectionScopeStatus() {
      const item = this.getAgentSiteSelectionReadinessItems().find((entry) => entry.key === 'scope')
      return item || { ready: false, detail: '请先生成等时圈或选择分析范围' }
    },
    async generateAgentSiteSelection() {
      if (this.isAgentSiteSelectionRunning()) return
      if (!this.isAgentSiteSelectionTabActive()) {
        this.createAgentSiteSelectionTab({ title: '区域内选址' })
      }
      const targetType = this.inferAgentSiteSelectionTargetType()
      if (!targetType) {
        this.commitAgentSiteSelectionPayload({
          ui: {
            status: 'idle',
            error: '请先输入目标业态',
          },
        })
        return
      }
      const blocking = this.getAgentSiteSelectionBlockingItems()
      if (blocking.some((item) => item.key === 'scope')) {
        this.commitAgentSiteSelectionPayload({
          ui: {
            target_type: targetType,
            status: 'idle',
            error: this.formatAgentSiteSelectionError('missing_scope_polygon'),
          },
        })
        return
      }
      if (!this.isAgentSiteSelectionDataReady()) {
        this.commitAgentSiteSelectionPayload({
          ui: {
            target_type: targetType,
            status: 'idle',
            error: '请先补齐 POI、H3、人口、夜光和路网基础数据',
          },
        })
        return
      }
      const tabId = asText(this.getAgentActiveTopTab().id)
      const state = this.getAgentSiteSelectionState()
      const strategy = state.strategy || 'balanced'
      const scenario = state.scenario || 'commuter'
      this.commitAgentSiteSelectionPayload({
        ui: {
          target_type: targetType,
          strategy,
          scenario,
          status: 'running',
          error: '',
          warnings: [],
        },
      })
      try {
        const year = Number(this.resultPoiYear || this.poiYearSource || 0) || null
        const response = await fetch('/api/v1/analysis/agent/site-selection', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            conversation_id: this.getActiveAgentSessionId(),
            history_id: asText(this.getCurrentAgentHistoryId && this.getCurrentAgentHistoryId()),
            analysis_snapshot: this.buildAgentAnalysisSnapshot(),
            place_type: targetType,
            policy_key: 'business_catchment_1km',
            strategy,
            scenario,
            source: asText(this.resultDataSource || this.poiDataSource || 'local') || 'local',
            year,
          }),
        })
        let data = {}
        try {
          data = await response.json()
        } catch (jsonError) {
          data = {}
        }
        if (!response.ok || data.status === 'failed') {
          throw new Error(this.formatAgentSiteSelectionError(data.error || data.detail))
        }
        const pack = data.site_selection_pack && typeof data.site_selection_pack === 'object'
          ? data.site_selection_pack
          : {}
        const firstCandidate = cloneArray(pack.candidate_sites)[0] || {}
        const selectedH3Id = asText(firstCandidate.h3_id || firstCandidate.h3Id)
        const hasPackContent = !!Object.keys(pack).length
        this.switchAgentTopTab(tabId)
        this.commitAgentSiteSelectionPayload({
          panelPayloads: {
            site_selection_pack: pack,
            current_target_supply_gap: data.current_target_supply_gap || {},
            current_site_candidate_scores: data.current_site_candidate_scores || {},
          },
          ui: {
            target_type: targetType,
            strategy,
            scenario,
            selected_h3_id: selectedH3Id,
            status: hasPackContent ? 'ready' : 'empty',
            error: '',
            warnings: cloneArray(data.warnings).map((item) => asText(item)).filter(Boolean),
          },
        })
      } catch (error) {
        this.switchAgentTopTab(tabId)
        this.commitAgentSiteSelectionPayload({
          ui: {
            target_type: targetType,
            strategy,
            scenario,
            status: 'failed',
            error: this.formatAgentSiteSelectionError(error && error.message ? error.message : '选址分析失败'),
          },
        })
      }
    },
    getAgentSiteSelectionCandidates() {
      const pack = this.getAgentSiteSelectionPack()
      return cloneArray(pack.candidate_sites).slice(0, 5).map((item, index) => {
        const scoreParts = item && typeof item.scores === 'object' ? item.scores : {}
        const center = item && typeof item.center_point === 'object' ? item.center_point : {}
        const lng = Number(center.lng ?? center.longitude)
        const lat = Number(center.lat ?? center.latitude)
        const coordinate = Number.isFinite(lng) && Number.isFinite(lat) ? `${lng.toFixed(5)}, ${lat.toFixed(5)}` : ''
        return {
          rank: Number(item.rank || index + 1) || index + 1,
          h3Id: asText(item.h3_id || item.h3Id),
          title: asText(item.display_title || item.approx_address || item.label) || `候选${index + 1}`,
          approxAddress: asText(item.approx_address),
          coordinate,
          positioning: asText(item.positioning) || this.getAgentSiteSelectionFallbackPositioning(),
          totalScore: Number(item.total_score ?? item.totalScore ?? 0) || 0,
          gapScore: Number(item.gap_score ?? item.gapScore ?? scoreParts.supply_gap ?? 0) || 0,
          populationScore: Number(scoreParts.population_support ?? scoreParts.population ?? item.population_score ?? item.populationScore ?? 0) || 0,
          vitalityScore: Number(scoreParts.vitality ?? item.vitality_score ?? item.vitalityScore ?? 0) || 0,
          roadScore: Number(scoreParts.accessibility ?? scoreParts.road ?? item.road_score ?? item.roadScore ?? 0) || 0,
          reason: asText(item.reason_summary || item.reason || item.summary),
          whySuitable: cloneArray(item.why_suitable || item.whySuitable).map((entry) => asText(entry)).filter(Boolean),
          nextValidationSteps: cloneArray(item.next_validation_steps || item.nextValidationSteps).map((entry) => asText(entry)).filter(Boolean),
          strengths: cloneArray(item.strengths).map((entry) => asText(entry)).filter(Boolean),
          risks: cloneArray(item.risks).map((entry) => asText(entry)).filter(Boolean),
        }
      })
    },
    getAgentSiteSelectionFallbackPositioning() {
      const state = this.getAgentSiteSelectionState()
      const scenario = this.getAgentSiteSelectionScenarioOptions().find((item) => item.value === state.scenario)
      const strategy = this.getAgentSiteSelectionStrategyOptions().find((item) => item.value === state.strategy)
      const target = this.inferAgentSiteSelectionTargetType() || '门店'
      return `${scenario ? scenario.label : '通勤快取'}型${target} · ${strategy ? strategy.label : '综合评估'}`
    },
    getAgentSiteSelectionVerdict() {
      const pack = this.getAgentSiteSelectionPack()
      const verdict = asText(pack.overall_verdict || pack.overallVerdict)
      const labelMap = { suitable: '适合优先验证', cautious: '谨慎预筛', not_recommended: '暂不建议' }
      return {
        key: verdict || 'cautious',
        label: labelMap[verdict] || labelMap.cautious,
        text: asText(pack.verdict_text || pack.verdictText || pack.summary_text || pack.not_recommended_reason) || '当前结果适合作为区域内候选片区预筛。',
      }
    },
    getAgentSiteSelectionRankingRows() {
      return cloneArray(this.getAgentSiteSelectionPack().ranking).slice(0, 5).map((item, index) => ({
        rank: Number(item.rank || index + 1) || index + 1,
        title: asText(item.title) || `候选${index + 1}`,
        totalScore: Number(item.total_score ?? item.totalScore ?? 0) || 0,
      }))
    },
    getAgentSiteSelectionSelectedCandidate() {
      const candidates = this.getAgentSiteSelectionCandidates()
      const selectedH3Id = this.getAgentSiteSelectionState().selectedH3Id
      return candidates.find((item) => item.h3Id && item.h3Id === selectedH3Id) || candidates[0] || null
    },
    getAgentSiteSelectionSelectedWhySuitable() {
      const candidate = this.getAgentSiteSelectionSelectedCandidate()
      if (!candidate) return []
      const points = [...candidate.whySuitable, ...candidate.strengths]
      if (!points.length && candidate.reason) points.push(candidate.reason)
      return points.filter(Boolean).slice(0, 4)
    },
    getAgentSiteSelectionSelectedValidationSteps() {
      const candidate = this.getAgentSiteSelectionSelectedCandidate()
      if (!candidate) return []
      if (candidate.nextValidationSteps.length) return candidate.nextValidationSteps.slice(0, 5)
      return [
        '现场复核临街可见度、门面开口和动线方向',
        '观察早晚高峰人流与停留情况',
        '核对租金、面积和周边同类店经营状态',
      ]
    },
    getAgentSiteSelectionAvoidAreas() {
      const pack = this.getAgentSiteSelectionPack()
      return cloneArray(pack.avoid_areas || pack.avoidAreas).slice(0, 3).map((item, index) => ({
        rank: index + 1,
        h3Id: asText(item.h3_id || item.h3Id),
        title: asText(item.title || item.display_title || item.approx_address) || `不建议网格 ${index + 1}`,
        reason: asText(item.reason || item.not_recommended_reason) || '综合风险较高，暂不作为优先看点。',
        score: Number(item.score ?? item.total_score ?? 0) || 0,
      }))
    },
    getAgentSiteSelectionEvidenceChain() {
      return cloneArray(this.getAgentSiteSelectionPack().evidence_chain).map((item, index) => ({
        key: asText(item.tool_name || item.metric) || `evidence-${index}`,
        toolName: asText(item.tool_name) || '-',
        value: this.formatAgentSiteSelectionValue(item.value),
        reason: asText(item.rule_or_reason || item.reason),
        confidence: asText(item.confidence) || 'weak',
      }))
    },
    formatAgentSiteSelectionValue(value) {
      if (Array.isArray(value)) return value.length ? `${value.length} 项` : '无'
      if (value && typeof value === 'object') return Object.keys(value).length ? '已生成' : '无'
      return asText(value) || '无'
    },
    formatAgentSiteSelectionScore(value = 0) {
      const score = Number(value || 0)
      if (!Number.isFinite(score)) return '0'
      return score >= 10 ? score.toFixed(0) : score.toFixed(2)
    },
    getAgentSiteSelectionConfidenceLabel(value = '') {
      const key = asText(value)
      const mapping = { strong: '强', moderate: '中', weak: '弱' }
      return mapping[key] || key || '弱'
    },
    async onAgentSiteSelectionCandidateClick(candidate = null) {
      const h3Id = asText(candidate && (candidate.h3Id || candidate.h3_id))
      if (!h3Id) return
      this.commitAgentSiteSelectionPayload({
        ui: {
          selected_h3_id: h3Id,
          error: '',
        },
      })
      await this.onAgentCardItemClick({
        type: 'h3_candidate',
        h3_id: h3Id,
        text: asText(candidate && candidate.title) || '候选网格',
      })
    },
    getAgentIterationKinds() {
      return [
        { key: 'poi', label: 'POI', disabled: false },
        { key: 'population', label: '人口', disabled: false },
        { key: 'nightlight', label: '夜光', disabled: false },
      ]
    },
    getAgentIterationSecondaryView(kind = '') {
      const currentKind = asText(kind || this.agentIterationActiveKind) || 'poi'
      const view = cloneObject(this.agentIterationSecondaryView)
      const items = this.getAgentIterationSecondaryNavItems(currentKind)
      const saved = asText(view[currentKind])
      if (saved && items.some((item) => item.key === saved)) return saved
      const defaultItem = items[0] || {}
      return asText(defaultItem.key)
    },
    isAgentIterationSecondaryView(key = '', kind = '') {
      return this.getAgentIterationSecondaryView(kind) === asText(key)
    },
    setAgentIterationSecondaryView(key = '', kind = '') {
      const currentKind = asText(kind || this.agentIterationActiveKind) || 'poi'
      const target = asText(key)
      const items = this.getAgentIterationSecondaryNavItems(currentKind)
      if (!items.some((item) => item.key === target)) return
      this.agentIterationSecondaryView = {
        ...cloneObject(this.agentIterationSecondaryView),
        [currentKind]: target,
      }
    },
    getAgentIterationSelectedSecondaryItem(kind = '') {
      const currentKind = asText(kind || this.agentIterationActiveKind) || 'poi'
      const key = this.getAgentIterationSecondaryView(currentKind)
      return this.getAgentIterationSecondaryNavItems(currentKind).find((item) => item.key === key) || {}
    },
    getAgentIterationSecondaryPlaceholderTitle(kind = '') {
      const item = this.getAgentIterationSelectedSecondaryItem(kind)
      return `${asText(item.label) || '模块'}生成中`
    },
    shouldShowAgentIterationSecondaryPlaceholder(kind = '') {
      const currentKind = asText(kind || this.agentIterationActiveKind) || 'poi'
      const item = this.getAgentIterationSelectedSecondaryItem(currentKind)
      if (!asText(item.key)) return false
      if (currentKind === 'poi') {
        if (this.agentIterationPoiError || this.getAgentIterationPoiPayload().error) return false
        if (item.key === 'ai' && asText(this.getAgentIterationPoiPayload().status) === 'ready') return false
        return !item.available
      }
      if (currentKind === 'population') {
        if (this.agentIterationPopulationError || this.getAgentIterationPopulationPayload().error) return false
        return !item.available
      }
      if (this.agentIterationNightlightError || this.getAgentIterationNightlightPayload().error) return false
      return !item.available
    },
    getAgentIterationSecondaryNavItems() {
      const activeKind = asText(arguments[0] || this.agentIterationActiveKind) || 'poi'
      if (activeKind === 'poi') {
        const readiness = this.getAgentIterationPoiReadiness()
        const poiReady = asText(this.getAgentIterationPoiPayload().status) === 'ready' && readiness.ready
        const dataItem = { key: 'data', label: '数据补齐', available: true }
        if (!poiReady) return [dataItem]
        return [
          dataItem,
          { key: 'ai', label: '业态基础分析', available: poiReady },
          { key: 'metrics', label: '核心指标', available: poiReady },
          { key: 'trend', label: '趋势结构', available: this.getAgentIterationPoiTotalLineChart().length >= 2 },
          { key: 'space', label: '空间分布', available: this.getAgentIterationPoiAreaHeatmaps().length > 0 },
          { key: 'detail', label: '年度明细', available: this.getAgentIterationPoiSnapshotRows().length > 0 },
        ]
      }
      if (activeKind === 'population') {
        return [
          { key: 'metrics', label: '核心指标', available: asText(this.getAgentIterationPopulationPayload().status) === 'ready' },
        ]
      }
      return [
        { key: 'snapshots', label: '年度快照', available: cloneArray(this.getAgentIterationNightlightPayload().snapshots).length > 0 },
        { key: 'ai', label: 'AI解读', available: !!asText(this.getAgentIterationNightlightPayload().status) },
        { key: 'trend', label: '趋势指标', available: !!asText(this.getAgentIterationNightlightPayload().status) },
      ]
    },
    getAgentIterationPayload(kind = 'nightlight') {
      const payloads = cloneObject(this.agentPanelPayloads)
      const root = payloads.iteration_change && typeof payloads.iteration_change === 'object'
        ? payloads.iteration_change
        : {}
      return cloneObject(root[asText(kind) || 'nightlight'])
    },
    getAgentIterationNightlightPayload() {
      return this.getAgentIterationPayload('nightlight')
    },
    getAgentIterationPoiPayload() {
      return this.getAgentIterationPayload('poi')
    },
    getAgentIterationPopulationPayload() {
      return this.getAgentIterationPayload('population')
    },
    getAgentIterationActiveLoading() {
      if (this.agentIterationActiveKind === 'poi') return !!this.agentIterationPoiLoading
      if (this.agentIterationActiveKind === 'population') return !!this.agentIterationPopulationLoading
      return !!this.agentIterationNightlightLoading
    },
    getAgentIterationActiveLoadingText() {
      return this.getAgentIterationActiveLoading() ? '生成中' : '重新生成'
    },
    getAgentIterationActiveDescription() {
      if (this.agentIterationActiveKind === 'poi') return '历史 POI 特征与多年结构变化趋势'
      if (this.agentIterationActiveKind === 'population') return '人口变化的总结特征'
      return '近三年夜光快照与热点迁移趋势解析'
    },
    isAgentIterationPayloadEmpty(payload = null) {
      const status = asText(payload && payload.status)
      return !status || status === 'idle'
    },
    getAgentIterationEmptyNotice(kind = '') {
      const payload = this.getAgentIterationPayload(kind || this.agentIterationActiveKind)
      return asText(payload.notice) || '已切换历史记录，请重新生成多年迭代变化。'
    },
    getAgentIterationNightlightAnalysisRows() {
      const payload = this.getAgentIterationNightlightPayload()
      const analysis = cloneObject(payload.ai_analysis)
      return [
        { key: 'headline', label: '趋势判断', value: analysis.headline },
        { key: 'trend_summary', label: '总体变化', value: analysis.trend_summary },
        { key: 'hotspot_migration', label: '热点迁移', value: analysis.hotspot_migration },
        { key: 'risk_or_opportunity', label: '机会风险', value: analysis.risk_or_opportunity },
      ].filter((item) => asText(item.value))
    },
    formatAgentIterationMetric(value, digits = 2) {
      const number = Number(value)
      if (!Number.isFinite(number)) return '-'
      return number.toLocaleString('zh-CN', {
        maximumFractionDigits: digits,
        minimumFractionDigits: Math.min(1, digits),
      })
    },
    formatAgentIterationPercent(value) {
      const number = Number(value)
      if (!Number.isFinite(number)) return '-'
      return `${(number * 100).toFixed(1)}%`
    },
    formatAgentIterationSignedPercent(value) {
      const number = Number(value)
      if (!Number.isFinite(number)) return '-'
      return `${number >= 0 ? '+' : ''}${(number * 100).toFixed(1)}%`
    },
    getAgentIterationPopulationAgeGroupRatios(row = {}) {
      const groups = row && typeof row.age_group_ratios === 'object' ? row.age_group_ratios : {}
      const distribution = cloneArray(row && row.age_distribution)
      const total = Number(row && (row.total_population ?? row.population ?? 0)) || distribution.reduce((sum, item) => sum + (Number(item && item.total) || 0), 0)
      if (groups && Object.keys(groups).length) {
        return {
          child: Number(groups.child_0_14),
          working: Number(groups.working_15_64),
          senior: Number(groups.senior_65_plus),
        }
      }
      const sums = { child: 0, working: 0, senior: 0 }
      distribution.forEach((item) => {
        const key = asText(item && item.age_band)
        const start = key === '00' ? 0 : Number(key)
        const value = Number(item && item.total) || 0
        if (!Number.isFinite(start)) return
        if (start < 15) sums.child += value
        else if (start < 65) sums.working += value
        else sums.senior += value
      })
      if (!total) return { child: NaN, working: NaN, senior: NaN }
      return {
        child: sums.child / total,
        working: sums.working / total,
        senior: sums.senior / total,
      }
    },
    getAgentIterationPopulationFeatureRows() {
      const payload = this.getAgentIterationPopulationPayload()
      const series = cloneArray(payload.series || (payload.timeseries && payload.timeseries.series))
      const layerSummary = (((payload.timeseries || {}).layer || {}).summary) || {}
      const first = series[0] || {}
      const last = series[series.length - 1] || first
      const countDelta = Number(last.total_population ?? last.population ?? 0) - Number(first.total_population ?? first.population ?? 0)
      const densityDelta = Number(last.population_density ?? last.density ?? 0) - Number(first.population_density ?? first.density ?? 0)
      const maleTotal = Number(last.male_total)
      const femaleTotal = Number(last.female_total)
      const totalPopulation = Number(last.total_population ?? last.population ?? 0)
      const maleRatio = Number.isFinite(Number(last.male_ratio))
        ? Number(last.male_ratio)
        : (Number.isFinite(maleTotal) && Number.isFinite(femaleTotal) && (maleTotal + femaleTotal) > 0 ? maleTotal / (maleTotal + femaleTotal) : NaN)
      const femaleRatio = Number.isFinite(Number(last.female_ratio))
        ? Number(last.female_ratio)
        : (Number.isFinite(maleRatio) ? 1 - maleRatio : NaN)
      const sexDelta = Number.isFinite(maleTotal) && Number.isFinite(femaleTotal) ? maleTotal - femaleTotal : NaN
      const ageGroups = this.getAgentIterationPopulationAgeGroupRatios(last)
      const dominantAge = asText(last.top_age_band_label || last.dominant_age_band || last.top_age_band)
      const firstDominantAge = asText(first.top_age_band_label || first.dominant_age_band || first.top_age_band)
      const topAgeRatio = Number(last.top_age_band_ratio)
      const rows = [
        { key: 'period', label: '分析周期', value: asText(payload.period) || '-' },
        { key: 'cell_count', label: '格网数', value: Number.isFinite(Number(layerSummary.cell_count)) ? Math.round(Number(layerSummary.cell_count)) : '-' },
        { key: 'increase', label: '增长格网', value: Math.round(Number(layerSummary.increase_count || 0)) },
        { key: 'decrease', label: '下降格网', value: Math.round(Number(layerSummary.decrease_count || 0)) },
        { key: 'average_rate', label: '平均变化率', value: this.formatAgentIterationSignedPercent(layerSummary.average_rate) },
      ]
      if (series.length >= 2) {
        rows.push(
          { key: 'population_delta', label: '总人口首尾变化', value: this.formatAgentIterationMetric(countDelta, 0) },
          { key: 'density_delta', label: '平均密度首尾变化', value: this.formatAgentIterationMetric(densityDelta, 2) },
        )
      }
      rows.push(
        { key: 'male_total', label: '末年男性人口', value: Number.isFinite(maleTotal) ? this.formatAgentIterationMetric(maleTotal, 0) : '' },
        { key: 'female_total', label: '末年女性人口', value: Number.isFinite(femaleTotal) ? this.formatAgentIterationMetric(femaleTotal, 0) : '' },
        { key: 'male_ratio', label: '末年男性占比', value: Number.isFinite(maleRatio) ? this.formatAgentIterationPercent(maleRatio) : '' },
        { key: 'female_ratio', label: '末年女性占比', value: Number.isFinite(femaleRatio) ? this.formatAgentIterationPercent(femaleRatio) : '' },
        { key: 'sex_delta', label: '末年性别差（男-女）', value: Number.isFinite(sexDelta) ? this.formatAgentIterationMetric(sexDelta, 0) : '' },
        { key: 'dominant_age_band', label: '末年主年龄段', value: dominantAge },
        {
          key: 'dominant_age_shift',
          label: '主年龄段首尾变化',
          value: firstDominantAge && dominantAge ? `${firstDominantAge} -> ${dominantAge}` : '',
        },
        { key: 'top_age_band_ratio', label: '主年龄段占比', value: Number.isFinite(topAgeRatio) ? this.formatAgentIterationPercent(topAgeRatio) : '' },
        { key: 'child_ratio', label: '少儿人口占比(0-14)', value: Number.isFinite(ageGroups.child) ? this.formatAgentIterationPercent(ageGroups.child) : '' },
        { key: 'working_age_ratio', label: '劳动年龄占比(15-64)', value: Number.isFinite(ageGroups.working) ? this.formatAgentIterationPercent(ageGroups.working) : '' },
        { key: 'senior_ratio', label: '老年人口占比(65+)', value: Number.isFinite(ageGroups.senior) ? this.formatAgentIterationPercent(ageGroups.senior) : '' },
      )
      return rows.filter((item) => item.value !== undefined && item.value !== null && item.value !== '')
    },
    getAgentIterationNightlightTrendRows() {
      const payload = this.getAgentIterationNightlightPayload()
      const series = cloneArray(payload.series || (payload.timeseries && payload.timeseries.series))
      if (series.length < 2) return []
      const first = series[0] || {}
      const last = series[series.length - 1] || {}
      const delta = (key) => Number(last[key] || 0) - Number(first[key] || 0)
      return [
        { key: 'total_radiance', label: '总辐亮首尾变化', value: this.formatAgentIterationMetric(delta('total_radiance'), 1) },
        { key: 'mean_radiance', label: '平均辐亮首尾变化', value: this.formatAgentIterationMetric(delta('mean_radiance'), 2) },
        { key: 'p90_radiance', label: 'P90首尾变化', value: this.formatAgentIterationMetric(delta('p90_radiance'), 2) },
        { key: 'lit_pixel_ratio', label: '点亮占比首尾变化', value: this.formatAgentIterationPercent(delta('lit_pixel_ratio')) },
      ]
    },
    getAgentIterationNightlightHotspotRows() {
      const payload = this.getAgentIterationNightlightPayload()
      const counts = (((payload.timeseries || {}).layer || {}).summary || {}).class_counts || {}
      return [
        { key: 'hotspot_emerging', label: '新增热点', value: counts.hotspot_emerging },
        { key: 'hotspot_stable', label: '持续热点', value: counts.hotspot_stable },
        { key: 'hotspot_faded', label: '衰退热点', value: counts.hotspot_faded },
        { key: 'stable', label: '稳定格网', value: counts.stable },
      ].filter((item) => item.value !== undefined && item.value !== null)
    },
    getAgentIterationPoiFeatureRows() {
      const payload = this.getAgentIterationPoiPayload()
      const summaries = cloneArray(payload.summaries)
      const latest = summaries[summaries.length - 1] || {}
      const topSubcategory = (cloneArray(latest.top_subcategories)[0] || {})
      return [
        { key: 'year', label: '特征年份', value: latest.year || asText(payload.year) || '-' },
        { key: 'total', label: 'POI 数量', value: this.formatAgentIterationMetric(latest.count, 0) },
        { key: 'category_count', label: '业态类型数', value: this.formatAgentIterationMetric(latest.category_count, 0) },
        { key: 'top_category', label: '第一业态', value: ((latest.top_categories || [])[0] || {}).name || '-' },
        { key: 'top_category_count', label: '第一业态数量', value: this.formatAgentIterationMetric((((latest.top_categories || [])[0] || {}).count), 0) },
        { key: 'subcategory_count', label: '小类类型数', value: this.formatAgentIterationMetric(latest.subcategory_count, 0) },
        { key: 'top_subcategory', label: '第一小类', value: topSubcategory.name || '-' },
        { key: 'top_subcategory_parent', label: '第一小类所属大类', value: topSubcategory.parent || '-' },
        { key: 'top_area', label: '主要行政区', value: ((latest.top_areas || [])[0] || {}).name || '-' },
      ].filter((item) => item.value !== undefined && item.value !== null && item.value !== '')
    },
    getAgentIterationPoiTrendRows() {
      const payload = this.getAgentIterationPoiPayload()
      return cloneArray(payload.trend_rows)
        .concat(cloneArray(payload.subcategory_trend_rows))
        .filter((item) => asText(item.label) && item.value !== undefined && item.value !== null)
    },
    getAgentIterationPoiTargetYears() {
      const historyYears = cloneArray(this.currentHistoryAvailablePoiYears)
        .map((item) => Number(item))
        .filter((item) => Number.isFinite(item))
      const selected = cloneArray(this.poiYearSelections)
        .map((item) => Number(item))
        .filter((item) => Number.isFinite(item))
      if (this.agentIterationPoiYearSelectionTouched && selected.length >= 2) {
        return Array.from(new Set(selected)).sort((a, b) => a - b)
      }
      if (historyYears.length >= 2) return Array.from(new Set(historyYears)).sort((a, b) => a - b)
      if (selected.length >= 2) return Array.from(new Set(selected)).sort((a, b) => a - b)
      return [2020, 2022, 2024]
    },
    getAgentIterationPoiYearlyGridEvidence() {
      const payload = this.getAgentIterationPoiPayload()
      const evidence = payload.yearly_grid_evidence && typeof payload.yearly_grid_evidence === 'object'
        ? payload.yearly_grid_evidence
        : {}
      return cloneObject(evidence)
    },
    getAgentIterationPoiReadiness() {
      const years = this.getAgentIterationPoiTargetYears()
      const historyYears = cloneArray(this.currentHistoryAvailablePoiYears)
        .map((item) => Number(item))
        .filter((item) => Number.isFinite(item))
      const hasReadableHistory = !!asText(this.currentHistoryRecordId)
      const hasMultiYearPoi = hasReadableHistory && historyYears.length >= 2
      const yearly = this.getAgentIterationPoiYearlyGridEvidence()
      const readyH3Years = new Set(cloneArray(yearly.h3_items || yearly.items)
        .filter((item) => asText(item && item.status || 'ready') === 'ready')
        .map((item) => Number(item && item.year))
        .filter((item) => Number.isFinite(item)))
      const hasYearlyH3Grid = years.length >= 2 && years.every((year) => readyH3Years.has(Number(year)))
      const missingTasks = []
      if (!hasMultiYearPoi) missingTasks.push('poi_fetch')
      if (!hasYearlyH3Grid) missingTasks.push('poi_h3_grid')
      return {
        checked: true,
        ready: missingTasks.length === 0,
        missingTasks,
        reused: [
          hasMultiYearPoi ? 'poi_fetch' : '',
          hasYearlyH3Grid ? 'poi_h3_grid' : '',
        ].filter(Boolean),
        fetched: [],
        years,
      }
    },
    getAgentIterationPoiTaskBoardTasks() {
      const readiness = this.getAgentIterationPoiReadiness()
      const board = this.getAgentIterationPoiPayload().task_board || {}
      const taskMap = new Map(cloneArray(board.tasks).map((item) => [asText(item && item.key), item]))
      return ['poi_fetch', 'poi_h3_grid'].map((key) => {
        const existing = cloneObject(taskMap.get(key))
        const isMissing = readiness.missingTasks.includes(key)
        const isReused = readiness.reused.includes(key)
        const status = asText(existing.status) === 'running' || asText(existing.status) === 'failed'
          ? asText(existing.status)
          : (isMissing ? 'pending' : (isReused ? 'reused' : 'completed'))
        return {
          key,
          label: this.getAgentSummaryTaskLabel(key),
          status,
          error: asText(existing.error),
          startedAt: asText(existing.startedAt),
          endedAt: asText(existing.endedAt),
        }
      })
    },
    getAgentIterationPoiTaskKeysToFill() {
      return this.getAgentIterationPoiReadiness().missingTasks
    },
    isAgentIterationPoiTaskBoardRunning() {
      return this.getAgentIterationPoiTaskBoardTasks().some((task) => task.status === 'running')
    },
    getAgentIterationPoiPrimaryActionLabel() {
      if (this.isAgentIterationPoiTaskBoardRunning()) return '补齐中'
      return this.getAgentIterationPoiTaskKeysToFill().length ? '补齐缺失' : '重新抓取/重算'
    },
    getAgentIterationPoiDataCompletionYears() {
      return this.getAgentIterationPoiTargetYears()
    },
    getAgentIterationPoiYearOptionRows() {
      const optionMap = new Map()
      cloneArray(typeof this.getPoiMultiYearOptions === 'function' ? this.getPoiMultiYearOptions() : [])
        .forEach((item) => {
          const year = Number(item && item.value)
          if (Number.isFinite(year)) optionMap.set(year, { year, label: asText(item.label) || `${year}` })
        })
      cloneArray(this.currentHistoryAvailablePoiYears)
        .map((item) => Number(item))
        .filter((item) => Number.isFinite(item))
        .forEach((year) => {
          if (!optionMap.has(year)) optionMap.set(year, { year, label: `${year} 本地` })
        })
      this.getAgentIterationPoiTargetYears().forEach((year) => {
        if (!optionMap.has(year)) optionMap.set(year, { year, label: `${year}` })
      })
      const selectedYears = new Set(this.getAgentIterationPoiTargetYears().map((year) => Number(year)))
      const availableYears = new Set(cloneArray(this.currentHistoryAvailablePoiYears)
        .map((item) => Number(item))
        .filter((item) => Number.isFinite(item)))
      return Array.from(optionMap.values())
        .sort((a, b) => Number(a.year) - Number(b.year))
        .map((item) => ({
          ...item,
          selected: selectedYears.has(Number(item.year)),
          fetched: availableYears.has(Number(item.year)),
        }))
    },
    toggleAgentIterationPoiYearSelection(year, checked) {
      this.agentIterationPoiYearSelectionTouched = true
      if (typeof this.togglePoiYearSelection === 'function') {
        this.togglePoiYearSelection(year, checked)
      } else {
        const value = Number(year)
        if (!Number.isFinite(value)) return
        const next = new Set(this.getAgentIterationPoiTargetYears())
        if (checked) next.add(value)
        else if (next.size > 1) next.delete(value)
        this.poiYearSelections = Array.from(next).sort((a, b) => a - b)
      }
      this.commitAgentIterationPoiPayload({
        status: 'needs_data',
        yearly_grid_evidence: {},
        h3_evidence: {},
      })
    },
    getAgentIterationPoiYearStatusLabel(status = '') {
      const value = asText(status)
      if (value === 'ready' || value === 'completed' || value === 'reused') return '已完成'
      if (value === 'running') return '运行中'
      if (value === 'queued') return '排队中'
      if (value === 'failed') return '失败'
      return '缺失'
    },
    getAgentIterationPoiFetchYearRows() {
      const years = this.getAgentIterationPoiDataCompletionYears()
      const availableYears = new Set(cloneArray(this.currentHistoryAvailablePoiYears)
        .map((item) => Number(item))
        .filter((item) => Number.isFinite(item)))
      const task = this.getAgentIterationPoiTaskBoardTasks().find((item) => item.key === 'poi_fetch') || {}
      const taskStatus = asText(task.status)
      return years.map((year) => {
        const hasYear = availableYears.has(Number(year))
        const status = taskStatus === 'running'
          ? 'running'
          : (taskStatus === 'failed' && !hasYear ? 'failed' : (hasYear ? 'ready' : 'missing'))
        return {
          year,
          status,
          label: this.getAgentIterationPoiYearStatusLabel(status),
          source: hasYear ? '历史 POI 快照' : '待抓取',
          reuse: hasYear ? '可复用' : '未复用',
          error: status === 'failed' ? asText(task.error) : '',
        }
      })
    },
    getAgentIterationPoiGridYearRows() {
      const years = this.getAgentIterationPoiDataCompletionYears()
      const yearly = this.getAgentIterationPoiYearlyGridEvidence()
      const itemMap = new Map(cloneArray(yearly.items).map((item) => [Number(item && item.year), cloneObject(item)]))
      const task = this.getAgentIterationPoiTaskBoardTasks().find((item) => item.key === 'poi_h3_grid') || {}
      const taskStatus = asText(task.status)
      const stageLabelMap = {
        queued: '排队中',
        build_grid: '生成网格中',
        aggregate_poi: '聚合 POI 中',
        compute_metrics: '计算指标中',
        arcgis_prepare: '准备 ArcGIS 中',
        arcgis_running: 'ArcGIS 热点分析中',
        finalize: '整理结果中',
        completed: '已完成',
        failed: '失败',
      }
      return years.map((year) => {
        const item = itemMap.get(Number(year)) || {}
        const itemStatus = asText(item.status)
        const progress = cloneObject(item.progress || {})
        const stage = asText(progress.stage || '')
        const hasH3 = !!Object.keys(cloneObject(item.h3_evidence)).length
        const status = itemStatus === 'running'
          ? 'running'
          : (itemStatus === 'failed'
            ? 'failed'
            : (itemStatus === 'ready' || hasH3
              ? 'ready'
              : (taskStatus === 'running' ? 'queued' : 'missing')))
        const total = Number(progress.total || 0) || 7
        const step = Math.max(0, Math.min(total, Number(progress.step || 0) || 0))
        const elapsedSec = Math.max(0, Math.floor(Number(progress.elapsed_sec || 0) || 0))
        const extra = cloneObject(progress.extra || {})
        const gridCount = Number(extra.grid_count || (((item.h3_evidence || {}).summary || {}).grid_count) || 0) || 0
        const poiCount = Number(extra.poi_count || (((item.h3_evidence || {}).summary || {}).poi_count) || 0) || 0
        return {
          year,
          status,
          label: this.getAgentIterationPoiYearStatusLabel(status),
          stageLabel: stageLabelMap[stage] || (status === 'ready' ? '已完成' : (status === 'failed' ? '失败' : (status === 'running' ? '运行中' : '缺失'))),
          detailLabel: status === 'running'
            ? `${step}/${total} · ${elapsedSec}s${gridCount ? ` · ${gridCount}格` : ''}${poiCount ? ` · ${poiCount}POI` : ''}`
            : (status === 'ready'
              ? `${gridCount || Number((((item.h3_evidence || {}).summary || {}).grid_count) || 0) || 0}格 · ${poiCount || Number((((item.h3_evidence || {}).summary || {}).poi_count) || 0) || 0}POI`
              : ''),
          resolution: (((item.h3_evidence || {}).params || {}).h3_resolution) || this.h3GridResolution || '-',
          scope: asText(item.grid_scope || yearly.grid_scope) || 'poi_iteration_h3_per_year',
          error: asText(item.error) || (status === 'failed' ? asText(task.error) : ''),
          runId: asText(item.run_id),
          progress,
        }
      })
    },
    getAgentIterationPoiGridReadyCount() {
      return this.getAgentIterationPoiGridYearRows()
        .filter((row) => asText(row && row.status) === 'ready')
        .length
    },
    getAgentIterationPoiGridErrorRows() {
      return this.getAgentIterationPoiGridYearRows()
        .filter((row) => !!asText(row && row.error))
    },
    getAgentIterationPoiRasterGridYearRows() {
      const years = this.getAgentIterationPoiDataCompletionYears()
      const yearly = this.getAgentIterationPoiYearlyGridEvidence()
      const itemMap = new Map(cloneArray(yearly.raster_items).map((item) => [Number(item && item.year), cloneObject(item)]))
      const task = this.getAgentIterationPoiTaskBoardTasks().find((item) => item.key === 'poi_raster_grid') || {}
      const taskStatus = asText(task.status)
      return years.map((year) => {
        const item = itemMap.get(Number(year)) || {}
        const itemStatus = asText(item.status)
        const hasRaster = !!Object.keys(cloneObject(item.raster_evidence)).length
        const status = itemStatus === 'running'
          ? 'running'
          : (itemStatus === 'failed'
            ? 'failed'
            : (itemStatus === 'ready' || hasRaster
              ? 'ready'
              : (taskStatus === 'running' ? 'queued' : 'missing')))
        return {
          year,
          status,
          label: this.getAgentIterationPoiYearStatusLabel(status),
          resolution: 'cell_id',
          scope: asText(item.grid_scope || yearly.raster_grid_scope) || 'poi_iteration_raster_per_year',
          error: asText(item.error) || (status === 'failed' ? asText(task.error) : ''),
        }
      })
    },
    getAgentIterationPoiRasterGridReadyCount() {
      return this.getAgentIterationPoiRasterGridYearRows()
        .filter((row) => asText(row && row.status) === 'ready')
        .length
    },
    getAgentIterationPoiRasterGridErrorRows() {
      return this.getAgentIterationPoiRasterGridYearRows()
        .filter((row) => !!asText(row && row.error))
    },
    getAgentIterationPoiLatestH3YearLabel() {
      const yearly = this.getAgentIterationPoiYearlyGridEvidence()
      return yearly.latest_year ? `${yearly.latest_year}` : '-'
    },
    getAgentIterationPoiAiSummaryRows() {
      const payload = this.getAgentIterationPoiPayload()
      const rows = cloneArray(payload.ai_summary).map((item) => asText(item)).filter(Boolean)
      if (rows.length) return rows
      return []
    },
    getAgentIterationPoiReportSections() {
      const payload = this.getAgentIterationPoiPayload()
      const sections = cloneArray(payload.report_sections).map((item, idx) => {
        const heading = asText(item && item.heading) || `章节${idx + 1}`
        const paragraphs = cloneArray(item && item.paragraphs).map((paragraph) => asText(paragraph)).filter(Boolean)
        return { key: `report-section-${idx}`, heading, paragraphs }
      }).filter((item) => item.paragraphs.length)
      if (sections.length) return sections
      const content = asText(payload.report_content)
      if (!content) return []
      return [{
        key: 'report-content',
        heading: asText(payload.report_title) || '业态基础分析总结报告',
        paragraphs: content.split(/\n{2,}/).map((item) => asText(item)).filter(Boolean),
      }]
    },
    hasAgentIterationPoiReport() {
      return !!(this.getAgentIterationPoiReportSections().length || asText(this.getAgentIterationPoiPayload().report_content))
    },
    isAgentIterationAiTimeout(error = '') {
      return /ai_timeout/i.test(asText(error))
    },
    getAgentIterationPoiAiStatusText() {
      const payload = this.getAgentIterationPoiPayload()
      if (this.hasAgentIterationPoiReport()) return ''
      if (asText(payload.ai_status) === 'loading') return '基础统计已完成，AI 深度解读正在生成。'
      if (this.isAgentIterationAiTimeout(payload.ai_error)) return '基础统计和快照已完成，AI 深度解读仍在补充。'
      if (payload.ai_error) return this.getAgentIterationAiErrorLabel(payload.ai_error)
      return '基础统计已完成，等待 AI 深度解读。'
    },
    shouldShowAgentIterationPoiAiPlaceholder() {
      const payload = this.getAgentIterationPoiPayload()
      return asText(payload.status) === 'ready'
        && !cloneArray(payload.ai_summary).length
        && !this.hasAgentIterationPoiReport()
        && !asText(payload.ai_error)
    },
    getAgentIterationPoiAiInsightRows() {
      const payload = this.getAgentIterationPoiPayload()
      const insights = cloneObject(payload.ai_insights)
      const pickInsightValue = (key) => insights[key] || ''
      const normalizeGrowthAreaValue = (value) => {
        const text = formatInsightValue(value)
        if (!text) return ''
        const hasOldAreaTerm = text.includes('新兴区域') || text.includes('新兴片区')
        if (!hasOldAreaTerm) return text
        return text.replaceAll('新兴区域', '增长片区').replaceAll('新兴片区', '增长片区')
      }
      const formatInsightValue = (value) => {
        if (value && typeof value === 'object' && !Array.isArray(value)) {
          const name = asText(value.name || value.area_signal || value.current_structure)
          const category = asText(value.category)
          const subcategory = asText(value.subcategory)
          const area = asText(value.area || value.region || value.direction || value.ring)
          const delta = value.delta ?? value.change ?? ''
          const count = value.count ?? ''
          const evidence = asText(value.evidence || value.reason)
          const interpretation = asText(value.interpretation || value.trend)
          const parts = []
          if (name) parts.push(`判断：${name}`)
          if (category) parts.push(`大类：${category}`)
          if (subcategory) parts.push(`小类：${subcategory}${category && !subcategory.includes(category) ? `（${category}）` : ''}`)
          if (area) parts.push(`区域：${area}`)
          if (delta !== '') parts.push(`变化：${delta}`)
          if (count !== '') parts.push(`数量：${count}`)
          if (evidence) parts.push(`证据：${evidence}`)
          if (interpretation) parts.push(`解读：${interpretation}`)
          return parts.join('；') || JSON.stringify(value)
        }
        if (Array.isArray(value)) return value.map((item) => formatInsightValue(item)).filter(Boolean).join('；')
        return asText(value)
      }
      return [
        { key: 'fastest_growth', label: '增长最快行业', value: formatInsightValue(pickInsightValue('fastest_growth')) },
        { key: 'declining_category', label: '衰退行业', value: formatInsightValue(pickInsightValue('declining_category')) },
        { key: 'emerging_area', label: '增长片区', value: normalizeGrowthAreaValue(pickInsightValue('emerging_area')) },
        { key: 'structure_judgement', label: '结构判断', value: formatInsightValue(pickInsightValue('structure_judgement')) },
      ].filter((item) => item.value)
    },
    getAgentIterationPoiDriverRows() {
      const payload = this.getAgentIterationPoiPayload()
      const rows = cloneArray(payload.driver_analysis).length
        ? cloneArray(payload.driver_analysis)
        : cloneArray(cloneObject(payload.ai_insights).driver_analysis)
      return rows.map((row, idx) => ({
        key: `driver-${idx}`,
        label: asText(row.driver) || `原因${idx + 1}`,
        value: [
          asText(row.evidence) ? `证据：${asText(row.evidence)}` : '',
          asText(row.confidence) ? `置信度：${asText(row.confidence)}` : '',
          asText(row.explanation),
        ].filter(Boolean).join('；'),
      })).filter((row) => row.value)
    },
    getAgentIterationPoiPlanningRows() {
      const payload = this.getAgentIterationPoiPayload()
      const rows = cloneArray(payload.planning_implications).length
        ? cloneArray(payload.planning_implications)
        : cloneArray(cloneObject(payload.ai_insights).planning_implications)
      return rows.map((row, idx) => ({
        key: `planning-${idx}`,
        label: asText(row.implication) || `启示${idx + 1}`,
        value: [
          asText(row.evidence) ? `依据：${asText(row.evidence)}` : '',
          asText(row.suggested_direction) ? `方向：${asText(row.suggested_direction)}` : '',
        ].filter(Boolean).join('；'),
      })).filter((row) => row.value)
    },
    shouldShowAgentIterationPoiInsightPlaceholder() {
      const payload = this.getAgentIterationPoiPayload()
      return asText(payload.status) === 'ready'
        && ['pending', 'loading'].includes(asText(payload.ai_status))
        && !this.getAgentIterationPoiAiInsightRows().length
        && !asText(payload.ai_error)
    },
    isAgentIterationPoiSpatialSignalLoading() {
      const payload = this.getAgentIterationPoiPayload()
      const aiStatus = asText(payload.ai_status)
      return asText(payload.status) === 'ready'
        && ['pending', 'loading'].includes(aiStatus)
        && !cloneArray(payload.subcategory_spatial_trend_rows).length
        && !asText(payload.ai_error)
    },
    getAgentIterationPoiSpatialTrendRows(limit = undefined) {
      const rows = cloneArray(this.getAgentIterationPoiPayload().subcategory_spatial_trend_rows)
        .map((row) => ({
          name: asText(row.name),
          parent: asText(row.parent),
          delta: Number(row.delta || 0),
          dominantDirection: asText(row.dominant_direction),
          secondaryDirection: asText(row.secondary_direction),
          dominantRing: asText(row.dominant_ring),
          centroidShiftDirection: asText(row.centroid_shift_direction),
          centroidShiftM: Number(row.centroid_shift_m || 0),
          hotspotGridCount: Number(row.hotspot_grid_count || 0),
          hotspotGridCountDelta: Number(row.hotspot_grid_count_delta || 0),
          hotspotPattern: asText(row.hotspot_pattern),
          topArea: asText(row.top_area),
        }))
        .filter((row) => row.name)
      const safeLimit = Number(limit)
      return Number.isFinite(safeLimit) && safeLimit > 0 ? rows.slice(0, safeLimit) : rows
    },
    formatAgentIterationPoiSpatialTrend(row = {}) {
      const delta = Number(row.delta || 0)
      const pieces = []
      if (row.dominantDirection) {
        pieces.push(`主导方位 ${row.dominantDirection}${row.secondaryDirection ? `/${row.secondaryDirection}` : ''}`)
      }
      if (row.dominantRing) pieces.push(`圈层 ${row.dominantRing}`)
      if (row.centroidShiftDirection && Number(row.centroidShiftM || 0) > 0) {
        pieces.push(`重心向${row.centroidShiftDirection}移动 ${this.formatAgentIterationMetric(row.centroidShiftM, 0)}米`)
      }
      if (Number.isFinite(Number(row.hotspotGridCount))) {
        const hotspotDelta = Number(row.hotspotGridCountDelta || 0)
        pieces.push(`热点格 ${this.formatAgentIterationMetric(row.hotspotGridCount, 0)}个${hotspotDelta ? `（${hotspotDelta > 0 ? '+' : ''}${hotspotDelta}）` : ''}`)
      }
      if (row.topArea) pieces.push(`主要区域 ${row.topArea}`)
      return `${delta >= 0 ? '+' : ''}${delta}；${pieces.join('；') || '空间变化信号有限'}`
    },
    getAgentIterationPoiSnapshotRows() {
      return cloneArray(this.getAgentIterationPoiPayload().summaries)
    },
    getAgentIterationPoiTotalLineChart() {
      const payload = this.getAgentIterationPoiPayload()
      const series = cloneArray(payload.total_series)
      if (series.length >= 2) return series
      return cloneArray(payload.summaries)
        .filter((item) => item && item.year !== undefined && item.count !== undefined)
        .map((item) => ({ year: item.year, value: Number(item.count || 0) }))
    },
    getAgentIterationPoiCategoryStackChart() {
      return cloneArray(this.getAgentIterationPoiPayload().category_stack)
    },
    getAgentIterationPoiSubcategoryStackChart() {
      return cloneArray(this.getAgentIterationPoiPayload().subcategory_stack)
    },
    getAgentIterationPoiSubcategoryGroups() {
      const payload = this.getAgentIterationPoiPayload()
      const summaries = cloneArray(payload.summaries)
      const latest = summaries[summaries.length - 1] || {}
      const latestTotal = Math.max(1, Number(latest.count || 0))
      const categoryCounts = cloneObject(latest.category_counts)
      const mix = cloneObject(latest.category_to_subcategory_mix)
      const groupMap = new Map()
      Object.entries(mix).forEach(([category, rows]) => {
        const items = cloneArray(rows)
          .map((item) => ({
            name: asText(item.name),
            parent: asText(item.parent || category),
            count: Number(item.count || 0),
            ratio: Number(item.count || 0) / latestTotal,
          }))
          .filter((item) => item.name)
          .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, 'zh-CN'))
        if (items.length) {
          const total = Number(categoryCounts[category] || 0) || items.reduce((sum, item) => sum + Number(item.count || 0), 0)
          groupMap.set(category, { category, total, subcategoryCount: items.length, items })
        }
      })
      if (!groupMap.size) {
        cloneArray(latest.top_subcategories).forEach((item) => {
          const category = asText(item.parent) || '未分类'
          if (!groupMap.has(category)) groupMap.set(category, { category, total: 0, subcategoryCount: 0, items: [] })
          const group = groupMap.get(category)
          const count = Number(item.count || 0)
          group.total += count
          group.items.push({
            name: asText(item.name),
            parent: category,
            count,
            ratio: Number(item.ratio || 0) || count / latestTotal,
          })
          group.subcategoryCount = group.items.length
        })
      }
      return Array.from(groupMap.values())
        .map((group) => ({
          ...group,
          items: cloneArray(group.items).sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, 'zh-CN')),
        }))
        .sort((a, b) => Number(b.total || 0) - Number(a.total || 0) || a.category.localeCompare(b.category, 'zh-CN'))
    },
    getAgentIterationPoiSubcategoryTotal() {
      const payload = this.getAgentIterationPoiPayload()
      const summaries = cloneArray(payload.summaries)
      const latest = summaries[summaries.length - 1] || {}
      const count = Number(latest.subcategory_count)
      if (Number.isFinite(count) && count >= 0) return count
      return this.getAgentIterationPoiSubcategoryGroups().reduce((sum, group) => sum + cloneArray(group.items).length, 0)
    },
    getAgentIterationPoiTopSubcategoryRows(limit = undefined) {
      const payload = this.getAgentIterationPoiPayload()
      const summaries = cloneArray(payload.summaries)
      const latest = summaries[summaries.length - 1] || {}
      const rows = cloneArray(latest.top_subcategories)
      const safeLimit = Number(limit)
      return Number.isFinite(safeLimit) && safeLimit > 0 ? rows.slice(0, safeLimit) : rows
    },
    getAgentIterationPoiStructureSpatialCategories() {
      return this.getAgentIterationPoiSubcategoryGroups()
        .map((group) => ({ category: asText(group.category), total: Number(group.total || 0), subcategoryCount: Number(group.subcategoryCount || 0) }))
        .filter((item) => item.category)
    },
    getAgentIterationPoiStructureSpatialRows() {
      const trendMap = new Map(this.getAgentIterationPoiSpatialTrendRows().map((row) => [row.name, row]))
      const rowMap = new Map()
      this.getAgentIterationPoiSubcategoryGroups().forEach((group) => {
        cloneArray(group.items).forEach((item) => {
          const name = asText(item.name)
          if (!name) return
          const trend = trendMap.get(name) || {}
          const hasSpatialSignal = Boolean(trendMap.has(name))
          rowMap.set(name, {
            name,
            parent: asText(item.parent || group.category || trend.parent) || '未分类',
            count: Number(item.count || 0),
            ratio: Number(item.ratio || 0),
            delta: Number(trend.delta || 0),
            dominantDirection: asText(trend.dominantDirection),
            secondaryDirection: asText(trend.secondaryDirection),
            dominantRing: asText(trend.dominantRing),
            centroidShiftDirection: asText(trend.centroidShiftDirection),
            centroidShiftM: Number(trend.centroidShiftM || 0),
            hotspotGridCount: Number(trend.hotspotGridCount || 0),
            hotspotGridCountDelta: Number(trend.hotspotGridCountDelta || 0),
            hotspotPattern: asText(trend.hotspotPattern),
            topArea: asText(trend.topArea),
            hasSpatialSignal,
          })
        })
      })
      this.getAgentIterationPoiSpatialTrendRows().forEach((trend) => {
        if (rowMap.has(trend.name)) return
        rowMap.set(trend.name, {
          name: trend.name,
          parent: asText(trend.parent) || '未分类',
          count: 0,
          ratio: 0,
          delta: Number(trend.delta || 0),
          dominantDirection: asText(trend.dominantDirection),
          secondaryDirection: asText(trend.secondaryDirection),
          dominantRing: asText(trend.dominantRing),
          centroidShiftDirection: asText(trend.centroidShiftDirection),
          centroidShiftM: Number(trend.centroidShiftM || 0),
          hotspotGridCount: Number(trend.hotspotGridCount || 0),
          hotspotGridCountDelta: Number(trend.hotspotGridCountDelta || 0),
          hotspotPattern: asText(trend.hotspotPattern),
          topArea: asText(trend.topArea),
          hasSpatialSignal: true,
        })
      })
      return Array.from(rowMap.values())
    },
    getAgentIterationPoiStructureSpatialGroups() {
      const state = cloneObject(this.agentIterationPoiStructureSpatialView)
      const category = asText(state.category)
      const sortBy = asText(state.sortBy) || 'count'
      const spatialOnly = Boolean(state.spatialOnly)
      const compare = (a, b) => {
        if (sortBy === 'ratio') return Number(b.ratio || 0) - Number(a.ratio || 0) || Number(b.count || 0) - Number(a.count || 0)
        if (sortBy === 'abs_delta') return Math.abs(Number(b.delta || 0)) - Math.abs(Number(a.delta || 0)) || Number(b.count || 0) - Number(a.count || 0)
        if (sortBy === 'growth') return Number(b.delta || 0) - Number(a.delta || 0) || Number(b.count || 0) - Number(a.count || 0)
        if (sortBy === 'decrease') return Number(a.delta || 0) - Number(b.delta || 0) || Number(b.count || 0) - Number(a.count || 0)
        return Number(b.count || 0) - Number(a.count || 0) || Number(b.ratio || 0) - Number(a.ratio || 0)
      }
      const groups = new Map()
      this.getAgentIterationPoiStructureSpatialRows()
        .filter((row) => (!category || row.parent === category) && (!spatialOnly || row.hasSpatialSignal))
        .sort((a, b) => compare(a, b) || a.name.localeCompare(b.name, 'zh-CN'))
        .forEach((row) => {
          const parent = asText(row.parent) || '未分类'
          if (!groups.has(parent)) groups.set(parent, { category: parent, total: 0, subcategoryCount: 0, rows: [] })
          const group = groups.get(parent)
          group.total += Number(row.count || 0)
          group.rows.push(row)
          group.subcategoryCount = group.rows.length
        })
      return Array.from(groups.values())
        .sort((a, b) => Number(b.total || 0) - Number(a.total || 0) || a.category.localeCompare(b.category, 'zh-CN'))
    },
    getAgentIterationPoiAreaHeatmapCalibratedPayload() {
      return this.getAgentIterationPoiPayload()
    },
    setAgentIterationPoiStructureSpatialViewPatch(patch = {}) {
      const current = cloneObject(this.agentIterationPoiStructureSpatialView)
      const next = { ...current, ...cloneObject(patch) }
      const validSorts = new Set(['count', 'ratio', 'abs_delta', 'growth', 'decrease'])
      const categories = this.getAgentIterationPoiStructureSpatialCategories().map((item) => item.category)
      this.agentIterationPoiStructureSpatialView = {
        category: categories.includes(asText(next.category)) ? asText(next.category) : '',
        sortBy: validSorts.has(asText(next.sortBy)) ? asText(next.sortBy) : 'count',
        spatialOnly: Boolean(next.spatialOnly),
      }
      return this.agentIterationPoiStructureSpatialView
    },
    getAgentIterationPoiAreaHeatmaps() {
      const rows = cloneArray(this.getAgentIterationPoiAreaHeatmapCalibratedPayload().area_heatmaps)
        .filter((row) => row && asText(row.year))
        .sort((a, b) => Number(a.year || 0) - Number(b.year || 0))
      if (!rows.length) return []
      const counts = rows.map((row) => Number(row.point_count || cloneArray(row.points).length || 0))
      const minCount = Math.min(...counts)
      const maxCount = Math.max(...counts)
      const span = Math.max(1, maxCount - minCount)
      let previous = null
      const firstCount = counts[0] || 0
      return rows.map((row, index) => {
        const count = Number(row.point_count || cloneArray(row.points).length || 0)
        const delta = previous ? count - Number(previous.point_count || cloneArray(previous.points).length || 0) : 0
        const ratio = previous && Number(previous.point_count || 0)
          ? delta / Math.max(1, Number(previous.point_count || 0))
          : 0
        previous = row
        return {
          ...row,
          cells: cloneArray(row.cells),
          points: cloneArray(row.points),
          point_count: count,
          delta_from_previous: delta,
          delta_from_first: count - firstCount,
          delta_ratio_from_previous: ratio,
          is_first_year: index === 0,
          count_level: (count - minCount) / span,
        }
      })
    },
    getAgentIterationPoiAreaHeatmapChangeSummary() {
      const rows = this.getAgentIterationPoiAreaHeatmaps()
      if (rows.length < 2) return '展示当前区域全部 POI 的年度空间分布。'
      const first = rows[0]
      const last = rows[rows.length - 1]
      const deltas = rows.slice(1).map((row) => Number(row.delta_from_previous || 0))
      const totalDelta = Number(last.point_count || 0) - Number(first.point_count || 0)
      const trend = deltas.every((delta) => delta > 0)
        ? '持续增长'
        : deltas.every((delta) => delta < 0)
          ? '持续下降'
          : (deltas[0] < 0 && deltas[deltas.length - 1] > 0 ? '先降后回升' : '波动变化')
      return `${first.year}-${last.year} 全部 POI ${trend}，净变化 ${this.formatAgentIterationPoiAreaHeatmapDelta(totalDelta)}。`
    },
    formatAgentIterationPoiAreaHeatmapDelta(value = 0) {
      const number = Number(value || 0)
      if (!Number.isFinite(number) || number === 0) return '持平'
      return `${number > 0 ? '+' : ''}${this.formatAgentIterationMetric(number, 0)}`
    },
    getAgentIterationPoiAreaHeatmapDeltaStateClass(value = 0) {
      const number = Number(value || 0)
      return {
        'is-positive': number > 0,
        'is-negative': number < 0,
        'is-flat': !number,
      }
    },
    getAgentIterationPoiAreaHeatmapHotspotCount(heatmap = {}) {
      return cloneArray(heatmap.cells).length
    },
    isAgentIterationPoiAreaHeatmapCopying(heatmap = {}) {
      return asText(this.agentIterationSnapshotCopyKey) === `poi-area-${asText(heatmap.year)}`
        && /正在复制/.test(asText(this.agentIterationSnapshotCopyStatus))
    },
    isAgentIterationPoiAreaHeatmapCopied(heatmap = {}) {
      return asText(this.agentIterationSnapshotCopyKey) === `poi-area-${asText(heatmap.year)}`
        && /已复制/.test(asText(this.agentIterationSnapshotCopyStatus))
    },
    isAgentIterationPoiAreaHeatmapCopyFailed(heatmap = {}) {
      return asText(this.agentIterationSnapshotCopyKey) === `poi-area-${asText(heatmap.year)}`
        && /失败/.test(asText(this.agentIterationSnapshotCopyStatus))
    },
    getAgentIterationPoiAreaHeatmapCopyLabel(heatmap = {}) {
      if (this.isAgentIterationPoiAreaHeatmapCopying(heatmap)) return '复制中'
      if (this.isAgentIterationPoiAreaHeatmapCopied(heatmap)) return '已复制'
      if (this.isAgentIterationPoiAreaHeatmapCopyFailed(heatmap)) return '复制失败'
      return '点击复制'
    },
    getAgentIterationPoiAreaHeatmapLayerState() {
      const layers = cloneObject(this.agentIterationPoiAreaHeatmapLayers)
      const mode = asText(layers.mode)
      if (mode === 'cells' || mode === 'points') {
        return {
          cells: mode === 'cells',
          points: mode === 'points',
        }
      }
      if (Boolean(layers.cells) && !Boolean(layers.points)) {
        return { cells: true, points: false }
      }
      return {
        cells: false,
        points: true,
      }
    },
    isAgentIterationPoiAreaHeatmapLayerVisible(layer = '') {
      const key = asText(layer)
      const layers = this.getAgentIterationPoiAreaHeatmapLayerState()
      if (!Object.prototype.hasOwnProperty.call(layers, key)) return true
      return Boolean(layers[key])
    },
    getAgentIterationPoiAreaHeatmapLayerLabel(layer = '') {
      const key = asText(layer)
      if (key === 'cells') return '格网'
      if (key === 'points') return '点位'
      return key || '图层'
    },
    toggleAgentIterationPoiAreaHeatmapLayer(layer = '', event = null) {
      if (event && typeof event.preventDefault === 'function') event.preventDefault()
      if (event && typeof event.stopPropagation === 'function') event.stopPropagation()
      const key = asText(layer)
      if (!['cells', 'points'].includes(key)) return this.getAgentIterationPoiAreaHeatmapLayerState()
      this.agentIterationPoiAreaHeatmapLayers = {
        mode: key,
        cells: key === 'cells',
        points: key === 'points',
      }
      return this.agentIterationPoiAreaHeatmapLayers
    },
    getAgentIterationPoiAreaHeatmapBasemap() {
      return cloneObject(this.getAgentIterationPoiAreaHeatmapCalibratedPayload().area_heatmap_basemap)
    },
    hasAgentIterationPoiAreaHeatmapBasemapImage() {
      const basemap = this.getAgentIterationPoiAreaHeatmapBasemap()
      return !!asText(basemap.url)
    },
    getAgentIterationPoiAreaHeatmapViewSize() {
      const basemap = this.getAgentIterationPoiAreaHeatmapBasemap()
      const view = cloneObject(basemap.view)
      const width = Number(view.width || 0)
      const height = Number(view.height || 0)
      if (Number.isFinite(width) && width > 0 && Number.isFinite(height) && height > 0) {
        return { width, height }
      }
      const parts = asText(basemap.view_box).split(/\s+/).map((part) => Number(part)).filter((part) => Number.isFinite(part))
      if (parts.length >= 4 && parts[2] > 0 && parts[3] > 0) {
        return { width: parts[2], height: parts[3] }
      }
      return { width: 100, height: 100 }
    },
    getAgentIterationPoiAreaHeatmapViewBox() {
      const basemap = this.getAgentIterationPoiAreaHeatmapBasemap()
      const viewBox = asText(basemap.view_box)
      if (viewBox) return viewBox
      const size = this.getAgentIterationPoiAreaHeatmapViewSize()
      return `0 0 ${size.width} ${size.height}`
    },
    getAgentIterationPoiAreaHeatmapSvgAttrs() {
      return {
        viewBox: this.getAgentIterationPoiAreaHeatmapViewBox(),
      }
    },
    getAgentIterationPoiAreaHeatmapAspectStyle() {
      const basemap = this.getAgentIterationPoiAreaHeatmapBasemap()
      const aspectRatio = asText(basemap.aspect_ratio)
      if (aspectRatio) return { aspectRatio }
      const size = this.getAgentIterationPoiAreaHeatmapViewSize()
      return { aspectRatio: `${size.width} / ${size.height}` }
    },
    getAgentIterationPoiAreaHeatmapBoundary() {
      return cloneArray(this.getAgentIterationPoiAreaHeatmapCalibratedPayload().area_heatmap_boundary)
    },
    getAgentIterationPoiAreaHeatmapFittedViewBox() {
      const boundary = this.getAgentIterationPoiAreaHeatmapBoundary()
        .map((point) => ({ x: Number(point && point.x), y: Number(point && point.y) }))
        .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y))
      if (boundary.length < 2) {
        const basemap = this.getAgentIterationPoiAreaHeatmapBasemap()
        return asText(basemap.view_box)
      }
      const xs = boundary.map((point) => point.x)
      const ys = boundary.map((point) => point.y)
      const minX = Math.min(...xs)
      const maxX = Math.max(...xs)
      const minY = Math.min(...ys)
      const maxY = Math.max(...ys)
      const width = Math.max(maxX - minX, 1e-6)
      const height = Math.max(maxY - minY, 1e-6)
      const pad = Math.max(width, height) * 0.08
      return [
        Number((minX - pad).toFixed(3)),
        Number((minY - pad).toFixed(3)),
        Number((width + pad * 2).toFixed(3)),
        Number((height + pad * 2).toFixed(3)),
      ].join(' ')
    },
    getAgentIterationPoiAreaHeatmapBoundaryBox() {
      const boundary = this.getAgentIterationPoiAreaHeatmapBoundary()
        .map((point) => ({ x: Number(point && point.x), y: Number(point && point.y) }))
        .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y))
      if (boundary.length < 2) return null
      const xs = boundary.map((point) => point.x)
      const ys = boundary.map((point) => point.y)
      const minX = Math.min(...xs)
      const maxX = Math.max(...xs)
      const minY = Math.min(...ys)
      const maxY = Math.max(...ys)
      return {
        minX,
        maxX,
        minY,
        maxY,
        width: Math.max(maxX - minX, 1e-6),
        height: Math.max(maxY - minY, 1e-6),
      }
    },
    getAgentIterationPoiAreaHeatmapDisplayFrame() {
      return this.getAgentIterationPoiAreaHeatmapViewSize()
    },
    getAgentIterationPoiAreaHeatmapDisplayTransform() {
      if (this.hasAgentIterationPoiAreaHeatmapBasemapImage()) return null
      const box = this.getAgentIterationPoiAreaHeatmapBoundaryBox()
      if (!box) return null
      const frame = this.getAgentIterationPoiAreaHeatmapDisplayFrame()
      const frameWidth = Math.max(1, Number(frame.width || 100))
      const frameHeight = Math.max(1, Number(frame.height || 100))
      const fillRatio = 0.88
      const scale = Math.min(
        Math.max(1e-6, frameWidth * fillRatio) / box.width,
        Math.max(1e-6, frameHeight * fillRatio) / box.height,
      )
      const fittedWidth = box.width * scale
      const fittedHeight = box.height * scale
      return {
        minX: box.minX,
        minY: box.minY,
        scale,
        offsetX: (frameWidth - fittedWidth) / 2,
        offsetY: (frameHeight - fittedHeight) / 2,
      }
    },
    projectAgentIterationPoiAreaHeatmapDisplayPoint(point = {}, transform = null) {
      const x = Number(point && point.x)
      const y = Number(point && point.y)
      if (!Number.isFinite(x) || !Number.isFinite(y)) return { x: 0, y: 0 }
      if (!transform) return { x, y }
      return {
        x: Number((Number(transform.offsetX || 0) + (x - Number(transform.minX || 0)) * Number(transform.scale || 1)).toFixed(3)),
        y: Number((Number(transform.offsetY || 0) + (y - Number(transform.minY || 0)) * Number(transform.scale || 1)).toFixed(3)),
      }
    },
    getAgentIterationPoiAreaHeatmapDisplayBoundary() {
      const transform = this.getAgentIterationPoiAreaHeatmapDisplayTransform()
      return this.getAgentIterationPoiAreaHeatmapBoundary()
        .map((point) => this.projectAgentIterationPoiAreaHeatmapDisplayPoint(point, transform))
    },
    getAgentIterationPoiAreaHeatmapDisplayBoundaryPoints() {
      return this.getAgentIterationPoiAreaHeatmapDisplayBoundary()
        .map((point) => `${Number(point.x || 0).toFixed(2)},${Number(point.y || 0).toFixed(2)}`)
        .join(' ')
    },
    getAgentIterationPoiAreaHeatmapDisplayPoints(heatmap = {}) {
      const transform = this.getAgentIterationPoiAreaHeatmapDisplayTransform()
      const points = cloneArray(heatmap.points)
        .map((point) => ({
          ...point,
          ...this.projectAgentIterationPoiAreaHeatmapDisplayPoint(point, transform),
        }))
      return this.clusterAgentIterationPoiAreaHeatmapDisplayPoints(points)
    },
    clusterAgentIterationPoiAreaHeatmapDisplayPoints(points = []) {
      const rows = cloneArray(points).filter((point) => Number.isFinite(Number(point.x)) && Number.isFinite(Number(point.y)))
      if (rows.length <= 60) {
        return rows.map((point) => ({ ...point, count: 1, radius: 2, opacity: 0.68 }))
      }
      const cellSize = rows.length > 420 ? 8 : rows.length > 180 ? 7 : 6
      const clusters = new Map()
      rows.forEach((point) => {
        const key = `${Math.floor(Number(point.x) / cellSize)}:${Math.floor(Number(point.y) / cellSize)}`
        const cluster = clusters.get(key) || { xSum: 0, ySum: 0, count: 0, points: [] }
        cluster.xSum += Number(point.x)
        cluster.ySum += Number(point.y)
        cluster.count += 1
        cluster.points.push(point)
        clusters.set(key, cluster)
      })
      return [...clusters.values()].map((cluster) => {
        const count = Math.max(1, Number(cluster.count || 0))
        return {
          ...(cluster.points[0] || {}),
          x: Number((cluster.xSum / count).toFixed(3)),
          y: Number((cluster.ySum / count).toFixed(3)),
          count,
          radius: Number(Math.min(5.4, 1.8 + Math.sqrt(count) * 0.72).toFixed(2)),
          opacity: Number(Math.min(0.74, 0.42 + Math.sqrt(count) * 0.045).toFixed(2)),
        }
      })
    },
    getAgentIterationPoiAreaHeatmapDisplayCells(heatmap = {}) {
      const transform = this.getAgentIterationPoiAreaHeatmapDisplayTransform()
      if (!transform) return cloneArray(heatmap.cells)
      return cloneArray(heatmap.cells).map((cell) => {
        const topLeft = this.projectAgentIterationPoiAreaHeatmapDisplayPoint({ x: cell.x, y: cell.y }, transform)
        return {
          ...cell,
          x: topLeft.x,
          y: topLeft.y,
          width: Number((Number(cell.width || 0) * Number(transform.scale || 1)).toFixed(3)),
          height: Number((Number(cell.height || 0) * Number(transform.scale || 1)).toFixed(3)),
        }
      })
    },
    getAgentIterationPoiAreaHeatmapBoundaryPoints() {
      return this.getAgentIterationPoiAreaHeatmapBoundary()
        .map((point) => `${Number(point.x || 0).toFixed(2)},${Number(point.y || 0).toFixed(2)}`)
        .join(' ')
    },
    getAgentIterationPoiAreaHeatmapPolygon() {
      return cloneArray(this.getAgentIterationPoiAreaHeatmapCalibratedPayload().area_heatmap_polygon)
    },
    normalizeAgentPoiAreaHeatmapPolygon(polygon = []) {
      return this.normalizeAgentIterationSnapshotPolygon(polygon)
    },
    getAgentPoiAreaHeatmapSourcePairs(summaries = [], polygon = []) {
      const polygonPairs = this.normalizeAgentPoiAreaHeatmapPolygon(polygon)
      if (polygonPairs.length >= 3) return polygonPairs
      return cloneArray(summaries)
        .flatMap((summary) => cloneArray(summary.points))
        .map((point) => [Number(point && point.lng), Number(point && point.lat)])
        .filter((point) => Number.isFinite(point[0]) && Number.isFinite(point[1]))
    },
    buildAgentPoiAreaHeatmapViewport(summaries = [], polygon = []) {
      const pairs = this.getAgentPoiAreaHeatmapSourcePairs(summaries, polygon)
      if (!pairs.length) return null
      const lngs = pairs.map((point) => Number(point[0])).filter(Number.isFinite)
      const lats = pairs.map((point) => Number(point[1])).filter(Number.isFinite)
      if (!lngs.length || !lats.length) return null
      const minLng = Math.min(...lngs)
      const maxLng = Math.max(...lngs)
      const minLat = Math.min(...lats)
      const maxLat = Math.max(...lats)
      const refLat = (minLat + maxLat) / 2
      const metersPerLon = Math.max(1000, 111320 * Math.abs(Math.cos((refLat * Math.PI) / 180)))
      const projectRaw = (lng, lat) => ({
        x: Number(lng) * metersPerLon,
        y: Number(lat) * 111320,
      })
      const minProjected = projectRaw(minLng, minLat)
      const maxProjected = projectRaw(maxLng, maxLat)
      const rawSpanX = Math.max(maxProjected.x - minProjected.x, 1e-9)
      const rawSpanY = Math.max(maxProjected.y - minProjected.y, 1e-9)
      const viewWidth = 100
      const viewHeight = Math.max(50, Math.min(100, Number((viewWidth * rawSpanY / rawSpanX).toFixed(3))))
      const padding = 6
      const usableWidth = Math.max(1, viewWidth - padding * 2)
      const usableHeight = Math.max(1, viewHeight - padding * 2)
      const scale = Math.min(usableWidth / rawSpanX, usableHeight / rawSpanY)
      const contentWidth = rawSpanX * scale
      const contentHeight = rawSpanY * scale
      return {
        minLng,
        minLat,
        maxLng,
        maxLat,
        refLat,
        metersPerLon,
        minProjected,
        maxProjected,
        rawSpanX,
        rawSpanY,
        view: { width: viewWidth, height: viewHeight },
        padding,
        scale,
        offsetX: (viewWidth - contentWidth) / 2,
        offsetY: (viewHeight - contentHeight) / 2,
      }
    },
    projectAgentPoiAreaHeatmapPoint(lng, lat, viewport = null) {
      if (!viewport) return { x: 0, y: 0 }
      const projected = {
        x: Number(lng) * Number(viewport.metersPerLon || 1),
        y: Number(lat) * 111320,
      }
      const x = Number(viewport.offsetX || 0) + ((projected.x - Number((viewport.minProjected || {}).x || 0)) * Number(viewport.scale || 1))
      const y = Number((viewport.view || {}).height || 100)
        - Number(viewport.offsetY || 0)
        - ((projected.y - Number((viewport.minProjected || {}).y || 0)) * Number(viewport.scale || 1))
      const viewWidth = Math.max(1, Number((viewport.view || {}).width || 100))
      const viewHeight = Math.max(1, Number((viewport.view || {}).height || 100))
      return {
        x: Number(Math.max(0, Math.min(viewWidth, x)).toFixed(3)),
        y: Number(Math.max(0, Math.min(viewHeight, y)).toFixed(3)),
      }
    },
    isAgentPoiAreaHeatmapPointInPolygon(lng, lat, polygon = []) {
      const ring = this.normalizeAgentPoiAreaHeatmapPolygon(polygon)
      if (ring.length < 3) return true
      const x = Number(lng)
      const y = Number(lat)
      if (!Number.isFinite(x) || !Number.isFinite(y)) return false
      let inside = false
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
        const xi = Number(ring[i][0])
        const yi = Number(ring[i][1])
        const xj = Number(ring[j][0])
        const yj = Number(ring[j][1])
        const intersects = ((yi > y) !== (yj > y))
          && (x < ((xj - xi) * (y - yi)) / ((yj - yi) || 1e-12) + xi)
        if (intersects) inside = !inside
      }
      return inside
    },
    buildAgentPoiAreaHeatmapBoundary(polygon = [], viewport = null) {
      return this.normalizeAgentPoiAreaHeatmapPolygon(polygon)
        .map((point) => this.projectAgentPoiAreaHeatmapPoint(point[0], point[1], viewport))
        .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y))
    },
    buildAgentPoiAreaHeatmapBasemap(viewport = null) {
      const view = cloneObject(viewport && viewport.view, { width: 100, height: 100 })
      const width = Math.max(1, Number(view.width || 100))
      const height = Math.max(1, Number(view.height || 100))
      const bounds = viewport
        ? {
            min_lng: Number(Number(viewport.minLng).toFixed(6)),
            min_lat: Number(Number(viewport.minLat).toFixed(6)),
            max_lng: Number(Number(viewport.maxLng).toFixed(6)),
            max_lat: Number(Number(viewport.maxLat).toFixed(6)),
            ref_lat: Number(Number(viewport.refLat).toFixed(6)),
          }
        : {}
      return {
        url: '',
        bounds,
        center: viewport ? [Number(((Number(viewport.minLng) + Number(viewport.maxLng)) / 2).toFixed(6)), Number(((Number(viewport.minLat) + Number(viewport.maxLat)) / 2).toFixed(6))] : [],
        zoom: null,
        size: { width: 640, height: Math.max(320, Math.round(640 * height / width)) },
        source: 'none',
        view: { width, height },
        view_box: `0 0 ${width} ${height}`,
        aspect_ratio: `${width} / ${height}`,
        viewport: {},
      }
    },
    getAgentIterationPoiAreaHeatmapSnapshots() {
      const payload = this.getAgentIterationPoiPayload()
      const byYear = new Map(cloneArray(payload.area_heatmaps).map((row) => [String(row.year), row]))
      return cloneArray(payload.area_heatmap_snapshots).map((snapshot) => {
        const fallback = byYear.get(String(snapshot.year)) || {}
        return {
          year: snapshot.year,
          image_url: asText(snapshot.image_url),
          point_count: Number(snapshot.point_count ?? fallback.point_count ?? 0),
          top_area: asText(snapshot.top_area || fallback.top_area),
          status: asText(snapshot.status) || 'pending',
          error: asText(snapshot.error),
        }
      })
    },
    getAgentIterationPoiAreaHeatmapSnapshot(year) {
      const key = String(year || '')
      return this.getAgentIterationPoiAreaHeatmapSnapshots().find((item) => String(item.year || '') === key) || {}
    },
    getAgentIterationPoiAreaHeatmapSnapshotStatusText(snapshot = {}) {
      const status = asText(snapshot.status)
      if (status === 'ready') return '快照已生成'
      if (status === 'loading') return `${asText(snapshot.year) || '该年份'} 快照生成中`
      if (status === 'failed') return '快照生成失败，已显示矢量兜底'
      return `${asText(snapshot.year) || '该年份'} 等待生成快照`
    },
    getAgentIterationPoiAreaHeatmapCellOpacity(cell = {}) {
      const intensity = Math.max(0, Math.min(1, Number(cell.intensity || 0)))
      return (0.12 + intensity * 0.52).toFixed(3)
    },
    getAgentIterationPoiAreaHeatmapDeltaText(heatmap = {}) {
      const delta = Number(heatmap.delta_from_previous || 0)
      if (!Number.isFinite(delta) || delta === 0) return '首期/持平'
      const ratio = Number(heatmap.delta_ratio_from_previous || 0)
      const ratioText = Number.isFinite(ratio) && ratio
        ? `，${ratio > 0 ? '+' : ''}${Math.round(ratio * 100)}%`
        : ''
      return `${delta > 0 ? '+' : ''}${this.formatAgentIterationMetric(delta, 0)}点${ratioText}`
    },
    getAgentIterationPoiAreaHeatmapDeltaClass(heatmap = {}) {
      const delta = Number(heatmap.delta_from_previous || 0)
      if (delta > 0) return 'positive'
      if (delta < 0) return 'negative'
      return ''
    },
    getAgentIterationPoiAreaHeatmapTrendStyle(heatmap = {}) {
      const level = Math.max(0, Math.min(1, Number(heatmap.count_level || 0)))
      return { width: `${Math.max(8, Math.round(level * 100))}%` }
    },
    buildAgentPoiAreaHeatmapSnapshotPlaceholders(payload = {}) {
      const heatmapByYear = new Map(cloneArray(payload.area_heatmaps).map((row) => [String(row.year), row]))
      return cloneArray(payload.summaries).map((summary) => {
        const fallback = heatmapByYear.get(String(summary.year)) || {}
        return {
          year: summary.year,
          image_url: '',
          point_count: Number(cloneArray(summary.points).length || fallback.point_count || 0),
          top_area: asText((((cloneArray(summary.top_areas)[0] || {})).name) || fallback.top_area),
          status: 'pending',
          error: '',
        }
      })
    },
    getAgentPoiAreaSnapshotCacheKey(payload = {}) {
      const years = cloneArray(payload.years).join(',')
      const polygon = JSON.stringify(cloneArray(payload.area_heatmap_polygon).slice(0, 160))
      const counts = cloneArray(payload.summaries).map((summary) => `${summary.year}:${cloneArray(summary.points).length}`).join(',')
      const size = this.getAgentPoiSnapshotRenderSize(payload)
      return `basemap-points-v4|${size.width}x${size.height}|${asText(payload.historyId || payload.history_id)}|${years}|${counts}|${polygon.length}:${polygon.slice(0, 80)}`
    },
    getAgentPoiAreaHeatmapCalibrationCacheKey(payload = {}) {
      const years = cloneArray(payload.years).join(',')
      const polygon = JSON.stringify(cloneArray(payload.area_heatmap_polygon).slice(0, 220))
      const counts = cloneArray(payload.summaries).map((summary) => `${summary.year}:${cloneArray(summary.points).length}`).join(',')
      return `${asText(payload.historyId || payload.history_id || payload.source)}|${years}|${counts}|${polygon.length}:${polygon.slice(0, 120)}`
    },
    buildAgentPoiAreaHeatmapBasemapFromImage(imageUrl = '', size = {}) {
      const width = Math.max(1, Number(size.width || 760))
      const height = Math.max(1, Number(size.height || 760))
      return {
        url: asText(imageUrl),
        bounds: {},
        center: [],
        zoom: null,
        size: { width, height },
        source: asText(imageUrl) ? 'amap_js_snapshot' : 'none',
        view: { width, height },
        view_box: `0 0 ${width} ${height}`,
        aspect_ratio: `${width} / ${height}`,
        viewport: {},
      }
    },
    getAgentPoiSnapshotRenderSize(payload = {}) {
      const basemap = cloneObject(payload.area_heatmap_basemap)
      const size = cloneObject(basemap.size || basemap.view)
      const width = Math.max(1, Math.round(Number(size.width || 760)))
      const height = Math.max(1, Math.round(Number(size.height || width || 760)))
      return { width, height }
    },
    projectAgentPoiAreaHeatmapLngLatWithMap(map = null, lng, lat) {
      if (!map || typeof map.lngLatToContainer !== 'function' || !window.AMap || typeof AMap.LngLat !== 'function') return null
      const point = map.lngLatToContainer(new AMap.LngLat(Number(lng), Number(lat)))
      const x = Number(point && (point.x ?? point.getX?.()))
      const y = Number(point && (point.y ?? point.getY?.()))
      if (!Number.isFinite(x) || !Number.isFinite(y)) return null
      return { x: Number(x.toFixed(3)), y: Number(y.toFixed(3)) }
    },
    buildAgentPoiAreaHeatmapRowsFromProjectedSummaries(summaries = [], polygon = [], map = null, size = {}) {
      const width = Math.max(1, Number(size.width || 760))
      const height = Math.max(1, Number(size.height || 760))
      const gridSize = 12
      const cellWidth = width / gridSize
      const cellHeight = height / gridSize
      return cloneArray(summaries)
        .filter((summary) => cloneArray(summary.points).length)
        .sort((a, b) => Number(a.year || 0) - Number(b.year || 0))
        .map((summary) => {
          const points = cloneArray(summary.points)
            .filter((point) => this.isAgentPoiAreaHeatmapPointInPolygon(point && point.lng, point && point.lat, polygon))
            .map((point) => {
              const projected = this.projectAgentPoiAreaHeatmapLngLatWithMap(map, point && point.lng, point && point.lat)
              if (!projected) return null
              return {
                x: Math.max(0, Math.min(width, projected.x)),
                y: Math.max(0, Math.min(height, projected.y)),
                area: asText(point.area),
                category: asText(point.category),
                subcategory: asText(point.subcategory),
              }
            })
            .filter(Boolean)
          const cellCounts = new Map()
          points.forEach((point) => {
            const col = Math.max(0, Math.min(gridSize - 1, Math.floor(Number(point.x || 0) / cellWidth)))
            const row = Math.max(0, Math.min(gridSize - 1, Math.floor(Number(point.y || 0) / cellHeight)))
            const key = `${col}:${row}`
            cellCounts.set(key, (cellCounts.get(key) || 0) + 1)
          })
          const maxCellCount = Math.max(1, ...Array.from(cellCounts.values()))
          const cells = Array.from(cellCounts.entries())
            .sort(([a], [b]) => {
              const [aCol, aRow] = a.split(':').map((item) => Number(item))
              const [bCol, bRow] = b.split(':').map((item) => Number(item))
              return aRow - bRow || aCol - bCol
            })
            .map(([key, count]) => {
              const [col, row] = key.split(':').map((item) => Number(item))
              return {
                x: Number((col * cellWidth).toFixed(3)),
                y: Number((row * cellHeight).toFixed(3)),
                width: Number(cellWidth.toFixed(3)),
                height: Number(cellHeight.toFixed(3)),
                count,
                intensity: Number((count / maxCellCount).toFixed(4)),
              }
            })
          return {
            year: summary.year,
            points: points.slice(0, 260),
            cells,
            point_count: points.length,
            top_area: asText(((cloneArray(summary.top_areas)[0] || {}).name)),
          }
        })
    },
    buildAgentPoiAreaHeatmapBoundaryFromMap(polygon = [], map = null, size = {}) {
      const width = Math.max(1, Number(size.width || 760))
      const height = Math.max(1, Number(size.height || 760))
      return this.normalizeAgentPoiAreaHeatmapPolygon(polygon)
        .map((point) => this.projectAgentPoiAreaHeatmapLngLatWithMap(map, point[0], point[1]))
        .filter(Boolean)
        .map((point) => ({
          x: Math.max(0, Math.min(width, point.x)),
          y: Math.max(0, Math.min(height, point.y)),
        }))
    },
    async renderAgentIterationPoiAreaHeatmapCalibration(payload = {}) {
      if (!window.AMap || typeof AMap.Map !== 'function') throw new Error('amap_unavailable')
      if (typeof html2canvas !== 'function') throw new Error('html2canvas_unavailable')
      const summaries = cloneArray(payload.summaries)
      if (!summaries.length) throw new Error('no_summaries')
      const polygonPath = this.normalizeAgentIterationSnapshotPolygon(payload.area_heatmap_polygon)
      const allPoints = summaries.flatMap((summary) => cloneArray(summary.points))
        .filter((point) => Number.isFinite(Number(point && point.lng)) && Number.isFinite(Number(point && point.lat)))
      if (polygonPath.length < 3 && !allPoints.length) throw new Error('no_geometry')
      const size = { width: 760, height: 760 }
      const host = this.getOrCreateAgentIterationPoiSnapshotHost()
      host.innerHTML = ''
      const mapEl = document.createElement('div')
      mapEl.style.cssText = `width:${size.width}px;height:${size.height}px;position:relative;background:#fff;overflow:hidden;`
      host.appendChild(mapEl)

      const overlays = []
      let map = null
      try {
        map = new AMap.Map(mapEl, {
          zoom: 13,
          viewMode: '2D',
          resizeEnable: false,
          features: ['bg', 'point', 'road', 'building'],
        })
        let polygonOverlay = null
        if (polygonPath.length >= 3 && typeof AMap.Polygon === 'function') {
          polygonOverlay = new AMap.Polygon({
            path: polygonPath,
            strokeOpacity: 0,
            fillOpacity: 0,
            zIndex: 1,
          })
          polygonOverlay.setMap(map)
          overlays.push(polygonOverlay)
        }
        const fitMarkers = []
        if (!polygonOverlay && typeof AMap.Marker === 'function') {
          allPoints.slice(0, 1200).forEach((point) => {
            const marker = new AMap.Marker({
              position: [Number(point.lng), Number(point.lat)],
              opacity: 0,
              zIndex: 1,
            })
            marker.setMap(map)
            overlays.push(marker)
            fitMarkers.push(marker)
          })
        }
        if (polygonOverlay && typeof map.setFitView === 'function') {
          map.setFitView([polygonOverlay], false, [32, 32, 32, 32])
        } else if (fitMarkers.length && typeof map.setFitView === 'function') {
          map.setFitView(fitMarkers, false, [32, 32, 32, 32])
        }
        await this.waitForAgentPoiSnapshotPaint(900)
        const boundary = this.buildAgentPoiAreaHeatmapBoundaryFromMap(polygonPath, map, size)
        const rows = this.buildAgentPoiAreaHeatmapRowsFromProjectedSummaries(summaries, polygonPath, map, size)
        overlays.forEach((overlay) => {
          try { if (overlay && typeof overlay.setMap === 'function') overlay.setMap(null) } catch (_) {}
        })
        this.cleanAgentPoiSnapshotMapChrome(mapEl)
        const basemapReady = await this.waitForAgentPoiSnapshotImages(mapEl, 3000)
        if (!basemapReady) throw new Error('basemap_image_load_failed')
        const canvas = await html2canvas(mapEl, {
          useCORS: true,
          backgroundColor: '#ffffff',
          scale: 1,
          logging: false,
          ignoreElements: (element) => this.isAgentPoiSnapshotIgnoredElement(element),
        })
        const imageUrl = canvas && typeof canvas.toDataURL === 'function' ? canvas.toDataURL('image/png') : ''
        if (!asText(imageUrl).startsWith('data:image/png')) throw new Error('snapshot_unavailable')
        if (polygonPath.length >= 3 && boundary.length < 3) throw new Error('boundary_projection_unavailable')
        if (asText(imageUrl).length < 50000) throw new Error('basemap_snapshot_too_small')
        return {
          status: 'ready',
          area_heatmaps: rows,
          area_heatmap_basemap: this.buildAgentPoiAreaHeatmapBasemapFromImage(imageUrl, size),
          area_heatmap_boundary: boundary,
          area_heatmap_polygon: polygonPath,
        }
      } finally {
        overlays.forEach((overlay) => {
          try { if (overlay && typeof overlay.setMap === 'function') overlay.setMap(null) } catch (_) {}
        })
        try { if (map && typeof map.destroy === 'function') map.destroy() } catch (_) {}
        host.innerHTML = ''
      }
    },
    async ensureAgentIterationPoiAreaHeatmapCalibration(payloadArg = null) {
      const payload = payloadArg || this.getAgentIterationPoiPayload()
      if (asText(payload.status) !== 'ready') return payload
      const cacheKey = this.getAgentPoiAreaHeatmapCalibrationCacheKey(payload)
      if (!cacheKey || asText(this.agentIterationPoiAreaHeatmapCalibrationGeneratingKey) === cacheKey) return payload
      const cached = cloneObject((this.agentIterationPoiAreaHeatmapCalibrationCache || {})[cacheKey])
      if (asText(cached.status) === 'ready') return payload
      this.agentIterationPoiAreaHeatmapCalibrationGeneratingKey = cacheKey
      try {
        const calibrated = await this.renderAgentIterationPoiAreaHeatmapCalibration(payload)
        this.agentIterationPoiAreaHeatmapCalibrationCache = {
          ...cloneObject(this.agentIterationPoiAreaHeatmapCalibrationCache),
          [cacheKey]: calibrated,
        }
      } catch (err) {
        const nextCache = cloneObject(this.agentIterationPoiAreaHeatmapCalibrationCache)
        delete nextCache[cacheKey]
        this.agentIterationPoiAreaHeatmapCalibrationCache = nextCache
      } finally {
        if (asText(this.agentIterationPoiAreaHeatmapCalibrationGeneratingKey) === cacheKey) {
          this.agentIterationPoiAreaHeatmapCalibrationGeneratingKey = ''
        }
      }
      return payload
    },
    async ensureAgentIterationPoiAreaHeatmapSnapshots(payloadArg = null) {
      const payload = payloadArg || this.getAgentIterationPoiPayload()
      if (asText(payload.status) !== 'ready') return payload
      const years = cloneArray(payload.summaries).map((summary) => summary.year).filter((year) => asText(year))
      if (!years.length) return payload
      const cacheKey = this.getAgentPoiAreaSnapshotCacheKey(payload)
      if (asText(this.agentIterationPoiSnapshotGeneratingKey) === cacheKey) return payload
      const cached = cloneArray((this.agentIterationPoiSnapshotCache || {})[cacheKey])
      if (cached.length && cached.every((item) => asText(item.status) === 'ready' || asText(item.status) === 'failed')) {
        return this.commitAgentIterationPoiPayload({ area_heatmap_snapshots: cached })
      }

      const placeholders = (cloneArray(payload.area_heatmap_snapshots).length
        ? cloneArray(payload.area_heatmap_snapshots)
        : this.buildAgentPoiAreaHeatmapSnapshotPlaceholders(payload))
        .map((item) => ({
          ...item,
          status: asText(item.image_url) ? 'ready' : 'pending',
          error: '',
        }))
      this.commitAgentIterationPoiPayload({
        area_heatmap_snapshots: placeholders,
      })

      this.agentIterationPoiSnapshotGeneratingKey = cacheKey
      try {
        const snapshots = []
        for (const summary of cloneArray(payload.summaries)) {
          const year = summary.year
          const base = placeholders.find((item) => String(item.year) === String(year)) || {}
          const currentSnapshots = this.getAgentIterationPoiAreaHeatmapSnapshots().length
            ? this.getAgentIterationPoiAreaHeatmapSnapshots()
            : placeholders
          this.commitAgentIterationPoiPayload({ area_heatmap_snapshots: currentSnapshots.map((item) => (
            String(item.year) === String(year) && !asText(item.image_url)
              ? { ...item, status: 'loading', error: '' }
              : item
          )) })
          try {
            const imageUrl = await this.renderAgentIterationPoiAreaSnapshot(summary, payload)
            snapshots.push({
              ...base,
              year,
              image_url: imageUrl,
              point_count: cloneArray(summary.points).length,
              top_area: asText((((cloneArray(summary.top_areas)[0] || {})).name) || base.top_area),
              status: imageUrl ? 'ready' : 'failed',
              error: imageUrl ? '' : 'snapshot_unavailable',
            })
          } catch (err) {
            snapshots.push({
              ...base,
              year,
              image_url: '',
              point_count: cloneArray(summary.points).length,
              top_area: asText((((cloneArray(summary.top_areas)[0] || {})).name) || base.top_area),
              status: 'failed',
              error: asText(err && err.message) || 'snapshot_failed',
            })
          }
          this.commitAgentIterationPoiPayload({ area_heatmap_snapshots: cloneArray(snapshots).concat(
            placeholders.filter((item) => !snapshots.some((snapshot) => String(snapshot.year) === String(item.year)))
          ) })
        }
        this.agentIterationPoiSnapshotCache = {
          ...cloneObject(this.agentIterationPoiSnapshotCache),
          [cacheKey]: snapshots,
        }
        return this.commitAgentIterationPoiPayload({ area_heatmap_snapshots: snapshots })
      } finally {
        if (asText(this.agentIterationPoiSnapshotGeneratingKey) === cacheKey) {
          this.agentIterationPoiSnapshotGeneratingKey = ''
        }
      }
    },
    normalizeAgentIterationSnapshotPolygon(polygon = []) {
      const source = cloneArray(polygon)
      const ring = Array.isArray(source[0]) && Array.isArray(source[0][0]) ? source[0] : source
      return cloneArray(ring)
        .map((point) => [Number(point && point[0]), Number(point && point[1])])
        .filter((point) => Number.isFinite(point[0]) && Number.isFinite(point[1]))
    },
    getOrCreateAgentIterationPoiSnapshotHost() {
      let host = document.getElementById('agentIterationPoiSnapshotHost')
      if (host) return host
      host = document.createElement('div')
      host.id = 'agentIterationPoiSnapshotHost'
      host.style.cssText = 'position:fixed;left:0;top:0;width:760px;height:760px;background:#fff;z-index:-1;pointer-events:none;overflow:hidden;'
      document.body.appendChild(host)
      return host
    },
    waitForAgentPoiSnapshotPaint(ms = 650) {
      return new Promise((resolve) => window.setTimeout(resolve, Math.max(0, Number(ms) || 0)))
    },
    extractAgentPoiSnapshotCssUrls(value = '') {
      const raw = asText(value)
      if (!raw || raw === 'none') return []
      const urls = []
      raw.replace(/url\((['"]?)(.*?)\1\)/g, (_match, _quote, url) => {
        const normalized = asText(url).trim()
        if (normalized) urls.push(normalized)
        return _match
      })
      return urls
    },
    async waitForAgentPoiSnapshotImageUrl(src = '', timeoutMs = 3000) {
      const url = asText(src)
      if (!url || typeof Image === 'undefined') return true
      return await new Promise((resolve) => {
        let settled = false
        const timerApi = typeof window !== 'undefined' ? window : globalThis
        const finish = (ok) => {
          if (settled) return
          settled = true
          if (timer) timerApi.clearTimeout(timer)
          resolve(!!ok)
        }
        const timer = timerApi.setTimeout(() => finish(false), Math.max(250, Number(timeoutMs) || 3000))
        const image = new Image()
        image.crossOrigin = 'anonymous'
        image.onload = async () => {
          try {
            if (typeof image.decode === 'function') await image.decode()
          } catch (_) {}
          finish(true)
        }
        image.onerror = () => finish(false)
        image.src = url
      })
    },
    async waitForAgentPoiSnapshotImages(root = null, timeoutMs = 3000) {
      if (!root || typeof root.querySelectorAll !== 'function') return true
      const urls = new Set()
      const nodes = [root, ...Array.from(root.querySelectorAll('*') || [])]
      nodes.forEach((node) => {
        if (!node) return
        if (node.tagName && String(node.tagName).toLowerCase() === 'img') {
          const src = asText(node.currentSrc || node.src || (node.getAttribute && node.getAttribute('src')))
          if (src) urls.add(src)
        }
        if (node.style && node.style.backgroundImage) {
          this.extractAgentPoiSnapshotCssUrls(node.style.backgroundImage).forEach((url) => urls.add(url))
        }
      })
      const results = await Promise.all(Array.from(urls).map((url) => this.waitForAgentPoiSnapshotImageUrl(url, timeoutMs)))
      return results.every(Boolean)
    },
    isAgentPoiSnapshotIgnoredElement(element = null) {
      if (!element || typeof element.matches !== 'function') return false
      return element.matches('.amap-logo, .amap-copyright, .amap-control, [class^="amap-control"], [class*=" amap-control"]')
    },
    cleanAgentPoiSnapshotMapChrome(root = null) {
      if (!root || typeof root.querySelectorAll !== 'function') return
      root.querySelectorAll('.amap-logo, .amap-copyright, .amap-control, [class^="amap-control"], [class*=" amap-control"]').forEach((node) => {
        if (node && node.style) {
          node.style.display = 'none'
          node.style.visibility = 'hidden'
          node.style.opacity = '0'
        }
      })
    },
    applyAgentPoiSnapshotBasemap(mapEl = null, payload = {}) {
      if (!mapEl || !mapEl.style) return false
      const url = asText((payload.area_heatmap_basemap || {}).url)
      if (!url) return false
      mapEl.style.backgroundImage = `url("${url}")`
      mapEl.style.backgroundSize = '100% 100%'
      mapEl.style.backgroundPosition = 'center'
      mapEl.style.backgroundRepeat = 'no-repeat'
      return true
    },
    buildAgentPoiSnapshotOverlaySvg(map = null, summary = {}, payload = {}) {
      if (!map || typeof map.lngLatToContainer !== 'function') return ''
      const size = this.getAgentPoiSnapshotRenderSize(payload)
      const polygonPath = this.normalizeAgentIterationSnapshotPolygon(payload.area_heatmap_polygon)
      const boundary = this.buildAgentPoiAreaHeatmapBoundaryFromMap(polygonPath, map, size)
      const row = this.buildAgentPoiAreaHeatmapRowsFromProjectedSummaries([summary], polygonPath, map, size)[0] || {}
      const boundaryPoints = boundary.map((point) => `${Number(point.x || 0).toFixed(1)},${Number(point.y || 0).toFixed(1)}`).join(' ')
      const clipId = `poi-snapshot-clip-${asText(summary.year) || 'year'}`
      const points = cloneArray(row.points).slice(0, 900).map((point) => (
        `<circle cx="${Number(point.x || 0).toFixed(1)}" cy="${Number(point.y || 0).toFixed(1)}" r="1.35" fill="#17324d" fill-opacity="0.7" stroke="rgba(255,255,255,0.72)" stroke-width="0.42"></circle>`
      )).join('')
      const clipOpen = boundaryPoints ? `<g clip-path="url(#${clipId})">` : '<g>'
      const defs = boundaryPoints ? `<defs><clipPath id="${clipId}"><polygon points="${boundaryPoints}"></polygon></clipPath></defs>` : ''
      return `
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${size.width} ${size.height}" style="position:absolute;inset:0;width:100%;height:100%;pointer-events:none;">
          ${defs}
          ${clipOpen}${points}</g>
        </svg>
      `
    },
    async renderAgentIterationPoiAreaSnapshot(summary = {}, payload = {}) {
      if (!window.AMap || typeof AMap.Map !== 'function') throw new Error('amap_unavailable')
      if (typeof html2canvas !== 'function') throw new Error('html2canvas_unavailable')
      const points = cloneArray(summary.points).filter((point) => Number.isFinite(Number(point.lng)) && Number.isFinite(Number(point.lat)))
      if (!points.length) throw new Error('no_points')
      const polygonPath = this.normalizeAgentIterationSnapshotPolygon(payload.area_heatmap_polygon)
      const size = this.getAgentPoiSnapshotRenderSize(payload)
      const host = this.getOrCreateAgentIterationPoiSnapshotHost()
      host.innerHTML = ''
      const mapEl = document.createElement('div')
      mapEl.style.cssText = `width:${size.width}px;height:${size.height}px;position:relative;background:#fff;overflow:hidden;`
      const hasFallbackBasemap = this.applyAgentPoiSnapshotBasemap(mapEl, payload)
      host.appendChild(mapEl)

      const overlays = []
      let map = null
      try {
        map = new AMap.Map(mapEl, {
          zoom: 13,
          viewMode: '2D',
          resizeEnable: false,
          features: ['bg', 'point', 'road', 'building'],
        })
        let polygonOverlay = null
        if (polygonPath.length >= 3 && typeof AMap.Polygon === 'function') {
          polygonOverlay = new AMap.Polygon({
            path: polygonPath,
            strokeColor: '#2563eb',
            strokeWeight: 1.5,
            strokeOpacity: 0.95,
            fillColor: '#2563eb',
            fillOpacity: 0.05,
            zIndex: 20,
          })
          polygonOverlay.setMap(map)
          overlays.push(polygonOverlay)
        }
        if (polygonOverlay && typeof map.setFitView === 'function') {
          map.setFitView([polygonOverlay], false, [28, 28, 28, 28])
        } else if (typeof map.setFitView === 'function') {
          map.setFitView(overlays, false, [28, 28, 28, 28])
        }
        if (polygonOverlay && typeof polygonOverlay.setMap === 'function') {
          polygonOverlay.setMap(null)
        }
        await this.waitForAgentPoiSnapshotPaint()
        if (hasFallbackBasemap) {
          const basemapReady = await this.waitForAgentPoiSnapshotImageUrl((payload.area_heatmap_basemap || {}).url, 3000)
          if (!basemapReady) throw new Error('basemap_image_load_failed')
        }
        const overlayHost = document.createElement('div')
        overlayHost.style.cssText = 'position:absolute;inset:0;pointer-events:none;z-index:50;'
        overlayHost.innerHTML = this.buildAgentPoiSnapshotOverlaySvg(map, summary, payload)
        mapEl.appendChild(overlayHost)
        this.cleanAgentPoiSnapshotMapChrome(mapEl)
        const basemapReady = await this.waitForAgentPoiSnapshotImages(mapEl, 3000)
        if (!basemapReady) throw new Error('basemap_image_load_failed')
        const canvas = await html2canvas(mapEl, {
          useCORS: true,
          backgroundColor: '#ffffff',
          scale: 1,
          logging: false,
          ignoreElements: (element) => this.isAgentPoiSnapshotIgnoredElement(element),
        })
        const dataUrl = canvas && typeof canvas.toDataURL === 'function' ? canvas.toDataURL('image/png') : ''
        return asText(dataUrl).startsWith('data:image/png') ? dataUrl : ''
      } finally {
        overlays.forEach((overlay) => {
          try { if (overlay && typeof overlay.setMap === 'function') overlay.setMap(null) } catch (_) {}
        })
        try { if (map && typeof map.destroy === 'function') map.destroy() } catch (_) {}
        host.innerHTML = ''
      }
    },
    getAgentIterationPoiLineChartPoints() {
      const series = this.getAgentIterationPoiTotalLineChart()
      if (!series.length) return []
      const values = series.map((item) => Number(item.value || 0))
      const minValue = Math.min(...values)
      const maxValue = Math.max(...values)
      const span = Math.max(maxValue - minValue, 1)
      const width = 320
      const height = 140
      const padX = 18
      const padY = 18
      const step = series.length > 1 ? (width - padX * 2) / (series.length - 1) : 0
      return series.map((item, index) => ({
        year: item.year,
        value: Number(item.value || 0),
        x: padX + step * index,
        y: height - padY - ((Number(item.value || 0) - minValue) / span) * (height - padY * 2),
      }))
    },
    getAgentIterationPoiLineChartPolyline() {
      return this.getAgentIterationPoiLineChartPoints()
        .map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`)
        .join(' ')
    },
    getAgentIterationPoiCategoryLegend() {
      const names = []
      this.getAgentIterationPoiCategoryStackChart().forEach((row) => {
        cloneArray(row.segments).forEach((segment) => {
          const name = asText(segment.name)
          if (name && !names.includes(name)) names.push(name)
        })
      })
      return names
    },
    getAgentIterationCategoryColor(name = '') {
      const palette = ['#2563eb', '#f97316', '#16a34a', '#9333ea', '#dc2626', '#94a3b8']
      const legend = this.getAgentIterationPoiCategoryLegend()
      const index = Math.max(0, legend.indexOf(asText(name)))
      return palette[index % palette.length]
    },
    setAgentIterationKind(kind = '') {
      const next = asText(kind) || 'nightlight'
      if (!this.getAgentIterationKinds().some((item) => item.key === next && !item.disabled)) return
      this.agentIterationActiveKind = next
      const nextSecondary = this.getAgentIterationSecondaryView(next)
      if (!nextSecondary) this.setAgentIterationSecondaryView((this.getAgentIterationSecondaryNavItems(next)[0] || {}).key, next)
      const tabs = this.ensureAgentTabs(true)
      const activeId = asText(tabs.activeTabId)
      tabs.iterationChangeTabs = cloneArray(tabs.iterationChangeTabs).map((item) => (
        item.id === activeId ? { ...item, activeKind: next } : item
      ))
      this.agentTabs = { ...tabs, iterationChangeTabs: cloneArray(tabs.iterationChangeTabs) }
      this.ensureAgentIterationKind(next).catch((err) => {
        console.warn('[Agent] iteration kind load failed:', err)
      })
    },
    ensureAgentIterationKind(kind = '', force = false) {
      const next = asText(kind || this.agentIterationActiveKind) || 'poi'
      if (next === 'poi') return this.ensureAgentIterationPoi(force)
      if (next === 'population') return this.ensureAgentIterationPopulation(force)
      return this.ensureAgentIterationNightlight(force)
    },
    resetAgentIterationChangeForHistorySwitch(historyId = '', options = {}) {
      const nextHistoryId = asText(historyId)
      if (!nextHistoryId) return false
      const previousHistoryId = asText(options.previousHistoryId || options.previous_history_id)
      if (previousHistoryId && previousHistoryId === nextHistoryId) return false

      const notice = '已切换历史记录，请重新生成多年迭代变化。'
      const now = new Date().toISOString()
      const buildIdlePayload = (kind) => ({
        status: 'idle',
        historyId: nextHistoryId,
        history_id: nextHistoryId,
        notice,
        error: '',
        reset_reason: 'history_switch',
        kind,
        updated_at: now,
      })
      const resetRoot = {
        poi: buildIdlePayload('poi'),
        population: buildIdlePayload('population'),
        nightlight: buildIdlePayload('nightlight'),
      }
      const resetPanelPayloads = (panelPayloads = {}) => ({
        ...cloneObject(panelPayloads),
        iteration_change: cloneObject(resetRoot),
      })

      const tabs = this.ensureAgentTabs(true)
      const iterationTabs = cloneArray(tabs.iterationChangeTabs)
      tabs.iterationChangeTabs = iterationTabs.map((item) => ({
        ...item,
        panelPayloads: resetPanelPayloads(item && item.panelPayloads),
      }))
      this.agentTabs = { ...tabs, iterationChangeTabs: cloneArray(tabs.iterationChangeTabs) }

      this.agentPanelPayloads = resetPanelPayloads(this.agentPanelPayloads)
      if (asText(this.getAgentActiveTopTab().kind) === 'iteration_change') {
        const activeId = asText(this.getAgentActiveTopTab().id)
        const activeTab = cloneArray(this.agentTabs.iterationChangeTabs).find((item) => item.id === activeId)
        if (activeTab && activeTab.panelPayloads && typeof activeTab.panelPayloads === 'object') {
          this.agentPanelPayloads = cloneObject(activeTab.panelPayloads)
        }
      }

      this.agentIterationPoiLoading = false
      this.agentIterationPoiError = ''
      this.agentIterationPopulationLoading = false
      this.agentIterationPopulationError = ''
      this.agentIterationNightlightLoading = false
      this.agentIterationNightlightError = ''
      if (typeof this.syncCurrentAgentSession === 'function') {
        this.syncCurrentAgentSession()
      }
      return true
    },
    async requestAgentPopulationTimeseries(period) {
      const polygon = this.getIsochronePolygonPayload()
      const res = await fetch('/api/v1/analysis/timeseries/population', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          polygon,
          coord_type: 'gcj02',
          period,
          layer_view: 'population_delta',
        }),
      })
      if (!res.ok) {
        let detail = ''
        try { detail = await res.text() } catch (_) {}
        throw new Error(detail || '人口时序变化请求失败')
      }
      return res.json()
    },
    commitAgentIterationPayload(kind = 'nightlight', patch = {}, options = {}) {
      const normalizedKind = asText(kind) || 'nightlight'
      const tabs = this.ensureAgentTabs(true)
      const activeId = asText(options.tabId) || asText(tabs.activeTabId)
      const targetTab = cloneArray(tabs.iterationChangeTabs).find((item) => item.id === activeId)
      const currentPayloads = targetTab && targetTab.panelPayloads && typeof targetTab.panelPayloads === 'object'
        ? cloneObject(targetTab.panelPayloads)
        : cloneObject(this.agentPanelPayloads)
      const currentRoot = cloneObject(currentPayloads.iteration_change)
      const nextPayload = {
        ...cloneObject(currentRoot[normalizedKind]),
        ...cloneObject(patch),
        updated_at: new Date().toISOString(),
      }
      const nextPayloads = {
        ...currentPayloads,
        iteration_change: {
          ...currentRoot,
          [normalizedKind]: nextPayload,
        },
      }
      tabs.iterationChangeTabs = cloneArray(tabs.iterationChangeTabs).map((item) => (
        item.id === activeId ? { ...item, panelPayloads: cloneObject(nextPayloads), activeKind: normalizedKind } : item
      ))
      this.agentTabs = { ...tabs, iterationChangeTabs: cloneArray(tabs.iterationChangeTabs) }
      if (asText(tabs.activeTabId) === activeId) {
        this.agentPanelPayloads = nextPayloads
      }
      this.syncCurrentAgentSession()
      return nextPayload
    },
    commitAgentIterationPopulationPayload(patch = {}, options = {}) {
      return this.commitAgentIterationPayload('population', patch, options)
    },
    commitAgentIterationPoiPayload(patch = {}, options = {}) {
      return this.commitAgentIterationPayload('poi', patch, options)
    },
    clearAgentIterationPoiNoticeIfReady(options = {}) {
      const readiness = this.getAgentIterationPoiReadiness()
      if (!readiness.ready) return this.getAgentIterationPoiPayload()
      return this.commitAgentIterationPoiPayload({ notice: '', error: '' }, options)
    },
    async ensureAgentIterationPopulation(force = false) {
      if (!this.getIsochronePolygonRing || !this.getIsochronePolygonRing()) {
        this.agentIterationPopulationError = '请先生成或选择分析范围'
        return null
      }
      const existing = this.getAgentIterationPopulationPayload()
      if (!force && asText(existing.status) === 'ready') return existing
      if (this.agentIterationPopulationLoading) return existing
      const targetTabId = asText(this.getAgentActiveTopTab().kind) === 'iteration_change'
        ? asText(this.getAgentActiveTopTab().id)
        : ''
      this.agentIterationPopulationLoading = true
      this.agentIterationPopulationError = ''
      this.commitAgentIterationPopulationPayload({ status: 'loading', error: '' }, { tabId: targetTabId })
      try {
        const metaRes = await fetch('/api/v1/analysis/timeseries/meta')
        if (!metaRes.ok) throw new Error(`/api/v1/analysis/timeseries/meta 请求失败(${metaRes.status})`)
        const meta = await metaRes.json()
        const period = asText(meta.default_population_period)
          || asText((cloneArray(meta.population_periods).slice(-1)[0] || {}).value)
          || '2024-2026'
        const timeseries = await this.requestAgentPopulationTimeseries(period)
        return this.commitAgentIterationPopulationPayload({
          status: 'ready',
          period,
          timeseries,
          series: cloneArray(timeseries.series),
          insights: cloneArray(timeseries.insights),
          error: '',
        }, { tabId: targetTabId })
      } catch (err) {
        const message = asText(err && err.message) || String(err)
        this.agentIterationPopulationError = message
        return this.commitAgentIterationPopulationPayload({ status: 'failed', error: message }, { tabId: targetTabId })
      } finally {
        this.agentIterationPopulationLoading = false
      }
    },
    getAgentPoiCategoryName(poi = {}) {
      return this.getAgentPoiTypeBreakdown(poi).category
    },
    getAgentPoiTypeBreakdown(poi = {}) {
      const rawType = asText(poi.type || poi.typecode || poi.type_code)
      let subcategoryId = ''
      if (rawType && typeof this.resolvePoiTypeId === 'function') {
        subcategoryId = asText(this.resolvePoiTypeId(rawType))
      }
      if (subcategoryId) {
        const subcategory = typeof this.getPoiTypeLabel === 'function'
          ? asText(this.getPoiTypeLabel(subcategoryId))
          : subcategoryId
        const parentId = this.typeIdToGroupId && this.typeIdToGroupId[subcategoryId]
          ? asText(this.typeIdToGroupId[subcategoryId])
          : ''
        const category = parentId && this.categoryById && this.categoryById[parentId]
          ? asText(this.categoryById[parentId].name)
          : (rawType && typeof this.resolvePoiCategory === 'function'
              ? asText((this.resolvePoiCategory(rawType) || {}).name)
              : '')
        return {
          category: category || '未分类',
          subcategory: subcategory || '未分类小类',
          subcategory_id: subcategoryId,
          raw_type: rawType,
        }
      }
      if (rawType && typeof this.resolvePoiCategory === 'function') {
        const category = this.resolvePoiCategory(rawType)
        if (category && category.name) {
          return {
            category: asText(category.name),
            subcategory: '未分类小类',
            subcategory_id: '',
            raw_type: rawType,
          }
        }
      }
      const labels = rawType.split(/[;|,，/]/).map((item) => asText(item)).filter(Boolean)
      return {
        category: labels[0] || '未分类',
        subcategory: labels[1] || labels[0] || '未分类小类',
        subcategory_id: '',
        raw_type: rawType,
      }
    },
    summarizeAgentIterationPois(pois = [], year = null) {
      const categoryCounts = new Map()
      const subcategoryCounts = new Map()
      const subcategoryParentMap = new Map()
      const categoryToSubcategoryCounts = new Map()
      const areaCounts = new Map()
      const points = []
      cloneArray(pois).forEach((poi) => {
        const typeInfo = this.getAgentPoiTypeBreakdown(poi)
        const category = asText(typeInfo.category) || '未分类'
        const subcategory = asText(typeInfo.subcategory) || '未分类小类'
        categoryCounts.set(category, (categoryCounts.get(category) || 0) + 1)
        subcategoryCounts.set(subcategory, (subcategoryCounts.get(subcategory) || 0) + 1)
        if (!subcategoryParentMap.has(subcategory)) subcategoryParentMap.set(subcategory, category)
        if (!categoryToSubcategoryCounts.has(category)) categoryToSubcategoryCounts.set(category, new Map())
        const childCounts = categoryToSubcategoryCounts.get(category)
        childCounts.set(subcategory, (childCounts.get(subcategory) || 0) + 1)
        const area = asText(poi.adname || poi.cityname || poi.pname) || '未知区域'
        areaCounts.set(area, (areaCounts.get(area) || 0) + 1)
        const location = Array.isArray(poi && poi.location) ? poi.location : []
        const lng = Number(location[0])
        const lat = Number(location[1])
        if (Number.isFinite(lng) && Number.isFinite(lat)) {
          points.push({ lng, lat, category, subcategory, area })
        }
      })
      const total = Math.max(1, cloneArray(pois).length)
      const sortCounts = (map, extra = () => ({})) => Array.from(map.entries())
        .map(([name, count]) => ({ name, count, ratio: Number(count || 0) / total, ...extra(name, count) }))
        .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, 'zh-CN'))
      const categoryToSubcategoryMix = {}
      categoryToSubcategoryCounts.forEach((childMap, category) => {
        const categoryTotal = Math.max(1, Number(categoryCounts.get(category) || 0))
        categoryToSubcategoryMix[category] = Array.from(childMap.entries())
          .map(([name, count]) => ({
            name,
            parent: category,
            count,
            ratio: Number(count || 0) / categoryTotal,
          }))
          .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, 'zh-CN'))
      })
      return {
        year: Number.isFinite(Number(year)) ? Number(year) : null,
        count: cloneArray(pois).length,
        category_count: categoryCounts.size,
        subcategory_count: subcategoryCounts.size,
        top_categories: sortCounts(categoryCounts).slice(0, 5),
        top_subcategories: sortCounts(subcategoryCounts, (name) => ({ parent: subcategoryParentMap.get(name) || '未分类' })),
        top_areas: sortCounts(areaCounts).slice(0, 5),
        category_counts: Object.fromEntries(categoryCounts.entries()),
        subcategory_counts: Object.fromEntries(subcategoryCounts.entries()),
        category_to_subcategory_mix: categoryToSubcategoryMix,
        area_counts: Object.fromEntries(areaCounts.entries()),
        points,
      }
    },
    buildAgentPoiCategoryStack(summaries = []) {
      const sorted = cloneArray(summaries).filter((item) => item && item.category_counts).sort((a, b) => Number(a.year || 0) - Number(b.year || 0))
      if (sorted.length < 2) return []
      const totals = new Map()
      sorted.forEach((summary) => {
        Object.entries(cloneObject(summary.category_counts)).forEach(([name, count]) => {
          totals.set(name, (totals.get(name) || 0) + Number(count || 0))
        })
      })
      const topNames = Array.from(totals.entries())
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'zh-CN'))
        .slice(0, 5)
        .map(([name]) => name)
      return sorted.map((summary) => {
        const counts = cloneObject(summary.category_counts)
        const total = Math.max(1, Number(summary.count || 0))
        const segments = topNames.map((name) => ({
          name,
          count: Number(counts[name] || 0),
          ratio: Number(counts[name] || 0) / total,
        }))
        const known = segments.reduce((sum, item) => sum + item.count, 0)
        if (Math.max(0, Number(summary.count || 0) - known) > 0) {
          segments.push({
            name: '其他',
            count: Math.max(0, Number(summary.count || 0) - known),
            ratio: Math.max(0, Number(summary.count || 0) - known) / total,
          })
        }
        return { year: summary.year, total: Number(summary.count || 0), segments }
      })
    },
    buildAgentPoiSubcategoryStack(summaries = []) {
      const sorted = cloneArray(summaries).filter((item) => item && item.subcategory_counts).sort((a, b) => Number(a.year || 0) - Number(b.year || 0))
      if (sorted.length < 2) return []
      const totals = new Map()
      const parentByName = new Map()
      sorted.forEach((summary) => {
        cloneArray(summary.top_subcategories).forEach((item) => {
          if (item && item.name && !parentByName.has(item.name)) parentByName.set(item.name, item.parent || '')
        })
        Object.entries(cloneObject(summary.subcategory_counts)).forEach(([name, count]) => {
          totals.set(name, (totals.get(name) || 0) + Number(count || 0))
        })
      })
      const topNames = Array.from(totals.entries())
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'zh-CN'))
        .slice(0, 6)
        .map(([name]) => name)
      return sorted.map((summary) => {
        const counts = cloneObject(summary.subcategory_counts)
        const total = Math.max(1, Number(summary.count || 0))
        const segments = topNames.map((name) => ({
          name,
          parent: parentByName.get(name) || '',
          count: Number(counts[name] || 0),
          ratio: Number(counts[name] || 0) / total,
        }))
        const known = segments.reduce((sum, item) => sum + item.count, 0)
        if (Math.max(0, Number(summary.count || 0) - known) > 0) {
          segments.push({
            name: '其他小类',
            parent: '',
            count: Math.max(0, Number(summary.count || 0) - known),
            ratio: Math.max(0, Number(summary.count || 0) - known) / total,
          })
        }
        return { year: summary.year, total: Number(summary.count || 0), segments }
      })
    },
    buildAgentPoiAreaHeatmaps(summaries = [], polygon = []) {
      const sorted = cloneArray(summaries).filter((item) => cloneArray(item.points).length).sort((a, b) => Number(a.year || 0) - Number(b.year || 0))
      if (!sorted.length) return []
      const viewport = this.buildAgentPoiAreaHeatmapViewport(sorted, polygon)
      if (!viewport) return []
      const view = cloneObject(viewport.view, { width: 100, height: 100 })
      const viewWidth = Math.max(1, Number(view.width || 100))
      const viewHeight = Math.max(1, Number(view.height || 100))
      return sorted.map((summary) => {
        const points = cloneArray(summary.points)
          .filter((point) => this.isAgentPoiAreaHeatmapPointInPolygon(point && point.lng, point && point.lat, polygon))
          .map((point) => ({
            ...this.projectAgentPoiAreaHeatmapPoint(point.lng, point.lat, viewport),
            area: asText(point.area),
            category: asText(point.category),
            subcategory: asText(point.subcategory),
          }))
        const gridSize = 12
        const cellCounts = new Map()
        const cellWidth = viewWidth / gridSize
        const cellHeight = viewHeight / gridSize
        points.forEach((point) => {
          const col = Math.max(0, Math.min(gridSize - 1, Math.floor(Number(point.x || 0) / cellWidth)))
          const row = Math.max(0, Math.min(gridSize - 1, Math.floor(Number(point.y || 0) / cellHeight)))
          const key = `${col}:${row}`
          cellCounts.set(key, (cellCounts.get(key) || 0) + 1)
        })
        const maxCellCount = Math.max(1, ...Array.from(cellCounts.values()))
        const cells = Array.from(cellCounts.entries())
          .map(([key, count]) => {
            const [col, row] = key.split(':').map((item) => Number(item))
            return {
              x: Number((col * cellWidth).toFixed(3)),
              y: Number((row * cellHeight).toFixed(3)),
              width: Number(cellWidth.toFixed(3)),
              height: Number(cellHeight.toFixed(3)),
              count,
              intensity: Number((count / maxCellCount).toFixed(4)),
            }
          })
          .sort((a, b) => Number(a.y || 0) - Number(b.y || 0) || Number(a.x || 0) - Number(b.x || 0))
        return {
          year: summary.year,
          points: points.slice(0, 260),
          cells,
          point_count: points.length,
          top_area: ((cloneArray(summary.top_areas)[0] || {}).name) || '',
        }
      })
    },
    buildAgentPoiAreaHeatmapBundle(summaries = [], polygon = []) {
      const normalizedPolygon = this.normalizeAgentPoiAreaHeatmapPolygon(polygon)
      const viewport = this.buildAgentPoiAreaHeatmapViewport(summaries, normalizedPolygon)
      return {
        area_heatmaps: this.buildAgentPoiAreaHeatmaps(summaries, normalizedPolygon),
        area_heatmap_basemap: this.buildAgentPoiAreaHeatmapBasemap(viewport),
        area_heatmap_boundary: normalizedPolygon.length >= 3 ? this.buildAgentPoiAreaHeatmapBoundary(normalizedPolygon, viewport) : [],
        area_heatmap_polygon: normalizedPolygon,
      }
    },
    buildAgentPoiRuleInsights(summaries = []) {
      const sorted = cloneArray(summaries).filter((item) => item && item.count !== undefined).sort((a, b) => Number(a.year || 0) - Number(b.year || 0))
      const latest = sorted[sorted.length - 1] || {}
      const formatTopSubcategories = (summary = {}, limit = 3) => cloneArray(summary.top_subcategories)
        .slice(0, limit)
        .map((item) => `${item.name}${item.parent ? `（${item.parent}）` : ''}`)
        .join('、')
      if (sorted.length < 2) {
        const topCategory = (cloneArray(latest.top_categories)[0] || {})
        const topSubcategory = (cloneArray(latest.top_subcategories)[0] || {})
        const subcategoryText = formatTopSubcategories(latest)
        const topArea = (cloneArray(latest.top_areas)[0] || {})
        return {
          summary: [
            `当前POI规模为 ${this.formatAgentIterationMetric(latest.count, 0)}，一级主导业态为${topCategory.name || '未分类'}。`,
            subcategoryText ? `关键小类集中在${subcategoryText}。` : '当前小类结构信号有限。',
            `${topArea.name || '主要区域'}为核心聚集区，呈现当前POI的主要空间承载。`,
          ],
          insights: {
            fastest_growth: '当前只有一个年份，暂无法判断增长最快行业。',
            declining_category: '当前只有一个年份，暂无法判断衰退行业。',
            emerging_area: topArea.name ? `当前核心承载片区：${topArea.name}` : '当前缺少可识别的增长片区信号。',
            structure_judgement: topCategory.name ? `一级业态以${topCategory.name}为主${topSubcategory.name ? `，内部小类以${topSubcategory.name}较突出` : ''}。` : '业态结构信号有限。',
          },
        }
      }
      const first = sorted[0]
      const last = sorted[sorted.length - 1]
      const firstCounts = cloneObject(first.category_counts)
      const lastCounts = cloneObject(last.category_counts)
      const firstSubCounts = cloneObject(first.subcategory_counts)
      const lastSubCounts = cloneObject(last.subcategory_counts)
      const names = Array.from(new Set([...Object.keys(firstCounts), ...Object.keys(lastCounts)]))
      const changes = names.map((name) => {
        const before = Number(firstCounts[name] || 0)
        const after = Number(lastCounts[name] || 0)
        return {
          name,
          before,
          after,
          delta: after - before,
          rate: before > 0 ? ((after - before) / before) : (after > 0 ? 1 : 0),
        }
      })
      const fastest = changes.filter((item) => item.delta > 0).sort((a, b) => b.rate - a.rate || b.delta - a.delta)[0]
      const declining = changes.filter((item) => item.delta < 0).sort((a, b) => a.rate - b.rate || a.delta - b.delta)[0]
      const subNames = Array.from(new Set([...Object.keys(firstSubCounts), ...Object.keys(lastSubCounts)]))
      const subChanges = subNames.map((name) => {
        const before = Number(firstSubCounts[name] || 0)
        const after = Number(lastSubCounts[name] || 0)
        const parent = ((cloneArray(last.top_subcategories).find((item) => item.name === name) || cloneArray(first.top_subcategories).find((item) => item.name === name) || {}).parent) || ''
        return {
          name,
          parent,
          before,
          after,
          delta: after - before,
          rate: before > 0 ? ((after - before) / before) : (after > 0 ? 1 : 0),
        }
      })
      const fastestSubcategory = subChanges.filter((item) => item.delta > 0).sort((a, b) => b.rate - a.rate || b.delta - a.delta)[0]
      const decliningSubcategory = subChanges.filter((item) => item.delta < 0).sort((a, b) => a.rate - b.rate || a.delta - b.delta)[0]
      const firstAreas = cloneObject(first.area_counts)
      const lastAreas = cloneObject(last.area_counts)
      const areaNames = Array.from(new Set([...Object.keys(firstAreas), ...Object.keys(lastAreas)]))
      const growthArea = areaNames.map((name) => ({
        name,
        before: Number(firstAreas[name] || 0),
        after: Number(lastAreas[name] || 0),
        delta: Number(lastAreas[name] || 0) - Number(firstAreas[name] || 0),
      })).filter((item) => item.delta > 0).sort((a, b) => b.delta - a.delta)[0]
      const growthAreaText = growthArea
        ? `${growthArea.name}内部 POI 增量较明显（+${growthArea.delta}）。`
        : '未形成可命名增长片区；需结合小类空间信号判断具体增量方向。'
      const topCategory = (cloneArray(last.top_categories)[0] || {})
      const topSubcategory = (cloneArray(last.top_subcategories)[0] || {})
      const topArea = (cloneArray(last.top_areas)[0] || {})
      const topRatio = Number(last.count || 0) > 0 ? Number(topCategory.count || 0) / Number(last.count || 0) : 0
      const totalDelta = Number(last.count || 0) - Number(first.count || 0)
      const subcategoryText = formatTopSubcategories(last)
      return {
        summary: [
          `当前POI规模为 ${this.formatAgentIterationMetric(last.count, 0)}，较${first.year || '首年'}${totalDelta >= 0 ? '增加' : '减少'} ${this.formatAgentIterationMetric(Math.abs(totalDelta), 0)}。`,
          `${topCategory.name || '主导业态'}占比约 ${(topRatio * 100).toFixed(1)}%，是当前一级主导业态。`,
          subcategoryText ? `小类层面以${subcategoryText}最为突出。` : '小类层面暂未形成清晰主导。',
          `${topArea.name || '主要区域'}为核心聚集区，承担最多POI分布。`,
          `业态结构整体${topRatio >= 0.25 ? '呈现较强主导业态特征' : '较分散'}。`,
        ],
        insights: {
          fastest_growth: fastest ? `${fastest.name}大类增长较快（${fastest.delta >= 0 ? '+' : ''}${fastest.delta}，${fastest.rate >= 0 ? '+' : ''}${(fastest.rate * 100).toFixed(1)}%）${fastestSubcategory ? `；小类增长最快为${fastestSubcategory.name}${fastestSubcategory.parent ? `（${fastestSubcategory.parent}）` : ''}，+${fastestSubcategory.delta}` : ''}` : '未发现明显增长行业。',
          declining_category: declining ? `${declining.name}大类下降明显（${declining.delta}，${(declining.rate * 100).toFixed(1)}%）${decliningSubcategory ? `；小类下降明显为${decliningSubcategory.name}${decliningSubcategory.parent ? `（${decliningSubcategory.parent}）` : ''}，${decliningSubcategory.delta}` : ''}` : '未发现明显衰退行业。',
          emerging_area: growthAreaText,
          structure_judgement: topCategory.name ? `一级结构偏向${topCategory.name}主导${topSubcategory.name ? `，其下小类${topSubcategory.name}表现突出` : ''}，需结合目标业态判断消费型/生产型属性。` : '结构判断信号有限。',
        },
      }
    },
    compactAgentPoiIterationH3Evidence(value = {}, cellLimit = 40, rowLimit = 20) {
      const source = cloneObject(value || {})
      const pickNumber = (item) => {
        const parsed = Number(item)
        return Number.isFinite(parsed) ? parsed : null
      }
      const pickCell = (cell = {}) => {
        const props = cell && typeof cell.properties === 'object' ? cell.properties : cell
        const h3Id = asText(props && props.h3_id)
        if (!h3Id) return null
        return {
          h3_id: h3Id,
          poi_count: pickNumber(props.poi_count),
          density_poi_per_km2: pickNumber(props.density_poi_per_km2),
          local_entropy: pickNumber(props.local_entropy),
          neighbor_mean_density: pickNumber(props.neighbor_mean_density),
          neighbor_mean_entropy: pickNumber(props.neighbor_mean_entropy),
          neighbor_count: pickNumber(props.neighbor_count),
          category_counts: cloneObject(props.category_counts || {}),
          gi_star_z_score: pickNumber(props.gi_star_z_score),
          gi_star_value: pickNumber(props.gi_star_value),
          lisa_i: pickNumber(props.lisa_i),
          lisa_z_score: pickNumber(props.lisa_z_score),
        }
      }
      const derived = cloneObject(source.derived_stats)
      const rowsFrom = (compactKey, legacyKey) => {
        const compact = cloneArray(derived[compactKey])
        if (compact.length) return compact.slice(0, rowLimit)
        return cloneArray(derived[legacyKey] && derived[legacyKey].rows).slice(0, rowLimit)
      }
      const summaryFrom = (compactKey, legacyKey) => {
        const compact = cloneObject(derived[compactKey])
        if (Object.keys(compact).length) return compact
        const legacy = cloneObject(derived[legacyKey])
        delete legacy.rows
        return legacy
      }
      const allCells = cloneArray(source.cells).map(pickCell).filter(Boolean)
      const cells = allCells.slice(0, cellLimit)
      return {
        evidence_version: asText(source.evidence_version) || 'poi_h3_evidence_v1',
        grid_type: asText(source.grid_type) || 'h3',
        usage: asText(source.usage) || 'POI-only spatial structure evidence; do not use it for population or nightlight coupling.',
        params: cloneObject(source.params),
        counts: {
          ...cloneObject(source.counts),
          cell_count: Number((source.counts && source.counts.cell_count) || allCells.length || 0) || 0,
          included_cell_count: cells.length,
        },
        metrics: cloneObject(source.metrics),
        summary: cloneObject(source.summary),
        charts: cloneObject(source.charts),
        cells,
        derived_stats: {
          structure_rows: rowsFrom('structure_rows', 'structureSummary'),
          typing_rows: rowsFrom('typing_rows', 'typingSummary'),
          lq_rows: rowsFrom('lq_rows', 'lqSummary'),
          gap_rows: rowsFrom('gap_rows', 'gapSummary'),
          structure_summary: summaryFrom('structure_summary', 'structureSummary'),
          typing_summary: summaryFrom('typing_summary', 'typingSummary'),
          lq_summary: summaryFrom('lq_summary', 'lqSummary'),
          gap_summary: summaryFrom('gap_summary', 'gapSummary'),
        },
        omitted: {
          cells_total: Number((source.omitted && source.omitted.cells_total) || allCells.length || 0) || 0,
          cells_included: cells.length,
          geometry_removed: true,
        },
        constraints: {
          poi_only: true,
          do_not_use_for_population_nightlight_coupling: true,
        },
      }
    },
    compactAgentPoiIterationYearlyGridEvidence(value = {}) {
      const source = cloneObject(value || {})
      const compactRaster = (item = {}) => ({
        year: item && item.year,
        status: asText(item && item.status) || 'ready',
        error: asText(item && item.error),
        grid_scope: asText((item && item.grid_scope) || source.raster_grid_scope) || 'poi_iteration_raster_per_year',
        raster_evidence: this.compactAgentPoiIterationRasterEvidence((item && item.raster_evidence) || {}, 20),
      })
      const compactH3 = (item = {}) => ({
        year: item && item.year,
        status: asText(item && item.status) || 'ready',
        error: asText(item && item.error),
        grid_scope: asText((item && item.grid_scope) || source.grid_scope) || 'poi_iteration_h3_per_year',
        h3_evidence: this.compactAgentPoiIterationH3Evidence((item && item.h3_evidence) || {}, 20, 12),
      })
      const h3Items = cloneArray(source.h3_items || source.items).map(compactH3)
      return {
        evidence_version: asText(source.evidence_version) || 'poi_iteration_yearly_grid_evidence_v1',
        years: cloneArray(source.years),
        grid_scope: asText(source.grid_scope) || 'poi_iteration_h3_per_year',
        grid_type: asText(source.grid_type) || 'h3',
        raster_grid_scope: asText(source.raster_grid_scope) || 'poi_iteration_raster_per_year',
        latest_year: source.latest_year || null,
        latest_h3_evidence: this.compactAgentPoiIterationH3Evidence(source.latest_h3_evidence || {}, 20, 12),
        items: h3Items,
        h3_items: h3Items,
        raster_items: cloneArray(source.raster_items).map(compactRaster),
      }
    },
    compactAgentPoiIterationRasterEvidence(value = {}, cellLimit = 40) {
      const source = cloneObject(value || {})
      return {
        evidence_version: asText(source.evidence_version) || 'poi_raster_grid_evidence_v1',
        grid_type: asText(source.grid_type) || 'raster',
        params: cloneObject(source.params),
        summary: cloneObject(source.summary),
        counts: cloneObject(source.counts),
        cells: cloneArray(source.cells).slice(0, cellLimit),
        constraints: {
          shared_cell_id: true,
          use_for_population_nightlight_coupling: true,
        },
      }
    },
    buildAgentPoiIterationEvidence(payload = {}) {
      const centerLng = Number(this.selectedPoint && this.selectedPoint.lng)
      const centerLat = Number(this.selectedPoint && this.selectedPoint.lat)
      const center = Number.isFinite(centerLng) && Number.isFinite(centerLat)
        ? [centerLng, centerLat]
        : undefined
      return {
        years: cloneArray(payload.years),
        center,
        summaries: cloneArray(payload.summaries).map((summary) => ({
          year: summary.year,
          count: summary.count,
          category_count: summary.category_count,
          top_categories: cloneArray(summary.top_categories),
          category_counts: cloneObject(summary.category_counts),
          subcategory_count: summary.subcategory_count,
          top_subcategories: cloneArray(summary.top_subcategories),
          subcategory_counts: cloneObject(summary.subcategory_counts),
          top_areas: cloneArray(summary.top_areas),
          category_to_subcategory_mix: cloneObject(summary.category_to_subcategory_mix),
          points: cloneArray(summary.points).map((point) => ({
            lng: Number(point.lng),
            lat: Number(point.lat),
            category: asText(point.category),
            subcategory: asText(point.subcategory),
            area: asText(point.area),
          })).filter((point) => Number.isFinite(point.lng) && Number.isFinite(point.lat)),
        })),
        trend_rows: cloneArray(payload.trend_rows),
        total_series: cloneArray(payload.total_series),
        category_stack: cloneArray(payload.category_stack).map((row) => ({
          year: row.year,
          segments: cloneArray(row.segments).map((segment) => ({
            name: segment.name,
            count: segment.count,
            ratio: segment.ratio,
          })),
        })),
        subcategory_stack: cloneArray(payload.subcategory_stack).map((row) => ({
          year: row.year,
          segments: cloneArray(row.segments).map((segment) => ({
            name: segment.name,
            parent: segment.parent,
            count: segment.count,
            ratio: segment.ratio,
          })),
        })),
        subcategory_trend_rows: cloneArray(payload.subcategory_trend_rows),
        area_heatmaps: cloneArray(payload.area_heatmaps).map((row) => ({
          year: row.year,
          point_count: row.point_count,
          top_area: row.top_area,
          points: cloneArray(row.points),
          cells: cloneArray(row.cells),
        })),
        area_heatmap_basemap: cloneObject(payload.area_heatmap_basemap),
        area_heatmap_boundary: cloneArray(payload.area_heatmap_boundary),
        area_heatmap_polygon: cloneArray(payload.area_heatmap_polygon),
        area_heatmap_snapshots: cloneArray(payload.area_heatmap_snapshots),
        h3_evidence: this.compactAgentPoiIterationH3Evidence(payload.h3_evidence || {}),
        yearly_grid_evidence: this.compactAgentPoiIterationYearlyGridEvidence(payload.yearly_grid_evidence || {}),
        rule_insights: cloneObject(payload.rule_insights),
      }
    },
    buildAgentPoiIterationAiEvidencePreview(payload = {}) {
      const evidence = this.buildAgentPoiIterationEvidence(payload)
      const summaries = cloneArray(evidence.summaries)
      const first = summaries[0] || {}
      const last = summaries[summaries.length - 1] || {}
      const getCounts = (summary, key) => cloneObject(summary && summary[key])
      const ratio = (count, total) => {
        const safeTotal = Math.max(0, Number(total || 0))
        return safeTotal > 0 ? Number((Number(count || 0) / safeTotal).toFixed(6)) : 0
      }
      const spatialRows = cloneArray(payload.subcategory_spatial_trend_rows)
      const spatialNames = new Set(spatialRows.map((row) => asText(row && row.name)).filter(Boolean))
      const parentLookup = new Map()
      summaries.forEach((summary) => {
        cloneArray(summary.top_subcategories).forEach((item) => {
          const name = asText(item && item.name)
          const parent = asText(item && item.parent)
          if (name && parent && !parentLookup.has(name)) parentLookup.set(name, parent)
        })
        Object.entries(cloneObject(summary.category_to_subcategory_mix)).forEach(([category, rows]) => {
          cloneArray(rows).forEach((item) => {
            const name = asText(item && item.name)
            const parent = asText((item && item.parent) || category)
            if (name && parent && !parentLookup.has(name)) parentLookup.set(name, parent)
          })
        })
      })
      const buildChanges = (key, limit, includeParent = false) => {
        const firstCounts = getCounts(first, key)
        const lastCounts = getCounts(last, key)
        const names = Array.from(new Set(Object.keys(firstCounts).concat(Object.keys(lastCounts)))).filter(Boolean)
        return names.map((name) => {
          const firstCount = Number(firstCounts[name] || 0)
          const lastCount = Number(lastCounts[name] || 0)
          const row = {
            name,
            first_count: firstCount,
            last_count: lastCount,
            delta: lastCount - firstCount,
            rate: firstCount > 0 ? Number(((lastCount - firstCount) / firstCount).toFixed(6)) : null,
            first_ratio: ratio(firstCount, first.count),
            last_ratio: ratio(lastCount, last.count),
            is_low_base: Math.max(firstCount, lastCount) < 10,
          }
          if (includeParent && parentLookup.get(name)) row.parent = parentLookup.get(name)
          if (includeParent && spatialNames.has(name)) row.has_spatial_signal = true
          return row
        }).sort((a, b) => {
          if (includeParent) {
            const spatialDelta = Number(!!b.has_spatial_signal) - Number(!!a.has_spatial_signal)
            if (spatialDelta) return spatialDelta
          }
          return Math.abs(Number(b.delta || 0)) - Math.abs(Number(a.delta || 0))
            || Number(b.last_ratio || 0) - Number(a.last_ratio || 0)
            || Number(b.last_count || 0) - Number(a.last_count || 0)
        }).slice(0, limit)
      }
      const materialChangeRows = (rows, direction, limit = 5) => {
        const sign = direction === 'growth' ? 1 : -1
        return cloneArray(rows)
          .filter((row) => Number(row && row.delta) * sign > 0)
          .sort((a, b) => Math.abs(Number(b.delta || 0)) - Math.abs(Number(a.delta || 0))
            || Number(!!a.is_low_base) - Number(!!b.is_low_base)
            || Number(b.last_ratio || 0) - Number(a.last_ratio || 0)
            || Number(b.last_count || 0) - Number(a.last_count || 0))
          .slice(0, limit)
      }
      const lowBaseGrowthRows = (rows, limit = 8) => cloneArray(rows)
        .filter((row) => row && row.is_low_base && Number(row.delta) > 0)
        .sort((a, b) => Number(b.rate || 0) - Number(a.rate || 0)
          || Math.abs(Number(b.delta || 0)) - Math.abs(Number(a.delta || 0)))
        .slice(0, limit)
      const growthAreaSignalRows = cloneArray(spatialRows)
        .filter((row) => Number(row && row.delta) > 0)
        .sort((a, b) => Number(b.delta || 0) - Number(a.delta || 0)
          || Number(b.centroid_shift_m || 0) - Number(a.centroid_shift_m || 0)
          || Number(b.hotspot_grid_count || 0) - Number(a.hotspot_grid_count || 0))
        .slice(0, 5)
        .map((row) => ({
          name: row.name,
          parent: row.parent,
          delta: row.delta,
          dominant_direction: row.dominant_direction,
          secondary_direction: row.secondary_direction,
          dominant_ring: row.dominant_ring,
          centroid_shift_direction: row.centroid_shift_direction,
          centroid_shift_m: row.centroid_shift_m,
          hotspot_grid_count: row.hotspot_grid_count,
          hotspot_grid_count_delta: row.hotspot_grid_count_delta,
          top_area: row.top_area,
        }))
      const areaName = cloneArray(last.top_areas)[0] && asText(cloneArray(last.top_areas)[0].name)
      const categoryChanges = buildChanges('category_counts', 12, false)
      const subcategoryChanges = buildChanges('subcategory_counts', 24, true)
      return {
        task: 'poi_iteration_change',
        evidence_version: 'poi_iteration_v1',
        years: cloneArray(evidence.years),
        scope: {
          center: evidence.center,
          area_name: areaName || '',
          scope_type: cloneArray(evidence.area_heatmap_polygon).length ? 'history_polygon' : 'point_bounds',
          polygon_point_count: cloneArray(evidence.area_heatmap_polygon).length,
        },
        year_summaries: summaries.map((summary) => ({
          year: summary.year,
          poi_count: summary.count,
          category_count: summary.category_count,
          top_categories: cloneArray(summary.top_categories).slice(0, 8),
          subcategory_count: summary.subcategory_count,
          top_subcategories: cloneArray(summary.top_subcategories).slice(0, 12),
          top_areas: cloneArray(summary.top_areas).slice(0, 8),
        })),
        trend_metrics: cloneArray(evidence.trend_rows),
        category_changes: categoryChanges,
        subcategory_changes: subcategoryChanges,
        material_change_highlights: {
          ranking_policy: 'primary_rank_by_absolute_delta_then_last_ratio_and_last_count; percentage_rate_is_secondary',
          category_growth: materialChangeRows(categoryChanges, 'growth', 5),
          category_decline: materialChangeRows(categoryChanges, 'decline', 5),
          subcategory_growth: materialChangeRows(subcategoryChanges, 'growth', 8),
          subcategory_decline: materialChangeRows(subcategoryChanges, 'decline', 8),
          low_base_growth_watchlist: lowBaseGrowthRows(categoryChanges.concat(subcategoryChanges), 8),
        },
        spatial_factors: cloneObject(payload.spatial_factors),
        subcategory_spatial_trends: spatialRows.slice(0, 30).map((row) => ({
          name: row.name,
          parent: row.parent,
          delta: row.delta,
          dominant_direction: row.dominant_direction,
          secondary_direction: row.secondary_direction,
          dominant_ring: row.dominant_ring,
          centroid_shift_direction: row.centroid_shift_direction,
          centroid_shift_m: row.centroid_shift_m,
          hotspot_grid_count: row.hotspot_grid_count,
          hotspot_grid_count_delta: row.hotspot_grid_count_delta,
          top_area: row.top_area,
        })),
        growth_area_signal: {
          label: 'growth_area_direction',
          interpretation_policy: 'describe internal growth direction/ring/hotspots inside the isochrone; do not require an administrative new area name',
          has_named_area: false,
          growth_rows: growthAreaSignalRows,
        },
        h3_evidence: cloneObject(evidence.h3_evidence),
        yearly_grid_evidence: cloneObject(evidence.yearly_grid_evidence),
        area_distribution: cloneArray(evidence.area_heatmaps).map((row) => ({
          year: row.year,
          point_count: row.point_count,
          top_area: row.top_area,
          hotspot_cell_count: cloneArray(row.cells).length,
          top_cells: cloneArray(row.cells)
            .slice()
            .sort((a, b) => Number(b.intensity || 0) - Number(a.intensity || 0))
            .slice(0, 12)
            .map((cell, index) => ({
              rank: index + 1,
              intensity: cell.intensity,
              poi_count: cell.count || cell.poi_count || cell.point_count,
            })),
        })),
        rule_insights: cloneObject(evidence.rule_insights),
        constraints: {
          no_invented_places: true,
          no_coordinate_reasoning: true,
          no_low_base_rate_as_primary: true,
          growth_ranking_policy: 'use material_change_highlights; rank by absolute delta before percentage rate',
          output_language: 'zh-CN',
        },
      }
    },
    async requestAgentPoiIterationAnalysis(payload = {}) {
      const res = await fetch('/api/v1/analysis/agent/iteration/poi/interpret', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ evidence: this.buildAgentPoiIterationEvidence(payload) }),
      })
      if (!res.ok) {
        let detail = ''
        try { detail = await res.text() } catch (_) {}
        throw new Error(detail || 'AI POI 趋势解析失败')
      }
      return res.json()
    },
    async requestAgentPoiIterationBuild({ historyId = '', years = [], center = undefined, h3Evidence = undefined, yearlyGridEvidence = undefined } = {}) {
      const res = await fetch('/api/v1/analysis/agent/iteration/poi/build', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          history_id: asText(historyId),
          years: cloneArray(years).map((item) => Number(item)).filter((item) => Number.isFinite(item)),
          center,
          h3_evidence: h3Evidence || (typeof this.buildAgentPoiH3Evidence === 'function' ? this.buildAgentPoiH3Evidence() : {}),
          yearly_grid_evidence: yearlyGridEvidence || this.getAgentIterationPoiPayload().yearly_grid_evidence || {},
        }),
      })
      if (!res.ok) {
        let detail = ''
        try { detail = await res.text() } catch (_) {}
        throw new Error(detail || 'POI 多年迭代聚合失败')
      }
      return res.json()
    },
    async ensureAgentIterationPoiAiAnalysis(payloadArg = null, options = {}) {
      const payload = payloadArg || this.getAgentIterationPoiPayload()
      if (asText(payload.status) !== 'ready') return payload
      if (this.hasAgentIterationPoiReport() || asText(payload.ai_status) === 'loading') return payload
      const tabId = asText(options.tabId)
      this.commitAgentIterationPoiPayload({ ai_status: 'loading', ai_error: '' }, tabId ? { tabId } : {})
      try {
        const aiResult = await this.requestAgentPoiIterationAnalysis(payload)
        return this.commitAgentIterationPoiPayload({
          ai_status: aiResult.status === 'ready' ? 'ready' : 'failed',
          ai_summary: [],
          ai_insights: {},
          driver_analysis: [],
          planning_implications: [],
          report_title: asText(aiResult.report_title),
          report_sections: cloneArray(aiResult.report_sections),
          report_content: asText(aiResult.report_content),
          spatial_factors: cloneObject(aiResult.spatial_factors),
          subcategory_spatial_trend_rows: cloneArray(aiResult.subcategory_spatial_trend_rows),
          subcategory_spatial_summary: cloneArray(aiResult.subcategory_spatial_summary),
          ai_prompt: asText(aiResult.ai_prompt),
          ai_prompt_payload_note: asText(aiResult.ai_prompt_payload_note),
          prompt_snapshot: cloneObject(aiResult.prompt_snapshot),
          prompt_snapshots: cloneObject(aiResult.prompt_snapshots),
          ai_error: aiResult.status === 'ready' ? '' : asText(aiResult.error),
        }, tabId ? { tabId } : {})
      } catch (err) {
        const message = asText(err && err.message) || String(err)
        return this.commitAgentIterationPoiPayload({
          ai_status: 'failed',
          ai_error: message,
        }, tabId ? { tabId } : {})
      }
    },
    buildAgentPoiTrendRows(summaries = []) {
      const sorted = cloneArray(summaries).filter((item) => item && item.count !== undefined)
      if (sorted.length < 2) return []
      const first = sorted[0]
      const last = sorted[sorted.length - 1]
      const firstCounts = cloneObject(first.category_counts)
      const lastCounts = cloneObject(last.category_counts)
      const categoryNames = Array.from(new Set([...Object.keys(firstCounts), ...Object.keys(lastCounts)]))
      const deltas = categoryNames.map((name) => ({
        name,
        delta: Number(lastCounts[name] || 0) - Number(firstCounts[name] || 0),
      })).sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta) || a.name.localeCompare(b.name, 'zh-CN'))
      const topIncrease = deltas.find((item) => item.delta > 0)
      const topDecrease = deltas.find((item) => item.delta < 0)
      const totalDelta = Number(last.count || 0) - Number(first.count || 0)
      return [
        { key: 'years', label: '覆盖年份', value: `${first.year || '-'}-${last.year || '-'}` },
        { key: 'total_delta', label: 'POI 首尾变化', value: `${totalDelta >= 0 ? '+' : ''}${this.formatAgentIterationMetric(totalDelta, 0)}` },
        { key: 'category_delta', label: '业态类型变化', value: `${Number(last.category_count || 0) - Number(first.category_count || 0) >= 0 ? '+' : ''}${Number(last.category_count || 0) - Number(first.category_count || 0)}` },
        { key: 'top_increase', label: '增长最明显业态', value: topIncrease ? `${topIncrease.name} +${topIncrease.delta}` : '-' },
        { key: 'top_decrease', label: '减少最明显业态', value: topDecrease ? `${topDecrease.name} ${topDecrease.delta}` : '-' },
        { key: 'latest_top', label: '末年第一业态', value: ((last.top_categories || [])[0] || {}).name || '-' },
      ]
    },
    buildAgentPoiSubcategoryTrendRows(summaries = []) {
      const sorted = cloneArray(summaries).filter((item) => item && item.count !== undefined)
      if (sorted.length < 2) return []
      const first = sorted[0]
      const last = sorted[sorted.length - 1]
      const firstCounts = cloneObject(first.subcategory_counts)
      const lastCounts = cloneObject(last.subcategory_counts)
      const names = Array.from(new Set([...Object.keys(firstCounts), ...Object.keys(lastCounts)]))
      const parentByName = {}
      cloneArray(first.top_subcategories).concat(cloneArray(last.top_subcategories)).forEach((item) => {
        if (item && item.name && !parentByName[item.name]) parentByName[item.name] = item.parent || ''
      })
      const deltas = names.map((name) => ({
        name,
        parent: parentByName[name] || '',
        delta: Number(lastCounts[name] || 0) - Number(firstCounts[name] || 0),
      })).sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta) || a.name.localeCompare(b.name, 'zh-CN'))
      const topIncrease = deltas.find((item) => item.delta > 0)
      const topDecrease = deltas.find((item) => item.delta < 0)
      const latestTop = (cloneArray(last.top_subcategories)[0] || {})
      return [
        { key: 'subcategory_delta', label: '小类类型变化', value: `${Number(last.subcategory_count || 0) - Number(first.subcategory_count || 0) >= 0 ? '+' : ''}${Number(last.subcategory_count || 0) - Number(first.subcategory_count || 0)}` },
        { key: 'top_subcategory_increase', label: '增长最明显小类', value: topIncrease ? `${topIncrease.name}${topIncrease.parent ? `（${topIncrease.parent}）` : ''} +${topIncrease.delta}` : '-' },
        { key: 'top_subcategory_decrease', label: '减少最明显小类', value: topDecrease ? `${topDecrease.name}${topDecrease.parent ? `（${topDecrease.parent}）` : ''} ${topDecrease.delta}` : '-' },
        { key: 'latest_top_subcategory', label: '末年第一小类', value: latestTop.name ? `${latestTop.name}${latestTop.parent ? `（${latestTop.parent}）` : ''}` : '-' },
      ]
    },
    async requestAgentPoiYearSnapshot(year) {
      const historyId = asText(this.currentHistoryRecordId)
      if (!historyId) throw new Error('当前没有可读取的历史记录')
      const res = await fetch(`/api/v1/analysis/history/${historyId}/pois?year=${Number(year)}`)
      if (!res.ok) {
        let detail = ''
        try { detail = await res.text() } catch (_) {}
        throw new Error(detail || `历史 POI ${year} 请求失败(${res.status})`)
      }
      return res.json()
    },
    commitAgentIterationPoiTaskBoardPatch(taskKey = '', patch = {}) {
      const key = asText(taskKey)
      if (!key) return this.getAgentIterationPoiPayload()
      const payload = this.getAgentIterationPoiPayload()
      const current = payload.task_board && typeof payload.task_board === 'object' ? payload.task_board : {}
      const tasks = this.getAgentIterationPoiTaskBoardTasks().map((task) => (
        task.key === key ? { ...task, ...cloneObject(patch) } : task
      ))
      return this.commitAgentIterationPoiPayload({
        task_board: {
          ...cloneObject(current),
          runState: tasks.some((task) => task.status === 'running') ? 'running' : asText(current.runState || 'idle'),
          tasks,
          lastRunAt: asText(current.lastRunAt) || new Date().toISOString(),
        },
      })
    },
    buildAgentPoiRasterGridEvidence() {
      const bundle = buildAnalysisTaskParamBundle(this, 'poi_raster_grid')
      const params = cloneObject(bundle.params || {})
      return {
        evidence_version: 'poi_raster_grid_evidence_v1',
        grid_type: 'raster',
        params: {
          poi_year: Number(this.poiYearSource || this.resultPoiYear || 0) || null,
          raster: cloneObject(params || {}),
        },
        summary: cloneObject(this.poiGridSummary || {}),
        counts: {
          grid_count: Number((this.poiGridSummary && this.poiGridSummary.grid_count) || cloneArray(this.poiGridFeatures).length || 0) || 0,
          active_cell_count: Number(this.poiGridSummary && this.poiGridSummary.active_cell_count || 0) || 0,
          assigned_poi_count: Number(this.poiGridSummary && this.poiGridSummary.assigned_poi_count || 0) || 0,
        },
        cells: cloneArray(this.poiGridFeatures).map((feature) => {
          const props = cloneObject(feature && feature.properties)
          return {
            cell_id: asText(props.cell_id || props.h3_id),
            poi_count: Number(props.poi_count || 0) || 0,
            density_poi_per_km2: Number(props.density_poi_per_km2 || 0) || 0,
            dominant_category: asText(props.dominant_category),
            dominant_category_name: asText(props.dominant_category_name),
            category_counts: cloneObject(props.category_counts),
          }
        }).filter((cell) => cell.cell_id).slice(0, 80),
      }
    },
    async buildAgentPoiYearlyGridEvidence(years = []) {
      const targetYears = cloneArray(years).map((item) => Number(item)).filter((item) => Number.isFinite(item)).sort((a, b) => a - b)
      const h3Items = []
      const publishProgress = () => {
        const readyItems = h3Items.filter((item) => asText(item.status) === 'ready')
        const latest = readyItems.slice().sort((a, b) => Number(a.year || 0) - Number(b.year || 0)).slice(-1)[0] || {}
        this.commitAgentIterationPoiPayload({
          yearly_grid_evidence: {
            evidence_version: 'poi_iteration_yearly_grid_evidence_v1',
            years: targetYears,
            grid_scope: 'poi_iteration_h3_per_year',
            grid_type: 'h3',
            items: cloneArray(h3Items),
            h3_items: cloneArray(h3Items),
            latest_year: latest.year || null,
            latest_h3_evidence: cloneObject(latest.h3_evidence || {}),
          },
          h3_evidence: cloneObject(latest.h3_evidence || {}),
        })
      }
      for (const year of targetYears) {
        h3Items.push({
          year,
          status: 'running',
          error: '',
          grid_scope: 'poi_iteration_h3_per_year',
          h3_evidence: {},
          run_id: '',
          progress: { status: 'running', stage: 'queued', message: '已接收请求，等待开始计算', step: 0, total: 7, elapsed_sec: 0, extra: { year } },
        })
        publishProgress()
        try {
          let h3 = null
          if (typeof this.ensurePoiGridResult === 'function') {
            h3 = await this.ensurePoiGridResult({ year, gridType: 'h3', force: false })
          } else {
            await this.selectAgentPoiYearForGrid(year)
            if (typeof this.selectAllH3PoiFilters === 'function') this.selectAllH3PoiFilters()
            const h3Run = typeof this.computeH3Analysis === 'function' ? await this.computeH3Analysis() : null
            h3 = {
              evidence: typeof this.buildAgentPoiH3Evidence === 'function' ? this.buildAgentPoiH3Evidence() : {},
              progress: cloneObject((h3Run && h3Run.progress) || this.h3AnalysisProgress || {}),
            }
          }
          h3Items[h3Items.length - 1] = {
            year,
            status: 'ready',
            error: '',
            grid_scope: 'poi_iteration_h3_per_year',
            h3_evidence: cloneObject(h3.evidence || {}),
            run_id: asText(((h3.progress || {}).run_id)),
            progress: cloneObject(h3.progress || {}),
          }
        } catch (err) {
          h3Items[h3Items.length - 1] = {
            year,
            status: 'failed',
            error: asText(err && err.message) || String(err),
            grid_scope: 'poi_iteration_h3_per_year',
            h3_evidence: {},
            run_id: '',
            progress: { status: 'failed', stage: 'failed', message: asText(err && err.message) || String(err), step: 7, total: 7, elapsed_sec: 0, extra: { year } },
          }
        }
        publishProgress()
      }
      const readyItems = h3Items.filter((item) => asText(item.status) === 'ready')
      const latest = readyItems.slice().sort((a, b) => Number(a.year || 0) - Number(b.year || 0)).slice(-1)[0] || {}
      return {
        evidence_version: 'poi_iteration_yearly_grid_evidence_v1',
        years: targetYears,
        grid_scope: 'poi_iteration_h3_per_year',
        grid_type: 'h3',
        items: h3Items,
        h3_items: h3Items,
        latest_year: latest.year || null,
        latest_h3_evidence: cloneObject(latest.h3_evidence || {}),
      }
    },
    async runAgentIterationPoiTask(taskKey = '') {
      const key = asText(taskKey)
      if (!['poi_fetch', 'poi_h3_grid'].includes(key)) return
      const startedAt = new Date().toISOString()
      this.commitAgentIterationPoiTaskBoardPatch(key, { status: 'running', startedAt, endedAt: '', error: '' })
      try {
        if (key === 'poi_fetch') {
          const years = this.getAgentIterationPoiTargetYears()
          this.poiYearSelections = years
          if (typeof this.fetchPois !== 'function') throw new Error('POI 抓取入口不可用')
          await this.fetchPois({ preserveCurrentPanel: true })
        } else {
          const years = this.getAgentIterationPoiTargetYears()
          for (const year of years) {
            if (typeof this.ensurePoiGridResult === 'function') {
              await this.ensurePoiGridResult({ year, gridType: 'h3', force: false })
            } else {
              await this.selectAgentPoiYearForGrid(year)
              if (typeof this.selectAllH3PoiFilters === 'function') this.selectAllH3PoiFilters()
              if (typeof this.computeH3Analysis === 'function') await this.computeH3Analysis()
            }
          }
          const evidence = await this.buildAgentPoiYearlyGridEvidence(years)
          const failedRows = cloneArray(evidence.h3_items || evidence.items)
          const failed = failedRows.find((item) => asText(item.status) === 'failed')
          if (failed) throw new Error(`${failed.year || ''} 年H3计算失败：${asText(failed.error)}`)
          this.commitAgentIterationPoiPayload({
            yearly_grid_evidence: evidence,
            h3_evidence: cloneObject(evidence.latest_h3_evidence || {}),
          })
          this.clearAgentIterationPoiNoticeIfReady()
        }
        this.commitAgentIterationPoiTaskBoardPatch(key, { status: 'completed', endedAt: new Date().toISOString(), error: '' })
      } catch (err) {
        const message = asText(err && err.message) || String(err)
        this.commitAgentIterationPoiTaskBoardPatch(key, { status: 'failed', endedAt: new Date().toISOString(), error: message })
        throw err
      }
    },
    async runAgentIterationPoiPrimaryAction() {
      const missing = this.getAgentIterationPoiTaskKeysToFill()
      if (missing.length) {
        for (const key of missing) {
          await this.runAgentIterationPoiTask(key)
        }
      } else {
        await this.runAgentIterationPoiTask('poi_fetch')
        await this.runAgentIterationPoiTask('poi_h3_grid')
      }
      const payload = await this.ensureAgentIterationPoi(true)
      if (asText(payload.status) === 'ready') this.setAgentIterationSecondaryView('ai', 'poi')
      return payload
    },
    async ensureAgentIterationPoi(force = false) {
      const existing = this.getAgentIterationPoiPayload()
      if (!force && asText(existing.status) === 'ready') {
        this.ensureAgentIterationPoiAreaHeatmapSnapshots(existing).catch((err) => {
          console.warn('[agent-iteration-poi] area snapshot generation failed', err)
        })
        return existing
      }
      if (this.agentIterationPoiLoading) return existing
      const targetTabId = asText(this.getAgentActiveTopTab().kind) === 'iteration_change'
        ? asText(this.getAgentActiveTopTab().id)
        : ''
      this.agentIterationPoiLoading = true
      this.agentIterationPoiError = ''
      this.commitAgentIterationPoiPayload({ status: 'loading', error: '' }, { tabId: targetTabId })
      try {
        const readiness = this.getAgentIterationPoiReadiness()
        if (!readiness.ready) {
          return this.commitAgentIterationPoiPayload({
            status: 'needs_data',
            source: 'readiness',
            years: cloneArray(readiness.years),
            error: '',
            notice: `多年 POI 分析还缺 ${readiness.missingTasks.map((key) => this.getAgentSummaryTaskLabel(key)).join('、')}，请先补齐。`,
          }, { tabId: targetTabId })
        }
        const historyYears = cloneArray(this.currentHistoryAvailablePoiYears)
          .map((item) => Number(item))
          .filter((item) => Number.isFinite(item))
          .sort((a, b) => a - b)
        const historyId = asText(this.currentHistoryRecordId)
        if (historyId && historyYears.length >= 2) {
          const centerLng = Number(this.selectedPoint && this.selectedPoint.lng)
          const centerLat = Number(this.selectedPoint && this.selectedPoint.lat)
          const center = Number.isFinite(centerLng) && Number.isFinite(centerLat)
            ? [centerLng, centerLat]
            : undefined
          const yearlyGridEvidence = this.getAgentIterationPoiYearlyGridEvidence()
          const latestH3 = cloneObject(yearlyGridEvidence.latest_h3_evidence)
          const latestH3HasMetrics = cloneArray(latestH3.cells).length || Object.keys(cloneObject(latestH3.summary)).length || Object.keys(cloneObject(latestH3.metrics)).length
          const h3Evidence = latestH3HasMetrics ? latestH3 : (typeof this.buildAgentPoiH3Evidence === 'function' ? this.buildAgentPoiH3Evidence() : {})
          const builtPayload = await this.requestAgentPoiIterationBuild({ historyId, years: historyYears, center, h3Evidence, yearlyGridEvidence })
          const committed = this.commitAgentIterationPoiPayload({
            status: asText(builtPayload.status) || 'ready',
            source: asText(builtPayload.source) || 'history',
            historyId,
            years: cloneArray(builtPayload.years),
            summaries: cloneArray(builtPayload.summaries),
            trend_rows: cloneArray(builtPayload.trend_rows),
            total_series: cloneArray(builtPayload.total_series),
            category_stack: cloneArray(builtPayload.category_stack),
            subcategory_stack: cloneArray(builtPayload.subcategory_stack),
            subcategory_trend_rows: cloneArray(builtPayload.subcategory_trend_rows),
            area_heatmaps: cloneArray(builtPayload.area_heatmaps),
            area_heatmap_basemap: cloneObject(builtPayload.area_heatmap_basemap),
            area_heatmap_boundary: cloneArray(builtPayload.area_heatmap_boundary),
            area_heatmap_polygon: cloneArray(builtPayload.area_heatmap_polygon),
            area_heatmap_snapshots: this.buildAgentPoiAreaHeatmapSnapshotPlaceholders(builtPayload),
            spatial_factors: cloneObject(builtPayload.spatial_factors),
            subcategory_spatial_trend_rows: cloneArray(builtPayload.subcategory_spatial_trend_rows),
            subcategory_spatial_summary: cloneArray(builtPayload.subcategory_spatial_summary),
            h3_evidence: cloneObject(builtPayload.h3_evidence || h3Evidence),
            yearly_grid_evidence: cloneObject(builtPayload.yearly_grid_evidence || yearlyGridEvidence),
            rule_summary: cloneArray(builtPayload.rule_summary),
            rule_insights: cloneObject(builtPayload.rule_insights),
            ai_summary: [],
            ai_insights: {},
            driver_analysis: [],
            planning_implications: [],
            report_title: asText(builtPayload.report_title),
            report_sections: cloneArray(builtPayload.report_sections),
            report_content: asText(builtPayload.report_content),
            ai_status: asText(builtPayload.ai_status) || (cloneArray(builtPayload.report_sections).length || asText(builtPayload.report_content) ? 'ready' : 'pending'),
            ai_error: asText(builtPayload.ai_error),
            error: asText(builtPayload.error),
            notice: '',
          }, { tabId: targetTabId })
          this.ensureAgentIterationPoiAreaHeatmapSnapshots(committed).catch((err) => {
            console.warn('[agent-iteration-poi] area snapshot generation failed', err)
          })
          this.ensureAgentIterationPoiAiAnalysis(committed, { tabId: targetTabId }).catch((err) => {
            console.warn('[agent-iteration-poi] ai analysis failed', err)
          })
          if (this.getAgentIterationSecondaryView('poi') === 'data') this.setAgentIterationSecondaryView('ai', 'poi')
          return committed
        }
        return this.commitAgentIterationPoiPayload({
          status: 'needs_data',
          source: 'readiness',
          years: cloneArray(this.getAgentIterationPoiTargetYears()),
          error: '',
          notice: '多年 POI 分析需要可读取的多年 POI 历史记录和年度网格证据，请先补齐。',
        }, { tabId: targetTabId })
      } catch (err) {
        const message = asText(err && err.message) || String(err)
        this.agentIterationPoiError = message
        return this.commitAgentIterationPoiPayload({ status: 'failed', error: message }, { tabId: targetTabId })
      } finally {
        this.agentIterationPoiLoading = false
      }
    },
    async requestAgentNightlightYearSnapshot(year) {
      const polygon = this.getIsochronePolygonPayload()
      const requestBody = { polygon, coord_type: 'gcj02', year: Number(year) || null }
      const overviewRes = await fetch('/api/v1/analysis/nightlight/overview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody),
      })
      if (!overviewRes.ok) {
        let detail = ''
        try { detail = await overviewRes.text() } catch (_) {}
        throw new Error(detail || `夜光${year}概览请求失败`)
      }
      const overview = await overviewRes.json()
      const gridPromise = fetch('/api/v1/analysis/nightlight/grid', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody),
      }).then(async (res) => {
        if (!res.ok) throw new Error(`夜光${year}格网请求失败`)
        return res.json()
      })
      const layerPromise = fetch('/api/v1/analysis/nightlight/layer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...requestBody,
          scope_id: overview.scope_id || null,
          view: 'radiance',
        }),
      }).then(async (res) => {
        if (!res.ok) throw new Error(`夜光${year}图层请求失败`)
        return res.json()
      })
      const rasterRes = await fetch('/api/v1/analysis/nightlight/raster', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...requestBody, scope_id: overview.scope_id || null }),
      })
      if (!rasterRes.ok) {
        let detail = ''
        try { detail = await rasterRes.text() } catch (_) {}
        throw new Error(detail || `夜光${year}快照请求失败`)
      }
      const raster = await rasterRes.json()
      const [gridResult, layerResult] = await Promise.allSettled([gridPromise, layerPromise])
      const grid = gridResult.status === 'fulfilled' ? gridResult.value : {}
      const layer = layerResult.status === 'fulfilled' ? layerResult.value : {}
      return {
        year: Number(year),
        summary: cloneObject(overview.summary || raster.summary),
        image_url: asText(raster.image_url),
        bounds_gcj02: cloneArray(raster.bounds_gcj02),
        legend: cloneObject(raster.legend),
        grid_features: cloneArray(grid.features),
        layer_cells: cloneArray(layer.cells),
        vector_legend: cloneObject(layer.legend),
        scope_id: asText(raster.scope_id || overview.scope_id),
      }
    },
    async requestAgentNightlightTimeseries(period) {
      const polygon = this.getIsochronePolygonPayload()
      const res = await fetch('/api/v1/analysis/timeseries/nightlight', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          polygon,
          coord_type: 'gcj02',
          period,
          layer_view: 'hotspot_shift',
        }),
      })
      if (!res.ok) {
        let detail = ''
        try { detail = await res.text() } catch (_) {}
        throw new Error(detail || '夜光热点迁移请求失败')
      }
      return res.json()
    },
    buildAgentNightlightIterationEvidence(payload = {}) {
      const snapshots = cloneArray(payload.snapshots).map((item) => ({
        year: item.year,
        summary: cloneObject(item.summary),
        has_image: !!item.image_url,
        has_vector: cloneArray(item.grid_features).length > 0 && cloneArray(item.layer_cells).length > 0,
        bounds_gcj02: cloneArray(item.bounds_gcj02),
      }))
      const timeseries = cloneObject(payload.timeseries)
      return {
        task: 'nightlight_iteration_change',
        evidence_version: 'nightlight_iteration_v1',
        years: cloneArray(payload.years),
        period: asText(payload.period),
        series: cloneArray(payload.series || timeseries.series),
        hotspot_shift: cloneObject((timeseries.layer || {}).summary),
        insights: cloneArray(timeseries.insights),
        snapshot_refs: snapshots,
      }
    },
    async requestAgentNightlightIterationAnalysis(payload = {}) {
      const res = await fetch('/api/v1/analysis/agent/iteration/nightlight/interpret', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ evidence: this.buildAgentNightlightIterationEvidence(payload) }),
      })
      if (!res.ok) {
        let detail = ''
        try { detail = await res.text() } catch (_) {}
        throw new Error(detail || 'AI夜光趋势解析失败')
      }
      return res.json()
    },
    commitAgentIterationNightlightPayload(patch = {}, options = {}) {
      const tabs = this.ensureAgentTabs(true)
      const activeId = asText(options.tabId) || asText(tabs.activeTabId)
      const targetTab = cloneArray(tabs.iterationChangeTabs).find((item) => item.id === activeId)
      const currentPayloads = targetTab && targetTab.panelPayloads && typeof targetTab.panelPayloads === 'object'
        ? cloneObject(targetTab.panelPayloads)
        : cloneObject(this.agentPanelPayloads)
      const currentRoot = cloneObject(currentPayloads.iteration_change)
      const nextNightlight = {
        ...cloneObject(currentRoot.nightlight),
        ...cloneObject(patch),
        updated_at: new Date().toISOString(),
      }
      const nextPayloads = {
        ...currentPayloads,
        iteration_change: {
          ...currentRoot,
          nightlight: nextNightlight,
        },
      }
      tabs.iterationChangeTabs = cloneArray(tabs.iterationChangeTabs).map((item) => (
        item.id === activeId ? { ...item, panelPayloads: cloneObject(nextPayloads), activeKind: 'nightlight' } : item
      ))
      this.agentTabs = { ...tabs, iterationChangeTabs: cloneArray(tabs.iterationChangeTabs) }
      if (asText(tabs.activeTabId) === activeId) {
        this.agentPanelPayloads = nextPayloads
      }
      this.syncCurrentAgentSession()
      return nextNightlight
    },
    async ensureAgentIterationNightlight(force = false) {
      if (!this.getIsochronePolygonRing || !this.getIsochronePolygonRing()) {
        this.agentIterationNightlightError = '请先生成或选择分析范围'
        return null
      }
      const existing = this.getAgentIterationNightlightPayload()
      if (!force && asText(existing.status) === 'ready' && cloneArray(existing.snapshots).length) return existing
      if (this.agentIterationNightlightLoading) return existing
      const targetTabId = asText(this.getAgentActiveTopTab().kind) === 'iteration_change'
        ? asText(this.getAgentActiveTopTab().id)
        : ''
      this.agentIterationNightlightLoading = true
      this.agentIterationNightlightError = ''
      this.commitAgentIterationNightlightPayload({ status: 'loading', error: '' }, { tabId: targetTabId })
      try {
        const metaRes = await fetch('/api/v1/analysis/timeseries/meta')
        if (!metaRes.ok) throw new Error(`/api/v1/analysis/timeseries/meta 请求失败(${metaRes.status})`)
        const meta = await metaRes.json()
        const years = cloneArray(meta.nightlight_years)
          .map((item) => Number(item))
          .filter((item) => Number.isFinite(item))
          .sort((a, b) => a - b)
          .slice(-3)
        if (years.length < 2) throw new Error('夜光多年数据不足')
        const period = `${years[0]}-${years[years.length - 1]}`
        const [timeseriesResult, ...snapshotResults] = await Promise.allSettled([
          this.requestAgentNightlightTimeseries(period),
          ...years.map((year) => this.requestAgentNightlightYearSnapshot(year)),
        ])
        const timeseries = timeseriesResult.status === 'fulfilled' ? timeseriesResult.value : {}
        const snapshots = snapshotResults.map((result, index) => {
          if (result.status === 'fulfilled') return result.value
          return { year: years[index], error: asText(result.reason && result.reason.message) || '快照加载失败' }
        })
        const basePayload = {
          status: 'analysis_loading',
          years,
          period,
          snapshots,
          timeseries,
          series: cloneArray(timeseries.series),
          error: '',
        }
        this.commitAgentIterationNightlightPayload(basePayload, { tabId: targetTabId })
        let aiResult = { status: 'failed', ai_analysis: {}, error: '' }
        try {
          aiResult = await this.requestAgentNightlightIterationAnalysis(basePayload)
        } catch (err) {
          aiResult = { status: 'failed', ai_analysis: {}, error: asText(err && err.message) || 'AI解析失败' }
        }
        return this.commitAgentIterationNightlightPayload({
          ...basePayload,
          status: aiResult.status === 'ready' ? 'ready' : 'ready_with_ai_error',
          ai_analysis: cloneObject(aiResult.ai_analysis),
          ai_prompt: asText(aiResult.ai_prompt),
          ai_prompt_payload_note: asText(aiResult.ai_prompt_payload_note),
          prompt_snapshot: cloneObject(aiResult.prompt_snapshot),
          ai_error: asText(aiResult.error),
        }, { tabId: targetTabId })
      } catch (err) {
        const message = asText(err && err.message) || String(err)
        this.agentIterationNightlightError = message
        return this.commitAgentIterationNightlightPayload({ status: 'failed', error: message }, { tabId: targetTabId })
      } finally {
        this.agentIterationNightlightLoading = false
      }
    },
    getAgentIterationSnapshotCells(snapshot = {}) {
      const features = cloneArray(snapshot.grid_features)
      const cells = cloneArray(snapshot.layer_cells)
      if (!features.length || !cells.length) return []
      const styleById = new Map(cells.map((cell) => [asText(cell && cell.cell_id), cloneObject(cell)]))
      const points = []
      features.forEach((feature) => {
        const rings = (((feature || {}).geometry || {}).coordinates || [])
        const outerRing = Array.isArray(rings[0]) ? rings[0] : []
        outerRing.forEach((point) => {
          if (Array.isArray(point) && Number.isFinite(Number(point[0])) && Number.isFinite(Number(point[1]))) {
            points.push([Number(point[0]), Number(point[1])])
          }
        })
      })
      if (!points.length) return []
      const xs = points.map((point) => point[0])
      const ys = points.map((point) => point[1])
      const minX = Math.min(...xs)
      const maxX = Math.max(...xs)
      const minY = Math.min(...ys)
      const maxY = Math.max(...ys)
      const spanX = Math.max(maxX - minX, 1e-9)
      const spanY = Math.max(maxY - minY, 1e-9)
      const width = 360
      const height = 260
      const pad = 14
      const scale = Math.min((width - pad * 2) / spanX, (height - pad * 2) / spanY)
      const offsetX = (width - spanX * scale) / 2
      const offsetY = (height - spanY * scale) / 2
      const project = (point) => {
        const x = offsetX + ((Number(point[0]) - minX) * scale)
        const y = height - offsetY - ((Number(point[1]) - minY) * scale)
        return `${x.toFixed(1)},${y.toFixed(1)}`
      }
      return features.map((feature, index) => {
        const props = cloneObject(feature && feature.properties)
        const cellId = asText(props.cell_id)
        const style = styleById.get(cellId) || {}
        const rawRings = (((feature || {}).geometry || {}).coordinates || [])
        const ring = Array.isArray(rawRings[0]) ? rawRings[0] : []
        const rawOpacity = Number(style.fill_opacity)
        const brightOpacity = Number.isFinite(rawOpacity)
          ? Math.min(0.92, Math.max(0.34, rawOpacity + 0.18))
          : 0.68
        return {
          key: cellId || `cell-${index}`,
          points: ring.map(project).join(' '),
          fill: asText(style.fill_color) || '#334155',
          opacity: brightOpacity,
          stroke: 'rgba(148, 163, 184, 0.28)',
        }
      }).filter((item) => item.points)
    },
    getAgentIterationSnapshotCellCount(snapshot = {}) {
      const cells = cloneArray(snapshot.layer_cells)
      if (cells.length) return cells.length
      return this.getAgentIterationSnapshotCells(snapshot).length
    },
    buildAgentIterationSnapshotCopyText(snapshot = {}) {
      const summary = cloneObject(snapshot.summary)
      return [
        `年份：${asText(snapshot.year) || '-'}`,
        `总辐亮：${this.formatAgentIterationMetric(summary.total_radiance, 1)}`,
        `均值：${this.formatAgentIterationMetric(summary.mean_radiance, 2)}`,
        `P90：${this.formatAgentIterationMetric(summary.p90_radiance, 2)}`,
        `点亮率：${this.formatAgentIterationPercent(summary.lit_pixel_ratio)}`,
        `快照格网数：${this.getAgentIterationSnapshotCellCount(snapshot)}`,
      ].join('\n')
    },
    buildAgentIterationSnapshotSvgMarkup(snapshot = {}) {
      const cells = this.getAgentIterationSnapshotCells(snapshot)
      if (!cells.length) return ''
      const year = asText(snapshot.year) || 'snapshot'
      const polygons = cells.map((cell) => (
        `<polygon points="${asText(cell.points)}" fill="${asText(cell.fill) || '#334155'}" fill-opacity="${Number(cell.opacity) || 0.68}" stroke="${asText(cell.stroke) || 'rgba(148, 163, 184, 0.28)'}" stroke-width="0.55"></polygon>`
      )).join('')
      return [
        '<svg xmlns="http://www.w3.org/2000/svg" width="720" height="520" viewBox="0 0 360 260" role="img">',
        '<defs><linearGradient id="agent-nightlight-copy-bg" x1="0" y1="0" x2="1" y2="1">',
        '<stop offset="0%" stop-color="#0f2347"></stop>',
        '<stop offset="58%" stop-color="#07152f"></stop>',
        '<stop offset="100%" stop-color="#020617"></stop>',
        '</linearGradient></defs>',
        `<title>${year} 夜光格网快照</title>`,
        '<rect x="0" y="0" width="360" height="260" rx="10" fill="url(#agent-nightlight-copy-bg)"></rect>',
        polygons,
        '</svg>',
      ].join('')
    },
    findAgentIterationSnapshotSvgFromEvent(event = null) {
      const target = event && event.currentTarget && typeof event.currentTarget.querySelector === 'function'
        ? event.currentTarget
        : null
      return target ? target.querySelector('.agent-iteration-snapshot-svg') : null
    },
    buildAgentIterationSnapshotSvgMarkupFromNode(svgNode = null, options = {}) {
      if (!svgNode || typeof XMLSerializer === 'undefined') return ''
      const cloned = svgNode.cloneNode(true)
      cloned.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
      const width = Number(options && options.width) || 360
      const height = Number(options && options.height) || 260
      cloned.setAttribute('width', String(Math.max(1, Math.round(width))))
      cloned.setAttribute('height', String(Math.max(1, Math.round(height))))
      cloned.querySelectorAll('.agent-iteration-heatmap-boundary').forEach((polygon) => {
        polygon.setAttribute('fill', '#2563eb')
        polygon.setAttribute('fill-opacity', polygon.getAttribute('fill-opacity') || '0.07')
        polygon.setAttribute('stroke', '#1d4ed8')
        polygon.setAttribute('stroke-width', polygon.getAttribute('stroke-width') || '0.72')
        polygon.setAttribute('stroke-linejoin', 'round')
        polygon.setAttribute('vector-effect', 'non-scaling-stroke')
      })
      cloned.querySelectorAll('.agent-iteration-heatmap-cell').forEach((rect) => {
        rect.setAttribute('fill', '#f97316')
        rect.setAttribute('stroke', '#7f1d1d')
        rect.setAttribute('stroke-opacity', rect.getAttribute('stroke-opacity') || '0.36')
        rect.setAttribute('stroke-width', rect.getAttribute('stroke-width') || '0.14')
      })
      cloned.querySelectorAll('.agent-iteration-heatmap-point').forEach((circle) => {
        circle.setAttribute('fill', '#0891b2')
        circle.setAttribute('stroke', '#f0fdfa')
        circle.setAttribute('stroke-opacity', circle.getAttribute('stroke-opacity') || '0.94')
        circle.setAttribute('stroke-width', circle.getAttribute('stroke-width') || '0.68')
        circle.setAttribute('paint-order', 'stroke fill')
        circle.setAttribute('vector-effect', 'non-scaling-stroke')
      })
      cloned.querySelectorAll('polygon').forEach((polygon) => {
        polygon.setAttribute('stroke-width', polygon.getAttribute('stroke-width') || '0.55')
      })
      return new XMLSerializer().serializeToString(cloned)
    },
    dataUrlToBlob(dataUrl = '') {
      const raw = asText(dataUrl)
      const match = raw.match(/^data:([^;,]+)(;base64)?,(.*)$/)
      if (!match) return null
      const mime = match[1] || 'image/png'
      const encoded = match[3] || ''
      if (match[2]) {
        const binary = atob(encoded)
        const bytes = new Uint8Array(binary.length)
        for (let index = 0; index < binary.length; index += 1) {
          bytes[index] = binary.charCodeAt(index)
        }
        return new Blob([bytes], { type: mime })
      }
      return new Blob([decodeURIComponent(encoded)], { type: mime })
    },
    async renderAgentIterationSnapshotPngBlob(snapshot = {}, svgNode = null) {
      const imageUrl = asText(snapshot.image_url)
      if (imageUrl.startsWith('data:image/png')) return this.dataUrlToBlob(imageUrl)
      const svgMarkup = this.buildAgentIterationSnapshotSvgMarkupFromNode(svgNode) || this.buildAgentIterationSnapshotSvgMarkup(snapshot)
      if (!svgMarkup || typeof document === 'undefined') return null
      const viewBox = svgNode && svgNode.viewBox && svgNode.viewBox.baseVal
        ? svgNode.viewBox.baseVal
        : null
      const baseWidth = Math.max(360, Math.round((viewBox && viewBox.width) || 360))
      const baseHeight = Math.max(260, Math.round((viewBox && viewBox.height) || 260))
      const scale = 4
      const svgBlob = new Blob([svgMarkup], { type: 'image/svg+xml;charset=utf-8' })
      const svgUrl = URL.createObjectURL(svgBlob)
      try {
        const image = await new Promise((resolve, reject) => {
          const img = new Image()
          img.onload = () => resolve(img)
          img.onerror = () => reject(new Error('snapshot_image_load_failed'))
          img.src = svgUrl
        })
        const canvas = document.createElement('canvas')
        canvas.width = baseWidth * scale
        canvas.height = baseHeight * scale
        const context = canvas.getContext('2d')
        if (!context) return null
        context.imageSmoothingEnabled = true
        context.imageSmoothingQuality = 'high'
        context.drawImage(image, 0, 0, canvas.width, canvas.height)
        return await new Promise((resolve) => {
          canvas.toBlob((blob) => resolve(blob), 'image/png')
        })
      } finally {
        URL.revokeObjectURL(svgUrl)
      }
    },
    getAgentIterationPoiAreaHeatmapViewportSize(viewport = null) {
      if (!viewport) return { width: 0, height: 0 }
      const rect = typeof viewport.getBoundingClientRect === 'function'
        ? viewport.getBoundingClientRect()
        : {}
      const width = Math.max(1, Math.round(Number(rect.width || viewport.clientWidth || viewport.offsetWidth || 0)))
      const height = Math.max(1, Math.round(Number(rect.height || viewport.clientHeight || viewport.offsetHeight || width || 0)))
      return { width, height }
    },
    async loadAgentIterationImageElement(src = '') {
      const url = asText(src)
      if (!url || typeof Image === 'undefined') return null
      return await new Promise((resolve, reject) => {
        const image = new Image()
        image.crossOrigin = 'anonymous'
        image.onload = () => resolve(image)
        image.onerror = () => reject(new Error('heatmap_image_load_failed'))
        image.src = url
      })
    },
    async renderAgentIterationPoiAreaHeatmapViewportBlob(cardNode = null) {
      if (!cardNode || typeof cardNode.querySelector !== 'function' || typeof document === 'undefined') return null
      const viewport = cardNode.querySelector('.agent-iteration-heatmap-viewport')
      if (!viewport) return null
      const size = this.getAgentIterationPoiAreaHeatmapViewportSize(viewport)
      if (!size.width || !size.height) return null
      const scale = 2
      const canvas = document.createElement('canvas')
      canvas.width = size.width * scale
      canvas.height = size.height * scale
      const context = canvas.getContext('2d')
      if (!context) return null
      context.fillStyle = '#ffffff'
      context.fillRect(0, 0, canvas.width, canvas.height)
      context.imageSmoothingEnabled = true
      context.imageSmoothingQuality = 'high'
      const imageNode = viewport.querySelector('img.agent-iteration-heatmap-img')
      const imageSrc = imageNode && imageNode.getAttribute ? asText(imageNode.getAttribute('src')) : ''
      if (imageSrc) {
        try {
          const image = await this.loadAgentIterationImageElement(imageSrc)
          if (image) context.drawImage(image, 0, 0, canvas.width, canvas.height)
        } catch (_) {}
      }
      const svgNode = viewport.querySelector('svg.agent-iteration-heatmap-svg')
      const svgMarkup = svgNode ? this.buildAgentIterationSnapshotSvgMarkupFromNode(svgNode, {
        width: canvas.width,
        height: canvas.height,
      }) : ''
      if (svgMarkup) {
        const svgUrl = URL.createObjectURL(new Blob([svgMarkup], { type: 'image/svg+xml;charset=utf-8' }))
        try {
          const overlay = await this.loadAgentIterationImageElement(svgUrl)
          if (overlay) context.drawImage(overlay, 0, 0, canvas.width, canvas.height)
        } finally {
          URL.revokeObjectURL(svgUrl)
        }
      }
      if (!imageSrc && !svgMarkup) return null
      return await new Promise((resolve) => {
        try {
          canvas.toBlob((blob) => resolve(blob), 'image/png')
        } catch (_) {
          resolve(null)
        }
      })
    },
    async copyAgentIterationSnapshotImage(snapshot = {}, svgNode = null) {
      const target = cloneObject(snapshot)
      const key = asText(target.year) || 'snapshot'
      this.agentIterationSnapshotCopyKey = key
      this.agentIterationSnapshotCopyStatus = '正在复制图片…'
      try {
        if (typeof navigator === 'undefined' || !navigator.clipboard || typeof navigator.clipboard.write !== 'function' || typeof ClipboardItem === 'undefined') {
          throw new Error('clipboard_image_unavailable')
        }
        const blob = await this.renderAgentIterationSnapshotPngBlob(target, svgNode)
        if (!blob) throw new Error('snapshot_image_unavailable')
        await navigator.clipboard.write([new ClipboardItem({ [blob.type || 'image/png']: blob })])
        this.agentIterationSnapshotCopyStatus = '图片已复制'
        this.agentIterationSnapshotDetailOpen = false
        this.agentIterationSnapshotDetail = null
      } catch (_) {
        this.agentIterationSnapshotDetail = target
        this.agentIterationSnapshotDetailOpen = true
        this.agentIterationSnapshotCopyStatus = '图片复制失败，可复制下方指标文本'
      }
    },
    async copyAgentIterationPoiAreaHeatmapImage(heatmap = {}, event = null) {
      const year = asText(heatmap && heatmap.year)
      if (!year) return
      const snapshot = {
        ...cloneObject(this.getAgentIterationPoiAreaHeatmapSnapshot(year)),
        year,
        image_url: asText((this.getAgentIterationPoiAreaHeatmapSnapshot(year) || {}).image_url),
        point_count: heatmap.point_count,
        top_area: heatmap.top_area,
      }
      this.agentIterationSnapshotCopyKey = `poi-area-${year}`
      this.agentIterationSnapshotCopyStatus = '正在复制图片…'
      try {
        if (typeof navigator === 'undefined' || !navigator.clipboard || typeof navigator.clipboard.write !== 'function' || typeof ClipboardItem === 'undefined') {
          throw new Error('clipboard_image_unavailable')
        }
        const cardNode = event && event.currentTarget ? event.currentTarget : null
        const blobPromise = (async () => {
          let blob = null
          if (cardNode) {
            blob = await this.renderAgentIterationPoiAreaHeatmapViewportBlob(cardNode)
          }
          if (!blob) {
            blob = asText(snapshot.image_url).startsWith('data:image/png')
              ? this.dataUrlToBlob(snapshot.image_url)
              : null
          }
          if (!blob) {
            blob = await this.renderAgentIterationSnapshotPngBlob(snapshot, cardNode && cardNode.querySelector ? cardNode.querySelector('svg') : null)
          }
          if (!blob) throw new Error('snapshot_image_unavailable')
          return blob.type === 'image/png' ? blob : new Blob([blob], { type: 'image/png' })
        })()
        await navigator.clipboard.write([new ClipboardItem({ 'image/png': blobPromise })])
        this.agentIterationSnapshotCopyKey = `poi-area-${year}`
        this.agentIterationSnapshotCopyStatus = '图片已复制'
      } catch (_) {
        this.agentIterationSnapshotCopyKey = `poi-area-${year}`
        this.agentIterationSnapshotCopyStatus = '图片复制失败，请重试'
      }
    },
    openAgentIterationSnapshotDetail(snapshot = {}, event = null) {
      if (!snapshot || typeof snapshot !== 'object' || asText(snapshot.error)) return
      const hasVector = this.getAgentIterationSnapshotCells(snapshot).length > 0
      const hasImage = !!asText(snapshot.image_url)
      if (!hasVector && !hasImage) return
      this.copyAgentIterationSnapshotImage(snapshot, this.findAgentIterationSnapshotSvgFromEvent(event))
    },
    closeAgentIterationSnapshotDetail() {
      this.agentIterationSnapshotDetailOpen = false
      this.agentIterationSnapshotDetail = null
      this.agentIterationSnapshotCopyStatus = ''
      this.agentIterationSnapshotCopyKey = ''
    },
    async copyAgentIterationSnapshotDetail() {
      const snapshot = cloneObject(this.agentIterationSnapshotDetail)
      const text = this.buildAgentIterationSnapshotCopyText(snapshot)
      if (!text.trim()) {
        this.agentIterationSnapshotCopyStatus = '无可复制内容'
        return
      }
      try {
        if (typeof navigator === 'undefined' || !navigator.clipboard || typeof navigator.clipboard.writeText !== 'function') {
          throw new Error('clipboard_unavailable')
        }
        await navigator.clipboard.writeText(text)
        this.agentIterationSnapshotCopyStatus = '已复制'
      } catch (_) {
        this.agentIterationSnapshotCopyStatus = '复制失败，请手动复制下方文本'
      }
    },
    getAgentIterationAiErrorLabel(error = '') {
      const raw = asText(error)
      if (!raw) return ''
      if (/ai_timeout/i.test(raw)) return '基础统计和快照已完成，AI 深度解读仍在补充。'
      if (/llm_unavailable/i.test(raw)) return 'AI 服务暂未启用，当前先展示结构化变化指标与年度快照。'
      if (/invalid_ai_analysis/i.test(raw)) return 'AI 解析结果格式异常，当前先展示结构化变化指标与年度快照。'
      return raw
    },
    shouldShowAgentComposer() {
      const activeTab = this.getAgentActiveTopTab()
      return ['followup', 'deep_analysis'].includes(asText(activeTab.kind))
    },
    buildAgentTabsUiState() {
      this.captureAgentActiveSummaryTabState()
      this.captureAgentActiveSiteSelectionTabState()
      this.captureAgentActiveDeepAnalysisTabState()
      this.captureAgentActiveFollowupTabState()
      const tabs = this.ensureAgentTabs(true)
      const currentSummaryTab = cloneArray(tabs.summaryTabs).find((item) => asText(item.source) === 'current') || null
      return {
        summary_tab: {
          id: asText((currentSummaryTab || {}).id || (tabs.summaryTab || {}).id) || 'summary',
          frozen: true,
          created_at: asText((currentSummaryTab || {}).createdAt || (tabs.summaryTab || {}).createdAt) || new Date().toISOString(),
          content: cloneObject((currentSummaryTab || {}).content || (tabs.summaryTab || {}).content),
          evidence_refs: cloneArray((currentSummaryTab || {}).evidenceRefs || (tabs.summaryTab || {}).evidenceRefs),
        },
        summary_tabs: cloneArray(tabs.summaryTabs).map((item) => ({
          id: item.id,
          title: item.title || '区域总结',
          kind: 'summary',
          source: item.source || 'history',
          session_id: item.sessionId || '',
          readonly: Object.prototype.hasOwnProperty.call(item || {}, 'readonly') ? !!item.readonly : false,
          created_at: item.createdAt,
          panel_payloads: cloneObject(item.panelPayloads),
          content: cloneObject(item.content),
          evidence_refs: cloneArray(item.evidenceRefs),
        })),
        iteration_change_tabs: cloneArray(tabs.iterationChangeTabs).map((item) => ({
          id: item.id,
          title: item.title || '多年迭代变化',
          kind: 'iteration_change',
          source: item.source || 'draft',
          session_id: item.sessionId || '',
          readonly: !!item.readonly,
          created_at: item.createdAt,
          active_kind: item.activeKind || 'nightlight',
          panel_payloads: cloneObject(item.panelPayloads || this.agentPanelPayloads),
        })),
        site_selection_tabs: cloneArray(tabs.siteSelectionTabs).map((item) => ({
          id: item.id,
          title: item.title || '区域内选址',
          kind: 'site_selection',
          source: item.source || 'draft',
          session_id: item.sessionId || '',
          readonly: !!item.readonly,
          created_at: item.createdAt,
          panel_payloads: cloneObject(item.panelPayloads || this.agentPanelPayloads),
        })),
        deep_analysis_tabs: cloneArray(tabs.deepAnalysisTabs).map((item) => ({
          id: item.id,
          title: item.title || '继续分析',
          kind: 'deep_analysis',
          source: item.source || 'draft',
          session_id: item.sessionId || '',
          readonly: !!item.readonly,
          created_at: item.createdAt,
          target: this.normalizeContextAskTarget(item.target),
          question: asText(item.question),
          mode: asText(item.mode) || 'quick',
          result_module_id: asText(item.resultModuleId || item.result_module_id),
          thread: this.createAgentFollowupThreadState(item.thread),
          panel_payloads: cloneObject(item.panelPayloads || this.agentPanelPayloads),
        })),
        followup_tabs: cloneArray(tabs.followupTabs).map((item) => ({
          id: item.id,
          title: item.title,
          kind: 'followup',
          source: item.source || 'draft',
          session_id: item.sessionId || '',
          readonly: !!item.readonly,
          linked_summary_id: item.linkedSummaryId || 'summary',
          created_at: item.createdAt,
          thread: this.createAgentFollowupThreadState(item.thread),
        })),
        active_tab_id: asText(tabs.activeTabId),
        followup_limit: Number(tabs.followupLimit || 6) || 6,
        next_followup_number: Number(tabs.nextFollowupNumber || 1) || 1,
      }
    },
    restoreAgentTabsFromSession(session = null) {
      const panelPayloads = cloneObject((session && session.panelPayloads) || this.agentPanelPayloads)
      const uiState = panelPayloads.agent_tabs && typeof panelPayloads.agent_tabs === 'object'
        ? panelPayloads.agent_tabs
        : {}
      const defaultTabs = this.createDefaultAgentTabs()
      const summaryTab = {
        id: asText((uiState.summary_tab || {}).id) || 'summary',
        kind: 'summary',
        frozen: true,
        source: 'current',
        sessionId: '',
        title: '区域总结',
        createdAt: asText((uiState.summary_tab || {}).created_at) || new Date().toISOString(),
        content: cloneObject((uiState.summary_tab || {}).content),
        evidenceRefs: cloneArray((uiState.summary_tab || {}).evidence_refs),
      }
      const summaryTabs = cloneArray(uiState.summary_tabs).map((item) => ({
        id: asText(item && item.id),
        kind: 'summary',
        title: asText(item && item.title) || '区域总结',
        source: asText(item && item.source) || 'history',
        sessionId: asText((item && (item.session_id || item.sessionId)) || ''),
        readonly: Object.prototype.hasOwnProperty.call(item || {}, 'readonly') ? !!item.readonly : false,
        createdAt: asText(item && item.created_at) || new Date().toISOString(),
        panelPayloads: cloneObject(item && (item.panel_payloads || item.panelPayloads)),
        content: cloneObject(item && item.content),
        evidenceRefs: cloneArray(item && item.evidence_refs),
      })).filter((item) => item.id)
      if (summaryTab.id && !summaryTabs.some((item) => asText(item.source) === 'current')) {
        const legacyPack = cloneObject(summaryTab.content)
        if (this.hasAgentSummaryPack(legacyPack) || Object.keys(legacyPack).length || asText(uiState.active_tab_id) === 'summary') {
          summaryTabs.unshift({
            id: 'summary-current',
            kind: 'summary',
            title: this.getAgentSummaryViewTitle({ summary_pack: legacyPack }, '区域总结'),
            source: 'current',
            sessionId: '',
            readonly: false,
            createdAt: summaryTab.createdAt,
            panelPayloads: cloneObject(panelPayloads),
            content: legacyPack,
            evidenceRefs: cloneArray(summaryTab.evidenceRefs),
          })
        }
      }
      const followupTabs = cloneArray(uiState.followup_tabs).map((item) => ({
        id: asText(item && item.id),
        kind: 'followup',
        title: this.getAgentFollowupViewTitle(item, item && item.title),
        linkedSummaryId: asText(item && item.linked_summary_id) || 'summary',
        source: asText(item && item.source) || 'draft',
        sessionId: asText((item && (item.session_id || item.sessionId)) || ''),
        readonly: !!(item && item.readonly && asText(item && item.source) !== 'history'),
        createdAt: asText(item && item.created_at) || new Date().toISOString(),
        thread: this.createAgentFollowupThreadState(item && item.thread),
      })).filter((item) => item.id)
      const iterationChangeTabs = cloneArray(uiState.iteration_change_tabs || uiState.iterationChangeTabs).map((item) => ({
        id: asText(item && item.id),
        kind: 'iteration_change',
        title: asText(item && item.title) || '多年迭代变化',
        source: asText(item && item.source) || 'draft',
        sessionId: asText((item && (item.session_id || item.sessionId)) || ''),
        readonly: !!(item && item.readonly && asText(item && item.source) !== 'history'),
        createdAt: asText(item && item.created_at) || new Date().toISOString(),
        activeKind: asText(item && (item.active_kind || item.activeKind)) || 'poi',
        panelPayloads: cloneObject(item && (item.panel_payloads || item.panelPayloads)),
      })).filter((item) => item.id)
      const siteSelectionTabs = cloneArray(uiState.site_selection_tabs || uiState.siteSelectionTabs).map((item) => ({
        id: asText(item && item.id),
        kind: 'site_selection',
        title: asText(item && item.title) || '区域内选址',
        source: asText(item && item.source) || 'draft',
        sessionId: asText((item && (item.session_id || item.sessionId)) || ''),
        readonly: !!(item && item.readonly && asText(item && item.source) !== 'history'),
        createdAt: asText(item && item.created_at) || new Date().toISOString(),
        panelPayloads: cloneObject(item && (item.panel_payloads || item.panelPayloads)),
      })).filter((item) => item.id)
      const deepAnalysisTabs = cloneArray(uiState.deep_analysis_tabs || uiState.deepAnalysisTabs).map((item) => ({
        id: asText(item && item.id),
        kind: 'deep_analysis',
        title: asText(item && item.title) || '继续分析',
        source: asText(item && item.source) || 'draft',
        sessionId: asText((item && (item.session_id || item.sessionId)) || ''),
        readonly: !!(item && item.readonly && asText(item && item.source) !== 'history'),
        createdAt: asText(item && item.created_at) || new Date().toISOString(),
        target: this.normalizeContextAskTarget(item && item.target),
        question: asText(item && item.question),
        mode: asText(item && item.mode) || 'quick',
        resultModuleId: asText(item && (item.result_module_id || item.resultModuleId)),
        thread: this.createAgentFollowupThreadState(item && item.thread),
        panelPayloads: cloneObject(item && (item.panel_payloads || item.panelPayloads)),
      })).filter((item) => item.id)
      const activeId = asText(uiState.active_tab_id)
      this.agentTabs = {
        summaryTab: summaryTab.id ? summaryTab : defaultTabs.summaryTab,
        summaryTabs,
        iterationChangeTabs,
        siteSelectionTabs,
        deepAnalysisTabs,
        followupTabs,
        activeTabId: activeId || (summaryTabs[0] ? summaryTabs[0].id : (iterationChangeTabs[0] ? iterationChangeTabs[0].id : (siteSelectionTabs[0] ? siteSelectionTabs[0].id : (deepAnalysisTabs[0] ? deepAnalysisTabs[0].id : (followupTabs[0] ? followupTabs[0].id : ''))))),
        followupLimit: Number(uiState.followup_limit || 6) || 6,
        nextFollowupNumber: Number(uiState.next_followup_number || (followupTabs.length + 1) || 1) || 1,
      }
      this.ensureAgentTabs(true)
      if (!this.isAgentSummaryTabActive()) {
        const activeTopTab = this.getAgentActiveTopTab()
        if (asText(activeTopTab.kind) === 'iteration_change') {
          const activeIteration = cloneArray(this.agentTabs.iterationChangeTabs).find((item) => item.id === this.agentTabs.activeTabId)
          if (activeIteration && activeIteration.panelPayloads && typeof activeIteration.panelPayloads === 'object') {
            this.agentPanelPayloads = cloneObject(activeIteration.panelPayloads)
          }
          this.agentIterationActiveKind = asText(activeIteration && activeIteration.activeKind) || 'poi'
        } else if (asText(activeTopTab.kind) === 'site_selection') {
          const activeSiteSelection = cloneArray(this.agentTabs.siteSelectionTabs).find((item) => item.id === this.agentTabs.activeTabId)
          if (activeSiteSelection && activeSiteSelection.panelPayloads && typeof activeSiteSelection.panelPayloads === 'object') {
            this.agentPanelPayloads = cloneObject(activeSiteSelection.panelPayloads)
          }
        } else if (asText(activeTopTab.kind) === 'deep_analysis') {
          const activeDeepAnalysis = cloneArray(this.agentTabs.deepAnalysisTabs).find((item) => item.id === this.agentTabs.activeTabId)
          if (activeDeepAnalysis) {
            this.applyAgentFollowupThreadToCurrentState(activeDeepAnalysis.thread)
            if (activeDeepAnalysis.panelPayloads && typeof activeDeepAnalysis.panelPayloads === 'object') {
              this.agentPanelPayloads = cloneObject(activeDeepAnalysis.panelPayloads)
            }
          }
        } else {
          const activeTab = this.getAgentActiveFollowupTab()
          if (activeTab) {
            this.applyAgentFollowupThreadToCurrentState(activeTab.thread)
          }
        }
      } else if (this.isCurrentAgentSummaryTabActive()) {
        const activeSummaryTab = cloneArray(this.agentTabs.summaryTabs).find((item) => item.id === this.agentTabs.activeTabId)
        if (activeSummaryTab && activeSummaryTab.panelPayloads && typeof activeSummaryTab.panelPayloads === 'object') {
          this.agentPanelPayloads = cloneObject(activeSummaryTab.panelPayloads)
        }
        this.syncAgentSummaryStateFromPanelPayload(this.agentPanelPayloads)
      }
    },
    queueAgentPrompt(prompt = '') {
      const text = String(prompt || '').trim()
      this.openAgentPanel()
      this.agentWorkspaceView = 'report'
      this.ensureAgentFollowupTabForPrompt(text)
      this.agentInput = text
      this.closeAgentComposerMenu()
      this.syncCurrentAgentSession()
    },
    getAgentToolLabel(value = '') {
      const mapping = {
        information: '信息',
        action: '执行',
        processing: '处理',
        foundation: '基础工具',
        capability: '能力工具',
        scenario: '场景工具',
        poi: 'POI',
        grid: '网格/H3',
        population: '人口',
        nightlight: '夜光',
        road: '路网',
        commerce: '商业',
        general: '通用',
        fetch: '获取',
        transform: '清洗/转换',
        analyze: '分析',
        interpret: '解释',
        decide: '决策',
        none: '未分类',
        area_character: '区域特征',
        site_selection: '选址分析',
        vitality: '活力评估',
        tod: 'TOD/站点规划',
        livability: '宜居评估',
        facility_gap: '设施缺口',
        renewal_priority: '更新优先级',
        primary: '主要',
        secondary: '次要',
        hidden: '隐含',
        safe: '低',
        normal: '中',
        expensive: '高',
        guarded: '需确认',
      }
      const key = asText(value)
      return mapping[key] || key || '-'
    },
    getAgentToolSchemaFields(schema = {}) {
      const properties = schema && typeof schema === 'object' && schema.properties && typeof schema.properties === 'object'
        ? schema.properties
        : {}
      return Object.keys(properties)
    },
    setAgentToolsViewMode(mode = 'tools') {
      const next = asText(mode) === 'input_packages' ? 'input_packages' : 'tools'
      this.agentToolsViewMode = next
    },
    countObjectKeys(value = null) {
      return value && typeof value === 'object' && !Array.isArray(value) ? Object.keys(value).length : 0
    },
    summarizeAgentInputPackage(value = null) {
      if (Array.isArray(value)) return `${value.length} 项`
      if (!value || typeof value !== 'object') return asText(value) || '-'
      const parts = []
      const version = asText(value.evidence_version || value.version)
      if (version) parts.push(`版本 ${version}`)
      const counts = value.counts && typeof value.counts === 'object' ? value.counts : {}
      Object.entries(counts).slice(0, 4).forEach(([key, val]) => {
        if (val !== undefined && val !== null && asText(val) !== '') parts.push(`${key}: ${val}`)
      })
      if (!parts.length) {
        const keys = Object.keys(value)
        if (keys.length) parts.push(`${keys.length} 个字段`)
      }
      return parts.join(' · ') || '-'
    },
    getBasisValidationResultItems() {
      const payload = this.getBasisDrawerPayload()
      const validationResults = payload.validationResults && typeof payload.validationResults === 'object'
        ? payload.validationResults
        : {}
      return Object.entries(validationResults).map(([key, item]) => ({
        key,
        title: asText((item && item.prompt_key) || key),
        status: asText(item && item.status) || 'unknown',
        note: asText(item && item.note),
        evidenceVersion: asText(item && item.evidence_version),
        outputSchema: cloneObject(item && item.output_schema),
        validatedOutput: cloneObject(item && item.validated_output),
        checks: cloneArray(item && item.checks),
      }))
    },
    getAgentInputPackageStatus(item = {}) {
      const value = item && typeof item === 'object' ? item.rawInput : null
      if (!value || (typeof value === 'object' && !Array.isArray(value) && !Object.keys(value).length)) return 'missing'
      if (item.requiredVersion && asText(value.evidence_version) !== asText(item.requiredVersion)) return 'partial'
      if (item.key === 'shared_grid' && Number(value.counts && value.counts.complete_overlap_cells || 0) <= 0) return 'partial'
      return 'ready'
    },
    getAgentInputPackageStatusLabel(item = {}) {
      const status = this.getAgentInputPackageStatus(item)
      if (status === 'ready') return '已就绪'
      if (status === 'partial') return '部分可用'
      return '未就绪'
    },
    createAgentInputPackageItem({ key, title, description, sourcePath, rawInput, requiredVersion = '', fields = [] }) {
      const item = {
        key: asText(key),
        title: asText(title),
        description: asText(description),
        sourcePath: asText(sourcePath),
        rawInput: cloneObject(rawInput || {}),
        requiredVersion: asText(requiredVersion),
        fields: cloneArray(fields),
      }
      return {
        ...item,
        status: this.getAgentInputPackageStatus(item),
        summary: this.summarizeAgentInputPackage(item.rawInput),
      }
    },
    buildAgentInputPackageGroups() {
      const snapshot = typeof this.buildAgentAnalysisSnapshot === 'function'
        ? this.buildAgentAnalysisSnapshot()
        : {}
      const paramBundles = snapshot.param_bundles && typeof snapshot.param_bundles === 'object' ? snapshot.param_bundles : {}
      const paramOrder = ['poi_fetch', 'poi_raster_grid', 'poi_h3_grid', 'population', 'nightlight', 'road_syntax']
      const paramItems = paramOrder
        .filter((key) => paramBundles[key])
        .map((key) => this.createAgentInputPackageItem({
          key: `param_${key}`,
          title: key,
          description: asText(paramBundles[key].display_label) || '分析任务参数口径',
          sourcePath: `param_bundles.${key}`,
          rawInput: paramBundles[key],
          fields: [
            { key: 'task_key', label: '任务', value: paramBundles[key].task_key },
            { key: 'domain', label: '领域', value: paramBundles[key].domain },
            { key: 'version', label: '版本', value: paramBundles[key].version },
            { key: 'cache_key', label: '缓存键', value: paramBundles[key].cache_key },
          ],
        }))
      const sharedGrid = cloneObject(snapshot.shared_grid || {})
      const poiH3 = cloneObject(snapshot.h3 && snapshot.h3.poi_h3_evidence || {})
      return [
        {
          key: 'param_bundles',
          label: '分析参数包',
          description: '当前任务的计算口径、缓存键和 evidence 参数。',
          items: paramItems,
        },
        {
          key: 'shared_grid',
          label: '同源栅格交叉证据',
          description: '人口、POI 栅格、夜光按同一 cell_id 对齐后的交叉证据。',
          items: [
            this.createAgentInputPackageItem({
              key: 'shared_grid',
              title: 'shared_grid_evidence_v1',
              description: '只用于人口 × POI × 夜光空间耦合判断。',
              sourcePath: 'shared_grid',
              rawInput: sharedGrid,
              requiredVersion: 'shared_grid_evidence_v1',
              fields: [
                { key: 'evidence_version', label: '证据版本', value: sharedGrid.evidence_version },
                { key: 'join_key', label: '连接键', value: sharedGrid.join_key },
                { key: 'uses', label: '使用数据', value: sharedGrid.uses },
                { key: 'counts', label: '计数', value: sharedGrid.counts },
              ],
            }),
          ],
        },
        {
          key: 'poi_spatial',
          label: 'POI 专项空间证据',
          description: 'H3 专项空间结构证据；POI 栅格只通过 shared_grid 参与耦合判断。',
          items: [
            this.createAgentInputPackageItem({
              key: 'poi_h3',
              title: 'poi_h3_evidence_v1',
              description: '只用于 POI 密度、集聚、熵、Gi/LISA 和热点结构判断。',
              sourcePath: 'h3.poi_h3_evidence',
              rawInput: poiH3,
              requiredVersion: 'poi_h3_evidence_v1',
              fields: [
                { key: 'evidence_version', label: '证据版本', value: poiH3.evidence_version },
                { key: 'grid_type', label: '网格类型', value: poiH3.grid_type },
                { key: 'counts', label: '计数', value: poiH3.counts },
                { key: 'metrics', label: '指标', value: poiH3.metrics },
              ],
            }),
          ],
        },
        {
          key: 'summary_evidence',
          label: '总结输入 evidence',
          description: 'summary/tourism payload 会读取的当前压缩证据对象。',
          items: [
            this.createAgentInputPackageItem({ key: 'summary_population', title: 'population', description: '人口 summary 与 grid_evidence。', sourcePath: 'population', rawInput: snapshot.population || {} }),
            this.createAgentInputPackageItem({ key: 'summary_nightlight', title: 'nightlight', description: '夜光 summary。', sourcePath: 'nightlight', rawInput: snapshot.nightlight || {} }),
            this.createAgentInputPackageItem({ key: 'summary_poi', title: 'poi_summary', description: 'POI 总量和来源；栅格耦合读取 shared_grid。', sourcePath: 'poi_summary', rawInput: snapshot.poi_summary || {} }),
            this.createAgentInputPackageItem({ key: 'summary_frontend', title: 'frontend_analysis', description: '前端导出的结构化分析块。', sourcePath: 'frontend_analysis', rawInput: snapshot.frontend_analysis || {} }),
          ],
        },
      ]
    },
    buildAgentInputPackageBasisPayload(packageItem = {}) {
      const item = packageItem && typeof packageItem === 'object' ? packageItem : {}
      return {
        title: `${asText(item.title) || '输入包'}字段`,
        currentConclusion: asText(item.description) || '当前输入包字段预览。',
        fields: [
          { key: 'status', label: '状态', value: this.getAgentInputPackageStatusLabel(item) },
          { key: 'source_path', label: '来源对象', value: item.sourcePath },
          { key: 'summary', label: '摘要', value: item.summary || this.summarizeAgentInputPackage(item.rawInput) },
          ...cloneArray(item.fields),
        ],
        rules: [
          '输入包为只读预览，用于查看当前会传给总结、文旅分析或 Agent 的参数口径与证据。',
          '同源栅格交叉证据只使用 shared_grid_evidence_v1；H3 只作为 POI 专项空间结构证据。',
        ],
        template: '从当前 analysis snapshot 中读取{来源对象}，用于检查 AI 输入口径和证据边界。',
        aiPrompt: '未调用 AI。该抽屉展示当前前端运行态 snapshot 中的输入包字段。',
        rawInput: cloneObject(item.rawInput || {}),
        sourceType: 'rule',
      }
    },
    getAgentToolDetail() {
      const targetName = asText(this.agentActiveToolDetailName)
      if (!targetName) return null
      return Array.isArray(this.agentTools)
        ? this.agentTools.find((tool) => asText(tool && tool.name) === targetName) || null
        : null
    },
    getGroupedAgentTools() {
      const tierOrder = ['foundation', 'capability', 'scenario']
      const groups = []
      tierOrder.forEach((tierKey) => {
        const tools = cloneArray(this.agentTools).filter((item) => asText(item && item.uiTier) === tierKey)
        if (!tools.length) return
        const subgroupMap = new Map()
        tools.forEach((tool) => {
          const subgroupKey = tierKey === 'scenario'
            ? (asText(tool.sceneType) || 'general')
            : (asText(tool.dataDomain) || 'general')
          if (!subgroupMap.has(subgroupKey)) subgroupMap.set(subgroupKey, [])
          subgroupMap.get(subgroupKey).push(tool)
        })
        groups.push({
          key: tierKey,
          label: this.getAgentToolLabel(tierKey),
          description: tierKey === 'foundation'
            ? '底层数据与计算能力，主要用于补证和兜底。'
            : tierKey === 'capability'
              ? '把获取、分析、解释、决策固化为统一能力接口。'
              : '面向真实任务场景，供 Planner 优先选择。',
          subgroups: Array.from(subgroupMap.entries()).map(([subgroupKey, subgroupTools]) => ({
            key: subgroupKey,
            label: this.getAgentToolLabel(subgroupKey),
            tools: subgroupTools.slice().sort((a, b) => a.name.localeCompare(b.name, 'zh-Hans-CN')),
          })),
        })
      })
      return groups
    },
    async loadAgentTools(force = false) {
      if (this.agentToolsLoading) return this.agentTools
      if (this.agentToolsLoaded && !force) return this.agentTools

      this.agentToolsLoading = true
      this.agentToolsError = ''
      try {
        const res = await fetch('/api/v1/analysis/agent/tools', {
          cache: force ? 'no-store' : 'default',
        })
        if (!res.ok) {
          throw new Error(`/api/v1/analysis/agent/tools 请求失败(${res.status})`)
        }
        const data = await res.json()
        this.agentTools = Array.isArray(data)
          ? data.map((item) => normalizeAgentToolSummary(item)).filter((item) => item.name)
          : []
        this.agentToolsLoaded = true
        return this.agentTools
      } catch (err) {
        this.agentToolsError = err && err.message ? err.message : String(err)
        throw err
      } finally {
        this.agentToolsLoading = false
      }
    },
    openAgentToolsPanel() {
      if (typeof this.selectStep3Panel === 'function') {
        this.selectStep3Panel('agent')
      } else {
        this.activeStep3Panel = 'agent'
        if (typeof this.ensureAgentPanelReady === 'function') {
          this.ensureAgentPanelReady()
        }
      }
      this.agentWorkspaceView = 'tools'
      this.closeAgentSessionMenu()
      if (!this.agentToolsLoaded && !this.agentToolsLoading) {
        this.loadAgentTools(false).catch((err) => {
          console.warn('Agent tools load failed', err)
        })
      }
    },
    backToAgentReport() {
      this.agentWorkspaceView = 'report'
      this.closeAgentToolDetail()
    },
    openAgentToolDetail(tool = null, event = null) {
      if (event && typeof event.stopPropagation === 'function') {
        event.stopPropagation()
      }
      const toolName = asText(tool && tool.name)
      if (!toolName) return
      this.agentActiveToolDetailName = toolName
      this.agentToolDetailDialogOpen = true
    },
    closeAgentToolDetail() {
      this.agentToolDetailDialogOpen = false
      this.agentActiveToolDetailName = ''
    },
    agentCanSubmit() {
      return !this.agentSessionHydrating && !!String(this.agentInput || '').trim()
    },
    getAgentCurrentTurnMessageBoundary() {
      const messages = Array.isArray(this.agentMessages) ? this.agentMessages : []
      if (!this.agentHasThinkingContent() || !messages.length) return -1
      for (let index = messages.length - 1; index >= 0; index -= 1) {
        if (asText(messages[index] && messages[index].role) === 'user') {
          return index
        }
      }
      return -1
    },
    getAgentMessagesBeforeThinking() {
      const messages = cloneArray(this.agentMessages)
      const boundaryIndex = this.getAgentCurrentTurnMessageBoundary()
      if (boundaryIndex < 0) return messages
      return messages.slice(0, boundaryIndex + 1)
    },
    getAgentMessagesAfterThinking() {
      const messages = cloneArray(this.agentMessages)
      const boundaryIndex = this.getAgentCurrentTurnMessageBoundary()
      if (boundaryIndex < 0 || boundaryIndex >= messages.length - 1) return []
      return messages.slice(boundaryIndex + 1).filter((message) => asText(message && message.role) === 'assistant')
    },
    getAgentStatusLabel() {
      if (this.agentSessionHydrating) {
        return '加载中'
      }
      const mapping = {
        idle: '待执行',
        running: '执行中',
        answered: '已完成',
        requires_clarification: '需补充',
        requires_risk_confirmation: '待确认',
        failed: '失败',
      }
      return mapping[String(this.agentStatus || 'idle')] || String(this.agentStatus || '待执行')
    },
    agentShouldRenderThinkingBlock() {
      return this.agentHasThinkingContent()
    },
    shouldShowAgentThinkingProcessBlock() {
      if (!this.agentHasThinkingContent()) return false
      if (this.isAgentReactLoopProcess()) return false
      return (
        asText(this.agentDeepAnalysisMode) === 'deep'
        || asText(this.agentComposerMode) === 'deep'
        || !!this.agentPendingTaskConfirmation
        || !!this.agentRiskPrompt
        || !!this.agentClarificationQuestion
      )
    },
    isAgentReactLoopProcess() {
      return cloneArray(this.agentThinkingTimeline).some((item) => {
        const meta = cloneObject(item && item.meta)
        return !!meta.reactLoop || asText(item && item.phase) === 'react_loop'
      })
    },
    getAgentReactProcessMessages() {
      if (!this.isAgentReactLoopProcess()) return []
      const visibleTypes = new Set(['thought', 'action', 'observation', 'reflection', 'error'])
      return cloneArray(this.agentThinkingTimeline)
        .map((item) => {
          const meta = cloneObject(item && item.meta)
          const reactType = asText(meta.reactType)
          const raw = cloneObject(meta.raw)
          const detail = asText(item && item.detail)
          if (!visibleTypes.has(reactType) || !detail) return null
          const labels = {
            thought: '思考',
            action: '行动',
            observation: '观察',
            reflection: '复盘',
            error: '异常',
          }
          const tool = asText(meta.tool_label || meta.tool || raw.tool_label || raw.tool)
          const argumentSummary = asText(raw.arguments_summary)
          const evidenceCount = raw.evidence_count
          const warningCount = raw.warning_count
          const metaParts = []
          if (argumentSummary && argumentSummary !== '无参数') metaParts.push(`参数：${argumentSummary}`)
          if (evidenceCount !== undefined && evidenceCount !== null && String(evidenceCount) !== '') metaParts.push(`证据：${evidenceCount} 条`)
          if (warningCount !== undefined && warningCount !== null && Number(warningCount) > 0) metaParts.push(`警告：${warningCount} 条`)
          return {
            id: asText(item && item.id),
            type: reactType,
            label: labels[reactType] || '过程',
            content: detail,
            tool,
            metaParts,
            state: asText(item && item.state) || 'pending',
          }
        })
        .filter(Boolean)
    },
    agentHasThinkingContent() {
      return !!(
        this.agentLoading
        || (Array.isArray(this.agentThinkingTimeline) && this.agentThinkingTimeline.length)
        || (Array.isArray(this.agentReasoningBlocks) && this.agentReasoningBlocks.length)
        || hasAgentPlanContent(this.agentPlan)
        || hasAgentExecutionTraceContent(this.agentExecutionTrace)
        || this.agentPendingTaskConfirmation
      )
    },
    getAgentThinkingStatusLabel() {
      if (this.agentLoading) return '思考中...'
      if (this.agentStreamState === 'failed') return '思考失败'
      if (this.agentThinkingTimeline.length) return '已思考'
      if (this.getAgentVisibleReasoningBlocks().length) return '已思考'
      if (this.agentExecutionTrace.length || hasAgentPlanContent(this.agentPlan)) return '已思考'
      return '处理中'
    },
    getAgentVisibleProcessSteps() {
      const steps = cloneArray(this.agentThinkingTimeline)
        .map((item) => ({
          id: asText(item && item.id),
          phase: asText(item && item.phase),
          title: asText(item && item.title) || '处理中',
          detail: asText(item && item.detail),
          items: cloneArray(item && item.items).map((entry) => asText(entry)).filter(Boolean),
          state: asText(item && item.state) || 'pending',
        }))
        .filter((item) => item.id !== 'stream-connect')
      const hasBackendStep = steps.some((item) => item.id && !item.id.startsWith('frontend-'))
      if (!hasBackendStep) return steps
      return steps.filter((item) => !item.id.startsWith('frontend-wait-'))
    },
    getAgentProcessRoleGroups() {
      const roleMeta = {
        connecting: {
          title: '\u8bf7\u6c42\u63d0\u4ea4',
          description: '\u628a\u95ee\u9898\u53d1\u9001\u7ed9 Agent\uff0c\u5e76\u7b49\u5f85\u540e\u7aef\u8fd4\u56de\u771f\u5b9e\u8fc7\u7a0b\u3002',
        },
        gating: {
          title: '\u95e8\u536b\u5224\u65ad',
          description: '\u5224\u65ad\u95ee\u9898\u662f\u5426\u6e05\u6670\u3001\u5f53\u524d\u8303\u56f4\u662f\u5426\u5177\u5907\u76f4\u63a5\u5206\u6790\u6761\u4ef6\u3002',
        },
        clarifying: {
          title: '\u8ffd\u95ee\u751f\u6210',
          description: '\u6574\u7406\u9700\u8981\u7528\u6237\u8865\u5145\u7684\u5173\u952e\u4fe1\u606f\u3002',
        },
        context_ready: {
          title: '\u4e0a\u4e0b\u6587\u6574\u7406',
          description: '\u6c47\u603b\u5f53\u524d\u8303\u56f4\u3001\u9762\u677f\u72b6\u6001\u548c\u53ef\u590d\u7528\u5206\u6790\u7ed3\u679c\u3002',
        },
        planning: {
          title: 'Planner',
          description: '\u89c4\u5212\u672c\u8f6e\u8981\u8c03\u7528\u7684\u5de5\u5177\u548c\u8bc1\u636e\u94fe\u3002',
        },
        replanning: {
          title: 'Planner \u590d\u76d8',
          description: '\u6839\u636e\u73b0\u573a\u53d8\u91cf\uff0c\u8c03\u6574\u8def\u7ebf\u6216\u66f4\u6362\u6267\u884c\u6b65\u9aa4\u3002',
        },
        tool_confirmation: {
          title: '\u5de5\u5177\u786e\u8ba4',
          description: '\u7b49\u5f85\u9700\u8981\u7528\u6237\u786e\u8ba4\u7684 Agent \u8c03\u7528\u3002\u786e\u8ba4\u540e\u53ef\u7ee7\u7eed\u6267\u884c\u3002',
        },
        executing: {
          title: '\u5de5\u5177\u6267\u884c',
          description: '\u6267\u884c\u5206\u6790\u5de5\u5177\u5e76\u6536\u96c6\u8bc1\u636e\u3002\u8fc7\u7a0b\u4fe1\u606f\u4f1a\u663e\u793a\u5728\u4e0b\u65b9\u6b65\u9aa4\u4e2d\u3002',
        },
        auditing: {
          title: '\u6821\u9a8c',
          description: '\u6574\u7406\u6267\u884c\u7ed3\u679c\uff0c\u505a\u8d28\u91cf\u548c\u98ce\u9669\u590d\u6838\u3002',
        },
        synthesizing: {
          title: '\u7ed3\u679c\u7ec4\u88c5',
          description: '\u628a\u6536\u96c6\u5230\u7684\u8bc1\u636e\u7ec4\u7ec7\u4e3a\u53ef\u8bfb\u7ed3\u8bba\uff0c\u5e76\u4fdd\u7559\u5173\u952e\u7406\u7531\u3002',
        },
        answering: {
          title: '\u8f93\u51fa\u56de\u7b54',
          description: '\u56de\u7b54\u751f\u6210\u4e2d\uff0c\u7ec4\u7ec7\u7ed3\u6784\u5316\u5185\u5bb9\u3002',
        },
        react_loop: {
          title: 'ReAct \u5faa\u73af',
          description: '\u6309\u601d\u8003\u3001\u884c\u52a8\u3001\u89c2\u5bdf\u7684\u987a\u5e8f\u5c55\u793a Agent \u6b63\u5728\u505a\u4ec0\u4e48\u3002',
        },
        answered: {
          title: '\u5df2\u5b8c\u6210',
          description: '\u5df2\u5b8c\u6210\u8f93\u51fa\u56de\u7b54\u3002',
        },
        failed: {
          title: '\u5931\u8d25\u5904\u7406',
          description: '\u8bb0\u5f55\u6267\u884c\u5931\u8d25\u539f\u56e0\uff0c\u53ef\u5728\u6b64\u57fa\u7840\u4e0a\u91cd\u8bd5\u3002',
        },
        requires_clarification: {
          title: '\u7b49\u5f85\u8865\u5145',
          description: '\u7b49\u5f85\u7528\u6237\u8865\u5145\u4fe1\u606f\u540e\u7ee7\u7eed\u3002',
        },
      }
      const phaseOrder = [
        'connecting',
        'gating',
        'clarifying',
        'context_ready',
        'planning',
        'replanning',
        'tool_confirmation',
        'executing',
        'auditing',
        'synthesizing',
        'answering',
        'react_loop',
        'answered',
        'requires_clarification',
        'failed',
      ]
      const groupsByPhase = new Map()
      const ensureGroup = (phase = '', fallbackStep = null) => {
        const nextPhase = asText(phase) || 'status'
        if (!groupsByPhase.has(nextPhase)) {
          const meta = roleMeta[nextPhase] || {
            title: asText(fallbackStep && fallbackStep.title) || '\u6d41\u7a0b\u6b65\u9aa4',
            description: 'Agent \u672a\u63d0\u4f9b\u8be5\u9636\u6bb5\u63cf\u8ff0\uff0c\u5c06\u7ee7\u7eed\u5c55\u793a\u3002',
          }
          groupsByPhase.set(nextPhase, {
            key: nextPhase,
            title: meta.title,
            description: meta.description,
            state: 'pending',
            steps: [],
            planChecklist: null,
            toolCallItems: [],
            taskConfirmation: null,
            progressLabel: '',
          })
        }
        return groupsByPhase.get(nextPhase)
      }
      this.getAgentVisibleProcessSteps().forEach((step) => {
        const phase = asText(step && step.phase) || 'status'
        const group = ensureGroup(phase, step)
        group.steps.push(step)
      })
      const planChecklist = this.getAgentPlanChecklist()
      if (planChecklist.visible) {
        const planGroupKey = planChecklist.followupApplied ? 'replanning' : 'planning'
        const planGroup = ensureGroup(planGroupKey)
        planGroup.planChecklist = planChecklist
        planGroup.progressLabel = planChecklist.progressLabel
      }
      const toolCallItems = this.getAgentToolCallItems()
      if (toolCallItems.length) {
        const toolGroup = ensureGroup('executing')
        toolGroup.toolCallItems = toolCallItems
        toolGroup.progressLabel = `${toolCallItems.length} \u6b21`
      }
      const taskConfirmation = this.getAgentTaskConfirmation()
      if (taskConfirmation) {
        const taskGroup = ensureGroup('tool_confirmation')
        taskGroup.taskConfirmation = taskConfirmation
        taskGroup.progressLabel = this.getAgentTaskConfirmationStatusLabel(taskConfirmation.status)
      }
      const stateRank = {
        failed: 4,
        active: 3,
        blocked: 3,
        pending: 2,
        skipped: 1,
        completed: 0,
      }
      const sortGroup = (left, right) => {
        const leftIndex = phaseOrder.indexOf(left.key)
        const rightIndex = phaseOrder.indexOf(right.key)
        const safeLeft = leftIndex >= 0 ? leftIndex : phaseOrder.length
        const safeRight = rightIndex >= 0 ? rightIndex : phaseOrder.length
        if (safeLeft !== safeRight) return safeLeft - safeRight
        return left.key.localeCompare(right.key, 'zh-Hans-CN')
      }
      return Array.from(groupsByPhase.values())
        .map((group) => {
          const itemStates = [
            ...group.steps.map((step) => asText(step && step.state) || 'pending'),
            ...((group.planChecklist && group.planChecklist.visible)
              ? group.planChecklist.groups.flatMap((planGroup) => planGroup.items.map((item) => asText(item && item.status) || 'pending'))
              : []),
            ...cloneArray(group.toolCallItems).map((item) => {
              const status = asText(item && item.status)
              if (status === 'success') return 'completed'
              if (status === 'failed') return 'failed'
              if (status === 'blocked') return 'blocked'
              if (status === 'skipped') return 'skipped'
              return 'active'
            }),
            ...((group.taskConfirmation)
              ? [this.getAgentTaskConfirmationProcessState(group.taskConfirmation.status)]
              : []),
          ]
          const state = itemStates.reduce((current, nextState) => {
            const normalizedState = asText(nextState) || 'pending'
            return (stateRank[normalizedState] || 0) > (stateRank[current] || 0) ? normalizedState : current
          }, itemStates.length ? 'completed' : 'pending')
          const activeStep = group.steps.find((step) => asText(step && step.state) === 'active')
          const lastStep = group.steps[group.steps.length - 1]
          const summary = asText(group.taskConfirmation && group.taskConfirmation.description)
            || asText((activeStep || lastStep || {}).detail)
            || group.description
          const countParts = []
          if (group.steps.length) countParts.push(`${group.steps.length} \u6b65`)
          if (group.progressLabel) countParts.push(group.progressLabel)
          return {
            ...group,
            state,
            summary,
            countLabel: countParts.join(' \u00b7 ') || group.progressLabel || '',
            steps: group.steps,
          }
        })
        .sort(sortGroup)
    },
    getAgentVisibleReasoningBlocks() {
      return cloneArray(this.agentReasoningBlocks)
        .map((item) => ({
          id: asText(item && item.id) || 'agent-reasoning',
          phase: asText(item && item.phase),
          title: asText(item && item.title) || '推理过程',
          content: String((item && item.content) || ''),
          state: asText(item && item.state) || 'active',
        }))
        .filter((item) => item.content || item.state === 'active')
    },
    toggleAgentThinkingExpanded() {
      this.agentThinkingExpanded = !this.agentThinkingExpanded
    },
    toggleAgentPlanExpanded() {
      this.agentPlanExpanded = !this.agentPlanExpanded
    },
    toggleAgentTraceExpanded() {
      this.agentTraceExpanded = !this.agentTraceExpanded
    },
    getAgentPlanChecklist() {
      return buildAgentPlanChecklist(this.agentPlan, this.agentExecutionTrace, {
        isLoading: this.agentLoading,
        stage: this.agentStage,
        diagnostics: (this.findAgentSession(this.activeAgentSessionId) || {}).diagnostics || {},
      })
    },
    getAgentPlanSummary() {
      return this.getAgentPlanChecklist().summary
    },
    getAgentPlanProgressLabel() {
      return this.getAgentPlanChecklist().progressLabel
    },
    getAgentToolCallItems() {
      return buildAgentToolCallItems(this.agentExecutionTrace)
    },
    getAgentToolCallStatusLabel(status = '') {
      const mapping = {
        start: '执行中',
        success: '成功',
        failed: '失败',
        blocked: '等待确认',
        skipped: '已跳过',
      }
      return mapping[asText(status)] || '执行中'
    },
    getAgentTaskConfirmation() {
      return cloneAnalysisTaskConfirmation(this.agentPendingTaskConfirmation)
    },
    getAgentTaskConfirmationStatusLabel(status = '') {
      const mapping = {
        ready: '待确认',
        reuse_available: '可复用',
        running: '运行中',
        blocked: '已阻塞',
        executing: '执行中',
        completed: '已完成',
        failed: '失败',
        cancelled: '已取消',
      }
      return mapping[asText(status)] || '待确认'
    },
    getAgentTaskConfirmationProcessState(status = '') {
      const key = asText(status)
      if (key === 'completed') return 'completed'
      if (key === 'failed') return 'failed'
      if (key === 'blocked') return 'blocked'
      if (key === 'cancelled') return 'skipped'
      if (key === 'running' || key === 'executing') return 'active'
      return 'blocked'
    },
    setAgentTaskConfirmation(nextConfirmation = null, sessionId = '') {
      const normalized = cloneAnalysisTaskConfirmation(nextConfirmation)
      this.agentPendingTaskConfirmation = normalized
      const targetSessionId = this.getActiveAgentSessionId(sessionId)
      if (!targetSessionId) return normalized
      this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
        ...session,
        pendingTaskConfirmation: normalized,
      }))
      return normalized
    },
    refreshAgentTaskConfirmation(seed = {}) {
      const current = this.getAgentTaskConfirmation()
      if (!current) return null
      const next = buildAnalysisTaskConfirmation(this, current.taskKey, {
        ...current,
        ...seed,
        updatedAt: new Date().toISOString(),
      })
      return this.setAgentTaskConfirmation(next)
    },
    onAgentTaskAdjustClick(taskConfirmation = null) {
      const current = cloneAnalysisTaskConfirmation(taskConfirmation || this.agentPendingTaskConfirmation)
      if (!current) return
      focusAnalysisTaskPanel(this, current.taskKey)
    },
    onAgentTaskCancelClick(taskConfirmation = null) {
      const current = cloneAnalysisTaskConfirmation(taskConfirmation || this.agentPendingTaskConfirmation)
      if (!current) return
      this.setAgentTaskConfirmation({
        ...current,
        status: 'cancelled',
        statusLabel: '已取消',
        updatedAt: new Date().toISOString(),
      })
    },
    async onAgentTaskReuseClick(taskConfirmation = null) {
      const current = cloneAnalysisTaskConfirmation(taskConfirmation || this.agentPendingTaskConfirmation)
      if (!current || this.agentLoading || this.agentSessionHydrating) return
      focusAnalysisTaskPanel(this, current.taskKey)
      this.setAgentTaskConfirmation({
        ...current,
        status: 'completed',
        statusLabel: '\u5df2\u590d\u7528',
        updatedAt: new Date().toISOString(),
      })
      await this.submitAgentTurn({
        prompt: `已复用当前${current.label}结果，请基于最新左侧计算结果继续回答。`,
        panelKind: asText(this.getAgentActiveTopTab().kind) === 'deep_analysis' ? 'deep_analysis' : undefined,
      })
    },
    async onAgentTaskStartClick(taskConfirmation = null) {
      const current = cloneAnalysisTaskConfirmation(taskConfirmation || this.agentPendingTaskConfirmation)
      if (!current || this.agentLoading || this.agentSessionHydrating) return
      const checked = buildAnalysisTaskConfirmation(this, current.taskKey, current)
      this.setAgentTaskConfirmation(checked)
      if (!checked || !checked.canStart || ['blocked', 'running'].includes(asText(checked.status))) {
        focusAnalysisTaskPanel(this, current.taskKey)
        return
      }
      this.setAgentTaskConfirmation({
        ...checked,
        status: 'executing',
        statusLabel: '执行中',
        updatedAt: new Date().toISOString(),
      })
      try {
        await runAnalysisTask(this, current.taskKey)
        this.setAgentTaskConfirmation({
          ...checked,
          status: 'completed',
          statusLabel: '已完成',
          updatedAt: new Date().toISOString(),
        })
        await this.submitAgentTurn({
          prompt: `${checked.label}已完成，请基于最新左侧计算结果继续回答。`,
          panelKind: asText(this.getAgentActiveTopTab().kind) === 'deep_analysis' ? 'deep_analysis' : undefined,
        })
      } catch (err) {
        this.setAgentTaskConfirmation({
          ...checked,
          status: 'failed',
          statusLabel: '执行失败',
          error: err && err.message ? err.message : String(err),
          updatedAt: new Date().toISOString(),
        })
      }
    },
    getAgentPlanStatusLabel(status = '') {
      const mapping = {
        completed: '已完成',
        active: '执行中',
        pending: '待执行',
        failed: '失败',
        blocked: '等待确认',
        skipped: '已跳过',
      }
      return mapping[asText(status)] || '待执行'
    },
    getAgentPlanStatusSymbol(status = '') {
      const mapping = {
        completed: '✓',
        active: '•',
        pending: '•',
        failed: '×',
        blocked: '!',
        skipped: '-',
      }
      return mapping[asText(status)] || '•'
    },
    getAgentPanelPreloadNotes() {
      const runState = this.getAgentRunState(this.activeAgentSessionId)
      if (runState) {
        return normalizeAgentPanelPreloadNotes(runState.panelPreloadNotes)
      }
      const activeSession = this.findAgentSession(this.activeAgentSessionId)
      if (activeSession) {
        return normalizeAgentPanelPreloadNotes(activeSession.panelPreloadNotes)
      }
      return normalizeAgentPanelPreloadNotes(this.agentPanelPreloadNotes)
    },
    getAgentActivePanelPayloads(sessionId = '') {
      const targetSession = this.findAgentSession(sessionId || this.activeAgentSessionId)
      if (targetSession) {
        return cloneObject(targetSession.panelPayloads)
      }
      return cloneObject(this.agentPanelPayloads)
    },
    hasAgentStructuredOutput() {
      return !!(
        asText(this.agentDecision && this.agentDecision.summary)
        || (Array.isArray(this.agentSupport) && this.agentSupport.length)
        || (Array.isArray(this.agentActions) && this.agentActions.length)
        || (Array.isArray(this.agentCounterpoints) && this.agentCounterpoints.length)
        || (Array.isArray(this.agentBoundary) && this.agentBoundary.length)
        || this.shouldShowAgentReviewContract()
      )
    },
    shouldShowAgentReviewContract() {
      return asText(this.agentDeepAnalysisMode) === 'deep' && this.getAgentReviewContractItems().length > 0
    },
    getAgentReviewContractItems() {
      const contract = cloneObject(this.agentReviewContract)
      const keys = ['spatial_consistency', 'evidence_status', 'planning_translation', 'report_expression']
      const fallbackLabels = {
        spatial_consistency: '空间自洽',
        evidence_status: '证据状态',
        planning_translation: '策划转译',
        report_expression: '报告写回',
      }
      return keys
        .map((key) => {
          const item = cloneObject(contract[key])
          if (!Object.keys(item).length) return null
          const evidence = cloneArray(item.evidence).map((entry) => asText(entry)).filter(Boolean)
          const gaps = cloneArray(item.gaps).map((entry) => asText(entry)).filter(Boolean)
          return {
            key,
            label: asText(item.label) || fallbackLabels[key],
            status: asText(item.status || 'partial') || 'partial',
            summary: asText(item.summary),
            evidence,
            gaps,
            nextQuestion: asText(item.next_question || item.nextQuestion),
          }
        })
        .filter((item) => item && (item.summary || item.evidence.length || item.gaps.length || item.nextQuestion))
    },
    getAgentReviewContractStatusLabel(status = '') {
      return {
        supported: '已支撑',
        partial: '部分支撑',
        missing: '缺证据',
      }[asText(status)] || '部分支撑'
    },
    getAgentDecisionStrengthLabel(strength = '') {
      const key = asText(strength || (this.agentDecision && this.agentDecision.strength) || 'weak')
      return {
        strong: '强判断',
        moderate: '中等判断',
        weak: '方向性判断',
      }[key] || '方向性判断'
    },
    getAgentDecisionModeLabel(mode = '') {
      const key = asText(mode || (this.agentDecision && this.agentDecision.mode) || 'judgment')
      return {
        cognition: '认知输出',
        judgment: '判断输出',
        action: '行动输出',
      }[key] || '判断输出'
    },
    getAgentStructuredItemKey(item = null, fallbackIndex = 0) {
      if (item && typeof item === 'object') {
        return asText(item.key || item.metric || item.title || item.prompt) || `agent-structured-item-${fallbackIndex}`
      }
      return `agent-structured-item-${fallbackIndex}`
    },
    hasAgentActionPrompt(item = null) {
      return !!asText(item && item.prompt)
    },
    getAgentClarificationOptions(limit = 3) {
      const max = Math.max(0, Number(limit || 0))
      return cloneArray(this.agentClarificationOptions)
        .map((item) => asText(item))
        .filter(Boolean)
        .slice(0, max)
    },
    hasAgentClarificationOptions() {
      return this.getAgentClarificationOptions().length > 0
    },
    getAgentClarificationInputIndexLabel() {
      return this.hasAgentClarificationOptions() ? '4.' : ''
    },
    canSubmitAgentClarificationDraft() {
      return !this.agentLoading
        && !this.agentSessionHydrating
        && !this.agentClarificationSubmitting
        && !!String(this.agentClarificationDraft || '').trim()
    },
    onAgentClarificationOptionClick(option = '') {
      const prompt = asText(option)
      if (!prompt || this.agentLoading || this.agentSessionHydrating || this.agentClarificationSubmitting) return
      this.agentClarificationSubmitting = true
      this.submitAgentTurn({ prompt })
    },
    onAgentClarificationDraftSubmit() {
      const prompt = String(this.agentClarificationDraft || '').trim()
      if (!prompt || this.agentLoading || this.agentSessionHydrating || this.agentClarificationSubmitting) return
      this.agentClarificationSubmitting = true
      this.submitAgentTurn({ prompt })
    },
    onAgentActionPromptClick(item = null) {
      const prompt = asText(item && item.prompt)
      if (!prompt) return
      this.queueAgentPrompt(prompt)
    },
    isAgentCardActionItem(item = null) {
      return !!(item && typeof item === 'object' && asText(item.type) === 'h3_candidate' && asText(item.h3_id))
    },
    getAgentCardItemText(item = null) {
      if (item && typeof item === 'object') {
        return asText(item.text || item.label || item.title || '')
      }
      return asText(item)
    },
    getAgentCardItemKey(item = null, fallbackIndex = 0) {
      if (item && typeof item === 'object') {
        return asText(item.h3_id || item.key || item.label) || `agent-card-item-${fallbackIndex}`
      }
      return asText(item) || `agent-card-item-${fallbackIndex}`
    },
    async onAgentCardItemClick(item = null) {
      if (!this.isAgentCardActionItem(item)) return
      const h3Id = asText(item.h3_id)
      if (!h3Id) return
      this.sidebarView = 'wizard'
      this.step = 2
      this.lastNonAgentStep3Panel = 'poi'
      if (typeof this.selectStep3Panel === 'function') {
        this.selectStep3Panel('poi')
      } else {
        this.activeStep3Panel = 'poi'
        this.poiSubTab = 'grid'
      }
      this.poiSubTab = 'grid'
      if (typeof this.$nextTick === 'function') {
        await this.$nextTick()
      }
      const activePanelPayloads = this.getAgentActivePanelPayloads()
      const ready = typeof this.ensureH3ReadyForAgentTarget === 'function'
        ? await this.ensureH3ReadyForAgentTarget(activePanelPayloads, {
          allowCompute: true,
          targetCategory: asText((activePanelPayloads.h3_result || {}).ui && (activePanelPayloads.h3_result || {}).ui.target_category),
        })
        : false
      if (ready && typeof this.focusGridByH3Id === 'function') {
        this.focusGridByH3Id(h3Id)
      }
    },
    closeAgentSessionMenu() {
      this.agentSessionMenuId = ''
    },
    toggleAgentSessionMenu(sessionId = '', event = null) {
      if (event && typeof event.stopPropagation === 'function') {
        event.stopPropagation()
      }
      const nextId = asText(sessionId)
      this.agentSessionMenuId = this.agentSessionMenuId === nextId ? '' : nextId
    },
    openAgentRenameDialog(sessionId = '', event = null) {
      if (event && typeof event.stopPropagation === 'function') {
        event.stopPropagation()
      }
      const session = this.findAgentSession(sessionId)
      if (!session) return
      this.agentRenameDialogOpen = true
      this.agentRenameSessionId = session.id
      this.agentRenameInput = this.getAgentSessionTitle(session)
      this.closeAgentSessionMenu()
    },
    closeAgentRenameDialog() {
      this.agentRenameDialogOpen = false
      this.agentRenameSessionId = ''
      this.agentRenameInput = ''
    },
    async submitAgentRename() {
      const sessionId = asText(this.agentRenameSessionId)
      const title = clampText(this.agentRenameInput, 60)
      if (!sessionId || !title) {
        window.alert('名称不能为空')
        return
      }
      const session = this.findAgentSession(sessionId)
      if (!session) return
      let nextSession = null
      if (session.persisted) {
        nextSession = await this.patchAgentSessionMetadata(sessionId, { title })
      } else {
        nextSession = createAgentSessionRecord({
          ...session,
          title,
          titleSource: 'user',
          updatedAt: new Date().toISOString(),
        })
        const filtered = this.agentSessions.filter((item) => asText(item && item.id) !== sessionId)
        this.updateAgentSessions([nextSession, ...filtered], { loaded: this.agentSessionsLoaded })
      }
      if (asText(this.activeAgentSessionId) === sessionId && nextSession) {
        this.applyAgentSessionSnapshot(nextSession)
      }
      this.closeAgentRenameDialog()
    },
    async toggleAgentSessionPinned(sessionId = '', event = null) {
      if (event && typeof event.stopPropagation === 'function') {
        event.stopPropagation()
      }
      const session = this.findAgentSession(sessionId)
      if (!session) return
      const nextPinned = !session.isPinned
      if (session.persisted) {
        const nextSession = await this.patchAgentSessionMetadata(session.id, { is_pinned: nextPinned })
        if (asText(this.activeAgentSessionId) === session.id) {
          this.applyAgentSessionSnapshot(nextSession)
        }
      } else {
        const nextSession = createAgentSessionRecord({
          ...session,
          isPinned: nextPinned,
          pinnedAt: nextPinned ? new Date().toISOString() : '',
          updatedAt: new Date().toISOString(),
        })
        const filtered = this.agentSessions.filter((item) => asText(item && item.id) !== session.id)
        this.updateAgentSessions([nextSession, ...filtered], { loaded: this.agentSessionsLoaded })
        if (asText(this.activeAgentSessionId) === session.id) {
          this.applyAgentSessionSnapshot(nextSession)
        }
      }
      this.closeAgentSessionMenu()
    },
    async activateFallbackAgentSession(remainingSessions = []) {
      const rows = sortAgentSessions(remainingSessions)
      const visibleRows = rows.filter((item) => !!(item && item.persisted))
      if (!visibleRows.length) {
        const session = this.createAgentSession()
        this.updateAgentSessions([...rows.filter((item) => !!(item && !item.persisted)), session], { loaded: this.agentSessionsLoaded })
        this.applyAgentSessionSnapshot(session)
        return
      }
      const nextSession = visibleRows[0]
      if (nextSession.persisted && !nextSession.snapshotLoaded) {
        await this.activateAgentSession(nextSession.id)
        return
      }
      this.applyAgentSessionSnapshot(nextSession)
    },
    async deleteAgentSession(sessionId = '', event = null) {
      if (event && typeof event.stopPropagation === 'function') {
        event.stopPropagation()
      }
      this.syncCurrentAgentSession()
      const session = this.findAgentSession(sessionId)
      if (!session) return
      if (!window.confirm('确定要删除这条分析记录吗？')) return

      const previousSessions = this.agentSessions
        .map((item) => cloneAgentSessionRecord(item))
        .filter((item) => !!item)
      const previousActiveSessionId = asText(this.activeAgentSessionId)
      const previousAgentSessionDetailLoadingId = asText(this.agentSessionDetailLoadingId)
      const previousAgentSessionDetailRequestToken = Number(this.agentSessionDetailRequestToken || 0)
      const previousAgentSessionHydrating = !!this.agentSessionHydrating
      const previousActiveSession = cloneAgentSessionRecord(
        previousActiveSessionId ? this.findAgentSession(previousActiveSessionId) : null,
      )

      this.closeAgentSessionMenu()
      const remaining = this.agentSessions.filter((item) => asText(item && item.id) !== session.id)
      this.updateAgentSessions(remaining, { loaded: this.agentSessionsLoaded })
      if (asText(this.activeAgentSessionId) === session.id) {
        await this.activateFallbackAgentSession(remaining)
      }

      if (session.persisted) {
        try {
          const res = await fetch(`/api/v1/analysis/agent/sessions/${encodeURIComponent(session.id)}`, {
            method: 'DELETE',
          })
          if (!res.ok) {
            throw new Error(`/api/v1/analysis/agent/sessions/${session.id} DELETE 失败(${res.status})`)
          }
        } catch (err) {
          this.updateAgentSessions(previousSessions, { loaded: this.agentSessionsLoaded })
          this.agentSessionDetailLoadingId = previousAgentSessionDetailLoadingId
          this.agentSessionDetailRequestToken = previousAgentSessionDetailRequestToken
          this.agentSessionHydrating = previousAgentSessionHydrating
          if (previousActiveSession) {
            this.applyAgentSessionSnapshot(previousActiveSession, {
              hydrating: previousAgentSessionHydrating,
              keepDetailLoadingId: previousAgentSessionHydrating && !!previousAgentSessionDetailLoadingId,
            })
          } else {
            this.activeAgentSessionId = previousActiveSessionId
          }
          window.alert(`删除分析记录失败: ${err && err.message ? err.message : String(err)}`)
          return
        }
      }
    },
  }
}

export {
  createAgentUiMethods,
}
