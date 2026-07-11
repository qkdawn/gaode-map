import { asText, cloneArray, cloneObject } from './normalizers.js'
import { getAnalysisTaskDefinition } from './analysis-task-registry.js'
import { createAgentAnalysisAskMethods } from './analysis-ask.js'
import { createAgentPptApiAdapterMethods } from './ppt-api-adapters.js'
import { createAgentPptGenerationFlowMethods } from './ppt-generation-flow.js'
import { normalizePptGenerationErrorMessage } from './ppt-generation-errors.js'
import { createAgentPptRevisionActionMethods } from './ppt-revision-actions.js'
import { createAgentPptSlideGenerationMethods } from './ppt-slide-generation.js'
import { createAgentPptSourceActionMethods } from './ppt-source-actions.js'
import { createAgentPptVisualGenerationMethods } from './ppt-visual-generation.js'
import { createAgentPptVisualSnapshotMethods } from './ppt-visual-snapshots.js'
import { ANALYSIS_WORKSPACE_TAB_KIND } from './workspace-kinds.js'
import {
  cloneAgentTabsState,
  getAnalysisWorkspaceTabsFromState,
  withAnalysisWorkspaceTabs,
} from './analysis-workspace-tabs.js'
import { createPptSystemSources, createPptTransportFromAiPayload } from '../ppt-planning/model.js'
import {
  applyCapabilitySourceSelectionPolicy,
  capabilityInputSelectionFingerprint,
  capabilityRunSourceId,
  capabilitySourceRunId,
  createStage1CapabilityFailedSource,
  createStage1CapabilityPlaceholderSource,
  createStage1CapabilityPptSource,
  normalizeCapabilityInputSelections,
} from '../ppt-planning/capability-source.js'
import {
  cleanupPptVisualArtifacts,
  getJobStatus,
  uploadDocumentSource,
  uploadImageSource,
} from '../ppt-planning/api.js'
import {
  addPptDataPackageSource,
  appendPptGenerationDebugEvent,
  applyDirectiveResponseAndMarkReady,
  applyPptSourceGroupsResponse,
  createPptPlanningState,
  getActiveDeckSlideBrief,
  getPptSourceSummary,
  failPptGenerationJob,
  mergePptPlanningSources,
  selectDeckSlideBrief,
  clearPptSourceRefreshPlaceholderSources,
  setPptDataPackageGenerating,
  setPptGenerationError,
  setPptSourceRefreshing,
  setPptSourceGrouping,
  syncPptSourceRefreshPlaceholderSources,
  syncPptPackagePlaceholderSources,
  upsertPptDocumentSource,
  upsertPptImageSource,
} from '../ppt-planning/ui-state.js'
import {
  buildPptAnalysisMetrics,
  buildPptDataPackageSpatialPayload,
  buildCurrentNightlightAnalysis,
  createPackageAiPayload,
  documentIdFromPptSource,
  getPptEvidencePackageKey,
  hasRing,
  hasPptEvidencePackage,
  imageAttachmentIdFromPptSource,
  imageConversationIdFromPptSource,
  isPptDocumentSource,
  isPptImageSource,
  isPptPersistedArtifactSource,
  isReadySource,
  normalizePptLngLat,
  normalizeBackendPptDataSource,
  resolvePptPlanningRadiusMeters,
  webSourceRetryPayloadFromPptSource,
} from '../ppt-planning/source-payloads.js'

const CAPABILITY_RUNS_URL = '/api/v1/analysis/agent/analysis-capability-runs'
const DEFAULT_PPT_POI_EVIDENCE_INTENT = '为 PPT 指令生成整理当前区域代表性 POI 资料'
const DEFAULT_PPT_NIGHTLIFE_POI_INTENT = '整理夜生活与夜间消费相关 POI，并与夜光格子对应'
const DEFAULT_PPT_CARRIER_EVIDENCE_INTENT = '识别当前区域 POI、路网、人口、夜光共同支撑的空间载体'
const PPT_NIGHTLIFE_PACKAGE_VERSION = 'nightlife-evidence-v2'
const PPT_CARRIER_PACKAGE_VERSION = 'road-carrier-evidence-v2'
let pptUploadSequence = 0

function createPptUploadSourceId(sourceKind = 'source') {
  pptUploadSequence += 1
  return `${asText(sourceKind) || 'source'}-upload:${Date.now()}:${pptUploadSequence}`
}
const PPT_AUTO_PACKAGE_DEFINITIONS = Object.freeze([
  {
    key: 'poi-evidence',
    title: 'POI 资料包',
    sourceIds: ['current:dataset:poi'],
    packageMode: 'evidence',
    intent: DEFAULT_PPT_POI_EVIDENCE_INTENT,
    limit: 50,
  },
  {
    key: 'nightlife-poi',
    title: '夜生活 POI × 夜光格子资料包',
    sourceIds: ['current:dataset:poi', 'current:analysis:nightlight'],
    packageMode: 'evidence',
    intent: DEFAULT_PPT_NIGHTLIFE_POI_INTENT,
    packageVersion: PPT_NIGHTLIFE_PACKAGE_VERSION,
    limit: 50,
  },
  {
    key: 'road-carrier',
    title: 'POI × 路网空间载体资料包',
    sourceIds: ['current:dataset:poi', 'current:analysis:road', 'current:analysis:population', 'current:analysis:nightlight'],
    packageMode: 'evidence',
    intent: DEFAULT_PPT_CARRIER_EVIDENCE_INTENT,
    packageVersion: PPT_CARRIER_PACKAGE_VERSION,
    limit: 50,
  },
])

function getPptAutoPackageDefinition(key = '') {
  return PPT_AUTO_PACKAGE_DEFINITIONS.find((item) => item.key === asText(key)) || null
}

function delay(ms = 0) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

async function waitForPptPlanningJob(jobId = '', { attempts = 20, intervalMs = 1500 } = {}) {
  const normalizedJobId = asText(jobId)
  if (!normalizedJobId) return null
  for (let index = 0; index < attempts; index += 1) {
    const job = await getJobStatus(normalizedJobId)
    const status = asText(job && job.status)
    if (status === 'succeeded') return job
    if (status === 'failed') throw new Error(asText(job && job.error) || 'document_job_failed')
    await delay(intervalMs)
  }
  return null
}

function attachPptDataPackageRuntimeMeta(response = {}, areaId = '', options = {}) {
  const source = cloneObject(response.source || response)
  if (!source.id) return response
  const meta = cloneObject(source.meta)
  const pack = cloneObject(meta.package)
  const title = asText(source.title)
  const persistedAiPayload = cloneObject(meta.aiPayload || meta.ai_payload)
  const aiPayload = persistedAiPayload.version === 'ppt_ai_input_block_v1'
    ? persistedAiPayload
    : createPackageAiPayload(asText(source.id), title, pack)
  return {
    ...response,
    source: {
      ...source,
      meta: {
        ...meta,
        areaId: asText(areaId),
        autoGenerated: !!options.autoGenerated,
        packageVersion: asText(options.packageVersion),
        aiPayload,
        ai_payload: aiPayload,
        transport: createPptTransportFromAiPayload(aiPayload),
      },
    },
  }
}

function uniquePptText(items = []) {
  return [...new Set(cloneArray(items).map((item) => asText(item)).filter(Boolean))]
}

function pptGenerationJobDebug(job = {}) {
  const source = cloneObject(job)
  return {
    id: asText(source.id),
    phase: asText(source.phase),
    type: asText(source.type),
  }
}

function appendPptDebugEventToState(state = {}, eventName = '', details = {}) {
  return appendPptGenerationDebugEvent(createPptPlanningState(state), eventName, details)
}

function isRecoverablePptDeckBriefJobStatus(status = '') {
  return ['queued', 'running', 'validating'].includes(asText(status))
}

