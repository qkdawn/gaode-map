import assert from 'node:assert/strict'
import test from 'node:test'

import {
  CONVERSATION_TURN_STREAM_URL,
  buildConversationTurnRequest,
} from '../src/features/agent/conversation-request.js'

test('conversation request sends one message and bounded map context', () => {
  const request = buildConversationTurnRequest({
    buildAgentAnalysisSnapshot() {
      return {
        active_panel: 'poi',
        scope: { polygon: [[113, 23], [114, 23], [113, 23]] },
        current_filters: { year: 2025 },
      }
    },
    getAgentMapViewState() {
      return { center: [113.3, 23.1], zoom: 12 }
    },
    getAgentAnalysisSourceState() {
      return { sources: [] }
    },
  }, {
    targetSessionId: 'conversation-1',
    historyId: 'history-1',
    rawQuestion: '这个区域适合什么功能？',
    panelKind: 'analysis',
    requestMessages: [
      { role: 'user', content: '旧问题' },
      { role: 'assistant', content: '旧回答' },
    ],
  })

  assert.equal(CONVERSATION_TURN_STREAM_URL, '/api/v1/analysis/agent/conversations/turns/stream')
  assert.deepEqual(request, {
    conversation_id: 'conversation-1',
    history_id: 'history-1',
    message: '这个区域适合什么功能？',
    panel_kind: 'analysis',
    map_context: {
      active_panel: 'poi',
      scope: { polygon: [[113, 23], [114, 23], [113, 23]] },
      current_filters: { year: 2025 },
      map_view: { center: [113.3, 23.1], zoom: 12 },
      selected_sources: [],
      target_capability_id: '',
      capability_input_selections: [],
    },
  })
  assert.equal(Object.hasOwn(request, 'messages'), false)
  assert.equal(Object.hasOwn(request, 'analysis_snapshot'), false)
  assert.equal(Object.hasOwn(request, 'execution_profile'), false)
})
