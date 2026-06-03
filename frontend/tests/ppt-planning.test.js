import test from 'node:test'
import assert from 'node:assert/strict'

import {
  createAgentTabsMethods,
} from '../src/features/agent/tabs.js'
import {
  createPptSystemSources,
} from '../src/features/ppt-planning/model.js'
import { createAgentPptPlanningTabMethods } from '../src/features/agent/ppt-planning-tabs.js'

import {
  applyDeckBriefResponse,
  applyPptSpecResponse,
  applyPptSourceGroupsResponse,
  addPptDataPackageSource,
  buildDeckBriefPayload,
  buildPptSpecPayload,
  createPptPlanningState,
  getActiveDeckSlideBrief,
  getPptSourceSummary,
  mergePptPlanningSources,
  movePptSourceToGroup,
  removePptSource,
  removePptSourceGroup,
  setAllPptSourcesSelected,
  setPptSourceGroupSelected,
  togglePptSourceSelection,
} from '../src/features/ppt-planning/ui-state.js'

const DEFAULT_PPT_POI_EVIDENCE_INTENT = '为 PPT 指令生成整理当前区域代表性 POI 资料'
const DEFAULT_PPT_NIGHTLIFE_POI_INTENT = '整理夜生活与夜间消费相关 POI，并与夜光格子对应'

function createPptPlanningTestContext(overrides = {}) {
  const methods = createAgentPptPlanningTabMethods()
  return {
    ...methods,
    agentPanelPayloads: {},
    currentHistoryRecordId: 'history-1',
    activeAgentSessionId: 'session-1',
    agentTabs: {
      activeTabId: 'ppt-1',
      summaryTabs: [],
      iterationChangeTabs: [],
      siteSelectionTabs: [],
      pptPlanningTabs: [{
        id: 'ppt-1',
        kind: 'ppt_planning',
        source: 'current',
        pptPlanningState: createPptPlanningState(),
      }],
      deepAnalysisTabs: [],
      followupTabs: [],
    },
    ensureAgentTabs() {
      return this.agentTabs
    },
    getAgentActiveTopTab() {
      return { id: this.agentTabs.activeTabId, kind: 'ppt_planning' }
    },
    normalizeAgentSiteSelectionScope() {
      return {
        polygon: [[0, 0], [1, 0], [1, 1]],
        drawnPolygon: [],
        isochroneFeature: null,
      }
    },
    syncCurrentAgentSession() {},
    syncActiveAgentRuntimeView() {},
    formatAgentTabTitle(_kind, title) {
      return title || '策划 PPT'
    },
    captureAgentActiveSummaryTabState() {},
    captureAgentActiveSiteSelectionTabState() {},
    captureAgentActiveDeepAnalysisTabState() {},
    captureAgentActiveFollowupTabState() {},
    requestAgentPptPlanningDataSources() {
      return Promise.resolve([])
    },
    requestAgentPptPlanningDataPackage() {
      return Promise.resolve({})
    },
    ...overrides,
  }
}

test('ppt planning state creates NotebookLM-style system sources and default spec', () => {
  const state = createPptPlanningState()

  assert.equal(state.spec.audience, '政府评审')
  assert.equal(state.spec.pageCount, 15)
  assert.equal(state.sources.length, 6)
  assert.ok(state.sourceGroups.length >= 4)
  assert.equal(state.removedSourceIds.length, 0)
  assert.deepEqual(getPptSourceSummary(state), { total: 6, selected: 0, ready: 0 })
})

test('ppt source group response normalizes missing sources into uncategorized group', () => {
  const state = mergePptPlanningSources(createPptPlanningState(), createPptSystemSources({
    scope: { polygon: [[0, 0], [1, 0], [1, 1]] },
    taskResults: { poi_fetch: true, nightlight: true },
  }))
  const grouped = applyPptSourceGroupsResponse(state, {
    groups: [
      { id: 'group:vitality', title: '城市活力证据', source_ids: ['system:poi', 'system:unknown', 'system:poi'] },
    ],
  })

  const vitality = grouped.sourceGroups.find((item) => item.id === 'group:vitality')
  const uncategorized = grouped.sourceGroups.find((item) => item.id === 'group:uncategorized')

  assert.deepEqual(vitality.sourceIds, ['system:poi'])
  assert.ok(uncategorized.sourceIds.includes('system:scope'))
  assert.ok(uncategorized.sourceIds.includes('system:nightlight'))
})

