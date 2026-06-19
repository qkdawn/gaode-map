import test from 'node:test'
import assert from 'node:assert/strict'

import {
  createAgentTabsMethods,
} from '../src/features/agent/tabs.js'
import {
  createDefaultDeckBriefPreview,
  createPptSystemSources,
  normalizeDeckBrief,
  normalizeDeckSlideBrief,
  normalizeNarrativePlan,
} from '../src/features/ppt-planning/model.js'
import {
  buildPptCarrierPreviewModel,
  normalizePptPackageDetail,
} from '../src/features/ppt-planning/carrier-preview.js'
import { createAgentPptPlanningTabMethods } from '../src/features/agent/ppt-planning-tabs.js'
import { createAgentRuntimeMethods } from '../src/features/agent/runtime.js'
import { regenerateDeckBriefSlide } from '../src/features/ppt-planning/api.js'
import {
  MAP_LAYER_RENDERERS,
  capturePptMapRequestAsset,
  isPptMapSnapshotRequest,
} from '../src/features/ppt-planning/map-snapshot.js'
import {
  capturePptCarrierSnapshotAsset,
  isPptCarrierSnapshotRequest,
} from '../src/features/ppt-planning/carrier-snapshot.js'

import {
  applyDeckBriefResponse,
  applyDirectiveResponseAndMarkReady,
  applySlideResponseAndMarkReady,
  applyPptVisualArtifactsResponse,
  applyNarrativePlanResponse,
  applyPptSpecResponse,
  applyPptSourceGroupsResponse,
  addPptDataPackageSource,
  applyDeckBriefSlideRevision,
  applyPptOutlineSectionRevision,
  buildDeckBriefPayload,
  buildDeckBriefSlidePayload,
  buildPptVisualArtifactsPayload,
  buildNarrativePlanPayload,
  buildPptOutlineSectionPayload,
  buildPptSpecPayload,
  clearPptSlideMapSnapshotCaptureErrors,
  collectPptVisualArtifactFilenames,
  createPptPlanningState,
  failPptVisualArtifacts,
  getActiveDeckSlideBrief,
  getBlockingPptInputSources,
  hasPptBlockingInputs,
  getPendingPptPackageSources,
  getPptPromptActions,
  getPptSourceDeliveryManifest,
  getPptSourceSummary,
  markSlideApplying,
  markSlideFailed,
  markSlideGenerationPageActive,
  markSlideRequestStarted,
  markSlideResponseReceived,
  markSlideTimedOut,
  markPptDirectiveStaleForSources,
  mergePptPlanningSources,
  movePptSourceToGroup,
  removePptSource,
  removePptSourceGroup,
  resetPptPlanningToMaterials,
  resetPptPlanningToNarrativeReady,
  resetPptPlanningToOutlineReady,
  startPptVisualArtifactsGeneration,
  startPptGenerationJob,
  startSlideGenerationQueue,
  setAllPptSourcesSelected,
  setPptGenerationError,
  setPptSourceRefreshing,
  setPptActiveRevisionTarget,
  setPptRevisionDraftField,
  setPptSourceGroupSelected,
  togglePptSourceSelection,
  undoPptSectionRevision,
} from '../src/features/ppt-planning/ui-state.js'

const DEFAULT_PPT_POI_EVIDENCE_INTENT = '为 PPT 指令生成整理当前区域代表性 POI 资料'
const DEFAULT_PPT_NIGHTLIFE_POI_INTENT = '整理夜生活与夜间消费相关 POI，并与夜光格子对应'
const DEFAULT_PPT_CARRIER_EVIDENCE_INTENT = '识别当前区域 POI、路网、人口、夜光共同支撑的空间载体'

test('ppt normalizeDeckBrief keeps empty responses empty', () => {
  const brief = normalizeDeckBrief({})
  assert.equal(brief.status, 'draft')
  assert.deepEqual(brief.slides, [])
})

test('ppt narrative plan and slide queue feed single slide payloads', () => {
  let state = createPptPlanningState({
    sources: [
      {
        id: 'current:scope',
        title: '当前等时圈范围',
        type: 'data',
        status: 'ready',
        selected: true,
        meta: {
          aiPayload: {
            included: ['scope'],
            scope: { area_name: '测试范围' },
            counts: { scope: 1 },
          },
        },
      },
    ],
  })
  state = applyPptSpecResponse(state, {
    title: '测试目录',
    goal: '测试',
    audience: '政府评审',
    deck_type: '城市更新概念策划',
    page_count: 2,
    outline: [
      { id: 'p1', page_no: 1, theme: '开场', purpose: '建立问题' },
      { id: 'p2', page_no: 2, theme: '证据', purpose: '说明判断' },
    ],
  })
  const narrativePayload = buildNarrativePlanPayload(state, { areaId: 'area-1' })
  assert.equal(narrativePayload.outline.length, 2)
  state = applyNarrativePlanResponse(state, {
    storyline: '问题界定到决策请示',
    chapters: [
      { name: '开篇定调', page_range: '01', job: '建立问题', output: '明确主线' },
      { name: '结构诊断', page_range: '02', job: '说明判断', output: '形成结论' },
    ],
    evidence_buckets: [
      { id: 'scope', label: '范围', allowed_sources: ['current:scope'] },
      { id: 'metrics', label: '指标', allowed_sources: ['current:scope'] },
    ],
    slide_roles: [
      { page_no: 1, role: '开题', job: '建立问题', evidence_bucket: 'scope', visual_family: 'existing_map_layer' },
      { page_no: 2, role: '证据页', job: '说明判断', evidence_bucket: 'metrics', visual_family: 'dashboard' },
    ],
    visual_rules: {
      spatial_first: true,
      numeric_charts_require_data: true,
      diagram_for_strategy_pages: true,
      no_fallback_bar: true,
    },
    context_manifest: {
      metric_context: {
        metrics: [{ metric_id: 'analysis:test:large', description: 'x'.repeat(10_000) }],
      },
      evidence_context: {
        items: [{ text: 'y'.repeat(10_000) }],
      },
    },
  })
  state = startSlideGenerationQueue(state)
  assert.equal(state.currentStep, 'slides_generating')
  state = markSlideRequestStarted(state, 1, 'req-1')
  assert.equal(state.slideGenerationQueue[0].status, 'requesting')
  const slidePayload = buildDeckBriefSlidePayload(state, { index: 1 }, '生成第一页', { areaId: 'area-1' })
  assert.equal(slidePayload.narrative_plan.slide_roles.length, 2)
  assert.equal(Object.hasOwn(slidePayload.narrative_plan, 'context_manifest'), false)
  assert.equal(Object.hasOwn(slidePayload.narrative_plan, 'style_guide'), false)
  assert.equal(Object.hasOwn(slidePayload.narrative_plan, 'evidence_strategy'), false)
  assert.equal(Object.hasOwn(slidePayload.narrative_plan, 'chart_strategy'), false)
  assert.equal(slidePayload.narrative_plan.slide_roles[1].evidence_bucket, 'metrics')
  assert.equal(slidePayload.narrative_plan.slide_roles[1].visual_family, 'dashboard')
  assert.equal(slidePayload.target.index, 1)
  state = markSlideResponseReceived(state, 1, 'req-1', { responseIndex: 1 })
  state = markSlideApplying(state, 1, 'req-1')
  state = applySlideResponseAndMarkReady(state, 1, 'req-1', { index: 1, title: '开场', purpose: '建立问题' })
  assert.equal(state.deckBrief.slides.length, 1)
  assert.equal(state.slideGenerationQueue[0].status, 'ready')
  assert.equal(state.slideGenerationQueue[1].status, 'pending')
  const secondPayload = buildDeckBriefSlidePayload(state, { index: 2 }, '生成第二页', { areaId: 'area-1' })
  assert.equal(secondPayload.page_no, 2)
  assert.match(secondPayload.context_id, /^ppt-brief-/)
  assert.deepEqual(secondPayload.slides, [])
  assert.equal(secondPayload.previous_slide_summary.index, 1)
  assert.equal(secondPayload.previous_slide_summary.title, '开场')
  assert.equal(secondPayload.deck_progress_summary.page_count, 2)
  assert.deepEqual(secondPayload.deck_progress_summary.generated_pages, [1])
})

test('ppt narrative plan normalizer preserves structured narrative fields for display', () => {
  const plan = normalizeNarrativePlan({
    storyline: '从问题到证据',
    chapters: [
      { name: '开篇定调', page_range: '01', job: '建立问题', output: '明确主线' },
    ],
    evidence_buckets: [
      { id: 'scope_population', label: '范围与人口底座', allowed_sources: ['current:scope'] },
    ],
    slide_roles: [
      {
        page_no: 2,
        role: '空间底座',
        job: '说明研究边界',
        evidence_bucket: 'scope_population',
        visual_family: 'map_metric_card',
        transition_note: '承接诊断页',
      },
    ],
    visual_rules: {
      spatial_first: true,
      numeric_charts_require_data: true,
      diagram_for_strategy_pages: true,
      no_fallback_bar: true,
    },
  })

  assert.equal(plan.storyline, '从问题到证据')
  assert.equal(plan.chapters[0].name, '开篇定调')
  assert.equal(plan.chapters[0].job, '建立问题')
  assert.equal(plan.slideRoles[0].pageNo, 2)
  assert.equal(plan.slideRoles[0].evidenceBucket, 'scope_population')
  assert.equal(plan.slideRoles[0].visualFamily, 'map_metric_card')
  assert.equal(plan.evidenceBuckets[0].id, 'scope_population')
  assert.equal(plan.visualRules.noFallbackBar, true)
})

test('ppt slide queue tracks active page timing and preserves briefs after failure', () => {
  let state = createPptPlanningState()
  state = applyPptSpecResponse(state, {
    title: '测试目录',
    page_count: 2,
    outline: [
      { id: 'p1', page_no: 1, theme: '开场', purpose: '建立问题' },
      { id: 'p2', page_no: 2, theme: '证据', purpose: '说明判断' },
    ],
  })
  state = applyNarrativePlanResponse(state, {
    storyline: '从问题到证据',
    slide_roles: [
      { page_no: 1, role: '开题', job: '建立问题' },
      { page_no: 2, role: '证据页', job: '说明判断' },
    ],
  })

  state = startSlideGenerationQueue(state)
  state = markSlideRequestStarted(state, 1, 'req-1')
  assert.equal(state.slideGenerationJob.currentPageNo, 1)
  assert.ok(state.slideGenerationJob.activePageStartedAt)

  state = markSlideResponseReceived(state, 1, 'req-1', { responseIndex: 1 })
  state = markSlideApplying(state, 1, 'req-1')
  state = applySlideResponseAndMarkReady(state, 1, 'req-1', {
    index: 1,
    title: '开场',
    purpose: '建立问题',
    key_message: '问题成立',
  })
  assert.equal(state.deckBrief.slides.length, 1)
  assert.equal(state.slideGenerationJob.currentPageNo, 2)
  assert.equal(state.slideGenerationQueue[1].status, 'pending')

  state = markSlideFailed(state, 2, '', '第 2 页 brief JSON 格式错误', 'http_error')
  assert.equal(state.deckBrief.slides.length, 1)
  assert.equal(state.slideGenerationJob.active, false)
  assert.equal(state.slideGenerationJob.failedPageNo, 2)
  assert.equal(state.slideGenerationJob.activePageStartedAt, '')
  assert.equal(state.slideGenerationQueue[1].status, 'failed')
})

test('ppt slide writeback failure keeps brief workspace visible', () => {
  let state = createPptPlanningState()
  state = applyPptSpecResponse(state, {
    outline: [
      { id: 'p1', page_no: 1, theme: '开场', purpose: '建立问题' },
      { id: 'p2', page_no: 2, theme: '证据', purpose: '说明判断' },
    ],
  })
  state = applyNarrativePlanResponse(state, {
    storyline: '从问题到证据',
    slide_roles: [
      { page_no: 1, role: '开题', job: '建立问题' },
      { page_no: 2, role: '证据页', job: '说明判断' },
    ],
  })
  state = startSlideGenerationQueue(state)

  state = markSlideFailed(state, 1, '', '第 1 页已返回但未写入前端状态', 'writeback_lost')

  assert.equal(state.currentStep, 'slides_generating')
  assert.equal(state.slideGenerationJob.active, false)
  assert.equal(state.slideGenerationJob.failedPageNo, 1)
  assert.equal(state.slideGenerationQueue[0].status, 'failed')
  assert.match(state.generationError, /未写入前端状态/)
})

test('ppt slide queue can mark each requested page active before the response returns', () => {
  let state = createPptPlanningState()
  state = applyPptSpecResponse(state, {
    outline: [
      { id: 'p1', page_no: 1, theme: '开场', purpose: '建立问题' },
      { id: 'p2', page_no: 2, theme: '证据', purpose: '说明判断' },
      { id: 'p3', page_no: 3, theme: '策略', purpose: '给出路径' },
    ],
  })
  state = applyNarrativePlanResponse(state, {
    storyline: '从问题到证据',
    slide_roles: [
      { page_no: 1, role: '开题', job: '建立问题' },
      { page_no: 2, role: '证据页', job: '说明判断' },
      { page_no: 3, role: '策略页', job: '给出路径' },
    ],
  })
  state = startSlideGenerationQueue(state)
  state = markSlideRequestStarted(state, 1, 'req-1')
  state = applySlideResponseAndMarkReady(state, 1, 'req-1', { index: 1, title: '开场', purpose: '建立问题', key_message: '问题成立' })

  state = markSlideGenerationPageActive(state, 3)

  assert.equal(state.currentStep, 'slides_generating')
  assert.equal(state.slideGenerationJob.active, true)
  assert.equal(state.slideGenerationJob.currentPageNo, 3)
  assert.ok(state.slideGenerationJob.activePageStartedAt)
  assert.deepEqual(state.slideGenerationQueue.map((item) => item.status), ['ready', 'pending', 'requesting'])
})

test('ppt slide queue marks timeout and ignores stale response ids', () => {
  let state = createPptPlanningState()
  state = applyPptSpecResponse(state, {
    outline: [
      { id: 'p1', page_no: 1, theme: '开场', purpose: '建立问题' },
      { id: 'p2', page_no: 2, theme: '证据', purpose: '说明判断' },
    ],
  })
  state = applyNarrativePlanResponse(state, {
    storyline: '从问题到证据',
    slide_roles: [
      { page_no: 1, role: '开题', job: '建立问题' },
      { page_no: 2, role: '证据页', job: '说明判断' },
    ],
  })
  state = startSlideGenerationQueue(state)
  state = markSlideRequestStarted(state, 1, 'req-live')

  const stale = markSlideResponseReceived(state, 1, 'req-old', { responseIndex: 1 })
  assert.equal(stale.slideGenerationQueue[0].status, 'requesting')
  assert.ok(stale.generationJob.events.find((event) => event.name === 'stale_slide_response_ignored'))

  const timedOut = markSlideTimedOut(state, 1, 'req-live')
  assert.equal(timedOut.slideGenerationQueue[0].status, 'timed_out')
  assert.equal(timedOut.slideGenerationQueue[0].errorKind, 'timeout')
  assert.equal(timedOut.slideGenerationJob.status, 'failed')
  assert.equal(timedOut.slideGenerationJob.failedPageNo, 1)
  assert.match(timedOut.generationError, /请求超时/)
})

function createPptStateWithOutlineNarrativeAndSlides() {
  let state = createPptPlanningState({
    sources: [
      {
        id: 'current:scope',
        title: '当前范围',
        type: 'data',
        status: 'ready',
        selected: true,
        meta: { aiPayload: { included: ['scope'], counts: { scope: 1 } } },
      },
    ],
  })
  state = applyPptSpecResponse(state, {
    title: '测试目录',
    page_count: 2,
    audience: '政府评审',
    outline: [
      { id: 'p1', page_no: 1, theme: '开场', purpose: '建立问题' },
      { id: 'p2', page_no: 2, theme: '证据', purpose: '说明判断' },
    ],
  })
  state = applyNarrativePlanResponse(state, {
    storyline: '从问题到证据',
    slide_roles: [
      { page_no: 1, role: '开题', job: '建立问题' },
      { page_no: 2, role: '证据页', job: '说明判断' },
    ],
  })
  state = markSlideRequestStarted(state, 1, 'req-1')
  return applySlideResponseAndMarkReady(state, 1, 'req-1', { index: 1, title: '开场', purpose: '建立问题' })
}

test('ppt reset to narrative ready keeps outline and narrative but clears generated briefs', () => {
  const state = createPptStateWithOutlineNarrativeAndSlides()
  const reset = resetPptPlanningToNarrativeReady(startSlideGenerationQueue(state))

  assert.equal(reset.currentStep, 'narrative_ready')
  assert.equal(reset.outline.length, 2)
  assert.equal(reset.narrativePlan.slideRoles.length, 2)
  assert.deepEqual(reset.deckBrief.slides, [])
  assert.deepEqual(reset.slideGenerationQueue, [])
  assert.equal(reset.slideGenerationJob.active, false)
  assert.equal(reset.slideGenerationJob.currentPageNo, 0)
})

test('ppt reset to outline ready clears narrative plan and downstream briefs', () => {
  const state = createPptStateWithOutlineNarrativeAndSlides()
  const reset = resetPptPlanningToOutlineReady(state)

  assert.equal(reset.currentStep, 'outline_ready')
  assert.equal(reset.outline.length, 2)
  assert.equal(reset.narrativePlan.slideRoles.length, 0)
  assert.deepEqual(reset.deckBrief.slides, [])
  assert.deepEqual(reset.slideGenerationQueue, [])
})

test('ppt prompt actions expose only the current stage actions', () => {
  const empty = createPptPlanningState()
  assert.deepEqual(getPptPromptActions(empty).map((item) => item.event), ['generate-outline'])

  const outlineReady = applyPptSpecResponse(createPptPlanningState(), {
    outline: [{ id: 'p1', page_no: 1, theme: '开场', purpose: '建立问题' }],
  })
  assert.deepEqual(getPptPromptActions(outlineReady).map((item) => item.event), ['generate-narrative-plan', 'regenerate-outline'])

  const narrativeReady = applyNarrativePlanResponse(outlineReady, {
    slide_roles: [{ page_no: 1, role: '开题', job: '建立问题' }],
  })
  assert.deepEqual(getPptPromptActions(narrativeReady).map((item) => item.event), ['generate-slides', 'regenerate-narrative-plan'])

  const failedSlides = {
    ...startSlideGenerationQueue(narrativeReady),
    slideGenerationJob: { failedPageNo: 1 },
  }
  assert.equal(getPptPromptActions(failedSlides)[0].label, '生成 brief')

  const started = markSlideRequestStarted(startSlideGenerationQueue(narrativeReady), 1, 'req-1')
  const briefReady = applySlideResponseAndMarkReady(started, 1, 'req-1', { index: 1, title: '开场', purpose: '建立问题' })
  assert.deepEqual(getPptPromptActions(briefReady).map((item) => item.event), ['regenerate-slides'])
  assert.equal(getPptPromptActions(briefReady)[0].label, '重新生成 brief')
})

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

