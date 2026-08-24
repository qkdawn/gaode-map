import {
  asText,
  clampText,
  cloneArray,
  cloneObject,
} from './normalizers.js'

function serializeContextAskTarget(target = {}) {
  const source = target && typeof target === 'object' ? target : {}
  return {
    type: asText(source.type) || 'report_section',
    id: asText(source.id),
    title: asText(source.title),
    source: asText(source.source) || 'report',
    summary: asText(source.summary),
    evidence: cloneArray(source.evidence),
    artifact_refs: cloneArray(source.artifact_refs).map((item) => asText(item)).filter(Boolean),
    payload: cloneObject(source.payload),
  }
}

export function createAgentContextAskUiMethods() {
  return {
    normalizeContextAskTarget(target = null) {
      const source = target && typeof target === 'object' ? target : {}
      const allowedTypes = new Set(['report_section', 'trend_chart', 'trend_metric', 'site_candidate', 'analysis_run'])
      const allowedSources = new Set(['report', 'iteration', 'site_selection', 'analysis_run'])
      const type = allowedTypes.has(asText(source.type)) ? asText(source.type) : 'report_section'
      const targetSource = allowedSources.has(asText(source.source)) ? asText(source.source) : 'report'
      const title = clampText(asText(source.title), 80) || '当前上下文'
      const evidence = cloneArray(source.evidence || source.evidence_refs || source.evidenceRefs)
        .map((item) => (item && typeof item === 'object' ? cloneObject(item) : asText(item)))
        .filter((item) => (typeof item === 'object' ? Object.keys(item).length : !!item))
      const artifactRefs = cloneArray(source.artifact_refs)
        .map((item) => asText(item))
        .filter(Boolean)
      return {
        type,
        id: asText(source.id || source.key) || `${type}-${Date.now().toString(36)}`,
        title,
        source: targetSource,
        summary: clampText(asText(source.summary || source.reasoning || source.content || source.value), 800),
        evidence,
        artifact_refs: artifactRefs,
        payload: cloneObject(source.payload),
      }
    },
    getContextAskSourceLabel(source = '') {
      const labels = {
        report: '区域报告',
        iteration: '多年变化',
        site_selection: '区域内选址',
        analysis_run: '能力运行版本',
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
          content: `我会在当前 Codex 会话中围绕“${normalized.title}”继续分析。`,
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
        const data = await this.submitMainAgentTurn({
          prompt: text,
          panelKind: 'analysis',
          mapContext: {
            context_target: serializeContextAskTarget(target),
          },
        })
        if (!data || !asText(data.answer)) {
          throw new Error(asText(this.agentError) || 'App Server 未返回结果')
        }
        const assistant = {
          role: 'assistant',
          content: asText(data.answer),
          evidence: [],
          citations: [],
          warnings: [],
        }
        this.contextAskMessages = [...cloneArray(this.contextAskMessages), assistant]
        return assistant
      } catch (error) {
        const message = `Codex 追问失败：${asText(error && error.message) || 'App Server 未返回结果'}`
        const assistant = {
          role: 'assistant',
          content: message,
          evidence: [],
          citations: [],
          warnings: [],
        }
        this.contextAskMessages = [...cloneArray(this.contextAskMessages), assistant]
        this.contextAskError = message
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
        artifact_refs: cloneArray(source.artifact_refs || basis.evidenceRefs),
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
        artifact_refs: cloneArray(source.artifact_refs),
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
      return this.normalizeContextAskTarget({
        type: 'site_candidate',
        id: asText(source.h3Id || source.h3_id || source.title) || 'site-candidate',
        title: asText(source.title) || `候选 ${source.sourceOrder || ''}`.trim() || '候选点',
        source: 'site_selection',
        summary: `供需差值 ${Number(source.gapValue || 0)}，需求份额 ${Number(source.demandShare || 0)}，供给份额 ${Number(source.supplyShare || 0)}`,
        evidence: [],
        artifact_refs: [asText(source.h3Id || source.h3_id)].filter(Boolean),
        payload: {
          sourceOrder: Number(source.sourceOrder || 0) || 0,
          h3Id: asText(source.h3Id || source.h3_id),
          gapValue: Number(source.gapValue || 0) || 0,
          demandShare: Number(source.demandShare || 0) || 0,
          supplyShare: Number(source.supplyShare || 0) || 0,
          cellPopulation: Number(source.cellPopulation || 0) || 0,
          scopePopulation: Number(source.scopePopulation || 0) || 0,
          roadNodeCount: Number(source.roadNodeCount || 0) || 0,
          roadEdgeCount: Number(source.roadEdgeCount || 0) || 0,
        },
      })
    },
  }
}
