import {
  asText,
  clampText,
  cloneArray,
  cloneObject,
} from './normalizers.js'
import { postContextAsk } from './context-ask-request.js'

export function createAgentContextAskUiMethods() {
  return {
    normalizeContextAskTarget(target = null) {
      const source = target && typeof target === 'object' ? target : {}
      const allowedTypes = new Set(['report_section', 'trend_chart', 'trend_metric', 'site_candidate'])
      const allowedSources = new Set(['report', 'iteration', 'site_selection'])
      const type = allowedTypes.has(asText(source.type)) ? asText(source.type) : 'report_section'
      const targetSource = allowedSources.has(asText(source.source)) ? asText(source.source) : 'report'
      const title = clampText(asText(source.title), 80) || '当前上下文'
      const evidence = cloneArray(source.evidence || source.evidence_refs || source.evidenceRefs)
        .map((item) => (item && typeof item === 'object' ? cloneObject(item) : asText(item)))
        .filter((item) => (typeof item === 'object' ? Object.keys(item).length : !!item))
      const artifactRefs = cloneArray(source.artifactRefs || source.artifact_refs)
        .map((item) => asText(item))
        .filter(Boolean)
      return {
        type,
        id: asText(source.id || source.key) || `${type}-${Date.now().toString(36)}`,
        title,
        source: targetSource,
        summary: clampText(asText(source.summary || source.reasoning || source.content || source.value), 800),
        evidence,
        artifactRefs,
        payload: cloneObject(source.payload),
      }
    },
    getContextAskSourceLabel(source = '') {
      const labels = {
        report: '区域报告',
        iteration: '多年变化',
        site_selection: '区域内选址',
      }
      return labels[asText(source)] || '当前分析'
    },
    getContextAskQuickQuestions() {
      return ['为什么这么判断？', '用了哪些证据？', '这个结论可靠吗？']
    },
    openContextAsk(target = null, options = {}) {
      const normalized = this.normalizeContextAskTarget(target)
      this.contextAskTarget = normalized
      this.contextAskVisible = true
      this.contextAskMinimized = !!options.minimized
      this.contextAskError = ''
      this.contextAskDraft = asText(options.question)
      if (!Array.isArray(this.contextAskMessages) || options.resetMessages) {
        this.contextAskMessages = []
      }
      if (!this.contextAskMessages.length || options.resetMessages) {
        this.contextAskMessages = [{
          role: 'assistant',
          content: `我会围绕“${normalized.title}”解释，不会离开当前区域上下文。`,
          evidence: [],
          citations: [],
          warnings: [],
        }]
      }
      return normalized
    },
    closeContextAsk() {
      this.contextAskVisible = false
      this.contextAskMinimized = false
      this.contextAskLoading = false
      this.contextAskError = ''
      this.contextAskDraft = ''
    },
    minimizeContextAsk() {
      this.contextAskMinimized = !this.contextAskMinimized
      this.contextAskVisible = true
    },
    resizeContextAsk(size = {}) {
      const current = this.contextAskSize && typeof this.contextAskSize === 'object'
        ? this.contextAskSize
        : { width: 420, height: 560 }
      const width = Math.min(720, Math.max(320, Number(size.width || current.width || 420)))
      const height = Math.min(760, Math.max(220, Number(size.height || current.height || 560)))
      this.contextAskSize = { width, height }
      return this.contextAskSize
    },
    buildContextAskFallbackAnswer(question = '', targetSeed = null) {
      const target = this.normalizeContextAskTarget(targetSeed || this.contextAskTarget)
      const summary = asText(target.summary) || '当前对象没有完整自然语言摘要，需要结合右侧证据和图表继续核对。'
      const evidenceCount = cloneArray(target.evidence).length
      const refsCount = cloneArray(target.artifactRefs).length
      const basis = evidenceCount ? `已有 ${evidenceCount} 条证据可参考` : '当前上下文没有传入结构化证据'
      const refs = refsCount ? `，并关联 ${refsCount} 个产物引用` : ''
      return [
        `针对“${target.title}”：${summary}`,
        `你的问题是“${asText(question) || '请解释这个判断'}”。${basis}${refs}。`,
        '不确定性：这个回答只解释当前点击对象，不会重新跑工具；如果原始数据缺失或证据链较弱，需要回到报告证据抽屉复核。',
      ].join('\n')
    },
    async submitContextAskQuestion(question = '') {
      const text = asText(question || this.contextAskDraft).trim()
      if (!text || this.contextAskLoading) return null
      const target = this.normalizeContextAskTarget(this.contextAskTarget)
      this.contextAskVisible = true
      this.contextAskMinimized = false
      this.contextAskDraft = ''
      this.contextAskError = ''
      this.contextAskMessages = [
        ...cloneArray(this.contextAskMessages),
        { role: 'user', content: text },
      ]
      this.contextAskLoading = true
      try {
        const data = await postContextAsk({
          conversation_id: this.getActiveAgentSessionId ? this.getActiveAgentSessionId() : asText(this.activeAgentSessionId),
          history_id: asText(this.getCurrentAgentHistoryId && this.getCurrentAgentHistoryId()),
          question: text,
          analysis_snapshot: this.buildAgentAnalysisSnapshot ? this.buildAgentAnalysisSnapshot() : {},
          target: {
            ...target,
            artifact_refs: cloneArray(target.artifactRefs),
          },
        })
        const assistant = {
          role: 'assistant',
          content: asText(data.answer) || this.buildContextAskFallbackAnswer(text, target),
          evidence: cloneArray(data.evidence),
          citations: cloneArray(data.citations),
          warnings: cloneArray(data.warnings),
        }
        this.contextAskMessages = [...cloneArray(this.contextAskMessages), assistant]
        return assistant
      } catch (error) {
        const assistant = {
          role: 'assistant',
          content: this.buildContextAskFallbackAnswer(text, target),
          evidence: cloneArray(target.evidence),
          citations: cloneArray(target.artifactRefs),
          warnings: ['AI 解释接口暂不可用，已返回本地规则解释。'],
        }
        this.contextAskMessages = [...cloneArray(this.contextAskMessages), assistant]
        this.contextAskError = asText(error && error.message)
        return assistant
      } finally {
        this.contextAskLoading = false
      }
    },
    buildReportSectionContextAskTarget(seed = {}) {
      const source = seed && typeof seed === 'object' ? seed : { summary: asText(seed) }
      const sectionKey = asText(source.sectionKey || source.section_key || source.id || source.key) || 'report-section'
      const basis = this.buildAgentSummaryBasisPayload
        ? this.buildAgentSummaryBasisPayload({
          sectionKey,
          title: asText(source.title) || '区域报告',
          reasoning: asText(source.reasoning || source.summary || source.content || source.value),
        })
        : {}
      return this.normalizeContextAskTarget({
        type: 'report_section',
        id: sectionKey,
        title: asText(source.title) || asText(basis.title) || '区域报告',
        source: 'report',
        summary: asText(source.summary || source.reasoning || source.content || source.value || basis.currentConclusion),
        evidence: cloneArray(source.evidence || basis.fields),
        artifactRefs: cloneArray(source.artifactRefs || source.artifact_refs || basis.evidenceRefs),
        payload: {
          section_key: sectionKey,
          dimensions: cloneArray(source.dimensions),
          basis,
        },
      })
    },
    buildIterationContextAskTarget(seed = {}) {
      const source = seed && typeof seed === 'object' ? seed : { summary: asText(seed) }
      const kind = asText(source.kind || this.agentIterationActiveKind) || 'poi'
      const section = asText(source.section || source.id || source.key) || kind
      const payload = source.payload && typeof source.payload === 'object'
        ? cloneObject(source.payload)
        : this.getAgentIterationPayload(kind)
      return this.normalizeContextAskTarget({
        type: asText(source.type) || 'trend_metric',
        id: `${kind}-${section}`,
        title: asText(source.title) || this.getAgentIterationActiveDescription(),
        source: 'iteration',
        summary: asText(source.summary || source.value || payload.notice || payload.report_title),
        evidence: cloneArray(source.evidence || source.rows || payload.report_sections || payload.ai_summary),
        artifactRefs: cloneArray(source.artifactRefs || source.artifact_refs),
        payload: {
          kind,
          section,
          row: cloneObject(source.row),
          payload,
        },
      })
    },
    buildSiteCandidateContextAskTarget(candidate = null) {
      const source = candidate && typeof candidate === 'object'
        ? candidate
        : (this.getAgentSiteSelectionSelectedCandidate ? this.getAgentSiteSelectionSelectedCandidate() : {})
      const evidenceChain = this.getAgentSiteSelectionEvidenceChain ? this.getAgentSiteSelectionEvidenceChain() : []
      return this.normalizeContextAskTarget({
        type: 'site_candidate',
        id: asText(source.h3Id || source.h3_id || source.title) || 'site-candidate',
        title: asText(source.title) || `候选 ${source.rank || ''}`.trim() || '候选点',
        source: 'site_selection',
        summary: asText(source.reason) || cloneArray(source.whySuitable).join('；') || cloneArray(source.strengths).join('；'),
        evidence: evidenceChain,
        artifactRefs: [asText(source.h3Id || source.h3_id)].filter(Boolean),
        payload: {
          rank: Number(source.rank || 0) || 0,
          h3Id: asText(source.h3Id || source.h3_id),
          score: Number(source.totalScore || source.total_score || 0) || 0,
          reason: asText(source.reason),
          strengths: cloneArray(source.strengths).map((item) => asText(item)).filter(Boolean),
          risks: cloneArray(source.risks).map((item) => asText(item)).filter(Boolean),
          whySuitable: cloneArray(source.whySuitable || source.why_suitable).map((item) => asText(item)).filter(Boolean),
          validationSteps: cloneArray(source.nextValidationSteps || source.next_validation_steps).map((item) => asText(item)).filter(Boolean),
          evidence_chain: evidenceChain,
        },
      })
    },
  }
}
