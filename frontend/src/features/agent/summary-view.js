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
import { createAgentPptPlanningTabMethods } from './ppt-planning-tabs.js'
import {
  normalizeAgentPptPlanningTab,
  serializeAgentPptPlanningTab,
} from './ppt-planning-tabs.js'

export function createAgentSummaryViewMethods() {
  return {
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
      const currentSummaryTab = cloneArray(tabs.summaryTabs).find((item) => asText(item && item.source) === 'current')
        || cloneArray(tabs.summaryTabs)[0]
      const fallbackPack = cloneObject((currentSummaryTab && currentSummaryTab.content) || {})
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
        sectionKey: asText(item && (item.section_key || item.sectionKey)) || `section-${index}`,
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
        poi_raster_grid: 'POI 共享栅格计算',
        poi_h3_grid: 'POI H3 六边形网格计算',
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
      if (typeof this.captureAgentActiveSummaryTabState === 'function') {
        this.captureAgentActiveSummaryTabState()
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
          panelPayloads: payloads,
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
      this.agentAnswer = ''
      this.agentExecutionTrace = []
      this.agentUsedTools = []
      this.agentCitations = []
      this.agentResearchNotes = []
      this.agentAuditIssues = []
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
          answer: '',
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
  }
}
