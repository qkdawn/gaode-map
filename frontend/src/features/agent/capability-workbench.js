import { buildAnalysisQuickAskSelectedSourcesContext } from './analysis-quick-request.js'

const CATALOG_URL = '/api/v1/analysis/agent/analysis-capabilities'
const CAPABILITY_INTENT_URL = `${CATALOG_URL}/resolve-intent`
const RUNS_URL = '/api/v1/analysis/agent/analysis/runs'
const RUN_COMPARISONS_URL = '/api/v1/analysis/agent/analysis/run-comparisons'
const WORKBENCH_URL = '/api/v1/analysis/agent/analysis-capabilities/workbench'
const REQUIRED_STAGE1_ARTIFACT_IDS = Object.freeze([
  'stage1-report',
  'stage1-evidence-appendix',
  'stage1-design-handoff',
])

const text = value => String(value || '').trim()

const clonePayloadValue = value => {
  if (Array.isArray(value)) return value.map(clonePayloadValue)
  if (!value || typeof value !== 'object') return value
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, clonePayloadValue(item)]))
}

const collectAnalysisRunSpatialObjects = detail => {
  const attempts = Array.isArray(detail?.run?.metric_attempts) ? detail.run.metric_attempts : []
  const attemptsByTarget = new Map()
  for (const attempt of attempts) {
    const targetId = text(attempt?.spatial_target?.target_id)
    if (!targetId) continue
    const existing = attemptsByTarget.get(targetId) || { metricIds: [], evidenceNodeIds: [] }
    existing.metricIds.push(text(attempt?.metric_id))
    existing.evidenceNodeIds.push(...(Array.isArray(attempt?.evidence_node_ids) ? attempt.evidence_node_ids.map(text) : []))
    attemptsByTarget.set(targetId, existing)
  }
  const objects = new Map()
  let visited = 0
  const visit = (value, depth = 0) => {
    if (value == null || visited >= 3000 || depth > 8) return
    visited += 1
    if (Array.isArray(value)) { value.forEach(item => visit(item, depth + 1)); return }
    if (typeof value !== 'object') return
    const geometry = value.geometry
    const objectId = text(value.zone_id || value.route_id)
    let objectType = ''
    if (value.zone_id && Array.isArray(value.cell_ids)) objectType = 'hotspot_zone'
    else if (value.route_id && value.destination_id) objectType = 'route'
    if (objectId && objectType && geometry && typeof geometry === 'object' && !objects.has(objectId)) {
      const linkage = attemptsByTarget.get(objectId) || { metricIds: [], evidenceNodeIds: [] }
      const sourceMetricIds = Array.isArray(value.source_metric_ids) ? value.source_metric_ids.map(text) : []
      objects.set(objectId, {
        object_id: objectId,
        object_type: objectType,
        label: text(value.label) || ({ hotspot_zone: '热点区', route: '步行路径' })[objectType],
        feature: { type: 'Feature', properties: { object_id: objectId, object_type: objectType }, geometry: clonePayloadValue(geometry) },
        metric_ids: uniqueTextItems([...sourceMetricIds, ...linkage.metricIds]),
        evidence_node_ids: uniqueTextItems(linkage.evidenceNodeIds),
        source_type: text(value.source_type),
      })
    }
    Object.values(value).forEach(item => visit(item, depth + 1))
  }
  ;(Array.isArray(detail?.artifacts) ? detail.artifacts : []).forEach(snapshot => visit(snapshot?.payload))
  return Array.from(objects.values())
}

const collectPayloadText = (value) => {
  if (Array.isArray(value)) return value.flatMap(collectPayloadText)
  if (value && typeof value === 'object') return Object.values(value).flatMap(collectPayloadText)
  const item = text(value)
  return item ? [item] : []
}

const uniqueTextItems = (values, limit = 16) => {
  const seen = new Set()
  const items = []
  for (const value of values || []) {
    const item = text(value)
    if (!item || seen.has(item)) continue
    seen.add(item)
    items.push(item)
    if (items.length >= limit) break
  }
  return items
}

const collectPayloadHighlights = (value, limit = 5) => {
  const highlights = []
  const seen = new Set()
  let visited = 0
  const visit = (item, depth = 0, path = '') => {
    if (highlights.length >= limit || visited >= 80 || depth > 4 || item == null) return
    visited += 1
    if (Array.isArray(item)) {
      for (const child of item.slice(0, 8)) visit(child, depth + 1, path)
      return
    }
    if (typeof item === 'object') {
      for (const [key, child] of Object.entries(item).slice(0, 12)) {
        visit(child, depth + 1, path ? `${path}.${key}` : key)
        if (highlights.length >= limit) break
      }
      return
    }
    const scalar = text(item)
    if (!scalar || scalar.length < 2) return
    const normalized = scalar.length > 180 ? `${scalar.slice(0, 177)}...` : scalar
    const label = path ? `${path}: ${normalized}` : normalized
    if (seen.has(label)) return
    seen.add(label)
    highlights.push(label)
  }
  visit(value)
  return highlights
}

const compactRunArtifact = (artifact, direction = '', snapshot = null) => ({
  direction: text(direction || snapshot?.direction),
  artifact_id: text(artifact?.artifact_id),
  artifact_type: text(artifact?.artifact_type),
  title: text(artifact?.title),
  version: text(artifact?.version),
  source_run_id: text(artifact?.source_run_id),
  source_artifact_refs: uniqueTextItems(artifact?.source_artifact_refs, 8),
  evidence_refs: uniqueTextItems(artifact?.evidence_refs, 8),
  content_digest: text(artifact?.content_digest),
  snapshot_state: snapshot ? (snapshot.payload === null ? 'metadata_only' : 'immutable_payload') : 'run_manifest',
  payload_highlights: snapshot?.payload === null ? [] : collectPayloadHighlights(snapshot?.payload),
})

const CAPABILITY_PROMPTS = Object.freeze({
  'client-decision-spatial-strategy': '围绕当前项目问题，按顺序完成十一个分析方向；每个方向自由组织分析内容。',
  'spatial-business-analyst': '基于当前分析范围、材料和空间分析结果，生成面向下一步决策的专业空间项目报告。',
  'urban-strategy-stage1': '基于当前分析范围、资料和分析结果，执行城市更新第一阶段策划并生成可审计报告。',
  'spatial-programming-matrix': '基于当前项目证据，重点生成空间功能策划决策矩阵，并说明候选功能、排除理由和前置条件。',
  'evidence-audit': '审计当前项目分析的 Claim-Evidence 关系、代理指标边界、冲突与待验证事项。',
})

const SPATIAL_STRATEGY_STEPS = Object.freeze([
  { step: 'step_01_policy_site', step_order: 1, label: '政策与场地' },
  { step: 'step_02_regional_role', step_order: 2, label: '区域角色' },
  { step: 'step_03_supply_gap', step_order: 3, label: '供给与空位' },
  { step: 'step_04_audience_use', step_order: 4, label: '客群与使用' },
  { step: 'step_05_theme_resources', step_order: 5, label: '主题与资源' },
  { step: 'step_06_positioning', step_order: 6, label: '项目定位' },
  { step: 'step_07_product_mix', step_order: 7, label: '产品组合' },
  { step: 'step_08_spatial_layout', step_order: 8, label: '空间布局' },
  { step: 'step_09_operating_model', step_order: 9, label: '运营模式' },
  { step: 'step_10_financial_check', step_order: 10, label: '财务校验' },
  { step: 'step_11_phasing', step_order: 11, label: '分期实施' },
])

