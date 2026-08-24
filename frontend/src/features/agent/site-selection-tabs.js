import {
  asText,
  clampText,
  cloneArray,
  cloneAgentSessionRecord,
  cloneObject,
  consumeSseStream,
  normalizeAgentPanelPreloadNotes,
  normalizeAgentToolSummary,
  sortAgentSessions,
} from './normalizers.js'
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

export function createAgentSiteSelectionTabMethods() {
  return {
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
        || Number(pack.candidate_count || 0) > 0
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
            current_site_candidate_facts: data.current_site_candidate_facts || {},
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
        const supplyDemand = item && typeof item.supply_demand === 'object' ? item.supply_demand : {}
        const populationContext = item && typeof item.population_context === 'object' ? item.population_context : {}
        const roadContext = item && typeof item.road_context === 'object' ? item.road_context : {}
        const center = item && typeof item.center_point === 'object' ? item.center_point : {}
        const lng = Number(center.lng ?? center.longitude)
        const lat = Number(center.lat ?? center.latitude)
        const coordinate = Number.isFinite(lng) && Number.isFinite(lat) ? `${lng.toFixed(5)}, ${lat.toFixed(5)}` : ''
        return {
          sourceOrder: Number(item.source_order || index + 1) || index + 1,
          h3Id: asText(item.h3_id || item.h3Id),
          title: asText(item.display_title || item.approx_address || item.label) || `候选${index + 1}`,
          approxAddress: asText(item.approx_address),
          coordinate,
          gapValue: Number(supplyDemand.gap_value ?? 0) || 0,
          demandShare: Number(supplyDemand.demand_share ?? 0) || 0,
          supplyShare: Number(supplyDemand.supply_share ?? 0) || 0,
          cellPopulation: Number(populationContext.cell_population ?? 0) || 0,
          scopePopulation: Number(populationContext.scope_population ?? 0) || 0,
          roadNodeCount: Number(roadContext.scope_node_count ?? 0) || 0,
          roadEdgeCount: Number(roadContext.scope_edge_count ?? 0) || 0,
        }
      })
    },
    getAgentSiteSelectionSelectedCandidate() {
      const candidates = this.getAgentSiteSelectionCandidates()
      const selectedH3Id = this.getAgentSiteSelectionState().selectedH3Id
      return candidates.find((item) => item.h3Id && item.h3Id === selectedH3Id) || candidates[0] || null
    },
    formatAgentSiteSelectionNumber(value = 0) {
      const number = Number(value || 0)
      if (!Number.isFinite(number)) return '0'
      return Math.abs(number) >= 10 ? number.toFixed(0) : number.toFixed(2)
    },
    formatAgentSiteSelectionRatio(value = 0) {
      const ratio = Number(value || 0)
      return Number.isFinite(ratio) ? `${(ratio * 100).toFixed(1)}%` : '-'
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
  }
}
