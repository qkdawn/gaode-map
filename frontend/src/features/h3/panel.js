    function createAnalysisH3InitialState() {
        return {
            isGeneratingGrid: false,
            h3GridStatus: '',
            h3GridCount: 0,
            h3GridResolution: 10,
            h3GridIncludeMode: 'intersects',
            h3NeighborRing: 1,
            h3GridMinOverlapRatio: 0.15,
            h3ParamsSubTab: 'grid',
            h3ArcgisImageVersion: 0,
            h3ArcgisSnapshotLoadError: false,
            isGeneratingH3ArcgisSnapshot: false,
            h3BasemapMuted: false,
            h3SimplifyMenuOpen: false,
            h3SimplifyTargets: ['map', 'isochrone', 'drawn_polygon', 'poi'],
            h3SimplifyTargetsInitialized: false,
            h3GridFeatures: [],
            selectedH3Id: null,
            isComputingH3Analysis: false,
            h3AnalysisSummary: null,
            h3AnalysisCharts: null,
            h3AnalysisGridFeatures: [],
            h3AnalysisProgress: null,
            h3MainStage: 'params',
            h3MainStageLabels: {
                params: '参数',
                analysis: '分析',
                diagnosis: '诊断',
                evaluate: '评估',
            },
            h3MainStageTabs: {
                params: [],
                analysis: ['metric_map', 'structure_map'],
                diagnosis: ['typing', 'lq'],
                evaluate: ['gap'],
            },
            h3SubTabLabels: {
                metric_map: '密度场',
                structure_map: '结构图',
                typing: '功能混合度',
                lq: '区位商优势（LQ）',
                gap: '缺口优先区',
            },
            h3MetricView: 'density',
            h3StructureFillMode: 'gi_z',
            h3Legend: null,
            h3StructureRenderStats: null,
            h3EntropyMinPoi: 3,
            h3SubTab: 'metric_map',
            h3TargetCategory: '',
            h3DecisionTopN: 10,
            h3OnlySignificant: false,
            h3LqSmoothingAlpha: 0.5,
            h3CategoryMeta: [],
            h3GapWeights: { transport: 0.4, life: 0.25, education: 0.2, medical: 0.15 },
            h3DerivedStats: {
                structureSummary: null,
                typingSummary: null,
                lqSummary: null,
                gapSummary: null,
                topCells: {},
            },
            h3CategoryChart: null,
            h3DensityChart: null,
            h3LqChart: null,
            h3GapChart: null,
            h3StructureChart: null,
            h3ChartsResizeHandler: null,
            h3ChartsRetryTimer: null,
            h3ChartsRetryCount: 0,
            h3PoiFilterCategoryIds: [],
        };
    }

    function createAnalysisH3Methods() {
        return {
            _buildDefaultH3CategoryMeta() {
                const fromTypeMap = (this.typeMapGroups || []).map((group) => ({
                    key: String(group.id || ''),
                    label: String(group.title || group.id || ''),
                })).filter(item => item.key && item.label);
                if (fromTypeMap.length) return fromTypeMap;
                return [
                    { key: 'group-7', label: '餐饮' },
                    { key: 'group-6', label: '购物' },
                    { key: 'group-4', label: '商务住宅' },
                    { key: 'group-3', label: '交通' },
                    { key: 'group-2', label: '旅游' },
                    { key: 'group-13', label: '科教文化' },
                    { key: 'group-10', label: '医疗' },
                ];
            },
            _resolveDefaultH3TargetCategory() {
                const categories = Array.isArray(this.h3CategoryMeta) ? this.h3CategoryMeta : [];
                if (!categories.length) return '';
                const dining = categories.find(item => this._normalizeCategoryTitle(item.label) === '餐饮');
                if (dining && dining.key) return dining.key;
                return String((categories[0] && categories[0].key) || '');
            },
            _ensureH3CategoryState() {
                if (!Array.isArray(this.h3CategoryMeta) || !this.h3CategoryMeta.length) {
                    this.h3CategoryMeta = this._buildDefaultH3CategoryMeta();
                }
                const hasCurrentTarget = (this.h3CategoryMeta || []).some(item => String(item.key) === String(this.h3TargetCategory));
                if (!hasCurrentTarget) {
                    this.h3TargetCategory = this._resolveDefaultH3TargetCategory();
                }
            },
            _resolveGapDemandCategoryMap() {
                const aliases = {
                    transport: '交通',
                    life: '商务住宅',
                    education: '科教文化',
                    medical: '医疗',
                };
                const labelToKey = {};
                (this.h3CategoryMeta || []).forEach((item) => {
                    const normalized = this._normalizeCategoryTitle(item.label);
                    if (!normalized || !item.key || labelToKey[normalized]) return;
                    labelToKey[normalized] = String(item.key);
                });
                const mapping = {};
                const missingTitles = [];
                Object.entries(aliases).forEach(([weightKey, title]) => {
                    const normalized = this._normalizeCategoryTitle(title);
                    const key = labelToKey[normalized];
                    if (key) {
                        mapping[weightKey] = key;
                    } else {
                        missingTitles.push(title);
                    }
                });
                return { mapping, missingTitles };
            },
            syncH3PoiFilterSelection(forceAll = false) {
                const ids = (this.poiCategories || [])
                    .map((cat) => String((cat && cat.id) || ''))
                    .filter(Boolean);
                if (!ids.length) {
                    this.h3PoiFilterCategoryIds = [];
                    return;
                }
                if (forceAll || !Array.isArray(this.h3PoiFilterCategoryIds) || this.h3PoiFilterCategoryIds.length === 0) {
                    this.h3PoiFilterCategoryIds = ids.slice();
                    return;
                }
                const currentSet = new Set(
                    this.h3PoiFilterCategoryIds
                        .map((id) => String(id || ''))
                        .filter(Boolean)
                );
                const kept = ids.filter((id) => currentSet.has(id));
                this.h3PoiFilterCategoryIds = kept.length ? kept : ids.slice();
            },
            selectAllH3PoiFilters() {
                this.syncH3PoiFilterSelection(true);
            },
            clearH3PoiFilters() {
                this.h3PoiFilterCategoryIds = [];
            },
            _getH3PoiFilterSet() {
                return new Set(
                    (this.h3PoiFilterCategoryIds || [])
                        .map((id) => String(id || ''))
                        .filter(Boolean)
                );
            },
            _buildH3AnalysisPois() {
                const source = Array.isArray(this.allPoisDetails) ? this.allPoisDetails : [];
                if (!source.length) return [];
                const selectedCategoryIds = this._getH3PoiFilterSet();
                if (!selectedCategoryIds.size) return [];
                return source.filter((poi) => {
                    const categoryId = String(this.resolvePoiCategoryId(poi && poi.type) || '');
                    return categoryId && selectedCategoryIds.has(categoryId);
                });
            },
            getH3FilteredPoiCount() {
                return this._buildH3AnalysisPois().length;
            },
            resetH3AnalysisState() {
                this.isComputingH3Analysis = false;
                this.h3AnalysisSummary = null;
                this.h3AnalysisCharts = null;
                this.h3AnalysisGridFeatures = [];
                this.selectedH3Id = null;
                this.h3MainStage = 'params';
                this.h3MetricView = 'density';
                this.h3StructureFillMode = 'gi_z';
                this.h3ParamsSubTab = 'grid';
                this.h3SubTab = 'metric_map';
                this._ensureH3CategoryState();
                this.h3TargetCategory = this._resolveDefaultH3TargetCategory();
                this.h3DecisionTopN = 10;
                this.h3OnlySignificant = false;
                this.h3Legend = null;
                this.h3DerivedStats = {
                    structureSummary: null,
                    typingSummary: null,
                    lqSummary: null,
                    gapSummary: null,
                    topCells: {},
                };
                this.disposeH3Charts();
            },
            clearH3Grid() {
                this.h3GridFeatures = [];
                this.h3GridCount = 0;
                this.h3GridStatus = '';
                this.h3ExportMenuOpen = false;
                this._normalizeExportBundleParts();
                this.resetH3AnalysisState();
                if (this.mapCore && this.mapCore.clearGridPolygons) {
                    this.mapCore.clearGridPolygons();
                }
                this.applySimplifyConfig();
            },
            isH3PanelActive() {
                const activePanel = String(this.activeStep3Panel || '');
                const poiSubTab = String(this.poiSubTab || '').trim().toLowerCase();
                return this.step === 2 && activePanel === 'poi' && poiSubTab === 'grid';
            },
            isH3DisplayActive() {
                return this.step === 2
                    && (typeof this.hasSimplifyDisplayTarget === 'function'
                        ? this.hasSimplifyDisplayTarget('h3')
                        : this.isH3PanelActive());
            },
            getDefaultSimplifyTargets() {
                return ['map', 'isochrone', 'drawn_polygon', 'poi'];
            },
            getSimplifyAnalysisTargets() {
                return ['h3', 'population', 'nightlight', 'gwr', 'timeseries', 'syntax'];
            },
            getSimplifyGridAnalysisTargets() {
                return ['h3', 'population', 'nightlight', 'gwr', 'timeseries'];
            },
            getAllowedSimplifyTargets() {
                return [
                    ...this.getDefaultSimplifyTargets(),
                    ...this.getSimplifyAnalysisTargets(),
                ];
            },
            extractSimplifyBaseTargets(targets = null) {
                const source = Array.isArray(targets)
                    ? targets
                    : this.normalizeSimplifyTargets();
                const analysisTargets = new Set(this.getSimplifyAnalysisTargets());
                return source.filter((item) => !analysisTargets.has(String(item || '').trim().toLowerCase()));
            },
            resolveSimplifyAnalysisTargetForPanel(panelId = '', options = {}) {
                const panel = String(panelId || '').trim().toLowerCase();
                const openPoiGrid = !!(options && options.openPoiGrid);
                const poiSubTab = openPoiGrid
                    ? 'grid'
                    : String(this.poiSubTab || '').trim().toLowerCase();
                if (panel === 'population') return 'population';
                if (panel === 'nightlight') return 'nightlight';
                if (panel === 'gwr') return 'gwr';
                if (panel === 'timeseries') return 'timeseries';
                if (panel === 'syntax') return 'syntax';
                if (panel === 'poi' && poiSubTab === 'grid') return 'h3';
                return '';
            },
            resetAnalysisDisplayTargetsForPanel(panelId = '', options = {}) {
                const next = this.extractSimplifyBaseTargets().slice();
                const analysisTarget = this.resolveSimplifyAnalysisTargetForPanel(panelId, options);
                if (analysisTarget) next.push(analysisTarget);
                this.h3SimplifyTargets = next;
                this.h3SimplifyTargetsInitialized = true;
                if (!options || options.apply !== false) {
                    this.applySimplifyConfig();
                }
                return next;
            },
            hasSimplifyDisplayTarget(target) {
                const key = String(target || '').trim().toLowerCase();
                if (!key) return false;
                return this.normalizeSimplifyTargets().includes(key);
            },
            enableSimplifyDisplayTarget(target, enabled = true, options = {}) {
                const key = String(target || '').trim().toLowerCase();
                if (!key) return;
                const next = this.normalizeSimplifyTargets().slice();
                const existingIndex = next.indexOf(key);
                if (enabled) {
                    if (existingIndex < 0) next.push(key);
                } else if (existingIndex >= 0) {
                    next.splice(existingIndex, 1);
                }

                if (enabled && this.getSimplifyGridAnalysisTargets().includes(key)) {
                    this.getSimplifyGridAnalysisTargets().forEach((item) => {
                        if (item === key) return;
                        const idx = next.indexOf(item);
                        if (idx >= 0) next.splice(idx, 1);
                    });
                }

                this.h3SimplifyTargets = next;
                this.h3SimplifyTargetsInitialized = true;
                if (!options || options.apply !== false) {
                    this.applySimplifyConfig();
                }
            },
            clearH3GridDisplayOnLeave() {
                if (!this.mapCore || typeof this.mapCore.clearGridPolygons !== 'function') return;
                this.mapCore.clearGridPolygons();
            },
            restoreH3GridDisplayOnEnter() {
                if (this.isPoiRasterGridMode && this.isPoiRasterGridMode()) {
                    if (typeof this.restorePoiRasterGridDisplayOnEnter === 'function') {
                        this.restorePoiRasterGridDisplayOnEnter();
                    }
                    return;
                }
                if (!this.isH3DisplayActive()) return;
                if (!this.mapCore) return;
                const shouldRenderAnalysis = this.h3MainStage !== 'params'
                    && Array.isArray(this.h3AnalysisGridFeatures)
                    && this.h3AnalysisGridFeatures.length > 0;
                if (shouldRenderAnalysis) {
                    this.renderH3BySubTab();
                    if (this.isH3PanelActive()) {
                        this.$nextTick(() => {
                            this.updateH3Charts();
                            this.updateDecisionCards();
                        });
                    }
                    return;
                }
                const plainGridFeatures = Array.isArray(this.h3GridFeatures) && this.h3GridFeatures.length
                    ? this.h3GridFeatures
                    : (Array.isArray(this.h3AnalysisGridFeatures) ? this.h3AnalysisGridFeatures : []);
                if (plainGridFeatures.length && typeof this.mapCore.setGridFeatures === 'function') {
                    this.mapCore.setGridFeatures(plainGridFeatures, {
                        strokeColor: '#2c6ecb',
                        strokeWeight: 1.1,
                        fillOpacity: 0,
                        webglBatch: true,
                    });
                }
            },
            ensureH3PanelEntryState() {
                if (this.isPoiRasterGridMode && this.isPoiRasterGridMode()) {
                    return;
                }
                this._ensureH3CategoryState();
                const hasAnalysis = Array.isArray(this.h3AnalysisGridFeatures)
                    && this.h3AnalysisGridFeatures.length > 0
                    && (!!this.h3AnalysisSummary || !!this.h3AnalysisCharts);
                const stage = String(this.h3MainStage || '').trim();
                if (!hasAnalysis) {
                    this.h3MainStage = 'params';
                    this.h3ParamsSubTab = String(this.h3ParamsSubTab || 'grid') === 'analysis' ? 'analysis' : 'grid';
                    this.h3SubTab = 'metric_map';
                    return;
                }
                if (!['analysis', 'diagnosis', 'evaluate'].includes(stage)) {
                    this.h3MainStage = 'analysis';
                }
                const validTabs = this.getH3CurrentStageTabs();
                if (!Array.isArray(validTabs) || !validTabs.includes(this.h3SubTab)) {
                    this.h3SubTab = this.getH3DefaultSubTabByStage(this.h3MainStage);
                }
                if (!this.h3DerivedStats || typeof this.h3DerivedStats !== 'object') {
                    this.computeH3DerivedStats();
                }
            },
            async applyH3AnalysisResultPayload(h3Result, options = {}) {
                const payload = h3Result && typeof h3Result === 'object' ? h3Result : {};
                const grid = payload.grid && typeof payload.grid === 'object' ? payload.grid : {};
                const features = Array.isArray(grid.features) ? grid.features : [];
                const summary = payload.summary && typeof payload.summary === 'object' ? payload.summary : null;
                if (!features.length && !summary) return false;

                this.h3AnalysisGridFeatures = features;
                this.h3GridFeatures = features;
                const countRaw = Number(grid.count);
                this.h3GridCount = Number.isFinite(countRaw) ? countRaw : features.length;
                this.h3AnalysisSummary = summary;
                this.h3AnalysisCharts = (payload.charts && typeof payload.charts === 'object') ? payload.charts : null;

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

                const ui = (payload.ui && typeof payload.ui === 'object') ? payload.ui : {};
                const targetCategory = String(options.targetCategory || ui.target_category || '').trim();
                if (targetCategory) {
                    this.h3TargetCategory = targetCategory;
                }
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
                this._ensureH3CategoryState();
                this.computeH3DerivedStats();
                this.ensureH3PanelEntryState();
                if (this.activeStep3Panel === 'poi' && String(this.poiSubTab || '').trim().toLowerCase() === 'grid') {
                    this.renderH3BySubTab();
                    await this.$nextTick();
                    this.updateH3Charts();
                    this.updateDecisionCards();
                }
                return true;
            },
            async ensureH3ReadyForAgentTarget(agentPayloads = {}, options = {}) {
                const payloads = agentPayloads && typeof agentPayloads === 'object' ? agentPayloads : {};
                const h3Result = (payloads.h3_result && typeof payloads.h3_result === 'object')
                    ? payloads.h3_result
                    : ((payloads.h3Result && typeof payloads.h3Result === 'object') ? payloads.h3Result : payloads);
                const hydrated = await this.applyH3AnalysisResultPayload(h3Result, options);
                if (hydrated) return true;
                if (!options.allowCompute) return false;
                const targetCategory = String(options.targetCategory || ((h3Result.ui || {}).target_category || '')).trim();
                if (targetCategory) {
                    this.h3TargetCategory = targetCategory;
                }
                this._ensureH3CategoryState();
                if (typeof this.selectAllH3PoiFilters === 'function') {
                    this.selectAllH3PoiFilters();
                }
                if (typeof this.generateH3Grid === 'function') {
                    await this.generateH3Grid();
                }
                if (typeof this.computeH3Analysis === 'function') {
                    await this.computeH3Analysis();
                }
                return !!(Array.isArray(this.h3AnalysisGridFeatures) && this.h3AnalysisGridFeatures.length)
                    || !!this.h3AnalysisSummary;
            },
            async onH3ResolutionChange() {
                const rawRing = this.getIsochronePolygonRing();
                if (!rawRing) {
                    this.clearH3Grid();
                    this.h3GridStatus = '请先完成范围分析后再生成网格';
                    return;
                }
                if (this.isComputingH3Analysis) {
                    this.h3GridStatus = '正在计算网格分析，请稍后再调整网格级别';
                    return;
                }
                this.h3GridStatus = `网格级别已切换为 res=${this.h3GridResolution}，正在自动刷新网格...`;
                await this.generateH3Grid();
            },
            onH3GridSettingsChange() {
                this.clearH3Grid();
                if (this.h3GridIncludeMode === 'inside') {
                    this.h3GridStatus = `已切换到“完全包含（严格）”，请点击“计算分析”`;
                } else {
                    this.h3GridStatus = `已切换到“相交优先（边缘保留）”，最小重叠比例=${this.h3GridMinOverlapRatio.toFixed(2)}，请点击“计算分析”`;
                }
            },
            shouldShowDrawnPolygonSimplifyOption() {
                return (
                    this.isochroneScopeMode === 'area'
                    && Array.isArray(this.drawnScopePolygon)
                    && this.drawnScopePolygon.length >= 3
                );
            },
            hasIsochroneOutlineForSimplifyOption() {
                return this.extractIsochroneOutlinePaths().length > 0;
            },
            getVisibleSimplifyOptions() {
                const options = [{ value: 'map', label: '地图' }];
                if (this.hasIsochroneOutlineForSimplifyOption()) {
                    options.push({ value: 'isochrone', label: '等时圈' });
                }
                if (this.shouldShowDrawnPolygonSimplifyOption()) {
                    options.push({ value: 'drawn_polygon', label: '手绘多边形' });
                }
                options.push(
                    { value: 'poi', label: 'POI' },
                    { value: 'h3', label: '网格' },
                    { value: 'population', label: '人口' },
                    { value: 'nightlight', label: '夜光' },
                    { value: 'syntax', label: '路网' },
                );
                return options;
            },
            normalizeSimplifyTargets() {
                const rawTargets = Array.isArray(this.h3SimplifyTargets) ? this.h3SimplifyTargets : [];
                const allowed = new Set(this.getAllowedSimplifyTargets());
                const normalized = [];
                const source = (!this.h3SimplifyTargetsInitialized && rawTargets.length === 0)
                    ? this.getDefaultSimplifyTargets()
                    : rawTargets;
                source.forEach((item) => {
                    const key = String(item || '').trim().toLowerCase();
                    if (!allowed.has(key)) return;
                    if (this.getSimplifyGridAnalysisTargets().includes(key)) {
                        this.getSimplifyGridAnalysisTargets().forEach((item) => {
                            if (item === key) return;
                            const idx = normalized.indexOf(item);
                            if (idx >= 0) normalized.splice(idx, 1);
                        });
                    }
                    if (normalized.indexOf(key) >= 0) return;
                    normalized.push(key);
                });
                const changed = (
                    normalized.length !== rawTargets.length
                    || normalized.some((item, index) => item !== rawTargets[index])
                );
                if (changed) {
                    this.h3SimplifyTargets = normalized;
                }
                if (!this.h3SimplifyTargetsInitialized) {
                    this.h3SimplifyTargetsInitialized = true;
                }
                return normalized;
            },
            toggleSimplifyMenu() {
                if (this.h3SimplifyMenuOpen) {
                    this.h3SimplifyMenuOpen = false;
                    return;
                }
                this.normalizeSimplifyTargets();
                this.h3ExportMenuOpen = false;
                this.h3SimplifyMenuOpen = true;
            },
            onSimplifyTargetToggle(target, checked) {
                const key = String(target || '').trim().toLowerCase();
                const allowed = new Set(this.getAllowedSimplifyTargets());
                if (!allowed.has(key)) return;
                this.enableSimplifyDisplayTarget(key, !!checked);
            },
            applySimplifyConfig() {
                const targets = this.normalizeSimplifyTargets();
                const showMap = targets.indexOf('map') >= 0;
                this.pointSimplifyEnabled = !showMap;
                this.h3BasemapMuted = !showMap;
                if (String(this.activeStep3Panel || '') === 'syntax') {
                    const showPoiInSyntax = targets.indexOf('poi') >= 0;
                    if (showPoiInSyntax) {
                        if (typeof this.resumePoiSystemAfterSyntax === 'function') {
                            this.resumePoiSystemAfterSyntax();
                        }
                    } else if (typeof this.suspendPoiSystemForSyntax === 'function') {
                        this.suspendPoiSystemForSyntax();
                    }
                }
                this.applySimplifyBasemapStyle();
                this.applySimplifyPointVisibility();
                this.refreshScopeOutlineDisplay();
                this.syncSimplifyResultLayerVisibility(targets);
            },
            syncSimplifyResultLayerVisibility(targets) {
                const normalizedTargets = Array.isArray(targets) ? targets : this.normalizeSimplifyTargets();
                const showH3 = this.step === 2 && normalizedTargets.indexOf('h3') >= 0;
                const showPopulation = this.step === 2 && normalizedTargets.indexOf('population') >= 0;
                const showNightlight = this.step === 2 && normalizedTargets.indexOf('nightlight') >= 0;
                const showGwr = this.step === 2 && normalizedTargets.indexOf('gwr') >= 0;
                const showTimeseries = this.step === 2 && normalizedTargets.indexOf('timeseries') >= 0;
                const showSyntax = this.step === 2 && normalizedTargets.indexOf('syntax') >= 0;

                const clearGridDisplay = () => {
                    if (this.isPoiRasterGridMode && this.isPoiRasterGridMode()) {
                        if (typeof this.clearPoiRasterGridDisplayOnLeave === 'function') this.clearPoiRasterGridDisplayOnLeave();
                    } else {
                        this.clearH3GridDisplayOnLeave();
                    }
                };

                if (showPopulation) {
                    clearGridDisplay();
                    this.clearNightlightDisplayOnLeave();
                    if (typeof this.clearGwrDisplayOnLeave === 'function') this.clearGwrDisplayOnLeave();
                    if (typeof this.clearTimeseriesDisplayOnLeave === 'function') this.clearTimeseriesDisplayOnLeave();
                    this.restorePopulationRasterDisplayOnEnter();
                } else if (showNightlight) {
                    clearGridDisplay();
                    this.clearPopulationRasterDisplayOnLeave();
                    if (typeof this.clearGwrDisplayOnLeave === 'function') this.clearGwrDisplayOnLeave();
                    if (typeof this.clearTimeseriesDisplayOnLeave === 'function') this.clearTimeseriesDisplayOnLeave();
                    this.restoreNightlightDisplayOnEnter();
                } else if (showGwr) {
                    clearGridDisplay();
                    this.clearPopulationRasterDisplayOnLeave();
                    this.clearNightlightDisplayOnLeave();
                    if (typeof this.clearTimeseriesDisplayOnLeave === 'function') this.clearTimeseriesDisplayOnLeave();
                    if (typeof this.restoreGwrDisplayOnEnter === 'function') this.restoreGwrDisplayOnEnter();
                } else if (showTimeseries) {
                    clearGridDisplay();
                    this.clearPopulationRasterDisplayOnLeave();
                    this.clearNightlightDisplayOnLeave();
                    if (typeof this.clearGwrDisplayOnLeave === 'function') this.clearGwrDisplayOnLeave();
                    if (typeof this.restoreTimeseriesDisplayOnEnter === 'function') this.restoreTimeseriesDisplayOnEnter();
                } else if (showH3) {
                    this.clearPopulationRasterDisplayOnLeave();
                    this.clearNightlightDisplayOnLeave();
                    if (typeof this.clearGwrDisplayOnLeave === 'function') this.clearGwrDisplayOnLeave();
                    if (typeof this.clearTimeseriesDisplayOnLeave === 'function') this.clearTimeseriesDisplayOnLeave();
                    this.restoreH3GridDisplayOnEnter();
                } else {
                    clearGridDisplay();
                    this.clearPopulationRasterDisplayOnLeave();
                    this.clearNightlightDisplayOnLeave();
                    if (typeof this.clearGwrDisplayOnLeave === 'function') this.clearGwrDisplayOnLeave();
                    if (typeof this.clearTimeseriesDisplayOnLeave === 'function') this.clearTimeseriesDisplayOnLeave();
                }

                if (showSyntax) {
                    if (typeof this.resumeRoadSyntaxDisplay === 'function') {
                        this.resumeRoadSyntaxDisplay();
                    }
                } else if (typeof this.suspendRoadSyntaxDisplay === 'function') {
                    this.suspendRoadSyntaxDisplay();
                }
            },
            extractIsochroneOutlinePaths() {
                const feature = this.lastIsochroneGeoJSON || null;
                const geometry = feature && feature.geometry ? feature.geometry : null;
                if (!geometry || !geometry.type) return [];
                const mode = String(((feature && feature.properties) || {}).mode || '').toLowerCase();
                if (mode === 'drawn_polygon') return [];
                const paths = [];
                if (geometry.type === 'Polygon' && Array.isArray(geometry.coordinates) && Array.isArray(geometry.coordinates[0])) {
                    const ring = this._closePolygonRing(this.normalizePath(geometry.coordinates[0], 3, 'scope.outline.iso.polygon'));
                    if (Array.isArray(ring) && ring.length >= 4) paths.push(ring.map((pt) => [Number(pt[0]), Number(pt[1])]));
                } else if (geometry.type === 'MultiPolygon' && Array.isArray(geometry.coordinates)) {
                    geometry.coordinates.forEach((poly, idx) => {
                        const rawRing = Array.isArray(poly) ? poly[0] : null;
                        const ring = this._closePolygonRing(this.normalizePath(rawRing, 3, `scope.outline.iso.multi_${idx}`));
                        if (Array.isArray(ring) && ring.length >= 4) {
                            paths.push(ring.map((pt) => [Number(pt[0]), Number(pt[1])]));
                        }
                    });
                }
                return paths;
            },
            refreshScopeOutlineDisplay() {
                if (!this.mapCore) return;
                const canClear = typeof this.mapCore.clearCustomPolygons === 'function';
                const canSet = typeof this.mapCore.setCustomPolygons === 'function';
                const targets = this.normalizeSimplifyTargets();
                const showDrawnPolygon = targets.indexOf('drawn_polygon') >= 0;
                const showIsochrone = targets.indexOf('isochrone') >= 0;
                const paths = [];

                if (showDrawnPolygon && this.shouldShowDrawnPolygonSimplifyOption()) {
                    const drawnRing = this._closePolygonRing(this.normalizePath(this.drawnScopePolygon, 3, 'scope.outline.drawn'));
                    if (Array.isArray(drawnRing) && drawnRing.length >= 4) {
                        paths.push(drawnRing.map((pt) => [Number(pt[0]), Number(pt[1])]));
                    }
                }
                if (showIsochrone) {
                    paths.push(...this.extractIsochroneOutlinePaths());
                }

                if (!paths.length) {
                    if (canClear) this.mapCore.clearCustomPolygons();
                    return;
                }
                if (canSet) {
                    this.mapCore.setCustomPolygons(paths);
                }
            },
            clearScopeOutlineDisplay() {
                if (!this.mapCore || typeof this.mapCore.clearCustomPolygons !== 'function') return;
                this.mapCore.clearCustomPolygons();
            },
            applySimplifyBasemapStyle() {
                if (!this.mapCore || typeof this.mapCore.setBasemapMuted !== 'function') return;
                const muted = !!this.h3BasemapMuted;
                this.mapCore.setBasemapMuted(muted);
                console.info('[basemap-display]', {
                    basemap_muted: muted,
                    source: this.basemapSource || ''
                });
            },
            shortH3Id(h3Id) {
                const id = h3Id ? String(h3Id) : '';
                if (!id) return '-';
                if (id.length <= 12) return id;
                return `${id.slice(0, 5)}...${id.slice(-4)}`;
            },
            focusGridByH3Id(h3Id) {
                const id = h3Id ? String(h3Id) : '';
                if (!id || !this.mapCore || !this.mapCore.focusGridCellById) return;
                this.selectedH3Id = id;
                const found = this.mapCore.focusGridCellById(id, {
                    fitView: true,
                    zoomMin: 16,
                    animate: true,
                    preserveFill: true,
                    animateFill: false,
                    strokeColor: '#22d3ee',
                    pulseColor: '#ecfeff'
                });
                if (!found) {
                    this.h3GridStatus = `未找到对应网格：${id}`;
                    return;
                }
                const row = this._findH3RowById(id);
                if (row) {
                    this.h3GridStatus = this._buildH3StructureStatusText(row);
                } else {
                    this.h3GridStatus = `已定位网格：${id}`;
                }
            },
            onH3GridFeatureClick(payload) {
                const id = payload && payload.h3_id ? String(payload.h3_id) : '';
                if (!id) return;
                this.focusGridByH3Id(id);
            },
            _findH3RowById(h3Id) {
                const id = h3Id ? String(h3Id) : '';
                if (!id) return null;
                const rows = (this.h3DerivedStats && this.h3DerivedStats.structureSummary && this.h3DerivedStats.structureSummary.rows) || [];
                const found = rows.find((row) => String(row.h3_id || '') === id);
                if (found) return found;
                const feature = (this.h3AnalysisGridFeatures || []).find((f) => String((f.properties || {}).h3_id || '') === id);
                if (!feature) return null;
                const props = feature.properties || {};
                const giZ = Number.isFinite(Number(props.gi_star_z_score)) ? Number(props.gi_star_z_score) : null;
                const lisaI = Number.isFinite(Number(props.lisa_i)) ? Number(props.lisa_i) : null;
                const fallbackSignal = Math.max(
                    Number.isFinite(giZ) ? Math.abs(giZ) : 0,
                    Number.isFinite(lisaI) ? Math.abs(lisaI) : 0
                );
                return {
                    h3_id: id,
                    gi_star_z_score: giZ,
                    lisa_i: lisaI,
                    structure_signal: Number.isFinite(Number(props.structure_signal)) ? Number(props.structure_signal) : fallbackSignal,
                    density: this._toNumber(props.density_poi_per_km2, 0),
                };
            },
            _buildH3StructureStatusText(row) {
                const giText = row && Number.isFinite(this._toNumber(row.gi_star_z_score, NaN))
                    ? this._toNumber(row.gi_star_z_score, 0).toFixed(2)
                    : '-';
                const lisaText = row && Number.isFinite(this._toNumber(row.lisa_i, NaN))
                    ? this._toNumber(row.lisa_i, 0).toFixed(2)
                    : '-';
                const signalText = row && Number.isFinite(this._toNumber(row.structure_signal, NaN))
                    ? this._toNumber(row.structure_signal, 0).toFixed(2)
                    : '-';
                const densityText = row && Number.isFinite(this._toNumber(row.density, NaN))
                    ? this._toNumber(row.density, 0).toFixed(2)
                    : '-';
                return `Gi*z=${giText} | LISA I=${lisaText} | 结构信号=${signalText} | 密度=${densityText}`;
            },
            getArcgisSnapshotUrl() {
                const summary = this.h3AnalysisSummary || {};
                const giUrl = this._normalizeArcgisSnapshotUrl(summary.arcgis_image_url_gi);
                const lisaUrl = this._normalizeArcgisSnapshotUrl(summary.arcgis_image_url_lisa);
                const fallbackUrl = this._normalizeArcgisSnapshotUrl(summary.arcgis_image_url);
                if (this.h3SubTab === 'structure_map') {
                    if (this.h3StructureFillMode === 'lisa_i') {
                        // Keep snapshot layer-consistent: never fallback to Gi* image in LISA mode.
                        return lisaUrl || null;
                    }
                    // Keep snapshot layer-consistent: never fallback to LISA image in Gi* mode.
                    return giUrl || null;
                }
                return fallbackUrl || giUrl || lisaUrl || null;
            },
            getArcgisSnapshotSrc() {
                const url = this.getArcgisSnapshotUrl();
                if (!url) return '';
                if (String(url).startsWith('data:')) return url;
                const joiner = String(url).includes('?') ? '&' : '?';
                return `${url}${joiner}v=${this.h3ArcgisImageVersion}`;
            },
            _normalizeArcgisSnapshotUrl(rawUrl) {
                const raw = String(rawUrl || '').trim();
                if (!raw || raw.toLowerCase() === 'null' || raw.toLowerCase() === 'none') return null;
                if (raw.startsWith('data:') || raw.startsWith('http://') || raw.startsWith('https://') || raw.startsWith('/')) {
                    return raw;
                }
                const slashNorm = raw.replace(/\\\\/g, '/').replace(/\\/g, '/');
                const marker = '/static/generated/arcgis/';
                const idx = slashNorm.indexOf(marker);
                if (idx >= 0) {
                    return slashNorm.slice(idx);
                }
                const marker2 = 'static/generated/arcgis/';
                const idx2 = slashNorm.indexOf(marker2);
                if (idx2 >= 0) {
                    return '/' + slashNorm.slice(idx2);
                }
                return null;
            },
            getArcgisSnapshotTitle() {
                if (this.h3SubTab === 'structure_map') {
                    if (this.h3StructureFillMode === 'lisa_i') {
                        return 'ArcGIS 结构快照（LISA / LMiIndex）';
                    }
                    return 'ArcGIS 结构快照（Gi* / Z-score）';
                }
                return 'ArcGIS 结构快照';
            },
            clearGridLock() {
                if (this.mapCore && this.mapCore.clearGridFocus) {
                    this.mapCore.clearGridFocus({ restoreView: true });
                }
                this.selectedH3Id = null;
                this.h3GridStatus = '';
            },
            tryRefocusSelectedGrid() {
                if (!this.selectedH3Id || !this.mapCore || !this.mapCore.focusGridCellById) return;
                this.mapCore.focusGridCellById(this.selectedH3Id, {
                    panTo: false,
                    animate: false,
                    preserveFill: true,
                    animateFill: false
                });
            },
            _quantile(sortedValues, q) {
                if (!Array.isArray(sortedValues) || sortedValues.length === 0) return 0;
                if (sortedValues.length === 1) return sortedValues[0];
                const qq = Math.max(0, Math.min(1, q));
                const pos = qq * (sortedValues.length - 1);
                const lower = Math.floor(pos);
                const upper = Math.min(sortedValues.length - 1, lower + 1);
                const ratio = pos - lower;
                return sortedValues[lower] + (sortedValues[upper] - sortedValues[lower]) * ratio;
            },
            _calcContinuousStats(values) {
                const valid = (values || [])
                    .map(v => this._toNumber(v, NaN))
                    .filter(v => Number.isFinite(v))
                    .sort((a, b) => a - b);
                if (!valid.length) {
                    return {
                        count: 0,
                        mean: null,
                        std: null,
                        min: null,
                        max: null,
                        p10: null,
                        p50: null,
                        p90: null,
                    };
                }
                const count = valid.length;
                const mean = valid.reduce((sum, v) => sum + v, 0) / count;
                const variance = valid.reduce((sum, v) => sum + (v - mean) * (v - mean), 0) / count;
                return {
                    count: count,
                    mean: mean,
                    std: Math.sqrt(Math.max(0, variance)),
                    min: valid[0],
                    max: valid[valid.length - 1],
                    p10: this._quantile(valid, 0.1),
                    p50: this._quantile(valid, 0.5),
                    p90: this._quantile(valid, 0.9),
                };
            },
            _normalizeContinuousStats(stats, fallback) {
                const source = (stats && typeof stats === 'object') ? stats : (fallback || {});
                const toMetric = (value) => Number.isFinite(this._toNumber(value, NaN))
                    ? this._toNumber(value, 0)
                    : null;
                return {
                    count: Math.max(0, Math.round(this._toNumber(source.count, 0))),
                    mean: toMetric(source.mean),
                    std: toMetric(source.std),
                    min: toMetric(source.min),
                    max: toMetric(source.max),
                    p10: toMetric(source.p10),
                    p50: toMetric(source.p50),
                    p90: toMetric(source.p90),
                };
            },
            _normalizeGiRenderMeta(meta) {
                const source = (meta && typeof meta === 'object') ? meta : {};
                const min = Number.isFinite(this._toNumber(source.min, NaN)) ? this._toNumber(source.min, -3) : -3;
                const max = Number.isFinite(this._toNumber(source.max, NaN)) ? this._toNumber(source.max, 3) : 3;
                const center = Number.isFinite(this._toNumber(source.center, NaN)) ? this._toNumber(source.center, 0) : 0;
                return {
                    mode: 'fixed_z',
                    min: Math.min(min, max),
                    max: Math.max(min, max),
                    center: Math.max(Math.min(center, Math.max(min, max)), Math.min(min, max)),
                };
            },
            _normalizeLisaRenderMeta(meta, lisaIStats) {
                const stats = lisaIStats || {};
                const mean = Number.isFinite(this._toNumber(stats.mean, NaN)) ? this._toNumber(stats.mean, 0) : 0;
                const std = Number.isFinite(this._toNumber(stats.std, NaN)) ? this._toNumber(stats.std, 0) : 0;
                const p10 = Number.isFinite(this._toNumber(stats.p10, NaN)) ? this._toNumber(stats.p10, NaN) : null;
                const p90 = Number.isFinite(this._toNumber(stats.p90, NaN)) ? this._toNumber(stats.p90, NaN) : null;
                const minV = Number.isFinite(this._toNumber(stats.min, NaN)) ? this._toNumber(stats.min, NaN) : null;
                const maxV = Number.isFinite(this._toNumber(stats.max, NaN)) ? this._toNumber(stats.max, NaN) : null;
                const source = (meta && typeof meta === 'object') ? meta : {};
                const clipMinRaw = Number.isFinite(this._toNumber(source.clip_min, NaN))
                    ? this._toNumber(source.clip_min, NaN)
                    : Math.max(
                        Number.isFinite(this._toNumber(mean - 2 * std, NaN)) ? this._toNumber(mean - 2 * std, NaN) : -Infinity,
                        Number.isFinite(this._toNumber(p10, NaN)) ? this._toNumber(p10, NaN) : -Infinity,
                        Number.isFinite(this._toNumber(minV, NaN)) ? this._toNumber(minV, NaN) : -Infinity
                    );
                const clipMaxRaw = Number.isFinite(this._toNumber(source.clip_max, NaN))
                    ? this._toNumber(source.clip_max, NaN)
                    : Math.min(
                        Number.isFinite(this._toNumber(mean + 2 * std, NaN)) ? this._toNumber(mean + 2 * std, NaN) : Infinity,
                        Number.isFinite(this._toNumber(p90, NaN)) ? this._toNumber(p90, NaN) : Infinity,
                        Number.isFinite(this._toNumber(maxV, NaN)) ? this._toNumber(maxV, NaN) : Infinity
                    );
                const clipMin = Number.isFinite(clipMinRaw) ? clipMinRaw : mean;
                const clipMax = Number.isFinite(clipMaxRaw) ? clipMaxRaw : mean;
                const fallbackDegraded = !(Number.isFinite(std) && std > 0 && Number.isFinite(clipMin) && Number.isFinite(clipMax) && clipMax > clipMin);
                return {
                    mode: 'stddev',
                    mean: Number.isFinite(this._toNumber(source.mean, NaN)) ? this._toNumber(source.mean, mean) : mean,
                    std: Number.isFinite(this._toNumber(source.std, NaN)) ? this._toNumber(source.std, std) : std,
                    min: Number.isFinite(this._toNumber(source.min, NaN)) ? this._toNumber(source.min, NaN) : stats.min,
                    max: Number.isFinite(this._toNumber(source.max, NaN)) ? this._toNumber(source.max, NaN) : stats.max,
                    clip_min: Math.min(clipMin, clipMax),
                    clip_max: Math.max(clipMin, clipMax),
                    degraded: source.degraded === true || fallbackDegraded,
                    message: source.message || (fallbackDegraded ? 'LMiIndex方差不足' : null),
                };
            },
            _buildQuantileBreaks(values, binCount = 5) {
                const sorted = (values || [])
                    .map(v => this._toNumber(v, NaN))
                    .filter(v => Number.isFinite(v))
                    .sort((a, b) => a - b);
                if (!sorted.length || sorted[0] === sorted[sorted.length - 1]) {
                    return [];
                }
                const breaks = [];
                for (let i = 1; i < binCount; i += 1) {
                    breaks.push(this._quantile(sorted, i / binCount));
                }
                for (let i = 1; i < breaks.length; i += 1) {
                    if (breaks[i] < breaks[i - 1]) {
                        breaks[i] = breaks[i - 1];
                    }
                }
                const deduped = [];
                const eps = 1e-9;
                for (const value of breaks) {
                    if (!deduped.length || Math.abs(value - deduped[deduped.length - 1]) > eps) {
                        deduped.push(value);
                    }
                }
                return deduped;
            },
            _buildDivergingBreaks(values) {
                const valid = (values || [])
                    .map(v => this._toNumber(v, NaN))
                    .filter(v => Number.isFinite(v))
                    .sort((a, b) => a - b);
                if (!valid.length) return [];
                const negatives = valid.filter(v => v < 0);
                const positives = valid.filter(v => v > 0);
                if (!negatives.length || !positives.length) {
                    return this._buildQuantileBreaks(valid, 5);
                }
                const breaks = [
                    this._quantile(negatives, 1 / 3),
                    this._quantile(negatives, 2 / 3),
                    this._quantile(positives, 1 / 3),
                    this._quantile(positives, 2 / 3),
                ];
                for (let i = 1; i < breaks.length; i += 1) {
                    if (breaks[i] < breaks[i - 1]) {
                        breaks[i] = breaks[i - 1];
                    }
                }
                const deduped = [];
                const eps = 1e-9;
                for (const value of breaks) {
                    if (!deduped.length || Math.abs(value - deduped[deduped.length - 1]) > eps) {
                        deduped.push(value);
                    }
                }
                return deduped;
            },
            _getMetricSpec(metricKey) {
                if (metricKey === 'entropy') {
                    return {
                        key: 'entropy',
                        label: '局部熵（归一化）',
                        unit: '0~1',
                        diverging: false,
                        palette: ['#f4fbe8', '#d6efbe', '#a5d88a', '#6bb65d', '#2f7e39'],
                        noDataColor: '#d1d5db',
                        noDataOpacity: 0.10,
                        fillOpacity: 0.24,
                        noDataLabel: `无数据（样本<${this.h3EntropyMinPoi}）`,
                    };
                }
                if (metricKey === 'neighbor_delta') {
                    return {
                        key: 'neighbor_delta',
                        label: '邻域差值（本格-邻域）',
                        unit: 'POI/km²',
                        diverging: true,
                        palette: ['#2b6cb0', '#90cdf4', '#f7f7f7', '#f6ad55', '#c53030'],
                        noDataColor: '#d1d5db',
                        noDataOpacity: 0.10,
                        fillOpacity: 0.24,
                        noDataLabel: '',
                    };
                }
                return {
                    key: 'density',
                    label: '密度',
                    unit: 'POI/km²',
                    diverging: false,
                    palette: ['#e8f1ff', '#b7d2ff', '#7eaef9', '#3f82e0', '#1f4f9a'],
                    noDataColor: '#d1d5db',
                    noDataOpacity: 0.10,
                    fillOpacity: 0.24,
                    noDataLabel: '',
                };
            },
            _getH3MetricValue(props, metricKey) {
                if (!props) return { value: null, noData: true };
                const density = this._toNumber(props.density_poi_per_km2, 0);
                if (metricKey === 'entropy') {
                    const poiCount = this._toNumber(props.poi_count, 0);
                    if (poiCount < this.h3EntropyMinPoi) {
                        return { value: null, noData: true };
                    }
                    const rawEntropy = this._toNumber(props.local_entropy, 0);
                    const normalized = rawEntropy / Math.log(7);
                    const bounded = Math.max(0, Math.min(1, normalized));
                    return { value: bounded, noData: false };
                }
                if (metricKey === 'neighbor_delta') {
                    const neighbor = this._toNumber(props.neighbor_mean_density, 0);
                    return { value: density - neighbor, noData: false };
                }
                return { value: density, noData: false };
            },
            _colorByBreaks(value, breaks, palette) {
                if (!Number.isFinite(value)) return '#d1d5db';
                if (!Array.isArray(breaks) || !breaks.length) {
                    return palette[Math.max(0, Math.floor((palette.length - 1) / 2))] || '#dbe9ff';
                }
                let idx = breaks.findIndex(bound => value <= bound);
                if (idx < 0) idx = palette.length - 1;
                return palette[Math.max(0, Math.min(idx, palette.length - 1))] || '#dbe9ff';
            },
            _formatLegendValue(value, metricKey) {
                if (!Number.isFinite(value)) return '-';
                if (metricKey === 'entropy') return value.toFixed(2);
                const abs = Math.abs(value);
                if (abs >= 100) return value.toFixed(0);
                if (abs >= 10) return value.toFixed(1);
                return value.toFixed(2);
            },
            _buildLegend(metricSpec, breaks, validValues) {
                const palette = metricSpec.palette || [];
                const legend = {
                    title: metricSpec.label,
                    unit: metricSpec.unit,
                    items: [],
                    noDataLabel: metricSpec.noDataLabel || '',
                    noDataColor: metricSpec.noDataColor || '#d1d5db',
                };
                if (!palette.length) return legend;
                if (!Array.isArray(validValues) || !validValues.length) {
                    legend.items = [{ color: palette[0], label: '无有效数据' }];
                    return legend;
                }
                if (!breaks.length) {
                    const minV = Math.min(...validValues);
                    const maxV = Math.max(...validValues);
                    legend.items = [{
                        color: palette[palette.length - 1],
                        label: `${this._formatLegendValue(minV, metricSpec.key)} ~ ${this._formatLegendValue(maxV, metricSpec.key)}`
                    }];
                    return legend;
                }
                const classCount = Math.min(palette.length, breaks.length + 1);
                for (let i = 0; i < classCount; i += 1) {
                    let label = '';
                    if (i === 0) {
                        label = `≤ ${this._formatLegendValue(breaks[0], metricSpec.key)}`;
                    } else if (i === classCount - 1) {
                        label = `> ${this._formatLegendValue(breaks[breaks.length - 1], metricSpec.key)}`;
                    } else {
                        label = `${this._formatLegendValue(breaks[i - 1], metricSpec.key)} ~ ${this._formatLegendValue(breaks[i], metricSpec.key)}`;
                    }
                    legend.items.push({ color: palette[i], label: label });
                }
                return legend;
            },
            _percentileFromSorted(sortedValues, value) {
                if (!Array.isArray(sortedValues) || !sortedValues.length || !Number.isFinite(value)) return 0;
                const n = sortedValues.length;
                if (n === 1) return 0.5;
                let lower = 0;
                while (lower < n && sortedValues[lower] < value) lower += 1;
                let upper = lower;
                while (upper < n && sortedValues[upper] <= value) upper += 1;
                const midRank = (lower + upper - 1) / 2;
                return Math.max(0, Math.min(1, midRank / (n - 1)));
            },
            _getConfidenceInfo(poiCount) {
                const count = this._toNumber(poiCount, 0);
                if (count >= 10) return { score: 2, label: '高' };
                if (count >= 5) return { score: 1, label: '中' };
                return { score: 0, label: '低' };
            },
            _getH3CategoryLabel(key) {
                const hit = (this.h3CategoryMeta || []).find(item => item.key === key);
                return hit ? hit.label : key;
            },
            classifyGridType(featureProps, thresholds = {}) {
                const density = this._toNumber(featureProps.density, 0);
                const entropyNorm = Number.isFinite(featureProps.entropy_norm) ? featureProps.entropy_norm : null;
                const neighborDelta = this._toNumber(featureProps.neighbor_delta, 0);
                if (entropyNorm === null) {
                    return {
                        type_key: 'no_data',
                        type_label: '样本不足',
                        is_opportunity: false,
                    };
                }
                const highDensity = density >= this._toNumber(thresholds.densityP70, 0);
                const highEntropy = entropyNorm >= this._toNumber(thresholds.entropyP70, 0);
                let typeKey = 'low_density_low_mix';
                let typeLabel = '低密-低混合';
                if (highDensity && highEntropy) {
                    typeKey = 'high_density_high_mix';
                    typeLabel = '高密-高混合';
                } else if (highDensity && !highEntropy) {
                    typeKey = 'high_density_low_mix';
                    typeLabel = '高密-低混合';
                } else if (!highDensity && highEntropy) {
                    typeKey = 'low_density_high_mix';
                    typeLabel = '低密-高混合';
                }
                const isOpportunity = typeKey === 'high_density_high_mix' && neighborDelta > 0;
                return {
                    type_key: typeKey,
                    type_label: typeLabel,
                    is_opportunity: isOpportunity,
                };
            },
            computeCellLQ(featureProps, globalCategoryCounts, globalTotal) {
                const poiCount = this._toNumber(featureProps.poi_count, 0);
                if (poiCount < this.h3EntropyMinPoi) return null;
                const categoryCounts = featureProps.category_counts || {};
                const categorySize = Math.max(1, (this.h3CategoryMeta || []).length);
                const alpha = Math.max(0, this._toNumber(this.h3LqSmoothingAlpha, 0.5));
                const result = {};
                (this.h3CategoryMeta || []).forEach(item => {
                    const key = item.key;
                    const gCount = this._toNumber(globalCategoryCounts[key], 0);
                    const cCount = this._toNumber(categoryCounts[key], 0);
                    const gShare = (gCount + alpha) / (Math.max(0, globalTotal) + alpha * categorySize);
                    const cShare = (cCount + alpha) / (Math.max(0, poiCount) + alpha * categorySize);
                    result[key] = gShare > 0 ? (cShare / gShare) : null;
                });
                return result;
            },
            computeGapScore(featureProps, targetCategory, gapDemandMapping = null) {
                const density = this._toNumber(featureProps.density, 0);
                const poiCount = this._toNumber(featureProps.poi_count, 0);
                const categoryCounts = featureProps.category_counts || {};
                const densityByCategory = {};
                (this.h3CategoryMeta || []).forEach(item => {
                    const count = this._toNumber(categoryCounts[item.key], 0);
                    densityByCategory[item.key] = poiCount > 0 ? density * (count / poiCount) : 0;
                });
                const weights = this.h3GapWeights || {};
                const mapping = gapDemandMapping || {};
                const demandProxy =
                    this._toNumber(weights.transport, 0) * this._toNumber(densityByCategory[mapping.transport], 0) +
                    this._toNumber(weights.life, 0) * this._toNumber(densityByCategory[mapping.life], 0) +
                    this._toNumber(weights.education, 0) * this._toNumber(densityByCategory[mapping.education], 0) +
                    this._toNumber(weights.medical, 0) * this._toNumber(densityByCategory[mapping.medical], 0);
                const supplyTargetDensity = this._toNumber(densityByCategory[targetCategory], 0);
                return {
                    demand_proxy: demandProxy,
                    supply_target_density: supplyTargetDensity,
                };
            },
            classifyGapZone(demandPct, supplyPct, gapScore) {
                const demand = this._toNumber(demandPct, 0);
                const supply = this._toNumber(supplyPct, 0);
                const gap = this._toNumber(gapScore, 0);
                if (demand >= 0.6 && supply < 0.4) return '补位机会区';
                if (demand >= 0.6 && supply >= 0.6) return '高需求高供给（竞争区）';
                if (demand < 0.4 && supply >= 0.6) return '低需求高供给（偏饱和）';
                if (demand < 0.4 && supply < 0.4) return '低需求低供给（观察区）';
                if (gap >= 0.15) return '偏机会区';
                if (gap <= -0.15) return '偏饱和区';
                return '相对平衡区';
            },
            computeH3DerivedStats() {
                this._ensureH3CategoryState();
                const features = this.h3AnalysisGridFeatures || [];
                const topN = Math.max(3, Math.min(30, Math.round(this._toNumber(this.h3DecisionTopN, 10))));
                this.h3DecisionTopN = topN;
                if (!features.length) {
                    this.h3DerivedStats = {
                        structureSummary: null,
                        typingSummary: null,
                        lqSummary: null,
                        gapSummary: null,
                        topCells: {},
                    };
                    return;
                }

                const rowsBase = features.map((feature) => {
                    const props = feature.properties || {};
                    const entropyRaw = this._getH3MetricValue(props, 'entropy');
                    const density = this._toNumber(props.density_poi_per_km2, 0);
                    const neighborDensity = this._toNumber(props.neighbor_mean_density, 0);
                    return {
                        h3_id: props.h3_id || '',
                        poi_count: this._toNumber(props.poi_count, 0),
                        density: density,
                        entropy_norm: entropyRaw.noData ? null : entropyRaw.value,
                        neighbor_delta: density - neighborDensity,
                        category_counts: Object.assign({}, props.category_counts || {}),
                        confidence: this._getConfidenceInfo(props.poi_count),
                        lisa_i: Number.isFinite(Number(props.lisa_i)) ? Number(props.lisa_i) : null,
                        gi_star_z_score: Number.isFinite(Number(props.gi_star_z_score)) ? Number(props.gi_star_z_score) : null,
                    };
                });
                const rowsEnriched = rowsBase;

                const densitySorted = rowsEnriched.map(r => r.density).filter(v => Number.isFinite(v)).sort((a, b) => a - b);
                const entropySorted = rowsEnriched.map(r => r.entropy_norm).filter(v => Number.isFinite(v)).sort((a, b) => a - b);
                const densityP70 = densitySorted.length ? this._quantile(densitySorted, 0.7) : 0;
                const entropyP70 = entropySorted.length ? this._quantile(entropySorted, 0.7) : 0;

                const typingRowsAll = rowsEnriched.map((row) => {
                    const typed = this.classifyGridType(row, { densityP70, entropyP70 });
                    return Object.assign({}, row, typed);
                }).sort((a, b) => {
                    if ((b.is_opportunity ? 1 : 0) !== (a.is_opportunity ? 1 : 0)) {
                        return (b.is_opportunity ? 1 : 0) - (a.is_opportunity ? 1 : 0);
                    }
                    if (b.density !== a.density) return b.density - a.density;
                    const confidenceDiff = this._toNumber(b.confidence && b.confidence.score, 0)
                        - this._toNumber(a.confidence && a.confidence.score, 0);
                    if (confidenceDiff !== 0) return confidenceDiff;
                    return this._toNumber(b.entropy_norm, -1) - this._toNumber(a.entropy_norm, -1);
                });

                const baseGiStats = this._normalizeContinuousStats(
                    this.h3AnalysisSummary && this.h3AnalysisSummary.gi_z_stats,
                    this._calcContinuousStats(rowsEnriched.map(r => r.gi_star_z_score))
                );
                const baseLisaStats = this._normalizeContinuousStats(
                    this.h3AnalysisSummary && this.h3AnalysisSummary.lisa_i_stats,
                    this._calcContinuousStats(rowsEnriched.map(r => r.lisa_i))
                );
                const lisaMean = this._toNumber(baseLisaStats.mean, 0);
                const lisaStd = this._toNumber(baseLisaStats.std, 0);
                const structureRowsBase = rowsEnriched.map((row) => {
                    const giSignal = Number.isFinite(row.gi_star_z_score)
                        ? Math.abs(this._toNumber(row.gi_star_z_score, 0))
                        : 0;
                    let lisaSignal = 0;
                    if (Number.isFinite(row.lisa_i)) {
                        if (lisaStd > 0) {
                            lisaSignal = Math.abs((this._toNumber(row.lisa_i, 0) - lisaMean) / lisaStd);
                        } else {
                            lisaSignal = Math.abs(this._toNumber(row.lisa_i, 0) - lisaMean) > 0 ? 1 : 0;
                        }
                    }
                    const structureSignal = Math.max(giSignal, lisaSignal);
                    const hasStructureMetric = Number.isFinite(row.gi_star_z_score) || Number.isFinite(row.lisa_i);
                    return Object.assign({}, row, {
                        structure_signal: structureSignal,
                        structure_rank: structureSignal,
                        is_structure_signal: hasStructureMetric && structureSignal > 1,
                    });
                });
                const structureSignalByH3 = {};
                structureRowsBase.forEach((row) => {
                    const key = String(row.h3_id || '');
                    if (!key) return;
                    structureSignalByH3[key] = {
                        structure_signal: row.structure_signal,
                        structure_rank: row.structure_rank,
                        is_structure_signal: !!row.is_structure_signal,
                    };
                });
                const typingRowsAllWithSignal = typingRowsAll.map((row) => {
                    const key = String(row.h3_id || '');
                    const signalMeta = structureSignalByH3[key] || {};
                    return Object.assign({}, row, signalMeta);
                });
                const typingRows = (this.h3OnlySignificant
                    ? typingRowsAllWithSignal.filter(r => r.is_structure_signal)
                    : typingRowsAllWithSignal
                );
                const typingCountByType = {};
                typingRows.forEach(row => {
                    const key = row.type_key || 'unknown';
                    typingCountByType[key] = (typingCountByType[key] || 0) + 1;
                });
                const typingOpportunityCount = typingRows.filter(r => r.is_opportunity).length;
                const typingMaxDensity = typingRows.length ? Math.max(...typingRows.map(r => this._toNumber(r.density, 0))) : 0;
                const structureRows = (this.h3OnlySignificant
                    ? structureRowsBase.filter(r => r.is_structure_signal)
                    : structureRowsBase
                ).sort((a, b) => {
                    const rankDiff = this._toNumber(b.structure_rank, 0) - this._toNumber(a.structure_rank, 0);
                    if (rankDiff !== 0) return rankDiff;
                    const giDiff = Math.abs(this._toNumber(b.gi_star_z_score, 0)) - Math.abs(this._toNumber(a.gi_star_z_score, 0));
                    if (giDiff !== 0) return giDiff;
                    if (b.density !== a.density) return b.density - a.density;
                    return this._toNumber(b.poi_count, 0) - this._toNumber(a.poi_count, 0);
                });
                const giZStats = this._normalizeContinuousStats(
                    this.h3AnalysisSummary && this.h3AnalysisSummary.gi_z_stats,
                    this._calcContinuousStats(structureRowsBase.map(r => r.gi_star_z_score))
                );
                const lisaIStats = this._normalizeContinuousStats(
                    this.h3AnalysisSummary && this.h3AnalysisSummary.lisa_i_stats,
                    this._calcContinuousStats(structureRowsBase.map(r => r.lisa_i))
                );
                const giRenderMeta = this._normalizeGiRenderMeta(
                    this.h3AnalysisSummary && this.h3AnalysisSummary.gi_render_meta
                );
                const lisaRenderMeta = this._normalizeLisaRenderMeta(
                    this.h3AnalysisSummary && this.h3AnalysisSummary.lisa_render_meta,
                    lisaIStats
                );
                const lisaValidCount = Math.max(0, this._toNumber(lisaIStats.count, 0));
                const lisaPositiveCount = structureRowsBase.filter(r => Number.isFinite(r.lisa_i) && this._toNumber(r.lisa_i, 0) > 0).length;
                const lisaNegativeCount = structureRowsBase.filter(r => Number.isFinite(r.lisa_i) && this._toNumber(r.lisa_i, 0) < 0).length;
                const lisaPositivePct = lisaValidCount > 0 ? (lisaPositiveCount / lisaValidCount) : null;
                const lisaNegativePct = lisaValidCount > 0 ? (lisaNegativeCount / lisaValidCount) : null;

                const rowsWithSignal = structureRowsBase;
                const globalCategoryCounts = {};
                (this.h3CategoryMeta || []).forEach(item => { globalCategoryCounts[item.key] = 0; });
                rowsWithSignal.forEach(row => {
                    (this.h3CategoryMeta || []).forEach(item => {
                        globalCategoryCounts[item.key] += this._toNumber(row.category_counts[item.key], 0);
                    });
                });
                const globalTotal = Object.values(globalCategoryCounts).reduce((s, v) => s + this._toNumber(v, 0), 0);
                const lqRowsAll = rowsWithSignal.map(row => {
                    const lqMap = this.computeCellLQ(row, globalCategoryCounts, globalTotal);
                    let dominantKey = null;
                    let dominantValue = null;
                    if (lqMap) {
                        (this.h3CategoryMeta || []).forEach(item => {
                            const v = lqMap[item.key];
                            if (!Number.isFinite(v)) return;
                            if (!Number.isFinite(dominantValue) || v > dominantValue) {
                                dominantValue = v;
                                dominantKey = item.key;
                            }
                        });
                    }
                    return Object.assign({}, row, {
                        lq_map: lqMap,
                        lq_target: lqMap ? lqMap[this.h3TargetCategory] : null,
                        dominant_key: dominantKey,
                        dominant_value: dominantValue,
                    });
                }).sort((a, b) => {
                    const lqDiff = this._toNumber(b.lq_target, -1) - this._toNumber(a.lq_target, -1);
                    if (lqDiff !== 0) return lqDiff;
                    return this._toNumber(b.confidence && b.confidence.score, 0)
                        - this._toNumber(a.confidence && a.confidence.score, 0);
                });
                const lqRows = this.h3OnlySignificant
                    ? lqRowsAll.filter(r => r.is_structure_signal)
                    : lqRowsAll;
                const lqOpportunityCount = lqRows.filter(r => Number.isFinite(r.lq_target) && r.lq_target >= 1.2).length;
                const lqMax = lqRows.length ? Math.max(...lqRows.map(r => this._toNumber(r.lq_target, 0))) : 0;
                const dominantCounts = {};
                (this.h3CategoryMeta || []).forEach(item => { dominantCounts[item.key] = 0; });
                lqRowsAll.forEach(row => {
                    if (row.dominant_key && Number.isFinite(row.dominant_value) && row.dominant_value > 1) {
                        dominantCounts[row.dominant_key] += 1;
                    }
                });

                const gapDemandCategory = this._resolveGapDemandCategoryMap();
                const missingMapTitles = gapDemandCategory.missingTitles || [];
                const gapMappingWarning = missingMapTitles.length
                    ? `Gap映射缺失：未找到“${missingMapTitles.join('、')}”，对应权重按0处理`
                    : '';
                const gapRowsRaw = rowsWithSignal.map(row => Object.assign({}, row, this.computeGapScore(
                    row,
                    this.h3TargetCategory,
                    gapDemandCategory.mapping || {}
                )));
                const demandValues = gapRowsRaw.map(r => r.demand_proxy).filter(v => Number.isFinite(v));
                const supplyValues = gapRowsRaw.map(r => r.supply_target_density).filter(v => Number.isFinite(v));
                const demandSorted = demandValues.slice().sort((a, b) => a - b);
                const supplySorted = supplyValues.slice().sort((a, b) => a - b);
                const gapRowsAll = gapRowsRaw.map(row => {
                    const demandPct = this._percentileFromSorted(demandSorted, row.demand_proxy);
                    const supplyPct = this._percentileFromSorted(supplySorted, row.supply_target_density);
                    const gapScore = demandPct - supplyPct;
                    return Object.assign({}, row, {
                        demand_pct: demandPct,
                        supply_pct: supplyPct,
                        gap_score: gapScore,
                        gap_zone_label: this.classifyGapZone(demandPct, supplyPct, gapScore),
                    });
                }).sort((a, b) => {
                    const gapDiff = this._toNumber(b.gap_score, -999) - this._toNumber(a.gap_score, -999);
                    if (gapDiff !== 0) return gapDiff;
                    return this._toNumber(b.confidence && b.confidence.score, 0)
                        - this._toNumber(a.confidence && a.confidence.score, 0);
                });
                const gapRows = this.h3OnlySignificant
                    ? gapRowsAll.filter(r => r.is_structure_signal)
                    : gapRowsAll;
                const gapOpportunityCount = gapRows.filter(r => this._toNumber(r.gap_score, 0) > 0.25 && this._toNumber(r.demand_pct, 0) >= 0.6).length;
                const gapMax = gapRows.length ? Math.max(...gapRows.map(r => this._toNumber(r.gap_score, 0))) : 0;
                const topGap = gapRows.length ? gapRows[0] : null;
                const gapInsightBase = topGap
                    ? `Top1 网格需求分位 ${Math.round(this._toNumber(topGap.demand_pct, 0) * 100)}，供给分位 ${Math.round(this._toNumber(topGap.supply_pct, 0) * 100)}，结论：${topGap.gap_zone_label}`
                    : '当前缺口结果为空，请调整范围或业态后重算';
                const gapInsight = gapMappingWarning
                    ? `${gapMappingWarning}。${gapInsightBase}`
                    : gapInsightBase;

                this.h3DerivedStats = {
                    structureSummary: {
                        rows: structureRows,
                        giZStats: giZStats,
                        lisaIStats: lisaIStats,
                        lisaPositivePct: lisaPositivePct,
                        lisaNegativePct: lisaNegativePct,
                        giRenderMeta: giRenderMeta,
                        lisaRenderMeta: lisaRenderMeta,
                        recommendation: structureRows.length > 0
                            ? '优先观察Gi*与LMiIndex连续梯度，再结合LQ/缺口结果做落位'
                            : '当前结构梯度较弱，可扩大范围或切换圈层复核',
                    },
                    typingSummary: {
                        counts: typingCountByType,
                        rows: typingRows,
                        densityP70: densityP70,
                        entropyP70: entropyP70,
                        opportunityCount: typingOpportunityCount,
                        maxDensity: typingMaxDensity,
                        recommendation: typingOpportunityCount > 0
                            ? '优先排查高密-高混合且邻域为正的网格'
                            : '当前高密高混合机会有限，可结合区位商优势与缺口优先区复核',
                    },
                    lqSummary: {
                        rows: lqRows,
                        dominantCounts: dominantCounts,
                        opportunityCount: lqOpportunityCount,
                        maxLq: lqMax,
                        recommendation: `${this._getH3CategoryLabel(this.h3TargetCategory)}区位商优势格可优先巩固`,
                    },
                    gapSummary: {
                        rows: gapRows,
                        opportunityCount: gapOpportunityCount,
                        maxGap: gapMax,
                        mappingWarning: gapMappingWarning,
                        recommendation: topGap
                            ? `${this._getH3CategoryLabel(this.h3TargetCategory)}优先关注${topGap.gap_zone_label}`
                            : `${this._getH3CategoryLabel(this.h3TargetCategory)}当前无明显缺口优先区`,
                        insight: gapInsight,
                    },
                    topCells: {
                        structure: structureRows.slice(0, topN),
                        typing: typingRows.slice(0, topN),
                        lq: lqRows.slice(0, topN),
                        gap: gapRows.slice(0, topN),
                    },
                };
            },
            _renderTypingMap() {
                const typing = this.h3DerivedStats && this.h3DerivedStats.typingSummary;
                if (!typing || !this.mapCore || !this.mapCore.setGridFeatures) return;
                this.h3StructureRenderStats = null;
                const colorByType = {
                    high_density_high_mix: '#0f766e',
                    high_density_low_mix: '#b45309',
                    low_density_high_mix: '#2563eb',
                    low_density_low_mix: '#64748b',
                    no_data: '#d1d5db',
                };
                const rowMap = {};
                (typing.rows || []).forEach(row => { rowMap[row.h3_id] = row; });
                const styled = (this.h3AnalysisGridFeatures || []).map(feature => {
                    const props = Object.assign({}, feature.properties || {});
                    const row = rowMap[props.h3_id] || {};
                    const typeKey = row.type_key || 'no_data';
                    props.fillColor = colorByType[typeKey] || '#d1d5db';
                    props.fillOpacity = typeKey === 'no_data' ? 0.10 : 0.24;
                    props.strokeColor = '#2c6ecb';
                    props.strokeWeight = 1;
                    return { type: feature.type, geometry: feature.geometry, properties: props };
                });
                this.h3Legend = {
                    title: '功能混合度',
                    unit: '分类',
                    items: [
                        { color: colorByType.high_density_high_mix, label: '高密-高混合' },
                        { color: colorByType.high_density_low_mix, label: '高密-低混合' },
                        { color: colorByType.low_density_high_mix, label: '低密-高混合' },
                        { color: colorByType.low_density_low_mix, label: '低密-低混合' },
                    ],
                    noDataLabel: `无数据（样本<${this.h3EntropyMinPoi}）`,
                    noDataColor: '#d1d5db',
                };
                this.mapCore.setGridFeatures(styled, { fillOpacity: 0.22, strokeWeight: 1.2, webglBatch: true });
                this.tryRefocusSelectedGrid();
            },
            _interpolateHexColor(fromHex, toHex, t) {
                const from = String(fromHex || '#000000').replace('#', '');
                const to = String(toHex || '#000000').replace('#', '');
                if (from.length !== 6 || to.length !== 6) return fromHex || '#000000';
                const ratio = Math.max(0, Math.min(1, this._toNumber(t, 0)));
                const fr = parseInt(from.slice(0, 2), 16);
                const fg = parseInt(from.slice(2, 4), 16);
                const fb = parseInt(from.slice(4, 6), 16);
                const tr = parseInt(to.slice(0, 2), 16);
                const tg = parseInt(to.slice(2, 4), 16);
                const tb = parseInt(to.slice(4, 6), 16);
                const rr = Math.round(fr + (tr - fr) * ratio);
                const rg = Math.round(fg + (tg - fg) * ratio);
                const rb = Math.round(fb + (tb - fb) * ratio);
                return '#' + [rr, rg, rb].map((v) => {
                    const s = v.toString(16);
                    return s.length === 1 ? `0${s}` : s;
                }).join('');
            },
            _resolveContinuousDivergingStyle(value, min, center, max, options = {}) {
                if (!Number.isFinite(value)) return { fillColor: '#000000', fillOpacity: 0 };
                const low = Number.isFinite(this._toNumber(min, NaN)) ? this._toNumber(min, -1) : -1;
                const high = Number.isFinite(this._toNumber(max, NaN)) ? this._toNumber(max, 1) : 1;
                if (!(high > low)) {
                    return {
                        fillColor: options.midColor || '#f8fafc',
                        fillOpacity: options.minOpacity || 0.08,
                    };
                }
                const mid = Number.isFinite(this._toNumber(center, NaN))
                    ? this._toNumber(center, 0)
                    : (low + high) / 2;
                const clamp = (v) => Math.min(high, Math.max(low, v));
                const vv = clamp(value);
                const safeMid = Math.min(high, Math.max(low, mid));
                const minOpacity = Number.isFinite(this._toNumber(options.minOpacity, NaN))
                    ? this._toNumber(options.minOpacity, 0.08)
                    : 0.08;
                const maxOpacity = Number.isFinite(this._toNumber(options.maxOpacity, NaN))
                    ? this._toNumber(options.maxOpacity, 0.48)
                    : 0.48;
                const threshold = Number.isFinite(this._toNumber(options.thresholdAbs, NaN))
                    ? Math.max(0, this._toNumber(options.thresholdAbs, 0))
                    : 0;
                const lowColor = options.lowColor || '#1d4ed8';
                const midColor = options.midColor || '#f8fafc';
                const highColor = options.highColor || '#b91c1c';
                let ratio = 0;
                let color = midColor;
                if (vv >= safeMid) {
                    const span = Math.max(1e-9, high - safeMid);
                    ratio = (vv - safeMid) / span;
                    color = this._interpolateHexColor(midColor, highColor, ratio);
                } else {
                    const span = Math.max(1e-9, safeMid - low);
                    ratio = (safeMid - vv) / span;
                    color = this._interpolateHexColor(midColor, lowColor, ratio);
                }
                if (Math.abs(vv - safeMid) < threshold) {
                    return { fillColor: color, fillOpacity: minOpacity * 0.6 };
                }
                const fillOpacity = minOpacity + (maxOpacity - minOpacity) * Math.max(0, Math.min(1, ratio));
                return { fillColor: color, fillOpacity };
            },
            _resolveGiZFillStyle(zValue, giMeta) {
                const meta = giMeta || { min: -3, max: 3, center: 0 };
                return this._resolveContinuousDivergingStyle(
                    zValue,
                    this._toNumber(meta.min, -3),
                    this._toNumber(meta.center, 0),
                    this._toNumber(meta.max, 3),
                    {
                        lowColor: '#1d4ed8',
                        midColor: '#f8fafc',
                        highColor: '#b91c1c',
                        minOpacity: 0.06,
                        maxOpacity: 0.42,
                        thresholdAbs: 0.2,
                    }
                );
            },
            _resolveLisaIFillStyle(lisaValue, lisaMeta) {
                const meta = lisaMeta || {};
                if (meta.degraded) {
                    if (!Number.isFinite(lisaValue)) return { fillColor: '#000000', fillOpacity: 0 };
                    return { fillColor: '#cbd5e1', fillOpacity: 0.06 };
                }
                return this._resolveContinuousDivergingStyle(
                    lisaValue,
                    this._toNumber(meta.clip_min, this._toNumber(meta.mean, 0)),
                    this._toNumber(meta.mean, 0),
                    this._toNumber(meta.clip_max, this._toNumber(meta.mean, 0)),
                    {
                        lowColor: '#0f766e',
                        midColor: '#f8fafc',
                        highColor: '#f97316',
                        minOpacity: 0.06,
                        maxOpacity: 0.38,
                        thresholdAbs: 0,
                    }
                );
            },
            _formatStructureValue(value) {
                if (!Number.isFinite(this._toNumber(value, NaN))) return '-';
                return this._toNumber(value, 0).toFixed(2);
            },
            _buildGiLegend(giMeta) {
                const meta = giMeta || { min: -3, max: 3, center: 0 };
                const min = this._toNumber(meta.min, -3);
                const max = this._toNumber(meta.max, 3);
                const marks = [min, -2, -1, 0, 1, 2, max];
                const items = [];
                for (let i = 0; i < marks.length - 1; i += 1) {
                    const left = marks[i];
                    const right = marks[i + 1];
                    const mid = (left + right) / 2;
                    const style = this._resolveGiZFillStyle(mid, meta);
                    items.push({
                        color: style.fillColor,
                        label: `${this._formatStructureValue(left)} ~ ${this._formatStructureValue(right)}`,
                    });
                }
                return {
                    title: '结构图（Gi*）',
                    unit: 'GiZScore',
                    items: items,
                    noDataLabel: '|z| 近0或缺失时透明',
                    noDataColor: '#d1d5db',
                };
            },
            _buildLisaLegend(lisaMeta) {
                const meta = lisaMeta || {};
                if (meta.degraded) {
                    return {
                        title: '结构图（LISA）',
                        unit: 'LMiIndex',
                        items: [{ color: '#cbd5e1', label: '方差不足（弱结构）' }],
                        noDataLabel: '无效值透明',
                        noDataColor: '#d1d5db',
                    };
                }
                const mean = this._toNumber(meta.mean, 0);
                const std = Math.max(0, this._toNumber(meta.std, 0));
                const clipMin = this._toNumber(meta.clip_min, mean - 3 * std);
                const clipMax = this._toNumber(meta.clip_max, mean + 3 * std);
                const marks = [clipMin, mean - 2 * std, mean - std, mean, mean + std, mean + 2 * std, clipMax];
                const items = [];
                for (let i = 0; i < marks.length - 1; i += 1) {
                    const left = marks[i];
                    const right = marks[i + 1];
                    const mid = (left + right) / 2;
                    const style = this._resolveLisaIFillStyle(mid, meta);
                    items.push({
                        color: style.fillColor,
                        label: `${this._formatStructureValue(left)} ~ ${this._formatStructureValue(right)}`,
                    });
                }
                return {
                    title: '结构图（LISA）',
                    unit: 'LMiIndex（标准差）',
                    items: items,
                    noDataLabel: '无效值透明',
                    noDataColor: '#d1d5db',
                };
            },
            _renderStructureMapStandalone() {
                const summary = this.h3DerivedStats && this.h3DerivedStats.structureSummary;
                if (!summary || !this.mapCore || !this.mapCore.setGridFeatures) return;
                const mode = this.h3StructureFillMode === 'lisa_i' ? 'lisa_i' : 'gi_z';
                const rowMap = {};
                (summary.rows || []).forEach((row) => { rowMap[row.h3_id] = row; });
                const giMeta = summary.giRenderMeta || this._normalizeGiRenderMeta(this.h3AnalysisSummary && this.h3AnalysisSummary.gi_render_meta);
                const lisaMeta = summary.lisaRenderMeta || this._normalizeLisaRenderMeta(
                    this.h3AnalysisSummary && this.h3AnalysisSummary.lisa_render_meta,
                    summary.lisaIStats
                );
                const styled = (this.h3AnalysisGridFeatures || []).map((feature) => {
                    const props = Object.assign({}, feature.properties || {});
                    const row = rowMap[props.h3_id] || {};
                    const giZValue = Number.isFinite(Number(row.gi_star_z_score))
                        ? Number(row.gi_star_z_score)
                        : (Number.isFinite(Number(props.gi_star_z_score)) ? Number(props.gi_star_z_score) : null);
                    const lisaIValue = Number.isFinite(Number(row.lisa_i))
                        ? Number(row.lisa_i)
                        : (Number.isFinite(Number(props.lisa_i)) ? Number(props.lisa_i) : null);
                    const fillStyle = mode === 'lisa_i'
                        ? this._resolveLisaIFillStyle(lisaIValue, lisaMeta)
                        : this._resolveGiZFillStyle(giZValue, giMeta);
                    props.gi_star_z_score = giZValue;
                    props.lisa_i = lisaIValue;
                    props.fillColor = fillStyle.fillColor;
                    props.fillOpacity = fillStyle.fillOpacity;
                    props.strokeColor = '#2c6ecb';
                    props.strokeWeight = 1;
                    return { type: feature.type, geometry: feature.geometry, properties: props };
                });
                this.h3Legend = mode === 'lisa_i' ? this._buildLisaLegend(lisaMeta) : this._buildGiLegend(giMeta);
                this.mapCore.setGridFeatures(styled, {
                    fillOpacity: 0.22,
                    strokeWeight: 1.2,
                    structureBoundaryEdges: false,
                    webglBatch: true,
                });
                this.h3StructureRenderStats = null;
                this.tryRefocusSelectedGrid();
            },
            _renderLqMap() {
                const lq = this.h3DerivedStats && this.h3DerivedStats.lqSummary;
                if (!lq || !this.mapCore || !this.mapCore.setGridFeatures) return;
                this.h3StructureRenderStats = null;
                const metricSpec = {
                    key: 'lq',
                    label: `${this._getH3CategoryLabel(this.h3TargetCategory)} 区位商优势（LQ）`,
                    unit: '相对值',
                    palette: ['#edf7ed', '#c4e3c4', '#8ccb8c', '#4ea95d', '#1b6e33'],
                    noDataColor: '#d1d5db',
                    noDataOpacity: 0.10,
                    fillOpacity: 0.24,
                    noDataLabel: `无数据（样本<${this.h3EntropyMinPoi}）`,
                };
                const rowMap = {};
                (lq.rows || []).forEach(row => { rowMap[row.h3_id] = row; });
                const validValues = (lq.rows || []).map(r => r.lq_target).filter(v => Number.isFinite(v));
                const breaks = this._buildQuantileBreaks(validValues, 5);
                this.h3Legend = this._buildLegend(metricSpec, breaks, validValues);
                const styled = (this.h3AnalysisGridFeatures || []).map(feature => {
                    const props = Object.assign({}, feature.properties || {});
                    const row = rowMap[props.h3_id] || {};
                    const value = row.lq_target;
                    if (!Number.isFinite(value)) {
                        props.fillColor = metricSpec.noDataColor;
                        props.fillOpacity = metricSpec.noDataOpacity;
                    } else {
                        props.fillColor = this._colorByBreaks(value, breaks, metricSpec.palette);
                        props.fillOpacity = metricSpec.fillOpacity;
                    }
                    props.strokeColor = '#2c6ecb';
                    props.strokeWeight = 1;
                    return { type: feature.type, geometry: feature.geometry, properties: props };
                });
                this.mapCore.setGridFeatures(styled, { fillOpacity: 0.22, strokeWeight: 1.2, webglBatch: true });
                this.tryRefocusSelectedGrid();
            },
            _renderGapMap() {
                const gap = this.h3DerivedStats && this.h3DerivedStats.gapSummary;
                if (!gap || !this.mapCore || !this.mapCore.setGridFeatures) return;
                this.h3StructureRenderStats = null;
                const metricSpec = {
                    key: 'gap',
                    label: `${this._getH3CategoryLabel(this.h3TargetCategory)} 缺口分`,
                    unit: '百分位差值',
                    palette: ['#2b6cb0', '#90cdf4', '#f7f7f7', '#f6ad55', '#c53030'],
                    noDataColor: '#d1d5db',
                    noDataOpacity: 0.10,
                    fillOpacity: 0.24,
                    noDataLabel: '',
                };
                const rowMap = {};
                (gap.rows || []).forEach(row => { rowMap[row.h3_id] = row; });
                const validValues = (gap.rows || []).map(r => r.gap_score).filter(v => Number.isFinite(v));
                const breaks = this._buildDivergingBreaks(validValues);
                this.h3Legend = this._buildLegend(metricSpec, breaks, validValues);
                const styled = (this.h3AnalysisGridFeatures || []).map(feature => {
                    const props = Object.assign({}, feature.properties || {});
                    const row = rowMap[props.h3_id] || {};
                    const value = row.gap_score;
                    if (!Number.isFinite(value)) {
                        props.fillColor = metricSpec.noDataColor;
                        props.fillOpacity = metricSpec.noDataOpacity;
                    } else {
                        props.fillColor = this._colorByBreaks(value, breaks, metricSpec.palette);
                        props.fillOpacity = metricSpec.fillOpacity;
                    }
                    props.strokeColor = '#2c6ecb';
                    props.strokeWeight = 1;
                    return { type: feature.type, geometry: feature.geometry, properties: props };
                });
                this.mapCore.setGridFeatures(styled, { fillOpacity: 0.22, strokeWeight: 1.2, webglBatch: true });
                this.tryRefocusSelectedGrid();
            },
            renderH3BySubTab() {
                if (!this.isH3DisplayActive()) {
                    this.clearH3GridDisplayOnLeave();
                    return;
                }
                if (!this.h3AnalysisGridFeatures || !this.h3AnalysisGridFeatures.length) {
                    this.h3Legend = null;
                    return;
                }
                if (this.h3SubTab === 'structure_map') {
                    this._renderStructureMapStandalone();
                } else if (this.h3SubTab === 'typing') {
                    this._renderTypingMap();
                } else if (this.h3SubTab === 'lq') {
                    this._renderLqMap();
                } else if (this.h3SubTab === 'gap') {
                    this._renderGapMap();
                } else {
                    this.renderH3AnalysisGrid(this.h3MetricView);
                }
            },
            updateDecisionCards() {
                if (!window.echarts || !this.h3DerivedStats) return;
                const lqEl = document.getElementById('h3LqChart');
                const gapEl = document.getElementById('h3GapChart');
                const structureEl = document.getElementById('h3StructureChart');
                if (!this.h3ChartsResizeHandler) {
                    this.h3ChartsResizeHandler = () => {
                        if (this.h3CategoryChart) this.h3CategoryChart.resize();
                        if (this.h3DensityChart) this.h3DensityChart.resize();
                        if (this.h3LqChart) this.h3LqChart.resize();
                        if (this.h3GapChart) this.h3GapChart.resize();
                        if (this.h3StructureChart) this.h3StructureChart.resize();
                    };
                    window.addEventListener('resize', this.h3ChartsResizeHandler);
                }

                if (structureEl && this.h3SubTab === 'structure_map') {
                    let chart = echarts.getInstanceByDom(structureEl);
                    if (!chart) chart = echarts.init(structureEl);
                    this.h3StructureChart = chart;
                    const summary = this.h3DerivedStats.structureSummary || {};
                    const structureMode = this.h3StructureFillMode === 'lisa_i' ? 'lisa_i' : 'gi_z';
                    const giStats = summary.giZStats || {};
                    const lisaStats = summary.lisaIStats || {};
                    const labels = ['均值', '中位数', 'P90', 'P10', '最小', '最大'];
                    const activeStats = structureMode === 'lisa_i' ? lisaStats : giStats;
                    const activeSeriesName = structureMode === 'lisa_i' ? 'LISA I' : 'Gi* Z';
                    const activeSeriesColor = structureMode === 'lisa_i' ? '#0f766e' : '#b91c1c';
                    const activeValues = [
                        this._toNumber(activeStats.mean, 0),
                        this._toNumber(activeStats.p50, 0),
                        this._toNumber(activeStats.p90, 0),
                        this._toNumber(activeStats.p10, 0),
                        this._toNumber(activeStats.min, 0),
                        this._toNumber(activeStats.max, 0),
                    ];
                    chart.setOption({
                        title: { text: `结构连续指标概览（${activeSeriesName}）`, left: 'center', top: 2, textStyle: { fontSize: 12 } },
                        grid: { left: 44, right: 14, top: 28, bottom: 24, containLabel: true },
                        legend: { top: 4, right: 8, itemWidth: 10, itemHeight: 8, textStyle: { fontSize: 11 } },
                        xAxis: { type: 'value', splitLine: { lineStyle: { color: '#eceff3' } } },
                        yAxis: {
                            type: 'category',
                            data: labels,
                            axisTick: { show: false },
                            axisLine: { show: false }
                        },
                        series: [
                            {
                                name: activeSeriesName,
                                type: 'bar',
                                data: activeValues,
                                barWidth: 10,
                                itemStyle: { color: activeSeriesColor },
                            }
                        ]
                    }, true);
                }

                if (lqEl && this.h3SubTab === 'lq') {
                    let chart = echarts.getInstanceByDom(lqEl);
                    if (!chart) chart = echarts.init(lqEl);
                    this.h3LqChart = chart;
                    const summary = this.h3DerivedStats.lqSummary || {};
                    const labels = (this.h3CategoryMeta || []).map(item => item.label);
                    const values = (this.h3CategoryMeta || []).map(item => this._toNumber((summary.dominantCounts || {})[item.key], 0));
                    chart.setOption({
                        title: { text: '主导优势类别分布', left: 'center', top: 2, textStyle: { fontSize: 12 } },
                        grid: { left: 44, right: 14, top: 28, bottom: 24, containLabel: true },
                        xAxis: { type: 'value', minInterval: 1, splitLine: { lineStyle: { color: '#eceff3' } } },
                        yAxis: { type: 'category', data: labels, axisTick: { show: false }, axisLine: { show: false } },
                        series: [{ type: 'bar', data: values, barWidth: 12, itemStyle: { color: '#4f8ad9' } }]
                    }, true);
                }

                if (gapEl && this.h3SubTab === 'gap') {
                    let chart = echarts.getInstanceByDom(gapEl);
                    if (!chart) chart = echarts.init(gapEl);
                    this.h3GapChart = chart;
                    const rows = ((this.h3DerivedStats.gapSummary || {}).rows || []);
                    const data = rows.map((row) => {
                        const demandPct = Math.max(0, Math.min(1, this._toNumber(row.demand_pct, 0)));
                        const supplyPct = Math.max(0, Math.min(1, this._toNumber(row.supply_pct, 0)));
                        const gapScore = this._toNumber(row.gap_score, 0);
                        const poiCount = Math.max(0, this._toNumber(row.poi_count, 0));
                        const symbolSize = Math.max(8, Math.min(26, 8 + Math.sqrt(poiCount) * 2));
                        return {
                            h3_id: row.h3_id,
                            gap_zone_label: row.gap_zone_label || '',
                            confidence_label: (row.confidence && row.confidence.label) || '低',
                            demand_pct: demandPct,
                            supply_pct: supplyPct,
                            gap_score: gapScore,
                            poi_count: poiCount,
                            symbolSize: symbolSize,
                            value: [Math.round(supplyPct * 100), Math.round(demandPct * 100), gapScore]
                        };
                    });
                    chart.setOption({
                        title: { text: '需求-供给散点（每点=网格）', left: 'center', top: 2, textStyle: { fontSize: 12 } },
                        grid: { left: 54, right: 14, top: 28, bottom: 34, containLabel: true },
                        tooltip: {
                            trigger: 'item',
                            formatter: (params) => {
                                const d = params.data || {};
                                const hid = d.h3_id || '-';
                                return [
                                    `<b>${this.shortH3Id(hid)}</b>`,
                                    `需求分位: ${d.value ? d.value[1] : 0}`,
                                    `供给分位: ${d.value ? d.value[0] : 0}`,
                                    `缺口分: ${this._toNumber(d.gap_score, 0).toFixed(2)}`,
                                    `可信度: ${d.confidence_label || '-'}`,
                                    `结论: ${d.gap_zone_label || '-'}`,
                                ].join('<br/>');
                            }
                        },
                        xAxis: {
                            type: 'value',
                            name: '供给百分位',
                            min: 0,
                            max: 100,
                            splitLine: { lineStyle: { color: '#eceff3' } }
                        },
                        yAxis: {
                            type: 'value',
                            name: '需求百分位',
                            min: 0,
                            max: 100,
                            splitLine: { lineStyle: { color: '#eceff3' } }
                        },
                        series: [{
                            type: 'scatter',
                            data: data,
                            symbolSize: (item) => item.symbolSize || 10,
                            itemStyle: {
                                color: (params) => {
                                    const gap = this._toNumber(params && params.data && params.data.gap_score, 0);
                                    if (gap >= 0.25) return '#d8573f';
                                    if (gap <= -0.25) return '#3f7fd8';
                                    return '#93a5bf';
                                },
                                opacity: 0.85
                            },
                            emphasis: {
                                itemStyle: {
                                    borderColor: '#111827',
                                    borderWidth: 1
                                }
                            },
                            markLine: {
                                silent: true,
                                symbol: ['none', 'none'],
                                lineStyle: { type: 'dashed', color: '#cbd5e1' },
                                data: [{ xAxis: 50 }, { yAxis: 50 }]
                            }
                        }]
                    }, true);
                    chart.off('click');
                    chart.on('click', (params) => {
                        const h3Id = params && params.data && params.data.h3_id;
                        if (h3Id) this.focusGridByH3Id(h3Id);
                    });
                }
            },
            renderH3AnalysisGrid(metricKey) {
                const source = this.h3AnalysisGridFeatures;
                if (!this.isH3DisplayActive()) {
                    this.clearH3GridDisplayOnLeave();
                    return;
                }
                if (!Array.isArray(source) || source.length === 0 || !this.mapCore || !this.mapCore.setGridFeatures) {
                    this.h3Legend = null;
                    return;
                }
                this.h3StructureRenderStats = null;

                const metricSpec = this._getMetricSpec(metricKey);
                const measured = source.map((feature) => {
                    const datum = this._getH3MetricValue((feature && feature.properties) || {}, metricKey);
                    return {
                        feature: feature,
                        value: datum.value,
                        noData: datum.noData
                    };
                });
                const validValues = measured
                    .filter(item => !item.noData && Number.isFinite(item.value))
                    .map(item => item.value);
                const breaks = metricSpec.diverging
                    ? this._buildDivergingBreaks(validValues)
                    : this._buildQuantileBreaks(validValues, 5);
                this.h3Legend = this._buildLegend(metricSpec, breaks, validValues);

                const styled = measured.map((item) => {
                    const feature = item.feature;
                    const props = Object.assign({}, feature.properties || {});
                    if (item.noData || !Number.isFinite(item.value)) {
                        props.fillColor = metricSpec.noDataColor;
                        props.fillOpacity = metricSpec.noDataOpacity;
                        props.metric_value = null;
                        props.metric_no_data = true;
                    } else {
                        props.fillColor = this._colorByBreaks(item.value, breaks, metricSpec.palette);
                        props.fillOpacity = metricSpec.fillOpacity;
                        props.metric_value = item.value;
                        props.metric_no_data = false;
                    }
                    props.strokeColor = '#2c6ecb';
                    props.strokeWeight = 1;

                    return {
                        type: feature.type,
                        geometry: feature.geometry,
                        properties: props
                    };
                });

                this.mapCore.setGridFeatures(styled, {
                    fillOpacity: 0.22,
                    strokeWeight: 1.2,
                    structureBoundaryEdges: false,
                    structureBoundaryGi: false,
                    structureBoundaryLisa: false,
                    webglBatch: true,
                });
                this.tryRefocusSelectedGrid();
            },
            getH3CurrentStageTabs() {
                const fallback = ['metric_map'];
                const stageTabs = this.h3MainStageTabs || {};
                const tabs = stageTabs[this.h3MainStage] || fallback;
                return Array.isArray(tabs) && tabs.length ? tabs : fallback;
            },
            getH3DefaultSubTabByStage(stage) {
                const stageTabs = this.h3MainStageTabs || {};
                const tabs = stageTabs[stage];
                if (Array.isArray(tabs) && tabs.length) return tabs[0];
                return 'metric_map';
            },
            resolveH3MainStageBySubTab(tab) {
                const stageTabs = this.h3MainStageTabs || {};
                const stageOrder = ['analysis', 'diagnosis', 'evaluate'];
                for (const stage of stageOrder) {
                    const tabs = stageTabs[stage];
                    if (Array.isArray(tabs) && tabs.includes(tab)) return stage;
                }
                return 'analysis';
            },
            async onH3MainStageChange(stage) {
                if (stage !== 'params' && stage !== 'analysis' && stage !== 'diagnosis' && stage !== 'evaluate') return;
                this.h3MainStage = stage;
                if (stage === 'params') {
                    this.h3ParamsSubTab = 'grid';
                    return;
                }
                const targetTab = this.getH3DefaultSubTabByStage(stage);
                await this.onH3SubTabChange(targetTab);
            },
            onH3MetricViewChange() {
                if (!this.h3AnalysisGridFeatures.length) return;
                if (this.h3SubTab !== 'metric_map') return;
                this.refreshMetricMapView();
            },
            onH3StructureFillModeChange() {
                if (!this.h3AnalysisGridFeatures.length) return;
                if (this.h3SubTab !== 'structure_map') return;
                this._renderStructureMapStandalone();
                this.$nextTick(() => {
                    this.updateDecisionCards();
                });
            },
            async refreshMetricMapView() {
                if (!this.h3AnalysisGridFeatures.length) return;
                if (this.h3SubTab !== 'metric_map') return;
                this.renderH3AnalysisGrid(this.h3MetricView);
                await this.$nextTick();
                this.updateH3Charts();
            },
            async onH3SubTabChange(tab) {
                this.h3SubTab = tab;
                this.h3MainStage = this.resolveH3MainStageBySubTab(tab);
                if (!this.h3AnalysisGridFeatures.length) return;
                this.computeH3DerivedStats();
                await this.$nextTick();
                this.renderH3BySubTab();
                await this.$nextTick();
                this.updateH3Charts();
                this.updateDecisionCards();
            },
            async onH3DecisionSettingsChange() {
                if (!this.h3AnalysisGridFeatures.length) return;
                this.computeH3DerivedStats();
                await this.$nextTick();
                this.renderH3BySubTab();
                await this.$nextTick();
                this.updateH3Charts();
                this.updateDecisionCards();
            },
            async computeH3Analysis() {
                const rawRing = this.getIsochronePolygonRing();
                if (!rawRing || this.isComputingH3Analysis) return;
                const progressRunId = `h3-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
                const stageLabelMap = {
                    queued: '排队中',
                    build_grid: '生成网格中',
                    aggregate_poi: '聚合 POI 中',
                    compute_metrics: '计算指标中',
                    arcgis_prepare: '准备 ArcGIS 中',
                    arcgis_running: 'ArcGIS 热点分析中',
                    finalize: '整理结果中',
                    completed: '已完成',
                    failed: '失败',
                };
                let progressTimer = null;
                let latestProgress = {
                    run_id: progressRunId,
                    status: 'running',
                    stage: 'queued',
                    message: '已接收请求，等待开始计算',
                    step: 0,
                    total: 7,
                    elapsed_sec: 0,
                    extra: {},
                };
                const applyProgress = (snapshot = {}) => {
                    latestProgress = {
                        ...latestProgress,
                        ...snapshot,
                        extra: snapshot && typeof snapshot.extra === 'object' ? { ...snapshot.extra } : { ...latestProgress.extra },
                    };
                    const stage = String(latestProgress.stage || 'queued');
                    const label = stageLabelMap[stage] || String(latestProgress.message || '计算中');
                    const total = Number(latestProgress.total || 0) || 7;
                    const step = Math.max(0, Math.min(total, Number(latestProgress.step || 0) || 0));
                    const sec = Math.max(0, Math.floor(Number(latestProgress.elapsed_sec || 0) || 0));
                    const detail = String(latestProgress.message || '').trim();
                    this.h3GridStatus = `网格分析进度 ${step}/${total}：${label}${detail && detail !== label ? ` · ${detail}` : ''}（${sec}s）`;
                    this.h3AnalysisProgress = { ...latestProgress };
                };
                const pollProgress = async () => {
                    try {
                        const resp = await fetch(`/api/v1/analysis/h3-metrics/progress?run_id=${encodeURIComponent(progressRunId)}`, {
                            cache: 'no-store',
                        });
                        if (!resp.ok) return;
                        const data = await resp.json();
                        applyProgress(data || {});
                    } catch (_) {
                    }
                };
                this.isComputingH3Analysis = true;
                applyProgress(latestProgress);
                progressTimer = window.setInterval(() => {
                    if (!this.isComputingH3Analysis) return;
                    pollProgress();
                }, 800);
                try {
                    const polygon = this.getIsochronePolygonPayload();
                    const neighborRing = Math.max(1, Math.min(3, Math.round(this._toNumber(this.h3NeighborRing, 1))));
                    this.h3NeighborRing = neighborRing;
                    const analysisPois = this._buildH3AnalysisPois();
                    if (!analysisPois.length) {
                        throw new Error('当前“分析POI”配置下无可计算样本，请先在参数页勾选至少一个有数据的POI分类');
                    }

                    const payload = {
                        polygon: polygon,
                        resolution: this.h3GridResolution,
                        coord_type: 'gcj02',
                        include_mode: this.h3GridIncludeMode,
                        min_overlap_ratio: this.h3GridIncludeMode === 'intersects' ? this.h3GridMinOverlapRatio : 0,
                        pois: analysisPois,
                        poi_coord_type: 'gcj02',
                        neighbor_ring: neighborRing,
                        use_arcgis: true,
                        arcgis_neighbor_ring: neighborRing,
                        arcgis_export_image: false,
                        arcgis_timeout_sec: 240,
                        run_id: progressRunId,
                    };
                    const res = await fetch('/api/v1/analysis/h3-metrics', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload),
                    });
                    if (!res.ok) {
                        let detail = '';
                        try {
                            const errJson = await res.json();
                            if (errJson && typeof errJson === 'object') {
                                detail = errJson.detail || JSON.stringify(errJson);
                            } else {
                                detail = String(errJson || '');
                            }
                        } catch (_) {
                            try { detail = await res.text(); } catch (_) { }
                        }
                        throw new Error(detail || '网格分析失败');
                    }
                    await pollProgress();
                    const data = await res.json();
                    const grid = data.grid || {};
                    this.h3AnalysisGridFeatures = grid.features || [];
                    this.h3GridFeatures = this.h3AnalysisGridFeatures;
                    this.h3GridCount = Number.isFinite(grid.count) ? grid.count : this.h3AnalysisGridFeatures.length;
                    this.h3AnalysisSummary = data.summary || null;
                    this.h3AnalysisCharts = data.charts || null;
                    // 分析完成后默认进入“分析”主栏，避免停留在参数页。
                    this.h3MainStage = 'analysis';
                    this.h3SubTab = this.getH3DefaultSubTabByStage('analysis');
                    this.h3ArcgisSnapshotLoadError = false;
                    this.h3ArcgisImageVersion = Date.now();
                    this.computeH3DerivedStats();
                    const baseStatus = this.h3GridCount > 0
                        ? `分析完成：${this.h3GridCount} 个网格，${(this.h3AnalysisSummary && this.h3AnalysisSummary.poi_count) || 0} 个POI`
                        : '分析完成，但当前范围无可用网格';
                    await pollProgress();
                    applyProgress({ status: 'success', stage: 'completed', message: 'H3 网格分析计算完成' });
                    if (this.isH3DisplayActive()) {
                        this.renderH3BySubTab();
                        if (this.isH3PanelActive()) {
                            await this.$nextTick();
                            this.updateH3Charts();
                            this.updateDecisionCards();
                        }
                        this.h3GridStatus = baseStatus;
                    } else {
                        this.clearH3GridDisplayOnLeave();
                        this.h3GridStatus = `${baseStatus}（已就绪，切换到“网格”查看）`;
                    }
                    if (typeof this.saveAnalysisHistoryAsync === 'function') {
                        this.saveAnalysisHistoryAsync(
                            this.getIsochronePolygonPayload(),
                            typeof this.buildSelectedCategoryBuckets === 'function' ? this.buildSelectedCategoryBuckets() : [],
                            this.allPoisDetails
                        );
                    }
                    if (typeof this.commitCurrentPoiGridResult === 'function') {
                        this.commitCurrentPoiGridResult('h3', Number(this.poiYearSource || this.resultPoiYear || 0) || null);
                    }
                    return { progress: { ...latestProgress } };
                } catch (e) {
                    console.error(e);
                    applyProgress({ status: 'failed', stage: 'failed', message: String((e && e.message) || e || '网格分析失败') });
                    this.h3GridStatus = '网格分析失败: ' + e.message;
                    throw e;
                } finally {
                    if (progressTimer) {
                        window.clearInterval(progressTimer);
                        progressTimer = null;
                    }
                    this.isComputingH3Analysis = false;
                }
            },
            async generateH3ArcgisSnapshot() {
                if (this.isComputingH3Analysis || this.isGeneratingH3ArcgisSnapshot) return;
                if (!this.h3AnalysisGridFeatures || this.h3AnalysisGridFeatures.length === 0) {
                    this.h3GridStatus = '请先完成网格分析，再生成结构快照';
                    return;
                }
                const rawRing = this.getIsochronePolygonRing();
                if (!rawRing) {
                    this.h3GridStatus = '当前无有效范围，无法生成结构快照';
                    return;
                }
                this.isGeneratingH3ArcgisSnapshot = true;
                this.h3ArcgisSnapshotLoadError = false;
                const startedAt = Date.now();
                this.h3GridStatus = '正在生成 ArcGIS 结构快照...';
                try {
                    const polygon = this.getIsochronePolygonPayload();
                    const neighborRing = Math.max(1, Math.min(3, Math.round(this._toNumber(this.h3NeighborRing, 1))));
                    const analysisPois = this._buildH3AnalysisPois();
                    if (!analysisPois.length) {
                        throw new Error('当前“分析POI”配置下无可计算样本，请先勾选至少一个有数据的POI分类');
                    }
                    const payload = {
                        polygon: polygon,
                        resolution: this.h3GridResolution,
                        coord_type: 'gcj02',
                        include_mode: this.h3GridIncludeMode,
                        min_overlap_ratio: this.h3GridIncludeMode === 'intersects' ? this.h3GridMinOverlapRatio : 0,
                        pois: analysisPois,
                        poi_coord_type: 'gcj02',
                        neighbor_ring: neighborRing,
                        use_arcgis: true,
                        arcgis_neighbor_ring: neighborRing,
                        arcgis_export_image: true,
                        arcgis_timeout_sec: 240
                    };
                    const res = await fetch('/api/v1/analysis/h3-metrics', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload),
                    });
                    if (!res.ok) {
                        let detail = '';
                        try {
                            const errJson = await res.json();
                            if (errJson && typeof errJson === 'object') {
                                detail = errJson.detail || JSON.stringify(errJson);
                            } else {
                                detail = String(errJson || '');
                            }
                        } catch (_) {
                            try { detail = await res.text(); } catch (_) { }
                        }
                        throw new Error(detail || '结构快照生成失败');
                    }
                    const data = await res.json();
                    const grid = data.grid || {};
                    if (Array.isArray(grid.features) && grid.features.length) {
                        this.h3AnalysisGridFeatures = grid.features;
                        this.h3GridFeatures = this.h3AnalysisGridFeatures;
                        this.h3GridCount = Number.isFinite(grid.count) ? grid.count : this.h3AnalysisGridFeatures.length;
                    }
                    this.h3AnalysisSummary = data.summary || this.h3AnalysisSummary;
                    this.h3AnalysisCharts = data.charts || this.h3AnalysisCharts;
                    this.computeH3DerivedStats();
                    this.h3ArcgisImageVersion = Date.now();
                    this.h3ArcgisSnapshotLoadError = false;
                    const sec = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
                    if (this.isH3DisplayActive()) {
                        this.renderH3BySubTab();
                        if (this.isH3PanelActive()) {
                            await this.$nextTick();
                            this.updateH3Charts();
                            this.updateDecisionCards();
                        }
                        this.h3GridStatus = `ArcGIS 结构快照已生成（${sec}s）`;
                    } else {
                        this.clearH3GridDisplayOnLeave();
                        this.h3GridStatus = `ArcGIS 结构快照已生成（${sec}s），切换到“网格”查看`;
                    }
                    if (typeof this.commitCurrentPoiGridResult === 'function') {
                        this.commitCurrentPoiGridResult('h3', Number(this.poiYearSource || this.resultPoiYear || 0) || null);
                    }
                } catch (e) {
                    console.error(e);
                    this.h3GridStatus = '结构快照生成失败: ' + ((e && e.message) ? e.message : String(e));
                } finally {
                    this.isGeneratingH3ArcgisSnapshot = false;
                }
            },
            disposeH3Charts() {
                if (this.h3CategoryChart) {
                    this.h3CategoryChart.dispose();
                    this.h3CategoryChart = null;
                }
                if (this.h3DensityChart) {
                    this.h3DensityChart.dispose();
                    this.h3DensityChart = null;
                }
                if (this.h3LqChart) {
                    this.h3LqChart.dispose();
                    this.h3LqChart = null;
                }
                if (this.h3GapChart) {
                    this.h3GapChart.dispose();
                    this.h3GapChart = null;
                }
                if (this.h3StructureChart) {
                    this.h3StructureChart.dispose();
                    this.h3StructureChart = null;
                }
                if (this.h3ChartsResizeHandler) {
                    window.removeEventListener('resize', this.h3ChartsResizeHandler);
                    this.h3ChartsResizeHandler = null;
                }
                if (this.h3ChartsRetryTimer) {
                    window.clearTimeout(this.h3ChartsRetryTimer);
                    this.h3ChartsRetryTimer = null;
                }
                this.h3ChartsRetryCount = 0;
            },
            _clearH3ChartRetryTimer() {
                if (this.h3ChartsRetryTimer) {
                    window.clearTimeout(this.h3ChartsRetryTimer);
                    this.h3ChartsRetryTimer = null;
                }
                this.h3ChartsRetryCount = 0;
            },
            _scheduleH3ChartRetry() {
                if (!this.isH3PanelActive()) return;
                if (this.h3ChartsRetryTimer) return;
                if (this.h3ChartsRetryCount >= 8) return;
                this.h3ChartsRetryCount += 1;
                this.h3ChartsRetryTimer = window.setTimeout(() => {
                    this.h3ChartsRetryTimer = null;
                    if (!this.isH3PanelActive()) return;
                    this.updateH3Charts();
                    this.updateDecisionCards();
                }, 90);
            },
            _resolveCategoryColors(labels) {
                const colorByName = {};
                (this.poiCategories || []).forEach((item) => {
                    colorByName[item.name] = item.color || '#888';
                });
                return (labels || []).map(label => colorByName[label] || '#5b8ff9');
            },
            _buildHistogram(values, metricKey, binCount = 8) {
                const valid = (values || [])
                    .map(v => this._toNumber(v, NaN))
                    .filter(v => Number.isFinite(v));
                if (!valid.length) {
                    return { bins: [], counts: [] };
                }
                const minV = Math.min(...valid);
                const maxV = Math.max(...valid);
                if (Math.abs(maxV - minV) < 1e-12) {
                    const label = `${this._formatLegendValue(minV, metricKey)} ~ ${this._formatLegendValue(maxV, metricKey)}`;
                    return { bins: [label], counts: [valid.length] };
                }

                const bins = [];
                const counts = new Array(binCount).fill(0);
                const span = maxV - minV;
                const step = span / binCount;
                for (let i = 0; i < binCount; i += 1) {
                    const start = minV + step * i;
                    const end = i === binCount - 1 ? maxV : (minV + step * (i + 1));
                    bins.push(`${this._formatLegendValue(start, metricKey)} ~ ${this._formatLegendValue(end, metricKey)}`);
                }
                for (const v of valid) {
                    let idx = Math.floor((v - minV) / step);
                    if (!Number.isFinite(idx)) idx = 0;
                    if (idx < 0) idx = 0;
                    if (idx >= binCount) idx = binCount - 1;
                    counts[idx] += 1;
                }
                return { bins, counts };
            },
            _resolveMetricHistogram(metricKey) {
                const source = this.h3AnalysisGridFeatures || [];
                const values = source.map((feature) => {
                    const props = (feature && feature.properties) || {};
                    const datum = this._getH3MetricValue(props, metricKey);
                    return datum.noData ? null : datum.value;
                }).filter(v => Number.isFinite(v));

                if (metricKey === 'entropy') {
                    const hist = this._buildHistogram(values, 'entropy', 10);
                    return {
                        title: '局部熵分布（0~1）',
                        xAxisName: '熵区间',
                        bins: hist.bins,
                        counts: hist.counts,
                        color: '#4cae63',
                        subtext: '仅统计样本数足够的网格',
                    };
                }
                if (metricKey === 'neighbor_delta') {
                    const hist = this._buildHistogram(values, 'neighbor_delta', 8);
                    return {
                        title: '邻域差值分布（POI/km²）',
                        xAxisName: '差值区间（本格-邻域）',
                        bins: hist.bins,
                        counts: hist.counts,
                        color: '#3f7fd8',
                        subtext: '正值表示高于邻域，负值表示低于邻域',
                    };
                }

                const densityData = this.h3AnalysisCharts && this.h3AnalysisCharts.density_histogram
                    ? this.h3AnalysisCharts.density_histogram
                    : null;
                if (densityData && Array.isArray(densityData.bins) && Array.isArray(densityData.counts)) {
                    return {
                        title: '密度分布（POI/km²）',
                        xAxisName: '密度区间 (POI/km²)',
                        bins: densityData.bins,
                        counts: densityData.counts.map(v => this._toNumber(v, 0)),
                        color: '#4c8bf5',
                        subtext: '',
                    };
                }

                const hist = this._buildHistogram(values, 'density', 8);
                return {
                    title: '密度分布（POI/km²）',
                    xAxisName: '密度区间 (POI/km²)',
                    bins: hist.bins,
                    counts: hist.counts,
                    color: '#4c8bf5',
                    subtext: '',
                };
            },
            updateH3Charts() {
                if (!window.echarts || !this.h3AnalysisCharts) {
                    this._clearH3ChartRetryTimer();
                    return;
                }
                const categoryEl = document.getElementById('h3CategoryChart');
                const densityEl = document.getElementById('h3DensityChart');
                if (!categoryEl || !densityEl) {
                    this._clearH3ChartRetryTimer();
                    return;
                }
                if (categoryEl.clientWidth === 0 || densityEl.clientWidth === 0) {
                    this._scheduleH3ChartRetry();
                    return;
                }
                this._clearH3ChartRetryTimer();

                if (!this.h3ChartsResizeHandler) {
                    this.h3ChartsResizeHandler = () => {
                        if (this.h3CategoryChart) this.h3CategoryChart.resize();
                        if (this.h3DensityChart) this.h3DensityChart.resize();
                        if (this.h3LqChart) this.h3LqChart.resize();
                        if (this.h3GapChart) this.h3GapChart.resize();
                        if (this.h3StructureChart) this.h3StructureChart.resize();
                    };
                    window.addEventListener('resize', this.h3ChartsResizeHandler);
                }

                let categoryChart = echarts.getInstanceByDom(categoryEl);
                if (!categoryChart) categoryChart = echarts.init(categoryEl);
                this.h3CategoryChart = categoryChart;

                let densityChart = echarts.getInstanceByDom(densityEl);
                if (!densityChart) densityChart = echarts.init(densityEl);
                this.h3DensityChart = densityChart;

                const categoryData = this.h3AnalysisCharts.category_distribution || {};
                const categoryLabels = categoryData.labels || [];
                const categoryValues = (categoryData.values || []).map(v => this._toNumber(v, 0));
                const categoryColors = this._resolveCategoryColors(categoryLabels);
                categoryChart.setOption(
                    {
                        animationDuration: 240,
                        grid: { left: 48, right: 12, top: 22, bottom: 20, containLabel: true },
                        xAxis: {
                            type: 'value',
                            axisLine: { show: false },
                            axisTick: { show: false },
                            splitLine: { lineStyle: { color: '#eceff3' } },
                            minInterval: 1,
                        },
                        yAxis: {
                            type: 'category',
                            inverse: true,
                            data: categoryLabels,
                            axisLine: { show: false },
                            axisTick: { show: false },
                        },
                        series: [{
                            type: 'bar',
                            data: categoryValues,
                            barWidth: 12,
                            itemStyle: { color: (params) => categoryColors[params.dataIndex] || '#5b8ff9' },
                            label: {
                                show: true,
                                position: 'right',
                                formatter: '{c}',
                                color: '#555',
                                fontSize: 11
                            }
                        }]
                    },
                    true
                );

                const metricHist = this._resolveMetricHistogram(this.h3MetricView || 'density');
                const bins = metricHist.bins || [];
                const counts = (metricHist.counts || []).map(v => this._toNumber(v, 0));
                const densitySubtext = metricHist.subtext || '';
                densityChart.setOption(
                    {
                        title: {
                            text: metricHist.title || '指标分布',
                            subtext: densitySubtext,
                            left: 'center',
                            top: 0,
                            textStyle: { fontSize: 12, fontWeight: 600, color: '#374151' },
                            subtextStyle: { fontSize: 10, color: '#6b7280' }
                        },
                        animationDuration: 240,
                        grid: { left: 44, right: 16, top: densitySubtext ? 52 : 36, bottom: 40, containLabel: true },
                        xAxis: {
                            type: 'category',
                            data: bins,
                            name: metricHist.xAxisName || '区间',
                            nameLocation: 'middle',
                            nameGap: 28,
                            nameTextStyle: { color: '#6b7280', fontSize: 10 },
                            axisLabel: {
                                color: '#6b7280',
                                fontSize: 10,
                                interval: 0,
                                rotate: bins.length > 6 ? 35 : 0,
                            },
                            axisLine: { lineStyle: { color: '#d7dce3' } }
                        },
                        yAxis: {
                            type: 'value',
                            minInterval: 1,
                            name: '网格数',
                            nameLocation: 'middle',
                            nameGap: 34,
                            nameTextStyle: { color: '#6b7280', fontSize: 10 },
                            axisLine: { show: false },
                            axisTick: { show: false },
                            splitLine: { lineStyle: { color: '#eceff3' } }
                        },
                        series: [{
                            type: 'bar',
                            data: counts,
                            barMaxWidth: 20,
                            itemStyle: { color: metricHist.color || '#4c8bf5' }
                        }]
                    },
                    true
                );
            },
        };
    }

export { createAnalysisH3InitialState, createAnalysisH3Methods };