test('ppt source group selection toggles only ready group sources', () => {
  const state = mergePptPlanningSources(createPptPlanningState(), createPptSystemSources({
    scope: { polygon: [[0, 0], [1, 0], [1, 1]] },
    taskResults: { poi_fetch: true },
  }))
  const groupId = state.sourceGroups.find((group) => group.sourceIds.includes('system:scope')).id
  const deselected = setPptSourceGroupSelected(state, groupId, false)
  const payload = buildPptSpecPayload(deselected)

  assert.equal(deselected.sources.find((item) => item.id === 'system:scope').selected, false)
  assert.equal(payload.source_ids.includes('system:scope'), false)
})

test('moving a ppt source between groups keeps selected source payload unchanged', () => {
  const state = mergePptPlanningSources(createPptPlanningState(), createPptSystemSources({
    scope: { polygon: [[0, 0], [1, 0], [1, 1]] },
    taskResults: { poi_fetch: true, nightlight: true },
  }))
  const before = buildPptSpecPayload(state).source_ids
  const targetGroup = state.sourceGroups.find((group) => group.sourceIds.includes('system:scope'))
  const moved = movePptSourceToGroup(state, 'system:nightlight', targetGroup.id)

  assert.deepEqual(buildPptSpecPayload(moved).source_ids.sort(), before.sort())
  assert.ok(moved.sourceGroups.find((group) => group.id === targetGroup.id).sourceIds.includes('system:nightlight'))
})

test('removing a ppt group keeps its sources in uncategorized group', () => {
  const state = mergePptPlanningSources(createPptPlanningState(), createPptSystemSources({
    scope: { polygon: [[0, 0], [1, 0], [1, 1]] },
    taskResults: { poi_fetch: true },
  }))
  const group = state.sourceGroups.find((item) => item.sourceIds.includes('system:scope'))
  const removed = removePptSourceGroup(state, group.id)
  const uncategorized = removed.sourceGroups.find((item) => item.id === 'group:uncategorized')

  assert.ok(removed.sources.find((item) => item.id === 'system:scope'))
  assert.ok(uncategorized.sourceIds.includes('system:scope'))
})

test('removing a ppt source excludes it from payload and future system refreshes', () => {
  const initial = mergePptPlanningSources(createPptPlanningState(), createPptSystemSources({
    scope: { polygon: [[0, 0], [1, 0], [1, 1]] },
    taskResults: { poi_fetch: true },
  }))
  const removed = removePptSource(initial, 'system:poi')
  const refreshed = mergePptPlanningSources(removed, createPptSystemSources({
    scope: { polygon: [[0, 0], [1, 0], [1, 1]] },
    taskResults: { poi_fetch: true, nightlight: true },
  }))

  assert.equal(refreshed.sources.some((item) => item.id === 'system:poi'), false)
  assert.equal(buildPptSpecPayload(refreshed).source_ids.includes('system:poi'), false)
  assert.ok(refreshed.removedSourceIds.includes('system:poi'))
})

test('ppt source selection only includes ready sources in the spec payload', () => {
  const systemSources = createPptSystemSources({
    scope: { polygon: [[0, 0], [1, 0], [1, 1]] },
    taskResults: { poi_fetch: true },
  })
  const state = togglePptSourceSelection(
    mergePptPlanningSources(createPptPlanningState(), systemSources),
    'system:nightlight',
  )
  const payload = buildPptSpecPayload(state, { areaId: 'area-1' })

  assert.equal(payload.area_id, 'area-1')
  assert.equal(payload.audience, '政府评审')
  assert.equal(payload.page_count, 15)
  assert.ok(payload.source_ids.includes('system:scope'))
  assert.ok(payload.source_ids.includes('system:poi'))
  assert.equal(payload.source_ids.includes('system:nightlight'), false)
})

