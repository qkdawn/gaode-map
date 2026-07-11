import test from 'node:test'
import assert from 'node:assert/strict'

import { buildMainLoopRequestBody } from '../src/features/agent/main-loop-request.js'

test('main loop request carries capability target and explicit upstream selections', async () => {
  const ctx = {
    ensureAgentVisualSnapshotCache: async () => [],
    buildAgentAnalysisSnapshot: () => ({ scope: { scope_id: 'scope-1' } }),
    buildAgentMapSearchContext: () => ({}),
  }
  const body = await buildMainLoopRequestBody(ctx, {
    panelKind: 'analysis',
    mode: 'deep',
    targetSessionId: 'conversation-1',
    historyId: 'history-1',
    requestMessages: [{ role: 'user', content: '生成空间矩阵' }],
    requestRiskConfirmations: [],
    executionProfile: { model_profile_id: 'model-1', skill_id: 'urban-strategy-stage1' },
  }, {
    visualSnapshots: false,
    targetCapabilityId: 'spatial-programming-matrix',
    capabilityInputSelections: [{
      requirement_id: 'stage1_basis',
      mode: 'specific_run',
      run_id: 'run-1',
    }],
  })

  assert.equal(body.target_capability_id, 'spatial-programming-matrix')
  assert.deepEqual(body.capability_input_selections, [{
    requirement_id: 'stage1_basis',
    mode: 'specific_run',
    run_id: 'run-1',
  }])
})
