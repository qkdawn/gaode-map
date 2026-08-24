import {
  asText,
  clampText,
  cloneArray,
  cloneObject,
  cloneRecordMap,
  consumeSseStream,
  createAgentRunState,
  deriveAgentSessionPreview,
  deriveAgentSessionTitle,
  normalizeAgentThinkingItem,
  upsertThinkingItemInList,
} from './normalizers.js'
import { ANALYSIS_WORKSPACE_TAB_KIND } from './workspace-kinds.js'
import { postConversationTurnStream } from './conversation-request.js'
import {
  buildAgentAnalysisSnapshot as buildAgentAnalysisSnapshotPayload,
  buildAgentPoiGridEvidence as buildAgentPoiGridEvidencePayload,
  buildAgentPoiH3Evidence as buildAgentPoiH3EvidencePayload,
  buildAgentPopulationGridEvidence as buildAgentPopulationGridEvidencePayload,
  buildAgentSharedGridEvidence as buildAgentSharedGridEvidencePayload,
} from './analysis-snapshot-evidence.js'

function createAgentRuntimeMethods() {
  return {
    normalizeAgentSiteSelectionScope() {
      const normalizeRing = (raw) => {
        if (!Array.isArray(raw) || !raw.length) return []
        if (typeof this._closePolygonRing === 'function' && typeof this.normalizePath === 'function') {
          const ring = this._closePolygonRing(this.normalizePath(raw, 3, 'agent.site_selection.scope'))
          return Array.isArray(ring) && ring.length >= 4 ? ring : []
        }
        const points = raw
          .filter((pt) => Array.isArray(pt) && pt.length >= 2)
          .map((pt) => [Number(pt[0]), Number(pt[1])])
          .filter((pt) => Number.isFinite(pt[0]) && Number.isFinite(pt[1]))
        if (points.length < 3) return []
        const first = points[0]
        const last = points[points.length - 1]
        if (Math.abs(first[0] - last[0]) > 1e-8 || Math.abs(first[1] - last[1]) > 1e-8) {
          points.push([first[0], first[1]])
        }
        return points.length >= 4 ? points : []
      }
      const normalizePayload = (raw) => {
        if (!Array.isArray(raw) || !raw.length) return []
        const direct = normalizeRing(raw)
        if (direct.length) return direct
        const rings = []
        raw.forEach((item) => {
          const ring = normalizeRing(item)
          if (ring.length) rings.push(ring)
          else if (Array.isArray(item) && Array.isArray(item[0])) {
            const outer = normalizeRing(item[0])
            if (outer.length) rings.push(outer)
          }
        })
        return rings.length === 1 ? rings[0] : rings
      }
      const polygon = typeof this.getIsochronePolygonPayload === 'function'
        ? normalizePayload(this.getIsochronePolygonPayload())
        : []
      const drawnPolygon = typeof this.getDrawnScopePolygonPoints === 'function'
        ? normalizeRing(this.getDrawnScopePolygonPoints())
        : []
      const isochroneFeature = typeof this._normalizeIsochroneFeatureForExport === 'function'
        ? this._normalizeIsochroneFeatureForExport()
        : null
      let featurePolygon = []
      const geometry = isochroneFeature && isochroneFeature.geometry ? isochroneFeature.geometry : null
      if (geometry && Array.isArray(geometry.coordinates)) {
        featurePolygon = normalizePayload(geometry.type === 'Polygon' ? geometry.coordinates[0] : geometry.coordinates)
      }
      const historyPolygon = normalizePayload(this.currentHistoryPolygon || this.currentHistoryPolygonGcj02 || [])
      const activePolygon = polygon.length
        ? polygon
        : (drawnPolygon.length ? drawnPolygon : (featurePolygon.length ? featurePolygon : historyPolygon))
      return {
        hasScope: Array.isArray(activePolygon) && activePolygon.length > 0,
        polygon: activePolygon,
        drawnPolygon,
        isochroneFeature,
      }
    },
    getAgentRunState(sessionId = '') {
      const nextId = this.getActiveAgentSessionId(sessionId)
      if (!nextId) return null
      const registry = cloneRecordMap(this.agentRunRegistry)
      const current = registry[nextId]
      return current ? createAgentRunState(current) : null
    },
    setAgentRunState(sessionId = '', patch = {}) {
      const nextId = asText(sessionId)
      if (!nextId) return null
      const registry = cloneRecordMap(this.agentRunRegistry)
      const current = registry[nextId] ? createAgentRunState(registry[nextId]) : createAgentRunState()
      const nextState = createAgentRunState({ ...current, ...patch })
      this.agentRunRegistry = {
        ...registry,
        [nextId]: nextState,
      }
      if (nextId === asText(this.activeAgentSessionId)) {
        this.syncActiveAgentRuntimeView(nextId)
      }
      return nextState
    },
    clearAgentRunState(sessionId = '', options = {}) {
      const nextId = asText(sessionId)
      if (!nextId) return
      const registry = cloneRecordMap(this.agentRunRegistry)
      const current = registry[nextId] ? createAgentRunState(registry[nextId]) : null
      if (current && current.elapsedTimer && typeof window !== 'undefined' && typeof window.clearInterval === 'function') {
        window.clearInterval(current.elapsedTimer)
      }
      if (current && options.abort && current.abortController) {
        try {
          current.abortController.abort()
        } catch (_) {
          // Ignore abort errors from already-settled controllers.
        }
      }
      delete registry[nextId]
      this.agentRunRegistry = registry
      if (nextId === asText(this.activeAgentSessionId)) {
        this.syncActiveAgentRuntimeView(nextId)
      }
    },
    destroyAllAgentRuns() {
      Object.keys(cloneRecordMap(this.agentRunRegistry)).forEach((sessionId) => {
        this.clearAgentRunState(sessionId, { abort: true })
      })
      this.agentRunRegistry = {}
      this.agentTurnAbortController = null
    },
    isAgentSessionRunning(sessionId = '') {
      const runState = this.getAgentRunState(sessionId)
      return !!(runState && runState.loading)
    },
    getRunningAgentSessionCount() {
      return Object.values(cloneRecordMap(this.agentRunRegistry))
        .map((entry) => createAgentRunState(entry))
        .filter((entry) => entry.loading)
        .length
    },
    getAgentRunningBadgeText() {
      const count = this.getRunningAgentSessionCount()
      if (count <= 0) return ''
      return count > 1 ? String(count) : '运行中'
    },
    syncActiveAgentRuntimeView(sessionId = '') {
      const nextId = this.getActiveAgentSessionId(sessionId)
      const runState = nextId ? this.getAgentRunState(nextId) : null
      const session = nextId ? this.findAgentSession(nextId) : null
      this.agentLoading = !!(runState && runState.loading)
      this.agentStreamState = asText((runState && runState.streamState) || 'idle') || 'idle'
      this.agentStreamStartedAt = Number((runState && runState.startedAt) || 0) || 0
      this.agentStreamElapsedTick = Number((runState && (runState.elapsedTick || runState.startedAt)) || 0) || 0
      this.agentStreamElapsedTimer = (runState && runState.elapsedTimer) || null
      this.agentStreamingMessageId = asText(runState && runState.streamingMessageId)
      this.agentTurnAbortController = (runState && runState.abortController) || null
      this.agentPanelPayloads = cloneObject(session && session.panelPayloads)
      this.agentActivityItems = cloneArray(session && session.activityItems)
    },
    resetAgentStreamingState(sessionId = '') {
      const targetSessionId = this.getActiveAgentSessionId(sessionId)
      if (!targetSessionId) return
      this.setAgentRunState(targetSessionId, {
        loading: false,
        streamState: 'idle',
        startedAt: 0,
        elapsedTick: 0,
        streamingMessageId: '',
      })
    },
    startAgentThinkingTimer(sessionId = '') {
      const targetSessionId = this.getActiveAgentSessionId(sessionId)
      if (!targetSessionId) return
      const runState = this.getAgentRunState(targetSessionId) || createAgentRunState()
      if (runState.elapsedTimer && typeof window !== 'undefined' && typeof window.clearInterval === 'function') {
        window.clearInterval(runState.elapsedTimer)
      }
      const startedAt = Date.now()
      const patch = { startedAt, elapsedTick: startedAt }
      if (typeof window !== 'undefined' && typeof window.setInterval === 'function') {
        patch.elapsedTimer = window.setInterval(() => {
          const current = this.getAgentRunState(targetSessionId)
          if (!current || !current.loading) return
          this.setAgentRunState(targetSessionId, { elapsedTick: Date.now() })
        }, 1000)
      }
      this.setAgentRunState(targetSessionId, patch)
    },
    stopAgentThinkingTimer(sessionId = '') {
      const targetSessionId = this.getActiveAgentSessionId(sessionId)
      const runState = targetSessionId ? this.getAgentRunState(targetSessionId) : null
      if (runState && runState.elapsedTimer && typeof window !== 'undefined' && typeof window.clearInterval === 'function') {
        window.clearInterval(runState.elapsedTimer)
      }
      if (runState) this.setAgentRunState(targetSessionId, { elapsedTimer: null })
    },
    getAgentReportThreadElement() {
      return (this.$refs && this.$refs.agentReportThreadBody) || null
    },
    getAgentReportThreadDistanceToBottom() {
      const body = this.getAgentReportThreadElement()
      if (!body) return 0
      return Math.max(0, body.scrollHeight - body.scrollTop - body.clientHeight)
    },
    isAgentReportThreadNearBottom(thresholdPx = 24) {
      return this.getAgentReportThreadDistanceToBottom() <= thresholdPx
    },
    setAgentAutoScrollLock(locked = false, options = {}) {
      const targetSessionId = this.getActiveAgentSessionId(options && options.sessionId)
      if (!targetSessionId) return
      const patch = {
        autoScrollLocked: !!locked,
      }
      if (Object.prototype.hasOwnProperty.call(options || {}, 'sticky')) {
        patch.autoScrollSticky = !!options.sticky
      }
      if (Object.prototype.hasOwnProperty.call(options || {}, 'thresholdPx')) {
        patch.autoScrollThresholdPx = Number(options.thresholdPx || 0) || 24
      }
      this.setAgentRunState(targetSessionId, patch)
    },
    onAgentInnerScrollIntent() {
      const targetSessionId = this.getActiveAgentSessionId()
      if (!targetSessionId || !this.isAgentSessionRunning(targetSessionId)) return
      this.setAgentAutoScrollLock(true, { sessionId: targetSessionId })
    },
    onAgentReportThreadWheel() {
      const targetSessionId = this.getActiveAgentSessionId()
      if (!targetSessionId || !this.isAgentSessionRunning(targetSessionId)) return
      const nearBottom = this.isAgentReportThreadNearBottom()
      this.setAgentAutoScrollLock(!nearBottom, { sessionId: targetSessionId, sticky: nearBottom })
    },
    onAgentReportThreadTouchMove() {
      this.onAgentReportThreadWheel()
    },
    onAgentReportThreadScroll() {
      if (Date.now() < Number(this.agentProgrammaticScrollUntil || 0)) return
      const targetSessionId = this.getActiveAgentSessionId()
      if (!targetSessionId || !this.isAgentSessionRunning(targetSessionId)) return
      const nearBottom = this.isAgentReportThreadNearBottom()
      this.setAgentAutoScrollLock(!nearBottom, { sessionId: targetSessionId, sticky: nearBottom })
    },
    scrollAgentThreadToLatest(options = {}) {
      const body = this.getAgentReportThreadElement()
      if (!body) return
      const behavior = options.behavior || 'smooth'
      this.agentProgrammaticScrollUntil = Date.now() + 120
      body.scrollTo({
        top: body.scrollHeight,
        behavior,
      })
    },
    maybeAutoScrollAgentThread(options = {}) {
      const targetSessionId = this.getActiveAgentSessionId(options && options.sessionId)
      const force = !!(options && options.force)
      if (!targetSessionId) return
      const runState = this.getAgentRunState(targetSessionId)
      if (!runState) {
        if (force) {
          this.scrollAgentThreadToLatest({ behavior: 'auto' })
        }
        return
      }
      if (!force && runState.autoScrollLocked && !runState.autoScrollSticky) return
      this.scrollAgentThreadToLatest({ behavior: force ? 'auto' : 'smooth' })
    },
    getAgentThinkingElapsedLabel() {
      const startedAt = Number(this.agentStreamStartedAt || 0)
      if (!startedAt) return ''
      const tick = Number(this.agentStreamElapsedTick || startedAt)
      const seconds = Math.max(1, Math.floor((tick - startedAt) / 1000))
      return `${seconds}s`
    },
    getCurrentAgentHistoryId() {
      return asText(this.currentHistoryRecordId)
    },
    buildAgentPoiGridEvidence() {
      return buildAgentPoiGridEvidencePayload(this)
    },
    buildAgentPoiH3Evidence() {
      return buildAgentPoiH3EvidencePayload(this)
    },
    buildAgentPopulationGridEvidence() {
      return buildAgentPopulationGridEvidencePayload(this)
    },
    buildAgentSharedGridEvidence() {
      return buildAgentSharedGridEvidencePayload(this)
    },
    buildAgentPlaceAnchors() {
      const pois = Array.isArray(this.allPoisDetails) ? this.allPoisDetails : []
      const keywordGroups = [
        { key: 'campus_culture', label: '校园与文教', tokens: ['大学', '学院', '师范', '中学', '小学', '学校', '图书馆', '博物馆', '美术馆', '文化', '艺术'] },
        { key: 'landscape', label: '山水与公共空间', tokens: ['山', '湖', '江', '河', '溪', '洲', '岛', '公园', '绿地', '景区', '风景', '广场'] },
        { key: 'commercial_life', label: '商业与生活服务', tokens: ['商场', '广场', '超市', '市场', '餐饮', '酒店', '民宿', '咖啡', '茶', '购物'] },
        { key: 'transport_corridor', label: '道路与交通节点', tokens: ['路', '街', '大道', '桥', '地铁', '公交', '车站', '码头', '隧道'] },
      ]
      const seen = new Set()
      const groups = keywordGroups.map((group) => ({ key: group.key, label: group.label, items: [] }))
      const pushAnchor = (groupIndex, poi) => {
        if (!poi || typeof poi !== 'object') return
        const name = asText(poi.name || poi.title)
        if (!name || seen.has(name)) return
        const anchor = {
          name,
          type: asText(poi.type || poi.type_label || poi.category || poi.category_label),
          address: asText(poi.address || poi.adname || poi.district),
          lng: Number.isFinite(Number(poi.lng)) ? Number(poi.lng) : (Array.isArray(poi.location) ? Number(poi.location[0]) : null),
          lat: Number.isFinite(Number(poi.lat)) ? Number(poi.lat) : (Array.isArray(poi.location) ? Number(poi.location[1]) : null),
        }
        seen.add(name)
        groups[groupIndex].items.push(anchor)
      }
      pois.forEach((poi) => {
        const haystack = `${asText(poi && (poi.name || poi.title))} ${asText(poi && poi.type)} ${asText(poi && poi.address)}`
        keywordGroups.forEach((group, index) => {
          if (groups[index].items.length >= 10) return
          if (group.tokens.some((token) => haystack.includes(token))) {
            pushAnchor(index, poi)
          }
        })
      })
      if (!seen.size) {
        pois.slice(0, 24).forEach((poi) => pushAnchor(2, poi))
      }
      const compactGroups = groups
        .map((group) => ({ ...group, items: group.items.slice(0, 10) }))
        .filter((group) => group.items.length)
      return {
        source: 'frontend_current_pois',
        rule: '这些是前端从当前 POI 结果中抽取的地名锚点，用于让回答落到具体山水、校园、道路和商业节点；不得据此虚构不存在的地名。',
        groups: compactGroups,
        names: compactGroups.flatMap((group) => group.items.map((item) => item.name)).slice(0, 36),
      }
    },
    buildAgentSpatialAnchors() {
      const pickProps = (value = {}, keys = []) => {
        const props = value && value.properties && typeof value.properties === 'object' ? value.properties : value
        const result = {}
        keys.forEach((key) => {
          if (props && props[key] !== undefined && props[key] !== null && props[key] !== '') result[key] = props[key]
        })
        return result
      }
      const numericValue = (value, keys = []) => {
        const props = value && value.properties && typeof value.properties === 'object' ? value.properties : value
        for (const key of keys) {
          const parsed = Number(props && props[key])
          if (Number.isFinite(parsed)) return parsed
        }
        return -Infinity
      }
      const topRows = (rows = [], keys = [], pickKeys = [], limit = 10) => cloneArray(rows)
        .filter((row) => row && typeof row === 'object')
        .sort((a, b) => numericValue(b, keys) - numericValue(a, keys))
        .slice(0, limit)
        .map((row) => pickProps(row, pickKeys))
        .filter((row) => Object.keys(row).length)

      const h3Features = cloneArray(this.h3AnalysisGridFeatures)
      const roadFeatures = cloneArray(Array.isArray(this.roadSyntaxEdgeFeatures) && this.roadSyntaxEdgeFeatures.length
        ? this.roadSyntaxEdgeFeatures
        : this.roadSyntaxRoadFeatures)
      const roadGridFeatures = cloneArray(this.roadSyntaxGridFeatures)
      const populationCells = cloneArray((this.populationLayer && this.populationLayer.cells) || [])
      const nightlightCells = cloneArray((this.nightlightLayer && this.nightlightLayer.cells) || [])
      const roadMetricTabs = typeof this.roadSyntaxMetricTabs === 'function'
        ? this.roadSyntaxMetricTabs().map((tab) => ({ value: asText(tab && tab.value), label: asText(tab && tab.label) })).filter((tab) => tab.value)
        : []
      const roadMetricKeys = Array.from(new Set(roadFeatures.flatMap((feature) => Object.keys((feature && feature.properties) || {}))))
        .filter((key) => /(connect|control|depth|choice|integration|intelligibility|score|value)/i.test(key))
        .slice(0, 24)
      return {
        selected_point: this.selectedPoint
          ? {
              name: asText(this.selectedPoint.name),
              lng: Number(this.selectedPoint.lng),
              lat: Number(this.selectedPoint.lat),
            }
          : {},
        h3: {
          feature_count: h3Features.length,
          top_cells: topRows(
            h3Features,
            ['poi_count', 'density', 'gi_z_score', 'lisa_z_score', 'value'],
            ['h3_id', 'poi_count', 'density', 'gi_z_score', 'lisa_z_score', 'gap_score', 'label'],
            12,
          ),
        },
        road: {
          feature_count: roadFeatures.length,
          edge_count: roadFeatures.length,
          grid_cell_count: roadGridFeatures.length,
          metric_tabs: roadMetricTabs,
          metric_keys: roadMetricKeys,
          sample_segments: topRows(
            roadFeatures,
            ['integration_score', 'choice_score', 'connectivity_score', 'control_score', 'depth_score', 'value'],
            ['id', 'name', 'road_name', 'integration_score', 'choice_score', 'connectivity_score', 'control_score', 'depth_score', 'intelligibility_score'],
            12,
          ),
          top_grid_cells: topRows(
            roadGridFeatures,
            ['road_integration', 'road_choice', 'road_connectivity', 'road_length_km_per_km2'],
            ['cell_id', 'road_length_km', 'road_length_km_per_km2', 'road_integration', 'road_choice', 'road_connectivity'],
            12,
          ),
        },
        population: {
          cell_count: populationCells.length,
          layer_summary: cloneObject((this.populationLayer && this.populationLayer.summary) || {}),
          top_cells: topRows(
            populationCells,
            ['total_population', 'population', 'density', 'value'],
            ['cell_id', 'total_population', 'population', 'density', 'dominant_age_band_label', 'male_total', 'female_total'],
            12,
          ),
        },
        nightlight: {
          cell_count: nightlightCells.length,
          layer_summary: cloneObject((this.nightlightLayer && this.nightlightLayer.summary) || {}),
          analysis: cloneObject((this.nightlightLayer && this.nightlightLayer.analysis) || {}),
          top_cells: topRows(
            nightlightCells,
            ['radiance', 'mean_radiance', 'value', 'sum_radiance'],
            ['cell_id', 'radiance', 'mean_radiance', 'sum_radiance', 'value', 'class_label'],
            12,
          ),
        },
      }
    },
    buildAgentMapSearchContext() {
      return {
        evidence_version: 'frontend_map_search_context_v1',
        source: 'frontend_current_map_layers',
        rule: '这些结构化空间对象只作为本轮可检索证据源；Agent 必须先 search_analysis_context 再 read_analysis_evidence_node，才能在最终回答中引用具体地名、格子、线段或 cell。',
        place_anchors: this.buildAgentPlaceAnchors(),
        spatial_anchors: this.buildAgentSpatialAnchors(),
      }
    },
    buildAgentAnalysisSnapshot() {
      return buildAgentAnalysisSnapshotPayload(this)
    },
    async patchAgentSessionMetadata(sessionId = '', payload = {}) {
      const nextId = asText(sessionId)
      if (!nextId) {
        throw new Error('missing agent session id')
      }
      const res = await fetch(`/api/v1/analysis/agent/sessions/${encodeURIComponent(nextId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        throw new Error(`/api/v1/analysis/agent/sessions/${nextId} PATCH 失败(${res.status})`)
      }
      const detail = await res.json()
      return this.mergeAgentSessionDetail(detail)
    },
    buildTurnContext(options = {}) {
      const panelKind = asText(options && options.panelKind)
        || (typeof this.getAgentActiveTopTab === 'function' ? asText(this.getAgentActiveTopTab().kind) : '')
        || 'followup'
      const target = (options && options.target) || null
      const rawQuestion = String((options && options.prompt) || this.agentInput || '').trim()
      if (!rawQuestion || this.agentSessionHydrating) return null
      const activeSessionId = this.getActiveAgentSessionId(this.activeAgentSessionId)
      if (this.agentLoading || (activeSessionId && this.isAgentSessionRunning(activeSessionId))) return null
      this.ensureAgentPanelReady()
      if (panelKind !== ANALYSIS_WORKSPACE_TAB_KIND && typeof this.ensureAgentFollowupTabForPrompt === 'function') {
        this.ensureAgentFollowupTabForPrompt(rawQuestion)
      }
      const currentSession = this.syncCurrentAgentSession() || this.readSessionState(this.activeAgentSessionId)
      const targetSessionId = this.getActiveAgentSessionId(currentSession && currentSession.id) || this.createAgentSession().id
      const wasPersisted = !!(currentSession && currentSession.persisted)
      const historyId = this.getCurrentAgentHistoryId()
      const requestAbortController = typeof AbortController !== 'undefined' ? new AbortController() : null
      let baseMessages = cloneArray((currentSession && currentSession.messages) || [])
      if (!baseMessages.length && typeof this.getAgentActiveFollowupTab === 'function') {
        const activeFollowupTab = this.getAgentActiveFollowupTab()
        const threadMessages = cloneArray(activeFollowupTab && activeFollowupTab.thread && activeFollowupTab.thread.messages)
        if (threadMessages.length) {
          baseMessages = threadMessages
        }
      }
      if (!baseMessages.length) {
        baseMessages = cloneArray(this.agentMessages)
      }
      const nextMessages = [...baseMessages, { role: 'user', content: rawQuestion }]
      return {
        question: rawQuestion,
        rawQuestion,
        panelKind,
        target,
        currentSession,
        targetSessionId,
        wasPersisted,
        historyId,
        requestAbortController,
        nextMessages,
      }
    },
    async submitAgentComposer(options = {}) {
      let activeKind = typeof this.getAgentActiveTopTab === 'function'
        ? asText(this.getAgentActiveTopTab().kind)
        : ''
      if (activeKind !== ANALYSIS_WORKSPACE_TAB_KIND) {
        if (typeof this.openAgentPptPlanningFromReport === 'function') {
          this.openAgentPptPlanningFromReport()
          activeKind = typeof this.getAgentActiveTopTab === 'function'
            ? asText(this.getAgentActiveTopTab().kind)
            : ''
        }
        if (activeKind !== ANALYSIS_WORKSPACE_TAB_KIND) {
          this.agentError = '请先进入分析页后再提问。'
          return null
        }
      }
      const panelKind = ANALYSIS_WORKSPACE_TAB_KIND
      return this.submitMainAgentTurn({
        ...options,
        panelKind,
      })
    },
    async consumeTurnStream(res, handler) {
      await consumeSseStream(res, handler)
    },
    getAgentMapInstance() {
      return (this.mapCore && this.mapCore.map) || this.map || null
    },
    getAgentMapViewState() {
      const map = this.getAgentMapInstance()
      if (!map) return null
      const center = typeof map.getCenter === 'function' ? map.getCenter() : null
      const zoom = typeof map.getZoom === 'function' ? map.getZoom() : null
      return {
        center: center ? [Number(center.lng), Number(center.lat)] : null,
        zoom: Number.isFinite(Number(zoom)) ? Number(zoom) : null,
      }
    },
    getAgentVisualLayerState() {
      return {
        activeStep3Panel: asText(this.activeStep3Panel),
        poiSubTab: asText(this.poiSubTab),
        h3StructureFillMode: asText(this.h3StructureFillMode),
        roadSyntaxMainTab: asText(this.roadSyntaxMainTab),
        roadSyntaxMetric: asText(this.roadSyntaxMetric),
        roadSyntaxLastMetricTab: asText(this.roadSyntaxLastMetricTab),
      }
    },
    restoreAgentMapViewState(view = null) {
      const map = this.getAgentMapInstance()
      if (!map || !view || !Array.isArray(view.center)) return
      const center = view.center
      const zoom = Number(view.zoom)
      if (typeof map.setZoomAndCenter === 'function' && Number.isFinite(zoom)) {
        map.setZoomAndCenter(zoom, center)
        return
      }
      if (typeof map.setCenter === 'function') map.setCenter(center)
      if (typeof map.setZoom === 'function' && Number.isFinite(zoom)) map.setZoom(zoom)
    },
    async restoreAgentVisualLayerState(state = null) {
      if (!state || typeof state !== 'object') return
      this.activeStep3Panel = asText(state.activeStep3Panel || this.activeStep3Panel)
      if (Object.prototype.hasOwnProperty.call(state, 'poiSubTab')) this.poiSubTab = asText(state.poiSubTab)
      if (Object.prototype.hasOwnProperty.call(state, 'h3StructureFillMode')) this.h3StructureFillMode = asText(state.h3StructureFillMode || this.h3StructureFillMode)
      if (Object.prototype.hasOwnProperty.call(state, 'roadSyntaxMainTab')) this.roadSyntaxMainTab = asText(state.roadSyntaxMainTab || this.roadSyntaxMainTab)
      if (Object.prototype.hasOwnProperty.call(state, 'roadSyntaxMetric')) this.roadSyntaxMetric = asText(state.roadSyntaxMetric || this.roadSyntaxMetric)
      if (Object.prototype.hasOwnProperty.call(state, 'roadSyntaxLastMetricTab')) this.roadSyntaxLastMetricTab = asText(state.roadSyntaxLastMetricTab || this.roadSyntaxLastMetricTab)
      if (this.activeStep3Panel === 'syntax' && this.roadSyntaxMainTab !== 'params' && typeof this.renderRoadSyntaxByMetric === 'function') {
        await this.renderRoadSyntaxByMetric(this.roadSyntaxMetric || this.roadSyntaxLastMetricTab)
      }
      await this.waitForAgentVisualSnapshotPaint()
    },
    getAgentScopeBounds() {
      const snapshot = this.buildAgentAnalysisSnapshot ? this.buildAgentAnalysisSnapshot() : {}
      const polygon = snapshot && snapshot.scope && Array.isArray(snapshot.scope.polygon) ? snapshot.scope.polygon : []
      return this.computeAgentLngLatBoundsFromCoordinates(polygon)
    },
    computeAgentLngLatBoundsFromCoordinates(source = []) {
      const points = []
      const visit = (value) => {
        if (!Array.isArray(value)) return
        if (value.length >= 2 && Number.isFinite(Number(value[0])) && Number.isFinite(Number(value[1]))) {
          points.push([Number(value[0]), Number(value[1])])
          return
        }
        value.forEach(visit)
      }
      visit(source)
      if (!points.length) return null
      const lngs = points.map((item) => item[0])
      const lats = points.map((item) => item[1])
      return {
        west: Math.min(...lngs),
        south: Math.min(...lats),
        east: Math.max(...lngs),
        north: Math.max(...lats),
      }
    },
    getAgentRoadFeatureBounds() {
      const features = Array.isArray(this.roadSyntaxRoadFeatures) ? this.roadSyntaxRoadFeatures : []
      const coords = []
      features.forEach((feature) => {
        if (feature && feature.geometry && Array.isArray(feature.geometry.coordinates)) {
          coords.push(feature.geometry.coordinates)
        }
      })
      return this.computeAgentLngLatBoundsFromCoordinates(coords)
    },
    async fitAgentMapToBounds(bounds = null) {
      const map = this.getAgentMapInstance()
      if (!map || !bounds || !window.AMap || !AMap.LngLat || !AMap.Bounds) return false
      try {
        const sw = new AMap.LngLat(bounds.west, bounds.south)
        const ne = new AMap.LngLat(bounds.east, bounds.north)
        const amapBounds = new AMap.Bounds(sw, ne)
        if (typeof map.setBounds === 'function') {
          map.setBounds(amapBounds)
        } else if (typeof map.setFitView === 'function') {
          map.setFitView()
          if (typeof map.setCenter === 'function' && amapBounds.getCenter) map.setCenter(amapBounds.getCenter())
        } else {
          return false
        }
        await this.waitForAgentVisualSnapshotPaint()
        return true
      } catch (err) {
        console.warn('fit agent map snapshot bounds failed', err)
        return false
      }
    },
    waitForAgentVisualSnapshotPaint() {
      const waitFrame = () => new Promise((resolve) => {
        if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
          window.requestAnimationFrame(() => resolve())
        } else {
          resolve()
        }
      })
      return waitFrame().then(waitFrame).then(() => this._sleepForExport ? this._sleepForExport(120) : undefined)
    },
    buildAgentVisualSnapshotFingerprint() {
      const snapshot = typeof this.buildAgentAnalysisSnapshot === 'function'
        ? this.buildAgentAnalysisSnapshot()
        : {}
      const summarizeObject = (value = null, keys = []) => {
        const source = value && typeof value === 'object' ? value : {}
        const output = {}
        keys.forEach((key) => {
          const nextValue = source[key]
          if (nextValue !== undefined && nextValue !== null && nextValue !== '') output[key] = nextValue
        })
        return output
      }
      const roadTabs = (typeof this.roadSyntaxMetricTabs === 'function'
        ? cloneArray(this.roadSyntaxMetricTabs())
        : []
      ).map((tab) => asText(tab && tab.value)).filter(Boolean)
      const fingerprint = {
        scope: {
          polygon: cloneArray(snapshot && snapshot.scope && snapshot.scope.polygon),
          bounds: this.getAgentScopeBounds() || {},
        },
        selected_point: summarizeObject(this.selectedPoint, ['name', 'lng', 'lat']),
        poi: {
          count: Array.isArray(this.allPoisDetails) ? this.allPoisDetails.length : 0,
          total: (snapshot && snapshot.poi_summary && snapshot.poi_summary.total) || 0,
        },
        h3: {
          available: !!(this.h3AnalysisSummary || (this.sharedGridMetrics && Object.keys(this.sharedGridMetrics || {}).length)),
          grid_count: Number(this.h3GridCount || (this.h3AnalysisSummary && this.h3AnalysisSummary.grid_count) || 0) || 0,
          feature_count: Array.isArray(this.h3AnalysisGridFeatures) ? this.h3AnalysisGridFeatures.length : 0,
          mode: asText(this.h3StructureFillMode || this.h3MetricView),
        },
        population: {
          available: !!(this.populationSummary || this.populationOverview || this.populationLayer || this.populationRaster || this.populationAnalysisResult),
          summary: summarizeObject((this.populationSummary || this.populationOverview || {}).summary || this.populationSummary || this.populationOverview, ['total_population', 'cell_count', 'grid_count']),
        },
        nightlight: {
          available: !!(this.nightlightSummary || this.nightlightOverview || this.nightlightLayer || this.nightlightRaster || this.nightlightAnalysisResult),
          summary: summarizeObject((this.nightlightSummary || this.nightlightOverview || {}).summary || this.nightlightSummary || this.nightlightOverview, ['mean_radiance', 'max_radiance', 'lit_pixel_ratio', 'cell_count']),
        },
        road: {
          available: !!(this.roadSyntaxSummary || (Array.isArray(this.roadSyntaxRoadFeatures) && this.roadSyntaxRoadFeatures.length)),
          feature_count: Array.isArray(this.roadSyntaxRoadFeatures) ? this.roadSyntaxRoadFeatures.length : 0,
          summary: summarizeObject(this.roadSyntaxSummary, ['node_count', 'edge_count', 'segment_count']),
          metric_tabs: roadTabs,
        },
      }
      return JSON.stringify(fingerprint)
    },
    buildAgentVisualSnapshotTargets() {
      const snapshotLimit = 12
      const targets = [{ kind: 'overview_map', title: '当前地图总览', key: '' }]
      if (Array.isArray(this.allPoisDetails) && this.allPoisDetails.length) {
        targets.push({ kind: 'poi_map', title: 'POI 点位与分类图层', key: 'poi' })
      }
      if (this.h3AnalysisSummary || (this.sharedGridMetrics && Object.keys(this.sharedGridMetrics || {}).length)) {
        targets.push({ kind: 'h3_map', title: 'H3 网格分析图层', key: 'h3' })
      }
      if (this.populationSummary || this.populationOverview || this.populationLayer || this.populationRaster || this.populationAnalysisResult) {
        targets.push({ kind: 'population_map', title: '人口分析图层', key: 'population' })
      }
      if (this.nightlightSummary || this.nightlightOverview || this.nightlightLayer || this.nightlightRaster || this.nightlightAnalysisResult) {
        targets.push({ kind: 'nightlight_map', title: '夜光活力图层', key: 'nightlight' })
      }
      if (this.roadSyntaxSummary || (Array.isArray(this.roadSyntaxRoadFeatures) && this.roadSyntaxRoadFeatures.length)) {
        const tabs = (typeof this.roadSyntaxMetricTabs === 'function')
          ? this.roadSyntaxMetricTabs()
          : [
              { value: 'connectivity', label: '连接度' },
              { value: 'control', label: '控制值' },
              { value: 'depth', label: '深度值' },
              { value: 'choice', label: '选择度' },
              { value: 'integration', label: '整合度' },
              { value: 'intelligibility', label: '可理解度' },
            ]
        const seenMetrics = new Set()
        cloneArray(tabs).forEach((tab) => {
          const metric = asText(tab && tab.value)
          if (!metric || seenMetrics.has(metric)) return
          seenMetrics.add(metric)
          const label = asText(tab && tab.label) || metric
          targets.push({
            kind: 'road_map',
            title: `路网分析全范围图层 · ${label}`,
            key: 'syntax',
            fit: 'road',
            metric,
          })
        })
      }
      return targets.slice(0, snapshotLimit)
    },
    canCaptureAgentOffscreenVisualSnapshots() {
      const amap = this.getAgentAmapSdk()
      const hasHtml2canvas = (typeof globalThis !== 'undefined' && typeof globalThis.html2canvas === 'function')
        || (typeof window !== 'undefined' && typeof window.html2canvas === 'function')
      return typeof document !== 'undefined'
        && typeof window !== 'undefined'
        && amap
        && typeof amap.Map === 'function'
        && hasHtml2canvas
    },
    async waitForPptMapSnapshotRendererStep(promise, code = 'ppt_map_renderer_timeout', timeoutMs = 8000) {
      let timeoutId = null
      const timeout = new Promise((_, reject) => {
        const timerHost = (typeof window !== 'undefined' && typeof window.setTimeout === 'function') ? window : globalThis
        timeoutId = timerHost.setTimeout(() => reject(new Error(code)), Math.max(500, Number(timeoutMs) || 8000))
      })
      try {
        return await Promise.race([promise, timeout])
      } finally {
        if (timeoutId !== null) {
          const timerHost = (typeof window !== 'undefined' && typeof window.clearTimeout === 'function') ? window : globalThis
          timerHost.clearTimeout(timeoutId)
        }
      }
    },
    async loadPptMapSnapshotScript(src = '', errorCode = 'ppt_map_renderer_script_unavailable') {
      const normalizedSrc = asText(src)
      if (!normalizedSrc) throw new Error(errorCode)
      if (typeof document === 'undefined') throw new Error('ppt_map_renderer_dom_unavailable')
      const cacheKey = `script:${normalizedSrc}`
      const cache = cloneObject(this.pptMapSnapshotRendererReadyCache)
      if (cache[cacheKey]) return true
      await this.waitForPptMapSnapshotRendererStep(new Promise((resolve, reject) => {
        const selector = `script[data-ppt-map-snapshot-src="${normalizedSrc}"]`
        const existing = document.querySelector(selector)
        if (existing) {
          if (existing.__loaded) {
            resolve(true)
            return
          }
          existing.addEventListener('load', () => resolve(true), { once: true })
          existing.addEventListener('error', () => reject(new Error(errorCode)), { once: true })
          return
        }
        const script = document.createElement('script')
        script.src = normalizedSrc
        script.async = false
        script.dataset.pptMapSnapshotSrc = normalizedSrc
        script.onload = () => {
          script.__loaded = true
          resolve(true)
        }
        script.onerror = () => reject(new Error(errorCode))
        document.head.appendChild(script)
      }), 'ppt_map_renderer_timeout')
      this.pptMapSnapshotRendererReadyCache = {
        ...cloneObject(this.pptMapSnapshotRendererReadyCache),
        [cacheKey]: true,
      }
      return true
    },
    async ensurePptMapSnapshotRendererReady() {
      if (typeof document === 'undefined' || typeof window === 'undefined') {
        throw new Error('ppt_map_renderer_dom_unavailable')
      }
      const getHtml2canvas = () => (typeof globalThis !== 'undefined' && typeof globalThis.html2canvas === 'function')
        ? globalThis.html2canvas
        : (typeof window !== 'undefined' && typeof window.html2canvas === 'function' ? window.html2canvas : null)
      if (!getHtml2canvas()) {
        await this.loadPptMapSnapshotScript('/static/vendor/html2canvas.min.js', 'ppt_map_renderer_html2canvas_unavailable')
      }
      if (!getHtml2canvas()) {
        throw new Error('ppt_map_renderer_html2canvas_unavailable')
      }
      let amap = this.getAgentAmapSdk()
      if (!amap || typeof amap.Map !== 'function') {
        if (typeof this.loadAMapScript !== 'function') {
          throw new Error('ppt_map_renderer_amap_unavailable')
        }
        const config = cloneObject(this.config || (typeof window !== 'undefined' ? window.__ANALYSIS_BOOTSTRAP__ && window.__ANALYSIS_BOOTSTRAP__.config : null))
        await this.waitForPptMapSnapshotRendererStep(
          Promise.resolve(this.loadAMapScript(config.amap_js_api_key || '', config.amap_js_security_code || '')),
          'ppt_map_renderer_timeout',
        ).catch((error) => {
          if (asText(error && error.message) === 'ppt_map_renderer_timeout') throw error
          throw new Error('ppt_map_renderer_amap_unavailable')
        })
        amap = this.getAgentAmapSdk()
      }
      if (!amap || typeof amap.Map !== 'function') {
        throw new Error('ppt_map_renderer_amap_unavailable')
      }
      return { ready: true }
    },
    getAgentAmapSdk() {
      if (typeof window !== 'undefined' && window.AMap) return window.AMap
      if (typeof globalThis !== 'undefined' && globalThis.AMap) return globalThis.AMap
      return null
    },
    getAgentVisualSnapshotRenderSize() {
      return { width: 960, height: 960 }
    },
    normalizeAgentSnapshotLngLat(value = null) {
      if (Array.isArray(value) && value.length >= 2) {
        const lng = Number(value[0])
        const lat = Number(value[1])
        return Number.isFinite(lng) && Number.isFinite(lat) ? [lng, lat] : null
      }
      if (value && typeof value === 'object') {
        const lng = Number(value.lng ?? value.longitude ?? value.x ?? value[0])
        const lat = Number(value.lat ?? value.latitude ?? value.y ?? value[1])
        return Number.isFinite(lng) && Number.isFinite(lat) ? [lng, lat] : null
      }
      return null
    },
    normalizeAgentSnapshotRing(source = []) {
      const ring = cloneArray(source).map((point) => this.normalizeAgentSnapshotLngLat(point)).filter(Boolean)
      if (ring.length < 3) return []
      const first = ring[0]
      const last = ring[ring.length - 1]
      if (first && last && (first[0] !== last[0] || first[1] !== last[1])) {
        ring.push([first[0], first[1]])
      }
      return ring
    },
    buildAgentSnapshotScopeRing() {
      const snapshot = this.buildAgentAnalysisSnapshot ? this.buildAgentAnalysisSnapshot() : {}
      const polygon = snapshot && snapshot.scope && Array.isArray(snapshot.scope.polygon) ? snapshot.scope.polygon : []
      if (polygon.length && Array.isArray(polygon[0]) && this.normalizeAgentSnapshotLngLat(polygon[0])) {
        return this.normalizeAgentSnapshotRing(polygon)
      }
      if (polygon.length && Array.isArray(polygon[0])) {
        return this.normalizeAgentSnapshotRing(polygon[0])
      }
      return []
    },
    addAgentSnapshotScopeOverlay(map = null, overlays = [], options = {}) {
      const ring = this.buildAgentSnapshotScopeRing()
      const amap = this.getAgentAmapSdk()
      if (!map || !ring.length || !amap || typeof amap.Polygon !== 'function') return null
      const polygon = new amap.Polygon({
        path: ring,
        strokeColor: options.strokeColor || '#f97316',
        strokeWeight: Number(options.strokeWeight || 2),
        strokeOpacity: Number(options.strokeOpacity || 0.95),
        fillColor: options.fillColor || '#f97316',
        fillOpacity: Number(options.fillOpacity ?? 0.03),
        zIndex: Number(options.zIndex || 120),
        bubble: true,
      })
      polygon.setMap(map)
      overlays.push(polygon)
      return polygon
    },
    getAgentSnapshotFeatureRings(feature = null) {
      const geometry = feature && feature.geometry ? feature.geometry : {}
      const type = asText(geometry.type)
      const coordinates = Array.isArray(geometry.coordinates) ? geometry.coordinates : []
      if (type === 'Polygon') {
        return coordinates.slice(0, 1).map((ring) => this.normalizeAgentSnapshotRing(ring)).filter((ring) => ring.length >= 3)
      }
      if (type === 'MultiPolygon') {
        return coordinates.flatMap((polygon) => (Array.isArray(polygon) ? polygon : []).slice(0, 1).map((ring) => this.normalizeAgentSnapshotRing(ring))).filter((ring) => ring.length >= 3)
      }
      return []
    },
    getAgentSnapshotFeatureLines(feature = null) {
      const geometry = feature && feature.geometry ? feature.geometry : {}
      const type = asText(geometry.type)
      const coordinates = Array.isArray(geometry.coordinates) ? geometry.coordinates : []
      if (type === 'LineString') {
        const line = coordinates.map((point) => this.normalizeAgentSnapshotLngLat(point)).filter(Boolean)
        return line.length >= 2 ? [line] : []
      }
      if (type === 'MultiLineString') {
        return coordinates.map((line) => (Array.isArray(line) ? line : []).map((point) => this.normalizeAgentSnapshotLngLat(point)).filter(Boolean)).filter((line) => line.length >= 2)
      }
      return []
    },
    agentSnapshotColorFromRatio(ratio = 0, palette = ['#dbeafe', '#60a5fa', '#22c55e', '#f59e0b', '#ef4444']) {
      const value = Math.max(0, Math.min(1, Number(ratio) || 0))
      const index = Math.max(0, Math.min(palette.length - 1, Math.floor(value * palette.length)))
      return palette[index]
    },
    addAgentSnapshotPolygonFeatures(map = null, overlays = [], features = [], style = {}) {
      const amap = this.getAgentAmapSdk()
      if (!map || !amap || typeof amap.Polygon !== 'function') return 0
      let count = 0
      cloneArray(features).forEach((feature) => {
        const props = feature && typeof feature === 'object' ? (feature.properties || {}) : {}
        this.getAgentSnapshotFeatureRings(feature).forEach((ring) => {
          const polygon = new amap.Polygon({
            path: ring,
            strokeColor: asText(props.strokeColor) || style.strokeColor || '#64748b',
            strokeWeight: Number(props.strokeWeight ?? style.strokeWeight ?? 0.9),
            strokeOpacity: Number(style.strokeOpacity ?? 0.78),
            fillColor: asText(props.fillColor) || style.fillColor || '#93c5fd',
            fillOpacity: Number(props.fillOpacity ?? style.fillOpacity ?? 0.28),
            zIndex: Number(style.zIndex || 80),
            clickable: false,
            bubble: true,
          })
          polygon.setMap(map)
          overlays.push(polygon)
          count += 1
        })
      })
      return count
    },
    getAgentSnapshotPoiColor(type = '') {
      const text = asText(type)
      if (/餐饮|美食|food|restaurant/i.test(text)) return '#a855f7'
      if (/购物|shop|mall/i.test(text)) return '#facc15'
      if (/科教|教育|文化|school|university/i.test(text)) return '#0ea5e9'
      if (/交通|transport/i.test(text)) return '#14b8a6'
      if (/公司|企业|office/i.test(text)) return '#64748b'
      if (/医疗|hospital/i.test(text)) return '#ef4444'
      if (/住宿|hotel/i.test(text)) return '#84cc16'
      return '#10b981'
    },
    renderAgentOffscreenPoiLayer(map = null, overlays = []) {
      const amap = this.getAgentAmapSdk()
      if (!map || !amap) return 0
      const pois = cloneArray(this.allPoisDetails)
      let count = 0
      pois.slice(0, 5000).forEach((poi) => {
        const position = this.normalizeAgentSnapshotLngLat(poi && (poi.location || [poi.lng, poi.lat]))
        if (!position) return
        const color = this.getAgentSnapshotPoiColor(poi && (poi.type || poi.category || poi.type_name))
        const marker = typeof amap.CircleMarker === 'function'
          ? new amap.CircleMarker({
              center: position,
              radius: 4,
              strokeColor: '#ffffff',
              strokeWeight: 1,
              strokeOpacity: 0.9,
              fillColor: color,
              fillOpacity: 0.78,
              zIndex: 150,
              bubble: true,
            })
          : (typeof amap.Marker === 'function' ? new amap.Marker({ position, zIndex: 150 }) : null)
        if (!marker) return
        marker.setMap(map)
        overlays.push(marker)
        count += 1
      })
      return count
    },
    buildAgentOffscreenH3Features() {
      const source = Array.isArray(this.h3AnalysisGridFeatures) && this.h3AnalysisGridFeatures.length
        ? this.h3AnalysisGridFeatures
        : (Array.isArray(this.poiGridFeatures) ? this.poiGridFeatures : [])
      const counts = cloneArray(source).map((feature) => Number(feature && feature.properties && (feature.properties.poi_count || feature.properties.count || 0))).filter((value) => Number.isFinite(value))
      const maxCount = Math.max(1, ...counts, Number(this.h3AnalysisSummary && (this.h3AnalysisSummary.max_poi_count || this.h3AnalysisSummary.max_count) || 0))
      return cloneArray(source).map((feature) => {
        const props = Object.assign({}, feature && feature.properties)
        const count = Number(props.poi_count || props.count || 0)
        const ratio = maxCount > 0 ? count / maxCount : 0
        return {
          type: (feature && feature.type) || 'Feature',
          geometry: feature && feature.geometry,
          properties: Object.assign({}, props, {
            fillColor: props.fillColor || this.agentSnapshotColorFromRatio(ratio, ['#eff6ff', '#bfdbfe', '#60a5fa', '#2563eb', '#1e3a8a']),
            fillOpacity: props.fillOpacity ?? (count > 0 ? 0.42 : 0.10),
            strokeColor: props.strokeColor || '#475569',
            strokeWeight: props.strokeWeight ?? 0.75,
          }),
        }
      })
    },
    buildAgentOffscreenPopulationFeatures() {
      if (typeof this.buildPopulationStyledFeatures === 'function') {
        const features = this.buildPopulationStyledFeatures()
        if (features && features.length) return features
      }
      return cloneArray((this.populationGrid && this.populationGrid.features) || [])
    },
    buildAgentOffscreenNightlightFeatures() {
      if (typeof this.buildNightlightStyledFeatures === 'function') {
        const features = this.buildNightlightStyledFeatures()
        if (features && features.length) return features
      }
      return cloneArray((this.nightlightGrid && this.nightlightGrid.features) || [])
    },
    getAgentRoadMetricField(metric = '') {
      if (typeof this.resolveRoadSyntaxMetricField === 'function') {
        return this.resolveRoadSyntaxMetricField(metric)
      }
      if (metric === 'control') return 'control_score'
      if (metric === 'depth') return 'depth_score'
      if (metric === 'choice') return 'choice_score'
      if (metric === 'integration') return 'integration_score'
      if (metric === 'intelligibility') return 'intelligibility_score'
      return 'connectivity_score'
    },
    getAgentRoadFallbackField(metric = '') {
      if (typeof this.resolveRoadSyntaxFallbackField === 'function') {
        return this.resolveRoadSyntaxFallbackField(metric)
      }
      if (metric === 'choice') return 'choice_global'
      if (metric === 'integration') return 'integration_global'
      return this.getAgentRoadMetricField(metric)
    },
    getAgentRoadMetricScore(props = {}, metric = '') {
      const fields = [
        this.getAgentRoadMetricField(metric),
        this.getAgentRoadFallbackField(metric),
        `${metric}_score`,
        metric,
        'value',
      ].filter(Boolean)
      for (const field of fields) {
        const value = Number(props && props[field])
        if (Number.isFinite(value)) return Math.max(0, Math.min(1, value))
      }
      return NaN
    },
    getAgentRoadStyle(props = {}, metric = '') {
      if (typeof this.buildRoadSyntaxStyleForMetric === 'function') {
        return this.buildRoadSyntaxStyleForMetric(
          props,
          this.getAgentRoadMetricField(metric),
          this.getAgentRoadFallbackField(metric),
          metric,
          false,
        )
      }
      const score = this.getAgentRoadMetricScore(props, metric)
      return {
        strokeColor: this.agentSnapshotColorFromRatio(Number.isFinite(score) ? score : 0.35, ['#38bdf8', '#22c55e', '#facc15', '#fb923c', '#ef4444']),
        strokeWeight: metric === 'intelligibility' ? 2 : 2.2,
        strokeOpacity: metric === 'intelligibility' ? 0.62 : 0.86,
        zIndex: 110,
      }
    },
    renderAgentOffscreenRoadLayer(map = null, overlays = [], metric = '') {
      const amap = this.getAgentAmapSdk()
      if (!map || !amap || typeof amap.Polyline !== 'function') return 0
      let count = 0
      cloneArray(this.roadSyntaxRoadFeatures).forEach((feature) => {
        const props = (feature && feature.properties) || {}
        const style = this.getAgentRoadStyle(props, metric)
        this.getAgentSnapshotFeatureLines(feature).forEach((path) => {
          const line = new amap.Polyline({
            path,
            strokeColor: style.strokeColor || '#2563eb',
            strokeWeight: Number(style.strokeWeight || 2),
            strokeOpacity: Number(style.strokeOpacity ?? 0.82),
            zIndex: Number(style.zIndex || 110),
            bubble: true,
          })
          line.setMap(map)
          overlays.push(line)
          count += 1
        })
      })
      return count
    },
    createAgentOffscreenSnapshotHost(size = {}, options = {}) {
      const width = Math.max(320, Number(size.width || 960))
      const height = Math.max(320, Number(size.height || 960))
      const captureInViewport = !!(options && options.captureInViewport)
      const host = document.createElement('div')
      host.setAttribute('data-agent-offscreen-snapshot-host', '1')
      host.style.cssText = [
        'position:fixed',
        `left:${captureInViewport ? 0 : -20000}px`,
        'top:0',
        `width:${width}px`,
        `height:${height}px`,
        'background:#ffffff',
        'overflow:hidden',
        'pointer-events:none',
        `z-index:${captureInViewport ? -1 : -1}`,
        'visibility:visible',
        'transform:translateZ(0)',
      ].join(';')
      document.body.appendChild(host)
      return host
    },
    cleanAgentOffscreenMapChrome(mapEl = null) {
      if (!mapEl || typeof mapEl.querySelectorAll !== 'function') return
      mapEl.querySelectorAll('.amap-logo,.amap-copyright,.amap-controlbar,.amap-toolbar,.amap-scalecontrol').forEach((node) => {
        node.style.display = 'none'
      })
    },
    waitForAgentOffscreenImages(root = null, timeoutMs = 3000) {
      const images = Array.from(root && root.querySelectorAll ? root.querySelectorAll('img') : [])
      if (!images.length) return Promise.resolve(true)
      let pending = images.filter((img) => !(img.complete && img.naturalWidth > 0))
      if (!pending.length) return Promise.resolve(true)
      return new Promise((resolve) => {
        let done = false
        const finish = (ok) => {
          if (done) return
          done = true
          pending.forEach((img) => {
            img.removeEventListener('load', check)
            img.removeEventListener('error', check)
          })
          resolve(ok)
        }
        const check = () => {
          pending = pending.filter((img) => !(img.complete && img.naturalWidth > 0))
          if (!pending.length) finish(true)
        }
        pending.forEach((img) => {
          img.addEventListener('load', check, { once: true })
          img.addEventListener('error', check, { once: true })
        })
        window.setTimeout(() => finish(false), Math.max(500, Number(timeoutMs) || 3000))
        check()
      })
    },
    async waitForAgentOffscreenSnapshotPaint(mapEl = null, waitMs = 900) {
      await this.waitForAgentVisualSnapshotPaint()
      await (this._sleepForExport ? this._sleepForExport(waitMs) : new Promise((resolve) => window.setTimeout(resolve, waitMs)))
      this.cleanAgentOffscreenMapChrome(mapEl)
      await this.waitForAgentOffscreenImages(mapEl, 3000)
      await this.waitForAgentVisualSnapshotPaint()
    },
    fitAgentOffscreenSnapshotMap(map = null, fitOverlays = []) {
      if (!map) return
      const overlays = cloneArray(fitOverlays).filter(Boolean)
      try {
        if (overlays.length && typeof map.setFitView === 'function') {
          map.setFitView(overlays, false, [42, 42, 42, 42])
          return
        }
      } catch (_) {}
      const bounds = this.getAgentScopeBounds()
      const amap = this.getAgentAmapSdk()
      if (bounds && amap && amap.LngLat && amap.Bounds && typeof map.setBounds === 'function') {
        try {
          map.setBounds(new amap.Bounds(new amap.LngLat(bounds.west, bounds.south), new amap.LngLat(bounds.east, bounds.north)))
          return
        } catch (_) {}
      }
      const view = this.getAgentMapViewState()
      if (view && Array.isArray(view.center) && typeof map.setCenter === 'function') map.setCenter(view.center)
      if (view && Number.isFinite(Number(view.zoom)) && typeof map.setZoom === 'function') map.setZoom(Number(view.zoom))
    },
    renderAgentOffscreenSnapshotTarget(map = null, target = {}, overlays = []) {
      const fitOverlays = []
      const scopeOverlay = this.addAgentSnapshotScopeOverlay(map, overlays, {
        fillOpacity: asText(target.kind) === 'overview_map' ? 0.06 : 0.02,
        strokeWeight: 2,
        zIndex: 180,
      })
      if (scopeOverlay) fitOverlays.push(scopeOverlay)
      const kind = asText(target.kind)
      if (kind === 'poi_map') {
        this.renderAgentOffscreenPoiLayer(map, overlays)
      } else if (kind === 'h3_map') {
        this.addAgentSnapshotPolygonFeatures(map, overlays, this.buildAgentOffscreenH3Features(), {
          strokeColor: '#475569',
          strokeWeight: 0.8,
          fillColor: '#bfdbfe',
          fillOpacity: 0.34,
          zIndex: 90,
        })
      } else if (kind === 'population_map') {
        this.addAgentSnapshotPolygonFeatures(map, overlays, this.buildAgentOffscreenPopulationFeatures(), {
          strokeColor: '#ffffff',
          strokeWeight: 0.7,
          fillColor: '#f4f6f8',
          fillOpacity: 0.20,
          zIndex: 90,
        })
      } else if (kind === 'nightlight_map') {
        const container = map && typeof map.getContainer === 'function' ? map.getContainer() : null
        if (container) {
          container.style.backgroundColor = '#162033'
          container.style.backgroundImage = 'radial-gradient(circle at 52% 42%, rgba(251,191,36,0.1) 0%, rgba(35,49,74,0.82) 28%, rgba(22,32,51,0.94) 62%, rgba(10,15,27,1) 100%)'
        }
        this.addAgentSnapshotPolygonFeatures(map, overlays, this.buildAgentOffscreenNightlightFeatures(), {
          strokeColor: '#94a3b8',
          strokeWeight: 0.7,
          fillColor: '#f59e0b',
          fillOpacity: 0.36,
          zIndex: 90,
        })
      } else if (kind === 'road_map') {
        this.renderAgentOffscreenRoadLayer(map, overlays, asText(target.metric))
      }
      return fitOverlays
    },
    pptMapRequestLayerType(layer = {}) {
      return asText(layer && (layer.layer_type || layer.layerType || layer.type))
    },
    inferPptRoadSnapshotMetric(mapRequest = {}, layer = {}) {
      const explicit = asText(layer.metric || layer.metric_key || layer.metricKey || mapRequest.metric || mapRequest.metric_key || mapRequest.metricKey)
      if (explicit) return explicit.replace(/^avg_/, '')
      const text = [
        ...cloneArray(mapRequest.annotations).map((item) => `${asText(item && (item.metric_id || item.metricId))} ${asText(item && item.label)}`),
        asText(mapRequest.title),
      ].join(' ').toLowerCase()
      if (/choice|选择/.test(text)) return 'choice'
      if (/integration|整合/.test(text)) return 'integration'
      if (/depth|深度/.test(text)) return 'depth'
      if (/control|控制/.test(text)) return 'control'
      if (/intelligibility|理解/.test(text)) return 'intelligibility'
      return 'connectivity'
    },
    pptMapRequestLayerTarget(mapRequest = {}, layer = {}) {
      const type = this.pptMapRequestLayerType(layer)
      if (type === 'scope_boundary') {
        return { kind: 'overview_map', title: asText(mapRequest.title) || '空间边界与基底概貌', key: 'scope' }
      }
      if (type === 'poi_points') return { kind: 'poi_map', title: asText(mapRequest.title) || 'POI 点位图层', key: 'poi' }
      if (type === 'h3_grid') return { kind: 'h3_map', title: asText(mapRequest.title) || 'H3 网格图层', key: 'h3' }
      if (type === 'population_grid') return { kind: 'population_map', title: asText(mapRequest.title) || '人口图层', key: 'population' }
      if (type === 'nightlight_grid') return { kind: 'nightlight_map', title: asText(mapRequest.title) || '夜光图层', key: 'nightlight' }
      if (type === 'road_syntax') {
        return {
          kind: 'road_map',
          title: asText(mapRequest.title) || '路网句法图层',
          key: 'syntax',
          fit: 'road',
          metric: this.inferPptRoadSnapshotMetric(mapRequest, layer),
        }
      }
      return null
    },
    pptMapRequestHistoryId(mapRequest = {}) {
      const request = cloneObject(mapRequest)
      const scope = cloneObject(request.scope || request.focus || request.bounds)
      const direct = asText(
        request.history_id
        || request.historyId
        || request.area_id
        || request.areaId
        || scope.history_id
        || scope.historyId
        || scope.area_id
        || scope.areaId,
      )
      if (direct) return direct
      for (const layer of cloneArray(request.layers)) {
        const source = asText(layer && (layer.source || layer.source_id || layer.sourceId))
        const match = source.match(/^history:([^:]+):/)
        if (match && match[1]) return match[1]
      }
      return asText(typeof this.getCurrentAgentHistoryId === 'function'
        ? this.getCurrentAgentHistoryId()
        : this.currentHistoryRecordId)
    },
    pptMapRequestLayerTargets(mapRequest = {}) {
      return cloneArray(mapRequest.layers)
        .map((layer) => ({ layer, target: this.pptMapRequestLayerTarget(mapRequest, layer) }))
        .filter((item) => item.target)
    },
    pptMapRequestPrimarySnapshotTarget(mapRequest = {}) {
      const targets = this.pptMapRequestLayerTargets(mapRequest)
        .map((item) => cloneObject(item.target))
      return targets.find((target) => asText(target.kind) !== 'overview_map') || targets[0] || null
    },
    pptMapRequestMissingLayers(mapRequest = {}) {
      return this.pptMapRequestLayerTargets(mapRequest)
        .filter((item) => !this.hasPptMapRequestLayerData(item.target))
    },
    hasPptMapRequestLayerData(target = {}) {
      const kind = asText(target.kind)
      if (kind === 'overview_map') return !!this.getAgentScopeBounds()
      if (kind === 'poi_map') return Array.isArray(this.allPoisDetails) && this.allPoisDetails.length > 0
      if (kind === 'h3_map') return !!(this.h3AnalysisSummary || (this.sharedGridMetrics && Object.keys(this.sharedGridMetrics || {}).length) || (Array.isArray(this.h3AnalysisGridFeatures) && this.h3AnalysisGridFeatures.length))
      if (kind === 'population_map') return !!(this.populationSummary || this.populationOverview || this.populationLayer || this.populationRaster || this.populationAnalysisResult || (this.populationGrid && Array.isArray(this.populationGrid.features) && this.populationGrid.features.length))
      if (kind === 'nightlight_map') return !!(this.nightlightSummary || this.nightlightOverview || this.nightlightLayer || this.nightlightRaster || this.nightlightAnalysisResult || (this.nightlightGrid && Array.isArray(this.nightlightGrid.features) && this.nightlightGrid.features.length))
      if (kind === 'road_map') return !!(this.roadSyntaxSummary || (Array.isArray(this.roadSyntaxRoadFeatures) && this.roadSyntaxRoadFeatures.length))
      return false
    },
    normalizePptMapSnapshotCaptureError(error = null) {
      const rawMessage = asText(error && error.message ? error.message : error)
      const [rawCode, layerType = ''] = rawMessage.split(':')
      const code = asText(rawCode) || 'ppt_map_snapshot_capture_failed'
      const detail = error && typeof error === 'object'
        ? asText(error.detail || error.cause && error.cause.message || error.reason)
        : ''
      const messages = {
        ppt_map_renderer_dom_unavailable: '地图截图环境不可用：浏览器 DOM 未就绪',
        ppt_map_renderer_amap_unavailable: '地图截图环境未就绪：高德地图脚本未加载',
        ppt_map_renderer_html2canvas_unavailable: '地图截图环境未就绪：截图组件未加载',
        ppt_map_renderer_timeout: '地图截图环境加载超时',
        ppt_map_request_renderer_unavailable: '地图截图环境未就绪：高德地图或截图组件不可用',
        ppt_map_request_no_supported_layers: '地图请求没有可渲染图层',
        ppt_map_request_no_rendered_features: '地图图层渲染为空',
        ppt_map_main_capture_unavailable: '主地图截图方法不可用',
        ppt_map_main_capture_empty: '主地图截图返回空',
        ppt_map_main_capture_invalid_data_url: '主地图截图不是有效图片',
        ppt_map_main_capture_failed: '主地图截图失败',
        ppt_map_offscreen_capture_failed: '离屏地图截图失败',
        ppt_map_asset_invalid_data_url: '地图截图不是有效图片',
        ppt_map_snapshot_capture_failed: '地图截图导出失败',
        ppt_map_snapshot_canvas_empty: '地图截图画布为空',
        ppt_map_snapshot_data_url_empty: '地图截图导出为空',
        ppt_map_snapshot_canvas_tainted: '地图截图被跨域瓦片阻止导出',
        ppt_carrier_package_missing: '载体资料包未恢复',
        ppt_carrier_package_carriers_missing: '载体资料包没有载体记录',
        ppt_carrier_geometry_missing: '载体资料包缺少空间几何',
        ppt_carrier_snapshot_empty: '载体分布图渲染为空',
        ppt_carrier_snapshot_render_failed: '载体分布图导出失败',
        ppt_carrier_snapshot_encoder_unavailable: '载体分布图编码组件不可用',
      }
      const layerMessages = {
        population_grid: '人口图层数据未恢复',
        h3_grid: 'H3 网格数据未恢复',
        nightlight_grid: '夜光图层数据未恢复',
        road_syntax: '路网句法图层数据未恢复',
        poi_points: 'POI 点位数据未恢复',
        scope_boundary: '空间范围边界未恢复',
      }
      const message = code === 'ppt_map_request_layer_data_missing'
        ? (layerMessages[layerType] || '地图图层数据未恢复')
        : (messages[code] || rawMessage || '地图截图失败')
      return {
        code,
        message,
        layer_type: layerType,
        detail,
        renderer_ready: ![
          'ppt_map_renderer_dom_unavailable',
          'ppt_map_renderer_amap_unavailable',
          'ppt_map_renderer_html2canvas_unavailable',
          'ppt_map_renderer_timeout',
          'ppt_map_request_renderer_unavailable',
          'ppt_map_offscreen_capture_failed',
        ].includes(code),
        captured_at: new Date().toISOString(),
      }
    },
    attachPptMapSnapshotCaptureError(visual = {}, error = null) {
      const data = cloneObject(visual && visual.data)
      return {
        ...cloneObject(visual),
        status: asText(visual && visual.status) || 'needs_existing_asset',
        data: {
          ...data,
          capture_error: this.normalizePptMapSnapshotCaptureError(error),
        },
      }
    },
    async renderPptMapRequestMainMapSnapshot(mapRequest = {}) {
      if (typeof this._captureMapSnapshotBase64 !== 'function') {
        throw new Error('ppt_map_main_capture_unavailable')
      }
      const layers = this.pptMapRequestLayerTargets(mapRequest)
      if (!layers.length) throw new Error('ppt_map_request_no_supported_layers')
      const missing = this.pptMapRequestMissingLayers(mapRequest)[0]
      if (missing) {
        throw new Error(`ppt_map_request_layer_data_missing:${this.pptMapRequestLayerType(missing.layer)}`)
      }
      const target = this.pptMapRequestPrimarySnapshotTarget(mapRequest)
      if (!target) throw new Error('ppt_map_request_no_supported_layers')
      const view = typeof this.getAgentMapViewState === 'function' ? this.getAgentMapViewState() : null
      const layerState = typeof this.getAgentVisualLayerState === 'function' ? this.getAgentVisualLayerState() : null
      try {
        if (typeof this.prepareAgentVisualSnapshotTarget === 'function') {
          await this.prepareAgentVisualSnapshotTarget(target)
        }
        const rawDataUrl = await this._captureMapSnapshotBase64()
        if (!asText(rawDataUrl).startsWith('data:image/')) {
          throw new Error('ppt_map_main_capture_empty')
        }
        if (typeof this.compressAgentVisualSnapshotDataUrl === 'function') {
          return await this.compressAgentVisualSnapshotDataUrl(rawDataUrl) || rawDataUrl
        }
        return rawDataUrl
      } catch (error) {
        const message = asText(error && error.message ? error.message : error)
        if (message.startsWith('ppt_map_')) throw error
        throw Object.assign(new Error('ppt_map_main_capture_failed'), {
          cause: error,
          detail: message,
        })
      } finally {
        try {
          if (typeof this.restoreAgentVisualLayerState === 'function') {
            await this.restoreAgentVisualLayerState(layerState)
          }
        } catch (_) {}
        try {
          if (typeof this.restoreAgentMapViewState === 'function') {
            this.restoreAgentMapViewState(view)
          }
        } catch (_) {}
        try {
          if (typeof this.waitForAgentVisualSnapshotPaint === 'function') {
            await this.waitForAgentVisualSnapshotPaint()
          }
        } catch (_) {}
      }
    },
    normalizePptMapRequestHistoryPolygon(source = []) {
      const normalizeRing = (raw) => {
        if (!Array.isArray(raw) || !raw.length) return []
        const points = raw
          .map((point) => this.normalizeAgentSnapshotLngLat(point))
          .filter(Boolean)
        if (points.length < 3) return []
        const first = points[0]
        const last = points[points.length - 1]
        if (first && last && (first[0] !== last[0] || first[1] !== last[1])) {
          points.push([first[0], first[1]])
        }
        return points.length >= 4 ? points : []
      }
      if (!Array.isArray(source) || !source.length) return []
      const direct = normalizeRing(source)
      if (direct.length) return direct
      const rings = []
      source.forEach((item) => {
        const ring = normalizeRing(item)
        if (ring.length) rings.push(ring)
        else if (Array.isArray(item) && Array.isArray(item[0])) {
          const outer = normalizeRing(item[0])
          if (outer.length) rings.push(outer)
        }
      })
      return rings.length === 1 ? rings[0] : rings
    },
    applyPptMapRequestHistoryScope(detail = {}, historyId = '') {
      const polygon = this.normalizePptMapRequestHistoryPolygon(detail && detail.polygon)
      const polygonWgs84 = JSON.parse(JSON.stringify((detail && detail.polygon_wgs84) || []))
      if (!polygon.length) return false
      const polygonCopy = JSON.parse(JSON.stringify(polygon))
      this.currentHistoryRecordId = asText(historyId) || asText(this.currentHistoryRecordId)
      this.currentHistoryPolygon = polygonCopy
      this.currentHistoryPolygonWgs84 = polygonWgs84
      this.scopeSource = 'history'
      this.lastIsochroneGeoJSON = Array.isArray(polygon[0]) && this.normalizeAgentSnapshotLngLat(polygon[0])
        ? {
            type: 'Feature',
            properties: { mode: 'history' },
            geometry: { type: 'Polygon', coordinates: [polygonCopy] },
          }
        : {
            type: 'Feature',
            properties: { mode: 'history' },
            geometry: { type: 'MultiPolygon', coordinates: polygonCopy.map((ring) => [ring]) },
          }
      return true
    },
    async ensurePptMapRequestHistoryScope(historyId = '') {
      const normalizedHistoryId = asText(historyId)
      if (!normalizedHistoryId) return false
      const scopeBounds = this.getAgentScopeBounds()
      if (scopeBounds && asText(this.currentHistoryRecordId) === normalizedHistoryId) return true
      const cacheKey = `scope:${normalizedHistoryId}`
      if (this.pptMapRequestHistoryRestoreCache && this.pptMapRequestHistoryRestoreCache[cacheKey]) {
        return true
      }
      if (typeof fetch !== 'function') return false
      const res = await fetch(`/api/v1/analysis/history/${encodeURIComponent(normalizedHistoryId)}?include_pois=false`)
      if (!res.ok) throw new Error(`ppt_map_request_history_detail_failed:${res.status}`)
      const detail = await res.json()
      const applied = this.applyPptMapRequestHistoryScope(detail, normalizedHistoryId)
      if (applied) {
        this.pptMapRequestHistoryRestoreCache = {
          ...cloneObject(this.pptMapRequestHistoryRestoreCache),
          [cacheKey]: true,
        }
      }
      return applied
    },
    async ensurePptMapRequestHistoryData(mapRequest = {}) {
      const historyId = this.pptMapRequestHistoryId(mapRequest)
      if (!historyId) return false
      const beforeMissing = this.pptMapRequestMissingLayers(mapRequest)
      const needsPoi = beforeMissing.some((item) => asText(item.target.kind) === 'poi_map')
      const needsArtifacts = beforeMissing.some((item) => asText(item.target.kind) !== 'poi_map')
      if (!beforeMissing.length && this.getAgentScopeBounds()) return true
      await this.ensurePptMapRequestHistoryScope(historyId)
      const token = Number(this.historyDetailLoadToken || 0) || 0
      const cache = cloneObject(this.pptMapRequestHistoryRestoreCache)
      if (needsArtifacts && typeof this.restoreHistoryArtifactsAsync === 'function') {
        const artifactKey = `artifacts:${historyId}`
        if (!cache[artifactKey]) {
          await this.restoreHistoryArtifactsAsync(historyId, token)
          cache[artifactKey] = true
        }
      }
      if (needsPoi && typeof this._restoreHistoryPoisAsync === 'function') {
        const poiKey = `pois:${historyId}:${asText(this.currentHistorySelectedPoiYear || this.resultPoiYear || '')}`
        if (!cache[poiKey]) {
          await this._restoreHistoryPoisAsync(historyId, token, null, 0, this.currentHistorySelectedPoiYear || this.resultPoiYear || null)
          cache[poiKey] = true
        }
      }
      this.pptMapRequestHistoryRestoreCache = cache
      return this.pptMapRequestMissingLayers(mapRequest).length === 0
    },
    renderPptMapRequestLayer(map = null, overlays = [], target = {}) {
      const kind = asText(target.kind)
      if (kind === 'overview_map') return this.getAgentScopeBounds() ? 1 : 0
      if (kind === 'poi_map') return this.renderAgentOffscreenPoiLayer(map, overlays)
      if (kind === 'h3_map') {
        return this.addAgentSnapshotPolygonFeatures(map, overlays, this.buildAgentOffscreenH3Features(), {
          strokeColor: '#475569',
          strokeWeight: 0.8,
          fillColor: '#bfdbfe',
          fillOpacity: 0.34,
          zIndex: 90,
        })
      }
      if (kind === 'population_map') {
        return this.addAgentSnapshotPolygonFeatures(map, overlays, this.buildAgentOffscreenPopulationFeatures(), {
          strokeColor: '#ffffff',
          strokeWeight: 0.7,
          fillColor: '#f4f6f8',
          fillOpacity: 0.20,
          zIndex: 90,
        })
      }
      if (kind === 'nightlight_map') {
        const container = map && typeof map.getContainer === 'function' ? map.getContainer() : null
        if (container) {
          container.style.backgroundColor = '#162033'
          container.style.backgroundImage = 'radial-gradient(circle at 52% 42%, rgba(251,191,36,0.1) 0%, rgba(35,49,74,0.82) 28%, rgba(22,32,51,0.94) 62%, rgba(10,15,27,1) 100%)'
        }
        return this.addAgentSnapshotPolygonFeatures(map, overlays, this.buildAgentOffscreenNightlightFeatures(), {
          strokeColor: '#94a3b8',
          strokeWeight: 0.7,
          fillColor: '#f59e0b',
          fillOpacity: 0.36,
          zIndex: 90,
        })
      }
      if (kind === 'road_map') return this.renderAgentOffscreenRoadLayer(map, overlays, asText(target.metric))
      return 0
    },
    createPptMapContainer(host = null, size = {}, options = {}) {
      if (!host || typeof document === 'undefined') return null
      const width = Math.max(320, Number(size.width || 960))
      const height = Math.max(320, Number(size.height || 960))
      const mapEl = document.createElement('div')
      mapEl.setAttribute('data-agent-ppt-map-container', '1')
      mapEl.style.cssText = [
        'position:relative',
        `width:${width}px`,
        `height:${height}px`,
        `background:${options.backgroundColor || '#ffffff'}`,
        'overflow:hidden',
        'transform:translateZ(0)',
      ].join(';')
      host.appendChild(mapEl)
      return mapEl
    },
    createPptMapSvgOverlay(mapEl = null, size = {}) {
      if (!mapEl || typeof document === 'undefined' || typeof document.createElementNS !== 'function') return null
      const width = Math.max(320, Number(size.width || 960))
      const height = Math.max(320, Number(size.height || 960))
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
      svg.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
      svg.setAttribute('width', String(width))
      svg.setAttribute('height', String(height))
      svg.setAttribute('viewBox', `0 0 ${width} ${height}`)
      svg.setAttribute('data-agent-ppt-svg-overlay', '1')
      svg.style.cssText = [
        'position:absolute',
        'inset:0',
        `width:${width}px`,
        `height:${height}px`,
        'pointer-events:none',
        'z-index:20',
        'overflow:hidden',
      ].join(';')
      if (mapEl.style) {
        mapEl.style.position = mapEl.style.position || 'relative'
      }
      mapEl.appendChild(svg)
      return svg
    },
    appendPptMapSvgNode(svg = null, tag = '', attrs = {}) {
      if (!svg || typeof document === 'undefined' || typeof document.createElementNS !== 'function') return null
      const node = document.createElementNS('http://www.w3.org/2000/svg', tag)
      Object.entries(attrs || {}).forEach(([key, value]) => {
        if (value === undefined || value === null || value === '') return
        node.setAttribute(key, String(value))
      })
      svg.appendChild(node)
      return node
    },
    projectPptMapSvgPoint(map = null, lngLat = null) {
      const point = this.normalizeAgentSnapshotLngLat(lngLat)
      if (!map || !point || typeof map.lngLatToContainer !== 'function') return null
      try {
        const amap = this.getAgentAmapSdk()
        const input = amap && typeof amap.LngLat === 'function'
          ? new amap.LngLat(point[0], point[1])
          : point
        const projected = map.lngLatToContainer(input)
        const rawX = projected && projected.x !== undefined
          ? projected.x
          : (projected && typeof projected.getX === 'function' ? projected.getX() : (projected && projected[0]))
        const rawY = projected && projected.y !== undefined
          ? projected.y
          : (projected && typeof projected.getY === 'function' ? projected.getY() : (projected && projected[1]))
        const x = Number(rawX)
        const y = Number(rawY)
        if (!Number.isFinite(x) || !Number.isFinite(y)) return null
        return [Math.round(x * 10) / 10, Math.round(y * 10) / 10]
      } catch (_) {
        return null
      }
    },
    pptMapSvgPathForRing(map = null, ring = []) {
      const points = (Array.isArray(ring) ? ring : []).map((point) => this.projectPptMapSvgPoint(map, point)).filter(Boolean)
      if (points.length < 3) return ''
      return points.map((point, index) => `${index === 0 ? 'M' : 'L'}${point[0]} ${point[1]}`).join(' ') + ' Z'
    },
    pptMapSvgPathForLine(map = null, line = []) {
      const points = (Array.isArray(line) ? line : []).map((point) => this.projectPptMapSvgPoint(map, point)).filter(Boolean)
      if (points.length < 2) return ''
      return points.map((point, index) => `${index === 0 ? 'M' : 'L'}${point[0]} ${point[1]}`).join(' ')
    },
    renderPptMapSvgScopeLayer(svg = null, map = null, options = {}) {
      const ring = this.buildAgentSnapshotScopeRing()
      const path = this.pptMapSvgPathForRing(map, ring)
      if (!path) return { renderedCount: 0, boundsCount: 0, warnings: ['scope_boundary_empty'] }
      this.appendPptMapSvgNode(svg, 'path', {
        d: path,
        fill: options.fill || '#f97316',
        'fill-opacity': options.fillOpacity ?? 0.055,
        stroke: options.stroke || '#ea580c',
        'stroke-width': options.strokeWidth || 3,
        'stroke-opacity': options.strokeOpacity ?? 0.92,
        'stroke-linejoin': 'round',
      })
      return { renderedCount: 1, boundsCount: 1, warnings: [] }
    },
    renderPptMapSvgPolygonFeatures(svg = null, map = null, features = [], style = {}) {
      let renderedCount = 0
      cloneArray(features).forEach((feature) => {
        const props = feature && typeof feature === 'object' ? (feature.properties || {}) : {}
        this.getAgentSnapshotFeatureRings(feature).forEach((ring) => {
          const path = this.pptMapSvgPathForRing(map, ring)
          if (!path) return
          this.appendPptMapSvgNode(svg, 'path', {
            d: path,
            fill: asText(props.fillColor) || style.fillColor || '#60a5fa',
            'fill-opacity': Number(props.fillOpacity ?? style.fillOpacity ?? 0.32),
            stroke: asText(props.strokeColor) || style.strokeColor || '#ffffff',
            'stroke-width': Number(props.strokeWeight ?? style.strokeWidth ?? style.strokeWeight ?? 0.8),
            'stroke-opacity': Number(props.strokeOpacity ?? style.strokeOpacity ?? 0.82),
            'stroke-linejoin': 'round',
            'vector-effect': 'non-scaling-stroke',
          })
          renderedCount += 1
        })
      })
      return { renderedCount, boundsCount: renderedCount, warnings: [] }
    },
    renderPptMapSvgPoiLayer(svg = null, map = null) {
      let renderedCount = 0
      cloneArray(this.allPoisDetails).slice(0, 5000).forEach((poi) => {
        const point = this.projectPptMapSvgPoint(map, poi && (poi.location || [poi.lng, poi.lat]))
        if (!point) return
        const color = this.getAgentSnapshotPoiColor(poi && (poi.type || poi.category || poi.type_name))
        this.appendPptMapSvgNode(svg, 'circle', {
          cx: point[0],
          cy: point[1],
          r: 4.2,
          fill: color,
          'fill-opacity': 0.82,
          stroke: '#ffffff',
          'stroke-width': 1.2,
          'stroke-opacity': 0.96,
        })
        renderedCount += 1
      })
      return { renderedCount, boundsCount: renderedCount, warnings: [] }
    },
    renderPptMapSvgRoadLayer(svg = null, map = null, metric = '') {
      let renderedCount = 0
      cloneArray(this.roadSyntaxRoadFeatures).forEach((feature) => {
        const props = (feature && feature.properties) || {}
        const style = this.getAgentRoadStyle(props, metric)
        this.getAgentSnapshotFeatureLines(feature).forEach((line) => {
          const path = this.pptMapSvgPathForLine(map, line)
          if (!path) return
          this.appendPptMapSvgNode(svg, 'path', {
            d: path,
            fill: 'none',
            stroke: style.strokeColor || '#2563eb',
            'stroke-width': Math.max(1.4, Number(style.strokeWeight || 2.2)),
            'stroke-opacity': Number(style.strokeOpacity ?? 0.82),
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
            'vector-effect': 'non-scaling-stroke',
          })
          renderedCount += 1
        })
      })
      return { renderedCount, boundsCount: renderedCount, warnings: [] }
    },
    getPptMapSvgLayerRenderers() {
      return {
        overview_map: (svg, map) => this.renderPptMapSvgScopeLayer(svg, map, { fillOpacity: 0.07, strokeWidth: 3.4 }),
        poi_map: (svg, map) => this.renderPptMapSvgPoiLayer(svg, map),
        h3_map: (svg, map) => this.renderPptMapSvgPolygonFeatures(svg, map, this.buildAgentOffscreenH3Features(), {
          strokeColor: '#334155',
          strokeWidth: 0.9,
          fillColor: '#60a5fa',
          fillOpacity: 0.36,
        }),
        population_map: (svg, map) => this.renderPptMapSvgPolygonFeatures(svg, map, this.buildAgentOffscreenPopulationFeatures(), {
          strokeColor: '#ffffff',
          strokeWidth: 0.75,
          fillColor: '#38bdf8',
          fillOpacity: 0.34,
        }),
        nightlight_map: (svg, map) => this.renderPptMapSvgPolygonFeatures(svg, map, this.buildAgentOffscreenNightlightFeatures(), {
          strokeColor: '#fde68a',
          strokeWidth: 0.7,
          fillColor: '#f59e0b',
          fillOpacity: 0.42,
          strokeOpacity: 0.72,
        }),
        road_map: (svg, map, target) => this.renderPptMapSvgRoadLayer(svg, map, asText(target && target.metric)),
      }
    },
    renderPptMapRequestSvgLayer(svg = null, map = null, target = {}, size = {}, mapRequest = {}) {
      const kind = asText(target.kind)
      const renderer = this.getPptMapSvgLayerRenderers()[kind]
      if (typeof renderer !== 'function') return { renderedCount: 0, boundsCount: 0, warnings: [`unsupported_layer:${kind}`] }
      return renderer(svg, map, target, size, mapRequest) || { renderedCount: 0, boundsCount: 0, warnings: [] }
    },
    async renderPptMapRequestSnapshot(mapRequest = {}) {
      if (!this.canCaptureAgentOffscreenVisualSnapshots()) {
        throw new Error('ppt_map_request_renderer_unavailable')
      }
      const layers = this.pptMapRequestLayerTargets(mapRequest)
      if (!layers.length) throw new Error('ppt_map_request_no_supported_layers')
      const missing = this.pptMapRequestMissingLayers(mapRequest)[0]
      if (missing) {
        throw new Error(`ppt_map_request_layer_data_missing:${this.pptMapRequestLayerType(missing.layer)}`)
      }
      const primaryTarget = (layers.find((item) => asText(item.target.kind) !== 'overview_map') || layers[0]).target
      const size = this.getAgentVisualSnapshotRenderSize()
      const host = this.createAgentOffscreenSnapshotHost(size)
      const overlays = []
      const fitOverlays = []
      let map = null
      let mapEl = null
      let svgOverlay = null
      const amap = this.getAgentAmapSdk()
      const capture = (typeof globalThis !== 'undefined' && typeof globalThis.html2canvas === 'function')
        ? globalThis.html2canvas
        : (typeof window !== 'undefined' && typeof window.html2canvas === 'function' ? window.html2canvas : null)
      try {
        const isNightlight = layers.some((item) => asText(item.target.kind) === 'nightlight_map')
        mapEl = this.createPptMapContainer(host, size, {
          backgroundColor: isNightlight ? '#162033' : '#ffffff',
        })
        if (!mapEl) throw new Error('ppt_map_request_renderer_unavailable')
        map = new amap.Map(mapEl, {
          zoom: 13,
          viewMode: '2D',
          resizeEnable: false,
          features: isNightlight ? ['bg', 'road'] : ['bg', 'point', 'road', 'building'],
        })
        const scopeOverlay = this.addAgentSnapshotScopeOverlay(map, overlays, {
          fillOpacity: 0,
          strokeOpacity: 0,
          strokeWeight: 0,
          zIndex: 180,
        })
        if (scopeOverlay) fitOverlays.push(scopeOverlay)
        this.fitAgentOffscreenSnapshotMap(map, asText(primaryTarget.fit) === 'road' ? [] : fitOverlays)
        if (map && typeof map.resize === 'function') {
          try { map.resize() } catch (_) {}
        }
        await this.waitForAgentOffscreenSnapshotPaint(mapEl, 1200)
        svgOverlay = this.createPptMapSvgOverlay(mapEl, size)
        if (!svgOverlay) throw new Error('ppt_map_request_renderer_unavailable')
        const scopeResult = this.renderPptMapSvgScopeLayer(svgOverlay, map, {
          fillOpacity: layers.length === 1 ? 0.075 : 0.035,
          strokeWidth: 3,
        })
        let renderedCount = Number(scopeResult.renderedCount || 0)
        let businessRenderedCount = 0
        layers.forEach((item) => {
          if (asText(item.target.kind) === 'overview_map') return
          const result = this.renderPptMapRequestSvgLayer(svgOverlay, map, item.target, size, mapRequest)
          const count = Number(result && result.renderedCount || 0)
          renderedCount += count
          businessRenderedCount += count
        })
        const hasBusinessLayer = layers.some((item) => asText(item.target.kind) !== 'overview_map')
        if (hasBusinessLayer ? businessRenderedCount <= 0 : renderedCount <= 0) {
          throw new Error('ppt_map_request_no_rendered_features')
        }
        await this.waitForAgentVisualSnapshotPaint()
        await this.waitForAgentOffscreenImages(mapEl, 3000)
        const canvas = await capture(mapEl, {
          useCORS: true,
          backgroundColor: isNightlight ? '#162033' : '#ffffff',
          scale: 1,
          logging: false,
          width: size.width,
          height: size.height,
          windowWidth: size.width,
          windowHeight: size.height,
          scrollX: 0,
          scrollY: 0,
          onclone: (clonedDocument) => {
            const clonedMap = clonedDocument && typeof clonedDocument.querySelector === 'function'
              ? clonedDocument.querySelector('[data-agent-ppt-map-container="1"]')
              : null
            if (clonedMap && clonedMap.style) {
              clonedMap.style.left = '0px'
              clonedMap.style.top = '0px'
              clonedMap.style.zIndex = '1'
            }
          },
        })
        if (!canvas || !Number(canvas.width) || !Number(canvas.height) || typeof canvas.toDataURL !== 'function') {
          throw new Error('ppt_map_snapshot_canvas_empty')
        }
        let rawDataUrl = ''
        try {
          rawDataUrl = canvas.toDataURL('image/png')
        } catch (error) {
          throw Object.assign(new Error('ppt_map_snapshot_canvas_tainted'), {
            cause: error,
            detail: asText(error && error.message ? error.message : error),
          })
        }
        if (!asText(rawDataUrl) || asText(rawDataUrl) === 'data:,') throw new Error('ppt_map_snapshot_data_url_empty')
        if (!asText(rawDataUrl).startsWith('data:image/png')) throw new Error('ppt_map_snapshot_capture_failed')
        if (typeof this.compressAgentVisualSnapshotDataUrl === 'function') {
          return await this.compressAgentVisualSnapshotDataUrl(rawDataUrl) || rawDataUrl
        }
        return rawDataUrl
      } finally {
        overlays.forEach((overlay) => {
          try {
            if (overlay && typeof overlay.setMap === 'function') overlay.setMap(null)
          } catch (_) {}
        })
        try {
          if (map && typeof map.destroy === 'function') map.destroy()
        } catch (_) {}
        if (host && host.parentNode) host.parentNode.removeChild(host)
      }
    },
    async captureAgentOffscreenVisualSnapshot(target = {}) {
      const size = this.getAgentVisualSnapshotRenderSize()
      const host = this.createAgentOffscreenSnapshotHost(size)
      const overlays = []
      let map = null
      const amap = this.getAgentAmapSdk()
      try {
        if (!amap || typeof amap.Map !== 'function') {
          throw new Error('offscreen_amap_unavailable')
        }
        map = new amap.Map(host, {
          zoom: 13,
          viewMode: '2D',
          resizeEnable: false,
          features: asText(target.kind) === 'nightlight_map' ? ['bg', 'road'] : ['bg', 'point', 'road', 'building'],
        })
        const fitOverlays = this.renderAgentOffscreenSnapshotTarget(map, target, overlays)
        this.fitAgentOffscreenSnapshotMap(map, fitOverlays)
        await this.waitForAgentOffscreenSnapshotPaint(host, 900)
        const canvas = await html2canvas(host, {
          useCORS: true,
          backgroundColor: asText(target.kind) === 'nightlight_map' ? '#162033' : '#ffffff',
          scale: 1,
          logging: false,
        })
        const dataUrl = canvas && typeof canvas.toDataURL === 'function' ? canvas.toDataURL('image/png') : ''
        if (!asText(dataUrl).startsWith('data:image/png')) {
          throw new Error(`${asText(target.kind) || 'map'}_capture_unavailable`)
        }
        return dataUrl
      } finally {
        overlays.forEach((overlay) => {
          try {
            if (overlay && typeof overlay.setMap === 'function') overlay.setMap(null)
          } catch (_) {}
        })
        try {
          if (map && typeof map.destroy === 'function') map.destroy()
        } catch (_) {}
        if (host && host.parentNode) host.parentNode.removeChild(host)
      }
    },
    async captureAgentOffscreenVisualSnapshots(targets = []) {
      const snapshots = []
      for (const target of cloneArray(targets)) {
        const warnings = []
        let dataUrl = ''
        try {
          const rawDataUrl = await this.captureAgentOffscreenVisualSnapshot(target)
          dataUrl = await this.compressAgentVisualSnapshotDataUrl(rawDataUrl)
          if (!dataUrl) warnings.push(`${asText(target.kind) || 'map'}_capture_too_large`)
        } catch (err) {
          const message = err && err.message ? err.message : String(err)
          warnings.push(`${asText(target.kind) || 'map'}_capture_failed: ${message}`)
        }
        snapshots.push({
          snapshot_id: `visual-${Date.now().toString(36)}-${snapshots.length + 1}`,
          kind: asText(target.kind),
          title: asText(target.title),
          data_url: dataUrl,
          source: 'frontend_offscreen_map',
          captured_at: new Date().toISOString(),
          bounds: asText(target.fit) === 'road' ? (this.getAgentRoadFeatureBounds() || this.getAgentScopeBounds() || {}) : (this.getAgentScopeBounds() || {}),
          warnings,
        })
      }
      return snapshots.slice(0, 12)
    },
    applyAgentVisualSnapshotPanelState(target = {}) {
      const key = asText(target.key)
      if (key === 'poi') {
        this.activeStep3Panel = 'poi'
        if (this.poiSubTab !== 'grid') this.poiSubTab = 'category'
      } else if (key === 'h3') {
        this.activeStep3Panel = 'poi'
        this.poiSubTab = 'grid'
      } else if (key === 'population') {
        this.activeStep3Panel = 'population'
      } else if (key === 'nightlight') {
        this.activeStep3Panel = 'nightlight'
      } else if (key === 'syntax') {
        this.activeStep3Panel = 'syntax'
      }
    },
    async prepareAgentVisualSnapshotTarget(target = {}) {
      const key = asText(target.key)
      this.applyAgentVisualSnapshotPanelState(target)
      if (key === 'syntax' && asText(target.metric)) {
        this.roadSyntaxMainTab = asText(target.metric)
        this.roadSyntaxMetric = asText(target.metric)
        this.roadSyntaxLastMetricTab = asText(target.metric)
      }
      if (key && typeof this.preloadAgentPanelContent === 'function') {
        await this.preloadAgentPanelContent({ key })
      }
      const bounds = target.fit === 'road'
        ? (this.getAgentRoadFeatureBounds() || this.getAgentScopeBounds())
        : this.getAgentScopeBounds()
      if (target.fit === 'road' && bounds) {
        await this.fitAgentMapToBounds(bounds)
      }
      await this.waitForAgentVisualSnapshotPaint()
      return bounds || {}
    },
    async compressAgentVisualSnapshotDataUrl(dataUrl = '') {
      const raw = asText(dataUrl)
      if (!raw.startsWith('data:image/')) return ''
      if (typeof document === 'undefined' || typeof Image === 'undefined') return raw
      return new Promise((resolve) => {
        const image = new Image()
        image.onload = () => {
          try {
            const maxEdge = 1280
            const scale = Math.min(1, maxEdge / Math.max(image.naturalWidth || image.width || maxEdge, image.naturalHeight || image.height || maxEdge))
            const width = Math.max(1, Math.round((image.naturalWidth || image.width || maxEdge) * scale))
            const height = Math.max(1, Math.round((image.naturalHeight || image.height || maxEdge) * scale))
            const canvas = document.createElement('canvas')
            canvas.width = width
            canvas.height = height
            const ctx = canvas.getContext('2d')
            if (!ctx) {
              resolve(raw)
              return
            }
            ctx.fillStyle = '#ffffff'
            ctx.fillRect(0, 0, width, height)
            ctx.drawImage(image, 0, 0, width, height)
            const qualities = [0.82, 0.76, 0.70]
            let best = raw
            for (const quality of qualities) {
              const next = canvas.toDataURL('image/jpeg', quality)
              if (next && next.length < best.length) best = next
              if (next && next.length <= 1500000) {
                resolve(next)
                return
              }
            }
            resolve(best.length <= 1500000 ? best : '')
          } catch (err) {
            console.warn('compress agent visual snapshot failed', err)
            resolve(raw.length <= 1500000 ? raw : '')
          }
        }
        image.onerror = () => resolve(raw.length <= 1500000 ? raw : '')
        image.src = raw
      })
    },
    async captureAgentMainMapVisualSnapshots(targets = null) {
      if (typeof this._captureMapSnapshotBase64 !== 'function') {
        return [{
          snapshot_id: `visual-${Date.now().toString(36)}-missing-capture`,
          kind: 'overview_map',
          title: '当前地图总览',
          data_url: '',
          source: 'frontend_map',
          captured_at: new Date().toISOString(),
          bounds: {},
          warnings: ['前端缺少地图截图方法，未能传入地图快照。'],
        }]
      }
      const view = this.getAgentMapViewState()
      const layerState = this.getAgentVisualLayerState()
      const snapshotTargets = cloneArray(targets).length ? cloneArray(targets) : this.buildAgentVisualSnapshotTargets()
      const snapshots = []
      try {
        for (const target of snapshotTargets) {
          const warnings = []
          let bounds = {}
          try {
            bounds = await this.prepareAgentVisualSnapshotTarget(target)
            const rawDataUrl = await this._captureMapSnapshotBase64()
            if (!rawDataUrl) {
              snapshots.push({
                snapshot_id: `visual-${Date.now().toString(36)}-${snapshots.length + 1}`,
                kind: asText(target.kind),
                title: asText(target.title),
                data_url: '',
                source: 'frontend_map',
                captured_at: new Date().toISOString(),
                bounds: bounds || {},
                warnings: ['地图截图方法未返回有效图片，已跳过该快照。'],
              })
              continue
            }
            const dataUrl = await this.compressAgentVisualSnapshotDataUrl(rawDataUrl)
            if (!dataUrl) {
              snapshots.push({
                snapshot_id: `visual-${Date.now().toString(36)}-${snapshots.length + 1}`,
                kind: asText(target.kind),
                title: asText(target.title),
                data_url: '',
                source: 'frontend_map',
                captured_at: new Date().toISOString(),
                bounds: bounds || {},
                warnings: ['地图快照生成后超过大小限制，已跳过直传。'],
              })
              continue
            }
            snapshots.push({
              snapshot_id: `visual-${Date.now().toString(36)}-${snapshots.length + 1}`,
              kind: asText(target.kind),
              title: asText(target.title),
              data_url: dataUrl,
              source: 'frontend_map',
              captured_at: new Date().toISOString(),
              bounds: bounds || {},
              warnings,
            })
          } catch (err) {
            console.warn('capture agent visual snapshot failed', target, err)
          }
        }
      } finally {
        await this.restoreAgentVisualLayerState(layerState)
        this.restoreAgentMapViewState(view)
        await this.waitForAgentVisualSnapshotPaint()
      }
      return snapshots.slice(0, 12)
    },
    async captureAgentVisualSnapshots(options = {}) {
      const targets = this.buildAgentVisualSnapshotTargets()
      if (this.canCaptureAgentOffscreenVisualSnapshots()) {
        return this.captureAgentOffscreenVisualSnapshots(targets)
      }
      if (options.allowMainMapFallback === false) {
        return [{
          snapshot_id: `visual-${Date.now().toString(36)}-offscreen-unavailable`,
          kind: 'overview_map',
          title: '地图视觉快照',
          data_url: '',
          source: 'frontend_offscreen_map',
          captured_at: new Date().toISOString(),
          bounds: {},
          warnings: ['offscreen_snapshot_unavailable_main_map_fallback_disabled'],
        }]
      }
      const snapshots = await this.captureAgentMainMapVisualSnapshots(targets)
      return cloneArray(snapshots).map((snapshot) => ({
        ...snapshot,
        warnings: [
          ...cloneArray(snapshot && snapshot.warnings).map((item) => asText(item)).filter(Boolean),
          'offscreen_snapshot_unavailable_fallback_to_main_map',
        ],
      }))
    },
    getCachedAgentVisualSnapshots(fingerprint = '') {
      const cache = this.agentVisualSnapshotCache && typeof this.agentVisualSnapshotCache === 'object'
        ? this.agentVisualSnapshotCache
        : {}
      if (asText(cache.status) !== 'ready') return []
      if (asText(cache.fingerprint) !== asText(fingerprint)) return []
      const normalized = this.normalizeAgentVisualSnapshotCache(cache)
      if (normalized.visual_snapshots.length !== cloneArray(cache.visual_snapshots || cache.visualSnapshots).length) {
        this.agentVisualSnapshotCache = normalized
      }
      return cloneArray(normalized.visual_snapshots)
    },
    invalidateAgentVisualSnapshotCache(reason = '') {
      this.agentVisualSnapshotCache = {
        status: 'invalidated',
        fingerprint: '',
        generated_at: '',
        visual_snapshots: [],
        warnings: asText(reason) ? [asText(reason)] : [],
      }
    },
    shouldMirrorAgentVisualSnapshotCacheForDev() {
      return !!(import.meta && import.meta.env && import.meta.env.DEV)
    },
    mirrorAgentVisualSnapshotCacheForDev(cache = {}) {
      if (typeof document === 'undefined' || !this.shouldMirrorAgentVisualSnapshotCacheForDev()) return
      let mirror = document.getElementById('__agent_visual_snapshot_cache__')
      if (!mirror) {
        mirror = document.createElement('script')
        mirror.id = '__agent_visual_snapshot_cache__'
        mirror.type = 'application/json'
        mirror.style.display = 'none'
        document.body.appendChild(mirror)
      }
      mirror.textContent = JSON.stringify(cache)
    },
    commitAgentVisualSnapshotCache(cache = {}) {
      const nextCache = this.normalizeAgentVisualSnapshotCache({
        status: asText(cache.status) || 'ready',
        fingerprint: asText(cache.fingerprint),
        generated_at: asText(cache.generated_at || cache.generatedAt) || new Date().toISOString(),
        visual_snapshots: cloneArray(cache.visual_snapshots || cache.visualSnapshots),
        warnings: cloneArray(cache.warnings).map((item) => asText(item)).filter(Boolean),
      })
      this.agentVisualSnapshotCache = nextCache
      this.mirrorAgentVisualSnapshotCacheForDev(nextCache)
      return nextCache
    },
    normalizeAgentVisualSnapshotCache(cache = {}) {
      const snapshots = cloneArray(cache.visual_snapshots || cache.visualSnapshots)
      const warnings = cloneArray(cache.warnings).map((item) => asText(item)).filter(Boolean)
      const validSnapshots = []
      snapshots.forEach((item) => {
        const snapshot = item && typeof item === 'object' ? { ...item } : {}
        const dataUrl = asText(snapshot.data_url || snapshot.dataUrl)
        if (dataUrl.startsWith('data:image/')) {
          snapshot.data_url = dataUrl
          validSnapshots.push(snapshot)
          return
        }
        const title = asText(snapshot.title || snapshot.kind || '地图快照')
        cloneArray(snapshot.warnings).forEach((warning) => {
          const text = asText(warning)
          if (text && !warnings.includes(text)) warnings.push(text)
        })
        const skipped = `${title} 未传入有效图片，已从视觉快照缓存中移除。`
        if (title && !warnings.includes(skipped)) warnings.push(skipped)
      })
      return {
        status: asText(cache.status) || 'ready',
        fingerprint: asText(cache.fingerprint),
        generated_at: asText(cache.generated_at || cache.generatedAt) || new Date().toISOString(),
        visual_snapshots: validSnapshots,
        warnings,
      }
    },
    async ensureAgentVisualSnapshotCache(options = {}) {
      const fingerprint = this.buildAgentVisualSnapshotFingerprint()
      const currentCache = this.agentVisualSnapshotCache && typeof this.agentVisualSnapshotCache === 'object'
        ? this.agentVisualSnapshotCache
        : {}
      if (asText(currentCache.status) === 'failed' && asText(currentCache.fingerprint) === fingerprint) {
        return []
      }
      const cached = this.getCachedAgentVisualSnapshots(fingerprint)
      if (cached.length) return cached

      const preparingItem = normalizeAgentThinkingItem({
        id: 'frontend-visual-snapshot-cache',
        phase: 'connecting',
        title: '准备地图视觉证据',
        detail: '第一次提问正在生成当前分析图层快照，后续追问会直接复用。',
        state: 'active',
      })
      if (this.activeAgentSessionId) {
        this.updateAgentSessionSnapshot(this.activeAgentSessionId, (session) => ({
          ...session,
          activityItems: upsertThinkingItemInList(session.activityItems, preparingItem),
        }))
      }

      try {
        const snapshots = await this.captureAgentVisualSnapshots(options)
        const normalizedCache = this.normalizeAgentVisualSnapshotCache({
          status: 'ready',
          fingerprint,
          visual_snapshots: snapshots,
        })
        const validSnapshots = cloneArray(normalizedCache.visual_snapshots)
        const warnings = cloneArray(normalizedCache.warnings).map((item) => asText(item)).filter(Boolean)
        this.commitAgentVisualSnapshotCache({
          status: 'ready',
          fingerprint,
          visual_snapshots: validSnapshots,
          warnings,
        })
        const completedItem = normalizeAgentThinkingItem({
          ...preparingItem,
          detail: validSnapshots.length
            ? `已生成 ${validSnapshots.length} 张地图视觉快照，本轮和后续追问将复用这组证据。`
            : '未生成可用地图视觉快照，本轮将继续使用结构化证据。',
          state: 'completed',
        })
        if (this.activeAgentSessionId) {
          this.updateAgentSessionSnapshot(this.activeAgentSessionId, (session) => ({
            ...session,
            activityItems: upsertThinkingItemInList(session.activityItems, completedItem),
          }))
        }
        return cloneArray(validSnapshots)
      } catch (snapshotErr) {
        const message = snapshotErr && snapshotErr.message ? snapshotErr.message : String(snapshotErr)
        console.warn('Agent visual snapshots failed; continuing text-only', snapshotErr)
        this.commitAgentVisualSnapshotCache({
          status: 'failed',
          fingerprint,
          visual_snapshots: [],
          warnings: [`地图视觉快照生成失败：${message}`],
        })
        const failedItem = normalizeAgentThinkingItem({
          ...preparingItem,
          detail: '地图视觉快照生成失败，本轮将继续使用文字与结构化证据。',
          state: 'completed',
        })
        if (this.activeAgentSessionId) {
          this.updateAgentSessionSnapshot(this.activeAgentSessionId, (session) => ({
            ...session,
            activityItems: upsertThinkingItemInList(session.activityItems, failedItem),
          }))
        }
        return []
      }
    },
    syncUiAfterTurn(turnContext = {}) {
      const targetSessionId = asText(turnContext.targetSessionId)
      this.stopAgentThinkingTimer(targetSessionId)
      const runState = this.getAgentRunState(targetSessionId)
      if (runState && runState.abortController === turnContext.requestAbortController) {
        this.clearAgentRunState(targetSessionId)
      }
      if (targetSessionId === asText(this.activeAgentSessionId)) {
        this.syncActiveAgentRuntimeView(targetSessionId)
      }
    },
    async submitMainAgentTurn(options = {}) {
      const turnContext = this.buildTurnContext(options)
      if (!turnContext) return null
      const {
        question,
        rawQuestion,
        panelKind,
        targetSessionId,
        wasPersisted,
        historyId,
        requestAbortController,
        nextMessages,
      } = turnContext
      const streamingMessageId = `codex-message-${Date.now().toString(36)}`
      let assistantText = ''
      let completed = false
      this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
        ...session,
        panelKind,
        persisted: wasPersisted,
        snapshotLoaded: true,
        historyId,
        input: '',
        messages: [...cloneArray(nextMessages), {
          id: streamingMessageId,
          role: 'assistant',
          content: '',
        }],
        answer: '',
        error: '',
        status: 'running',
        activityItems: [normalizeAgentThinkingItem({
          id: 'codex-turn',
          phase: 'executing',
          title: 'Codex 正在分析',
          detail: '正在读取项目数据并组织回答。',
          state: 'active',
        })],
      }))
      this.setAgentRunState(targetSessionId, {
        abortController: requestAbortController,
        loading: true,
        streamState: 'connecting',
        streamingMessageId,
      })
      this.agentTurnAbortController = requestAbortController
      this.agentInput = ''
      this.startAgentThinkingTimer(targetSessionId)
      try {
        const response = await postConversationTurnStream(this, turnContext, options || {})
        await this.consumeTurnStream(response, ({ type, payload }) => {
          if (type === 'thread') {
            this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
              ...session,
              persisted: true,
            }))
            return
          }
          if (type === 'turn_started') {
            this.setAgentRunState(targetSessionId, { streamState: 'streaming' })
            return
          }
          if (type === 'message_delta') {
            assistantText += String((payload && payload.delta) || '')
            this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
              ...session,
              messages: cloneArray(session.messages).some((message) => asText(message && message.id) === streamingMessageId)
                ? cloneArray(session.messages).map((message) => (
                  asText(message && message.id) === streamingMessageId
                    ? { ...message, content: assistantText }
                    : message
                ))
                : [...cloneArray(session.messages), {
                  id: streamingMessageId,
                  role: 'assistant',
                  content: assistantText,
                }],
            }))
            this.maybeAutoScrollAgentThread({ sessionId: targetSessionId })
            return
          }
          if (type === 'item_started' && payload && payload.type === 'mcpToolCall') {
            const toolName = asText(payload.tool) || '空间数据工具'
            this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
              ...session,
              activityItems: [normalizeAgentThinkingItem({
                id: asText(payload.id) || `mcp-${toolName}`,
                phase: 'executing',
                title: `调用 ${toolName}`,
                detail: '正在通过 spatial-project MCP 读取项目事实。',
                state: 'active',
              })],
            }))
            return
          }
          if (type === 'item_completed' && payload) {
            if (payload.type === 'agentMessage' && payload.text) {
              assistantText = String(payload.text)
              this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
                ...session,
                messages: cloneArray(session.messages).some((message) => asText(message && message.id) === streamingMessageId)
                  ? cloneArray(session.messages).map((message) => (
                    asText(message && message.id) === streamingMessageId
                      ? { ...message, content: assistantText }
                      : message
                  ))
                  : [...cloneArray(session.messages), {
                    id: streamingMessageId,
                    role: 'assistant',
                    content: assistantText,
                  }],
              }))
            } else if (payload.type === 'mcpToolCall') {
              this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
                ...session,
                activityItems: cloneArray(session.activityItems).map((item) => (
                  asText(item && item.id) === asText(payload.id)
                    ? { ...item, state: payload.error ? 'failed' : 'completed' }
                    : item
                )),
              }))
            }
            return
          }
          if (type === 'error') {
            throw new Error(asText(payload && payload.message) || 'Codex App Server 执行失败')
          }
          if (type !== 'turn_completed') return
          if (asText(payload && payload.status) !== 'completed') {
            throw new Error(asText(payload && payload.error) || `Codex turn ${asText(payload && payload.status) || 'failed'}`)
          }
          completed = true
          this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
            ...session,
            persisted: true,
            status: 'answered',
            messages: cloneArray(session.messages).filter((message) => (
              asText(message && message.id) !== streamingMessageId || !!asText(message && message.content)
            )),
            activityItems: cloneArray(session.activityItems).map((item) => ({
              ...item,
              state: item.state === 'active' ? 'completed' : item.state,
            })),
          }))
          this.setAgentRunState(targetSessionId, { streamState: 'completed' })
        })
        if (!completed) throw new Error('Codex turn 未返回完成事件')
        if (!wasPersisted) await this.loadAgentSessionSummaries(true)
        return { status: 'answered', answer: assistantText }
      } catch (error) {
        if (error && (error.name === 'AbortError' || String(error.message || '').toLowerCase().includes('aborted'))) {
          this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
            ...session,
            status: 'idle',
            input: rawQuestion || question,
            messages: cloneArray(session.messages).filter((message) => asText(message && message.id) !== streamingMessageId),
            activityItems: [],
          }))
          this.agentInput = rawQuestion || question
          return null
        }
        const message = `Agent 执行失败: ${error && error.message ? error.message : String(error)}`
        this.updateAgentSessionSnapshot(targetSessionId, (session) => ({
          ...session,
          status: 'failed',
          error: message,
          messages: cloneArray(session.messages).filter((item) => (
            asText(item && item.id) !== streamingMessageId || !!asText(item && item.content)
          )),
          activityItems: [],
        }))
        this.setAgentRunState(targetSessionId, { streamState: 'failed' })
        return null
      } finally {
        this.syncUiAfterTurn(turnContext)
      }
    },
    cancelAgentTurn(sessionId = '') {
      const runState = this.getAgentRunState(this.getActiveAgentSessionId(sessionId))
      const controller = runState && runState.abortController
      if (!controller) return
      try {
        controller.abort()
      } catch (_) {
        // Ignore abort errors from already-settled controllers.
      }
    },
  }
}

export { createAgentRuntimeMethods }
