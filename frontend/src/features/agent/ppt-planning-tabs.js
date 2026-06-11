import { asText, cloneArray, cloneObject } from './normalizers.js'
import { getAnalysisTaskDefinition } from './analysis-task-registry.js'
import { createPptSystemSources } from '../ppt-planning/model.js'
import {
  classifyPptSourceGroups,
  createPptDataPackage,
  generateDeckBrief,
  generatePptSpec,
  listPptDataSources,
  regenerateDeckBriefSlide,
  regeneratePptSpecSection,
} from '../ppt-planning/api.js'
import {
  addPptDataPackageSource,
  applyDeckBriefSlideRevision,
  applyDeckBriefResponse,
  applyPptOutlineSectionRevision,
  applyPptSpecResponse,
  applyPptSourceGroupsResponse,
  buildDeckBriefSlidePayload,
  buildDeckBriefPayload,
  buildPptOutlineSectionPayload,
  buildPptSpecPayload,
  createPptPlanningState,
  getActiveDeckSlideBrief,
  getPptRevisionKey,
  getPendingPptPackageSources,
  getPptSourceSummary,
  isPptDirectivePageStale,
  mergePptPlanningSources,
  movePptSourceToGroup,
  removePptSource,
  removePptSourceGroup,
  renamePptSource,
  renamePptSourceGroup,
  resetPptPlanningToMaterials,
  resetPptPlanningToOutlineReady,
  selectDeckSlideBrief,
  setAllPptSourcesSelected,
  setPptDataPackageGenerating,
  setPptGenerationError,
  setPptDirectiveGenerating,
  setPptOutlineGenerating,
  setPptActiveRevisionTarget,
  setPptRevisionDraftField,
  setPptRevisionGeneratingTarget,
  setPptSourceGroupEmoji,
  setPptSourceGrouping,
  setPptSpecField,
  setPptSourceGroupSelected,
  syncPptPackagePlaceholderSources,
  togglePptSourceGroupCollapsed,
  togglePptSourceSelection,
  undoPptSectionRevision,
} from '../ppt-planning/ui-state.js'

const DEFAULT_PPT_POI_EVIDENCE_INTENT = '为 PPT 指令生成整理当前区域代表性 POI 资料'
const DEFAULT_PPT_NIGHTLIFE_POI_INTENT = '整理夜生活与夜间消费相关 POI，并与夜光格子对应'
const DEFAULT_PPT_CARRIER_EVIDENCE_INTENT = '识别当前区域 POI、路网、人口、夜光共同支撑的空间载体'
const PPT_NIGHTLIFE_PACKAGE_VERSION = 'nightlife-evidence-v2'
const PPT_CARRIER_PACKAGE_VERSION = 'road-carrier-evidence-v2'
const PPT_AUTO_PACKAGE_DEFINITIONS = Object.freeze([
  {
    key: 'poi-evidence',
    title: 'POI 资料包',
    sourceIds: ['system:poi'],
    packageMode: 'evidence',
    intent: DEFAULT_PPT_POI_EVIDENCE_INTENT,
    limit: 50,
  },
  {
    key: 'nightlife-poi',
    title: '夜生活 POI × 夜光格子资料包',
    sourceIds: ['system:poi', 'system:nightlight'],
    packageMode: 'evidence',
    intent: DEFAULT_PPT_NIGHTLIFE_POI_INTENT,
    packageVersion: PPT_NIGHTLIFE_PACKAGE_VERSION,
    limit: 50,
  },
  {
    key: 'road-carrier',
    title: 'POI × 路网空间载体资料包',
    sourceIds: ['system:poi', 'system:road-syntax', 'system:population', 'system:nightlight'],
    packageMode: 'evidence',
    intent: DEFAULT_PPT_CARRIER_EVIDENCE_INTENT,
    packageVersion: PPT_CARRIER_PACKAGE_VERSION,
    limit: 50,
  },
])

function normalizePptLngLat(value = null) {
  if (!value) return []
  let lng = NaN
  let lat = NaN
  if (Array.isArray(value)) {
    lng = Number(value[0])
    lat = Number(value[1])
  } else if (typeof value === 'object') {
    if (typeof value.getLng === 'function' && typeof value.getLat === 'function') {
      lng = Number(value.getLng())
      lat = Number(value.getLat())
    } else {
      lng = Number(value.lng ?? value.longitude ?? value.lon ?? value.x)
      lat = Number(value.lat ?? value.latitude ?? value.y)
    }
  }
  if (!Number.isFinite(lng) || !Number.isFinite(lat)) return []
  if (lng < -180 || lng > 180 || lat < -90 || lat > 90) return []
  return [lng, lat]
}