test('ppt package detail normalizer tolerates null and missing fields', () => {
  const detail = normalizePptPackageDetail(null)

  assert.deepEqual(detail.payload, {})
  assert.equal(detail.title, '')
  assert.equal(detail.summary, '')
  assert.deepEqual(detail.items, [])
  assert.deepEqual(detail.carriers, [])
  assert.deepEqual(detail.previewCarriers, [])
  assert.deepEqual(detail.previewRoads, [])
  assert.deepEqual(detail.evidenceRefs, [])
  assert.deepEqual(detail.warnings, [])
  assert.deepEqual(detail.alignment, {})
  assert.deepEqual(detail.carrierSummary, {})
  assert.deepEqual(detail.sourceIds, [])
})

test('ppt package detail normalizer keeps stable arrays with partial payloads', () => {
  const detail = normalizePptPackageDetail({
    title: '资料包',
    meta: {
      package: {
        summary: '摘要',
        items: null,
        carriers: undefined,
        evidence_refs: ['证据 1'],
        warnings: ['缺少载体'],
      },
    },
  })

  assert.equal(detail.title, '资料包')
  assert.equal(detail.summary, '摘要')
  assert.deepEqual(detail.items, [])
  assert.deepEqual(detail.carriers, [])
  assert.deepEqual(detail.evidenceRefs, ['证据 1'])
  assert.deepEqual(detail.warnings, ['缺少载体'])
})

test('ppt slide normalizer keeps metric claims and visual specs', () => {
  const slide = normalizeDeckSlideBrief({
    index: 2,
    title: '空间诊断',
    insight: '这说明片区不是单点优势，而是具备成片承接条件。',
    evidence_explanation: [
      'POI 数量来自当前范围去重统计',
      '仅使用 ready 指标，不读取原始明细',
      '第三条保留',
      '第四条会被截断',
    ],
    metric_claims: [
      { claim_id: 'c1', metric_id: 'poi:total', value: 120, unit: '个', text: 'POI 共 120 个' },
    ],
    metric_gaps: [
      { gap_id: 'g1', text: '缺少夜光梯度数据' },
    ],
    visual_specs: [
      {
        visual_id: 'visual-1',
        visual_type: 'figure',
        status: 'renderable',
        title: 'POI 数量',
        data: {
          columns: [{ key: 'label' }, { key: 'value' }],
          rows: [{ label: 'POI', value: 120 }],
        },
      },
    ],
    visual_artifacts: [
      { visual_id: 'visual-1', url: '/download/visual.svg' },
    ],
  })

  assert.equal(slide.insight, '这说明片区不是单点优势，而是具备成片承接条件。')
  assert.deepEqual(slide.evidenceExplanation, [
    'POI 数量来自当前范围去重统计',
    '仅使用 ready 指标，不读取原始明细',
    '第三条保留',
  ])
  assert.equal(slide.metricClaims[0].value, 120)
  assert.equal(slide.metricGaps[0].text, '缺少夜光梯度数据')
  assert.equal(slide.visualSpecs[0].data.rows[0].value, 120)
  assert.equal(slide.visualArtifacts[0].url, '/download/visual.svg')
})

test('ppt visual artifact filename collection reads filenames and download urls', () => {
  const filenames = collectPptVisualArtifactFilenames({
    slides: [
      {
        visualArtifacts: [
          { filename: 'visual-a.svg' },
          { url: '/download/visual-b.svg?cache=1' },
          { url: 'http://localhost:5173/download/visual-c.svg#preview' },
        ],
      },
      {
        visual_artifacts: [
          { filename: 'visual-a.svg' },
        ],
      },
    ],
  })

  assert.deepEqual(filenames, ['visual-a.svg', 'visual-b.svg', 'visual-c.svg'])
})

test('ppt source changes mark only dependent directive pages stale', () => {
  const state = applyDeckBriefResponse(createPptPlanningState(), {
    slides: [
      {
        index: 1,
        title: 'POI 判断',
        required_sources: ['current:dataset:poi'],
        metric_claims: [{ source_id: 'current:dataset:poi', text: 'POI 总数' }],
      },
      {
        index: 2,
        title: '人口判断',
        required_sources: ['current:analysis:population'],
      },
    ],
  })

  const stale = markPptDirectiveStaleForSources(state, ['current:dataset:poi'])

  assert.deepEqual(stale.staleDirectivePageIds, ['1'])
})

test('ppt spec response stores context manifest on sources', () => {
  const state = createPptPlanningState({
    sources: [
      {
        id: 'current:analysis:poi_h3',
        type: 'sheet',
        title: 'POI / H3 空间结构分析',
        status: 'ready',
        selected: true,
        meta: { sourceKind: 'system' },
      },
    ],
  })

  const next = applyPptSpecResponse(state, {
    title: '更新策划',
    outline: [{ id: 'p1', page_no: 1, theme: '项目命题', purpose: '建立判断' }],
    context_manifest: {
      version: 'ppt_llm_context_bundle_v1',
      source_manifest: [
        {
          source_id: 'current:analysis:poi_h3',
          transport_status: 'included',
          included: ['metrics', 'evidence'],
          metric_count: 3,
          evidence_count: 1,
          excluded: [{ type: 'current_raw_payload', reason: '不传完整 current。' }],
          policy: '数字来自 metric_context。',
        },
      ],
    },
  })

  assert.equal(next.contextManifest.version, 'ppt_llm_context_bundle_v1')
  assert.equal(next.sources[0].meta.transport.metricCount, 3)
  assert.deepEqual(next.sources[0].meta.transport.included, ['metrics', 'evidence'])
  assert.equal(next.sources[0].meta.transport.excluded[0].type, 'current_raw_payload')
})

test('ppt directive response refreshes source transport manifest', () => {
  const state = createPptPlanningState({
    sources: [
      {
        id: 'document:1',
        type: 'document',
        title: '项目文档',
        status: 'ready',
        selected: true,
        meta: { sourceKind: 'document' },
      },
    ],
  })

  const next = applyDeckBriefResponse(state, {
    slides: [{ index: 1, title: '封面' }],
    context_manifest: {
      source_manifest: [
        {
          source_id: 'document:1',
          transport_status: 'included',
          included: ['evidence'],
          metric_count: 0,
          evidence_count: 4,
          policy: '文档使用 PageIndex 章节摘要。',
        },
      ],
    },
  })

  assert.equal(next.sources[0].meta.transport.evidenceCount, 4)
  assert.equal(next.sources[0].meta.transport.policy, '文档使用 PageIndex 章节摘要。')
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
    requestAgentPptPlanningOutlineWithDebug(payload, options = {}) {
      return this.requestAgentPptPlanningOutline(payload, options)
    },
    requestAgentPptPlanningDirectiveWithDebug(payload, options = {}) {
      return this.requestAgentPptPlanningDirective(payload, options)
    },
    requestAgentPptPlanningNarrativePlanWithDebug(payload, options = {}) {
      return this.requestAgentPptPlanningNarrativePlan(payload, options)
    },
    ensureAgentVisualSnapshotCache() {
      return Promise.resolve([])
    },
    ...overrides,
  }
}

test('ppt planning state creates NotebookLM-style system sources and default spec', () => {
  const state = createPptPlanningState()

  assert.equal(state.spec.audience, '政府评审')
  assert.equal(state.spec.pageCount, 15)
  assert.equal(state.sources.length, 7)
  assert.ok(state.sourceGroups.length >= 4)
  assert.equal(state.removedSourceIds.length, 0)
  assert.equal(state.ungroupedSourceIds.length, 0)
  assert.equal(getPptSourceSummary(state).total, 7)
  assert.equal(getPptSourceSummary(state).selected, 0)
  assert.equal(getPptSourceSummary(state).ready, 0)
})

test('ppt system sources expose prebuilt transport preview before generation', () => {
  const sources = createPptSystemSources({
    scope: { polygon: [[0, 0], [1, 0], [1, 1]] },
    taskResults: { poi_h3_grid: true },
    metrics: {
      metrics: [
        {
          metric_id: 'analysis:h3:density',
          source_ids: ['current:analysis:poi_h3'],
          status: 'ready',
          label: 'POI 密度',
          value: 12,
        },
        {
          metric_id: 'analysis:h3:lq',
          source_ids: ['current:analysis:poi_h3'],
          status: 'missing',
          label: 'LQ',
        },
      ],
    },
  })
  const poiH3 = sources.find((source) => source.id === 'current:analysis:poi_h3')
  const scope = sources.find((source) => source.id === 'current:scope')

  assert.equal(scope.meta.transport.transportStatus, 'ready_to_send')
  assert.deepEqual(scope.meta.transport.included, ['scope'])
  assert.equal(scope.meta.transport.scopeCount, 1)
  assert.equal(poiH3.meta.readyMetricCount, 1)
  assert.equal(poiH3.meta.gapMetricCount, 1)
  assert.equal(poiH3.meta.transport.transportStatus, 'ready_to_send')
  assert.equal(poiH3.meta.transport.metricCount, 1)
  assert.equal(poiH3.meta.transport.evidenceCount, 1)
})

test('agent ppt system source refresh replaces stale empty transport preview', () => {
  const ctx = createPptPlanningTestContext({
    h3AnalysisSummary: { avg_density_poi_per_km2: 12 },
    h3AnalysisGridFeatures: [{ id: 'h3-1' }],
  })
  ctx.updateAgentActivePptPlanningState(createPptPlanningState({
    sources: [
      {
        id: 'current:analysis:poi_h3',
        type: 'sheet',
        title: 'POI / H3 空间结构分析',
        status: 'ready',
        selected: true,
        meta: {
          sourceKind: 'system',
          areaId: 'history-1',
          transport: {
            transportStatus: 'selected_no_payload',
            metricCount: 0,
            evidenceCount: 0,
          },
        },
      },
    ],
  }))

  const refreshed = ctx.getAgentPptPlanningStateWithSystemSources()
  const source = refreshed.sources.find((item) => item.id === 'current:analysis:poi_h3')

  assert.equal(source.selected, true)
  assert.equal(source.meta.transport.transportStatus, 'ready_to_send')
  assert.ok(source.meta.transport.metricCount > 0)
  assert.ok(source.meta.transport.evidenceCount >= 1)
})

test('ppt source group response keeps missing sources as top-level ungrouped items', () => {
  const state = mergePptPlanningSources(createPptPlanningState(), createPptSystemSources({
    scope: { polygon: [[0, 0], [1, 0], [1, 1]] },
    taskResults: { poi_fetch: true, nightlight: true },
  }))
  const grouped = applyPptSourceGroupsResponse(state, {
    groups: [
      { id: 'group:vitality', title: '城市活力证据', source_ids: ['current:dataset:poi', 'current:unknown', 'current:dataset:poi'] },
    ],
  })

  const vitality = grouped.sourceGroups.find((item) => item.id === 'group:vitality')

  assert.deepEqual(vitality.sourceIds, ['current:dataset:poi'])
  assert.equal(grouped.sourceGroups.some((item) => item.id === 'group:uncategorized'), false)
  assert.ok(grouped.ungroupedSourceIds.includes('current:scope'))
  assert.ok(grouped.ungroupedSourceIds.includes('current:analysis:nightlight'))
})

test('agent ppt document source delete removes backend document before source', async () => {
  const deleted = []
  const ctx = createPptPlanningTestContext({
    requestAgentPptPlanningDocumentDelete(documentId) {
      deleted.push(documentId)
      return Promise.resolve({ id: documentId })
    },
  })
  ctx.updateAgentActivePptPlanningState(createPptPlanningState({
    sources: [
      {
        id: 'document:doc-1',
        type: 'document',
        title: '项目文档',
        status: 'ready',
        selected: true,
        meta: { sourceKind: 'document', documentId: 'doc-1' },
      },
      {
        id: 'current:dataset:poi',
        type: 'data',
        title: 'POI 基础数据',
        status: 'ready',
        selected: true,
        meta: { sourceKind: 'system' },
      },
    ],
    ungroupedSourceIds: ['document:doc-1', 'current:dataset:poi'],
  }))

  await ctx.removeAgentPptPlanningSource('document:doc-1')

  const state = ctx.getAgentActivePptPlanningState()
  assert.deepEqual(deleted, ['doc-1'])
  assert.equal(state.sources.some((source) => source.id === 'document:doc-1'), false)
  assert.equal(state.removedSourceIds.includes('document:doc-1'), true)
})

test('ppt source group selection toggles only ready group sources', () => {
  const state = mergePptPlanningSources(createPptPlanningState(), createPptSystemSources({
    scope: { polygon: [[0, 0], [1, 0], [1, 1]] },
    taskResults: { poi_fetch: true },
  }))
  const groupId = state.sourceGroups.find((group) => group.sourceIds.includes('current:scope')).id
  const deselected = setPptSourceGroupSelected(state, groupId, false)
  const payload = buildPptSpecPayload(deselected)

  assert.equal(deselected.sources.find((item) => item.id === 'current:scope').selected, false)
  assert.equal(payload.source_ids.includes('current:scope'), false)
})

test('moving a ppt source between groups keeps selected source payload unchanged', () => {
  const state = mergePptPlanningSources(createPptPlanningState(), createPptSystemSources({
    scope: { polygon: [[0, 0], [1, 0], [1, 1]] },
    taskResults: { poi_fetch: true, nightlight: true },
  }))
  const before = buildPptSpecPayload(state).source_ids
  const targetGroup = state.sourceGroups.find((group) => group.sourceIds.includes('current:scope'))
  const moved = movePptSourceToGroup(state, 'current:analysis:nightlight', targetGroup.id)

  assert.deepEqual(buildPptSpecPayload(moved).source_ids.sort(), before.sort())
  assert.ok(moved.sourceGroups.find((group) => group.id === targetGroup.id).sourceIds.includes('current:analysis:nightlight'))
})

test('moving a ppt source out of a group keeps it top-level across refreshes', () => {
  const state = mergePptPlanningSources(createPptPlanningState(), createPptSystemSources({
    scope: { polygon: [[0, 0], [1, 0], [1, 1]] },
    taskResults: { poi_fetch: true, nightlight: true },
  }))
  const before = buildPptSpecPayload(state).source_ids
  const moved = movePptSourceToGroup(state, 'current:dataset:poi', '')
  const refreshed = mergePptPlanningSources(moved, createPptSystemSources({
    scope: { polygon: [[0, 0], [1, 0], [1, 1]] },
    taskResults: { poi_fetch: true, nightlight: true },
  }))

  assert.deepEqual(buildPptSpecPayload(refreshed).source_ids.sort(), before.sort())
  assert.ok(refreshed.ungroupedSourceIds.includes('current:dataset:poi'))
  assert.equal(refreshed.sourceGroups.some((group) => group.sourceIds.includes('current:dataset:poi')), false)
})

test('removing a ppt group keeps its sources as top-level ungrouped items', () => {
  const state = mergePptPlanningSources(createPptPlanningState(), createPptSystemSources({
    scope: { polygon: [[0, 0], [1, 0], [1, 1]] },
    taskResults: { poi_fetch: true },
  }))
  const group = state.sourceGroups.find((item) => item.sourceIds.includes('current:scope'))
  const removed = removePptSourceGroup(state, group.id)

  assert.ok(removed.sources.find((item) => item.id === 'current:scope'))
  assert.equal(removed.sourceGroups.some((item) => item.id === 'group:uncategorized'), false)
  assert.ok(removed.ungroupedSourceIds.includes('current:scope'))
})

test('removing a ppt source excludes it from payload and future system refreshes', () => {
  const initial = mergePptPlanningSources(createPptPlanningState(), createPptSystemSources({
    scope: { polygon: [[0, 0], [1, 0], [1, 1]] },
    taskResults: { poi_fetch: true },
  }))
  const removed = removePptSource(initial, 'current:dataset:poi')
  const refreshed = mergePptPlanningSources(removed, createPptSystemSources({
    scope: { polygon: [[0, 0], [1, 0], [1, 1]] },
    taskResults: { poi_fetch: true, nightlight: true },
  }))

  assert.equal(refreshed.sources.some((item) => item.id === 'current:dataset:poi'), false)
  assert.equal(buildPptSpecPayload(refreshed).source_ids.includes('current:dataset:poi'), false)
  assert.ok(refreshed.removedSourceIds.includes('current:dataset:poi'))
  assert.equal(refreshed.ungroupedSourceIds.includes('current:dataset:poi'), false)
})

test('ppt source selection only includes ready sources in the spec payload', () => {
  const systemSources = createPptSystemSources({
    scope: { polygon: [[0, 0], [1, 0], [1, 1]] },
    taskResults: { poi_fetch: true },
  })
  const state = togglePptSourceSelection(
    mergePptPlanningSources(createPptPlanningState(), systemSources),
    'current:analysis:nightlight',
  )
  const payload = buildPptSpecPayload(state, { areaId: 'area-1' })

  assert.equal(payload.area_id, 'area-1')
  assert.equal(payload.audience, '政府评审')
  assert.equal(payload.page_count, 15)
  assert.ok(payload.source_ids.includes('current:scope'))
  assert.ok(payload.source_ids.includes('current:dataset:poi'))
  assert.equal(payload.source_ids.includes('current:analysis:nightlight'), false)
})

test('ppt payload uses only selected sources with deliverable ai payload', () => {
  const state = createPptPlanningState({
    sources: [
      {
        id: 'summary',
        type: 'data',
        title: 'summary',
        status: 'ready',
        selected: true,
        meta: { sourceKind: 'system', transport: { transport_status: 'selected_no_payload', included: [] } },
      },
      {
        id: 'current:scope',
        type: 'data',
        title: '当前等时圈范围',
        status: 'ready',
        selected: true,
        meta: {
          sourceKind: 'system',
          aiPayload: {
            version: 'ppt_ai_input_block_v1',
            source_id: 'current:scope',
            included: ['scope'],
            scope: { type: 'scope_brief' },
          },
        },
      },
      {
        id: 'package:poi:test',
        type: 'package',
        title: 'POI 资料包',
        status: 'ready',
        selected: true,
        meta: {
          sourceKind: 'package',
          aiPayload: {
            version: 'ppt_ai_input_block_v1',
            source_id: 'package:poi:test',
            included: ['evidence'],
            evidence: [{ title: '样本', text: '代表性 POI' }],
          },
        },
      },
    ],
  })
  const summary = getPptSourceSummary(state)
  const manifest = getPptSourceDeliveryManifest(state)
  const payload = buildPptSpecPayload(state, { areaId: 'area-1' })

  assert.equal(summary.selected, 3)
  assert.equal(summary.deliverable, 2)
  assert.equal(summary.emptyPayload, 1)
  assert.deepEqual(manifest.emptyPayloadSourceIds, ['summary'])
  assert.deepEqual(payload.source_ids.sort(), ['current:scope', 'package:poi:test'].sort())
  assert.equal(payload.sources.length, 2)
  assert.equal(payload.sources.some((source) => source.id === 'summary'), false)
})

test('ppt state can select all sources and keep an active page brief', () => {
  const systemSources = createPptSystemSources({
    scope: { polygon: [[0, 0], [1, 0], [1, 1]] },
    taskResults: { poi_fetch: true, population: true },
  })
  const state = applyDeckBriefResponse(
    setAllPptSourcesSelected(mergePptPlanningSources(createPptPlanningState(), systemSources), true),
    createDefaultDeckBriefPreview(),
  )
  const active = getActiveDeckSlideBrief(state)

  assert.equal(getPptSourceSummary(state).selected, 3)
  assert.equal(active.title, '封面')
  assert.equal(Object.hasOwn(active, 'speakerNotes'), false)
})