export function createAgentCapabilityWorkbenchMethods() {
  return {
    isN8nSpatialStrategyCapability(capability = null) {
      return text(capability?.id) === 'client-decision-spatial-strategy'
        || text(capability?.executor_id) === 'n8n-spatial-strategy'
    },
    getSpatialStrategyTenantId() {
      const bootstrap = window.__ANALYSIS_BOOTSTRAP__ && typeof window.__ANALYSIS_BOOTSTRAP__ === 'object'
        ? window.__ANALYSIS_BOOTSTRAP__
        : {}
      return text(bootstrap.tenantId || bootstrap.tenant_id || 'default') || 'default'
    },
    getSpatialStrategyAccessGroups() {
      const bootstrap = window.__ANALYSIS_BOOTSTRAP__ && typeof window.__ANALYSIS_BOOTSTRAP__ === 'object'
        ? window.__ANALYSIS_BOOTSTRAP__
        : {}
      const values = Array.isArray(bootstrap.accessGroups || bootstrap.access_groups)
        ? bootstrap.accessGroups || bootstrap.access_groups
        : []
      return uniqueTextItems(values, 32)
    },
    stopN8nSpatialStrategyPolling() {
      if (this.n8nSpatialStrategyPollHandle) window.clearTimeout(this.n8nSpatialStrategyPollHandle)
      this.n8nSpatialStrategyPollHandle = null
    },
    getN8nSpatialStrategyStepLabel(step = null) {
      return text(step?.title) || '等待开始'
    },
    getN8nSpatialStrategySteps() {
      const run = this.n8nSpatialStrategyRun || {}
      return Array.isArray(run.chapters) ? clonePayloadValue(run.chapters) : []
    },
    getN8nSpatialStrategyStatusLabel(status = '') {
      return text(status) || '准备中'
    },
    getN8nSpatialStrategyCitationKind(citation = null) {
      return {
        project_document: '项目材料',
        project_data: '项目数据',
        project_data_record: '项目数据',
        project_computed_result: '空间数据',
        knowledge_base: '公开资料',
      }[text(citation?.source_type)] || '待现场核验'
    },
    getN8nSpatialStrategyLiveMessage() {
      return text(this.n8nSpatialStrategyRun?.message)
    },
    isN8nSpatialStrategyStepOpen(stepResult = null) {
      const status = text(stepResult?.status)
      return ['正在分析', '需要处理'].includes(status)
    },
    getN8nSpatialStrategyFinalSummary() {
      if (this.n8nSpatialStrategyRun?.status !== '已完成') return null
      const steps = this.getN8nSpatialStrategySteps()
      const sections = steps
        .filter(item => text(item?.content))
        .map(item => ({
          number: item.number,
          label: this.getN8nSpatialStrategyStepLabel(item),
          summary: text(item.content),
        }))
      return {
        headline: text(this.n8nSpatialStrategyRun?.report?.summary) || '11 章空间策略已完成。',
        sections,
      }
    },
    async refreshN8nSpatialStrategyRun(runId = '', { schedule = true } = {}) {
      const id = text(runId || this.n8nSpatialStrategyRun?.run_id)
      if (!id) return null
      this.n8nSpatialStrategyLoading = true
      this.n8nSpatialStrategyError = ''
      try {
        const response = await fetch(`/api/v1/analysis/spatial-strategy/runs/${encodeURIComponent(id)}`, {
          headers: { 'X-Tenant-Id': this.getSpatialStrategyTenantId() },
        })
        if (!response.ok) throw new Error(`空间决策状态请求失败(${response.status})`)
        const payload = await response.json()
        this.n8nSpatialStrategyRun = clonePayloadValue(payload)
        const status = text(payload?.status)
        if (schedule && ['准备中', '分析中'].includes(status)) {
          this.stopN8nSpatialStrategyPolling()
          this.n8nSpatialStrategyPollHandle = window.setTimeout(() => {
            this.refreshN8nSpatialStrategyRun(id).catch(() => {})
          }, 2500)
        } else {
          this.stopN8nSpatialStrategyPolling()
        }
        return this.n8nSpatialStrategyRun
      } catch (error) {
        this.n8nSpatialStrategyError = error instanceof Error ? error.message : String(error)
        return null
      } finally {
        this.n8nSpatialStrategyLoading = false
      }
    },
    async runN8nSpatialStrategy() {
      this.stopN8nSpatialStrategyPolling()
      this.n8nSpatialStrategyLoading = true
      this.n8nSpatialStrategyError = ''
      const historyId = typeof this.getCurrentAgentHistoryId === 'function' ? text(this.getCurrentAgentHistoryId()) : ''
      const payload = {
        project_question: text(this.agentInput) || CAPABILITY_PROMPTS['client-decision-spatial-strategy'],
        history_id: historyId,
        metadata_filter: historyId ? { history_id: historyId } : {},
        deliver_to_feishu: this.n8nSpatialStrategyDeliverToFeishu === true,
      }
      try {
        const response = await fetch('/api/v1/analysis/spatial-strategy/runs', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Tenant-Id': this.getSpatialStrategyTenantId(),
            'X-Access-Groups': this.getSpatialStrategyAccessGroups().join(','),
          },
          body: JSON.stringify(payload),
        })
        if (!response.ok) throw new Error(`空间决策提交失败(${response.status})`)
        const accepted = await response.json()
        this.n8nSpatialStrategyRun = {
          ...accepted,
          chapters: SPATIAL_STRATEGY_STEPS.map(item => ({ number: item.step_order, title: item.label, status: '等待分析', content: '' })),
          progress: { completed_chapters: 0, total_chapters: 12 },
        }
        this.n8nSpatialStrategyDeliverToFeishu = false
        this.agentInput = ''
        await this.refreshN8nSpatialStrategyRun(accepted.run_id)
        return accepted
      } catch (error) {
        this.n8nSpatialStrategyError = error instanceof Error ? error.message : String(error)
        return null
      } finally {
        this.n8nSpatialStrategyLoading = false
      }
    },
    async resumeN8nSpatialStrategy() {
      const runId = text(this.n8nSpatialStrategyRun?.run_id)
      if (!runId || this.n8nSpatialStrategyRun?.status !== '需要处理') return null
      this.stopN8nSpatialStrategyPolling()
      this.n8nSpatialStrategyLoading = true
      this.n8nSpatialStrategyError = ''
      try {
        const response = await fetch(`/api/v1/analysis/spatial-strategy/runs/${encodeURIComponent(runId)}/resume`, {
          method: 'POST',
          headers: { 'X-Tenant-Id': this.getSpatialStrategyTenantId() },
        })
        if (!response.ok) throw new Error(`空间决策恢复失败(${response.status})`)
        const accepted = await response.json()
        this.n8nSpatialStrategyRun = { ...this.n8nSpatialStrategyRun, ...accepted, error: '' }
        await this.refreshN8nSpatialStrategyRun(runId)
        return accepted
      } catch (error) {
        this.n8nSpatialStrategyError = error instanceof Error ? error.message : String(error)
        return null
      } finally {
        this.n8nSpatialStrategyLoading = false
      }
    },
    async resolveAnalysisCapabilityIntent(prompt = '') {
      const message = text(prompt)
      if (!message) return null
      const response = await fetch(CAPABILITY_INTENT_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message }),
      })
      if (!response.ok) throw new Error(`能力意图识别失败(${response.status})`)
      const payload = await response.json()
      return payload && typeof payload === 'object' ? clonePayloadValue(payload) : null
    },
    async routeAnalysisCapabilityIntent(prompt = '') {
      let resolution = null
      try {
        resolution = await this.resolveAnalysisCapabilityIntent(prompt)
      } catch (_) {
        return null
      }
      if (!resolution?.matched || !text(resolution.capability_id)) return null
      await this.loadAnalysisCapabilities()
      const registered = (this.analysisCapabilities || []).some(item => text(item?.id) === text(resolution.capability_id))
      if (!registered) return null
      this.analysisCapabilityIntentResolution = clonePayloadValue(resolution)
      this.agentInput = ''
      this.openAnalysisCapabilitiesPanel()
      const capability = await this.openAnalysisCapabilityOverviewTarget(resolution.capability_id)
      if (!capability) return null
      return { type: 'capability_intent', resolution: clonePayloadValue(resolution) }
    },
    getAnalysisCapabilityIntentResolution() {
      const resolution = this.analysisCapabilityIntentResolution
      return resolution && typeof resolution === 'object' ? clonePayloadValue(resolution) : null
    },
    clearAnalysisCapabilityIntentResolution() {
      this.analysisCapabilityIntentResolution = null
    },
    async loadAnalysisCapabilities(force = false) {
      if (this.analysisCapabilitiesLoaded && !force) return this.analysisCapabilities
      this.analysisCapabilitiesLoading = true
      this.analysisCapabilitiesError = ''
      try {
        const response = await fetch(CATALOG_URL)
        if (!response.ok) throw new Error(`分析能力目录请求失败(${response.status})`)
        const payload = await response.json()
        this.analysisCapabilities = Array.isArray(payload) ? payload : []
        this.analysisCapabilitiesLoaded = true
        return this.analysisCapabilities
      } catch (error) {
        this.analysisCapabilitiesError = error instanceof Error ? error.message : String(error)
        throw error
      } finally {
        this.analysisCapabilitiesLoading = false
      }
    },
    openAnalysisCapabilitiesPanel() {
      if (typeof this.selectStep3Panel === 'function') this.selectStep3Panel('agent')
      this.agentWorkspaceView = 'capabilities'
      this.closeAgentSessionMenu()
      this.loadAnalysisCapabilities().catch(() => {})
      this.loadAnalysisCapabilityOverview(true).catch(() => {})
      this.loadAnalysisRuns().catch(() => {})
    },
    async loadPptCapabilityLauncher() {
      await this.loadAnalysisCapabilities()
      await this.loadAnalysisCapabilityOverview().catch(() => null)
      return this.analysisCapabilities
    },
    async openAnalysisCapabilityFromLauncher(capabilityId = '') {
      const id = text(capabilityId)
      if (!id || id === 'ppt-planning') return null
      await this.loadPptCapabilityLauncher()
      if (typeof this.selectStep3Panel === 'function') this.selectStep3Panel('agent')
      this.agentWorkspaceView = 'capabilities'
      this.closeAgentSessionMenu()
      return this.openAnalysisCapabilityOverviewTarget(id)
    },
    buildAnalysisCapabilityWorkbenchPayload() {
      return {
        conversation_id: text(this.activeAgentSessionId),
        history_id: typeof this.getCurrentAgentHistoryId === 'function' ? text(this.getCurrentAgentHistoryId()) : '',
        messages: [{ role: 'user', content: '检查当前项目的分析能力就绪度并推荐下一步。' }],
        analysis_snapshot: typeof this.buildAgentAnalysisSnapshot === 'function' ? this.buildAgentAnalysisSnapshot() : {},
        selected_sources_context: buildAnalysisQuickAskSelectedSourcesContext(this),
      }
    },
    async loadAnalysisCapabilityOverview(force = false) {
      const requestPayload = this.buildAnalysisCapabilityWorkbenchPayload()
      const historyId = text(requestPayload.history_id)
      const sameContext = text(this.analysisCapabilityOverviewHistoryId) === historyId
      if (this.analysisCapabilityOverviewLoaded && sameContext && !force) return this.getAnalysisCapabilityOverview()
      const requestToken = Number(this.analysisCapabilityOverviewRequestToken || 0) + 1
      this.analysisCapabilityOverviewRequestToken = requestToken
      this.analysisCapabilityOverviewHistoryId = historyId
      this.analysisCapabilityOverviewLoading = true
      this.analysisCapabilityOverviewLoaded = false
      this.analysisCapabilityOverviewError = ''
      this.analysisCapabilityOverview = null
      try {
        const response = await fetch(WORKBENCH_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(requestPayload),
        })
        if (!response.ok) throw new Error(`能力工作台状态请求失败(${response.status})`)
        const payload = await response.json()
        if (this.analysisCapabilityOverviewRequestToken !== requestToken) return null
        this.analysisCapabilityOverview = payload && typeof payload === 'object' ? clonePayloadValue(payload) : null
        this.analysisCapabilityOverviewLoaded = true
        const readiness = { ...(this.analysisCapabilityReadiness || {}) }
        for (const card of this.analysisCapabilityOverview?.cards || []) {
          if (text(card?.capability_id) && card?.readiness) readiness[text(card.capability_id)] = clonePayloadValue(card.readiness)
        }
        this.analysisCapabilityReadiness = readiness
        return this.getAnalysisCapabilityOverview()
      } catch (error) {
        if (this.analysisCapabilityOverviewRequestToken !== requestToken) return null
        this.analysisCapabilityOverviewError = error instanceof Error ? error.message : String(error)
        throw error
      } finally {
        if (this.analysisCapabilityOverviewRequestToken === requestToken) this.analysisCapabilityOverviewLoading = false
      }
    },
    getAnalysisCapabilityOverview() {
      return this.analysisCapabilityOverview && typeof this.analysisCapabilityOverview === 'object'
        ? clonePayloadValue(this.analysisCapabilityOverview)
        : null
    },
    getAnalysisCapabilityOverviewCard(capabilityId = '') {
      const card = (this.analysisCapabilityOverview?.cards || []).find(item => text(item?.capability_id) === text(capabilityId))
      return card ? clonePayloadValue(card) : null
    },
    getAnalysisCapabilityRecommendation() {
      const recommendation = this.analysisCapabilityOverview?.recommendation
      return recommendation && typeof recommendation === 'object' ? clonePayloadValue(recommendation) : null
    },
    getAnalysisCapabilityRecommendationLabel(recommendation = null) {
      return {
        inspect_run: '查看当前任务',
        resolve_inputs: '检查输入缺口',
        run: '配置并运行',
        rerun: '检查并重跑',
        review_result: '复核最新成果',
      }[text(recommendation?.action)] || '查看能力'
    },
    getAnalysisCapabilityRecentRuns() {
      const runs = this.analysisCapabilityOverview?.recent_runs
      return Array.isArray(runs) ? clonePayloadValue(runs) : []
    },
    getAnalysisCapabilityCardState(capability = null) {
      return text(this.getAnalysisCapabilityOverviewCard(capability?.id)?.state) || (capability?.status === 'available' ? 'checking' : 'unavailable')
    },
    getAnalysisCapabilityCardStateLabel(capability = null) {
      return {
        ready: '可运行',
        limited: '有条件可运行',
        blocked: '缺少输入',
        running: '正在运行',
        completed: '已有结果',
        stale: '结果已过期',
        failed: '运行失败',
        unavailable: '不可执行',
        checking: '检查中',
      }[this.getAnalysisCapabilityCardState(capability)] || '待检查'
    },
    getAnalysisCapabilityCardMeta(capability = null) {
      if (capability?.status !== 'available') {
        const requirements = Array.isArray(capability?.activation_requirements) ? capability.activation_requirements.length : 0
        return requirements ? `需完成 ${requirements} 项启用条件` : '尚未注册可执行能力'
      }
      const card = this.getAnalysisCapabilityOverviewCard(capability?.id)
      if (!card) return `${Number(capability?.estimated_stages || 0)} 个阶段 · ${capability?.output_contract?.length || 0} 类成果`
      const missing = Array.isArray(card.readiness?.missing_required) ? card.readiness.missing_required.length : 0
      if (missing) return `缺少 ${missing} 项必需输入 · ${card.run_count || 0} 个版本`
      if (card.latest_run) return `最近运行 ${this.getAnalysisCapabilityRunTimeLabel(card.latest_run)} · ${card.run_count || 0} 个版本`
      return `${Number(capability?.estimated_stages || 0)} 个阶段 · 尚无运行`
    },
    getFilteredAnalysisCapabilities() {
      const query = text(this.analysisCapabilitySearchQuery).toLowerCase()
      const status = text(this.analysisCapabilityStatusFilter) || 'all'
      return (this.analysisCapabilities || []).filter((capability) => {
        const state = this.getAnalysisCapabilityCardState(capability)
        if (status !== 'all' && state !== status) return false
        if (!query) return true
        const haystack = [
          capability.id,
          capability.display_name,
          capability.description,
          capability.category,
          capability.availability_note,
          ...(capability.intent_phrases || []),
          ...(capability.activation_requirements || []),
          ...(capability.output_contract || []),
          ...(capability.input_requirements || []).map(item => item?.label),
        ].map(text).join(' ').toLowerCase()
        return haystack.includes(query)
      })
    },
    async openAnalysisCapabilityOverviewTarget(capabilityId = '', runId = '') {
      const capability = (this.analysisCapabilities || []).find(item => text(item?.id) === text(capabilityId))
      if (!capability) return null
      await this.inspectAnalysisCapability(capability)
      if (runId) {
        const run = this.getAnalysisRuns().find(item => text(item?.run_id) === text(runId))
        if (run) await this.selectAnalysisRun(run)
      }
      return capability
    },
    openAnalysisCapabilityRecommendation() {
      const recommendation = this.getAnalysisCapabilityRecommendation()
      if (!recommendation) return Promise.resolve(null)
      return this.openAnalysisCapabilityOverviewTarget(recommendation.capability_id, recommendation.run_id)
    },
    openAnalysisCapabilityRecentRun(run = null) {
      return this.openAnalysisCapabilityOverviewTarget(run?.capability_id, run?.run_id)
    },
    async loadAnalysisRuns({ force = false, capabilityId = '' } = {}) {
      const historyId = typeof this.getCurrentAgentHistoryId === 'function' ? text(this.getCurrentAgentHistoryId()) : ''
      const normalizedCapabilityId = text(capabilityId)
      if (!historyId) {
        this.analysisRunsRequestToken = Number(this.analysisRunsRequestToken || 0) + 1
        this.analysisRuns = []
        this.analysisRunsLoaded = false
        this.analysisRunsHistoryId = ''
        this.analysisRunsCapabilityId = normalizedCapabilityId
        this.analysisRunsError = ''
        this.analysisRunsLoading = false
        this.clearSelectedAnalysisRun()
        return []
      }
      const sameQuery = this.analysisRunsHistoryId === historyId
        && this.analysisRunsCapabilityId === normalizedCapabilityId
      if (!force && sameQuery && this.analysisRunsLoaded) return this.getAnalysisRuns()
      if (!force && sameQuery && this.analysisRunsLoading) return []

      const requestToken = Number(this.analysisRunsRequestToken || 0) + 1
      this.analysisRunsRequestToken = requestToken
      this.analysisRunsLoading = true
      this.analysisRunsLoaded = false
      this.analysisRunsError = ''
      this.analysisRuns = []
      this.analysisRunsHistoryId = historyId
      this.analysisRunsCapabilityId = normalizedCapabilityId
      this.clearSelectedAnalysisRun()
      const query = new URLSearchParams({ history_id: historyId })
      if (normalizedCapabilityId) query.set('capability_id', normalizedCapabilityId)
      try {
        const response = await fetch(`${RUNS_URL}?${query.toString()}`)
        if (!response.ok) throw new Error(`运行版本请求失败(${response.status})`)
        const payload = await response.json()
        if (this.analysisRunsRequestToken !== requestToken) return []
        this.analysisRuns = Array.isArray(payload) ? clonePayloadValue(payload) : []
        this.analysisRunsLoaded = true
        return this.getAnalysisRuns()
      } catch (error) {
        if (this.analysisRunsRequestToken !== requestToken) return []
        this.analysisRunsError = error instanceof Error ? error.message : String(error)
        throw error
      } finally {
        if (this.analysisRunsRequestToken === requestToken) this.analysisRunsLoading = false
      }
    },
    getAnalysisRuns() {
      return Array.isArray(this.analysisRuns) ? clonePayloadValue(this.analysisRuns) : []
    },
    async loadAnalysisRunDetail(runId = '') {
      const normalizedRunId = text(runId)
      if (!normalizedRunId) return null
      const requestToken = Number(this.selectedAnalysisRunRequestToken || 0) + 1
      this.selectedAnalysisRunRequestToken = requestToken
      this.clearAnalysisRunComparison()
      this.selectedAnalysisRunId = normalizedRunId
      this.selectedAnalysisRunDetail = null
      this.selectedAnalysisRunSpatialObjectId = ''
      this.analysisRunSpatialPresentationMessage = ''
      this.selectedAnalysisRunLoading = true
      this.selectedAnalysisRunError = ''
      try {
        const response = await fetch(`${RUNS_URL}/${encodeURIComponent(normalizedRunId)}`)
        if (!response.ok) throw new Error(`运行快照请求失败(${response.status})`)
        const detail = await response.json()
        if (this.selectedAnalysisRunRequestToken !== requestToken) return null
        this.selectedAnalysisRunDetail = detail && typeof detail === 'object' ? clonePayloadValue(detail) : null
        return this.getSelectedAnalysisRunDetail()
      } catch (error) {
        if (this.selectedAnalysisRunRequestToken !== requestToken) return null
        this.selectedAnalysisRunError = error instanceof Error ? error.message : String(error)
        throw error
      } finally {
        if (this.selectedAnalysisRunRequestToken === requestToken) this.selectedAnalysisRunLoading = false
      }
    },
    selectAnalysisRun(run = null) {
      const runId = text(run?.run_id)
      if (!runId) return Promise.resolve(null)
      if (runId === this.selectedAnalysisRunId && this.selectedAnalysisRunDetail) {
        return Promise.resolve(this.getSelectedAnalysisRunDetail())
      }
      return this.loadAnalysisRunDetail(runId)
    },
    clearSelectedAnalysisRun() {
      this.selectedAnalysisRunRequestToken = Number(this.selectedAnalysisRunRequestToken || 0) + 1
      this.selectedAnalysisRunId = ''
      this.selectedAnalysisRunDetail = null
      this.selectedAnalysisRunLoading = false
      this.selectedAnalysisRunError = ''
      this.selectedAnalysisRunSpatialObjectId = ''
      this.analysisRunSpatialPresentationMessage = ''
      this.clearAnalysisRunComparison()
    },
    getAnalysisCapabilityComparisonCandidates() {
      const selectedRunId = text(this.selectedAnalysisRunId)
      return this.getAnalysisRuns().filter(run => text(run?.run_id) && text(run.run_id) !== selectedRunId)
    },
    setAnalysisCapabilityComparisonBaseRunId(runId = '') {
      const normalizedRunId = text(runId)
      if (normalizedRunId === text(this.selectedAnalysisRunId)) return ''
      this.analysisCapabilityComparisonBaseRunId = normalizedRunId
      this.analysisRunComparison = null
      this.analysisRunComparisonError = ''
      return normalizedRunId
    },
    clearAnalysisRunComparison() {
      this.analysisRunComparisonRequestToken = Number(this.analysisRunComparisonRequestToken || 0) + 1
      this.analysisCapabilityComparisonBaseRunId = ''
      this.analysisRunComparison = null
      this.analysisRunComparisonLoading = false
      this.analysisRunComparisonError = ''
    },
    async compareSelectedAnalysisRun() {
      const baseRunId = text(this.analysisCapabilityComparisonBaseRunId)
      const targetRunId = text(this.selectedAnalysisRunId)
      if (!baseRunId || !targetRunId || baseRunId === targetRunId) return null
      const requestToken = Number(this.analysisRunComparisonRequestToken || 0) + 1
      this.analysisRunComparisonRequestToken = requestToken
      this.analysisRunComparisonLoading = true
      this.analysisRunComparisonError = ''
      this.analysisRunComparison = null
      const query = new URLSearchParams({ base_run_id: baseRunId, target_run_id: targetRunId })
      try {
        const response = await fetch(`${RUN_COMPARISONS_URL}?${query.toString()}`)
        if (!response.ok) throw new Error(`运行版本比较失败(${response.status})`)
        const payload = await response.json()
        if (this.analysisRunComparisonRequestToken !== requestToken) return null
        this.analysisRunComparison = payload && typeof payload === 'object' ? clonePayloadValue(payload) : null
        return this.getAnalysisRunComparison()
      } catch (error) {
        if (this.analysisRunComparisonRequestToken !== requestToken) return null
        this.analysisRunComparisonError = error instanceof Error ? error.message : String(error)
        throw error
      } finally {
        if (this.analysisRunComparisonRequestToken === requestToken) this.analysisRunComparisonLoading = false
      }
    },
    getAnalysisRunComparison() {
      const comparison = this.analysisRunComparison
      return comparison && typeof comparison === 'object' ? clonePayloadValue(comparison) : null
    },
    getAnalysisCapabilityComparisonChangeLabel(changeType = '') {
      return ({ added: '新增', removed: '移除', changed: '调整' })[text(changeType)] || '变化'
    },
    getAnalysisCapabilityComparisonEntityLabel(category = '') {
      return ({
        strategy_option: '定位方案', space_decision: '空间决策', evidence: '证据',
        hard_constraint: '硬约束', quality_issue: '质量问题',
      })[text(category)] || '对象'
    },
    formatAnalysisCapabilityComparisonValue(value) {
      if (value == null || value === '') return '未设置'
      if (Array.isArray(value)) {
        if (!value.length) return '无'
        if (value.every(item => item == null || ['string', 'number', 'boolean'].includes(typeof item))) {
          return value.map(item => text(item)).filter(Boolean).join('、') || '无'
        }
        const serialized = JSON.stringify(value)
        return serialized.length > 180 ? `${serialized.slice(0, 177)}...` : serialized
      }
      if (typeof value === 'object') {
        const serialized = JSON.stringify(value)
        return serialized.length > 180 ? `${serialized.slice(0, 177)}...` : serialized
      }
      return text(value)
    },
    getSelectedAnalysisRun() {
      const runId = text(this.selectedAnalysisRunId)
      return this.getAnalysisRuns().find(run => text(run?.run_id) === runId) || null
    },
    getSelectedAnalysisRunDetail() {
      const detail = this.selectedAnalysisRunDetail
      return detail && typeof detail === 'object' ? clonePayloadValue(detail) : null
    },
    getSelectedAnalysisRunArtifacts() {
      const artifacts = this.getSelectedAnalysisRunDetail()?.artifacts
      return Array.isArray(artifacts) ? clonePayloadValue(artifacts) : []
    },
    getSelectedAnalysisRunMetricPlanDiagnostics() {
      const diagnostics = this.getSelectedAnalysisRunDetail()?.metric_plan_diagnostics
      return diagnostics && typeof diagnostics === 'object' ? clonePayloadValue(diagnostics) : null
    },
    getSelectedAnalysisRunMetricPlanEntries(entryIds = []) {
      const ids = new Set(Array.isArray(entryIds) ? entryIds.map(text) : [])
      const entries = this.getSelectedAnalysisRunDetail()?.run?.metric_plan?.entries
      return (Array.isArray(entries) ? entries : []).filter(entry => ids.has(text(entry?.plan_entry_id))).map(clonePayloadValue)
    },
    getSelectedAnalysisRunSpatialObjects() {
      return collectAnalysisRunSpatialObjects(this.getSelectedAnalysisRunDetail())
    },
    getSelectedAnalysisRunSpatialObject() {
      const objectId = text(this.selectedAnalysisRunSpatialObjectId)
      return this.getSelectedAnalysisRunSpatialObjects().find(item => item.object_id === objectId) || null
    },
    selectAnalysisRunSpatialObject(item = null) {
      const objectId = text(item?.object_id)
      this.selectedAnalysisRunSpatialObjectId = objectId
      return this.getSelectedAnalysisRunSpatialObject()
    },
    renderSelectedAnalysisRunSpatialObjects({ fitView = true } = {}) {
      const mapCore = this.mapCore
      const objects = this.getSelectedAnalysisRunSpatialObjects()
      if (!mapCore || typeof mapCore.showSpatialPresentation !== 'function') {
        this.analysisRunSpatialPresentationMessage = '地图尚未就绪，无法显示空间动作对象。'
        return 0
      }
      const colors = { hotspot_zone: '#dc2626', route: '#0f766e' }
      const count = mapCore.showSpatialPresentation(objects.map(item => ({
        object_id: item.object_id, feature: item.feature, color: colors[item.object_type],
        fillOpacity: item.object_type === 'hotspot_zone' ? 0.28 : 0.18, strokeWeight: item.object_type === 'route' ? 6 : 4,
      })), { fitView, onClick: rendered => this.selectAnalysisRunSpatialObject(objects.find(item => item.object_id === rendered?.object_id)) })
      this.analysisRunSpatialPresentationMessage = count ? `已显示 ${objects.length} 个空间动作对象；点击地图对象查看指标与证据。` : '当前运行没有可定位的热点区或路径对象。'
      return count
    },
    getAnalysisCapabilityRunStatusLabel(run = null) {
      const labels = {
        draft: '草稿', checking_inputs: '检查输入', ready: '已就绪', queued: '排队中', running: '运行中',
        waiting_for_user: '等待补充', completed: '已完成', completed_with_warnings: '完成但有提示', failed: '运行失败',
        cancelled: '已取消', stale: '上游已更新',
      }
      return labels[run?.status] || text(run?.status) || '未记录'
    },
    getAnalysisRunVersionLabel(run = null, index = 0) {
      const total = this.getAnalysisRuns().length
      const ordinal = Math.max(total - Number(index || 0), 1)
      return `${index === 0 ? '最新' : '历史'} v${ordinal}`
    },
    getAnalysisRunComparisonOptionLabel(run = null) {
      const runs = this.getAnalysisRuns()
      const index = runs.findIndex(item => text(item?.run_id) === text(run?.run_id))
      const version = this.getAnalysisRunVersionLabel(run, Math.max(index, 0))
      return `${version} · ${this.getAnalysisCapabilityRunTimeLabel(run)} · ${this.getAnalysisCapabilityRunStatusLabel(run)}`
    },
    getAnalysisCapabilityRunTimeLabel(run = null) {
      const value = text(run?.completed_at || run?.created_at)
      if (!value) return '未记录时间'
      const date = new Date(value)
      if (Number.isNaN(date.getTime())) return value
      return new Intl.DateTimeFormat('zh-CN', {
        year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
      }).format(date)
    },
    getAnalysisCapabilityRunCurrentStageLabel(run = null) {
      const records = Array.isArray(run?.stage_records) ? run.stage_records : []
      const stage = records.find(item => item?.stage_id === run?.current_stage)
      return text(stage?.title || run?.current_stage) || '尚未开始'
    },
    getAnalysisRunChangedInputIds(run = null) {
      return Array.isArray(run?.stale_input_artifact_ids) ? run.stale_input_artifact_ids.map(text).filter(Boolean) : []
    },
    buildAnalysisRunContextAskTarget(detailSeed = null) {
      const selectedDetail = detailSeed && typeof detailSeed === 'object' && detailSeed.run
        ? clonePayloadValue(detailSeed)
        : null
      const run = selectedDetail?.run || this.getAnalysisRun()
      if (!run || !text(run.run_id)) return null

      const snapshots = Array.isArray(selectedDetail?.artifacts) ? selectedDetail.artifacts : []
      const snapshotByArtifact = new Map()
      for (const snapshot of snapshots) {
        const artifactId = text(snapshot?.artifact?.artifact_id)
        if (artifactId) snapshotByArtifact.set(`${text(snapshot?.direction)}:${artifactId}`, snapshot)
      }
      const artifactContexts = []
      const seenArtifacts = new Set()
      const appendArtifact = (artifact, direction, snapshot = null) => {
        const artifactId = text(artifact?.artifact_id)
        const key = `${direction}:${artifactId}`
        if (!artifactId || seenArtifacts.has(key) || artifactContexts.length >= 16) return
        seenArtifacts.add(key)
        artifactContexts.push(compactRunArtifact(artifact, direction, snapshot))
      }
      for (const [direction, refs] of [
        ['input', run.input_artifact_refs],
        ['output', run.output_artifact_refs],
      ]) {
        for (const artifact of Array.isArray(refs) ? refs : []) {
          appendArtifact(artifact, direction, snapshotByArtifact.get(`${direction}:${text(artifact?.artifact_id)}`) || null)
        }
      }
      for (const snapshot of snapshots) appendArtifact(snapshot?.artifact, text(snapshot?.direction), snapshot)

      const capability = (this.analysisCapabilities || []).find(item => text(item?.id) === text(run.capability_id))
      const capabilityLabel = text(capability?.display_name || run.capability_id) || '分析能力'
      const staleInputs = this.getAnalysisRunChangedInputIds(run)
      const diagnostics = uniqueTextItems(run.diagnostics, 6)
      const outputTitles = artifactContexts.filter(item => item.direction === 'output').map(item => item.title || item.artifact_id)
      const stages = (Array.isArray(run.stage_records) ? run.stage_records : []).slice(0, 10).map(stage => ({
        stage_id: text(stage?.stage_id),
        title: text(stage?.title),
        status: text(stage?.status),
        summary: text(stage?.summary).slice(0, 240),
        diagnostics: uniqueTextItems(stage?.diagnostics, 4),
      }))
      const evidence = []
      for (const artifact of artifactContexts) {
        for (const evidenceRef of artifact.evidence_refs) {
          evidence.push({ evidence_ref: evidenceRef, artifact_id: artifact.artifact_id })
          if (evidence.length >= 12) break
        }
        if (evidence.length >= 12) break
      }
      const artifactRefs = uniqueTextItems(artifactContexts.map(item => item.artifact_id), 16)
      const versionKind = selectedDetail ? 'immutable_history' : 'current_result'
      const summaryParts = [
        `${capabilityLabel} 运行 ${run.run_id} 的${selectedDetail ? '不可变历史快照' : '当前结果'}，状态为${this.getAnalysisCapabilityRunStatusLabel(run)}，当前阶段为${this.getAnalysisCapabilityRunCurrentStageLabel(run)}。`,
      ]
      if (outputTitles.length) summaryParts.push(`输出产物：${outputTitles.slice(0, 6).join('、')}。`)
      if (staleInputs.length) summaryParts.push(`上游已更新：${staleInputs.join('、')}；回答时不得将该版本表述为当前最新结论。`)
      if (diagnostics.length) summaryParts.push(`运行诊断：${diagnostics.slice(0, 3).join('；')}。`)

      const target = {
        type: 'analysis_run',
        id: text(run.run_id),
        title: `${capabilityLabel} · ${run.run_id}`,
        source: 'analysis_run',
        summary: summaryParts.join(' '),
        evidence,
        artifact_refs: artifactRefs,
        payload: {
          run_id: text(run.run_id),
          capability_id: text(run.capability_id),
          version_kind: versionKind,
          status: text(run.status),
          current_stage: text(run.current_stage),
          created_at: text(run.created_at),
          completed_at: text(run.completed_at),
          stale_input_artifact_ids: staleInputs,
          diagnostics,
          stages,
          artifacts: artifactContexts,
        },
      }
      return typeof this.normalizeContextAskTarget === 'function'
        ? this.normalizeContextAskTarget(target)
        : target
    },
    openAnalysisRunContextAsk(detailSeed = null) {
      const target = this.buildAnalysisRunContextAskTarget(detailSeed)
      if (!target || typeof this.openContextAsk !== 'function') return null
      return this.openContextAsk(target, { resetMessages: true })
    },
    isAnalysisRunSelected(run = null) {
      return !!text(run?.run_id) && text(run.run_id) === text(this.selectedAnalysisRunId)
    },
    getAnalysisCapabilityGroups() {
      const labels = { planning: '策划决策', analysis: '空间分析', governance: '证据治理', delivery: '成果交付' }
      const groups = []
      for (const capability of this.getFilteredAnalysisCapabilities()) {
        const key = text(capability.category) || 'analysis'
        let group = groups.find(item => item.key === key)
        if (!group) {
          group = { key, label: labels[key] || key, items: [] }
          groups.push(group)
        }
        group.items.push(capability)
      }
      return groups
    },
    getAnalysisCapabilityById(capabilityId = '') {
      return (this.analysisCapabilities || []).find(item => text(item?.id) === text(capabilityId)) || null
    },
    getActiveAnalysisCapability() {
      return this.getAnalysisCapabilityById(this.activeAnalysisCapabilityId)
    },
    getAnalysisCapabilityReadiness(capabilityId = '') {
      return (this.analysisCapabilityReadiness || {})[text(capabilityId)] || null
    },
    getAnalysisCapabilityReadinessError(capabilityId = '') {
      return (this.analysisCapabilityReadinessErrors || {})[text(capabilityId)] || ''
    },
    isAnalysisCapabilityReady(capabilityId = '') {
      return this.getAnalysisCapabilityReadiness(capabilityId)?.status === 'ready'
    },
    getAnalysisCapabilityInputResolutions(capabilityId = '') {
      const resolutions = this.getAnalysisCapabilityReadiness(capabilityId)?.input_resolutions
      return Array.isArray(resolutions) ? clonePayloadValue(resolutions) : []
    },
    getAnalysisCapabilityInputSelection(capabilityId = '', requirementId = '') {
      const capabilitySelections = (this.analysisCapabilityInputSelections || {})[text(capabilityId)] || {}
      const selected = capabilitySelections[text(requirementId)]
      if (selected && typeof selected === 'object') return { ...selected }
      const resolution = this.getAnalysisCapabilityInputResolutions(capabilityId)
        .find(item => text(item.requirement_id) === text(requirementId))
      return {
        mode: text(resolution?.selection_mode) || 'latest_successful',
        run_id: text(resolution?.selected_run_id),
      }
    },
    buildAnalysisCapabilityInputSelections(capabilityId = '') {
      return this.getAnalysisCapabilityInputResolutions(capabilityId).map((resolution) => {
        const selected = this.getAnalysisCapabilityInputSelection(capabilityId, resolution.requirement_id)
        const item = {
          requirement_id: text(resolution.requirement_id),
          mode: text(selected.mode) || 'latest_successful',
        }
        if (item.mode === 'specific_run') item.run_id = text(selected.run_id)
        return item
      })
    },
    buildLockedAnalysisCapabilityInputSelections(capabilityId = '') {
      return this.getAnalysisCapabilityInputResolutions(capabilityId).map((resolution) => {
        const requirementId = text(resolution.requirement_id)
        const state = text(resolution.state)
        const runId = text(resolution.selected_run_id)
        if (state === 'ignored') return { requirement_id: requirementId, mode: 'ignore_optional' }
        if (state === 'resolved' && runId) {
          return { requirement_id: requirementId, mode: 'specific_run', run_id: runId }
        }
        const selected = this.getAnalysisCapabilityInputSelection(capabilityId, requirementId)
        const item = { requirement_id: requirementId, mode: text(selected.mode) || 'latest_successful' }
        if (item.mode === 'specific_run') item.run_id = text(selected.run_id)
        return item
      })
    },
    getAnalysisCapabilityRunPreview(capability = null) {
      const activeCapability = capability || this.getActiveAnalysisCapability()
      if (!activeCapability) return null
      const capabilityId = text(activeCapability.id)
      const readiness = this.getAnalysisCapabilityReadiness(capabilityId)
      const readinessError = this.getAnalysisCapabilityReadinessError(capabilityId)
      const snapshot = typeof this.buildAgentAnalysisSnapshot === 'function'
        ? clonePayloadValue(this.buildAgentAnalysisSnapshot() || {})
        : {}
      const selectedSourcesContext = buildAnalysisQuickAskSelectedSourcesContext(this)
      const selectedSources = (selectedSourcesContext.sources || []).map(source => ({
        id: text(source?.source_id),
        title: text(source?.title) || text(source?.source_id) || '未命名来源',
        kind: text(source?.source_kind) || 'analysis',
      }))
      const scope = snapshot.scope || {}
      const scopePolygon = Array.isArray(scope.drawn_polygon) && scope.drawn_polygon.length
        ? scope.drawn_polygon
        : (Array.isArray(scope.polygon) ? scope.polygon : [])
      let scopeLabel = '未检测到地图空间范围'
      if (scope.isochrone_feature) scopeLabel = '当前等时圈分析范围'
      else if (scopePolygon.length) scopeLabel = `当前地图多边形 · ${scopePolygon.length} 个顶点`
      else if (text(snapshot.context?.history_id)) scopeLabel = `当前历史任务 · ${text(snapshot.context.history_id)}`

      const parameters = []
      const addParameter = (label, value) => {
        const normalized = text(value)
        if (normalized && !parameters.some(item => item.label === label && item.value === normalized)) {
          parameters.push({ label, value: normalized })
        }
      }
      const modeLabels = { walking: '步行', driving: '驾车', bicycling: '骑行', transit: '公共交通' }
      const context = snapshot.context || {}
      const filters = snapshot.current_filters || {}
      if (text(context.mode)) addParameter('交通方式', modeLabels[text(context.mode)] || context.mode)
      if (Number(context.time_min) > 0) addParameter('时间阈值', `${Number(context.time_min)} 分钟`)
      addParameter('数据来源', context.source || filters.poi_source)
      if (Number(filters.h3_resolution) > 0) addParameter('H3 分辨率', filters.h3_resolution)
      addParameter('路网指标', filters.road_metric)
      addParameter('人口视图', filters.population_view)
      addParameter('夜光视图', filters.nightlight_view)
      if (!parameters.length) addParameter('参数策略', '沿用当前分析上下文默认参数')

      const lockedSelections = new Map(
        this.buildLockedAnalysisCapabilityInputSelections(capabilityId)
          .map(item => [text(item.requirement_id), item]),
      )
      const selectedInputs = this.getAnalysisCapabilityInputResolutions(capabilityId).map((resolution) => {
        const locked = lockedSelections.get(text(resolution.requirement_id)) || {}
        return {
          requirement_id: text(resolution.requirement_id),
          label: text(resolution.label) || text(resolution.requirement_id),
          state: text(resolution.state),
          mode: text(locked.mode),
          run_id: text(locked.run_id),
          artifact_count: Array.isArray(resolution.artifact_refs) ? resolution.artifact_refs.length : 0,
        }
      })

      const risks = []
      const addRisks = (items, level, prefix = '') => {
        for (const item of items || []) {
          const label = text(item?.label || item)
          if (label) risks.push({ level, label: prefix ? `${prefix}${label}` : label })
        }
      }
      if (readinessError) addRisks([readinessError], 'blocked')
      addRisks(readiness?.missing_required, 'blocked', '缺少必需输入：')
      addRisks(readiness?.conflicts, 'blocked', '输入冲突：')
      addRisks(readiness?.missing_optional, 'warning', '可选缺口：')
      addRisks(readiness?.actions, 'warning', '建议处理：')

      let status = 'checking'
      if (this.analysisCapabilityReadinessLoading) status = 'checking'
      else if (readinessError || ['blocked', 'unavailable'].includes(text(readiness?.status))) status = 'blocked'
      else if (text(readiness?.status) === 'ready') status = 'ready'
      else if (text(readiness?.status) === 'limited') status = 'review'

      return {
        capability_id: capabilityId,
        status,
        capability: text(activeCapability.display_name) || capabilityId,
        scope: scopeLabel,
        sources: selectedSources,
        parameters: parameters.slice(0, 6),
        model: this.isN8nSpatialStrategyCapability(activeCapability)
          ? 'Codex Harness（SDK）'
          : 'Codex App Server',
        executor: this.isN8nSpatialStrategyCapability(activeCapability)
          ? 'n8n · 11 章策略编排'
          : `${activeCapability.executor_type === 'service' ? '服务' : 'Skill'} · ${text(activeCapability.executor_id) || '未配置'}`,
        estimated_stages: Number(activeCapability.estimated_stages || 0) || 1,
        selected_inputs: selectedInputs,
        risks,
        outputs: Array.isArray(activeCapability.output_contract)
          ? activeCapability.output_contract.map(text).filter(Boolean)
          : [],
      }
    },
    syncAnalysisCapabilityInputSelections(capabilityId = '', readiness = null) {
      const id = text(capabilityId)
      const previous = (this.analysisCapabilityInputSelections || {})[id] || {}
      const next = { ...previous }
      for (const resolution of readiness?.input_resolutions || []) {
        const requirementId = text(resolution?.requirement_id)
        if (!requirementId || next[requirementId]) continue
        next[requirementId] = {
          mode: text(resolution.selection_mode) || 'latest_successful',
          run_id: text(resolution.selected_run_id),
        }
      }
      this.analysisCapabilityInputSelections = {
        ...(this.analysisCapabilityInputSelections || {}),
        [id]: next,
      }
    },
    getAnalysisCapabilityInputRequirement(requirementId = '') {
      const requirements = this.getActiveAnalysisCapability()?.input_requirements
      return (Array.isArray(requirements) ? requirements : [])
        .find(item => text(item.id) === text(requirementId)) || null
    },
    getAnalysisCapabilityInputModes(resolution = null) {
      const requirement = this.getAnalysisCapabilityInputRequirement(resolution?.requirement_id)
      const modes = Array.isArray(requirement?.selection_modes) ? requirement.selection_modes : []
      return modes.map(mode => ({
        value: mode,
        label: {
          latest_successful: '使用最新成功版本',
          specific_run: '选择历史版本',
          recalculate: '先重新计算上游',
          ignore_optional: '明确忽略此可选输入',
        }[mode] || mode,
      }))
    },
    getAnalysisCapabilityInputStateLabel(resolution = null) {
      return {
        resolved: '已锁定',
        missing: '缺少版本',
        invalid: '选择无效',
        recalculate_required: '等待重算',
        ignored: '已明确忽略',
      }[text(resolution?.state)] || '待检查'
    },
    getAnalysisCapabilityVersionLabel(version = null) {
      const timestamp = text(version?.completed_at || version?.created_at)
      const suffix = version?.stale ? ' · 已过期' : ''
      return `${text(version?.run_id) || '未知版本'}${timestamp ? ` · ${timestamp}` : ''}${suffix}`
    },
    async setAnalysisCapabilityInputMode(capabilityId = '', requirementId = '', event = null) {
      const id = text(capabilityId)
      const requirement = text(requirementId)
      const mode = text(event?.target?.value || event) || 'latest_successful'
      const current = (this.analysisCapabilityInputSelections || {})[id] || {}
      this.analysisCapabilityInputSelections = {
        ...(this.analysisCapabilityInputSelections || {}),
        [id]: {
          ...current,
          [requirement]: { mode, run_id: '' },
        },
      }
      if (mode === 'specific_run') {
        const readiness = this.getAnalysisCapabilityReadiness(id)
        if (readiness) {
          this.analysisCapabilityReadiness = {
            ...this.analysisCapabilityReadiness,
            [id]: {
              ...clonePayloadValue(readiness),
              input_resolutions: this.getAnalysisCapabilityInputResolutions(id).map(item => (
                text(item.requirement_id) === requirement
                  ? { ...item, selection_mode: mode, state: 'missing', selected_run_id: '', artifact_refs: [], diagnostics: ['请选择一个不可变历史版本。'] }
                  : item
              )),
            },
          }
        }
      }
      if (mode !== 'specific_run') {
        await this.refreshAnalysisCapabilityReadiness(this.getActiveAnalysisCapability())
      }
    },
    async setAnalysisCapabilityInputRun(capabilityId = '', requirementId = '', event = null) {
      const id = text(capabilityId)
      const requirement = text(requirementId)
      const runId = text(event?.target?.value || event)
      const current = (this.analysisCapabilityInputSelections || {})[id] || {}
      this.analysisCapabilityInputSelections = {
        ...(this.analysisCapabilityInputSelections || {}),
        [id]: {
          ...current,
          [requirement]: { mode: 'specific_run', run_id: runId },
        },
      }
      if (runId) await this.refreshAnalysisCapabilityReadiness(this.getActiveAnalysisCapability())
    },
    async refreshAnalysisCapabilityReadiness(capability = null) {
      const id = text(capability?.id)
      if (!id) return null
      this.analysisCapabilityReadinessLoading = true
      this.analysisCapabilityReadinessErrors = { ...this.analysisCapabilityReadinessErrors, [id]: '' }
      try {
        const response = await fetch(`${CATALOG_URL}/${encodeURIComponent(id)}/readiness`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            conversation_id: text(this.activeAgentSessionId),
            history_id: typeof this.getCurrentAgentHistoryId === 'function' ? text(this.getCurrentAgentHistoryId()) : '',
            target_capability_id: id,
            capability_input_selections: this.buildAnalysisCapabilityInputSelections(id),
            messages: [{ role: 'user', content: CAPABILITY_PROMPTS[id] || capability.description || capability.display_name }],
            analysis_snapshot: typeof this.buildAgentAnalysisSnapshot === 'function' ? this.buildAgentAnalysisSnapshot() : {},
            selected_sources_context: buildAnalysisQuickAskSelectedSourcesContext(this),
          }),
        })
        if (!response.ok) throw new Error(`输入检查失败(${response.status})`)
        const readiness = await response.json()
        this.analysisCapabilityReadiness = { ...this.analysisCapabilityReadiness, [id]: readiness }
        this.syncAnalysisCapabilityInputSelections(id, readiness)
        return readiness
      } catch (error) {
        this.analysisCapabilityReadinessErrors = {
          ...this.analysisCapabilityReadinessErrors,
          [id]: error instanceof Error ? error.message : String(error),
        }
        return null
      } finally {
        this.analysisCapabilityReadinessLoading = false
      }
    },
    async inspectAnalysisCapability(capability = null) {
      const id = text(capability && capability.id)
      if (!id) return
      this.activeAnalysisCapabilityId = id
      const runsPromise = this.loadAnalysisRuns({ capabilityId: id }).catch(() => [])
      await this.refreshAnalysisCapabilityReadiness(capability)
      await runsPromise
    },
    async runAnalysisCapability(capability = null) {
      if (!capability || capability.status !== 'available') return
      const readiness = this.getAnalysisCapabilityReadiness(capability.id)
      if (!readiness || readiness.status !== 'ready') {
        this.analysisCapabilityReadinessErrors = {
          ...this.analysisCapabilityReadinessErrors,
          [capability.id]: readiness
            ? '请先完成并确认所有必需输入。'
            : '请先检查并锁定能力输入。',
        }
        return
      }
      const capabilityInputSelections = this.buildLockedAnalysisCapabilityInputSelections(capability.id)
      if (this.isN8nSpatialStrategyCapability(capability)) {
        return this.runN8nSpatialStrategy(capability)
      }
      if (capability.executor_type === 'service' && capability.executor_id === 'ppt-planning') {
        this.openAgentPptPlanningFromReport({ capabilityInputSelections })
        return
      }
      this.agentWorkspaceView = 'report'
      await this.submitAgentComposer({
        prompt: CAPABILITY_PROMPTS[capability.id] || capability.description,
        targetCapabilityId: capability.id,
        capabilityInputSelections,
      })
      await this.loadAnalysisRuns({ force: true, capabilityId: capability.id }).catch(() => {})
      await this.loadAnalysisCapabilityOverview(true).catch(() => {})
    },
    getAnalysisRun() {
      const run = (this.agentPanelPayloads || {}).analysis_run
      return run && typeof run === 'object' ? clonePayloadValue(run) : null
    },
    getAnalysisRunStatusLabel() {
      return this.getAnalysisCapabilityRunStatusLabel(this.getAnalysisRun())
    },
    getAnalysisRunStages() {
      const records = this.getAnalysisRun()?.stage_records
      return Array.isArray(records) ? clonePayloadValue(records) : []
    },
    getAnalysisRunOutputArtifacts() {
      const artifacts = this.getAnalysisRun()?.output_artifact_refs
      return Array.isArray(artifacts) ? clonePayloadValue(artifacts) : []
    },
    getAnalysisRunArtifactTypeLabel(artifact) {
      const labels = {
        structured_data: '结构化数据',
        map_layer: '地图图层',
        table: '表格',
        chart: '图表',
        report: '报告',
        presentation: '演示文稿',
        evidence_nodes: '证据节点',
        design_handoff: '设计移交',
        export_file: '导出文件',
        diagnostic_report: '诊断记录',
      }
      return labels[artifact?.artifact_type] || text(artifact?.artifact_type) || '产物'
    },
    getAnalysisRunArtifactLineageText(artifact) {
      const upstream = Array.isArray(artifact?.source_artifact_refs) ? artifact.source_artifact_refs.length : 0
      const evidence = Array.isArray(artifact?.evidence_refs) ? artifact.evidence_refs.length : 0
      const parts = [`${upstream} 个上游`]
      if (evidence) parts.push(`${evidence} 条证据`)
      if (text(artifact?.content_digest)) parts.push(text(artifact.content_digest).slice(0, 18))
      return parts.join(' · ')
    },
    getAnalysisRunCurrentStageLabel() {
      return this.getAnalysisCapabilityRunCurrentStageLabel(this.getAnalysisRun())
    },
    getAnalysisRunModelLabel() {
      const profile = this.getAnalysisRun()?.execution_profile || {}
      return text(profile.model_display_name || profile.model || profile.model_profile_id) || '未锁定模型'
    },
    getAnalysisRunSkillLabel() {
      const profile = this.getAnalysisRun()?.execution_profile || {}
      return text(profile.skill_display_name || profile.skill_id) || '未锁定 Skill'
    },
    getAnalysisRunSourceCount() {
      return this.getAnalysisRun()?.input_artifact_refs?.length || 0
    },
    getStage1QualityAudit() {
      return (this.agentPanelPayloads || {}).stage1_quality_audit || null
    },
    getStage1SpatialObjectRegistry() {
      const registry = (this.agentPanelPayloads || {}).stage1_spatial_object_registry
      return registry && typeof registry === 'object' ? clonePayloadValue(registry) : null
    },
    getStage1SpatialObjectRegistryStatusLabel() {
      const labels = {
        ready: '权威空间对象目录可用于地图绑定',
        partial: '部分空间对象可用；绑定能力存在缺口',
        unavailable: '缺少可定位的权威空间对象',
      }
      return labels[this.getStage1SpatialObjectRegistry()?.status] || '尚未核对权威空间对象目录'
    },
    getStage1SpatialObjectRegistryTypeSummary() {
      const counts = this.getStage1SpatialObjectRegistry()?.object_type_counts
      if (!counts || typeof counts !== 'object') return '尚无已接受对象'
      const summary = Object.entries(counts)
        .filter(([objectType, count]) => text(objectType) && Number.isFinite(Number(count)) && Number(count) > 0)
        .map(([objectType, count]) => `${text(objectType).replaceAll('_', ' ')} ${Number(count)}`)
        .join(' · ')
      return summary || '尚无已接受对象'
    },
    getStage1SpatialMatrixRepair() {
      const repair = (this.agentPanelPayloads || {}).stage1_spatial_matrix_repair
      return repair && typeof repair === 'object' ? clonePayloadValue(repair) : null
    },
    getStage1SpatialMatrixRepairStatusLabel() {
      const repair = this.getStage1SpatialMatrixRepair()
      if (repair?.status === 'passed') return '矩阵契约已由 Agent 自主修复'
      if (repair?.status === 'failed') return '一次自主修复后仍未通过契约'
      return '未触发矩阵契约修复'
    },
    getStage1RepairPlan() {
      const plan = (this.agentPanelPayloads || {}).stage1_repair_plan
      return plan && typeof plan === 'object' ? clonePayloadValue(plan) : null
    },
    getStage1RepairAttempts() {
      const attempts = (this.agentPanelPayloads || {}).stage1_repair_attempts
      return Array.isArray(attempts) ? clonePayloadValue(attempts) : []
    },
    getStage1RepairStatusLabel() {
      const plan = this.getStage1RepairPlan()
      const attempts = this.getStage1RepairAttempts()
      const latest = attempts.at(-1)
      if (latest?.status === 'passed') return 'Agent 已自主修复并重新通过审计'
      if (latest?.status === 'incomplete') return 'Agent 已修复一次，仍有阻断项'
      if (latest?.status === 'failed') return '自主修复结果未通过契约'
      if (plan?.status === 'automatic') return '已识别可由 Agent 自主修复的问题'
      if (plan?.status === 'external_input_required') return '需要补充外部证据或现场核验'
      return '无需自主修复'
    },
    getStage1RepairScoreText(attempt) {
      const before = Number(attempt?.before_audit?.score)
      const after = Number(attempt?.after_audit?.score)
      if (!Number.isFinite(before) || !Number.isFinite(after)) return ''
      return before === after ? `${before} 分` : `${before} → ${after} 分`
    },
    getStage1EvidenceVerification() {
      return (this.agentPanelPayloads || {}).stage1_evidence_verification || null
    },
    getStage1ConflictRegister() {
      const conflicts = (this.agentPanelPayloads || {}).stage1_conflict_register
      return Array.isArray(conflicts) ? clonePayloadValue(conflicts) : []
    },
    getStage1UnresolvedConflictCount() {
      return this.getStage1ConflictRegister().filter(item => item?.unresolved === true).length
    },
    getStage1ConflictStatusLabel(conflict) {
      return conflict?.unresolved === true ? '待裁决' : '已确定口径'
    },
    getStage1ConflictValuesText(conflict) {
      return Array.isArray(conflict?.values) ? conflict.values.map(text).filter(Boolean).join(' / ') : ''
    },
    getStage1ProvenanceBinding() {
      const provenance = (this.agentPanelPayloads || {}).stage1_provenance_binding
      return provenance && typeof provenance === 'object' ? clonePayloadValue(provenance) : null
    },
    getStage1ProvenanceStatusLabel() {
      const labels = {
        passed: '真实资产绑定通过',
        passed_with_gaps: '真实资产绑定存在缺口',
        failed: '真实资产绑定阻断交付',
      }
      return labels[this.getStage1ProvenanceBinding()?.status] || '尚未执行真实资产绑定'
    },
    getStage1ProvenanceStatusItems() {
      const counts = this.getStage1ProvenanceBinding()?.status_counts || {}
      const labels = {
        verified: '已验证',
        corrected: '已修正',
        unverifiable: '无法定位',
        conflicting: '来源冲突',
      }
      return Object.entries(labels)
        .map(([key, label]) => ({ key, label, count: Number(counts[key] || 0) }))
        .filter(item => item.count > 0)
    },
    getStage1ProvenanceBindings() {
      const bindings = this.getStage1ProvenanceBinding()?.bindings
      return Array.isArray(bindings) ? clonePayloadValue(bindings) : []
    },
    getStage1ProvenanceIssues() {
      const issues = this.getStage1ProvenanceBinding()?.issues
      return Array.isArray(issues) ? clonePayloadValue(issues) : []
    },
    getStage1ProvenanceCorrectionText(binding) {
      const fields = Array.isArray(binding?.corrected_fields) ? binding.corrected_fields.map(text).filter(Boolean) : []
      return fields.length ? `修正字段：${fields.join('、')}` : ''
    },
    getStage1ProvenanceUnverifiedText(binding) {
      const fields = Array.isArray(binding?.unverified_fields) ? binding.unverified_fields.map(text).filter(Boolean) : []
      return fields.length ? `资产未登记：${fields.join('、')}` : ''
    },
    getStage1ProvenanceDiscrepancyText(binding) {
      const discrepancies = Array.isArray(binding?.discrepancies) ? binding.discrepancies : []
      return discrepancies.map((item) => {
        const declared = item?.declared && typeof item.declared === 'object' ? JSON.stringify(item.declared) : text(item?.declared) || '未声明'
        const authoritative = item?.authoritative && typeof item.authoritative === 'object' ? JSON.stringify(item.authoritative) : text(item?.authoritative) || '未登记'
        return `${text(item?.field) || '字段'}：${declared} → ${authoritative}`
      }).join('；')
    },
    getStage1DataQuality() {
      const quality = (this.agentPanelPayloads || {}).stage1_data_quality
      return quality && typeof quality === 'object' ? clonePayloadValue(quality) : null
    },
    getStage1DataQualityStatusLabel() {
      const labels = {
        passed: '数据质量通过',
        passed_with_gaps: '数据质量存在缺口',
        failed: '数据质量阻断交付',
      }
      return labels[this.getStage1DataQuality()?.status] || '尚未执行数据质量审计'
    },
    getStage1DataQualityCoverageItems() {
      const quality = this.getStage1DataQuality() || {}
      const total = Number(quality.assessed_count || 0)
      const analyticTotal = Number(quality.analytic_count || 0)
      const coverage = quality.coverage || {}
      const labels = {
        source_date: '来源日期',
        source_locator: '精确定位',
        analysis_date: '计算日期',
        sample_diagnostics: '样本诊断',
        coordinate_system: '坐标口径',
      }
      return Object.entries(labels).map(([key, label]) => {
        const itemTotal = ['analysis_date', 'sample_diagnostics', 'coordinate_system'].includes(key) ? analyticTotal : total
        const count = Number(coverage[key] || 0)
        return { key, label, count, total: itemTotal, display: itemTotal > 0 ? `${count}/${itemTotal}` : '不适用', gap: itemTotal > 0 && count < itemTotal }
      })
    },
    getStage1DataQualityIssues() {
      const issues = this.getStage1DataQuality()?.issues
      return Array.isArray(issues) ? clonePayloadValue(issues) : []
    },
    getStage1DataQualityCoordinateText() {
      const systems = this.getStage1DataQuality()?.coordinate_systems
      return Array.isArray(systems) ? systems.map(text).filter(Boolean).join(' / ') : ''
    },
    getStage1HardConstraintScreening() {
      const screening = (this.agentPanelPayloads || {}).stage1_hard_constraint_screening
      return screening && typeof screening === 'object' ? clonePayloadValue(screening) : null
    },
    getStage1HardConstraintStatusLabel() {
      const labels = {
        clear: '硬约束已确认',
        conditional: '硬约束待核验',
        blocked: '硬约束阻断方案',
      }
      return labels[this.getStage1HardConstraintScreening()?.status] || '尚未执行硬约束筛选'
    },
    getStage1HardConstraintAssessments() {
      const assessments = this.getStage1HardConstraintScreening()?.assessments
      return Array.isArray(assessments) ? clonePayloadValue(assessments) : []
    },
    getStage1HardConstraintStateLabel(assessment) {
      const labels = { verified: '已核验', constrained: '存在限制', unknown: '待核验', not_applicable: '不适用' }
      return labels[assessment?.state] || text(assessment?.state) || '未标记'
    },
    getStage1HardConstraintEffectLabel(assessment) {
      const labels = { allow: '允许进入方案', condition: '作为前置条件', exclude: '排除当前方案' }
      return labels[assessment?.decision_effect] || text(assessment?.decision_effect) || '未标记'
    },
    getStage1HardConstraintPendingActions() {
      const actions = this.getStage1HardConstraintScreening()?.pending_actions
      return Array.isArray(actions) ? clonePayloadValue(actions) : []
    },
    getStage1Deliverables() {
      const deliverables = (this.agentPanelPayloads || {}).stage1_deliverables
      return deliverables && typeof deliverables === 'object' ? clonePayloadValue(deliverables) : null
    },
    getStage1DeliverableArtifacts() {
      const artifacts = this.getStage1Deliverables()?.artifacts
      return Array.isArray(artifacts) ? clonePayloadValue(artifacts) : []
    },
    getStage1DesignHandoff() {
      const handoff = this.getStage1Deliverables()?.design_handoff
      return handoff && typeof handoff === 'object' ? clonePayloadValue(handoff) : null
    },
    getStage1DesignHandoffSpaceCount() {
      const requirements = this.getStage1DesignHandoff()?.space_requirements
      return Array.isArray(requirements) ? requirements.length : 0
    },
    getStage1DesignHandoffConstraintCount() {
      const constraints = this.getStage1DesignHandoff()?.unresolved_constraints
      return Array.isArray(constraints) ? constraints.length : 0
    },
    hasStage1Outcome() {
      return !!(this.getAnalysisRun() || this.getStage1QualityAudit() || this.getStage1EvidenceVerification() || this.getStage1ProvenanceBinding() || this.getStage1DataQuality() || this.getStage1HardConstraintScreening() || this.getStage1Deliverables())
    },
    getStage1EvidenceLedger() {
      const ledger = (this.agentPanelPayloads || {}).stage1_evidence_nodes
      return Array.isArray(ledger) ? clonePayloadValue(ledger) : []
    },
    getStage1EvidenceCount() {
      return this.getStage1EvidenceLedger().length
    },
    getStage1SpatialMatrix() {
      const matrix = (this.agentPanelPayloads || {}).stage1_spatial_matrix
      return matrix && typeof matrix === 'object' ? clonePayloadValue(matrix) : null
    },
    getStage1SpatialMapPresentation() {
      const presentation = this.getStage1SpatialMatrix()?.map_presentation
      return presentation && typeof presentation === 'object' ? clonePayloadValue(presentation) : null
    },
    getStage1SpatialMapModes() {
      const modes = this.getStage1SpatialMapPresentation()?.modes
      return Array.isArray(modes) ? clonePayloadValue(modes) : []
    },
    getStage1SpatialMapMode() {
      const modes = this.getStage1SpatialMapModes()
      const selected = text(this.stage1SpatialMapMode)
      return modes.find(item => text(item?.id) === selected) || modes[0] || null
    },
    getStage1SpatialHierarchyLevels() {
      const levels = this.getStage1SpatialMapPresentation()?.hierarchy_levels
      return [
        { id: 'all', label: '全部层级', decision_count: this.getStage1SpaceDecisionCount() },
        ...(Array.isArray(levels) ? clonePayloadValue(levels) : []),
      ]
    },
    getStage1SpatialHierarchyLabel(level) {
      return { system: '系统层', cluster: '组团层', unit: '单元层' }[text(level)] || text(level) || '未分层'
    },
    getStage1SpatialPresentationItems() {
      const items = this.getStage1SpatialMapPresentation()?.items
      const level = text(this.stage1SpatialHierarchyLevel) || 'all'
      return (Array.isArray(items) ? clonePayloadValue(items) : [])
        .filter(item => level === 'all' || text(item?.hierarchy_level) === level)
    },
    getStage1SpatialPresentationItem(spaceId) {
      const items = this.getStage1SpatialMapPresentation()?.items
      return (Array.isArray(items) ? items : [])
        .find(item => text(item?.space_id) === text(spaceId)) || null
    },
    getStage1DecisionMapValue(decision, modeId) {
      const value = this.getStage1SpatialPresentationItem(decision?.space_id)?.values?.[text(modeId)]
      return value && typeof value === 'object' ? clonePayloadValue(value) : null
    },
    getStage1SpatialPresentationLegend() {
      const mode = this.getStage1SpatialMapMode()
      return Array.isArray(mode?.legend) ? clonePayloadValue(mode.legend) : []
    },
    getStage1SpatialPresentationBoundCount() {
      return this.getStage1SpatialPresentationItems()
        .filter(item => item?.map_binding?.status === 'bound' && item?.map_binding?.feature?.geometry).length
    },
    setStage1SpatialMapMode(mode) {
      this.stage1SpatialMapMode = text(mode?.target?.value || mode) || 'suggested_function'
      return this.renderStage1SpatialPresentation()
    },
    setStage1SpatialHierarchyLevel(level) {
      this.stage1SpatialHierarchyLevel = text(level?.target?.value || level) || 'all'
      return this.renderStage1SpatialPresentation()
    },
    renderStage1SpatialPresentation({ fitView = true } = {}) {
      const mapCore = this.mapCore
      if (!mapCore || typeof mapCore.showSpatialPresentation !== 'function') {
        this.stage1SpatialPresentationMessage = '地图尚未就绪，无法显示空间策划图层。'
        return 0
      }
      const mode = this.getStage1SpatialMapMode()
      if (!mode) {
        if (typeof mapCore.clearSpatialPresentation === 'function') mapCore.clearSpatialPresentation()
        this.stage1SpatialPresentationMessage = '当前矩阵没有可用的地图表达模式。'
        return 0
      }
      const items = this.getStage1SpatialPresentationItems()
        .filter(item => item?.map_binding?.status === 'bound' && item?.map_binding?.feature?.geometry)
        .map(item => ({
          space_id: text(item?.space_id),
          feature: clonePayloadValue(item.map_binding.feature),
          color: text(item?.values?.[mode.id]?.color) || '#0f766e',
          label: text(item?.values?.[mode.id]?.label),
        }))
      const count = mapCore.showSpatialPresentation(items, {
        fitView,
        onClick: item => {
          const decision = this.getStage1SpaceDecisionById(item?.space_id)
          if (decision) this.selectStage1SpaceDecision(decision)
        },
      })
      const levelLabel = this.stage1SpatialHierarchyLevel === 'all'
        ? '全部层级'
        : this.getStage1SpatialHierarchyLabel(this.stage1SpatialHierarchyLevel)
      this.stage1SpatialPresentationMessage = count
        ? `已显示${levelLabel}的“${text(mode.label)}”图层，共 ${count} 个地图覆盖物。`
        : '当前筛选下没有已绑定权威几何的空间决策。'
      return count
    },
    getStage1MovementPresentation() {
      const presentation = this.getStage1SpatialMatrix()?.movement_presentation
      return presentation && typeof presentation === 'object' ? clonePayloadValue(presentation) : null
    },
    getStage1MovementTypes() {
      const types = this.getStage1MovementPresentation()?.types
      const items = Array.isArray(types) ? clonePayloadValue(types) : []
      return [
        { id: 'all', label: '全部流线', color: '', route_count: this.getStage1MovementRouteCount() },
        ...items,
      ]
    },
    getStage1MovementItems() {
      const items = this.getStage1MovementPresentation()?.items
      const movementType = text(this.stage1MovementType) || 'all'
      return (Array.isArray(items) ? clonePayloadValue(items) : [])
        .filter(item => movementType === 'all' || text(item?.movement_type) === movementType)
    },
    getStage1MovementRouteCount() {
      const items = this.getStage1MovementPresentation()?.items
      return Array.isArray(items) ? items.length : 0
    },
    getStage1MovementBoundCount() {
      return this.getStage1MovementItems()
        .filter(item => item?.map_binding?.status === 'bound' && item?.map_binding?.feature?.geometry).length
    },
    getStage1MovementAffectedSpaceNames(route) {
      const names = (Array.isArray(route?.affected_space_ids) ? route.affected_space_ids : [])
        .map(spaceId => this.getStage1SpaceDecisionById(spaceId)?.space_name || text(spaceId))
        .filter(Boolean)
      return names.join('、') || '未关联空间'
    },
    isStage1MovementSelected(route) {
      return !!text(route?.route_id) && text(route?.route_id) === text(this.stage1SelectedMovementRouteId)
    },
    selectStage1MovementRoute(route) {
      const routeId = text(route?.route_id)
      if (!routeId) return null
      this.stage1SelectedMovementRouteId = routeId
      const firstSpaceId = Array.isArray(route?.affected_space_ids) ? text(route.affected_space_ids[0]) : ''
      const decision = firstSpaceId ? this.getStage1SpaceDecisionById(firstSpaceId) : null
      if (decision) this.selectStage1SpaceDecision(decision)
      return route
    },
    setStage1MovementType(movementType) {
      this.stage1MovementType = text(movementType?.target?.value || movementType) || 'all'
      return this.renderStage1MovementPresentation()
    },
    renderStage1MovementPresentation({ fitView = true } = {}) {
      const mapCore = this.mapCore
      if (!mapCore || typeof mapCore.showSpatialPresentation !== 'function') {
        this.stage1MovementPresentationMessage = '地图尚未就绪，无法显示策划流线。'
        return 0
      }
      const items = this.getStage1MovementItems()
        .filter(item => item?.map_binding?.status === 'bound' && item?.map_binding?.feature?.geometry)
        .map(item => ({
          route_id: text(item?.route_id),
          feature: clonePayloadValue(item.map_binding.feature),
          color: text(item?.color),
          label: text(item?.movement_label),
          strokeWeight: 6,
        }))
      const count = mapCore.showSpatialPresentation(items, {
        fitView,
        onClick: item => {
          const route = this.getStage1MovementItems().find(candidate => text(candidate?.route_id) === text(item?.route_id))
          if (route) this.selectStage1MovementRoute(route)
        },
      })
      const selectedType = this.getStage1MovementTypes()
        .find(item => text(item?.id) === text(this.stage1MovementType))
      this.stage1MovementPresentationMessage = count
        ? `已显示“${text(selectedType?.label) || '全部流线'}”，共 ${count} 个权威路径覆盖物。点击地图路径可定位流线及关联空间。`
        : '当前筛选下没有已绑定权威路径的流线；请查看卡片中的缺口和核验动作。'
      return count
    },

    getStage1SpaceDecisions() {
      const decisions = this.getStage1SpatialMatrix()?.space_decisions
      return Array.isArray(decisions) ? clonePayloadValue(decisions) : []
    },
    getStage1SpaceDecisionCount() {
      return this.getStage1SpaceDecisions().length
    },
    getStage1SpaceManagementRows() {
      return this.getStage1SpaceDecisions().map(decision => ({
        space_id: text(decision?.space_id),
        space_name: text(decision?.space_name) || text(decision?.space_id) || '未命名空间',
        hierarchy_id: text(decision?.hierarchy_id),
        hierarchy_level: text(this.getStage1SpatialPresentationItem(decision?.space_id)?.hierarchy_level),
        hierarchy_label: this.getStage1SpatialHierarchyLabel(this.getStage1SpatialPresentationItem(decision?.space_id)?.hierarchy_level),
        future_role: text(decision?.future_role) || '未说明',
        preferred_function: this.getStage1FunctionLabel(decision?.preferred_function),
        core_audiences: this.getStage1DecisionDetailText(decision?.core_audiences),
        movement_role: text(decision?.movement_role) || '未说明',
        value_role: text(decision?.value_role) || '未说明',
        recommendation_status: text(decision?.recommendation_status),
        recommendation_label: this.getStage1DecisionStatusLabel(decision),
        preconditions: this.getStage1DecisionDetailText(decision?.preconditions),
        evidence_count: Array.isArray(decision?.evidence_refs) ? decision.evidence_refs.length : 0,
        map_bound: this.isStage1MapBindingAvailable(decision),
        map_label: this.getStage1MapBindingLabel(decision),
      }))
    },
    getStage1SpaceDecisionById(spaceId) {
      const target = text(spaceId)
      return this.getStage1SpaceDecisions().find(item => text(item?.space_id) === target) || null
    },
    getStage1MapBinding(decision) {
      const binding = decision?.map_binding
      return binding && typeof binding === 'object' ? clonePayloadValue(binding) : null
    },
    isStage1MapBindingAvailable(decision) {
      const binding = this.getStage1MapBinding(decision)
      return binding?.status === 'bound' && !!text(binding?.spatial_object_id) && !!binding?.feature?.geometry
    },
    getStage1MapBindingLabel(decision) {
      const binding = this.getStage1MapBinding(decision)
      if (this.isStage1MapBindingAvailable(decision)) {
        return text(binding?.title) || text(binding?.spatial_object_id) || '已绑定地图对象'
      }
      return text(binding?.reason) || '没有权威地图对象绑定'
    },
    selectStage1SpaceDecision(decision) {
      const spaceId = text(decision?.space_id)
      if (!spaceId) return
      this.stage1ExpandedSpaceId = spaceId
      this.stage1ExpandedRunId = text(this.getAnalysisRun()?.run_id)
    },
    isStage1SpaceDecisionExpanded(decision) {
      return text(this.stage1ExpandedRunId) === text(this.getAnalysisRun()?.run_id)
        && text(this.stage1ExpandedSpaceId) === text(decision?.space_id)
    },
    toggleStage1SpaceDecision(decision, event = null) {
      const open = !!event?.target?.open
      if (open) this.selectStage1SpaceDecision(decision)
      else if (this.isStage1SpaceDecisionExpanded(decision)) {
        this.stage1ExpandedSpaceId = ''
        this.stage1ExpandedRunId = ''
      }
    },
    focusStage1SpaceOnMap(decision) {
      const binding = this.getStage1MapBinding(decision)
      if (!this.isStage1MapBindingAvailable(decision)) {
        this.stage1MapFocusMessage = this.getStage1MapBindingLabel(decision)
        return false
      }
      const mapCore = this.mapCore
      if (!mapCore || typeof mapCore.focusSpatialFeature !== 'function') {
        this.stage1MapFocusMessage = '地图尚未就绪，无法定位该空间对象。'
        return false
      }
      const focused = mapCore.focusSpatialFeature(binding.feature, {
        fitView: true,
        onClick: () => this.selectStage1SpaceDecision(decision),
      })
      if (!focused) {
        this.stage1MapFocusMessage = '权威对象几何无法在当前地图中显示。'
        return false
      }
      this.selectStage1SpaceDecision(decision)
      this.stage1MapFocusedSpaceId = text(decision?.space_id)
      this.stage1MapFocusedRunId = text(this.getAnalysisRun()?.run_id)
      this.stage1MapFocusMessage = `已定位：${text(binding?.title) || text(decision?.space_name) || text(decision?.space_id)}`
      return true
    },
    isStage1SpaceMapFocused(decision) {
      return text(this.stage1MapFocusedRunId) === text(this.getAnalysisRun()?.run_id)
        && text(this.stage1MapFocusedSpaceId) === text(decision?.space_id)
    },
    resetStage1SpatialInteraction() {
      if (this.mapCore && typeof this.mapCore.clearSpatialFeatureFocus === 'function') {
        this.mapCore.clearSpatialFeatureFocus()
      }
      if (this.mapCore && typeof this.mapCore.clearSpatialPresentation === 'function') {
        this.mapCore.clearSpatialPresentation()
      }
      this.stage1ExpandedSpaceId = ''
      this.stage1ExpandedRunId = ''
      this.stage1MapFocusedSpaceId = ''
      this.stage1MapFocusedRunId = ''
      this.stage1MapFocusMessage = ''
      this.stage1SpatialPresentationMessage = ''
      this.stage1SelectedMovementRouteId = ''
      this.stage1MovementPresentationMessage = ''
    },
    openStage1EvidenceDrawer(decision) {
      const spaceId = text(decision?.space_id)
      if (!spaceId) return
      this.stage1EvidenceDrawerSpaceId = spaceId
      this.stage1EvidenceDrawerRunId = text(this.getAnalysisRun()?.run_id)
    },
    closeStage1EvidenceDrawer() {
      this.stage1EvidenceDrawerSpaceId = ''
      this.stage1EvidenceDrawerRunId = ''
    },
    getStage1EvidenceDrawerDecision() {
      if (text(this.stage1EvidenceDrawerRunId) !== text(this.getAnalysisRun()?.run_id)) return null
      return this.getStage1SpaceDecisionById(this.stage1EvidenceDrawerSpaceId)
    },
    getStage1DecisionEvidenceEntries(decision) {
      const refs = uniqueTextItems(decision?.evidence_refs, 64)
      if (!refs.length) return []
      const ledger = new Map(this.getStage1EvidenceLedger().map(item => [text(item?.id), item]))
      const verification = this.getStage1EvidenceVerification() || {}
      const tasks = Array.isArray(verification.tasks) ? verification.tasks : []
      const automatedChecks = Array.isArray(verification.automated_checks) ? verification.automated_checks : []
      const provenance = new Map(this.getStage1ProvenanceBindings().map(item => [text(item?.evidence_id), item]))
      const qualityIssues = this.getStage1DataQualityIssues()
      const conflicts = this.getStage1ConflictRegister()
      return refs.map((evidenceId) => {
        const node = ledger.get(evidenceId) || { id: evidenceId }
        return {
          ...clonePayloadValue(node),
          id: evidenceId,
          missing: !ledger.has(evidenceId),
          used_by_space_id: text(decision?.space_id),
          verification_task: clonePayloadValue(tasks.find(item => text(item?.evidence_id) === evidenceId) || null),
          automated_check: clonePayloadValue(automatedChecks.find(item => text(item?.evidence_id) === evidenceId) || null),
          provenance: clonePayloadValue(provenance.get(evidenceId) || null),
          quality_issues: clonePayloadValue(qualityIssues.filter(item => text(item?.evidence_id) === evidenceId)),
          conflicts: clonePayloadValue(conflicts.filter(item => item?.unresolved === true && (Array.isArray(item?.evidence_ids) ? item.evidence_ids : []).map(text).includes(evidenceId))),
        }
      })
    },
    getStage1EvidenceTypeLabel(entry) {
      const labels = { F: '项目事实', G: 'GIS 分析', P: '代理指标', H: '策划假设', V: '待验证事项' }
      return labels[entry?.evidence_type] || text(entry?.evidence_type) || '未标证据类型'
    },
    getStage1EvidenceStatusLabel(entry) {
      const labels = {
        verified: '已验证', cross_checked: '已交叉核对', inferred: '推断', hypothesis: '假设',
        blocked: '阻断', fieldwork_required: '需现场核验',
      }
      return labels[entry?.status] || text(entry?.status) || (entry?.missing ? '引用失效' : '未标验证状态')
    },
    getStage1EvidenceSourceText(entry) {
      return [entry?.source_ref, entry?.source_artifact_id, entry?.source_locator]
        .map(text).filter(Boolean).filter((item, index, values) => values.indexOf(item) === index).join(' · ')
    },
    getStage1EvidenceDateText(entry) {
      const parts = []
      if (text(entry?.source_date)) parts.push(`来源 ${text(entry.source_date)}`)
      if (text(entry?.analysis_date)) parts.push(`分析 ${text(entry.analysis_date)}`)
      return parts.join(' · ')
    },
    getStage1EvidenceMetricText(entry) {
      const metric = text(entry?.metric)
      const value = text(entry?.value)
      return [metric, value].filter(Boolean).join('：')
    },
    getStage1EvidenceQualityText(entry) {
      const parts = []
      if (text(entry?.confidence)) parts.push(`${this.getStage1DecisionConfidenceLabel(entry)}证据`)
      if (entry?.provenance?.status) parts.push(`来源${entry.provenance.status === 'verified' ? '已绑定' : entry.provenance.status === 'corrected' ? '已修正' : '存在缺口'}`)
      if (entry?.automated_check?.outcome) parts.push(`自动核验 ${text(entry.automated_check.outcome)}`)
      return parts.join(' · ')
    },
    getStage1EvidenceGapText(entry) {
      const parts = []
      if (entry?.missing) parts.push('该引用未在本轮证据节点中找到')
      if (text(entry?.limitation)) parts.push(text(entry.limitation))
      if (entry?.verification_task?.blocking_reason) parts.push(text(entry.verification_task.blocking_reason))
      if (Array.isArray(entry?.quality_issues)) parts.push(...entry.quality_issues.map(item => text(item?.message)))
      if (Array.isArray(entry?.conflicts)) parts.push(...entry.conflicts.map(item => `${text(item?.label || item?.metric_key) || '证据'}存在未裁决口径`))
      return uniqueTextItems(parts, 8).join('；')
    },
    getStage1EvidenceNextActionText(entry) {
      return text(entry?.verification_task?.next_action || entry?.next_action || entry?.verification_task?.verification_method)
    },
    getStage1FunctionLabel(value) {
      if (value && typeof value === 'object') return text(value.name || value.title || value.label || value.id) || '未命名功能'
      return text(value) || '未命名功能'
    },
    getStage1FunctionListText(values) {
      return Array.isArray(values) ? values.map(item => this.getStage1FunctionLabel(item)).filter(Boolean).join('、') : ''
    },
    getStage1DecisionDetailText(value) {
      return [...new Set(collectPayloadText(value))].join('；')
    },
    getStage1DecisionStatusLabel(decision) {
      const labels = { strong: '强推荐', conditional: '条件推荐', alternative: '备选', excluded: '排除' }
      return labels[decision?.recommendation_status] || text(decision?.recommendation_status) || '未标记'
    },
    getStage1DecisionConfidenceLabel(decision) {
      const labels = { high: '高置信', medium: '中置信', low: '低置信' }
      return labels[decision?.confidence] || text(decision?.confidence) || '未标记'
    },
    getStage1VerificationStatusLabel() {
      const verification = this.getStage1EvidenceVerification() || {}
      const labels = {
        passed: '证据门控通过',
        passed_with_gaps: '证据门控通过，仍有缺口',
        failed: '证据门控未通过',
      }
      return labels[verification.status] || '尚未执行证据门控'
    },
    getStage1VerificationStatusItems() {
      const counts = (this.getStage1EvidenceVerification() || {}).status_counts || {}
      const labels = {
        verified: '已验证',
        cross_checked: '已交叉核对',
        inferred: '推断',
        hypothesis: '假设',
        blocked: '阻塞',
        fieldwork_required: '需现场核验',
      }
      return Object.keys(labels)
        .filter(key => Number(counts[key] || 0) > 0)
        .map(key => ({ key, label: labels[key], count: Number(counts[key]) }))
    },
    getStage1AutomatedVerificationChecks() {
      const checks = (this.getStage1EvidenceVerification() || {}).automated_checks
      return Array.isArray(checks)
        ? checks.map(item => ({
            ...clonePayloadValue(item),
            claim_types: Array.isArray(item.claim_types) ? clonePayloadValue(item.claim_types) : [],
            diagnostics: Array.isArray(item.diagnostics) ? clonePayloadValue(item.diagnostics) : [],
            derived_values: clonePayloadValue(item.derived_values || {}),
          }))
        : []
    },
    getStage1VerificationToolLabel(check) {
      const labels = {
        verify_road_analysis_claim: '路网指标一致性核验',
        verify_proxy_indicator_claim: '代理指标边界核验',
      }
      return labels[check?.tool_id] || check?.tool_id || '自动核验'
    },
    getStage1VerificationDerivedText(check) {
      return Object.entries(check?.derived_values || {})
        .map(([key, value]) => `${key}=${value ?? '-'}`)
        .join('；')
    },
    getStage1QualityGate() {
      const verification = this.getStage1EvidenceVerification()
      const quality = this.getStage1QualityAudit()
      const provenance = this.getStage1ProvenanceBinding()
      const dataQuality = this.getStage1DataQuality()
      const deliverables = this.getStage1Deliverables()
      const hardConstraints = this.getStage1HardConstraintScreening()
      const conflicts = this.getStage1ConflictRegister()
      if (!verification && !quality && !provenance && !dataQuality && !hardConstraints && !deliverables && !conflicts.length) return null

      const checks = []
      const blockingItems = []
      const seenBlockingItems = new Set()
      const addBlockingItem = (source, message, repairHint = '') => {
        const normalizedMessage = text(message)
        if (!normalizedMessage || seenBlockingItems.has(normalizedMessage)) return
        seenBlockingItems.add(normalizedMessage)
        blockingItems.push({ source, message: normalizedMessage, repair_hint: text(repairHint) })
      }
      const statusFor = status => status === 'failed' ? 'failed' : status === 'passed_with_gaps' ? 'warning' : status === 'passed' ? 'passed' : 'pending'

      if (quality) {
        const auditIssues = Array.isArray(quality.issues) ? quality.issues : []
        checks.push({
          key: 'quality',
          label: '报告质量审计',
          status: quality.status === 'passed' && auditIssues.some(item => item?.severity === 'warning') ? 'warning' : statusFor(quality.status),
          detail: `${Number(quality.score || 0)} 分 · ${Number(quality.checks_passed || 0)}/${Number(quality.checks_total || 0)} 项通过`,
        })
        auditIssues.filter(item => item?.severity === 'error').forEach(item => addBlockingItem('报告质量', item.message, item.repair_hint))
        if (quality.status === 'failed' && !auditIssues.some(item => item?.severity === 'error')) addBlockingItem('报告质量', '报告质量审计未通过。')
      }
      if (verification) {
        const counts = verification.status_counts || {}
        const total = Object.values(counts).reduce((sum, value) => sum + Number(value || 0), 0)
        const verified = Number(counts.verified || 0) + Number(counts.cross_checked || 0)
        checks.push({ key: 'evidence', label: '证据门控', status: statusFor(verification.status), detail: `${verified}/${total} 条已验证或交叉核对` })
        const verificationBlockingReasons = Array.isArray(verification.blocking_reasons) ? verification.blocking_reasons : []
        verificationBlockingReasons.forEach(message => addBlockingItem('证据门控', message))
        if (verification.report_allowed === false && !verificationBlockingReasons.length) addBlockingItem('证据门控', '证据门控禁止生成正式报告。')
      }
      if (provenance) {
        const assessed = Number(provenance.assessed_count || 0)
        const bound = Number(provenance.status_counts?.verified || 0) + Number(provenance.status_counts?.corrected || 0)
        checks.push({ key: 'provenance', label: '真实来源绑定', status: statusFor(provenance.status), detail: `${bound}/${assessed} 条已定位或修正` })
        const provenanceIssues = Array.isArray(provenance.issues) ? provenance.issues : []
        provenanceIssues.filter(item => item?.severity === 'error').forEach(item => addBlockingItem('来源绑定', item.message, item.repair_hint))
        if (provenance.status === 'failed' && !provenanceIssues.some(item => item?.severity === 'error')) addBlockingItem('来源绑定', '关键证据未能绑定到真实数据资产。')
      }
      if (dataQuality) {
        checks.push({ key: 'data', label: '数据质量', status: statusFor(dataQuality.status), detail: `${Number(dataQuality.assessed_count || 0)} 条证据已审计` })
        const dataQualityIssues = Array.isArray(dataQuality.issues) ? dataQuality.issues : []
        dataQualityIssues.filter(item => item?.severity === 'error').forEach(item => addBlockingItem('数据质量', item.message, item.repair_hint))
        if (dataQuality.status === 'failed' && !dataQualityIssues.some(item => item?.severity === 'error')) addBlockingItem('数据质量', '数据质量审计未通过。')
      }

      if (hardConstraints) {
        const assessments = this.getStage1HardConstraintAssessments()
        const verified = assessments.filter(item => ['verified', 'not_applicable'].includes(item?.state)).length
        const status = hardConstraints.status === 'blocked' ? 'failed' : hardConstraints.status === 'conditional' ? 'warning' : hardConstraints.status === 'clear' ? 'passed' : 'pending'
        checks.push({ key: 'hard-constraints', label: '硬约束筛选', status, detail: `${verified}/${assessments.length} 项已确认或不适用` })
        if (hardConstraints.status === 'blocked') {
          assessments
            .filter(item => item?.decision_effect === 'exclude')
            .forEach(item => addBlockingItem('硬约束', `${text(item.label || item.constraint_id)}排除当前方案。`, item.verification_action || item.finding))
        }
      }

      const unresolvedConflicts = conflicts.filter(item => item?.unresolved === true)
      if (conflicts.length) {
        checks.push({ key: 'conflicts', label: '来源冲突', status: unresolvedConflicts.length ? 'failed' : 'passed', detail: unresolvedConflicts.length ? `${unresolvedConflicts.length} 项待裁决` : `${conflicts.length} 项已确定口径` })
        unresolvedConflicts.forEach(item => addBlockingItem('来源冲突', `${text(item.label || item.metric_key) || '关键指标'}仍存在未裁决口径冲突。`, item.explanation))
      }
      if (deliverables) {
        const artifactIds = new Set((Array.isArray(deliverables.artifacts) ? deliverables.artifacts : []).filter(item => item?.status === 'ready').map(item => text(item?.artifact_id)))
        const missingArtifactIds = REQUIRED_STAGE1_ARTIFACT_IDS.filter(id => !artifactIds.has(id))
        checks.push({ key: 'deliverables', label: '正式交付物', status: deliverables.status === 'ready' && !missingArtifactIds.length ? 'passed' : 'failed', detail: `${REQUIRED_STAGE1_ARTIFACT_IDS.length - missingArtifactIds.length}/${REQUIRED_STAGE1_ARTIFACT_IDS.length} 项核心成果就绪` })
        if (deliverables.status !== 'ready') addBlockingItem('正式交付物', '第一阶段正式交付物尚未完成编译。')
        if (missingArtifactIds.length) addBlockingItem('正式交付物', `缺少核心成果：${missingArtifactIds.join('、')}。`)
      }

      const evidenceTasks = this.getStage1VerificationTasks()
      const hardConstraintTasks = this.getStage1HardConstraintPendingActions()
      const tasks = [...evidenceTasks, ...hardConstraintTasks]
      const taskCounts = { agent: 0, manual_authority: 0, fieldwork: 0 }
      tasks.forEach((task) => {
        const executor = text(task?.executor)
        if (Object.hasOwn(taskCounts, executor)) taskCounts[executor] += 1
      })
      const hasReviewItems = checks.some(item => item.status !== 'passed') || tasks.length > 0
      const status = blockingItems.length ? 'blocked' : hasReviewItems ? 'review' : 'ready'
      const labels = { blocked: '质量门已阻断', review: '有条件通过', ready: '质量门通过' }
      const summaries = {
        blocked: `${blockingItems.length} 项问题必须修复后才能作为正式交付依据。`,
        review: `核心质量检查已通过，仍有 ${tasks.length} 项证据或硬约束核验任务需要纳入后续决策。`,
        ready: '证据、数据、来源与正式交付物满足当前 Stage 1 质量门。',
      }
      return { status, label: labels[status], summary: summaries[status], checks, blocking_items: blockingItems, task_counts: taskCounts, task_total: tasks.length }
    },
    getStage1VerificationTasks() {
      const tasks = (this.getStage1EvidenceVerification() || {}).tasks
      return Array.isArray(tasks) ? clonePayloadValue(tasks) : []
    },
    getStage1VerificationTaskExecutorLabel(task) {
      const labels = { agent: 'Agent 验证编排器', manual_authority: '项目方或主管部门', fieldwork: '现场调研负责人' }
      return text(task?.responsible_party) || labels[task?.executor] || '项目负责人'
    },
    getStage1QualityBlockingIssues() {
      const issues = (this.getStage1QualityAudit() || {}).issues
      return Array.isArray(issues)
        ? issues.filter(item => item && item.severity === 'error').map(item => ({ ...item }))
        : []
    },
  }
}