function resolvePptPlanningRadiusMeters(ctx = {}, featureProps = {}) {
  const explicitRadius = Number(featureProps.radius_m ?? featureProps.radiusM ?? 0)
  if (Number.isFinite(explicitRadius) && explicitRadius > 0) {
    return Math.min(50000, Math.round(explicitRadius))
  }
  if (ctx && typeof ctx._resolveCircleRadiusMeters === 'function') {
    const runtimeRadius = Number(ctx._resolveCircleRadiusMeters())
    if (Number.isFinite(runtimeRadius) && runtimeRadius > 0) {
      return Math.min(50000, Math.round(runtimeRadius))
    }
  }
  const speedByMode = { walking: 5, bicycling: 15, driving: 30 }
  const mode = asText(ctx && ctx.transportMode).toLowerCase()
  const speedKmh = Number(speedByMode[mode]) || speedByMode.walking
  const timeMin = Number((ctx && ctx.timeHorizon) || featureProps.time_min || featureProps.timeMin || 0) || 0
  if (!Number.isFinite(timeMin) || timeMin <= 0) return null
  return Math.min(50000, Math.round((speedKmh * 1000 * timeMin) / 60))
}

function buildPptDataPackageSpatialPayload(analysisContext = {}) {
  const scope = cloneObject(analysisContext.scope)
  const center = normalizePptLngLat(scope.center || scope.center_gcj02 || scope.centerGcj02)
  const payload = {}
  if (center.length) {
    payload.center = center
    payload.center_coord_type = asText(scope.center_coord_type || scope.centerCoordType) || 'gcj02'
  }
  const radiusM = Number(scope.radius_m ?? scope.radiusM ?? 0)
  if (Number.isFinite(radiusM) && radiusM > 0) {
    payload.radius_m = Math.min(50000, Math.round(radiusM))
  }
  return payload
}

function isReadySource(source = {}) {
  return asText(source && source.status) === 'ready'
}

function normalizeBackendPptDataSource(source = {}, areaId = '') {
  const status = asText(source.status) || 'pending'
  const summary = asText(source.summary)
  const meta = cloneObject(source.meta)
  return {
    id: asText(source.id),
    type: asText(source.type) || 'data',
    title: asText(source.title) || '未命名来源',
    status,
    selected: status === 'ready',
    meta: {
      ...meta,
      label: asText(meta.label) || summary || (status === 'ready' ? '已生成' : '待生成'),
      sourceKind: 'system',
      areaId: asText(meta.areaId) || asText(areaId),
      count: Number(source.count || meta.count || 0) || 0,
    },
  }
}

function hasPptEvidencePackage(state = {}, areaId = '', options = {}) {
  const normalizedAreaId = asText(areaId)
  const expectedMode = asText(options.packageMode) || 'evidence'
  const expectedIntent = asText(options.intent)
  const expectedVersion = asText(options.packageVersion)
  const expectedSourceIds = cloneArray(options.sourceIds).map((item) => asText(item)).filter(Boolean)
  return cloneArray(createPptPlanningState(state).sources).some((source) => {
    const meta = cloneObject(source.meta)
    const pack = cloneObject(meta.package)
    const sourceIds = cloneArray(pack.source_ids).map((item) => asText(item))
    if (asText(meta.sourceKind) !== 'package' && !asText(source.id).startsWith('package:')) return false
    if (normalizedAreaId && asText(meta.areaId) !== normalizedAreaId) return false
    if (expectedMode && asText(pack.package_mode) !== expectedMode) return false
    if (expectedIntent && asText(pack.intent) !== expectedIntent) return false
    if (expectedVersion && asText(meta.packageVersion) !== expectedVersion) return false
    return expectedSourceIds.every((sourceId) => sourceIds.includes(sourceId))
  })
}

function getPptEvidencePackageKey(areaId = '', options = {}) {
  const normalizedAreaId = asText(areaId)
  const sourceKey = cloneArray(options.sourceIds).map((item) => asText(item)).filter(Boolean).sort().join('+')
  const mode = asText(options.packageMode) || 'evidence'
  const intent = asText(options.intent)
  const version = asText(options.packageVersion)
  return normalizedAreaId ? `${normalizedAreaId}::${sourceKey}::${mode}::${intent}::${version}` : ''
}

