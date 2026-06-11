import test from 'node:test'
import assert from 'node:assert/strict'

import {
  createAgentTabsMethods,
} from '../src/features/agent/tabs.js'
import {
  createPptSystemSources,
} from '../src/features/ppt-planning/model.js'
import {
  buildPptCarrierPreviewModel,
} from '../src/features/ppt-planning/carrier-preview.js'
import { createAgentPptPlanningTabMethods } from '../src/features/agent/ppt-planning-tabs.js'

import {
  applyDeckBriefResponse,
  applyPptSpecResponse,
  applyPptSourceGroupsResponse,
  addPptDataPackageSource,
  applyDeckBriefSlideRevision,
  applyPptOutlineSectionRevision,
  buildDeckBriefPayload,
  buildDeckBriefSlidePayload,
  buildPptOutlineSectionPayload,
  buildPptSpecPayload,
  createPptPlanningState,
  getActiveDeckSlideBrief,
  getPendingPptPackageSources,
  getPptSourceSummary,
  mergePptPlanningSources,
  movePptSourceToGroup,
  removePptSource,
  removePptSourceGroup,
  resetPptPlanningToMaterials,
  resetPptPlanningToOutlineReady,
  setAllPptSourcesSelected,
  setPptGenerationError,
  setPptActiveRevisionTarget,
  setPptRevisionDraftField,
  setPptSourceGroupSelected,
  togglePptSourceSelection,
  undoPptSectionRevision,
} from '../src/features/ppt-planning/ui-state.js'

const DEFAULT_PPT_POI_EVIDENCE_INTENT = '为 PPT 指令生成整理当前区域代表性 POI 资料'
const DEFAULT_PPT_NIGHTLIFE_POI_INTENT = '整理夜生活与夜间消费相关 POI，并与夜光格子对应'
const DEFAULT_PPT_CARRIER_EVIDENCE_INTENT = '识别当前区域 POI、路网、人口、夜光共同支撑的空间载体'

test('ppt carrier preview model projects road context and carrier geometries into svg paths', () => {
  const preview = buildPptCarrierPreviewModel([
    {
      carrier_id: 'block_loop_01',
      carrier_type: 'block_loop',
      carrier_label: '成熟商业街区',
      geometry: {
        polygon: [[112.9, 28.2], [112.904, 28.2], [112.904, 28.204], [112.9, 28.204], [112.9, 28.2]],
        boundary: [[112.9, 28.2], [112.904, 28.2], [112.904, 28.204]],
      },
    },
    {
      carrier_id: 'corridor_01',
      carrier_type: 'corridor',
      carrier_label: '高分通达廊道',
      geometry: {
        boundary: [[112.906, 28.2], [112.908, 28.202], [112.906, 28.204]],
      },
    },
    {
      carrier_id: 'segment_01',
      carrier_type: 'segment',
      carrier_label: '重要通达路段',
      geometry: {
        boundary: [[112.898, 28.199], [112.899, 28.201]],
      },
    },
  ], {
    focusId: 'block_loop_01',
    roadContext: {
      features: [
        {
          id: 'road-bottom',
          path: [[112.9, 28.2], [112.904, 28.2]],
          skeleton_score: 0.82,
          choice_score: 0.9,
          integration_score: 0.88,
          is_skeleton: true,
        },
        {
          id: 'road-context',
          path: [[112.898, 28.199], [112.91, 28.205]],
          skeleton_score: 0.35,
          choice_score: 0.2,
          integration_score: 0.44,
          is_skeleton: false,
        },
      ],
    },
  })

  assert.equal(preview.viewBox, '0 0 1000 620')
  assert.equal(preview.items.length, 3)
  assert.equal(preview.roadItems.length, 2)
  assert.equal(preview.roadItems[0].id, 'road-bottom')
  assert.ok(preview.roadItems[0].path.startsWith('M '))
  assert.ok(preview.roadItems[0].className.includes('is-skeleton'))
  const focusedLoop = preview.items.find((item) => item.id === 'block_loop_01')
  const corridor = preview.items.find((item) => item.id === 'corridor_01')
  const segment = preview.items.find((item) => item.id === 'segment_01')
  assert.equal(focusedLoop.isFocus, true)
  assert.equal(focusedLoop.type, 'block_loop')
  assert.ok(focusedLoop.polygonPath.startsWith('M '))
  assert.ok(focusedLoop.polygonPath.endsWith(' Z'))
  assert.equal(focusedLoop.outlinePath, focusedLoop.polygonPath)
  assert.equal(corridor.type, 'corridor')
  assert.ok(corridor.boundaryPath.startsWith('M '))
  assert.equal(corridor.outlinePath, corridor.boundaryPath)
  assert.equal(segment.type, 'segment')
  assert.ok(segment.boundaryPath.startsWith('M '))
  assert.equal(segment.outlinePath, segment.boundaryPath)
})

