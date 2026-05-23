import test from 'node:test'
import assert from 'node:assert/strict'

import { createAnalysisSessionInitialState } from '../src/stores/analysis/session.js'
import {
  createAnalysisHistoryListInitialState,
  createAnalysisHistoryListMethods,
} from '../src/features/history/list.js'

const historyListMethods = createAnalysisHistoryListMethods()

function createContext(overrides = {}) {
  return Object.assign(
    {},
    createAnalysisSessionInitialState(),
    createAnalysisHistoryListInitialState(),
    historyListMethods,
    {
      activeStep3Panel: 'poi',
      selectStep3Panel(panelId) {
        this.activeStep3Panel = panelId
      },
      loadHistoryList() {
        this.historyListLoadCalls = (this.historyListLoadCalls || 0) + 1
        return Promise.resolve()
      },
      backToHome() {
        this.backToHomeCalls = (this.backToHomeCalls || 0) + 1
        this.sidebarView = 'start'
        this.step = 1
      },
    },
    overrides,
  )
}

test('openHistoryView captures start page as return context', async () => {
  const ctx = createContext({
    sidebarView: 'start',
    step: 1,
  })

  ctx.openHistoryView()
  await Promise.resolve()

  assert.equal(ctx.sidebarView, 'history')
  assert.deepEqual(ctx.historyReturnContext, {
    sidebarView: 'start',
    step: 1,
    activeStep3Panel: '',
  })
  assert.equal(ctx.getHistoryBackButtonLabel(), '← 返回主界面')
})

test('openHistoryView captures wizard step and panel, then backFromHistory restores them', async () => {
  const ctx = createContext({
    sidebarView: 'wizard',
    step: 2,
    activeStep3Panel: 'agent',
  })

  ctx.openHistoryView()
  await Promise.resolve()

  assert.deepEqual(ctx.historyReturnContext, {
    sidebarView: 'wizard',
    step: 2,
    activeStep3Panel: 'agent',
  })
  assert.equal(ctx.getHistoryBackButtonLabel(), '← 返回结果界面')

  ctx.backFromHistory()

  assert.equal(ctx.sidebarView, 'wizard')
  assert.equal(ctx.step, 2)
  assert.equal(ctx.activeStep3Panel, 'agent')
  assert.equal(ctx.historyReturnContext, null)
})

test('backFromHistory exits selection mode before restoring page', () => {
  const ctx = createContext({
    sidebarView: 'history',
    isSelectionMode: true,
    historyReturnContext: {
      sidebarView: 'wizard',
      step: 2,
      activeStep3Panel: 'population',
    },
  })

  ctx.backFromHistory()

  assert.equal(ctx.isSelectionMode, false)
  assert.equal(ctx.sidebarView, 'history')
  assert.deepEqual(ctx.historyReturnContext, {
    sidebarView: 'wizard',
    step: 2,
    activeStep3Panel: 'population',
  })
})

test('backFromHistory falls back to home when return context is missing', () => {
  const ctx = createContext({
    sidebarView: 'history',
    step: 2,
  })

  ctx.backFromHistory()

  assert.equal(ctx.backToHomeCalls, 1)
  assert.equal(ctx.sidebarView, 'start')
  assert.equal(ctx.step, 1)
  assert.equal(ctx.historyReturnContext, null)
})

test('loadHistoryList surfaces database failures instead of showing empty state', async () => {
  const ctx = createContext({
    historyList: [{ id: 'existing' }],
    historyListRaw: [{ id: 'existing' }],
    historyLoadedCount: 1,
  })
  const previousFetch = global.fetch
  global.fetch = async () => ({
    ok: false,
    status: 503,
    json: async () => ({}),
  })

  try {
    await historyListMethods.loadHistoryList.call(ctx, { force: true, keepExisting: true })
    assert.equal(ctx.historyLoadError, '历史记录请求失败(503)')
    assert.equal(ctx.historyLoading, false)
    assert.deepEqual(ctx.historyList, [{ id: 'existing' }])
  } finally {
    global.fetch = previousFetch
  }
})