test('ppt system sources refresh preserves ready selections and blocks pending sources', () => {
  const initial = mergePptPlanningSources(createPptPlanningState(), createPptSystemSources({
    scope: { polygon: [[0, 0], [1, 0], [1, 1]] },
    taskResults: { poi_fetch: true },
  }))
  const deselectedPoi = togglePptSourceSelection(initial, 'current:dataset:poi', false)
  const refreshed = mergePptPlanningSources(deselectedPoi, createPptSystemSources({
    scope: { polygon: [[0, 0], [1, 0], [1, 1]] },
    taskResults: { poi_fetch: true, nightlight: true },
  }))

  const poi = refreshed.sources.find((item) => item.id === 'current:dataset:poi')
  const nightlight = refreshed.sources.find((item) => item.id === 'current:analysis:nightlight')
  const road = refreshed.sources.find((item) => item.id === 'current:analysis:road')

  assert.equal(poi.selected, false)
  assert.equal(nightlight.selected, true)
  assert.equal(road.status, 'pending')
  assert.equal(road.selected, false)
})

test('ppt nightlight metrics read layer analysis fields when overview summary is partial', () => {
  const methods = createAgentPptPlanningTabMethods()
  const ctx = {
    ...methods,
    normalizeAgentSiteSelectionScope() {
      return { polygon: [[0, 0], [1, 0], [1, 1]], drawnPolygon: [], isochroneFeature: null }
    },
    agentPanelPayloads: {},
    allPoisDetails: [],
    h3AnalysisSummary: null,
    h3GridCount: 0,
    h3AnalysisGridFeatures: [],
    populationOverview: null,
    roadSyntaxSummary: null,
    timeHorizon: 15,
    transportMode: 'walking',
    nightlightOverview: {
      summary: {
        total_radiance: 100,
        mean_radiance: 8.5,
        p90_radiance: 18,
        lit_pixel_ratio: 0.72,
      },
    },
    nightlightLayer: {
      analysis: {
        core_hotspot_count: 4,
        hotspot_cell_ratio: 0.25,
        peak_to_edge_ratio: 2.1,
      },
    },
  }

  const current = ctx.buildAgentPptPlanningCurrent()
  const nightlightMetrics = current.metrics.metrics.filter((item) => item.domain === 'nightlight')

  assert.equal(nightlightMetrics.find((item) => item.metric_id === 'analysis:nightlight:core_hotspot_count').status, 'ready')
  assert.equal(nightlightMetrics.find((item) => item.metric_id === 'analysis:nightlight:gradient_decay').status, 'ready')
  assert.equal(nightlightMetrics.find((item) => item.metric_id === 'analysis:nightlight:gradient_decay').source_path, 'nightlightLayer.analysis.peak_to_edge_ratio')
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

test('agent ppt refresh rebuilds package ai payload from persisted package meta', async () => {
  const ctx = createPptPlanningTestContext({
    requestAgentPptPlanningDataSources(areaId) {
      return Promise.resolve([
        {
          id: 'package:poi-road-carriers:restored',
          type: 'package',
          title: 'POI × 路网空间载体资料包',
          status: 'ready',
          summary: '空间载体 1 个',
          count: 1,
          meta: {
            label: '空间载体 1 个',
            sourceKind: 'package',
            areaId,
            package: {
              package_mode: 'evidence',
              intent: DEFAULT_PPT_CARRIER_EVIDENCE_INTENT,
              summary: '已识别 1 个路网空间载体。',
              source_ids: ['current:dataset:poi', 'current:analysis:road'],
              carriers: [{ carrier_id: 'corridor_01', carrier_type: 'corridor', summary: '主街走廊。' }],
              items: [{ id: 'poi-1', name: '样本 POI', category: '餐饮', address: '示例路' }],
            },
          },
        },
      ])
    },
  })

  await ctx.refreshAgentActivePptPlanningDataSources({ autoPackage: false })
  const state = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)
  const source = state.sources.find((item) => item.id === 'package:poi-road-carriers:restored')

  assert.equal(source.selected, true)
  assert.ok(source.meta.aiPayload)
  assert.equal(source.meta.transport.transportStatus, 'ready_to_send')
  assert.equal(source.meta.transport.evidenceCount, 3)
  assert.equal(getPptSourceSummary(state).selectedDeliverable, 1)
})

test('agent ppt source refresh adds pending package placeholders without selecting them', async () => {
  const ctx = createPptPlanningTestContext({
    requestAgentPptPlanningDataSources(areaId) {
      return Promise.resolve([
        {
          id: 'current:dataset:poi',
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
  assert.equal(poiPlaceholder.meta.label, '点击生成')
  assert.equal(poiPlaceholder.meta.sourceKind, 'package-placeholder')
  assert.equal(payload.source_ids.includes('package-placeholder:poi-evidence'), false)
})

test('ppt outline waits for package placeholders only when their inputs are ready', () => {
  const scopeOnlyState = createPptPlanningState({
    sources: [
      {
        id: 'current:scope',
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
          package: { source_ids: ['current:dataset:poi'] },
        },
      },
    ],
  })
  const readyInputState = createPptPlanningState({
    sources: [
      ...scopeOnlyState.sources,
      {
        id: 'current:dataset:poi',
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
          package: { source_ids: ['current:dataset:poi'] },
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

test('ppt outline blocks when any selected source is not ready', () => {
  const state = createPptPlanningState({
    sources: [
      {
        id: 'current:scope',
        type: 'data',
        title: '当前等时圈范围',
        status: 'ready',
        selected: true,
        meta: { sourceKind: 'system' },
      },
      {
        id: 'document:uploading',
        type: 'document',
        title: '上传文档',
        status: 'generating',
        selected: true,
        meta: { sourceKind: 'document' },
      },
    ],
  })

  assert.deepEqual(
    getBlockingPptInputSources(state).map((item) => item.id),
    ['document:uploading'],
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
            id: 'current:dataset:poi',
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
  assert.equal(generatingState.dataPackageGenerating, false)

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
          source_ids: ['current:dataset:poi'],
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
            id: 'current:dataset:poi',
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
              source_ids: ['current:dataset:poi'],
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

test('deck brief payload sends selected source ai input blocks with lightweight visual context', () => {
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
    current: { scope: { time_min: 35 } },
  })

  assert.equal(payload.area_id, 'history-1')
  assert.equal(payload.sources[0].id, 'package:poi:test')
  assert.equal(Object.prototype.hasOwnProperty.call(payload, 'current'), true)
  assert.deepEqual(payload.current.visual_snapshots || [], [])
  assert.equal(payload.current.scope.time_min, 35)
  assert.equal(payload.sources[0].meta.aiPayload.version, 'ppt_ai_input_block_v1')
  assert.equal(payload.sources[0].meta.aiPayload.evidence[0].text, '已整理 POI。')
  assert.equal(payload.sources[0].meta.package, undefined)
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
        required_sources: ['current:scope'],
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
  assert.deepEqual(outlineReady.deckBrief.slides, [])

  const materials = resetPptPlanningToMaterials(directiveState)
  assert.equal(materials.currentStep, 'materials')
  assert.deepEqual(materials.outline, [])
  assert.deepEqual(materials.spec.outline, [])
  assert.deepEqual(materials.deckBrief.slides, [])
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
        { index: 1, title: '项目命题', purpose: '建立汇报主线', required_sources: ['current:scope'] },
      ],
    },
    staleDirectivePageIds: ['1'],
  })

  const revised = applyDeckBriefSlideRevision(state, {
    index: 1,
    title: '项目命题重写',
    purpose: '更聚焦评审',
    keyMessage: '解释更新必要性',
    insight: '这说明更新议题已经具备明确评审价值。',
    evidenceExplanation: ['范围口径来自当前等时圈'],
    visualPlan: '区域底图',
    requiredSources: ['current:scope'],
  })

  assert.equal(revised.deckBrief.slides[0].title, '项目命题重写')
  assert.equal(revised.deckBrief.slides[0].insight, '这说明更新议题已经具备明确评审价值。')
  assert.deepEqual(revised.deckBrief.slides[0].evidenceExplanation, ['范围口径来自当前等时圈'])
  assert.deepEqual(revised.staleDirectivePageIds, [])
  assert.ok(revised.revisionSnapshots['slide:1'])

  const undone = undoPptSectionRevision(revised, 'directive', { index: 1 })
  assert.equal(undone.deckBrief.slides[0].title, '项目命题')
  assert.equal(Boolean(undone.revisionSnapshots['slide:1']), false)
})

test('ppt directive manual revision keeps existing visual specs and artifacts', () => {
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
          required_sources: ['current:scope'],
          visual_specs: [{ visual_id: 'visual-1', visual_type: 'figure', title: 'POI 结构', status: 'renderable' }],
          visual_artifacts: [{ visual_id: 'visual-1', filename: 'poi.svg', url: '/download/poi.svg' }],
        },
      ],
    },
  })

  const revised = applyDeckBriefSlideRevision(state, {
    index: 1,
    title: '项目命题重写',
    purpose: '更聚焦评审',
    keyMessage: '解释更新必要性',
    visualPlan: '区域底图和重点指标',
    requiredSources: ['current:scope'],
  })

  assert.equal(revised.deckBrief.slides[0].title, '项目命题重写')
  assert.equal(revised.deckBrief.slides[0].visualSpecs[0].title, 'POI 结构')
  assert.equal(revised.deckBrief.slides[0].visualArtifacts[0].url, '/download/poi.svg')
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
          required_sources: ['current:scope'],
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
    requiredSources: ['current:scope'],
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
    current: { scope: { time_min: 35 } },
  })

  assert.equal(drafted.outlineRevisionDraft.theme, '项目命题')
  assert.equal(payload.area_id, 'history-1')
  assert.equal(payload.target.id, 'page-1')
  assert.equal(payload.revision_note, '更强调评审价值')

  const withSlide = applyDeckBriefResponse(outlineReady, {
    slides: [{
      index: 1,
      title: '项目命题',
      purpose: '建立汇报主线',
      insight: '这说明空间证据已经足以支撑更新判断。',
      required_sources: ['current:scope'],
      metric_claims: [{ metric_id: 'poi:total:1', value: 120, unit: '个', text: 'POI 总数 120 个' }],
      metric_gaps: [{ text: '缺少人口年龄结构' }],
      visual_specs: [{
        visual_id: 'visual-1',
        visual_type: 'figure',
        status: 'renderable',
        title: 'POI 总量',
        data: {
          columns: [{ key: 'label' }, { key: 'value' }],
          rows: [{ label: 'POI', value: 120 }],
        },
      }],
      visual_artifacts: [{ visual_id: 'visual-1', url: '/download/visual.svg' }],
    }],
  })
  const slidePayload = buildDeckBriefSlidePayload(withSlide, { index: 1 }, '重写这一页', {
    areaId: 'history-1',
    current: { scope: { time_min: 35 } },
  })

  assert.equal(slidePayload.target.index, 1)
  assert.equal(slidePayload.outline_item.page_no, 1)
  assert.equal(slidePayload.revision_note, '重写这一页')
  assert.equal(slidePayload.target.insight, '这说明空间证据已经足以支撑更新判断。')
  assert.equal(slidePayload.target.metric_claims[0].value, 120)
  assert.deepEqual(slidePayload.slides, [])
  assert.equal(slidePayload.page_no, 1)
  assert.equal(slidePayload.deck_progress_summary.page_count, 1)
  assert.equal(slidePayload.target.visual_artifacts[0].url, '/download/visual.svg')
})

test('ppt visual artifact payload and response are independent from brief generation', () => {
  const state = createPptPlanningState({
    sources: [
      {
        id: 'current:dataset:poi',
        type: 'data',
        title: 'POI 基础数据',
        status: 'ready',
        selected: true,
        meta: {
          aiPayload: {
            version: 'ppt_ai_input_block_v1',
            source_id: 'current:dataset:poi',
            sourceId: 'current:dataset:poi',
            title: 'POI 基础数据',
            included: ['metrics'],
            metrics: [{
              metric_id: 'analysis:poi:poi_count',
              label: 'POI 数量',
              value: 120,
              unit: '个',
              status: 'ready',
              source_id: 'current:dataset:poi',
            }],
            metric_gaps: [],
            evidence: [],
            counts: { metrics: 1, metric_gaps: 0, evidence: 0, visual_specs: 0 },
          },
        },
      },
    ],
    deckBrief: {
      slides: [{
        index: 1,
        title: '项目命题',
        purpose: '建立汇报主线',
        visualSpecs: [{
          visual_id: 'visual-1',
          visual_type: 'figure',
          status: 'renderable',
          title: 'POI 总量',
          source_metric_ids: ['analysis:poi:poi_count'],
          data: { columns: [], rows: [] },
        }],
        visualArtifacts: [],
      }],
    },
  })

  const payload = buildPptVisualArtifactsPayload(state, state.deckBrief.slides[0], {
    current: {
      visual_snapshots: [{ asset_id: 'map-1', url: '/download/map.png' }],
    },
  })
  assert.equal(payload.slide_index, 1)
  assert.equal(payload.metric_context.metrics[0].metric_id, 'analysis:poi:poi_count')
  assert.equal(payload.existing_assets[0].asset_id, 'map-1')

  const generating = startPptVisualArtifactsGeneration(state, 1)
  assert.equal(generating.visualGenerationBySlide['1'].status, 'generating')

  const applied = applyPptVisualArtifactsResponse(generating, {
    slide_index: 1,
    visual_artifacts: [{ visual_id: 'visual-1', url: '/download/visual-1.svg' }],
  })
  assert.equal(applied.deckBrief.slides[0].visualArtifacts[0].url, '/download/visual-1.svg')
  assert.equal(applied.visualGenerationBySlide['1'].status, 'ready')
})

test('ppt visual artifact payload clears stale map snapshot capture errors before retry', () => {
  const state = createPptPlanningState({
    deckBrief: {
      slides: [{
        index: 1,
        title: 'POI-H3空间结构与混合度诊断',
        visualSpecs: [{
          visual_id: 'visual-map',
          visual_type: 'existing_asset',
          status: 'needs_existing_asset',
          title: 'POI-H3空间结构与混合度诊断',
          source_ids: ['current:analysis:poi_h3'],
          data: {
            composition: 'map_snapshot_request',
            capture_error: {
              code: 'ppt_map_snapshot_capture_failed',
              message: '地图截图导出失败',
            },
            captureError: {
              code: 'legacy_error',
            },
            map_request: {
              composition: 'h3',
              layers: [{ layer_type: 'h3_grid', source: 'current:analysis:poi_h3' }],
            },
            metric_overlays: [{ label: '混合度', value: 0.62 }],
          },
        }],
      }],
    },
  })

  const clearedState = clearPptSlideMapSnapshotCaptureErrors(state, 1)
  const clearedVisual = clearedState.deckBrief.slides[0].visualSpecs[0]
  assert.equal(clearedVisual.data.capture_error, undefined)
  assert.equal(clearedVisual.data.captureError, undefined)
  assert.equal(clearedVisual.data.map_request.composition, 'h3')
  assert.equal(clearedVisual.data.metric_overlays[0].label, '混合度')

  const payload = buildPptVisualArtifactsPayload(state, state.deckBrief.slides[0], { current: {} })
  assert.equal(payload.visual_specs[0].data.capture_error, undefined)
  assert.equal(payload.visual_specs[0].data.captureError, undefined)
  assert.equal(payload.visual_specs[0].data.map_request.layers[0].layer_type, 'h3_grid')
})

test('ppt visual artifact payload includes current ready metrics when source payload is stale', () => {
  const state = createPptPlanningState({
    sources: [{
      id: 'current:analysis:population',
      type: 'data',
      title: '人口结构分析',
      status: 'ready',
      selected: true,
      meta: {
        sourceKind: 'system',
        aiPayload: {
          version: 'ppt_ai_input_block_v1',
          source_id: 'current:analysis:population',
          included: ['metrics'],
          metrics: [],
          metric_gaps: [],
        },
      },
    }],
    deckBrief: {
      slides: [{
        index: 1,
        title: '人口密度',
        visualSpecs: [{
          visual_id: 'visual-density',
          visual_type: 'metric_card',
          status: 'renderable',
          title: '人口密度',
          source_ids: ['current:analysis:population'],
          source_metric_ids: ['analysis:population:population_density'],
          data: {},
        }],
      }],
    },
  })

  const payload = buildPptVisualArtifactsPayload(state, state.deckBrief.slides[0], {
    current: {
      metrics: {
        metrics: [{
          metric_id: 'analysis:population:population_density',
          source_id: 'current:analysis:population',
          source_ids: ['current:analysis:population'],
          label: '人口密度',
          value: 8000,
          unit: '人/km²',
          status: 'ready',
        }],
      },
    },
  })

  assert.ok(payload.metric_context.metrics.find((item) => (
    item.metric_id === 'analysis:population:population_density'
    && item.status === 'ready'
    && item.value === 8000
  )))
})

test('ppt visual artifact response refreshes visual specs alongside artifacts', () => {
  const state = createPptPlanningState({
    deckBrief: {
      slides: [{
        index: 1,
        title: '人口密度',
        purpose: '展示空间居住性与活动密度',
        visualSpecs: [{
          visual_id: 'visual-1',
          visual_type: 'metric_card',
          status: 'missing_data',
          title: '人口密度',
          source_ids: ['current:analysis:population'],
        }],
        visualArtifacts: [],
      }],
    },
  })

  const applied = applyPptVisualArtifactsResponse(state, {
    slide_index: 1,
    visual_specs: [{
      visual_id: 'visual-1',
      visual_type: 'existing_asset',
      status: 'renderable',
      title: '人口密度',
      source_ids: ['current:analysis:population'],
      asset_id: 'population-map-1',
      asset: { asset_id: 'population-map-1', data_url: 'data:image/png;base64,population' },
      data: {
        composition: 'map_with_metric_overlays',
        metric_overlays: [
          { label: '人口密度', value: 8000, unit: '人/km²', metric_id: 'analysis:population:population_density' },
        ],
      },
    }],
    visual_artifacts: [{
      visual_id: 'visual-1',
      visual_type: 'existing_asset',
      asset_id: 'population-map-1',
      url: 'data:image/png;base64,population',
    }],
  })

  assert.equal(applied.deckBrief.slides[0].visualSpecs[0].status, 'renderable')
  assert.equal(applied.deckBrief.slides[0].visualSpecs[0].visual_type, 'existing_asset')
  assert.equal(applied.deckBrief.slides[0].visualSpecs[0].data.composition, 'map_with_metric_overlays')
  assert.equal(applied.deckBrief.slides[0].visualSpecs[0].data.metric_overlays[0].label, '人口密度')
  assert.equal(applied.deckBrief.slides[0].visualArtifacts[0].url, 'data:image/png;base64,population')
})

test('ppt map snapshot request helpers validate and preserve source request', async () => {
  assert.equal(typeof MAP_LAYER_RENDERERS.population_grid, 'function')
  const visual = {
    visual_type: 'existing_asset',
    status: 'needs_existing_asset',
    data: {
      composition: 'map_snapshot_request',
      map_request: {
        composition: 'population',
        title: '人口密度',
        layers: [
          { layer_type: 'scope_boundary', source: 'current:scope' },
          { layer_type: 'population_grid', source: 'current:analysis:population' },
        ],
      },
    },
  }
  assert.equal(isPptMapSnapshotRequest(visual), true)

  const asset = await capturePptMapRequestAsset(visual.data.map_request, {
    renderMapRequest: async (request) => {
      assert.equal(request.layers.length, 2)
      return 'data:image/png;base64,map'
    },
  })
  assert.equal(asset.asset_kind, 'map_snapshot')
  assert.equal(asset.data_url, 'data:image/png;base64,map')
  assert.equal(asset.data.map_request.composition, 'population')

  const jpegAsset = await capturePptMapRequestAsset(visual.data.map_request, {
    renderMapRequest: async () => 'data:image/jpeg;base64,map',
  })
  assert.equal(jpegAsset.asset_kind, 'map_snapshot')
  assert.equal(jpegAsset.data_url, 'data:image/jpeg;base64,map')

  const overviewAsset = await capturePptMapRequestAsset({
    composition: 'overview',
    layers: [{ layer_type: 'scope_boundary', source: 'current:scope' }],
  }, { renderMapRequest: async () => 'data:image/png;base64,overview' })
  assert.equal(overviewAsset.asset_kind, 'map_snapshot')
  assert.equal(overviewAsset.data.map_request.composition, 'overview')

  await assert.rejects(
    () => capturePptMapRequestAsset({
      composition: 'population',
      layers: [{ layer_type: 'scope_boundary', source: 'current:scope' }],
    }, { renderMapRequest: async () => 'data:image/png;base64,map' }),
    /ppt_map_request_missing_renderable_layer/,
  )

  await assert.rejects(
    () => capturePptMapRequestAsset(visual.data.map_request, {
      renderMapRequest: async () => 'data:text/plain;base64,map',
    }),
    /ppt_map_asset_invalid_data_url/,
  )
})

test('ppt map request runtime maps protocol layers to real offscreen targets', () => {
  const runtime = createAgentRuntimeMethods()
  const ctx = {}
  Object.assign(ctx, runtime, {
    roadSyntaxSummary: { edge_count: 1 },
    roadSyntaxRoadFeatures: [{ properties: { choice_score: 0.8 }, geometry: { type: 'LineString', coordinates: [[112, 28], [112.1, 28.1]] } }],
  })

  assert.deepEqual(ctx.pptMapRequestLayerTarget({}, { layer_type: 'population_grid' }), {
    kind: 'population_map',
    title: '人口图层',
    key: 'population',
  })
  assert.equal(ctx.pptMapRequestLayerTarget({}, { layer_type: 'nightlight_grid' }).kind, 'nightlight_map')
  assert.equal(ctx.pptMapRequestLayerTarget({}, { layer_type: 'h3_grid' }).kind, 'h3_map')
  assert.equal(ctx.pptMapRequestLayerTarget({}, { layer_type: 'poi_points' }).kind, 'poi_map')
  assert.equal(ctx.pptMapRequestLayerTarget({}, { layer_type: 'scope_boundary' }).kind, 'overview_map')
  assert.deepEqual(ctx.pptMapRequestLayerTarget({
    annotations: [{ metric_id: 'analysis:road:avg_choice', label: '平均选择度' }],
  }, { layer_type: 'road_syntax' }), {
    kind: 'road_map',
    title: '路网句法图层',
    key: 'syntax',
    fit: 'road',
    metric: 'choice',
  })
})

test('ppt map request runtime captures from main map and restores map state', async () => {
  const runtime = createAgentRuntimeMethods()
  const events = []
  const ctx = {}
  Object.assign(ctx, runtime, {
    populationOverview: { summary: { total_population: 1200 } },
    roadSyntaxMainTab: 'integration',
    roadSyntaxMetric: 'integration',
    roadSyntaxLastMetricTab: 'integration',
    getAgentScopeBounds: () => ({ west: 112.9, south: 28.1, east: 113.1, north: 28.3 }),
    getAgentMapViewState: () => ({ center: [113, 28.2], zoom: 12 }),
    getAgentVisualLayerState: () => ({
      panel: 'poi',
      subTab: 'category',
      roadSyntaxMainTab: ctx.roadSyntaxMainTab,
      roadSyntaxMetric: ctx.roadSyntaxMetric,
      roadSyntaxLastMetricTab: ctx.roadSyntaxLastMetricTab,
    }),
    restoreAgentVisualLayerState(state) {
      events.push(`restore-layer:${state.panel}:${state.subTab}`)
      this.roadSyntaxMainTab = state.roadSyntaxMainTab
      this.roadSyntaxMetric = state.roadSyntaxMetric
      this.roadSyntaxLastMetricTab = state.roadSyntaxLastMetricTab
      return Promise.resolve(true)
    },
    restoreAgentMapViewState(view) {
      events.push(`restore-view:${view.zoom}`)
    },
    prepareAgentVisualSnapshotTarget(target) {
      events.push(`prepare:${target.kind}:${target.key}`)
      return Promise.resolve({ west: 112.9, south: 28.1, east: 113.1, north: 28.3 })
    },
    waitForAgentVisualSnapshotPaint() {
      events.push('paint')
      return Promise.resolve(true)
    },
    _captureMapSnapshotBase64() {
      events.push('capture-main')
      return Promise.resolve('data:image/png;base64,main-map')
    },
  })

  const dataUrl = await ctx.renderPptMapRequestMainMapSnapshot({
    composition: 'population',
    title: '人口密度',
    layers: [
      { layer_type: 'scope_boundary', source: 'current:scope' },
      { layer_type: 'population_grid', source: 'current:analysis:population' },
    ],
  })

  assert.equal(dataUrl, 'data:image/png;base64,main-map')
  assert.equal(ctx.roadSyntaxMainTab, 'integration')
  assert.equal(ctx.roadSyntaxMetric, 'integration')
  assert.equal(ctx.roadSyntaxLastMetricTab, 'integration')
  assert.deepEqual(events, [
    'prepare:population_map:population',
    'capture-main',
    'restore-layer:poi:category',
    'restore-view:12',
    'paint',
  ])
})

test('ppt map snapshot renderer readiness loads html2canvas and AMap before capture', async () => {
  const runtime = createAgentRuntimeMethods()
  const appendedScripts = []
  const loadCalls = []
  const originalDocument = globalThis.document
  const originalWindow = globalThis.window
  const originalHtml2canvas = globalThis.html2canvas
  const originalAmap = globalThis.AMap
  const windowMock = { __ANALYSIS_BOOTSTRAP__: { config: { amap_js_api_key: 'key-1', amap_js_security_code: 'sec-1' } } }
  globalThis.window = windowMock
  delete globalThis.html2canvas
  delete globalThis.AMap
  globalThis.document = {
    querySelector: () => null,
    createElement: () => ({
      dataset: {},
      addEventListener() {},
    }),
    head: {
      appendChild(script) {
        appendedScripts.push(script.src)
        globalThis.html2canvas = async () => ({ toDataURL: () => 'data:image/png;base64,canvas' })
        if (typeof script.onload === 'function') script.onload()
      },
    },
  }
  const ctx = {}
  Object.assign(ctx, runtime, {
    config: { amap_js_api_key: 'key-ctx', amap_js_security_code: 'sec-ctx' },
    loadAMapScript(key, securityCode) {
      loadCalls.push({ key, securityCode })
      windowMock.AMap = { Map() {} }
      return Promise.resolve(true)
    },
  })

  try {
    await ctx.ensurePptMapSnapshotRendererReady()
    assert.deepEqual(appendedScripts, ['/static/vendor/html2canvas.min.js'])
    assert.deepEqual(loadCalls, [{ key: 'key-ctx', securityCode: 'sec-ctx' }])
  } finally {
    if (originalDocument === undefined) delete globalThis.document
    else globalThis.document = originalDocument
    if (originalWindow === undefined) delete globalThis.window
    else globalThis.window = originalWindow
    if (originalHtml2canvas === undefined) delete globalThis.html2canvas
    else globalThis.html2canvas = originalHtml2canvas
    if (originalAmap === undefined) delete globalThis.AMap
    else globalThis.AMap = originalAmap
  }
})

test('ppt map request renderer draws analysis layers as svg over offscreen AMap basemap', async () => {
  const runtime = createAgentRuntimeMethods()
  const originalDocument = globalThis.document
  const originalWindow = globalThis.window
  const originalHtml2canvas = globalThis.html2canvas
  const originalAmap = globalThis.AMap
  const createdMaps = []
  const appendedHosts = []
  const svgNodes = []

  const createNode = (tag) => ({
    tag,
    attrs: {},
    style: { cssText: '', position: '', backgroundColor: '' },
    children: [],
    parentNode: null,
    setAttribute(name, value) { this.attrs[name] = String(value) },
    getAttribute(name) { return this.attrs[name] },
    appendChild(node) {
      node.parentNode = this
      this.children.push(node)
    },
    removeChild(node) {
      this.children = this.children.filter((item) => item !== node)
      node.parentNode = null
    },
    querySelectorAll() { return [] },
  })
  const findNode = (node, predicate) => {
    if (!node) return null
    if (predicate(node)) return node
    for (const child of node.children || []) {
      const found = findNode(child, predicate)
      if (found) return found
    }
    return null
  }
  const collectNodes = (node, tag, out = []) => {
    if (!node) return out
    if (node.tag === tag) out.push(node)
    ;(node.children || []).forEach((child) => collectNodes(child, tag, out))
    return out
  }

  class FakeOverlay {
    constructor(options = {}) {
      this.options = options
    }
    setMap(map) {
      this.map = map
      if (map && map.overlays) map.overlays.push(this)
    }
  }
  class FakeMap {
    constructor(host, options = {}) {
      this.host = host
      this.options = options
      this.overlays = []
      createdMaps.push(this)
    }
    setFitView(overlays, immediate, padding) {
      this.fit = { overlays, immediate, padding }
    }
    lngLatToContainer(point) {
      const lng = Number(point.lng ?? point[0])
      const lat = Number(point.lat ?? point[1])
      return { x: Math.round((lng - 112) * 1000), y: Math.round((29 - lat) * 1000) }
    }
    destroy() {
      this.destroyed = true
    }
  }

  globalThis.document = {
    createElement: createNode,
    createElementNS: (_ns, tag) => createNode(tag),
    body: {
      appendChild(node) {
        node.parentNode = this
        appendedHosts.push(node)
      },
      removeChild(node) {
        node.parentNode = null
      },
    },
  }
  globalThis.window = {
    setTimeout: (fn) => {
      fn()
      return 1
    },
    clearTimeout() {},
    AMap: {
      Map: FakeMap,
      Polygon: class Polygon extends FakeOverlay {},
      LngLat: class LngLat {
        constructor(lng, lat) {
          this.lng = lng
          this.lat = lat
        }
      },
    },
  }
  globalThis.AMap = globalThis.window.AMap
  globalThis.html2canvas = async (host) => {
    const svg = findNode(host, (node) => node.attrs && node.attrs['data-agent-ppt-svg-overlay'] === '1')
    assert.ok(svg)
    const paths = svgNodes.filter((node) => node.tag === 'path')
    const circles = svgNodes.filter((node) => node.tag === 'circle')
    assert.ok(paths.length >= 4, `expected at least 4 paths, got ${paths.length}: ${paths.map((node) => `${node.attrs.fill || node.attrs.stroke}:${node.attrs.d}`).join('|')}`)
    assert.ok(circles.length >= 1)
    assert.equal(paths.some((node) => String(node.attrs.d || '').startsWith('M900 900 L920 900')), true)
    assert.equal(paths.some((node) => node.attrs.fill === 'none'), true)
    return {
      width: 960,
      height: 960,
      toDataURL: () => 'data:image/png;base64,svg-map',
    }
  }

  const ctx = {}
  Object.assign(ctx, runtime, {
    _sleepForExport: async () => {},
    waitForAgentVisualSnapshotPaint: async () => true,
    getAgentVisualSnapshotRenderSize: () => ({ width: 960, height: 960 }),
    appendPptMapSvgNode(svg, tag, attrs = {}) {
      svgNodes.push({ tag, attrs: { ...attrs } })
      return runtime.appendPptMapSvgNode.call(this, svg, tag, attrs)
    },
    buildAgentAnalysisSnapshot: () => ({
      scope: { polygon: [[112.9, 28.1], [113.1, 28.1], [113.1, 28.3], [112.9, 28.1]] },
    }),
    getAgentScopeBounds: () => ({ west: 112.9, south: 28.1, east: 113.1, north: 28.3 }),
    populationOverview: { summary: { total_population: 1200 } },
    buildPopulationStyledFeatures: () => [{
      type: 'Feature',
      geometry: { type: 'Polygon', coordinates: [[[112.9, 28.1], [112.92, 28.1], [112.92, 28.12], [112.9, 28.1]]] },
      properties: { fillColor: '#0ea5e9', fillOpacity: 0.45 },
    }],
    nightlightOverview: { summary: { mean_radiance: 12 } },
    buildNightlightStyledFeatures: () => [{
      type: 'Feature',
      geometry: { type: 'Polygon', coordinates: [[[112.93, 28.13], [112.95, 28.13], [112.95, 28.15], [112.93, 28.13]]] },
      properties: { fillColor: '#f59e0b', fillOpacity: 0.42 },
    }],
    h3AnalysisSummary: { grid_count: 1 },
    h3AnalysisGridFeatures: [{
      type: 'Feature',
      geometry: { type: 'Polygon', coordinates: [[[112.96, 28.16], [112.98, 28.16], [112.98, 28.18], [112.96, 28.16]]] },
      properties: { poi_count: 8 },
    }],
    roadSyntaxSummary: { edge_count: 1 },
    roadSyntaxRoadFeatures: [{
      type: 'Feature',
      geometry: { type: 'LineString', coordinates: [[112.9, 28.1], [112.98, 28.18]] },
      properties: { choice_score: 0.8 },
    }],
    allPoisDetails: [{ id: 'poi-1', type: '餐饮', lng: 112.94, lat: 28.14 }],
    renderPptMapRequestMainMapSnapshot() {
      throw new Error('main_map_should_not_be_called')
    },
  })

  try {
    const directMap = new FakeMap(createNode('div'))
    assert.deepEqual(ctx.projectPptMapSvgPoint(directMap, [112.9, 28.1]), [900, 900])
    assert.match(ctx.pptMapSvgPathForRing(directMap, [[112.9, 28.1], [112.92, 28.1], [112.92, 28.12], [112.9, 28.1]]), /^M900 900 L920 900/)
    const dataUrl = await ctx.renderPptMapRequestSnapshot({
      composition: 'composite_nightlife',
      title: '复合空间诊断',
      layers: [
        { layer_type: 'scope_boundary', source: 'current:scope' },
        { layer_type: 'population_grid', source: 'current:analysis:population' },
        { layer_type: 'nightlight_grid', source: 'current:analysis:nightlight' },
        { layer_type: 'h3_grid', source: 'current:analysis:h3' },
        { layer_type: 'road_syntax', source: 'current:analysis:road', metric: 'choice' },
        { layer_type: 'poi_points', source: 'current:dataset:poi' },
      ],
    })

    assert.equal(dataUrl, 'data:image/png;base64,svg-map')
    assert.equal(createdMaps.length, 2)
    assert.equal(createdMaps[1].destroyed, true)
    assert.equal(appendedHosts[0].parentNode, null)
  } finally {
    if (originalDocument === undefined) delete globalThis.document
    else globalThis.document = originalDocument
    if (originalWindow === undefined) delete globalThis.window
    else globalThis.window = originalWindow
    if (originalHtml2canvas === undefined) delete globalThis.html2canvas
    else globalThis.html2canvas = originalHtml2canvas
    if (originalAmap === undefined) delete globalThis.AMap
    else globalThis.AMap = originalAmap
  }
})

test('ppt visual api context disables main map snapshot fallback', async () => {
  const methods = createAgentPptPlanningTabMethods()
  let seenOptions = null
  const ctx = {}
  Object.assign(ctx, methods, {
    buildAgentPptPlanningApiContext: () => ({ current: { area_id: 'area-1' } }),
    ensureAgentVisualSnapshotCache: async (options = {}) => {
      seenOptions = options
      return [{ kind: 'population_map', data_url: 'data:image/png;base64,map' }]
    },
  })

  const context = await ctx.buildAgentPptPlanningVisualApiContext()

  assert.equal(seenOptions.allowMainMapFallback, false)
  assert.equal(context.current.visual_snapshots.length, 1)
})

test('agent visual snapshot capture can disable legacy main map fallback', async () => {
  const runtime = createAgentRuntimeMethods()
  let legacyCalls = 0
  const ctx = {}
  Object.assign(ctx, runtime, {
    buildAgentVisualSnapshotTargets: () => [{ kind: 'population_map', key: 'population' }],
    canCaptureAgentOffscreenVisualSnapshots: () => false,
    captureAgentLegacyVisualSnapshots: async () => {
      legacyCalls += 1
      return [{ kind: 'population_map', data_url: 'data:image/png;base64,legacy' }]
    },
  })

  const snapshots = await ctx.captureAgentVisualSnapshots({ allowMainMapFallback: false })

  assert.equal(legacyCalls, 0)
  assert.equal(snapshots[0].data_url, '')
  assert.deepEqual(snapshots[0].warnings, ['offscreen_snapshot_unavailable_main_map_fallback_disabled'])
})

test('ppt map request runtime hydrates history scope and missing layer data before capture', async () => {
  const runtime = createAgentRuntimeMethods()
  const ctx = {}
  const calls = []
  const originalFetch = globalThis.fetch
  Object.assign(ctx, runtime, {
    currentHistoryRecordId: 'history-1',
    historyDetailLoadToken: 7,
    restoreHistoryArtifactsAsync(historyId, token) {
      calls.push({ type: 'artifacts', historyId, token })
      this.populationOverview = { summary: { total_population: 1200 } }
      this.populationLayer = { cells: [{ cell_id: 'cell-1' }] }
      return Promise.resolve({ populationRestored: true })
    },
    _restoreHistoryPoisAsync(historyId, token, signal, hint, year) {
      calls.push({ type: 'pois', historyId, token, signal, hint, year })
      this.allPoisDetails = [{ id: 'poi-1', location: [112.9, 28.2] }]
      return Promise.resolve(true)
    },
  })
  globalThis.fetch = async (url) => {
    calls.push({ type: 'fetch', url: String(url) })
    return {
      ok: true,
      json: async () => ({
        polygon: [[112.9, 28.2], [113.0, 28.2], [113.0, 28.3], [112.9, 28.2]],
        polygon_wgs84: [[112.89, 28.19], [112.99, 28.19], [112.99, 28.29], [112.89, 28.19]],
      }),
    }
  }
  try {
    const restored = await ctx.ensurePptMapRequestHistoryData({
      composition: 'population',
      layers: [
        { layer_type: 'scope_boundary', source: 'current:scope' },
        { layer_type: 'population_grid', source: 'current:analysis:population' },
        { layer_type: 'poi_points', source: 'current:dataset:poi' },
      ],
    })
    assert.equal(restored, true)
    assert.equal(ctx.currentHistoryRecordId, 'history-1')
    assert.equal(ctx.currentHistoryPolygon.length, 4)
    assert.equal(ctx.getAgentScopeBounds().west, 112.9)
    assert.equal(ctx.populationLayer.cells.length, 1)
    assert.equal(ctx.allPoisDetails.length, 1)
    assert.deepEqual(calls.map((item) => item.type), ['fetch', 'artifacts', 'pois'])
    assert.equal(calls[1].token, 7)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('ppt map snapshot capture errors expose readable layer failure messages', () => {
  const runtime = createAgentRuntimeMethods()
  const ctx = {}
  Object.assign(ctx, runtime)

  const population = ctx.normalizePptMapSnapshotCaptureError(new Error('ppt_map_request_layer_data_missing:population_grid'))
  assert.equal(population.message, '人口图层数据未恢复')
  assert.equal(population.layer_type, 'population_grid')
  assert.equal(population.renderer_ready, true)

  const h3 = ctx.normalizePptMapSnapshotCaptureError(new Error('ppt_map_request_layer_data_missing:h3_grid'))
  assert.equal(h3.message, 'H3 网格数据未恢复')

  const renderer = ctx.normalizePptMapSnapshotCaptureError(new Error('ppt_map_renderer_amap_unavailable'))
  assert.equal(renderer.message, '地图截图环境未就绪：高德地图脚本未加载')
  assert.equal(renderer.renderer_ready, false)

  const empty = ctx.normalizePptMapSnapshotCaptureError(new Error('ppt_map_snapshot_data_url_empty'))
  assert.equal(empty.message, '地图截图导出为空')
})

test('ppt carrier snapshot request renders package geometry into map asset', async () => {
  const visual = {
    visual_type: 'existing_asset',
    status: 'needs_existing_asset',
    source_ids: ['package:poi-road-carriers:test'],
    data: {
      composition: 'carrier_snapshot_request',
      package_source_id: 'package:poi-road-carriers:test',
      carrier_snapshot_request: {
        title: '核心空间载体分布图',
        package_source_id: 'package:poi-road-carriers:test',
        extent_mode: 'all',
      },
    },
  }
  assert.equal(isPptCarrierSnapshotRequest(visual), true)

  const asset = await capturePptCarrierSnapshotAsset(visual.data.carrier_snapshot_request, {
    sources: [{
      id: 'package:poi-road-carriers:test',
      meta: {
        package: {
          title: '核心空间载体',
          summary: '真实资料包几何',
          road_context: {
            features: [{ id: 'r1', path: [[116.1, 39.1], [116.2, 39.2]], is_skeleton: true }],
          },
          carriers: [{
            carrier_id: 'corridor_01',
            carrier_type: 'corridor',
            carrier_label: '商业活力廊道',
            geometry: { boundary: [[116.1, 39.1], [116.16, 39.15], [116.2, 39.2]] },
          }],
        },
      },
    }],
  })

  assert.equal(asset.asset_kind, 'map_snapshot')
  assert.equal(asset.source, 'frontend_carrier_package_snapshot')
  assert.match(asset.data_url, /^data:image\/svg\+xml;base64,/)
  assert.equal(asset.data.composition, 'carrier_snapshot')
  assert.equal(asset.data.package_source_id, 'package:poi-road-carriers:test')
})

test('ppt carrier snapshot refuses package without geometry', async () => {
  await assert.rejects(
    () => capturePptCarrierSnapshotAsset({
      package_source_id: 'package:poi-road-carriers:test',
    }, {
      sources: [{
        id: 'package:poi-road-carriers:test',
        meta: { package: { carriers: [{ carrier_id: 'corridor_01', geometry: {} }] } },
      }],
    }),
    /ppt_carrier_geometry_missing/,
  )
})

test('ppt visual artifact generation captures map requests before writeback', async () => {
  const methods = createAgentPptPlanningTabMethods()
  const state = createPptPlanningState({
    deckBrief: {
      slides: [{
        index: 1,
        title: '人口密度',
        visualSpecs: [{
          visual_id: 'visual-map',
          visual_type: 'existing_asset',
          status: 'needs_existing_asset',
          title: '人口密度',
          data: {
            composition: 'map_snapshot_request',
            capture_error: { code: 'ppt_map_snapshot_capture_failed', message: '旧错误' },
            map_request: {
              composition: 'population',
              layers: [{ layer_type: 'population_grid', source: 'current:analysis:population' }],
            },
          },
        }],
        visualArtifacts: [],
      }],
    },
  })
  const calls = []
  let mainMapRenderCalls = 0
  let offscreenRenderCalls = 0
  const ctx = {}
  Object.assign(ctx, methods, {
    activeStep3Panel: 'agent',
    poiSubTab: 'category',
    roadSyntaxMainTab: 'params',
    agentTabs: {
      activeTabId: 'ppt-1',
      pptPlanningTabs: [{ id: 'ppt-1', kind: 'ppt_planning', pptPlanningState: state }],
      summaryTabs: [],
      iterationChangeTabs: [],
      siteSelectionTabs: [],
      deepAnalysisTabs: [],
      followupTabs: [],
    },
    getAgentActivePptPlanningTab: () => ({ id: 'ppt-1' }),
    getAgentPptPlanningTabStateWithSystemSources: () => ctx.agentTabs.pptPlanningTabs[0].pptPlanningState,
    updateAgentPptPlanningTabState: (_tabId, nextState) => {
      ctx.agentTabs.pptPlanningTabs[0].pptPlanningState = nextState
    },
    buildAgentPptPlanningVisualApiContext: async () => ({ current: {} }),
    ensurePptMapRequestHistoryData: async () => true,
    renderPptMapRequestMainMapSnapshot: async () => {
      mainMapRenderCalls += 1
      return 'data:image/png;base64,main'
    },
    requestAgentPptPlanningVisualArtifacts: async (payload) => {
      calls.push(payload)
      if (calls.length === 1) {
        assert.equal(payload.visual_specs[0].data.capture_error, undefined)
        return {
          slide_index: 1,
          visual_specs: [{
            visual_id: 'visual-map',
            visual_type: 'existing_asset',
            status: 'needs_existing_asset',
            data: {
              composition: 'map_snapshot_request',
              map_request: {
                composition: 'population',
                title: '人口密度',
                layers: [{ layer_type: 'population_grid', source: 'current:analysis:population' }],
              },
            },
          }],
          visual_artifacts: [],
        }
      }
      assert.equal(payload.existing_assets[0].asset_kind, 'map_snapshot')
      return {
        slide_index: 1,
        visual_specs: [{ visual_id: 'visual-map', visual_type: 'existing_asset', status: 'renderable' }],
        visual_artifacts: [{ visual_id: 'visual-map', url: payload.existing_assets[0].data_url }],
      }
    },
    ensurePptMapSnapshotRendererReady: async () => {
      return true
    },
    renderPptMapRequestSnapshot: async () => {
      offscreenRenderCalls += 1
      return 'data:image/png;base64,offscreen'
    },
  })

  await ctx.generateAgentPptPlanningSlideVisuals(1)
  assert.equal(calls.length, 2)
  assert.equal(mainMapRenderCalls, 1)
  assert.equal(offscreenRenderCalls, 0)
  assert.equal(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState.deckBrief.slides[0].visualArtifacts[0].url, 'data:image/png;base64,main')
  assert.equal(ctx.activeStep3Panel, 'agent')
  assert.equal(ctx.poiSubTab, 'category')
  assert.equal(ctx.roadSyntaxMainTab, 'params')
})

test('ppt visual artifact generation captures carrier package snapshot requests before writeback', async () => {
  const methods = createAgentPptPlanningTabMethods()
  const state = createPptPlanningState({
    sources: [{
      id: 'package:poi-road-carriers:test',
      type: 'package',
      selected: true,
      meta: {
        package: {
          carriers: [{
            carrier_id: 'corridor_01',
            carrier_type: 'corridor',
            carrier_label: '商业活力廊道',
            geometry: { boundary: [[116.1, 39.1], [116.16, 39.15], [116.2, 39.2]] },
          }],
          road_context: {
            features: [{ id: 'road-1', path: [[116.1, 39.1], [116.2, 39.2]], is_skeleton: true }],
          },
        },
      },
    }],
    deckBrief: {
      slides: [{
        index: 1,
        title: '核心空间载体',
        visualSpecs: [{
          visual_id: 'visual-carrier-map',
          visual_type: 'existing_asset',
          status: 'needs_existing_asset',
          title: '核心空间载体分布图',
          source_ids: ['package:poi-road-carriers:test'],
          data: {
            composition: 'carrier_snapshot_request',
            package_source_id: 'package:poi-road-carriers:test',
            carrier_snapshot_request: {
              title: '核心空间载体分布图',
              package_source_id: 'package:poi-road-carriers:test',
              extent_mode: 'all',
            },
          },
        }],
        visualArtifacts: [],
      }],
    },
  })
  const calls = []
  const ctx = {}
  Object.assign(ctx, methods, {
    agentTabs: {
      activeTabId: 'ppt-1',
      pptPlanningTabs: [{ id: 'ppt-1', kind: 'ppt_planning', pptPlanningState: state }],
      summaryTabs: [],
      iterationChangeTabs: [],
      siteSelectionTabs: [],
      deepAnalysisTabs: [],
      followupTabs: [],
    },
    getAgentActivePptPlanningTab: () => ({ id: 'ppt-1' }),
    getAgentPptPlanningTabStateWithSystemSources: () => ctx.agentTabs.pptPlanningTabs[0].pptPlanningState,
    getAgentPptPlanningStateWithSystemSources: () => ctx.agentTabs.pptPlanningTabs[0].pptPlanningState,
    updateAgentPptPlanningTabState: (_tabId, nextState) => {
      ctx.agentTabs.pptPlanningTabs[0].pptPlanningState = nextState
    },
    buildAgentPptPlanningVisualApiContext: async () => ({ current: {} }),
    requestAgentPptPlanningVisualArtifacts: async (payload) => {
      calls.push(payload)
      if (calls.length === 1) {
        return {
          slide_index: 1,
          visual_specs: [{
            visual_id: 'visual-carrier-map',
            visual_type: 'existing_asset',
            status: 'needs_existing_asset',
            title: '核心空间载体分布图',
            source_ids: ['package:poi-road-carriers:test'],
            data: {
              composition: 'carrier_snapshot_request',
              package_source_id: 'package:poi-road-carriers:test',
              carrier_snapshot_request: {
                title: '核心空间载体分布图',
                package_source_id: 'package:poi-road-carriers:test',
                extent_mode: 'all',
              },
            },
          }],
          visual_artifacts: [],
        }
      }
      assert.equal(payload.existing_assets[0].source, 'frontend_carrier_package_snapshot')
      assert.match(payload.existing_assets[0].data_url, /^data:image\/svg\+xml;base64,/)
      return {
        slide_index: 1,
        visual_specs: [{ visual_id: 'visual-carrier-map', visual_type: 'existing_asset', status: 'renderable' }],
        visual_artifacts: [{ visual_id: 'visual-carrier-map', url: payload.existing_assets[0].data_url }],
      }
    },
  })

  await ctx.generateAgentPptPlanningSlideVisuals(1)
  assert.equal(calls.length, 2)
  assert.equal(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState.deckBrief.slides[0].visualSpecs[0].status, 'renderable')
})

test('ppt visual artifact generation captures maps from main map by default', async () => {
  const methods = createAgentPptPlanningTabMethods()
  const state = createPptPlanningState({
    deckBrief: {
      slides: [{
        index: 1,
        title: '人口密度',
        visualSpecs: [{ visual_id: 'visual-map', visual_type: 'metric_card', title: '人口密度' }],
        visualArtifacts: [],
      }],
    },
  })
  const events = []
  const ctx = {}
  Object.assign(ctx, methods, {
    agentTabs: {
      activeTabId: 'ppt-1',
      pptPlanningTabs: [{ id: 'ppt-1', kind: 'ppt_planning', pptPlanningState: state }],
      summaryTabs: [],
      iterationChangeTabs: [],
      siteSelectionTabs: [],
      deepAnalysisTabs: [],
      followupTabs: [],
    },
    getAgentActivePptPlanningTab: () => ({ id: 'ppt-1' }),
    getAgentPptPlanningTabStateWithSystemSources: () => ctx.agentTabs.pptPlanningTabs[0].pptPlanningState,
    updateAgentPptPlanningTabState: (_tabId, nextState) => {
      ctx.agentTabs.pptPlanningTabs[0].pptPlanningState = nextState
    },
    buildAgentPptPlanningVisualApiContext: async () => ({ current: {} }),
    ensurePptMapRequestHistoryData: async () => true,
    ensurePptMapSnapshotRendererReady: async () => {
      events.push('ready-offscreen')
    },
    renderPptMapRequestMainMapSnapshot: async () => {
      events.push('render-main')
      return 'data:image/png;base64,main-map'
    },
    renderPptMapRequestSnapshot: async () => {
      events.push('render-offscreen')
      return 'data:image/png;base64,offscreen'
    },
    requestAgentPptPlanningVisualArtifacts: async (payload) => {
      if (!payload.existing_assets.length) {
        return {
          slide_index: 1,
          visual_specs: [{
            visual_id: 'visual-map',
            visual_type: 'existing_asset',
            status: 'needs_existing_asset',
            data: {
              composition: 'map_snapshot_request',
              map_request: {
                composition: 'population',
                layers: [{ layer_type: 'population_grid', source: 'current:analysis:population' }],
              },
            },
          }],
          visual_artifacts: [],
        }
      }
      return {
        slide_index: 1,
        visual_specs: [{ visual_id: 'visual-map', visual_type: 'existing_asset', status: 'renderable' }],
        visual_artifacts: [{ visual_id: 'visual-map', url: payload.existing_assets[0].data_url }],
      }
    },
  })

  await ctx.generateAgentPptPlanningSlideVisuals(1)

  assert.deepEqual(events, ['render-main'])
  assert.equal(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState.deckBrief.slides[0].visualArtifacts[0].url, 'data:image/png;base64,main-map')
})

test('ppt map request capture can explicitly prefer offscreen renderer', async () => {
  const methods = createAgentPptPlanningTabMethods()
  const visual = {
    visual_id: 'visual-map',
    visual_type: 'existing_asset',
    status: 'needs_existing_asset',
    data: {
      composition: 'map_snapshot_request',
      map_request: {
        composition: 'population',
        layers: [{ layer_type: 'population_grid', source: 'current:analysis:population' }],
      },
    },
  }
  const events = []
  const ctx = {}
  Object.assign(ctx, methods, {
    ensurePptMapRequestHistoryData: async () => true,
    ensurePptMapSnapshotRendererReady: async () => {
      events.push('ready-offscreen')
    },
    renderPptMapRequestSnapshot: async () => {
      events.push('render-offscreen')
      return 'data:image/png;base64,offscreen'
    },
    renderPptMapRequestMainMapSnapshot: async () => {
      events.push('render-main')
      return 'data:image/png;base64,main'
    },
  })

  const result = await ctx.captureAgentPptMapRequestAssets([visual], { preferOffscreenMapCapture: true })

  assert.deepEqual(events, ['ready-offscreen', 'render-offscreen'])
  assert.equal(result.assets[0].data_url, 'data:image/png;base64,offscreen')
})

test('ppt map request capture deduplicates identical scenes and reuses cache', async () => {
  const methods = createAgentPptPlanningTabMethods()
  const visuals = [
    {
      visual_id: 'visual-map-a',
      visual_type: 'existing_asset',
      status: 'needs_existing_asset',
      title: '人口分布 A',
      source_ids: ['current:analysis:population'],
      data: {
        composition: 'map_snapshot_request',
        map_request: {
          composition: 'population',
          title: '人口分布 A',
          layers: [
            { layer_type: 'scope_boundary', source: 'current:scope' },
            { layer_type: 'population_grid', source: 'current:analysis:population' },
          ],
        },
      },
    },
    {
      visual_id: 'visual-map-b',
      visual_type: 'existing_asset',
      status: 'needs_existing_asset',
      title: '人口分布 B',
      source_ids: ['current:analysis:population'],
      data: {
        composition: 'map_snapshot_request',
        map_request: {
          composition: 'population',
          title: '人口分布 B',
          layers: [
            { layer_type: 'population_grid', source: 'current:analysis:population' },
            { layer_type: 'scope_boundary', source: 'current:scope' },
          ],
        },
      },
    },
  ]
  let captureCount = 0
  let hydrateCount = 0
  const ctx = {}
  Object.assign(ctx, methods, {
    buildAgentVisualSnapshotFingerprint: () => 'fingerprint-1',
    ensurePptMapRequestHistoryData: async () => {
      hydrateCount += 1
      return true
    },
    renderPptMapRequestMainMapSnapshot: async () => {
      captureCount += 1
      return 'data:image/png;base64,deduped-map'
    },
  })

  const first = await ctx.captureAgentPptMapRequestAssets(visuals)
  const second = await ctx.captureAgentPptMapRequestAssets(visuals)

  assert.equal(captureCount, 1)
  assert.equal(hydrateCount, 1)
  assert.equal(first.assets.length, 2)
  assert.deepEqual(first.assets.map((asset) => asset.visual_id).sort(), ['visual-map-a', 'visual-map-b'])
  assert.equal(first.assets[0].data_url, 'data:image/png;base64,deduped-map')
  assert.equal(first.assets[1].data_url, 'data:image/png;base64,deduped-map')
  assert.equal(second.assets.length, 2)
  assert.equal(second.assets[0].data_url, 'data:image/png;base64,deduped-map')
  assert.equal(Object.keys(ctx.pptMapSnapshotAssetCache || {}).length, 1)
})

test('ppt map request capture keeps different scenes separate', async () => {
  const methods = createAgentPptPlanningTabMethods()
  const visuals = [
    {
      visual_id: 'visual-road-choice',
      visual_type: 'existing_asset',
      status: 'needs_existing_asset',
      data: {
        composition: 'map_snapshot_request',
        map_request: {
          composition: 'road',
          layers: [{ layer_type: 'road_syntax', source: 'current:analysis:road', metric: 'choice' }],
        },
      },
    },
    {
      visual_id: 'visual-road-integration',
      visual_type: 'existing_asset',
      status: 'needs_existing_asset',
      data: {
        composition: 'map_snapshot_request',
        map_request: {
          composition: 'road',
          layers: [{ layer_type: 'road_syntax', source: 'current:analysis:road', metric: 'integration' }],
        },
      },
    },
  ]
  let captureCount = 0
  const ctx = {}
  Object.assign(ctx, methods, {
    buildAgentVisualSnapshotFingerprint: () => 'fingerprint-1',
    ensurePptMapRequestHistoryData: async () => true,
    renderPptMapRequestMainMapSnapshot: async () => {
      captureCount += 1
      return `data:image/png;base64,road-${captureCount}`
    },
  })

  const result = await ctx.captureAgentPptMapRequestAssets(visuals)

  assert.equal(captureCount, 2)
  assert.equal(result.assets.length, 2)
  assert.equal(result.assets[0].data_url, 'data:image/png;base64,road-1')
  assert.equal(result.assets[1].data_url, 'data:image/png;base64,road-2')
})

test('ppt carrier snapshots do not use map scene cache', async () => {
  const methods = createAgentPptPlanningTabMethods()
  const visual = {
    visual_id: 'visual-carrier-map',
    visual_type: 'existing_asset',
    status: 'needs_existing_asset',
    source_ids: ['package:poi-road-carriers:test'],
    data: {
      composition: 'carrier_snapshot_request',
      package_source_id: 'package:poi-road-carriers:test',
      carrier_snapshot_request: {
        title: '核心空间载体分布图',
        package_source_id: 'package:poi-road-carriers:test',
        extent_mode: 'all',
      },
    },
  }
  const ctx = {}
  Object.assign(ctx, methods, {
    pptMapSnapshotAssetCache: {
      stale: { data_url: 'data:image/png;base64,map-cache' },
    },
    getAgentPptPlanningStateWithSystemSources: () => ({
      sources: [{
        id: 'package:poi-road-carriers:test',
        meta: {
          package: {
            carriers: [{
              carrier_id: 'corridor_01',
              carrier_type: 'corridor',
              carrier_label: '商业活力廊道',
              geometry: { boundary: [[116.1, 39.1], [116.16, 39.15], [116.2, 39.2]] },
            }],
          },
        },
      }],
    }),
    renderPptMapRequestMainMapSnapshot() {
      throw new Error('map_capture_should_not_run_for_carrier')
    },
  })

  const result = await ctx.captureAgentPptMapRequestAssets([visual])

  assert.equal(result.assets.length, 1)
  assert.equal(result.assets[0].source, 'frontend_carrier_package_snapshot')
  assert.match(result.assets[0].data_url, /^data:image\/svg\+xml;base64,/)
  assert.equal(Object.keys(ctx.pptMapSnapshotAssetCache).length, 1)
})

test('ppt visual artifact generation hydrates map request data before rendering snapshot', async () => {
  const methods = createAgentPptPlanningTabMethods()
  const state = createPptPlanningState({
    deckBrief: {
      slides: [{
        index: 1,
        title: '人口密度',
        visualSpecs: [{ visual_id: 'visual-map', visual_type: 'metric_card', title: '人口密度' }],
      }],
    },
  })
  const events = []
  const ctx = {}
  Object.assign(ctx, methods, {
    agentTabs: {
      activeTabId: 'ppt-1',
      pptPlanningTabs: [{ id: 'ppt-1', kind: 'ppt_planning', pptPlanningState: state }],
      summaryTabs: [],
      iterationChangeTabs: [],
      siteSelectionTabs: [],
      deepAnalysisTabs: [],
      followupTabs: [],
    },
    getAgentActivePptPlanningTab: () => ({ id: 'ppt-1' }),
    getAgentPptPlanningTabStateWithSystemSources: () => ctx.agentTabs.pptPlanningTabs[0].pptPlanningState,
    updateAgentPptPlanningTabState: (_tabId, nextState) => {
      ctx.agentTabs.pptPlanningTabs[0].pptPlanningState = nextState
    },
    buildAgentPptPlanningVisualApiContext: async () => ({ current: {} }),
    ensurePptMapRequestHistoryData: async (mapRequest) => {
      events.push(`hydrate:${mapRequest.composition}`)
      return true
    },
    requestAgentPptPlanningVisualArtifacts: async (payload) => {
      if (events.length === 0) events.push('request-initial')
      if (events.filter((item) => item === 'request-initial').length === 1 && !payload.existing_assets.length) {
        return {
          slide_index: 1,
          visual_specs: [{
            visual_id: 'visual-map',
            visual_type: 'existing_asset',
            status: 'needs_existing_asset',
            data: {
              composition: 'map_snapshot_request',
              map_request: {
                composition: 'population',
                layers: [{ layer_type: 'population_grid', source: 'current:analysis:population' }],
              },
            },
          }],
          visual_artifacts: [],
        }
      }
      events.push('request-writeback')
      return {
        slide_index: 1,
        visual_specs: [{ visual_id: 'visual-map', visual_type: 'existing_asset', status: 'renderable' }],
        visual_artifacts: [{ visual_id: 'visual-map', url: payload.existing_assets[0].data_url }],
      }
    },
    renderPptMapRequestMainMapSnapshot: async () => {
      events.push('render-main')
      return 'data:image/png;base64,captured'
    },
    ensurePptMapSnapshotRendererReady: async () => {
      events.push('ready-offscreen')
    },
    renderPptMapRequestSnapshot: async () => {
      events.push('render-offscreen')
      return 'data:image/png;base64,offscreen'
    },
  })

  await ctx.generateAgentPptPlanningSlideVisuals(1)

  assert.deepEqual(events, ['request-initial', 'hydrate:population', 'render-main', 'request-writeback'])
  assert.equal(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState.deckBrief.slides[0].visualArtifacts[0].url, 'data:image/png;base64,captured')
})

test('ppt visual artifact generation isolates failed map captures per visual', async () => {
  const methods = createAgentPptPlanningTabMethods()
  const runtime = createAgentRuntimeMethods()
  const state = createPptPlanningState({
    deckBrief: {
      slides: [{
        index: 1,
        title: '空间诊断',
        visualSpecs: [
          { visual_id: 'visual-pop', visual_type: 'metric_card', title: '人口密度' },
          { visual_id: 'visual-h3', visual_type: 'metric_card', title: 'H3 网格' },
        ],
        visualArtifacts: [],
      }],
    },
  })
  const calls = []
  const ctx = {}
  Object.assign(ctx, methods, runtime, {
    agentTabs: {
      activeTabId: 'ppt-1',
      pptPlanningTabs: [{ id: 'ppt-1', kind: 'ppt_planning', pptPlanningState: state }],
      summaryTabs: [],
      iterationChangeTabs: [],
      siteSelectionTabs: [],
      deepAnalysisTabs: [],
      followupTabs: [],
    },
    getAgentActivePptPlanningTab: () => ({ id: 'ppt-1' }),
    getAgentPptPlanningTabStateWithSystemSources: () => ctx.agentTabs.pptPlanningTabs[0].pptPlanningState,
    updateAgentPptPlanningTabState: (_tabId, nextState) => {
      ctx.agentTabs.pptPlanningTabs[0].pptPlanningState = nextState
    },
    buildAgentPptPlanningVisualApiContext: async () => ({ current: {} }),
    ensurePptMapRequestHistoryData: async () => true,
    renderPptMapRequestMainMapSnapshot: async (mapRequest) => {
      if (mapRequest.composition === 'population') {
        throw new Error('ppt_map_request_layer_data_missing:population_grid')
      }
      return 'data:image/png;base64,h3'
    },
    requestAgentPptPlanningVisualArtifacts: async (payload) => {
      calls.push(payload)
      if (calls.length === 1) {
        return {
          slide_index: 1,
          visual_specs: [
            {
              visual_id: 'visual-pop',
              visual_type: 'existing_asset',
              status: 'needs_existing_asset',
              data: {
                composition: 'map_snapshot_request',
                map_request: {
                  composition: 'population',
                  layers: [{ layer_type: 'population_grid', source: 'current:analysis:population' }],
                },
              },
            },
            {
              visual_id: 'visual-h3',
              visual_type: 'existing_asset',
              status: 'needs_existing_asset',
              data: {
                composition: 'map_snapshot_request',
                map_request: {
                  composition: 'h3',
                  layers: [{ layer_type: 'h3_grid', source: 'current:analysis:h3' }],
                },
              },
            },
          ],
          visual_artifacts: [],
        }
      }
      assert.equal(payload.existing_assets.length, 1)
      assert.equal(payload.existing_assets[0].visual_id, 'visual-h3')
      const failed = payload.visual_specs.find((visual) => visual.visual_id === 'visual-pop')
      assert.equal(failed.data.capture_error.message, '人口图层数据未恢复')
      assert.equal(failed.data.capture_error.code, 'ppt_map_request_layer_data_missing')
      return {
        slide_index: 1,
        visual_specs: [
          failed,
          { visual_id: 'visual-h3', visual_type: 'existing_asset', status: 'renderable' },
        ],
        visual_artifacts: [{ visual_id: 'visual-h3', url: payload.existing_assets[0].data_url }],
      }
    },
  })

  await ctx.generateAgentPptPlanningSlideVisuals(1)

  const slide = ctx.agentTabs.pptPlanningTabs[0].pptPlanningState.deckBrief.slides[0]
  assert.equal(calls.length, 2)
  assert.equal(slide.visualArtifacts[0].url, 'data:image/png;base64,h3')
  assert.equal(slide.visualSpecs[0].data.capture_error.message, '人口图层数据未恢复')
  assert.equal(slide.visualSpecs[1].status, 'renderable')
})

test('ppt visual artifact generation does not create css fallback maps without real renderer', async () => {
  const methods = createAgentPptPlanningTabMethods()
  const runtime = createAgentRuntimeMethods()
  const state = createPptPlanningState({
    deckBrief: {
      slides: [{
        index: 1,
        title: '人口密度',
        visualSpecs: [{ visual_id: 'visual-map', visual_type: 'metric_card', title: '人口密度' }],
        visualArtifacts: [],
      }],
    },
  })
  const calls = []
  const ctx = {}
  Object.assign(ctx, methods, runtime, {
    agentTabs: {
      activeTabId: 'ppt-1',
      pptPlanningTabs: [{ id: 'ppt-1', kind: 'ppt_planning', pptPlanningState: state }],
      summaryTabs: [],
      iterationChangeTabs: [],
      siteSelectionTabs: [],
      deepAnalysisTabs: [],
      followupTabs: [],
    },
    getAgentActivePptPlanningTab: () => ({ id: 'ppt-1' }),
    getAgentPptPlanningTabStateWithSystemSources: () => ctx.agentTabs.pptPlanningTabs[0].pptPlanningState,
    updateAgentPptPlanningTabState: (_tabId, nextState) => {
      ctx.agentTabs.pptPlanningTabs[0].pptPlanningState = nextState
    },
    buildAgentPptPlanningVisualApiContext: async () => ({ current: {} }),
    renderPptMapRequestMainMapSnapshot: async () => {
      throw new Error('ppt_map_main_capture_unavailable')
    },
    requestAgentPptPlanningVisualArtifacts: async (payload) => {
      calls.push(payload)
      return {
        slide_index: 1,
        visual_specs: [{
          visual_id: 'visual-map',
          visual_type: 'existing_asset',
          status: 'needs_existing_asset',
          data: {
            composition: 'map_snapshot_request',
            map_request: {
              composition: 'population',
              title: '人口密度',
              layers: [{ layer_type: 'population_grid', source: 'current:analysis:population' }],
            },
          },
        }],
        visual_artifacts: [],
      }
    },
  })

  await ctx.generateAgentPptPlanningSlideVisuals(1)
  assert.equal(calls.length, 1)
  const slide = ctx.agentTabs.pptPlanningTabs[0].pptPlanningState.deckBrief.slides[0]
  assert.equal(slide.visualSpecs[0].status, 'needs_existing_asset')
  assert.equal(slide.visualSpecs[0].data.capture_error.message, '主地图截图方法不可用')
  assert.equal(slide.visualSpecs[0].data.capture_error.code, 'ppt_map_main_capture_unavailable')
  assert.equal(slide.visualSpecs[0].data.capture_error.renderer_ready, true)
  assert.equal(slide.visualArtifacts.length, 0)
})

test('ppt visual artifact failure does not change generated brief slides', () => {
  const state = createPptPlanningState({
    deckBrief: {
      slides: [{
        index: 1,
        title: '项目命题',
        purpose: '建立汇报主线',
        visualSpecs: [{ visual_id: 'visual-1', visual_type: 'figure', status: 'renderable', title: 'POI' }],
        visualArtifacts: [],
      }],
    },
  })

  const failed = failPptVisualArtifacts(state, 1, 'renderer timeout')

  assert.equal(failed.deckBrief.slides[0].title, '项目命题')
  assert.equal(failed.deckBrief.slides[0].visualArtifacts.length, 0)
  assert.equal(failed.visualGenerationBySlide['1'].status, 'failed')
  assert.equal(failed.visualGenerationBySlide['1'].error, 'renderer timeout')
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

  ctx.toggleAgentPptPlanningSource('current:scope')

  const state = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)
  const scope = state.sources.find((item) => item.id === 'current:scope')
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
    requestAgentPptPlanningOutlineWithDebug(payload, options = {}) {
      return this.requestAgentPptPlanningOutline(payload, options)
    },
    requestAgentPptPlanningDeckBriefJob() {
      return Promise.resolve({ job_id: 'brief-job-active', status: 'queued' })
    },
    requestAgentPptPlanningDeckBriefJobStatus() {
      return Promise.resolve({
        job_id: 'brief-job-active',
        status: 'completed',
        result: {
          status: 'draft',
          slides: [
            {
              index: 1,
              title: '项目命题',
              purpose: '建立汇报主线',
              key_message: '解释项目为什么成立',
              visual_plan: '区域底图',
              required_sources: ['current:scope'],
            },
          ],
        },
      })
    },
    buildAgentPptPlanningVisualApiContext() {
      throw new Error('visual context should not block full brief generation')
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
  assert.ok(state.generationJob.events.find((event) => event.name === 'directive_response_unwrapped' && event.details.slideCount === 1))
  assert.ok(state.generationJob.events.find((event) => event.name === 'directive_apply_done' && event.details.slideCount === 1))
  assert.equal(state.generationError, '')
})

test('agent ppt deck brief job completed writes slides into the active tab', async () => {
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
    requestAgentPptPlanningDeckBriefJob() {
      return Promise.resolve({
        job_id: 'brief-job-1',
        status: 'queued',
        updated_at: '2026-06-18T00:00:00.000Z',
      })
    },
    requestAgentPptPlanningDeckBriefJobStatus() {
      return Promise.resolve({
        job_id: 'brief-job-1',
        status: 'completed',
        updated_at: '2026-06-18T00:00:01.000Z',
        result: {
          status: 'draft',
          slides: [
            { index: 1, title: '项目命题', purpose: '建立汇报主线', key_message: '问题成立' },
          ],
        },
      })
    },
    syncCurrentAgentSession() {},
    buildAgentPptPlanningVisualApiContext() {
      return Promise.resolve({
        areaId: 'history-1',
        current: { visual_snapshots: [] },
      })
    },
  }

  let state = applyPptSpecResponse(createPptPlanningState(), {
    outline: [
      { id: 'page-1', page_no: 1, theme: '项目命题', purpose: '建立汇报主线' },
    ],
  })
  state = applyNarrativePlanResponse(state, {
    storyline: '从问题到证据',
    slide_roles: [{ page_no: 1, role: '开题', job: '建立问题' }],
  })
  ctx.agentTabs.pptPlanningTabs[0].pptPlanningState = state

  await ctx.generateAgentPptPlanningDirective()

  const finalState = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)
  assert.equal(finalState.currentStep, 'directive_draft')
  assert.equal(finalState.deckBrief.slides.length, 1)
  assert.equal(finalState.deckBrief.slides[0].title, '项目命题')
  assert.ok(finalState.generationJob.events.find((event) => event.name === 'directive_apply_done'))
})

test('agent ppt deck brief job failed does not write slides', async () => {
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
    requestAgentPptPlanningDeckBriefJob() {
      return Promise.resolve({
        job_id: 'brief-job-2',
        status: 'queued',
        updated_at: '2026-06-18T00:00:00.000Z',
      })
    },
    requestAgentPptPlanningDeckBriefJobStatus() {
      return Promise.resolve({
        job_id: 'brief-job-2',
        status: 'failed',
        updated_at: '2026-06-18T00:00:01.000Z',
        error: {
          code: 'ppt_deck_brief_job_failed',
          message: 'brief 生成失败',
        },
      })
    },
    syncCurrentAgentSession() {},
    buildAgentPptPlanningVisualApiContext() {
      return Promise.resolve({
        areaId: 'history-1',
        current: { visual_snapshots: [] },
      })
    },
  }

  let state = applyPptSpecResponse(createPptPlanningState(), {
    outline: [
      { id: 'page-1', page_no: 1, theme: '项目命题', purpose: '建立汇报主线' },
    ],
  })
  state = applyNarrativePlanResponse(state, {
    storyline: '从问题到证据',
    slide_roles: [{ page_no: 1, role: '开题', job: '建立问题' }],
  })
  ctx.agentTabs.pptPlanningTabs[0].pptPlanningState = state

  await ctx.generateAgentPptPlanningDirective()

  const finalState = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)
  assert.equal(finalState.deckBrief.slides.length, 0)
  assert.equal(finalState.currentStep, 'slides_generating')
  assert.match(finalState.generationError, /brief 生成失败/)
})

test('ppt directive response helper fails stale or empty writebacks explicitly', () => {
  let state = applyPptSpecResponse(createPptPlanningState(), {
    outline: [{ id: 'page-1', page_no: 1, theme: '项目命题', purpose: '建立汇报主线' }],
  })
  state = startPptGenerationJob(state, { requestId: 'req-live', type: 'directive', tabId: 'ppt-1' })

  const stale = applyDirectiveResponseAndMarkReady(state, 'req-old', {
    status: 'draft',
    slides: [{ index: 1, title: '旧响应' }],
  })
  assert.equal(stale.deckBrief.slides.length, 0)
  assert.equal(stale.generationJob.phase, 'failed')
  assert.match(stale.generationError, /请求已不是当前任务/)
  assert.ok(stale.generationJob.events.find((event) => event.name === 'stale_response_ignored'))

  const missing = applyDirectiveResponseAndMarkReady(state, 'req-live', {
    status: 'draft',
    slides: [],
  })
  assert.equal(missing.deckBrief.slides.length, 0)
  assert.equal(missing.generationJob.phase, 'failed')
  assert.match(missing.generationError, /未写入前端状态/)
  assert.ok(missing.generationJob.events.find((event) => event.name === 'directive_writeback_missing'))
})

test('agent ppt slide generation marks each page active before sending its request', async () => {
  const activePageNos = []
  const activeStatuses = []
  const requestPageNos = []
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
        pptPlanningState: createPptPlanningState(),
      }],
      deepAnalysisTabs: [],
      followupTabs: [],
    },
    requestAgentPptPlanningDirectiveSlide(payload) {
      const state = createPptPlanningState(this.agentTabs.pptPlanningTabs[0].pptPlanningState)
      activePageNos.push(state.slideGenerationJob.currentPageNo)
      const pageNo = Number(payload.target && payload.target.index)
      const queueItem = state.slideGenerationQueue.find((item) => Number(item.pageNo || 0) === pageNo)
      activeStatuses.push(queueItem && queueItem.status)
      requestPageNos.push(Number(payload.target && payload.target.index))
      return Promise.resolve({
        index: Number(payload.target && payload.target.index),
        title: `页面 ${payload.target.index}`,
        purpose: '生成 brief',
        key_message: '已生成',
      })
    },
  })
  let state = applyPptSpecResponse(createPptPlanningState(), {
    outline: [
      { id: 'p1', page_no: 1, theme: '开场', purpose: '建立问题' },
      { id: 'p2', page_no: 2, theme: '证据', purpose: '说明判断' },
    ],
  })
  state = applyNarrativePlanResponse(state, {
    storyline: '从问题到证据',
    slide_roles: [
      { page_no: 1, role: '开题', job: '建立问题' },
      { page_no: 2, role: '证据页', job: '说明判断' },
    ],
  })
  ctx.agentTabs.pptPlanningTabs[0].pptPlanningState = state

  await ctx.generateAgentPptPlanningSlides()

  const finalState = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)
  assert.deepEqual(requestPageNos, [1, 2])
  assert.deepEqual(activePageNos, [1, 2])
  assert.deepEqual(activeStatuses, ['requesting', 'requesting'])
  assert.equal(finalState.deckBrief.slides.length, 2)
  assert.equal(finalState.slideGenerationJob.active, false)
  const appliedEvents = finalState.generationJob.events.filter((event) => event.name === 'slide_page_applied')
  assert.equal(appliedEvents.length, 2)
  assert.equal(appliedEvents[0].details.beforeSlideCount, 0)
  assert.equal(appliedEvents[0].details.afterSlideCount, 1)
  assert.deepEqual(appliedEvents[1].details.slideIndexes, [1, 2])
  assert.ok(finalState.generationJob.events.find((event) => event.name === 'tab_update_after_sync' && event.details.afterSyncSlideCount === 2))
})