export function normalizeAgentPptPlanningTab(item = {}, options = {}) {
  const source = asText(item && item.source) || 'draft'
  let pptPlanningState = createPptPlanningState(item && (item.ppt_planning_state || item.pptPlanningState))
  const generationJob = cloneObject(pptPlanningState.generationJob)
  const hasRecoverableBriefJob = asText(pptPlanningState.briefJobId || pptPlanningState.brief_job_id)
    && isRecoverablePptDeckBriefJobStatus(pptPlanningState.briefJobStatus || pptPlanningState.brief_job_status)
  if (options.restore && ['requesting', 'response_received', 'applying'].includes(asText(generationJob.phase)) && !hasRecoverableBriefJob) {
    pptPlanningState = failPptGenerationJob(
      pptPlanningState,
      generationJob.id,
      '页面已重新加载，请重新发起生成请求。',
      { source: generationJob.type },
    )
    pptPlanningState = appendPptDebugEventToState(
      pptPlanningState,
      'tabs_restored_from_session',
      {
        sessionId: asText(options.sessionId || options.session_id),
        tabId: asText(item && item.id),
        restoredAsFailed: true,
        before: pptGenerationJobDebug(generationJob),
        after: pptGenerationJobDebug(pptPlanningState.generationJob),
      },
    )
  }
  return {
    id: asText(item && item.id),
    kind: ANALYSIS_WORKSPACE_TAB_KIND,
    title: asText(item && item.title) || '分析',
    source,
    sessionId: asText((item && (item.session_id || item.sessionId)) || ''),
    readonly: options.restore ? !!(item && item.readonly && source !== 'history') : !!(item && item.readonly),
    createdAt: asText(item && (item.created_at || item.createdAt)) || new Date().toISOString(),
    panelPayloads: cloneObject(item && (item.panel_payloads || item.panelPayloads)),
    capabilityInputSelections: normalizeCapabilityInputSelections(
      item && (item.capability_input_selections || item.capabilityInputSelections),
    ),
    pptPlanningState,
  }
}

export function serializeAgentPptPlanningTab(item = {}, fallbackPanelPayloads = {}) {
  return {
    id: item.id,
    title: item.title || '分析',
    kind: ANALYSIS_WORKSPACE_TAB_KIND,
    source: item.source || 'draft',
    session_id: item.sessionId || '',
    readonly: !!item.readonly,
    created_at: item.createdAt,
    panel_payloads: cloneObject(item.panelPayloads || fallbackPanelPayloads),
    capability_input_selections: normalizeCapabilityInputSelections(item.capabilityInputSelections),
    ppt_planning_state: createPptPlanningState(item.pptPlanningState),
  }
}