function getPptAutoPackageDefinition(key = '') {
  return PPT_AUTO_PACKAGE_DEFINITIONS.find((item) => item.key === asText(key)) || null
}

function attachPptDataPackageRuntimeMeta(response = {}, areaId = '', options = {}) {
  const source = cloneObject(response.source || response)
  if (!source.id) return response
  return {
    ...response,
    source: {
      ...source,
      meta: {
        ...cloneObject(source.meta),
        areaId: asText(areaId),
        autoGenerated: !!options.autoGenerated,
        packageVersion: asText(options.packageVersion),
      },
    },
  }
}

export function normalizeAgentPptPlanningTab(item = {}, options = {}) {
  const source = asText(item && item.source) || 'draft'
  return {
    id: asText(item && item.id),
    kind: 'ppt_planning',
    title: asText(item && item.title) || '策划 PPT',
    source,
    sessionId: asText((item && (item.session_id || item.sessionId)) || ''),
    readonly: options.restore ? !!(item && item.readonly && source !== 'history') : !!(item && item.readonly),
    createdAt: asText(item && (item.created_at || item.createdAt)) || new Date().toISOString(),
    panelPayloads: cloneObject(item && (item.panel_payloads || item.panelPayloads)),
    pptPlanningState: createPptPlanningState(item && (item.ppt_planning_state || item.pptPlanningState)),
  }
}

export function serializeAgentPptPlanningTab(item = {}, fallbackPanelPayloads = {}) {
  return {
    id: item.id,
    title: item.title || '策划 PPT',
    kind: 'ppt_planning',
    source: item.source || 'draft',
    session_id: item.sessionId || '',
    readonly: !!item.readonly,
    created_at: item.createdAt,
    panel_payloads: cloneObject(item.panelPayloads || fallbackPanelPayloads),
    ppt_planning_state: createPptPlanningState(item.pptPlanningState),
  }
}

