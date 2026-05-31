import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildAgentPlanChecklist,
  buildAgentToolCallItems,
  shouldExpandAgentProcessSection,
  shouldShowAgentProcessLiveStatus,
  shouldShowAgentProcessToggle,
} from '../src/features/agent/derived.js'

test('buildAgentPlanChecklist maps execution trace into planner progress and statuses', () => {
  const checklist = buildAgentPlanChecklist(
    {
      steps: [
        { tool_name: 'read_current_scope', reason: '读取范围', evidence_goal: '拿到 scope_polygon' },
        { tool_name: 'fetch_pois_in_scope', reason: '抓取 POI', evidence_goal: '确认业态结构' },
      ],
      followup_steps: [
        { tool_name: 'compute_h3_metrics_from_scope_and_pois', reason: '补充 H3', evidence_goal: '补强空间证据' },
      ],
      followup_applied: true,
      summary: '先看范围，再看供给结构',
    },
    [
      { tool_name: 'read_current_scope', status: 'success' },
      { tool_name: 'fetch_pois_in_scope', status: 'blocked' },
    ],
    {
      isLoading: true,
      stage: 'executing',
    },
  )

  assert.equal(checklist.visible, true)
  assert.equal(checklist.progressLabel, '1/3 已完成')
  assert.equal(checklist.groups[0].items[0].status, 'completed')
  assert.equal(checklist.groups[0].items[1].status, 'blocked')
  assert.equal(checklist.groups[1].items[0].status, 'pending')
  assert.match(checklist.summary, /已根据审计补充步骤/)
})

test('buildAgentToolCallItems normalizes trace metadata and artifact labels', () => {
  const items = buildAgentToolCallItems([
    {
      call_id: 'trace-1',
      tool_name: 'fetch_pois_in_scope',
      status: 'success',
      arguments_summary: 'scope_polygon',
      result_summary: '返回 132 个 POI',
      evidence_count: 3,
      warning_count: 1,
      produced_artifacts: ['current_pois', 'current_poi_summary'],
    },
  ])

  assert.equal(items.length, 1)
  assert.equal(items[0].id, 'trace-1')
  assert.equal(items[0].statusTone, 'success')
  assert.equal(items[0].argumentsSummary, 'scope_polygon')
  assert.equal(items[0].resultSummary, '返回 132 个 POI')
  assert.deepEqual(items[0].producedArtifacts, ['current_pois', 'current_poi_summary'])
})

test('shouldExpandAgentProcessSection keeps completed and failed history collapsed', () => {
  assert.equal(shouldExpandAgentProcessSection('answered', { hasContent: true, isLoading: false }), false)
  assert.equal(shouldExpandAgentProcessSection('running', { hasContent: true, isLoading: false }), true)
  assert.equal(shouldExpandAgentProcessSection('failed', { hasContent: true, isLoading: false }), false)
  assert.equal(shouldExpandAgentProcessSection('requires_risk_confirmation', { hasContent: true, isLoading: false }), true)
  assert.equal(shouldExpandAgentProcessSection('answered', { hasContent: false, isLoading: true }), false)
})

test('agent process toggle is hidden while live status is running', () => {
  assert.equal(shouldShowAgentProcessLiveStatus('running', { hasContent: true, isLoading: true }), true)
  assert.equal(shouldShowAgentProcessToggle('running', { hasContent: true, isLoading: true }), false)
  assert.equal(shouldShowAgentProcessLiveStatus('answered', { hasContent: true, isLoading: false }), false)
  assert.equal(shouldShowAgentProcessToggle('answered', { hasContent: true, isLoading: false }), true)
  assert.equal(shouldShowAgentProcessToggle('answered', { hasContent: false, isLoading: false }), false)
})
