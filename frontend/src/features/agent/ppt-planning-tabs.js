import { asText, cloneArray, cloneObject } from './normalizers.js'
import {
  createPptPlanningState,
  getActiveDeckSlideBrief,
  getPptSourceSummary,
  selectDeckSlideBrief,
  setAllPptSourcesSelected,
  togglePptSourceSelection,
} from '../ppt-planning/ui-state.js'

export function normalizeAgentPptPlanningTab(item = {}, options = {}) {
  const source = asText(item && item.source) || 'draft'
  return {
    id: asText(item && item.id),
    kind: 'ppt_planning',
    title: asText(item && item.title) || '策划 PPT',
    source,
    sessionId: asText((item && (item.session_id || item.sessionId)) || ''),
    readonly: options.restore ? !!(item && item.readonly && source !== 'history') : !!(item && item.readonly),
    createdAt: asText(item && (item.created_at || item.createdAt)) || new Date().toISOString(),
    panelPayloads: cloneObject(item && (item.panel_payloads || item.panelPayloads)),
    pptPlanningState: createPptPlanningState(item && (item.ppt_planning_state || item.pptPlanningState)),
  }
}

export function serializeAgentPptPlanningTab(item = {}, fallbackPanelPayloads = {}) {
  return {
    id: item.id,
    title: item.title || '策划 PPT',
    kind: 'ppt_planning',
    source: item.source || 'draft',
    session_id: item.sessionId || '',
    readonly: !!item.readonly,
    created_at: item.createdAt,
    panel_payloads: cloneObject(item.panelPayloads || fallbackPanelPayloads),
    ppt_planning_state: createPptPlanningState(item.pptPlanningState),
  }
}