test('ppt state can select all sources and keep an active page brief', () => {
  const systemSources = createPptSystemSources({
    scope: { polygon: [[0, 0], [1, 0], [1, 1]] },
    taskResults: { poi_fetch: true, population: true },
  })
  const state = setAllPptSourcesSelected(mergePptPlanningSources(createPptPlanningState(), systemSources), true)
  const active = getActiveDeckSlideBrief(state)

  assert.equal(getPptSourceSummary(state).selected, 3)
  assert.equal(active.title, '封面')
  assert.equal(active.speakerNotes.includes('不直接生成 PPTX'), true)
})

test('ppt system sources refresh preserves ready selections and blocks pending sources', () => {
  const initial = mergePptPlanningSources(createPptPlanningState(), createPptSystemSources({
    scope: { polygon: [[0, 0], [1, 0], [1, 1]] },
    taskResults: { poi_fetch: true },
  }))
  const deselectedPoi = togglePptSourceSelection(initial, 'system:poi', false)
  const refreshed = mergePptPlanningSources(deselectedPoi, createPptSystemSources({
    scope: { polygon: [[0, 0], [1, 0], [1, 1]] },
    taskResults: { poi_fetch: true, nightlight: true },
  }))

  const poi = refreshed.sources.find((item) => item.id === 'system:poi')
  const nightlight = refreshed.sources.find((item) => item.id === 'system:nightlight')
  const road = refreshed.sources.find((item) => item.id === 'system:road-syntax')

  assert.equal(poi.selected, false)
  assert.equal(nightlight.selected, true)
  assert.equal(road.status, 'pending')
  assert.equal(road.selected, false)
})

test('ppt data package source is visible and survives system source refresh', () => {
  const initial = mergePptPlanningSources(createPptPlanningState(), createPptSystemSources({
    scope: { polygon: [[0, 0], [1, 0], [1, 1]] },
    taskResults: { poi_fetch: true },
  }))
  const withPackage = addPptDataPackageSource(initial, {
    source: {
      id: 'package:poi:test',
      type: 'package',
      title: 'POI 资料包',
      status: 'ready',
      selected: true,
      meta: {
        label: 'POI 2 条',
        sourceKind: 'package',
        package: { summary: '已整理 2 条 POI 样例。' },
      },
    },
  })
  const refreshed = mergePptPlanningSources(withPackage, createPptSystemSources({
    scope: { polygon: [[0, 0], [1, 0], [1, 1]] },
    taskResults: { poi_fetch: true, population: true },
  }))
  const packageSource = refreshed.sources.find((item) => item.id === 'package:poi:test')

  assert.equal(packageSource.selected, true)
  assert.equal(packageSource.meta.sourceKind, 'package')
  assert.ok(getPptSourceSummary(refreshed).selected >= 3)
})

test('deck brief payload includes selected package sources and analysis context', () => {
  const state = addPptDataPackageSource(createPptPlanningState(), {
    source: {
      id: 'package:poi:test',
      type: 'package',
      title: 'POI 资料包',
      status: 'ready',
      selected: true,
      meta: {
        sourceKind: 'package',
        package: { summary: '已整理 POI。' },
      },
    },
  })
  const payload = buildDeckBriefPayload(state, {
    areaId: 'history-1',
    analysisContext: { scope: { time_min: 35 } },
  })

  assert.equal(payload.area_id, 'history-1')
  assert.equal(payload.sources[0].id, 'package:poi:test')
  assert.equal(payload.analysis_context.scope.time_min, 35)
})

