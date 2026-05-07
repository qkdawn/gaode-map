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

function createAgentUiMethods() {
  return {
    getAgentSessionTitle(session = null) {
      if (!session || typeof session !== 'object') return '新对话'
      return clampText(session.title, 60) || '新对话'
    },
    getAgentSessionPreview(session = null) {
      if (!session || typeof session !== 'object') return '开始一段新的分析对话'
      return clampText(session.preview, 120) || '开始一段新的分析对话'
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
      return '追问解释'
    },
    extractAgentTabShortTitle(kind = '', seed = '') {
      const label = this.getAgentTabKindLabel(kind)
      const raw = clampText(asText(seed).replace(/^(?:区域总结|多年迭代变化|区域内选址|追问解释|总结|追问)\s*[·:：-]\s*/u, '').trim(), 24)
      if (raw) return raw
      return label
    },
    formatAgentTabTitle(kind = '', seed = '') {
      return this.getAgentTabKindLabel(kind)
    },
    getAgentSummaryWindowTitle(panelPayloads = null, fallbackTitle = '') {
      const pack = this.getAgentSummaryPack(panelPayloads)
      const headline = asText(((pack.headline_judgment || {}).summary) || fallbackTitle)
      return this.formatAgentTabTitle('summary', headline)
    },
    getAgentFollowupWindowTitle(seed = null, fallbackTitle = '') {
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
      const followupTab = cloneArray(tabs.followupTabs).find((item) => asText(item && item.id) === activeId)
      if (followupTab) return { ...cloneObject(followupTab), kind: 'followup', fixed: false }
      return { id: '', kind: '', fixed: false, source: '', sessionId: '', title: '' }
    },
    isCurrentAgentSummaryTabActive() {
      const activeTab = this.getAgentActiveTopTab()
      return asText(activeTab.kind) === 'summary' && asText(activeTab.source) === 'current'
    },
    createAgentSummaryWindowId() {
      return `summary-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
    },
    createAgentSiteSelectionWindowId() {
      return `site-selection-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
    },
    createAgentIterationChangeWindowId() {
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
      this.basisDrawerOpen = true
    },
    closeBasisDrawer() {
      this.basisDrawerOpen = false
      this.basisDrawerPayload = null
      this.basisDrawerActiveTab = 'basic'
    },
    setBasisDrawerTab(tab = 'basic') {
      const key = asText(tab) || 'basic'
      if (!this.getBasisDrawerTabs().some((item) => item.key === key)) return
      this.basisDrawerActiveTab = key
    },
    getBasisDrawerTabs() {
      return [
        { key: 'basic', label: '基础说明' },
        { key: 'template', label: '规则模板' },
        { key: 'raw', label: '原始字段' },
      ]
    },
    getBasisDrawerPayload() {
      return this.normalizeBasisPayload(this.basisDrawerPayload || {})
    },
    normalizeBasisPayload(payload = null) {
      const source = payload && typeof payload === 'object' ? payload : {}
      return {
        title: asText(source.title) || '生成依据',
        currentConclusion: asText(source.currentConclusion || source.current_conclusion),
        fields: cloneArray(source.fields).filter((item) => item && (asText(item.label) || asText(item.key))),
        rules: cloneArray(source.rules).map((item) => asText(item)).filter(Boolean),
        template: asText(source.template),
        aiPrompt: asText(source.aiPrompt || source.ai_prompt) || '该结论由规则模板生成，未调用 AI',
        rawInput: cloneObject(source.rawInput || source.raw_input || {}),
        sourceType: asText(source.sourceType || source.source_type || 'rule'),
      }
    },
    formatBasisFieldValue(value) {
      if (value === undefined || value === null || value === '') return '-'
      if (Array.isArray(value)) {
        return value.map((item) => {
          if (item && typeof item === 'object') return JSON.stringify(item)
          return asText(item)
        }).filter(Boolean).join('、') || '-'
      }
      if (typeof value === 'object') return JSON.stringify(value)
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
    buildAgentSummaryBasisPayload(item = null) {
      const section = item && typeof item === 'object' ? item : {}
      const key = asText(section.sectionKey || section.section_key)
      const panelPayloads = this.getAgentActiveSummaryPanelPayloads()
      const pack = this.getAgentSummaryPack(panelPayloads)
      const nightlightPattern = cloneObject(
        panelPayloads.current_nightlight_pattern_analysis
        || panelPayloads.nightlight_pattern
        || panelPayloads.nightlight
        || {},
      )
      const nightlightSummary = cloneObject(
        panelPayloads.current_nightlight_summary
        || ((panelPayloads.nightlight_overview || {}).summary)
        || ((this.nightlightOverview || {}).summary)
        || {},
      )
      const roadSummary = cloneObject(
        panelPayloads.road_syntax_summary
        || ((panelPayloads.road || {}).summary)
        || this.roadSyntaxSummary
        || {},
      )
      const fields = cloneArray(section.dimensions).map((dimension) => ({
        key: asText(dimension.key),
        label: asText(dimension.label),
        value: asText(dimension.conclusion),
      }))
      if (key === 'consumption_vitality') {
        fields.push(
          { key: 'economic_activity_intensity_level', label: '经济活动强度等级', value: nightlightPattern.economic_activity_intensity_level || nightlightSummary.economic_activity_intensity_level },
          { key: 'total_radiance', label: '总辐亮', value: nightlightPattern.total_radiance ?? nightlightSummary.total_radiance },
          { key: 'mean_radiance', label: '平均辐亮', value: nightlightPattern.mean_radiance ?? nightlightSummary.mean_radiance },
          { key: 'p90_radiance', label: 'P90 辐亮', value: nightlightPattern.p90_radiance ?? nightlightSummary.p90_radiance },
          { key: 'lit_pixel_ratio', label: '点亮占比', value: nightlightPattern.lit_pixel_ratio ?? nightlightSummary.lit_pixel_ratio },
          { key: 'sector_direction_analysis', label: '夜光扇区方位', value: nightlightPattern.sector_direction_analysis || nightlightSummary.sector_direction_analysis },
          { key: 'road_orientation_analysis', label: '路网方位', value: roadSummary.road_orientation_analysis },
        )
      }
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
        aiPrompt: '区域总结由 AI 生成后经后端校验/规则重写；涉及经济活动强度时仅允许使用夜光和路网等结构化证据。',
        rawInput: {
          section,
          summary_pack: pack,
          nightlight_pattern: nightlightPattern,
          nightlight_summary: nightlightSummary,
          road_summary: roadSummary,
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
        aiPrompt: '该面板为算法指标说明，未调用 AI',
        rawInput: {
          overview: this.nightlightOverview || {},
          layer: this.nightlightLayer || {},
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
        aiPrompt: '该面板为算法指标说明，未调用 AI',
        rawInput: {
          summary,
          diagnostics: this.roadSyntaxDiagnostics || {},
          metric: this.roadSyntaxMetric,
          radius: this.roadSyntaxRadius,
        },
        sourceType: 'rule',
      }
    },
    buildAgentIterationBasisPayload(kind = 'poi') {
      const safeKind = asText(kind) || 'poi'
      const payload = this.getAgentIterationPayload(safeKind)
      const isNightlight = safeKind === 'nightlight'
      const isPoi = safeKind === 'poi'
      const conclusionRows = isNightlight
        ? this.getAgentIterationNightlightAnalysisRows().map((row) => `${row.label}：${row.value}`)
        : this.getAgentIterationPoiAiSummaryRows()
      return {
        title: `${isNightlight ? '夜光多年变化' : 'POI 多年变化'}依据`,
        currentConclusion: conclusionRows.join('\n') || '当前暂无可展示结论。',
        fields: isNightlight
          ? [
            { key: 'period', label: '分析周期', value: payload.period },
            { key: 'trend_rows', label: '趋势指标', value: this.getAgentIterationNightlightTrendRows() },
            { key: 'hotspot_rows', label: '热点变化', value: this.getAgentIterationNightlightHotspotRows() },
          ]
          : [
            { key: 'period', label: '分析周期', value: payload.period },
            { key: 'feature_rows', label: 'POI 特征', value: this.getAgentIterationPoiFeatureRows() },
            { key: 'trend_rows', label: '趋势指标', value: this.getAgentIterationPoiTrendRows() },
            { key: 'spatial_factors', label: '空间因子', value: payload.spatial_factors },
            { key: 'subcategory_spatial_trend_rows', label: '小类空间变化', value: payload.subcategory_spatial_trend_rows },
            { key: 'insight_rows', label: 'AI 洞察', value: this.getAgentIterationPoiAiInsightRows() },
          ],
        rules: [
          '多年迭代先抽取年度快照和结构化指标，再生成趋势判断。',
          'AI 输出会被后端要求按固定 JSON 字段返回，前端只展示通过校验的字段。',
          isPoi ? 'POI 分析关注总量、业态结构、区域分布与增长/衰退方向。' : '夜光分析关注总辐亮、均值、P90、点亮占比和热点迁移。',
        ],
        template: isPoi
          ? '基于{年份序列}的 POI 总量、业态结构和区域分布变化，概括{趋势判断}、{结构变化}与{机会风险}。'
          : '基于近三年夜光快照，概括{趋势判断}、{总体变化}、{热点迁移}与{机会风险}。',
        aiPrompt: 'AI 生成 + 后端校验/重写：将多年快照、趋势指标和关键结构字段喂给模型，要求返回固定 JSON 字段，缺失或不合规内容由规则摘要兜底。',
        rawInput: payload,
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
      return ['poi_fetch', 'population', 'nightlight', 'poi_grid', 'road_syntax']
    },
    mapReadinessTaskToBoardTaskKeys(taskKey = '') {
      const key = asText(taskKey)
      if (!key) return []
      const mapping = {
        poi_fetch: ['poi_fetch'],
        poi_grid: ['poi_grid'],
        population: ['population'],
        nightlight: ['nightlight'],
        road_syntax: ['road_syntax'],
        poi_structure: ['poi_grid'],
        spatial_structure: ['poi_grid', 'population', 'nightlight', 'road_syntax'],
        area_labels: ['poi_grid', 'population', 'nightlight', 'road_syntax'],
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
      if (key === 'poi_grid') return asText(this.h3GridStatus || '')
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
      if (key === 'poi_fetch') {
        return {
          source: asText(this.poiDataSource || this.resultDataSource || ''),
        }
      }
      if (key === 'poi_grid') {
        return {
          resolution: Number(this.h3GridResolution || 0) || 10,
          neighbor_ring: Number(this.h3NeighborRing || 0) || 1,
          include_mode: asText(this.h3GridIncludeMode || ''),
        }
      }
      if (key === 'population') {
        return {
          year: asText(this.populationSelectedYear || ''),
        }
      }
      if (key === 'nightlight') {
        return {
          year: asText(this.nightlightSelectedYear || ''),
        }
      }
      if (key === 'road_syntax') {
        return {
          graph_model: asText(this.roadSyntaxGraphModel || ''),
          metric: asText(this.roadSyntaxLastMetricTab || this.roadSyntaxMetric || ''),
          blue: Number(this.roadSyntaxDisplayBlue || 0),
          red: Number(this.roadSyntaxDisplayRed || 0),
        }
      }
      return {}
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
      if (key === 'poi_fetch') return ['poi_fetch', 'poi_grid']
      if (key === 'poi_grid') return ['poi_grid']
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
      this.agentConversationId = draft.id
      this.activeAgentSessionId = draft.id
      this.agentWorkspaceView = 'chat'
      this.agentInput = ''
      this.agentStatus = 'idle'
      this.agentStage = 'gating'
      this.agentCards = []
      this.agentDecision = { summary: '', mode: 'judgment', strength: 'weak', canAct: false }
      this.agentSupport = []
      this.agentCounterpoints = []
      this.agentActions = []
      this.agentBoundary = []
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
        { key: 'headline', title: '一句话结论', layout: 'text', taskKeys: ['poi_grid', 'population', 'nightlight', 'road_syntax'] },
        { key: 'tags', title: '商业类型标签（ICSC）', layout: 'tags', taskKeys: ['poi_grid'] },
        { key: 'spatial_structure', title: '空间结构', layout: 'panel', taskKeys: ['poi_grid', 'population', 'nightlight', 'road_syntax'] },
        { key: 'poi_structure', title: 'POI结构', layout: 'panel', taskKeys: ['poi_grid'] },
        { key: 'consumption_vitality', title: '经济活动强度', layout: 'panel', taskKeys: ['nightlight'] },
        { key: 'business_support', title: '业态承接', layout: 'panel', taskKeys: ['poi_grid', 'road_syntax'] },
        { key: 'user_profile', title: '用户画像', layout: 'list', taskKeys: ['population'] },
        { key: 'behavior', title: '商业行为推断', layout: 'list', taskKeys: ['nightlight', 'road_syntax'] },
        { key: 'followups', title: '快捷追问', layout: 'actions', taskKeys: ['poi_grid', 'population', 'nightlight', 'road_syntax'] },
      ]
      return sections.map((section) => {
        const live = liveSections[section.key] || {}
        const state = buildTaskState(section.taskKeys)
        let status = 'pending'
        if (['ready', 'failed', 'active'].includes(asText(live.status))) {
          status = asText(live.status)
        } else if (phaseStarted && (section.key === 'headline' || section.key === 'followups')) {
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
            conversation_id: asText(this.activeAgentSessionId || this.agentConversationId),
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
            conversation_id: asText(this.activeAgentSessionId || this.agentConversationId),
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
        })).filter((item) => item.id),
        followupTabs: cloneArray(base.followupTabs).map((item) => ({
          id: asText(item && item.id),
          kind: 'followup',
          title: this.getAgentFollowupWindowTitle(item, item && item.title),
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
          title: this.getAgentSummaryWindowTitle(panelPayloads, item.title || currentSummaryStatus.title),
          panelPayloads,
          content: cloneObject(content),
          evidenceRefs: cloneArray(content.evidence_refs || item.evidenceRefs || []),
        }
      })
      if (!syncedCurrentSummaryTabs.length && shouldAutoCreateCurrentSummary) {
        syncedCurrentSummaryTabs = [{
          id: 'summary-current',
          kind: 'summary',
          title: this.getAgentSummaryWindowTitle(this.agentPanelPayloads, currentSummaryStatus.title),
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
      const validIds = new Set([...nextTabs.summaryTabs.map((item) => item.id), ...nextTabs.iterationChangeTabs.map((item) => item.id), ...nextTabs.siteSelectionTabs.map((item) => item.id), ...nextTabs.followupTabs.map((item) => item.id)])
      if (!validIds.has(nextTabs.activeTabId)) {
        nextTabs.activeTabId = nextTabs.summaryTabs[0] ? nextTabs.summaryTabs[0].id : (nextTabs.iterationChangeTabs[0] ? nextTabs.iterationChangeTabs[0].id : (nextTabs.siteSelectionTabs[0] ? nextTabs.siteSelectionTabs[0].id : (nextTabs.followupTabs[0] ? nextTabs.followupTabs[0].id : '')))
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
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), iterationChangeTabs: cloneArray(tabs.iterationChangeTabs), siteSelectionTabs: cloneArray(tabs.siteSelectionTabs), followupTabs: cloneArray(tabs.followupTabs) }
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
      target.title = this.getAgentSummaryWindowTitle(panelPayloads, target.title || '区域总结')
      target.panelPayloads = panelPayloads
      target.content = cloneObject(summaryPack)
      target.evidenceRefs = cloneArray(summaryPack.evidence_refs || [])
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), iterationChangeTabs: cloneArray(tabs.iterationChangeTabs), siteSelectionTabs: cloneArray(tabs.siteSelectionTabs), followupTabs: cloneArray(tabs.followupTabs) }
    },
    switchAgentTopTab(tabId = '') {
      const nextId = asText(tabId)
      if (!nextId) return
      this.closeAgentCreateTabMenu()
      this.captureAgentActiveSummaryTabState()
      this.captureAgentActiveFollowupTabState()
      const tabs = this.ensureAgentTabs(true)
      if (tabs.activeTabId === nextId) return
      tabs.activeTabId = nextId
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), iterationChangeTabs: cloneArray(tabs.iterationChangeTabs), siteSelectionTabs: cloneArray(tabs.siteSelectionTabs), followupTabs: cloneArray(tabs.followupTabs) }
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
    openAgentCreateTabMenu() {
      this.agentCreateTabMenuOpen = true
    },
    closeAgentCreateTabMenu() {
      this.agentCreateTabMenuOpen = false
    },
    toggleAgentCreateTabMenu(event = null) {
      if (event && typeof event.stopPropagation === 'function') event.stopPropagation()
      this.agentCreateTabMenuOpen = !this.agentCreateTabMenuOpen
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
        id: reuseExisting ? 'summary-current' : this.createAgentSummaryWindowId(),
        kind: 'summary',
        source: 'current',
        sessionId: '',
        readonly: false,
        createdAt: new Date().toISOString(),
        panelPayloads,
        content: cloneObject(summaryPack),
        evidenceRefs: cloneArray(summaryPack.evidence_refs || []),
      }
      summaryTab.title = this.getAgentSummaryWindowTitle(panelPayloads, options.title)
      summaryTab.panelPayloads = panelPayloads
      summaryTab.content = cloneObject(summaryPack)
      summaryTab.evidenceRefs = cloneArray(summaryPack.evidence_refs || [])
      if (!existing) {
        tabs.summaryTabs = [...cloneArray(tabs.summaryTabs), summaryTab]
      } else {
        tabs.summaryTabs = cloneArray(tabs.summaryTabs).map((item) => (item.id === existing.id ? summaryTab : item))
      }
      tabs.activeTabId = summaryTab.id
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), iterationChangeTabs: cloneArray(tabs.iterationChangeTabs), siteSelectionTabs: cloneArray(tabs.siteSelectionTabs), followupTabs: cloneArray(tabs.followupTabs) }
      this.closeAgentCreateTabMenu()
      this.syncActiveAgentRuntimeView(this.activeAgentSessionId)
      this.syncSummaryTaskBoardFromLocalResults()
      this.syncCurrentAgentSession()
      this.refreshAgentSummaryReadiness(false)
      return summaryTab.id
    },
    createAgentSiteSelectionTab(options = {}) {
      const tabs = this.ensureAgentTabs(true)
      this.captureAgentActiveSummaryTabState()
      this.captureAgentActiveFollowupTabState()
      const tabId = this.createAgentSiteSelectionWindowId()
      const tab = {
        id: tabId,
        kind: 'site_selection',
        title: this.formatAgentTabTitle('site_selection', options.title),
        source: asText(options.source) || 'draft',
        sessionId: '',
        readonly: false,
        createdAt: new Date().toISOString(),
      }
      tabs.siteSelectionTabs = [...cloneArray(tabs.siteSelectionTabs), tab]
      tabs.activeTabId = tabId
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), iterationChangeTabs: cloneArray(tabs.iterationChangeTabs), siteSelectionTabs: cloneArray(tabs.siteSelectionTabs), followupTabs: cloneArray(tabs.followupTabs) }
      this.closeAgentCreateTabMenu()
      this.syncActiveAgentRuntimeView(this.activeAgentSessionId)
      this.syncCurrentAgentSession()
      return tabId
    },
    createAgentIterationChangeTab(options = {}) {
      const tabs = this.ensureAgentTabs(true)
      this.captureAgentActiveSummaryTabState()
      this.captureAgentActiveFollowupTabState()
      const reuseExisting = !!options.reuseExisting
      const existing = reuseExisting
        ? cloneArray(tabs.iterationChangeTabs).find((item) => asText(item.source) === 'current')
        : null
      const tabId = existing ? existing.id : this.createAgentIterationChangeWindowId()
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
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), iterationChangeTabs: cloneArray(tabs.iterationChangeTabs), siteSelectionTabs: cloneArray(tabs.siteSelectionTabs), followupTabs: cloneArray(tabs.followupTabs) }
      this.closeAgentCreateTabMenu()
      this.syncActiveAgentRuntimeView(this.activeAgentSessionId)
      this.syncCurrentAgentSession()
      if (options.autoload !== false) {
        this.ensureAgentIterationKind(tab.activeKind).catch((err) => {
          console.warn('Agent iteration load failed', err)
        })
      }
      return tabId
    },
    createAgentFollowupTab(options = {}) {
      const tabs = this.ensureAgentTabs(true)
      if (!this.canCreateAgentFollowupTab()) {
        window.alert(`最多可创建 ${tabs.followupLimit} 个追问解释标签，请先关闭旧标签。`)
        return null
      }
      this.captureAgentActiveFollowupTabState()
      const number = Number(tabs.nextFollowupNumber || (tabs.followupTabs.length + 1))
      const tabId = `followup-${number}`
      const seedPrompt = asText(options.seedPrompt)
      const thread = this.createAgentFollowupThreadState({
        input: seedPrompt,
      })
      const title = this.getAgentFollowupWindowTitle({
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
      this.closeAgentCreateTabMenu()
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
        title: this.getAgentSummaryWindowTitle(panelPayloads, session && session.title),
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
        title: this.getAgentFollowupWindowTitle(session, session && session.title),
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
      const tabs = this.ensureAgentTabs(true)
      const tab = this.buildAgentHistorySummaryTab(session)
      const existing = cloneArray(tabs.summaryTabs).find((item) => item.sessionId === tab.sessionId || item.id === tab.id)
      if (existing) {
        tabs.activeTabId = existing.id
      } else {
        tabs.summaryTabs = [...cloneArray(tabs.summaryTabs), tab]
        tabs.activeTabId = tab.id
      }
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), iterationChangeTabs: cloneArray(tabs.iterationChangeTabs), siteSelectionTabs: cloneArray(tabs.siteSelectionTabs), followupTabs: cloneArray(tabs.followupTabs) }
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
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), iterationChangeTabs: cloneArray(tabs.iterationChangeTabs), siteSelectionTabs: cloneArray(tabs.siteSelectionTabs), followupTabs: cloneArray(tabs.followupTabs) }
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
      this.agentWorkspaceView = 'chat'
      if (this.isAgentSummaryHistorySession(session)) {
        return this.openAgentSummaryHistoryTab(session)
      }
      return this.openAgentFollowupHistoryTab(session)
    },
    closeAgentTopTab(tabId = '', event = null) {
      if (event && typeof event.stopPropagation === 'function') event.stopPropagation()
      const targetId = asText(tabId)
      if (!targetId) return
      const tabs = this.ensureAgentTabs(true)
      const currentActiveId = asText(tabs.activeTabId)
      const orderedIds = [...cloneArray(tabs.summaryTabs).map((item) => item.id), ...cloneArray(tabs.iterationChangeTabs).map((item) => item.id), ...cloneArray(tabs.siteSelectionTabs).map((item) => item.id), ...cloneArray(tabs.followupTabs).map((item) => item.id)]
      const targetIndex = Math.max(0, orderedIds.indexOf(targetId))
      tabs.summaryTabs = cloneArray(tabs.summaryTabs).filter((item) => item.id !== targetId)
      tabs.iterationChangeTabs = cloneArray(tabs.iterationChangeTabs).filter((item) => item.id !== targetId)
      tabs.siteSelectionTabs = cloneArray(tabs.siteSelectionTabs).filter((item) => item.id !== targetId)
      tabs.followupTabs = cloneArray(tabs.followupTabs).filter((item) => item.id !== targetId)
      if (currentActiveId === targetId) {
        const nextIds = [...cloneArray(tabs.summaryTabs).map((item) => item.id), ...cloneArray(tabs.iterationChangeTabs).map((item) => item.id), ...cloneArray(tabs.siteSelectionTabs).map((item) => item.id), ...cloneArray(tabs.followupTabs).map((item) => item.id)]
        const fallbackIndex = Math.max(0, Math.min(targetIndex - 1, nextIds.length - 1))
        tabs.activeTabId = nextIds[fallbackIndex] || ''
        const activeFollowup = tabs.followupTabs.find((item) => item.id === tabs.activeTabId)
        if (activeFollowup) this.applyAgentFollowupThreadToCurrentState(activeFollowup.thread)
      }
      this.agentTabs = tabs
      this.syncActiveAgentRuntimeView(this.activeAgentSessionId)
      this.syncCurrentAgentSession()
    },
    closeAgentFollowupTab(tabId = '', event = null) {
      this.closeAgentTopTab(tabId, event)
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
    getAgentIterationKinds() {
      return [
        { key: 'poi', label: 'POI', disabled: false },
        { key: 'population', label: '人口', disabled: false },
        { key: 'nightlight', label: '夜光', disabled: false },
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
    getAgentIterationPopulationFeatureRows() {
      const payload = this.getAgentIterationPopulationPayload()
      const series = cloneArray(payload.series || (payload.timeseries && payload.timeseries.series))
      const layerSummary = (((payload.timeseries || {}).layer || {}).summary) || {}
      const first = series[0] || {}
      const last = series[series.length - 1] || first
      const countDelta = Number(last.total_population ?? last.population ?? 0) - Number(first.total_population ?? first.population ?? 0)
      const densityDelta = Number(last.population_density ?? last.density ?? 0) - Number(first.population_density ?? first.density ?? 0)
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
    getAgentIterationPoiAiSummaryRows() {
      const payload = this.getAgentIterationPoiPayload()
      const rows = cloneArray(payload.ai_summary).map((item) => asText(item)).filter(Boolean)
      if (rows.length) return rows
      return cloneArray(payload.rule_summary).map((item) => asText(item)).filter(Boolean)
    },
    getAgentIterationPoiAiInsightRows() {
      const payload = this.getAgentIterationPoiPayload()
      const insights = cloneObject(payload.ai_insights)
      const fallback = cloneObject(payload.rule_insights)
      const formatInsightValue = (value) => {
        if (value && typeof value === 'object' && !Array.isArray(value)) {
          const category = asText(value.category)
          const subcategory = asText(value.subcategory)
          const area = asText(value.area || value.region)
          const delta = value.delta ?? value.change ?? ''
          const count = value.count ?? ''
          const parts = []
          if (category) parts.push(`大类：${category}`)
          if (subcategory) parts.push(`小类：${subcategory}${category && !subcategory.includes(category) ? `（${category}）` : ''}`)
          if (area) parts.push(`区域：${area}`)
          if (delta !== '') parts.push(`变化：${delta}`)
          if (count !== '') parts.push(`数量：${count}`)
          return parts.join('；') || JSON.stringify(value)
        }
        if (Array.isArray(value)) return value.map((item) => formatInsightValue(item)).filter(Boolean).join('；')
        return asText(value)
      }
      return [
        { key: 'fastest_growth', label: '增长最快行业', value: formatInsightValue(insights.fastest_growth || fallback.fastest_growth) },
        { key: 'declining_category', label: '衰退行业', value: formatInsightValue(insights.declining_category || fallback.declining_category) },
        { key: 'emerging_area', label: '新兴区域', value: formatInsightValue(insights.emerging_area || fallback.emerging_area) },
        { key: 'structure_judgement', label: '结构判断', value: formatInsightValue(insights.structure_judgement || fallback.structure_judgement) },
      ].filter((item) => item.value)
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
      const rows = cloneArray(this.getAgentIterationPoiPayload().area_heatmaps)
        .filter((row) => row && asText(row.year))
        .sort((a, b) => Number(a.year || 0) - Number(b.year || 0))
      if (!rows.length) return []
      const counts = rows.map((row) => Number(row.point_count || cloneArray(row.points).length || 0))
      const minCount = Math.min(...counts)
      const maxCount = Math.max(...counts)
      const span = Math.max(1, maxCount - minCount)
      let previous = null
      return rows.map((row) => {
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
          delta_ratio_from_previous: ratio,
          count_level: (count - minCount) / span,
        }
      })
    },
    getAgentIterationPoiAreaHeatmapBasemap() {
      return cloneObject(this.getAgentIterationPoiPayload().area_heatmap_basemap)
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
    getAgentIterationPoiAreaHeatmapAspectStyle() {
      const basemap = this.getAgentIterationPoiAreaHeatmapBasemap()
      const aspectRatio = asText(basemap.aspect_ratio)
      if (aspectRatio) return { aspectRatio }
      const size = this.getAgentIterationPoiAreaHeatmapViewSize()
      return { aspectRatio: `${size.width} / ${size.height}` }
    },
    getAgentIterationPoiAreaHeatmapBoundary() {
      return cloneArray(this.getAgentIterationPoiPayload().area_heatmap_boundary)
    },
    getAgentIterationPoiAreaHeatmapBoundaryPoints() {
      return this.getAgentIterationPoiAreaHeatmapBoundary()
        .map((point) => `${Number(point.x || 0).toFixed(2)},${Number(point.y || 0).toFixed(2)}`)
        .join(' ')
    },
    getAgentIterationPoiAreaHeatmapPolygon() {
      return cloneArray(this.getAgentIterationPoiPayload().area_heatmap_polygon)
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
      return `${asText(payload.historyId || payload.history_id)}|${years}|${counts}|${polygon.length}:${polygon.slice(0, 80)}`
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

      const placeholders = cloneArray(payload.area_heatmap_snapshots).length
        ? cloneArray(payload.area_heatmap_snapshots)
        : this.buildAgentPoiAreaHeatmapSnapshotPlaceholders(payload)
      this.commitAgentIterationPoiPayload({
        area_heatmap_snapshots: placeholders.map((item) => ({
          ...item,
          status: asText(item.image_url) ? 'ready' : 'loading',
          error: '',
        })),
      })

      this.agentIterationPoiSnapshotGeneratingKey = cacheKey
      try {
        const snapshots = []
        for (const summary of cloneArray(payload.summaries)) {
          const year = summary.year
          const base = placeholders.find((item) => String(item.year) === String(year)) || {}
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
      host.style.cssText = 'position:fixed;left:-20000px;top:0;width:760px;height:420px;background:#fff;z-index:-1;pointer-events:none;overflow:hidden;'
      document.body.appendChild(host)
      return host
    },
    waitForAgentPoiSnapshotPaint(ms = 650) {
      return new Promise((resolve) => window.setTimeout(resolve, Math.max(0, Number(ms) || 0)))
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
    async renderAgentIterationPoiAreaSnapshot(summary = {}, payload = {}) {
      if (!window.AMap || typeof AMap.Map !== 'function') throw new Error('amap_unavailable')
      if (typeof html2canvas !== 'function') throw new Error('html2canvas_unavailable')
      const points = cloneArray(summary.points).filter((point) => Number.isFinite(Number(point.lng)) && Number.isFinite(Number(point.lat)))
      if (!points.length) throw new Error('no_points')
      const polygonPath = this.normalizeAgentIterationSnapshotPolygon(payload.area_heatmap_polygon)
      const host = this.getOrCreateAgentIterationPoiSnapshotHost()
      host.innerHTML = ''
      const mapEl = document.createElement('div')
      mapEl.style.cssText = 'width:760px;height:420px;position:relative;background:#fff;overflow:hidden;'
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
        points.slice(0, 1200).forEach((point, index) => {
          const marker = new AMap.Marker({
            position: [Number(point.lng), Number(point.lat)],
            title: asText(point.subcategory || point.category || `POI ${index + 1}`),
            content: '<div class="marker-dot marker-restaurant"></div>',
            offset: new AMap.Pixel(-8, -8),
            zIndex: 30,
          })
          marker.setMap(map)
          overlays.push(marker)
        })
        if (polygonOverlay && typeof map.setFitView === 'function') {
          map.setFitView([polygonOverlay], false, [28, 28, 28, 28])
        } else if (typeof map.setFitView === 'function') {
          map.setFitView(overlays, false, [28, 28, 28, 28])
        }
        await this.waitForAgentPoiSnapshotPaint()
        this.cleanAgentPoiSnapshotMapChrome(mapEl)
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
    buildAgentPoiAreaHeatmaps(summaries = []) {
      const sorted = cloneArray(summaries).filter((item) => cloneArray(item.points).length).sort((a, b) => Number(a.year || 0) - Number(b.year || 0))
      if (!sorted.length) return []
      const allPoints = sorted.flatMap((summary) => cloneArray(summary.points))
      const lngs = allPoints.map((point) => Number(point.lng)).filter(Number.isFinite)
      const lats = allPoints.map((point) => Number(point.lat)).filter(Number.isFinite)
      if (!lngs.length || !lats.length) return []
      const minLng = Math.min(...lngs)
      const maxLng = Math.max(...lngs)
      const minLat = Math.min(...lats)
      const maxLat = Math.max(...lats)
      const refLat = (minLat + maxLat) / 2
      const metersPerLon = Math.max(1000, 111320 * Math.abs(Math.cos((refLat * Math.PI) / 180)))
      const projectPoint = (lng, lat) => ({
        x: Number(lng) * metersPerLon,
        y: Number(lat) * 111320,
      })
      const minProjected = projectPoint(minLng, minLat)
      const maxProjected = projectPoint(maxLng, maxLat)
      const spanX = Math.max(maxProjected.x - minProjected.x, 1e-9)
      const spanY = Math.max(maxProjected.y - minProjected.y, 1e-9)
      return sorted.map((summary) => {
        const points = cloneArray(summary.points).map((point) => ({
          x: Math.max(4, Math.min(96, 4 + ((projectPoint(point.lng, point.lat).x - minProjected.x) / spanX) * 92)),
          y: Math.max(4, Math.min(96, 96 - ((projectPoint(point.lng, point.lat).y - minProjected.y) / spanY) * 92)),
          area: asText(point.area),
          category: asText(point.category),
          subcategory: asText(point.subcategory),
        }))
        const gridSize = 12
        const cellCounts = new Map()
        points.forEach((point) => {
          const col = Math.max(0, Math.min(gridSize - 1, Math.floor(Number(point.x || 0) / (100 / gridSize))))
          const row = Math.max(0, Math.min(gridSize - 1, Math.floor(Number(point.y || 0) / (100 / gridSize))))
          const key = `${col}:${row}`
          cellCounts.set(key, (cellCounts.get(key) || 0) + 1)
        })
        const maxCellCount = Math.max(1, ...Array.from(cellCounts.values()))
        const cells = Array.from(cellCounts.entries())
          .map(([key, count]) => {
            const [col, row] = key.split(':').map((item) => Number(item))
            return {
              x: Number(((col * 100) / gridSize).toFixed(3)),
              y: Number(((row * 100) / gridSize).toFixed(3)),
              width: Number((100 / gridSize).toFixed(3)),
              height: Number((100 / gridSize).toFixed(3)),
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
            emerging_area: topArea.name ? `当前核心聚集区：${topArea.name}` : '当前缺少可识别的新兴区域信号。',
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
      const emergingArea = areaNames.map((name) => ({
        name,
        before: Number(firstAreas[name] || 0),
        after: Number(lastAreas[name] || 0),
        delta: Number(lastAreas[name] || 0) - Number(firstAreas[name] || 0),
      })).filter((item) => item.delta > 0).sort((a, b) => b.delta - a.delta)[0]
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
          emerging_area: emergingArea ? `${emergingArea.name}（+${emergingArea.delta}）` : '未发现明显新兴区域。',
          structure_judgement: topCategory.name ? `一级结构偏向${topCategory.name}主导${topSubcategory.name ? `，其下小类${topSubcategory.name}表现突出` : ''}，需结合目标业态判断消费型/生产型属性。` : '结构判断信号有限。',
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
        rule_insights: cloneObject(payload.rule_insights),
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
    async requestAgentPoiIterationBuild({ historyId = '', years = [], center = undefined } = {}) {
      const res = await fetch('/api/v1/analysis/agent/iteration/poi/build', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          history_id: asText(historyId),
          years: cloneArray(years).map((item) => Number(item)).filter((item) => Number.isFinite(item)),
          center,
        }),
      })
      if (!res.ok) {
        let detail = ''
        try { detail = await res.text() } catch (_) {}
        throw new Error(detail || 'POI 多年迭代聚合失败')
      }
      return res.json()
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
    async ensureAgentIterationPoi(force = false) {
      const existing = this.getAgentIterationPoiPayload()
      if (!force && asText(existing.status) === 'ready') return existing
      if (this.agentIterationPoiLoading) return existing
      const targetTabId = asText(this.getAgentActiveTopTab().kind) === 'iteration_change'
        ? asText(this.getAgentActiveTopTab().id)
        : ''
      this.agentIterationPoiLoading = true
      this.agentIterationPoiError = ''
      this.commitAgentIterationPoiPayload({ status: 'loading', error: '' }, { tabId: targetTabId })
      try {
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
          const builtPayload = await this.requestAgentPoiIterationBuild({ historyId, years: historyYears, center })
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
            rule_summary: cloneArray(builtPayload.rule_summary),
            rule_insights: cloneObject(builtPayload.rule_insights),
            ai_summary: cloneArray(builtPayload.ai_summary),
            ai_insights: cloneObject(builtPayload.ai_insights),
            ai_error: asText(builtPayload.ai_error),
            error: asText(builtPayload.error),
          }, { tabId: targetTabId })
          this.ensureAgentIterationPoiAreaHeatmapSnapshots(committed).catch((err) => {
            console.warn('[agent-iteration-poi] area snapshot generation failed', err)
          })
          return committed
        }
        const pois = cloneArray(this.allPoisDetails)
        if (pois.length) {
          const year = Number.isFinite(Number(this.currentHistorySelectedPoiYear || this.resultPoiYear))
            ? Number(this.currentHistorySelectedPoiYear || this.resultPoiYear)
            : null
          const summary = this.summarizeAgentIterationPois(pois, year)
          const rule = this.buildAgentPoiRuleInsights([summary])
          const committed = this.commitAgentIterationPoiPayload({
            status: 'ready',
            source: 'current',
            years: year ? [year] : [],
            summaries: [summary],
            trend_rows: [],
            total_series: [],
            category_stack: [],
            subcategory_stack: [],
            subcategory_trend_rows: [],
            area_heatmaps: this.buildAgentPoiAreaHeatmaps([summary]),
            area_heatmap_polygon: this.getIsochronePolygonPayload ? cloneArray(this.getIsochronePolygonPayload()) : [],
            area_heatmap_snapshots: this.buildAgentPoiAreaHeatmapSnapshotPlaceholders({
              summaries: [summary],
              area_heatmaps: this.buildAgentPoiAreaHeatmaps([summary]),
            }),
            spatial_factors: {},
            subcategory_spatial_trend_rows: [],
            subcategory_spatial_summary: [],
            rule_summary: rule.summary,
            rule_insights: rule.insights,
            ai_summary: [],
            ai_insights: {},
            ai_error: '',
            notice: '当前只有一个年份 POI，只展示特征；多年趋势需要从包含多个年份的历史记录恢复。',
            error: '',
          }, { tabId: targetTabId })
          this.ensureAgentIterationPoiAreaHeatmapSnapshots(committed).catch((err) => {
            console.warn('[agent-iteration-poi] area snapshot generation failed', err)
          })
          return committed
        }
        throw new Error('当前没有可分析的 POI 明细')
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
    buildAgentIterationSnapshotSvgMarkupFromNode(svgNode = null) {
      if (!svgNode || typeof XMLSerializer === 'undefined') return ''
      const cloned = svgNode.cloneNode(true)
      cloned.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
      cloned.setAttribute('width', '360')
      cloned.setAttribute('height', '260')
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
      if (/llm_unavailable/i.test(raw)) return 'AI 服务暂未启用，当前先展示结构化变化指标与年度快照。'
      if (/invalid_ai_analysis/i.test(raw)) return 'AI 解析结果格式异常，当前先展示结构化变化指标与年度快照。'
      return raw
    },
    shouldShowAgentComposer() {
      const activeTab = this.getAgentActiveTopTab()
      return asText(activeTab.kind) === 'followup'
    },
    buildAgentTabsUiState() {
      this.captureAgentActiveSummaryTabState()
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
            title: this.getAgentSummaryWindowTitle({ summary_pack: legacyPack }, '区域总结'),
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
        title: this.getAgentFollowupWindowTitle(item, item && item.title),
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
      const activeId = asText(uiState.active_tab_id)
      this.agentTabs = {
        summaryTab: summaryTab.id ? summaryTab : defaultTabs.summaryTab,
        summaryTabs,
        iterationChangeTabs,
        siteSelectionTabs: [],
        followupTabs,
        activeTabId: activeId || (summaryTabs[0] ? summaryTabs[0].id : (iterationChangeTabs[0] ? iterationChangeTabs[0].id : (followupTabs[0] ? followupTabs[0].id : ''))),
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
      this.agentWorkspaceView = 'chat'
      this.ensureAgentFollowupTabForPrompt(text)
      this.agentInput = text
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
    backToAgentChat() {
      this.agentWorkspaceView = 'chat'
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
      if (!this.agentShouldRenderThinkingBlock() || !messages.length) return -1
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
      const targetSessionId = asText(sessionId || this.activeAgentSessionId || this.agentConversationId)
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
      )
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
      if (!window.confirm('确定要删除这条对话吗？')) return

      const previousSessions = this.agentSessions
        .map((item) => cloneAgentSessionRecord(item))
        .filter((item) => !!item)
      const previousActiveSessionId = asText(this.activeAgentSessionId)
      const previousConversationId = asText(this.agentConversationId)
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
          this.agentConversationId = previousConversationId
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
          window.alert(`删除对话失败: ${err && err.message ? err.message : String(err)}`)
          return
        }
      }
    },
  }
}

export {
  createAgentUiMethods,
}