export function createAgentPptPlanningTabMethods() {
  return {
    createAgentPptPlanningViewId() {
      return `ppt-planning-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
    },
    openAgentPptPlanningFromReport(options = {}) {
      this.agentWorkspaceView = 'report'
      const tabs = this.ensureAgentTabs(true)
      const existing = cloneArray(tabs.pptPlanningTabs).find((item) => asText(item && item.source) === 'current' || asText(item && item.source) === 'draft')
      if (existing && !options.forceNew) {
        this.switchAgentTopTab(existing.id)
        return existing.id
      }
      return this.createAgentPptPlanningTab({ title: '策划 PPT', source: 'current' })
    },
    isAgentPptPlanningTabActive() {
      return asText(this.getAgentActiveTopTab().kind) === 'ppt_planning'
    },
    getAgentActivePptPlanningTab() {
      const tabs = this.ensureAgentTabs(false)
      const activeId = asText(tabs.activeTabId)
      return cloneArray(tabs.pptPlanningTabs).find((item) => asText(item && item.id) === activeId) || null
    },
    getAgentActivePptPlanningState() {
      const tab = this.getAgentActivePptPlanningTab()
      return createPptPlanningState(tab && tab.pptPlanningState)
    },
    getAgentPptPlanningSources() {
      return cloneArray(this.getAgentActivePptPlanningState().sources)
    },
    getAgentPptPlanningSpec() {
      return cloneObject(this.getAgentActivePptPlanningState().spec)
    },
    getAgentPptPlanningSlides() {
      return cloneArray((this.getAgentActivePptPlanningState().deckBrief || {}).slides)
    },
    getAgentPptPlanningSourceSummary() {
      return getPptSourceSummary(this.getAgentActivePptPlanningState())
    },
    getAgentPptPlanningActiveSlide() {
      return getActiveDeckSlideBrief(this.getAgentActivePptPlanningState()) || {}
    },
    isAgentPptPlanningSlideActive(slideId = '') {
      return asText(this.getAgentActivePptPlanningState().selectedSlideId) === asText(slideId)
    },
    updateAgentActivePptPlanningState(nextState = {}) {
      const tabs = this.ensureAgentTabs(true)
      const activeTab = this.getAgentActiveTopTab()
      if (asText(activeTab.kind) !== 'ppt_planning') return
      const target = cloneArray(tabs.pptPlanningTabs).find((item) => item.id === activeTab.id)
      if (!target || target.readonly) return
      target.pptPlanningState = createPptPlanningState(nextState)
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), iterationChangeTabs: cloneArray(tabs.iterationChangeTabs), siteSelectionTabs: cloneArray(tabs.siteSelectionTabs), pptPlanningTabs: cloneArray(tabs.pptPlanningTabs), deepAnalysisTabs: cloneArray(tabs.deepAnalysisTabs), followupTabs: cloneArray(tabs.followupTabs) }
      this.syncCurrentAgentSession()
    },
    toggleAgentPptPlanningSource(sourceId = '') {
      this.updateAgentActivePptPlanningState(togglePptSourceSelection(this.getAgentActivePptPlanningState(), sourceId))
    },
    toggleAllAgentPptPlanningSources() {
      const summary = this.getAgentPptPlanningSourceSummary()
      this.updateAgentActivePptPlanningState(setAllPptSourcesSelected(this.getAgentActivePptPlanningState(), summary.selected < summary.total))
    },
    selectAgentPptPlanningSlide(slideId = '') {
      this.updateAgentActivePptPlanningState(selectDeckSlideBrief(this.getAgentActivePptPlanningState(), slideId))
    },
    captureAgentActivePptPlanningTabState() {
      const tabs = this.ensureAgentTabs(true)
      const activeTab = this.getAgentActiveTopTab()
      if (asText(activeTab.kind) !== 'ppt_planning') return
      const target = cloneArray(tabs.pptPlanningTabs).find((item) => item.id === activeTab.id)
      if (!target || target.readonly) return
      target.panelPayloads = cloneObject(this.agentPanelPayloads)
      target.pptPlanningState = createPptPlanningState(target.pptPlanningState)
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), iterationChangeTabs: cloneArray(tabs.iterationChangeTabs), siteSelectionTabs: cloneArray(tabs.siteSelectionTabs), pptPlanningTabs: cloneArray(tabs.pptPlanningTabs), deepAnalysisTabs: cloneArray(tabs.deepAnalysisTabs), followupTabs: cloneArray(tabs.followupTabs) }
    },
    createAgentPptPlanningTab(options = {}) {
      const tabs = this.ensureAgentTabs(true)
      this.captureAgentActiveSummaryTabState()
      this.captureAgentActiveSiteSelectionTabState()
      this.captureAgentActivePptPlanningTabState()
      this.captureAgentActiveDeepAnalysisTabState()
      this.captureAgentActiveFollowupTabState()
      const tabId = this.createAgentPptPlanningViewId()
      const tab = {
        id: tabId,
        kind: 'ppt_planning',
        title: this.formatAgentTabTitle('ppt_planning', options.title),
        source: asText(options.source) || 'draft',
        sessionId: asText(options.sessionId),
        readonly: !!options.readonly,
        createdAt: new Date().toISOString(),
        panelPayloads: cloneObject(this.agentPanelPayloads),
        pptPlanningState: createPptPlanningState(options.pptPlanningState),
      }
      tabs.pptPlanningTabs = [...cloneArray(tabs.pptPlanningTabs), tab]
      tabs.activeTabId = tabId
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), iterationChangeTabs: cloneArray(tabs.iterationChangeTabs), siteSelectionTabs: cloneArray(tabs.siteSelectionTabs), pptPlanningTabs: cloneArray(tabs.pptPlanningTabs), deepAnalysisTabs: cloneArray(tabs.deepAnalysisTabs), followupTabs: cloneArray(tabs.followupTabs) }
      this.syncActiveAgentRuntimeView(this.activeAgentSessionId)
      this.syncCurrentAgentSession()
      return tabId
    },
  }
}