test('ppt carrier preview model switches between local and full extents', () => {
  const carriers = [
    {
      carrier_id: 'block_loop_01',
      carrier_type: 'block_loop',
      carrier_label: '成熟商业街区',
      geometry: {
        polygon: [[112.9, 28.2], [112.904, 28.2], [112.904, 28.204], [112.9, 28.204], [112.9, 28.2]],
      },
    },
    {
      carrier_id: 'corridor_01',
      carrier_type: 'corridor',
      carrier_label: '高分通达廊道',
      geometry: {
        boundary: [[112.94, 28.24], [112.945, 28.245]],
      },
    },
  ]
  const roadContext = {
    features: [
      {
        id: 'distant-road',
        path: [[112.86, 28.18], [112.97, 28.27]],
        skeleton_score: 0.38,
      },
    ],
  }

  const localPreview = buildPptCarrierPreviewModel(carriers, {
    focusId: 'block_loop_01',
    extentMode: 'local',
    roadContext,
  })
  const fullPreview = buildPptCarrierPreviewModel(carriers, {
    focusId: 'block_loop_01',
    extentMode: 'all',
    roadContext,
  })
  const localLoop = localPreview.items.find((item) => item.id === 'block_loop_01')
  const fullLoop = fullPreview.items.find((item) => item.id === 'block_loop_01')

  assert.equal(localPreview.extentMode, 'local')
  assert.equal(fullPreview.extentMode, 'all')
  assert.notEqual(localLoop.polygonPath, fullLoop.polygonPath)
  assert.equal(fullPreview.roadItems.length, 1)
})

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

test('agent ppt source refresh adds pending package placeholders without selecting them', async () => {
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
  })

  await ctx.refreshAgentActivePptPlanningDataSources({ autoPackage: false })
  const state = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)
  const packageGroup = state.sourceGroups.find((item) => item.id === 'group:packages')
  const poiPlaceholder = state.sources.find((item) => item.id === 'package-placeholder:poi-evidence')
  const payload = buildPptSpecPayload(state)

  assert.ok(packageGroup)
  assert.ok(packageGroup.sourceIds.includes('package-placeholder:poi-evidence'))
  assert.equal(poiPlaceholder.title, 'POI 资料包')
  assert.equal(poiPlaceholder.status, 'pending')
  assert.equal(poiPlaceholder.selected, false)
  assert.equal(poiPlaceholder.meta.label, '待生成')
  assert.equal(poiPlaceholder.meta.sourceKind, 'package-placeholder')
  assert.equal(payload.source_ids.includes('package-placeholder:poi-evidence'), false)
})

test('ppt outline waits for package placeholders only when their inputs are ready', () => {
  const scopeOnlyState = createPptPlanningState({
    sources: [
      {
        id: 'system:scope',
        type: 'data',
        title: '当前等时圈范围',
        status: 'ready',
        selected: true,
        meta: { sourceKind: 'system' },
      },
      {
        id: 'package-placeholder:poi-evidence',
        type: 'package',
        title: 'POI 资料包',
        status: 'pending',
        selected: false,
        meta: {
          sourceKind: 'package-placeholder',
          package: { source_ids: ['system:poi'] },
        },
      },
    ],
  })
  const readyInputState = createPptPlanningState({
    sources: [
      ...scopeOnlyState.sources,
      {
        id: 'system:poi',
        type: 'data',
        title: 'POI 基础数据',
        status: 'ready',
        selected: true,
        meta: { sourceKind: 'system' },
      },
      {
        id: 'package-placeholder:nightlife-poi',
        type: 'package',
        title: '夜生活 POI × 夜光格子资料包',
        status: 'generating',
        selected: false,
        meta: {
          sourceKind: 'package-placeholder',
          package: { source_ids: ['system:poi'] },
        },
      },
    ],
  })

  assert.deepEqual(getPendingPptPackageSources(scopeOnlyState), [])
  assert.deepEqual(
    getPendingPptPackageSources(readyInputState).map((item) => item.id),
    ['package-placeholder:poi-evidence', 'package-placeholder:nightlife-poi'],
  )
})