test('ppt planning applies AI outline before directive draft', () => {
  const state = mergePptPlanningSources(createPptPlanningState(), createPptSystemSources({
    scope: { polygon: [[0, 0], [1, 0], [1, 1]] },
    taskResults: { poi_fetch: true, population: true },
  }))
  const outlineState = applyPptSpecResponse(state, {
    title: 'AI 生成目录',
    page_count: 15,
    outline: [
      { id: 'page-1', page_no: 1, theme: '项目命题', purpose: '建立汇报主线' },
    ],
  })
  const directiveState = applyDeckBriefResponse(outlineState, {
    status: 'draft',
    slides: [
      {
        index: 1,
        title: '项目命题',
        purpose: '建立汇报主线',
        key_message: '解释项目为什么成立',
        visual_plan: '区域底图',
        required_sources: ['system:scope'],
        speaker_notes: '第一阶段先生成逐页指令，不直接生成 PPTX。',
      },
    ],
  })

  assert.equal(outlineState.currentStep, 'outline_ready')
  assert.ok(outlineState.outline.length > 0)
  assert.equal(directiveState.currentStep, 'directive_draft')
  assert.equal(directiveState.deckBrief.slides.length, outlineState.outline.length)
})

test('agent ppt source toggle writes back to the active tab state', () => {
  const methods = createAgentPptPlanningTabMethods()
  const ctx = {
    ...methods,
    agentPanelPayloads: {},
    agentTabs: {
      activeTabId: 'ppt-1',
      summaryTabs: [],
      iterationChangeTabs: [],
      siteSelectionTabs: [],
      pptPlanningTabs: [{
        id: 'ppt-1',
        kind: 'ppt_planning',
        source: 'current',
        pptPlanningState: createPptPlanningState(),
      }],
      deepAnalysisTabs: [],
      followupTabs: [],
    },
    ensureAgentTabs() {
      return this.agentTabs
    },
    getAgentActiveTopTab() {
      return { id: this.agentTabs.activeTabId, kind: 'ppt_planning' }
    },
    normalizeAgentSiteSelectionScope() {
      return {
        polygon: [[0, 0], [1, 0], [1, 1]],
        drawnPolygon: [],
        isochroneFeature: null,
      }
    },
    timeHorizon: 35,
    syncCurrentAgentSession() {},
  }

  ctx.toggleAgentPptPlanningSource('system:scope')

  const state = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)
  const scope = state.sources.find((item) => item.id === 'system:scope')
  assert.equal(scope.status, 'ready')
  assert.equal(scope.selected, false)
})

test('agent ppt generation actions write outline and directive into the active tab', async () => {
  const methods = createAgentPptPlanningTabMethods()
  const ctx = {
    ...methods,
    agentPanelPayloads: {},
    agentTabs: {
      activeTabId: 'ppt-1',
      summaryTabs: [],
      iterationChangeTabs: [],
      siteSelectionTabs: [],
      pptPlanningTabs: [{
        id: 'ppt-1',
        kind: 'ppt_planning',
        source: 'current',
        pptPlanningState: createPptPlanningState(),
      }],
      deepAnalysisTabs: [],
      followupTabs: [],
    },
    ensureAgentTabs() {
      return this.agentTabs
    },
    getAgentActiveTopTab() {
      return { id: this.agentTabs.activeTabId, kind: 'ppt_planning' }
    },
    normalizeAgentSiteSelectionScope() {
      return {
        polygon: [[0, 0], [1, 0], [1, 1]],
        drawnPolygon: [],
        isochroneFeature: null,
      }
    },
    requestAgentPptPlanningOutline() {
      return Promise.resolve({
        title: 'AI 生成目录',
        page_count: 15,
        outline: [
          { id: 'page-1', page_no: 1, theme: '项目命题', purpose: '建立汇报主线' },
        ],
      })
    },
    requestAgentPptPlanningDirective() {
      return Promise.resolve({
        status: 'draft',
        slides: [
          {
            index: 1,
            title: '项目命题',
            purpose: '建立汇报主线',
            key_message: '解释项目为什么成立',
            visual_plan: '区域底图',
            required_sources: ['system:scope'],
            speaker_notes: '第一阶段先生成逐页指令，不直接生成 PPTX。',
          },
        ],
      })
    },
    syncCurrentAgentSession() {},
  }

  await ctx.generateAgentPptPlanningOutline()
  let state = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)
  assert.equal(state.currentStep, 'outline_ready')
  assert.ok(state.outline.length > 0)

  await ctx.generateAgentPptPlanningDirective()
  state = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)
  assert.equal(state.currentStep, 'directive_draft')
  assert.equal(state.deckBrief.slides.length, state.outline.length)
})

