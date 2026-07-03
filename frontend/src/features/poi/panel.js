    function createEmptyPoiKdeStats() {
        return {
            visiblePointCount: 0,
            maxIntensity: 6,
            topCategoryRows: [],
            chartRows: [],
        };
    }

    function clonePoiGridValue(value) {
        if (value === undefined || value === null) return Array.isArray(value) ? [] : {};
        try {
            return JSON.parse(JSON.stringify(value));
        } catch (_) {
            return Array.isArray(value) ? value.slice() : Object.assign({}, value);
        }
    }

    function createEmptyH3DerivedStats() {
        return {
            structureSummary: null,
            typingSummary: null,
            lqSummary: null,
            gapSummary: null,
            topCells: {},
        };
    }

    function createAnalysisPoiInitialState() {
        return {
            poiMarkers: [],
            allPoisDetails: [],
            poiChart: null,
            poiChartResizeHandler: null,
            poiSubTab: 'category',
            poiAnalysisSubTab: 'kde',
            poiGridType: 'shared',
            poiGridConfigExpanded: false,
            isLoadingPoiGrid: false,
            poiGridStatus: '',
            poiGridProgress: null,
            poiGridFeatures: [],
            poiGridSummary: null,
            poiGridResultsByYearType: {},
            activePoiGridResultKey: '',
            selectedPoiGridCellId: null,
            poiKdeEnabled: false,
            poiKdeRadius: 28,
            poiKdeStats: createEmptyPoiKdeStats(),
            poiCategorySummary: [],
            poiFetchErrors: [],
        };
    }

    function createAnalysisPoiPanelMethods() {
        return {
            createEmptyPoiKdeStats,
            initPoiChart() {
                const el = document.getElementById('poiChart');
                if (!el || !window.echarts || el.clientWidth === 0) return null;

                let chart = echarts.getInstanceByDom(el);
                if (!chart) {
                    chart = echarts.init(el);
                    if (!this.poiChartResizeHandler) {
                        this.poiChartResizeHandler = () => this.resizePoiChart();
                        window.addEventListener('resize', this.poiChartResizeHandler);
                    }
                }
                this.poiChart = chart;
                return chart;
            },
            resizePoiChart() {
                if (this.poiChart) this.poiChart.resize();
            },
            disposePoiChart() {
                if (this.poiChart) {
                    this.poiChart.dispose();
                    this.poiChart = null;
                }
                if (this.poiChartResizeHandler) {
                    window.removeEventListener('resize', this.poiChartResizeHandler);
                    this.poiChartResizeHandler = null;
                }
            },
            isPoiRasterGridMode() {
                return this.normalizePoiGridType(this.poiGridType) === 'shared';
            },
            isPoiSharedGridMode() {
                return this.normalizePoiGridType(this.poiGridType) === 'shared';
            },
            getPoiGridTypeLabel() {
                return this.isPoiRasterGridMode() ? '共享栅格' : 'H3 六边形网格';
            },
            getPoiGridRuntimeStatus() {
                return this.isPoiRasterGridMode()
                    ? String(this.poiGridStatus || '')
                    : String(this.h3GridStatus || '');
            },
            getPoiGridRuntimeProgress() {
                const source = this.isPoiRasterGridMode() ? this.poiGridProgress : this.h3AnalysisProgress;
                return (source && typeof source === 'object') ? source : null;
            },
            normalizePoiGridType(type) {
                const normalized = String(type || '').trim().toLowerCase();
                if (normalized === 'h3' || normalized === 'hex') return 'h3';
                return 'shared';
            },
            poiGridTypeToUiValue(type) {
                return this.normalizePoiGridType(type) === 'h3' ? 'hex' : 'shared';
            },
            hasPoiSharedGridAnalysis() {
                return this.isPoiSharedGridMode()
                    && Array.isArray(this.h3AnalysisGridFeatures)
                    && this.h3AnalysisGridFeatures.length > 0
                    && (!!this.h3AnalysisSummary || !!this.h3AnalysisCharts);
            },
            shouldUsePoiUnifiedGridUi() {
                const type = this.normalizePoiGridType(this.poiGridType);
                return type === 'h3' || this.hasPoiSharedGridAnalysis();
            },
            getActivePoiGridYear() {
                const year = Number(this.poiYearSource || this.resultPoiYear || this.currentHistorySelectedPoiYear || 0);
                return Number.isFinite(year) && year > 0 ? year : null;
            },
            makePoiGridResultKey(year, gridType) {
                const safeYear = Number(year);
                const type = this.normalizePoiGridType(gridType);
                return `${Number.isFinite(safeYear) && safeYear > 0 ? safeYear : 'current'}:${type}`;
            },
            getPoiGridResult(year, gridType) {
                const key = this.makePoiGridResultKey(year, gridType);
                const source = this.poiGridResultsByYearType && typeof this.poiGridResultsByYearType === 'object'
                    ? this.poiGridResultsByYearType[key]
                    : null;
                return source && typeof source === 'object' ? clonePoiGridValue(source) : null;
            },
            commitPoiGridResult(year, gridType, patch = {}) {
                const type = this.normalizePoiGridType(gridType);
                const safeYear = Number(year);
                const normalizedYear = Number.isFinite(safeYear) && safeYear > 0 ? safeYear : this.getActivePoiGridYear();
                const key = this.makePoiGridResultKey(normalizedYear, type);
                const current = this.poiGridResultsByYearType && typeof this.poiGridResultsByYearType === 'object'
                    ? this.poiGridResultsByYearType
                    : {};
                const existing = current[key] && typeof current[key] === 'object' ? current[key] : {};
                const next = Object.assign({}, clonePoiGridValue(existing), clonePoiGridValue(patch), {
                    key,
                    year: normalizedYear,
                    gridType: type,
                    updatedAt: new Date().toISOString(),
                });
                this.poiGridResultsByYearType = Object.assign({}, current, { [key]: next });
                if (this.makePoiGridResultKey(this.getActivePoiGridYear(), this.normalizePoiGridType(this.poiGridType)) === key) {
                    this.activePoiGridResultKey = key;
                }
                return clonePoiGridValue(next);
            },
            buildCurrentPoiGridResult(gridType = null, year = null) {
                const type = this.normalizePoiGridType(gridType || this.poiGridType);
                const safeYear = Number(year || this.getActivePoiGridYear());
                if (type === 'h3') {
                    return {
                        status: (Array.isArray(this.h3AnalysisGridFeatures) && this.h3AnalysisGridFeatures.length) || this.h3AnalysisSummary ? 'ready' : 'empty',
                        features: clonePoiGridValue(this.h3AnalysisGridFeatures || []),
                        summary: clonePoiGridValue(this.h3AnalysisSummary || {}),
                        charts: clonePoiGridValue(this.h3AnalysisCharts || {}),
                        progress: clonePoiGridValue(this.h3AnalysisProgress || {}),
                        derivedStats: clonePoiGridValue(this.h3DerivedStats || createEmptyH3DerivedStats()),
                        params: {
                            h3_resolution: Number(this.h3GridResolution || 0) || null,
                            include_mode: String(this.h3GridIncludeMode || ''),
                            min_overlap_ratio: Number(this.h3GridMinOverlapRatio || 0),
                            neighbor_ring: Number(this.h3NeighborRing || 0) || null,
                        },
                        evidence: typeof this.buildAgentPoiH3Evidence === 'function' ? this.buildAgentPoiH3Evidence() : {},
                        error: '',
                        year: Number.isFinite(safeYear) && safeYear > 0 ? safeYear : null,
                        gridType: type,
                    };
                }
                return {
                    status: (Array.isArray(this.poiGridFeatures) && this.poiGridFeatures.length) || this.poiGridSummary ? 'ready' : 'empty',
                    features: clonePoiGridValue(this.poiGridFeatures || []),
                    summary: clonePoiGridValue(this.poiGridSummary || {}),
                    charts: clonePoiGridValue(this.h3AnalysisCharts || {}),
                    derivedStats: clonePoiGridValue(this.h3DerivedStats || createEmptyH3DerivedStats()),
                    params: {
                        poi_year: Number.isFinite(safeYear) && safeYear > 0 ? safeYear : null,
                        shared_grid: {
                            grid_type: 'shared_raster',
                            neighbor_ring: Number(this.h3NeighborRing || 0) || 1,
                        },
                    },
                    evidence: typeof this.buildAgentPoiRasterGridEvidence === 'function' ? this.buildAgentPoiRasterGridEvidence() : {},
                    error: '',
                    progress: clonePoiGridValue(this.poiGridProgress || {}),
                    year: Number.isFinite(safeYear) && safeYear > 0 ? safeYear : null,
                    gridType: type,
                };
            },
            commitCurrentPoiGridResult(gridType = null, year = null) {
                const type = this.normalizePoiGridType(gridType || this.poiGridType);
                const safeYear = Number(year || this.getActivePoiGridYear());
                return this.commitPoiGridResult(safeYear, type, this.buildCurrentPoiGridResult(type, safeYear));
            },
            applyPoiGridResultToProjection(result = {}) {
                const type = this.normalizePoiGridType(result.gridType || result.grid_type || this.poiGridType);
                this.poiGridType = this.poiGridTypeToUiValue(type);
                this.activePoiGridResultKey = String(result.key || this.makePoiGridResultKey(result.year, type));
                if (Number.isFinite(Number(result.year))) {
                    this.poiYearSource = String(Number(result.year));
                    this.resultPoiYear = Number(result.year);
                    this.currentHistorySelectedPoiYear = Number(result.year);
                }
                if (type === 'h3') {
                    this.h3AnalysisGridFeatures = clonePoiGridValue(result.features || []);
                    this.h3GridFeatures = this.h3AnalysisGridFeatures;
                    this.h3GridCount = Number((result.summary && result.summary.grid_count) || this.h3AnalysisGridFeatures.length || 0);
                    this.h3AnalysisSummary = clonePoiGridValue(result.summary || {});
                    this.h3AnalysisCharts = clonePoiGridValue(result.charts || {});
                    this.h3DerivedStats = clonePoiGridValue(result.derivedStats || createEmptyH3DerivedStats());
                    this.selectedH3Id = null;
                    if (this.poiSubTab === 'grid') {
                        if (typeof this.restoreH3GridDisplayOnEnter === 'function') this.restoreH3GridDisplayOnEnter();
                        if (typeof this.updateH3Charts === 'function') this.$nextTick(() => this.updateH3Charts());
                        if (typeof this.updateDecisionCards === 'function') this.$nextTick(() => this.updateDecisionCards());
                    }
                    return;
                }
                this.poiGridFeatures = clonePoiGridValue(result.features || []);
                this.poiGridSummary = clonePoiGridValue(result.summary || {});
                this.h3AnalysisGridFeatures = clonePoiGridValue(result.features || []);
                this.h3GridFeatures = this.h3AnalysisGridFeatures;
                this.h3GridCount = Number((result.summary && result.summary.grid_count) || this.h3AnalysisGridFeatures.length || 0);
                this.h3AnalysisSummary = clonePoiGridValue(result.summary || {});
                this.h3AnalysisCharts = clonePoiGridValue(result.charts || {});
                this.h3DerivedStats = clonePoiGridValue(result.derivedStats || createEmptyH3DerivedStats());
                this.poiGridProgress = clonePoiGridValue(result.progress || {});
                this.selectedPoiGridCellId = null;
                this.selectedH3Id = null;
                if (this.poiSubTab === 'grid') {
                    if (typeof this.ensureH3PanelEntryState === 'function') this.ensureH3PanelEntryState();
                    if (typeof this.restoreH3GridDisplayOnEnter === 'function') this.restoreH3GridDisplayOnEnter();
                    if (typeof this.updateH3Charts === 'function') this.$nextTick(() => this.updateH3Charts());
                    if (typeof this.updateDecisionCards === 'function') this.$nextTick(() => this.updateDecisionCards());
                }
            },
            async activatePoiGridResult(year, gridType) {
                const type = this.normalizePoiGridType(gridType);
                const result = this.getPoiGridResult(year, type);
                this.poiGridType = this.poiGridTypeToUiValue(type);
                if (result && String(result.status || '') === 'ready') {
                    this.applyPoiGridResultToProjection(result);
                    return result;
                }
                if (Number.isFinite(Number(year)) && typeof this.selectAgentPoiYearForGrid === 'function') {
                    await this.selectAgentPoiYearForGrid(Number(year));
                }
                return null;
            },
            async ensurePoiGridResult({ year = null, gridType = null, force = false } = {}) {
                const type = this.normalizePoiGridType(gridType || this.poiGridType);
                const targetYear = Number(year || this.getActivePoiGridYear());
                const existing = this.getPoiGridResult(targetYear, type);
                this.poiGridType = this.poiGridTypeToUiValue(type);
                if (!force && existing && String(existing.status || '') === 'ready') {
                    this.applyPoiGridResultToProjection(existing);
                    return existing;
                }
                    this.commitPoiGridResult(targetYear, type, { status: 'running', error: '' });
                try {
                    if (Number.isFinite(targetYear) && targetYear > 0 && typeof this.selectAgentPoiYearForGrid === 'function') {
                        await this.selectAgentPoiYearForGrid(targetYear);
                    }
                    let data = null;
                    if (type === 'h3') {
                        if (typeof this.syncH3PoiFilterSelection === 'function') this.syncH3PoiFilterSelection(false);
                        if (typeof this.computeH3Analysis !== 'function') throw new Error('POI H3 六边形网格计算入口不可用');
                        const h3Run = await this.computeH3Analysis();
                        data = this.buildCurrentPoiGridResult('h3', targetYear);
                        if (h3Run && h3Run.progress) data.progress = clonePoiGridValue(h3Run.progress);
                        if (!data.features.length && !Object.keys(data.summary || {}).length) {
                            throw new Error(this.h3GridStatus || 'POI H3 六边形网格计算未返回结果');
                        }
                    } else {
                        data = await this.ensurePoiSharedGridAnalysis(true);
                        if (!data) throw new Error(this.poiGridStatus || 'POI 共享网格分析失败');
                        data = this.buildCurrentPoiGridResult('shared', targetYear);
                    }
                    data.status = 'ready';
                    data.error = '';
                    const committed = this.commitPoiGridResult(targetYear, type, data);
                    this.applyPoiGridResultToProjection(committed);
                    return committed;
                } catch (err) {
                    const message = err && err.message ? err.message : String(err);
                    this.commitPoiGridResult(targetYear, type, { status: 'failed', error: message });
                    if (type === 'h3') this.h3GridStatus = `POI H3 六边形网格生成失败: ${message}`;
                    else this.poiGridStatus = `POI 共享栅格分析失败: ${message}`;
                    throw err;
                }
            },
            async ensureActivePoiGridResult(force = false) {
                return this.ensurePoiGridResult({
                    year: this.getActivePoiGridYear(),
                    gridType: this.normalizePoiGridType(this.poiGridType),
                    force,
                });
            },
            getPoiGridMatrixYears() {
                const historyYears = Array.isArray(this.currentHistoryAvailablePoiYears)
                    ? this.currentHistoryAvailablePoiYears
                    : [];
                const selectedYears = Array.isArray(this.poiYearSelections) ? this.poiYearSelections : [];
                const years = Array.from(new Set(historyYears.concat(selectedYears)
                    .map((item) => Number(item))
                    .filter((item) => Number.isFinite(item) && item > 0)))
                    .sort((a, b) => a - b);
                if (years.length) return years;
                const active = this.getActivePoiGridYear();
                return active ? [active] : [2020, 2022, 2024];
            },
            getPoiGridResultStatus(year, gridType) {
                const result = this.getPoiGridResult(year, gridType);
                return result ? String(result.status || 'ready') : 'pending';
            },
            getPoiGridMatrixRows() {
                const labels = { shared: '共享栅格', h3: 'H3' };
                return this.getPoiGridMatrixYears().flatMap((year) => ['shared', 'h3'].map((type) => {
                    const result = this.getPoiGridResult(year, type);
                    const status = result ? String(result.status || 'ready') : 'pending';
                    const count = type === 'h3'
                        ? Number((result && result.summary && result.summary.grid_count) || (result && result.features && result.features.length) || 0)
                        : Number((result && result.summary && result.summary.grid_count) || (result && result.features && result.features.length) || 0);
                    return {
                        key: this.makePoiGridResultKey(year, type),
                        year,
                        gridType: type,
                        label: labels[type],
                        status,
                        count,
                        error: result && result.error ? String(result.error) : '',
                        active: this.activePoiGridResultKey === this.makePoiGridResultKey(year, type),
                    };
                }));
            },
            getPoiGridMatrixYearGroups() {
                const rowsByYear = this.getPoiGridMatrixRows().reduce((groups, row) => {
                    const yearKey = String(row.year || 'current');
                    if (!groups.has(yearKey)) {
                        groups.set(yearKey, {
                            year: row.year || '当前',
                            readyCount: 0,
                            totalCount: 0,
                            rows: [],
                        });
                    }
                    const group = groups.get(yearKey);
                    group.totalCount += 1;
                    if (String(row.status || '').toLowerCase() === 'ready') group.readyCount += 1;
                    group.rows.push(row);
                    return groups;
                }, new Map());
                return Array.from(rowsByYear.values());
            },
            getPoiGridResultStatusLabel(status) {
                const normalized = String(status || '').toLowerCase();
                if (normalized === 'ready') return '已就绪';
                if (normalized === 'running') return '生成中';
                if (normalized === 'failed') return '失败';
                return '待生成';
            },
            async onPoiGridMatrixSelect(row = {}) {
                const type = this.normalizePoiGridType(row.gridType || this.poiGridType);
                const targetYear = Number(row.year || this.getActivePoiGridYear());
                this.poiGridType = this.poiGridTypeToUiValue(type);
                this.activePoiGridResultKey = this.makePoiGridResultKey(targetYear, type);
                const result = this.getPoiGridResult(targetYear, type);
                if (result && String(result.status || '') === 'ready') {
                    this.applyPoiGridResultToProjection(result);
                    return result;
                }
                if (Number.isFinite(targetYear) && targetYear > 0 && typeof this.selectAgentPoiYearForGrid === 'function') {
                    await this.selectAgentPoiYearForGrid(targetYear);
                }
                if (type === 'h3') {
                    if (typeof this.clearPoiRasterGridDisplayOnLeave === 'function') this.clearPoiRasterGridDisplayOnLeave();
                    if (typeof this.clearH3Grid === 'function') this.clearH3Grid();
                    return null;
                }
                this.poiGridFeatures = [];
                this.poiGridSummary = null;
                this.h3AnalysisGridFeatures = [];
                this.h3AnalysisSummary = null;
                this.h3AnalysisCharts = null;
                this.h3DerivedStats = createEmptyH3DerivedStats();
                this.selectedPoiGridCellId = null;
                if (typeof this.clearH3GridDisplayOnLeave === 'function') this.clearH3GridDisplayOnLeave();
                if (typeof this.clearPoiRasterGridDisplayOnLeave === 'function') this.clearPoiRasterGridDisplayOnLeave();
                return null;
            },
            async generatePoiGridMatrixCell(row = {}, force = true) {
                await this.ensurePoiGridResult({ year: row.year, gridType: row.gridType, force });
            },
            async ensureAllPoiGridMatrixResults(force = false) {
                const years = this.getPoiGridMatrixYears();
                for (const year of years) {
                    await this.ensurePoiGridResult({ year, gridType: 'shared', force });
                    await this.ensurePoiGridResult({ year, gridType: 'h3', force });
                }
            },
            togglePoiGridConfig() {
                this.poiGridConfigExpanded = !this.poiGridConfigExpanded;
            },
            async setPoiGridType(type) {
                const normalized = this.poiGridTypeToUiValue(type);
                if (this.poiGridType === normalized) return;
                this.poiGridType = normalized;
                if (this.poiSubTab !== 'grid') return;
                if (normalized === 'hex') {
                    const cached = this.getPoiGridResult(this.getActivePoiGridYear(), 'h3');
                    if (cached && String(cached.status || '') === 'ready') {
                        this.applyPoiGridResultToProjection(cached);
                        return;
                    }
                    if (typeof this.syncH3PoiFilterSelection === 'function') {
                        this.syncH3PoiFilterSelection(false);
                    }
                    if (typeof this.ensureH3PanelEntryState === 'function') {
                        this.ensureH3PanelEntryState();
                    }
                    if (typeof this.restoreH3GridDisplayOnEnter === 'function') {
                        this.restoreH3GridDisplayOnEnter();
                    }
                    if (typeof this.updateH3Charts === 'function') {
                        this.updateH3Charts();
                    }
                    if (typeof this.updateDecisionCards === 'function') {
                        this.updateDecisionCards();
                    }
                    return;
                }
                const cached = this.getPoiGridResult(this.getActivePoiGridYear(), 'shared');
                if (cached && String(cached.status || '') === 'ready') {
                    this.applyPoiGridResultToProjection(cached);
                    return;
                }
                this.h3MainStage = 'params';
                if (typeof this.clearH3GridDisplayOnLeave === 'function') {
                    this.clearH3GridDisplayOnLeave();
                }
                this.restorePoiRasterGridDisplayOnEnter();
            },
            async startPoiGridAnalysis() {
                return this.ensureActivePoiGridResult(true);
            },
            setPoiSubTab(tab) {
                const normalized = String(tab || '').trim().toLowerCase();
                let nextTab = 'category';
                if (normalized === 'analysis') nextTab = 'analysis';
                if (normalized === 'load') nextTab = 'load';
                if (normalized === 'grid') nextTab = 'grid';
                if (this.poiSubTab === nextTab && this.poiKdeEnabled === (nextTab === 'analysis')) {
                    return;
                }
                const prevTab = String(this.poiSubTab || '').trim().toLowerCase();
                this.poiSubTab = nextTab;
                if (nextTab === 'analysis' && !['kde', 'stats'].includes(String(this.poiAnalysisSubTab || ''))) {
                    this.poiAnalysisSubTab = 'kde';
                }
                this.poiKdeEnabled = nextTab === 'analysis';
                if (typeof this.autoEnableDisplayTargetsForPanel === 'function') {
                    this.autoEnableDisplayTargetsForPanel('poi', { openPoiGrid: nextTab === 'grid' });
                }
                this.applySimplifyPointVisibility();
                this.$nextTick(() => {
                    if (nextTab === 'category') {
                        if (
                            prevTab === 'grid'
                            && typeof this.clearH3GridDisplayOnLeave === 'function'
                            && !(typeof this.hasSimplifyDisplayTarget === 'function' && this.hasSimplifyDisplayTarget('h3'))
                        ) {
                            this.clearH3GridDisplayOnLeave();
                        }
                        this.updatePoiCharts();
                        setTimeout(() => this.resizePoiChart(), 0);
                    } else if (nextTab === 'analysis') {
                        if (
                            prevTab === 'grid'
                            && typeof this.clearH3GridDisplayOnLeave === 'function'
                            && !(typeof this.hasSimplifyDisplayTarget === 'function' && this.hasSimplifyDisplayTarget('h3'))
                        ) {
                            this.clearH3GridDisplayOnLeave();
                        }
                        this.recomputePoiKdeStats();
                    } else if (nextTab === 'grid') {
                        if (this.isPoiRasterGridMode()) {
                            this.restorePoiRasterGridDisplayOnEnter();
                        } else {
                            if (typeof this.syncH3PoiFilterSelection === 'function') {
                                this.syncH3PoiFilterSelection(false);
                            }
                            if (typeof this.ensureH3PanelEntryState === 'function') {
                                this.ensureH3PanelEntryState();
                            }
                            if (typeof this.restoreH3GridDisplayOnEnter === 'function') {
                                this.restoreH3GridDisplayOnEnter();
                            }
                            if (typeof this.updateH3Charts === 'function') {
                                this.updateH3Charts();
                            }
                            if (typeof this.updateDecisionCards === 'function') {
                                this.updateDecisionCards();
                            }
                        }
                    } else if (
                        prevTab === 'grid'
                        && typeof this.clearH3GridDisplayOnLeave === 'function'
                        && !(typeof this.hasSimplifyDisplayTarget === 'function' && this.hasSimplifyDisplayTarget('h3'))
                    ) {
                        this.clearH3GridDisplayOnLeave();
                    }
                    this.refreshPoiKdeOverlay();
                });
            },
            setPoiAnalysisSubTab(tab) {
                const nextTab = String(tab || '').trim().toLowerCase() === 'stats' ? 'stats' : 'kde';
                if (this.poiAnalysisSubTab === nextTab) {
                    return;
                }
                this.poiAnalysisSubTab = nextTab;
                if (this.poiSubTab === 'analysis') {
                    this.$nextTick(() => {
                        this.recomputePoiKdeStats();
                        if (nextTab === 'kde') {
                            this.refreshPoiKdeOverlay();
                        }
                    });
                }
            },
            shouldShowPoiPanelStatus() {
                if (this.shouldShowHistoryRestoreProgress && this.shouldShowHistoryRestoreProgress()) return true;
                const text = String(this.poiStatus || '').trim();
                if (!text) return false;
                if (text.indexOf('已加载历史:') === 0) return false;
                return true;
            },
            getPoiPanelStatusText() {
                const text = String(this.poiStatus || '').trim();
                if (!text) return '';
                if (text.indexOf('已加载历史:') === 0) return '';
                return text;
            },
            getPoiFetchErrorRows(limit = 8) {
                const rows = Array.isArray(this.poiFetchErrors) ? this.poiFetchErrors : [];
                const max = Math.max(1, Number(limit) || 8);
                return rows.slice(0, max).map((item, index) => ({
                    key: [
                        item && item.year,
                        item && item.source,
                        item && item.category,
                        index,
                    ].join('-'),
                    year: item && item.year ? String(item.year) : '-',
                    source: this.formatPoiFetchErrorSource(item && item.source),
                    category: item && item.category ? String(item.category) : '未命名分类',
                    error: this.formatPoiFetchErrorMessage(item),
                }));
            },
            getPoiFetchErrorHiddenCount(limit = 8) {
                const rows = Array.isArray(this.poiFetchErrors) ? this.poiFetchErrors : [];
                const max = Math.max(1, Number(limit) || 8);
                return Math.max(0, rows.length - max);
            },
            formatPoiFetchErrorSource(source) {
                const value = String(source || '').trim().toLowerCase();
                if (value === 'gaode') return '高德';
                if (value === 'local') return '本地';
                return source ? String(source) : '-';
            },
            formatPoiFetchErrorMessage(item) {
                const code = item && item.error ? String(item.error) : '未知错误';
                const reason = this.formatPoiFetchErrorReason(item && item.reason_type);
                const detail = this.formatPoiFetchErrorDetail(item && item.detail);
                return [code, reason, detail].filter(Boolean).join(' · ');
            },
            formatPoiFetchErrorReason(reasonType) {
                const value = String(reasonType || '').trim();
                if (value === 'qps_limit') return '高德 QPS 限流';
                if (value === 'quota_limit') return '高德配额/Key 耗尽';
                if (value === 'request_budget') return '请求预算触顶';
                if (value === 'network_or_http') return '网络或 HTTP 异常';
                if (value === 'result_cap') return '结果量仍接近上限';
                if (value === 'unknown') return '原因待确认';
                return '';
            },
            formatPoiFetchErrorDetail(detail) {
                if (!detail || typeof detail !== 'object') return '';
                const count = Number(detail.count || 0);
                const samples = Array.isArray(detail.samples) ? detail.samples : [];
                const reason = samples.map((item) => item && item.reason ? String(item.reason) : '').find(Boolean);
                if (reason) return reason.slice(0, 80);
                if (count > 0) return `${count} 个异常瓦片`;
                if (detail.api_call_count) return `API 调用 ${detail.api_call_count}`;
                if (detail.request_count) return `请求数 ${detail.request_count}`;
                return '';
            },
            isHistoryPoiRestoring() {
                const progress = this.historyRestoreProgress && typeof this.historyRestoreProgress === 'object'
                    ? this.historyRestoreProgress
                    : null;
                if (progress) return !!progress.active;
                const text = String(this.poiStatus || '');
                return !!this.historyDetailAbortController && text.indexOf('正在加载历史 POI') >= 0;
            },
            shouldShowHistoryRestoreProgress() {
                const progress = this.historyRestoreProgress && typeof this.historyRestoreProgress === 'object'
                    ? this.historyRestoreProgress
                    : null;
                if (!progress) return false;
                if (progress.active) return true;
                if (Array.isArray(progress.warnings) && progress.warnings.length) return true;
                const message = String(progress.message || '').trim();
                return !!message && message.indexOf('历史恢复') >= 0;
            },
            getHistoryRestoreProgressPercent() {
                const value = Number(this.historyRestoreProgress && this.historyRestoreProgress.percent);
                return Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));
            },
            getHistoryRestoreProgressMessage() {
                const progress = this.historyRestoreProgress && typeof this.historyRestoreProgress === 'object'
                    ? this.historyRestoreProgress
                    : {};
                return String(progress.message || this.getPoiPanelStatusText() || '').trim();
            },
            getHistoryRestoreProgressItems() {
                const progress = this.historyRestoreProgress && typeof this.historyRestoreProgress === 'object'
                    ? this.historyRestoreProgress
                    : {};
                return Array.isArray(progress.items) ? progress.items : [];
            },
            getHistoryRestoreProgressWarnings() {
                const progress = this.historyRestoreProgress && typeof this.historyRestoreProgress === 'object'
                    ? this.historyRestoreProgress
                    : {};
                return Array.isArray(progress.warnings) ? progress.warnings.slice(0, 3) : [];
            },
            clearPoiKdeOverlay() {
                if (!this.mapCore || typeof this.mapCore.clearPoiHeatmap !== 'function') return;
                this.mapCore.clearPoiHeatmap();
            },
            getPoiRasterGridSourcePois() {
                if (Array.isArray(this.allPoisDetails) && this.allPoisDetails.length) {
                    return this.allPoisDetails;
                }
                return (this.markerManager && typeof this.markerManager.getVisiblePoints === 'function')
                    ? this.markerManager.getVisiblePoints()
                    : [];
            },
            getPoiGridCategoryPayload() {
                return (this.poiCategories || []).map((cat) => ({
                    id: String((cat && cat.id) || ''),
                    name: String((cat && cat.name) || (cat && cat.title) || (cat && cat.id) || ''),
                    types: String((cat && cat.types) || ''),
                })).filter((cat) => cat.id);
            },
            getPoiRasterGridYear() {
                const year = Number(this.poiYearSource);
                return Number.isFinite(year) ? year : null;
            },
            clearPoiRasterGridDisplayOnLeave() {
                if (!this.mapCore || typeof this.mapCore.clearGridPolygons !== 'function') return;
                this.mapCore.clearGridPolygons();
            },
            buildPoiRasterGridStyledFeatures() {
                const features = Array.isArray(this.poiGridFeatures) ? this.poiGridFeatures : [];
                const maxCount = Math.max(1, Number((this.poiGridSummary && this.poiGridSummary.max_poi_count) || 0));
                return features.map((feature) => {
                    const props = Object.assign({}, (feature && feature.properties) || {});
                    const cellId = String(props.cell_id || props.h3_id || '');
                    const count = Number(props.poi_count || 0);
                    const ratio = maxCount > 0 ? Math.max(0, Math.min(1, count / maxCount)) : 0;
                    props.cell_id = cellId;
                    props.h3_id = cellId;
                    props.fillColor = this._getPoiRasterGridColor(count, ratio);
                    props.fillOpacity = count > 0 ? 0.34 : 0.10;
                    props.strokeColor = count > 0 ? '#64748b' : '#cbd5e1';
                    props.strokeWeight = count > 0 ? 1 : 0.75;
                    return {
                        type: (feature && feature.type) || 'Feature',
                        geometry: feature && feature.geometry,
                        properties: props,
                    };
                });
            },
            _getPoiRasterGridColor(count, ratio = 0) {
                const value = Number(count || 0);
                if (value <= 0) return '#f8fafc';
                const normalized = Math.max(0, Math.min(1, Number(ratio) || 0));
                if (normalized <= 0.33) return '#dbeafe';
                if (normalized <= 0.66) return '#60a5fa';
                return '#1d4ed8';
            },
            restorePoiRasterGridDisplayOnEnter() {
                if (!this.isPoiRasterGridMode()) return;
                if (!this.mapCore || typeof this.mapCore.setGridFeatures !== 'function') return;
                const styled = this.buildPoiRasterGridStyledFeatures();
                if (!styled.length) {
                    this.clearPoiRasterGridDisplayOnLeave();
                    return;
                }
                this.mapCore.setGridFeatures(styled, {
                    strokeColor: '#64748b',
                    strokeWeight: 0.85,
                    fillColor: '#dbeafe',
                    fillOpacity: 0.20,
                    clickable: true,
                    webglBatch: false,
                });
            },
            clearPoiRasterGrid() {
                this.poiGridFeatures = [];
                this.poiGridSummary = null;
                this.poiGridStatus = '';
                this.poiGridProgress = null;
                this.selectedPoiGridCellId = null;
                this.selectedH3Id = null;
                this.h3AnalysisGridFeatures = [];
                this.h3AnalysisSummary = null;
                this.h3AnalysisCharts = null;
                this.h3DerivedStats = createEmptyH3DerivedStats();
                this.clearPoiRasterGridDisplayOnLeave();
            },
            async ensurePoiRasterGrid(force = false) {
                if (!this.getIsochronePolygonRing || !this.getIsochronePolygonRing()) {
                    this.poiGridStatus = '请先生成分析范围';
                    return null;
                }
                if (this.isLoadingPoiGrid) return null;
                if (!force && Array.isArray(this.poiGridFeatures) && this.poiGridFeatures.length) {
                    return { features: this.poiGridFeatures, summary: this.poiGridSummary };
                }
                this.isLoadingPoiGrid = true;
                if (force) {
                    this.poiGridFeatures = [];
                    this.poiGridSummary = null;
                    this.poiGridProgress = null;
                    this.selectedPoiGridCellId = null;
                    this.selectedH3Id = null;
                    this.clearPoiRasterGridDisplayOnLeave();
                }
                this.poiGridStatus = '正在生成 POI 共享栅格底座...';
                try {
                    const polygon = this.getIsochronePolygonPayload();
                    const res = await fetch('/api/v1/analysis/pois/grid', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            polygon,
                            coord_type: 'gcj02',
                            pois: this.getPoiRasterGridSourcePois(),
                            poi_coord_type: 'gcj02',
                            categories: this.getPoiGridCategoryPayload(),
                            year: this.getPoiRasterGridYear(),
                        }),
                    });
                    if (!res.ok) {
                        let detail = '';
                        try {
                            detail = await res.text();
                        } catch (_) {}
                        throw new Error(detail || 'POI 共享栅格底座生成失败');
                    }
                    const data = await res.json();
                    this.poiGridFeatures = Array.isArray(data.features) ? data.features : [];
                    this.poiGridSummary = data.summary || null;
                    const count = Number((this.poiGridSummary && this.poiGridSummary.grid_count) || this.poiGridFeatures.length || 0);
                    const activeCount = Number((this.poiGridSummary && this.poiGridSummary.active_cell_count) || 0);
                    const assigned = Number((this.poiGridSummary && this.poiGridSummary.assigned_poi_count) || 0);
                    this.poiGridStatus = count > 0
                        ? `已生成 ${count} 个共享栅格，${activeCount} 个共享栅格含 POI，已匹配 ${assigned} 个 POI`
                        : '当前范围没有可用共享栅格';
                    if (this.poiSubTab === 'grid' && this.isPoiRasterGridMode()) {
                        this.restorePoiRasterGridDisplayOnEnter();
                    }
                    this.commitCurrentPoiGridResult('shared', this.getPoiRasterGridYear());
                    if (typeof this.persistAnalysisArtifactQuietly === 'function') {
                        this.persistAnalysisArtifactQuietly('poi_raster_grid');
                    }
                    return data;
                } catch (err) {
                    console.error(err);
                    this.poiGridStatus = 'POI 共享栅格底座生成失败: ' + (err && err.message ? err.message : String(err));
                    return null;
                } finally {
                    this.isLoadingPoiGrid = false;
                }
            },
            async ensurePoiSharedGridAnalysis(force = false) {
                if (!this.getIsochronePolygonRing || !this.getIsochronePolygonRing()) {
                    this.poiGridStatus = '请先生成分析范围';
                    return null;
                }
                if (this.isLoadingPoiGrid) return null;
                const hasReady = Array.isArray(this.poiGridFeatures) && this.poiGridFeatures.length && this.poiGridSummary;
                if (!force && hasReady && this.hasPoiSharedGridAnalysis()) {
                    return {
                        grid: { features: this.poiGridFeatures, count: this.poiGridFeatures.length },
                        summary: this.poiGridSummary,
                        charts: this.h3AnalysisCharts || {},
                    };
                }
                this.isLoadingPoiGrid = true;
                if (force) {
                    this.poiGridFeatures = [];
                    this.poiGridSummary = null;
                    this.poiGridProgress = null;
                    this.h3AnalysisGridFeatures = [];
                    this.h3AnalysisSummary = null;
                    this.h3AnalysisCharts = null;
                    this.h3DerivedStats = createEmptyH3DerivedStats();
                    this.selectedPoiGridCellId = null;
                    this.selectedH3Id = null;
                    this.clearPoiRasterGridDisplayOnLeave();
                    if (typeof this.clearH3GridDisplayOnLeave === 'function') this.clearH3GridDisplayOnLeave();
                }
                const stageLabelMap = {
                    queued: '排队中',
                    build_grid: '生成共享栅格中',
                    aggregate_poi: '聚合 POI 中',
                    compute_metrics: '计算指标中',
                    arcgis_prepare: '准备 ArcGIS 中',
                    arcgis_running: 'ArcGIS 热点分析中',
                    finalize: '整理结果中',
                    completed: '已完成',
                    failed: '失败',
                };
                const progressRunId = `poi-shared-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
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
                    this.poiGridStatus = `共享栅格分析进度 ${step}/${total}：${label}${detail && detail !== label ? ` · ${detail}` : ''}（${sec}s）`;
                    this.poiGridProgress = { ...latestProgress };
                };
                const pollProgress = async () => {
                    try {
                        const resp = await fetch(`/api/v1/analysis/pois/grid-metrics/progress?run_id=${encodeURIComponent(progressRunId)}`, {
                            cache: 'no-store',
                        });
                        if (!resp.ok) return;
                        const data = await resp.json();
                        applyProgress(data || {});
                    } catch (_) {
                    }
                };
                applyProgress(latestProgress);
                progressTimer = window.setInterval(() => {
                    if (!this.isLoadingPoiGrid) return;
                    pollProgress();
                }, 800);
                try {
                    const polygon = this.getIsochronePolygonPayload();
                    const neighborRing = Math.max(1, Math.min(3, Math.round(this._toNumber(this.h3NeighborRing, 1))));
                    const res = await fetch('/api/v1/analysis/pois/grid-metrics', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            polygon,
                            coord_type: 'gcj02',
                            pois: this.getPoiRasterGridSourcePois(),
                            poi_coord_type: 'gcj02',
                            categories: this.getPoiGridCategoryPayload(),
                            year: this.getPoiRasterGridYear(),
                            neighbor_ring: neighborRing,
                            arcgis_neighbor_ring: neighborRing,
                            arcgis_export_image: true,
                            arcgis_timeout_sec: 240,
                            run_id: progressRunId,
                        }),
                    });
                    if (!res.ok) {
                        let detail = '';
                        try {
                            const errJson = await res.json();
                            if (errJson && typeof errJson === 'object') detail = errJson.detail || JSON.stringify(errJson);
                        } catch (_) {
                            try { detail = await res.text(); } catch (_) {}
                        }
                        throw new Error(detail || 'POI 共享栅格分析失败');
                    }
                    await pollProgress();
                    const data = await res.json();
                    const grid = data.grid && typeof data.grid === 'object' ? data.grid : {};
                    const features = Array.isArray(grid.features) ? grid.features : [];
                    this.poiGridFeatures = features;
                    this.poiGridSummary = data.summary || null;
                    this.h3AnalysisGridFeatures = features;
                    this.h3GridFeatures = features;
                    this.h3GridCount = Number(grid.count || (data.summary && data.summary.grid_count) || features.length || 0);
                    this.h3AnalysisSummary = data.summary || null;
                    this.h3AnalysisCharts = data.charts || null;
                    if (typeof this.computeH3DerivedStats === 'function') {
                        this.computeH3DerivedStats();
                    }
                    const count = Number((this.poiGridSummary && this.poiGridSummary.grid_count) || features.length || 0);
                    const assigned = Number((this.poiGridSummary && this.poiGridSummary.poi_count) || 0);
                    const moran = this.poiGridSummary && this.poiGridSummary.global_moran_i_density;
                    await pollProgress();
                    applyProgress({ status: 'success', stage: 'completed', message: 'POI 共享栅格分析计算完成' });
                    this.poiGridStatus = count > 0
                        ? `已完成 ${count} 个共享栅格分析，已匹配 ${assigned} 个 POI${Number.isFinite(Number(moran)) ? `，Moran I=${Number(moran).toFixed(3)}` : ''}`
                        : '当前范围没有可用共享栅格';
                    if (this.poiSubTab === 'grid') {
                        if (typeof this.ensureH3PanelEntryState === 'function') this.ensureH3PanelEntryState();
                        if (typeof this.restoreH3GridDisplayOnEnter === 'function') this.restoreH3GridDisplayOnEnter();
                        if (typeof this.updateH3Charts === 'function') this.$nextTick(() => this.updateH3Charts());
                        if (typeof this.updateDecisionCards === 'function') this.$nextTick(() => this.updateDecisionCards());
                    }
                    this.commitCurrentPoiGridResult('shared', this.getPoiRasterGridYear());
                    if (typeof this.persistAnalysisArtifactQuietly === 'function') {
                        this.persistAnalysisArtifactQuietly('poi_raster_grid');
                    }
                    return data;
                } catch (err) {
                    console.error(err);
                    const message = err && err.message ? err.message : String(err);
                    applyProgress({ status: 'failed', stage: 'failed', message });
                    this.h3AnalysisGridFeatures = [];
                    this.h3AnalysisSummary = null;
                    this.h3AnalysisCharts = null;
                    this.h3DerivedStats = createEmptyH3DerivedStats();
                    if (typeof this.clearH3GridDisplayOnLeave === 'function') {
                        this.clearH3GridDisplayOnLeave();
                    }
                    this.poiGridStatus = 'POI 共享栅格完整分析失败，正在回退到底座栅格: ' + message;
                    this.poiGridProgress = null;
                    this.isLoadingPoiGrid = false;
                    const fallback = await this.ensurePoiRasterGrid(force);
                    if (fallback) {
                        this.poiGridStatus = 'POI 共享栅格完整分析暂不可用，当前展示共享栅格底座';
                        if (this.poiSubTab === 'grid' && typeof this.restorePoiRasterGridDisplayOnEnter === 'function') {
                            this.restorePoiRasterGridDisplayOnEnter();
                        }
                        return fallback;
                    }
                    this.poiGridStatus = 'POI 共享栅格分析失败: ' + message;
                    return null;
                } finally {
                    if (progressTimer) {
                        window.clearInterval(progressTimer);
                        progressTimer = null;
                    }
                    this.isLoadingPoiGrid = false;
                }
            },
            getPoiRasterGridTopCells(limit = 5) {
                const rows = (this.poiGridSummary && Array.isArray(this.poiGridSummary.top_cells))
                    ? this.poiGridSummary.top_cells
                    : [];
                return rows.slice(0, Math.max(1, Number(limit) || 5));
            },
            _getPoiRasterGridCategoryName(categoryId) {
                const id = String(categoryId || '');
                if (!id) return '未分类';
                const fromH3 = (this.h3CategoryMeta || []).find((item) => String(item.key || '') === id);
                if (fromH3 && fromH3.label) return String(fromH3.label);
                const fromPoi = (this.poiCategories || []).find((item) => String(item.id || '') === id);
                return fromPoi ? String(fromPoi.name || fromPoi.title || fromPoi.id || id) : id;
            },
            _getPoiRasterTargetCategoryLabel() {
                return this._getPoiRasterGridCategoryName(this.h3TargetCategory);
            },
            getPoiRasterTargetCategoryLabel() {
                return this._getPoiRasterTargetCategoryLabel();
            },
            _normalizePoiRasterGridRow(feature) {
                const props = Object.assign({}, (feature && feature.properties) || {});
                const categoryCounts = Object.assign({}, props.category_counts || {});
                const positiveCategories = Object.entries(categoryCounts)
                    .map(([key, value]) => ({ key, count: Number(value || 0) }))
                    .filter((item) => item.count > 0)
                    .sort((a, b) => b.count - a.count);
                const poiCount = Number(props.poi_count || 0);
                const density = Number(props.density_poi_per_km2 || 0);
                const dominantCategory = String(props.dominant_category || (positiveCategories[0] && positiveCategories[0].key) || '');
                const targetCategory = String(this.h3TargetCategory || '');
                const targetCount = targetCategory ? Number(categoryCounts[targetCategory] || 0) : 0;
                const topCategoryCount = positiveCategories.length ? positiveCategories[0].count : 0;
                const mixScore = poiCount > 0 ? Math.max(0, Math.min(1, 1 - (topCategoryCount / poiCount))) : 0;
                return {
                    cell_id: String(props.cell_id || props.h3_id || ''),
                    poi_count: poiCount,
                    density_poi_per_km2: density,
                    category_counts: categoryCounts,
                    category_count: positiveCategories.length,
                    dominant_category: dominantCategory,
                    dominant_category_name: String(props.dominant_category_name || this._getPoiRasterGridCategoryName(dominantCategory)),
                    target_category: targetCategory,
                    target_category_name: this._getPoiRasterGridCategoryName(targetCategory),
                    target_count: targetCount,
                    target_share: poiCount > 0 ? targetCount / poiCount : 0,
                    mix_score: mixScore,
                    confidence: this._getConfidenceInfo ? this._getConfidenceInfo(poiCount) : { label: poiCount >= 5 ? '中' : '低' },
                };
            },
            getPoiRasterGridRows() {
                return (Array.isArray(this.poiGridFeatures) ? this.poiGridFeatures : [])
                    .map((feature) => this._normalizePoiRasterGridRow(feature))
                    .filter((row) => row.cell_id);
            },
            getPoiRasterGridTopRows(limit = null) {
                const max = Math.max(1, Number(limit || this.h3DecisionTopN || 10) || 10);
                return this.getPoiRasterGridRows()
                    .filter((row) => row.poi_count > 0)
                    .sort((a, b) => (b.poi_count - a.poi_count) || (b.density_poi_per_km2 - a.density_poi_per_km2))
                    .slice(0, max);
            },
            getPoiRasterGridSparseRows(limit = null) {
                const max = Math.max(1, Number(limit || this.h3DecisionTopN || 10) || 10);
                return this.getPoiRasterGridRows()
                    .sort((a, b) => (a.poi_count - b.poi_count) || (a.density_poi_per_km2 - b.density_poi_per_km2))
                    .slice(0, max);
            },
            getPoiRasterGridSingleCategoryRows(limit = null) {
                const max = Math.max(1, Number(limit || this.h3DecisionTopN || 10) || 10);
                return this.getPoiRasterGridRows()
                    .filter((row) => row.poi_count >= 3 && row.category_count <= 1)
                    .sort((a, b) => b.poi_count - a.poi_count)
                    .slice(0, max);
            },
            getPoiRasterGridMixedRows(limit = null) {
                const max = Math.max(1, Number(limit || this.h3DecisionTopN || 10) || 10);
                return this.getPoiRasterGridRows()
                    .filter((row) => row.poi_count >= 3 && row.category_count >= 2)
                    .sort((a, b) => (b.mix_score - a.mix_score) || (b.poi_count - a.poi_count))
                    .slice(0, max);
            },
            getPoiRasterTargetLowSupplyRows(limit = null) {
                const max = Math.max(1, Number(limit || this.h3DecisionTopN || 10) || 10);
                const target = String(this.h3TargetCategory || '');
                if (!target) return [];
                return this.getPoiRasterGridRows()
                    .filter((row) => row.poi_count > 0)
                    .sort((a, b) => (a.target_count - b.target_count) || (b.poi_count - a.poi_count))
                    .slice(0, max);
            },
            getPoiRasterGridLowSampleRows(limit = null) {
                const max = Math.max(1, Number(limit || this.h3DecisionTopN || 10) || 10);
                return this.getPoiRasterGridRows()
                    .filter((row) => row.poi_count > 0 && row.poi_count < 3)
                    .sort((a, b) => a.poi_count - b.poi_count)
                    .slice(0, max);
            },
            getPoiRasterGridDerivedSummary() {
                const rows = this.getPoiRasterGridRows();
                const activeRows = rows.filter((row) => row.poi_count > 0);
                const densities = rows.map((row) => row.density_poi_per_km2).filter((value) => Number.isFinite(value));
                const avgDensity = Number((this.poiGridSummary && this.poiGridSummary.avg_density_poi_per_km2) || 0);
                const maxDensity = densities.length ? Math.max(...densities) : 0;
                const maxPoi = rows.length ? Math.max(...rows.map((row) => row.poi_count)) : 0;
                const mixedRows = this.getPoiRasterGridMixedRows(9999);
                const singleRows = this.getPoiRasterGridSingleCategoryRows(9999);
                const lowSupplyRows = this.getPoiRasterTargetLowSupplyRows(9999).filter((row) => row.target_count === 0);
                return {
                    grid_count: Number((this.poiGridSummary && this.poiGridSummary.grid_count) || rows.length || 0),
                    active_cell_count: Number((this.poiGridSummary && this.poiGridSummary.active_cell_count) || activeRows.length || 0),
                    assigned_poi_count: Number((this.poiGridSummary && this.poiGridSummary.assigned_poi_count) || activeRows.reduce((sum, row) => sum + row.poi_count, 0)),
                    max_poi_count: Number((this.poiGridSummary && this.poiGridSummary.max_poi_count) || maxPoi || 0),
                    avg_density_poi_per_km2: avgDensity,
                    max_density_poi_per_km2: maxDensity,
                    mixed_cell_count: mixedRows.length,
                    single_category_cell_count: singleRows.length,
                    target_low_supply_count: lowSupplyRows.length,
                    low_sample_count: this.getPoiRasterGridLowSampleRows(9999).length,
                };
            },
            getPoiRasterGridLegend() {
                const rows = this.getPoiRasterGridRows();
                if (!rows.length) return null;
                const maxCount = Math.max(1, ...rows.map((row) => row.poi_count));
                const lowMax = Math.max(1, Math.ceil(maxCount / 3));
                const midMax = Math.max(lowMax + 1, Math.ceil(maxCount * 2 / 3));
                return {
                    title: 'POI共享栅格密度',
                    unit: 'POI数/格',
                    items: [
                        { color: '#f8fafc', label: '0' },
                        { color: '#dbeafe', label: `1 ~ ${lowMax}` },
                        { color: '#60a5fa', label: `${lowMax + 1} ~ ${midMax}` },
                        { color: '#1d4ed8', label: `${midMax + 1} ~ ${maxCount}` },
                    ],
                    noDataLabel: '无POI',
                    noDataColor: '#f8fafc',
                };
            },
            focusPoiRasterGridCell(cellId) {
                const id = String(cellId || '');
                if (!id || !this.mapCore || typeof this.mapCore.focusGridCellById !== 'function') return;
                this.selectedPoiGridCellId = id;
                const found = this.mapCore.focusGridCellById(id, {
                    fitView: true,
                    zoomMin: 16,
                    animate: true,
                    preserveFill: true,
                    animateFill: false,
                    strokeColor: '#1d4ed8',
                    pulseColor: '#bfdbfe',
                });
                this.poiGridStatus = found ? `已定位共享栅格：${id}` : `未找到对应共享栅格：${id}`;
            },
            _getPoiKdeSourcePoints() {
                if (this.markerManager && typeof this.markerManager.getVisiblePointsData === 'function') {
                    return this.markerManager.getVisiblePointsData(1);
                }
                const source = Array.isArray(this.allPoisDetails) ? this.allPoisDetails : [];
                return source.map((poi) => {
                    const loc = this.normalizeLngLat(poi && poi.location, 'poi.kde.location');
                    if (!loc) return null;
                    return { lng: Number(loc[0]), lat: Number(loc[1]), count: 1 };
                }).filter((item) => !!item);
            },
            _getPoiKdeStatsSourcePois() {
                if (Array.isArray(this.allPoisDetails) && this.allPoisDetails.length) {
                    return this.allPoisDetails;
                }
                return (this.markerManager && typeof this.markerManager.getVisiblePoints === 'function')
                    ? this.markerManager.getVisiblePoints()
                    : [];
            },
            getPoiYearSourceOptions() {
                const historyYears = Array.isArray(this.currentHistoryAvailablePoiYears)
                    ? this.currentHistoryAvailablePoiYears
                        .map((item) => Number(item))
                        .filter((item) => Number.isFinite(item))
                        .sort((a, b) => a - b)
                    : [];
                const source = String(this.scopeSource || '').trim().toLowerCase();
                if (source === 'history' && historyYears.length) {
                    return historyYears.map((year) => ({
                        value: String(year),
                        label: year === 2026 ? '2026 高德' : `${year} 本地`,
                    }));
                }
                return [
                    { value: '2020', label: '2020 本地' },
                    { value: '2022', label: '2022 本地' },
                    { value: '2024', label: '2024 本地' },
                    { value: '2026', label: '2026 高德' },
                ];
            },
            getPoiMultiYearOptions() {
                return [
                    { value: 2020, label: '2020 本地' },
                    { value: 2022, label: '2022 本地' },
                    { value: 2024, label: '2024 本地' },
                    { value: 2026, label: '2026 高德' },
                ];
            },
            getSelectedPoiYears() {
                const years = Array.isArray(this.poiYearSelections)
                    ? this.poiYearSelections
                    : [];
                const normalized = Array.from(new Set(
                    years
                        .map((item) => Number(item))
                        .filter((item) => [2020, 2022, 2024, 2026].includes(item))
                )).sort((a, b) => a - b);
                return normalized.length ? normalized : [2020, 2022, 2024];
            },
            isPoiYearSelected(year) {
                return this.getSelectedPoiYears().includes(Number(year));
            },
            togglePoiYearSelection(year, checked) {
                const value = Number(year);
                if (![2020, 2022, 2024, 2026].includes(value)) return;
                const next = new Set(this.getSelectedPoiYears());
                if (checked) {
                    next.add(value);
                } else if (next.size > 1) {
                    next.delete(value);
                }
                this.poiYearSelections = Array.from(next).sort((a, b) => a - b);
            },
            getPoiYearOptionLabel(year) {
                const value = Number(year);
                const match = this.getPoiMultiYearOptions().find((item) => Number(item.value) === value);
                return match ? String(match.label || value) : (Number.isFinite(value) ? `${value} 年` : '-');
            },
            _buildPoiKdeTopCategoryRows(limit = 5) {
                const stats = this.computePoiStats(this._getPoiKdeStatsSourcePois());
                const rows = (stats.labels || []).map((label, index) => ({
                    id: String((this.poiCategories[index] && this.poiCategories[index].id) || `poi-kde-${index}`),
                    label: String(label || `分类${index + 1}`),
                    color: (stats.colors && stats.colors[index]) || '#94a3b8',
                    value: Number((stats.values && stats.values[index]) || 0),
                })).filter((item) => item.value > 0)
                    .sort((a, b) => b.value - a.value);
                const safeLimit = Number(limit);
                const limitedRows = Number.isFinite(safeLimit) && safeLimit > 0
                    ? rows.slice(0, Math.max(1, safeLimit))
                    : rows;
                const maxValue = limitedRows.reduce((max, item) => Math.max(max, Number(item.value) || 0), 0);
                return limitedRows.map((item) => Object.assign({}, item, {
                    ratio: maxValue > 0 ? Math.max(10, Math.round((Number(item.value) || 0) / maxValue * 100)) : 0,
                }));
            },
            _buildPoiKdeChartRows(rows) {
                const sourceRows = Array.isArray(rows) ? rows : [];
                const maxValue = sourceRows.reduce((max, item) => Math.max(max, Number(item.value) || 0), 0);
                return sourceRows.map((item) => {
                    const label = String(item.label || '');
                    return Object.assign({}, item, {
                        height: maxValue > 0 ? Math.max(16, Math.round((Number(item.value) || 0) / maxValue * 100)) : 0,
                        shortLabel: label.length > 4 ? `${label.slice(0, 4)}...` : label,
                    });
                });
            },
            recomputePoiKdeStats() {
                const visiblePointCount = this._getPoiKdeSourcePoints().length;
                const maxIntensity = Math.max(6, Math.ceil(visiblePointCount / 40));
                const rankedRows = this._buildPoiKdeTopCategoryRows(0);
                const topCategoryRows = rankedRows.slice(0, 5);
                const chartRows = this._buildPoiKdeChartRows(rankedRows);
                this.poiKdeStats = {
                    visiblePointCount,
                    maxIntensity,
                    topCategoryRows,
                    chartRows,
                };
                return this.poiKdeStats;
            },
            async refreshPoiKdeOverlay() {
                if (!this.mapCore || typeof this.mapCore.renderPoiHeatmap !== 'function') return;
                if (!this.poiKdeEnabled || (typeof this.shouldShowPoiKdeOnCurrentPanel === 'function' && !this.shouldShowPoiKdeOnCurrentPanel())) {
                    this.clearPoiKdeOverlay();
                    return;
                }
                const points = this._getPoiKdeSourcePoints();
                const stats = this.recomputePoiKdeStats();
                if (!points.length) {
                    this.clearPoiKdeOverlay();
                    return;
                }
                const max = Math.max(6, Number((stats && stats.maxIntensity) || 0));
                await this.mapCore.renderPoiHeatmap(points, {
                    radius: this.poiKdeRadius,
                    max: max,
                    opacity: 0.7
                });
            },
        };
    }

export { createEmptyPoiKdeStats, createAnalysisPoiInitialState, createAnalysisPoiPanelMethods };
