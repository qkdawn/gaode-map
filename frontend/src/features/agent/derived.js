import {
  asText,
  cloneArray,
  cloneObject,
  normalizeAgentPlanEnvelope,
  normalizeAgentProducedArtifacts,
} from './normalizers.js'

function getAgentPlanTraceStatus(seed = {}) {
  const status = asText(seed.status)
  if (status === 'success') return 'completed'
  if (status === 'failed') return 'failed'
  if (status === 'blocked') return 'blocked'
  if (status === 'skipped') return 'skipped'
  if (status === 'start') return 'active'
  return 'pending'
}

function summarizeAgentPlan(plan = {}, diagnostics = {}) {
  const baseSummary = asText(plan.summary || diagnostics.planningSummary || diagnostics.planning_summary)
  if (plan.followupApplied && cloneArray(plan.followupSteps).length) {
    return baseSummary ? `${baseSummary} 已根据审计补充步骤。` : '已根据审计补充步骤。'
  }
  return baseSummary
}

function buildAgentPlanChecklist(plan = {}, executionTrace = [], options = {}) {
  const normalizedPlan = normalizeAgentPlanEnvelope(plan)
  const traces = cloneArray(executionTrace)
  const groups = [
    { key: 'initial', title: '初始计划', description: 'AI 生成的首轮分析步骤', items: normalizedPlan.steps },
    { key: 'followup', title: '补充计划', description: '审计后补充的步骤', items: normalizedPlan.followupSteps },
  ].filter((group) => group.items.length)
  const allSteps = groups.flatMap((group) => group.items)
  const totalCount = allSteps.length
  if (!totalCount) {
    return {
      visible: false,
      summary: summarizeAgentPlan(normalizedPlan, options.diagnostics),
      progressLabel: '',
      completedCount: 0,
      totalCount: 0,
      followupApplied: normalizedPlan.followupApplied,
      groups: [],
    }
  }

  let traceCursor = 0
  let firstPendingAssigned = false
  const isExecuting = !!options.isLoading && ['planning', 'executing', 'auditing', 'replanning', 'synthesizing'].includes(asText(options.stage))
  const normalizedGroups = groups.map((group) => ({
    ...group,
    items: group.items.map((step) => {
      const toolName = asText(step.tool_name || step.toolName)
      let matchedTrace = null
      for (let index = traceCursor; index < traces.length; index += 1) {
        const traceToolName = asText(traces[index] && (traces[index].tool_name || traces[index].toolName))
        if (traceToolName === toolName) {
          matchedTrace = traces[index]
          while (index + 1 < traces.length) {
            const nextTraceToolName = asText(traces[index + 1] && (traces[index + 1].tool_name || traces[index + 1].toolName))
            if (nextTraceToolName !== toolName) break
            index += 1
            matchedTrace = traces[index]
          }
          traceCursor = index + 1
          break
        }
      }

      let status = matchedTrace ? getAgentPlanTraceStatus(matchedTrace) : 'pending'
      if (!matchedTrace && isExecuting && !firstPendingAssigned) {
        status = 'active'
        firstPendingAssigned = true
      } else if (status !== 'pending') {
        firstPendingAssigned = true
      }

      return {
        ...step,
        title: asText(step.reason) || toolName,
        detail: asText(step.evidence_goal || step.evidenceGoal),
        status,
        toolName,
      }
    }),
  }))

  const completedCount = normalizedGroups.reduce(
    (sum, group) => sum + group.items.filter((item) => item.status === 'completed').length,
    0,
  )

  return {
    visible: true,
    summary: summarizeAgentPlan(normalizedPlan, options.diagnostics),
    progressLabel: `${completedCount}/${totalCount} 已完成`,
    completedCount,
    totalCount,
    followupApplied: normalizedPlan.followupApplied,
    groups: normalizedGroups,
  }
}

function hasAgentPlanContent(plan = {}) {
  const normalizedPlan = normalizeAgentPlanEnvelope(plan || {})
  return !!(normalizedPlan.steps.length || normalizedPlan.followupSteps.length)
}

function hasAgentExecutionTraceContent(executionTrace = []) {
  return cloneArray(executionTrace).length > 0
}

function shouldExpandAgentProcessSection(status = '', options = {}) {
  const normalizedStatus = asText(status)
  const hasContent = !!options.hasContent
  if (!hasContent) return false
  if (options.isLoading) return true
  return ['running', 'requires_risk_confirmation'].includes(normalizedStatus)
}

function shouldShowAgentProcessToggle(status = '', options = {}) {
  return !!options.hasContent && !options.isLoading
}

function shouldShowAgentProcessLiveStatus(status = '', options = {}) {
  return !!options.hasContent && !!options.isLoading
}

function buildAgentToolCallItems(executionTrace = []) {
  return cloneArray(executionTrace)
    .map((item, index) => {
      const normalized = cloneObject(item)
      const toolName = asText(normalized.tool_name || normalized.toolName) || `tool_call_${index + 1}`
      const status = asText(normalized.status || 'start') || 'start'
      const statusTone = {
        start: 'active',
        success: 'success',
        failed: 'failed',
        blocked: 'blocked',
        skipped: 'skipped',
      }[status] || 'active'
      return {
        id: asText(normalized.id || normalized.call_id || normalized.callId) || `${toolName}-${index}`,
        toolName,
        status,
        statusTone,
        message: asText(normalized.message),
        reason: asText(normalized.reason),
        argumentsSummary: asText(normalized.arguments_summary || normalized.argumentsSummary),
        resultSummary: asText(normalized.result_summary || normalized.resultSummary),
        evidenceCount: normalized.evidence_count ?? normalized.evidenceCount,
        warningCount: normalized.warning_count ?? normalized.warningCount,
        producedArtifacts: normalizeAgentProducedArtifacts(normalized),
      }
    })
    .filter((item) => item.toolName)
}

export {
  getAgentPlanTraceStatus,
  summarizeAgentPlan,
  buildAgentPlanChecklist,
  hasAgentPlanContent,
  hasAgentExecutionTraceContent,
  shouldExpandAgentProcessSection,
  shouldShowAgentProcessToggle,
  shouldShowAgentProcessLiveStatus,
  buildAgentToolCallItems,
}