test('agent ppt slide generation syncs only stable slide states', async () => {
  let syncCount = 0
  const ctx = createPptPlanningTestContext({
    syncCurrentAgentSession() {
      syncCount += 1
    },
    requestAgentPptPlanningDirectiveSlide(payload, options = {}) {
      if (typeof options.onDebugEvent === 'function') {
        options.onDebugEvent('fetch_response_headers_received', { status: 200, ok: true })
      }
      return Promise.resolve({
        index: Number(payload.target && payload.target.index),
        title: `页面 ${payload.target.index}`,
        purpose: '生成 brief',
        key_message: '已生成',
      })
    },
  })
  let state = applyPptSpecResponse(createPptPlanningState(), {
    outline: [
      { id: 'p1', page_no: 1, theme: '开场', purpose: '建立问题' },
      { id: 'p2', page_no: 2, theme: '证据', purpose: '说明判断' },
    ],
  })
  state = applyNarrativePlanResponse(state, {
    storyline: '从问题到证据',
    slide_roles: [
      { page_no: 1, role: '开题', job: '建立问题' },
      { page_no: 2, role: '证据页', job: '说明判断' },
    ],
  })
  ctx.agentTabs.pptPlanningTabs[0].pptPlanningState = state

  await ctx.generateAgentPptPlanningSlides()

  const finalState = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)
  assert.equal(finalState.deckBrief.slides.length, 2)
  assert.equal(syncCount, 2)
})