export function createAgentPptPlanningTabMethods() {
  return {
    createAgentPptPlanningViewId() {
      return `ppt-planning-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
    },
    openAgentPptPlanningFromReport(options = {}) {
      this.agentWorkspaceView = 'report'
      const tabs = this.ensureAgentTabs(true)
      const existing = cloneArray(tabs.pptPlanningTabs).find((item) => asText(item && item.source) === 'current' || asText(item && item.source) === 'draft')
      if (existing && !options.forceNew) {
        const alreadyActive = asText(tabs.activeTabId) === asText(existing.id)
        this.switchAgentTopTab(existing.id)
        if (alreadyActive) {
          this.refreshAgentActivePptPlanningSources()
          this.refreshAgentActivePptPlanningDataSources()
        }
        return existing.id
      }
      return this.createAgentPptPlanningTab({ title: '策划 PPT', source: 'current' })
    },
    isAgentPptPlanningTabActive() {
      return asText(this.getAgentActiveTopTab().kind) === 'ppt_planning'
    },
    getAgentActivePptPlanningTab() {
      const tabs = this.ensureAgentTabs(false)
      const activeId = asText(tabs.activeTabId)
      return cloneArray(tabs.pptPlanningTabs).find((item) => asText(item && item.id) === activeId) || null
    },
    getAgentActivePptPlanningState() {
      const tab = this.getAgentActivePptPlanningTab()
      return createPptPlanningState(tab && tab.pptPlanningState)
    },
    buildAgentPptPlanningSystemSourceContext() {
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
      const featureProps = cloneObject(siteSelectionScope.isochroneFeature && siteSelectionScope.isochroneFeature.properties)
      const selectedCenter = normalizePptLngLat(this.selectedPoint)
      const featureCenter = normalizePptLngLat(featureProps.center || featureProps.center_gcj02 || featureProps.centerGcj02)
      const scopeCenter = selectedCenter.length ? selectedCenter : featureCenter
      const timeMin = Number(this.timeHorizon || featureProps.time_min || featureProps.timeMin || 0) || 0
      const radiusM = resolvePptPlanningRadiusMeters(this, featureProps)
      return {
        scope: {
          polygon: cloneArray(siteSelectionScope.polygon),
          drawn_polygon: cloneArray(siteSelectionScope.drawnPolygon),
          isochrone_feature: siteSelectionScope.isochroneFeature || null,
          center: scopeCenter,
          center_coord_type: scopeCenter.length ? 'gcj02' : '',
          radius_m: radiusM,
          time_min: timeMin,
          mode: asText(this.transportMode),
        },
        panelPayloads,
        summaryPack: cloneObject(panelPayloads.summary_pack || panelPayloads.summaryPack),
        summaryReady,
        taskResults,
        sourceDetails: {
          scope: this.timeHorizon ? `${Number(this.timeHorizon)} 分钟范围` : '',
          center: scopeCenter.length ? `${scopeCenter[0].toFixed(4)}, ${scopeCenter[1].toFixed(4)}` : '',
          summary: summaryReady ? '已生成' : '',
          poi_fetch: poiTotal ? `POI ${poiTotal} 条` : '',
          poi_h3_grid: h3Count ? `H3 ${h3Count} 个` : '',
          population: taskResults.population ? '已生成' : '',
          nightlight: taskResults.nightlight ? '已生成' : '',
          road_syntax: taskResults.road_syntax ? '已生成' : '',
        },
      }
    },
    getAgentPptPlanningStateWithSystemSources() {
      const state = this.getAgentActivePptPlanningState()
      const context = this.buildAgentPptPlanningApiContext()
      const areaId = asText(context.areaId || context.area_id)
      const previousById = new Map(cloneArray(state.sources).map((item) => [asText(item.id), item]))
      const systemSources = createPptSystemSources(this.buildAgentPptPlanningSystemSourceContext()).map((source) => {
        const previous = previousById.get(asText(source.id))
        if (
          previous
          && isReadySource(previous)
          && asText(previous.meta && previous.meta.sourceKind) === 'system'
          && areaId
          && asText(previous.meta && previous.meta.areaId) === areaId
        ) {
          return previous
        }
        return source
      })
      return this.getAgentPptPlanningStateWithPackagePlaceholders(mergePptPlanningSources(state, systemSources), areaId)
    },
    getAgentPptPlanningStateWithPackagePlaceholders(state = {}, areaId = '') {
      const normalized = createPptPlanningState(state)
      const normalizedAreaId = asText(areaId || (this.buildAgentPptPlanningApiContext && this.buildAgentPptPlanningApiContext().areaId))
      const activeKeys = this.agentPptPlanningAutoPackageKeys || {}
      const placeholders = PPT_AUTO_PACKAGE_DEFINITIONS
        .filter((definition) => !hasPptEvidencePackage(normalized, normalizedAreaId, definition))
        .map((definition) => {
          const packageKey = getPptEvidencePackageKey(normalizedAreaId, definition)
          const generating = !!(packageKey && activeKeys[packageKey])
          return {
            id: `package-placeholder:${definition.key}`,
            type: 'package',
            title: definition.title,
            status: generating ? 'generating' : 'pending',
            selected: false,
            meta: {
              label: generating ? '整理中' : '待生成',
              sourceKind: 'package-placeholder',
              packagePlaceholder: true,
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
      if (asText(activeTab.kind) !== 'ppt_planning') return
      const nextPptPlanningTabs = cloneArray(tabs.pptPlanningTabs).map((item) => {
        if (item.id !== activeTab.id || item.readonly) return item
        return {
          ...item,
          pptPlanningState: this.getAgentPptPlanningStateWithSystemSources(),
        }
      })
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), iterationChangeTabs: cloneArray(tabs.iterationChangeTabs), siteSelectionTabs: cloneArray(tabs.siteSelectionTabs), pptPlanningTabs: nextPptPlanningTabs, deepAnalysisTabs: cloneArray(tabs.deepAnalysisTabs), followupTabs: cloneArray(tabs.followupTabs) }
      this.syncCurrentAgentSession()
    },
    async refreshAgentActivePptPlanningDataSources(options = {}) {
      const context = this.buildAgentPptPlanningApiContext()
      const areaId = asText(context.areaId || context.area_id)
      const activeTab = this.getAgentActiveTopTab()
      const activeTabId = asText(activeTab && activeTab.id)
      if (!areaId || asText(activeTab && activeTab.kind) !== 'ppt_planning') return
      try {
        const backendSources = await this.requestAgentPptPlanningDataSources(areaId)
        const tabs = this.ensureAgentTabs(true)
        if (asText(tabs.activeTabId) !== activeTabId) return
        const nextSources = cloneArray(backendSources).map((source) => normalizeBackendPptDataSource(source, areaId))
        this.updateAgentActivePptPlanningState(this.getAgentPptPlanningStateWithPackagePlaceholders(
          mergePptPlanningSources(this.getAgentActivePptPlanningState(), nextSources),
          areaId,
        ))
        if (options.autoPackage !== false) {
          await this.autoCreateAgentPptPlanningPoiEvidencePackage({ areaId })
          await this.autoCreateAgentPptPlanningNightlifePoiPackage({ areaId })
          await this.autoCreateAgentPptPlanningRoadCarrierPackage({ areaId })
        }
      } catch (error) {
        this.updateAgentActivePptPlanningState(setPptGenerationError(this.getAgentPptPlanningStateWithSystemSources(), error && error.message, 'source_refresh'))
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
    getAgentPptPlanningSlides() {
      return cloneArray((this.getAgentActivePptPlanningState().deckBrief || {}).slides)
    },
    getAgentPptPlanningGenerationError() {
      return asText(this.getAgentActivePptPlanningState().generationError)
    },
    getAgentPptPlanningGenerationErrorSource() {
      return asText(this.getAgentActivePptPlanningState().generationErrorSource)
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
    isAgentPptPlanningSourceGrouping() {
      return !!this.getAgentActivePptPlanningState().sourceGrouping
    },
    getAgentPptPlanningSourceSummary() {
      return getPptSourceSummary(this.getAgentPptPlanningStateWithSystemSources())
    },
    getAgentPptPlanningActiveSlide() {
      return getActiveDeckSlideBrief(this.getAgentActivePptPlanningState()) || {}
    },
    isAgentPptPlanningSlideActive(slideId = '') {
      return asText(this.getAgentActivePptPlanningState().selectedSlideId) === asText(slideId)
    },
    updateAgentActivePptPlanningState(nextState = {}) {
      const tabs = this.ensureAgentTabs(true)
      const activeTab = this.getAgentActiveTopTab()
      if (asText(activeTab.kind) !== 'ppt_planning') return
      let changed = false
      const nextPptPlanningTabs = cloneArray(tabs.pptPlanningTabs).map((item) => {
        if (item.id !== activeTab.id || item.readonly) return item
        changed = true
        return {
          ...item,
          pptPlanningState: createPptPlanningState(nextState),
        }
      })
      if (!changed) return
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), iterationChangeTabs: cloneArray(tabs.iterationChangeTabs), siteSelectionTabs: cloneArray(tabs.siteSelectionTabs), pptPlanningTabs: nextPptPlanningTabs, deepAnalysisTabs: cloneArray(tabs.deepAnalysisTabs), followupTabs: cloneArray(tabs.followupTabs) }
      this.syncCurrentAgentSession()
    },
    toggleAgentPptPlanningSource(sourceId = '') {
      this.updateAgentActivePptPlanningState(togglePptSourceSelection(this.getAgentPptPlanningStateWithSystemSources(), sourceId))
    },
    toggleAgentPptPlanningSourceGroupCollapsed(groupId = '') {
      this.updateAgentActivePptPlanningState(togglePptSourceGroupCollapsed(this.getAgentPptPlanningStateWithSystemSources(), groupId))
    },
    setAgentPptPlanningSourceGroupSelected(groupId = '', selected = true) {
      this.updateAgentActivePptPlanningState(setPptSourceGroupSelected(this.getAgentPptPlanningStateWithSystemSources(), groupId, selected))
    },
    moveAgentPptPlanningSourceToGroup(sourceId = '', groupId = '') {
      this.updateAgentActivePptPlanningState(movePptSourceToGroup(this.getAgentPptPlanningStateWithSystemSources(), sourceId, groupId))
    },
    renameAgentPptPlanningSource(sourceId = '', title = '') {
      this.updateAgentActivePptPlanningState(renamePptSource(this.getAgentPptPlanningStateWithSystemSources(), sourceId, title))
    },
    removeAgentPptPlanningSource(sourceId = '') {
      this.updateAgentActivePptPlanningState(removePptSource(this.getAgentPptPlanningStateWithSystemSources(), sourceId))
    },
    renameAgentPptPlanningSourceGroup(groupId = '', title = '') {
      this.updateAgentActivePptPlanningState(renamePptSourceGroup(this.getAgentPptPlanningStateWithSystemSources(), groupId, title))
    },
    setAgentPptPlanningSourceGroupEmoji(groupId = '', emoji = '') {
      this.updateAgentActivePptPlanningState(setPptSourceGroupEmoji(this.getAgentPptPlanningStateWithSystemSources(), groupId, emoji))
    },
    removeAgentPptPlanningSourceGroup(groupId = '') {
      this.updateAgentActivePptPlanningState(removePptSourceGroup(this.getAgentPptPlanningStateWithSystemSources(), groupId))
    },
    toggleAllAgentPptPlanningSources() {
      const summary = this.getAgentPptPlanningSourceSummary()
      this.updateAgentActivePptPlanningState(setAllPptSourcesSelected(this.getAgentPptPlanningStateWithSystemSources(), summary.selected < summary.ready))
    },
    updateAgentPptPlanningSpecField(field = '', value = '') {
      this.updateAgentActivePptPlanningState(setPptSpecField(this.getAgentPptPlanningStateWithSystemSources(), field, value))
    },
    openAgentPptPlanningRevisionTarget(type = '', target = {}) {
      this.updateAgentActivePptPlanningState(setPptActiveRevisionTarget(this.getAgentPptPlanningStateWithSystemSources(), { ...target, type }))
    },
    closeAgentPptPlanningRevisionTarget() {
      this.updateAgentActivePptPlanningState(setPptActiveRevisionTarget(this.getAgentActivePptPlanningState(), {}))
    },
    updateAgentPptPlanningRevisionDraft(type = '', field = '', value = '') {
      this.updateAgentActivePptPlanningState(setPptRevisionDraftField(this.getAgentActivePptPlanningState(), type, field, value))
    },
    saveAgentPptPlanningRevision(type = '') {
      const state = this.getAgentActivePptPlanningState()
      const target = cloneObject(state.activeRevisionTarget)
      if (asText(type) === 'directive') {
        const draft = cloneObject(state.directiveRevisionDraft)
        const requiredSources = asText(draft.requiredSources)
          .split(/[,，\n]/)
          .map((item) => asText(item))
          .filter(Boolean)
        this.updateAgentActivePptPlanningState(applyDeckBriefSlideRevision(state, {
          index: Number(target.index || target.pageNo || 0) || 0,
          title: asText(draft.title),
          purpose: asText(draft.purpose),
          keyMessage: asText(draft.keyMessage),
          visualPlan: asText(draft.visualPlan),
          requiredSources,
          speakerNotes: asText(draft.speakerNotes),
        }))
        return
      }
      const draft = cloneObject(state.outlineRevisionDraft)
      this.updateAgentActivePptPlanningState(applyPptOutlineSectionRevision(state, {
        id: asText(target.id),
        pageNo: Number(target.pageNo || 0) || 0,
        theme: asText(draft.theme),
        purpose: asText(draft.purpose),
      }))
    },
    async regenerateAgentPptPlanningRevision(type = '') {
      const state = this.getAgentPptPlanningStateWithSystemSources()
      const target = cloneObject(state.activeRevisionTarget)
      const normalizedType = asText(type)
      const draft = normalizedType === 'directive' ? cloneObject(state.directiveRevisionDraft) : cloneObject(state.outlineRevisionDraft)
      const revisionNote = asText(draft.revisionNote)
      if (!target.type || !revisionNote) return
      this.updateAgentActivePptPlanningState(setPptRevisionGeneratingTarget(state, target))
      try {
        const context = this.buildAgentPptPlanningApiContext()
        if (normalizedType === 'directive') {
          const response = await this.requestAgentPptPlanningDirectiveSlide(buildDeckBriefSlidePayload(state, target, revisionNote, context))
          this.updateAgentActivePptPlanningState(applyDeckBriefSlideRevision(this.getAgentActivePptPlanningState(), response))
          return
        }
        const response = await this.requestAgentPptPlanningOutlineSection(buildPptOutlineSectionPayload(state, target, revisionNote, context))
        this.updateAgentActivePptPlanningState(applyPptOutlineSectionRevision(this.getAgentActivePptPlanningState(), response))
      } catch (error) {
        this.updateAgentActivePptPlanningState(setPptGenerationError(this.getAgentActivePptPlanningState(), error && error.message, normalizedType === 'directive' ? 'directive' : 'outline'))
      }
    },
    undoAgentPptPlanningRevision(type = '', target = {}) {
      this.updateAgentActivePptPlanningState(undoPptSectionRevision(this.getAgentActivePptPlanningState(), type, target))
    },
    hasAgentPptPlanningRevisionSnapshot(type = '', target = {}) {
      const state = this.getAgentActivePptPlanningState()
      const key = getPptRevisionKey(type, target)
      return !!(key && state.revisionSnapshots && state.revisionSnapshots[key])
    },
    isAgentPptPlanningDirectivePageStale(pageNo = 0) {
      return isPptDirectivePageStale(this.getAgentActivePptPlanningState(), pageNo)
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
        analysisContext: this.buildAgentPptPlanningSystemSourceContext(),
      }
    },
    requestAgentPptPlanningOutline(payload = {}) {
      return generatePptSpec(payload)
    },
    requestAgentPptPlanningOutlineSection(payload = {}) {
      return regeneratePptSpecSection(payload)
    },
    requestAgentPptPlanningDirective(payload = {}) {
      return generateDeckBrief(payload)
    },
    requestAgentPptPlanningDirectiveSlide(payload = {}) {
      return regenerateDeckBriefSlide(payload)
    },
    requestAgentPptPlanningDataSources(areaId = '') {
      return listPptDataSources(areaId)
    },
    requestAgentPptPlanningDataPackage(payload = {}) {
      return createPptDataPackage(payload)
    },
    requestAgentPptSourceGroupClassification(payload = {}) {
      return classifyPptSourceGroups(payload)
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
          analysis_context: cloneObject(context.analysisContext || context.analysis_context),
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
        || state.dataPackageGenerating
        || sourceIds.some((sourceId) => !isReadySource(sourcesById.get(sourceId)))
        || hasPptEvidencePackage(state, areaId, packageOptions)
      ) return
      this.agentPptPlanningAutoPackageKeys = this.agentPptPlanningAutoPackageKeys || {}
      if (packageKey && this.agentPptPlanningAutoPackageKeys[packageKey]) return
      if (packageKey) this.agentPptPlanningAutoPackageKeys[packageKey] = true
      this.updateAgentActivePptPlanningState(this.getAgentPptPlanningStateWithPackagePlaceholders(
        setPptDataPackageGenerating(state, true),
        areaId,
      ))
      try {
        const spatialPayload = buildPptDataPackageSpatialPayload(context.analysisContext || context.analysis_context)
        const response = await this.requestAgentPptPlanningDataPackage({
          area_id: areaId,
          source_ids: sourceIds,
          package_mode: packageMode,
          intent,
          query: '',
          limit: Number(options.limit || 50) || 50,
          ...spatialPayload,
        })
        this.updateAgentActivePptPlanningState(addPptDataPackageSource(
          this.getAgentPptPlanningStateWithSystemSources(),
          attachPptDataPackageRuntimeMeta(response, areaId, { autoGenerated: true, packageVersion }),
        ))
      } catch (error) {
        this.updateAgentActivePptPlanningState(setPptGenerationError(this.getAgentPptPlanningStateWithSystemSources(), error && error.message, 'data_package'))
      } finally {
        if (packageKey && this.agentPptPlanningAutoPackageKeys) {
          delete this.agentPptPlanningAutoPackageKeys[packageKey]
        }
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
        const spatialPayload = buildPptDataPackageSpatialPayload(context.analysisContext || context.analysis_context)
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
    async generateAgentPptPlanningOutline() {
      const state = this.getAgentPptPlanningStateWithSystemSources()
      if (!getPptSourceSummary(state).selected) return
      if (getPendingPptPackageSources(state).length) return
      this.updateAgentActivePptPlanningState(setPptOutlineGenerating(state))
      try {
        const response = await this.requestAgentPptPlanningOutline(buildPptSpecPayload(state, this.buildAgentPptPlanningApiContext()))
        this.updateAgentActivePptPlanningState(applyPptSpecResponse(this.getAgentPptPlanningStateWithSystemSources(), response))
      } catch (error) {
        this.updateAgentActivePptPlanningState(setPptGenerationError(this.getAgentPptPlanningStateWithSystemSources(), error && error.message, 'outline'))
      }
    },
    async generateAgentPptPlanningDirective() {
      const state = this.getAgentPptPlanningStateWithSystemSources()
      if (!cloneArray(state.outline).length) return
      this.updateAgentActivePptPlanningState(setPptDirectiveGenerating(state))
      try {
        const response = await this.requestAgentPptPlanningDirective(buildDeckBriefPayload(state, this.buildAgentPptPlanningApiContext()))
        this.updateAgentActivePptPlanningState(applyDeckBriefResponse(this.getAgentPptPlanningStateWithSystemSources(), response))
      } catch (error) {
        this.updateAgentActivePptPlanningState(setPptGenerationError(this.getAgentPptPlanningStateWithSystemSources(), error && error.message, 'directive'))
      }
    },
    confirmAgentPptPlanningStepReset(message = '') {
      if (typeof this.confirmPptPlanningStepReset === 'function') {
        return this.confirmPptPlanningStepReset(message)
      }
      if (typeof window === 'undefined' || typeof window.confirm !== 'function') return true
      return window.confirm(message)
    },
    async regenerateAgentPptPlanningOutlineWithConfirm() {
      const state = this.getAgentPptPlanningStateWithSystemSources()
      const hasOutline = cloneArray(state.outline).length > 0
      const hasDirective = asText(state.currentStep) === 'directive_draft' && cloneArray((state.deckBrief || {}).slides).length > 0
      if (!hasOutline && !hasDirective) return
      if (!getPptSourceSummary(state).selected || getPendingPptPackageSources(state).length) return
      const confirmed = await this.confirmAgentPptPlanningStepReset('重新生成目录会清空旧目录和旧指令文件，确认继续？')
      if (!confirmed) return
      this.updateAgentActivePptPlanningState(resetPptPlanningToMaterials(this.getAgentPptPlanningStateWithSystemSources()))
      await this.generateAgentPptPlanningOutline()
    },
    async regenerateAgentPptPlanningDirectiveWithConfirm() {
      const state = this.getAgentPptPlanningStateWithSystemSources()
      const hasOutline = cloneArray(state.outline).length > 0
      const hasDirective = asText(state.currentStep) === 'directive_draft' && cloneArray((state.deckBrief || {}).slides).length > 0
      if (!hasOutline || !hasDirective) return
      const confirmed = await this.confirmAgentPptPlanningStepReset('重新生成指令文件会清空旧指令文件，但保留当前目录，确认继续？')
      if (!confirmed) return
      this.updateAgentActivePptPlanningState(resetPptPlanningToOutlineReady(this.getAgentPptPlanningStateWithSystemSources()))
      await this.generateAgentPptPlanningDirective()
    },
    selectAgentPptPlanningSlide(slideId = '') {
      this.updateAgentActivePptPlanningState(selectDeckSlideBrief(this.getAgentActivePptPlanningState(), slideId))
    },
    captureAgentActivePptPlanningTabState() {
      const tabs = this.ensureAgentTabs(true)
      const activeTab = this.getAgentActiveTopTab()
      if (asText(activeTab.kind) !== 'ppt_planning') return
      const nextPptPlanningTabs = cloneArray(tabs.pptPlanningTabs).map((item) => {
        if (item.id !== activeTab.id || item.readonly) return item
        return {
          ...item,
          panelPayloads: cloneObject(this.agentPanelPayloads),
          pptPlanningState: createPptPlanningState(item.pptPlanningState),
        }
      })
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), iterationChangeTabs: cloneArray(tabs.iterationChangeTabs), siteSelectionTabs: cloneArray(tabs.siteSelectionTabs), pptPlanningTabs: nextPptPlanningTabs, deepAnalysisTabs: cloneArray(tabs.deepAnalysisTabs), followupTabs: cloneArray(tabs.followupTabs) }
    },
    createAgentPptPlanningTab(options = {}) {
      const tabs = this.ensureAgentTabs(true)
      this.captureAgentActiveSummaryTabState()
      this.captureAgentActiveSiteSelectionTabState()
      this.captureAgentActivePptPlanningTabState()
      this.captureAgentActiveDeepAnalysisTabState()
      this.captureAgentActiveFollowupTabState()
      const tabId = this.createAgentPptPlanningViewId()
      const tab = {
        id: tabId,
        kind: 'ppt_planning',
        title: this.formatAgentTabTitle('ppt_planning', options.title),
        source: asText(options.source) || 'draft',
        sessionId: asText(options.sessionId),
        readonly: !!options.readonly,
        createdAt: new Date().toISOString(),
        panelPayloads: cloneObject(this.agentPanelPayloads),
        pptPlanningState: mergePptPlanningSources(createPptPlanningState(options.pptPlanningState), createPptSystemSources(this.buildAgentPptPlanningSystemSourceContext())),
      }
      tabs.pptPlanningTabs = [...cloneArray(tabs.pptPlanningTabs), tab]
      tabs.activeTabId = tabId
      this.agentTabs = { ...tabs, summaryTabs: cloneArray(tabs.summaryTabs), iterationChangeTabs: cloneArray(tabs.iterationChangeTabs), siteSelectionTabs: cloneArray(tabs.siteSelectionTabs), pptPlanningTabs: cloneArray(tabs.pptPlanningTabs), deepAnalysisTabs: cloneArray(tabs.deepAnalysisTabs), followupTabs: cloneArray(tabs.followupTabs) }
      this.syncActiveAgentRuntimeView(this.activeAgentSessionId)
      this.syncCurrentAgentSession()
      this.refreshAgentActivePptPlanningDataSources()
      return tabId
    },
  }
}