test('agent ppt data package action writes a visible package source', async () => {
  const methods = createAgentPptPlanningTabMethods()
  let seenPayload = null
  const ctx = {
    ...methods,
    agentPanelPayloads: {},
    currentHistoryRecordId: 'history-1',
    agentTabs: {
      activeTabId: 'ppt-1',
      summaryTabs: [],
      iterationChangeTabs: [],
      siteSelectionTabs: [],
      pptPlanningTabs: [{
        id: 'ppt-1',
        kind: 'ppt_planning',
        source: 'current',
        pptPlanningState: createPptPlanningState(),
      }],
      deepAnalysisTabs: [],
      followupTabs: [],
    },
    ensureAgentTabs() {
      return this.agentTabs
    },
    getAgentActiveTopTab() {
      return { id: this.agentTabs.activeTabId, kind: 'ppt_planning' }
    },
    normalizeAgentSiteSelectionScope() {
      return {
        polygon: [[0, 0], [1, 0], [1, 1]],
        drawnPolygon: [],
        isochroneFeature: null,
      }
    },
    requestAgentPptPlanningDataPackage(payload) {
      seenPayload = payload
      return Promise.resolve({
        source: {
          id: 'package:poi:test',
          type: 'package',
          title: 'POI 资料包',
          status: 'ready',
          selected: true,
          meta: { label: 'POI 1 条', sourceKind: 'package', package: { items: [] } },
        },
      })
    },
    syncCurrentAgentSession() {},
  }

  await ctx.createAgentPptPlanningDataPackage()
  const state = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)
  const packageSource = state.sources.find((item) => item.id === 'package:poi:test')

  assert.equal(seenPayload.area_id, 'history-1')
  assert.equal(seenPayload.package_mode, 'evidence')
  assert.equal(seenPayload.intent, DEFAULT_PPT_POI_EVIDENCE_INTENT)
  assert.ok(seenPayload.source_ids.includes('system:scope'))
  assert.equal(packageSource.selected, true)
  assert.equal(packageSource.meta.sourceKind, 'package')
})

test('agent ppt refresh loads backend sources and auto creates poi evidence package', async () => {
  let seenPackagePayload = null
  const ctx = createPptPlanningTestContext({
    requestAgentPptPlanningDataSources(areaId) {
      assert.equal(areaId, 'history-1')
      return Promise.resolve([
        {
          id: 'system:scope',
          type: 'data',
          title: '当前等时圈范围',
          status: 'ready',
          summary: '已生成',
          count: 1,
          meta: { label: '已生成', sourceKind: 'system', areaId },
        },
        {
          id: 'system:poi',
          type: 'data',
          title: 'POI 基础数据',
          status: 'ready',
          summary: 'POI 3996 条',
          count: 3996,
          meta: { label: 'POI 3996 条', sourceKind: 'system', areaId },
        },
      ])
    },
    requestAgentPptPlanningDataPackage(payload) {
      seenPackagePayload = payload
      return Promise.resolve({
        source: {
          id: 'package:poi:auto',
          type: 'package',
          title: 'POI 资料包',
          status: 'ready',
          selected: true,
          meta: {
            label: 'POI 8 条',
            sourceKind: 'package',
            package: {
              package_mode: 'evidence',
              intent: DEFAULT_PPT_POI_EVIDENCE_INTENT,
              source_ids: ['system:poi'],
              items: [],
            },
          },
        },
      })
    },
  })

  await ctx.refreshAgentActivePptPlanningDataSources()
  const state = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)
  const poiSource = state.sources.find((item) => item.id === 'system:poi')
  const packageSource = state.sources.find((item) => item.id === 'package:poi:auto')

  assert.equal(poiSource.status, 'ready')
  assert.equal(poiSource.meta.label, 'POI 3996 条')
  assert.equal(seenPackagePayload.area_id, 'history-1')
  assert.deepEqual(seenPackagePayload.source_ids, ['system:poi'])
  assert.equal(seenPackagePayload.package_mode, 'evidence')
  assert.equal(seenPackagePayload.intent, DEFAULT_PPT_POI_EVIDENCE_INTENT)
  assert.equal(packageSource.selected, true)
  assert.equal(packageSource.meta.areaId, 'history-1')
  assert.equal(packageSource.meta.autoGenerated, true)
})

