import test from 'node:test'
import assert from 'node:assert/strict'

import {
  deriveAgentSessionPreview,
  deriveAgentSessionTitle,
  normalizeAgentSessionSummary,
  normalizeAgentTurnPayload,
} from '../src/features/agent/normalizers.js'

test('normalizeAgentTurnPayload normalizes structured agent response fields', () => {
  const normalized = normalizeAgentTurnPayload({
    status: 'requires_clarification',
    output: {
      cards: [{ type: 'summary', title: '概览', content: '这里以社区商业为主', items: [] }],
      clarification_question: '你希望这里最终怎么展示？',
      clarification_options: ['问题+建议回答', '只显示真实追问'],
      panel_payloads: { poi_result: { total: 12 } },
      decision: { summary: '先补充目标再继续', mode: 'judgment', strength: 'moderate', can_act: false },
    },
    diagnostics: {
      execution_trace: [{ tool_name: 'read_current_scope', status: 'success' }],
      thinking_timeline: [{ id: 'thinking-1', title: '输入检查完成', state: 'completed' }],
      planning_summary: '先读范围，再追问缺口',
    },
    plan: {
      steps: [{ tool_name: 'read_current_scope', reason: '读取当前分析范围' }],
      summary: '先读范围，再追问缺口',
    },
  })

  assert.equal(normalized.status, 'requires_clarification')
  assert.equal(normalized.output.clarificationQuestion, '你希望这里最终怎么展示？')
  assert.deepEqual(normalized.output.clarificationOptions, ['问题+建议回答', '只显示真实追问'])
  assert.equal(normalized.output.panelPayloads.poi_result.total, 12)
  assert.equal(normalized.diagnostics.executionTrace[0].tool_name, 'read_current_scope')
  assert.equal(normalized.diagnostics.thinkingTimeline[0].id, 'thinking-1')
  assert.equal(normalized.plan.steps[0].tool_name, 'read_current_scope')
})

test('deriveAgentSessionPreview prefers summary card and deriveAgentSessionTitle prefers first user message', () => {
  const session = {
    messages: [
      { role: 'user', content: '总结这个区域的商业特征' },
      { role: 'assistant', content: '这里以社区商业为主' },
    ],
    cards: [{ type: 'summary', title: '核心判断', content: '这里以社区商业为主', items: [] }],
  }

  assert.equal(deriveAgentSessionPreview(session), '这里以社区商业为主')
  assert.equal(deriveAgentSessionTitle(session.messages), '总结这个区域的商业特征')
})

test('normalizeAgentSessionSummary keeps persisted metadata and existing snapshot flags', () => {
  const summary = normalizeAgentSessionSummary(
    {
      id: 'session-1',
      title: '区域商业总结',
      preview: '这里以餐饮和零售为主',
      status: 'answered',
      title_source: 'user',
      history_id: 'history-123',
      panel_kind: 'commercial_summary',
      is_pinned: true,
    },
    { snapshotLoaded: true },
  )

  assert.equal(summary.id, 'session-1')
  assert.equal(summary.title, '区域商业总结')
  assert.equal(summary.preview, '这里以餐饮和零售为主')
  assert.equal(summary.persisted, true)
  assert.equal(summary.snapshotLoaded, true)
  assert.equal(summary.isPinned, true)
  assert.equal(summary.historyId, 'history-123')
  assert.equal(summary.panelKind, 'commercial_summary')
})
