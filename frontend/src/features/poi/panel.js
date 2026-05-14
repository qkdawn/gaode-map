    function createEmptyPoiKdeStats() {
        return {
            visiblePointCount: 0,
            maxIntensity: 6,
            topCategoryRows: [],
            chartRows: [],
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
            poiGridType: 'raster',
            poiGridConfigExpanded: false,
            isLoadingPoiGrid: false,
            poiGridStatus: '',
            poiGridFeatures: [],
            poiGridSummary: null,
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
                return String(this.poiGridType || 'raster').trim().toLowerCase() !== 'hex';
            },
            getPoiGridTypeLabel() {
                return this.isPoiRasterGridMode() ? '栅格' : '六边形格子';
            },
            togglePoiGridConfig() {
                this.poiGridConfigExpanded = !this.poiGridConfigExpanded;
            },
            async setPoiGridType(type) {
                const normalized = String(type || '').trim().toLowerCase() === 'hex' ? 'hex' : 'raster';
                if (this.poiGridType === normalized) return;
                this.poiGridType = normalized;
                if (this.poiSubTab !== 'grid') return;
                if (normalized === 'hex') {
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
                this.h3MainStage = 'params';
                if (typeof this.clearH3GridDisplayOnLeave === 'function') {
                    this.clearH3GridDisplayOnLeave();
                }
                this.restorePoiRasterGridDisplayOnEnter();
            },
            async startPoiGridAnalysis() {
                if (this.isPoiRasterGridMode()) {
                    return this.ensurePoiRasterGrid(true);
                }
                return this.computeH3Analysis();
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
                    error: item && item.error ? String(item.error) : '未知错误',
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
            isHistoryPoiRestoring() {
                const text = String(this.poiStatus || '');
                return !!this.historyDetailAbortController && text.indexOf('正在加载历史 POI') >= 0;
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
                    this.selectedH3Id = null;
                    this.clearPoiRasterGridDisplayOnLeave();
                }
                this.poiGridStatus = '正在生成 POI 栅格...';
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
                        throw new Error(detail || 'POI 栅格生成失败');
                    }
                    const data = await res.json();
                    this.poiGridFeatures = Array.isArray(data.features) ? data.features : [];
                    this.poiGridSummary = data.summary || null;
                    const count = Number((this.poiGridSummary && this.poiGridSummary.grid_count) || this.poiGridFeatures.length || 0);
                    const activeCount = Number((this.poiGridSummary && this.poiGridSummary.active_cell_count) || 0);
                    const assigned = Number((this.poiGridSummary && this.poiGridSummary.assigned_poi_count) || 0);
                    this.poiGridStatus = count > 0
                        ? `已生成 ${count} 个栅格，${activeCount} 个栅格含 POI，已匹配 ${assigned} 个 POI`
                        : '当前范围没有可用栅格';
                    if (this.poiSubTab === 'grid' && this.isPoiRasterGridMode()) {
                        this.restorePoiRasterGridDisplayOnEnter();
                    }
                    return data;
                } catch (err) {
                    console.error(err);
                    this.poiGridStatus = 'POI 栅格生成失败: ' + (err && err.message ? err.message : String(err));
                    return null;
                } finally {
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
                    title: 'POI栅格密度',
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
                this.selectedH3Id = id;
                const found = this.mapCore.focusGridCellById(id, {
                    fitView: true,
                    zoomMin: 16,
                    animate: true,
                    preserveFill: true,
                    animateFill: false,
                    strokeColor: '#1d4ed8',
                    pulseColor: '#bfdbfe',
                });
                this.poiGridStatus = found ? `已定位栅格：${id}` : `未找到对应栅格：${id}`;
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
