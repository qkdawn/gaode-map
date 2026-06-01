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
import { createAgentTabsMethods } from './tabs.js'
import { createAgentSummaryViewMethods } from './summary-view.js'
import { createAgentBasisDrawerMethods } from './basis-drawer.js'
import { createAgentContextAskUiMethods } from './context-ask-ui.js'
import { createAgentSiteSelectionTabMethods } from './site-selection-tabs.js'
import { createAgentIterationChangeUiMethods } from './iteration-change-ui.js'
import { createAgentThreadUiMethods } from './thread-ui.js'

function createAgentUiMethods() {
  return {
    escapeAgentMessageHtml(value = '') {
      return asText(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')
    },
    renderAgentInlineMarkdown(value = '') {
      return this.escapeAgentMessageHtml(value)
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/`([^`]+)`/g, '<code>$1</code>')
    },
    renderAgentMessageHtml(message = {}) {
      const role = asText(message && message.role)
      const content = asText(message && message.content)
      if (!content) return ''
      if (role === 'user') {
        return this.escapeAgentMessageHtml(content).replace(/\n/g, '<br>')
      }
      const lines = content.replace(/\r\n/g, '\n').split('\n')
      const html = []
      for (const rawLine of lines) {
        const line = asText(rawLine).trim()
        if (!line) {
          html.push('<div class="agent-message-gap"></div>')
          continue
        }
        const heading = line.match(/^(#{1,4})\s+(.+)$/)
        if (heading) {
          html.push(`<div class="agent-message-heading">${this.renderAgentInlineMarkdown(heading[2])}</div>`)
          continue
        }
        const quote = line.match(/^>\s*(.+)$/)
        if (quote) {
          html.push(`<div class="agent-message-quote">${this.renderAgentInlineMarkdown(quote[1])}</div>`)
          continue
        }
        const bullet = line.match(/^[-*]\s+(.+)$/)
        if (bullet) {
          html.push(`<div class="agent-message-list-item"><span>•</span><span>${this.renderAgentInlineMarkdown(bullet[1])}</span></div>`)
          continue
        }
        html.push(`<div class="agent-message-paragraph">${this.renderAgentInlineMarkdown(line)}</div>`)
      }
      return html.join('')
    },
    renderAgentReportMarkdownHtml(value = '') {
      const content = asText(value).replace(/\r\n/g, '\n')
      if (!content) return ''
      const lines = content
        .split('\n')
        .filter((line) => !/^```(?:markdown|md)?\s*$/i.test(asText(line).trim()))
      const html = []
      let seenContent = false
      const hasStructuredLines = lines.some((line) => /^(\d+)[.、]\s+/.test(asText(line).trim()) || /^#{1,4}\s+/.test(asText(line).trim()))
      for (const rawLine of lines) {
        const line = asText(rawLine).trim()
        if (!line) {
          if (html.length) html.push('<div class="agent-iteration-report-gap"></div>')
          continue
        }
        const heading = line.match(/^(#{1,4})\s+(.+)$/)
        if (heading) {
          html.push(`<div class="agent-iteration-report-md-heading">${this.renderAgentInlineMarkdown(heading[2])}</div>`)
          seenContent = true
          continue
        }
        if (!seenContent && hasStructuredLines && line.length <= 40 && !/^(\d+)[.、]\s+/.test(line)) {
          html.push(`<div class="agent-iteration-report-md-heading">${this.renderAgentInlineMarkdown(line)}</div>`)
          seenContent = true
          continue
        }
        const numbered = line.match(/^(\d+)[.、]\s+(.+)$/)
        if (numbered) {
          html.push(`<div class="agent-iteration-report-md-list-item"><span>${this.escapeAgentMessageHtml(numbered[1])}.</span><span>${this.renderAgentInlineMarkdown(numbered[2])}</span></div>`)
          seenContent = true
          continue
        }
        const bullet = line.match(/^[-*]\s+(.+)$/)
        if (bullet) {
          html.push(`<div class="agent-iteration-report-md-list-item"><span>•</span><span>${this.renderAgentInlineMarkdown(bullet[1])}</span></div>`)
          seenContent = true
          continue
        }
        html.push(`<div class="agent-iteration-report-md-paragraph">${this.renderAgentInlineMarkdown(line)}</div>`)
        seenContent = true
      }
      return html.join('')
    },
    ...createAgentTabsMethods(),
    ...createAgentSummaryViewMethods(),
    ...createAgentBasisDrawerMethods(),
    ...createAgentContextAskUiMethods(),
    ...createAgentSiteSelectionTabMethods(),
    ...createAgentIterationChangeUiMethods(),
    ...createAgentThreadUiMethods(),
  }
}

export { createAgentUiMethods }
