import {
  asText,
  clampText,
  cloneArray,
  cloneAgentSessionRecord,
  cloneObject,
  consumeSseStream,
  createAgentSessionRecord,
  hasAgentMessageProcessContent,
  normalizeAgentMessageProcess,
  normalizeAgentPanelPreloadNotes,
  normalizeAgentToolSummary,
  sortAgentSessions,
} from './normalizers.js'
import {
  buildAgentPlanChecklist,
  buildAgentToolCallItems,
  hasAgentExecutionTraceContent,
  hasAgentPlanContent,
  shouldShowAgentProcessLiveStatus,
  shouldShowAgentProcessToggle,
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

export function createAgentThreadUiMethods() {
  return {
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
        || asText(this.agentAnswer)
        || this.agentError
        || this.agentClarificationQuestion
        || this.agentRiskPrompt,
      )
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
    getAgentToolDetail() {
      const targetName = asText(this.agentActiveToolDetailName)
      if (!targetName) return null
      return Array.isArray(this.agentTools)
        ? this.agentTools.find((tool) => asText(tool && tool.name) === targetName) || null
        : null
    },
    getGroupedAgentTools() {
      const tierOrder = ['foundation', 'retrieval', 'source', 'dataset', 'business_analyst', 'capability', 'scenario']
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
          description: this.getAgentToolGroupDescription(tierKey),
          subgroups: Array.from(subgroupMap.entries()).map(([subgroupKey, subgroupTools]) => ({
            key: subgroupKey,
            label: this.getAgentToolLabel(subgroupKey),
            tools: subgroupTools.slice().sort((a, b) => a.name.localeCompare(b.name, 'zh-Hans-CN')),
          })),
        })
      })
      return groups
    },
    getAgentToolGroupDescription(tierKey = '') {
      const descriptions = {
        foundation: '读取当前范围和已有结果，避免在对话中重复计算。',
        retrieval: '检索分析和报告证据，给回答提供可追溯上下文。',
        source: '读取用户已选资料，支撑快速问答和 PPT 材料复用。',
        dataset: '查询与聚合范围数据集，按需返回结构化记录。',
        business_analyst: '规划外部 Business Analyst 分析，不在对话内直接执行高成本流程。',
        capability: '保留的能力接口分组。',
        scenario: '保留的场景接口分组。',
      }
      return descriptions[asText(tierKey)] || '当前 Agent 可调用的工具。'
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
    getAgentThreadMessages() {
      return cloneArray(this.agentMessages)
    },
    getAgentMessageProcess(message = {}) {
      return normalizeAgentMessageProcess(message && message.process)
    },
    shouldShowAgentMessageProcess(message = {}) {
      return asText(message && message.role) === 'assistant'
        && hasAgentMessageProcessContent(this.getAgentMessageProcess(message))
    },
    getAgentMessageProcessKey(message = {}, index = 0) {
      const process = this.getAgentMessageProcess(message)
      return asText(process.turnId || message.id) || `agent-message-process-${index}`
    },
    isAgentMessageProcessExpanded(message = {}, index = 0) {
      const key = this.getAgentMessageProcessKey(message, index)
      return !!(this.agentMessageProcessExpandedIds && this.agentMessageProcessExpandedIds[key])
    },
    toggleAgentMessageProcessExpanded(message = {}, index = 0) {
      const key = this.getAgentMessageProcessKey(message, index)
      if (!key) return
      this.agentMessageProcessExpandedIds = {
        ...(this.agentMessageProcessExpandedIds || {}),
        [key]: !this.isAgentMessageProcessExpanded(message, index),
      }
    },
    getAgentMessageProcessElapsedLabel(message = {}) {
      const process = this.getAgentMessageProcess(message)
      let elapsedMs = Number(process.elapsedMs || 0) || 0
      if (!elapsedMs && process.startedAt && process.completedAt) {
        const startedAt = Date.parse(process.startedAt)
        const completedAt = Date.parse(process.completedAt)
        if (Number.isFinite(startedAt) && Number.isFinite(completedAt) && completedAt >= startedAt) {
          elapsedMs = completedAt - startedAt
        }
      }
      if (!elapsedMs) return ''
      const seconds = Math.max(1, Math.round(elapsedMs / 1000))
      return `${seconds}s`
    },
    getAgentMessageProcessStatusLabel(message = {}) {
      const elapsed = this.getAgentMessageProcessElapsedLabel(message)
      if (elapsed) return `已处理 ${elapsed}`
      const process = this.getAgentMessageProcess(message)
      const mapping = {
        answered: '已思考',
        failed: '思考失败',
        requires_clarification: '已思考',
        requires_risk_confirmation: '等待确认',
        running: '思考中',
      }
      return mapping[asText(process.status)] || '已思考'
    },
    getAgentMessageNaturalProcessItems(message = {}) {
      return this.getAgentNaturalProcessItems(this.getAgentMessageProcess(message))
    },
    isAgentLatestAssistantMessage(message = {}, index = 0) {
      if (asText(message && message.role) !== 'assistant') return false
      const messages = cloneArray(this.agentMessages)
      for (let cursor = messages.length - 1; cursor >= 0; cursor -= 1) {
        if (asText(messages[cursor] && messages[cursor].role) === 'assistant') {
          return cursor === index
        }
      }
      return false
    },
    getAgentMessageTaskConfirmation(message = {}, index = 0) {
      if (!this.isAgentLatestAssistantMessage(message, index)) return null
      return this.getAgentTaskConfirmation(this.getAgentMessageProcess(message))
    },
    agentLatestAssistantMessageHasProcess() {
      const messages = cloneArray(this.agentMessages)
      for (let index = messages.length - 1; index >= 0; index -= 1) {
        const message = messages[index]
        if (asText(message && message.role) !== 'assistant') continue
        return this.shouldShowAgentMessageProcess(message)
      }
      return false
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
      if (!this.agentLoading && asText(this.agentStatus) === 'answered' && this.agentLatestAssistantMessageHasProcess()) {
        return false
      }
      return true
    },
    shouldShowAgentThinkingLiveStatus() {
      return shouldShowAgentProcessLiveStatus(this.agentStatus, {
        hasContent: this.agentHasThinkingContent(),
        isLoading: this.agentLoading,
      })
    },
    shouldShowAgentThinkingToggle() {
      return shouldShowAgentProcessToggle(this.agentStatus, {
        hasContent: this.agentHasThinkingContent(),
        isLoading: this.agentLoading,
      })
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
    getAgentVisibleProcessSteps(process = null) {
      const processContext = process ? normalizeAgentMessageProcess(process) : null
      const steps = cloneArray(processContext ? processContext.thinkingTimeline : this.agentThinkingTimeline)
        .map((item) => ({
          id: asText(item && item.id),
          phase: asText(item && item.phase),
          title: asText(item && item.title) || '处理中',
          detail: asText(item && item.detail),
          displayText: asText(item && (item.displayText || item.display_text)),
          resultSummary: asText(item && (item.resultSummary || item.result_summary)),
          items: cloneArray(item && item.items).map((entry) => asText(entry)).filter(Boolean),
          meta: cloneObject(item && item.meta),
          state: asText(item && item.state) || 'pending',
        }))
        .filter((item) => item.id !== 'stream-connect')
      const hasBackendStep = steps.some((item) => item.id && !item.id.startsWith('frontend-'))
      if (!hasBackendStep) return steps
      return steps.filter((item) => !item.id.startsWith('frontend-wait-'))
    },
    getAgentNaturalProcessItems(process = null) {
      const processContext = process ? normalizeAgentMessageProcess(process) : null
      const toolLabels = {
        read_current_scope: '读取当前分析范围',
        read_current_results: '读取已有分析结果',
        list_selected_sources: '列出已选资料',
        search_selected_source_evidence: '检索已选资料证据',
        read_selected_source_evidence_node: '读取资料证据节点',
        search_analysis_context: '检索分析上下文',
        read_analysis_evidence_node: '读取分析证据节点',
        search_report_context: '检索报告上下文',
        read_report_evidence_node: '读取报告证据节点',
        list_scope_datasets: '列出范围数据集',
        query_scope_dataset: '查询范围数据',
        aggregate_scope_dataset: '聚合范围数据',
        read_scope_record: '读取范围记录',
        plan_business_analyst_analysis: '规划 Business Analyst 分析',
      }
      const forbiddenLabels = new Set(['思考', '行动', '观察', '复盘', '异常'])
      const genericResultLabels = new Set(['执行成功', '成功', '已完成', '完成', 'ok', 'OK', '无结果'])
      const clean = (value = '') => asText(value)
        .replace(/^(思考|行动|观察|复盘|异常)\s*[·:：-]?\s*/u, '')
        .trim()
      const cleanResultSummary = (value = '') => {
        const text = clean(value)
        return genericResultLabels.has(text) ? '' : text
      }
      const readItemValue = (items = [], prefix = '') => {
        const matched = cloneArray(items)
          .map((entry) => asText(entry))
          .find((entry) => entry.startsWith(prefix))
        return matched ? matched.slice(prefix.length).trim() : ''
      }
      const formatTool = (name = '') => {
        const normalizedName = asText(name)
        return toolLabels[normalizedName] || normalizedName || '工具'
      }
      const makeTextItem = (seed = {}) => {
        const text = clean(seed.text)
        if (!text || forbiddenLabels.has(text)) return null
        return {
          id: seed.id,
          kind: seed.kind || 'text',
          text,
          metaText: clean(seed.metaText),
          state: asText(seed.state) || 'pending',
        }
      }
      const items = []
      const visibleSteps = this.getAgentVisibleProcessSteps(processContext)
      const hasBackendStep = visibleSteps.some((step) => {
        const id = asText(step && step.id)
        return id && !id.startsWith('frontend-')
      })
      const seenText = new Set()
      visibleSteps.forEach((step, index) => {
        const meta = cloneObject(step && step.meta)
        const toolName = asText(meta.toolName || meta.tool_name)
        const status = asText(meta.status)
        const argumentsSummary = readItemValue(step.items, '参数：')
        const evidenceSummary = readItemValue(step.items, '证据：')
        const warningSummary = readItemValue(step.items, '警告：')
        const displayText = clean(step.displayText)
        if (toolName) {
          if (status === 'start' || status === 'active' || !status) {
            const metaParts = []
            if (displayText) metaParts.push(displayText)
            if (argumentsSummary && argumentsSummary !== '无参数') metaParts.push(`参数：${argumentsSummary}`)
            const toolItem = makeTextItem({
              id: `${step.id || index}-tool-start`,
              kind: 'tool',
              text: `调用工具：${formatTool(toolName)}`,
              metaText: metaParts.join('；'),
              state: step.state,
            })
            if (toolItem) items.push(toolItem)
            return
          }
          const metaParts = []
          if (evidenceSummary) metaParts.push(`证据：${evidenceSummary}`)
          if (warningSummary) metaParts.push(`警告：${warningSummary}`)
          const resultText = displayText || cleanResultSummary(step.resultSummary)
          if (!resultText) return
          const resultItem = makeTextItem({
            id: `${step.id || index}-tool-result`,
            kind: status === 'success' ? 'result' : 'warning',
            text: resultText,
            metaText: metaParts.join('；'),
            state: step.state,
          })
          if (resultItem) items.push(resultItem)
          return
        }
        if (hasBackendStep && asText(step.id).startsWith('frontend-')) return
        const text = displayText
        if (!text) return
        if (seenText.has(text)) return
        seenText.add(text)
        const plainItem = makeTextItem({
          id: step.id || `process-${index}`,
          kind: 'text',
          text,
          state: step.state,
        })
        if (plainItem) items.push(plainItem)
      })
      const planChecklist = this.getAgentPlanChecklist(processContext)
      if (planChecklist.visible && planChecklist.summary && !items.some((item) => item.id === 'agent-plan-summary')) {
        const planItem = makeTextItem({
          id: 'agent-plan-summary',
          kind: 'text',
          text: planChecklist.summary,
          metaText: planChecklist.progressLabel,
          state: 'completed',
        })
        if (planItem) items.push(planItem)
      }
      const taskConfirmation = this.getAgentTaskConfirmation(processContext)
      if (taskConfirmation) {
        const taskItem = makeTextItem({
          id: `agent-task-${taskConfirmation.taskKey || 'confirmation'}`,
          kind: 'warning',
          text: taskConfirmation.description || `${taskConfirmation.label || '分析任务'}需要确认后继续。`,
          metaText: taskConfirmation.parameterSummary || taskConfirmation.resultUsage,
          state: this.getAgentTaskConfirmationProcessState(taskConfirmation.status),
        })
        if (taskItem) items.push(taskItem)
      }
      return items
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
          title: '\u5de5\u5177\u5224\u65ad',
          description: '\u5224\u65ad\u8fd9\u4e00\u8f6e\u6700\u8be5\u5148\u8c03\u4ec0\u4e48\u5de5\u5177\uff0c\u4ee5\u53ca\u8fd8\u9700\u8981\u8865\u54ea\u4e9b\u8bc1\u636e\u3002',
        },
        replanning: {
          title: '\u7ee7\u7eed\u5224\u65ad',
          description: '\u6839\u636e\u65b0\u8bc1\u636e\u8c03\u6574\u4e0b\u4e00\u6b65\u8981\u4e0d\u8981\u7ee7\u7eed\u8c03\u5de5\u5177\u3002',
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
    getAgentPlanChecklist(process = null) {
      const processContext = process ? normalizeAgentMessageProcess(process) : null
      return buildAgentPlanChecklist(
        processContext ? processContext.plan : this.agentPlan,
        processContext ? processContext.executionTrace : this.agentExecutionTrace,
        {
          isLoading: processContext ? false : this.agentLoading,
          stage: processContext ? processContext.stage : this.agentStage,
          diagnostics: (this.findAgentSession(this.activeAgentSessionId) || {}).diagnostics || {},
        },
      )
    },
    getAgentPlanSummary() {
      return this.getAgentPlanChecklist().summary
    },
    getAgentPlanProgressLabel() {
      return this.getAgentPlanChecklist().progressLabel
    },
    getAgentToolCallItems(process = null) {
      const processContext = process ? normalizeAgentMessageProcess(process) : null
      return buildAgentToolCallItems(processContext ? processContext.executionTrace : this.agentExecutionTrace)
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
    getAgentTaskConfirmation(process = null) {
      const processContext = process ? normalizeAgentMessageProcess(process) : null
      return cloneAnalysisTaskConfirmation(processContext ? processContext.pendingTaskConfirmation : this.agentPendingTaskConfirmation)
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
      await this.submitMainAgentTurn({
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
        await this.submitMainAgentTurn({
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
      this.submitMainAgentTurn({ prompt })
    },
    onAgentClarificationDraftSubmit() {
      const prompt = String(this.agentClarificationDraft || '').trim()
      if (!prompt || this.agentLoading || this.agentSessionHydrating || this.agentClarificationSubmitting) return
      this.agentClarificationSubmitting = true
      this.submitMainAgentTurn({ prompt })
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