test('agent ppt refresh auto creates nightlife poi nightlight package when both sources are ready', async () => {
  const packagePayloads = []
  const ctx = createPptPlanningTestContext({
    requestAgentPptPlanningDataSources(areaId) {
      return Promise.resolve([
        {
          id: 'system:poi',
          type: 'data',
          title: 'POI 基础数据',
          status: 'ready',
          summary: 'POI 3996 条',
          count: 3996,
          meta: { label: 'POI 3996 条', sourceKind: 'system', areaId },
        },
        {
          id: 'system:nightlight',
          type: 'data',
          title: '夜光强度分析',
          status: 'ready',
          summary: '已生成',
          count: 1,
          meta: { label: '已生成', sourceKind: 'system', areaId },
        },
      ])
    },
    requestAgentPptPlanningDataPackage(payload) {
      packagePayloads.push(payload)
      const isNightlife = payload.intent === DEFAULT_PPT_NIGHTLIFE_POI_INTENT
      return Promise.resolve({
        source: {
          id: isNightlife ? 'package:poi-nightlife:auto' : 'package:poi:auto',
          type: 'package',
          title: isNightlife ? '夜生活 POI × 夜光格子资料包' : 'POI 资料包',
          status: 'ready',
          selected: true,
          meta: {
            label: isNightlife ? 'POI 12 条 / 夜光格 4 个' : 'POI 36 条',
            sourceKind: 'package',
            package: {
              package_mode: 'evidence',
              intent: payload.intent,
              source_ids: payload.source_ids,
              items: [],
            },
          },
        },
      })
    },
  })

  await ctx.refreshAgentActivePptPlanningDataSources()
  const state = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)
  const nightlifePayload = packagePayloads.find((payload) => payload.intent === DEFAULT_PPT_NIGHTLIFE_POI_INTENT)
  const nightlifePackage = state.sources.find((item) => item.id === 'package:poi-nightlife:auto')

  assert.equal(packagePayloads.length, 2)
  assert.deepEqual(nightlifePayload.source_ids, ['system:poi', 'system:nightlight'])
  assert.equal(nightlifePayload.package_mode, 'evidence')
  assert.equal(nightlifePayload.limit, 50)
  assert.equal(nightlifePackage.selected, true)
  assert.equal(nightlifePackage.meta.areaId, 'history-1')
  assert.equal(nightlifePackage.meta.autoGenerated, true)
})

