import { buildAnalysisQuickAskSelectedSourcesContext } from './analysis-quick-request.js'

const CATALOG_URL = '/api/v1/analysis/agent/analysis-capabilities'

const text = value => String(value || '').trim()

const clonePayloadValue = value => {
  if (Array.isArray(value)) return value.map(clonePayloadValue)
  if (!value || typeof value !== 'object') return value
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, clonePayloadValue(item)]))
}

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
    },
    getStage1QualityAudit() {
      return (this.agentPanelPayloads || {}).stage1_quality_audit || null
    },
    getStage1EvidenceVerification() {
      return (this.agentPanelPayloads || {}).stage1_evidence_verification || null
    },
    hasStage1Outcome() {
      return !!(this.getStage1QualityAudit() || this.getStage1EvidenceVerification())
    },
    getStage1EvidenceCount() {
      const ledger = (this.agentPanelPayloads || {}).stage1_evidence_ledger
      return Array.isArray(ledger) ? ledger.length : 0
    },
    getStage1SpaceDecisionCount() {
      const matrix = (this.agentPanelPayloads || {}).stage1_spatial_matrix || {}
      return Array.isArray(matrix.space_decisions) ? matrix.space_decisions.length : 0
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
