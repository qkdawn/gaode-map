    function createAnalysisHistoryInitialState() {
        return {
            historyDetailAbortController: null,
            historyDetailLoadToken: 0,
            currentHistoryRecordId: '',
            currentHistoryPolygonWgs84: [],
            currentHistoryAvailablePoiYears: [],
            currentHistorySelectedPoiYear: null,
        };
    }

    function createAnalysisHistoryMethods() {
        return {
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
                const grid = (h3Result.grid && typeof h3Result.grid === 'object') ? h3Result.grid : {};
                const features = Array.isArray(grid.features) ? grid.features : [];
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
                return true;
            },
            async _restoreHistoryRoadResultAsync(roadResult, token) {
                if (token !== this.historyDetailLoadToken) return false;
                if (!roadResult || typeof roadResult !== 'object') return false;
                const roads = (roadResult.roads && typeof roadResult.roads === 'object') ? roadResult.roads : {};
                const nodes = (roadResult.nodes && typeof roadResult.nodes === 'object') ? roadResult.nodes : {};
                const summary = (roadResult.summary && typeof roadResult.summary === 'object') ? roadResult.summary : null;
                const roadFeatures = Array.isArray(roads.features) ? roads.features : [];
                const nodeFeatures = Array.isArray(nodes.features) ? nodes.features : [];
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
                    roads: {
                        type: 'FeatureCollection',
                        features: roadFeatures,
                    },
                    nodes: {
                        type: 'FeatureCollection',
                        features: nodeFeatures,
                    },
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
                const qs = Number.isFinite(Number(year)) ? `?year=${Number(year)}` : '';
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
                let controller = null;
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
                    this.poiStatus = '正在加载历史记录...';
                    await this.$nextTick();

                    controller = new AbortController();
                    const token = this.historyDetailLoadToken + 1;
                    this.historyDetailLoadToken = token;
                    this.historyDetailAbortController = controller;
                    const timerHost = (typeof window !== 'undefined' && typeof window.setTimeout === 'function')
                        ? window
                        : globalThis;
                    historyDetailTimeoutId = timerHost.setTimeout(() => {
                        if (token === this.historyDetailLoadToken && this.historyDetailAbortController === controller) {
                            controller.abort();
                        }
                    }, 30000);
                    historyDetailTimeoutId = { host: timerHost, id: historyDetailTimeoutId };

                    const res = await fetch(`/api/v1/analysis/history/${historyId}?include_pois=false`, {
                        signal: controller.signal
                    });
                    if (!res.ok) {
                        throw new Error(`历史详情请求失败(${res.status})`);
                    }
                    const data = await res.json();
                    if (!data || token !== this.historyDetailLoadToken) return;

                    this._applyHistoryDetailBaseResult(data);
                    this.currentHistoryRecordId = historyId;
                    if (this.lastIsochroneGeoJSON) {
                        this.scopeSource = 'history';
                    }
                    if (typeof this.resetAgentIterationChangeForHistorySwitch === 'function') {
                        this.resetAgentIterationChangeForHistorySwitch(historyId, { previousHistoryId });
                    }
                    baseRestored = true;
                    const restoredSnapshots = await this._restoreHistoryAnalysisSnapshotsAsync(data, token);
                    if (token !== this.historyDetailLoadToken) return;
                    this.currentHistoryRecordId = historyId;
                    if (this.lastIsochroneGeoJSON) {
                        this.scopeSource = 'history';
                    }
                    const poiCountHint = Math.max(
                        0,
                        Number((data && data.poi_count) || (((data || {}).poi_summary || {}).total) || 0)
                    );
                    const restoredTags = [];
                    if (restoredSnapshots.h3Restored) restoredTags.push('网格');
                    if (restoredSnapshots.roadRestored) restoredTags.push('路网');
                    const restoredText = restoredTags.length ? `（${restoredTags.join(' + ')}已恢复）` : '';
                    this.poiStatus = poiCountHint > 0
                        ? `历史主结果${restoredText}，正在加载历史 POI（${poiCountHint} 条）...`
                        : `历史主结果${restoredText}，正在检查 POI 数据...`;
                    await this.$nextTick();
                    await new Promise((resolve) => window.requestAnimationFrame(resolve));
                    await this._restoreHistoryPoisAsync(historyId, token, controller.signal, poiCountHint);

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
                    if (controller && this.historyDetailAbortController === controller) {
                        this.historyDetailAbortController = null;
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