test('agent ppt slide generation starts without visual snapshot context', async () => {
  let visualContextCalls = 0
  const seenPayloads = []
  const ctx = createPptPlanningTestContext({
    buildAgentPptPlanningVisualApiContext() {
      visualContextCalls += 1
      throw new Error('visual context should not block brief generation')
    },
    requestAgentPptPlanningDirectiveSlide(payload) {
      seenPayloads.push(payload)
      return Promise.resolve({
        index: Number(payload.target && payload.target.index),
        title: `页面 ${payload.target.index}`,
        purpose: '生成 brief',
        key_message: '已生成',
      })
    },
  })
  let state = applyPptSpecResponse(createPptPlanningState(), {
    outline: [
      { id: 'p1', page_no: 1, theme: '开场', purpose: '建立问题' },
    ],
  })
  state = applyNarrativePlanResponse(state, {
    storyline: '从问题到证据',
    slide_roles: [
      { page_no: 1, role: '开题', job: '建立问题' },
    ],
  })
  ctx.agentTabs.pptPlanningTabs[0].pptPlanningState = state

  await ctx.generateAgentPptPlanningSlides()

  const finalState = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)
  assert.equal(visualContextCalls, 0)
  assert.equal(seenPayloads.length, 1)
  assert.deepEqual((seenPayloads[0].current || {}).visual_snapshots || [], [])
  assert.equal(finalState.deckBrief.slides.length, 1)
})

