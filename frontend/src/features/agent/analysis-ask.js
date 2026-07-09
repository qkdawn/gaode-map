import { asText, cloneArray } from './normalizers.js'
import { ANALYSIS_WORKSPACE_TAB_KIND } from './workspace-kinds.js'
import { postContextAsk } from './context-ask-request.js'
import { buildAnalysisSourceTarget } from '../analysis-sources/target.js'

function writeAnalysisAskSessionState(ctx, patch = {}, options = {}) {
  if (!ctx.activeAgentSessionId || typeof ctx.updateAgentSessionSnapshot !== 'function') return
  ctx.updateAgentSessionSnapshot(ctx.activeAgentSessionId, (session) => ({
    ...session,
    panelKind: ANALYSIS_WORKSPACE_TAB_KIND,
    status: asText(patch.status || session.status || 'idle'),
    stage: asText(patch.stage || session.stage || 'answered'),
    answer: Object.prototype.hasOwnProperty.call(patch, 'answer') ? asText(patch.answer) : session.answer,
    input: '',
    messages: cloneArray(patch.messages || ctx.agentMessages),
    executionTrace: [],
    usedTools: [],
    citations: [],
    researchNotes: [],
    auditIssues: [],
    thinkingTimeline: [],
    plan: { steps: [], summary: '' },
    pendingTaskConfirmation: null,
    error: asText(patch.error || ''),
  }), options)
}

export function createAgentAnalysisAskMethods() {
  return {
    buildAgentAnalysisSourceTarget() {
      const state = typeof this.getAgentAnalysisSourceState === 'function'
        ? this.getAgentAnalysisSourceState()
        : {}
      return buildAnalysisSourceTarget(state)
    },
    buildAgentAnalysisQuickAskRequest(question = '') {
      const target = this.buildAgentAnalysisSourceTarget()
      if (!cloneArray(target.payload && target.payload.sources).length) return null
      return {
        conversation_id: this.getActiveAgentSessionId ? this.getActiveAgentSessionId() : asText(this.activeAgentSessionId),
        history_id: asText(this.getCurrentAgentHistoryId && this.getCurrentAgentHistoryId()),
        question: asText(question),
        analysis_snapshot: this.buildAgentAnalysisSnapshot ? this.buildAgentAnalysisSnapshot() : {},
        target: {
          ...target,
          artifact_refs: cloneArray(target.artifactRefs),
        },
        require_ai: true,
      }
    },
    appendAgentAnalysisQuickAskMessage(message = {}) {
      this.agentMessages = [...cloneArray(this.agentMessages), {
        role: asText(message.role) || 'assistant',
        content: String(message.content || ''),
      }]
      writeAnalysisAskSessionState(this, {
        status: asText(message.status || 'idle'),
        stage: asText(message.stage || 'answered'),
        messages: this.agentMessages,
        error: asText(message.error || ''),
      }, { syncActive: true })
    },
    replaceAgentAnalysisQuickAskPendingMessage(content = '', options = {}) {
      const messages = cloneArray(this.agentMessages)
      const pendingId = asText(options.pendingId) || 'analysis-quick-ask-pending'
      const pendingIndex = messages.findIndex((item) => asText(item && item.id) === pendingId)
      const nextMessage = {
        role: 'assistant',
        content: asText(content),
      }
      if (pendingIndex >= 0) {
        messages.splice(pendingIndex, 1, nextMessage)
      } else {
        messages.push(nextMessage)
      }
      this.agentMessages = messages
      writeAnalysisAskSessionState(this, {
        status: options.failed ? 'failed' : 'answered',
        stage: options.failed ? 'failed' : 'answered',
        answer: options.failed ? '' : asText(content),
        messages,
        error: options.failed ? asText(content) : '',
      }, { syncActive: true })
    },
    stopAgentAnalysisQuickAskPendingMessage(pendingId = '') {
      const id = asText(pendingId)
      if (!id) return
      const messages = cloneArray(this.agentMessages)
      const pendingIndex = messages.findIndex((item) => asText(item && item.id) === id)
      if (pendingIndex < 0) return
      messages.splice(pendingIndex, 1, {
        role: 'assistant',
        content: '上一条问题已停止，正在处理新的问题。',
      })
      this.agentMessages = messages
      writeAnalysisAskSessionState(this, {
        status: 'running',
        stage: 'answered',
        messages,
        error: '',
      }, { syncActive: true })
    },
    async submitAgentAnalysisQuickAsk(options = {}) {
      const text = asText((options && options.prompt) || this.agentInput)
      if (!text || this.agentSessionHydrating) return null
      if (this.agentAnalysisQuickAskAbortController) {
        try {
          this.agentAnalysisQuickAskAbortController.abort()
        } catch (_) {}
      }
      this.stopAgentAnalysisQuickAskPendingMessage(this.agentAnalysisQuickAskPendingId)
      const requestId = Number(this.agentAnalysisQuickAskRequestId || 0) + 1
      const pendingId = `analysis-quick-ask-pending-${requestId}`
      const controller = typeof AbortController !== 'undefined' ? new AbortController() : null
      this.agentAnalysisQuickAskRequestId = requestId
      this.agentAnalysisQuickAskAbortController = controller
      this.agentAnalysisQuickAskPendingId = pendingId
      const request = this.buildAgentAnalysisQuickAskRequest(text)
      this.agentInput = ''
      this.agentError = ''
      this.appendAgentAnalysisQuickAskMessage({ role: 'user', content: text, status: 'running', stage: 'answered' })
      if (!request) {
        this.appendAgentAnalysisQuickAskMessage({ role: 'assistant', content: '请先勾选可用于 AI 的来源', status: 'failed', stage: 'failed', error: 'no_analysis_ai_sources' })
        if (this.agentAnalysisQuickAskAbortController === controller) this.agentAnalysisQuickAskAbortController = null
        return null
      }
      this.agentMessages = [...cloneArray(this.agentMessages), {
        id: pendingId,
        role: 'assistant',
        content: 'AI 正在读取已选来源...',
      }]
      writeAnalysisAskSessionState(this, {
        status: 'running',
        stage: 'answered',
        messages: this.agentMessages,
        error: '',
      }, { syncActive: true })
      try {
        const data = await postContextAsk(request, { signal: controller ? controller.signal : undefined })
        if (requestId !== Number(this.agentAnalysisQuickAskRequestId || 0)) return null
        const answer = asText(data.answer)
        if (!answer) throw new Error('ai_invalid_response')
        this.replaceAgentAnalysisQuickAskPendingMessage(answer, { pendingId })
        return { role: 'assistant', content: answer, evidence: cloneArray(data.evidence), citations: cloneArray(data.citations), warnings: cloneArray(data.warnings) }
      } catch (error) {
        if (error && (error.name === 'AbortError' || String(error.message || '').toLowerCase().includes('aborted'))) {
          return null
        }
        if (requestId !== Number(this.agentAnalysisQuickAskRequestId || 0)) return null
        const message = `快速分析失败：${asText(error && error.message) || 'AI 不可用'}`
        this.replaceAgentAnalysisQuickAskPendingMessage(message, { failed: true, pendingId })
        return null
      } finally {
        if (this.agentAnalysisQuickAskAbortController === controller) {
          this.agentAnalysisQuickAskAbortController = null
          this.agentAnalysisQuickAskPendingId = ''
        }
      }
    },
  }
}
