import {
    restoreFeatureCollection,
    restoreLayer,
} from './artifacts.js';

    function createAnalysisHistoryInitialState() {
        return {
            historyDetailAbortController: null,
            historyPoiAbortController: null,
            historyArtifactsAbortController: null,
            historyDetailLoadToken: 0,
            currentHistoryRecordId: '',
            currentHistoryPolygonWgs84: [],
            currentHistoryAvailablePoiYears: [],
            currentHistorySelectedPoiYear: null,
            historyRestoreProgress: {
                active: false,
                currentStep: '',
                totalSteps: 8,
                percent: 0,
                message: '',
                warnings: [],
                items: [
                    { key: 'base', label: '主结果', status: 'pending' },
                    { key: 'poi', label: 'POI 明细', status: 'pending' },
                    { key: 'artifacts', label: '分析产物', status: 'pending' },
                    { key: 'population', label: '人口', status: 'pending' },
                    { key: 'nightlight', label: '夜光', status: 'pending' },
                    { key: 'road', label: '路网', status: 'pending' },
                    { key: 'grid', label: '网格/H3', status: 'pending' },
                    { key: 'complete', label: '完成', status: 'pending' },
                ],
            },
        };
    }

    function createAnalysisHistoryMethods() {
        return {
            createHistoryRestoreProgressState(active = false) {
                return {
                    active: !!active,
                    currentStep: '',
                    totalSteps: 8,
                    percent: 0,
                    message: '',
                    warnings: [],
                    items: [
                        { key: 'base', label: '主结果', status: 'pending' },
                        { key: 'poi', label: 'POI 明细', status: 'pending' },
                        { key: 'artifacts', label: '分析产物', status: 'pending' },
                        { key: 'population', label: '人口', status: 'pending' },
                        { key: 'nightlight', label: '夜光', status: 'pending' },
                        { key: 'road', label: '路网', status: 'pending' },
                        { key: 'grid', label: '网格/H3', status: 'pending' },
                        { key: 'complete', label: '完成', status: 'pending' },
                    ],
                };
            },
            updateHistoryRestoreProgress(patch = {}) {
                const current = (this.historyRestoreProgress && typeof this.historyRestoreProgress === 'object')
                    ? this.historyRestoreProgress
                    : this.createHistoryRestoreProgressState(false);
                let items = Array.isArray(current.items) ? current.items.map((item) => ({ ...item })) : this.createHistoryRestoreProgressState(false).items;
                const updates = patch.items && typeof patch.items === 'object' ? patch.items : {};
                if (Object.keys(updates).length) {
                    items = items.map((item) => {
                        const update = updates[item.key];
                        return update && typeof update === 'object' ? { ...item, ...update } : item;
                    });
                }
                const completed = items.filter((item) => item.status === 'done' || item.status === 'failed' || item.status === 'skipped').length;
                const total = Number.isFinite(Number(patch.totalSteps)) ? Number(patch.totalSteps) : (Number(current.totalSteps) || items.length || 1);
                const active = patch.active !== undefined ? !!patch.active : !!current.active;
                const currentStepKey = String(patch.currentStep || current.currentStep || '');
                const currentStepIndex = items.findIndex((item) => String(item.key || '') === currentStepKey);
                const reachedSteps = currentStepIndex >= 0
                    ? Math.max(completed, currentStepIndex + 1)
                    : completed;
                const percent = Number.isFinite(Number(patch.percent))
                    ? Number(patch.percent)
                    : Math.round((reachedSteps / Math.max(1, total)) * 100);
                this.historyRestoreProgress = {
                    ...current,
                    ...patch,
                    active,
                    totalSteps: total,
                    percent: Math.max(0, Math.min(100, percent)),
                    warnings: Array.isArray(patch.warnings) ? patch.warnings : (Array.isArray(current.warnings) ? current.warnings : []),
                    items,
                };
            },
            setHistoryRestoreStep(key, status, message = '') {
                const nextMessage = String(message || '').trim();
                this.updateHistoryRestoreProgress({
                    active: status !== 'done' || key !== 'complete',
                    currentStep: key,
                    message: nextMessage || (this.historyRestoreProgress && this.historyRestoreProgress.message) || '',
                    items: { [key]: { status } },
                });
                if (nextMessage) {
                    this.poiStatus = nextMessage;
                }
            },
            appendHistoryRestoreWarning(message) {
                const text = String(message || '').trim();
                if (!text) return;
                const current = this.historyRestoreProgress && typeof this.historyRestoreProgress === 'object'
                    ? this.historyRestoreProgress
                    : this.createHistoryRestoreProgressState(true);
                const warnings = Array.isArray(current.warnings) ? current.warnings.slice() : [];
                if (!warnings.includes(text)) warnings.push(text);
                this.updateHistoryRestoreProgress({ warnings });
            },
            _resolveHistoryPreferredStep3Panel(data) {
                const params = (data && data.params && typeof data.params === 'object') ? data.params : {};
                const h3Result = (params && typeof params.h3_result === 'object') ? params.h3_result : null;
                const roadResult = (params && typeof params.road_result === 'object') ? params.road_result : null;
                const h3HasData = !!(h3Result && h3Result.grid && Array.isArray(h3Result.grid.features) && h3Result.grid.features.length)
                    || !!(h3Result && h3Result.summary);
                const roadHasData = !!(roadResult && roadResult.roads && Array.isArray(roadResult.roads.features) && roadResult.roads.features.length)
                    || !!(roadResult && roadResult.summary);
                const h3Ui = (h3Result && typeof h3Result.ui === 'object') ? h3Result.ui : {};
                const roadUi = (roadResult && typeof roadResult.ui === 'object') ? roadResult.ui : {};

                if (roadHasData && !!roadUi.panel_active) return 'syntax';
                if (h3HasData && !!h3Ui.panel_active) return 'poi';
                if (roadHasData && !h3HasData) return 'syntax';
                if (h3HasData && !roadHasData) return 'poi';
                return 'poi';
            },
            async _restoreHistoryH3ResultAsync(h3Result, token) {
                if (token !== this.historyDetailLoadToken) return false;
                if (!h3Result || typeof h3Result !== 'object') return false;
                const grid = restoreFeatureCollection(h3Result.grid, false);
                const features = Array.isArray(grid && grid.features) ? grid.features : [];
                const summary = (h3Result.summary && typeof h3Result.summary === 'object') ? h3Result.summary : null;
                if (!features.length && !summary) return false;

                this.h3AnalysisGridFeatures = features;
                this.h3GridFeatures = features;
                const countRaw = Number(grid.count);
                this.h3GridCount = Number.isFinite(countRaw) ? countRaw : features.length;
                this.h3AnalysisSummary = summary;
                this.h3AnalysisCharts = (h3Result.charts && typeof h3Result.charts === 'object') ? h3Result.charts : null;

                const resolutionRaw = Number(grid.resolution);
                if (Number.isFinite(resolutionRaw) && resolutionRaw >= 0) {
                    this.h3GridResolution = Math.round(resolutionRaw);
                }
                const includeModeRaw = String(grid.include_mode || '').trim().toLowerCase();
                if (includeModeRaw === 'inside' || includeModeRaw === 'intersects') {
                    this.h3GridIncludeMode = includeModeRaw;
                }
                const overlapRaw = Number(grid.min_overlap_ratio);
                if (Number.isFinite(overlapRaw)) {
                    this.h3GridMinOverlapRatio = Math.max(0, Math.min(1, overlapRaw));
                }

                const ui = (h3Result.ui && typeof h3Result.ui === 'object') ? h3Result.ui : {};
                const mainStage = String(ui.main_stage || '').trim().toLowerCase();
                if (['params', 'analysis', 'diagnosis', 'evaluate'].includes(mainStage)) {
                    this.h3MainStage = mainStage;
                }
                const subTab = String(ui.sub_tab || '').trim();
                if (subTab) {
                    this.h3SubTab = subTab;
                }
                const metricView = String(ui.metric_view || '').trim();
                if (metricView) {
                    this.h3MetricView = metricView;
                }
                const structureFillMode = String(ui.structure_fill_mode || '').trim();
                if (structureFillMode) {
                    this.h3StructureFillMode = structureFillMode;
                }
                const hasAnalysisSnapshot = !!summary
                    || !!(h3Result.charts && typeof h3Result.charts === 'object');
                if (hasAnalysisSnapshot && String(this.h3MainStage || '') === 'params') {
                    this.h3MainStage = 'analysis';
                }
                if (typeof this.computeH3DerivedStats === 'function') {
                    this.computeH3DerivedStats();
                }
                if (typeof this.ensureH3PanelEntryState === 'function') {
                    this.ensureH3PanelEntryState();
                }
                if (this.activeStep3Panel === 'poi' && String(this.poiSubTab || '').trim().toLowerCase() === 'grid') {
                    if (typeof this.renderH3BySubTab === 'function') {
                        this.renderH3BySubTab();
                    }
                    await this.$nextTick();
                    if (typeof this.updateH3Charts === 'function') {
                        this.updateH3Charts();
                    }
                    if (typeof this.updateDecisionCards === 'function') {
                        this.updateDecisionCards();
                    }
                }
                if (typeof this.commitCurrentPoiGridResult === 'function') {
                    const restoredYear = Number(
                        h3Result.year
                        || (h3Result.params && h3Result.params.year)
                        || this.currentHistorySelectedPoiYear
                        || this.resultPoiYear
                        || this.poiYearSource
                        || 0
                    );
                    this.commitCurrentPoiGridResult('h3', Number.isFinite(restoredYear) && restoredYear > 0 ? restoredYear : null);
                }
                return true;
            },
            async _restoreHistoryRoadResultAsync(roadResult, token) {
                if (token !== this.historyDetailLoadToken) return false;
                if (!roadResult || typeof roadResult !== 'object') return false;
                const roads = restoreFeatureCollection(roadResult.roads, false);
                const nodes = restoreFeatureCollection(roadResult.nodes, false);
                const summary = (roadResult.summary && typeof roadResult.summary === 'object') ? roadResult.summary : null;
                const roadFeatures = Array.isArray(roads && roads.features) ? roads.features : [];
                const nodeFeatures = Array.isArray(nodes && nodes.features) ? nodes.features : [];
                if (!summary && !roadFeatures.length && !nodeFeatures.length) return false;

                const ui = (roadResult.ui && typeof roadResult.ui === 'object') ? roadResult.ui : {};
                const graphModelRaw = String(ui.graph_model || '').trim().toLowerCase();
                if (graphModelRaw === 'axial' || graphModelRaw === 'segment') {
                    this.roadSyntaxGraphModel = graphModelRaw;
                }
                if (typeof this.clamp01 === 'function') {
                    const blue = Number(ui.display_blue);
                    const red = Number(ui.display_red);
                    if (Number.isFinite(blue)) this.roadSyntaxDisplayBlue = this.clamp01(blue);
                    if (Number.isFinite(red)) this.roadSyntaxDisplayRed = this.clamp01(red);
                }
                const colorScaleRaw = String(ui.color_scale || '').trim();
                if (colorScaleRaw) {
                    this.roadSyntaxDepthmapColorScale = colorScaleRaw;
                }

                const payload = {
                    summary: summary || {},
                    diagnostics: (roadResult.diagnostics && typeof roadResult.diagnostics === 'object')
                        ? roadResult.diagnostics
                        : {},
                    roads,
                    nodes,
                    webgl: (roadResult.webgl && typeof roadResult.webgl === 'object') ? roadResult.webgl : null,
                };
                const preferredMetricRaw = String(ui.metric || '').trim();
                const validMetricTabs = (typeof this.roadSyntaxMetricTabs === 'function')
                    ? this.roadSyntaxMetricTabs().map((item) => item.value)
                    : ['connectivity', 'control', 'depth', 'choice', 'integration', 'intelligibility'];
                const preferredMetric = validMetricTabs.includes(preferredMetricRaw)
                    ? preferredMetricRaw
                    : (typeof this.roadSyntaxDefaultMetric === 'function' ? this.roadSyntaxDefaultMetric() : 'connectivity');
                if (typeof this.applyRoadSyntaxResponseData === 'function') {
                    this.applyRoadSyntaxResponseData(payload, preferredMetric);
                } else {
                    this.roadSyntaxRoadFeatures = roadFeatures;
                    this.roadSyntaxNodes = nodeFeatures;
                    this.roadSyntaxSummary = summary || null;
                    this.roadSyntaxDiagnostics = payload.diagnostics || null;
                    this.roadSyntaxWebglPayload = payload.webgl;
                    this.roadSyntaxMetric = preferredMetric;
                    this.roadSyntaxLastMetricTab = preferredMetric;
                }

                const radiusLabelRaw = String(ui.radius_label || '').trim().toLowerCase();
                if (
                    radiusLabelRaw
                    && typeof this.roadSyntaxMetricUsesRadius === 'function'
                    && this.roadSyntaxMetricUsesRadius(this.roadSyntaxMetric)
                    && typeof this.roadSyntaxHasRadiusLabel === 'function'
                    && this.roadSyntaxHasRadiusLabel(radiusLabelRaw)
                ) {
                    this.roadSyntaxRadiusLabel = radiusLabelRaw;
                }

                const mainTabRaw = String(ui.main_tab || '').trim();
                const validTabs = (this.roadSyntaxTabs || []).map((tab) => tab.value);
                const hasRoadSnapshot = !!summary || roadFeatures.length > 0 || nodeFeatures.length > 0;
                const targetTab = (hasRoadSnapshot && mainTabRaw === 'params')
                    ? preferredMetric
                    : (validTabs.includes(mainTabRaw) ? mainTabRaw : preferredMetric);
                if (targetTab !== 'params') {
                    if (typeof this.setRoadSyntaxMainTab === 'function') {
                        this.setRoadSyntaxMainTab(targetTab, { refresh: false, syncMetric: true });
                    } else {
                        this.roadSyntaxMainTab = targetTab;
                    }
                    if (typeof this.roadSyntaxApplyRadiusCircle === 'function') {
                        this.roadSyntaxApplyRadiusCircle(this.roadSyntaxMetric);
                    }
                } else {
                    if (typeof this.setRoadSyntaxMainTab === 'function') {
                        this.setRoadSyntaxMainTab('params', { refresh: false, syncMetric: false });
                    } else {
                        this.roadSyntaxMainTab = 'params';
                    }
                }

                if (this.activeStep3Panel === 'syntax' && targetTab !== 'params' && typeof this.renderRoadSyntaxByMetric === 'function') {
                    await this.renderRoadSyntaxByMetric(this.roadSyntaxMetric || preferredMetric);
                } else if (
                    this.activeStep3Panel !== 'syntax'
                    && typeof this.suspendRoadSyntaxDisplay === 'function'
                    && !(typeof this.hasSimplifyDisplayTarget === 'function' && this.hasSimplifyDisplayTarget('syntax'))
                ) {
                    this.suspendRoadSyntaxDisplay();
                }
                return true;
            },
            async _restoreHistoryAnalysisSnapshotsAsync(data, token) {
                if (token !== this.historyDetailLoadToken) return { h3Restored: false, roadRestored: false };
                const params = (data && data.params && typeof data.params === 'object') ? data.params : {};
                const h3Result = (params && typeof params.h3_result === 'object') ? params.h3_result : null;
                const roadResult = (params && typeof params.road_result === 'object') ? params.road_result : null;
                // Keep user on POI panel when opening history from step 3.
                // H3/road snapshots are still restored into state for later manual switch.
                if (this.activeStep3Panel !== 'poi') {
                    this.activeStep3Panel = 'poi';
                    this.lastNonAgentStep3Panel = 'poi';
                    if (typeof this.resetAnalysisDisplayTargetsForPanel === 'function') {
                        this.resetAnalysisDisplayTargetsForPanel('poi', { apply: false });
                    }
                    this.applySimplifyConfig();
                    await this.$nextTick();
                }

                const h3Restored = await this._restoreHistoryH3ResultAsync(h3Result, token);
                const roadRestored = await this._restoreHistoryRoadResultAsync(roadResult, token);
                return { h3Restored, roadRestored };
            },
            getHistoryArtifactYear(artifact = {}) {
                const payload = artifact && artifact.payload && typeof artifact.payload === 'object' ? artifact.payload : {};
                const params = artifact && artifact.params && typeof artifact.params === 'object' ? artifact.params : {};
                const payloadParams = payload && payload.params && typeof payload.params === 'object' ? payload.params : {};
                const raw = payload.year || payloadParams.year || params.year;
                const year = Number(raw);
                return Number.isFinite(year) && year > 0 ? year : null;
            },
            getHistoryArtifactPreferredYear() {
                const year = Number(this.currentHistorySelectedPoiYear || this.resultPoiYear || this.poiYearSource || 0);
                return Number.isFinite(year) && year > 0 ? year : null;
            },
            pickLatestHistoryArtifact(artifacts = [], artifactType = '', options = {}) {
                const type = String(artifactType || '').trim();
                const candidates = (Array.isArray(artifacts) ? artifacts : [])
                    .filter((item) => item && String(item.artifact_type || '') === type)
                    .sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')));
                const preferredYear = Number(options.preferredYear || 0);
                if (Number.isFinite(preferredYear) && preferredYear > 0) {
                    const matched = candidates.find((item) => this.getHistoryArtifactYear(item) === preferredYear);
                    if (matched) return matched;
                }
                return candidates[0] || null;
            },
            pickLatestHistoryArtifactsByYear(artifacts = [], artifactType = '') {
                const type = String(artifactType || '').trim();
                const latestByYear = new Map();
                const unknown = [];
                for (const item of (Array.isArray(artifacts) ? artifacts : [])) {
                    if (!item || String(item.artifact_type || '') !== type) continue;
                    const year = this.getHistoryArtifactYear(item);
                    if (!year) {
                        unknown.push(item);
                        continue;
                    }
                    const existing = latestByYear.get(year);
                    if (!existing || String(item.updated_at || '').localeCompare(String(existing.updated_at || '')) > 0) {
                        latestByYear.set(year, item);
                    }
                }
                const rows = Array.from(latestByYear.values())
                    .sort((a, b) => (this.getHistoryArtifactYear(a) || 0) - (this.getHistoryArtifactYear(b) || 0));
                if (!rows.length && unknown.length) {
                    rows.push(unknown.sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')))[0]);
                }
                return rows;
            },
            async fetchHistoryArtifacts(historyId, signal = null) {
                const res = await fetch(`/api/v1/analysis/history/${encodeURIComponent(historyId)}/artifacts`, { signal });
                if (!res.ok) {
                    let detail = '';
                    try { detail = await res.text(); } catch (_) {}
                    throw new Error(`历史证据请求失败(${res.status})${detail ? `: ${detail}` : ''}`);
                }
                const data = await res.json();
                return Array.isArray(data) ? data : [];
            },
            async restoreHistoryPoiRasterArtifact(artifact, token, options = {}) {
                if (token !== this.historyDetailLoadToken || !artifact) return false;
                const payload = artifact.payload && typeof artifact.payload === 'object' ? artifact.payload : {};
                const grid = restoreFeatureCollection(payload.grid && typeof payload.grid === 'object' ? payload.grid : payload, false);
                const features = Array.isArray(grid && grid.features) ? grid.features : [];
                const summary = payload.summary && typeof payload.summary === 'object' ? payload.summary : (artifact.summary || null);
                const charts = payload.charts && typeof payload.charts === 'object' ? payload.charts : {};
                if (!features.length && !summary) return false;
                const restoredYear = this.getHistoryArtifactYear(artifact);
                const applyToProjection = options.applyToProjection !== false;
                const gridResult = {
                    status: 'ready',
                    features: features,
                    summary: summary || {},
                    charts: charts,
                    derivedStats: {},
                    params: artifact.params && typeof artifact.params === 'object' ? JSON.parse(JSON.stringify(artifact.params)) : {},
                    evidence: {},
                    error: '',
                    year: restoredYear,
                    gridType: 'shared',
                };
                if (typeof this.commitPoiGridResult === 'function') {
                    this.commitPoiGridResult(restoredYear, 'shared', gridResult);
                }
                if (!applyToProjection) return true;
                this.poiGridFeatures = features;
                this.poiGridSummary = summary || null;
                this.poiGridType = 'shared';
                this.h3AnalysisGridFeatures = features;
                this.h3GridFeatures = features;
                this.h3GridCount = Number((summary && summary.grid_count) || features.length || 0);
                this.h3AnalysisSummary = summary || null;
                this.h3AnalysisCharts = charts || null;
                if (typeof this.computeH3DerivedStats === 'function' && summary) {
                    this.computeH3DerivedStats();
                }
                if (typeof this.commitCurrentPoiGridResult === 'function') {
                    this.commitCurrentPoiGridResult('shared', restoredYear);
                }
                if (this.poiSubTab === 'grid' && typeof this.restoreH3GridDisplayOnEnter === 'function') {
                    this.restoreH3GridDisplayOnEnter();
                }
                return true;
            },
            buildHistoryH3PayloadFromArtifact(artifact) {
                if (!artifact || !artifact.payload || typeof artifact.payload !== 'object') return null;
                const payload = artifact.payload;
                return Object.assign(
                    {},
                    payload,
                    {
                        params: Object.assign(
                            {},
                            artifact.params && typeof artifact.params === 'object' ? artifact.params : {},
                            payload.params && typeof payload.params === 'object' ? payload.params : {}
                        ),
                        year: this.getHistoryArtifactYear(artifact),
                    }
                );
            },
            async restoreHistoryH3Artifact(artifact, token, options = {}) {
                if (token !== this.historyDetailLoadToken || !artifact) return false;
                const h3Payload = this.buildHistoryH3PayloadFromArtifact(artifact);
                if (!h3Payload) return false;
                const applyToProjection = options.applyToProjection !== false;
                if (applyToProjection) {
                    return this._restoreHistoryH3ResultAsync(h3Payload, token);
                }
                const grid = restoreFeatureCollection(h3Payload.grid, false);
                const features = Array.isArray(grid && grid.features) ? grid.features : [];
                const summary = h3Payload.summary && typeof h3Payload.summary === 'object' ? h3Payload.summary : {};
                if (!features.length && !Object.keys(summary).length) return false;
                if (typeof this.commitPoiGridResult === 'function') {
                    this.commitPoiGridResult(this.getHistoryArtifactYear(artifact), 'h3', {
                        status: 'ready',
                        features,
                        summary,
                        charts: h3Payload.charts && typeof h3Payload.charts === 'object' ? h3Payload.charts : {},
                        derivedStats: {},
                        params: h3Payload.params && typeof h3Payload.params === 'object' ? JSON.parse(JSON.stringify(h3Payload.params)) : {},
                        evidence: {},
                        error: '',
                        year: this.getHistoryArtifactYear(artifact),
                        gridType: 'h3',
                    });
                }
                return true;
            },
            async restoreHistoryPopulationArtifact(artifact, token) {
                if (token !== this.historyDetailLoadToken || !artifact) return false;
                const payload = artifact.payload && typeof artifact.payload === 'object' ? artifact.payload : {};
                const overview = payload.overview && typeof payload.overview === 'object' ? payload.overview : {};
                const summary = payload.summary && typeof payload.summary === 'object' ? payload.summary : {};
                const grid = restoreFeatureCollection(payload.grid, true);
                const layer = restoreLayer(payload.layer, true);
                if ((!Object.keys(overview).length && !Object.keys(summary).length) || !grid || !layer) return false;
                this.populationOverview = Object.keys(overview).length ? overview : { summary };
                this.populationGrid = grid;
                this.populationLayer = layer;
                this.populationGridCount = this.populationGrid.cell_count;
                this.populationScopeId = String(grid.scope_id || layer.scope_id || payload.scope_id || '');
                if (payload.year) this.populationSelectedYear = String(payload.year);
                if (payload.view) this.populationAnalysisView = String(payload.view);
                this.populationSubTab = 'analysis';
                if (typeof this.updatePopulationCharts === 'function') {
                    this.$nextTick(() => this.updatePopulationCharts());
                }
                return true;
            },
            async restoreHistoryNightlightArtifact(artifact, token) {
                if (token !== this.historyDetailLoadToken || !artifact) return false;
                const payload = artifact.payload && typeof artifact.payload === 'object' ? artifact.payload : {};
                const overview = payload.overview && typeof payload.overview === 'object' ? payload.overview : {};
                const summary = payload.summary && typeof payload.summary === 'object' ? payload.summary : {};
                const grid = restoreFeatureCollection(payload.grid, true);
                const layer = restoreLayer(payload.layer, true);
                if ((!Object.keys(overview).length && !Object.keys(summary).length) || !grid || !layer) return false;
                this.nightlightOverview = Object.keys(overview).length ? overview : { summary };
                this.nightlightGrid = grid;
                this.nightlightLayer = layer;
                this.nightlightGridCount = this.nightlightGrid.cell_count;
                this.nightlightScopeId = String(grid.scope_id || layer.scope_id || payload.scope_id || '');
                this.nightlightRaster = payload.raster && typeof payload.raster === 'object' ? payload.raster : null;
                if (payload.year) this.nightlightSelectedYear = Number(payload.year);
                if (payload.view) this.nightlightAnalysisView = String(payload.view);
                return true;
            },
            async restoreHistoryArtifactsAsync(historyId, token, signal = null) {
                if (token !== this.historyDetailLoadToken) {
                    return { rasterRestored: false, h3Restored: false, populationRestored: false, nightlightRestored: false, roadRestored: false };
                }
                let artifacts;
                try {
                    this.setHistoryRestoreStep('artifacts', 'running', '正在读取历史分析产物...');
                    artifacts = await this.fetchHistoryArtifacts(historyId, signal);
                    this.setHistoryRestoreStep('artifacts', 'done', '历史分析产物已读取，正在恢复各类结果...');
                } catch (e) {
                    if (e && (e.name === 'AbortError' || String(e.message || '').toLowerCase().includes('aborted'))) {
                        this.setHistoryRestoreStep('artifacts', 'failed', '历史分析产物读取已中断');
                        return { rasterRestored: false, h3Restored: false, populationRestored: false, nightlightRestored: false, roadRestored: false };
                    }
                    throw e;
                }
                if (token !== this.historyDetailLoadToken) {
                    return { rasterRestored: false, h3Restored: false, populationRestored: false, nightlightRestored: false, roadRestored: false };
                }
                const preferredYear = this.getHistoryArtifactPreferredYear();
                const rasterArtifacts = this.pickLatestHistoryArtifactsByYear(artifacts, 'poi_raster_grid');
                const preferredRaster = this.pickLatestHistoryArtifact(artifacts, 'poi_raster_grid', { preferredYear });
                let rasterRestored = false;
                this.setHistoryRestoreStep('grid', 'running', '正在恢复历史网格和 H3 结果...');
                for (const artifact of rasterArtifacts) {
                    const restored = await this.restoreHistoryPoiRasterArtifact(artifact, token, {
                        applyToProjection: artifact === preferredRaster,
                    });
                    rasterRestored = rasterRestored || restored;
                }
                const h3Artifacts = this.pickLatestHistoryArtifactsByYear(artifacts, 'poi_h3_grid');
                const preferredH3 = this.pickLatestHistoryArtifact(artifacts, 'poi_h3_grid', { preferredYear });
                let h3Restored = false;
                for (const artifact of h3Artifacts) {
                    const restored = await this.restoreHistoryH3Artifact(artifact, token, {
                        applyToProjection: artifact === preferredH3,
                    });
                    h3Restored = h3Restored || restored;
                }
                this.setHistoryRestoreStep('grid', (rasterRestored || h3Restored) ? 'done' : 'skipped', (rasterRestored || h3Restored) ? '历史网格和 H3 结果已恢复' : '该历史未找到可恢复的网格/H3 结果');
                this.setHistoryRestoreStep('population', 'running', '正在恢复历史人口结果...');
                const populationRestored = await this.restoreHistoryPopulationArtifact(this.pickLatestHistoryArtifact(artifacts, 'population'), token);
                this.setHistoryRestoreStep('population', populationRestored ? 'done' : 'skipped', populationRestored ? '历史人口结果已恢复' : '该历史未找到可恢复的人口结果');
                this.setHistoryRestoreStep('nightlight', 'running', '正在恢复历史夜光结果...');
                const nightlightRestored = await this.restoreHistoryNightlightArtifact(this.pickLatestHistoryArtifact(artifacts, 'nightlight'), token);
                this.setHistoryRestoreStep('nightlight', nightlightRestored ? 'done' : 'skipped', nightlightRestored ? '历史夜光结果已恢复' : '该历史未找到可恢复的夜光结果');
                this.setHistoryRestoreStep('road', 'running', '正在恢复历史路网结果...');
                const roadArtifact = this.pickLatestHistoryArtifact(artifacts, 'road_syntax');
                const roadRestored = await this._restoreHistoryRoadResultAsync(roadArtifact && roadArtifact.payload, token);
                this.setHistoryRestoreStep('road', roadRestored ? 'done' : 'skipped', roadRestored ? '历史路网结果已恢复' : '该历史未找到可恢复的路网结果');
                if (
                    token === this.historyDetailLoadToken
                    && (rasterRestored || h3Restored || populationRestored || nightlightRestored || roadRestored)
                    && typeof this.syncSummaryTaskBoardFromLocalResults === 'function'
                ) {
                    this.syncSummaryTaskBoardFromLocalResults({ sync: false });
                }
                return { rasterRestored, h3Restored, populationRestored, nightlightRestored, roadRestored };
            },
            _applyHistoryDetailBaseResult(data) {
                this.clearH3Grid();
                this.clearPoiOverlayLayers({
                    reason: 'load_history_detail',
                    clearManager: true,
                    clearSimpleMarkers: true,
                    clearCenterMarker: true,
                    resetFilterPanel: true
                });
                this.clearScopeOutlineDisplay();
                this.drawnScopePolygon = [];
                this.resetRoadSyntaxState();
                this.resetPopulationAnalysisState({ keepMeta: true, keepYear: true });
                this.resetNightlightAnalysisState({ keepMeta: true, keepYear: true });
                this.allPoisDetails = [];
                this.poiGridResultsByYearType = {};
                this.activePoiGridResultKey = '';
                this.currentHistoryAvailablePoiYears = Array.isArray(data && data.available_years)
                    ? data.available_years.map((item) => Number(item)).filter((item) => Number.isFinite(item))
                    : [];
                if (this.currentHistoryAvailablePoiYears.length) {
                    this.poiYearSelections = this.currentHistoryAvailablePoiYears.slice();
                }
                this.currentHistorySelectedPoiYear = Number.isFinite(Number(data && data.selected_year))
                    ? Number(data.selected_year)
                    : null;

                if (data.params && data.params.center) {
                    this.selectedPoint = { lng: data.params.center[0], lat: data.params.center[1] };
                    this.mapCore.map.setCenter(data.params.center);
                    this.mapCore.center = { lng: data.params.center[0], lat: data.params.center[1] };
                    this.mapCore.setRadius(0);
                    if (data.params.time_min) this.timeHorizon = data.params.time_min;
                    if (data.params.mode) this.transportMode = data.params.mode;
                }
                this.resultDataSource = this.normalizePoiSource(
                    data && data.params ? data.params.source : '',
                    'unknown'
                );
                this.poiDataSource = this.resultDataSource;
                this.resultPoiYear = Number.isFinite(Number(data && data.selected_year))
                    ? Number(data.selected_year)
                    : (Number.isFinite(Number(data && data.params ? data.params.year : null))
                        ? Number(data.params.year)
                        : (this.resultDataSource === 'gaode' ? 2026 : 2020));
                this.poiYearSource = String(this.resultPoiYear || 2020);
                const historyDrawnPolygon = this._closePolygonRing(this.normalizePath(
                    data && data.params ? data.params.drawn_polygon : [],
                    3,
                    'history.detail.drawn_polygon'
                ));
                const hasHistoryDrawnPolygon = Array.isArray(historyDrawnPolygon) && historyDrawnPolygon.length >= 4;
                this.drawnScopePolygon = hasHistoryDrawnPolygon ? historyDrawnPolygon.slice() : [];
                this.isochroneScopeMode = hasHistoryDrawnPolygon ? 'area' : 'point';

                if (data.polygon) {
                    const historyRings = this._normalizePolygonPayloadRings(
                        data.polygon,
                        'history.detail.polygon'
                    );
                    this.scopeSource = historyRings.length ? 'history' : '';
                    if (historyRings.length === 1) {
                        this.lastIsochroneGeoJSON = {
                            type: 'Feature',
                            properties: { mode: 'history' },
                            geometry: { type: 'Polygon', coordinates: [historyRings[0]] },
                        };
                    } else if (historyRings.length > 1) {
                        this.lastIsochroneGeoJSON = {
                            type: 'Feature',
                            properties: { mode: 'history' },
                            geometry: { type: 'MultiPolygon', coordinates: historyRings.map((ring) => [ring]) },
                        };
                    } else {
                        this.lastIsochroneGeoJSON = null;
                    }
                } else {
                    this.scopeSource = '';
                    this.lastIsochroneGeoJSON = null;
                }
                this.currentHistoryPolygonWgs84 = Array.isArray(data && data.polygon_wgs84)
                    ? JSON.parse(JSON.stringify(data.polygon_wgs84))
                    : [];
                this.applySimplifyConfig();

                this.step = 2;
                this.sidebarView = 'wizard';
                this.activeStep3Panel = 'poi';
                this.lastNonAgentStep3Panel = 'poi';
                if (typeof this.resetAnalysisDisplayTargetsForPanel === 'function') {
                    this.resetAnalysisDisplayTargetsForPanel('poi', { apply: false });
                }
                this.applySimplifyConfig();
            },
            async _restoreHistoryPoisAsync(id, token, signal, poiCountHint = 0, year = null) {
                const normalizedYear = year === null || year === undefined || year === ''
                    ? null
                    : Number(year);
                const qs = Number.isFinite(normalizedYear) ? `?year=${normalizedYear}` : '';
                const res = await fetch(`/api/v1/analysis/history/${id}/pois${qs}`, { signal });
                if (!res.ok) {
                    let detail = '';
                    try {
                        const payload = await res.clone().json();
                        detail = String((payload && payload.detail) || '').trim();
                    } catch (_) {
                        try {
                            detail = String(await res.text() || '').trim();
                        } catch (_) {}
                    }
                    throw new Error(`历史 POI 请求失败(${res.status})${detail ? `: ${detail}` : ''}`);
                }
                const data = await res.json();
                if (token !== this.historyDetailLoadToken) return;

                const pois = Array.isArray(data && data.pois) ? data.pois : [];
                this.allPoisDetails = pois;
                this.currentHistoryAvailablePoiYears = Array.isArray(data && data.available_years)
                    ? data.available_years.map((item) => Number(item)).filter((item) => Number.isFinite(item))
                    : this.currentHistoryAvailablePoiYears;
                if (this.currentHistoryAvailablePoiYears.length) {
                    this.poiYearSelections = this.currentHistoryAvailablePoiYears.slice();
                }
                this.currentHistorySelectedPoiYear = Number.isFinite(Number(data && data.selected_year))
                    ? Number(data.selected_year)
                    : this.currentHistorySelectedPoiYear;
                if (Number.isFinite(Number(this.currentHistorySelectedPoiYear))) {
                    this.resultPoiYear = Number(this.currentHistorySelectedPoiYear);
                    this.poiYearSource = String(this.currentHistorySelectedPoiYear);
                }

                if (!pois.length) {
                    this.poiStatus = poiCountHint > 0
                        ? `历史主结果已恢复，但未取到 POI 明细（期望 ${poiCountHint} 条）`
                        : '该历史无 POI 数据';
                    return;
                }

                this.rebuildPoiRuntimeSystem(pois);
                if (token !== this.historyDetailLoadToken) return;
                this.recomputePoiKdeStats();
                this.poiStatus = '';
                this.applySimplifyConfig();
                setTimeout(() => this.resizePoiChart(), 0);
            },
            async loadCurrentHistoryPoiYear(year) {
                const historyId = String(this.currentHistoryRecordId || '').trim();
                if (!historyId) return;
                if (!this.historyDetailAbortController) {
                    this.historyDetailAbortController = new AbortController();
                }
                const token = this.historyDetailLoadToken;
                const targetYear = Number.isFinite(Number(year)) ? Number(year) : null;
                this.poiStatus = targetYear
                    ? `正在切换历史 POI 年份：${targetYear} 年`
                    : '正在切换历史 POI 年份';
                await this._restoreHistoryPoisAsync(historyId, token, this.historyDetailAbortController.signal, 0, targetYear);
                this.poiStatus = '';
            },
            async loadHistoryDetail(id) {
                const historyId = String(id || '').trim();
                if (!historyId) return;
                let detailController = null;
                let poiController = null;
                let artifactsController = null;
                let baseRestored = false;
                let historyDetailTimeoutId = null;
                const previousHistoryId = String(this.currentHistoryRecordId || '').trim();
                try {
                    this.currentHistoryRecordId = historyId;
                    this.currentHistoryPolygonWgs84 = [];
                    this.currentHistoryAvailablePoiYears = [];
                    this.currentHistorySelectedPoiYear = null;
                    this.cancelHistoryLoading();
                    this.cancelHistoryDetailLoading();
                    this.stopScopeDrawing();
                    this.clearIsochroneDebugState();
                    this.errorMessage = '';
                    if (!this.mapCore || !this.mapCore.map) {
                        this.errorMessage = '地图尚未初始化，请稍后重试';
                        return;
                    }
                    // Give immediate feedback when opening history from result step:
                    // switch back to workbench first, then stream in restored data.
                    this.step = 2;
                    this.sidebarView = 'wizard';
                    this.activeStep3Panel = 'poi';
                    this.lastNonAgentStep3Panel = 'poi';
                    if (typeof this.resetAnalysisDisplayTargetsForPanel === 'function') {
                        this.resetAnalysisDisplayTargetsForPanel('poi', { apply: false });
                    }
                    this.applySimplifyConfig();
                    this.historyRestoreProgress = this.createHistoryRestoreProgressState(true);
                    this.setHistoryRestoreStep('base', 'running', '正在加载历史主结果...');
                    await this.$nextTick();

                    detailController = new AbortController();
                    const token = this.historyDetailLoadToken + 1;
                    this.historyDetailLoadToken = token;
                    this.historyDetailAbortController = detailController;
                    const timerHost = (typeof window !== 'undefined' && typeof window.setTimeout === 'function')
                        ? window
                        : globalThis;
                    historyDetailTimeoutId = timerHost.setTimeout(() => {
                        if (token === this.historyDetailLoadToken && this.historyDetailAbortController === detailController) {
                            detailController.abort();
                        }
                    }, 30000);
                    historyDetailTimeoutId = { host: timerHost, id: historyDetailTimeoutId };

                    const res = await fetch(`/api/v1/analysis/history/${historyId}?include_pois=false`, {
                        signal: detailController.signal
                    });
                    if (!res.ok) {
                        throw new Error(`历史详情请求失败(${res.status})`);
                    }
                    const data = await res.json();
                    if (!data || token !== this.historyDetailLoadToken) return;

                    this._applyHistoryDetailBaseResult(data);
                    this.setHistoryRestoreStep('base', 'done', '历史主结果已恢复');
                    this.currentHistoryRecordId = historyId;
                    if (this.lastIsochroneGeoJSON) {
                        this.scopeSource = 'history';
                    }
                    if (typeof this.resetAgentIterationChangeForHistorySwitch === 'function') {
                        this.resetAgentIterationChangeForHistorySwitch(historyId, { previousHistoryId });
                    }
                    baseRestored = true;
                    const poiCountHint = Math.max(
                        0,
                        Number((data && data.poi_count) || (((data || {}).poi_summary || {}).total) || 0)
                    );
                    await this.$nextTick();
                    await new Promise((resolve) => window.requestAnimationFrame(resolve));
                    this.setHistoryRestoreStep('poi', 'running', poiCountHint > 0
                        ? `正在加载历史 POI（${poiCountHint} 条）...`
                        : '正在检查历史 POI 数据...');
                    poiController = new AbortController();
                    artifactsController = new AbortController();
                    this.historyPoiAbortController = poiController;
                    this.historyArtifactsAbortController = artifactsController;
                    const poiPromise = this._restoreHistoryPoisAsync(historyId, token, poiController.signal, poiCountHint)
                        .then(() => {
                            if (token !== this.historyDetailLoadToken) return false;
                            const hasPois = Array.isArray(this.allPoisDetails) && this.allPoisDetails.length > 0;
                            this.setHistoryRestoreStep('poi', hasPois ? 'done' : 'skipped', hasPois ? `历史 POI 已恢复（${this.allPoisDetails.length} 条）` : '该历史无可恢复 POI 明细');
                            return true;
                        })
                        .catch((poiErr) => {
                            console.warn('history POI restore failed', poiErr);
                            const message = poiErr && poiErr.message ? poiErr.message : String(poiErr || '');
                            this.setHistoryRestoreStep('poi', 'failed', '历史 POI 恢复失败，其他分析结果继续恢复');
                            this.appendHistoryRestoreWarning(message ? `POI 恢复失败：${message}` : 'POI 恢复失败');
                            return false;
                        });
                    const artifactPromise = (async () => {
                        const legacySnapshots = { h3Restored: false, roadRestored: false };
                        try {
                            this.setHistoryRestoreStep('artifacts', 'running', '正在恢复历史分析快照和分析产物...');
                            const restored = await this._restoreHistoryAnalysisSnapshotsAsync(data, token);
                            legacySnapshots.h3Restored = !!(restored && restored.h3Restored);
                            legacySnapshots.roadRestored = !!(restored && restored.roadRestored);
                        } catch (legacyErr) {
                            console.warn('history legacy snapshots restore failed', legacyErr);
                            const message = legacyErr && legacyErr.message ? legacyErr.message : String(legacyErr || '');
                            this.appendHistoryRestoreWarning(message ? `历史快照恢复失败：${message}` : '历史快照恢复失败');
                        }
                        if (token !== this.historyDetailLoadToken) return legacySnapshots;
                        const artifactSnapshots = await this.restoreHistoryArtifactsAsync(historyId, token, artifactsController.signal);
                        return {
                            h3Restored: artifactSnapshots.h3Restored || legacySnapshots.h3Restored,
                            roadRestored: artifactSnapshots.roadRestored || legacySnapshots.roadRestored,
                            rasterRestored: artifactSnapshots.rasterRestored,
                            populationRestored: artifactSnapshots.populationRestored,
                            nightlightRestored: artifactSnapshots.nightlightRestored,
                        };
                    })()
                        .catch((artifactErr) => {
                            if (artifactErr && (artifactErr.name === 'AbortError' || String(artifactErr.message || '').toLowerCase().includes('aborted'))) throw artifactErr;
                            console.warn('history artifacts restore failed', artifactErr);
                            const message = artifactErr && artifactErr.message ? artifactErr.message : String(artifactErr || '');
                            this.setHistoryRestoreStep('artifacts', 'failed', '历史分析产物恢复失败，POI 可继续使用');
                            this.appendHistoryRestoreWarning(message ? `分析产物恢复失败：${message}` : '分析产物恢复失败');
                            return {
                                h3Restored: false,
                                roadRestored: false,
                                rasterRestored: false,
                                populationRestored: false,
                                nightlightRestored: false,
                            };
                        });
                    await Promise.all([poiPromise, artifactPromise]);
                    if (token === this.historyDetailLoadToken) {
                        this.setHistoryRestoreStep('complete', 'done', this.historyRestoreProgress && this.historyRestoreProgress.warnings && this.historyRestoreProgress.warnings.length
                            ? '历史恢复完成，部分内容有提示'
                            : '历史恢复完成');
                        this.updateHistoryRestoreProgress({ active: false, percent: 100 });
                    }
                    if (token === this.historyDetailLoadToken && typeof this.syncSummaryTaskBoardFromLocalResults === 'function') {
                        this.syncSummaryTaskBoardFromLocalResults({ sync: false });
                    }

                } catch (e) {
                    if (e && e.name === 'AbortError') {
                        if (baseRestored && this.step === 2 && this.lastIsochroneGeoJSON) {
                            this.poiStatus = '历史主结果已恢复，但 POI 加载超时，可稍后重试';
                        } else {
                            this.poiStatus = '';
                            this.errorMessage = '加载历史超时，请检查远端数据库连接或稍后重试';
                        }
                        return;
                    }
                    console.error(e);
                    const message = (e && e.message) ? e.message : String(e || '');
                    if (baseRestored && this.step === 2 && this.lastIsochroneGeoJSON) {
                        this.poiStatus = message
                            ? `历史主结果已恢复，但 POI 恢复失败：${message}`
                            : '历史主结果已恢复，但 POI 恢复失败，可稍后重试';
                    } else {
                        this.errorMessage = `加载历史失败: ${message || e}`;
                    }
                } finally {
                    if (historyDetailTimeoutId !== null) {
                        historyDetailTimeoutId.host.clearTimeout(historyDetailTimeoutId.id);
                    }
                    if (baseRestored) {
                        this.currentHistoryRecordId = historyId;
                        if (this.lastIsochroneGeoJSON) {
                            this.scopeSource = 'history';
                        }
                    }
                    if (detailController && this.historyDetailAbortController === detailController) {
                        this.historyDetailAbortController = null;
                    }
                    if (poiController && this.historyPoiAbortController === poiController) {
                        this.historyPoiAbortController = null;
                    }
                    if (artifactsController && this.historyArtifactsAbortController === artifactsController) {
                        this.historyArtifactsAbortController = null;
                    }
                }
            },
            formatHistoryTitle(desc) {
                if (!desc) return '无标题分析';
                return desc.replace(/^\d+min Analysis - /, '');
            },
        };
    }

export { createAnalysisHistoryInitialState, createAnalysisHistoryMethods };
