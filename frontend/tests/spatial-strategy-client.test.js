import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createAgentCapabilityWorkbenchMethods } from '../src/features/agent/capability-workbench.js'
import { publishDocumentToKnowledgeBase } from '../src/features/ppt-planning/api.js'

test('spatial strategy panel presents a collapsed reader timeline without engine details', () => {
  const template = readFileSync(new URL('../src/pages/analysis/components/main.html', import.meta.url), 'utf8')

  assert.match(template, /<strong>分析进度<\/strong>/)
  assert.match(template, /<details class="agent-capability-run-timeline-disclosure">/)
  assert.match(template, /查看十二章分析进度/)
  assert.doesNotMatch(template, />n8n Run</)
  assert.doesNotMatch(template, />执行引擎</)
  assert.doesNotMatch(template, />引用方式</)
  assert.doesNotMatch(template, /\{\{ n8nSpatialStrategyRun\.run_id \}\}/)
})

test('n8n spatial strategy client submits through the backend proxy and polls status', async () => {
  const previousWindow = globalThis.window
  const previousFetch = globalThis.fetch
  const calls = []
  globalThis.window = {
    __ANALYSIS_BOOTSTRAP__: { tenantId: 'tenant-1', accessGroups: ['planning', 'planning'] },
    setTimeout: () => 1,
    clearTimeout: () => {},
  }
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, options })
    if (url.endsWith('/runs')) {
      return { ok: true, json: async () => ({ accepted: true, run_id: 'run-1', status: '准备中', message: '分析任务已接收。' }) }
    }
    return {
      ok: true,
      json: async () => ({
        run_id: 'run-1',
        status: '已完成',
        message: '十二章分析已完成。',
        progress: { completed_chapters: 12, total_chapters: 12 },
        chapters: [],
        report: { summary: '先核验，再试运营，最后决定建设。' },
      }),
    }
  }
  try {
    const methods = createAgentCapabilityWorkbenchMethods()
    const state = {
      ...methods,
      agentInput: '判断当前项目的空间定位',
      n8nSpatialStrategyRun: null,
      n8nSpatialStrategyLoading: false,
      n8nSpatialStrategyError: '',
      n8nSpatialStrategyPollHandle: null,
      n8nSpatialStrategyDeliverToFeishu: true,
    }
    await state.runN8nSpatialStrategy()
    assert.equal(calls[0].url, '/api/v1/analysis/spatial-strategy/runs')
    assert.equal(calls[0].options.headers['X-Tenant-Id'], 'tenant-1')
    assert.equal(calls[0].options.headers['X-Access-Groups'], 'planning')
    const submitted = JSON.parse(calls[0].options.body)
    assert.equal(submitted.project_question, '判断当前项目的空间定位')
    assert.equal(submitted.deliver_to_feishu, true)
    assert.equal(calls[1].url, '/api/v1/analysis/spatial-strategy/runs/run-1')
    assert.equal(state.n8nSpatialStrategyRun.status, '已完成')
    assert.equal(state.n8nSpatialStrategyDeliverToFeishu, false)
  } finally {
    globalThis.window = previousWindow
    globalThis.fetch = previousFetch
  }
})

test('document publishing sends tenant and access policy outside the RAG payload', async () => {
  const previousFetch = globalThis.fetch
  let request = null
  globalThis.fetch = async (url, options = {}) => {
    request = { url, options }
    return {
      ok: true,
      json: async () => ({ accepted: true, status: 'published', document_id: 'doc-1', tenant_id: 'tenant-1' }),
    }
  }
  try {
    await publishDocumentToKnowledgeBase('doc-1', {
      tenantId: 'tenant-1',
      accessGroups: ['planning', 'planning', 'finance'],
      metadata: { history_id: 'history-1' },
    })
    assert.equal(request.url, '/api/v1/analysis/knowledge-base/documents')
    assert.equal(request.options.headers['X-Tenant-Id'], 'tenant-1')
    assert.equal(request.options.headers['X-Access-Groups'], 'planning,finance')
    assert.deepEqual(JSON.parse(request.options.body), {
      document_id: 'doc-1',
      visibility: 'restricted',
      source_type: 'project_document',
      metadata: { history_id: 'history-1' },
    })
  } finally {
    globalThis.fetch = previousFetch
  }
})

