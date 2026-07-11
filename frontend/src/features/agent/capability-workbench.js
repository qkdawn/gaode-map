import { buildAnalysisQuickAskSelectedSourcesContext } from './analysis-quick-request.js'

const CATALOG_URL = '/api/v1/analysis/agent/analysis-capabilities'
const RUNS_URL = '/api/v1/analysis/agent/analysis-capability-runs'

const text = value => String(value || '').trim()

const clonePayloadValue = value => {
  if (Array.isArray(value)) return value.map(clonePayloadValue)
  if (!value || typeof value !== 'object') return value
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, clonePayloadValue(item)]))
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
  'urban-strategy-stage1': '基于当前项目范围、资料和分析结果，执行城市更新第一阶段策划并生成可审计报告。',
  'spatial-programming-matrix': '基于当前项目证据，重点生成空间功能策划决策矩阵，并说明候选功能、排除理由和前置条件。',
  'evidence-audit': '审计当前项目分析的 Claim-Evidence 关系、代理指标边界、冲突与待验证事项。',
})

export function createAgentCapabilityWorkbenchMethods() {
  return {
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
      this.loadAgentCapabilities()
      this.loadAnalysisCapabilities().catch(() => {})
      this.loadAnalysisCapabilityRuns().catch(() => {})
    },
    async loadAnalysisCapabilityRuns({ force = false, capabilityId = '' } = {}) {
      const historyId = typeof this.getCurrentAgentHistoryId === 'function' ? text(this.getCurrentAgentHistoryId()) : ''
      const normalizedCapabilityId = text(capabilityId)
      if (!historyId) {
        this.analysisCapabilityRunsRequestToken = Number(this.analysisCapabilityRunsRequestToken || 0) + 1
        this.analysisCapabilityRuns = []
        this.analysisCapabilityRunsLoaded = false
        this.analysisCapabilityRunsHistoryId = ''
        this.analysisCapabilityRunsCapabilityId = normalizedCapabilityId
        this.analysisCapabilityRunsError = ''
        this.analysisCapabilityRunsLoading = false
        this.clearSelectedAnalysisCapabilityRun()
        return []
      }
      const sameQuery = this.analysisCapabilityRunsHistoryId === historyId
        && this.analysisCapabilityRunsCapabilityId === normalizedCapabilityId
      if (!force && sameQuery && this.analysisCapabilityRunsLoaded) return this.getAnalysisCapabilityRuns()
      if (!force && sameQuery && this.analysisCapabilityRunsLoading) return []

      const requestToken = Number(this.analysisCapabilityRunsRequestToken || 0) + 1
      this.analysisCapabilityRunsRequestToken = requestToken
      this.analysisCapabilityRunsLoading = true
      this.analysisCapabilityRunsLoaded = false
      this.analysisCapabilityRunsError = ''
      this.analysisCapabilityRuns = []
      this.analysisCapabilityRunsHistoryId = historyId
      this.analysisCapabilityRunsCapabilityId = normalizedCapabilityId
      this.clearSelectedAnalysisCapabilityRun()
      const query = new URLSearchParams({ history_id: historyId })
      if (normalizedCapabilityId) query.set('capability_id', normalizedCapabilityId)
      try {
        const response = await fetch(`${RUNS_URL}?${query.toString()}`)
        if (!response.ok) throw new Error(`运行版本请求失败(${response.status})`)
        const payload = await response.json()
        if (this.analysisCapabilityRunsRequestToken !== requestToken) return []
        this.analysisCapabilityRuns = Array.isArray(payload) ? clonePayloadValue(payload) : []
        this.analysisCapabilityRunsLoaded = true
        return this.getAnalysisCapabilityRuns()
      } catch (error) {
        if (this.analysisCapabilityRunsRequestToken !== requestToken) return []
        this.analysisCapabilityRunsError = error instanceof Error ? error.message : String(error)
        throw error
      } finally {
        if (this.analysisCapabilityRunsRequestToken === requestToken) this.analysisCapabilityRunsLoading = false
      }
    },
    getAnalysisCapabilityRuns() {
      return Array.isArray(this.analysisCapabilityRuns) ? clonePayloadValue(this.analysisCapabilityRuns) : []
    },
    async loadAnalysisCapabilityRunDetail(runId = '') {
      const normalizedRunId = text(runId)
      if (!normalizedRunId) return null
      const requestToken = Number(this.selectedAnalysisCapabilityRunRequestToken || 0) + 1
      this.selectedAnalysisCapabilityRunRequestToken = requestToken
      this.selectedAnalysisCapabilityRunId = normalizedRunId
      this.selectedAnalysisCapabilityRunDetail = null
      this.selectedAnalysisCapabilityRunLoading = true
      this.selectedAnalysisCapabilityRunError = ''
      try {
        const response = await fetch(`${RUNS_URL}/${encodeURIComponent(normalizedRunId)}`)
        if (!response.ok) throw new Error(`运行快照请求失败(${response.status})`)
        const detail = await response.json()
        if (this.selectedAnalysisCapabilityRunRequestToken !== requestToken) return null
        this.selectedAnalysisCapabilityRunDetail = detail && typeof detail === 'object' ? clonePayloadValue(detail) : null
        return this.getSelectedAnalysisCapabilityRunDetail()
      } catch (error) {
        if (this.selectedAnalysisCapabilityRunRequestToken !== requestToken) return null
        this.selectedAnalysisCapabilityRunError = error instanceof Error ? error.message : String(error)
        throw error
      } finally {
        if (this.selectedAnalysisCapabilityRunRequestToken === requestToken) this.selectedAnalysisCapabilityRunLoading = false
      }
    },
    selectAnalysisCapabilityRun(run = null) {
      const runId = text(run?.run_id)
      if (!runId) return Promise.resolve(null)
      if (runId === this.selectedAnalysisCapabilityRunId && this.selectedAnalysisCapabilityRunDetail) {
        return Promise.resolve(this.getSelectedAnalysisCapabilityRunDetail())
      }
      return this.loadAnalysisCapabilityRunDetail(runId)
    },
    clearSelectedAnalysisCapabilityRun() {
      this.selectedAnalysisCapabilityRunRequestToken = Number(this.selectedAnalysisCapabilityRunRequestToken || 0) + 1
      this.selectedAnalysisCapabilityRunId = ''
      this.selectedAnalysisCapabilityRunDetail = null
      this.selectedAnalysisCapabilityRunLoading = false
      this.selectedAnalysisCapabilityRunError = ''
    },
    getSelectedAnalysisCapabilityRun() {
      const runId = text(this.selectedAnalysisCapabilityRunId)
      return this.getAnalysisCapabilityRuns().find(run => text(run?.run_id) === runId) || null
    },
    getSelectedAnalysisCapabilityRunDetail() {
      const detail = this.selectedAnalysisCapabilityRunDetail
      return detail && typeof detail === 'object' ? clonePayloadValue(detail) : null
    },
    getSelectedAnalysisCapabilityRunArtifacts() {
      const artifacts = this.getSelectedAnalysisCapabilityRunDetail()?.artifacts
      return Array.isArray(artifacts) ? clonePayloadValue(artifacts) : []
    },
    getAnalysisCapabilityRunStatusLabel(run = null) {
      const labels = {
        draft: '草稿', checking_inputs: '检查输入', ready: '已就绪', queued: '排队中', running: '运行中',
        waiting_for_user: '等待补充', completed: '已完成', completed_with_warnings: '完成但有提示', failed: '运行失败',
        cancelled: '已取消', stale: '上游已更新',
      }
      return labels[run?.status] || text(run?.status) || '未记录'
    },
    getAnalysisCapabilityRunVersionLabel(run = null, index = 0) {
      const total = this.getAnalysisCapabilityRuns().length
      const ordinal = Math.max(total - Number(index || 0), 1)
      return `${index === 0 ? '最新' : '历史'} v${ordinal}`
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
    getAnalysisCapabilityRunChangedInputIds(run = null) {
      return Array.isArray(run?.stale_input_artifact_ids) ? run.stale_input_artifact_ids.map(text).filter(Boolean) : []
    },
    buildCapabilityRunContextAskTarget(detailSeed = null) {
      const selectedDetail = detailSeed && typeof detailSeed === 'object' && detailSeed.run
        ? clonePayloadValue(detailSeed)
        : null
      const run = selectedDetail?.run || this.getCapabilityRun()
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
      const staleInputs = this.getAnalysisCapabilityRunChangedInputIds(run)
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
        type: 'capability_run',
        id: text(run.run_id),
        title: `${capabilityLabel} · ${run.run_id}`,
        source: 'capability_run',
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
    openCapabilityRunContextAsk(detailSeed = null) {
      const target = this.buildCapabilityRunContextAskTarget(detailSeed)
      if (!target || typeof this.openContextAsk !== 'function') return null
      return this.openContextAsk(target, { resetMessages: true })
    },
    isAnalysisCapabilityRunSelected(run = null) {
      return !!text(run?.run_id) && text(run.run_id) === text(this.selectedAnalysisCapabilityRunId)
    },
    getAnalysisCapabilityGroups() {
      const labels = { planning: '策划决策', analysis: '空间分析', governance: '证据治理', delivery: '成果交付' }
      const groups = []
      for (const capability of this.analysisCapabilities || []) {
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
    getActiveAnalysisCapability() {
      return (this.analysisCapabilities || []).find(item => item.id === this.activeAnalysisCapabilityId) || null
    },
    getAnalysisCapabilityReadiness(capabilityId = '') {
      return (this.analysisCapabilityReadiness || {})[text(capabilityId)] || null
    },
    getAnalysisCapabilityReadinessError(capabilityId = '') {
      return (this.analysisCapabilityReadinessErrors || {})[text(capabilityId)] || ''
    },
    async inspectAnalysisCapability(capability = null) {
      const id = text(capability && capability.id)
      if (!id) return
      this.activeAnalysisCapabilityId = id
      const runsPromise = this.loadAnalysisCapabilityRuns({ capabilityId: id }).catch(() => [])
      this.analysisCapabilityReadinessLoading = true
      this.analysisCapabilityReadinessErrors = { ...this.analysisCapabilityReadinessErrors, [id]: '' }
      try {
        const response = await fetch(`${CATALOG_URL}/${encodeURIComponent(id)}/readiness`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            conversation_id: text(this.activeAgentSessionId),
            history_id: typeof this.getCurrentAgentHistoryId === 'function' ? text(this.getCurrentAgentHistoryId()) : '',
            messages: [{ role: 'user', content: CAPABILITY_PROMPTS[id] || capability.description || capability.display_name }],
            analysis_snapshot: typeof this.buildAgentAnalysisSnapshot === 'function' ? this.buildAgentAnalysisSnapshot() : {},
            selected_sources_context: buildAnalysisQuickAskSelectedSourcesContext(this),
          }),
        })
        if (!response.ok) throw new Error(`输入检查失败(${response.status})`)
        const readiness = await response.json()
        this.analysisCapabilityReadiness = { ...this.analysisCapabilityReadiness, [id]: readiness }
      } catch (error) {
        this.analysisCapabilityReadinessErrors = {
          ...this.analysisCapabilityReadinessErrors,
          [id]: error instanceof Error ? error.message : String(error),
        }
      } finally {
        this.analysisCapabilityReadinessLoading = false
      }
      await runsPromise
    },
    async runAnalysisCapability(capability = null) {
      if (!capability || capability.status !== 'available') return
      if (capability.executor_type === 'service' && capability.executor_id === 'ppt-planning') {
        this.openAgentPptPlanningFromReport()
        return
      }
      await this.loadAgentCapabilities()
      const skill = (this.agentSkills || []).find(item => item.id === capability.executor_id)
      if (!skill) {
        this.analysisCapabilitiesError = '该分析能力的 Skill 当前不可用，请刷新能力目录或检查 Skill 注册。'
        return
      }
      this.chooseAgentSkill(skill)
      this.agentWorkspaceView = 'report'
      await this.submitAgentComposer({ prompt: CAPABILITY_PROMPTS[capability.id] || capability.description })
      await this.loadAnalysisCapabilityRuns({ force: true, capabilityId: capability.id }).catch(() => {})
    },
    getCapabilityRun() {
      const run = (this.agentPanelPayloads || {}).capability_run
      return run && typeof run === 'object' ? clonePayloadValue(run) : null
    },
    getCapabilityRunStatusLabel() {
      return this.getAnalysisCapabilityRunStatusLabel(this.getCapabilityRun())
    },
    getCapabilityRunStages() {
      const records = this.getCapabilityRun()?.stage_records
      return Array.isArray(records) ? clonePayloadValue(records) : []
    },
    getCapabilityRunOutputArtifacts() {
      const artifacts = this.getCapabilityRun()?.output_artifact_refs
      return Array.isArray(artifacts) ? clonePayloadValue(artifacts) : []
    },
    getCapabilityRunArtifactTypeLabel(artifact) {
      const labels = {
        structured_data: '结构化数据',
        map_layer: '地图图层',
        table: '表格',
        chart: '图表',
        report: '报告',
        presentation: '演示文稿',
        evidence_ledger: '证据台账',
        design_handoff: '设计移交',
        export_file: '导出文件',
        diagnostic_report: '诊断记录',
      }
      return labels[artifact?.artifact_type] || text(artifact?.artifact_type) || '产物'
    },
    getCapabilityRunArtifactLineageText(artifact) {
      const upstream = Array.isArray(artifact?.source_artifact_refs) ? artifact.source_artifact_refs.length : 0
      const evidence = Array.isArray(artifact?.evidence_refs) ? artifact.evidence_refs.length : 0
      const parts = [`${upstream} 个上游`]
      if (evidence) parts.push(`${evidence} 条证据`)
      if (text(artifact?.content_digest)) parts.push(text(artifact.content_digest).slice(0, 18))
      return parts.join(' · ')
    },
    getCapabilityRunCurrentStageLabel() {
      return this.getAnalysisCapabilityRunCurrentStageLabel(this.getCapabilityRun())
    },
    getCapabilityRunModelLabel() {
      const profile = this.getCapabilityRun()?.execution_profile || {}
      return text(profile.model_display_name || profile.model || profile.model_profile_id) || '未锁定模型'
    },
    getCapabilityRunSkillLabel() {
      const profile = this.getCapabilityRun()?.execution_profile || {}
      return text(profile.skill_display_name || profile.skill_id) || '未锁定 Skill'
    },
    getCapabilityRunSourceCount() {
      return this.getCapabilityRun()?.input_artifact_refs?.length || 0
    },
    getStage1QualityAudit() {
      return (this.agentPanelPayloads || {}).stage1_quality_audit || null
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
      return !!(this.getCapabilityRun() || this.getStage1QualityAudit() || this.getStage1EvidenceVerification() || this.getStage1ProvenanceBinding() || this.getStage1DataQuality() || this.getStage1Deliverables())
    },
    getStage1EvidenceCount() {
      const ledger = (this.agentPanelPayloads || {}).stage1_evidence_ledger
      return Array.isArray(ledger) ? ledger.length : 0
    },
    getStage1SpatialMatrix() {
      const matrix = (this.agentPanelPayloads || {}).stage1_spatial_matrix
      return matrix && typeof matrix === 'object' ? clonePayloadValue(matrix) : null
    },
    getStage1SpaceDecisions() {
      const decisions = this.getStage1SpatialMatrix()?.space_decisions
      return Array.isArray(decisions) ? clonePayloadValue(decisions) : []
    },
    getStage1SpaceDecisionCount() {
      return this.getStage1SpaceDecisions().length
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
    getStage1VerificationTasks() {
      const tasks = (this.getStage1EvidenceVerification() || {}).tasks
      return Array.isArray(tasks) ? tasks.map(item => ({ ...item })) : []
    },
    getStage1QualityBlockingIssues() {
      const issues = (this.getStage1QualityAudit() || {}).issues
      return Array.isArray(issues)
        ? issues.filter(item => item && item.severity === 'error').map(item => ({ ...item }))
        : []
    },
  }
}