test('agent ppt auto package marks placeholder generating then replaces it with real package', async () => {
  let resolvePackage = null
  let requestStartedResolve = null
  const requestStarted = new Promise((resolve) => {
    requestStartedResolve = resolve
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
        pptPlanningState: createPptPlanningState({
          sources: [{
            id: 'system:poi',
            type: 'data',
            title: 'POI 基础数据',
            status: 'ready',
            selected: true,
            meta: { label: 'POI 3996 条', sourceKind: 'system', areaId: 'history-1' },
          }],
        }),
      }],
      deepAnalysisTabs: [],
      followupTabs: [],
    },
    requestAgentPptPlanningDataPackage(payload) {
      requestStartedResolve(payload)
      return new Promise((resolve) => {
        resolvePackage = resolve
      })
    },
  })

  const generation = ctx.autoCreateAgentPptPlanningPoiEvidencePackage({ areaId: 'history-1' })
  const seenPayload = await requestStarted
  const generatingState = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)
  const generatingPlaceholder = generatingState.sources.find((item) => item.id === 'package-placeholder:poi-evidence')

  assert.equal(seenPayload.intent, DEFAULT_PPT_POI_EVIDENCE_INTENT)
  assert.equal(generatingPlaceholder.status, 'generating')
  assert.equal(generatingPlaceholder.meta.label, '整理中')
  assert.equal(generatingPlaceholder.selected, false)
  assert.equal(generatingState.dataPackageGenerating, true)

  resolvePackage({
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
  await generation
  const finalState = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)
  const packageSource = finalState.sources.find((item) => item.id === 'package:poi:auto')

  assert.equal(finalState.sources.some((item) => item.id === 'package-placeholder:poi-evidence'), false)
  assert.equal(packageSource.selected, true)
  assert.equal(packageSource.meta.sourceKind, 'package')
  assert.equal(finalState.dataPackageGenerating, false)
})