test('agent ppt slide generation rejects mismatched slide response index', async () => {
  const ctx = createPptPlanningTestContext({
    requestAgentPptPlanningDirectiveSlide(payload) {
      return Promise.resolve({
        index: Number(payload.target && payload.target.index) + 1,
        title: '错页 brief',
        purpose: '不应写入',
        key_message: '错页',
      })
    },
  })
  let state = applyPptSpecResponse(createPptPlanningState(), {
    outline: [
      { id: 'p1', page_no: 1, theme: '开场', purpose: '建立问题' },
      { id: 'p2', page_no: 2, theme: '证据', purpose: '说明判断' },
    ],
  })
  state = applyNarrativePlanResponse(state, {
    storyline: '从问题到证据',
    slide_roles: [
      { page_no: 1, role: '开题', job: '建立问题' },
      { page_no: 2, role: '证据页', job: '说明判断' },
    ],
  })
  ctx.agentTabs.pptPlanningTabs[0].pptPlanningState = state

  await ctx.generateAgentPptPlanningSlides()

  const finalState = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)
  assert.equal(finalState.deckBrief.slides.length, 0)
  assert.equal(finalState.slideGenerationQueue[0].status, 'failed')
  assert.match(finalState.generationError, /返回页码异常/)
  assert.ok(finalState.generationJob.events.find((event) => event.name === 'slide_page_response_received' && event.details.responseIndex === 2))
})