test('agent top tab switch refreshes backend ppt data sources when activating ppt tab', () => {
  const methods = createAgentTabsMethods()
  let sourceRefreshCalls = 0
  const ctx = {
    ...methods,
    agentPanelPayloads: {},
    currentHistoryRecordId: 'history-1',
    activeAgentSessionId: 'session-1',
    agentTabs: {
      activeTabId: 'site-1',
      summaryTabs: [],
      iterationChangeTabs: [],
      siteSelectionTabs: [{
        id: 'site-1',
        kind: 'site_selection',
        source: 'current',
        panelPayloads: {},
      }],
      pptPlanningTabs: [{
        id: 'ppt-1',
        kind: 'ppt_planning',
        source: 'current',
        panelPayloads: {},
        pptPlanningState: createPptPlanningState(),
      }],
      deepAnalysisTabs: [],
      followupTabs: [],
    },
    getAgentSummaryPack() {
      return {}
    },
    hasAgentSummaryPack() {
      return false
    },
    getAgentSummaryStatus() {
      return 'pending'
    },
    getAgentSummaryCompactTitle(_panelPayloads, fallbackTitle = '') {
      return fallbackTitle || '区域总结'
    },
    normalizeSummaryTaskBoard(board = {}) {
      return board && typeof board === 'object' ? board : {}
    },
    buildSummaryTaskBoardUiState() {
      return {}
    },
    summaryTaskBoard: {},
    normalizeAgentSiteSelectionScope() {
      return {
        polygon: [[0, 0], [1, 0], [1, 1]],
        drawnPolygon: [],
        isochroneFeature: null,
      }
    },
    requestAgentPptPlanningDataSources(areaId) {
      sourceRefreshCalls += 1
      assert.equal(areaId, 'history-1')
      return Promise.resolve([])
    },
    requestAgentPptPlanningDataPackage() {
      return Promise.resolve({})
    },
    syncActiveAgentRuntimeView() {},
    syncCurrentAgentSession() {},
  }

  ctx.switchAgentTopTab('ppt-1')

  assert.equal(ctx.getAgentActiveTopTab().kind, 'ppt_planning')
  assert.equal(sourceRefreshCalls, 1)
})

test('agent ppt auto poi evidence package is not created twice for same area', async () => {
  let packageCalls = 0
  const stateWithPackage = addPptDataPackageSource(createPptPlanningState({
    sources: [{
      id: 'system:poi',
      type: 'data',
      title: 'POI 基础数据',
      status: 'ready',
      selected: true,
      meta: { label: 'POI 3996 条', sourceKind: 'system', areaId: 'history-1' },
    }],
  }), {
    source: {
      id: 'package:poi:existing',
      type: 'package',
      title: 'POI 资料包',
      status: 'ready',
      selected: true,
      meta: {
        areaId: 'history-1',
        sourceKind: 'package',
        package: {
          package_mode: 'evidence',
          intent: DEFAULT_PPT_POI_EVIDENCE_INTENT,
          source_ids: ['system:poi'],
        },
      },
    },
  })
  const ctx = createPptPlanningTestContext({
    agentTabs: {
      activeTabId: 'ppt-1',
      summaryTabs: [],
      iterationChangeTabs: [],
      siteSelectionTabs: [],
      pptPlanningTabs: [{
        id: 'ppt-1',
        kind: 'ppt_planning',
        source: 'current',
        pptPlanningState: stateWithPackage,
      }],
      deepAnalysisTabs: [],
      followupTabs: [],
    },
    requestAgentPptPlanningDataPackage() {
      packageCalls += 1
      return Promise.resolve({})
    },
  })

  await ctx.autoCreateAgentPptPlanningPoiEvidencePackage({ areaId: 'history-1' })

  assert.equal(packageCalls, 0)
})

test('agent ppt auto package failure keeps ready sources and visible error', async () => {
  const ctx = createPptPlanningTestContext({
    requestAgentPptPlanningDataSources(areaId) {
      return Promise.resolve([
        {
          id: 'system:poi',
          type: 'data',
          title: 'POI 基础数据',
          status: 'ready',
          summary: 'POI 3996 条',
          count: 3996,
          meta: { label: 'POI 3996 条', sourceKind: 'system', areaId },
        },
      ])
    },
    requestAgentPptPlanningDataPackage() {
      return Promise.reject(new Error('ppt_data_intent_llm_unavailable'))
    },
  })

  await ctx.refreshAgentActivePptPlanningDataSources()
  const state = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)
  const poiSource = state.sources.find((item) => item.id === 'system:poi')

  assert.equal(poiSource.status, 'ready')
  assert.equal(poiSource.meta.label, 'POI 3996 条')
  assert.equal(state.sources.some((item) => String(item.id).startsWith('package:poi')), false)
  assert.equal(state.generationError, 'ppt_data_intent_llm_unavailable')
  assert.equal(state.dataPackageGenerating, false)
})