test('spatial strategy goal timeline includes pending steps and grounded final summary', () => {
  const methods = createAgentCapabilityWorkbenchMethods()
  const state = {
    ...methods,
    n8nSpatialStrategyRun: {
      status: '已完成',
      message: '十二章分析已完成。',
      progress: { completed_chapters: 12, total_chapters: 12 },
      chapters: Array.from({ length: 12 }, (_, index) => ({ number: index + 1, title: `章节 ${index + 1}`, status: '等待分析', content: '' })),
      report: { summary: '先核验，再试运营，最后决定建设。' },
      _unused: [
        {
          number: 7,
          title: '项目定位',
          status: '已完成',
          content: '选择可逆验证型定位。',
        },
        {
          number: 12,
          title: '分期实施',
          status: '已完成',
          content: '先核验，再试运营，最后决定建设。',
        },
      ],
    },
  }

  state.n8nSpatialStrategyRun.chapters[6] = state.n8nSpatialStrategyRun._unused[0]
  state.n8nSpatialStrategyRun.chapters[11] = state.n8nSpatialStrategyRun._unused[1]
  const timeline = state.getN8nSpatialStrategySteps()
  assert.equal(timeline.length, 12)
  assert.equal(timeline[0].status, '等待分析')
  assert.equal(timeline[6].status, '已完成')
    const summary = state.getN8nSpatialStrategyFinalSummary()
    assert.equal(summary.headline, '先核验，再试运营，最后决定建设。')
    assert.equal(summary.sections.length, 2)
  assert.equal(state.getN8nSpatialStrategyCitationKind({ source_type: 'project_document' }), '项目材料')
  assert.equal(state.getN8nSpatialStrategyCitationKind({ source_type: 'project_data' }), '项目数据')
  assert.equal(state.getN8nSpatialStrategyCitationKind({ source_type: 'project_data_record' }), '项目数据')
  assert.equal(state.getN8nSpatialStrategyCitationKind({ source_type: 'project_computed_result' }), '空间数据')
  assert.equal(state.getN8nSpatialStrategyCitationKind({ source_type: 'knowledge_base' }), '公开资料')
})

test('failed spatial strategy resumes through the backend without resending the question', async () => {
  const previousWindow = globalThis.window
  const previousFetch = globalThis.fetch
  const calls = []
  globalThis.window = {
    __ANALYSIS_BOOTSTRAP__: { tenantId: 'tenant-1' },
    setTimeout: () => 1,
    clearTimeout: () => {},
  }
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, options })
    if (url.endsWith('/resume')) {
      return { ok: true, json: async () => ({ accepted: true, run_id: 'run-1', status: '准备中', message: '分析任务已接收。' }) }
    }
    return {
      ok: true,
      json: async () => ({
        run_id: 'run-1', status: '分析中', message: '正在分析第 10 章。',
        progress: { completed_chapters: 9, total_chapters: 12 }, chapters: [],
      }),
    }
  }
  try {
    const methods = createAgentCapabilityWorkbenchMethods()
    const state = {
      ...methods,
      n8nSpatialStrategyRun: { run_id: 'run-1', status: '需要处理', chapters: [] },
      n8nSpatialStrategyLoading: false,
      n8nSpatialStrategyError: '',
      n8nSpatialStrategyPollHandle: null,
    }
    await state.resumeN8nSpatialStrategy()
    assert.equal(calls[0].url, '/api/v1/analysis/spatial-strategy/runs/run-1/resume')
    assert.equal(calls[0].options.headers['X-Tenant-Id'], 'tenant-1')
    assert.equal(calls[0].options.body, undefined)
    assert.equal(state.n8nSpatialStrategyRun.status, '分析中')
  } finally {
    globalThis.window = previousWindow
    globalThis.fetch = previousFetch
  }
})