test('agent ppt slide generation fails when applied slide is lost after sync', async () => {
  const ctx = createPptPlanningTestContext({
    requestAgentPptPlanningDirectiveSlide(payload) {
      return Promise.resolve({
        index: Number(payload.target && payload.target.index),
        title: '开场 brief',
        purpose: '生成 brief',
        key_message: '已生成',
      })
    },
    syncCurrentAgentSession() {
      const tab = this.agentTabs.pptPlanningTabs[0]
      const slides = ((tab.pptPlanningState || {}).deckBrief || {}).slides || []
      if (slides.length) {
        this.agentTabs.pptPlanningTabs[0] = {
          ...tab,
          pptPlanningState: {
            ...tab.pptPlanningState,
            deckBrief: {
              ...(tab.pptPlanningState.deckBrief || {}),
              slides: [],
            },
          },
        }
      }
    },
  })
  let state = applyPptSpecResponse(createPptPlanningState(), {
    outline: [
      { id: 'p1', page_no: 1, theme: '开场', purpose: '建立问题' },
      { id: 'p2', page_no: 2, theme: '证据', purpose: '说明判断' },
    ],
  })
  state = applyNarrativePlanResponse(state, {
    storyline: '从问题到证据',
    slide_roles: [
      { page_no: 1, role: '开题', job: '建立问题' },
      { page_no: 2, role: '证据页', job: '说明判断' },
    ],
  })
  ctx.agentTabs.pptPlanningTabs[0].pptPlanningState = state

  await ctx.generateAgentPptPlanningSlides()

  const finalState = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)
  assert.equal(finalState.deckBrief.slides.length, 0)
  assert.equal(finalState.slideGenerationQueue[0].status, 'failed')
  assert.match(finalState.generationError, /写入后被同步覆盖/)
  assert.ok(finalState.generationJob.events.find((event) => event.name === 'slide_writeback_lost_after_sync'))
})

test('agent ppt slide generation records structured validation failures by page', async () => {
  const ctx = createPptPlanningTestContext({
    requestAgentPptPlanningDirectiveSlide(payload, options = {}) {
      if (typeof options.onDebugEvent === 'function') {
        options.onDebugEvent('fetch_response_headers_received', { status: 502, ok: false })
      }
      const error = new Error('invalid_deck_brief_slide')
      error.kind = 'http_error'
      error.status = 502
      error.data = {
        detail: {
          code: 'invalid_deck_brief_slide',
          page_no: Number(payload.target && payload.target.index),
          reason: 'missing_required_brief_content',
          repaired: false,
          retried: false,
        },
      }
      return Promise.reject(error)
    },
  })
  let state = applyPptSpecResponse(createPptPlanningState(), {
    outline: [
      { id: 'p1', page_no: 1, theme: '开场', purpose: '建立问题' },
      { id: 'p2', page_no: 2, theme: '证据', purpose: '说明判断' },
    ],
  })
  state = applyNarrativePlanResponse(state, {
    storyline: '从问题到证据',
    slide_roles: [
      { page_no: 1, role: '开题', job: '建立问题' },
      { page_no: 2, role: '证据页', job: '说明判断' },
    ],
  })
  ctx.agentTabs.pptPlanningTabs[0].pptPlanningState = state

  await ctx.generateAgentPptPlanningSlides()

  const finalState = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)
  assert.equal(finalState.deckBrief.slides.length, 0)
  assert.equal(finalState.slideGenerationJob.active, false)
  assert.equal(finalState.slideGenerationJob.failedPageNo, 1)
  assert.equal(finalState.slideGenerationQueue[0].status, 'failed')
  assert.match(finalState.generationError, /第 1 页 brief 校验失败/)
  assert.match(finalState.generationError, /AI 返回内容不完整/)
  assert.notEqual(finalState.generationError, '[object Object]')
  assert.equal(finalState.generationJob.phase, 'failed')
  assert.ok(finalState.generationJob.events.find((event) => event.name === 'slide_page_request_started' && event.details.pageNo === 1))
  assert.ok(finalState.generationJob.events.find((event) => event.name === 'slide_page_request_failed' && event.details.detailCode === 'invalid_deck_brief_slide'))
  assert.ok(finalState.generationJob.events.find((event) => event.name === 'slide_fetch_response_headers_received' && event.details.status === 502))
})

test('ppt planning api keeps object error detail structured', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => ({
    ok: false,
    status: 502,
    text: async () => JSON.stringify({
      detail: {
        code: 'invalid_deck_brief_slide',
        page_no: 2,
        reason: 'missing_required_brief_content',
      },
    }),
  })
  try {
    await assert.rejects(
      () => regenerateDeckBriefSlide({ target: { index: 2 } }),
      (error) => {
        assert.equal(error.message, 'invalid_deck_brief_slide')
        assert.equal(error.status, 502)
        assert.equal(error.data.detail.page_no, 2)
        assert.equal(error.data.detail.reason, 'missing_required_brief_content')
        return true
      },
    )
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('agent ppt outline timeout restores materials state with readable error', async () => {
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
    requestAgentPptPlanningOutlineWithDebug() {
      return Promise.reject(new Error('ppt_planning_network_error'))
    },
    syncCurrentAgentSession() {},
  }

  await ctx.generateAgentPptPlanningOutline()

  const state = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)
  assert.equal(state.currentStep, 'materials')
  assert.equal(state.generationErrorSource, 'outline')
  assert.equal(state.generationError, 'ppt_planning_network_error')
})

test('agent ppt planning api context includes standardized analysis metrics', () => {
  const ctx = createPptPlanningTestContext({
    allPoisDetails: [{ id: 'poi-1' }, { id: 'poi-2' }],
    h3AnalysisSummary: {
      grid_count: 4,
      poi_count: 2,
      avg_density_poi_per_km2: 18.2,
      avg_local_entropy: 0.62,
    },
    populationOverview: {
      summary: {
        total_population: 12000,
      },
      age_distribution: [
        { age_band: '20', age_band_label: '20-24岁', total: 3000, male: 1500, female: 1500 },
        { age_band: '30', age_band_label: '30-34岁', total: 4200, male: 2100, female: 2100 },
      ],
    },
    populationLayer: {
      summary: {
        average_density_per_km2: 8000,
      },
    },
    nightlightOverview: {
      summary: {
        max_radiance: 9.8,
      },
    },
    roadSyntaxSummary: {
      node_count: 80,
      avg_integration: 1.4,
    },
  })

  const context = ctx.buildAgentPptPlanningApiContext()
  const metrics = context.current.metrics.metrics

  assert.equal(context.current.metrics.version, 'current_metrics_v1')
  assert.ok(metrics.find((item) => item.metric_id === 'analysis:poi:poi_count' && item.status === 'ready' && item.value === 2))
  assert.ok(metrics.find((item) => item.metric_id === 'analysis:h3:avg_density_poi_per_km2' && item.status === 'ready'))
  assert.ok(metrics.find((item) => item.metric_id === 'analysis:population:total_population' && item.status === 'ready'))
  assert.ok(metrics.find((item) => item.metric_id === 'analysis:population:population_density' && item.status === 'ready' && item.value === 8000))
  assert.ok(metrics.find((item) => item.metric_id === 'analysis:population:age_structure' && item.status === 'ready' && item.value === 35))
  assert.ok(metrics.find((item) => item.metric_id === 'analysis:nightlight:max_radiance' && item.status === 'ready'))
  assert.ok(metrics.find((item) => item.metric_id === 'analysis:road:avg_integration' && item.status === 'ready'))
  assert.ok(metrics.find((item) => item.metric_id === 'analysis:h3:lq' && item.status === 'missing'))
})

test('agent ppt population age structure reads overview age distribution without layer', () => {
  const ctx = createPptPlanningTestContext({
    populationOverview: {
      summary: {
        total_population: 1000,
      },
      age_distribution: [
        { age_band: '10', age_band_label: '10-14岁', total: 250 },
        { age_band: '25', age_band_label: '25-29岁', total: 400 },
      ],
    },
    populationLayer: null,
  })

  const metrics = ctx.buildAgentPptPlanningCurrent().metrics.metrics
  const age = metrics.find((item) => item.metric_id === 'analysis:population:age_structure')
  const density = metrics.find((item) => item.metric_id === 'analysis:population:population_density')

  assert.equal(age.status, 'ready')
  assert.equal(age.value, 40)
  assert.equal(age.unit, '%')
  assert.match(age.description, /25-29岁/)
  assert.equal(density.status, 'missing')
})

test('agent ppt population age structure remains missing when age distribution is empty', () => {
  const ctx = createPptPlanningTestContext({
    populationOverview: {
      summary: {
        total_population: 1000,
      },
      age_distribution: [],
    },
  })

  const metrics = ctx.buildAgentPptPlanningCurrent().metrics.metrics
  const age = metrics.find((item) => item.metric_id === 'analysis:population:age_structure')

  assert.equal(age.status, 'missing')
  assert.equal(age.source_path, 'populationOverview.age_distribution')
})

test('agent ppt h3 metrics use derived typing lq and neighbor results', () => {
  const ctx = createPptPlanningTestContext({
    allPoisDetails: [{ id: 'poi-1' }, { id: 'poi-2' }],
    h3AnalysisSummary: {
      grid_count: 2,
      poi_count: 2,
      avg_density_poi_per_km2: 18.2,
      avg_local_entropy: 0.62,
    },
    h3AnalysisGridFeatures: [
      { properties: { h3_id: 'h3-1', neighbor_mean_density: 10, neighbor_mean_entropy: 0.4 } },
      { properties: { h3_id: 'h3-2', neighbor_mean_density: 14, neighbor_mean_entropy: 0.6 } },
    ],
    h3DerivedStats: {
      typingSummary: {
        counts: { high_density_high_mix: 1, low_density_high_mix: 1 },
        rows: [{ h3_id: 'h3-1' }, { h3_id: 'h3-2' }],
        opportunityCount: 1,
      },
      lqSummary: {
        maxLq: 1.8,
        opportunityCount: 1,
      },
    },
  })

  const metrics = ctx.buildAgentPptPlanningApiContext().current.metrics.metrics
  assert.ok(metrics.find((item) => item.metric_id === 'analysis:h3:functional_mix_score' && item.status === 'ready'))
  assert.ok(metrics.find((item) => item.metric_id === 'analysis:h3:neighbor_interpolation' && item.status === 'ready' && item.value === 12))
  assert.ok(metrics.find((item) => item.metric_id === 'analysis:h3:lq' && item.status === 'ready' && item.value === 1.8))
  assert.ok(metrics.find((item) => item.metric_id === 'analysis:h3:lq_opportunity_count' && item.status === 'ready' && item.value === 1))
})

test('agent ppt road metrics use local and global syntax summary fields', () => {
  const ctx = createPptPlanningTestContext({
    roadSyntaxSummary: {
      node_count: 80,
      edge_count: 120,
      avg_choice_global: 0.41,
      avg_choice_local: 0.56,
      avg_integration_global: 0.72,
      avg_integration_local: 0.88,
      avg_intelligibility: 0.64,
    },
  })

  const metrics = ctx.buildAgentPptPlanningApiContext().current.metrics.metrics
  assert.ok(metrics.find((item) => item.metric_id === 'analysis:road:avg_choice' && item.status === 'ready' && item.value === 0.56))
  assert.ok(metrics.find((item) => item.metric_id === 'analysis:road:avg_integration' && item.status === 'ready' && item.value === 0.88))
  assert.ok(metrics.find((item) => item.metric_id === 'analysis:road:avg_intelligibility' && item.status === 'ready' && item.value === 0.64))
})

test('agent ppt directive regeneration cleans previous deck visual artifacts', async () => {
  const cleaned = []
  let initialState = applyDeckBriefResponse(applyPptSpecResponse(createPptPlanningState(), {
    title: '目录',
    page_count: 1,
    outline: [
      { id: 'page-1', page_no: 1, theme: '项目命题', purpose: '建立汇报主线' },
    ],
  }), {
    slides: [
      {
        index: 1,
        title: '旧指令',
        visual_artifacts: [{ filename: 'old-deck.svg' }],
      },
    ],
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
        pptPlanningState: initialState,
      }],
      deepAnalysisTabs: [],
      followupTabs: [],
    },
    requestAgentPptPlanningDeckBriefJob() {
      return Promise.resolve({ job_id: 'brief-job-cleanup', status: 'queued' })
    },
    requestAgentPptPlanningDeckBriefJobStatus() {
      return Promise.resolve({
        job_id: 'brief-job-cleanup',
        status: 'completed',
        result: {
          status: 'draft',
          slides: [
            {
              index: 1,
              title: '新指令',
              visual_artifacts: [{ filename: 'new-deck.svg' }],
            },
          ],
        },
      })
    },
    requestAgentPptPlanningVisualArtifactCleanup(filenames) {
      cleaned.push(...filenames)
      return Promise.resolve({ deleted: filenames, missing: [], skipped: [] })
    },
  })

  await ctx.generateAgentPptPlanningDirective()
  const state = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)

  assert.deepEqual(cleaned, ['old-deck.svg'])
  assert.equal(state.deckBrief.slides[0].visualArtifacts[0].filename, 'new-deck.svg')
})

test('agent ppt regenerate outline confirms and clears downstream output', async () => {
  const methods = createAgentPptPlanningTabMethods()
  let outlineCalls = 0
  let directiveCalls = 0
  let initialState = applyDeckBriefResponse(applyPptSpecResponse(createPptPlanningState(), {
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
  initialState = startSlideGenerationQueue(initialState)
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
    requestAgentPptPlanningOutlineWithDebug(payload, options = {}) {
      return this.requestAgentPptPlanningOutline(payload, options)
    },
    requestAgentPptPlanningDirective() {
      directiveCalls += 1
      return Promise.resolve({ slides: [{ index: 1, title: '不应调用' }] })
    },
    requestAgentPptPlanningDirectiveWithDebug(payload, options = {}) {
      return this.requestAgentPptPlanningDirective(payload, options)
    },
    syncCurrentAgentSession() {},
  }

  await ctx.regenerateAgentPptPlanningOutlineWithConfirm()
  const state = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)

  assert.equal(outlineCalls, 1)
  assert.equal(directiveCalls, 0)
  assert.equal(state.currentStep, 'outline_ready')
  assert.equal(state.outline[0].theme, '新目录页')
  assert.deepEqual(state.deckBrief.slides, [])
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
    requestAgentPptPlanningDeckBriefJob() {
      directiveCalls += 1
      return Promise.resolve({ job_id: 'brief-job-regenerate', status: 'queued' })
    },
    requestAgentPptPlanningDeckBriefJobStatus() {
      return Promise.resolve({
        job_id: 'brief-job-regenerate',
        status: 'completed',
        result: {
          status: 'draft',
          slides: [
            { index: 1, title: '新指令', purpose: '新指令目的' },
          ],
        },
      })
    },
    ensureAgentVisualSnapshotCache() {
      return Promise.resolve([])
    },
    syncCurrentAgentSession() {},
  }

  await ctx.regenerateAgentPptPlanningDirectiveWithConfirm()
  const state = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)

  assert.equal(directiveCalls, 1)
  assert.equal(state.currentStep, 'directive_draft')
  assert.equal(state.outline[0].theme, '保留目录页')
  assert.equal(state.deckBrief.slides[0].title, '新指令')
  assert.deepEqual(state.slideGenerationQueue, [])
  assert.equal(state.slideGenerationJob.active, false)
})