test('agent ppt auto package payload uses current isochrone center', async () => {
  let seenPayload = null
  const ctx = createPptPlanningTestContext({
    selectedPoint: { lng: 112.982315, lat: 28.194672 },
    timeHorizon: 30,
    transportMode: 'bicycling',
    agentTabs: {
      activeTabId: 'ppt-1',
      summaryTabs: [],
      iterationChangeTabs: [],
      siteSelectionTabs: [],
      pptPlanningTabs: [{
        id: 'ppt-1',
        kind: 'ppt_planning',
        source: 'current',
        pptPlanningState: createPptPlanningState({
          sources: [{
            id: 'system:poi',
            type: 'data',
            title: 'POI 基础数据',
            status: 'ready',
            selected: true,
            meta: { label: 'POI 3996 条', sourceKind: 'system', areaId: 'history-1' },
          }],
        }),
      }],
      deepAnalysisTabs: [],
      followupTabs: [],
    },
    normalizeAgentSiteSelectionScope() {
      return {
        polygon: [[113.4, 29.2], [113.5, 29.2], [113.5, 29.3], [113.4, 29.2]],
        drawnPolygon: [],
        isochroneFeature: {
          type: 'Feature',
          properties: { center: [113.45, 29.25], radius_m: 9999 },
          geometry: { type: 'Polygon', coordinates: [] },
        },
      }
    },
    requestAgentPptPlanningDataPackage(payload) {
      seenPayload = payload
      return Promise.resolve({
        source: {
          id: 'package:poi:auto-current-center',
          type: 'package',
          title: 'POI 资料包',
          status: 'ready',
          selected: true,
          meta: {
            label: 'POI 1 条',
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

  await ctx.autoCreateAgentPptPlanningPoiEvidencePackage({ areaId: 'history-1' })

  assert.deepEqual(seenPayload.center, [112.982315, 28.194672])
  assert.equal(seenPayload.center_coord_type, 'gcj02')
  assert.equal(seenPayload.radius_m, 9999)
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

test('ppt planning reset helpers clear downstream generated sections', () => {
  const directiveState = applyDeckBriefResponse(applyPptSpecResponse(createPptPlanningState(), {
    title: 'AI 生成目录',
    page_count: 1,
    outline: [
      { id: 'page-1', page_no: 1, theme: '项目命题', purpose: '建立汇报主线' },
    ],
  }), {
    slides: [
      { index: 1, title: '旧指令', purpose: '旧目的' },
    ],
  })

  const outlineReady = resetPptPlanningToOutlineReady(directiveState)
  assert.equal(outlineReady.currentStep, 'outline_ready')
  assert.equal(outlineReady.outline.length, 1)
  assert.equal(outlineReady.spec.outline.length, 1)
  assert.notEqual(outlineReady.deckBrief.slides[0].title, '旧指令')

  const materials = resetPptPlanningToMaterials(directiveState)
  assert.equal(materials.currentStep, 'materials')
  assert.deepEqual(materials.outline, [])
  assert.deepEqual(materials.spec.outline, [])
  assert.notEqual(materials.deckBrief.slides[0].title, '旧指令')
})

test('ppt outline section revision marks directive stale and supports one-step undo', () => {
  const state = applyDeckBriefResponse(applyPptSpecResponse(createPptPlanningState(), {
    title: 'AI 生成目录',
    page_count: 2,
    outline: [
      { id: 'page-1', page_no: 1, theme: '项目命题', purpose: '建立汇报主线' },
      { id: 'page-2', page_no: 2, theme: '空间证据', purpose: '说明现状' },
    ],
  }), {
    slides: [
      { index: 1, title: '项目命题', purpose: '建立汇报主线' },
      { index: 2, title: '空间证据', purpose: '说明现状' },
    ],
  })

  const revised = applyPptOutlineSectionRevision(state, {
    id: 'page-2',
    pageNo: 2,
    theme: '空间问题诊断',
    purpose: '突出问题判断',
  })

  assert.equal(revised.outline[1].theme, '空间问题诊断')
  assert.deepEqual(revised.staleDirectivePageIds, ['2'])
  assert.ok(revised.revisionSnapshots['outline:page-2'])

  const undone = undoPptSectionRevision(revised, 'outline', { id: 'page-2', pageNo: 2 })
  assert.equal(undone.outline[1].theme, '空间证据')
  assert.deepEqual(undone.staleDirectivePageIds, [])
  assert.equal(Boolean(undone.revisionSnapshots['outline:page-2']), false)
})

test('ppt directive slide revision clears stale flag and supports undo', () => {
  const state = createPptPlanningState({
    currentStep: 'directive_draft',
    outline: [
      { id: 'page-1', page_no: 1, theme: '项目命题', purpose: '建立汇报主线' },
    ],
    deckBrief: {
      status: 'draft',
      slides: [
        { index: 1, title: '项目命题', purpose: '建立汇报主线', required_sources: ['system:scope'] },
      ],
    },
    staleDirectivePageIds: ['1'],
  })

  const revised = applyDeckBriefSlideRevision(state, {
    index: 1,
    title: '项目命题重写',
    purpose: '更聚焦评审',
    keyMessage: '解释更新必要性',
    visualPlan: '区域底图',
    requiredSources: ['system:scope'],
    speakerNotes: '讲清楚背景。',
  })

  assert.equal(revised.deckBrief.slides[0].title, '项目命题重写')
  assert.deepEqual(revised.staleDirectivePageIds, [])
  assert.ok(revised.revisionSnapshots['slide:1'])

  const undone = undoPptSectionRevision(revised, 'directive', { index: 1 })
  assert.equal(undone.deckBrief.slides[0].title, '项目命题')
  assert.equal(Boolean(undone.revisionSnapshots['slide:1']), false)
})

test('ppt directive undo locates the edited current slide by target', () => {
  const state = createPptPlanningState({
    currentStep: 'directive_draft',
    deckBrief: {
      status: 'draft',
      slides: [
        {
          index: 1,
          title: '项目命题',
          purpose: '建立汇报主线',
          keyMessage: '解释更新必要性',
          visualPlan: '区域底图',
          required_sources: ['system:scope'],
          speakerNotes: '讲清楚背景。',
        },
      ],
    },
  })

  const revised = applyDeckBriefSlideRevision(state, {
    index: 1,
    title: '项目命题',
    purpose: '建立汇报主线',
    keyMessage: '解释更新必要性',
    visualPlan: '11',
    requiredSources: ['system:scope'],
    speakerNotes: '讲清楚背景。',
  })

  const undone = undoPptSectionRevision(revised, 'directive', { index: 1 })

  assert.equal(revised.deckBrief.slides[0].visualPlan, '11')
  assert.equal(undone.deckBrief.slides[0].visualPlan, '区域底图')
  assert.equal(Boolean(undone.revisionSnapshots['slide:1']), false)
})

test('ppt revision drafts and section payloads keep single target context', () => {
  const outlineReady = applyPptSpecResponse(createPptPlanningState(), {
    title: 'AI 生成目录',
    page_count: 1,
    outline: [
      { id: 'page-1', page_no: 1, theme: '项目命题', purpose: '建立汇报主线' },
    ],
  })
  const opened = setPptActiveRevisionTarget(outlineReady, { type: 'outline', id: 'page-1', pageNo: 1 })
  const drafted = setPptRevisionDraftField(opened, 'outline', 'revisionNote', '更强调评审价值')
  const payload = buildPptOutlineSectionPayload(drafted, drafted.activeRevisionTarget, drafted.outlineRevisionDraft.revisionNote, {
    areaId: 'history-1',
    analysisContext: { scope: { time_min: 35 } },
  })

  assert.equal(drafted.outlineRevisionDraft.theme, '项目命题')
  assert.equal(payload.area_id, 'history-1')
  assert.equal(payload.target.id, 'page-1')
  assert.equal(payload.revision_note, '更强调评审价值')

  const withSlide = applyDeckBriefResponse(outlineReady, {
    slides: [{ index: 1, title: '项目命题', purpose: '建立汇报主线', required_sources: ['system:scope'] }],
  })
  const slidePayload = buildDeckBriefSlidePayload(withSlide, { index: 1 }, '重写这一页', {
    areaId: 'history-1',
    analysisContext: { scope: { time_min: 35 } },
  })

  assert.equal(slidePayload.target.index, 1)
  assert.equal(slidePayload.outline_item.page_no, 1)
  assert.equal(slidePayload.revision_note, '重写这一页')
})

test('ppt planning errors keep their operation source', () => {
  const packageErrorState = setPptGenerationError(createPptPlanningState(), 'Internal Server Error', 'data_package')
  const outlineErrorState = setPptGenerationError(createPptPlanningState(), 'ppt_planning_llm_unavailable', 'outline')

  assert.equal(packageErrorState.generationError, 'Internal Server Error')
  assert.equal(packageErrorState.generationErrorSource, 'data_package')
  assert.equal(outlineErrorState.generationError, 'ppt_planning_llm_unavailable')
  assert.equal(outlineErrorState.generationErrorSource, 'outline')
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

test('agent ppt regenerate outline confirms and clears downstream output', async () => {
  const methods = createAgentPptPlanningTabMethods()
  let outlineCalls = 0
  let directiveCalls = 0
  const initialState = applyDeckBriefResponse(applyPptSpecResponse(createPptPlanningState(), {
    title: '旧目录',
    page_count: 1,
    outline: [
      { id: 'page-1', page_no: 1, theme: '旧目录页', purpose: '旧目录目的' },
    ],
  }), {
    slides: [
      { index: 1, title: '旧指令', purpose: '旧指令目的' },
    ],
  })
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
        pptPlanningState: initialState,
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
    confirmPptPlanningStepReset() {
      return true
    },
    requestAgentPptPlanningOutline() {
      outlineCalls += 1
      return Promise.resolve({
        title: '新目录',
        page_count: 1,
        outline: [
          { id: 'page-1', page_no: 1, theme: '新目录页', purpose: '新目录目的' },
        ],
      })
    },
    requestAgentPptPlanningDirective() {
      directiveCalls += 1
      return Promise.resolve({ slides: [{ index: 1, title: '不应调用' }] })
    },
    syncCurrentAgentSession() {},
  }

  await ctx.regenerateAgentPptPlanningOutlineWithConfirm()
  const state = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)

  assert.equal(outlineCalls, 1)
  assert.equal(directiveCalls, 0)
  assert.equal(state.currentStep, 'outline_ready')
  assert.equal(state.outline[0].theme, '新目录页')
  assert.notEqual(state.deckBrief.slides[0].title, '旧指令')
})

test('agent ppt regenerate directive confirms and keeps outline', async () => {
  const methods = createAgentPptPlanningTabMethods()
  let directiveCalls = 0
  const initialState = applyDeckBriefResponse(applyPptSpecResponse(createPptPlanningState(), {
    title: '目录',
    page_count: 1,
    outline: [
      { id: 'page-1', page_no: 1, theme: '保留目录页', purpose: '目录目的' },
    ],
  }), {
    slides: [
      { index: 1, title: '旧指令', purpose: '旧指令目的' },
    ],
  })
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
        pptPlanningState: initialState,
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
    confirmPptPlanningStepReset() {
      return true
    },
    requestAgentPptPlanningDirective() {
      directiveCalls += 1
      return Promise.resolve({
        status: 'draft',
        slides: [
          { index: 1, title: '新指令', purpose: '新指令目的' },
        ],
      })
    },
    syncCurrentAgentSession() {},
  }

  await ctx.regenerateAgentPptPlanningDirectiveWithConfirm()
  const state = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)

  assert.equal(directiveCalls, 1)
  assert.equal(state.currentStep, 'directive_draft')
  assert.equal(state.outline[0].theme, '保留目录页')
  assert.equal(state.deckBrief.slides[0].title, '新指令')
})

test('agent ppt regenerate cancellation keeps generated state unchanged', async () => {
  const methods = createAgentPptPlanningTabMethods()
  let outlineCalls = 0
  const initialState = applyDeckBriefResponse(applyPptSpecResponse(createPptPlanningState(), {
    title: '旧目录',
    page_count: 1,
    outline: [
      { id: 'page-1', page_no: 1, theme: '旧目录页', purpose: '旧目录目的' },
    ],
  }), {
    slides: [
      { index: 1, title: '旧指令', purpose: '旧指令目的' },
    ],
  })
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
        pptPlanningState: initialState,
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
    confirmPptPlanningStepReset() {
      return false
    },
    requestAgentPptPlanningOutline() {
      outlineCalls += 1
      return Promise.resolve({ outline: [] })
    },
    syncCurrentAgentSession() {},
  }

  await ctx.regenerateAgentPptPlanningOutlineWithConfirm()
  const state = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)

  assert.equal(outlineCalls, 0)
  assert.equal(state.currentStep, 'directive_draft')
  assert.equal(state.outline[0].theme, '旧目录页')
  assert.equal(state.deckBrief.slides[0].title, '旧指令')
})

test('agent ppt revision actions replace only the active section', async () => {
  const methods = createAgentPptPlanningTabMethods()
  const initialState = applyDeckBriefResponse(applyPptSpecResponse(createPptPlanningState(), {
    title: 'AI 生成目录',
    page_count: 2,
    outline: [
      { id: 'page-1', page_no: 1, theme: '项目命题', purpose: '建立汇报主线' },
      { id: 'page-2', page_no: 2, theme: '空间证据', purpose: '说明现状' },
    ],
  }), {
    slides: [
      { index: 1, title: '项目命题', purpose: '建立汇报主线' },
      { index: 2, title: '空间证据', purpose: '说明现状' },
    ],
  })
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
        pptPlanningState: initialState,
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
      return { polygon: [[0, 0], [1, 0], [1, 1]], drawnPolygon: [], isochroneFeature: null }
    },
    requestAgentPptPlanningOutlineSection(payload) {
      assert.equal(payload.target.id, 'page-2')
      assert.equal(payload.revision_note, '更像问题诊断')
      return Promise.resolve({ id: 'page-2', page_no: 2, theme: '空间问题诊断', purpose: '突出问题' })
    },
    requestAgentPptPlanningDirectiveSlide(payload) {
      assert.equal(payload.target.index, 2)
      assert.equal(payload.revision_note, '重写为诊断页')
      return Promise.resolve({
        index: 2,
        title: '空间问题诊断',
        purpose: '突出问题',
        key_message: '说明空间矛盾',
        visual_plan: '诊断图',
        required_sources: ['system:scope'],
        speaker_notes: '讲清楚问题。',
      })
    },
    syncCurrentAgentSession() {},
  }

  ctx.openAgentPptPlanningRevisionTarget('outline', { id: 'page-2', pageNo: 2 })
  ctx.updateAgentPptPlanningRevisionDraft('outline', 'revisionNote', '更像问题诊断')
  await ctx.regenerateAgentPptPlanningRevision('outline')
  let state = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)

  assert.equal(state.outline[0].theme, '项目命题')
  assert.equal(state.outline[1].theme, '空间问题诊断')
  assert.deepEqual(state.staleDirectivePageIds, ['2'])

  ctx.openAgentPptPlanningRevisionTarget('directive', { index: 2, pageNo: 2 })
  ctx.updateAgentPptPlanningRevisionDraft('directive', 'revisionNote', '重写为诊断页')
  await ctx.regenerateAgentPptPlanningRevision('directive')
  state = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)

  assert.equal(state.deckBrief.slides[0].title, '项目命题')
  assert.equal(state.deckBrief.slides[1].title, '空间问题诊断')
  assert.deepEqual(state.staleDirectivePageIds, [])
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

test('agent ppt refresh auto creates road carrier package when four evidence sources are ready', async () => {
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
          id: 'system:road-syntax',
          type: 'data',
          title: '路网与可达性分析',
          status: 'ready',
          summary: '已生成',
          count: 1,
          meta: { label: '已生成', sourceKind: 'system', areaId },
        },
        {
          id: 'system:population',
          type: 'data',
          title: '人口结构分析',
          status: 'ready',
          summary: '已生成',
          count: 1,
          meta: { label: '已生成', sourceKind: 'system', areaId },
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
      const isCarrier = payload.intent === DEFAULT_PPT_CARRIER_EVIDENCE_INTENT
      return Promise.resolve({
        source: {
          id: isCarrier ? 'package:poi-road-carriers:auto' : `package:auto:${packagePayloads.length}`,
          type: 'package',
          title: isCarrier ? 'POI × 路网空间载体资料包' : '资料包',
          status: 'ready',
          selected: true,
          meta: {
            label: isCarrier ? '空间载体 3 个' : '自动资料包',
            sourceKind: 'package',
            package: {
              package_mode: 'evidence',
              intent: payload.intent,
              source_ids: payload.source_ids,
              carriers: isCarrier ? [
                { carrier_id: 'block_loop_01', carrier_type: 'block_loop' },
                { carrier_id: 'corridor_01', carrier_type: 'corridor' },
                { carrier_id: 'segment_01', carrier_type: 'segment' },
              ] : [],
              items: [],
            },
          },
        },
      })
    },
  })

  await ctx.refreshAgentActivePptPlanningDataSources()
  const state = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)
  const carrierPayload = packagePayloads.find((payload) => payload.intent === DEFAULT_PPT_CARRIER_EVIDENCE_INTENT)
  const carrierPackage = state.sources.find((item) => item.id === 'package:poi-road-carriers:auto')

  assert.ok(carrierPayload)
  assert.deepEqual(carrierPayload.source_ids, ['system:poi', 'system:road-syntax', 'system:population', 'system:nightlight'])
  assert.equal(carrierPayload.package_mode, 'evidence')
  assert.equal(carrierPayload.limit, 50)
  assert.equal(carrierPackage.selected, true)
  assert.equal(carrierPackage.meta.areaId, 'history-1')
  assert.equal(carrierPackage.meta.autoGenerated, true)
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
  assert.equal(state.generationErrorSource, 'data_package')
  assert.equal(state.dataPackageGenerating, false)
})