export function createAgentPptPlanningTabMethods() {
  return {
    ...createAgentPptApiAdapterMethods(),
    ...createAgentPptSourceActionMethods(),
    ...createAgentPptRevisionActionMethods(),
    ...createAgentPptGenerationFlowMethods(),
    ...createAgentPptSlideGenerationMethods(),
    ...createAgentPptVisualGenerationMethods(),
    ...createAgentPptVisualSnapshotMethods(),
    appendPptPlanningDebugEvent(state = {}, eventName = '', details = {}) {
      return appendPptDebugEventToState(state, eventName, details)
    },
    createAgentPptPlanningViewId() {
      return `ppt-planning-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
    },
    openAgentPptPlanningFromReport(options = {}) {
      this.agentWorkspaceView = 'report'
      const tabs = this.ensureAgentTabs(true)
      const capabilityInputSelections = normalizeCapabilityInputSelections(options.capabilityInputSelections)
      const selectionFingerprint = capabilityInputSelectionFingerprint(capabilityInputSelections)
      const runId = capabilitySourceRunId(capabilityInputSelections)
      const existing = getAnalysisWorkspaceTabsFromState(tabs).find((item) => {
        if (!['current', 'draft'].includes(asText(item && item.source))) return false
        const itemFingerprint = capabilityInputSelectionFingerprint(item && item.capabilityInputSelections)
        return selectionFingerprint ? itemFingerprint === selectionFingerprint : !itemFingerprint
      })
      if (existing && !options.forceNew) {
        const alreadyActive = asText(tabs.activeTabId) === asText(existing.id)
        const existingState = createPptPlanningState(existing.pptPlanningState)
        const existingSource = existingState.sources.find(item => asText(item?.id) === capabilityRunSourceId(runId))
        const needsHydration = !!runId && asText(existingSource?.status) !== 'ready'
        this.switchAgentTopTab(existing.id)
        if (alreadyActive) {
          this.refreshAgentActivePptPlanningSources()
          this.refreshAgentActivePptPlanningDataSources()
        }
        if (needsHydration) void this.hydrateAgentPptPlanningCapabilitySource(existing.id, runId)
        return existing.id
      }
      const pptPlanningState = runId
        ? mergePptPlanningSources(createPptPlanningState(), [createStage1CapabilityPlaceholderSource(runId)])
        : createPptPlanningState()
      const tabId = this.createAgentPptPlanningTab({
        title: runId ? `分析 · ${runId}` : '分析',
        source: 'current',
        capabilityInputSelections,
        pptPlanningState,
      })
      if (runId) void this.hydrateAgentPptPlanningCapabilitySource(tabId, runId)
      return tabId
    },
    async hydrateAgentPptPlanningCapabilitySource(tabId = '', runId = '') {
      const targetTabId = asText(tabId)
      const targetRunId = asText(runId)
      if (!targetTabId || !targetRunId) return false
      try {
        const response = await fetch(`${CAPABILITY_RUNS_URL}/${encodeURIComponent(targetRunId)}`)
        if (!response.ok) throw new Error(`Capability Run 读取失败(${response.status})`)
        const source = createStage1CapabilityPptSource(await response.json(), targetRunId)
        const currentState = this.getAgentPptPlanningTabState(targetTabId)
        const additionalSelectedSourceIds = currentState.sources
          .filter(item => item?.selected && asText(item?.id) !== capabilityRunSourceId(targetRunId))
          .map(item => asText(item.id))
          .filter(Boolean)
        const nextState = applyCapabilitySourceSelectionPolicy(
          mergePptPlanningSources(currentState, [source]),
          targetRunId,
          { additionalSelectedSourceIds },
        )
        return this.updateAgentPptPlanningTabState(targetTabId, nextState)
      } catch (error) {
        const failedSource = createStage1CapabilityFailedSource(targetRunId, error)
        const nextState = applyCapabilitySourceSelectionPolicy(
          mergePptPlanningSources(this.getAgentPptPlanningTabState(targetTabId), [failedSource]),
          targetRunId,
        )
        this.updateAgentPptPlanningTabState(targetTabId, nextState)
        return false
      }
    },
    isAgentPptPlanningTabActive() {
      return asText(this.getAgentActiveTopTab().kind) === ANALYSIS_WORKSPACE_TAB_KIND
    },
    getAgentActivePptPlanningTab() {
      const tabs = this.ensureAgentTabs(false)
      const activeId = asText(tabs.activeTabId)
      return getAnalysisWorkspaceTabsFromState(tabs).find((item) => asText(item && item.id) === activeId) || null
    },
    getAgentActivePptPlanningState() {
      const tab = this.getAgentActivePptPlanningTab()
      return createPptPlanningState(tab && tab.pptPlanningState)
    },
    getAgentPptPlanningTabState(tabId = '') {
      const targetId = asText(tabId)
      if (!targetId) return createPptPlanningState()
      const tabs = this.ensureAgentTabs(false)
      const tab = getAnalysisWorkspaceTabsFromState(tabs).find((item) => asText(item && item.id) === targetId) || null
      return createPptPlanningState(tab && tab.pptPlanningState)
    },
    buildAgentPptPlanningCurrent({ includeRawData = true } = {}) {
      const siteSelectionScope = typeof this.normalizeAgentSiteSelectionScope === 'function'
        ? this.normalizeAgentSiteSelectionScope()
        : {}
      const panelPayloads = cloneObject(this.agentPanelPayloads)
      const taskKeys = ['poi_fetch', 'poi_h3_grid', 'population', 'nightlight', 'road_syntax']
      const taskResults = {}
      taskKeys.forEach((taskKey) => {
        const def = getAnalysisTaskDefinition(taskKey)
        taskResults[taskKey] = !!(def && typeof def.hasResult === 'function' && def.hasResult(this))
      })
      const summaryReady = typeof this.hasAgentSummaryPack === 'function'
        ? this.hasAgentSummaryPack(panelPayloads.summary_pack || panelPayloads.summaryPack)
        : !!(panelPayloads.summary_pack || panelPayloads.summaryPack)
      const poiTotal = Array.isArray(this.allPoisDetails) ? this.allPoisDetails.length : 0
      const h3Summary = this.h3AnalysisSummary || {}
      const h3Count = Number(h3Summary.grid_count || this.h3GridCount || 0) || 0
      const nightlightAnalysis = buildCurrentNightlightAnalysis(this)
      const featureProps = cloneObject(siteSelectionScope.isochroneFeature && siteSelectionScope.isochroneFeature.properties)
      const selectedCenter = normalizePptLngLat(this.selectedPoint)
      const featureCenter = normalizePptLngLat(featureProps.center || featureProps.center_gcj02 || featureProps.centerGcj02)
      const scopeCenter = selectedCenter.length ? selectedCenter : featureCenter
      const timeMin = Number(this.timeHorizon || featureProps.time_min || featureProps.timeMin || 0) || 0
      const radiusM = resolvePptPlanningRadiusMeters(this, featureProps)
      const scope = {
        polygon: cloneArray(siteSelectionScope.polygon),
        drawn_polygon: cloneArray(siteSelectionScope.drawnPolygon),
        isochrone_feature: siteSelectionScope.isochroneFeature || null,
        center: scopeCenter,
        center_coord_type: scopeCenter.length ? 'gcj02' : '',
        radius_m: radiusM,
        time_min: timeMin,
        mode: asText(this.transportMode),
      }
      const metrics = buildPptAnalysisMetrics(this, scope, taskResults)
      const status = {
        scope: hasRing(scope.polygon) || hasRing(scope.drawn_polygon) || !!scope.isochrone_feature ? 'ready' : 'not_ready',
        poi: taskResults.poi_fetch ? 'ready' : 'not_ready',
        h3: taskResults.poi_h3_grid ? 'ready' : 'not_ready',
        poi_h3: taskResults.poi_h3_grid ? 'ready' : 'not_ready',
        population: taskResults.population ? 'ready' : 'not_ready',
        nightlight: taskResults.nightlight ? 'ready' : 'not_ready',
        road: taskResults.road_syntax ? 'ready' : 'not_ready',
      }
      const metricSummaryForSource = (sourceId) => {
        const bound = cloneArray(metrics.metrics).filter((metric) => cloneArray(metric.source_ids || metric.sourceIds).includes(sourceId))
        const readyCount = bound.filter((metric) => asText(metric.status) === 'ready').length
        const gapCount = bound.filter((metric) => asText(metric.status) !== 'ready').length
        if (readyCount || gapCount) return `ready ${readyCount} 项 / 缺口 ${gapCount} 项`
        return ''
      }
      return {
        scope,
        datasets: {
          poi: { items: includeRawData ? cloneArray(this.allPoisDetails) : [], count: poiTotal },
          h3: { features: includeRawData ? cloneArray(this.h3AnalysisGridFeatures) : [], count: h3Count },
          population: cloneObject(this.populationOverview || {}),
          nightlight: nightlightAnalysis,
          road: cloneObject(this.roadSyntaxSummary || {}),
        },
        analysis: {
          poi_h3: {
            summary: cloneObject(this.h3AnalysisSummary || {}),
            features: includeRawData ? cloneArray(this.h3AnalysisGridFeatures) : [],
          },
          population: cloneObject(this.populationOverview || {}),
          nightlight: nightlightAnalysis,
          road: cloneObject(this.roadSyntaxSummary || {}),
        },
        metrics,
        visual_assets: {},
        status,
        panelPayloads,
        summaryPack: cloneObject(panelPayloads.summary_pack || panelPayloads.summaryPack),
        summaryReady,
        taskResults,
        sourceDetails: {
          'current:scope': this.timeHorizon ? `${Number(this.timeHorizon)} 分钟范围` : '',
          center: scopeCenter.length ? `${scopeCenter[0].toFixed(4)}, ${scopeCenter[1].toFixed(4)}` : '',
          summary: summaryReady ? '已生成' : '',
          'current:dataset:poi': poiTotal ? `POI ${poiTotal} 条` : '',
          'current:dataset:h3': h3Count ? `H3 ${h3Count} 个网格` : '',
          'current:analysis:poi_h3': metricSummaryForSource('current:analysis:poi_h3'),
          'current:analysis:population': metricSummaryForSource('current:analysis:population'),
          'current:analysis:nightlight': metricSummaryForSource('current:analysis:nightlight'),
          'current:analysis:road': metricSummaryForSource('current:analysis:road'),
        },
      }
    },
    buildAgentPptPlanningSystemSourceContext(options = {}) {
      return this.buildAgentPptPlanningCurrent(options)
    },
    mergeAgentPptPlanningSystemSources(state = {}, { preservePreviousPayload = true, includeRawData = true } = {}) {
      const normalizedState = createPptPlanningState(state)
      const context = this.buildAgentPptPlanningApiContext()
      const areaId = asText(context.areaId || context.area_id)
      const previousById = new Map(cloneArray(normalizedState.sources).map((item) => [asText(item.id), item]))
      const systemSources = createPptSystemSources(this.buildAgentPptPlanningSystemSourceContext({ includeRawData })).map((source) => {
        const previous = previousById.get(asText(source.id))
        if (
          previous
          && isReadySource(previous)
          && asText(previous.meta && previous.meta.sourceKind) === 'system'
          && areaId
          && asText(previous.meta && previous.meta.areaId) === areaId
        ) {
          const previousMeta = cloneObject(previous.meta)
          const sourceMeta = cloneObject(source.meta)
          const keepPreviousPayload = preservePreviousPayload && asText(source.status) !== 'ready'
          if (!preservePreviousPayload && asText(source.status) !== 'ready') return source
          return {
            ...source,
            title: asText(previous.title) || source.title,
            status: asText(source.status) === 'ready' ? source.status : previous.status,
            selected: !!previous.selected,
            meta: {
              ...(keepPreviousPayload ? sourceMeta : previousMeta),
              ...(keepPreviousPayload ? previousMeta : sourceMeta),
              aiPayload: keepPreviousPayload ? previousMeta.aiPayload : sourceMeta.aiPayload,
              ai_payload: keepPreviousPayload ? previousMeta.ai_payload : sourceMeta.ai_payload,
              transport: keepPreviousPayload ? previousMeta.transport : sourceMeta.transport,
              areaId,
            },
          }
        }
        return source
      })
      return this.getAgentPptPlanningStateWithPackagePlaceholders(mergePptPlanningSources(normalizedState, systemSources), areaId)
    },
    getAgentPptPlanningStateWithSystemSources(options = {}) {
      const activeTab = this.getAgentActivePptPlanningTab()
      const state = this.mergeAgentPptPlanningSystemSources(this.getAgentActivePptPlanningState(), options)
      const runId = capabilitySourceRunId(activeTab && activeTab.capabilityInputSelections)
      if (!runId) return state
      const explicitAdditionalSourceIds = this.getAgentActivePptPlanningState().sources
        .filter(item => item?.selected && asText(item?.id) !== capabilityRunSourceId(runId))
        .map(item => asText(item.id))
        .filter(Boolean)
      return applyCapabilitySourceSelectionPolicy(state, runId, {
        additionalSelectedSourceIds: explicitAdditionalSourceIds,
      })
    },
    getAgentAnalysisSourceState() {
      return this.getAgentPptPlanningStateWithSystemSources({
        preservePreviousPayload: false,
        includeRawData: false,
      })
    },
    getAgentPptPlanningTabStateWithSystemSources(tabId = '') {
      const state = this.mergeAgentPptPlanningSystemSources(this.getAgentPptPlanningTabState(tabId))
      const tabs = this.ensureAgentTabs(false)
      const tab = getAnalysisWorkspaceTabsFromState(tabs).find(item => asText(item?.id) === asText(tabId))
      const runId = capabilitySourceRunId(tab && tab.capabilityInputSelections)
      if (!runId) return state
      const explicitAdditionalSourceIds = this.getAgentPptPlanningTabState(tabId).sources
        .filter(item => item?.selected && asText(item?.id) !== capabilityRunSourceId(runId))
        .map(item => asText(item.id))
        .filter(Boolean)
      return applyCapabilitySourceSelectionPolicy(state, runId, {
        additionalSelectedSourceIds: explicitAdditionalSourceIds,
      })
    },
    getAgentPptPlanningStateWithPackagePlaceholders(state = {}, areaId = '') {
      const normalized = createPptPlanningState(state)
      const normalizedAreaId = asText(areaId || (this.buildAgentPptPlanningApiContext && this.buildAgentPptPlanningApiContext().areaId))
      const activeKeys = this.agentPptPlanningAutoPackageKeys || {}
      const packageErrors = this.agentPptPlanningPackageErrors || {}
      const readySourceIds = new Set(cloneArray(normalized.sources)
        .filter((source) => isReadySource(source))
        .map((source) => asText(source.id))
        .filter(Boolean))
      const placeholders = PPT_AUTO_PACKAGE_DEFINITIONS
        .filter((definition) => !hasPptEvidencePackage(normalized, normalizedAreaId, definition))
        .map((definition) => {
          const packageKey = getPptEvidencePackageKey(normalizedAreaId, definition)
          const generating = !!(packageKey && activeKeys[packageKey])
          const errorMessage = asText(packageKey && packageErrors[packageKey])
          const missingSourceIds = cloneArray(definition.sourceIds).filter((sourceId) => !readySourceIds.has(asText(sourceId)))
          return {
            id: `package-placeholder:${definition.key}`,
            type: 'package',
            title: definition.title,
            status: generating ? 'generating' : errorMessage ? 'failed' : 'pending',
            selected: false,
            meta: {
              label: generating ? '整理中' : errorMessage ? '生成失败' : missingSourceIds.length ? `缺少 ${missingSourceIds.length} 个依赖` : '点击生成',
              sourceKind: 'package-placeholder',
              packagePlaceholder: true,
              error: errorMessage,
              message: errorMessage,
              missingSourceIds,
              areaId: normalizedAreaId,
              packageVersion: asText(definition.packageVersion),
              package: {
                package_mode: definition.packageMode,
                intent: definition.intent,
                source_ids: cloneArray(definition.sourceIds),
              },
            },
          }
        })
      return syncPptPackagePlaceholderSources(normalized, placeholders)
    },
    refreshAgentActivePptPlanningSources() {
      const tabs = this.ensureAgentTabs(true)
      const activeTab = this.getAgentActiveTopTab()
      if (asText(activeTab.kind) !== ANALYSIS_WORKSPACE_TAB_KIND) return
      const nextAnalysisWorkspaceTabs = getAnalysisWorkspaceTabsFromState(tabs).map((item) => {
        if (item.id !== activeTab.id || item.readonly) return item
        return {
          ...item,
          pptPlanningState: this.getAgentPptPlanningStateWithSystemSources(),
        }
      })
      this.agentTabs = cloneAgentTabsState(withAnalysisWorkspaceTabs(tabs, nextAnalysisWorkspaceTabs))
      this.syncCurrentAgentSession()
    },
    async refreshAgentActivePptPlanningDataSources(options = {}) {
      const context = this.buildAgentPptPlanningApiContext()
      const areaId = asText(context.areaId || context.area_id)
      const activeTab = this.getAgentActiveTopTab()
      const activeTabId = asText(activeTab && activeTab.id)
      const capabilityRunId = capabilitySourceRunId(activeTab && activeTab.capabilityInputSelections)
      if (!areaId || asText(activeTab && activeTab.kind) !== ANALYSIS_WORKSPACE_TAB_KIND) return
      const initialState = this.getAgentPptPlanningStateWithPackagePlaceholders(
        this.getAgentPptPlanningStateWithSystemSources(),
        areaId,
      )
      this.updateAgentPptPlanningTabRuntimeState(activeTabId, setPptSourceRefreshing(
        capabilityRunId ? initialState : syncPptSourceRefreshPlaceholderSources(initialState),
        true,
      ))
      try {
        try {
          if (typeof this.requestAgentPptPlanningSourceManifest !== 'function') throw new Error('ppt_source_manifest_unavailable')
          const manifestSources = await this.requestAgentPptPlanningSourceManifest(areaId, { conversationId: activeTabId })
          const tabs = this.ensureAgentTabs(true)
          if (asText(tabs.activeTabId) !== activeTabId) return
          const manifestState = this.getAgentPptPlanningStateWithPackagePlaceholders(
            this.getAgentPptPlanningStateWithSystemSources(),
            areaId,
          )
          this.updateAgentPptPlanningTabRuntimeState(activeTabId, setPptSourceRefreshing(
            capabilityRunId ? manifestState : syncPptSourceRefreshPlaceholderSources(manifestState, manifestSources),
            true,
          ))
        } catch (_) {
          // The full source refresh is authoritative; manifest only improves the waiting state.
        }
        const backendSources = await this.requestAgentPptPlanningDataSources(areaId, { conversationId: activeTabId })
        const tabs = this.ensureAgentTabs(true)
        if (asText(tabs.activeTabId) !== activeTabId) return
        const nextSources = cloneArray(backendSources).map((source) => normalizeBackendPptDataSource(source, areaId))
        const nextSourceIds = new Set(nextSources.map((source) => asText(source && source.id)).filter(Boolean))
        const activeStateBeforeRefresh = clearPptSourceRefreshPlaceholderSources(this.getAgentActivePptPlanningState())
        const explicitCapabilityAdditionalSourceIds = capabilityRunId
          ? new Set(activeStateBeforeRefresh.sources
            .filter(source => source && source.selected && asText(source.id) !== capabilityRunSourceId(capabilityRunId))
            .map(source => asText(source.id))
            .filter(Boolean))
          : null
        const activeStateWithoutRefreshPlaceholders = activeStateBeforeRefresh
        const currentState = createPptPlanningState({
          ...activeStateWithoutRefreshPlaceholders,
          sources: cloneArray(activeStateWithoutRefreshPlaceholders.sources)
            .filter((source) => !nextSourceIds.has(asText(source && source.id))),
        })
        const selectedSourceIdsBeforeRefresh = new Set(cloneArray(currentState.sources)
          .filter((source) => source && source.selected && asText(source.status) === 'ready' && asText(source.meta && source.meta.sourceKind) !== 'system')
          .map((source) => asText(source.id))
          .filter(Boolean))
        const mergedBackendState = mergePptPlanningSources(currentState, nextSources)
        const mergedSystemState = this.mergeAgentPptPlanningSystemSources(mergedBackendState)
        const unfilteredRefreshedState = this.getAgentPptPlanningStateWithPackagePlaceholders(
          createPptPlanningState({
            ...mergedSystemState,
            sources: cloneArray(mergedSystemState.sources).map((source) => ({
              ...source,
              selected: nextSourceIds.has(asText(source && source.id))
                ? !!source.selected
                : selectedSourceIdsBeforeRefresh.has(asText(source && source.id)),
            })),
          }),
          areaId,
        )
        const refreshedState = capabilityRunId
          ? applyCapabilitySourceSelectionPolicy(unfilteredRefreshedState, capabilityRunId, {
            additionalSelectedSourceIds: [...explicitCapabilityAdditionalSourceIds],
          })
          : unfilteredRefreshedState
        this.updateAgentActivePptPlanningStateWithSourceStale(setPptSourceRefreshing(refreshedState, false), currentState)
        if (!capabilityRunId && options.autoPackage !== false) {
          await Promise.allSettled([
            this.autoCreateAgentPptPlanningPoiEvidencePackage({ areaId }),
            this.autoCreateAgentPptPlanningNightlifePoiPackage({ areaId }),
            this.autoCreateAgentPptPlanningRoadCarrierPackage({ areaId }),
          ])
        }
      } catch (error) {
        this.updateAgentActivePptPlanningState(setPptSourceRefreshing(
          setPptGenerationError(this.getAgentPptPlanningStateWithSystemSources(), error && error.message, 'source_refresh'),
          false,
        ))
      }
    },
    getAgentPptPlanningSources() {
      return cloneArray(this.getAgentPptPlanningStateWithSystemSources().sources)
    },
    getAgentPptPlanningSourceGroups() {
      return cloneArray(this.getAgentPptPlanningStateWithSystemSources().sourceGroups)
    },
    getAgentPptPlanningSpec() {
      return cloneObject(this.getAgentPptPlanningStateWithSystemSources().spec)
    },
    getAgentPptPlanningCurrentStep() {
      return asText(this.getAgentPptPlanningStateWithSystemSources().currentStep)
    },
    getAgentPptPlanningOutline() {
      return cloneArray(this.getAgentPptPlanningStateWithSystemSources().outline)
    },
    getAgentPptPlanningNarrativePlan() {
      return cloneObject(this.getAgentActivePptPlanningState().narrativePlan)
    },
    getAgentPptPlanningSlideGenerationQueue() {
      return cloneArray(this.getAgentActivePptPlanningState().slideGenerationQueue)
    },
    getAgentPptPlanningSlideGenerationJob() {
      return cloneObject(this.getAgentActivePptPlanningState().slideGenerationJob)
    },
    getAgentPptPlanningVisualGenerationBySlide() {
      return cloneObject(this.getAgentActivePptPlanningState().visualGenerationBySlide)
    },
    getAgentPptPlanningSlides() {
      return cloneArray((this.getAgentActivePptPlanningState().deckBrief || {}).slides)
    },
    getAgentPptPlanningGenerationError() {
      return asText(this.getAgentActivePptPlanningState().generationError)
    },
    getAgentPptPlanningGenerationErrorSource() {
      return asText(this.getAgentActivePptPlanningState().generationErrorSource)
    },
    getAgentPptPlanningGenerationResponse() {
      return cloneObject(this.getAgentActivePptPlanningState().generationResponse)
    },
    getAgentPptPlanningGenerationJob() {
      return cloneObject(this.getAgentActivePptPlanningState().generationJob)
    },
    isAgentPptPlanningSourceRefreshing() {
      return !!this.getAgentActivePptPlanningState().sourceRefreshing
    },
    getAgentPptPlanningActiveRevisionTarget() {
      return cloneObject(this.getAgentActivePptPlanningState().activeRevisionTarget)
    },
    getAgentPptPlanningOutlineRevisionDraft() {
      return cloneObject(this.getAgentActivePptPlanningState().outlineRevisionDraft)
    },
    getAgentPptPlanningDirectiveRevisionDraft() {
      return cloneObject(this.getAgentActivePptPlanningState().directiveRevisionDraft)
    },
    getAgentPptPlanningRevisionSnapshots() {
      return cloneObject(this.getAgentActivePptPlanningState().revisionSnapshots)
    },
    getAgentPptPlanningStaleDirectivePageIds() {
      return cloneArray(this.getAgentActivePptPlanningState().staleDirectivePageIds)
    },
    getAgentPptPlanningRevisionGeneratingTarget() {
      return cloneObject(this.getAgentActivePptPlanningState().revisionGeneratingTarget)
    },
    isAgentPptPlanningDataPackageGenerating() {
      return !!this.getAgentActivePptPlanningState().dataPackageGenerating
    },
    isAgentPptPlanningWebSourceGenerating() {
      return !!this.agentPptPlanningWebSourceGenerating
    },
    isAgentPptPlanningSourceDeleting() {
      return !!this.agentPptPlanningSourceDeleting
    },
    isAgentPptPlanningSourceGrouping() {
      return !!this.getAgentActivePptPlanningState().sourceGrouping
    },
    getAgentPptPlanningSourceSummary() {
      return getPptSourceSummary(this.getAgentPptPlanningStateWithSystemSources())
    },
    ...createAgentAnalysisAskMethods(),
    getAgentPptPlanningActiveSlide() {
      return getActiveDeckSlideBrief(this.getAgentActivePptPlanningState()) || {}
    },
    isAgentPptPlanningSlideActive(slideId = '') {
      return asText(this.getAgentActivePptPlanningState().selectedSlideId) === asText(slideId)
    },
    updateAgentActivePptPlanningState(nextState = {}) {
      const tabs = this.ensureAgentTabs(true)
      const activeTab = this.getAgentActiveTopTab()
      if (asText(activeTab.kind) !== ANALYSIS_WORKSPACE_TAB_KIND) return
      this.updateAgentPptPlanningTabState(activeTab.id, nextState)
    },
    patchAgentPptPlanningTabState(tabId = '', nextState = {}, options = {}) {
      const targetId = asText(tabId)
      if (!targetId) return false
      const tabs = this.ensureAgentTabs(true)
      const tabIds = getAnalysisWorkspaceTabsFromState(tabs).map((item) => asText(item && item.id)).filter(Boolean)
      const targetTab = getAnalysisWorkspaceTabsFromState(tabs).find((item) => asText(item && item.id) === targetId) || null
      const normalizedNextState = createPptPlanningState(nextState)
      const shouldSync = options.sync !== false
      const includeUpdateDebug = options.debug !== false
      const updateDetails = {
        targetId,
        tabIds,
        matched: !!targetTab,
        readonly: !!(targetTab && targetTab.readonly),
        before: pptGenerationJobDebug(targetTab && targetTab.pptPlanningState && targetTab.pptPlanningState.generationJob),
        next: pptGenerationJobDebug(normalizedNextState.generationJob),
        beforeSlideCount: cloneArray((targetTab && targetTab.pptPlanningState && targetTab.pptPlanningState.deckBrief || {}).slides).length,
        nextSlideCount: cloneArray((normalizedNextState.deckBrief || {}).slides).length,
      }
      const fallbackActiveId = asText(tabs.activeTabId)
      const writeDebugToTab = (eventName = '', details = {}) => {
        const debugTargetId = targetTab ? targetId : fallbackActiveId
        if (!debugTargetId) return
        const debugTabs = this.ensureAgentTabs(true)
        let debugChanged = false
        const nextTabs = getAnalysisWorkspaceTabsFromState(debugTabs).map((item) => {
          if (asText(item.id) !== debugTargetId) return item
          debugChanged = true
          return {
            ...item,
            pptPlanningState: appendPptDebugEventToState(item.pptPlanningState, eventName, details),
          }
        })
        if (debugChanged) {
          this.agentTabs = cloneAgentTabsState(withAnalysisWorkspaceTabs(debugTabs, nextTabs))
        }
      }
      if (includeUpdateDebug) writeDebugToTab('tab_update_attempt', updateDetails)
      if (!targetTab) {
        if (includeUpdateDebug) writeDebugToTab('tab_update_noop_missing_tab', updateDetails)
        return false
      }
      if (targetTab.readonly) {
        if (includeUpdateDebug) writeDebugToTab('tab_update_noop_readonly', updateDetails)
        return false
      }
      let changed = false
      const refreshedTabs = this.ensureAgentTabs(true)
      const nextAnalysisWorkspaceTabs = getAnalysisWorkspaceTabsFromState(refreshedTabs).map((item) => {
        if (asText(item.id) !== targetId || item.readonly) return item
        changed = true
        const stateWithAttempt = includeUpdateDebug
          ? appendPptDebugEventToState(normalizedNextState, 'tab_update_attempt', updateDetails)
          : normalizedNextState
        return {
          ...item,
          pptPlanningState: includeUpdateDebug
            ? appendPptDebugEventToState(stateWithAttempt, 'tab_update_applied', updateDetails)
            : stateWithAttempt,
        }
      })
      if (!changed) return false
      this.agentTabs = cloneAgentTabsState(withAnalysisWorkspaceTabs(refreshedTabs, nextAnalysisWorkspaceTabs))
      if (shouldSync) {
        this.syncCurrentAgentSession()
        if (includeUpdateDebug) {
          const afterSync = this.getAgentPptPlanningTabState(targetId)
          writeDebugToTab('tab_update_after_sync', {
            ...updateDetails,
            afterSync: pptGenerationJobDebug(afterSync.generationJob),
            afterSyncSlideCount: cloneArray((afterSync.deckBrief || {}).slides).length,
          })
          const nextSlideCount = Number(updateDetails.nextSlideCount || 0) || 0
          const afterSyncSlideCount = cloneArray((afterSync.deckBrief || {}).slides).length
          if (nextSlideCount > 0 && afterSyncSlideCount === 0) {
            const expectedIndexes = cloneArray((normalizedNextState.deckBrief || {}).slides)
              .map((slide) => Number(slide && slide.index || 0) || 0)
              .filter(Boolean)
            writeDebugToTab('slide_writeback_lost_after_sync', {
              ...updateDetails,
              expectedIndexes,
              afterSyncSlideCount,
            })
          }
        }
      }
      return true
    },
    updateAgentPptPlanningTabRuntimeState(tabId = '', nextState = {}) {
      return this.patchAgentPptPlanningTabState(tabId, nextState, { sync: false, debug: false })
    },
    updateAgentPptPlanningTabState(tabId = '', nextState = {}) {
      return this.patchAgentPptPlanningTabState(tabId, nextState, { sync: true, debug: true })
    },
    cleanupAgentPptPlanningVisualArtifacts(filenames = []) {
      const uniqueFilenames = uniquePptText(filenames)
      if (!uniqueFilenames.length) return Promise.resolve(null)
      const request = typeof this.requestAgentPptPlanningVisualArtifactCleanup === 'function'
        ? this.requestAgentPptPlanningVisualArtifactCleanup(uniqueFilenames)
        : cleanupPptVisualArtifacts(uniqueFilenames)
      return Promise.resolve(request).catch((error) => {
        if (typeof console !== 'undefined' && console.warn) {
          console.warn('PPT visual artifact cleanup failed', error)
        }
        return null
      })
    },
    buildAgentPptPlanningApiContext() {
      return {
        areaId: asText(
          (typeof this.getCurrentAgentHistoryId === 'function' && this.getCurrentAgentHistoryId())
          || this.currentHistoryRecordId
          || this.currentAnalysisId
          || this.analysisId
          || this.activeAgentSessionId,
        ),
        current: this.buildAgentPptPlanningCurrent(),
      }
    },
    async buildAgentPptPlanningVisualApiContext() {
      const context = this.buildAgentPptPlanningApiContext()
      let visualSnapshots = []
      if (typeof this.ensureAgentVisualSnapshotCache === 'function') {
        try {
          visualSnapshots = await this.ensureAgentVisualSnapshotCache({ allowMainMapFallback: false })
        } catch (error) {
          if (typeof console !== 'undefined' && console.warn) {
            console.warn('PPT visual snapshots failed; continuing without existing assets', error)
          }
        }
      }
      return {
        ...context,
        current: {
          ...cloneObject(context.current),
          visual_snapshots: cloneArray(visualSnapshots),
        },
      }
    },
    async uploadAgentPptPlanningDocumentSource(file, documentRole) {
      if (!file) return
      const placeholderSourceId = createPptUploadSourceId('document')
      const uploadDocument = { file_name: asText(file.name) || '文档资料', document_role: documentRole }
      this.updateAgentActivePptPlanningState(upsertPptDocumentSource(
        this.getAgentPptPlanningStateWithSystemSources(),
        uploadDocument,
        {
          sourceId: placeholderSourceId,
          status: 'generating',
          label: '上传中',
          documentRole,
          uploadPlaceholder: true,
        },
      ))
      let document = null
      try {
        document = await uploadDocumentSource(file, file.name || '', documentRole)
        const documentId = asText(document && document.id)
        if (documentId) {
          this.updateAgentActivePptPlanningState(upsertPptDocumentSource(
            this.getAgentPptPlanningStateWithSystemSources(),
            document,
            {
              previousSourceId: placeholderSourceId,
              status: 'generating',
              label: '整理中',
              documentRole,
            },
          ))
          const parseJob = await this.requestAgentPptPlanningDocumentParse(documentId)
          await waitForPptPlanningJob(parseJob && parseJob.job_id)
          this.updateAgentActivePptPlanningState(upsertPptDocumentSource(
            this.getAgentPptPlanningStateWithSystemSources(),
            document,
            {
              status: 'ready',
              label: 'PageIndex 已生成',
              documentRole,
            },
          ))
        }
        await this.refreshAgentActivePptPlanningDataSources({ autoPackage: false })
      } catch (error) {
        const documentId = asText(document && document.id)
        const failedDocument = documentId ? document : uploadDocument
        this.updateAgentActivePptPlanningState(upsertPptDocumentSource(
          this.getAgentPptPlanningStateWithSystemSources(),
          failedDocument,
          {
            sourceId: documentId ? '' : placeholderSourceId,
            previousSourceId: documentId ? placeholderSourceId : '',
            status: 'failed',
            label: documentId ? '整理失败' : '上传失败',
            documentRole,
            uploadPlaceholder: !documentId,
          },
        ))
        this.updateAgentActivePptPlanningState(setPptGenerationError(this.getAgentPptPlanningStateWithSystemSources(), error && error.message, 'source_refresh'))
      }
    },
    async uploadAgentPptPlanningImageSource(file) {
      if (!file) return
      const context = this.buildAgentPptPlanningApiContext ? this.buildAgentPptPlanningApiContext() : {}
      const areaId = asText(context.areaId || context.area_id)
      const activeTab = this.getAgentActiveTopTab()
      const conversationId = asText(activeTab && activeTab.id)
      const placeholderSourceId = createPptUploadSourceId('image')
      const uploadAttachment = { filename: asText(file.name) || '图片来源', mime_type: asText(file.type) }
      this.updateAgentActivePptPlanningState(upsertPptImageSource(
        this.getAgentPptPlanningStateWithSystemSources(),
        uploadAttachment,
        {
          sourceId: placeholderSourceId,
          status: 'generating',
          label: '上传中',
          conversationId,
          uploadPlaceholder: true,
        },
      ))
      let attachment = null
      try {
        attachment = await uploadImageSource(file, conversationId, areaId)
        if (attachment) {
          this.updateAgentActivePptPlanningState(upsertPptImageSource(
            this.getAgentPptPlanningStateWithSystemSources(),
            attachment,
            { previousSourceId: placeholderSourceId, status: 'generating', label: '图片解析中', conversationId },
          ))
        }
        await this.refreshAgentActivePptPlanningDataSources({ autoPackage: false })
      } catch (error) {
        this.updateAgentActivePptPlanningState(upsertPptImageSource(
          this.getAgentPptPlanningStateWithSystemSources(),
          attachment || uploadAttachment,
          {
            sourceId: attachment ? '' : placeholderSourceId,
            previousSourceId: attachment ? placeholderSourceId : '',
            status: 'failed',
            label: attachment ? '图片解析失败' : '上传失败',
            conversationId,
            uploadPlaceholder: !attachment,
          },
        ))
        this.updateAgentActivePptPlanningState(setPptGenerationError(this.getAgentPptPlanningStateWithSystemSources(), error && error.message, 'source_refresh'))
      }
    },
    async retryAgentPptPlanningSource(sourceId = '') {
      const state = this.getAgentPptPlanningStateWithSystemSources()
      const id = asText(sourceId)
      const source = cloneArray(state.sources).find((item) => asText(item && item.id) === id)
      if (!source) return
      const context = this.buildAgentPptPlanningApiContext ? this.buildAgentPptPlanningApiContext() : {}
      const areaId = asText(context.areaId || context.area_id)
      try {
        if (isPptDocumentSource(source)) {
          const documentId = documentIdFromPptSource(source)
          if (!documentId) throw new Error('document_source_id_missing')
          this.updateAgentActivePptPlanningState(upsertPptDocumentSource(state, { id: documentId, title: source.title }, { status: 'generating', label: '重新解析中' }))
          const parseJob = await this.requestAgentPptPlanningDocumentParse(documentId)
          await waitForPptPlanningJob(parseJob && parseJob.job_id)
          await this.refreshAgentActivePptPlanningDataSources({ autoPackage: false })
          return
        }
        if (isPptImageSource(source)) {
          const attachmentId = imageAttachmentIdFromPptSource(source)
          const conversationId = imageConversationIdFromPptSource(source)
          if (!attachmentId || !conversationId) throw new Error('image_source_id_missing')
          const attachment = await this.requestAgentPptPlanningImageRetry(attachmentId, conversationId)
          this.updateAgentActivePptPlanningState(upsertPptImageSource(state, attachment || { attachment_id: attachmentId }, { status: 'generating', label: '图片重新解析中', conversationId }))
          await this.refreshAgentActivePptPlanningDataSources({ autoPackage: false })
          return
        }
        if (isPptPersistedArtifactSource(source)) {
          const meta = cloneObject(source.meta)
          if (asText(meta.sourceKind) !== 'web' && !asText(source.id).startsWith('web:')) {
            throw new Error('source_retry_not_supported')
          }
          const preview = await this.requestAgentPptWebSourcePreview(webSourceRetryPayloadFromPptSource(source, areaId))
          const committed = await this.requestAgentPptWebSourceCommit({
            area_id: areaId,
            preview: preview && typeof preview.model_dump === 'function' ? preview.model_dump() : preview,
          })
          this.updateAgentActivePptPlanningState(addPptDataPackageSource(this.getAgentPptPlanningStateWithSystemSources(), committed))
          await this.refreshAgentActivePptPlanningDataSources({ autoPackage: false })
          return
        }
        throw new Error('source_retry_not_supported')
      } catch (error) {
        this.updateAgentActivePptPlanningState(setPptGenerationError(this.getAgentPptPlanningStateWithSystemSources(), error && error.message, 'source_refresh'))
      }
    },
    async manageAgentPptPlanningWebSource(payload = {}) {
      const mode = asText(payload.mode)
      const context = this.buildAgentPptPlanningApiContext ? this.buildAgentPptPlanningApiContext() : {}
      const areaId = asText(context.areaId || context.area_id)
      if (mode === 'location-default') {
        const resolve = typeof payload.resolve === 'function' ? payload.resolve : null
        try {
          const defaults = await this.requestAgentPptWebSourceLocationDefault({ area_id: areaId })
          if (resolve) resolve(defaults)
          return defaults
        } catch (error) {
          const fallback = { area_id: areaId, region_name: '当前分析区域', administrative_area: '', warnings: ['默认地区名生成失败，请手动输入。'] }
          if (resolve) resolve(fallback)
          return fallback
        }
      }
      if (!areaId || this.agentPptPlanningWebSourceGenerating) return
      this.agentPptPlanningWebSourceGenerating = true
      try {
        const requestPayload = {
          area_id: areaId,
          region_name: asText(payload.region_name) || '当前分析区域',
          administrative_area: asText(payload.administrative_area),
          topic: asText(payload.topic || this.getAgentPptPlanningSpec().topic),
          intent: asText(payload.topic || this.getAgentPptPlanningSpec().topic),
          categories: cloneArray(payload.categories).map((item) => asText(item)).filter(Boolean),
          source_modes: cloneArray(payload.source_modes || payload.sourceModes).map((item) => asText(item)).filter(Boolean),
          urls: cloneArray(payload.urls).map((item) => asText(item)).filter(Boolean),
          limit: 8,
        }
        if (mode === 'preview') {
          const response = await this.requestAgentPptWebSourcePreview(requestPayload)
          if (typeof payload.resolve === 'function') payload.resolve(response)
          return response
        }
        if (mode !== 'commit') {
          throw new Error('ppt_web_source_mode_required')
        }
        const response = await this.requestAgentPptWebSourceCommit({
          area_id: areaId,
          preview: cloneObject(payload.preview),
        })
        this.updateAgentActivePptPlanningState(addPptDataPackageSource(
          this.getAgentPptPlanningStateWithSystemSources(),
          response,
        ))
        if (typeof payload.resolve === 'function') payload.resolve(response)
        return response
      } catch (error) {
        if (typeof payload.reject === 'function') payload.reject(error)
        this.updateAgentActivePptPlanningState(setPptGenerationError(
          this.getAgentPptPlanningStateWithSystemSources(),
          normalizePptGenerationErrorMessage(error, 'source_refresh'),
          'source_refresh',
        ))
        throw error
      } finally {
        this.agentPptPlanningWebSourceGenerating = false
      }
    },
    async classifyAgentPptPlanningSourceGroups() {
      const state = this.getAgentPptPlanningStateWithSystemSources()
      if (!cloneArray(state.sources).length || state.sourceGrouping) return
      this.updateAgentActivePptPlanningState(setPptSourceGrouping(state, true))
      try {
        const context = this.buildAgentPptPlanningApiContext()
        const response = await this.requestAgentPptSourceGroupClassification({
          area_id: asText(context.areaId || context.area_id),
          sources: cloneArray(state.sources),
          current: cloneObject(context.current),
          previous_groups: cloneArray(state.sourceGroups).map((group) => ({
            id: group.id,
            title: group.title,
            emoji: group.emoji,
            source_ids: cloneArray(group.sourceIds),
            collapsed: !!group.collapsed,
            meta: cloneObject(group.meta),
          })),
        })
        this.updateAgentActivePptPlanningState(applyPptSourceGroupsResponse(this.getAgentPptPlanningStateWithSystemSources(), response))
      } catch (error) {
        this.updateAgentActivePptPlanningState(setPptGenerationError(this.getAgentPptPlanningStateWithSystemSources(), error && error.message, 'source_grouping'))
      }
    },
    async autoCreateAgentPptPlanningEvidencePackage(options = {}) {
      const context = this.buildAgentPptPlanningApiContext ? this.buildAgentPptPlanningApiContext() : {}
      const areaId = asText(options.areaId || context.areaId || context.area_id)
      const sourceIds = cloneArray(options.sourceIds).map((item) => asText(item)).filter(Boolean)
      const intent = asText(options.intent)
      const packageMode = asText(options.packageMode) || 'evidence'
      const packageVersion = asText(options.packageVersion)
      const state = this.getAgentPptPlanningStateWithSystemSources()
      const sourcesById = new Map(cloneArray(state.sources).map((item) => [asText(item.id), item]))
      const packageOptions = { sourceIds, packageMode, intent, packageVersion }
      const packageKey = getPptEvidencePackageKey(areaId, packageOptions)
      if (
        !areaId
        || !sourceIds.length
        || !intent
        || sourceIds.some((sourceId) => !isReadySource(sourcesById.get(sourceId)))
        || hasPptEvidencePackage(state, areaId, packageOptions)
      ) return
      const activePackageKeys = this.agentPptPlanningAutoPackageKeys || {}
      const packageErrors = this.agentPptPlanningPackageErrors || {}
      this.agentPptPlanningAutoPackageKeys = activePackageKeys
      this.agentPptPlanningPackageErrors = packageErrors
      if (packageKey && activePackageKeys[packageKey]) return
      if (packageKey) delete packageErrors[packageKey]
      if (packageKey) activePackageKeys[packageKey] = true
      this.updateAgentActivePptPlanningState(this.getAgentPptPlanningStateWithPackagePlaceholders(
        state,
        areaId,
      ))
      try {
        const spatialPayload = buildPptDataPackageSpatialPayload(context.current)
        const response = await this.requestAgentPptPlanningDataPackage({
          area_id: areaId,
          source_ids: sourceIds,
          package_mode: packageMode,
          package_version: packageVersion,
          intent,
          query: '',
          limit: Number(options.limit || 50) || 50,
          ...spatialPayload,
        })
        this.updateAgentActivePptPlanningState(addPptDataPackageSource(
          this.getAgentActivePptPlanningState(),
          attachPptDataPackageRuntimeMeta(response, areaId, { autoGenerated: true, packageVersion }),
        ))
        if (packageKey) delete packageErrors[packageKey]
        this.agentPptPlanningPackageErrors = packageErrors
      } catch (error) {
        const message = asText(error && error.message) || 'data_package_failed'
        if (packageKey) packageErrors[packageKey] = message
        this.agentPptPlanningPackageErrors = packageErrors
        this.updateAgentActivePptPlanningState(this.getAgentPptPlanningStateWithPackagePlaceholders(
          this.getAgentPptPlanningStateWithSystemSources(),
          areaId,
        ))
      } finally {
        if (packageKey) delete activePackageKeys[packageKey]
        this.updateAgentActivePptPlanningState(this.getAgentPptPlanningStateWithPackagePlaceholders(
          this.getAgentActivePptPlanningState(),
          areaId,
        ))
      }
    },
    async autoCreateAgentPptPlanningPoiEvidencePackage(options = {}) {
      const areaId = asText(options.areaId || (this.buildAgentPptPlanningApiContext && this.buildAgentPptPlanningApiContext().areaId))
      const definition = getPptAutoPackageDefinition('poi-evidence')
      return this.autoCreateAgentPptPlanningEvidencePackage({
        areaId,
        sourceIds: definition.sourceIds,
        packageMode: definition.packageMode,
        intent: definition.intent,
        packageVersion: definition.packageVersion,
        limit: definition.limit,
      })
    },
    async autoCreateAgentPptPlanningNightlifePoiPackage(options = {}) {
      const areaId = asText(options.areaId || (this.buildAgentPptPlanningApiContext && this.buildAgentPptPlanningApiContext().areaId))
      const definition = getPptAutoPackageDefinition('nightlife-poi')
      return this.autoCreateAgentPptPlanningEvidencePackage({
        areaId,
        sourceIds: definition.sourceIds,
        packageMode: definition.packageMode,
        intent: definition.intent,
        packageVersion: definition.packageVersion,
        limit: definition.limit,
      })
    },
    async autoCreateAgentPptPlanningRoadCarrierPackage(options = {}) {
      const areaId = asText(options.areaId || (this.buildAgentPptPlanningApiContext && this.buildAgentPptPlanningApiContext().areaId))
      const definition = getPptAutoPackageDefinition('road-carrier')
      return this.autoCreateAgentPptPlanningEvidencePackage({
        areaId,
        sourceIds: definition.sourceIds,
        packageMode: definition.packageMode,
        intent: definition.intent,
        packageVersion: definition.packageVersion,
        limit: definition.limit,
      })
    },
    async generateAgentPptPlanningPackageSource(sourceId = '') {
      const key = asText(sourceId).replace(/^package-placeholder:/, '')
      const definition = getPptAutoPackageDefinition(key)
      if (!definition) return
      const context = this.buildAgentPptPlanningApiContext ? this.buildAgentPptPlanningApiContext() : {}
      const areaId = asText(context.areaId || context.area_id)
      await this.autoCreateAgentPptPlanningEvidencePackage({
        areaId,
        sourceIds: definition.sourceIds,
        packageMode: definition.packageMode,
        intent: definition.intent,
        packageVersion: definition.packageVersion,
        limit: definition.limit,
      })
    },
    async createAgentPptPlanningDataPackage() {
      const state = this.getAgentPptPlanningStateWithSystemSources()
      const selectedSourceIds = cloneArray(state.sources)
        .filter((item) => item && item.selected && asText(item.status) === 'ready')
        .map((item) => asText(item.id))
        .filter(Boolean)
      if (!selectedSourceIds.length || state.dataPackageGenerating) return
      this.updateAgentActivePptPlanningState(setPptDataPackageGenerating(state, true))
      try {
        const context = this.buildAgentPptPlanningApiContext()
        const spatialPayload = buildPptDataPackageSpatialPayload(context.current)
        const response = await this.requestAgentPptPlanningDataPackage({
          area_id: asText(context.areaId || context.area_id),
          source_ids: selectedSourceIds,
          package_mode: 'evidence',
          intent: DEFAULT_PPT_POI_EVIDENCE_INTENT,
          query: '',
          limit: 50,
          ...spatialPayload,
        })
        this.updateAgentActivePptPlanningState(addPptDataPackageSource(
          this.getAgentPptPlanningStateWithSystemSources(),
          attachPptDataPackageRuntimeMeta(response, asText(context.areaId || context.area_id)),
        ))
      } catch (error) {
        this.updateAgentActivePptPlanningState(setPptGenerationError(this.getAgentPptPlanningStateWithSystemSources(), error && error.message, 'data_package'))
      }
    },
    selectAgentPptPlanningSlide(slideId = '') {
      this.updateAgentActivePptPlanningState(selectDeckSlideBrief(this.getAgentActivePptPlanningState(), slideId))
    },
    captureAgentActivePptPlanningTabState() {
      const tabs = this.ensureAgentTabs(true)
      const activeTab = this.getAgentActiveTopTab()
      if (asText(activeTab.kind) !== ANALYSIS_WORKSPACE_TAB_KIND) return
      const nextAnalysisWorkspaceTabs = getAnalysisWorkspaceTabsFromState(tabs).map((item) => {
        if (item.id !== activeTab.id || item.readonly) return item
        return {
          ...item,
          panelPayloads: cloneObject(this.agentPanelPayloads),
          pptPlanningState: createPptPlanningState(item.pptPlanningState),
        }
      })
      this.agentTabs = cloneAgentTabsState(withAnalysisWorkspaceTabs(tabs, nextAnalysisWorkspaceTabs))
    },
    createAgentPptPlanningTab(options = {}) {
      const tabs = this.ensureAgentTabs(true)
      this.captureAgentActiveSummaryTabState()
      this.captureAgentActiveSiteSelectionTabState()
      this.captureAgentActivePptPlanningTabState()
      this.captureAgentActiveFollowupTabState()
      const tabId = this.createAgentPptPlanningViewId()
      const tab = {
        id: tabId,
        kind: ANALYSIS_WORKSPACE_TAB_KIND,
        title: this.formatAgentTabTitle(ANALYSIS_WORKSPACE_TAB_KIND, options.title),
        source: asText(options.source) || 'draft',
        sessionId: asText(options.sessionId),
        readonly: !!options.readonly,
        createdAt: new Date().toISOString(),
        panelPayloads: cloneObject(this.agentPanelPayloads),
        capabilityInputSelections: normalizeCapabilityInputSelections(options.capabilityInputSelections),
        pptPlanningState: createPptPlanningState(options.pptPlanningState),
      }
      const capabilityRunId = capabilitySourceRunId(tab.capabilityInputSelections)
      tab.pptPlanningState = capabilityRunId
        ? applyCapabilitySourceSelectionPolicy(
          mergePptPlanningSources(tab.pptPlanningState, createPptSystemSources(this.buildAgentPptPlanningSystemSourceContext())),
          capabilityRunId,
        )
        : mergePptPlanningSources(tab.pptPlanningState, createPptSystemSources(this.buildAgentPptPlanningSystemSourceContext()))
      const nextAnalysisWorkspaceTabs = [...getAnalysisWorkspaceTabsFromState(tabs), tab]
      tabs.activeTabId = tabId
      this.agentTabs = cloneAgentTabsState(withAnalysisWorkspaceTabs(tabs, nextAnalysisWorkspaceTabs))
      this.syncActiveAgentRuntimeView(this.activeAgentSessionId)
      this.syncCurrentAgentSession()
      this.refreshAgentActivePptPlanningDataSources()
      return tabId
    },
  }
}