test('agent ppt regenerate narrative clears downstream and uses narrative endpoint', async () => {
  const methods = createAgentPptPlanningTabMethods()
  let narrativeCalls = 0
  let slideCalls = 0
  const initialState = createPptStateWithOutlineNarrativeAndSlides()
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
    confirmPptPlanningStepReset() {
      return true
    },
    requestAgentPptPlanningNarrativePlanWithDebug() {
      narrativeCalls += 1
      return Promise.resolve({
        storyline: '新叙事',
        slide_roles: [{ page_no: 1, role: '新开题', job: '新目标' }],
      })
    },
    requestAgentPptPlanningDirectiveSlide() {
      slideCalls += 1
      return Promise.resolve({ index: 1, title: '不应调用' })
    },
    syncCurrentAgentSession() {},
  }

  await ctx.regenerateAgentPptPlanningNarrativePlanWithConfirm()
  const state = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)

  assert.equal(narrativeCalls, 1)
  assert.equal(slideCalls, 0)
  assert.equal(state.currentStep, 'narrative_ready')
  assert.equal(state.narrativePlan.storyline, '新叙事')
  assert.deepEqual(state.deckBrief.slides, [])
})

test('agent ppt regenerate slides keeps outline and narrative while clearing old briefs', async () => {
  const methods = createAgentPptPlanningTabMethods()
  let slideCalls = 0
  const cleaned = []
  const initialState = applyDeckBriefResponse(createPptStateWithOutlineNarrativeAndSlides(), {
    slides: [
      { index: 1, title: '旧 brief', purpose: '旧目的', visual_artifacts: [{ filename: 'old-brief.svg' }] },
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
    confirmPptPlanningStepReset() {
      return true
    },
    requestAgentPptPlanningDirectiveSlide(payload) {
      slideCalls += 1
      return Promise.resolve({
        index: payload.target.index,
        title: `新 brief ${payload.target.index}`,
        purpose: payload.target.purpose,
      })
    },
    requestAgentPptPlanningVisualArtifactCleanup(filenames) {
      cleaned.push(...filenames)
      return Promise.resolve({ deleted: filenames, missing: [], skipped: [] })
    },
    syncCurrentAgentSession() {},
  }

  await ctx.regenerateAgentPptPlanningSlidesWithConfirm()
  const state = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)

  assert.equal(slideCalls, 2)
  assert.deepEqual(cleaned, ['old-brief.svg'])
  assert.equal(state.currentStep, 'directive_draft')
  assert.equal(state.narrativePlan.slideRoles.length, 2)
  assert.deepEqual(state.deckBrief.slides.map((slide) => slide.title), ['新 brief 1', '新 brief 2'])
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
  const cleaned = []
  const initialState = applyDeckBriefResponse(applyPptSpecResponse(createPptPlanningState(), {
    title: 'AI 生成目录',
    page_count: 2,
    outline: [
      { id: 'page-1', page_no: 1, theme: '项目命题', purpose: '建立汇报主线' },
      { id: 'page-2', page_no: 2, theme: '空间证据', purpose: '说明现状' },
    ],
  }), {
    slides: [
      { index: 1, title: '项目命题', purpose: '建立汇报主线', visual_artifacts: [{ filename: 'keep.svg' }] },
      { index: 2, title: '空间证据', purpose: '说明现状', visual_artifacts: [{ filename: 'old-slide-2.svg' }] },
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
        required_sources: ['current:scope'],
        visual_artifacts: [{ filename: 'new-slide-2.svg' }],
      })
    },
    requestAgentPptPlanningVisualArtifactCleanup(filenames) {
      cleaned.push(...filenames)
      return Promise.resolve({ deleted: filenames, missing: [], skipped: [] })
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
  assert.equal(state.deckBrief.slides[0].visualArtifacts[0].filename, 'keep.svg')
  assert.equal(state.deckBrief.slides[1].visualArtifacts[0].filename, 'new-slide-2.svg')
  assert.deepEqual(cleaned, ['old-slide-2.svg'])
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
  assert.ok(seenPayload.source_ids.includes('current:scope'))
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
          id: 'current:scope',
          type: 'data',
          title: '当前等时圈范围',
          status: 'ready',
          summary: '已生成',
          count: 1,
          meta: { label: '已生成', sourceKind: 'system', areaId },
        },
        {
          id: 'current:dataset:poi',
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
              source_ids: ['current:dataset:poi'],
              items: [],
            },
          },
        },
      })
    },
  })

  await ctx.refreshAgentActivePptPlanningDataSources()
  const state = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)
  const poiSource = state.sources.find((item) => item.id === 'current:dataset:poi')
  const packageSource = state.sources.find((item) => item.id === 'package:poi:auto')

  assert.equal(poiSource.status, 'ready')
  assert.equal(poiSource.meta.label, 'POI 3996 条')
  assert.equal(seenPackagePayload.area_id, 'history-1')
  assert.deepEqual(seenPackagePayload.source_ids, ['current:dataset:poi'])
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
          id: 'current:dataset:poi',
          type: 'data',
          title: 'POI 基础数据',
          status: 'ready',
          summary: 'POI 3996 条',
          count: 3996,
          meta: { label: 'POI 3996 条', sourceKind: 'system', areaId },
        },
        {
          id: 'current:analysis:nightlight',
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
  assert.deepEqual(nightlifePayload.source_ids, ['current:dataset:poi', 'current:analysis:nightlight'])
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
          id: 'current:dataset:poi',
          type: 'data',
          title: 'POI 基础数据',
          status: 'ready',
          summary: 'POI 3996 条',
          count: 3996,
          meta: { label: 'POI 3996 条', sourceKind: 'system', areaId },
        },
        {
          id: 'current:analysis:road',
          type: 'data',
          title: '路网与可达性分析',
          status: 'ready',
          summary: '已生成',
          count: 1,
          meta: { label: '已生成', sourceKind: 'system', areaId },
        },
        {
          id: 'current:analysis:population',
          type: 'data',
          title: '人口结构分析',
          status: 'ready',
          summary: '已生成',
          count: 1,
          meta: { label: '已生成', sourceKind: 'system', areaId },
        },
        {
          id: 'current:analysis:nightlight',
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
  assert.deepEqual(carrierPayload.source_ids, ['current:dataset:poi', 'current:analysis:road', 'current:analysis:population', 'current:analysis:nightlight'])
  assert.equal(carrierPayload.package_mode, 'evidence')
  assert.equal(carrierPayload.limit, 50)
  assert.equal(carrierPackage.selected, true)
  assert.equal(carrierPackage.meta.areaId, 'history-1')
  assert.equal(carrierPackage.meta.autoGenerated, true)
})

test('agent ppt refresh starts eligible auto packages in parallel', async () => {
  const packagePayloads = []
  const pendingPackages = []
  const ctx = createPptPlanningTestContext({
    requestAgentPptPlanningDataSources(areaId) {
      return Promise.resolve([
        {
          id: 'current:dataset:poi',
          type: 'data',
          title: 'POI 基础数据',
          status: 'ready',
          summary: 'POI 3996 条',
          count: 3996,
          meta: { label: 'POI 3996 条', sourceKind: 'system', areaId },
        },
        {
          id: 'current:analysis:road',
          type: 'data',
          title: '路网与可达性分析',
          status: 'ready',
          summary: '已生成',
          count: 1,
          meta: { label: '已生成', sourceKind: 'system', areaId },
        },
        {
          id: 'current:analysis:population',
          type: 'data',
          title: '人口结构分析',
          status: 'ready',
          summary: '已生成',
          count: 1,
          meta: { label: '已生成', sourceKind: 'system', areaId },
        },
        {
          id: 'current:analysis:nightlight',
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
      return new Promise((resolve) => {
        pendingPackages.push({ payload, resolve })
      })
    },
  })

  const refresh = ctx.refreshAgentActivePptPlanningDataSources()
  await Promise.resolve()
  await Promise.resolve()

  assert.equal(packagePayloads.length, 3)
  assert.deepEqual(packagePayloads.map((item) => item.intent).sort(), [
    DEFAULT_PPT_CARRIER_EVIDENCE_INTENT,
    DEFAULT_PPT_NIGHTLIFE_POI_INTENT,
    DEFAULT_PPT_POI_EVIDENCE_INTENT,
  ].sort())

  for (const pending of pendingPackages) {
    pending.resolve({
      source: {
        id: `package:${pending.payload.intent}:auto`,
        type: 'package',
        title: '自动资料包',
        status: 'ready',
        selected: true,
        meta: {
          label: '自动资料包',
          sourceKind: 'package',
          package: {
            package_mode: 'evidence',
            intent: pending.payload.intent,
            source_ids: pending.payload.source_ids,
            items: [],
          },
        },
      },
    })
  }
  await refresh
})

test('agent ppt auto package failure is isolated to its placeholder', async () => {
  const ctx = createPptPlanningTestContext({
    requestAgentPptPlanningDataSources(areaId) {
      return Promise.resolve([
        {
          id: 'current:dataset:poi',
          type: 'data',
          title: 'POI 基础数据',
          status: 'ready',
          summary: 'POI 3996 条',
          count: 3996,
          meta: { label: 'POI 3996 条', sourceKind: 'system', areaId },
        },
        {
          id: 'current:analysis:road',
          type: 'data',
          title: '路网与可达性分析',
          status: 'ready',
          summary: '已生成',
          count: 1,
          meta: { label: '已生成', sourceKind: 'system', areaId },
        },
        {
          id: 'current:analysis:population',
          type: 'data',
          title: '人口结构分析',
          status: 'ready',
          summary: '已生成',
          count: 1,
          meta: { label: '已生成', sourceKind: 'system', areaId },
        },
        {
          id: 'current:analysis:nightlight',
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
      if (payload.intent === DEFAULT_PPT_CARRIER_EVIDENCE_INTENT) {
        return Promise.reject(new Error('road_carrier_failed'))
      }
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
  const poiPackage = state.sources.find((item) => item.id === 'package:poi:auto')
  const nightlifePackage = state.sources.find((item) => item.id === 'package:poi-nightlife:auto')
  const carrierPlaceholder = state.sources.find((item) => item.id === 'package-placeholder:road-carrier')

  assert.equal(poiPackage.status, 'ready')
  assert.equal(nightlifePackage.status, 'ready')
  assert.equal(carrierPlaceholder.status, 'failed')
  assert.equal(carrierPlaceholder.meta.label, '生成失败')
  assert.equal(carrierPlaceholder.meta.error, 'road_carrier_failed')
  assert.equal(state.generationError, '')
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

test('ppt source refresh immediately marks planning state as blocked', async () => {
  let resolveSources
  const sourcePromise = new Promise((resolve) => {
    resolveSources = resolve
  })
  const ctx = createPptPlanningTestContext({
    requestAgentPptPlanningDataSources(areaId) {
      assert.equal(areaId, 'history-1')
      return sourcePromise
    },
  })

  const refreshPromise = ctx.refreshAgentActivePptPlanningDataSources({ autoPackage: false })
  const refreshingState = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)

  assert.equal(refreshingState.sourceRefreshing, true)
  assert.equal(hasPptBlockingInputs(refreshingState), true)

  resolveSources([])
  await refreshPromise

  const settledState = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)
  assert.equal(settledState.sourceRefreshing, false)
})

test('ppt outline generation does not call api while sources are refreshing', async () => {
  let outlineCalls = 0
  const ctx = createPptPlanningTestContext({
    requestAgentPptPlanningOutlineWithDebug() {
      outlineCalls += 1
      return Promise.resolve({ outline: [] })
    },
  })
  const systemState = mergePptPlanningSources(createPptPlanningState(), createPptSystemSources({
    scope: { polygon: [[0, 0], [1, 0], [1, 1]] },
    taskResults: { poi_fetch: true },
  }))
  ctx.updateAgentActivePptPlanningState(setPptSourceRefreshing(systemState, true))

  await ctx.generateAgentPptPlanningOutline()

  assert.equal(outlineCalls, 0)
})

test('ppt outline generation does not call api without deliverable selected sources', async () => {
  let outlineCalls = 0
  const staleState = createPptPlanningState({
    sources: [{
      id: 'summary',
      type: 'data',
      title: 'summary',
      status: 'ready',
      selected: true,
      meta: {
        sourceKind: 'system',
        transport: {
          source_id: 'summary',
          transport_status: 'selected_no_payload',
          included: [],
        },
      },
    }],
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
        pptPlanningState: staleState,
      }],
      deepAnalysisTabs: [],
      followupTabs: [],
    },
    getAgentPptPlanningStateWithSystemSources() {
      return createPptPlanningState(this.agentTabs.pptPlanningTabs[0].pptPlanningState)
    },
    requestAgentPptPlanningOutlineWithDebug() {
      outlineCalls += 1
      return Promise.resolve({})
    },
  })

  await ctx.generateAgentPptPlanningOutline()

  const finalState = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)
  assert.equal(outlineCalls, 0)
  assert.equal(finalState.generationJob.phase, 'failed')
  assert.match(finalState.generationError, /没有可发送给 AI/)
  assert.equal(finalState.generationJob.events.some((event) => event.name === 'source_payload_preflight_failed'), true)
})

test('agent ppt auto poi evidence package is not created twice for same area', async () => {
  let packageCalls = 0
  const stateWithPackage = addPptDataPackageSource(createPptPlanningState({
    sources: [{
      id: 'current:dataset:poi',
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
          source_ids: ['current:dataset:poi'],
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

test('agent ppt auto poi evidence package is not created twice while in flight', async () => {
  let packageCalls = 0
  let resolvePackage = null
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
            id: 'current:dataset:poi',
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
    requestAgentPptPlanningDataPackage() {
      packageCalls += 1
      return new Promise((resolve) => {
        resolvePackage = resolve
      })
    },
  })

  const first = ctx.autoCreateAgentPptPlanningPoiEvidencePackage({ areaId: 'history-1' })
  await Promise.resolve()
  await ctx.autoCreateAgentPptPlanningPoiEvidencePackage({ areaId: 'history-1' })

  assert.equal(packageCalls, 1)

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
          source_ids: ['current:dataset:poi'],
          items: [],
        },
      },
    },
  })
  await first
})

test('agent ppt auto package failure keeps ready sources and visible error', async () => {
  const ctx = createPptPlanningTestContext({
    requestAgentPptPlanningDataSources(areaId) {
      return Promise.resolve([
        {
          id: 'current:dataset:poi',
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
  const poiSource = state.sources.find((item) => item.id === 'current:dataset:poi')

  assert.equal(poiSource.status, 'ready')
  assert.equal(poiSource.meta.label, 'POI 3996 条')
  assert.equal(state.sources.some((item) => String(item.id).startsWith('package:poi')), false)
  const placeholder = state.sources.find((item) => item.id === 'package-placeholder:poi-evidence')
  assert.equal(placeholder.status, 'failed')
  assert.equal(placeholder.meta.label, '生成失败')
  assert.equal(placeholder.meta.error, 'ppt_data_intent_llm_unavailable')
  assert.equal(state.generationError, '')
  assert.equal(state.dataPackageGenerating, false)
})

test('agent ppt auto carrier package sends package version', async () => {
  let payload = null
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
          sources: [
            { id: 'current:dataset:poi', type: 'data', title: 'POI', status: 'ready', selected: true, meta: { sourceKind: 'system', areaId: 'history-1' } },
            { id: 'current:analysis:road', type: 'data', title: '路网', status: 'ready', selected: true, meta: { sourceKind: 'system', areaId: 'history-1' } },
            { id: 'current:analysis:population', type: 'data', title: '人口', status: 'ready', selected: true, meta: { sourceKind: 'system', areaId: 'history-1' } },
            { id: 'current:analysis:nightlight', type: 'data', title: '夜光', status: 'ready', selected: true, meta: { sourceKind: 'system', areaId: 'history-1' } },
          ],
        }),
      }],
      deepAnalysisTabs: [],
      followupTabs: [],
    },
    requestAgentPptPlanningDataPackage(nextPayload) {
      payload = nextPayload
      return Promise.resolve({
        source: {
          id: 'package:poi-road-carriers:auto',
          type: 'package',
          title: 'POI × 路网空间载体资料包',
          status: 'ready',
          selected: true,
          meta: {
            label: '空间载体 1 个',
            sourceKind: 'package',
            package: {
              package_mode: 'evidence',
              intent: DEFAULT_PPT_CARRIER_EVIDENCE_INTENT,
              source_ids: ['current:dataset:poi', 'current:analysis:road', 'current:analysis:population', 'current:analysis:nightlight'],
              carriers: [],
            },
          },
        },
      })
    },
  })

  await ctx.autoCreateAgentPptPlanningRoadCarrierPackage({ areaId: 'history-1' })

  assert.equal(payload.package_version, 'road-carrier-evidence-v2')
})

test('agent ppt restored package source satisfies auto package placeholder', async () => {
  const restoredPackage = {
    id: 'package:poi-road-carriers:restored',
    type: 'package',
    title: 'POI × 路网空间载体资料包',
    status: 'ready',
    summary: '空间载体 1 个',
    meta: {
      label: '空间载体 1 个',
      sourceKind: 'package',
      area_id: 'history-1',
      package: {
        package_mode: 'evidence',
        intent: DEFAULT_PPT_CARRIER_EVIDENCE_INTENT,
        package_version: 'road-carrier-evidence-v2',
        source_ids: ['current:dataset:poi', 'current:analysis:road', 'current:analysis:population', 'current:analysis:nightlight'],
        carriers: [],
      },
    },
  }
  const ctx = createPptPlanningTestContext({
    requestAgentPptPlanningDataSources() {
      return Promise.resolve([
        { id: 'current:dataset:poi', type: 'data', title: 'POI', status: 'ready', meta: { sourceKind: 'system', areaId: 'history-1' } },
        { id: 'current:analysis:road', type: 'data', title: '路网', status: 'ready', meta: { sourceKind: 'system', areaId: 'history-1' } },
        { id: 'current:analysis:population', type: 'data', title: '人口', status: 'ready', meta: { sourceKind: 'system', areaId: 'history-1' } },
        { id: 'current:analysis:nightlight', type: 'data', title: '夜光', status: 'ready', meta: { sourceKind: 'system', areaId: 'history-1' } },
        restoredPackage,
      ])
    },
  })

  await ctx.refreshAgentActivePptPlanningDataSources({ autoPackage: false })

  const state = createPptPlanningState(ctx.agentTabs.pptPlanningTabs[0].pptPlanningState)
  assert.ok(state.sources.some((item) => item.id === 'package:poi-road-carriers:restored'))
  assert.equal(state.sources.some((item) => item.id === 'package-placeholder:road-carrier'), false)
})

