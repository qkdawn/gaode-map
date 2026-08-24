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
import { createAgentTabsMethods } from './tabs.js'
import { createAgentSummaryViewMethods } from './summary-view.js'
import { createAgentBasisDrawerMethods } from './basis-drawer.js'
import { createAgentContextAskUiMethods } from './context-ask-ui.js'
import { createAgentSiteSelectionTabMethods } from './site-selection-tabs.js'
import { createAgentIterationChangeUiMethods } from './iteration-change-ui.js'
import { createAgentThreadUiMethods } from './thread-ui.js'
import { createAgentCapabilityWorkbenchMethods } from './capability-workbench.js'

function createAgentUiMethods() {
  return {
    resizeAgentComposerInput(event) {
      const input = event && event.target
      if (!input || !input.style || typeof input.scrollHeight !== 'number') return
      const maxHeight = 240
      input.style.height = 'auto'
      input.style.height = `${Math.min(Math.max(input.scrollHeight, 48), maxHeight)}px`
      input.style.overflowY = input.scrollHeight > maxHeight ? 'auto' : 'hidden'
    },
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
    splitAgentMarkdownTableRow(value = '') {
      const line = asText(value).trim()
      if (!line.includes('|')) return []
      const inner = line.replace(/^\|/, '').replace(/\|$/, '')
      return inner.split('|').map((cell) => asText(cell).trim())
    },
    isAgentMarkdownTableSeparator(value = '', columnCount = 0) {
      const cells = this.splitAgentMarkdownTableRow(value)
      if (!cells.length || (columnCount && cells.length !== columnCount)) return false
      return cells.every((cell) => /^:?-{3,}:?$/.test(cell.replace(/\s+/g, '')))
    },
    renderAgentMarkdownTable(headerCells = [], bodyRows = [], className = 'agent-message-table') {
      const headerHtml = headerCells
        .map((cell) => `<th>${this.renderAgentInlineMarkdown(cell)}</th>`)
        .join('')
      const bodyHtml = bodyRows
        .map((row) => `<tr>${row.map((cell) => `<td>${this.renderAgentInlineMarkdown(cell)}</td>`).join('')}</tr>`)
        .join('')
      return `<div class="${className}-wrap"><table class="${className}"><thead><tr>${headerHtml}</tr></thead><tbody>${bodyHtml}</tbody></table></div>`
    },
    readAgentMarkdownTable(lines = [], startIndex = 0, className = 'agent-message-table') {
      const headerCells = this.splitAgentMarkdownTableRow(lines[startIndex])
      if (!headerCells.length || !this.isAgentMarkdownTableSeparator(lines[startIndex + 1], headerCells.length)) return null
      const bodyRows = []
      let index = startIndex + 2
      while (index < lines.length) {
        const line = asText(lines[index]).trim()
        if (!line || !line.includes('|')) break
        const cells = this.splitAgentMarkdownTableRow(line)
        if (cells.length !== headerCells.length) break
        bodyRows.push(cells)
        index += 1
      }
      if (!bodyRows.length) return null
      return {
        html: this.renderAgentMarkdownTable(headerCells, bodyRows, className),
        nextIndex: index,
      }
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
      for (let index = 0; index < lines.length;) {
        const rawLine = lines[index]
        const line = asText(rawLine).trim()
        if (!line) {
          html.push('<div class="agent-message-gap"></div>')
          index += 1
          continue
        }
        const table = this.readAgentMarkdownTable(lines, index, 'agent-message-table')
        if (table) {
          html.push(table.html)
          index = table.nextIndex
          continue
        }
        const heading = line.match(/^(#{1,4})\s+(.+)$/)
        if (heading) {
          html.push(`<div class="agent-message-heading">${this.renderAgentInlineMarkdown(heading[2])}</div>`)
          index += 1
          continue
        }
        const quote = line.match(/^>\s*(.+)$/)
        if (quote) {
          html.push(`<div class="agent-message-quote">${this.renderAgentInlineMarkdown(quote[1])}</div>`)
          index += 1
          continue
        }
        const bullet = line.match(/^[-*]\s+(.+)$/)
        if (bullet) {
          html.push(`<div class="agent-message-list-item"><span>•</span><span>${this.renderAgentInlineMarkdown(bullet[1])}</span></div>`)
          index += 1
          continue
        }
        html.push(`<div class="agent-message-paragraph">${this.renderAgentInlineMarkdown(line)}</div>`)
        index += 1
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
      for (let index = 0; index < lines.length;) {
        const rawLine = lines[index]
        const line = asText(rawLine).trim()
        if (!line) {
          if (html.length) html.push('<div class="agent-iteration-report-gap"></div>')
          index += 1
          continue
        }
        const table = this.readAgentMarkdownTable(lines, index, 'agent-iteration-report-md-table')
        if (table) {
          html.push(table.html)
          seenContent = true
          index = table.nextIndex
          continue
        }
        const heading = line.match(/^(#{1,4})\s+(.+)$/)
        if (heading) {
          html.push(`<div class="agent-iteration-report-md-heading">${this.renderAgentInlineMarkdown(heading[2])}</div>`)
          seenContent = true
          index += 1
          continue
        }
        if (!seenContent && hasStructuredLines && line.length <= 40 && !/^(\d+)[.、]\s+/.test(line)) {
          html.push(`<div class="agent-iteration-report-md-heading">${this.renderAgentInlineMarkdown(line)}</div>`)
          seenContent = true
          index += 1
          continue
        }
        const numbered = line.match(/^(\d+)[.、]\s+(.+)$/)
        if (numbered) {
          html.push(`<div class="agent-iteration-report-md-list-item"><span>${this.escapeAgentMessageHtml(numbered[1])}.</span><span>${this.renderAgentInlineMarkdown(numbered[2])}</span></div>`)
          seenContent = true
          index += 1
          continue
        }
        const bullet = line.match(/^[-*]\s+(.+)$/)
        if (bullet) {
          html.push(`<div class="agent-iteration-report-md-list-item"><span>•</span><span>${this.renderAgentInlineMarkdown(bullet[1])}</span></div>`)
          seenContent = true
          index += 1
          continue
        }
        html.push(`<div class="agent-iteration-report-md-paragraph">${this.renderAgentInlineMarkdown(line)}</div>`)
        seenContent = true
        index += 1
      }
      return html.join('')
    },
    ...createAgentTabsMethods(),
    ...createAgentSummaryViewMethods(),
    ...createAgentBasisDrawerMethods(),
    ...createAgentContextAskUiMethods(),
    ...createAgentSiteSelectionTabMethods(),
    ...createAgentIterationChangeUiMethods(),
    ...createAgentCapabilityWorkbenchMethods(),
    ...createAgentThreadUiMethods(),
  }
}

export { createAgentUiMethods }
