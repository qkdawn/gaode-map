import test from 'node:test'
import assert from 'node:assert/strict'

import {
  cloneAgentSessionRecord,
  createAgentRunState,
  createAgentSessionRecord,
  deriveAgentSessionPreview,
  deriveAgentSessionTitle,
  normalizeAgentSessionSummary,
} from '../src/features/agent/normalizers.js'

test('conversation session keeps only product metadata, messages, activity, and local panel payloads', () => {
  const session = createAgentSessionRecord({
    id: 'session-1',
    status: 'running',
    messages: [{ id: 'user-1', role: 'user', content: '分析这个范围', process: { plan: {} } }],
    activityItems: [{ id: 'mcp-1', title: '调用 read_project', state: 'active' }],
    panelPayloads: { summary_pack: { title: '区域总结' } },
    executionTrace: [{ tool_name: 'legacy' }],
    plan: { steps: [{ tool_name: 'legacy' }] },
  })

  assert.equal(session.messages[0].process, undefined)
  assert.equal(session.activityItems[0].id, 'mcp-1')
  assert.equal(session.panelPayloads.summary_pack.title, '区域总结')
  assert.equal(session.executionTrace, undefined)
  assert.equal(session.plan, undefined)
  assert.deepEqual(cloneAgentSessionRecord(session), session)
})

test('deriveAgentSessionPreview prefers the latest message and title prefers the first user message', () => {
  const session = {
    messages: [
      { role: 'user', content: '总结这个区域的商业特征' },
      { role: 'assistant', content: '这里以社区商业为主' },
    ],
  }

  assert.equal(deriveAgentSessionPreview(session), '这里以社区商业为主')
  assert.equal(deriveAgentSessionTitle(session.messages), '总结这个区域的商业特征')
})

test('run state excludes reasoning and panel preload shadow-runtime state', () => {
  const state = createAgentRunState({
    loading: true,
    reasoningBlocks: [{ content: 'legacy reasoning' }],
    panelPreloadNotes: [{ key: 'poi', label: 'POI' }],
    pendingQuestion: 'legacy question',
  })

  assert.equal(state.loading, true)
  assert.equal(state.reasoningBlocks, undefined)
  assert.equal(state.panelPreloadNotes, undefined)
  assert.equal(state.pendingQuestion, undefined)
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
