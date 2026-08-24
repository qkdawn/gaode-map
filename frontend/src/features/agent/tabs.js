import {
  asText,
  clampText,
  cloneArray,
  cloneAgentSessionRecord,
  cloneObject,
  consumeSseStream,
  createAgentSessionRecord,
  normalizeAgentToolSummary,
  sortAgentSessions,
} from './normalizers.js'
import {
  buildAnalysisTaskConfirmation,
  focusAnalysisTaskPanel,
  getAnalysisTaskDefinition,
  getAnalysisTaskDefinitions,
  runAnalysisTask,
} from './analysis-task-registry.js'
import { buildAnalysisTaskParamBundle } from './analysis-task-params.js'
import { ANALYSIS_WORKSPACE_TAB_KIND } from './workspace-kinds.js'
import {
  cloneAgentTabsState,
  getAnalysisWorkspaceTabsFromState,
  withAnalysisWorkspaceTabs,
} from './analysis-workspace-tabs.js'
import { createAgentPptPlanningTabMethods } from './ppt-planning-tabs.js'
import {
  normalizeAgentPptPlanningTab,
  serializeAgentPptPlanningTab,
} from './ppt-planning-tabs.js'

export function createAgentTabsMethods() {
  return {
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
      return withAnalysisWorkspaceTabs({
        summaryTabs: [],
        iterationChangeTabs: [],
        siteSelectionTabs: [],
        followupTabs: [],
        activeTabId: '',
        followupLimit: 6,
        nextFollowupNumber: 1,
      }, [])
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
      if (normalized === ANALYSIS_WORKSPACE_TAB_KIND) return '分析'
      return '追问解释'
    },
    extractAgentTabShortTitle(kind = '', seed = '') {
      const label = this.getAgentTabKindLabel(kind)
      const raw = clampText(asText(seed).replace(/^(?:区域总结|多年迭代变化|区域内选址|分析|深度分析|追问解释|总结|追问)\s*[·:：-]\s*/u, '').trim(), 24)
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
        messages: cloneArray(normalized.messages),
        error: String(normalized.error || ''),
        panelPayloads: cloneObject(normalized.panelPayloads),
        activityItems: cloneArray(normalized.activityItems),
      }
    },
    buildAgentFollowupThreadFromCurrentState() {
      return this.createAgentFollowupThreadState({
        input: this.agentInput,
        status: this.agentStatus,
        messages: this.agentMessages,
        error: this.agentError,
        panelPayloads: this.agentPanelPayloads,
        activityItems: this.agentActivityItems,
      })
    },
    applyAgentFollowupThreadToCurrentState(thread = null) {
      const state = this.createAgentFollowupThreadState(thread || {})
      this.agentInput = String(state.input || '')
      this.agentStatus = String(state.status || 'idle')
      this.agentMessages = cloneArray(state.messages)
      this.agentError = String(state.error || '')
      this.agentPanelPayloads = cloneObject(state.panelPayloads)
      this.agentActivityItems = cloneArray(state.activityItems)
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
      const analysisWorkspaceTab = getAnalysisWorkspaceTabsFromState(tabs).find((item) => asText(item && item.id) === activeId)
      if (analysisWorkspaceTab) return { ...cloneObject(analysisWorkspaceTab), kind: ANALYSIS_WORKSPACE_TAB_KIND, fixed: false }
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
    getAgentAnalysisWorkspaceTabs(tabs = null) {
      return getAnalysisWorkspaceTabsFromState(tabs || this.ensureAgentTabs(false))
    },
    withAgentAnalysisWorkspaceTabs(tabs = {}, items = []) {
      return withAnalysisWorkspaceTabs(tabs, items)
    },
    ...createAgentPptPlanningTabMethods(),
    createAgentIterationChangeViewId() {
      return `iteration-change-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
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
    ensureAgentTabs(commit = false) {
      const base = this.agentTabs && typeof this.agentTabs === 'object'
        ? this.agentTabs
        : this.createDefaultAgentTabs()
      const currentSummaryPack = this.getAgentSummaryPack(this.agentPanelPayloads)
      const defaultSummaryPack = this.hasAgentSummaryPack(currentSummaryPack) || Object.keys(currentSummaryPack).length
        ? currentSummaryPack
        : {}
      const currentSummaryStatus = this.getAgentSummaryStatus(this.agentPanelPayloads)
      const analysisWorkspaceTabs = getAnalysisWorkspaceTabsFromState(base)
        .map((item) => normalizeAgentPptPlanningTab(item))
        .filter((item) => item.id)
      const nextTabs = withAnalysisWorkspaceTabs({
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
      }, analysisWorkspaceTabs)
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
      const validIds = new Set([...nextTabs.summaryTabs.map((item) => item.id), ...nextTabs.iterationChangeTabs.map((item) => item.id), ...nextTabs.siteSelectionTabs.map((item) => item.id), ...getAnalysisWorkspaceTabsFromState(nextTabs).map((item) => item.id), ...nextTabs.followupTabs.map((item) => item.id)])
      if (!validIds.has(nextTabs.activeTabId)) {
        const fallbackTab = [
          ...nextTabs.summaryTabs,
          ...nextTabs.iterationChangeTabs,
          ...nextTabs.siteSelectionTabs,
          ...getAnalysisWorkspaceTabsFromState(nextTabs),
          ...nextTabs.followupTabs,
        ].find((item) => asText(item && item.id))
        nextTabs.activeTabId = asText(fallbackTab && fallbackTab.id)
      }
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
        ...getAnalysisWorkspaceTabsFromState(tabs).map((item) => ({
          id: item.id,
          title: item.title || '分析',
          kind: ANALYSIS_WORKSPACE_TAB_KIND,
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
      if (kind === ANALYSIS_WORKSPACE_TAB_KIND) return '区域报告 / 分析'
      if (kind === 'followup') return '区域报告 / 追问'
      return 'Agent 工作台'
    },
    getAgentWorkspaceNavTitle() {
      const activeTab = this.getAgentActiveTopTab()
      const kind = asText(activeTab.kind)
      if (kind === 'site_selection') return '区域内选址'
      if (kind === 'iteration_change') return '多年变化'
      if (kind === ANALYSIS_WORKSPACE_TAB_KIND) return '分析'
      if (kind === 'followup') return '追问解释'
      return '区域报告'
    },
    getAgentWorkspaceNavSubtitle() {
      const kind = asText(this.getAgentActiveTopTab().kind)
      if (kind === 'site_selection') return '从区域报告进入的开店位置判断'
      if (kind === 'iteration_change') return '从区域报告进入的时间变化分析'
      if (kind === ANALYSIS_WORKSPACE_TAB_KIND) return '围绕已选来源做快速或深度分析，也可继续生成展示材料'
      if (kind === 'followup') return '围绕当前区域报告继续追问'
      if (this.hasAgentSummaryPack()) return '先看判断，再追问、查证据或继续做任务'
      return '先补齐证据并生成当前区域的智能报告'
    },
    isAgentReportDetailView() {
      return ['site_selection', 'iteration_change', ANALYSIS_WORKSPACE_TAB_KIND, 'followup'].includes(asText(this.getAgentActiveTopTab().kind))
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
      this.agentTabs = cloneAgentTabsState(tabs)
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
      this.agentTabs = cloneAgentTabsState(tabs)
    },
    captureAgentActiveSiteSelectionTabState() {
      const tabs = this.ensureAgentTabs(true)
      const activeTab = this.getAgentActiveTopTab()
      if (asText(activeTab.kind) !== 'site_selection') return
      const target = cloneArray(tabs.siteSelectionTabs).find((item) => item.id === activeTab.id)
      if (!target || target.readonly) return
      target.panelPayloads = cloneObject(this.agentPanelPayloads)
      this.agentTabs = cloneAgentTabsState(tabs)
    },
    switchAgentTopTab(tabId = '') {
      const nextId = asText(tabId)
      if (!nextId) return
      this.captureAgentActiveSummaryTabState()
      this.captureAgentActiveSiteSelectionTabState()
      this.captureAgentActivePptPlanningTabState()
      this.captureAgentActiveFollowupTabState()
      const tabs = this.ensureAgentTabs(true)
      if (tabs.activeTabId === nextId) return
      tabs.activeTabId = nextId
      this.agentTabs = cloneAgentTabsState(tabs)
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
      } else if (getAnalysisWorkspaceTabsFromState(tabs).some((item) => item.id === nextId)) {
        const target = getAnalysisWorkspaceTabsFromState(tabs).find((item) => item.id === nextId)
        this.syncActiveAgentRuntimeView(this.activeAgentSessionId)
        if (target && target.panelPayloads && typeof target.panelPayloads === 'object') {
          this.agentPanelPayloads = cloneObject(target.panelPayloads)
        }
        this.refreshAgentActivePptPlanningSources()
        this.refreshAgentActivePptPlanningDataSources()
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
      if (options.syncLocalResults !== false && typeof this.syncSummaryTaskBoardFromLocalResults === 'function') {
        this.syncSummaryTaskBoardFromLocalResults({ sync: false })
      }
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
      this.agentTabs = cloneAgentTabsState(tabs)
      this.syncActiveAgentRuntimeView(this.activeAgentSessionId)
      this.syncCurrentAgentSession()
      this.refreshAgentSummaryReadiness(false)
      return summaryTab.id
    },
    createAgentSiteSelectionTab(options = {}) {
      const tabs = this.ensureAgentTabs(true)
      this.captureAgentActiveSummaryTabState()
      this.captureAgentActivePptPlanningTabState()
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
      this.agentTabs = cloneAgentTabsState(tabs)
      this.syncActiveAgentRuntimeView(this.activeAgentSessionId)
      this.syncCurrentAgentSession()
      return tabId
    },
    createAgentIterationChangeTab(options = {}) {
      const tabs = this.ensureAgentTabs(true)
      this.captureAgentActiveSummaryTabState()
      this.captureAgentActivePptPlanningTabState()
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
      this.agentTabs = cloneAgentTabsState(tabs)
      this.syncActiveAgentRuntimeView(this.activeAgentSessionId)
      this.syncCurrentAgentSession()
      if (options.autoload !== false) {
        this.ensureAgentIterationKind(tab.activeKind).catch((err) => {
          console.warn('Agent iteration load failed', err)
        })
      }
      return tabId
    },
    startAgentComposerNewReportSession() {
      this.startNewAgentReportSession()
    },
    createAgentFollowupTab(options = {}) {
      const tabs = this.ensureAgentTabs(true)
      if (!this.canCreateAgentFollowupTab()) {
        window.alert(`最多可保留 ${tabs.followupLimit} 条追问解释，请先关闭旧追问。`)
        return null
      }
      this.captureAgentActivePptPlanningTabState()
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
      this.agentTabs = cloneAgentTabsState(tabs)
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
      this.agentTabs = cloneAgentTabsState(tabs)
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
    shouldShowAgentComposer() {
      const activeTab = this.getAgentActiveTopTab()
      return asText(activeTab.kind) === ANALYSIS_WORKSPACE_TAB_KIND
    },
    buildAgentTabsUiState() {
      this.captureAgentActiveSummaryTabState()
      this.captureAgentActiveSiteSelectionTabState()
      this.captureAgentActivePptPlanningTabState()
      this.captureAgentActiveFollowupTabState()
      const tabs = this.ensureAgentTabs(true)
      return {
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
        analysis_workspace_tabs: getAnalysisWorkspaceTabsFromState(tabs).map((item) => serializeAgentPptPlanningTab(item, this.agentPanelPayloads)),
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
      const analysisWorkspaceTabs = cloneArray(uiState.analysis_workspace_tabs || uiState.analysisWorkspaceTabs)
        .map((item) => normalizeAgentPptPlanningTab(item, { restore: true, sessionId: session && session.id }))
        .map((item) => ({
          ...item,
          pptPlanningState: this.appendPptPlanningDebugEvent
            ? this.appendPptPlanningDebugEvent(item.pptPlanningState, 'tabs_restored_from_session', {
              sessionId: session && session.id,
              activeTabId: asText(uiState.active_tab_id),
              tabIds: cloneArray(uiState.analysis_workspace_tabs || uiState.analysisWorkspaceTabs).map((tab) => asText(tab && tab.id)).filter(Boolean),
              tabId: asText(item && item.id),
              job: item && item.pptPlanningState ? item.pptPlanningState.generationJob : {},
            })
            : item.pptPlanningState,
        }))
        .filter((item) => item.id)
      const activeId = asText(uiState.active_tab_id)
      this.agentTabs = withAnalysisWorkspaceTabs({
        summaryTabs,
        iterationChangeTabs,
        siteSelectionTabs,
        followupTabs,
        activeTabId: activeId || asText([
          ...summaryTabs,
          ...iterationChangeTabs,
          ...siteSelectionTabs,
          ...analysisWorkspaceTabs,
          ...followupTabs,
        ].find((item) => asText(item && item.id))?.id),
        followupLimit: Number(uiState.followup_limit || 6) || 6,
        nextFollowupNumber: Number(uiState.next_followup_number || (followupTabs.length + 1) || 1) || 1,
      }, analysisWorkspaceTabs)
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
        } else if (asText(activeTopTab.kind) === ANALYSIS_WORKSPACE_TAB_KIND) {
          const activeAnalysisWorkspace = getAnalysisWorkspaceTabsFromState(this.agentTabs).find((item) => item.id === this.agentTabs.activeTabId)
          if (activeAnalysisWorkspace && activeAnalysisWorkspace.panelPayloads && typeof activeAnalysisWorkspace.panelPayloads === 'object') {
            this.agentPanelPayloads = cloneObject(activeAnalysisWorkspace.panelPayloads)
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
  }
}
