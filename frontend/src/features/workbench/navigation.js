    const STEP3_PANEL_IDS = Object.freeze({
        POI: 'poi',
        H3: 'h3',
        H3_SETTINGS: 'h3_settings',
        POPULATION: 'population',
        NIGHTLIGHT: 'nightlight',
        GWR: 'gwr',
        TIMESERIES: 'timeseries',
        SYNTAX: 'syntax',
        AGENT: 'agent',
    });

    function createAnalysisWorkbenchMethods() {
        return {
            normalizeStep3PanelId(panelId = '') {
                const panel = String(panelId || '');
                if (panel === STEP3_PANEL_IDS.H3_SETTINGS || panel === STEP3_PANEL_IDS.H3) {
                    return STEP3_PANEL_IDS.POI;
                }
                return panel;
            },
            shouldShowPoiOnCurrentPanel() {
                const panel = String(this.activeStep3Panel || '');
                const poiTab = String(this.poiSubTab || 'category').trim().toLowerCase();
                const panelAllowsPoi = panel === STEP3_PANEL_IDS.POI
                    && poiTab !== 'analysis'
                    && poiTab !== 'grid';
                const analysisDisplayActive = (typeof this.hasSimplifyDisplayTarget === 'function')
                    && (
                        this.hasSimplifyDisplayTarget('h3')
                        || this.hasSimplifyDisplayTarget('population')
                        || this.hasSimplifyDisplayTarget('nightlight')
                        || this.hasSimplifyDisplayTarget('gwr')
                        || this.hasSimplifyDisplayTarget('timeseries')
                        || this.hasSimplifyDisplayTarget('syntax')
                    );
                const displayAllowsPoi = (typeof this.hasSimplifyDisplayTarget === 'function')
                    ? (this.hasSimplifyDisplayTarget('poi') && !analysisDisplayActive)
                    : true;
                return this.step === 2
                    && !this.poiSystemSuspendedForSyntax
                    && (panelAllowsPoi || displayAllowsPoi);
            },
            shouldShowPoiKdeOnCurrentPanel() {
                const panel = String(this.activeStep3Panel || '');
                return panel === STEP3_PANEL_IDS.POI
                    && !this.poiSystemSuspendedForSyntax
                    && String(this.poiSubTab || '') === 'analysis'
                    && !!this.poiKdeEnabled;
            },
            autoEnableDisplayTargetsForPanel(panelId, options = {}) {
                if (typeof this.enableSimplifyDisplayTarget !== 'function') return;
                const panel = String(panelId || '').trim().toLowerCase();
                const openPoiGrid = !!(options && options.openPoiGrid);
                if (panel === STEP3_PANEL_IDS.POI && !openPoiGrid) {
                    this.enableSimplifyDisplayTarget('poi', true, { apply: false });
                } else {
                    this.enableSimplifyDisplayTarget('poi', false, { apply: false });
                }
                if (typeof this.resetAnalysisDisplayTargetsForPanel === 'function') {
                    this.resetAnalysisDisplayTargetsForPanel(panel, { ...options, apply: false });
                }
                this.applySimplifyConfig();
            },
            applyPoiFilterPanel(reason = '') {
                const panel = this.filterPanel;
                if (!panel || typeof panel.applyFilters !== 'function') {
                    return Promise.resolve({
                        ok: false,
                        skipped: true,
                        reason: 'filter_panel_unavailable:' + String(reason || ''),
                    });
                }
                try {
                    const maybePromise = panel.applyFilters();
                    if (maybePromise && typeof maybePromise.then === 'function') {
                        return maybePromise;
                    }
                    return Promise.resolve({
                        ok: true,
                        reason: 'filter_panel_sync:' + String(reason || ''),
                    });
                } catch (err) {
                    return Promise.resolve({
                        ok: false,
                        reason: 'filter_panel_exception:' + String(reason || ''),
                        error: err && err.message ? err.message : String(err),
                    });
                }
            },
            applySimplifyPointVisibility() {
                const shouldShowPoi = this.shouldShowPoiOnCurrentPanel();
                if (typeof this.applyPoiVisualState === 'function') {
                    this.applyPoiVisualState({
                        shouldShowPoi: shouldShowPoi,
                    });
                }

                if (!this.markerManager && shouldShowPoi && Array.isArray(this.allPoisDetails) && this.allPoisDetails.length > 0) {
                    this.rebuildPoiRuntimeSystem(this.allPoisDetails);
                }
            },
            resizeMapAfterSidebarLayoutChange() {
                this.$nextTick(() => {
                    const map = this.mapCore && this.mapCore.map ? this.mapCore.map : null;
                    if (map && typeof map.resize === 'function') {
                        map.resize();
                    }
                });
            },
            toggleStep3SidebarCollapsed(nextCollapsed) {
                const shouldCollapse = typeof nextCollapsed === 'boolean'
                    ? nextCollapsed
                    : !this.isStep3SidebarCollapsed;
                if (this.isStep3SidebarCollapsed === shouldCollapse) return;
                this.isStep3SidebarCollapsed = shouldCollapse;
                this.resizeMapAfterSidebarLayoutChange();
            },
            selectStep3Panel(panelId) {
                if (this.isDraggingNav) return;
                const requestedPanelId = String(panelId || '');
                const openPoiGrid = requestedPanelId === STEP3_PANEL_IDS.H3
                    || requestedPanelId === STEP3_PANEL_IDS.H3_SETTINGS;
                const nextPanelId = this.normalizeStep3PanelId(panelId);
                if (nextPanelId === STEP3_PANEL_IDS.SYNTAX && !this.roadSyntaxModulesReady) {
                    this.roadSyntaxSetStatus('路网模块未完整加载：' + (this.roadSyntaxModuleMissing || []).join(', '));
                    return;
                }
                if (!this.isStep3PanelVisible(nextPanelId)) return;

                const previousPanel = this.activeStep3Panel;
                const previousPoiSubTab = String(this.poiSubTab || '').trim().toLowerCase();
                if (previousPanel && previousPanel !== STEP3_PANEL_IDS.AGENT) {
                    this.lastNonAgentStep3Panel = previousPanel;
                }
                if (nextPanelId !== STEP3_PANEL_IDS.AGENT) {
                    this.lastNonAgentStep3Panel = nextPanelId;
                }
                this.activeStep3Panel = nextPanelId;
                if (nextPanelId === STEP3_PANEL_IDS.POI && openPoiGrid) {
                    this.poiSubTab = 'grid';
                    this.poiKdeEnabled = false;
                }
                if (
                    previousPanel === STEP3_PANEL_IDS.AGENT
                    && nextPanelId !== STEP3_PANEL_IDS.AGENT
                ) {
                    this.$nextTick(() => {
                        const map = this.mapCore && this.mapCore.map ? this.mapCore.map : null;
                        if (map && typeof map.resize === 'function') {
                            map.resize();
                        }
                    });
                }
                this.autoEnableDisplayTargetsForPanel(nextPanelId, { openPoiGrid });

                if (
                    previousPanel === STEP3_PANEL_IDS.SYNTAX
                    && nextPanelId !== STEP3_PANEL_IDS.SYNTAX
                    && !(typeof this.hasSimplifyDisplayTarget === 'function' && this.hasSimplifyDisplayTarget('syntax'))
                ) {
                    this.suspendRoadSyntaxDisplay();
                }
                if (
                    previousPanel === STEP3_PANEL_IDS.POPULATION
                    && nextPanelId !== STEP3_PANEL_IDS.POPULATION
                    && !(typeof this.hasSimplifyDisplayTarget === 'function' && this.hasSimplifyDisplayTarget('population'))
                ) {
                    this.clearPopulationRasterDisplayOnLeave();
                }
                if (
                    previousPanel === STEP3_PANEL_IDS.NIGHTLIGHT
                    && nextPanelId !== STEP3_PANEL_IDS.NIGHTLIGHT
                    && !(typeof this.hasSimplifyDisplayTarget === 'function' && this.hasSimplifyDisplayTarget('nightlight'))
                ) {
                    this.clearNightlightDisplayOnLeave();
                }
                if (
                    previousPanel === STEP3_PANEL_IDS.GWR
                    && nextPanelId !== STEP3_PANEL_IDS.GWR
                    && !(typeof this.hasSimplifyDisplayTarget === 'function' && this.hasSimplifyDisplayTarget('gwr'))
                ) {
                    this.clearGwrDisplayOnLeave();
                }
                if (
                    previousPanel === STEP3_PANEL_IDS.TIMESERIES
                    && nextPanelId !== STEP3_PANEL_IDS.TIMESERIES
                    && !(typeof this.hasSimplifyDisplayTarget === 'function' && this.hasSimplifyDisplayTarget('timeseries'))
                ) {
                    if (typeof this.clearTimeseriesDisplayOnLeave === 'function') this.clearTimeseriesDisplayOnLeave();
                }
                if (
                    previousPanel === STEP3_PANEL_IDS.POI
                    && previousPoiSubTab === 'grid'
                    && nextPanelId !== STEP3_PANEL_IDS.POI
                    && !(typeof this.hasSimplifyDisplayTarget === 'function' && this.hasSimplifyDisplayTarget('h3'))
                ) {
                    if (typeof this.isPoiRasterGridMode === 'function' && this.isPoiRasterGridMode()) {
                        if (typeof this.clearPoiRasterGridDisplayOnLeave === 'function') this.clearPoiRasterGridDisplayOnLeave();
                    } else {
                        this.clearH3GridDisplayOnLeave();
                    }
                }
                const nextPoiSubTab = openPoiGrid ? 'grid' : String(this.poiSubTab || '').trim().toLowerCase();
                const nextShowsH3Panel = nextPanelId === STEP3_PANEL_IDS.POI && nextPoiSubTab === 'grid';
                if (!nextShowsH3Panel) {
                    this.h3ExportMenuOpen = false;
                    this.h3ExportTasksOpen = false;
                }
                if (nextPanelId === STEP3_PANEL_IDS.POI) {
                    this.applySimplifyPointVisibility();
                    this.$nextTick(() => {
                        const poiTab = String(this.poiSubTab || 'category').trim().toLowerCase();
                        if (poiTab === 'analysis') {
                            this.refreshPoiKdeOverlay();
                        } else if (poiTab === 'category') {
                            this.updatePoiCharts();
                            setTimeout(() => this.resizePoiChart(), 0);
                        } else if (poiTab === 'grid') {
                            if (typeof this.isPoiRasterGridMode === 'function' && this.isPoiRasterGridMode()) {
                                if (typeof this.ensurePoiSharedGridAnalysis === 'function') this.ensurePoiSharedGridAnalysis();
                                if (typeof this.restoreH3GridDisplayOnEnter === 'function') this.restoreH3GridDisplayOnEnter();
                            } else {
                                this.syncH3PoiFilterSelection(false);
                                this.ensureH3PanelEntryState();
                                this.restoreH3GridDisplayOnEnter();
                                if (typeof this.updateH3Charts === 'function') this.updateH3Charts();
                                if (typeof this.updateDecisionCards === 'function') this.updateDecisionCards();
                            }
                        } else {
                            this.clearPoiKdeOverlay();
                        }
                    });
                    return;
                }
                if (nextPanelId === STEP3_PANEL_IDS.POPULATION) {
                    this.ensurePopulationPanelEntryState();
                    this.restorePopulationRasterDisplayOnEnter();
                    this.$nextTick(() => {
                        if (typeof this.updatePopulationCharts === 'function') this.updatePopulationCharts();
                    });
                    this.applySimplifyPointVisibility();
                    return;
                }
                if (nextPanelId === STEP3_PANEL_IDS.NIGHTLIGHT) {
                    this.ensureNightlightPanelEntryState();
                    this.restoreNightlightDisplayOnEnter();
                    this.applySimplifyPointVisibility();
                    return;
                }
                if (nextPanelId === STEP3_PANEL_IDS.GWR) {
                    if (typeof this.ensureGwrPanelEntryState === 'function') {
                        this.ensureGwrPanelEntryState();
                    }
                    if (typeof this.restoreGwrDisplayOnEnter === 'function') {
                        this.restoreGwrDisplayOnEnter();
                    }
                    this.applySimplifyPointVisibility();
                    return;
                }
                if (nextPanelId === STEP3_PANEL_IDS.TIMESERIES) {
                    if (typeof this.ensureTimeseriesPanelEntryState === 'function') this.ensureTimeseriesPanelEntryState();
                    if (typeof this.restoreTimeseriesDisplayOnEnter === 'function') this.restoreTimeseriesDisplayOnEnter();
                    this.applySimplifyPointVisibility();
                    return;
                }
                if (nextPanelId === STEP3_PANEL_IDS.AGENT) {
                    if (typeof this.ensureAgentPanelReady === 'function') {
                        this.ensureAgentPanelReady();
                    }
                    if (typeof this.applyPoiVisualState === 'function') {
                        this.applyPoiVisualState({
                            shouldShowPoi: false,
                        });
                    }
                    return;
                }
                if (nextPanelId === STEP3_PANEL_IDS.SYNTAX) {
                    const hasRoadSnapshot = !!this.roadSyntaxSummary
                        || (Array.isArray(this.roadSyntaxRoadFeatures) && this.roadSyntaxRoadFeatures.length > 0)
                        || (Array.isArray(this.roadSyntaxNodes) && this.roadSyntaxNodes.length > 0);
                    if (hasRoadSnapshot) {
                        const metricTabs = (typeof this.roadSyntaxMetricTabs === 'function')
                            ? this.roadSyntaxMetricTabs().map((tab) => tab.value)
                            : ['connectivity', 'control', 'depth', 'choice', 'integration', 'intelligibility'];
                        const currentTab = String(this.roadSyntaxMainTab || '').trim();
                        const currentMetric = String(this.roadSyntaxMetric || '').trim();
                        const lastMetric = String(this.roadSyntaxLastMetricTab || '').trim();
                        const defaultMetric = typeof this.roadSyntaxDefaultMetric === 'function'
                            ? this.roadSyntaxDefaultMetric()
                            : 'connectivity';
                        const targetTab = metricTabs.includes(currentTab)
                            ? currentTab
                            : (metricTabs.includes(currentMetric)
                                ? currentMetric
                                : (metricTabs.includes(lastMetric) ? lastMetric : defaultMetric));
                        this.setRoadSyntaxMainTab(targetTab, { refresh: false, syncMetric: true });
                    } else {
                        this.setRoadSyntaxMainTab('params', { refresh: false, syncMetric: false });
                    }
                    this.resumeRoadSyntaxDisplay();
                }
                this.applySimplifyPointVisibility();
            },
            suspendPoiSystemForSyntax() {
                if (this.poiSystemSuspendedForSyntax) return;
                this.clearPoiOverlayLayers({
                    reason: 'suspend_for_syntax',
                    clearManager: true,
                    clearSimpleMarkers: true,
                    resetFilterPanel: true,
                    immediate: true,
                });
                this.poiSystemSuspendedForSyntax = true;
            },
            resumePoiSystemAfterSyntax() {
                if (!this.poiSystemSuspendedForSyntax) return;
                this.poiSystemSuspendedForSyntax = false;
                if (!this.markerManager && Array.isArray(this.allPoisDetails) && this.allPoisDetails.length) {
                    this.rebuildPoiRuntimeSystem(this.allPoisDetails);
                }
            },
            onStep3DragStart(index, event) {
                this.dragIndex = index;
                this.dragOverIndex = index;
                this.dragInsertPosition = 'before';
                this.isDraggingNav = true;
                if (event && event.dataTransfer) {
                    event.dataTransfer.effectAllowed = 'move';
                }
            },
            onStep3DragOver(index, event) {
                if (event) event.preventDefault();
                this.dragOverIndex = index;
                const bounds = event.currentTarget.getBoundingClientRect();
                const midY = bounds.top + bounds.height / 2;
                this.dragInsertPosition = event.clientY < midY ? 'before' : 'after';
            },
            onStep3Drop(index) {
                if (this.dragIndex === null) {
                    this.dragOverIndex = null;
                    this.dragInsertPosition = null;
                    return;
                }
                const items = this.step3NavItems.slice();
                const moved = items.splice(this.dragIndex, 1)[0];
                let insertIndex = index;
                if (this.dragInsertPosition === 'after') {
                    insertIndex = index + 1;
                }
                if (this.dragIndex < insertIndex) {
                    insertIndex -= 1;
                }
                items.splice(insertIndex, 0, moved);
                this.step3NavItems = items;
                this.dragIndex = null;
                this.dragOverIndex = null;
                this.dragInsertPosition = null;
                this.isDraggingNav = false;
            },
            onStep3DragEnd() {
                this.dragIndex = null;
                this.dragOverIndex = null;
                this.dragInsertPosition = null;
                this.isDraggingNav = false;
            },
            goToStep(targetStep) {
                this.confirmNavigation(() => {
                    if (targetStep < this.step) {
                        if (typeof this.cancelHistoryDetailLoading === 'function') {
                            this.cancelHistoryDetailLoading();
                        }
                        if (this.step === 2 && targetStep <= 1) {
                            this.clearPoiOverlayLayers({
                                reason: 'go_to_step_back_to_step1',
                                clearManager: true,
                                clearSimpleMarkers: true,
                                resetFilterPanel: true,
                            });
                            this.resetRoadSyntaxState();
                            this.resetPopulationAnalysisState({ keepMeta: true, keepYear: true });
                            this.poiStatus = '';
                            this.clearH3Grid();
                        }

                        if (this.step >= 2 && targetStep <= 1) {
                            if (typeof this.clearScopePolygonsFromMap === 'function') {
                                this.clearScopePolygonsFromMap();
                            }
                            this.resetRoadSyntaxState();
                            this.resetPopulationAnalysisState({ keepMeta: true, keepYear: true });
                            this.lastIsochroneGeoJSON = null;
                            this.clearH3Grid();
                        }
                    }
                    if (Number(targetStep) !== 2) {
                        this.isStep3SidebarCollapsed = false;
                    }
                    this.step = targetStep;
                });
            },
            confirmNavigation(callback) {
                if (this.isFetchingPois) {
                    if (confirm('数据抓取正在进行中，离开将取消未完成的任务。确定要离开吗？')) {
                        this.cancelFetch();
                        callback();
                    }
                } else {
                    callback();
                }
            },
            cancelFetch() {
                if (this.abortController) {
                    this.abortController.abort();
                    this.abortController = null;
                }
                this.isFetchingPois = false;
                this.poiStatus = '任务已取消';
                this.resetFetchSubtypeProgress();
            },
            backToHome() {
                this.confirmNavigation(() => {
                    this.destroyPlaceSearch();
                    this.clearAnalysisLayers();
                    this.sidebarView = 'start';
                    this.step = 1;
                    this.isStep3SidebarCollapsed = false;
                    this.selectedPoint = null;
                    if (typeof this.clearCenterMarkerOverlay === 'function') {
                        this.clearCenterMarkerOverlay();
                    }
                    this.errorMessage = '';
                });
            },
        };
    }

export { createAnalysisWorkbenchMethods };
